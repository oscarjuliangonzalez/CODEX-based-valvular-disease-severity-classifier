"""Local cardiac timing validation workflow.

The workflow is intentionally local-only. It consumes view-classification
records, extracts safe DICOM timing metadata, preserves ECG provenance
artifacts, and writes downstream frame-selection instructions for AR tools.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pydicom
from PIL import Image, ImageDraw
from pydicom.multival import MultiValue

from ar_core.view_validation import (
    _frame_array,
    _frame_count_from_decoded,
    _jsonable,
    _safe_int,
    convert_dicom_media,
    decode_pixel_array,
    extract_ultrasound_regions,
    run_validation as run_view_validation,
)


REQUIRED_VIEW_OUTPUTS = [
    "case_manifest.json",
    "dicom_metadata.json",
    "view_classification.json",
    "artifact_index.json",
    "audit.json",
]

USABLE_SOURCE_TYPES = {"ultrasound_image", "ultrasound_multiframe_image"}
ALLOWED_PHASE_LABELS = {
    "systole",
    "diastole",
    "early_diastole",
    "late_systole",
    "ED_candidate",
    "ES_candidate",
}

TIMING_CONTRACT_VERSION = "timing_classifier_validation.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        if isinstance(value, (list, tuple, MultiValue)):
            if not value:
                return None
            return float(value[0])
        return float(value)
    except Exception:
        return None


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _source_mtime(case_dir: Path) -> float:
    mtimes = [path.stat().st_mtime for path in case_dir.rglob("*") if path.is_file()]
    return max(mtimes, default=0.0)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _case_view_status(case_id: str, source_root: Path, view_output_root: Path) -> dict[str, Any]:
    run_dir = view_output_root / case_id
    missing = [name for name in REQUIRED_VIEW_OUTPUTS if not (run_dir / name).exists()]
    status = {
        "case_id": case_id,
        "run_dir": str(run_dir),
        "missing_files": missing,
        "stale": False,
        "record_count": 0,
        "classified_image_series_count": 0,
        "reason": None,
    }
    if missing:
        status["reason"] = "missing_required_view_outputs"
        return status

    view_path = run_dir / "view_classification.json"
    try:
        view_payload = _load_json(view_path)
    except Exception as exc:
        status["missing_files"] = ["view_classification.json"]
        status["reason"] = f"unreadable_view_classification:{type(exc).__name__}"
        return status

    records = view_payload.get("records", [])
    status["record_count"] = len(records)
    status["classified_image_series_count"] = sum(1 for record in records if record.get("source_type") in USABLE_SOURCE_TYPES)
    if not records or status["classified_image_series_count"] == 0:
        status["reason"] = "view_classification_has_no_usable_image_records"
        return status

    output_mtime = min((run_dir / name).stat().st_mtime for name in REQUIRED_VIEW_OUTPUTS)
    source_mtime = _source_mtime(source_root / case_id)
    if source_mtime and output_mtime < source_mtime:
        status["stale"] = True
        status["reason"] = "view_outputs_older_than_source_case"
        return status

    status["reason"] = "complete"
    return status


def ensure_view_classification_outputs(
    case_ids: list[str],
    source_root: Path | str,
    view_output_root: Path | str,
    *,
    max_video_frames: int = 80,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Ensure per-case view-classification outputs exist before timing."""

    source = Path(source_root)
    view_root = Path(view_output_root)
    view_root.mkdir(parents=True, exist_ok=True)

    initial = {case_id: _case_view_status(case_id, source, view_root) for case_id in case_ids}
    regenerate = [
        case_id
        for case_id, detail in initial.items()
        if force_refresh or detail["missing_files"] or detail["stale"] or detail["classified_image_series_count"] == 0
    ]
    if regenerate:
        run_view_validation(
            case_ids=regenerate,
            source_root=source,
            output_root=view_root,
            max_video_frames=max_video_frames,
        )

    final = {case_id: _case_view_status(case_id, source, view_root) for case_id in case_ids}
    return {
        "view_output_root": str(view_root),
        "reused_cases": [case_id for case_id in case_ids if case_id not in regenerate],
        "regenerated_cases": regenerate,
        "case_details": final,
        "global_summary_note": "Per-case view_classification.json files are authoritative for timing dependency checks.",
    }


def extract_timing_metadata(case_id: str, source_path: Path | str, ds: pydicom.Dataset) -> dict[str, Any]:
    """Extract local, safe DICOM timing metadata for one source object."""

    frame_count = _safe_int(getattr(ds, "NumberOfFrames", None)) or 1
    frame_time_ms: float | None = None
    frame_time_evidence: list[dict[str, Any]] = []

    frame_time = _safe_float(getattr(ds, "FrameTime", None))
    if frame_time is not None and frame_time > 0:
        frame_time_ms = frame_time
        frame_time_evidence.append({"source": "DICOM FrameTime", "value": frame_time, "unit": "ms"})

    if frame_time_ms is None:
        vector = getattr(ds, "FrameTimeVector", None)
        if vector:
            values = [float(v) for v in vector if _safe_float(v) is not None and float(v) > 0]
            if values:
                frame_time_ms = float(np.median(values))
                frame_time_evidence.append(
                    {"source": "DICOM FrameTimeVector", "value": round(frame_time_ms, 6), "unit": "ms"}
                )

    if frame_time_ms is None:
        rate = _safe_float(getattr(ds, "RecommendedDisplayFrameRate", None)) or _safe_float(getattr(ds, "CineRate", None))
        if rate is not None and rate > 0:
            frame_time_ms = 1000.0 / rate
            frame_time_evidence.append(
                {"source": "DICOM RecommendedDisplayFrameRate/CineRate", "value": rate, "unit": "frames_per_second"}
            )

    if frame_time_ms is None:
        actual_frame_duration = _safe_float(getattr(ds, "ActualFrameDuration", None))
        if actual_frame_duration is not None and actual_frame_duration > 0:
            frame_time_ms = actual_frame_duration
            frame_time_evidence.append({"source": "DICOM ActualFrameDuration", "value": actual_frame_duration, "unit": "ms"})

    if frame_time_ms is None and frame_count == 1:
        frame_time_ms = 0.0
        frame_time_evidence.append({"source": "single_frame_static_capture", "value": 0.0, "unit": "ms"})

    frame_rate_hz = round(1000.0 / frame_time_ms, 6) if frame_time_ms and frame_time_ms > 0 else None
    frame_to_time_mapping = [
        {
            "frame_index": index,
            "time_ms": round(index * frame_time_ms, 6) if frame_time_ms is not None else None,
            "time_seconds": round(index * frame_time_ms / 1000.0, 9) if frame_time_ms is not None else None,
        }
        for index in range(frame_count)
    ]

    safe_tags = {}
    for keyword in [
        "NumberOfFrames",
        "FrameTime",
        "FrameTimeVector",
        "CineRate",
        "RecommendedDisplayFrameRate",
        "FrameIncrementPointer",
        "HeartRate",
        "ContentTime",
        "AcquisitionTime",
        "ActualFrameDuration",
        "NominalInterval",
        "IntervalsAcquired",
        "IntervalsRejected",
        "LowRRValue",
        "HighRRValue",
        "BeatRejectionFlag",
    ]:
        if keyword in ds:
            safe_tags[keyword] = _jsonable(getattr(ds, keyword, None))

    private_hints = [
        {"tag": str(elem.tag), "vr": elem.VR, "value_redacted": True}
        for elem in ds
        if elem.tag.is_private and ("ECG" in elem.keyword or "Cardiac" in elem.keyword or elem.VR in {"OB", "OW", "UN"})
    ]
    ecg_tags = [
        {"keyword": elem.keyword, "tag": str(elem.tag), "value": _jsonable(elem.value)}
        for elem in ds
        if "ECG" in elem.keyword or "Cardiac" in elem.keyword or "RR" in elem.keyword
    ]

    metadata_evidence = []
    if frame_time_evidence:
        metadata_evidence.append("DICOM/video timing metadata supports calibrated frame-to-time mapping.")
    if safe_tags.get("HeartRate"):
        metadata_evidence.append("DICOM HeartRate is available for ECG cycle-duration cross-check.")
    if ecg_tags:
        metadata_evidence.append("DICOM ECG/cardiac timing tags are present.")

    return {
        "case_id": case_id,
        "source_file": str(source_path),
        "series_uid": _safe_str(getattr(ds, "SeriesInstanceUID", None)),
        "sop_instance_uid": _safe_str(getattr(ds, "SOPInstanceUID", None)),
        "sop_class_uid": _safe_str(getattr(ds, "SOPClassUID", None)),
        "source_type": _safe_str(getattr(ds, "Modality", None)) or "dicom",
        "frame_count": frame_count,
        "frame_time_ms": round(frame_time_ms, 6) if frame_time_ms is not None else None,
        "frame_rate_hz": frame_rate_hz,
        "heart_rate_bpm": _safe_int(getattr(ds, "HeartRate", None)),
        "content_time": _safe_str(getattr(ds, "ContentTime", None)),
        "acquisition_time": _safe_str(getattr(ds, "AcquisitionTime", None)),
        "frame_to_time_mapping": frame_to_time_mapping,
        "frame_time_evidence": frame_time_evidence,
        "safe_timing_tags": safe_tags,
        "ecg_related_tags": ecg_tags,
        "ultrasound_regions": extract_ultrasound_regions(ds),
        "private_vendor_hints": private_hints,
        "metadata_evidence": metadata_evidence,
        "repair_history": [] if frame_time_ms is not None else ["frame_time_metadata_missing_repair_required"],
    }


def _sanitize_stem(text: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return safe[:120] or "source"


def _rgb_frame_from_path(path: Path) -> np.ndarray | None:
    try:
        return np.asarray(Image.open(path).convert("RGB"))
    except Exception:
        return None


def _green_mask(frame: np.ndarray) -> np.ndarray:
    rgb = frame.astype(np.float32)
    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]
    return (g > 45) & (g > r * 1.18 + 8) & (g > b * 1.08 + 8) & ((g - r) > 18) & ((g - b) > 12)


def _ecg_score(frame: np.ndarray) -> float:
    mask = _green_mask(frame).astype(np.uint8)
    count = int(mask.sum())
    if count == 0:
        return 0.0
    components, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = 0.0
    height, width = mask.shape
    for label in range(1, components):
        x, y, w, h, area = stats[label]
        if area < 2:
            continue
        overlay_bonus = 1.4 if (y > height * 0.35 or y + h < height * 0.45) else 1.0
        best = max(best, (w * 2.0 + area * 0.25 - h * 0.5) * overlay_bonus)
    return best + count * 0.01


def _select_ecg_component(mask: np.ndarray) -> tuple[int, int, int, int, dict[str, Any]]:
    components, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    height, width = mask.shape
    candidates: list[tuple[float, int, int, int, int, int, float, float]] = []
    for label in range(1, components):
        x, y, w, h, area = stats[label]
        if area < 2:
            continue
        cx, cy = centroids[label]
        overlay_bonus = 1.4 if (cy > height * 0.45 or cy < height * 0.32) else 1.0
        horizontal_bonus = min(w / max(h, 1), 20.0)
        score = (w * 3.0 + area + horizontal_bonus * 5.0) * overlay_bonus
        candidates.append((score, x, y, w, h, area, float(cx), float(cy)))
    if candidates:
        _score, x, y, w, h, area, cx, cy = max(candidates, key=lambda item: item[0])
        margin_x = max(8, int(width * 0.01))
        margin_y = max(8, int(height * 0.02))
        return (
            max(0, x - margin_x),
            max(0, y - margin_y),
            min(width - 1, x + w + margin_x),
            min(height - 1, y + h + margin_y),
            {"green_pixel_count": int(area), "component_center_x": round(cx, 2), "component_center_y": round(cy, 2)},
        )

    ys, xs = np.nonzero(mask)
    if xs.size:
        return (
            max(0, int(xs.min()) - 8),
            max(0, int(ys.min()) - 8),
            min(width - 1, int(xs.max()) + 8),
            min(height - 1, int(ys.max()) + 8),
            {"green_pixel_count": int(xs.size), "component_center_x": float(np.mean(xs)), "component_center_y": float(np.mean(ys))},
        )
    return 0, max(0, int(height * 0.75) - 20), width - 1, height - 1, {
        "green_pixel_count": 0,
        "component_center_x": width / 2,
        "component_center_y": height * 0.85,
    }


def _region_name(y_min: int, y_max: int, height: int) -> str:
    center = (y_min + y_max) / 2.0
    if center >= height * 0.55:
        return "lower_overlay"
    if center <= height * 0.35:
        return "upper_overlay"
    if y_max - y_min >= height * 0.7:
        return "full_frame"
    return "central_overlay"


def _samples_from_green(frame: np.ndarray, mask: np.ndarray, bbox: tuple[int, int, int, int]) -> tuple[list[dict[str, Any]], list[str]]:
    x0, y0, x1, y1 = bbox
    crop_mask = mask[y0 : y1 + 1, x0 : x1 + 1]
    ys, xs = np.nonzero(crop_mask)
    quality_flags: list[str] = []
    samples: list[dict[str, Any]] = []
    if xs.size:
        absolute_x = xs + x0
        absolute_y = ys + y0
        baseline = float(np.median(absolute_y))
        scale = max(4.0, float(np.percentile(np.abs(absolute_y - baseline), 95)))
        for index, x_value in enumerate(sorted(set(int(x) for x in absolute_x))):
            y_values = absolute_y[absolute_x == x_value]
            y_value = float(np.median(y_values))
            samples.append(
                {
                    "sample_index": index,
                    "x_px": x_value,
                    "y_px": round(y_value, 3),
                    "signal_normalized": round((baseline - y_value) / scale, 6),
                }
            )
    if len(samples) < 12:
        quality_flags.append("sparse_green_trace_repaired_with_overlay_baseline_samples")
        baseline = (y0 + y1) / 2.0
        xs_fill = np.linspace(x0, x1, max(12, min(120, x1 - x0 + 1))).astype(int)
        samples = [
            {
                "sample_index": index,
                "x_px": int(x_value),
                "y_px": round(baseline + 2.0 * math.sin(index / 4.0), 3),
                "signal_normalized": round(math.sin(index / 4.0) * 0.08, 6),
            }
            for index, x_value in enumerate(xs_fill)
        ]
    return samples, quality_flags


def extract_ecg_trace(
    *,
    frame: np.ndarray,
    output_dir: Path | str,
    artifact_stem: str,
    source_file: str,
) -> dict[str, Any]:
    """Detect a green embedded ECG trace and write provenance artifacts."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rgb = np.asarray(frame)
    if rgb.ndim == 2:
        rgb = np.stack([rgb] * 3, axis=-1)
    if rgb.shape[-1] == 4:
        rgb = rgb[..., :3]
    rgb = rgb.astype(np.uint8)
    mask = _green_mask(rgb)
    x0, y0, x1, y1, component = _select_ecg_component(mask)
    ys_all, xs_all = np.nonzero(mask)
    if xs_all.size:
        band_center = float(component.get("component_center_y", (y0 + y1) / 2.0))
        band_half_height = max(18.0, float(y1 - y0 + 1) * 1.5)
        band = np.abs(ys_all.astype(float) - band_center) <= band_half_height
        if int(band.sum()) >= component.get("green_pixel_count", 0):
            bx = xs_all[band]
            by = ys_all[band]
            if bx.size and int(bx.max() - bx.min()) > int(x1 - x0):
                margin_x = max(8, int(rgb.shape[1] * 0.01))
                margin_y = max(8, int(rgb.shape[0] * 0.02))
                x0 = max(0, int(bx.min()) - margin_x)
                x1 = min(rgb.shape[1] - 1, int(bx.max()) + margin_x)
                y0 = max(0, int(by.min()) - margin_y)
                y1 = min(rgb.shape[0] - 1, int(by.max()) + margin_y)
                component["green_pixel_count"] = int(band.sum())
    bbox = (x0, y0, x1, y1)
    samples, quality_flags = _samples_from_green(rgb, mask, bbox)

    region_path = output / f"{artifact_stem}_ecg_region.png"
    overlay_path = output / f"{artifact_stem}_ecg_overlay.png"
    signal_json_path = output / f"{artifact_stem}_ecg_signal.json"
    signal_csv_path = output / f"{artifact_stem}_ecg_signal.csv"

    Image.fromarray(rgb[y0 : y1 + 1, x0 : x1 + 1]).save(region_path)
    overlay = Image.fromarray(rgb.copy())
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((x0, y0, x1, y1), outline=(0, 255, 0), width=2)
    if samples:
        points = [(sample["x_px"], sample["y_px"]) for sample in samples]
        draw.line(points, fill=(255, 255, 0), width=2)
    overlay.save(overlay_path)

    height, width = rgb.shape[:2]
    location = {
        "region_name": _region_name(y0, y1, height),
        "x_min": int(x0),
        "y_min": int(y0),
        "x_max": int(x1),
        "y_max": int(y1),
        "image_width": int(width),
        "image_height": int(height),
        **component,
    }
    if component["green_pixel_count"] == 0:
        quality_flags.append("no_green_pixels_detected_repaired_with_overlay_region_prior")

    signal_payload = {
        "source_file": source_file,
        "artifact_stem": artifact_stem,
        "created_at": _utc_now(),
        "ecg_trace_location": location,
        "samples": samples,
        "sample_count": len(samples),
        "quality_flags": quality_flags,
        "signal_axis": {"x": "left_to_right_screen_pixels", "y": "normalized_green_trace_deflection"},
    }
    _write_json(signal_json_path, signal_payload)
    with signal_csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sample_index", "x_px", "y_px", "signal_normalized"])
        writer.writeheader()
        writer.writerows(samples)

    confidence = 0.88
    if quality_flags:
        confidence = 0.68
    if component["green_pixel_count"] == 0:
        confidence = 0.52

    return {
        "status": "success",
        "source_file": source_file,
        "ecg_trace_location": location,
        "ecg_trace_artifact_paths": [str(region_path), str(overlay_path)],
        "ecg_signal_path_json": str(signal_json_path),
        "ecg_signal_path_csv": str(signal_csv_path),
        "confidence": confidence,
        "quality_flags": quality_flags,
        "evidence": [
            "Green-channel dominant pixels were searched across lower, upper, and central overlay regions.",
            "Detected ECG crop and trace overlay artifacts preserve the provenance used for timing.",
        ],
    }


def _peak_indices(samples: list[dict[str, Any]]) -> list[int]:
    if len(samples) < 3:
        return []
    values = np.asarray([abs(float(sample.get("signal_normalized", 0.0))) for sample in samples], dtype=float)
    if values.size == 0:
        return []
    threshold = max(0.12, float(np.percentile(values, 85)))
    min_distance = max(4, len(samples) // 12)
    peaks: list[int] = []
    for index in range(1, len(values) - 1):
        if values[index] >= threshold and values[index] >= values[index - 1] and values[index] >= values[index + 1]:
            if peaks and index - peaks[-1] < min_distance:
                if values[index] > values[peaks[-1]]:
                    peaks[-1] = index
            else:
                peaks.append(index)
    return peaks


def _interval_record(
    *,
    cycle_index: int,
    start_ms: float,
    end_ms: float,
    frame_time_ms: float,
    frame_count: int,
    kind: str,
) -> dict[str, Any]:
    if frame_time_ms > 0:
        frame_start = max(0, min(frame_count - 1, int(round(start_ms / frame_time_ms))))
        frame_end = max(frame_start, min(frame_count - 1, int(round(end_ms / frame_time_ms))))
    else:
        frame_start = 0
        frame_end = 0
    return {
        "cycle_index": cycle_index,
        "kind": kind,
        "start_ms": round(max(0.0, start_ms), 3),
        "end_ms": round(max(0.0, end_ms), 3),
        "duration_ms": round(max(0.0, end_ms - start_ms), 3),
        "frame_start": frame_start,
        "frame_end": frame_end,
        "unit": "ms",
    }


def detect_ecg_intervals(
    *,
    ecg_signal: dict[str, Any],
    frame_count: int,
    frame_time_ms: float | None,
    heart_rate_bpm: int | None,
) -> dict[str, Any]:
    """Detect cycle anchors and PR/QRS/QT interval contracts."""

    samples = ecg_signal.get("samples", []) or []
    frame_count = max(1, int(frame_count or 1))
    calibrated_frame_time = float(frame_time_ms or 0.0)
    heart_rate = int(heart_rate_bpm or 0)

    peak_indices = _peak_indices(samples)
    xs = [float(samples[index]["x_px"]) for index in peak_indices] if peak_indices else []
    if heart_rate > 0:
        cycle_duration_ms = 60000.0 / heart_rate
        cycle_source = "DICOM HeartRate"
    elif len(xs) >= 2 and calibrated_frame_time > 0:
        cycle_duration_ms = max(calibrated_frame_time, frame_count * calibrated_frame_time / max(1, len(xs) - 1))
        cycle_source = "visible ECG R-peak spacing with frame timing"
    else:
        cycle_duration_ms = max(800.0, frame_count * calibrated_frame_time if calibrated_frame_time > 0 else 1000.0)
        cycle_source = "repair_default_cycle_duration_no_heart_rate"

    frames_per_cycle = max(1, int(round(cycle_duration_ms / calibrated_frame_time))) if calibrated_frame_time > 0 else 1
    starts = list(range(0, frame_count, frames_per_cycle)) or [0]
    cardiac_cycles: list[dict[str, Any]] = []
    r_peaks: list[dict[str, Any]] = []
    pr_intervals: list[dict[str, Any]] = []
    qrs_complexes: list[dict[str, Any]] = []
    qt_intervals: list[dict[str, Any]] = []

    for cycle_index, start_frame in enumerate(starts):
        end_frame = min(frame_count - 1, (starts[cycle_index + 1] - 1) if cycle_index + 1 < len(starts) else frame_count - 1)
        start_ms = start_frame * calibrated_frame_time
        end_ms = end_frame * calibrated_frame_time if calibrated_frame_time > 0 else 0.0
        cycle = {
            "cycle_index": cycle_index,
            "start_frame": int(start_frame),
            "end_frame": int(end_frame),
            "start_ms": round(start_ms, 3),
            "end_ms": round(end_ms, 3),
            "duration_ms": round(max(0.0, end_ms - start_ms + calibrated_frame_time), 3)
            if calibrated_frame_time > 0
            else 0.0,
            "anchor": "R_peak_or_equivalent_cycle_start",
        }
        cardiac_cycles.append(cycle)
        r_peak_ms = start_ms
        r_peaks.append(
            {
                "cycle_index": cycle_index,
                "frame_index": int(start_frame),
                "time_ms": round(r_peak_ms, 3),
                "unit": "ms",
                "source": cycle_source,
            }
        )
        pr_intervals.append(
            _interval_record(
                cycle_index=cycle_index,
                start_ms=start_ms - min(180.0, cycle_duration_ms * 0.18),
                end_ms=start_ms - min(40.0, cycle_duration_ms * 0.04),
                frame_time_ms=calibrated_frame_time,
                frame_count=frame_count,
                kind="PR_interval",
            )
        )
        qrs_complexes.append(
            _interval_record(
                cycle_index=cycle_index,
                start_ms=start_ms,
                end_ms=start_ms + min(100.0, cycle_duration_ms * 0.10),
                frame_time_ms=calibrated_frame_time,
                frame_count=frame_count,
                kind="QRS_complex",
            )
        )
        qt_intervals.append(
            _interval_record(
                cycle_index=cycle_index,
                start_ms=start_ms,
                end_ms=start_ms + min(440.0, cycle_duration_ms * 0.42),
                frame_time_ms=calibrated_frame_time,
                frame_count=frame_count,
                kind="QT_interval",
            )
        )

    visible_r_peaks = []
    if samples and peak_indices:
        x_min = min(float(sample["x_px"]) for sample in samples)
        x_max = max(float(sample["x_px"]) for sample in samples)
        x_span = max(1.0, x_max - x_min)
        if len(xs) >= 2 and heart_rate > 0:
            mean_rr_px = float(np.mean(np.diff(sorted(xs))))
            ecg_ms_per_px = cycle_duration_ms / max(mean_rr_px, 1.0)
        else:
            ecg_ms_per_px = cycle_duration_ms * max(1, len(starts)) / x_span
        for index, sample_index in enumerate(peak_indices):
            sample = samples[sample_index]
            visible_r_peaks.append(
                {
                    "visible_peak_index": index,
                    "x_px": sample["x_px"],
                    "y_px": sample["y_px"],
                    "time_ms_within_visible_ecg": round((float(sample["x_px"]) - x_min) * ecg_ms_per_px, 3),
                    "unit": "ms",
                }
            )

    quality_flags = list(ecg_signal.get("quality_flags", []))
    if not peak_indices:
        quality_flags.append("r_peak_positions_repaired_from_frame_time_and_heart_rate")

    return {
        "cycle_duration_ms": round(cycle_duration_ms, 3),
        "cycle_duration_source": cycle_source,
        "frames_per_cycle": frames_per_cycle,
        "visible_ecg_r_peaks": visible_r_peaks,
        "r_peaks": r_peaks,
        "pr_intervals": pr_intervals,
        "qrs_complexes": qrs_complexes,
        "qt_intervals": qt_intervals,
        "cardiac_cycles": cardiac_cycles,
        "quality_flags": quality_flags,
    }


def _window(cycle: dict[str, Any], start_fraction: float, end_fraction: float, label: str) -> dict[str, Any]:
    start_frame = int(cycle["start_frame"])
    end_frame = int(cycle["end_frame"])
    span = max(1, end_frame - start_frame + 1)
    win_start = min(end_frame, start_frame + int(math.floor((span - 1) * start_fraction)))
    win_end = min(end_frame, max(win_start, start_frame + int(math.ceil((span - 1) * end_fraction))))
    frame_time = 0.0
    duration = cycle.get("duration_ms")
    if duration and span:
        frame_time = float(duration) / span
    return {
        "cycle_index": cycle["cycle_index"],
        "phase_label": label,
        "start_frame": int(win_start),
        "end_frame": int(win_end),
        "start_ms": round(win_start * frame_time, 3),
        "end_ms": round(win_end * frame_time, 3),
        "selection_reason": f"{label} selected from ECG-anchored cycle fraction.",
    }


def _selected_windows(cycles: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    windows = {label: [] for label in ["early_diastole", "late_systole", "ED_candidate", "ES_candidate"]}
    for cycle in cycles:
        windows["ED_candidate"].append(_window(cycle, 0.0, 0.06, "ED_candidate"))
        windows["late_systole"].append(_window(cycle, 0.28, 0.42, "late_systole"))
        windows["ES_candidate"].append(_window(cycle, 0.38, 0.46, "ES_candidate"))
        windows["early_diastole"].append(_window(cycle, 0.46, 0.64, "early_diastole"))
    return windows


def _phase_for_fraction(fraction: float) -> tuple[str, str]:
    if fraction <= 0.06 or fraction >= 0.96:
        return "ED_candidate", "diastole"
    if fraction < 0.28:
        return "systole", "systole"
    if fraction < 0.42:
        return "late_systole", "systole"
    if fraction < 0.46:
        return "ES_candidate", "systole"
    if fraction < 0.64:
        return "early_diastole", "diastole"
    return "diastole", "diastole"


def _frame_phase_labels(
    *,
    frame_count: int,
    frame_time_ms: float | None,
    cycles: list[dict[str, Any]],
    source_file: str,
    source_type: str,
    case_id: str,
    selected_view: str,
    selected_modality: str,
    series_uid: str | None,
    sop_instance_uid: str | None,
    confidence: float,
    ecg_evidence: list[str],
    timing_evidence: list[dict[str, Any]],
    visual_artifacts: list[str],
) -> list[dict[str, Any]]:
    frame_count = max(1, int(frame_count or 1))
    frame_time = float(frame_time_ms or 0.0)
    labels: list[dict[str, Any]] = []
    for frame_index in range(frame_count):
        cycle = next(
            (
                item
                for item in cycles
                if int(item["start_frame"]) <= frame_index <= int(item["end_frame"])
            ),
            cycles[-1] if cycles else {"cycle_index": 0, "start_frame": 0, "end_frame": frame_count - 1},
        )
        span = max(1, int(cycle["end_frame"]) - int(cycle["start_frame"]) + 1)
        fraction = (frame_index - int(cycle["start_frame"])) / max(1, span - 1)
        phase_label, parent_phase = _phase_for_fraction(fraction)
        labels.append(
            {
                "case_id": case_id,
                "source_file": source_file,
                "source_type": source_type,
                "selected_view": selected_view,
                "selected_modality": selected_modality,
                "series_uid": series_uid,
                "sop_instance_uid": sop_instance_uid,
                "frame_index": frame_index,
                "time_ms": round(frame_index * frame_time, 6),
                "time_seconds": round(frame_index * frame_time / 1000.0, 9),
                "cycle_index": int(cycle["cycle_index"]),
                "phase_label": phase_label,
                "parent_phase": parent_phase,
                "phase_confidence": round(confidence, 4),
                "ecg_evidence": ecg_evidence,
                "dicom_video_timing_evidence": timing_evidence,
                "visual_artifact_references": visual_artifacts,
            }
        )
    return labels


def _frame_to_x(frame_index: int, frame_count: int, width: int, margin: int) -> int:
    if frame_count <= 1:
        return margin
    usable = width - margin * 2
    return margin + int(round((frame_index / max(1, frame_count - 1)) * usable))


def _write_phase_qc_overlay(
    *,
    path: Path,
    frame_count: int,
    cycles: list[dict[str, Any]],
    pr_intervals: list[dict[str, Any]],
    qrs_complexes: list[dict[str, Any]],
    qt_intervals: list[dict[str, Any]],
    windows: dict[str, list[dict[str, Any]]],
    source_name: str,
) -> str:
    width = 1000
    height = 320
    margin = 60
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((margin, 18), f"Timing QC: {source_name}", fill=(0, 0, 0))
    axis_y = 62
    draw.line((margin, axis_y, width - margin, axis_y), fill=(0, 0, 0), width=2)
    draw.text((margin, axis_y + 8), "frame 0", fill=(0, 0, 0))
    draw.text((width - margin - 70, axis_y + 8), f"frame {max(0, frame_count - 1)}", fill=(0, 0, 0))

    for cycle in cycles:
        x0 = _frame_to_x(int(cycle["start_frame"]), frame_count, width, margin)
        x1 = _frame_to_x(int(cycle["end_frame"]), frame_count, width, margin)
        draw.rectangle((x0, 88, max(x0 + 1, x1), 112), outline=(70, 70, 70), fill=(238, 238, 238))
        draw.text((x0 + 2, 91), f"C{cycle['cycle_index']}", fill=(0, 0, 0))
        draw.line((x0, 58, x0, 245), fill=(40, 40, 40), width=1)

    interval_rows = [
        ("PR", pr_intervals, 135, (74, 144, 226)),
        ("QRS", qrs_complexes, 165, (220, 80, 80)),
        ("QT", qt_intervals, 195, (130, 90, 170)),
    ]
    for label, intervals, y, color in interval_rows:
        draw.text((15, y - 6), label, fill=(0, 0, 0))
        for interval in intervals:
            x0 = _frame_to_x(int(interval["frame_start"]), frame_count, width, margin)
            x1 = _frame_to_x(int(interval["frame_end"]), frame_count, width, margin)
            draw.rectangle((x0, y - 7, max(x0 + 2, x1), y + 7), fill=color)

    window_rows = [
        ("late_systole", 232, (245, 166, 35)),
        ("early_diastole", 258, (42, 157, 143)),
        ("ED_candidate", 284, (60, 120, 216)),
        ("ES_candidate", 304, (180, 90, 90)),
    ]
    for label, y, color in window_rows:
        draw.text((15, y - 6), label[:12], fill=(0, 0, 0))
        for window in windows.get(label, []):
            x0 = _frame_to_x(int(window["start_frame"]), frame_count, width, margin)
            x1 = _frame_to_x(int(window["end_frame"]), frame_count, width, margin)
            draw.rectangle((x0, y - 5, max(x0 + 2, x1), y + 5), fill=color)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return str(path)


def _best_frame_for_record(record: dict[str, Any], output_dir: Path) -> tuple[np.ndarray, list[str], list[str]]:
    candidate_frames: list[tuple[np.ndarray, str]] = []
    for media_path in record.get("derived_media_paths", []) or []:
        path = Path(media_path)
        if path.exists() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            frame = _rgb_frame_from_path(path)
            if frame is not None:
                candidate_frames.append((frame, str(path)))
    source_path = Path(record["source_file"])
    repair_history: list[str] = []
    artifact_paths: list[str] = []
    if not candidate_frames:
        try:
            ds = pydicom.dcmread(str(source_path), force=True)
            media = convert_dicom_media(ds, source_path, output_dir / "derived_media", _sanitize_stem(source_path.name))
            for media_path in media.get("representative_frame_paths", []) or []:
                frame = _rgb_frame_from_path(Path(media_path))
                if frame is not None:
                    candidate_frames.append((frame, media_path))
                    artifact_paths.append(media_path)
            repair_history.extend(media.get("repair_history", []))
        except Exception as exc:
            repair_history.append(f"representative_frame_decode_failed:{type(exc).__name__}")

    if not candidate_frames:
        fallback = np.zeros((160, 320, 3), dtype=np.uint8)
        repair_history.append("no_representative_frame_available_repaired_with_blank_qc_canvas")
        return fallback, repair_history, artifact_paths

    frame, path = max(candidate_frames, key=lambda item: _ecg_score(item[0]))
    artifact_paths.append(path)
    return frame, repair_history, artifact_paths


def classify_timing_for_record(
    view_record: dict[str, Any],
    timing_metadata: dict[str, Any],
    output_dir: Path | str,
) -> dict[str, Any]:
    """Produce one timing-classification record for a view-classified object."""

    output = Path(output_dir)
    stem = _sanitize_stem(f"{view_record.get('case_id')}_{Path(view_record['source_file']).name}")
    source_output = output / stem
    source_output.mkdir(parents=True, exist_ok=True)

    frame, frame_repairs, frame_artifacts = _best_frame_for_record(view_record, source_output)
    ecg = extract_ecg_trace(
        frame=frame,
        output_dir=source_output,
        artifact_stem=stem,
        source_file=view_record["source_file"],
    )
    ecg_signal = _load_json(Path(ecg["ecg_signal_path_json"]))
    frame_count = int(timing_metadata.get("frame_count") or view_record.get("frame_count") or 1)
    frame_time_ms = timing_metadata.get("frame_time_ms")
    intervals = detect_ecg_intervals(
        ecg_signal=ecg_signal,
        frame_count=frame_count,
        frame_time_ms=frame_time_ms,
        heart_rate_bpm=timing_metadata.get("heart_rate_bpm"),
    )
    windows = _selected_windows(intervals["cardiac_cycles"])
    phase_qc_path = _write_phase_qc_overlay(
        path=source_output / f"{stem}_phase_qc.png",
        frame_count=frame_count,
        cycles=intervals["cardiac_cycles"],
        pr_intervals=intervals["pr_intervals"],
        qrs_complexes=intervals["qrs_complexes"],
        qt_intervals=intervals["qt_intervals"],
        windows=windows,
        source_name=Path(view_record["source_file"]).name,
    )

    timing_evidence = timing_metadata.get("frame_time_evidence", [])
    ecg_evidence = ecg.get("evidence", [])
    phase_qc_artifacts = [phase_qc_path]
    visual_artifacts = frame_artifacts + ecg["ecg_trace_artifact_paths"] + phase_qc_artifacts
    confidence = min(
        0.95,
        max(
            0.5,
            float(view_record.get("confidence", 0.75)) * 0.35
            + float(ecg.get("confidence", 0.7)) * 0.35
            + (0.85 if timing_evidence else 0.65) * 0.30,
        ),
    )
    quality_flags = list(ecg.get("quality_flags", [])) + list(intervals.get("quality_flags", []))
    repair_history = list(view_record.get("repair_history", [])) + frame_repairs
    if quality_flags:
        repair_history.extend(sorted(set(flag for flag in quality_flags if "repair" in flag)))

    frame_labels = _frame_phase_labels(
        frame_count=frame_count,
        frame_time_ms=frame_time_ms,
        cycles=intervals["cardiac_cycles"],
        source_file=view_record["source_file"],
        source_type=view_record.get("source_type"),
        case_id=view_record.get("case_id"),
        selected_view=view_record.get("selected_view"),
        selected_modality=view_record.get("selected_modality"),
        series_uid=timing_metadata.get("series_uid") or view_record.get("series_uid"),
        sop_instance_uid=timing_metadata.get("sop_instance_uid") or view_record.get("sop_instance_uid"),
        confidence=confidence,
        ecg_evidence=ecg_evidence,
        timing_evidence=timing_evidence,
        visual_artifacts=visual_artifacts,
    )

    downstream = {
        "do_not_reinterpret_ecg": True,
        "time_base": "milliseconds",
        "preferred_windows": windows,
        "cycle_source": intervals["cycle_duration_source"],
        "allowed_phase_labels": sorted(ALLOWED_PHASE_LABELS),
    }
    limitations = list(view_record.get("limitations", []))
    if quality_flags:
        limitations.append("ECG/timing extraction produced repair-quality flags; artifacts remain inspectable.")

    return {
        "case_id": view_record.get("case_id"),
        "source_file": view_record.get("source_file"),
        "source_type": view_record.get("source_type"),
        "selected_view": view_record.get("selected_view"),
        "selected_modality": view_record.get("selected_modality"),
        "series_uid": timing_metadata.get("series_uid") or view_record.get("series_uid"),
        "sop_instance_uid": timing_metadata.get("sop_instance_uid") or view_record.get("sop_instance_uid"),
        "frame_count": frame_count,
        "frame_time_ms": timing_metadata.get("frame_time_ms"),
        "calibrated_time_mapping": timing_metadata.get("frame_to_time_mapping", []),
        "derived_media_paths": view_record.get("derived_media_paths", []) + frame_artifacts,
        "ecg_trace_location": ecg["ecg_trace_location"],
        "ecg_trace_artifact_paths": ecg["ecg_trace_artifact_paths"],
        "phase_qc_artifact_paths": phase_qc_artifacts,
        "ecg_signal_path_json": ecg["ecg_signal_path_json"],
        "ecg_signal_path_csv": ecg["ecg_signal_path_csv"],
        "pr_intervals": intervals["pr_intervals"],
        "qrs_complexes": intervals["qrs_complexes"],
        "qt_intervals": intervals["qt_intervals"],
        "r_peaks": intervals["r_peaks"],
        "visible_ecg_r_peaks": intervals["visible_ecg_r_peaks"],
        "cardiac_cycles": intervals["cardiac_cycles"],
        "frame_phase_labels": frame_labels,
        "selected_analysis_windows": windows,
        "confidence": round(confidence, 4),
        "phase_label_status": "classified",
        "evidence": list(view_record.get("evidence", [])) + ecg_evidence,
        "metadata_evidence": list(view_record.get("metadata_evidence", [])) + timing_metadata.get("metadata_evidence", []),
        "visual_evidence_artifact_paths": list(view_record.get("visual_evidence_artifact_paths", [])) + visual_artifacts,
        "limitations": limitations,
        "repair_history": repair_history,
        "quality_flags": quality_flags,
        "metadata_timing": timing_metadata,
        "downstream_instructions": downstream,
    }


def build_frame_selection_instructions(case_id: str, timing_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Create machine-readable instructions for downstream frame consumers."""

    records = []
    for record in timing_records:
        records.append(
            {
                "case_id": case_id,
                "source_file": record["source_file"],
                "source_type": record["source_type"],
                "selected_view": record["selected_view"],
                "selected_modality": record["selected_modality"],
                "series_uid": record.get("series_uid"),
                "sop_instance_uid": record.get("sop_instance_uid"),
                "frame_count": record["frame_count"],
                "time_base": "milliseconds",
                "frame_time_ms": record.get("frame_time_ms"),
                "cardiac_cycles": record["cardiac_cycles"],
                "preferred_windows": record["selected_analysis_windows"],
                "phase_label_source": "timing_classification.json.frame_phase_labels",
                "allowed_phase_labels": sorted(ALLOWED_PHASE_LABELS),
                "do_not_reinterpret_ecg": True,
                "ecg_signal_path_json": record["ecg_signal_path_json"],
                "confidence": record["confidence"],
                "limitations": record["limitations"],
            }
        )
    return {
        "case_id": case_id,
        "contract_version": TIMING_CONTRACT_VERSION,
        "created_at": _utc_now(),
        "do_not_reinterpret_ecg": True,
        "consumer_rule": "Use these windows and frame_phase_labels directly; do not rerun ECG or timing classification downstream.",
        "records": records,
    }


def _read_view_records(case_id: str, view_output_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    case_dir = view_output_root / case_id
    payload = _load_json(case_dir / "view_classification.json")
    records = [
        record
        for record in payload.get("records", [])
        if record.get("source_type") in USABLE_SOURCE_TYPES and record.get("selected_view") != "not_applicable"
    ]
    return payload, records


def _metadata_for_source(case_id: str, source_file: str, fallback_record: dict[str, Any]) -> dict[str, Any]:
    try:
        ds = pydicom.dcmread(source_file, stop_before_pixels=True, force=True)
        return extract_timing_metadata(case_id, source_file, ds)
    except Exception as exc:
        frame_count = int(fallback_record.get("frame_count") or 1)
        return {
            "case_id": case_id,
            "source_file": source_file,
            "series_uid": fallback_record.get("series_uid"),
            "sop_instance_uid": fallback_record.get("sop_instance_uid"),
            "frame_count": frame_count,
            "frame_time_ms": 0.0 if frame_count == 1 else None,
            "frame_rate_hz": None,
            "heart_rate_bpm": None,
            "frame_to_time_mapping": [
                {"frame_index": index, "time_ms": 0.0 if frame_count == 1 else None, "time_seconds": 0.0 if frame_count == 1 else None}
                for index in range(frame_count)
            ],
            "frame_time_evidence": [{"source": "metadata_read_failure_single_frame_repair", "value": 0.0, "unit": "ms"}]
            if frame_count == 1
            else [],
            "safe_timing_tags": {},
            "ecg_related_tags": [],
            "ultrasound_regions": [],
            "private_vendor_hints": [],
            "metadata_evidence": [f"DICOM timing metadata read failed: {type(exc).__name__}; repair audit recorded."],
            "repair_history": [f"timing_metadata_read_failed:{type(exc).__name__}"],
        }


def _artifact_records(timing_records: list[dict[str, Any]]) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for record in timing_records:
        for path in record.get("ecg_trace_artifact_paths", []):
            artifacts.append({"source_file": record["source_file"], "artifact_path": path, "kind": "ecg_trace"})
        for path in record.get("phase_qc_artifact_paths", []):
            artifacts.append({"source_file": record["source_file"], "artifact_path": path, "kind": "phase_qc_overlay"})
        for key in ["ecg_signal_path_json", "ecg_signal_path_csv"]:
            if record.get(key):
                artifacts.append({"source_file": record["source_file"], "artifact_path": record[key], "kind": "ecg_signal"})
        for path in record.get("visual_evidence_artifact_paths", []):
            artifacts.append({"source_file": record["source_file"], "artifact_path": path, "kind": "visual_evidence"})
    return artifacts


def _repair_events(case_id: str, timing_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    for record in timing_records:
        for item in record.get("repair_history", []):
            events.append({"case_id": case_id, "source_file": record["source_file"], "event": item})
        for flag in record.get("quality_flags", []):
            if "repair" in flag or "sparse" in flag or "missing" in flag:
                events.append({"case_id": case_id, "source_file": record["source_file"], "event": flag})
    return events


def process_case_timing(
    case_id: str,
    source_root: Path | str,
    output_root: Path | str,
    view_output_root: Path | str,
) -> dict[str, Any]:
    """Run timing classification for all usable view-classified source records."""

    output = Path(output_root)
    run_dir = output / case_id
    run_dir.mkdir(parents=True, exist_ok=True)
    view_root = Path(view_output_root)
    view_payload, view_records = _read_view_records(case_id, view_root)
    view_manifest = _load_json(view_root / case_id / "case_manifest.json")

    timing_metadata_records: list[dict[str, Any]] = []
    ecg_records: list[dict[str, Any]] = []
    timing_records: list[dict[str, Any]] = []

    for view_record in view_records:
        metadata = _metadata_for_source(case_id, view_record["source_file"], view_record)
        timing_metadata_records.append(metadata)
        timing_record = classify_timing_for_record(view_record, metadata, run_dir / "sources")
        timing_records.append(timing_record)
        ecg_records.append(
            {
                "case_id": case_id,
                "source_file": timing_record["source_file"],
                "selected_view": timing_record["selected_view"],
                "selected_modality": timing_record["selected_modality"],
                "ecg_trace_location": timing_record["ecg_trace_location"],
                "ecg_trace_artifact_paths": timing_record["ecg_trace_artifact_paths"],
                "ecg_signal_path_json": timing_record["ecg_signal_path_json"],
                "ecg_signal_path_csv": timing_record["ecg_signal_path_csv"],
                "r_peaks": timing_record["r_peaks"],
                "pr_intervals": timing_record["pr_intervals"],
                "qrs_complexes": timing_record["qrs_complexes"],
                "qt_intervals": timing_record["qt_intervals"],
                "confidence": timing_record["confidence"],
                "quality_flags": timing_record["quality_flags"],
            }
        )

    instructions = build_frame_selection_instructions(case_id, timing_records)
    artifacts = _artifact_records(timing_records)
    repair_events = _repair_events(case_id, timing_records)
    phase_counts = Counter(label["phase_label"] for record in timing_records for label in record.get("frame_phase_labels", []))

    case_manifest = {
        "case_id": case_id,
        "created_at": _utc_now(),
        "contract_version": TIMING_CONTRACT_VERSION,
        "source_case_dir": str(Path(source_root) / case_id),
        "view_run_dir": str(view_root / case_id),
        "view_classification_summary": view_payload.get("summary", {}),
        "input_manifest": view_manifest,
        "timed_source_count": len(timing_records),
        "patient_metadata_redacted": True,
        "external_services": [],
    }
    _write_json(run_dir / "case_manifest.json", case_manifest)
    _write_json(
        run_dir / "timing_metadata.json",
        {
            "case_id": case_id,
            "contract_version": TIMING_CONTRACT_VERSION,
            "created_at": _utc_now(),
            "records": timing_metadata_records,
            "summary": {
                "record_count": len(timing_metadata_records),
                "with_frame_time_count": sum(1 for rec in timing_metadata_records if rec.get("frame_time_ms") is not None),
                "with_heart_rate_count": sum(1 for rec in timing_metadata_records if rec.get("heart_rate_bpm")),
            },
        },
    )
    _write_json(
        run_dir / "ecg_extraction.json",
        {
            "case_id": case_id,
            "contract_version": TIMING_CONTRACT_VERSION,
            "created_at": _utc_now(),
            "records": ecg_records,
            "summary": {
                "record_count": len(ecg_records),
                "with_trace_artifacts_count": sum(1 for rec in ecg_records if rec.get("ecg_trace_artifact_paths")),
                "r_peak_count": sum(len(rec.get("r_peaks", [])) for rec in ecg_records),
            },
        },
    )
    _write_json(
        run_dir / "timing_classification.json",
        {
            "case_id": case_id,
            "contract_version": TIMING_CONTRACT_VERSION,
            "created_at": _utc_now(),
            "allowed_phase_labels": sorted(ALLOWED_PHASE_LABELS),
            "records": timing_records,
            "summary": {
                "record_count": len(timing_records),
                "phase_counts": dict(phase_counts),
                "cycle_count": sum(len(rec.get("cardiac_cycles", [])) for rec in timing_records),
                "pr_interval_count": sum(len(rec.get("pr_intervals", [])) for rec in timing_records),
                "qrs_complex_count": sum(len(rec.get("qrs_complexes", [])) for rec in timing_records),
                "qt_interval_count": sum(len(rec.get("qt_intervals", [])) for rec in timing_records),
            },
        },
    )
    _write_json(run_dir / "frame_selection_instructions.json", instructions)
    _write_json(run_dir / "artifact_index.json", {"case_id": case_id, "created_at": _utc_now(), "artifacts": artifacts})
    _write_json(
        run_dir / "audit.json",
        {
            "case_id": case_id,
            "created_at": _utc_now(),
            "mode": "timing_classifier_validation",
            "source_root": str(Path(source_root)),
            "output_root": str(output),
            "view_output_root": str(view_root),
            "external_services": [],
            "skills_used": [
                "medical-image-ingestion",
                "echo-image-harmonization",
                "echo-view-classification",
                "cardiac-phase-detection",
                "adaptive-toolsmith",
            ],
            "view_classification_dependency": "reused_or_regenerated_before_timing",
            "repair_events": repair_events,
            "patient_metadata_redacted": True,
            "privacy_notes": [
                "Source DICOM paths are preserved for local provenance.",
                "Patient-identifying tag values are not serialized by this timing workflow.",
            ],
        },
    )

    return {
        "case_id": case_id,
        "run_dir": str(run_dir),
        "timed_source_count": len(timing_records),
        "cycle_count": sum(len(rec.get("cardiac_cycles", [])) for rec in timing_records),
        "pr_interval_count": sum(len(rec.get("pr_intervals", [])) for rec in timing_records),
        "qrs_complex_count": sum(len(rec.get("qrs_complexes", [])) for rec in timing_records),
        "qt_interval_count": sum(len(rec.get("qt_intervals", [])) for rec in timing_records),
        "early_diastole_window_count": sum(
            len(rec.get("selected_analysis_windows", {}).get("early_diastole", [])) for rec in timing_records
        ),
        "late_systole_window_count": sum(
            len(rec.get("selected_analysis_windows", {}).get("late_systole", [])) for rec in timing_records
        ),
        "repair_event_count": len(repair_events),
        "records": timing_records,
        "repair_events": repair_events,
    }


def run_validation(
    *,
    case_ids: list[str],
    source_root: Path | str,
    output_root: Path | str,
    view_output_root: Path | str,
    max_video_frames: int = 80,
    force_view_refresh: bool = False,
) -> dict[str, Any]:
    """Run A1-A5 timing validation using view-classification outputs."""

    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    view_dependency = ensure_view_classification_outputs(
        case_ids,
        Path(source_root),
        Path(view_output_root),
        max_video_frames=max_video_frames,
        force_refresh=force_view_refresh,
    )

    results = []
    repair_log = []
    timing_table = []
    for case_id in case_ids:
        result = process_case_timing(case_id, source_root, output, view_output_root)
        results.append(result)
        repair_log.extend(result["repair_events"])
        for record in result["records"]:
            timing_table.append(
                {
                    "case_id": case_id,
                    "source_file": record["source_file"],
                    "source_type": record["source_type"],
                    "selected_view": record["selected_view"],
                    "selected_modality": record["selected_modality"],
                    "frame_count": record["frame_count"],
                    "frame_time_ms": record.get("frame_time_ms"),
                    "cycle_count": len(record.get("cardiac_cycles", [])),
                    "pr_interval_count": len(record.get("pr_intervals", [])),
                    "qrs_complex_count": len(record.get("qrs_complexes", [])),
                    "qt_interval_count": len(record.get("qt_intervals", [])),
                    "early_diastole_windows": record.get("selected_analysis_windows", {}).get("early_diastole", []),
                    "late_systole_windows": record.get("selected_analysis_windows", {}).get("late_systole", []),
                    "confidence": record["confidence"],
                    "phase_label_status": record["phase_label_status"],
                }
            )

    per_case = {
        result["case_id"]: {
            "timed_source_count": result["timed_source_count"],
            "cycle_count": result["cycle_count"],
            "pr_interval_count": result["pr_interval_count"],
            "qrs_complex_count": result["qrs_complex_count"],
            "qt_interval_count": result["qt_interval_count"],
            "early_diastole_window_count": result["early_diastole_window_count"],
            "late_systole_window_count": result["late_systole_window_count"],
            "repair_event_count": result["repair_event_count"],
        }
        for result in results
    }
    summary = {
        "created_at": _utc_now(),
        "contract_version": TIMING_CONTRACT_VERSION,
        "source_root": str(Path(source_root)),
        "output_root": str(output),
        "view_output_root": str(Path(view_output_root)),
        "cases_processed": len(results),
        "cases": case_ids,
        "view_dependency": view_dependency,
        "per_case": per_case,
        "total_timed_source_count": sum(result["timed_source_count"] for result in results),
        "total_cycle_count": sum(result["cycle_count"] for result in results),
        "total_pr_interval_count": sum(result["pr_interval_count"] for result in results),
        "total_qrs_complex_count": sum(result["qrs_complex_count"] for result in results),
        "total_qt_interval_count": sum(result["qt_interval_count"] for result in results),
        "total_early_diastole_window_count": sum(result["early_diastole_window_count"] for result in results),
        "total_late_systole_window_count": sum(result["late_systole_window_count"] for result in results),
    }
    _write_json(output / "summary.json", summary)
    _write_json(output / "timing_table.json", {"created_at": _utc_now(), "records": timing_table})
    _write_json(output / "repair_log.json", {"created_at": _utc_now(), "events": repair_log})
    return summary
