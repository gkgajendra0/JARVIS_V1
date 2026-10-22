"""Bounded privacy controls, distinct from semantic fact extraction."""

import hashlib
import re
import unicodedata

from jarvis.personal_learning_scope import SUPPRESSION_KEYS

_ALIASES = {
    "owned_item.vehicle": (
        "vehicles",
        "vehicle",
        "cars",
        "car",
        "bikes",
        "bike",
        "gaadi",
        "gaadiyan",
        "gadiyan",
        "गाड़ी",
        "गाड़ियाँ",
        "गाड़ियां",
        "वाहन",
        "वाहनों",
    ),
    "owned_item.device": ("devices", "device", "gadgets", "gadget", "डिवाइस"),
    "food_preference": (
        "food preferences",
        "diet preference",
        "food preference",
        "khane ki pasand",
        "खाने की पसंद",
    ),
    "response_preference": (
        "response preferences",
        "response preference",
        "jawab ki pasand",
        "जवाब की पसंद",
    ),
    "routine": ("routines", "routine", "दिनचर्या"),
    "goal": ("goals", "goal", "लक्ष्य"),
}


def category_veto(text):
    # Full-turn commands only: quoted/hypothetical statements and 'this: ...'
    # cannot silently become a persistent category permission change.
    normalized = unicodedata.normalize("NFKC", text).casefold().strip().rstrip(".!।")
    normalized = normalized.replace("’", "'")
    for key, aliases in _ALIASES.items():
        for alias in aliases:
            alias = re.escape(unicodedata.normalize("NFKC", alias))
            patterns = (
                rf"(?:please )?(?:don't|do not) (?:remember|save|store|learn) (?:(?:any of )?my )?{alias}(?: anymore| from now on)?(?: please)?",
                rf"(?:meri|mere|mera) {alias} (?:ke baare mein (?:kuch )?)?(?:yaad|save|store) mat (?:rakhna|rakho|karna|karo)",
                rf"(?:मेरी|मेरे|मेरा) {alias} (?:के बारे में (?:कुछ )?)?(?:याद|सेव) मत (?:रखना|रखो|करना|करो)",
            )
            if any(re.fullmatch(pattern, normalized) for pattern in patterns):
                return (key,)
    return ()


def suppression_binding(source, categories):
    from jarvis.authority.personal_learning import LearningActionBinding

    keys = tuple(sorted(categories))
    if not keys or not set(keys) <= SUPPRESSION_KEYS:
        raise PermissionError("invalid suppression category")
    digest = hashlib.sha256((source.digest + "|" + "|".join(keys)).encode()).hexdigest()
    return LearningActionBinding(
        "suppress",
        source.receipt_id,
        digest,
        tuple(sorted({k.split(".")[0] for k in keys})),
        tuple((k, None) for k in keys),
    )
