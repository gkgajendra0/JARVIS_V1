"""Development-only fresh cases for the Phase 4.5D task-specific guard bake-off."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Final

SCHEMA_VERSION: Final = 1
LANGUAGES: Final = ("en", "hi", "hinglish")
LABELS: Final = (
    "current_value",
    "current_value_comparison",
    "reason_explanation",
    "provenance_actor",
    "replacement_successor",
    "related_record",
    "negated_or_contradicted",
    "other_or_advice",
)
ALLOW_LABELS: Final = frozenset({"current_value", "current_value_comparison"})
TRAIN_FACTS = 12
HOLDOUT_FACTS = 8
TRAIN_CASES = TRAIN_FACTS * len(LANGUAGES) * len(LABELS)
HOLDOUT_CASES = HOLDOUT_FACTS * len(LANGUAGES) * len(LABELS)


@dataclass(frozen=True, slots=True)
class GuardFact:
    subject: str
    relation_en: str
    relation_hi: str
    relation_hinglish: str
    value: str
    alternative: str


TRAIN_FACT_ROWS: Final = (
    GuardFact(
        "Orion desk",
        "focus profile",
        "फोकस प्रोफ़ाइल",
        "focus profile",
        "amber-7",
        "cobalt-2",
    ),
    GuardFact(
        "Atlas tablet", "sync channel", "सिंक चैनल", "sync channel", "north-4", "south-9"
    ),
    GuardFact(
        "Nimbus lamp",
        "reading preset",
        "रीडिंग प्रीसेट",
        "reading preset",
        "warm-3",
        "cool-8",
    ),
    GuardFact("Cedar router", "guest band", "गेस्ट बैंड", "guest band", "band-6", "band-1"),
    GuardFact(
        "Kite notebook", "backup lane", "बैकअप लेन", "backup lane", "lane-5", "lane-8"
    ),
    GuardFact(
        "Quartz speaker", "night level", "नाइट लेवल", "night level", "level-2", "level-6"
    ),
    GuardFact(
        "Harbor display", "layout mode", "लेआउट मोड", "layout mode", "grid-4", "stack-7"
    ),
    GuardFact(
        "Pine console", "access zone", "एक्सेस ज़ोन", "access zone", "zone-3", "zone-9"
    ),
    GuardFact(
        "Comet watch",
        "alert profile",
        "अलर्ट प्रोफ़ाइल",
        "alert profile",
        "pulse-5",
        "pulse-1",
    ),
    GuardFact(
        "Maple hub", "upload route", "अपलोड रूट", "upload route", "route-8", "route-2"
    ),
    GuardFact(
        "Silver camera",
        "capture preset",
        "कैप्चर प्रीसेट",
        "capture preset",
        "preset-6",
        "preset-3",
    ),
    GuardFact(
        "Delta keyboard", "typing mode", "टाइपिंग मोड", "typing mode", "mode-4", "mode-7"
    ),
)

HOLDOUT_FACT_ROWS: Final = (
    GuardFact(
        "Raven panel",
        "status profile",
        "स्टेटस प्रोफ़ाइल",
        "status profile",
        "echo-2",
        "echo-9",
    ),
    GuardFact(
        "Birch terminal", "login lane", "लॉगिन लेन", "login lane", "lane-3", "lane-7"
    ),
    GuardFact(
        "Lunar dock",
        "charging preset",
        "चार्जिंग प्रीसेट",
        "charging preset",
        "steady-4",
        "rapid-8",
    ),
    GuardFact(
        "Copper sensor",
        "reporting mode",
        "रिपोर्टिंग मोड",
        "reporting mode",
        "mode-5",
        "mode-1",
    ),
    GuardFact(
        "Falcon pad",
        "workspace zone",
        "वर्कस्पेस ज़ोन",
        "workspace zone",
        "zone-6",
        "zone-2",
    ),
    GuardFact(
        "Moss receiver",
        "audio profile",
        "ऑडियो प्रोफ़ाइल",
        "audio profile",
        "profile-8",
        "profile-3",
    ),
    GuardFact(
        "Indigo bridge",
        "transfer route",
        "ट्रांसफर रूट",
        "transfer route",
        "route-5",
        "route-1",
    ),
    GuardFact(
        "Solar keypad",
        "unlock preset",
        "अनलॉक प्रीसेट",
        "unlock preset",
        "preset-7",
        "preset-2",
    ),
)


def _template_map() -> dict[str, dict[str, tuple[str, ...]]]:
    return {
        "en": {
            "current_value": (
                "What current {relation} is recorded for {subject}?",
                "Tell me the present {relation} saved for {subject}.",
            ),
            "current_value_comparison": (
                "Is {value} still the current {relation} for {subject}?",
                "Does {subject} currently have {relation} set to {value}?",
            ),
            "reason_explanation": (
                "Why was {value} chosen as the {relation} for {subject}?",
                "What is the reason {subject} uses {value} for {relation}?",
            ),
            "provenance_actor": (
                "Who selected {value} as the {relation} for {subject}?",
                "Who originally set {subject}'s {relation} to {value}?",
            ),
            "replacement_successor": (
                "What replaced {value} as the {relation} for {subject}?",
                "Which value succeeded {value} for {subject}'s {relation}?",
            ),
            "related_record": (
                "Which related record is linked to {subject}'s {relation}?",
                "Show the linked record associated with the {relation} of {subject}.",
            ),
            "negated_or_contradicted": (
                "Do not confirm {value}; is {subject}'s {relation} explicitly not {value}?",
                "{subject}'s {relation} is not {value}, correct?",
            ),
            "other_or_advice": (
                "Should I change {subject}'s {relation} away from {value}?",
                "Would you recommend using {alternative} instead of {value} for {subject}'s {relation}?",
            ),
        },
        "hi": {
            "current_value": (
                "{subject} के लिए अभी कौन सा {relation} दर्ज है?",
                "{subject} का वर्तमान {relation} क्या सेव है?",
            ),
            "current_value_comparison": (
                "क्या {subject} का मौजूदा {relation} अभी भी {value} है?",
                "क्या अभी {subject} में {relation} {value} पर सेट है?",
            ),
            "reason_explanation": (
                "{subject} के {relation} के लिए {value} क्यों चुना गया?",
                "{subject} में {relation} के लिए {value} रखने की वजह क्या है?",
            ),
            "provenance_actor": (
                "{subject} का {relation} {value} किसने चुना?",
                "{subject} के {relation} को {value} पर किसने सेट किया था?",
            ),
            "replacement_successor": (
                "{subject} के {relation} में {value} की जगह क्या आया?",
                "{subject} के {relation} के लिए {value} को किस value ने replace किया?",
            ),
            "related_record": (
                "{subject} के {relation} से कौन सा related record जुड़ा है?",
                "{subject} के {relation} से linked record कौन सा है?",
            ),
            "negated_or_contradicted": (
                "{value} को confirm मत करो; क्या {subject} का {relation} {value} नहीं है?",
                "{subject} का {relation} {value} नहीं है, सही?",
            ),
            "other_or_advice": (
                "क्या मुझे {subject} का {relation} {value} से बदल देना चाहिए?",
                "क्या {subject} के {relation} के लिए {value} की जगह {alternative} बेहतर रहेगा?",
            ),
        },
        "hinglish": {
            "current_value": (
                "{subject} ka current {relation} kya recorded hai?",
                "{subject} ke liye abhi ka {relation} batao.",
            ),
            "current_value_comparison": (
                "Kya {subject} ka current {relation} abhi bhi {value} hai?",
                "Abhi {subject} ka {relation} {value} pe set hai kya?",
            ),
            "reason_explanation": (
                "{subject} ke {relation} ke liye {value} kyun choose hua tha?",
                "{subject} me {relation} {value} rakhne ka reason kya hai?",
            ),
            "provenance_actor": (
                "{subject} ka {relation} {value} kisne select kiya tha?",
                "{subject} ke {relation} ko {value} par kisne set kiya?",
            ),
            "replacement_successor": (
                "{subject} ke {relation} me {value} ko kis value ne replace kiya?",
                "{subject} ke {relation} ke liye {value} ke baad kya aaya?",
            ),
            "related_record": (
                "{subject} ke {relation} se kaunsa related record linked hai?",
                "{subject} ke {relation} ka linked record batao.",
            ),
            "negated_or_contradicted": (
                "{value} ko confirm mat karo; kya {subject} ka {relation} {value} nahi hai?",
                "{subject} ka {relation} {value} nahi hai na?",
            ),
            "other_or_advice": (
                "Kya mujhe {subject} ka {relation} {value} se change karna chahiye?",
                "{subject} ke {relation} ke liye {value} ki jagah {alternative} better rahega kya?",
            ),
        },
    }


def _holdout_template_map() -> dict[str, dict[str, tuple[str, ...]]]:
    return {
        "en": {
            "current_value": (
                "Which {relation} does {subject} have right now?",
                "Give me the currently stored {relation} for {subject}.",
            ),
            "current_value_comparison": (
                "For {subject}, is the recorded {relation} currently {value}?",
                "Check whether {value} matches {subject}'s current {relation}.",
            ),
            "reason_explanation": (
                "Explain why {subject}'s {relation} ended up as {value}.",
                "Why does the record use {value} for {subject}'s {relation}?",
            ),
            "provenance_actor": (
                "Which person or source picked {value} for {subject}'s {relation}?",
                "Who is responsible for choosing {value} for the {relation} of {subject}?",
            ),
            "replacement_successor": (
                "After {value} was retired, what became {subject}'s {relation}?",
                "What new setting took over from {value} for {subject}'s {relation}?",
            ),
            "related_record": (
                "What separate linked item belongs to {subject}'s {relation}?",
                "Find the associated record, not the value, for {subject}'s {relation}.",
            ),
            "negated_or_contradicted": (
                "I am saying {value} is not {subject}'s {relation}; is that negative statement right?",
                "Is it false that {subject}'s {relation} equals {value}?",
            ),
            "other_or_advice": (
                "Would changing {subject}'s {relation} from {value} be a good idea?",
                "Should {subject} use {alternative} for {relation} rather than {value}?",
            ),
        },
        "hi": {
            "current_value": (
                "अभी {subject} में कौन सा {relation} रखा हुआ है?",
                "{subject} के लिए currently stored {relation} बताओ.",
            ),
            "current_value_comparison": (
                "जाँचो कि {subject} का वर्तमान {relation} {value} है या नहीं.",
                "क्या recorded {relation} अभी {subject} के लिए {value} से match करता है?",
            ),
            "reason_explanation": (
                "समझाओ कि {subject} का {relation} {value} क्यों रखा गया.",
                "record में {subject} के {relation} के लिए {value} होने का कारण क्या है?",
            ),
            "provenance_actor": (
                "{subject} के {relation} के लिए {value} चुनने वाला कौन था?",
                "{subject} का {relation} {value} किस source ने तय किया?",
            ),
            "replacement_successor": (
                "{value} हटने के बाद {subject} का {relation} क्या बना?",
                "{subject} के {relation} में {value} के बाद नया setting क्या आया?",
            ),
            "related_record": (
                "value नहीं, {subject} के {relation} से जुड़ा अलग record कौन सा है?",
                "{subject} के {relation} का associated item ढूँढो.",
            ),
            "negated_or_contradicted": (
                "मैं कह रहा हूँ {subject} का {relation} {value} नहीं है; क्या यह negative statement सही है?",
                "क्या यह गलत है कि {subject} का {relation} {value} के बराबर है?",
            ),
            "other_or_advice": (
                "क्या {subject} का {relation} {value} से बदलना अच्छा idea होगा?",
                "क्या {subject} में {relation} के लिए {value} के बजाय {alternative} use करना चाहिए?",
            ),
        },
        "hinglish": {
            "current_value": (
                "Right now {subject} me kaunsa {relation} saved hai?",
                "{subject} ka currently stored {relation} de do.",
            ),
            "current_value_comparison": (
                "Check karo kya {subject} ka current {relation} {value} hai.",
                "Kya {value} {subject} ke recorded current {relation} se match karta hai?",
            ),
            "reason_explanation": (
                "Explain karo {subject} ka {relation} {value} kyun rakha gaya.",
                "Record me {subject} ke {relation} ke liye {value} hone ka reason kya hai?",
            ),
            "provenance_actor": (
                "{subject} ke {relation} ke liye {value} choose karne wala kaun tha?",
                "{subject} ka {relation} {value} kis source ne decide kiya?",
            ),
            "replacement_successor": (
                "{value} retire hone ke baad {subject} ka {relation} kya bana?",
                "{subject} ke {relation} me {value} ke baad naya setting kya aaya?",
            ),
            "related_record": (
                "Value nahi, {subject} ke {relation} se linked separate record kaunsa hai?",
                "{subject} ke {relation} ka associated item find karo.",
            ),
            "negated_or_contradicted": (
                "Main keh raha hoon {subject} ka {relation} {value} nahi hai; ye negative statement sahi hai?",
                "Kya ye false hai ki {subject} ka {relation} {value} ke equal hai?",
            ),
            "other_or_advice": (
                "Kya {subject} ka {relation} {value} se change karna good idea hoga?",
                "{subject} me {relation} ke liye {value} ke badle {alternative} use karna chahiye kya?",
            ),
        },
    }


def _relation(fact: GuardFact, language: str) -> str:
    if language == "hi":
        return fact.relation_hi
    if language == "hinglish":
        return fact.relation_hinglish
    return fact.relation_en


def _render(template: str, *, fact: GuardFact, language: str) -> str:
    return template.format(
        subject=fact.subject,
        relation=_relation(fact, language),
        value=fact.value,
        alternative=fact.alternative,
    )


def _rows(
    *,
    split: str,
    facts: tuple[GuardFact, ...],
    templates: dict[str, dict[str, tuple[str, ...]]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    counter = 0
    for fact_index, fact in enumerate(facts):
        for language in LANGUAGES:
            for label in LABELS:
                counter += 1
                choices = templates[language][label]
                template = choices[fact_index % len(choices)]
                output.append(
                    {
                        "case_id": f"tsg_{split}_{counter:04d}",
                        "split": split,
                        "language": language,
                        "label": label,
                        "allow": label in ALLOW_LABELS,
                        "query": _render(template, fact=fact, language=language),
                    }
                )
    return output


def build_payload() -> dict[str, object]:
    train = _rows(
        split="train",
        facts=TRAIN_FACT_ROWS,
        templates=_template_map(),
    )
    holdout = _rows(
        split="holdout",
        facts=HOLDOUT_FACT_ROWS,
        templates=_holdout_template_map(),
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "taxonomy": list(LABELS),
        "allow_labels": sorted(ALLOW_LABELS),
        "train": train,
        "holdout": holdout,
    }
    _validate_payload(payload)
    return payload


def normalized_query(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(normalized.split())


def _validate_payload(payload: dict[str, object]) -> None:
    train = payload["train"]
    holdout = payload["holdout"]
    if not isinstance(train, list) or len(train) != TRAIN_CASES:
        raise RuntimeError("task-specific guard train corpus shape changed")
    if not isinstance(holdout, list) or len(holdout) != HOLDOUT_CASES:
        raise RuntimeError("task-specific guard holdout corpus shape changed")
    all_rows = train + holdout
    queries = [normalized_query(str(row["query"])) for row in all_rows]
    if len(set(queries)) != len(queries):
        raise RuntimeError(
            "task-specific guard corpus contains duplicate normalized queries"
        )
    train_queries = {normalized_query(str(row["query"])) for row in train}
    holdout_queries = {normalized_query(str(row["query"])) for row in holdout}
    if train_queries.intersection(holdout_queries):
        raise RuntimeError("task-specific guard train/holdout query overlap detected")
    for split_rows, expected_facts in ((train, TRAIN_FACTS), (holdout, HOLDOUT_FACTS)):
        counts: dict[tuple[str, str], int] = {}
        for row in split_rows:
            key = (str(row["language"]), str(row["label"]))
            counts[key] = counts.get(key, 0) + 1
        if set(counts.values()) != {expected_facts}:
            raise RuntimeError("task-specific guard class/language balance changed")


def payload_sha256(payload: dict[str, object] | None = None) -> str:
    material = build_payload() if payload is None else payload
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def public_summary() -> dict[str, object]:
    payload = build_payload()
    return {
        "schema_version": SCHEMA_VERSION,
        "labels": len(LABELS),
        "languages": len(LANGUAGES),
        "train_cases": TRAIN_CASES,
        "holdout_cases": HOLDOUT_CASES,
        "sha256": payload_sha256(payload),
    }


if __name__ == "__main__":
    print(json.dumps(public_summary(), ensure_ascii=False))
