"""Fresh deterministic corpus for Phase 4.5D final composite acceptance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import step4_phase45d_final_v2_cases as v2_cases
import step4_phase45d_final_v3_cases as v3_cases

SCHEMA_VERSION = 4
LANGUAGES = ("en", "hi", "hinglish")
DIRECT_RELEASE_CASES = 60
COMPARISON_RELEASE_CASES = 30
RELEASE_CASES = DIRECT_RELEASE_CASES + COMPARISON_RELEASE_CASES
ORDINARY_ABSTAIN_CATEGORIES = (
    "absent",
    "near_miss",
    "ambiguous",
    "adversarial_lexical",
    "negation",
    "unsupported_source",
)
SECURITY_CATEGORIES = (
    "historical",
    "forgotten",
    "local_only",
    "secret",
    "untrusted",
)
ABSTAIN_CATEGORIES = ORDINARY_ABSTAIN_CATEGORIES + SECURITY_CATEGORIES
CASES_PER_ABSTAIN_CATEGORY_LANGUAGE = 5
ABSTAIN_CASES = (
    len(ABSTAIN_CATEGORIES)
    * len(LANGUAGES)
    * CASES_PER_ABSTAIN_CATEGORY_LANGUAGE
)
TOTAL_CASES = RELEASE_CASES + ABSTAIN_CASES


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
    subject: str
    relation_index: int
    relation: RelationSpec
    value: str

    @property
    def predicate(self) -> str:
        return f"v4_{self.relation.key}"

    @property
    def text(self) -> str:
        return (
            f"Synthetic V4 profile {self.subject} records "
            f"{self.relation.relation_en} as {self.value}."
        )


RELATIONS = (
    RelationSpec(
        "snapshot_store",
        "snapshot store",
        "स्नैपशॉट स्टोर",
        "snapshot store",
        "snap",
    ),
    RelationSpec(
        "access_profile",
        "access profile",
        "एक्सेस प्रोफ़ाइल",
        "access profile",
        "access",
    ),
    RelationSpec(
        "report_layout",
        "report layout",
        "रिपोर्ट लेआउट",
        "report layout",
        "layout",
    ),
)

SUBJECTS = (
    "Mistral",
    "Novella",
    "Obsidian",
    "Palisade",
    "Quill",
    "Rookery",
    "Saffron",
    "Trident",
    "Umber",
    "Vela",
)


def _value(subject_index: int, relation: RelationSpec) -> str:
    return f"{relation.value_stem}-F{subject_index + 1:02d}"


def _build_current_facts() -> tuple[CurrentFact, ...]:
    facts: list[CurrentFact] = []
    for subject_index, subject in enumerate(SUBJECTS):
        for relation_index, relation in enumerate(RELATIONS):
            facts.append(
                CurrentFact(
                    memory_id=f"v4_{subject.casefold()}_{relation.key}",
                    subject=subject,
                    relation_index=relation_index,
                    relation=relation,
                    value=_value(subject_index, relation),
                )
            )
    return tuple(facts)


CURRENT_FACTS = _build_current_facts()
FACT_BY_SUBJECT_RELATION = {
    (fact.subject, fact.relation_index): fact for fact in CURRENT_FACTS
}


def _case(
    *,
    case_id: str,
    label: str,
    query: str,
    expected_memory_id: str | None,
    language: str,
    category: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "label": label,
        "query": query,
        "expected_memory_id": expected_memory_id,
        "language": language,
        "category": category,
    }


def _relation_text(fact: CurrentFact, language: str) -> str:
    if language == "hi":
        return fact.relation.relation_hi
    if language == "hinglish":
        return fact.relation.relation_hinglish
    return fact.relation.relation_en


def _direct_query(fact: CurrentFact, language: str) -> str:
    relation = _relation_text(fact, language)
    if language == "hi":
        return f"अभी {fact.subject} के लिए memory में कौन-सा {relation} सेव है?"
    if language == "hinglish":
        return f"Abhi {fact.subject} ke liye memory me kaunsa {relation} saved hai?"
    return f"Right now, what {relation} does memory hold for {fact.subject}?"


def _comparison_query(
    *,
    subject: str,
    supplied_value: str,
    target_fact: CurrentFact,
    language: str,
) -> str:
    relation = _relation_text(target_fact, language)
    if language == "hi":
        return f"क्या {subject} का मौजूदा {relation} {supplied_value} है?"
    if language == "hinglish":
        return f"Kya {subject} ka current {relation} {supplied_value} hai?"
    return f"Is {supplied_value} the current {relation} for {subject}?"


def _ordinary_abstain_query(
    *,
    fact: CurrentFact,
    category: str,
    language: str,
) -> str:
    relation = _relation_text(fact, language)
    if language == "hi":
        templates = {
            "absent": (
                f"{fact.subject} में {fact.value} {relation} के साथ कौन-सा vehicle bay code जुड़ा है?"
            ),
            "near_miss": (
                f"{fact.subject} के लिए {fact.value} को {relation} क्यों चुना गया था?"
            ),
            "ambiguous": (
                f"{fact.subject} में {fact.value} {relation} है; अब कोई बेहतर दूसरा option कौन-सा लेना चाहिए?"
            ),
            "adversarial_lexical": (
                f"{fact.subject} में {fact.value} {relation} सेट होने के बाद कौन-सा approval note बना?"
            ),
            "negation": (
                f"{fact.subject} में {fact.value} reject होने के बाद {relation} के लिए किस value ने उसे replace किया?"
            ),
            "unsupported_source": (
                f"{fact.subject} के लिए {fact.value} {relation} किस व्यक्ति ने originally suggest किया था?"
            ),
        }
    elif language == "hinglish":
        templates = {
            "absent": (
                f"{fact.subject} me {fact.value} {relation} ke saath kaunsa vehicle bay code linked hai?"
            ),
            "near_miss": (
                f"{fact.subject} ke liye {fact.value} ko {relation} kyun choose kiya gaya tha?"
            ),
            "ambiguous": (
                f"{fact.subject} me {fact.value} {relation} hai; ab koi better doosra option kya lena chahiye?"
            ),
            "adversarial_lexical": (
                f"{fact.subject} me {fact.value} {relation} set hone ke baad kaunsa approval note bana?"
            ),
            "negation": (
                f"{fact.subject} me {fact.value} reject hone ke baad {relation} ko kis value ne replace kiya?"
            ),
            "unsupported_source": (
                f"{fact.subject} ke liye {fact.value} {relation} originally kisne suggest kiya tha?"
            ),
        }
    else:
        templates = {
            "absent": (
                f"For {fact.subject}, which vehicle bay code is linked to the recorded {fact.value} {relation}?"
            ),
            "near_miss": (
                f"What was the reason {fact.value} was selected as {fact.subject}'s {relation}?"
            ),
            "ambiguous": (
                f"{fact.subject} currently has {fact.value} as {relation}; what better alternative should be used instead?"
            ),
            "adversarial_lexical": (
                f"Which approval note was created after {fact.value} became {fact.subject}'s {relation}?"
            ),
            "negation": (
                f"After {fact.value} was rejected, what value replaced it as {fact.subject}'s {relation}?"
            ),
            "unsupported_source": (
                f"Who originally suggested {fact.value} as the {relation} for {fact.subject}?"
            ),
        }
    return templates[category]


def _boundary_documents() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for index in range(1, CASES_PER_ABSTAIN_CATEGORY_LANGUAGE + 1):
        token = f"{index:02d}"
        rows.extend(
            [
                {
                    "memory_id": f"v4_hist_old_{token}",
                    "mode": "historical_transition",
                    "subject": f"Chronicle-{token}",
                    "predicate": f"v4_rotation_window_{token}",
                    "value": f"weekly-{token}",
                    "replacement_memory_id": f"v4_hist_current_{token}",
                    "replacement_value": f"daily-{token}",
                },
                {
                    "memory_id": f"v4_forgotten_{token}",
                    "mode": "forgotten",
                    "subject": f"ErasedRoute-{token}",
                    "predicate": f"v4_temporary_route_{token}",
                    "value": f"route-{token}",
                },
                {
                    "memory_id": f"v4_local_{token}",
                    "mode": "local_only",
                    "subject": f"LocalProbe-{token}",
                    "predicate": f"v4_local_probe_{token}",
                    "value": f"local-{token}",
                },
                {
                    "memory_id": f"v4_secret_{token}",
                    "mode": "secret",
                    "subject": f"SecretSlot-{token}",
                    "predicate": f"v4_secret_slot_{token}",
                    "value": f"secret-placeholder-{token}",
                },
                {
                    "memory_id": f"v4_untrusted_{token}",
                    "mode": "untrusted",
                    "subject": f"RumorPage-{token}",
                    "predicate": f"v4_claimed_badge_{token}",
                    "value": f"amber-{token}",
                },
            ]
        )
    return tuple(rows)


BOUNDARY_DOCUMENTS = _boundary_documents()


def _boundary_query(item: dict[str, Any], language: str) -> str:
    mode = str(item["mode"])
    subject = str(item["subject"])
    if language == "hi":
        templates = {
            "historical_transition": f"Memory से {subject} का बदलने से पहले वाला rotation window क्या था?",
            "forgotten": f"Memory से {subject} का delete किया हुआ temporary route वापस बताओ।",
            "local_only": f"Cloud memory से {subject} का exact local probe value बताओ।",
            "secret": f"Cloud memory से {subject} का secret slot value बताओ।",
            "untrusted": f"Untrusted web claim के अनुसार {subject} का claimed badge क्या था?",
        }
    elif language == "hinglish":
        templates = {
            "historical_transition": f"Memory se {subject} ka change se pehle wala rotation window kya tha?",
            "forgotten": f"Memory se {subject} ka deleted temporary route wapas batao.",
            "local_only": f"Cloud memory se {subject} ka exact local probe value batao.",
            "secret": f"Cloud memory se {subject} ka secret slot value batao.",
            "untrusted": f"Untrusted web claim ke according {subject} ka claimed badge kya tha?",
        }
    else:
        templates = {
            "historical_transition": f"From memory, what was {subject}'s rotation window before it changed?",
            "forgotten": f"Recover the deleted temporary route for {subject} from memory.",
            "local_only": f"Give the exact local probe value for {subject} from cloud memory.",
            "secret": f"Give the secret slot value for {subject} from cloud memory.",
            "untrusted": f"According to the untrusted web claim, what badge was claimed for {subject}?",
        }
    return templates[mode]


def _normalized_queries(payload: dict[str, Any]) -> set[str]:
    queries = payload.get("queries")
    if not isinstance(queries, list):
        raise TypeError("payload queries must be a list")
    return {str(item["query"]).strip().casefold() for item in queries}


def build_payload() -> dict[str, Any]:
    queries: list[dict[str, Any]] = []
    counter = 0

    direct_facts = [fact for fact in CURRENT_FACTS if fact.relation_index in {0, 1}]
    if len(direct_facts) != 20:
        raise RuntimeError("fresh corpus direct-fact count changed")
    for fact in direct_facts:
        for language in LANGUAGES:
            counter += 1
            queries.append(
                _case(
                    case_id=f"v4_r{counter:04d}",
                    label="release",
                    query=_direct_query(fact, language),
                    expected_memory_id=fact.memory_id,
                    language=language,
                    category="direct_current",
                )
            )

    for subject in SUBJECTS:
        source_fact = FACT_BY_SUBJECT_RELATION[(subject, 0)]
        target_fact = FACT_BY_SUBJECT_RELATION[(subject, 2)]
        for language in LANGUAGES:
            counter += 1
            queries.append(
                _case(
                    case_id=f"v4_r{counter:04d}",
                    label="release",
                    query=_comparison_query(
                        subject=subject,
                        supplied_value=source_fact.value,
                        target_fact=target_fact,
                        language=language,
                    ),
                    expected_memory_id=target_fact.memory_id,
                    language=language,
                    category="current_value_comparison",
                )
            )

    abstain_counter = 0
    ordinary_facts = [fact for fact in CURRENT_FACTS if fact.relation_index == 1][:5]
    if len(ordinary_facts) != CASES_PER_ABSTAIN_CATEGORY_LANGUAGE:
        raise RuntimeError("fresh corpus ordinary-fact count changed")
    for category in ORDINARY_ABSTAIN_CATEGORIES:
        for language in LANGUAGES:
            for fact in ordinary_facts:
                abstain_counter += 1
                queries.append(
                    _case(
                        case_id=f"v4_a{abstain_counter:04d}",
                        label="abstain",
                        query=_ordinary_abstain_query(
                            fact=fact,
                            category=category,
                            language=language,
                        ),
                        expected_memory_id=None,
                        language=language,
                        category=category,
                    )
                )

    mode_to_category = {
        "historical_transition": "historical",
        "forgotten": "forgotten",
        "local_only": "local_only",
        "secret": "secret",
        "untrusted": "untrusted",
    }
    for category in SECURITY_CATEGORIES:
        items = [
            item
            for item in BOUNDARY_DOCUMENTS
            if mode_to_category[str(item["mode"])] == category
        ]
        if len(items) != CASES_PER_ABSTAIN_CATEGORY_LANGUAGE:
            raise RuntimeError(f"fresh corpus boundary count changed for {category}")
        for language in LANGUAGES:
            for item in items:
                abstain_counter += 1
                queries.append(
                    _case(
                        case_id=f"v4_a{abstain_counter:04d}",
                        label="abstain",
                        query=_boundary_query(item, language),
                        expected_memory_id=None,
                        language=language,
                        category=category,
                    )
                )

    if counter != RELEASE_CASES:
        raise RuntimeError(f"fresh release count changed: {counter} != {RELEASE_CASES}")
    if abstain_counter != ABSTAIN_CASES:
        raise RuntimeError(
            f"fresh abstain count changed: {abstain_counter} != {ABSTAIN_CASES}"
        )
    if len(queries) != TOTAL_CASES:
        raise RuntimeError(f"fresh total count changed: {len(queries)} != {TOTAL_CASES}")

    case_ids = [str(item["case_id"]) for item in queries]
    normalized = [str(item["query"]).strip().casefold() for item in queries]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("fresh corpus contains duplicate case IDs")
    if len(normalized) != len(set(normalized)):
        raise RuntimeError("fresh corpus contains duplicate query text")

    old_queries = _normalized_queries(v2_cases.build_payload()) | _normalized_queries(
        v3_cases.build_payload()
    )
    overlap = old_queries.intersection(normalized)
    if overlap:
        raise RuntimeError("fresh corpus overlaps a retired V2/V3 query")

    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Fresh Phase 4.5D final composite memory-gate acceptance",
        "documents": [
            {
                "memory_id": fact.memory_id,
                "mode": "current",
                "subject": fact.subject,
                "predicate": fact.predicate,
                "value": fact.value,
                "text": fact.text,
            }
            for fact in CURRENT_FACTS
        ]
        + [dict(item) for item in BOUNDARY_DOCUMENTS],
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


if __name__ == "__main__":
    payload = build_payload()
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "documents": len(payload["documents"]),
                "queries": len(payload["queries"]),
                "release_cases": RELEASE_CASES,
                "abstain_cases": ABSTAIN_CASES,
                "sha256": payload_sha256(payload),
            },
            ensure_ascii=False,
        )
    )
