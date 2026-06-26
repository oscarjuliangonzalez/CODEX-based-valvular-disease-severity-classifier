from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from ar_core.timing_validation import (
    build_frame_selection_instructions,
    classify_timing_for_record,
    detect_ecg_intervals,
    extract_ecg_trace,
    extract_timing_metadata,
    ensure_view_classification_outputs,
)


def _region(
    *,
    x0: int = 0,
    y0: int = 0,
    x1: int = 299,
    y1: int = 99,
    units_x: int = 3,
    units_y: int = 3,
    delta_x: float = 0.05,
    delta_y: float = 0.05,
) -> Dataset:
    item = Dataset()
    item.RegionSpatialFormat = 1
    item.RegionDataType = 1
    item.RegionFlags = 2
    item.RegionLocationMinX0 = x0
    item.RegionLocationMinY0 = y0
    item.RegionLocationMaxX1 = x1
    item.RegionLocationMaxY1 = y1
    item.PhysicalUnitsXDirection = units_x
    item.PhysicalUnitsYDirection = units_y
    item.PhysicalDeltaX = delta_x
    item.PhysicalDeltaY = delta_y
    return item


def _ecg_frame(width: int = 300, height: int = 140) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    baseline = height - 28
    for x in range(12, width - 12):
        y = baseline + int(3 * np.sin(x / 13.0))
        for peak_x in (55, 150, 245):
            distance = abs(x - peak_x)
            if distance <= 3:
                y = baseline - 28 + distance * 7
            elif 4 <= distance <= 9:
                y = baseline + 10 - (distance - 4)
        frame[max(0, y - 1) : min(height, y + 2), x, 1] = 235
    return frame


def _write_dicom(path: Path, pixels: np.ndarray, *, frame_time_ms: float = 25.0, heart_rate: int = 60) -> Path:
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
    ds.Rows = rows
    ds.Columns = cols
    ds.SamplesPerPixel = samples
    ds.PhotometricInterpretation = "RGB" if samples == 3 else "MONOCHROME2"
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.HeartRate = str(heart_rate)
    ds.ContentTime = "120000"
    if samples == 3:
        ds.PlanarConfiguration = 0
    if frames > 1:
        ds.NumberOfFrames = str(frames)
        ds.FrameTime = str(frame_time_ms)
        ds.CineRate = str(round(1000.0 / frame_time_ms))
        ds.RecommendedDisplayFrameRate = str(round(1000.0 / frame_time_ms))
    ds.SequenceOfUltrasoundRegions = Sequence([_region(x1=cols - 1, y1=rows - 1)])
    ds.PixelData = pixels.astype(np.uint8).tobytes()
    ds.save_as(path, write_like_original=False)
    return path


def test_timing_metadata_extracts_frame_timing_and_safe_identifiers(tmp_path: Path) -> None:
    pixels = np.stack([_ecg_frame() for _ in range(5)], axis=0)
    dicom_path = _write_dicom(tmp_path / "KX000001", pixels, frame_time_ms=20.0, heart_rate=75)
    ds = pydicom.dcmread(dicom_path, stop_before_pixels=True, force=True)

    metadata = extract_timing_metadata("T1", dicom_path, ds)

    assert metadata["case_id"] == "T1"
    assert metadata["frame_count"] == 5
    assert metadata["frame_time_ms"] == 20.0
    assert metadata["frame_rate_hz"] == 50.0
    assert metadata["heart_rate_bpm"] == 75
    assert metadata["series_uid"]
    assert metadata["sop_instance_uid"]
    assert metadata["frame_time_evidence"][0]["source"] == "DICOM FrameTime"


def test_view_dependency_reuses_complete_per_case_outputs(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    view_root = tmp_path / "view"
    source_case = source_root / "A1"
    run_case = view_root / "A1"
    source_case.mkdir(parents=True)
    run_case.mkdir(parents=True)
    source_file = source_case / "KX000001"
    source_file.write_bytes(b"placeholder")
    payload = {
        "case_id": "A1",
        "records": [
            {
                "case_id": "A1",
                "source_file": str(source_file),
                "source_type": "ultrasound_multiframe_image",
                "selected_view": "PLAX",
                "selected_modality": "2D",
                "frame_count": 5,
                "derived_media_paths": [],
            }
        ],
        "summary": {"classified_image_series_count": 1},
    }
    for name in ["case_manifest.json", "dicom_metadata.json", "artifact_index.json", "audit.json"]:
        (run_case / name).write_text(json.dumps({"case_id": "A1"}) + "\n")
    (run_case / "view_classification.json").write_text(json.dumps(payload) + "\n")

    status = ensure_view_classification_outputs(["A1"], source_root, view_root)

    assert status["regenerated_cases"] == []
    assert status["reused_cases"] == ["A1"]
    assert status["case_details"]["A1"]["record_count"] == 1


def test_ecg_extraction_writes_region_signal_and_overlay_artifacts(tmp_path: Path) -> None:
    result = extract_ecg_trace(
        frame=_ecg_frame(),
        output_dir=tmp_path,
        artifact_stem="synthetic",
        source_file="/case/KX000001",
    )

    assert result["status"] == "success"
    assert result["ecg_trace_location"]["region_name"] == "lower_overlay"
    assert result["ecg_trace_location"]["x_max"] - result["ecg_trace_location"]["x_min"] > 200
    assert Path(result["ecg_signal_path_json"]).exists()
    assert Path(result["ecg_signal_path_csv"]).exists()
    assert all(Path(path).exists() for path in result["ecg_trace_artifact_paths"])
    signal = json.loads(Path(result["ecg_signal_path_json"]).read_text())
    assert signal["samples"]


def test_pr_qrs_qt_interval_contract_uses_frames_and_milliseconds(tmp_path: Path) -> None:
    extraction = extract_ecg_trace(
        frame=_ecg_frame(),
        output_dir=tmp_path,
        artifact_stem="synthetic",
        source_file="/case/KX000001",
    )
    signal = json.loads(Path(extraction["ecg_signal_path_json"]).read_text())

    intervals = detect_ecg_intervals(
        ecg_signal=signal,
        frame_count=80,
        frame_time_ms=25.0,
        heart_rate_bpm=60,
    )

    assert len(intervals["r_peaks"]) >= 2
    assert len(intervals["pr_intervals"]) == len(intervals["qrs_complexes"]) == len(intervals["qt_intervals"])
    assert intervals["pr_intervals"][0]["unit"] == "ms"
    assert "frame_start" in intervals["qrs_complexes"][0]
    assert intervals["cardiac_cycles"][0]["start_frame"] == 0
    assert intervals["cardiac_cycles"][0]["end_frame"] >= intervals["cardiac_cycles"][0]["start_frame"]


def test_timing_classification_record_and_frame_selection_contract(tmp_path: Path) -> None:
    pixels = np.stack([_ecg_frame() for _ in range(40)], axis=0)
    dicom_path = _write_dicom(tmp_path / "KX000001", pixels, frame_time_ms=25.0, heart_rate=60)
    ds = pydicom.dcmread(dicom_path, force=True)
    metadata = extract_timing_metadata("T1", dicom_path, ds)
    record = {
        "case_id": "T1",
        "source_file": str(dicom_path),
        "source_type": "ultrasound_multiframe_image",
        "selected_view": "PLAX",
        "selected_modality": "2D",
        "series_uid": metadata["series_uid"],
        "sop_instance_uid": metadata["sop_instance_uid"],
        "frame_count": 40,
        "derived_media_paths": [],
        "confidence": 0.8,
        "evidence": ["fixture view evidence"],
        "metadata_evidence": [],
        "visual_evidence_artifact_paths": [],
        "limitations": [],
        "repair_history": [],
    }

    timing = classify_timing_for_record(record, metadata, tmp_path / "timing")
    instructions = build_frame_selection_instructions("T1", [timing])

    assert timing["phase_label_status"] == "classified"
    assert len(timing["frame_phase_labels"]) == 40
    assert timing["frame_phase_labels"][0]["source_type"] == "ultrasound_multiframe_image"
    assert timing["selected_analysis_windows"]["early_diastole"]
    assert timing["selected_analysis_windows"]["late_systole"]
    assert timing["ecg_trace_location"]["region_name"] in {"lower_overlay", "upper_overlay", "full_frame"}
    assert timing["phase_qc_artifact_paths"]
    assert all(Path(path).exists() for path in timing["phase_qc_artifact_paths"])
    assert instructions["case_id"] == "T1"
    assert instructions["records"][0]["source_file"] == str(dicom_path)
    assert instructions["records"][0]["preferred_windows"]["early_diastole"]
    assert instructions["records"][0]["do_not_reinterpret_ecg"] is True


def test_cli_fixture_execution_writes_required_outputs(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    view_root = tmp_path / "view"
    output_root = tmp_path / "timing"
    case_dir = source_root / "A1" / "KINETDX"
    case_dir.mkdir(parents=True)
    pixels = np.stack([_ecg_frame() for _ in range(12)], axis=0)
    dicom_path = _write_dicom(case_dir / "KX000001", pixels, frame_time_ms=25.0, heart_rate=60)
    frame_path = tmp_path / "frame.png"
    from PIL import Image

    Image.fromarray(_ecg_frame()).save(frame_path)
    case_view_dir = view_root / "A1"
    case_view_dir.mkdir(parents=True)
    view_payload = {
        "case_id": "A1",
        "records": [
            {
                "case_id": "A1",
                "source_file": str(dicom_path),
                "source_type": "ultrasound_multiframe_image",
                "selected_view": "PLAX",
                "selected_modality": "2D",
                "series_uid": "series",
                "sop_instance_uid": "sop",
                "frame_count": 12,
                "derived_media_paths": [str(frame_path)],
                "confidence": 0.8,
                "evidence": ["fixture view evidence"],
                "metadata_evidence": [],
                "visual_evidence_artifact_paths": [str(frame_path)],
                "limitations": [],
                "repair_history": [],
            }
        ],
        "summary": {"classified_image_series_count": 1},
    }
    for name in ["case_manifest.json", "dicom_metadata.json", "artifact_index.json", "audit.json"]:
        (case_view_dir / name).write_text(json.dumps({"case_id": "A1"}) + "\n")
    (case_view_dir / "view_classification.json").write_text(json.dumps(view_payload) + "\n")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_timing_classifier_validation.py",
            "--source-root",
            str(source_root),
            "--view-output-root",
            str(view_root),
            "--output-root",
            str(output_root),
            "--cases",
            "A1",
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (output_root / "A1" / "timing_classification.json").exists()
    assert (output_root / "A1" / "frame_selection_instructions.json").exists()
    summary = json.loads((output_root / "summary.json").read_text())
    assert summary["per_case"]["A1"]["timed_source_count"] == 1
