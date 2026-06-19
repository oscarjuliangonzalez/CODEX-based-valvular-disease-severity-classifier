"""Conservative deterministic evidence integration for synthetic workflows."""

from __future__ import annotations


def _class_bucket(classification: str | None) -> str:
    if not classification:
        return "indeterminate_support"
    if "mild" in classification:
        return "mild_support"
    if "severe" in classification:
        return "severe_support"
    if "moderate" in classification or "intermediate" in classification:
        return "moderate_support"
    return "indeterminate_support"


def conservative_integrate(measurements: list[dict], missing_information: list[str]) -> dict:
    contributions = []
    trusted_metrics = []
    downweighted_metrics = []
    excluded_metrics = []
    evidence_vector = {
        "mild_support": 0.0,
        "moderate_support": 0.0,
        "severe_support": 0.0,
        "indeterminate_support": 0.0,
    }

    for measurement in measurements:
        validity = measurement.get("technical_validity", "invalid")
        raw_class = measurement.get("ase_interpretation")
        base_reliability = float(measurement.get("reliability_weight_proposal", 0.5))
        adjusted_reliability = max(0.0, min(1.0, base_reliability))
        included = validity != "invalid"
        adjustment_reason = measurement.get("reliability_reason", "")

        if validity == "limited":
            adjusted_reliability *= 0.5
            downweighted_metrics.append(measurement.get("metric", "unknown_metric"))
            adjustment_reason = adjustment_reason or "technical validity is limited"
        elif validity == "invalid":
            adjusted_reliability = 0.0
            excluded_metrics.append(measurement.get("metric", "unknown_metric"))
            adjustment_reason = adjustment_reason or "technical validity is invalid"
        else:
            trusted_metrics.append(measurement.get("metric", "unknown_metric"))

        bucket = _class_bucket(raw_class)
        evidence_vector[bucket] += adjusted_reliability
        contributions.append(
            {
                "metric": measurement.get("metric", "unknown_metric"),
                "raw_value": measurement.get("value"),
                "raw_class": raw_class,
                "base_reliability": base_reliability,
                "adjusted_reliability": adjusted_reliability,
                "adjustment_reason": adjustment_reason,
                "included": included,
            }
        )

    included_classes = {
        item["raw_class"]
        for item in contributions
        if item["included"] and item["adjusted_reliability"] > 0 and item["raw_class"]
    }
    discordances = []
    if len(included_classes) > 1:
        discordances.append({"classes": sorted(included_classes), "reason": "included metrics cross severity-support categories"})

    total = sum(evidence_vector.values())
    if total:
        evidence_vector = {key: value / total for key, value in evidence_vector.items()}
    else:
        evidence_vector["indeterminate_support"] = 1.0

    if missing_information or len(contributions) < 2 or len(included_classes) != 1:
        return {
            "label": "indeterminate",
            "confidence": "low",
            "evidence_vector": evidence_vector,
            "reasoning_summary": ["Insufficient concordant validated evidence for integrated AR severity."],
            "metric_contributions": contributions,
            "trusted_metrics": trusted_metrics,
            "downweighted_metrics": downweighted_metrics,
            "excluded_metrics": excluded_metrics,
            "discordances": discordances,
            "missing_information": missing_information,
        }
    label = next(iter(included_classes)).replace("_supporting", "")
    return {
        "label": label,
        "confidence": "moderate",
        "evidence_vector": evidence_vector,
        "reasoning_summary": ["At least two valid concordant metrics support the same range."],
        "metric_contributions": contributions,
        "trusted_metrics": trusted_metrics,
        "downweighted_metrics": downweighted_metrics,
        "excluded_metrics": excluded_metrics,
        "discordances": discordances,
        "missing_information": missing_information,
    }
