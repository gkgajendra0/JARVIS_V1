"""Fresh zero-training answerability cases for Phase 4.5D."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Final

SCHEMA_VERSION: Final = 1
LANGUAGES: Final = ("en", "hi", "hinglish")
QA_ANSWERABLE_KINDS: Final = (
    "direct_current_1",
    "direct_current_2",
    "direct_current_3",
    "direct_current_4",
)
QA_NULL_KINDS: Final = (
    "reason_missing",
    "provenance_missing",
    "successor_missing",
    "related_record_missing",
    "advice_missing",
    "historical_missing",
    "wrong_relation",
    "wrong_subject",
)
NLI_KINDS: Final = (
    "comparison_true",
    "comparison_false",
    "comparison_unknown",
    "negated_true_value",
)


@dataclass(frozen=True, slots=True)
class AnswerabilityFact:
    subject: str
    relation_en: str
    relation_hi: str
    relation_hinglish: str
    value: str
    alternative: str


FACTS: Final = (
    AnswerabilityFact(
        "Aurora stand",
        "screen layout",
        "स्क्रीन लेआउट",
        "screen layout",
        "mosaic-4",
        "column-8",
    ),
    AnswerabilityFact(
        "Bamboo projector",
        "input source",
        "इनपुट सोर्स",
        "input source",
        "source-7",
        "source-2",
    ),
    AnswerabilityFact(
        "Cobalt charger",
        "charge mode",
        "चार्ज मोड",
        "charge mode",
        "steady-6",
        "rapid-3",
    ),
    AnswerabilityFact(
        "Dune thermostat",
        "comfort profile",
        "कम्फर्ट प्रोफ़ाइल",
        "comfort profile",
        "breeze-5",
        "warm-1",
    ),
    AnswerabilityFact(
        "Elm scanner",
        "scan preset",
        "स्कैन प्रीसेट",
        "scan preset",
        "detail-9",
        "quick-2",
    ),
    AnswerabilityFact(
        "Flint headset",
        "voice profile",
        "वॉइस प्रोफ़ाइल",
        "voice profile",
        "clear-8",
        "deep-4",
    ),
    AnswerabilityFact(
        "Glacier console",
        "dashboard mode",
        "डैशबोर्ड मोड",
        "dashboard mode",
        "focus-6",
        "wide-3",
    ),
    AnswerabilityFact(
        "Horizon badge",
        "access profile",
        "एक्सेस प्रोफ़ाइल",
        "access profile",
        "zone-12",
        "zone-5",
    ),
)


def normalized_query(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _relation(fact: AnswerabilityFact, language: str) -> str:
    return {
        "en": fact.relation_en,
        "hi": fact.relation_hi,
        "hinglish": fact.relation_hinglish,
    }[language]


def _canonical_context(fact: AnswerabilityFact, language: str) -> str:
    relation = _relation(fact, language)
    if language == "hi":
        return (
            f"वर्तमान canonical memory: {fact.subject} का {relation} "
            f"{fact.value} है।"
        )
    if language == "hinglish":
        return (
            f"Current canonical memory: {fact.subject} ka {relation} "
            f"{fact.value} hai."
        )
    return f"Current canonical memory: {fact.subject}'s {relation} is {fact.value}."


def _qa_templates() -> dict[str, dict[str, str]]:
    return {
        "en": {
            "direct_current_1": "What current {relation} is stored for {subject}?",
            "direct_current_2": "Tell me {subject}'s current {relation}.",
            "direct_current_3": "Which value is active for {subject}'s {relation} now?",
            "direct_current_4": "Read back the current {relation} for {subject}.",
            "reason_missing": "Why does {subject} use {value} for {relation}?",
            "provenance_missing": "Who selected {value} as {subject}'s {relation}?",
            "successor_missing": (
                "What specifically replaced {alternative} as {subject}'s {relation}, "
                "and when was it replaced?"
            ),
            "related_record_missing": (
                "Which separate linked record belongs to {subject}'s {relation}?"
            ),
            "advice_missing": (
                "Should {subject} change its {relation} from {value} to {alternative}?"
            ),
            "historical_missing": "What was {subject}'s previous {relation} before {value}?",
            "wrong_relation": "What is the current backup schedule for {subject}?",
            "wrong_subject": "What is Canyon device's current {relation}?",
        },
        "hi": {
            "direct_current_1": "{subject} का अभी कौन सा {relation} दर्ज है?",
            "direct_current_2": "{subject} का current {relation} बताओ।",
            "direct_current_3": "अभी {subject} के {relation} में कौन सा value active है?",
            "direct_current_4": "{subject} का वर्तमान {relation} read back करो।",
            "reason_missing": "{subject} के {relation} में {value} क्यों रखा गया है?",
            "provenance_missing": "{subject} का {relation} {value} किसने चुना था?",
            "successor_missing": (
                "{subject} के {relation} में {alternative} को exactly किसने replace किया "
                "और वह कब हुआ?"
            ),
            "related_record_missing": (
                "{subject} के {relation} से कौन सा अलग linked record जुड़ा है?"
            ),
            "advice_missing": (
                "क्या {subject} का {relation} {value} से {alternative} कर देना चाहिए?"
            ),
            "historical_missing": "{value} से पहले {subject} का पिछला {relation} क्या था?",
            "wrong_relation": "{subject} का current backup schedule क्या है?",
            "wrong_subject": "Canyon device का current {relation} क्या है?",
        },
        "hinglish": {
            "direct_current_1": "{subject} ka abhi kaunsa {relation} recorded hai?",
            "direct_current_2": "{subject} ka current {relation} batao.",
            "direct_current_3": "Abhi {subject} ke {relation} me kaunsa value active hai?",
            "direct_current_4": "{subject} ka present {relation} read back karo.",
            "reason_missing": "{subject} ke {relation} me {value} kyun rakha gaya hai?",
            "provenance_missing": "{subject} ka {relation} {value} kisne choose kiya tha?",
            "successor_missing": (
                "{subject} ke {relation} me {alternative} ko exactly kisne replace kiya "
                "aur ye kab hua?"
            ),
            "related_record_missing": (
                "{subject} ke {relation} se kaunsa alag linked record connected hai?"
            ),
            "advice_missing": (
                "Kya {subject} ka {relation} {value} se {alternative} kar dena chahiye?"
            ),
            "historical_missing": "{value} se pehle {subject} ka previous {relation} kya tha?",
            "wrong_relation": "{subject} ka current backup schedule kya hai?",
            "wrong_subject": "Canyon device ka current {relation} kya hai?",
        },
    }


def _nli_templates() -> dict[str, dict[str, tuple[str, str]]]:
    return {
        "en": {
            "comparison_true": (
                "Is {value} still {subject}'s current {relation}?",
                "{subject}'s current {relation} is {value}.",
            ),
            "comparison_false": (
                "Is {alternative} now {subject}'s current {relation}?",
                "{subject}'s current {relation} is {alternative}.",
            ),
            "comparison_unknown": (
                "Is {value} {subject}'s current backup schedule?",
                "{subject}'s current backup schedule is {value}.",
            ),
            "negated_true_value": (
                "{subject}'s current {relation} is not {value}, right?",
                "{subject}'s current {relation} is not {value}.",
            ),
        },
        "hi": {
            "comparison_true": (
                "क्या {subject} का current {relation} अभी भी {value} है?",
                "{subject} का current {relation} {value} है।",
            ),
            "comparison_false": (
                "क्या {subject} का current {relation} अब {alternative} है?",
                "{subject} का current {relation} {alternative} है।",
            ),
            "comparison_unknown": (
                "क्या {subject} का current backup schedule {value} है?",
                "{subject} का current backup schedule {value} है।",
            ),
            "negated_true_value": (
                "{subject} का current {relation} {value} नहीं है, सही?",
                "{subject} का current {relation} {value} नहीं है।",
            ),
        },
        "hinglish": {
            "comparison_true": (
                "Kya {subject} ka current {relation} abhi bhi {value} hai?",
                "{subject} ka current {relation} {value} hai.",
            ),
            "comparison_false": (
                "Kya {subject} ka current {relation} ab {alternative} hai?",
                "{subject} ka current {relation} {alternative} hai.",
            ),
            "comparison_unknown": (
                "Kya {subject} ka current backup schedule {value} hai?",
                "{subject} ka current backup schedule {value} hai.",
            ),
            "negated_true_value": (
                "{subject} ka current {relation} {value} nahi hai na?",
                "{subject} ka current {relation} {value} nahi hai.",
            ),
        },
    }


def _format(template: str, fact: AnswerabilityFact, language: str) -> str:
    return template.format(
        subject=fact.subject,
        relation=_relation(fact, language),
        value=fact.value,
        alternative=fact.alternative,
    )


def build_payload() -> dict[str, object]:
    qa_rows: list[dict[str, object]] = []
    nli_rows: list[dict[str, object]] = []
    qa_templates = _qa_templates()
    nli_templates = _nli_templates()

    for fact_index, fact in enumerate(FACTS, start=1):
        for language in LANGUAGES:
            context = _canonical_context(fact, language)
            for kind in QA_ANSWERABLE_KINDS + QA_NULL_KINDS:
                query = _format(qa_templates[language][kind], fact, language)
                qa_rows.append(
                    {
                        "case_id": f"ans_v1_qa_{fact_index:02d}_{language}_{kind}",
                        "language": language,
                        "kind": kind,
                        "question": query,
                        "context": context,
                        "expected_answer": (
                            fact.value if kind in QA_ANSWERABLE_KINDS else ""
                        ),
                        "expected_answerable": kind in QA_ANSWERABLE_KINDS,
                        "subject": fact.subject,
                        "relation": _relation(fact, language),
                        "value": fact.value,
                    }
                )

            for kind in NLI_KINDS:
                question_template, hypothesis_template = nli_templates[language][kind]
                question = _format(question_template, fact, language)
                hypothesis = _format(hypothesis_template, fact, language)
                expected_label = {
                    "comparison_true": "entailment",
                    "comparison_false": "contradiction",
                    "comparison_unknown": "neutral",
                    "negated_true_value": "contradiction",
                }[kind]
                nli_rows.append(
                    {
                        "case_id": f"ans_v1_nli_{fact_index:02d}_{language}_{kind}",
                        "language": language,
                        "kind": kind,
                        "question": question,
                        "premise": context,
                        "hypothesis": hypothesis,
                        "expected_label": expected_label,
                        "subject": fact.subject,
                        "relation": _relation(fact, language),
                        "value": fact.value,
                    }
                )

    return {
        "schema_version": SCHEMA_VERSION,
        "qa_cases": qa_rows,
        "nli_cases": nli_rows,
    }


def payload_sha256(payload: dict[str, object] | None = None) -> str:
    target = build_payload() if payload is None else payload
    raw = json.dumps(
        target,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def public_summary() -> dict[str, object]:
    payload = build_payload()
    qa_rows = payload["qa_cases"]
    nli_rows = payload["nli_cases"]
    assert isinstance(qa_rows, list)
    assert isinstance(nli_rows, list)
    return {
        "schema_version": SCHEMA_VERSION,
        "languages": list(LANGUAGES),
        "fact_count": len(FACTS),
        "qa_cases": len(qa_rows),
        "qa_answerable_cases": sum(
            bool(row["expected_answerable"]) for row in qa_rows
        ),
        "qa_null_cases": sum(not bool(row["expected_answerable"]) for row in qa_rows),
        "nli_cases": len(nli_rows),
        "payload_sha256": payload_sha256(payload),
    }
