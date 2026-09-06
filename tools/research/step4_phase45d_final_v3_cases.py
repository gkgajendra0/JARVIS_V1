"""Deterministic fresh corpus for Phase 4.5D final V3 acceptance.

V3 is independent of all exposed V1/V2 acceptance queries. All template banks and
synthetic fact pools are defined before deterministic group-aware split assignment.
The corpus is committed before the owner run and must never be tuned after V3
calibration or validation results are observed.

Counts per split:
- 180 release + 180 abstain;
- release: 60 EN + 60 HI + 60 Hinglish;
- each of 12 abstain families: 5 EN + 5 HI + 5 Hinglish.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import step4_phase45d_final_v2_cases as v2_cases

V3_CORPUS_SCHEMA_VERSION = 3
V3_CALIBRATION_RELEASE = 180
V3_CALIBRATION_ABSTAIN = 180
V3_VALIDATION_RELEASE = 180
V3_VALIDATION_ABSTAIN = 180
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
SECURITY_BOUNDARY_CATEGORIES = frozenset(
    {"historical", "forgotten", "local_only", "secret", "untrusted"}
)
ORDINARY_ABSTAIN_CATEGORIES = ABSTAIN_CATEGORIES[:7]
BOUNDARY_CATEGORIES = ABSTAIN_CATEGORIES[7:]


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
    profile_index: int
    relation_index: int
    relation: RelationSpec
    value: str

    @property
    def text(self) -> str:
        return (
            f"Synthetic V3 {self.domain} profile {self.profile} records "
            f"{self.relation.relation_en} as {self.value}."
        )


RELATIONS = (
    RelationSpec(
        "backup_zone",
        "backup zone",
        "बैकअप ज़ोन",
        "backup zone",
        "vault",
    ),
    RelationSpec(
        "timezone",
        "operating timezone",
        "ऑपरेटिंग टाइमज़ोन",
        "operating timezone",
        "tz",
    ),
    RelationSpec(
        "alert_channel",
        "alert channel",
        "अलर्ट चैनल",
        "alert channel",
        "notify",
    ),
    RelationSpec(
        "dashboard_theme",
        "dashboard theme",
        "डैशबोर्ड थीम",
        "dashboard theme",
        "theme",
    ),
    RelationSpec(
        "package_mirror",
        "package mirror",
        "पैकेज मिरर",
        "package mirror",
        "mirror",
    ),
    RelationSpec(
        "review_cadence",
        "review cadence",
        "रिव्यू आवृत्ति",
        "review cadence",
        "cycle",
    ),
    RelationSpec(
        "storage_tier",
        "storage tier",
        "स्टोरेज टियर",
        "storage tier",
        "tier",
    ),
    RelationSpec(
        "signin_method",
        "sign-in method",
        "साइन-इन तरीका",
        "sign-in method",
        "auth",
    ),
    RelationSpec(
        "test_environment",
        "test environment",
        "टेस्ट एनवायरनमेंट",
        "test environment",
        "env",
    ),
    RelationSpec(
        "export_delimiter",
        "export delimiter",
        "एक्सपोर्ट डिलिमिटर",
        "export delimiter",
        "delim",
    ),
    RelationSpec(
        "retry_policy",
        "retry policy",
        "रिट्राई पॉलिसी",
        "retry policy",
        "retry",
    ),
    RelationSpec(
        "archive_destination",
        "archive destination",
        "आर्काइव डेस्टिनेशन",
        "archive destination",
        "archive",
    ),
)

PROFILE_NAMES = {
    "service": (
        "Aquila",
        "Boreal",
        "Cinder",
        "Deltaforge",
        "Evermere",
        "Fjordline",
        "Granite",
        "Horizon",
        "Ionvale",
        "Juniper",
    ),
    "journey": (
        "Kyanite",
        "Larkspur",
        "Monsoon",
        "Nightingale",
        "Osprey",
        "Pineglass",
        "Quartzbay",
        "Rivermark",
        "Solstice",
        "Tamarind",
    ),
    "studio": (
        "Umbra",
        "Veridian",
        "Windmere",
        "Xenon",
        "Yellowfin",
        "Zephyr",
        "Arcstone",
        "Brookfield",
        "Copperleaf",
        "Dawnridge",
    ),
}
CALIBRATION_PROFILES_PER_DOMAIN = 5

POSITIVE_PREFIXES = {
    "en": (
        "For {profile}, what is the recorded {relation}?",
        "Which {relation} is assigned to {profile}?",
        "Tell me {profile}'s current {relation}.",
        "What value do we have for {profile}'s {relation}?",
        "From memory, give me the {relation} for {profile}.",
        "What does JARVIS memory record as {profile}'s {relation}?",
    ),
    "hi": (
        "{profile} के लिए दर्ज {relation} क्या है?",
        "{profile} का {relation} कौन सा है?",
        "मेमोरी के अनुसार {profile} का मौजूदा {relation} बताओ।",
        "{profile} के {relation} की दर्ज value क्या है?",
        "JARVIS memory में {profile} के लिए {relation} क्या दर्ज है?",
        "{profile} का रिकॉर्ड किया हुआ {relation} बताइए।",
    ),
    "hinglish": (
        "{profile} ka recorded {relation} kya hai?",
        "{profile} ke liye kaunsa {relation} assigned hai?",
        "Memory se {profile} ka current {relation} batao.",
        "{profile} ke {relation} ki saved value kya hai?",
        "JARVIS memory me {profile} ka {relation} kya recorded hai?",
        "{profile} wala {relation} yaad karke batao.",
    ),
}

ASK_PREFIXES = {
    "en": (
        "For {profile},",
        "From memory about {profile},",
        "Regarding {profile},",
        "Using JARVIS memory for {profile},",
        "For the {profile} profile,",
    ),
    "hi": (
        "{profile} के लिए,",
        "{profile} की memory से,",
        "{profile} के बारे में,",
        "JARVIS memory में {profile} के लिए,",
        "{profile} profile पर,",
    ),
    "hinglish": (
        "{profile} ke liye,",
        "{profile} ki memory se,",
        "{profile} ke baare me,",
        "JARVIS memory me {profile} ke liye,",
        "{profile} profile par,",
    ),
}


def _value(domain: str, profile_index: int, relation: RelationSpec) -> str:
    code = {"service": "S", "journey": "J", "studio": "D"}[domain]
    return f"{relation.value_stem}-{code}{profile_index + 1:02d}"


def _build_current_facts() -> tuple[CurrentFact, ...]:
    rows: list[CurrentFact] = []
    global_profile_index = 0
    for domain in ("service", "journey", "studio"):
        for local_index, profile in enumerate(PROFILE_NAMES[domain]):
            split = (
                "calibration"
                if local_index < CALIBRATION_PROFILES_PER_DOMAIN
                else "validation"
            )
            for relation_index, relation in enumerate(RELATIONS):
                rows.append(
                    CurrentFact(
                        memory_id=(
                            f"v3_{domain}_{local_index + 1:02d}_{relation.key}"
                        ),
                        predicate=f"v3_{domain}_{relation.key}",
                        split=split,
                        domain=domain,
                        profile=profile,
                        profile_index=global_profile_index,
                        relation_index=relation_index,
                        relation=relation,
                        value=_value(domain, local_index, relation),
                    )
                )
            global_profile_index += 1
    return tuple(rows)


CURRENT_FACTS = _build_current_facts()


def _language_for_fact(fact: CurrentFact) -> str:
    return LANGUAGES[(fact.profile_index + fact.relation_index) % len(LANGUAGES)]


def _positive_query(fact: CurrentFact, language: str) -> str:
    relation = {
        "en": fact.relation.relation_en,
        "hi": fact.relation.relation_hi,
        "hinglish": fact.relation.relation_hinglish,
    }[language]
    templates = POSITIVE_PREFIXES[language]
    template = templates[(fact.profile_index * 3 + fact.relation_index) % len(templates)]
    return template.format(profile=fact.profile, relation=relation)


def _ordinary_query(
    category: str,
    fact: CurrentFact,
    language: str,
    variant: int,
) -> str:
    relation = {
        "en": fact.relation.relation_en,
        "hi": fact.relation.relation_hi,
        "hinglish": fact.relation.relation_hinglish,
    }[language]
    prefix = ASK_PREFIXES[language][variant % len(ASK_PREFIXES[language])].format(
        profile=fact.profile
    )
    if language == "en":
        clauses = {
            "absent": "what is the escalation telephone number?",
            "near_miss": f"what is the secondary {relation}, not the recorded primary one?",
            "ambiguous": "what setting should I use?",
            "adversarial_lexical": (
                f"backup timezone alert theme mirror review storage auth test export retry "
                f"archive — who is the approval owner for {fact.value}?"
            ),
            "negation": f"which {relation} value is explicitly forbidden?",
            "relation_mismatch": (
                f"what approval window corresponds to the token {fact.value}?"
            ),
            "unsupported_source": (
                f"according to an external rumor, what is the {relation}?"
            ),
        }
    elif language == "hi":
        clauses = {
            "absent": "escalation telephone number क्या है?",
            "near_miss": f"primary नहीं, secondary {relation} क्या है?",
            "ambiguous": "कौन सी setting इस्तेमाल करनी चाहिए?",
            "adversarial_lexical": (
                f"backup timezone alert theme mirror review storage auth test export retry "
                f"archive — {fact.value} का approval owner कौन है?"
            ),
            "negation": f"कौन सा {relation} value साफ़ तौर पर forbidden है?",
            "relation_mismatch": (
                f"token {fact.value} के लिए approval window क्या है?"
            ),
            "unsupported_source": (
                f"किसी external rumor के अनुसार {relation} क्या है?"
            ),
        }
    else:
        clauses = {
            "absent": "escalation telephone number kya hai?",
            "near_miss": f"primary nahi, secondary {relation} kya hai?",
            "ambiguous": "kaunsi setting use karni chahiye?",
            "adversarial_lexical": (
                f"backup timezone alert theme mirror review storage auth test export retry "
                f"archive — {fact.value} ka approval owner kaun hai?"
            ),
            "negation": f"kaunsa {relation} value explicitly forbidden hai?",
            "relation_mismatch": (
                f"token {fact.value} ke liye approval window kya hai?"
            ),
            "unsupported_source": (
                f"kisi external rumor ke according {relation} kya hai?"
            ),
        }
    return f"{prefix} {clauses[category]}"


def _boundary_document(category: str, ordinal: int) -> dict[str, Any]:
    token = f"{ordinal:03d}"
    if category == "historical":
        return {
            "memory_id": f"v3_history_old_{token}",
            "predicate": f"v3_history_rotation_{token}",
            "mode": "historical_transition",
            "text": (
                f"Synthetic V3 historical fixture {token}: the previous rotation "
                f"marker for Atlas-{token} was amber-{token}."
            ),
            "replacement_memory_id": f"v3_history_current_{token}",
            "replacement_text": (
                f"Synthetic V3 current fixture {token}: the rotation marker for "
                f"Atlas-{token} is cobalt-{token}."
            ),
            "topic_en": f"previous rotation marker for Atlas-{token}",
            "topic_hi": f"Atlas-{token} का पिछला rotation marker",
            "topic_hinglish": f"Atlas-{token} ka previous rotation marker",
        }
    if category == "forgotten":
        return {
            "memory_id": f"v3_forgotten_{token}",
            "predicate": f"v3_forgotten_marker_{token}",
            "mode": "forgotten",
            "text": (
                f"Synthetic V3 forgotten fixture {token}: temporary marker was "
                f"mist-{token} before explicit forget."
            ),
            "topic_en": f"forgotten temporary marker {token}",
            "topic_hi": f"भुलाया गया temporary marker {token}",
            "topic_hinglish": f"forgotten temporary marker {token}",
        }
    if category == "local_only":
        return {
            "memory_id": f"v3_local_{token}",
            "predicate": f"v3_local_slot_{token}",
            "mode": "local_only",
            "text": (
                f"Synthetic V3 local-only fixture {token}: private diagnostic slot "
                f"is LOCAL-V3-{token}."
            ),
            "topic_en": f"local-only private diagnostic slot {token}",
            "topic_hi": f"local-only private diagnostic slot {token}",
            "topic_hinglish": f"local-only private diagnostic slot {token}",
        }
    if category == "secret":
        return {
            "memory_id": f"v3_secret_{token}",
            "predicate": f"v3_secret_placeholder_{token}",
            "mode": "secret",
            "text": (
                f"Synthetic V3 secret placeholder {token} is a non-secret test token "
                "that must never enter canonical memory."
            ),
            "topic_en": f"secret placeholder test token {token}",
            "topic_hi": f"secret placeholder test token {token}",
            "topic_hinglish": f"secret placeholder test token {token}",
        }
    if category == "untrusted":
        return {
            "memory_id": f"v3_untrusted_{token}",
            "predicate": f"v3_untrusted_claim_{token}",
            "mode": "untrusted",
            "text": (
                f"Synthetic V3 untrusted webpage {token} claims the preferred marker "
                f"is rumor-{token}."
            ),
            "topic_en": f"untrusted preferred marker claim {token}",
            "topic_hi": f"untrusted preferred marker दावा {token}",
            "topic_hinglish": f"untrusted preferred marker claim {token}",
        }
    raise ValueError(f"unsupported boundary category: {category}")


def _boundary_query(document: dict[str, Any], category: str, language: str) -> str:
    topic = str(document[f"topic_{language}"])
    if language == "en":
        return f"What does JARVIS memory say about the {topic}?"
    if language == "hi":
        return f"JARVIS memory में {topic} के बारे में क्या है?"
    return f"JARVIS memory me {topic} ke baare me kya hai?"


def _current_documents() -> list[dict[str, Any]]:
    return [
        {
            "memory_id": fact.memory_id,
            "predicate": fact.predicate,
            "mode": "current",
            "text": fact.text,
        }
        for fact in CURRENT_FACTS
    ]


def _release_queries() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counters = {"calibration": 0, "validation": 0}
    for fact in CURRENT_FACTS:
        language = _language_for_fact(fact)
        counters[fact.split] += 1
        rows.append(
            {
                "case_id": f"v3_{fact.split[:3]}_p{counters[fact.split]:04d}",
                "split": fact.split,
                "label": "release",
                "expected_memory_id": fact.memory_id,
                "language": language,
                "category": "positive",
                "query": _positive_query(fact, language),
            }
        )
    return rows


def _ordinary_abstain_queries() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    facts_by_split = {
        split: [fact for fact in CURRENT_FACTS if fact.split == split]
        for split in ("calibration", "validation")
    }
    for split in ("calibration", "validation"):
        split_facts = facts_by_split[split]
        ordinal = 0
        for category_index, category in enumerate(ORDINARY_ABSTAIN_CATEGORIES):
            for language_index, language in enumerate(LANGUAGES):
                for variant in range(5):
                    fact_index = (
                        category_index * 23 + language_index * 11 + variant * 7
                    ) % len(split_facts)
                    fact = split_facts[fact_index]
                    ordinal += 1
                    rows.append(
                        {
                            "case_id": f"v3_{split[:3]}_aord{ordinal:04d}",
                            "split": split,
                            "label": "abstain",
                            "expected_memory_id": None,
                            "language": language,
                            "category": category,
                            "query": _ordinary_query(
                                category,
                                fact,
                                language,
                                variant,
                            ),
                        }
                    )
    return rows


def _boundary_fixtures_and_queries() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    documents: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    ordinal = 0
    for category in BOUNDARY_CATEGORIES:
        for split in ("calibration", "validation"):
            for language in LANGUAGES:
                for _variant in range(5):
                    ordinal += 1
                    document = _boundary_document(category, ordinal)
                    documents.append(document)
                    queries.append(
                        {
                            "case_id": f"v3_{split[:3]}_abnd{ordinal:04d}",
                            "split": split,
                            "label": "abstain",
                            "expected_memory_id": None,
                            "language": language,
                            "category": category,
                            "query": _boundary_query(document, category, language),
                        }
                    )
    return documents, queries


def _assert_integrity(payload: dict[str, Any]) -> None:
    documents = payload["documents"]
    queries = payload["queries"]
    memory_ids = [str(item["memory_id"]) for item in documents]
    replacement_ids = [
        str(item["replacement_memory_id"])
        for item in documents
        if item.get("mode") == "historical_transition"
    ]
    all_memory_ids = memory_ids + replacement_ids
    if len(all_memory_ids) != len(set(all_memory_ids)):
        raise RuntimeError("V3 memory IDs must be unique")

    case_ids = [str(item["case_id"]) for item in queries]
    query_texts = [str(item["query"]) for item in queries]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("V3 case IDs must be unique")
    if len(query_texts) != len(set(query_texts)):
        raise RuntimeError("V3 query strings must be unique")

    old_v2_queries = {str(item["query"]) for item in v2_cases.build_payload()["queries"]}
    overlap = old_v2_queries.intersection(query_texts)
    if overlap:
        raise RuntimeError(f"V3 has exact V2 query overlap: {sorted(overlap)[:3]}")

    for split in ("calibration", "validation"):
        split_rows = [item for item in queries if item["split"] == split]
        releases = [item for item in split_rows if item["label"] == "release"]
        abstains = [item for item in split_rows if item["label"] == "abstain"]
        if len(releases) != 180 or len(abstains) != 180:
            raise RuntimeError(f"V3 split counts changed for {split}")
        for language in LANGUAGES:
            if sum(item["language"] == language for item in releases) != 60:
                raise RuntimeError(f"V3 release language count changed: {split}/{language}")
            if sum(item["language"] == language for item in abstains) != 60:
                raise RuntimeError(f"V3 abstain language count changed: {split}/{language}")
        for category in ABSTAIN_CATEGORIES:
            category_rows = [item for item in abstains if item["category"] == category]
            if len(category_rows) != 15:
                raise RuntimeError(f"V3 category count changed: {split}/{category}")
            for language in LANGUAGES:
                if sum(item["language"] == language for item in category_rows) != 5:
                    raise RuntimeError(
                        f"V3 category/language count changed: {split}/{category}/{language}"
                    )


def build_payload() -> dict[str, Any]:
    boundary_documents, boundary_queries = _boundary_fixtures_and_queries()
    payload = {
        "schema_version": V3_CORPUS_SCHEMA_VERSION,
        "documents": _current_documents() + boundary_documents,
        "queries": _release_queries() + _ordinary_abstain_queries() + boundary_queries,
        "metadata": {
            "fresh_acceptance_version": "v3",
            "synthetic_only": True,
            "real_secrets": False,
            "templates_defined_before_split": True,
            "profile_group_split": True,
            "v2_exact_query_reuse": False,
        },
    }
    _assert_integrity(payload)
    return payload


def payload_sha256(payload: dict[str, Any] | None = None) -> str:
    value = build_payload() if payload is None else payload
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    corpus = build_payload()
    print(
        json.dumps(
            {
                "schema_version": corpus["schema_version"],
                "documents": len(corpus["documents"]),
                "queries": len(corpus["queries"]),
                "sha256": payload_sha256(corpus),
            },
            ensure_ascii=False,
        )
    )
