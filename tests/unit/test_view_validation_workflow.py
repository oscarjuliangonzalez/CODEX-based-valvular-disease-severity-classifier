from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from ar_core.agentic_view_classifier import build_agent_task, build_evidence_packet, validate_agent_view_record
from ar_core.dicom_media import convert_dicom_media, extract_ultrasound_regions, inventory_case
from ar_core.guideline_summary import build_guideline_summaries
from ar_core.spectral import extract_spectral_trace


def _region(
    *,
    x0: int = 0,
    y0: int = 0,
    x1: int = 63,
    y1: int = 63,
    spatial_format: int = 1,
    data_type: int = 1,
    units_x: int = 3,
    units_y: int = 3,
    delta_x: float = 0.05,
    delta_y: float = 0.05,
    ref_x: int | None = None,
    ref_y: int | None = None,
) -> Dataset:
    item = Dataset()
    item.RegionSpatialFormat = spatial_format
    item.RegionDataType = data_type
    item.RegionFlags = 2
    item.RegionLocationMinX0 = x0
    item.RegionLocationMinY0 = y0
    item.RegionLocationMaxX1 = x1
    item.RegionLocationMaxY1 = y1
    item.PhysicalUnitsXDirection = units_x
    item.PhysicalUnitsYDirection = units_y
    item.PhysicalDeltaX = delta_x
    item.PhysicalDeltaY = delta_y
    if ref_x is not None:
        item.ReferencePixelX0 = ref_x
    if ref_y is not None:
        item.ReferencePixelY0 = ref_y
    return item


def _write_dicom(path: Path, pixels: np.ndarray, regions: list[Dataset]) -> Path:
    frames = pixels.shape[0] if pixels.ndim == 4 else 1
    rows = pixels.shape[-3] if pixels.ndim == 4 else pixels.shape[0]
    cols = pixels.shape[-2] if pixels.ndim == 4 else pixels.shape[1]
    samples = pixels.shape[-1] if pixels.ndim in {3, 4} else 1

    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.MediaStorageSOPClassUID = (
        "1.2.840.10008.5.1.4.1.1.3.1" if frames > 1 else "1.2.840.10008.5.1.4.1.1.6.1"
    )
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.ImplementationClassUID = generate_uid()

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "US"
    ds.Manufacturer = "Synthetic"
    ds.SeriesDescription = "ECHOCARDIOGRAM 2D COMPLETE"
    ds.ProtocolName = "Unit Test"
    ds.PatientName = "REDACTED^TEST"
    ds.PatientID = "UNITTEST"
    ds.Rows = rows
    ds.Columns = cols
    ds.SamplesPerPixel = samples
    ds.PhotometricInterpretation = "RGB" if samples == 3 else "MONOCHROME2"
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    if samples == 3:
        ds.PlanarConfiguration = 0
    if frames > 1:
        ds.NumberOfFrames = str(frames)
        ds.FrameTime = "25"
    ds.SequenceOfUltrasoundRegions = Sequence(regions)
    ds.PixelData = pixels.astype(np.uint8).tobytes()
    ds.save_as(path, write_like_original=False)
    return path


def test_inventory_extracts_dicom_metadata_without_phi_values(tmp_path: Path) -> None:
    pixels = np.zeros((2, 32, 32, 3), dtype=np.uint8)
    dicom_path = _write_dicom(tmp_path / "KX000001", pixels, [_region(x1=31, y1=31)])
    (tmp_path / ".DS_Store").write_bytes(b"local desktop metadata")
    (tmp_path / "notes.txt").write_text("non-dicom sidecar")

    manifest, metadata = inventory_case("T1", tmp_path)

    assert manifest["case_id"] == "T1"
    assert len(manifest["input_files"]) == 3
    dicom_meta = metadata["objects"][str(dicom_path)]
    assert dicom_meta["modality"] == "US"
    assert dicom_meta["frame_count"] == 2
    assert dicom_meta["redacted_fields"] == ["PatientID", "PatientName"]
    assert "REDACTED^TEST" not in json.dumps(metadata)
    assert dicom_meta["ultrasound_regions"][0]["physical_units_x"] == "cm"


def test_media_conversion_writes_representative_frames_and_mapping(tmp_path: Path) -> None:
    pixels = np.zeros((3, 40, 50, 3), dtype=np.uint8)
    pixels[:, 10:30, 20:35, :] = 220
    dicom_path = _write_dicom(tmp_path / "KX000002", pixels, [_region(x1=49, y1=39)])
    ds = pydicom.dcmread(dicom_path, force=True)

    media = convert_dicom_media(ds, dicom_path, tmp_path / "media", "T1_KX000002")

    assert media["decode_status"] == "success"
    assert len(media["representative_frame_paths"]) == 3
    assert Path(media["representative_frame_paths"][1]).exists()
    assert media["frame_map"][1]["source_frame_index"] == 1
    assert Path(media["contact_sheet_path"]).exists()
    assert Path(media["video_path"]).exists()


def test_agentic_evidence_packet_and_agent_record_contract(tmp_path: Path) -> None:
    metadata = {
        "case_id": "T1",
        "source_file": "/case/KX000003",
        "source_type": "dicom",
        "series_uid": "series",
        "sop_instance_uid": "sop",
        "frame_count": 1,
        "instance_number": 3,
        "ultrasound_regions": [
            _region(
                spatial_format=3,
                data_type=4,
                units_x=4,
                units_y=7,
                delta_x=0.003,
                delta_y=-1.5,
                ref_x=100,
                ref_y=80,
            )
        ],
    }

    summaries = build_guideline_summaries(Path("guidelines"), tmp_path / "summaries")
    packet = build_evidence_packet(
        metadata,
        {
            "decode_status": "success",
            "representative_frame_paths": ["frame.png"],
            "features": {"primary_region_aspect_ratio": 1.0, "bright_pixel_roundness": 0.4},
        },
        summaries,
    )
    task = build_agent_task(packet, skill_path=Path(".agents/skills/echo-view-classification/SKILL.md"))
    record = {
        "case_id": "T1",
        "source_file": "/case/KX000003",
        "source_type": "dicom",
        "series_uid": "series",
        "sop_instance_uid": "sop",
        "frame_count": 1,
        "derived_media_paths": ["frame.png"],
        "selected_view": "A3C",
        "selected_modality": "CWD",
        "zoom_status": "not_zoomed",
        "zoom_confidence": 0.71,
        "ranked_view_candidates": [{"view": "A3C", "confidence": 0.8, "evidence": ["agent visual review"]}],
        "ranked_modality_candidates": [{"modality": "CWD", "confidence": 0.9, "evidence": ["agent reviewed spectral layout"]}],
        "ranked_zoom_candidates": [{"zoom_status": "not_zoomed", "confidence": 0.71, "evidence": ["agent reviewed full field"]}],
        "confidence": 0.79,
        "guideline_evidence": {"summary_files": packet["guideline_summary_files"], "evidence": ["guideline summary used"]},
        "metadata_evidence": [],
        "visual_observations": {"modality_layout": "spectral Doppler panel", "zoom_indicators": ["full field"]},
        "visual_evidence_artifact_paths": ["frame.png"],
        "agent_reasoning_summary": "Agent inspected rendered evidence and selected A3C CWD.",
        "measurement_suitability": {"spectral_velocity_trace": True},
        "limitations": [],
        "repair_history": [],
    }

    assert "selected_view" not in packet
    assert "Inspect the rendered media" in task["prompt"]
    validate_agent_view_record(record, packet)


def test_spectral_trace_extraction_writes_calibrated_json_csv_and_overlay(tmp_path: Path) -> None:
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    for x in range(10, 110):
        y = 50 - (x - 10) // 5
        frame[max(0, y - 1) : y + 2, x, :] = 255
    region = {
        "region_index": 0,
        "data_type": 4,
        "region_location_min_x": 0,
        "region_location_min_y": 0,
        "region_location_max_x": 119,
        "region_location_max_y": 79,
        "reference_pixel_x": 10,
        "reference_pixel_y": 50,
        "physical_units_x": "seconds",
        "physical_units_y": "cm_per_second",
        "physical_delta_x": 0.01,
        "physical_delta_y": -2.0,
    }

    result = extract_spectral_trace(
        frame=frame,
        spectral_region=region,
        output_dir=tmp_path,
        artifact_stem="synthetic_cwd",
        source_file="/case/KX000004",
        modality="CWD",
    )

    assert result["status"] == "success"
    assert result["baseline_px"] == 50
    assert Path(result["envelope_trace_path_json"]).exists()
    assert Path(result["envelope_trace_path_csv"]).exists()
    assert Path(result["overlay_artifact_paths"][0]).exists()
    assert result["velocity_time_points"][0]["velocity_cm_s"] >= 0
    assert result["calibration_provenance"]["velocity_axis"]["unit"] == "cm/s"
