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

from ar_core.agentic_view_classifier import (
    build_agent_task,
    build_evidence_packet,
    run_validation,
    validate_agent_view_record,
)
from ar_core.dicom_media import convert_dicom_media, extract_ultrasound_regions, inventory_case
from ar_core.guideline_summary import build_guideline_summaries
from ar_core.spectral import extract_spectral_trace


ROOT = Path(__file__).resolve().parents[2]


def _region(
    *,
    x0: int = 0,
    y0: int = 0,
    x1: int = 95,
    y1: int = 95,
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


def _echo_frame(width: int = 96, height: int = 96, *, color: bool = False) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    center = width // 2
    for y in range(8, height - 8):
        span = int((y / height) * width * 0.55)
        left = max(2, center - span // 2)
        right = min(width - 3, center + span // 2)
        frame[y, left:right, :] = 35
        frame[y, center - max(2, span // 5) : center - 2, :] = 150
        frame[y, center + 2 : center + max(2, span // 5), :] = 165
    if color:
        frame[44:55, 48:60, 0] = 240
        frame[52:64, 38:49, 2] = 240
    return frame


def _spectral_frame(width: int = 128, height: int = 96) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    baseline = 62
    frame[baseline : baseline + 1, 6 : width - 6, :] = 90
    for x in range(12, width - 12):
        y = baseline - 4 - (x - 12) // 7
        frame[max(0, y - 1) : min(height, y + 2), x, :] = 255
    return frame


def _write_dicom(path: Path, pixels: np.ndarray, regions: list[Dataset], *, instance: int = 1) -> Path:
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
    ds.ManufacturerModelName = "AgenticFixture"
    ds.SeriesDescription = "ECHOCARDIOGRAM 2D COMPLETE"
    ds.ProtocolName = "Unit Test"
    ds.PatientName = "REDACTED^TEST"
    ds.PatientID = "UNITTEST"
    ds.InstanceNumber = str(instance)
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


def _agent_record(packet: dict, *, source_file: str | None = None) -> dict:
    return {
        "case_id": packet["case_id"],
        "source_file": source_file or packet["source_file"],
        "source_type": packet["source_type"],
        "series_uid": packet["series_uid"],
        "sop_instance_uid": packet["sop_instance_uid"],
        "frame_count": packet["frame_count"],
        "derived_media_paths": packet["rendered_media"]["derived_media_paths"],
        "selected_view": "A4C",
        "selected_modality": "color Doppler",
        "zoom_status": "not_zoomed",
        "zoom_confidence": 0.74,
        "ranked_view_candidates": [
            {"view": "A4C", "confidence": 0.82, "evidence": ["Agent inspected contact sheet and noted four-chamber apical anatomy."]},
            {"view": "A2C", "confidence": 0.42, "evidence": ["Less consistent because right-sided chambers appear visible."]},
        ],
        "ranked_modality_candidates": [
            {"modality": "color Doppler", "confidence": 0.86, "evidence": ["Agent observed red/blue flow overlay on 2D anatomy."]},
            {"modality": "2D", "confidence": 0.32, "evidence": ["Underlying grayscale anatomy is present but color overlay dominates."]},
        ],
        "ranked_zoom_candidates": [
            {"zoom_status": "not_zoomed", "confidence": 0.74, "evidence": ["Surrounding chambers remain visible."]},
            {"zoom_status": "zoomed_in", "confidence": 0.31, "evidence": ["No strong crop-focused valve/root cue."]},
        ],
        "confidence": 0.8,
        "guideline_evidence": {
            "summary_files": packet["guideline_summary_files"],
            "source_index_path": packet["guideline_source_index_path"],
            "evidence": ["Agent used guideline summary cues for apical four-chamber and color Doppler layout."],
        },
        "metadata_evidence": packet["dicom_metadata_summary"]["metadata_evidence"],
        "visual_observations": {
            "visible_chambers": ["left ventricle", "right ventricle", "left atrium", "right atrium"],
            "valve_aortic_root_visibility": ["mitral valve plane visible"],
            "short_axis_versus_long_axis_geometry": "apical long-axis chamber view favored by agent review",
            "apical_versus_parasternal_orientation": "apical orientation favored by agent review",
            "modality_layout": "2D sector with color Doppler overlay",
            "color_flow_overlay_presence": True,
            "zoom_indicators": ["surrounding anatomy preserved"],
        },
        "visual_evidence_artifact_paths": packet["rendered_media"]["derived_media_paths"],
        "agent_reasoning_summary": "Agent-authored fixture: visual evidence supports A4C color Doppler and not_zoomed.",
        "measurement_suitability": {"color_doppler": True, "spectral_velocity_trace": False, "requires_independent_review": False},
        "limitations": [],
        "repair_history": [],
    }


def test_guideline_summary_generation_extracts_text_and_figure_index(tmp_path: Path) -> None:
    guidelines = tmp_path / "guidelines"
    guidelines.mkdir()
    (guidelines / "adult_tte_reference.txt").write_text(
        "Parasternal long-axis view shows left ventricle, aortic root, mitral valve, and left atrium.\n"
        "Apical four-chamber view shows both ventricles and both atria.\n"
        "Spectral Doppler displays velocity over time; color Doppler overlays red and blue flow.\n"
    )

    result = build_guideline_summaries(guidelines, tmp_path / "summaries")

    assert Path(result["summary_files"]["view_classification_guidelines"]).exists()
    assert Path(result["summary_files"]["view_modality_zoom_definitions"]).exists()
    assert Path(result["summary_files"]["guideline_figure_index"]).exists()
    assert result["source_count"] == 1
    assert result["sources"][0]["relevant_snippets"]


def test_dicom_inventory_metadata_and_media_conversion_contract(tmp_path: Path) -> None:
    pixels = np.stack([_echo_frame(color=True), _echo_frame(color=True)], axis=0)
    dicom_path = _write_dicom(tmp_path / "KX000001", pixels, [_region(x1=95, y1=95)])

    manifest, metadata = inventory_case("T1", tmp_path)
    ds = pydicom.dcmread(dicom_path, force=True)
    media = convert_dicom_media(ds, dicom_path, tmp_path / "media", "T1_KX000001")

    assert manifest["case_id"] == "T1"
    assert metadata["objects"][str(dicom_path)]["redacted_fields"] == ["PatientID", "PatientName"]
    assert "REDACTED^TEST" not in json.dumps(metadata)
    assert extract_ultrasound_regions(ds)[0]["physical_units_x"] == "cm"
    assert media["decode_status"] == "success"
    assert Path(media["contact_sheet_path"]).exists()
    assert media["features"]["has_color_doppler_pixels"] is True


def test_evidence_packet_and_agent_task_contract(tmp_path: Path) -> None:
    pixels = np.stack([_echo_frame(color=True), _echo_frame(color=True)], axis=0)
    dicom_path = _write_dicom(tmp_path / "KX000002", pixels, [_region(x1=95, y1=95)])
    _manifest, metadata = inventory_case("T1", tmp_path)
    ds = pydicom.dcmread(dicom_path, force=True)
    media = convert_dicom_media(ds, dicom_path, tmp_path / "media", "T1_KX000002")
    summaries = build_guideline_summaries(ROOT / "guidelines", tmp_path / "summaries")

    packet = build_evidence_packet(metadata["objects"][str(dicom_path)], media, summaries)
    task = build_agent_task(packet, skill_path=ROOT / ".agents" / "skills" / "echo-view-classification" / "SKILL.md")
    record = _agent_record(packet)

    assert packet["guideline_summary_files"]
    assert packet["rendered_media"]["contact_sheet_path"]
    assert "selected_view" not in packet
    assert task["agent_name"] == "view_classifier"
    assert "Inspect the rendered media" in task["prompt"]
    validate_agent_view_record(record, packet)


def test_spectral_trace_extraction_is_preserved_outside_view_classifier(tmp_path: Path) -> None:
    region = {
        "region_index": 0,
        "data_type": 4,
        "region_location_min_x": 0,
        "region_location_min_y": 0,
        "region_location_max_x": 127,
        "region_location_max_y": 95,
        "reference_pixel_x": 12,
        "reference_pixel_y": 62,
        "physical_units_x": "seconds",
        "physical_units_y": "cm_per_second",
        "physical_delta_x": 0.01,
        "physical_delta_y": -2.0,
    }

    result = extract_spectral_trace(
        frame=_spectral_frame(),
        spectral_region=region,
        output_dir=tmp_path,
        artifact_stem="synthetic_cwd",
        source_file="/case/KX000003",
        modality="CWD",
    )

    assert result["status"] == "success"
    assert Path(result["envelope_trace_path_json"]).exists()
    assert Path(result["envelope_trace_path_csv"]).exists()
    assert Path(result["overlay_artifact_paths"][0]).exists()
    assert result["calibration_provenance"]["velocity_axis"]["unit"] == "cm/s"


def test_cli_dry_run_and_fixture_agent_result_execution(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    case_dir = source_root / "A1" / "KINETDX"
    case_dir.mkdir(parents=True)
    pixels = np.stack([_echo_frame(color=True), _echo_frame(color=True)], axis=0)
    dicom_path = _write_dicom(case_dir / "KX000004", pixels, [_region(x1=95, y1=95)])
    output_root = tmp_path / "runs"

    dry = subprocess.run(
        [
            sys.executable,
            "scripts/run_agentic_view_classifier_validation.py",
            "--source-root",
            str(source_root),
            "--cases",
            "A1",
            "--output-root",
            str(output_root),
            "--dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert dry.returncode == 0, dry.stderr
    assert "agentic_view_classifier_validation" in dry.stdout
    assert not (output_root / "A1" / "view_classification.json").exists()

    # First pass writes evidence packets and agent task prompts only.
    evidence_only = run_validation(
        case_ids=["A1"],
        source_root=source_root,
        output_root=output_root,
        max_video_frames=3,
        rerun=True,
    )
    assert evidence_only["per_case"]["A1"]["classification_status"] == "agent_decision_required"
    packet = json.loads((output_root / "A1" / "evidence_packets.json").read_text())["records"][0]

    decisions_root = tmp_path / "agent_decisions"
    decisions_root.mkdir()
    (decisions_root / "A1.json").write_text(json.dumps({"records": [_agent_record(packet, source_file=str(dicom_path))]}) + "\n")

    summary = run_validation(
        case_ids=["A1"],
        source_root=source_root,
        output_root=output_root,
        max_video_frames=3,
        rerun=True,
        agent_decisions_root=decisions_root,
        reuse_existing_media=True,
    )

    run_dir = output_root / "A1"
    for name in [
        "case_manifest.json",
        "dicom_metadata.json",
        "evidence_packets.json",
        "agent_observations.json",
        "view_classification.json",
        "spectral_extractions.json",
        "artifact_index.json",
        "audit.json",
    ]:
        assert (run_dir / name).exists(), name
    assert summary["per_case"]["A1"]["classified_count"] == 1
    view_payload = json.loads((run_dir / "view_classification.json").read_text())
    assert view_payload["records"][0]["selected_view"] == "A4C"
    assert view_payload["records"][0]["zoom_status"] == "not_zoomed"


def test_active_classifier_path_has_no_programmed_view_decision_logic() -> None:
    source = (ROOT / "ar_core" / "agentic_view_classifier.py").read_text()
    forbidden = [
        "def classify",
        "_rank_views",
        "def _geometry_observations",
        "def _layout_modality",
        "def _zoom_candidates",
        "selected_view =",
        "selected_modality =",
        "zoom_status =",
        "confidence = round",
        "VIEW_OPTIONS =",
        "MODALITY_OPTIONS =",
        "ZOOM_OPTIONS =",
        "order_view_hint",
        "case_order_fraction",
        "acquisition-order",
        "fallback candidate",
    ]
    for term in forbidden:
        assert term not in source
