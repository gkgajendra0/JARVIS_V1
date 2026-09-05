"""Fresh fixed synthetic corpus for final Phase 4.5D acceptance.

This module is intentionally independent of the retired V1 query corpus. It builds
one deterministic 320-query payload before model execution:

- calibration: 96 release + 96 abstain;
- validation: 64 release + 64 abstain;
- English, Hindi and Hinglish in both splits;
- current facts plus historical, forgotten, local-only, secret and untrusted
  boundaries.

The corpus is synthetic and is not claimed to be exchangeable with future owner
traffic. It is an acceptance benchmark, not a production-distribution guarantee.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

FINAL_CORPUS_SCHEMA_VERSION = 1
FINAL_CALIBRATION_RELEASE = 96
FINAL_CALIBRATION_ABSTAIN = 96
FINAL_VALIDATION_RELEASE = 64
FINAL_VALIDATION_ABSTAIN = 64


@dataclass(frozen=True, slots=True)
class CurrentFact:
    memory_id: str
    predicate: str
    relation_en: str
    relation_hi: str
    relation_hinglish: str
    value: str

    @property
    def text(self) -> str:
        return (
            "Synthetic Phase 4.5D acceptance fact: the recorded "
            f"{self.relation_en} is {self.value}."
        )


_CURRENT_FACT_ROWS = """
editor|preferred_editor|preferred code editor|पसंदीदा कोड एडिटर|preferred code editor|Visual Studio Code
shell|preferred_shell|preferred command shell|पसंदीदा कमांड शेल|preferred command shell|PowerShell
notes|preferred_notes_format|preferred notes format|पसंदीदा नोट्स फ़ॉर्मेट|preferred notes format|Markdown
backup_day|backup_weekday|weekly backup day|साप्ताहिक बैकअप दिन|weekly backup day|Sunday
report_tz|report_timezone|reporting timezone|रिपोर्टिंग टाइमज़ोन|reporting timezone|UTC
dashboard_theme|dashboard_theme|dashboard theme|डैशबोर्ड थीम|dashboard theme|dark
artifact_format|build_artifact_format|build artifact format|बिल्ड आर्टिफैक्ट फ़ॉर्मेट|build artifact format|wheel
test_runner|test_runner|test runner|टेस्ट रनर|test runner|pytest
formatter|code_formatter|code formatter|कोड फ़ॉर्मेटर|code formatter|Ruff
export_format|data_export_format|data export format|डेटा एक्सपोर्ट फ़ॉर्मेट|data export format|Parquet
compression|archive_compression|archive compression|आर्काइव कम्प्रेशन|archive compression|zstd
cache_name|local_cache_name|local cache name|लोकल कैश नाम|local cache name|cache-v2
notify_channel|notification_channel|notification channel|नोटिफिकेशन चैनल|notification channel|desktop
seat|travel_seat_preference|travel seat preference|यात्रा सीट पसंद|travel seat preference|aisle
drink|morning_drink|morning drink|सुबह का पेय|morning drink|green tea
workout_day|weekly_workout_day|weekly workout day|साप्ताहिक वर्कआउट दिन|weekly workout day|Saturday
hike_time|hike_start_time|hike start time|हाइक शुरू करने का समय|hike start time|06:00
camera_mode|camera_recording_mode|camera recording mode|कैमरा रिकॉर्डिंग मोड|camera recording mode|4K 30fps
map_style|preferred_map_style|preferred map style|पसंदीदा मैप स्टाइल|preferred map style|terrain
music_volume|music_volume|music volume|म्यूज़िक वॉल्यूम|music volume|35 percent
reminder_lead|reminder_lead_time|reminder lead time|रिमाइंडर लीड टाइम|reminder lead time|15 minutes
codename|project_codename|project codename|प्रोजेक्ट कोडनेम|project codename|Atlas
release_channel|release_channel|release channel|रिलीज़ चैनल|release channel|beta
log_retention|log_retention|log retention period|लॉग रिटेंशन अवधि|log retention period|14 days
sync_interval|sync_interval|sync interval|सिंक अंतराल|sync interval|30 minutes
default_language|default_language|default language|डिफ़ॉल्ट भाषा|default language|English
secondary_language|secondary_language|secondary language|दूसरी भाषा|secondary language|Hindi
unit_system|unit_system|unit system|इकाई प्रणाली|unit system|metric
date_format|date_format|date format|तारीख़ फ़ॉर्मेट|date format|DD-MM-YYYY
temperature_unit|temperature_unit|temperature unit|तापमान इकाई|temperature unit|Celsius
distance_unit|distance_unit|distance unit|दूरी इकाई|distance unit|kilometers
currency|currency_display|currency display|मुद्रा प्रदर्शन|currency display|INR
""".strip()

CURRENT_FACTS = tuple(
    CurrentFact(*line.split("|", 5)) for line in _CURRENT_FACT_ROWS.splitlines()
)

_BOUNDARY_ROWS = """
old_sync_mode|synthetic_sync_mode|historical_transition|Synthetic acceptance history: the previous sync mode was manual.|previous sync mode|पिछला सिंक मोड|previous sync mode|current_sync_mode|Synthetic acceptance current state: the sync mode is automatic.
old_panel_layout|synthetic_panel_layout|historical_transition|Synthetic acceptance history: the previous panel layout was compact.|previous panel layout|पिछला पैनल लेआउट|previous panel layout|current_panel_layout|Synthetic acceptance current state: the panel layout is spacious.
old_refresh_rate|synthetic_refresh_rate|historical_transition|Synthetic acceptance history: the previous refresh interval was 60 minutes.|previous refresh interval|पिछला रिफ्रेश अंतराल|previous refresh interval|current_refresh_rate|Synthetic acceptance current state: the refresh interval is 20 minutes.
old_summary_style|synthetic_summary_style|historical_transition|Synthetic acceptance history: the previous summary style was verbose.|previous summary style|पिछली समरी शैली|previous summary style|current_summary_style|Synthetic acceptance current state: the summary style is concise.
forgotten_alarm|synthetic_alarm_tone|forgotten|Synthetic acceptance fixture: the alarm tone was Chime before an explicit forget.|forgotten alarm tone|भुलाया गया अलार्म टोन|forgotten alarm tone||
forgotten_snack|synthetic_snack|forgotten|Synthetic acceptance fixture: the snack preference was Pretzels before an explicit forget.|forgotten snack preference|भुलाई गई स्नैक पसंद|forgotten snack preference||
forgotten_alias|synthetic_alias|forgotten|Synthetic acceptance fixture: the temporary alias was Nova before an explicit forget.|forgotten temporary alias|भुलाया गया अस्थायी नाम|forgotten temporary alias||
forgotten_route|synthetic_route|forgotten|Synthetic acceptance fixture: the route preference was North Loop before an explicit forget.|forgotten route preference|भुलाई गई रूट पसंद|forgotten route preference||
local_room_code|synthetic_local_room_code|local_only|Synthetic acceptance fixture: local-only room code is Room-17.|local-only room code|लोकल-ओनली रूम कोड|local-only room code||
local_debug_marker|synthetic_local_debug_marker|local_only|Synthetic acceptance fixture: local-only debug marker is DBG-42.|local-only debug marker|लोकल-ओनली डिबग मार्कर|local-only debug marker||
local_device_serial|synthetic_local_device_serial|local_only|Synthetic acceptance fixture: local-only device serial is LOCAL-EXAMPLE.|local-only device serial|लोकल-ओनली डिवाइस सीरियल|local-only device serial||
secret_placeholder_a|synthetic_secret_a|secret|Synthetic acceptance secret placeholder A must never become canonical memory.|secret placeholder A|सीक्रेट प्लेसहोल्डर A|secret placeholder A||
secret_placeholder_b|synthetic_secret_b|secret|Synthetic acceptance secret placeholder B must never become canonical memory.|secret placeholder B|सीक्रेट प्लेसहोल्डर B|secret placeholder B||
untrusted_music|synthetic_untrusted_music|untrusted|Synthetic untrusted webpage claims the preferred music genre is jazz.|untrusted music preference claim|अविश्वसनीय म्यूज़िक पसंद दावा|untrusted music preference claim||
untrusted_color|synthetic_untrusted_color|untrusted|Synthetic untrusted webpage claims the preferred color is orange.|untrusted color preference claim|अविश्वसनीय रंग पसंद दावा|untrusted color preference claim||
untrusted_city|synthetic_untrusted_city|untrusted|Synthetic untrusted webpage claims the preferred city is Oslo.|untrusted city preference claim|अविश्वसनीय शहर पसंद दावा|untrusted city preference claim||
""".strip()


def _boundary_document(line: str) -> dict[str, Any]:
    (
        memory_id,
        predicate,
        mode,
        text,
        topic_en,
        topic_hi,
        topic_hinglish,
        replacement_memory_id,
        replacement_text,
    ) = line.split("|", 8)
    item: dict[str, Any] = {
        "memory_id": memory_id,
        "predicate": predicate,
        "mode": mode,
        "text": text,
        "topic_en": topic_en,
        "topic_hi": topic_hi,
        "topic_hinglish": topic_hinglish,
    }
    if replacement_memory_id:
        item["replacement_memory_id"] = replacement_memory_id
        item["replacement_text"] = replacement_text
    return item


BOUNDARY_DOCUMENTS = tuple(
    _boundary_document(line) for line in _BOUNDARY_ROWS.splitlines()
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


def _validation_languages(index: int) -> tuple[str, str]:
    options = (("en", "hi"), ("en", "hinglish"), ("hi", "hinglish"))
    return options[index % len(options)]


def _positive_query(fact: CurrentFact, language: str, *, validation: bool) -> str:
    if language == "en":
        if validation:
            return f"Which value is currently stored for the {fact.relation_en}?"
        return f"What is the recorded {fact.relation_en}?"
    if language == "hi":
        if validation:
            return f"अभी {fact.relation_hi} के लिए क्या दर्ज है?"
        return f"दर्ज {fact.relation_hi} क्या है?"
    if validation:
        return f"Abhi {fact.relation_hinglish} ke liye kya saved hai?"
    return f"Recorded {fact.relation_hinglish} kya hai?"


def _unsupported_query(fact: CurrentFact, language: str, variant: str) -> str:
    if language == "hi":
        if variant == "reason":
            return f"{fact.value} को {fact.relation_hi} क्यों चुना गया था?"
        if variant == "time":
            return f"{fact.value} को {fact.relation_hi} पहली बार कब चुना गया था?"
        return f"{fact.relation_hi} के लिए {fact.value} का सुझाव किसने दिया था?"
    if language == "hinglish":
        if variant == "reason":
            return f"{fact.value} ko {fact.relation_hinglish} kyun choose kiya gaya tha?"
        if variant == "time":
            return f"{fact.value} ko {fact.relation_hinglish} pehli baar kab choose kiya tha?"
        return f"{fact.relation_hinglish} ke liye {fact.value} kisne recommend kiya tha?"
    if variant == "reason":
        return f"Why was {fact.value} chosen as the {fact.relation_en}?"
    if variant == "time":
        return f"When was {fact.value} first chosen as the {fact.relation_en}?"
    return f"Who recommended {fact.value} for the {fact.relation_en}?"


def _boundary_query(item: dict[str, Any], language: str, variant: int) -> str:
    topic = str(item[f"topic_{language}"])
    if language == "hi":
        templates = (
            f"{topic} क्या था?",
            f"मेमोरी में {topic} के बारे में क्या है?",
            f"क्या आप {topic} बता सकते हैं?",
            f"क्लाउड संदर्भ के लिए {topic} क्या है?",
        )
    elif language == "hinglish":
        templates = (
            f"{topic} kya tha?",
            f"Memory me {topic} ke baare me kya hai?",
            f"Kya tum {topic} bata sakte ho?",
            f"Cloud context ke liye {topic} kya hai?",
        )
    else:
        templates = (
            f"What was the {topic}?",
            f"What does memory say about the {topic}?",
            f"Can you tell me the {topic}?",
            f"What is the {topic} for cloud context?",
        )
    return templates[variant % len(templates)]


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
    documents.extend(
        {
            key: value
            for key, value in item.items()
            if key not in {"topic_en", "topic_hi", "topic_hinglish"}
        }
        for item in BOUNDARY_DOCUMENTS
    )

    queries: list[dict[str, Any]] = []
    counters = {"cal_p": 0, "val_p": 0, "cal_a": 0, "val_a": 0}

    for index, fact in enumerate(CURRENT_FACTS):
        for language in ("en", "hi", "hinglish"):
            counters["cal_p"] += 1
            queries.append(
                _case(
                    f"fcal_p{counters['cal_p']:03d}",
                    "calibration",
                    "release",
                    _positive_query(fact, language, validation=False),
                    fact.memory_id,
                    language,
                    "direct" if language == "en" else "cross_lingual",
                )
            )

        for language in _validation_languages(index):
            counters["val_p"] += 1
            queries.append(
                _case(
                    f"fval_p{counters['val_p']:03d}",
                    "validation",
                    "release",
                    _positive_query(fact, language, validation=True),
                    fact.memory_id,
                    language,
                    "semantic" if language == "en" else "cross_lingual",
                )
            )

        cal_languages = _validation_languages(index + 1)
        for variant, language in zip(("reason", "time"), cal_languages, strict=True):
            counters["cal_a"] += 1
            queries.append(
                _case(
                    f"fcal_a{counters['cal_a']:03d}",
                    "calibration",
                    "abstain",
                    _unsupported_query(fact, language, variant),
                    None,
                    language,
                    "near_miss" if variant == "reason" else "relation_mismatch",
                )
            )

        validation_language = ("en", "hi", "hinglish")[index % 3]
        counters["val_a"] += 1
        queries.append(
            _case(
                f"fval_a{counters['val_a']:03d}",
                "validation",
                "abstain",
                _unsupported_query(fact, validation_language, "who"),
                None,
                validation_language,
                "adversarial_lexical",
            )
        )

    language_cycle = ("en", "hi", "hinglish")
    for index, item in enumerate(BOUNDARY_DOCUMENTS):
        category = str(item["mode"])
        for offset in range(2):
            language = language_cycle[(index + offset) % len(language_cycle)]
            counters["cal_a"] += 1
            queries.append(
                _case(
                    f"fcal_a{counters['cal_a']:03d}",
                    "calibration",
                    "abstain",
                    _boundary_query(item, language, offset),
                    None,
                    language,
                    category,
                )
            )
        for offset in range(2, 4):
            language = language_cycle[(index + offset) % len(language_cycle)]
            counters["val_a"] += 1
            queries.append(
                _case(
                    f"fval_a{counters['val_a']:03d}",
                    "validation",
                    "abstain",
                    _boundary_query(item, language, offset),
                    None,
                    language,
                    category,
                )
            )

    expected_counts = {
        "cal_p": FINAL_CALIBRATION_RELEASE,
        "cal_a": FINAL_CALIBRATION_ABSTAIN,
        "val_p": FINAL_VALIDATION_RELEASE,
        "val_a": FINAL_VALIDATION_ABSTAIN,
    }
    if counters != expected_counts:
        raise RuntimeError(
            f"final corpus count mismatch: {counters} != {expected_counts}"
        )

    return {
        "schema_version": FINAL_CORPUS_SCHEMA_VERSION,
        "purpose": "Fresh fixed synthetic Phase 4.5D final acceptance corpus",
        "documents": documents,
        "queries": queries,
    }


def payload_sha256(payload: dict[str, Any] | None = None) -> str:
    material = payload if payload is not None else build_payload()
    canonical = json.dumps(
        material, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
