"""Code-owned personal-learning scope; no runtime or provider dependencies."""

POLICY_VERSION = "personal-learning-v1"
CATEGORIES = frozenset(
    {
        "owned_item",
        "food_preference",
        "response_preference",
        "routine",
        "goal",
        "personal_fact",
        "activity",
        "event",
        "plan",
    }
)
SCALAR_FACETS = {
    "food_preference": frozenset({"diet_preference"}),
    "response_preference": frozenset({"response_language", "response_style"}),
}
LEGACY_FACETS = {
    "vehicle": "owned_item.vehicle",
    "vehicles": "owned_item.vehicle",
    "device": "owned_item.device",
    "devices": "owned_item.device",
}
LEGACY_FACETS.update(
    {facet: cat for cat, facets in SCALAR_FACETS.items() for facet in facets}
)
SUPPRESSION_KEYS = frozenset(
    {
        "owned_item.vehicle",
        "owned_item.device",
        "owned_item.other",
        "food_preference",
        "response_preference",
        "routine",
        "goal",
        "personal_fact",
        "activity",
        "event",
        "plan",
    }
)


def record_scope(record):
    """Return only registered relations; arbitrary standard facts confer no scope."""
    if record.predicate in LEGACY_FACETS:
        return LEGACY_FACETS[record.predicate]
    value = record.value
    if not isinstance(value, dict) or value.get("schema") != POLICY_VERSION:
        return None
    category = value.get("category")
    if category not in {
        "owned_item",
        "routine",
        "goal",
        "personal_fact",
        "activity",
        "event",
        "plan",
    } or not record.predicate.startswith(category + "_"):
        return None
    key = f"owned_item.{value.get('kind')}" if category == "owned_item" else category
    return key if key in SUPPRESSION_KEYS else None
