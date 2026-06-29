"""Local guideline inventory and agent-usable summary generation."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ar_core.dicom_media import utc_now, write_json


VIEW_CRITERIA = {
    "PLAX": [
        "parasternal long-axis geometry",
        "left ventricle long axis",
        "aortic root and aortic valve",
        "mitral valve and left atrium",
        "anterior and posterior wall orientation",
    ],
    "PSAX": [
        "parasternal short-axis geometry",
        "circular ventricular or valve-level cross section",
        "aortic valve short-axis or LV short-axis level",
        "papillary muscle or mitral valve short-axis anatomy",
    ],
    "A4C": [
        "apical four-chamber geometry",
        "left and right ventricles visible",
        "left and right atria visible",
        "mitral and tricuspid valve plane",
        "apex near image sector origin",
    ],
    "A2C": [
        "apical two-chamber geometry",
        "left ventricle and left atrium",
        "mitral valve without right-sided chambers",
        "apex-to-base long-axis alignment",
    ],
    "A3C": [
        "apical long-axis geometry",
        "left ventricle, left atrium, mitral valve, and aortic valve",
        "LV outflow tract and aortic root from apical window",
    ],
    "suprasternal": [
        "suprasternal notch window",
        "aortic arch and great vessel orientation",
        "descending thoracic aorta continuity",
    ],
    "subcostal": [
        "subcostal window",
        "liver-proximal acoustic window",
        "inferior vena cava or abdominal aorta context",
        "horizontal four-chamber orientation may be present",
    ],
}

MODALITY_CRITERIA = {
    "2D": [
        "grayscale anatomy",
        "no persistent red-blue flow overlay",
        "no spectral velocity-time panel",
    ],
    "color Doppler": [
        "red and blue flow overlay inside the 2D sector",
        "color-flow jet or color map evidence",
        "2D anatomy remains visible behind color pixels",
    ],
    "CWD": [
        "spectral Doppler velocity over time",
        "continuous-wave spectral calibration",
        "high-velocity envelope display",
    ],
    "PWD": [
        "spectral Doppler velocity over time",
        "pulsed-wave spectral calibration",
        "sample volume or sample-site evidence required for AR interpretation",
    ],
    "M-mode": [
        "motion over time with depth axis",
        "DICOM ultrasound region in seconds by distance",
        "linear time-depth stripe layout",
    ],
}

ZOOM_CRITERIA = {
    "zoomed_in": [
        "cropped field of view",
        "enlarged valve, root, or jet region",
        "surrounding chamber context partly absent",
        "region area occupies most of the frame",
        "metadata or overlay suggests zoom focus",
    ],
    "not_zoomed": [
        "full sector field of view",
        "surrounding chambers and adjacent anatomy visible",
        "balanced field around target anatomy",
    ],
}

MEASUREMENT_SUITABILITY = {
    "PLAX": "Useful for aortic root, LVOT, aortic valve, color jet context, and vena contracta when calibrated.",
    "PSAX": "Useful for valve-level morphology and jet origin context; not a substitute for calibrated volumetric measurements.",
    "A4C": "Useful for chamber context, color Doppler, and PWD/CWD alignment when acquisition geometry supports it.",
    "A2C": "Useful for LV biplane support and apical color/spectral context.",
    "A3C": "Useful for LVOT/aortic valve alignment and AR CWD/color evidence.",
    "suprasternal": "Useful for aortic arch and descending aortic flow reversal evidence when sample site is known.",
    "subcostal": "Useful for alternative chamber/aortic context and abdominal aortic PWD reversal evidence when sample site is known.",
}


def _read_text_source(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".yaml", ".yml", ".json"}:
        return path.read_text(errors="ignore"), "plain_text"
    if suffix == ".pdf":
        text = "\n".join(_extract_pdf_pages(path))
        method = "pdf_text" if text else "pdf_metadata_only"
        return text, method
    return "", "unsupported_source_type"


def _bundled_python() -> Path | None:
    candidate = Path("/Users/general/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3")
    return candidate if candidate.exists() else None


def _poppler_binary(name: str) -> Path | None:
    candidate = Path("/Users/general/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin") / name
    if candidate.exists():
        return candidate
    return None


def _extract_pdf_pages(path: Path) -> list[str]:
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
        except Exception:
            continue
        try:
            reader = module.PdfReader(str(path))
            return [page.extract_text() or "" for page in reader.pages]
        except Exception:
            pass

    bundled = _bundled_python()
    if bundled:
        script = (
            "import json, sys; from pypdf import PdfReader; "
            "r=PdfReader(sys.argv[1]); "
            "print(json.dumps([p.extract_text() or '' for p in r.pages]))"
        )
        try:
            result = subprocess.run(
                [str(bundled), "-c", script, str(path)],
                check=True,
                text=True,
                capture_output=True,
            )
            return list(__import__("json").loads(result.stdout))
        except Exception:
            return []
    return []


def _snippets(text: str, terms: list[str]) -> list[str]:
    normalized = re.sub(r"\s+", " ", text)
    snippets = []
    for term in terms:
        match = re.search(re.escape(term), normalized, flags=re.IGNORECASE)
        if not match:
            continue
        start = max(0, match.start() - 120)
        end = min(len(normalized), match.end() + 180)
        snippets.append(normalized[start:end].strip())
    return snippets[:8]


def _inventory_sources(guidelines_dir: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(p for p in guidelines_dir.rglob("*") if p.is_file()):
        text, method = _read_text_source(path)
        terms = [
            "parasternal",
            "apical",
            "subcostal",
            "suprasternal",
            "Doppler",
            "M-mode",
            "color",
            "zoom",
        ]
        records.append(
            {
                "path": str(path),
                "name": path.name,
                "suffix": path.suffix.lower(),
                "extraction_method": method,
                "text_character_count": len(text),
                "relevant_snippets": _snippets(text, terms),
            }
        )
    return records


def _render_relevant_pdf_pages(guidelines_dir: Path, output_dir: Path, terms: list[str]) -> list[dict[str, Any]]:
    pdftoppm = _poppler_binary("pdftoppm")
    if pdftoppm is None:
        return []
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[dict[str, Any]] = []
    for path in sorted(guidelines_dir.rglob("*.pdf")):
        pages = _extract_pdf_pages(path)
        selected_pages: list[int] = []
        for index, text in enumerate(pages, start=1):
            if any(re.search(re.escape(term), text, flags=re.IGNORECASE) for term in terms):
                selected_pages.append(index)
            if len(selected_pages) >= 6:
                break
        if not selected_pages and pages:
            selected_pages = [1]
        for page_number in selected_pages:
            prefix = figure_dir / f"{path.stem}_page_{page_number:03d}"
            output_png = prefix.with_suffix(".png")
            if not output_png.exists():
                subprocess.run(
                    [
                        str(pdftoppm),
                        "-png",
                        "-f",
                        str(page_number),
                        "-l",
                        str(page_number),
                        "-r",
                        "130",
                        str(path),
                        str(prefix),
                    ],
                    check=False,
                    text=True,
                    capture_output=True,
                )
                generated_candidates = sorted(prefix.parent.glob(f"{prefix.name}-*.png"))
                if generated_candidates:
                    generated_candidates[0].replace(output_png)
            if output_png.exists():
                page_text = pages[page_number - 1] if page_number - 1 < len(pages) else ""
                rendered.append(
                    {
                        "source_file": str(path),
                        "page_number": page_number,
                        "artifact_path": str(output_png),
                        "matched_terms": [
                            term for term in terms if re.search(re.escape(term), page_text, flags=re.IGNORECASE)
                        ],
                    }
                )
    return rendered


def build_guideline_summaries(guidelines_dir: Path | str, output_dir: Path | str) -> dict[str, Any]:
    """Inventory local guideline files and write agent-usable summaries."""

    guideline_path = Path(guidelines_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    sources = _inventory_sources(guideline_path)
    search_terms = [
        "parasternal",
        "apical",
        "four-chamber",
        "two-chamber",
        "long-axis",
        "short-axis",
        "suprasternal",
        "subcostal",
        "Doppler",
        "M-mode",
        "color",
        "zoom",
    ]
    figure_records = _render_relevant_pdf_pages(guideline_path, output_path, search_terms)
    source_lines = [
        f"- `{Path(src['path']).name}`: {src['extraction_method']}, {src['text_character_count']} extracted characters"
        for src in sources
    ]
    provenance_lines = []
    for src in sources:
        provenance_lines.append(f"### {Path(src['path']).name}")
        provenance_lines.append(f"- Path: `{src['path']}`")
        provenance_lines.append(f"- Extraction method: `{src['extraction_method']}`")
        if src["relevant_snippets"]:
            provenance_lines.append("- Relevant local text snippets:")
            provenance_lines.extend(f"  - {snippet}" for snippet in src["relevant_snippets"])
        else:
            provenance_lines.append("- Relevant local text snippets: none extracted; source still inventoried for provenance.")

    view_summary = output_path / "view_classification_guidelines.md"
    modality_summary = output_path / "view_modality_zoom_definitions.md"
    figure_summary = output_path / "guideline_figure_index.md"
    source_index = output_path / "guideline_source_index.json"

    view_sections = [
        "# Agentic View Classification Guideline Summary",
        "",
        "This local summary is for research decision-support development. It must be used with rendered image evidence, DICOM metadata, calibration provenance, uncertainty, and privacy constraints.",
        "",
        "## Local Sources",
        *source_lines,
        "",
        "## View Criteria",
    ]
    for view, cues in VIEW_CRITERIA.items():
        view_sections.append(f"### {view}")
        view_sections.extend(f"- {cue}" for cue in cues)
        view_sections.append(f"- Measurement suitability: {MEASUREMENT_SUITABILITY[view]}")
        view_sections.append("")
    view_sections.extend(
        [
            "## Limitations And Safety Notes",
            "- These criteria support view and modality orientation only; they do not establish clinical severity.",
            "- Missing calibration, unreadable rendered media, or absent provenance is an engineering/tooling defect to repair.",
            "- Preserve discordant evidence and uncertainty; do not average contradictory sources into a single opaque label.",
            "",
            "## Rendered Guideline Pages For Agent Review",
            "Use these local page-render artifacts as visual guideline context. They are not patient data.",
            *[
                f"- `{Path(item['artifact_path']).name}` from `{Path(item['source_file']).name}` page {item['page_number']} (matched: {', '.join(item['matched_terms']) or 'page render'})"
                for item in figure_records
            ],
            "",
            "## Source Provenance",
            *provenance_lines,
        ]
    )

    modality_sections = [
        "# Agentic Modality And Zoom Definitions",
        "",
        "Use these definitions with local rendered frames/cine previews, DICOM metadata, and guideline provenance.",
        "",
        "## Modality And Layout Cues",
    ]
    for modality, cues in MODALITY_CRITERIA.items():
        modality_sections.append(f"### {modality}")
        modality_sections.extend(f"- {cue}" for cue in cues)
        modality_sections.append("")
    modality_sections.append("## Zoom Status Cues")
    for status, cues in ZOOM_CRITERIA.items():
        modality_sections.append(f"### {status}")
        modality_sections.extend(f"- {cue}" for cue in cues)
        modality_sections.append("")
    modality_sections.extend(
        [
            "## Measurement Suitability Implications",
            "- Spectral Doppler requires time/velocity calibration provenance before reporting velocities or envelopes.",
            "- PWD aortic flow reversal must not be interpreted for severity unless sample site evidence is known.",
            "- Color Doppler and zoomed views can support jet localization, but quantitative measurements still need calibration and inspectable artifacts.",
            "",
            "## Source Provenance",
            *provenance_lines,
        ]
    )

    figure_sections = [
        "# Guideline Figure And Page Index",
        "",
        "These local artifacts are rendered from guideline PDFs for Codex view-classifier agents to inspect. They are not patient data and do not replace the source PDF.",
        "",
    ]
    if figure_records:
        for item in figure_records:
            figure_sections.append(f"## {Path(item['source_file']).name} page {item['page_number']}")
            figure_sections.append(f"- Artifact: `{item['artifact_path']}`")
            figure_sections.append(f"- Matched terms: {', '.join(item['matched_terms']) or 'none recorded'}")
            figure_sections.append(f"- Source: `{item['source_file']}`")
            figure_sections.append("")
    else:
        figure_sections.append("No PDF page images were rendered. Poppler `pdftoppm` was unavailable or no PDF files were present.")

    view_summary.write_text("\n".join(view_sections).strip() + "\n")
    modality_summary.write_text("\n".join(modality_sections).strip() + "\n")
    figure_summary.write_text("\n".join(figure_sections).strip() + "\n")
    index_payload = {
        "created_at": utc_now(),
        "guidelines_dir": str(guideline_path),
        "source_count": len(sources),
        "sources": sources,
        "summary_files": {
            "view_classification_guidelines": str(view_summary),
            "view_modality_zoom_definitions": str(modality_summary),
            "guideline_figure_index": str(figure_summary),
        },
        "figure_records": figure_records,
        "view_criteria": VIEW_CRITERIA,
        "modality_criteria": MODALITY_CRITERIA,
        "zoom_criteria": ZOOM_CRITERIA,
    }
    write_json(source_index, index_payload)
    return {
        "created_at": index_payload["created_at"],
        "guidelines_dir": str(guideline_path),
        "source_count": len(sources),
        "sources": sources,
        "summary_files": index_payload["summary_files"],
        "source_index_path": str(source_index),
        "figure_records": figure_records,
        "view_criteria": VIEW_CRITERIA,
        "modality_criteria": MODALITY_CRITERIA,
        "zoom_criteria": ZOOM_CRITERIA,
    }
