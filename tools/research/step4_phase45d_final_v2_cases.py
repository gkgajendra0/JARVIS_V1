"""Deterministic fresh corpus for Phase 4.5D final V2 confidence acceptance.

This corpus is independent of the exposed 64-case and 320-case corpora. It is
committed before the owner run and must never be changed in response to V2
validation results.

Counts:
- calibration: 600 release + 600 abstain;
- validation: 300 release + 300 abstain;
- validation release cases: exactly 100 EN / 100 HI / 100 Hinglish.

Synthetic data cannot establish exchangeability with future owner traffic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

V2_CORPUS_SCHEMA_VERSION = 2
V2_CALIBRATION_RELEASE = 600
V2_CALIBRATION_ABSTAIN = 600
V2_VALIDATION_RELEASE = 300
V2_VALIDATION_ABSTAIN = 300
LANGUAGES = ("en", "hi", "hinglish")
ABSTAIN_CATEGORIES = (
    "absent",
    "near_miss",
    "ambiguous",
    "adversarial_lexical",
    "negation",
    "relation_mismatch",
    "unsupported_source",
    "historical",
    "forgotten",
    "local_only",
    "secret",
    "untrusted",
)
SECURITY_BOUNDARY_CATEGORIES = {
    "historical",
    "forgotten",
    "local_only",
    "secret",
    "untrusted",
}


@dataclass(frozen=True, slots=True)
class RelationSpec:
    key: str
    relation_en: str
    relation_hi: str
    relation_hinglish: str
    value_stem: str


@dataclass(frozen=True, slots=True)
class CurrentFact:
    memory_id: str
    predicate: str
    split: str
    domain: str
    profile: str
    relation_index: int
    relation_en: str
    relation_hi: str
    relation_hinglish: str
    value: str

    @property
    def text(self) -> str:
        return (
            f"Synthetic V2 {self.domain} profile {self.profile}: the recorded "
            f"{self.relation_en} is {self.value}."
        )


RELATIONS = (
    RelationSpec(
        "region",
        "deployment region",
        "डिप्लॉयमेंट रीजन",
        "deployment region",
        "asia-south",
    ),
    RelationSpec("branch", "build branch", "बिल्ड ब्रांच", "build branch", "release"),
    RelationSpec(
        "channel", "release channel", "रिलीज़ चैनल", "release channel", "stable"
    ),
    RelationSpec(
        "format", "artifact format", "आर्टिफैक्ट फ़ॉर्मेट", "artifact format", "bundle"
    ),
    RelationSpec("retention", "log retention", "लॉग रिटेंशन", "log retention", "days"),
    RelationSpec("seat", "seat preference", "सीट पसंद", "seat preference", "aisle"),
    RelationSpec("map", "map style", "मैप स्टाइल", "map style", "terrain"),
    RelationSpec("editor", "code editor", "कोड एडिटर", "code editor", "editor"),
    RelationSpec("shell", "command shell", "कमांड शेल", "command shell", "shell"),
    RelationSpec("sync", "sync interval", "सिंक अंतराल", "sync interval", "minutes"),
)

PROFILE_NAMES = {
    "project": (
        "Aster",
        "Bramble",
        "Corvus",
        "Driftwood",
        "Eon",
        "Falconer",
        "Glacier",
        "Harbor",
        "Indigo",
        "Javelin",
    ),
    "travel": (
        "Kestrel",
        "Lantern",
        "Meadow",
        "Northstar",
        "Opal",
        "Prairie",
        "Quasar",
        "Redwood",
        "Summit",
        "Timber",
    ),
    "workspace": (
        "Ultralight",
        "Vantage",
        "Warden",
        "Xylem",
        "Yonder",
        "Zenith",
        "AuroraX",
        "Birchline",
        "Cloudrift",
        "Dunecrest",
    ),
}
CALIBRATION_PROFILE_COUNTS = {"project": 7, "travel": 7, "workspace": 6}


def _value(domain: str, profile_index: int, relation: RelationSpec) -> str:
    domain_code = {"project": "P", "travel": "T", "workspace": "W"}[domain]
    return f"{relation.value_stem}-{domain_code}{profile_index + 1:02d}"


def _build_current_facts() -> tuple[CurrentFact, ...]:
    rows: list[CurrentFact] = []
    for domain in ("project", "travel", "workspace"):
        for profile_index, profile in enumerate(PROFILE_NAMES[domain]):
            split = (
                "calibration"
                if profile_index < CALIBRATION_PROFILE_COUNTS[domain]
                else "validation"
            )
            for relation_index, relation in enumerate(RELATIONS):
                rows.append(
                    CurrentFact(
                        memory_id=(
                            f"v2_{domain}_{profile_index + 1:02d}_{relation.key}"
                        ),
                        predicate=f"v2_{domain}_{relation.key}",
                        split=split,
                        domain=domain,
                        profile=profile,
                        relation_index=relation_index,
                        relation_en=relation.relation_en,
                        relation_hi=relation.relation_hi,
                        relation_hinglish=relation.relation_hinglish,
                        value=_value(domain, profile_index, relation),
                    )
                )
    return tuple(rows)


CURRENT_FACTS = _build_current_facts()


def _boundary_document(category: str, index: int) -> dict[str, Any]:
    token = f"{index:03d}"
    if category == "historical":
        return {
            "memory_id": f"v2_hist_old_{token}",
            "predicate": f"v2_history_policy_{token}",
            "mode": "historical_transition",
            "text": (
                f"Synthetic V2 history {token}: the previous archive cadence for "
                f"Ledger-{token} was weekly."
            ),
            "replacement_memory_id": f"v2_hist_current_{token}",
            "replacement_text": (
                f"Synthetic V2 current state {token}: the archive cadence for "
                f"Ledger-{token} is daily."
            ),
            "topic_en": f"previous archive cadence for Ledger-{token}",
            "topic_hi": f"Ledger-{token} की पिछली archive cadence",
            "topic_hinglish": f"Ledger-{token} ki previous archive cadence",
        }
    if category == "forgotten":
        return {
            "memory_id": f"v2_forgotten_{token}",
            "predicate": f"v2_forgotten_route_{token}",
            "mode": "forgotten",
            "text": (
                f"Synthetic V2 forgotten fixture {token}: temporary route token "
                f"was North-{token} before explicit forget."
            ),
            "topic_en": f"forgotten temporary route token {token}",
            "topic_hi": f"भुलाया गया temporary route token {token}",
            "topic_hinglish": f"forgotten temporary route token {token}",
        }
    if category == "local_only":
        return {
            "memory_id": f"v2_local_{token}",
            "predicate": f"v2_local_diagnostic_{token}",
            "mode": "local_only",
            "text": (
                f"Synthetic V2 local-only fixture {token}: diagnostic slot is "
                f"LOCAL-V2-{token}."
            ),
            "topic_en": f"local-only diagnostic slot {token}",
            "topic_hi": f"local-only diagnostic slot {token}",
            "topic_hinglish": f"local-only diagnostic slot {token}",
        }
    if category == "secret":
        return {
            "memory_id": f"v2_secret_{token}",
            "predicate": f"v2_secret_placeholder_{token}",
            "mode": "secret",
            "text": (
                f"Synthetic V2 secret placeholder {token} must never enter "
                "canonical memory."
            ),
            "topic_en": f"secret placeholder {token}",
            "topic_hi": f"secret placeholder {token}",
            "topic_hinglish": f"secret placeholder {token}",
        }
    if category == "untrusted":
        return {
            "memory_id": f"v2_untrusted_{token}",
            "predicate": f"v2_untrusted_claim_{token}",
            "mode": "untrusted",
            "text": (
                f"Synthetic V2 untrusted webpage {token} claims the preferred "
                f"badge is Amber-{token}."
            ),
            "topic_en": f"untrusted preferred badge claim {token}",
            "topic_hi": f"untrusted preferred badge दावा {token}",
            "topic_hinglish": f"untrusted preferred badge claim {token}",
        }
    raise ValueError(f"unsupported boundary category: {category}")


BOUNDARY_DOCUMENTS = tuple(
    _boundary_document(category, index)
    for category in ("historical", "forgotten", "local_only", "secret", "untrusted")
    for index in range(1, 76)
)


def _case(
    case_id: str,
    split: str,
    label: str,
    query: str,
    expected_memory_id: str | None,
    language: str,
    category: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "split": split,
        "label": label,
        "query": query,
        "expected_memory_id": expected_memory_id,
        "language": language,
        "category": category,
    }


def _positive_query(fact: CurrentFact, language: str, split: str) -> str:
    validation = split == "validation"
    if language == "hi":
        if validation:
            return (
                f"Memory check: {fact.profile} के लिए अभी {fact.relation_hi} क्या दर्ज है?"
            )
        return f"{fact.profile} के लिए दर्ज {fact.relation_hi} क्या है?"
    if language == "hinglish":
        if validation:
            return (
                f"Memory check: {fact.profile} ke liye abhi "
                f"{fact.relation_hinglish} kya recorded hai?"
            )
        return f"{fact.profile} ka recorded {fact.relation_hinglish} kya hai?"
    if validation:
        return (
            f"Memory check for {fact.profile}: which {fact.relation_en} is "
            "currently on record?"
        )
    return f"For {fact.profile}, what {fact.relation_en} is recorded?"


def _current_abstain_query(
    fact: CurrentFact,
    category: str,
    language: str,
) -> str:
    next_relation = RELATIONS[(fact.relation_index + 1) % len(RELATIONS)]
    if language == "hi":
        templates = {
            "absent": (
                f"{fact.profile} में {fact.value} {fact.relation_hi} के साथ "
                "कौन-सा parking permit zone दर्ज है?"
            ),
            "near_miss": (
                f"{fact.profile} के लिए {fact.value} को {fact.relation_hi} "
                "क्यों चुना गया था?"
            ),
            "ambiguous": (
                f"{fact.profile} में {fact.value} {fact.relation_hi} के लिए दर्ज है; "
                "अब कौन-सी दूसरी preference इस्तेमाल करनी चाहिए?"
            ),
            "adversarial_lexical": (
                f"{fact.profile} में {fact.value} को {fact.relation_hi} सेट करने "
                "के बाद कौन-सा approval ticket बना था?"
            ),
            "negation": (
                f"{fact.profile} में {fact.value} reject होने के बाद "
                f"{fact.relation_hi} के लिए कौन-सी value ने उसे replace किया?"
            ),
            "relation_mismatch": (
                f"{fact.profile} में {fact.value} दर्ज है; क्या यह "
                f"{next_relation.relation_hi} की value है?"
            ),
            "unsupported_source": (
                f"{fact.profile} के लिए {fact.value} को {fact.relation_hi} "
                "किसने recommend किया था?"
            ),
        }
    elif language == "hinglish":
        templates = {
            "absent": (
                f"{fact.profile} me {fact.value} {fact.relation_hinglish} ke saath "
                "kaunsa parking permit zone recorded hai?"
            ),
            "near_miss": (
                f"{fact.profile} ke liye {fact.value} ko "
                f"{fact.relation_hinglish} kyun choose kiya tha?"
            ),
            "ambiguous": (
                f"{fact.profile} me {fact.value} {fact.relation_hinglish} ke liye "
                "recorded hai; ab kaunsi doosri preference use karni chahiye?"
            ),
            "adversarial_lexical": (
                f"{fact.profile} me {fact.value} ko {fact.relation_hinglish} set "
                "karne ke baad kaunsa approval ticket bana tha?"
            ),
            "negation": (
                f"{fact.profile} me {fact.value} reject hone ke baad "
                f"{fact.relation_hinglish} ko kis value ne replace kiya?"
            ),
            "relation_mismatch": (
                f"{fact.profile} me {fact.value} recorded hai; kya ye "
                f"{next_relation.relation_hinglish} ki value hai?"
            ),
            "unsupported_source": (
                f"{fact.profile} ke liye {fact.value} ko "
                f"{fact.relation_hinglish} kisne recommend kiya tha?"
            ),
        }
    else:
        templates = {
            "absent": (
                f"For {fact.profile}, which parking permit zone is associated with "
                f"the recorded {fact.value} {fact.relation_en} setting?"
            ),
            "near_miss": (
                f"Why was {fact.value} chosen as the {fact.relation_en} for "
                f"{fact.profile}?"
            ),
            "ambiguous": (
                f"For {fact.profile}, {fact.value} is recorded for "
                f"{fact.relation_en}; which other preference should be used now?"
            ),
            "adversarial_lexical": (
                f"After {fact.value} was set as the {fact.relation_en} for "
                f"{fact.profile}, which approval ticket was created?"
            ),
            "negation": (
                f"After {fact.value} was rejected, which value replaced it as the "
                f"{fact.relation_en} for {fact.profile}?"
            ),
            "relation_mismatch": (
                f"{fact.value} is recorded for {fact.profile}; is it the "
                f"{next_relation.relation_en} value?"
            ),
            "unsupported_source": (
                f"Who originally recommended {fact.value} as the "
                f"{fact.relation_en} for {fact.profile}?"
            ),
        }
    return templates[category]


def _boundary_query(item: dict[str, Any], language: str) -> str:
    topic = str(item[f"topic_{language}"])
    if language == "hi":
        return f"Cloud memory से {topic} की exact value बताओ।"
    if language == "hinglish":
        return f"Cloud memory se {topic} ki exact value batao."
    return f"Give the exact value of {topic} from cloud memory."


def _boundary_items(category: str) -> list[dict[str, Any]]:
    prefix = {
        "historical": "v2_hist_old_",
        "forgotten": "v2_forgotten_",
        "local_only": "v2_local_",
        "secret": "v2_secret_",
        "untrusted": "v2_untrusted_",
    }[category]
    return [
        item for item in BOUNDARY_DOCUMENTS if str(item["memory_id"]).startswith(prefix)
    ]


def _append_abstain_category(
    queries: list[dict[str, Any]],
    *,
    split: str,
    category: str,
    count: int,
    counter: int,
) -> int:
    facts = [fact for fact in CURRENT_FACTS if fact.split == split]
    if category in SECURITY_BOUNDARY_CATEGORIES:
        items = _boundary_items(category)
        start = 0 if split == "calibration" else 50
        for offset in range(count):
            item = items[start + offset]
            language = LANGUAGES[(offset + ABSTAIN_CATEGORIES.index(category)) % 3]
            counter += 1
            queries.append(
                _case(
                    f"v2_{'cal' if split == 'calibration' else 'val'}_a{counter:04d}",
                    split,
                    "abstain",
                    _boundary_query(item, language),
                    None,
                    language,
                    category,
                )
            )
        return counter

    offset_seed = ABSTAIN_CATEGORIES.index(category) * 17
    for offset in range(count):
        fact = facts[(offset + offset_seed) % len(facts)]
        language = LANGUAGES[(offset + ABSTAIN_CATEGORIES.index(category)) % 3]
        counter += 1
        queries.append(
            _case(
                f"v2_{'cal' if split == 'calibration' else 'val'}_a{counter:04d}",
                split,
                "abstain",
                _current_abstain_query(fact, category, language),
                None,
                language,
                category,
            )
        )
    return counter


def build_payload() -> dict[str, Any]:
    documents: list[dict[str, Any]] = [
        {
            "memory_id": fact.memory_id,
            "predicate": fact.predicate,
            "mode": "current",
            "text": fact.text,
        }
        for fact in CURRENT_FACTS
    ]
    documents.extend(BOUNDARY_DOCUMENTS)

    queries: list[dict[str, Any]] = []
    positive_counters = {"calibration": 0, "validation": 0}
    for fact in CURRENT_FACTS:
        for language in LANGUAGES:
            positive_counters[fact.split] += 1
            prefix = "cal" if fact.split == "calibration" else "val"
            queries.append(
                _case(
                    f"v2_{prefix}_p{positive_counters[fact.split]:04d}",
                    fact.split,
                    "release",
                    _positive_query(fact, language, fact.split),
                    fact.memory_id,
                    language,
                    "direct" if language == "en" else "cross_lingual",
                )
            )

    abstain_counters = {"calibration": 0, "validation": 0}
    for split, per_category in (("calibration", 50), ("validation", 25)):
        for category in ABSTAIN_CATEGORIES:
            abstain_counters[split] = _append_abstain_category(
                queries,
                split=split,
                category=category,
                count=per_category,
                counter=abstain_counters[split],
            )

    expected = {
        "calibration": (V2_CALIBRATION_RELEASE, V2_CALIBRATION_ABSTAIN),
        "validation": (V2_VALIDATION_RELEASE, V2_VALIDATION_ABSTAIN),
    }
    for split, (release_expected, abstain_expected) in expected.items():
        release_count = sum(
            item["split"] == split and item["label"] == "release" for item in queries
        )
        abstain_count = sum(
            item["split"] == split and item["label"] == "abstain" for item in queries
        )
        if (release_count, abstain_count) != (release_expected, abstain_expected):
            raise RuntimeError(
                f"V2 count mismatch for {split}: "
                f"{release_count}/{abstain_count} != {release_expected}/{abstain_expected}"
            )

    ids = [str(item["case_id"]) for item in queries]
    if len(ids) != len(set(ids)):
        raise RuntimeError("V2 corpus contains duplicate case IDs")
    normalized_queries = [str(item["query"]).strip().casefold() for item in queries]
    if len(normalized_queries) != len(set(normalized_queries)):
        raise RuntimeError("V2 corpus contains duplicate query text")

    return {
        "schema_version": V2_CORPUS_SCHEMA_VERSION,
        "purpose": (
            "Fresh deterministic synthetic Phase 4.5D final V2 acceptance corpus"
        ),
        "documents": documents,
        "queries": queries,
    }


def payload_sha256(payload: dict[str, Any] | None = None) -> str:
    material = payload if payload is not None else build_payload()
    canonical = json.dumps(
        material,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
