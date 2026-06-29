"""Local DICOM inventory and media-rendering utilities.

These utilities are deterministic by design, but they do not assign echo view
labels. They provide safe metadata, local rendered evidence, and pixel/layout
features for the agentic view-classification workflow.
"""

from __future__ import annotations

import json
import math
from collections import Counter
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


US_IMAGE_STORAGE = {
    "1.2.840.10008.5.1.4.1.1.6.1": "ultrasound_image",
    "1.2.840.10008.5.1.4.1.1.3.1": "ultrasound_multiframe_image",
}

USABLE_IMAGE_SOURCE_TYPES = {"ultrasound_image", "ultrasound_multiframe_image"}

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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return f"<{len(value)} bytes redacted>"
    if isinstance(value, (list, tuple, MultiValue)):
        return [jsonable(v) for v in value]
    if hasattr(value, "keyword"):
        return str(value)
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def num(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def dicom_source_type(ds: pydicom.Dataset) -> str:
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


def redacted_fields(ds: pydicom.Dataset) -> list[str]:
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
            "spatial_format": jsonable(getattr(item, "RegionSpatialFormat", None)),
            "data_type": jsonable(getattr(item, "RegionDataType", None)),
            "region_flags": jsonable(getattr(item, "RegionFlags", None)),
            "region_location_min_x": jsonable(getattr(item, "RegionLocationMinX0", None)),
            "region_location_min_y": jsonable(getattr(item, "RegionLocationMinY0", None)),
            "region_location_max_x": jsonable(getattr(item, "RegionLocationMaxX1", None)),
            "region_location_max_y": jsonable(getattr(item, "RegionLocationMaxY1", None)),
            "reference_pixel_x": jsonable(getattr(item, "ReferencePixelX0", None)),
            "reference_pixel_y": jsonable(getattr(item, "ReferencePixelY0", None)),
            "physical_units_x": PHYSICAL_UNITS.get(units_x_code, f"code_{units_x_code}"),
            "physical_units_y": PHYSICAL_UNITS.get(units_y_code, f"code_{units_y_code}"),
            "physical_delta_x": jsonable(getattr(item, "PhysicalDeltaX", None)),
            "physical_delta_y": jsonable(getattr(item, "PhysicalDeltaY", None)),
        }
        regions.append(region)
    return regions


def coerce_ultrasound_region(region: Any) -> dict[str, Any]:
    if isinstance(region, dict):
        return region
    units_x_code = getattr(region, "PhysicalUnitsXDirection", None)
    units_y_code = getattr(region, "PhysicalUnitsYDirection", None)
    return {
        "region_index": safe_int(getattr(region, "RegionIndex", None)) or 0,
        "spatial_format": jsonable(getattr(region, "RegionSpatialFormat", None)),
        "data_type": jsonable(getattr(region, "RegionDataType", None)),
        "region_flags": jsonable(getattr(region, "RegionFlags", None)),
        "region_location_min_x": jsonable(getattr(region, "RegionLocationMinX0", None)),
        "region_location_min_y": jsonable(getattr(region, "RegionLocationMinY0", None)),
        "region_location_max_x": jsonable(getattr(region, "RegionLocationMaxX1", None)),
        "region_location_max_y": jsonable(getattr(region, "RegionLocationMaxY1", None)),
        "reference_pixel_x": jsonable(getattr(region, "ReferencePixelX0", None)),
        "reference_pixel_y": jsonable(getattr(region, "ReferencePixelY0", None)),
        "physical_units_x": PHYSICAL_UNITS.get(units_x_code, f"code_{units_x_code}"),
        "physical_units_y": PHYSICAL_UNITS.get(units_y_code, f"code_{units_y_code}"),
        "physical_delta_x": jsonable(getattr(region, "PhysicalDeltaX", None)),
        "physical_delta_y": jsonable(getattr(region, "PhysicalDeltaY", None)),
    }


def safe_dicom_metadata(case_id: str, path: Path, ds: pydicom.Dataset) -> dict[str, Any]:
    safe = {
        "case_id": case_id,
        "source_file": str(path),
        "source_type": dicom_source_type(ds),
        "modality": jsonable(getattr(ds, "Modality", None)),
        "series_uid": jsonable(getattr(ds, "SeriesInstanceUID", None)),
        "sop_instance_uid": jsonable(getattr(ds, "SOPInstanceUID", None)),
        "sop_class_uid": jsonable(getattr(ds, "SOPClassUID", None)),
        "frame_count": int(getattr(ds, "NumberOfFrames", 1) or 1),
        "rows": jsonable(getattr(ds, "Rows", None)),
        "columns": jsonable(getattr(ds, "Columns", None)),
        "instance_number": safe_int(getattr(ds, "InstanceNumber", None)),
        "transfer_syntax_uid": jsonable(getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)),
        "redacted_fields": redacted_fields(ds),
        "ultrasound_regions": extract_ultrasound_regions(ds),
        "safe_tags": {},
        "private_tag_hints": [],
        "metadata_evidence": [],
    }
    for keyword in SAFE_METADATA_KEYWORDS:
        if keyword in ds and keyword not in PHI_KEYWORDS:
            safe["safe_tags"][keyword] = jsonable(getattr(ds, keyword, None))
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
            file_record["source_type"] = non_dicom_type(path)
            input_files.append(file_record)
            continue

        if getattr(ds, "SOPClassUID", None):
            source_type = dicom_source_type(ds)
            file_record["source_type"] = source_type
            file_record["dicom"] = True
            file_record["sop_instance_uid"] = jsonable(getattr(ds, "SOPInstanceUID", None))
            file_record["series_uid"] = jsonable(getattr(ds, "SeriesInstanceUID", None))
            meta = safe_dicom_metadata(case_id, path, ds)
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
        "created_at": utc_now(),
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
                if is_spectral_region(region)
            ),
        },
        "missing_information": [],
        "file_hashes": {},
    }
    metadata = {
        "case_id": case_id,
        "created_at": utc_now(),
        "objects": metadata_objects,
        "deidentification_phi_risk_notes": [
            "DICOM PHI tag names are recorded when present, but tag values are redacted.",
            "Private tag values are not serialized; only tag, VR, and byte/string length hints are retained.",
            "Original source paths are preserved as requested for provenance.",
        ],
    }
    return manifest, metadata


def non_dicom_type(path: Path) -> str:
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


def frame_array(decoded: np.ndarray, frame_index: int = 0) -> np.ndarray:
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


def frame_count_from_decoded(decoded: np.ndarray) -> int:
    if decoded.ndim == 4:
        return int(decoded.shape[0])
    if decoded.ndim == 3 and decoded.shape[-1] not in {3, 4}:
        return int(decoded.shape[0])
    return 1


def representative_indices(frame_count: int, max_representative_frames: int = 3) -> list[int]:
    if frame_count <= 1:
        return [0]
    if max_representative_frames <= 1:
        return [frame_count // 2]
    indices = np.linspace(0, frame_count - 1, min(frame_count, max_representative_frames)).astype(int)
    return sorted(set(int(i) for i in indices))


def resize_for_video(frame: np.ndarray, max_width: int = 512) -> np.ndarray:
    if frame.shape[1] <= max_width:
        return frame
    scale = max_width / frame.shape[1]
    return cv2.resize(frame, (max_width, max(1, int(frame.shape[0] * scale))), interpolation=cv2.INTER_AREA)


def save_png(path: Path, frame: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame).save(path)


def make_contact_sheet(frames: list[tuple[int, np.ndarray]], path: Path) -> None:
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


def media_features(frame: np.ndarray, regions: list[dict[str, Any]]) -> dict[str, Any]:
    rgb = frame.astype(np.float32)
    maxc = rgb.max(axis=2)
    minc = rgb.min(axis=2)
    saturation = np.divide(maxc - minc, maxc + 1e-6)
    color_fraction = float(np.mean((saturation > 0.28) & (maxc > 55)))
    gray = np.mean(rgb, axis=2)
    bright_threshold = max(35.0, float(np.percentile(gray, 85)))
    mask = gray > bright_threshold
    ys, xs = np.nonzero(mask)
    orientation = None
    roundness = None
    bbox_fraction = None
    center_x_fraction = None
    center_y_fraction = None
    if len(xs) > 20:
        coords = np.column_stack([xs, ys]).astype(np.float32)
        center_x_fraction = float(xs.mean() / max(frame.shape[1] - 1, 1))
        center_y_fraction = float(ys.mean() / max(frame.shape[0] - 1, 1))
        bbox_area = (xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)
        bbox_fraction = float(bbox_area / max(frame.shape[0] * frame.shape[1], 1))
        coords -= coords.mean(axis=0, keepdims=True)
        cov = np.cov(coords.T)
        vals, vecs = np.linalg.eigh(cov)
        order = np.argsort(vals)[::-1]
        vals = vals[order]
        vec = vecs[:, order[0]]
        orientation = float(math.degrees(math.atan2(vec[1], vec[0])))
        roundness = float(vals[-1] / (vals[0] + 1e-6))
    first_region = regions[0] if regions else {}
    region_width = num(first_region.get("region_location_max_x")) - num(first_region.get("region_location_min_x"))
    region_height = num(first_region.get("region_location_max_y")) - num(first_region.get("region_location_min_y"))
    aspect = float(region_width / region_height) if region_width and region_height else None
    frame_area = max(frame.shape[0] * frame.shape[1], 1)
    region_area_fraction = float((region_width * region_height) / frame_area) if region_width and region_height else None
    return {
        "color_fraction": round(color_fraction, 5),
        "has_color_doppler_pixels": color_fraction > 0.015,
        "bright_pixel_orientation_degrees": orientation,
        "bright_pixel_roundness": roundness,
        "bright_pixel_bbox_fraction": bbox_fraction,
        "bright_pixel_center_x_fraction": center_x_fraction,
        "bright_pixel_center_y_fraction": center_y_fraction,
        "primary_region_aspect_ratio": aspect,
        "primary_region_area_fraction": region_area_fraction,
        "frame_width": int(frame.shape[1]),
        "frame_height": int(frame.shape[0]),
    }


def frame_rate(ds: pydicom.Dataset) -> float:
    rate = num(getattr(ds, "RecommendedDisplayFrameRate", None))
    if rate > 0:
        return max(1.0, min(rate, 60.0))
    frame_time_ms = num(getattr(ds, "FrameTime", None))
    if frame_time_ms > 0:
        return max(1.0, min(1000.0 / frame_time_ms, 60.0))
    return 20.0


def convert_dicom_media(
    ds: pydicom.Dataset,
    source_path: Path | str,
    output_dir: Path | str,
    artifact_stem: str,
    *,
    max_video_frames: int = 80,
    max_representative_frames: int = 3,
    reuse_existing: bool = False,
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

    frame_count = frame_count_from_decoded(decoded)
    result["decode_status"] = "success"
    result["repair_history"].extend(repair_history)
    regions = extract_ultrasound_regions(ds)
    rep_frames: list[tuple[int, np.ndarray]] = []
    for frame_index in representative_indices(frame_count, max_representative_frames):
        frame = frame_array(decoded, frame_index)
        frame_path = output_path / f"frame_{frame_index:04d}.png"
        if not (reuse_existing and frame_path.exists()):
            save_png(frame_path, frame)
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
        if not (reuse_existing and sheet_path.exists()):
            make_contact_sheet(rep_frames, sheet_path)
        result["contact_sheet_path"] = str(sheet_path)
        result["features"] = media_features(rep_frames[len(rep_frames) // 2][1], regions)

    if frame_count > 1:
        video_path = output_path / "cine_preview.mp4"
        sample_indices = np.linspace(0, frame_count - 1, min(frame_count, max_video_frames)).astype(int)
        first = resize_for_video(frame_array(decoded, int(sample_indices[0])))
        if reuse_existing and video_path.exists():
            result["video_path"] = str(video_path)
        else:
            writer = cv2.VideoWriter(
                str(video_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                frame_rate(ds),
                (first.shape[1], first.shape[0]),
            )
            if writer.isOpened():
                for output_index, source_index in enumerate(sample_indices):
                    frame = resize_for_video(frame_array(decoded, int(source_index)))
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


def media_paths(media: dict[str, Any]) -> list[str]:
    paths = []
    paths.extend(media.get("representative_frame_paths", []) or [])
    for key in ("contact_sheet_path", "video_path"):
        if media.get(key):
            paths.append(media[key])
    return paths


def is_spectral_region(region: dict[str, Any]) -> bool:
    return (
        region.get("physical_units_x") == "seconds"
        and region.get("physical_units_y") == "cm_per_second"
        and safe_int(region.get("data_type")) in {3, 4}
    )


def spectral_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [region for region in regions if is_spectral_region(region)]


def m_mode_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        region
        for region in regions
        if region.get("physical_units_x") == "seconds"
        and region.get("physical_units_y") == "cm"
        and safe_int(region.get("data_type")) == 1
    ]
