"""Fresh zero-training question-role cases for Phase 4.5D."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Final

SCHEMA_VERSION: Final = 1
LANGUAGES: Final = ("en", "hi", "hinglish")
ROLES: Final = (
    "current_value",
    "current_value_comparison",
    "reason_explanation",
    "provenance_actor",
    "replacement_successor",
    "related_record",
    "historical_value",
    "external_source",
    "broad_recall",
    "advice_or_other",
)
ALLOW_ROLES: Final = frozenset({"current_value", "current_value_comparison"})


@dataclass(frozen=True, slots=True)
class RoleFact:
    subject: str
    relation_en: str
    relation_hi: str
    relation_hinglish: str
    value: str
    alternative: str


FACTS: Final = (
    RoleFact(
        "Indigo dock",
        "display preset",
        "डिस्प्ले प्रीसेट",
        "display preset",
        "grid-7",
        "stack-2",
    ),
    RoleFact(
        "Juniper lamp",
        "lighting scene",
        "लाइटिंग सीन",
        "lighting scene",
        "calm-6",
        "focus-3",
    ),
    RoleFact(
        "Kestrel router",
        "network profile",
        "नेटवर्क प्रोफ़ाइल",
        "network profile",
        "mesh-8",
        "guest-4",
    ),
    RoleFact(
        "Lotus panel",
        "control layout",
        "कंट्रोल लेआउट",
        "control layout",
        "panel-5",
        "panel-9",
    ),
    RoleFact(
        "Marble speaker",
        "audio preset",
        "ऑडियो प्रीसेट",
        "audio preset",
        "studio-3",
        "cinema-8",
    ),
    RoleFact(
        "Nimbus lock",
        "entry profile",
        "एंट्री प्रोफ़ाइल",
        "entry profile",
        "home-4",
        "travel-9",
    ),
    RoleFact(
        "Opal tablet",
        "reading mode",
        "रीडिंग मोड",
        "reading mode",
        "paper-6",
        "night-2",
    ),
    RoleFact(
        "Pine camera",
        "capture profile",
        "कैप्चर प्रोफ़ाइल",
        "capture profile",
        "detail-4",
        "motion-7",
    ),
)


def normalized_query(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _relation(fact: RoleFact, language: str) -> str:
    return {
        "en": fact.relation_en,
        "hi": fact.relation_hi,
        "hinglish": fact.relation_hinglish,
    }[language]


def _templates() -> dict[str, dict[str, tuple[str, str]]]:
    return {
        "en": {
            "current_value": (
                "What is {subject}'s current {relation}?",
                "Tell me the present {relation} recorded for {subject}.",
            ),
            "current_value_comparison": (
                "Is {value} still {subject}'s current {relation}?",
                "{subject}'s current {relation} is not {alternative}, right?",
            ),
            "reason_explanation": (
                "Why was {value} chosen as {subject}'s {relation}?",
                "What was the reason for setting {subject}'s {relation} to {value}?",
            ),
            "provenance_actor": (
                "Who selected {value} as {subject}'s {relation}?",
                "Which person recommended {value} for {subject}'s {relation}?",
            ),
            "replacement_successor": (
                "What replaced {alternative} for {subject}'s {relation}?",
                "After {alternative} was rejected, which value succeeded it for "
                "{subject}'s {relation}?",
            ),
            "related_record": (
                "Which approval ticket was created for {subject}'s {relation}?",
                "What linked record is associated with setting {subject}'s {relation} "
                "to {value}?",
            ),
            "historical_value": (
                "What was {subject}'s previous {relation} before {value}?",
                "Which old {relation} did {subject} use last month?",
            ),
            "external_source": (
                "What does the email say about {subject}'s {relation}?",
                "According to the web page, what is {subject}'s {relation}?",
            ),
            "broad_recall": (
                "Tell me everything you remember about {subject}.",
                "List all memories related to {subject}'s settings.",
            ),
            "advice_or_other": (
                "Should I change {subject}'s {relation} from {value} to {alternative}?",
                "Would {alternative} be a better {relation} for {subject}?",
            ),
        },
        "hi": {
            "current_value": (
                "{subject} का current {relation} क्या है?",
                "{subject} के लिए अभी दर्ज {relation} बताओ।",
            ),
            "current_value_comparison": (
                "क्या {value} अभी भी {subject} का current {relation} है?",
                "{subject} का current {relation} {alternative} नहीं है, सही?",
            ),
            "reason_explanation": (
                "{subject} के {relation} के लिए {value} क्यों चुना गया था?",
                "{subject} का {relation} {value} रखने की वजह क्या थी?",
            ),
            "provenance_actor": (
                "{subject} का {relation} {value} किसने चुना था?",
                "{subject} के {relation} के लिए {value} किस व्यक्ति ने recommend किया था?",
            ),
            "replacement_successor": (
                "{subject} के {relation} में {alternative} की जगह क्या आया?",
                "{alternative} reject होने के बाद {subject} के {relation} में कौन सा "
                "value आया?",
            ),
            "related_record": (
                "{subject} के {relation} के लिए कौन सा approval ticket बना था?",
                "{subject} का {relation} {value} set करने से कौन सा linked record जुड़ा है?",
            ),
            "historical_value": (
                "{value} से पहले {subject} का previous {relation} क्या था?",
                "पिछले महीने {subject} का पुराना {relation} कौन सा था?",
            ),
            "external_source": (
                "Email में {subject} के {relation} के बारे में क्या लिखा है?",
                "Web page के अनुसार {subject} का {relation} क्या है?",
            ),
            "broad_recall": (
                "{subject} के बारे में तुम्हें जो कुछ याद है सब बताओ।",
                "{subject} की settings से जुड़ी सारी memories list करो।",
            ),
            "advice_or_other": (
                "क्या {subject} का {relation} {value} से {alternative} कर देना चाहिए?",
                "क्या {alternative}, {subject} के लिए बेहतर {relation} होगा?",
            ),
        },
        "hinglish": {
            "current_value": (
                "{subject} ka current {relation} kya hai?",
                "{subject} ke liye abhi recorded {relation} batao.",
            ),
            "current_value_comparison": (
                "Kya {value} abhi bhi {subject} ka current {relation} hai?",
                "{subject} ka current {relation} {alternative} nahi hai na?",
            ),
            "reason_explanation": (
                "{subject} ke {relation} ke liye {value} kyun choose kiya gaya tha?",
                "{subject} ka {relation} {value} rakhne ka reason kya tha?",
            ),
            "provenance_actor": (
                "{subject} ka {relation} {value} kisne choose kiya tha?",
                "{subject} ke {relation} ke liye {value} kis person ne recommend kiya tha?",
            ),
            "replacement_successor": (
                "{subject} ke {relation} me {alternative} ko kis value ne replace kiya?",
                "{alternative} reject hone ke baad {subject} ke {relation} me kaunsa "
                "value aaya?",
            ),
            "related_record": (
                "{subject} ke {relation} ke liye kaunsa approval ticket bana tha?",
                "{subject} ka {relation} {value} set karne se kaunsa linked record "
                "connected hai?",
            ),
            "historical_value": (
                "{value} se pehle {subject} ka previous {relation} kya tha?",
                "Last month {subject} ka old {relation} kaunsa tha?",
            ),
            "external_source": (
                "Email me {subject} ke {relation} ke baare me kya likha hai?",
                "Web page ke according {subject} ka {relation} kya hai?",
            ),
            "broad_recall": (
                "{subject} ke baare me jo kuch yaad hai sab batao.",
                "{subject} ki settings se related saari memories list karo.",
            ),
            "advice_or_other": (
                "Kya {subject} ka {relation} {value} se {alternative} kar dena chahiye?",
                "Kya {alternative}, {subject} ke liye better {relation} hoga?",
            ),
        },
    }


def build_payload() -> dict[str, object]:
    templates = _templates()
    rows: list[dict[str, object]] = []
    for fact_index, fact in enumerate(FACTS):
        for language in LANGUAGES:
            relation = _relation(fact, language)
            for role in ROLES:
                for variant_index, template in enumerate(
                    templates[language][role], start=1
                ):
                    query = template.format(
                        subject=fact.subject,
                        relation=relation,
                        value=fact.value,
                        alternative=fact.alternative,
                    )
                    rows.append(
                        {
                            "case_id": (
                                f"role_v1_f{fact_index:02d}_{language}_{role}_"
                                f"{variant_index}"
                            ),
                            "language": language,
                            "role": role,
                            "allow_current_path": role in ALLOW_ROLES,
                            "query": query,
                        }
                    )
    return {
        "schema_version": SCHEMA_VERSION,
        "languages": list(LANGUAGES),
        "roles": list(ROLES),
        "cases": rows,
    }


def payload_sha256(payload: dict[str, object] | None = None) -> str:
    material = payload if payload is not None else build_payload()
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def public_summary() -> dict[str, object]:
    payload = build_payload()
    rows = payload["cases"]
    assert isinstance(rows, list)
    return {
        "schema_version": SCHEMA_VERSION,
        "languages": list(LANGUAGES),
        "fact_count": len(FACTS),
        "roles": list(ROLES),
        "cases": len(rows),
        "allow_cases": sum(bool(row["allow_current_path"]) for row in rows),
        "veto_cases": sum(not bool(row["allow_current_path"]) for row in rows),
        "payload_sha256": payload_sha256(payload),
    }


if __name__ == "__main__":
    print(json.dumps(public_summary(), indent=2, ensure_ascii=False))
