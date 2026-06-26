"""Report-derived AR measurement ingestion for reasoning validation.

This module is an adapter: it extracts explicit report values and maps them to
the repository measurement contract. It does not produce an integrated severity
label; final severity remains the responsibility of ar_core.evidence.integrator.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from ar_core.evidence.interpretation import (
    interpret_jet_width_ratio,
    interpret_pressure_half_time,
    interpret_vena_contracta_width,
)

SOURCE_TYPE = "report_pdf_extracted_validation_input"

SEVERITY_EVIDENCE_METRICS = {
    "vena_contracta_width_cm",
    "jet_width_lvot_ratio",
    "pressure_half_time_ms",
    "diastolic_flow_reversal",
    "regurgitant_volume_ml_per_beat",
    "regurgitant_fraction_percent",
    "eroa_cm2",
    "report_stated_ar_severity",
}

_OTHER_SECTION_PREFIXES = (
    "Mitral Valve",
    "Tricuspid Valve",
    "Pulmonic Valve",
    "Pulmonary Valve",
    "Left Ventricle",
    "Right Ventricle",
    "Left Atrium",
    "Right Atrium",
)

_AR_LABEL = r"(?:aortic\s+(?:valve\s+)?(?:regurgitation|insufficiency)|AR|AI)"

_SEVERITY_PATTERN = re.compile(
    r"\b(trace|trivial|mild|moderate(?:\s+to\s+severe)?|severe)\b"
    r"(?:(?:\s+\w+){0,4})?\s+"
    rf"{_AR_LABEL}\b"
    rf"|{_AR_LABEL}\b"
    r"(?:(?:\s+\w+){0,4})?\s+"
    r"\b(trace|trivial|mild|moderate(?:\s+to\s+severe)?|severe)\b",
    re.IGNORECASE,
)


def discover_report_pdfs(reports_dir: Path) -> list[Path]:
    """Return report PDFs below reports_dir without assuming lowercase suffixes."""

    return sorted(path for path in reports_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf")


def read_pdf_pages(report_path: Path) -> list[dict[str, Any]]:
    """Read report PDF text into page records.

    PDF dependencies are imported lazily so tests can exercise the extraction
    logic without requiring a PDF stack in the unit-test environment.
    """

    try:
        import pdfplumber  # type: ignore
    except Exception:
        pdfplumber = None

    if pdfplumber is not None:
        with pdfplumber.open(report_path) as pdf:
            return [
                {"page_number": index, "text": page.extract_text() or ""}
                for index, page in enumerate(pdf.pages, 1)
            ]

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on local runtime
        raise RuntimeError("reading report PDFs requires pdfplumber or pypdf") from exc

    reader = PdfReader(str(report_path))
    return [
        {"page_number": index, "text": page.extract_text() or ""}
        for index, page in enumerate(reader.pages, 1)
    ]


def severity_evidence_measurements(measurements: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter extracted measurements to values intended for AR severity integration."""

    return [
        measurement
        for measurement in measurements
        if measurement.get("evidence_role") == "severity_evidence"
        and measurement.get("metric") in SEVERITY_EVIDENCE_METRICS
    ]


def extract_report_data_from_pages(
    *,
    patient_id: str,
    report_path: Path,
    pages: list[dict[str, Any]],
    run_dir: Path,
) -> dict[str, Any]:
    """Extract explicit AR-relevant values from pre-read report pages."""

    extraction: dict[str, Any] = {
        "patient_id": patient_id,
        "report_filename": str(report_path),
        "source_type": SOURCE_TYPE,
        "pages_read": [page["page_number"] for page in pages],
        "report_stated_ar_severity": None,
        "measurements": [],
        "mapping_audit": [],
        "unmapped_extractions": [],
        "limitations": [],
    }
    raw_items: list[dict[str, Any]] = []
    report_stated_severity: str | None = None
    current_section: str | None = None

    for page in pages:
        page_number = int(page["page_number"])
        lines = [_normalize_space(raw_line) for raw_line in str(page.get("text") or "").splitlines()]
        lines = [line for line in lines if line]
        for line_index, line in enumerate(lines):
            if not line:
                continue
            current_section = _section_for_line(line, current_section)
            report_stated_item = _extract_report_stated_severity_item(line, page_number)
            if report_stated_item and report_stated_severity is None:
                report_stated_severity = str(report_stated_item["raw_value"])
                raw_items.append(report_stated_item)
            raw_items.extend(_extract_measurement_items(line, current_section, page_number))
            raw_items.extend(_extract_multiline_measurement_items(lines, line_index, page_number))

    for index, item in enumerate(raw_items, 1):
        measurement = _build_measurement(
            patient_id=patient_id,
            report_path=report_path,
            run_dir=run_dir,
            item=item,
            index=index,
        )
        extraction["measurements"].append(measurement)
        extraction["mapping_audit"].append(
            {
                "report_value": item["raw_value"],
                "report_unit": item.get("raw_unit"),
                "report_label": item["label"],
                "metric": measurement["metric"],
                "normalized_value": measurement["value"],
                "normalized_unit": measurement["unit"],
                "page_number": item["page_number"],
                "extracted_text_snippet": item["snippet"],
                "source_type": SOURCE_TYPE,
                "interpretation_source": measurement.get("interpretation_source"),
                "evidence_role": measurement.get("evidence_role"),
            }
        )

    extraction["report_stated_ar_severity"] = report_stated_severity
    if not extraction["measurements"]:
        extraction["limitations"].append("no_explicit_ar_measurements_extracted")
    elif not severity_evidence_measurements(extraction["measurements"]):
        extraction["limitations"].append("no_integratable_ar_severity_measurements_extracted")
    return extraction


def extract_report_data(
    *,
    patient_id: str,
    report_path: Path,
    run_dir: Path,
) -> dict[str, Any]:
    """Read a report PDF and extract report-derived measurement JSON."""

    return extract_report_data_from_pages(
        patient_id=patient_id,
        report_path=report_path,
        pages=read_pdf_pages(report_path),
        run_dir=run_dir,
    )


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _section_for_line(line: str, current_section: str | None) -> str | None:
    if line.startswith(("Aortic Insufficiency", "Aortic Regurgitation")):
        return "aortic_regurgitation"
    if line.startswith("Aortic Valve"):
        return "aortic_valve"
    if line.startswith(_OTHER_SECTION_PREFIXES):
        return None
    return current_section


def _is_ar_context(line: str, current_section: str | None) -> bool:
    if current_section == "aortic_regurgitation":
        return True
    return bool(re.search(rf"\b(?:AI|AR|aortic\s+(?:valve\s+)?insufficiency|aortic\s+(?:valve\s+)?regurgitation)\b", line, re.IGNORECASE))


def _extract_report_stated_severity(line: str) -> str | None:
    match = _SEVERITY_PATTERN.search(line)
    if not match:
        return None
    raw = next(group for group in match.groups() if group)
    value = raw.lower().replace(" ", "_")
    if value in {"trivial", "trace"}:
        return "trace"
    if value == "moderate_to_severe":
        return "moderate_to_severe"
    return value


def _extract_report_stated_severity_item(line: str, page_number: int) -> dict[str, Any] | None:
    severity = _extract_report_stated_severity(line)
    if severity is None:
        return None
    return _item(
        metric="report_stated_ar_severity",
        label="report_stated_ar_severity",
        raw_value=severity,
        raw_unit="report_label",
        page_number=page_number,
        snippet=line,
        confidence=0.9,
    )


def _extract_measurement_items(line: str, current_section: str | None, page_number: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.extend(_extract_pressure_half_time(line, current_section, page_number))
    items.extend(_extract_vena_contracta(line, page_number))
    items.extend(_extract_jet_width_ratio(line, page_number))
    items.extend(_extract_volumetric_threshold_values(line, current_section, page_number))
    items.extend(_extract_flow_reversal(line, current_section, page_number))
    items.extend(_extract_context_values(line, page_number))
    return items


def _extract_multiline_measurement_items(lines: list[str], line_index: int, page_number: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.extend(_extract_split_lv_volume_row(lines, line_index, page_number))
    return items


def _item(
    *,
    metric: str,
    label: str,
    raw_value: Any,
    raw_unit: str,
    page_number: int,
    snippet: str,
    confidence: float,
    evidence_role: str = "severity_evidence",
    central_single_jet: bool | None = None,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "label": label,
        "raw_value": raw_value,
        "raw_unit": raw_unit,
        "page_number": page_number,
        "snippet": snippet,
        "confidence": confidence,
        "evidence_role": evidence_role,
        "central_single_jet": central_single_jet,
    }


def _extract_pressure_half_time(line: str, current_section: str | None, page_number: int) -> list[dict[str, Any]]:
    if not _is_ar_context(line, current_section):
        return []
    if re.search(r"\b(?:MV|mitral)\b", line, re.IGNORECASE):
        return []
    match = re.search(
        r"(?:AI|AR|aortic\s+(?:insufficiency|regurgitation))?\s*"
        r"(?:pressure\s*)?(?:half[-\s]?time|PHT)\s*:?\s*"
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>msec|ms)\b",
        line,
        re.IGNORECASE,
    )
    if not match:
        return []
    return [
        _item(
            metric="pressure_half_time_ms",
            label="pressure_half_time",
            raw_value=float(match.group("value")),
            raw_unit=match.group("unit"),
            page_number=page_number,
            snippet=line,
            confidence=0.94,
        )
    ]


def _extract_vena_contracta(line: str, page_number: int) -> list[dict[str, Any]]:
    match = re.search(
        r"\b(?:vena\s+contracta(?:\s+width)?|VCW)\b\s*:?\s*"
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>cm|mm)\b",
        line,
        re.IGNORECASE,
    )
    if not match:
        return []
    return [
        _item(
            metric="vena_contracta_width_cm",
            label="vena_contracta_width",
            raw_value=float(match.group("value")),
            raw_unit=match.group("unit"),
            page_number=page_number,
            snippet=line,
            confidence=0.9,
        )
    ]


def _extract_jet_width_ratio(line: str, page_number: int) -> list[dict[str, Any]]:
    match = re.search(
        r"\b(?:jet\s+width\s*/\s*LVOT|jet\s+width\s+LVOT\s+ratio|JW\s*/\s*LVOT)\b"
        r"[^0-9]{0,20}(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent|ratio)?\b",
        line,
        re.IGNORECASE,
    )
    if not match:
        return []
    lower = line.lower()
    central_single_jet = "central" in lower and "eccentric" not in lower and "multiple" not in lower
    return [
        _item(
            metric="jet_width_lvot_ratio",
            label="jet_width_lvot_ratio",
            raw_value=float(match.group("value")),
            raw_unit=match.group("unit") or "ratio",
            page_number=page_number,
            snippet=line,
            confidence=0.82,
            central_single_jet=central_single_jet,
        )
    ]


def _extract_volumetric_threshold_values(
    line: str,
    current_section: str | None,
    page_number: int,
) -> list[dict[str, Any]]:
    if not _is_ar_context(line, current_section):
        return []
    patterns = [
        (
            "eroa_cm2",
            "eroa",
            r"\b(?:AR\s*)?EROA\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>cm²|cm2|cm\^2)\b",
            0.88,
        ),
        (
            "regurgitant_volume_ml_per_beat",
            "regurgitant_volume",
            r"\b(?:regurgitant\s+volume|RVol)\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mL/beat|ml/beat|mL|ml)\b",
            0.86,
        ),
        (
            "regurgitant_fraction_percent",
            "regurgitant_fraction",
            r"\b(?:regurgitant\s+fraction|RF)\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent)\b",
            0.86,
        ),
        (
            "ar_cwd_vmax_m_s",
            "ar_cwd_vmax",
            r"\b(?:AI|AR)\s*(?:CWD\s*)?Vmax\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>m/s|cm/s)\b",
            0.78,
        ),
        (
            "ar_cwd_vti_cm",
            "ar_cwd_vti",
            r"\b(?:AI|AR)\s*(?:CWD\s*)?VTI\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>cm|m)\b",
            0.78,
        ),
    ]
    items: list[dict[str, Any]] = []
    for metric, label, pattern, confidence in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            role = "severity_evidence" if metric in SEVERITY_EVIDENCE_METRICS else "supporting_context"
            items.append(
                _item(
                    metric=metric,
                    label=label,
                    raw_value=float(match.group("value")),
                    raw_unit=match.group("unit"),
                    page_number=page_number,
                    snippet=line,
                    confidence=confidence,
                    evidence_role=role,
                )
            )
    return items


def _extract_flow_reversal(line: str, current_section: str | None, page_number: int) -> list[dict[str, Any]]:
    if not _is_ar_context(line, current_section):
        return []
    if not re.search(r"\b(?:holodiastolic|diastolic)\b.*\bflow\s+reversal\b", line, re.IGNORECASE):
        return []
    if re.search(r"\b(no|absent|without)\b", line, re.IGNORECASE):
        return []
    return [
        _item(
            metric="diastolic_flow_reversal",
            label="diastolic_flow_reversal",
            raw_value=1.0,
            raw_unit="categorical_presence",
            page_number=page_number,
            snippet=line,
            confidence=0.76,
        )
    ]


def _extract_context_values(line: str, page_number: int) -> list[dict[str, Any]]:
    patterns = [
        (
            "lv_lvidd_cm",
            "lv_lvidd",
            r"\bLVIDd\s*\([^)]*\)\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>cm)\b",
        ),
        (
            "lv_lvids_cm",
            "lv_lvids",
            r"\bLVIDs\s*\([^)]*\)\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>cm)\b",
        ),
        (
            "lv_ef_percent",
            "lv_ef",
            r"\b(?:LV\s+EF\s*\([^)]*\)|EF-Biplane)\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent)\b",
        ),
        (
            "lvot_vti_cm",
            "lvot_vti",
            r"\bLVOT\s+VTI\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>cm)\b",
        ),
        (
            "lvot_diameter_cm",
            "lvot_diameter",
            r"\bLVOT\s+Diameter\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>cm)\b",
        ),
        (
            "lvot_stroke_volume_ml",
            "lvot_stroke_volume",
            r"\bLVOT\s+SV\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ml|mL)\b",
        ),
    ]
    items: list[dict[str, Any]] = []
    for metric, label, pattern in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            items.append(
                _item(
                    metric=metric,
                    label=label,
                    raw_value=float(match.group("value")),
                    raw_unit=match.group("unit"),
                    page_number=page_number,
                    snippet=line,
                    confidence=0.85,
                    evidence_role="remodeling_context",
                )
            )
    return items


def _extract_split_lv_volume_row(lines: list[str], line_index: int, page_number: int) -> list[dict[str, Any]]:
    line = lines[line_index]
    if "Biplane-Diast" not in line or "Biplane-Syst" not in line:
        return []
    if line_index + 1 >= len(lines):
        return []
    value_line = lines[line_index + 1]
    values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", value_line)]
    if len(values) < 6:
        return []
    metrics = [
        ("lv_edv_a4c_ml", "lv_edv_a4c", values[0]),
        ("lv_esv_a4c_ml", "lv_esv_a4c", values[1]),
        ("lv_edv_a2c_ml", "lv_edv_a2c", values[2]),
        ("lv_esv_a2c_ml", "lv_esv_a2c", values[3]),
        ("lv_edv_biplane_ml", "lv_edv_biplane", values[4]),
        ("lv_esv_biplane_ml", "lv_esv_biplane", values[5]),
    ]
    snippet = f"{line} | {value_line}"
    return [
        _item(
            metric=metric,
            label=label,
            raw_value=value,
            raw_unit="ml",
            page_number=page_number,
            snippet=snippet,
            confidence=0.82,
            evidence_role="remodeling_context",
        )
        for metric, label, value in metrics
    ]


def _build_measurement(
    *,
    patient_id: str,
    report_path: Path,
    run_dir: Path,
    item: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    value, unit, conversion = _normalize_value_unit(item["metric"], item["raw_value"], item["raw_unit"])
    interpretation = _interpret_item(item, value)
    metric = item["metric"]
    measurement_id = _measurement_id(patient_id, metric, index)
    artifact_path = run_dir / "report_extraction.json"
    quality_flags = ["report_pdf_extracted_validation_input"]
    quality_flags.extend(interpretation["quality_flags"])

    return {
        "measurement_id": measurement_id,
        "metric": metric,
        "value": value,
        "unit": unit,
        "report_value": item["raw_value"],
        "report_unit": item["raw_unit"],
        "unit_conversion": conversion,
        "per_frame_values": [],
        "selected_frames": [
            {
                "source_file": str(report_path),
                "page_number": item["page_number"],
            }
        ],
        "calibration_source": f"{SOURCE_TYPE}:{report_path}:page_{item['page_number']}",
        "formula": interpretation["formula"],
        "uncertainty": None,
        "ase_interpretation": interpretation["ase_interpretation"],
        "technical_validity": interpretation["technical_validity"],
        "reliability_weight_proposal": interpretation["reliability_weight_proposal"],
        "reliability_reason": interpretation["reliability_reason"],
        "artifact_paths": [str(artifact_path)],
        "quality_flags": quality_flags,
        "provenance": {
            "source_type": SOURCE_TYPE,
            "report_filename": str(report_path),
            "page_number": item["page_number"],
            "extracted_text_snippet": item["snippet"],
            "extraction_confidence": item["confidence"],
        },
        "interpretation_source": interpretation["interpretation_source"],
        "guideline_source_id": "ase_2017_native_valvular_regurgitation",
        "source_map_rule_ids": interpretation["source_map_rule_ids"],
        "evidence_role": item["evidence_role"],
    }


def _normalize_value_unit(metric: str, raw_value: Any, raw_unit: str) -> tuple[float, str, dict[str, Any] | None]:
    unit = raw_unit
    value = float(raw_value) if isinstance(raw_value, (int, float)) else raw_value
    normalized_raw_unit = raw_unit.lower()
    if metric == "report_stated_ar_severity":
        ordinal = {
            "trace": 0.0,
            "trivial": 0.0,
            "mild": 1.0,
            "moderate": 2.0,
            "moderate_to_severe": 2.5,
            "severe": 3.0,
        }[str(raw_value)]
        return ordinal, "ordinal_report_label", {
            "from_unit": raw_unit,
            "to_unit": "ordinal_report_label",
            "factor": None,
            "reason": "explicit report-stated AR severity label encoded for measurement schema compatibility; no new grading performed",
        }
    if metric == "pressure_half_time_ms" and normalized_raw_unit == "msec":
        return value, "ms", {"from_unit": raw_unit, "to_unit": "ms", "factor": 1.0, "reason": "msec is equivalent to ms"}
    if metric == "vena_contracta_width_cm" and normalized_raw_unit == "mm":
        return value / 10.0, "cm", {"from_unit": raw_unit, "to_unit": "cm", "factor": 0.1, "reason": "10 mm equals 1 cm"}
    if metric == "jet_width_lvot_ratio" and normalized_raw_unit in {"%", "percent"}:
        return value / 100.0, "ratio", {"from_unit": raw_unit, "to_unit": "ratio", "factor": 0.01, "reason": "percent divided by 100"}
    if metric == "eroa_cm2":
        return value, "cm2", None
    if metric == "regurgitant_volume_ml_per_beat":
        return value, "ml/beat", None
    if metric == "regurgitant_fraction_percent":
        return value, "%", None
    if metric == "ar_cwd_vmax_m_s" and normalized_raw_unit == "cm/s":
        return value / 100.0, "m/s", {"from_unit": raw_unit, "to_unit": "m/s", "factor": 0.01, "reason": "100 cm/s equals 1 m/s"}
    if metric == "ar_cwd_vti_cm" and normalized_raw_unit == "m":
        return value * 100.0, "cm", {"from_unit": raw_unit, "to_unit": "cm", "factor": 100.0, "reason": "1 m equals 100 cm"}
    if normalized_raw_unit == "percent":
        unit = "%"
    return value, unit, None


def _interpret_item(item: dict[str, Any], value: float) -> dict[str, Any]:
    metric = item["metric"]
    if metric == "report_stated_ar_severity":
        severity = str(item["raw_value"])
        classification = {
            "trace": "trace_supporting",
            "trivial": "trace_supporting",
            "mild": "mild_supporting",
            "moderate": "moderate_supporting",
            "moderate_to_severe": "moderate_to_severe_supporting",
            "severe": "severe_supporting",
        }[severity]
        return {
            "ase_interpretation": classification,
            "technical_validity": "limited",
            "formula": "direct report-stated AR severity label; ordinal code used only for schema compatibility",
            "reliability_weight_proposal": 0.5,
            "reliability_reason": "explicit report-derived qualitative severity statement; not independently remeasured from quantitative images",
            "quality_flags": ["direct_report_stated_severity", "qualitative_report_value_encoded_as_numeric"],
            "interpretation_source": "report_ingestion_direct_report_stated_ar_severity_mapping",
            "source_map_rule_ids": ["ar_integrative_assessment"],
        }
    if metric == "pressure_half_time_ms":
        result = interpret_pressure_half_time(value)
        return _threshold_payload(
            result,
            formula="direct report AI pressure half-time value; safe unit normalization only",
            reliability=0.75,
            reason="explicit report-derived PHT; load dependent and not remeasured from CWD image",
            interpretation_source="ar_core.evidence.interpretation.interpret_pressure_half_time",
            rule_ids=["pht_load_dependence", "ar_integrative_assessment"],
        )
    if metric == "vena_contracta_width_cm":
        result = interpret_vena_contracta_width(value)
        return _threshold_payload(
            result,
            formula="direct report vena contracta value; safe unit normalization only",
            reliability=0.85,
            reason="explicit report-derived vena contracta width; not remeasured from image",
            interpretation_source="ar_core.evidence.interpretation.interpret_vena_contracta_width",
            rule_ids=["vena_contracta_width", "ar_integrative_assessment"],
        )
    if metric == "jet_width_lvot_ratio":
        result = interpret_jet_width_ratio(value, central_single_jet=bool(item.get("central_single_jet")))
        return _threshold_payload(
            result,
            formula="direct report jet width/LVOT ratio; central single jet accepted only if stated",
            reliability=0.7 if result["technical_validity"] == "valid" else 0.35,
            reason="report-derived jet width ratio; central/eccentric applicability preserved",
            interpretation_source="ar_core.evidence.interpretation.interpret_jet_width_ratio",
            rule_ids=["ar_integrative_assessment"],
        )
    if metric == "eroa_cm2":
        return _direct_threshold_payload(
            classification=_classify_eroa(value),
            formula="direct report EROA value; interpreted against existing ASE threshold YAML",
            reliability=0.85,
            reason="explicit report-derived EROA; not remeasured from PISA/CWD images",
            rule_ids=["ar_integrative_assessment"],
        )
    if metric == "regurgitant_volume_ml_per_beat":
        return _direct_threshold_payload(
            classification=_classify_regurgitant_volume(value),
            formula="direct report regurgitant volume; interpreted against existing ASE threshold YAML",
            reliability=0.85,
            reason="explicit report-derived regurgitant volume; not recomputed from Doppler volumetrics",
            rule_ids=["ar_integrative_assessment"],
        )
    if metric == "regurgitant_fraction_percent":
        return _direct_threshold_payload(
            classification=_classify_regurgitant_fraction(value),
            formula="direct report regurgitant fraction; interpreted against existing ASE threshold YAML",
            reliability=0.85,
            reason="explicit report-derived regurgitant fraction; not recomputed from Doppler volumetrics",
            rule_ids=["ar_integrative_assessment"],
        )
    if metric == "diastolic_flow_reversal":
        snippet = item["snippet"].lower()
        classification = "severe_supporting" if "abdominal" in snippet else "intermediate"
        return _direct_threshold_payload(
            classification=classification,
            formula="qualitative report statement encoded as categorical presence for schema compatibility",
            reliability=0.65,
            reason="report-derived qualitative holodiastolic flow reversal statement",
            rule_ids=["flow_reversal", "ar_integrative_assessment"],
            quality_flags=["qualitative_report_value_encoded_as_numeric"],
        )
    return {
        "ase_interpretation": "context_only_not_integrated",
        "technical_validity": "limited",
        "formula": "direct report context value; not an AR severity threshold metric",
        "reliability_weight_proposal": 0.1,
        "reliability_reason": "report-derived remodeling/context value; excluded from severity integration",
        "quality_flags": ["context_only_not_severity_integrated"],
        "interpretation_source": "report_ingestion_context_mapping_no_severity_threshold_applied",
        "source_map_rule_ids": ["ar_integrative_assessment"],
    }


def _threshold_payload(
    result: dict[str, Any],
    *,
    formula: str,
    reliability: float,
    reason: str,
    interpretation_source: str,
    rule_ids: list[str],
) -> dict[str, Any]:
    quality_flags = [
        "load_dependent_metric" if limitation == "load_dependent" else limitation
        for limitation in (result.get("limitations") or [])
    ]
    return {
        "ase_interpretation": result["classification"],
        "technical_validity": result.get("technical_validity", "valid"),
        "formula": formula,
        "reliability_weight_proposal": reliability,
        "reliability_reason": reason,
        "quality_flags": quality_flags,
        "interpretation_source": interpretation_source,
        "source_map_rule_ids": rule_ids,
    }


def _direct_threshold_payload(
    *,
    classification: str,
    formula: str,
    reliability: float,
    reason: str,
    rule_ids: list[str],
    quality_flags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ase_interpretation": classification,
        "technical_validity": "valid",
        "formula": formula,
        "reliability_weight_proposal": reliability,
        "reliability_reason": reason,
        "quality_flags": quality_flags or [],
        "interpretation_source": "ar_core.evidence.ase_ar_thresholds.yaml",
        "source_map_rule_ids": rule_ids,
    }


def _classify_regurgitant_volume(value: float) -> str:
    if value < 30:
        return "mild_supporting"
    if value < 45:
        return "lower_moderate_supporting"
    if value < 60:
        return "upper_moderate_supporting"
    return "severe_supporting"


def _classify_regurgitant_fraction(value: float) -> str:
    if value < 30:
        return "mild_supporting"
    if value < 40:
        return "lower_moderate_supporting"
    if value < 50:
        return "upper_moderate_supporting"
    return "severe_supporting"


def _classify_eroa(value: float) -> str:
    if value < 0.10:
        return "mild_supporting"
    if value < 0.20:
        return "lower_moderate_supporting"
    if value < 0.30:
        return "upper_moderate_supporting"
    return "severe_supporting"


def _measurement_id(patient_id: str, metric: str, index: int) -> str:
    safe_patient = re.sub(r"[^A-Za-z0-9_.-]+", "_", patient_id)
    return f"{safe_patient}_{metric}_report_{index}"
