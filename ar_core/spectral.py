"""Preserved spectral velocity-time extraction utilities.

This module intentionally contains no echo view classification. It preserves
the PWD/CWD envelope extraction behavior that previously lived inside the
deterministic view-classification module.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from ar_core.dicom_media import num, write_json


def spectral_crop(frame: np.ndarray, region: dict[str, Any]) -> tuple[np.ndarray, int, int, int, int]:
    x0 = int(num(region.get("region_location_min_x")))
    y0 = int(num(region.get("region_location_min_y")))
    x1 = int(num(region.get("region_location_max_x")))
    y1 = int(num(region.get("region_location_max_y")))
    x0 = max(0, min(frame.shape[1] - 1, x0))
    y0 = max(0, min(frame.shape[0] - 1, y0))
    x1 = max(x0, min(frame.shape[1] - 1, x1))
    y1 = max(y0, min(frame.shape[0] - 1, y1))
    return frame[y0 : y1 + 1, x0 : x1 + 1], x0, y0, x1, y1


def extract_spectral_trace(
    *,
    frame: np.ndarray,
    spectral_region: dict[str, Any],
    output_dir: Path | str,
    artifact_stem: str,
    source_file: str,
    modality: str,
) -> dict[str, Any]:
    """Extract a calibrated spectral envelope trace from one spectral frame."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    crop, x0, y0, _x1, _y1 = spectral_crop(frame, spectral_region)
    ref_x = spectral_region.get("reference_pixel_x")
    ref_y = spectral_region.get("reference_pixel_y")
    if ref_x is None or ref_y is None:
        return {
            "status": "repair_required",
            "source_file": source_file,
            "modality": modality,
            "quality_flags": ["missing_reference_pixel_calibration"],
            "calibration_provenance": {"source": "DICOM SequenceOfUltrasoundRegions"},
        }
    ref_x = int(num(ref_x))
    ref_y = int(num(ref_y))
    delta_x = float(num(spectral_region.get("physical_delta_x")))
    delta_y = float(num(spectral_region.get("physical_delta_y")))
    if not delta_x or not delta_y:
        return {
            "status": "repair_required",
            "source_file": source_file,
            "modality": modality,
            "quality_flags": ["missing_physical_delta_calibration"],
            "calibration_provenance": {"source": "DICOM SequenceOfUltrasoundRegions"},
        }

    gray = np.mean(crop.astype(np.float32), axis=2)
    baseline = max(0, min(gray.shape[0] - 1, ref_y))
    threshold = max(55.0, float(np.percentile(gray, 92)))
    mask = gray >= threshold
    mask[:, :3] = False
    mask[:, -3:] = False
    if baseline > 2:
        above_count = int(mask[:baseline, :].sum())
    else:
        above_count = 0
    below_count = int(mask[baseline + 1 :, :].sum()) if baseline + 1 < mask.shape[0] else 0
    direction = "above_baseline" if above_count >= below_count else "below_baseline"

    points = []
    for x in range(mask.shape[1]):
        ys = np.flatnonzero(mask[:, x])
        if ys.size == 0:
            continue
        if direction == "above_baseline":
            candidates = ys[ys <= baseline]
            if candidates.size == 0:
                continue
            y = int(candidates.min())
        else:
            candidates = ys[ys >= baseline]
            if candidates.size == 0:
                continue
            y = int(candidates.max())
        time_s = (x - ref_x) * delta_x
        velocity_cm_s = (y - ref_y) * delta_y
        points.append(
            {
                "x_px": x + x0,
                "y_px": y + y0,
                "time_s": round(float(time_s), 6),
                "velocity_cm_s": round(float(velocity_cm_s), 6),
            }
        )

    quality_flags = []
    if len(points) < 10:
        quality_flags.append("sparse_trace_points")
    if direction == "below_baseline":
        quality_flags.append("dominant_trace_below_baseline")

    trace_json = output / f"{artifact_stem}_trace.json"
    trace_csv = output / f"{artifact_stem}_trace.csv"
    overlay_path = output / f"{artifact_stem}_overlay.png"
    trace_payload = {
        "source_file": source_file,
        "modality": modality,
        "direction": direction,
        "baseline_px": baseline + y0,
        "time_axis_calibration": {"unit": "s", "delta_per_px": delta_x, "reference_pixel_x": ref_x + x0},
        "velocity_axis_calibration": {
            "unit": "cm/s",
            "delta_per_px": delta_y,
            "reference_pixel_y": ref_y + y0,
        },
        "velocity_time_points": points,
        "quality_flags": quality_flags,
    }
    write_json(trace_json, trace_payload)
    with trace_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["x_px", "y_px", "time_s", "velocity_cm_s"])
        writer.writeheader()
        writer.writerows(points)

    overlay = Image.fromarray(frame.copy())
    draw = ImageDraw.Draw(overlay)
    draw.line((x0, baseline + y0, x0 + crop.shape[1] - 1, baseline + y0), fill=(0, 255, 0), width=2)
    if points:
        xy = [(point["x_px"], point["y_px"]) for point in points]
        draw.line(xy, fill=(255, 0, 0), width=2)
    overlay.save(overlay_path)

    return {
        "status": "success" if points else "repair_required",
        "source_file": source_file,
        "modality": modality,
        "target": None,
        "sample_site": None,
        "baseline_px": baseline + y0,
        "time_axis_calibration": trace_payload["time_axis_calibration"],
        "velocity_axis_calibration": trace_payload["velocity_axis_calibration"],
        "velocity_time_points": points[:200],
        "envelope_trace_path_json": str(trace_json),
        "envelope_trace_path_csv": str(trace_csv),
        "overlay_artifact_paths": [str(overlay_path)],
        "sonographer_pointing_evidence": [
            "DICOM spectral region provides calibrated time/velocity axes.",
            "Anatomic target/sample-site text was not serialized from PHI-risk overlays.",
        ],
        "calibration_provenance": {
            "source": "DICOM SequenceOfUltrasoundRegions",
            "time_axis": trace_payload["time_axis_calibration"],
            "velocity_axis": trace_payload["velocity_axis_calibration"],
        },
        "quality_flags": quality_flags,
    }
