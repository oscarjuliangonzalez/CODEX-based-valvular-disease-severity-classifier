"""Deprecated compatibility shim for view-classification validation.

The deterministic view classifier was replaced by
``ar_core.agentic_view_classifier``. This module remains only to avoid breaking
older imports while routing active work to the agentic evidence workflow and
neutral DICOM/media/spectral utilities.
"""

from __future__ import annotations

from ar_core.agentic_view_classifier import (
    build_agent_task,
    build_evidence_packet,
    process_case,
    run_validation,
    validate_agent_view_record,
)
from ar_core.dicom_media import (
    convert_dicom_media,
    decode_pixel_array,
    extract_ultrasound_regions,
    frame_array as _frame_array,
    frame_count_from_decoded as _frame_count_from_decoded,
    inventory_case,
    jsonable as _jsonable,
    safe_int as _safe_int,
)
from ar_core.spectral import extract_spectral_trace


DEPRECATED_REPLACEMENT = "ar_core.agentic_view_classifier"
