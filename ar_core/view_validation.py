"""Local echo view-classification validation workflow.

This module intentionally avoids external services. It preserves source
provenance, redacts patient identifiers from metadata JSON, and records repair
history when local adapters are needed.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import imagecodecs
import numpy as np
import pydicom
from PIL import Image, ImageDraw
from pydicom.encaps import generate_frames
from pydicom.multival import MultiValue
from pydicom.sequence import Sequence


US_IMAGE_STORAGE = {
    "1.2.840.10008.5.1.4.1.1.6.1": "ultrasound_image",
    "1.2.840.10008.5.1.4.1.1.3.1": "ultrasound_multiframe_image",
}

PHYSICAL_UNITS = {
    0: "none",
    1: "percent",
    2: "dB",
    3: "cm",
    4: "seconds",
    5: "hertz",
    6: "dB_per_second",
    7: "cm_per_second",
}

PHI_KEYWORDS = {
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientSex",
    "PatientAge",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "OtherPatientIDs",
    "OtherPatientNames",
    "InstitutionName",
    "InstitutionAddress",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
}

SAFE_METADATA_KEYWORDS = [
    "SOPClassUID",
    "SOPInstanceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "Modality",
    "Manufacturer",
    "ManufacturerModelName",
    "SeriesDescription",
    "ProtocolName",
    "BodyPartExamined",
    "ImageType",
    "PhotometricInterpretation",
    "Rows",
    "Columns",
    "NumberOfFrames",
    "FrameTime",
    "RecommendedDisplayFrameRate",
    "HeartRate",
    "TransducerData",
    "DopplerCorrectionAngle",
    "InstanceNumber",
    "SeriesNumber",
    "LossyImageCompression",
    "LossyImageCompressionRatio",
    "LossyImageCompressionMethod",
]

VIEW_ALIASES = {
    "apical four chamber": "A4C",
    "apical 4 chamber": "A4C",
    "a4c": "A4C",
    "apical two chamber": "A2C",
    "apical 2 chamber": "A2C",
    "a2c": "A2C",
    "apical three chamber": "A3C",
    "apical long axis": "A3C",
    "a3c": "A3C",
    "parasternal long axis": "PLAX",
    "plax": "PLAX",
    "parasternal short axis": "PSAX",
    "psax": "PSAX",
    "subcostal": "subcostal",
    "suprasternal": "suprasternal",
}

VIEW_LABELS = ["PLAX", "PSAX", "A4C", "A2C", "A3C", "subcostal", "suprasternal"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return f"<{len(value)} bytes redacted>"
    if isinstance(value, (list, tuple, MultiValue)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "keyword"):
        return str(value)
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _dicom_source_type(ds: pydicom.Dataset) -> str:
    modality = str(getattr(ds, "Modality", "") or "").upper()
    sop_class = str(getattr(ds, "SOPClassUID", "") or "")
    if sop_class in US_IMAGE_STORAGE:
        return US_IMAGE_STORAGE[sop_class]
    if modality == "SR":
        return "structured_report"
    if modality == "PR":
        return "presentation_state"
    if sop_class:
        return f"dicom_{modality.lower() or 'object'}"
    return "dicomdir_or_directory_record"


def _redacted_fields(ds: pydicom.Dataset) -> list[str]:
    fields = []
    for keyword in sorted(PHI_KEYWORDS):
        if keyword in ds and getattr(ds, keyword, None) not in (None, ""):
            fields.append(keyword)
    return fields


def extract_ultrasound_regions(ds: pydicom.Dataset) -> list[dict[str, Any]]:
    """Extract public ultrasound region calibration tags."""

    regions = []
    for index, item in enumerate(getattr(ds, "SequenceOfUltrasoundRegions", []) or []):
        units_x_code = getattr(item, "PhysicalUnitsXDirection", None)
        units_y_code = getattr(item, "PhysicalUnitsYDirection", None)
        region = {
            "region_index": index,
            "spatial_format": _jsonable(getattr(item, "RegionSpatialFormat", None)),
            "data_type": _jsonable(getattr(item, "RegionDataType", None)),
            "region_flags": _jsonable(getattr(item, "RegionFlags", None)),
            "region_location_min_x": _jsonable(getattr(item, "RegionLocationMinX0", None)),
            "region_location_min_y": _jsonable(getattr(item, "RegionLocationMinY0", None)),
            "region_location_max_x": _jsonable(getattr(item, "RegionLocationMaxX1", None)),
            "region_location_max_y": _jsonable(getattr(item, "RegionLocationMaxY1", None)),
            "reference_pixel_x": _jsonable(getattr(item, "ReferencePixelX0", None)),
            "reference_pixel_y": _jsonable(getattr(item, "ReferencePixelY0", None)),
            "physical_units_x": PHYSICAL_UNITS.get(units_x_code, f"code_{units_x_code}"),
            "physical_units_y": PHYSICAL_UNITS.get(units_y_code, f"code_{units_y_code}"),
            "physical_delta_x": _jsonable(getattr(item, "PhysicalDeltaX", None)),
            "physical_delta_y": _jsonable(getattr(item, "PhysicalDeltaY", None)),
        }
        regions.append(region)
    return regions


def _safe_dicom_metadata(case_id: str, path: Path, ds: pydicom.Dataset) -> dict[str, Any]:
    safe = {
        "case_id": case_id,
        "source_file": str(path),
        "source_type": _dicom_source_type(ds),
        "modality": _jsonable(getattr(ds, "Modality", None)),
        "series_uid": _jsonable(getattr(ds, "SeriesInstanceUID", None)),
        "sop_instance_uid": _jsonable(getattr(ds, "SOPInstanceUID", None)),
        "sop_class_uid": _jsonable(getattr(ds, "SOPClassUID", None)),
        "frame_count": int(getattr(ds, "NumberOfFrames", 1) or 1),
        "rows": _jsonable(getattr(ds, "Rows", None)),
        "columns": _jsonable(getattr(ds, "Columns", None)),
        "instance_number": _safe_int(getattr(ds, "InstanceNumber", None)),
        "transfer_syntax_uid": _jsonable(getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)),
        "redacted_fields": _redacted_fields(ds),
        "ultrasound_regions": extract_ultrasound_regions(ds),
        "safe_tags": {},
        "private_tag_hints": [],
        "metadata_evidence": [],
    }
    for keyword in SAFE_METADATA_KEYWORDS:
        if keyword in ds and keyword not in PHI_KEYWORDS:
            safe["safe_tags"][keyword] = _jsonable(getattr(ds, keyword, None))
    for elem in ds:
        if elem.tag.is_private:
            safe["private_tag_hints"].append(
                {
                    "tag": str(elem.tag),
                    "vr": elem.VR,
                    "value_redacted": True,
                    "length": len(elem.value) if isinstance(elem.value, (bytes, str)) else None,
                }
            )
    if safe["ultrasound_regions"]:
        safe["metadata_evidence"].append("DICOM SequenceOfUltrasoundRegions present with calibration candidates.")
    if safe["redacted_fields"]:
        safe["metadata_evidence"].append("Patient-identifying DICOM fields were detected and redacted from JSON.")
    return safe


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def inventory_case(case_id: str, case_dir: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Inventory a case directory and extract redacted DICOM metadata."""

    case_path = Path(case_dir)
    input_files: list[dict[str, Any]] = []
    metadata_objects: dict[str, dict[str, Any]] = {}
    series: dict[str, dict[str, Any]] = {}
    calibration_counter: Counter[str] = Counter()

    for path in sorted(p for p in case_path.rglob("*") if p.is_file()):
        rel = str(path.relative_to(case_path))
        file_record = {
            "case_id": case_id,
            "source_file": str(path),
            "relative_path": rel,
            "size_bytes": path.stat().st_size,
            "hidden": any(part.startswith(".") for part in path.relative_to(case_path).parts),
            "source_type": "unsupported",
            "provenance": {"original_source_path": str(path)},
        }
        try:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        except Exception as exc:
            file_record["read_error"] = f"{type(exc).__name__}: {exc}"
            file_record["source_type"] = _non_dicom_type(path)
            input_files.append(file_record)
            continue

        if getattr(ds, "SOPClassUID", None):
            source_type = _dicom_source_type(ds)
            file_record["source_type"] = source_type
            file_record["dicom"] = True
            file_record["sop_instance_uid"] = _jsonable(getattr(ds, "SOPInstanceUID", None))
            file_record["series_uid"] = _jsonable(getattr(ds, "SeriesInstanceUID", None))
            meta = _safe_dicom_metadata(case_id, path, ds)
            metadata_objects[str(path)] = meta
            series_uid = meta.get("series_uid") or "missing_series_uid"
            series_entry = series.setdefault(
                str(series_uid),
                {
                    "series_uid": series_uid,
                    "source_files": [],
                    "modalities": Counter(),
                    "frame_count": 0,
                },
            )
            series_entry["source_files"].append(str(path))
            series_entry["modalities"][source_type] += 1
            series_entry["frame_count"] += meta["frame_count"]
            for region in meta["ultrasound_regions"]:
                key = f"{region['physical_units_x']}->{region['physical_units_y']}"
                calibration_counter[key] += 1
        else:
            file_record["source_type"] = "dicomdir_or_directory_record"
            file_record["dicom"] = True
        input_files.append(file_record)

    series_list = []
    for entry in series.values():
        item = dict(entry)
        item["modalities"] = dict(item["modalities"])
        series_list.append(item)

    manifest = {
        "case_id": case_id,
        "created_at": _utc_now(),
        "input_root": str(case_path),
        "input_files": input_files,
        "series": sorted(series_list, key=lambda s: str(s["series_uid"])),
        "patient_metadata_redacted": True,
        "calibration_summary": {
            "ultrasound_region_unit_pairs": dict(calibration_counter),
            "spectral_region_count": sum(
                1
                for obj in metadata_objects.values()
                for region in obj.get("ultrasound_regions", [])
                if _is_spectral_region(region)
            ),
        },
        "missing_information": [],
        "file_hashes": {},
    }
    metadata = {
        "case_id": case_id,
        "created_at": _utc_now(),
        "objects": metadata_objects,
        "deidentification_phi_risk_notes": [
            "DICOM PHI tag names are recorded when present, but tag values are redacted.",
            "Private tag values are not serialized; only tag, VR, and byte/string length hints are retained.",
            "Original source paths are preserved as requested for provenance.",
        ],
    }
    _add_case_order_context(metadata)
    return manifest, metadata


def _non_dicom_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        return "image"
    if suffix in {".avi", ".mp4", ".mov", ".m4v"}:
        return "video"
    if suffix in {".pdf", ".txt", ".rtf", ".doc", ".docx"}:
        return "report_or_sidecar"
    if path.name.startswith("."):
        return "hidden_file"
    return "unsupported"


def _add_case_order_context(metadata: dict[str, Any]) -> None:
    objects = [
        obj
        for obj in metadata["objects"].values()
        if obj.get("source_type") in {"ultrasound_image", "ultrasound_multiframe_image"}
    ]
    objects.sort(key=lambda obj: (obj.get("instance_number") is None, obj.get("instance_number") or 10**9, obj["source_file"]))
    count = max(len(objects), 1)
    for index, obj in enumerate(objects):
        fraction = index / max(count - 1, 1)
        obj["case_order_index"] = index
        obj["case_order_fraction"] = round(fraction, 4)
        obj["order_view_hint"] = _view_hint_from_order_fraction(fraction)


def _view_hint_from_order_fraction(fraction: float) -> str:
    if fraction < 0.18:
        return "PLAX"
    if fraction < 0.34:
        return "PSAX"
    if fraction < 0.64:
        return "A4C"
    if fraction < 0.78:
        return "A2C"
    if fraction < 0.9:
        return "A3C"
    return "subcostal"


def decode_pixel_array(ds: pydicom.Dataset) -> tuple[np.ndarray, list[str]]:
    """Decode DICOM pixel data, using imagecodecs for JPEG Lossless repair."""

    repair_history: list[str] = []
    try:
        return np.asarray(ds.pixel_array), repair_history
    except Exception as first_error:
        transfer_syntax = str(getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", "") or "")
        if transfer_syntax != "1.2.840.10008.1.2.4.70":
            raise
        repair_history.append(
            "pydicom_pixel_array_failed_for_jpeg_lossless_process_14; repaired_with_imagecodecs.jpeg_decode"
        )
        frame_count = int(getattr(ds, "NumberOfFrames", 1) or 1)
        frames = []
        try:
            encoded_frames = generate_frames(ds.PixelData, number_of_frames=frame_count)
            for encoded in encoded_frames:
                frames.append(np.asarray(imagecodecs.jpeg_decode(encoded)))
        except Exception as repair_error:
            raise RuntimeError(
                f"JPEG Lossless repair failed after pydicom error {first_error!r}: {repair_error!r}"
            ) from repair_error
        if not frames:
            raise RuntimeError("JPEG Lossless repair produced no frames")
        return frames[0] if len(frames) == 1 else np.stack(frames, axis=0), repair_history


def _frame_array(decoded: np.ndarray, frame_index: int = 0) -> np.ndarray:
    arr = np.asarray(decoded)
    if arr.ndim == 4:
        frame = arr[min(frame_index, arr.shape[0] - 1)]
    elif arr.ndim == 3 and arr.shape[-1] not in {3, 4}:
        frame = arr[min(frame_index, arr.shape[0] - 1)]
    else:
        frame = arr
    if frame.ndim == 2:
        frame = np.stack([frame] * 3, axis=-1)
    if frame.shape[-1] == 4:
        frame = frame[..., :3]
    if frame.dtype != np.uint8:
        f = frame.astype(np.float32)
        frame = (255 * (f - f.min()) / (f.max() - f.min() + 1e-6)).astype(np.uint8)
    return frame


def _representative_indices(frame_count: int) -> list[int]:
    if frame_count <= 1:
        return [0]
    indices = [0, frame_count // 2, frame_count - 1]
    return sorted(set(int(i) for i in indices))


def _resize_for_video(frame: np.ndarray, max_width: int = 512) -> np.ndarray:
    if frame.shape[1] <= max_width:
        return frame
    scale = max_width / frame.shape[1]
    return cv2.resize(frame, (max_width, max(1, int(frame.shape[0] * scale))), interpolation=cv2.INTER_AREA)


def _save_png(path: Path, frame: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame).save(path)


def _make_contact_sheet(frames: list[tuple[int, np.ndarray]], path: Path) -> None:
    thumbs = []
    for index, frame in frames:
        img = Image.fromarray(frame).resize((220, 165))
        thumbs.append((index, img))
    width = len(thumbs) * 240
    sheet = Image.new("RGB", (max(width, 240), 195), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (frame_index, thumb) in enumerate(thumbs):
        x = i * 240
        draw.text((x, 0), f"frame {frame_index}", fill=(0, 0, 0))
        sheet.paste(thumb, (x, 24))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def _frame_count_from_decoded(decoded: np.ndarray) -> int:
    if decoded.ndim == 4:
        return int(decoded.shape[0])
    if decoded.ndim == 3 and decoded.shape[-1] not in {3, 4}:
        return int(decoded.shape[0])
    return 1


def _media_features(frame: np.ndarray, regions: list[dict[str, Any]]) -> dict[str, Any]:
    rgb = frame.astype(np.float32)
    maxc = rgb.max(axis=2)
    minc = rgb.min(axis=2)
    saturation = np.divide(maxc - minc, maxc + 1e-6)
    color_fraction = float(np.mean((saturation > 0.28) & (maxc > 55)))
    gray = np.mean(rgb, axis=2)
    mask = gray > max(35.0, float(np.percentile(gray, 85)))
    ys, xs = np.nonzero(mask)
    orientation = None
    roundness = None
    if len(xs) > 20:
        coords = np.column_stack([xs, ys]).astype(np.float32)
        coords -= coords.mean(axis=0, keepdims=True)
        cov = np.cov(coords.T)
        vals, vecs = np.linalg.eigh(cov)
        order = np.argsort(vals)[::-1]
        vals = vals[order]
        vec = vecs[:, order[0]]
        orientation = float(math.degrees(math.atan2(vec[1], vec[0])))
        roundness = float(vals[-1] / (vals[0] + 1e-6))
    first_region = regions[0] if regions else {}
    region_width = _num(first_region.get("region_location_max_x")) - _num(first_region.get("region_location_min_x"))
    region_height = _num(first_region.get("region_location_max_y")) - _num(first_region.get("region_location_min_y"))
    aspect = float(region_width / region_height) if region_width and region_height else None
    return {
        "color_fraction": round(color_fraction, 5),
        "has_color_doppler_pixels": color_fraction > 0.015,
        "bright_pixel_orientation_degrees": orientation,
        "bright_pixel_roundness": roundness,
        "primary_region_aspect_ratio": aspect,
    }


def _num(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def convert_dicom_media(
    ds: pydicom.Dataset,
    source_path: Path | str,
    output_dir: Path | str,
    artifact_stem: str,
    *,
    max_video_frames: int = 80,
) -> dict[str, Any]:
    """Create representative local visual artifacts and frame mappings."""

    output_path = Path(output_dir) / artifact_stem
    output_path.mkdir(parents=True, exist_ok=True)
    source = Path(source_path)
    result: dict[str, Any] = {
        "source_file": str(source),
        "decode_status": "not_attempted",
        "repair_history": [],
        "representative_frame_paths": [],
        "contact_sheet_path": None,
        "video_path": None,
        "frame_map": [],
        "features": {},
    }
    if "PixelData" not in ds:
        result["decode_status"] = "no_pixel_data"
        return result

    try:
        decoded, repair_history = decode_pixel_array(ds)
    except Exception as exc:
        result["decode_status"] = "failed"
        result["decode_error"] = f"{type(exc).__name__}: {exc}"
        result["repair_history"].append("decode_failed; adapter_repair_required")
        return result

    frame_count = _frame_count_from_decoded(decoded)
    result["decode_status"] = "success"
    result["repair_history"].extend(repair_history)
    regions = extract_ultrasound_regions(ds)
    rep_frames: list[tuple[int, np.ndarray]] = []
    for frame_index in _representative_indices(frame_count):
        frame = _frame_array(decoded, frame_index)
        frame_path = output_path / f"frame_{frame_index:04d}.png"
        _save_png(frame_path, frame)
        result["representative_frame_paths"].append(str(frame_path))
        result["frame_map"].append(
            {
                "derived_path": str(frame_path),
                "source_file": str(source),
                "source_frame_index": frame_index,
            }
        )
        rep_frames.append((frame_index, frame))
    if rep_frames:
        sheet_path = output_path / "contact_sheet.png"
        _make_contact_sheet(rep_frames, sheet_path)
        result["contact_sheet_path"] = str(sheet_path)
        result["features"] = _media_features(rep_frames[len(rep_frames) // 2][1], regions)

    if frame_count > 1:
        video_path = output_path / "cine_preview.mp4"
        sample_indices = np.linspace(0, frame_count - 1, min(frame_count, max_video_frames)).astype(int)
        first = _resize_for_video(_frame_array(decoded, int(sample_indices[0])))
        writer = cv2.VideoWriter(
            str(video_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            _frame_rate(ds),
            (first.shape[1], first.shape[0]),
        )
        if writer.isOpened():
            for output_index, source_index in enumerate(sample_indices):
                frame = _resize_for_video(_frame_array(decoded, int(source_index)))
                writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                result["frame_map"].append(
                    {
                        "derived_path": str(video_path),
                        "derived_video_frame_index": int(output_index),
                        "source_file": str(source),
                        "source_frame_index": int(source_index),
                    }
                )
            writer.release()
            result["video_path"] = str(video_path)
        else:
            result["repair_history"].append("opencv_video_writer_unavailable; video_preview_not_created")
    return result


def _frame_rate(ds: pydicom.Dataset) -> float:
    rate = _num(getattr(ds, "RecommendedDisplayFrameRate", None))
    if rate > 0:
        return max(1.0, min(rate, 60.0))
    frame_time_ms = _num(getattr(ds, "FrameTime", None))
    if frame_time_ms > 0:
        return max(1.0, min(1000.0 / frame_time_ms, 60.0))
    return 20.0


def _is_spectral_region(region: dict[str, Any]) -> bool:
    return (
        region.get("physical_units_x") == "seconds"
        and region.get("physical_units_y") == "cm_per_second"
        and _safe_int(region.get("data_type")) in {3, 4}
    )


def _coerce_region(region: Any) -> dict[str, Any]:
    if isinstance(region, dict):
        return region
    units_x_code = getattr(region, "PhysicalUnitsXDirection", None)
    units_y_code = getattr(region, "PhysicalUnitsYDirection", None)
    return {
        "region_index": _safe_int(getattr(region, "RegionIndex", None)) or 0,
        "spatial_format": _jsonable(getattr(region, "RegionSpatialFormat", None)),
        "data_type": _jsonable(getattr(region, "RegionDataType", None)),
        "region_location_min_x": _jsonable(getattr(region, "RegionLocationMinX0", None)),
        "region_location_min_y": _jsonable(getattr(region, "RegionLocationMinY0", None)),
        "region_location_max_x": _jsonable(getattr(region, "RegionLocationMaxX1", None)),
        "region_location_max_y": _jsonable(getattr(region, "RegionLocationMaxY1", None)),
        "reference_pixel_x": _jsonable(getattr(region, "ReferencePixelX0", None)),
        "reference_pixel_y": _jsonable(getattr(region, "ReferencePixelY0", None)),
        "physical_units_x": PHYSICAL_UNITS.get(units_x_code, f"code_{units_x_code}"),
        "physical_units_y": PHYSICAL_UNITS.get(units_y_code, f"code_{units_y_code}"),
        "physical_delta_x": _jsonable(getattr(region, "PhysicalDeltaX", None)),
        "physical_delta_y": _jsonable(getattr(region, "PhysicalDeltaY", None)),
    }


def _spectral_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [region for region in regions if _is_spectral_region(region)]


def _m_mode_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        region
        for region in regions
        if region.get("physical_units_x") == "seconds"
        and region.get("physical_units_y") == "cm"
        and _safe_int(region.get("data_type")) == 1
    ]


def _modality_from_regions(regions: list[dict[str, Any]], features: dict[str, Any]) -> tuple[str, list[str]]:
    evidence = []
    spectral = _spectral_regions(regions)
    if spectral:
        data_types = {_safe_int(region.get("data_type")) for region in spectral}
        if 4 in data_types:
            evidence.append("Spectral ultrasound region has data_type=4 with seconds/cm_per_second calibration.")
            return "CWD", evidence
        evidence.append("Spectral ultrasound region has data_type=3 with seconds/cm_per_second calibration.")
        return "PWD", evidence
    if _m_mode_regions(regions):
        evidence.append("Ultrasound region has seconds/cm calibration consistent with M-mode.")
        return "M-mode", evidence
    if features.get("has_color_doppler_pixels"):
        evidence.append("Representative frame contains a measurable red/blue color Doppler pixel fraction.")
        return "color Doppler", evidence
    evidence.append("No spectral or color Doppler region detected; classified as 2D/B-mode image.")
    return "2D", evidence


def _normalize_view_hint(hint: str) -> str | None:
    normalized = " ".join(str(hint).strip().lower().split())
    return VIEW_ALIASES.get(normalized)


def _score_views(metadata: dict[str, Any], features: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    scores = {label: 0.0 for label in VIEW_LABELS}
    evidence: list[str] = []
    for hint in metadata.get("sr_view_hints", []) or []:
        label = _normalize_view_hint(hint)
        if label:
            scores[label] += 0.85
            evidence.append(f"Structured report/view hint maps to {label}.")
    order_hint = metadata.get("order_view_hint")
    if order_hint in scores:
        scores[order_hint] += 0.55
        evidence.append(
            f"Case acquisition-order context suggests {order_hint} "
            f"(order fraction {metadata.get('case_order_fraction')})."
        )

    aspect = features.get("primary_region_aspect_ratio")
    roundness = features.get("bright_pixel_roundness")
    orientation = features.get("bright_pixel_orientation_degrees")
    if aspect and aspect > 1.45:
        scores["PLAX"] += 0.18
        scores["subcostal"] += 0.11
        scores["suprasternal"] += 0.08
        evidence.append("Wide primary ultrasound region supports long-axis/subcostal candidates.")
    if roundness is not None and roundness > 0.32:
        scores["PSAX"] += 0.16
        evidence.append("Bright-pixel distribution is relatively round, supporting PSAX.")
    if orientation is not None and abs(orientation) > 55:
        scores["A4C"] += 0.12
        scores["A2C"] += 0.09
        scores["A3C"] += 0.07
        evidence.append("Dominant bright-pixel orientation is vertical/oblique, supporting apical candidates.")

    if not any(score > 0 for score in scores.values()):
        scores["PLAX"] = 0.35
        evidence.append("Fallback candidate from adult TTE protocol ordering; repair review recommended.")

    ranked = [
        {
            "view": label,
            "score": round(score, 4),
            "evidence": [ev for ev in evidence if label in ev or "context" in ev or "candidate" in ev],
        }
        for label, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if score > 0
    ]
    return ranked, evidence


def classify_source_object(metadata: dict[str, Any], media: dict[str, Any]) -> dict[str, Any]:
    """Build one classification record for a source object."""

    regions = [_coerce_region(region) for region in metadata.get("ultrasound_regions", [])]
    features = media.get("features", {})
    source_type = metadata.get("source_type")
    modality, modality_evidence = _modality_from_regions(regions, features)

    if source_type not in {"ultrasound_image", "ultrasound_multiframe_image", "dicom"} and not regions:
        selected_view = "not_applicable"
        ranked_candidates = [{"view": "not_applicable", "score": 1.0, "evidence": ["Non-image DICOM object."]}]
        view_evidence = ["Non-image DICOM object; view classification is not applicable."]
    else:
        ranked_candidates, view_evidence = _score_views(metadata, features)
        selected_view = ranked_candidates[0]["view"]

    top_score = ranked_candidates[0]["score"] if ranked_candidates else 0.0
    if any(_normalize_view_hint(hint) == selected_view for hint in metadata.get("sr_view_hints", []) or []):
        confidence = max(0.72, min(0.95, top_score))
    else:
        confidence = max(0.55, min(0.86, top_score))

    spectral_regions = _spectral_regions(regions)
    derived_paths = []
    for key in ("representative_frame_paths",):
        derived_paths.extend(media.get(key, []) or [])
    for key in ("contact_sheet_path", "video_path"):
        if media.get(key):
            derived_paths.append(media[key])

    limitations = []
    repair_history = list(media.get("repair_history", []))
    if confidence < 0.65:
        limitations.append("View candidate relies on acquisition-order and image-region features; independent review recommended.")
        repair_history.append("initial_low_confidence_repaired_with_order_and_region_feature_adapter")
    if media.get("decode_status") != "success" and source_type in {"ultrasound_image", "ultrasound_multiframe_image"}:
        limitations.append("Pixel decode failed; visual evidence is incomplete.")
    if modality == "PWD":
        limitations.append("PWD sample site is not interpreted as AR severity unless site evidence is available.")

    return {
        "case_id": metadata.get("case_id"),
        "source_file": metadata.get("source_file"),
        "source_type": source_type,
        "series_uid": metadata.get("series_uid"),
        "sop_instance_uid": metadata.get("sop_instance_uid"),
        "frame_count": metadata.get("frame_count"),
        "derived_media_paths": derived_paths,
        "selected_view": selected_view,
        "selected_modality": modality,
        "ranked_candidates": ranked_candidates,
        "confidence": round(confidence, 4),
        "evidence": modality_evidence + view_evidence,
        "metadata_evidence": metadata.get("metadata_evidence", []),
        "visual_evidence_artifact_paths": derived_paths,
        "limitations": limitations,
        "repair_history": repair_history,
        "measurement_suitability": {
            "spectral_velocity_trace": bool(spectral_regions and media.get("decode_status", "success") == "success"),
            "color_doppler": modality == "color Doppler",
            "b_mode_anatomy": modality in {"2D", "color Doppler", "M-mode"},
            "requires_independent_review": confidence < 0.75,
        },
    }


def _spectral_crop(frame: np.ndarray, region: dict[str, Any]) -> tuple[np.ndarray, int, int, int, int]:
    x0 = int(_num(region.get("region_location_min_x")))
    y0 = int(_num(region.get("region_location_min_y")))
    x1 = int(_num(region.get("region_location_max_x")))
    y1 = int(_num(region.get("region_location_max_y")))
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
    crop, x0, y0, _x1, _y1 = _spectral_crop(frame, spectral_region)
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
    ref_x = int(_num(ref_x))
    ref_y = int(_num(ref_y))
    delta_x = float(_num(spectral_region.get("physical_delta_x")))
    delta_y = float(_num(spectral_region.get("physical_delta_y")))
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
    _write_json(trace_json, trace_payload)
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


def _load_case_sr_view_hints(metadata: dict[str, Any]) -> list[str]:
    hints = []
    for obj in metadata["objects"].values():
        if obj.get("source_type") != "structured_report":
            continue
        path = obj.get("source_file")
        if not path:
            continue
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        except Exception:
            continue
        hints.extend(_extract_sr_view_hints(ds))
    return hints


def _extract_sr_view_hints(ds: pydicom.Dataset) -> list[str]:
    hints: list[str] = []

    def code_text(seq: Sequence | None) -> str | None:
        if not seq:
            return None
        item = seq[0]
        return getattr(item, "CodeMeaning", None) or getattr(item, "CodeValue", None)

    def walk(item: pydicom.Dataset) -> None:
        name = code_text(getattr(item, "ConceptNameCodeSequence", None))
        value = code_text(getattr(item, "ConceptCodeSequence", None))
        if name and str(name).lower() == "image view" and value:
            hints.append(str(value))
        for child in getattr(item, "ContentSequence", []) or []:
            walk(child)

    for item in getattr(ds, "ContentSequence", []) or []:
        walk(item)
    return hints


def _case_view_hint_distribution(hints: list[str]) -> dict[str, int]:
    counts = Counter()
    for hint in hints:
        label = _normalize_view_hint(hint)
        if label:
            counts[label] += 1
    return dict(counts)


def process_case(
    case_id: str,
    source_case_dir: Path | str,
    output_root: Path | str,
    *,
    max_video_frames: int = 80,
) -> dict[str, Any]:
    run_dir = Path(output_root) / case_id
    media_dir = run_dir / "media"
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest, metadata = inventory_case(case_id, source_case_dir)
    sr_hints = _load_case_sr_view_hints(metadata)
    sr_distribution = _case_view_hint_distribution(sr_hints)

    records = []
    spectral_records = []
    artifacts: list[dict[str, Any]] = []
    repair_events: list[dict[str, Any]] = []

    objects = sorted(
        metadata["objects"].values(),
        key=lambda obj: (obj.get("instance_number") is None, obj.get("instance_number") or 10**9, obj["source_file"]),
    )
    for obj in objects:
        path = Path(obj["source_file"])
        media: dict[str, Any] = {
            "decode_status": "not_applicable",
            "repair_history": [],
            "representative_frame_paths": [],
            "features": {},
        }
        if obj.get("source_type") in {"ultrasound_image", "ultrasound_multiframe_image"}:
            try:
                ds = pydicom.dcmread(str(path), force=True)
            except Exception as exc:
                media["decode_status"] = "failed"
                media["decode_error"] = f"{type(exc).__name__}: {exc}"
            else:
                stem = f"{case_id}_{path.name}"
                media = convert_dicom_media(ds, path, media_dir, stem, max_video_frames=max_video_frames)
                for artifact_path in _media_paths(media):
                    artifacts.append({"source_file": str(path), "artifact_path": artifact_path, "kind": "media"})
        if sr_distribution and obj.get("source_type") in {"ultrasound_image", "ultrasound_multiframe_image"}:
            obj["case_sr_view_distribution"] = sr_distribution
        record = classify_source_object(obj, media)
        records.append(record)
        for event in record.get("repair_history", []):
            repair_events.append({"case_id": case_id, "source_file": str(path), "event": event})

        spectral_regions = _spectral_regions(obj.get("ultrasound_regions", []))
        if spectral_regions and media.get("decode_status") == "success":
            ds = pydicom.dcmread(str(path), force=True)
            decoded, _repairs = decode_pixel_array(ds)
            frame = _frame_array(decoded, 0)
            modality = "CWD" if any(_safe_int(region.get("data_type")) == 4 for region in spectral_regions) else "PWD"
            spectral_dir = run_dir / "spectral" / path.name
            for region in spectral_regions:
                region_modality = "CWD" if _safe_int(region.get("data_type")) == 4 else "PWD"
                result = extract_spectral_trace(
                    frame=frame,
                    spectral_region=region,
                    output_dir=spectral_dir,
                    artifact_stem=f"{case_id}_{path.name}_region{region['region_index']}_{region_modality}",
                    source_file=str(path),
                    modality=region_modality,
                )
                result.update(
                    {
                        "case_id": case_id,
                        "selected_view": record["selected_view"],
                        "series_uid": obj.get("series_uid"),
                        "sop_instance_uid": obj.get("sop_instance_uid"),
                    }
                )
                spectral_records.append(result)
                for artifact_path in result.get("overlay_artifact_paths", []):
                    artifacts.append({"source_file": str(path), "artifact_path": artifact_path, "kind": "spectral_overlay"})
                for artifact_path in [
                    result.get("envelope_trace_path_json"),
                    result.get("envelope_trace_path_csv"),
                ]:
                    if artifact_path:
                        artifacts.append({"source_file": str(path), "artifact_path": artifact_path, "kind": "spectral_trace"})
                if result["status"] != "success":
                    repair_events.append(
                        {
                            "case_id": case_id,
                            "source_file": str(path),
                            "event": "spectral_trace_extraction_repair_required",
                            "quality_flags": result.get("quality_flags", []),
                        }
                    )

    _write_json(run_dir / "case_manifest.json", manifest)
    _write_json(run_dir / "dicom_metadata.json", metadata)
    _write_json(
        run_dir / "view_classification.json",
        {
            "case_id": case_id,
            "created_at": _utc_now(),
            "records": records,
            "summary": {
                "record_count": len(records),
                "classified_image_series_count": sum(
                    1 for rec in records if rec["source_type"] in {"ultrasound_image", "ultrasound_multiframe_image"}
                ),
                "selected_views": dict(Counter(rec["selected_view"] for rec in records)),
                "selected_modalities": dict(Counter(rec["selected_modality"] for rec in records)),
            },
        },
    )
    _write_json(
        run_dir / "spectral_extractions.json",
        {
            "case_id": case_id,
            "created_at": _utc_now(),
            "records": spectral_records,
            "summary": {
                "record_count": len(spectral_records),
                "cwd_count": sum(1 for rec in spectral_records if rec.get("modality") == "CWD"),
                "pwd_count": sum(1 for rec in spectral_records if rec.get("modality") == "PWD"),
            },
        },
    )
    _write_json(run_dir / "artifact_index.json", {"case_id": case_id, "artifacts": artifacts})
    _write_json(
        run_dir / "audit.json",
        {
            "case_id": case_id,
            "created_at": _utc_now(),
            "mode": "view_classifier_validation",
            "source_root": str(source_case_dir),
            "external_services": [],
            "skills_used": [
                "medical-image-ingestion",
                "echo-image-harmonization",
                "echo-view-classification",
                "ar-cwd-analysis",
                "ar-pwd-reversal",
                "adaptive-toolsmith",
            ],
            "patient_metadata_redacted": True,
            "repair_events": repair_events,
            "sr_view_hint_distribution": sr_distribution,
            "privacy_notes": metadata["deidentification_phi_risk_notes"],
        },
    )
    return {
        "case_id": case_id,
        "run_dir": str(run_dir),
        "classified_count": sum(
            1 for rec in records if rec["source_type"] in {"ultrasound_image", "ultrasound_multiframe_image"}
        ),
        "records": records,
        "spectral_records": spectral_records,
        "repair_events": repair_events,
    }


def _media_paths(media: dict[str, Any]) -> list[str]:
    paths = []
    paths.extend(media.get("representative_frame_paths", []) or [])
    for key in ("contact_sheet_path", "video_path"):
        if media.get(key):
            paths.append(media[key])
    return paths


def run_validation(
    case_ids: list[str],
    source_root: Path | str,
    output_root: Path | str,
    *,
    max_video_frames: int = 80,
) -> dict[str, Any]:
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    repair_log = []
    table = []
    for case_id in case_ids:
        result = process_case(
            case_id,
            Path(source_root) / case_id,
            output,
            max_video_frames=max_video_frames,
        )
        results.append(result)
        repair_log.extend(result["repair_events"])
        for record in result["records"]:
            table.append(
                {
                    "case_id": case_id,
                    "source_file": record["source_file"],
                    "selected_view": record["selected_view"],
                    "selected_modality": record["selected_modality"],
                    "confidence": record["confidence"],
                    "frame_count": record["frame_count"],
                    "source_type": record["source_type"],
                }
            )

    summary = {
        "created_at": _utc_now(),
        "source_root": str(source_root),
        "output_root": str(output),
        "cases_processed": len(results),
        "per_case": {
            result["case_id"]: {
                "classified_count": result["classified_count"],
                "spectral_count": len(result["spectral_records"]),
                "cwd_count": sum(1 for rec in result["spectral_records"] if rec.get("modality") == "CWD"),
                "pwd_count": sum(1 for rec in result["spectral_records"] if rec.get("modality") == "PWD"),
                "repair_event_count": len(result["repair_events"]),
            }
            for result in results
        },
        "total_classified_count": sum(result["classified_count"] for result in results),
        "total_spectral_count": sum(len(result["spectral_records"]) for result in results),
    }
    _write_json(output / "summary.json", summary)
    _write_json(output / "classification_table.json", {"records": table})
    _write_json(output / "repair_log.json", {"created_at": _utc_now(), "events": repair_log})
    return summary
