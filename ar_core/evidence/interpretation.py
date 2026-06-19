"""ASE-grounded AR threshold interpretation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ThresholdResult:
    classification: str
    technical_validity: str = "valid"
    limitations: tuple[str, ...] = ()
    source_id: str = "ase_2017_native_valvular_regurgitation"

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "technical_validity": self.technical_validity,
            "limitations": list(self.limitations),
            "source_id": self.source_id,
        }


def interpret_vena_contracta_width(vcw_cm: float) -> dict[str, Any]:
    if vcw_cm < 0:
        raise ValueError("vcw_cm must be non-negative")
    if vcw_cm < 0.3:
        return ThresholdResult("mild_supporting").as_dict()
    if vcw_cm <= 0.6:
        return ThresholdResult("moderate_supporting").as_dict()
    return ThresholdResult("severe_supporting").as_dict()


def interpret_jet_width_ratio(ratio: float, *, central_single_jet: bool) -> dict[str, Any]:
    if ratio < 0:
        raise ValueError("ratio must be non-negative")
    limitations = () if central_single_jet else ("not_validated_for_eccentric_or_multiple_jets",)
    technical_validity = "valid" if central_single_jet else "limited"
    if ratio < 0.25:
        classification = "mild_supporting"
    elif ratio <= 0.45:
        classification = "lower_moderate_supporting"
    elif ratio <= 0.64:
        classification = "upper_moderate_supporting"
    else:
        classification = "severe_supporting"
    return ThresholdResult(classification, technical_validity, limitations).as_dict()


def interpret_pressure_half_time(pht_ms: float) -> dict[str, Any]:
    if pht_ms <= 0:
        raise ValueError("pht_ms must be positive")
    if pht_ms > 500:
        classification = "mild_supporting"
    elif pht_ms >= 200:
        classification = "intermediate"
    else:
        classification = "severe_supporting"
    return ThresholdResult(classification, limitations=("load_dependent",)).as_dict()
