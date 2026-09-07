"""Fresh development cases for Phase 4.5D task-guard fine-tuning V3."""

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
        "Aster station",
        "display profile",
        "डिस्प्ले प्रोफ़ाइल",
        "display profile",
        "dawn-4",
        "dusk-8",
    ),
    GuardFact(
        "Beryl controller",
        "control lane",
        "कंट्रोल लेन",
        "control lane",
        "lane-12",
        "lane-3",
    ),
    GuardFact(
        "Cinder monitor",
        "contrast preset",
        "कॉन्ट्रास्ट प्रीसेट",
        "contrast preset",
        "soft-6",
        "sharp-2",
    ),
    GuardFact(
        "Drift gateway",
        "routing profile",
        "रूटिंग प्रोफ़ाइल",
        "routing profile",
        "west-5",
        "east-1",
    ),
    GuardFact(
        "Ember reader",
        "reading mode",
        "रीडिंग मोड",
        "reading mode",
        "paper-7",
        "night-2",
    ),
    GuardFact(
        "Frost dock", "power preset", "पावर प्रीसेट", "power preset", "eco-9", "boost-4"
    ),
    GuardFact(
        "Grove terminal", "session zone", "सेशन ज़ोन", "session zone", "zone-11", "zone-6"
    ),
    GuardFact(
        "Helix keypad",
        "input profile",
        "इनपुट प्रोफ़ाइल",
        "input profile",
        "tap-5",
        "hold-8",
    ),
    GuardFact(
        "Iris bridge",
        "transfer lane",
        "ट्रांसफर लेन",
        "transfer lane",
        "lane-14",
        "lane-9",
    ),
    GuardFact(
        "Juniper receiver",
        "sound preset",
        "साउंड प्रीसेट",
        "sound preset",
        "clear-3",
        "deep-6",
    ),
    GuardFact(
        "Kepler panel", "status mode", "स्टेटस मोड", "status mode", "live-8", "quiet-1"
    ),
    GuardFact(
        "Lattice hub",
        "upload profile",
        "अपलोड प्रोफ़ाइल",
        "upload profile",
        "burst-2",
        "steady-7",
    ),
    GuardFact(
        "Mica camera", "capture mode", "कैप्चर मोड", "capture mode", "frame-9", "frame-4"
    ),
    GuardFact(
        "Nova console",
        "access preset",
        "एक्सेस प्रीसेट",
        "access preset",
        "open-5",
        "guard-2",
    ),
    GuardFact(
        "Opal tablet",
        "sync profile",
        "सिंक प्रोफ़ाइल",
        "sync profile",
        "cloud-6",
        "local-3",
    ),
    GuardFact(
        "Prism speaker", "volume lane", "वॉल्यूम लेन", "volume lane", "lane-7", "lane-2"
    ),
)

HOLDOUT_FACT_ROWS: Final = (
    GuardFact(
        "Quill display",
        "layout profile",
        "लेआउट प्रोफ़ाइल",
        "layout profile",
        "tile-6",
        "stack-2",
    ),
    GuardFact(
        "Reef sensor", "report mode", "रिपोर्ट मोड", "report mode", "pulse-7", "batch-3"
    ),
    GuardFact(
        "Sable router",
        "guest profile",
        "गेस्ट प्रोफ़ाइल",
        "guest profile",
        "guest-4",
        "guest-9",
    ),
    GuardFact(
        "Tundra watch", "alert lane", "अलर्ट लेन", "alert lane", "lane-10", "lane-5"
    ),
    GuardFact(
        "Umber notebook",
        "backup mode",
        "बैकअप मोड",
        "backup mode",
        "daily-8",
        "weekly-2",
    ),
    GuardFact(
        "Vale keyboard",
        "typing profile",
        "टाइपिंग प्रोफ़ाइल",
        "typing profile",
        "swift-4",
        "calm-7",
    ),
    GuardFact(
        "Willow lamp", "night preset", "नाइट प्रीसेट", "night preset", "amber-9", "blue-3"
    ),
    GuardFact(
        "Zenith pad",
        "workspace mode",
        "वर्कस्पेस मोड",
        "workspace mode",
        "focus-5",
        "open-1",
    ),
)


def _train_templates() -> dict[str, dict[str, tuple[str, ...]]]:
    return {
        "en": {
            "current_value": (
                "What value is currently stored as {subject}'s {relation}?",
                "Give me {subject}'s present {relation} setting.",
                "Right now, which {relation} belongs to {subject}?",
            ),
            "current_value_comparison": (
                "Is {value} the value currently stored for {subject}'s {relation}?",
                "Does the current record say {subject}'s {relation} is {value}?",
                "Check if {subject} presently uses {value} for {relation}.",
            ),
            "reason_explanation": (
                "Why is {value} used for {subject}'s {relation}?",
                "Explain the reason behind {subject} having {relation} {value}.",
                "What caused {value} to be chosen for {subject}'s {relation}?",
            ),
            "provenance_actor": (
                "Who set {subject}'s {relation} to {value}?",
                "Which person or source chose {value} for {subject}'s {relation}?",
                "Who was responsible for recording {value} as {subject}'s {relation}?",
            ),
            "replacement_successor": (
                "What replaced {value} for {subject}'s {relation}?",
                "After {value}, which setting became {subject}'s {relation}?",
                "Which successor took over from {value} as {subject}'s {relation}?",
            ),
            "related_record": (
                "Which separate record is associated with {subject}'s {relation}?",
                "Find the linked item for {subject}'s {relation}, not its value.",
                "What related record belongs to the {relation} of {subject}?",
            ),
            "negated_or_contradicted": (
                "Is it incorrect that {subject}'s {relation} is {value}?",
                "I am saying {subject}'s {relation} is not {value}; is that right?",
                "Do not confirm {value}: is {subject}'s {relation} explicitly different from it?",
            ),
            "other_or_advice": (
                "Should I change {subject}'s {relation} from {value} to {alternative}?",
                "Would {alternative} be better than {value} for {subject}'s {relation}?",
                "What would you recommend for {subject}'s {relation} instead of {value}?",
            ),
        },
        "hi": {
            "current_value": (
                "अभी {subject} का {relation} कौन सा value सेव है?",
                "{subject} की वर्तमान {relation} setting बताओ.",
                "इस समय {subject} के लिए कौन सा {relation} दर्ज है?",
            ),
            "current_value_comparison": (
                "क्या अभी {subject} का {relation} {value} ही है?",
                "जाँचो कि current record में {subject} का {relation} {value} है या नहीं.",
                "क्या {subject} इस समय {relation} के लिए {value} use करता है?",
            ),
            "reason_explanation": (
                "{subject} के {relation} के लिए {value} क्यों रखा गया है?",
                "समझाओ कि {subject} का {relation} {value} होने की वजह क्या है.",
                "{subject} के {relation} में {value} चुनने का कारण क्या था?",
            ),
            "provenance_actor": (
                "{subject} का {relation} {value} किसने सेट किया?",
                "{subject} के {relation} के लिए {value} किस person या source ने चुना?",
                "{value} को {subject} का {relation} किसने record किया था?",
            ),
            "replacement_successor": (
                "{subject} के {relation} में {value} की जगह क्या आया?",
                "{value} के बाद {subject} का {relation} कौन सा setting बना?",
                "{subject} के {relation} के लिए {value} का successor क्या था?",
            ),
            "related_record": (
                "{subject} के {relation} से कौन सा अलग record जुड़ा है?",
                "value नहीं, {subject} के {relation} का linked item बताओ.",
                "{subject} के {relation} से associated record कौन सा है?",
            ),
            "negated_or_contradicted": (
                "क्या यह गलत है कि {subject} का {relation} {value} है?",
                "मैं कह रहा हूँ {subject} का {relation} {value} नहीं है; क्या यह सही है?",
                "{value} को confirm मत करो: क्या {subject} का {relation} इससे अलग है?",
            ),
            "other_or_advice": (
                "क्या मुझे {subject} का {relation} {value} से {alternative} कर देना चाहिए?",
                "क्या {subject} के {relation} के लिए {alternative}, {value} से बेहतर होगा?",
                "{subject} के {relation} में {value} की जगह क्या recommend करोगे?",
            ),
        },
        "hinglish": {
            "current_value": (
                "Abhi {subject} ka {relation} kaunsa value saved hai?",
                "{subject} ki present {relation} setting batao.",
                "Right now {subject} ke liye kaunsa {relation} recorded hai?",
            ),
            "current_value_comparison": (
                "Kya abhi {subject} ka {relation} {value} hi hai?",
                "Check karo current record me {subject} ka {relation} {value} hai ya nahi.",
                "Kya {subject} presently {relation} ke liye {value} use karta hai?",
            ),
            "reason_explanation": (
                "{subject} ke {relation} ke liye {value} kyun rakha gaya hai?",
                "Explain karo {subject} ka {relation} {value} hone ka reason kya hai.",
                "{subject} ke {relation} me {value} choose hone ki wajah kya thi?",
            ),
            "provenance_actor": (
                "{subject} ka {relation} {value} kisne set kiya?",
                "{subject} ke {relation} ke liye {value} kis person ya source ne choose kiya?",
                "{value} ko {subject} ka {relation} kisne record kiya tha?",
            ),
            "replacement_successor": (
                "{subject} ke {relation} me {value} ki jagah kya aaya?",
                "{value} ke baad {subject} ka {relation} kaunsa setting bana?",
                "{subject} ke {relation} ke liye {value} ka successor kya tha?",
            ),
            "related_record": (
                "{subject} ke {relation} se kaunsa alag record linked hai?",
                "Value nahi, {subject} ke {relation} ka linked item batao.",
                "{subject} ke {relation} se associated record kaunsa hai?",
            ),
            "negated_or_contradicted": (
                "Kya yeh galat hai ki {subject} ka {relation} {value} hai?",
                "Main bol raha hoon {subject} ka {relation} {value} nahi hai; kya ye sahi hai?",
                "{value} ko confirm mat karo: kya {subject} ka {relation} isse different hai?",
            ),
            "other_or_advice": (
                "Kya mujhe {subject} ka {relation} {value} se {alternative} kar dena chahiye?",
                "Kya {subject} ke {relation} ke liye {alternative}, {value} se better hoga?",
                "{subject} ke {relation} me {value} ki jagah kya recommend karoge?",
            ),
        },
    }


def _holdout_templates() -> dict[str, dict[str, tuple[str, ...]]]:
    return {
        "en": {
            "current_value": (
                "Tell me the value that applies to {subject}'s {relation} now.",
                "Which {relation} is active for {subject} at the moment?",
                "Read back the current {relation} recorded for {subject}.",
            ),
            "current_value_comparison": (
                "For {subject}, does {value} match the {relation} that is active now?",
                "Verify whether the present {relation} for {subject} equals {value}.",
                "Is the currently applicable {subject} {relation} still {value}?",
            ),
            "reason_explanation": (
                "What explains {subject} ending up with {value} as its {relation}?",
                "Give the reason the record has {value} for {subject}'s {relation}.",
                "Why did {value} become the {relation} used by {subject}?",
            ),
            "provenance_actor": (
                "Identify who decided on {value} for {subject}'s {relation}.",
                "What source assigned {value} to the {relation} of {subject}?",
                "Who made the choice that {subject}'s {relation} would be {value}?",
            ),
            "replacement_successor": (
                "When {value} stopped being used, what took its place for {subject}'s {relation}?",
                "Name the setting that came after {value} for {subject}'s {relation}.",
                "What became {subject}'s {relation} once {value} was replaced?",
            ),
            "related_record": (
                "Which associated item, separate from the value, is tied to {subject}'s {relation}?",
                "Locate the companion record linked with {subject}'s {relation}.",
                "What linked record goes with {subject}'s {relation}?",
            ),
            "negated_or_contradicted": (
                "Would it be correct to deny that {subject}'s {relation} is {value}?",
                "Is the statement '{subject}'s {relation} equals {value}' false?",
                "Confirm the negative claim that {value} is not {subject}'s {relation}.",
            ),
            "other_or_advice": (
                "Would you advise moving {subject}'s {relation} away from {value}?",
                "Should {subject} switch its {relation} to {alternative}?",
                "Which setting would you suggest instead of {value} for {subject}'s {relation}?",
            ),
        },
        "hi": {
            "current_value": (
                "अभी लागू {subject} का {relation} value बताओ.",
                "इस वक्त {subject} में कौन सा {relation} active है?",
                "{subject} के लिए दर्ज current {relation} वापस बताओ.",
            ),
            "current_value_comparison": (
                "क्या {subject} के लिए {value}, अभी active {relation} से match करता है?",
                "verify करो कि {subject} का वर्तमान {relation} {value} के बराबर है या नहीं.",
                "क्या {subject} का अभी लागू {relation} अभी भी {value} है?",
            ),
            "reason_explanation": (
                "{subject} का {relation} {value} कैसे बना, इसकी वजह क्या है?",
                "record में {subject} के {relation} के लिए {value} क्यों है?",
                "{value}, {subject} का {relation} क्यों बन गया था?",
            ),
            "provenance_actor": (
                "{subject} के {relation} में {value} तय करने वाला कौन था?",
                "किस source ने {subject} के {relation} को {value} assign किया?",
                "{subject} का {relation} {value} होगा, यह choice किसने की?",
            ),
            "replacement_successor": (
                "जब {value} use होना बंद हुआ तो {subject} के {relation} में क्या आया?",
                "{subject} के {relation} के लिए {value} के बाद वाला setting बताओ.",
                "{value} replace होने के बाद {subject} का {relation} क्या बना?",
            ),
            "related_record": (
                "value से अलग, {subject} के {relation} से कौन सा associated item जुड़ा है?",
                "{subject} के {relation} से linked companion record ढूँढो.",
                "{subject} के {relation} के साथ कौन सा linked record जाता है?",
            ),
            "negated_or_contradicted": (
                "क्या यह deny करना सही होगा कि {subject} का {relation} {value} है?",
                "क्या '{subject} का {relation} {value} है' statement false है?",
                "negative claim confirm करो कि {value}, {subject} का {relation} नहीं है.",
            ),
            "other_or_advice": (
                "क्या {subject} का {relation} {value} से हटाने की सलाह दोगे?",
                "क्या {subject} को अपना {relation} {alternative} पर switch करना चाहिए?",
                "{subject} के {relation} के लिए {value} की जगह क्या suggest करोगे?",
            ),
        },
        "hinglish": {
            "current_value": (
                "Abhi applicable {subject} ka {relation} value batao.",
                "Is waqt {subject} me kaunsa {relation} active hai?",
                "{subject} ke liye recorded current {relation} read back karo.",
            ),
            "current_value_comparison": (
                "Kya {subject} ke liye {value}, abhi active {relation} se match karta hai?",
                "Verify karo ki {subject} ka present {relation} {value} ke equal hai ya nahi.",
                "Kya {subject} ka currently applicable {relation} abhi bhi {value} hai?",
            ),
            "reason_explanation": (
                "{subject} ka {relation} {value} kaise bana, reason kya hai?",
                "Record me {subject} ke {relation} ke liye {value} kyun hai?",
                "{value}, {subject} ka {relation} kyun ban gaya tha?",
            ),
            "provenance_actor": (
                "{subject} ke {relation} me {value} decide karne wala kaun tha?",
                "Kis source ne {subject} ke {relation} ko {value} assign kiya?",
                "{subject} ka {relation} {value} hoga ye choice kisne ki?",
            ),
            "replacement_successor": (
                "Jab {value} use hona band hua to {subject} ke {relation} me kya aaya?",
                "{subject} ke {relation} ke liye {value} ke baad wala setting batao.",
                "{value} replace hone ke baad {subject} ka {relation} kya bana?",
            ),
            "related_record": (
                "Value se alag, {subject} ke {relation} se kaunsa associated item linked hai?",
                "{subject} ke {relation} se linked companion record find karo.",
                "{subject} ke {relation} ke saath kaunsa linked record jata hai?",
            ),
            "negated_or_contradicted": (
                "Kya yeh deny karna sahi hoga ki {subject} ka {relation} {value} hai?",
                "Kya '{subject} ka {relation} {value} hai' statement false hai?",
                "Negative claim confirm karo ki {value}, {subject} ka {relation} nahi hai.",
            ),
            "other_or_advice": (
                "Kya {subject} ka {relation} {value} se hatane ki advice doge?",
                "Kya {subject} ko apna {relation} {alternative} pe switch karna chahiye?",
                "{subject} ke {relation} ke liye {value} ki jagah kya suggest karoge?",
            ),
        },
    }


def normalized_query(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _relation(fact: GuardFact, language: str) -> str:
    if language == "en":
        return fact.relation_en
    if language == "hi":
        return fact.relation_hi
    if language == "hinglish":
        return fact.relation_hinglish
    raise ValueError(f"unsupported language: {language}")


def _build_split(
    facts: tuple[GuardFact, ...],
    templates: dict[str, dict[str, tuple[str, ...]]],
    *,
    split: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for fact_index, fact in enumerate(facts):
        for language in LANGUAGES:
            for label_index, label in enumerate(LABELS):
                choices = templates[language][label]
                template = choices[(fact_index + label_index) % len(choices)]
                query = template.format(
                    subject=fact.subject,
                    relation=_relation(fact, language),
                    value=fact.value,
                    alternative=fact.alternative,
                )
                rows.append(
                    {
                        "case_id": f"v3_{split}_{fact_index:02d}_{language}_{label_index}",
                        "split": split,
                        "language": language,
                        "label": label,
                        "allow": label in ALLOW_LABELS,
                        "query": query,
                    }
                )
    return rows


def build_payload() -> dict[str, object]:
    train = _build_split(TRAIN_FACT_ROWS, _train_templates(), split="train")
    holdout = _build_split(HOLDOUT_FACT_ROWS, _holdout_templates(), split="holdout")
    train_queries = {normalized_query(str(row["query"])) for row in train}
    holdout_queries = {normalized_query(str(row["query"])) for row in holdout}
    overlap = train_queries.intersection(holdout_queries)
    if overlap:
        raise RuntimeError(f"V3 train/holdout query overlap: {sorted(overlap)[:3]}")
    return {
        "schema_version": SCHEMA_VERSION,
        "languages": list(LANGUAGES),
        "labels": list(LABELS),
        "allow_labels": sorted(ALLOW_LABELS),
        "train": train,
        "holdout": holdout,
    }


def payload_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def public_summary() -> dict[str, object]:
    payload = build_payload()
    return {
        "schema_version": SCHEMA_VERSION,
        "train_cases": len(payload["train"]),
        "holdout_cases": len(payload["holdout"]),
        "languages": list(LANGUAGES),
        "labels": list(LABELS),
        "allow_labels": sorted(ALLOW_LABELS),
        "payload_sha256": payload_sha256(payload),
    }


if __name__ == "__main__":
    print(json.dumps(public_summary(), indent=2, ensure_ascii=False))
