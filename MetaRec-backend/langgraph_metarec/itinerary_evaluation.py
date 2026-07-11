"""Deterministic, provider-free itinerary quality metrics for CI and metadata."""
from __future__ import annotations

from typing import Any, Dict, Optional


def evaluate_itinerary(block: Dict[str, Any], previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    slots = [slot for slot in block.get("slots") or [] if isinstance(slot, dict)]
    chosen = [slot for slot in slots if isinstance(slot.get("chosen"), dict)]
    validation = block.get("validation") if isinstance(block.get("validation"), dict) else {}
    violations = validation.get("violations") if isinstance(validation.get("violations"), list) else []
    codes = [str(item.get("code")) for item in violations if isinstance(item, dict)]
    ids = [str(slot["chosen"].get("id")) for slot in chosen if slot["chosen"].get("id")]
    duplicate_count = max(0, len(ids) - len(set(ids)))
    schedule_codes = {"meal_window", "day_too_long", "known_closed"}
    schedule_conflicts = sum(code in schedule_codes for code in codes)
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    budget_limit = checks.get("budget_limit_sgd")
    spend = float(checks.get("estimated_food_spend_sgd") or 0)
    budget_deviation = max(0.0, spend - float(budget_limit)) if budget_limit is not None else None
    ratings = [float(slot["chosen"].get("rating")) / 5 for slot in chosen if slot["chosen"].get("rating") is not None]
    legs = [leg for leg in block.get("legs") or [] if isinstance(leg, dict)]
    fallback_count = sum(leg.get("source") == "estimate" for leg in legs)
    metrics: Dict[str, Any] = {
        "delivery_rate": round(len(chosen) / len(slots), 3) if slots else 0.0,
        "hard_constraint_pass_rate": 1.0 if not violations else 0.0,
        "commonsense_pass_rate": 1.0 if not any(code in schedule_codes | {"duplicate_poi", "missing_required_stop"} for code in codes) else 0.0,
        "duplicate_rate": round(duplicate_count / max(1, len(chosen)), 3),
        "schedule_conflict_rate": round(schedule_conflicts / max(1, len(slots)), 3),
        "route_travel_min": int((block.get("totals") or {}).get("total_travel_min") or 0),
        "budget_deviation_sgd": round(budget_deviation, 2) if budget_deviation is not None else None,
        "preference_match": round(sum(ratings) / len(ratings), 3) if ratings else None,
        "provider_call_count": sum(leg.get("source") != "estimate" and leg.get("cache") != "hit" for leg in legs),
        "fallback_rate": round(fallback_count / len(legs), 3) if legs else 0.0,
    }
    if previous is not None:
        prior = {
            int(slot.get("slot_index", -1)): str((slot.get("chosen") or {}).get("id") or "")
            for slot in previous.get("slots") or [] if isinstance(slot, dict)
        }
        unchanged = sum(prior.get(int(slot.get("slot_index", -1))) == str((slot.get("chosen") or {}).get("id") or "") for slot in slots)
        metrics["refinement_stability"] = round(unchanged / max(1, len(slots)), 3)
    return metrics

