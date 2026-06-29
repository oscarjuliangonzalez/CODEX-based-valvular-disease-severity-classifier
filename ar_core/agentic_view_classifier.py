"""Evidence-only orchestration for agentic echo view classification.

This module intentionally does not classify echo view, modality, or zoom
status. It inventories local sources, renders local evidence, writes agent task
packets, validates agent-authored results, and preserves spectral extraction.
The Codex orchestrator or a specialist view-classifier agent must author the
classification records.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pydicom
from PIL import Image, ImageDraw

from ar_core.dicom_media import (
    USABLE_IMAGE_SOURCE_TYPES,
    coerce_ultrasound_region,
    convert_dicom_media,
    decode_pixel_array,
    frame_array,
    inventory_case,
    media_paths,
    safe_int,
    spectral_regions,
    utc_now,
    write_json,
)
from ar_core.guideline_summary import build_guideline_summaries
from ar_core.spectral import extract_spectral_trace


CONTRACT_VERSION = "agentic_view_classifier_validation.v2"
MODE_NAME = "agentic_view_classifier_validation"

REQUIRED_AGENT_FIELDS = [
    "case_id",
    "source_file",
    "source_type",
    "series_uid",
    "sop_instance_uid",
    "frame_count",
    "derived_media_paths",
    "selected_view",
    "selected_modality",
    "zoom_status",
    "zoom_confidence",
    "ranked_view_candidates",
    "ranked_modality_candidates",
    "ranked_zoom_candidates",
    "confidence",
    "guideline_evidence",
    "metadata_evidence",
    "visual_observations",
    "visual_evidence_artifact_paths",
    "agent_reasoning_summary",
    "measurement_suitability",
    "limitations",
    "repair_history",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sanitize_stem(text: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return safe[:140] or "source"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _make_review_atlas(packets: list[dict[str, Any]], output_dir: Path, *, per_page: int = 20) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    atlas_paths: list[str] = []
    tile_w, tile_h = 320, 250
    cols = 2
    rows = max(1, (per_page + cols - 1) // cols)
    for page_index in range(0, len(packets), per_page):
        page_packets = packets[page_index : page_index + per_page]
        canvas = Image.new("RGB", (cols * tile_w, rows * tile_h), "white")
        draw = ImageDraw.Draw(canvas)
        for local_index, packet in enumerate(page_packets):
            col = local_index % cols
            row = local_index // cols
            x = col * tile_w
            y = row * tile_h
            label = f"{page_index + local_index + 1}: {Path(packet['source_file']).name}"
            draw.text((x + 8, y + 6), label[:48], fill=(0, 0, 0))
            media = packet.get("rendered_media", {})
            image_path = media.get("contact_sheet_path") or (
                media.get("representative_frame_paths") or [None]
            )[0]
            if image_path and Path(image_path).exists():
                try:
                    image = Image.open(image_path).convert("RGB")
                    image.thumbnail((tile_w - 16, tile_h - 38))
                    canvas.paste(image, (x + 8, y + 30))
                except Exception:
                    draw.text((x + 8, y + 40), "image preview unavailable", fill=(180, 0, 0))
            else:
                draw.text((x + 8, y + 40), "no rendered media", fill=(180, 0, 0))
        atlas_path = output_dir / f"view_classifier_review_atlas_{(page_index // per_page) + 1:03d}.png"
        canvas.save(atlas_path)
        atlas_paths.append(str(atlas_path))
    return atlas_paths


def build_evidence_packet(
    metadata: dict[str, Any],
    media: dict[str, Any],
    guideline_summary: dict[str, Any],
) -> dict[str, Any]:
    """Create one evidence packet without selecting a view or modality."""

    regions = [coerce_ultrasound_region(region) for region in metadata.get("ultrasound_regions", []) or []]
    derived_paths = media_paths(media)
    return {
        "contract_version": CONTRACT_VERSION,
        "case_id": metadata.get("case_id"),
        "source_file": metadata.get("source_file"),
        "source_type": metadata.get("source_type"),
        "series_uid": metadata.get("series_uid"),
        "sop_instance_uid": metadata.get("sop_instance_uid"),
        "frame_count": metadata.get("frame_count"),
        "dicom_metadata_summary": {
            "safe_tags": metadata.get("safe_tags", {}),
            "ultrasound_regions": regions,
            "metadata_evidence": metadata.get("metadata_evidence", []),
            "redacted_fields": metadata.get("redacted_fields", []),
            "private_tag_hints": metadata.get("private_tag_hints", []),
        },
        "layout_metadata": {
            "spectral_region_count": len(spectral_regions(regions)),
            "spectral_region_data_types": sorted(
                {safe_int(region.get("data_type")) for region in spectral_regions(regions) if safe_int(region.get("data_type"))}
            ),
            "rendered_media_features": media.get("features", {}),
        },
        "rendered_media": {
            "derived_media_paths": derived_paths,
            "representative_frame_paths": media.get("representative_frame_paths", []),
            "contact_sheet_path": media.get("contact_sheet_path"),
            "video_path": media.get("video_path"),
            "frame_map": media.get("frame_map", []),
            "features": media.get("features", {}),
            "decode_status": media.get("decode_status"),
            "repair_history": media.get("repair_history", []),
        },
        "frame_indices_represented": [
            item.get("source_frame_index")
            for item in media.get("frame_map", [])
            if item.get("source_frame_index") is not None
        ],
        "guideline_summary_files": guideline_summary.get("summary_files", {}),
        "guideline_source_index_path": guideline_summary.get("source_index_path"),
        "guideline_sources": [source.get("path") for source in guideline_summary.get("sources", [])],
        "possible_views": ["PLAX", "PSAX", "A4C", "A2C", "A3C", "suprasternal", "subcostal"],
        "possible_modalities": ["2D", "color Doppler", "CWD", "PWD", "M-mode", "spectral Doppler"],
        "possible_zoom_statuses": ["zoomed_in", "not_zoomed"],
        "provenance": {
            "metadata_source": metadata.get("source_file"),
            "media_source": media.get("source_file"),
            "guideline_sources": [source.get("path") for source in guideline_summary.get("sources", [])],
        },
    }


def build_agent_task(packet: dict[str, Any], *, skill_path: Path | str) -> dict[str, Any]:
    """Create the prompt payload a Codex view-classifier agent must answer."""

    prompt = f"""Use `{skill_path}` for this source object.

Inspect the rendered media paths in the evidence packet before classifying. Use
the local guideline summaries, DICOM metadata, layout metadata, and limitations.
Do not use acquisition order, fixed scoring tables, or hard-coded feature rules.

Return one JSON object with exactly the required view-classification fields:
{", ".join(REQUIRED_AGENT_FIELDS)}.

Terminal zoom_status must be `zoomed_in` or `not_zoomed`. If evidence is
insufficient, request repair of rendering, metadata parsing, guideline parsing,
or evidence packaging before returning a terminal record.
"""
    return {
        "contract_version": CONTRACT_VERSION,
        "agent_name": "view_classifier",
        "case_id": packet.get("case_id"),
        "source_file": packet.get("source_file"),
        "skill_path": str(skill_path),
        "evidence_packet_ref": {
            "source_file": packet.get("source_file"),
            "series_uid": packet.get("series_uid"),
            "sop_instance_uid": packet.get("sop_instance_uid"),
        },
        "prompt": prompt,
    }


def validate_agent_view_record(record: dict[str, Any], packet: dict[str, Any]) -> None:
    """Validate an agent-authored classification record against one packet."""

    missing = [field for field in REQUIRED_AGENT_FIELDS if field not in record]
    if missing:
        raise ValueError(f"agent record missing required fields: {missing}")
    for field in ["case_id", "source_file", "source_type", "series_uid", "sop_instance_uid", "frame_count"]:
        if record.get(field) != packet.get(field):
            raise ValueError(f"agent record field {field!r} does not match evidence packet")
    if record.get("zoom_status") not in {"zoomed_in", "not_zoomed"}:
        raise ValueError("agent record zoom_status must be terminal: zoomed_in or not_zoomed")
    for field in ["ranked_view_candidates", "ranked_modality_candidates", "ranked_zoom_candidates"]:
        if not isinstance(record.get(field), list) or not record[field]:
            raise ValueError(f"agent record {field} must be a non-empty list")
    for field in ["confidence", "zoom_confidence"]:
        value = record.get(field)
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
            raise ValueError(f"agent record {field} must be a numeric 0..1 confidence")
    if not record.get("agent_reasoning_summary"):
        raise ValueError("agent record must include an agent_reasoning_summary")
    if isinstance(record.get("visual_observations"), list):
        record["visual_observations"] = {"observations": record["visual_observations"]}
    if not isinstance(record.get("visual_observations"), dict):
        raise ValueError("agent record visual_observations must be an object or list")


def _load_agent_records(case_id: str, decisions_root: Path | None) -> list[dict[str, Any]]:
    if decisions_root is None:
        return []
    for candidate in [decisions_root / f"{case_id}.json", decisions_root / case_id / "view_classification.json"]:
        if candidate.exists():
            payload = _load_json(candidate)
            return payload.get("records", payload if isinstance(payload, list) else [])
    return []


def _load_or_render_media(
    case_id: str,
    obj: dict[str, Any],
    media_dir: Path,
    *,
    max_video_frames: int,
    max_representative_frames: int,
    reuse_existing_media: bool,
) -> dict[str, Any]:
    path = Path(obj["source_file"])
    media: dict[str, Any] = {
        "decode_status": "not_applicable",
        "repair_history": [],
        "representative_frame_paths": [],
        "features": {},
    }
    if obj.get("source_type") not in USABLE_IMAGE_SOURCE_TYPES:
        return media
    try:
        ds = pydicom.dcmread(str(path), force=True)
    except Exception as exc:
        media["decode_status"] = "failed"
        media["decode_error"] = f"{type(exc).__name__}: {exc}"
        media["repair_history"].append("dicom_read_failed_for_media_rendering")
        return media
    stem = _sanitize_stem(f"{case_id}_{path.name}_{obj.get('sop_instance_uid') or ''}")
    return convert_dicom_media(
        ds,
        path,
        media_dir,
        stem,
        max_video_frames=max_video_frames,
        max_representative_frames=max_representative_frames,
        reuse_existing=reuse_existing_media,
    )


def _extract_spectral_records(
    case_id: str,
    obj: dict[str, Any],
    run_dir: Path,
    *,
    agent_record: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    regions = spectral_regions(obj.get("ultrasound_regions", []) or [])
    if not regions:
        return [], [], []
    source_path = Path(obj["source_file"])
    artifacts: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        ds = pydicom.dcmread(str(source_path), force=True)
        decoded, repair_history = decode_pixel_array(ds)
        frame = frame_array(decoded, 0)
    except Exception as exc:
        repairs.append(
            {
                "case_id": case_id,
                "source_file": str(source_path),
                "event": "spectral_pixel_decode_repair_required",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return results, artifacts, repairs

    spectral_dir = run_dir / "spectral" / _sanitize_stem(source_path.name)
    for region in regions:
        region_modality = "CWD" if safe_int(region.get("data_type")) == 4 else "PWD"
        result = extract_spectral_trace(
            frame=frame,
            spectral_region=region,
            output_dir=spectral_dir,
            artifact_stem=f"{case_id}_{source_path.name}_region{region['region_index']}_{region_modality}",
            source_file=str(source_path),
            modality=region_modality,
        )
        result.update(
            {
                "case_id": case_id,
                "selected_view": agent_record.get("selected_view") if agent_record else None,
                "series_uid": obj.get("series_uid"),
                "sop_instance_uid": obj.get("sop_instance_uid"),
                "pixel_decode_repair_history": repair_history,
            }
        )
        results.append(result)
        for artifact_path in result.get("overlay_artifact_paths", []):
            artifacts.append({"source_file": str(source_path), "artifact_path": artifact_path, "kind": "spectral_overlay"})
        for artifact_path in [result.get("envelope_trace_path_json"), result.get("envelope_trace_path_csv")]:
            if artifact_path:
                artifacts.append({"source_file": str(source_path), "artifact_path": artifact_path, "kind": "spectral_trace"})
        if result["status"] != "success":
            repairs.append(
                {
                    "case_id": case_id,
                    "source_file": str(source_path),
                    "event": "spectral_trace_extraction_repair_required",
                    "quality_flags": result.get("quality_flags", []),
                }
            )
    return results, artifacts, repairs


def process_case(
    case_id: str,
    source_case_dir: Path | str,
    output_root: Path | str,
    guideline_summary: dict[str, Any],
    *,
    max_video_frames: int = 80,
    max_representative_frames: int = 3,
    reuse_existing_media: bool = False,
    agent_decisions_root: Path | None = None,
) -> dict[str, Any]:
    run_dir = Path(output_root) / case_id
    media_dir = run_dir / "media"
    task_dir = run_dir / "agent_tasks"
    run_dir.mkdir(parents=True, exist_ok=True)
    task_dir.mkdir(parents=True, exist_ok=True)

    manifest, metadata = inventory_case(case_id, source_case_dir)
    decision_records = _load_agent_records(case_id, agent_decisions_root)
    decisions_by_source = {record.get("source_file"): record for record in decision_records}

    packets = []
    tasks = []
    records = []
    observation_records = []
    spectral_records = []
    artifacts: list[dict[str, Any]] = []
    repair_events: list[dict[str, Any]] = []

    objects = sorted(
        [obj for obj in metadata["objects"].values() if obj.get("source_type") in USABLE_IMAGE_SOURCE_TYPES],
        key=lambda obj: (str(obj.get("series_uid") or ""), str(obj.get("sop_instance_uid") or ""), obj["source_file"]),
    )
    for obj in objects:
        media = _load_or_render_media(
            case_id,
            obj,
            media_dir,
            max_video_frames=max_video_frames,
            max_representative_frames=max_representative_frames,
            reuse_existing_media=reuse_existing_media,
        )
        for artifact_path in media_paths(media):
            artifacts.append({"source_file": obj["source_file"], "artifact_path": artifact_path, "kind": "media"})

        packet = build_evidence_packet(obj, media, guideline_summary)
        packets.append(packet)
        tasks.append(build_agent_task(packet, skill_path=_repo_root() / ".agents" / "skills" / "echo-view-classification" / "SKILL.md"))
        agent_record = decisions_by_source.get(obj["source_file"])
        if agent_record:
            validate_agent_view_record(agent_record, packet)
            records.append(agent_record)
            observation_records.append(
                {
                    "case_id": case_id,
                    "source_file": obj["source_file"],
                    "agent_name": "view_classifier",
                    "visual_observations": agent_record["visual_observations"],
                    "visual_evidence_artifact_paths": agent_record["visual_evidence_artifact_paths"],
                    "agent_reasoning_summary": agent_record["agent_reasoning_summary"],
                }
            )
        else:
            repair_events.append(
                {
                    "case_id": case_id,
                    "source_file": obj["source_file"],
                    "event": "agent_decision_required",
                    "action": "Dispatch Codex view_classifier specialist with evidence packet and rendered media.",
                }
            )

        extracted, spectral_artifacts, spectral_repairs = _extract_spectral_records(
            case_id,
            obj,
            run_dir,
            agent_record=agent_record,
        )
        spectral_records.extend(extracted)
        artifacts.extend(spectral_artifacts)
        repair_events.extend(spectral_repairs)

    atlas_paths = _make_review_atlas(packets, run_dir / "agent_tasks" / "review_atlas")
    for atlas_path in atlas_paths:
        artifacts.append({"source_file": None, "artifact_path": atlas_path, "kind": "agent_review_atlas"})

    write_json(run_dir / "case_manifest.json", manifest)
    write_json(run_dir / "dicom_metadata.json", metadata)
    write_json(run_dir / "evidence_packets.json", {"case_id": case_id, "created_at": utc_now(), "records": packets})
    write_json(
        run_dir / "agent_tasks" / "view_classifier_tasks.json",
        {"case_id": case_id, "review_atlas_paths": atlas_paths, "records": tasks},
    )
    write_json(
        run_dir / "agent_observations.json",
        {
            "case_id": case_id,
            "created_at": utc_now(),
            "classification_status": "complete" if len(records) == len(packets) else "agent_decision_required",
            "records": observation_records,
        },
    )
    view_counts = Counter(record["selected_view"] for record in records)
    modality_counts = Counter(record["selected_modality"] for record in records)
    zoom_counts = Counter(record["zoom_status"] for record in records)
    write_json(
        run_dir / "view_classification.json",
        {
            "case_id": case_id,
            "created_at": utc_now(),
            "contract_version": CONTRACT_VERSION,
            "classification_status": "complete" if len(records) == len(packets) else "agent_decision_required",
            "records": records,
            "summary": {
                "record_count": len(records),
                "evidence_packet_count": len(packets),
                "classified_image_series_count": len(records),
                "selected_views": dict(view_counts),
                "selected_modalities": dict(modality_counts),
                "zoom_statuses": dict(zoom_counts),
                "zoomed_in_count": zoom_counts.get("zoomed_in", 0),
            },
        },
    )
    write_json(
        run_dir / "spectral_extractions.json",
        {
            "case_id": case_id,
            "created_at": utc_now(),
            "records": spectral_records,
            "summary": {
                "record_count": len(spectral_records),
                "cwd_count": sum(1 for rec in spectral_records if rec.get("modality") == "CWD"),
                "pwd_count": sum(1 for rec in spectral_records if rec.get("modality") == "PWD"),
            },
        },
    )
    write_json(run_dir / "artifact_index.json", {"case_id": case_id, "artifacts": artifacts})
    write_json(
        run_dir / "audit.json",
        {
            "case_id": case_id,
            "created_at": utc_now(),
            "mode": MODE_NAME,
            "source_root": str(source_case_dir),
            "external_services": [],
            "orchestrator": "Codex local orchestrator",
            "classification_authority": "Codex view_classifier specialist agent, not Python evidence tools",
            "patient_metadata_redacted": True,
            "guideline_summary_files": guideline_summary.get("summary_files", {}),
            "repair_events": repair_events,
            "privacy_notes": metadata["deidentification_phi_risk_notes"],
        },
    )
    return {
        "case_id": case_id,
        "run_dir": str(run_dir),
        "classification_status": "complete" if len(records) == len(packets) else "agent_decision_required",
        "evidence_packet_count": len(packets),
        "classified_count": len(records),
        "zoomed_in_count": zoom_counts.get("zoomed_in", 0),
        "spectral_records": spectral_records,
        "repair_events": repair_events,
        "records": records,
    }


def _case_complete_without_rerun(case_id: str, output_root: Path) -> bool:
    run_dir = output_root / case_id
    required = [
        "case_manifest.json",
        "dicom_metadata.json",
        "evidence_packets.json",
        "agent_observations.json",
        "view_classification.json",
        "spectral_extractions.json",
        "artifact_index.json",
        "audit.json",
    ]
    return all((run_dir / name).exists() for name in required)


def _summarize_existing_case(case_id: str, output_root: Path) -> dict[str, Any]:
    run_dir = output_root / case_id
    view_payload = _load_json(run_dir / "view_classification.json")
    spectral_payload = _load_json(run_dir / "spectral_extractions.json")
    records = view_payload.get("records", [])
    return {
        "case_id": case_id,
        "run_dir": str(run_dir),
        "classification_status": view_payload.get("classification_status", "unknown"),
        "evidence_packet_count": view_payload.get("summary", {}).get("evidence_packet_count", 0),
        "classified_count": len(records),
        "zoomed_in_count": sum(1 for record in records if record.get("zoom_status") == "zoomed_in"),
        "spectral_records": spectral_payload.get("records", []),
        "repair_events": [],
        "records": records,
    }


def run_validation(
    case_ids: list[str],
    source_root: Path | str,
    output_root: Path | str,
    *,
    max_video_frames: int = 80,
    max_representative_frames: int = 3,
    reuse_existing_media: bool = False,
    rerun: bool = False,
    guidelines_dir: Path | str | None = None,
    guideline_output_dir: Path | str | None = None,
    agent_decisions_root: Path | str | None = None,
) -> dict[str, Any]:
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    root = _repo_root()
    guideline_summary = build_guideline_summaries(
        Path(guidelines_dir) if guidelines_dir is not None else root / "guidelines",
        Path(guideline_output_dir) if guideline_output_dir is not None else root / "docs" / "guideline_summaries",
    )
    decision_root = Path(agent_decisions_root) if agent_decisions_root is not None else None

    results = []
    repair_log = []
    table = []
    for case_id in case_ids:
        if not rerun and _case_complete_without_rerun(case_id, output):
            result = _summarize_existing_case(case_id, output)
        else:
            result = process_case(
                case_id,
                Path(source_root) / case_id,
                output,
                guideline_summary,
                max_video_frames=max_video_frames,
                max_representative_frames=max_representative_frames,
                reuse_existing_media=reuse_existing_media,
                agent_decisions_root=decision_root,
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
                    "zoom_status": record["zoom_status"],
                    "zoom_confidence": record["zoom_confidence"],
                    "confidence": record["confidence"],
                    "frame_count": record["frame_count"],
                    "source_type": record["source_type"],
                }
            )

    summary = {
        "created_at": utc_now(),
        "mode": MODE_NAME,
        "contract_version": CONTRACT_VERSION,
        "source_root": str(source_root),
        "output_root": str(output),
        "guideline_summary_files": guideline_summary.get("summary_files", {}),
        "cases_processed": len(results),
        "per_case": {
            result["case_id"]: {
                "classification_status": result["classification_status"],
                "evidence_packet_count": result["evidence_packet_count"],
                "classified_count": result["classified_count"],
                "zoomed_in_count": result["zoomed_in_count"],
                "spectral_count": len(result["spectral_records"]),
                "cwd_count": sum(1 for rec in result["spectral_records"] if rec.get("modality") == "CWD"),
                "pwd_count": sum(1 for rec in result["spectral_records"] if rec.get("modality") == "PWD"),
                "repair_event_count": len(result["repair_events"]),
            }
            for result in results
        },
        "total_evidence_packet_count": sum(result["evidence_packet_count"] for result in results),
        "total_classified_count": sum(result["classified_count"] for result in results),
        "total_zoomed_in_count": sum(result["zoomed_in_count"] for result in results),
        "total_spectral_count": sum(len(result["spectral_records"]) for result in results),
    }
    write_json(output / "summary.json", summary)
    write_json(output / "classification_table.json", {"created_at": utc_now(), "records": table})
    write_json(output / "repair_log.json", {"created_at": utc_now(), "events": repair_log})
    return summary


def dry_run_plan(case_ids: list[str], source_root: Path | str, output_root: Path | str) -> dict[str, Any]:
    return {
        "mode": MODE_NAME,
        "source_root": str(source_root),
        "output_root": str(output_root),
        "cases": [
            {
                "case_id": case_id,
                "input_dir": str(Path(source_root) / case_id),
                "output_dir": str(Path(output_root) / case_id),
            }
            for case_id in case_ids
        ],
        "would_write": [
            "case_manifest.json",
            "dicom_metadata.json",
            "media/",
            "evidence_packets.json",
            "agent_tasks/view_classifier_tasks.json",
            "agent_observations.json",
            "view_classification.json",
            "spectral_extractions.json",
            "artifact_index.json",
            "audit.json",
            "summary.json",
            "classification_table.json",
            "repair_log.json",
        ],
        "classification_authority": "Codex view_classifier specialist agent",
        "external_services": [],
    }
