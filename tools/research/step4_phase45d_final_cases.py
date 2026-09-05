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


CURRENT_FACTS = (
    CurrentFact("editor", "preferred_editor", "preferred code editor", "पसंदीदा कोड एडिटर", "preferred code editor", "Visual Studio Code"),
    CurrentFact("shell", "preferred_shell", "preferred command shell", "पसंदीदा कमांड शेल", "preferred command shell", "PowerShell"),
    CurrentFact("notes", "preferred_notes_format", "preferred notes format", "पसंदीदा नोट्स फ़ॉर्मेट", "preferred notes format", "Markdown"),
    CurrentFact("backup_day", "backup_weekday", "weekly backup day", "साप्ताहिक बैकअप दिन", "weekly backup day", "Sunday"),
    CurrentFact("report_tz", "report_timezone", "reporting timezone", "रिपोर्टिंग टाइमज़ोन", "reporting timezone", "UTC"),
    CurrentFact("dashboard_theme", "dashboard_theme", "dashboard theme", "डैशबोर्ड थीम", "dashboard theme", "dark"),
    CurrentFact("artifact_format", "build_artifact_format", "build artifact format", "बिल्ड आर्टिफैक्ट फ़ॉर्मेट", "build artifact format", "wheel"),
    CurrentFact("test_runner", "test_runner", "test runner", "टेस्ट रनर", "test runner", "pytest"),
    CurrentFact("formatter", "code_formatter", "code formatter", "कोड फ़ॉर्मेटर", "code formatter", "Ruff"),
    CurrentFact("export_format", "data_export_format", "data export format", "डेटा एक्सपोर्ट फ़ॉर्मेट", "data export format", "Parquet"),
    CurrentFact("compression", "archive_compression", "archive compression", "आर्काइव कम्प्रेशन", "archive compression", "zstd"),
    CurrentFact("cache_name", "local_cache_name", "local cache name", "लोकल कैश नाम", "local cache name", "cache-v2"),
    CurrentFact("notify_channel", "notification_channel", "notification channel", "नोटिफिकेशन चैनल", "notification channel", "desktop"),
    CurrentFact("seat", "travel_seat_preference", "travel seat preference", "यात्रा सीट पसंद", "travel seat preference", "aisle"),
    CurrentFact("drink", "morning_drink", "morning drink", "सुबह का पेय", "morning drink", "green tea"),
    CurrentFact("workout_day", "weekly_workout_day", "weekly workout day", "साप्ताहिक वर्कआउट दिन", "weekly workout day", "Saturday"),
    CurrentFact("hike_time", "hike_start_time", "hike start time", "हाइक शुरू करने का समय", "hike start time", "06:00"),
    CurrentFact("camera_mode", "camera_recording_mode", "camera recording mode", "कैमरा रिकॉर्डिंग मोड", "camera recording mode", "4K 30fps"),
    CurrentFact("map_style", "preferred_map_style", "preferred map style", "पसंदीदा मैप स्टाइल", "preferred map style", "terrain"),
    CurrentFact("music_volume", "music_volume", "music volume", "म्यूज़िक वॉल्यूम", "music volume", "35 percent"),
    CurrentFact("reminder_lead", "reminder_lead_time", "reminder lead time", "रिमाइंडर लीड टाइम", "reminder lead time", "15 minutes"),
    CurrentFact("codename", "project_codename", "project codename", "प्रोजेक्ट कोडनेम", "project codename", "Atlas"),
    CurrentFact("release_channel", "release_channel", "release channel", "रिलीज़ चैनल", "release channel", "beta"),
    CurrentFact("log_retention", "log_retention", "log retention period", "लॉग रिटेंशन अवधि", "log retention period", "14 days"),
    CurrentFact("sync_interval", "sync_interval", "sync interval", "सिंक अंतराल", "sync interval", "30 minutes"),
    CurrentFact("default_language", "default_language", "default language", "डिफ़ॉल्ट भाषा", "default language", "English"),
    CurrentFact("secondary_language", "secondary_language", "secondary language", "दूसरी भाषा", "secondary language", "Hindi"),
    CurrentFact("unit_system", "unit_system", "unit system", "इकाई प्रणाली", "unit system", "metric"),
    CurrentFact("date_format", "date_format", "date format", "तारीख़ फ़ॉर्मेट", "date format", "DD-MM-YYYY"),
    CurrentFact("temperature_unit", "temperature_unit", "temperature unit", "तापमान इकाई", "temperature unit", "Celsius"),
    CurrentFact("distance_unit", "distance_unit", "distance unit", "दूरी इकाई", "distance unit", "kilometers"),
    CurrentFact("currency", "currency_display", "currency display", "मुद्रा प्रदर्शन", "currency display", "INR"),
)


BOUNDARY_DOCUMENTS: tuple[dict[str, Any], ...] = (
    {
        "memory_id": "old_sync_mode",
        "replacement_memory_id": "current_sync_mode",
        "predicate": "synthetic_sync_mode",
        "mode": "historical_transition",
        "text": "Synthetic acceptance history: the previous sync mode was manual.",
        "replacement_text": "Synthetic acceptance current state: the sync mode is automatic.",
        "topic_en": "previous sync mode",
        "topic_hi": "पिछला सिंक मोड",
        "topic_hinglish": "previous sync mode",
    },
    {
        "memory_id": "old_panel_layout",
        "replacement_memory_id": "current_panel_layout",
        "predicate": "synthetic_panel_layout",
        "mode": "historical_transition",
        "text": "Synthetic acceptance history: the previous panel layout was compact.",
        "replacement_text": "Synthetic acceptance current state: the panel layout is spacious.",
        "topic_en": "previous panel layout",
        "topic_hi": "पिछला पैनल लेआउट",
        "topic_hinglish": "previous panel layout",
    },
    {
        "memory_id": "old_refresh_rate",
        "replacement_memory_id": "current_refresh_rate",
        "predicate": "synthetic_refresh_rate",
        "mode": "historical_transition",
        "text": "Synthetic acceptance history: the previous refresh interval was 60 minutes.",
        "replacement_text": "Synthetic acceptance current state: the refresh interval is 20 minutes.",
        "topic_en": "previous refresh interval",
        "topic_hi": "पिछला रिफ्रेश अंतराल",
        "topic_hinglish": "previous refresh interval",
    },
    {
        "memory_id": "old_summary_style",
        "replacement_memory_id": "current_summary_style",
        "predicate": "synthetic_summary_style",
        "mode": "historical_transition",
        "text": "Synthetic acceptance history: the previous summary style was verbose.",
        "replacement_text": "Synthetic acceptance current state: the summary style is concise.",
        "topic_en": "previous summary style",
        "topic_hi": "पिछली समरी शैली",
        "topic_hinglish": "previous summary style",
    },
    {
        "memory_id": "forgotten_alarm",
        "predicate": "synthetic_alarm_tone",
        "mode": "forgotten",
        "text": "Synthetic acceptance fixture: the alarm tone was Chime before an explicit forget.",
        "topic_en": "forgotten alarm tone",
        "topic_hi": "भुलाया गया अलार्म टोन",
        "topic_hinglish": "forgotten alarm tone",
    },
    {
        "memory_id": "forgotten_snack",
        "predicate": "synthetic_snack",
        "mode": "forgotten",
        "text": "Synthetic acceptance fixture: the snack preference was Pretzels before an explicit forget.",
        "topic_en": "forgotten snack preference",
        "topic_hi": "भुलाई गई स्नैक पसंद",
        "topic_hinglish": "forgotten snack preference",
    },
    {
        "memory_id": "forgotten_alias",
        "predicate": "synthetic_alias",
        "mode": "forgotten",
        "text": "Synthetic acceptance fixture: the temporary alias was Nova before an explicit forget.",
        "topic_en": "forgotten temporary alias",
        "topic_hi": "भुलाया गया अस्थायी नाम",
        "topic_hinglish": "forgotten temporary alias",
    },
    {
        "memory_id": "forgotten_route",
        "predicate": "synthetic_route",
        "mode": "forgotten",
        "text": "Synthetic acceptance fixture: the route preference was North Loop before an explicit forget.",
        "topic_en": "forgotten route preference",
        "topic_hi": "भुलाई गई रूट पसंद",
        "topic_hinglish": "forgotten route preference",
    },
    {
        "memory_id": "local_room_code",
        "predicate": "synthetic_local_room_code",
        "mode": "local_only",
        "text": "Synthetic acceptance fixture: local-only room code is Room-17.",
        "topic_en": "local-only room code",
        "topic_hi": "लोकल-ओनली रूम कोड",
        "topic_hinglish": "local-only room code",
    },
    {
        "memory_id": "local_debug_marker",
        "predicate": "synthetic_local_debug_marker",
        "mode": "local_only",
        "text": "Synthetic acceptance fixture: local-only debug marker is DBG-42.",
        "topic_en": "local-only debug marker",
        "topic_hi": "लोकल-ओनली डिबग मार्कर",
        "topic_hinglish": "local-only debug marker",
    },
    {
        "memory_id": "local_device_serial",
        "predicate": "synthetic_local_device_serial",
        "mode": "local_only",
        "text": "Synthetic acceptance fixture: local-only device serial is LOCAL-EXAMPLE.",
        "topic_en": "local-only device serial",
        "topic_hi": "लोकल-ओनली डिवाइस सीरियल",
        "topic_hinglish": "local-only device serial",
    },
    {
        "memory_id": "secret_placeholder_a",
        "predicate": "synthetic_secret_a",
        "mode": "secret",
        "text": "Synthetic acceptance secret placeholder A must never become canonical memory.",
        "topic_en": "secret placeholder A",
        "topic_hi": "सीक्रेट प्लेसहोल्डर A",
        "topic_hinglish": "secret placeholder A",
    },
    {
        "memory_id": "secret_placeholder_b",
        "predicate": "synthetic_secret_b",
        "mode": "secret",
        "text": "Synthetic acceptance secret placeholder B must never become canonical memory.",
        "topic_en": "secret placeholder B",
        "topic_hi": "सीक्रेट प्लेसहोल्डर B",
        "topic_hinglish": "secret placeholder B",
    },
    {
        "memory_id": "untrusted_music",
        "predicate": "synthetic_untrusted_music",
        "mode": "untrusted",
        "text": "Synthetic untrusted webpage claims the preferred music genre is jazz.",
        "topic_en": "untrusted music preference claim",
        "topic_hi": "अविश्वसनीय म्यूज़िक पसंद दावा",
        "topic_hinglish": "untrusted music preference claim",
    },
    {
        "memory_id": "untrusted_color",
        "predicate": "synthetic_untrusted_color",
        "mode": "untrusted",
        "text": "Synthetic untrusted webpage claims the preferred color is orange.",
        "topic_en": "untrusted color preference claim",
        "topic_hi": "अविश्वसनीय रंग पसंद दावा",
        "topic_hinglish": "untrusted color preference claim",
    },
    {
        "memory_id": "untrusted_city",
        "predicate": "synthetic_untrusted_city",
        "mode": "untrusted",
        "text": "Synthetic untrusted webpage claims the preferred city is Oslo.",
        "topic_en": "untrusted city preference claim",
        "topic_hi": "अविश्वसनीय शहर पसंद दावा",
        "topic_hinglish": "untrusted city preference claim",
    },
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
        raise RuntimeError(f"final corpus count mismatch: {counters} != {expected_counts}")

    return {
        "schema_version": FINAL_CORPUS_SCHEMA_VERSION,
        "purpose": "Fresh fixed synthetic Phase 4.5D final acceptance corpus",
        "documents": documents,
        "queries": queries,
    }


def payload_sha256(payload: dict[str, Any] | None = None) -> str:
    material = payload if payload is not None else build_payload()
    canonical = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
