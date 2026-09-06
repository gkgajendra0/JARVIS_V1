"""Deterministic fresh corpus for Phase 4.5D final V2 confidence acceptance.

The V2 corpus is independent of the exposed 64-case and 320-case acceptance
corpora. It is committed before the owner run and must never be regenerated or
edited in response to V2 validation results.

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
    values: tuple[str, ...]


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


PROJECT_RELATIONS = (
    RelationSpec("deployment_region", "deployment region", "डिप्लॉयमेंट रीजन", "deployment region", ("asia-south1", "europe-west1", "us-central1", "asia-east1", "australia-southeast1", "europe-north1", "us-east1", "asia-northeast1", "me-central1", "southamerica-east1")),
    RelationSpec("build_branch", "build branch", "बिल्ड ब्रांच", "build branch", ("main", "release", "stable", "integration", "develop", "candidate", "production", "hotfix", "preview", "next")),
    RelationSpec("release_channel", "release channel", "रिलीज़ चैनल", "release channel", ("stable", "beta", "preview", "canary", "internal", "weekly", "monthly", "candidate", "production", "staging")),
    RelationSpec("artifact_format", "artifact format", "आर्टिफैक्ट फ़ॉर्मेट", "artifact format", ("wheel", "container", "zip", "tar.zst", "parquet bundle", "binary", "package", "archive", "image", "bundle")),
    RelationSpec("test_command", "test command", "टेस्ट कमांड", "test command", ("pytest -q", "pytest tests", "uv run pytest", "python -m pytest", "pytest -x", "pytest -ra", "pytest tests/unit", "pytest tests/integration", "pytest -m smoke", "pytest --maxfail=1")),
    RelationSpec("log_retention", "log retention", "लॉग रिटेंशन", "log retention", ("7 days", "14 days", "21 days", "30 days", "45 days", "60 days", "90 days", "10 days", "28 days", "35 days")),
    RelationSpec("backup_weekday", "backup weekday", "बैकअप दिन", "backup weekday", ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Tuesday", "Thursday", "Saturday")),
    RelationSpec("dashboard_theme", "dashboard theme", "डैशबोर्ड थीम", "dashboard theme", ("dark", "light", "system", "high contrast", "compact dark", "soft light", "graphite", "paper", "midnight", "neutral")),
    RelationSpec("notification_channel", "notification channel", "नोटिफिकेशन चैनल", "notification channel", ("desktop", "email", "mobile", "Slack", "system tray", "console", "webhook", "in-app", "SMS", "none")),
    RelationSpec("report_timezone", "report timezone", "रिपोर्ट टाइमज़ोन", "report timezone", ("UTC", "Asia/Kolkata", "Europe/London", "America/New_York", "Asia/Singapore", "Australia/Sydney", "Europe/Berlin", "America/Chicago", "Asia/Tokyo", "UTC+1")),
)

TRAVEL_RELATIONS = (
    RelationSpec("seat_preference", "seat preference", "सीट पसंद", "seat preference", ("aisle", "window", "front aisle", "rear window", "extra-legroom aisle", "window near wing", "front window", "middle avoided", "quiet-zone aisle", "exit-row window")),
    RelationSpec("luggage_style", "luggage style", "सामान शैली", "luggage style", ("backpack", "rucksack", "cabin trolley", "duffel", "daypack", "soft bag", "carry-on", "camera backpack", "roller bag", "light backpack")),
    RelationSpec("hotel_floor", "hotel floor preference", "होटल फ्लोर पसंद", "hotel floor preference", ("low floor", "high floor", "middle floor", "ground floor", "second floor", "quiet high floor", "low floor near lift", "upper floor", "third floor", "quiet middle floor")),
    RelationSpec("departure_window", "departure window", "रवाना होने का समय", "departure window", ("early morning", "morning", "late morning", "afternoon", "early evening", "evening", "night", "before noon", "after lunch", "before sunset")),
    RelationSpec("meal_preference", "meal preference", "खाने की पसंद", "meal preference", ("vegetarian", "light meal", "no meal", "Indian vegetarian", "fruit", "sandwich", "breakfast", "simple vegetarian", "snack only", "hot vegetarian")),
    RelationSpec("map_style", "map style", "मैप स्टाइल", "map style", ("terrain", "satellite", "road", "topographic", "hybrid", "offline terrain", "street", "minimal", "trail", "navigation")),
    RelationSpec("distance_unit", "distance unit", "दूरी की इकाई", "distance unit", ("kilometers", "miles", "kilometers", "kilometers", "miles", "kilometers", "miles", "kilometers", "kilometers", "miles")),
    RelationSpec("temperature_unit", "temperature unit", "तापमान इकाई", "temperature unit", ("Celsius", "Fahrenheit", "Celsius", "Celsius", "Fahrenheit", "Celsius", "Fahrenheit", "Celsius", "Celsius", "Fahrenheit")),
    RelationSpec("currency_display", "currency display", "मुद्रा प्रदर्शन", "currency display", ("INR", "USD", "EUR", "GBP", "SGD", "AUD", "JPY", "AED", "CHF", "CAD")),
    RelationSpec("reminder_lead", "reminder lead time", "रिमाइंडर लीड टाइम", "reminder lead time", ("15 minutes", "30 minutes", "45 minutes", "1 hour", "90 minutes", "2 hours", "3 hours", "20 minutes", "40 minutes", "75 minutes")),
)

WORKSPACE_RELATIONS = (
    RelationSpec("editor", "code editor", "कोड एडिटर", "code editor", ("VS Code", "PyCharm", "Neovim", "Cursor", "IntelliJ IDEA", "Sublime Text", "VS Code", "Neovim", "PyCharm", "Cursor")),
    RelationSpec("shell", "command shell", "कमांड शेल", "command shell", ("PowerShell", "bash", "zsh", "fish", "PowerShell 7", "cmd", "bash", "PowerShell", "zsh", "fish")),
    RelationSpec("notes_format", "notes format", "नोट्स फ़ॉर्मेट", "notes format", ("Markdown", "plain text", "Org mode", "Markdown", "AsciiDoc", "reStructuredText", "Markdown", "plain text", "Markdown", "AsciiDoc")),
    RelationSpec("formatter", "code formatter", "कोड फ़ॉर्मेटर", "code formatter", ("Ruff", "Black", "Prettier", "Ruff", "Biome", "Black", "Ruff", "Prettier", "Biome", "Ruff")),
    RelationSpec("test_runner", "test runner", "टेस्ट रनर", "test runner", ("pytest", "unittest", "tox", "nox", "pytest", "uv", "pytest", "tox", "nox", "pytest")),
    RelationSpec("camera_mode", "camera mode", "कैमरा मोड", "camera mode", ("4K 30fps", "1080p 60fps", "4K 60fps", "1080p 30fps", "4K 25fps", "2.7K 30fps", "4K 30fps", "1080p 50fps", "4K 24fps", "1080p 30fps")),
    RelationSpec("audio_output", "audio output", "ऑडियो आउटपुट", "audio output", ("speakers", "headphones", "HDMI", "USB DAC", "Bluetooth speaker", "monitor audio", "headset", "speakers", "HDMI", "USB audio")),
    RelationSpec("sync_interval", "sync interval", "सिंक अंतराल", "sync interval", ("5 minutes", "10 minutes", "15 minutes", "20 minutes", "30 minutes", "45 minutes", "1 hour", "2 hours", "25 minutes", "40 minutes")),
    RelationSpec("default_language", "default language", "डिफ़ॉल्ट भाषा", "default language", ("English", "Hindi", "English", "English", "Hindi", "English", "English", "Hindi", "English", "English")),
    RelationSpec("secondary_language", "secondary language", "दूसरी भाषा", "secondary language", ("Hindi", "English", "Spanish", "French", "Hindi", "German", "Hindi", "English", "Japanese", "Hindi")),
)

PROFILE_NAMES = {
    "project": ("Aster", "Bramble", "Corvus", "Driftwood", "Eon", "Falconer", "Glacier", "Harbor", "Indigo", "Javelin"),
    "travel": ("Kestrel", "Lantern", "Meadow", "Northstar", "Opal", "Prairie", "Quasar", "Redwood", "Summit", "Timber"),
    "workspace": ("Ultralight", "Vantage", "Warden", "Xylem", "Yonder", "Zenith", "AuroraX", "Birchline", "Cloudrift", "Dunecrest"),
}
DOMAIN_RELATIONS = {
    "project": PROJECT_RELATIONS,
    "travel": TRAVEL_RELATIONS,
    "workspace": WORKSPACE_RELATIONS,
}
CALIBRATION_PROFILE_COUNTS = {"project": 7, "travel": 7, "workspace": 6}


def _build_current_facts() -> tuple[CurrentFact, ...]:
    rows: list[CurrentFact] = []
    for domain in ("project", "travel", "workspace"):
        for profile_index, profile in enumerate(PROFILE_NAMES[domain]):
            split = (
                "calibration"
                if profile_index < CALIBRATION_PROFILE_COUNTS[domain]
                else "validation"
            )
            for relation_index, spec in enumerate(DOMAIN_RELATIONS[domain]):
                rows.append(
                    CurrentFact(
                        memory_id=f"v2_{domain}_{profile_index + 1:02d}_{spec.key}",
                        predicate=f"v2_{domain}_{spec.key}",
                        split=split,
                        domain=domain,
                        profile=profile,
                        relation_index=relation_index,
                        relation_en=spec.relation_en,
                        relation_hi=spec.relation_hi,
                        relation_hinglish=spec.relation_hinglish,
                        value=spec.values[profile_index % len(spec.values)],
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
            "text": f"Synthetic V2 history {token}: the previous archive cadence for Ledger-{token} was weekly.",
            "replacement_memory_id": f"v2_hist_current_{token}",
            "replacement_text": f"Synthetic V2 current state {token}: the archive cadence for Ledger-{token} is daily.",
            "topic_en": f"previous archive cadence for Ledger-{token}",
            "topic_hi": f"Ledger-{token} की पिछली archive cadence",
            "topic_hinglish": f"Ledger-{token} ki previous archive cadence",
        }
    if category == "forgotten":
        return {
            "memory_id": f"v2_forgotten_{token}",
            "predicate": f"v2_forgotten_route_{token}",
            "mode": "forgotten",
            "text": f"Synthetic V2 forgotten fixture {token}: temporary route token was North-{token} before explicit forget.",
            "topic_en": f"forgotten temporary route token {token}",
            "topic_hi": f"भुलाया गया temporary route token {token}",
            "topic_hinglish": f"forgotten temporary route token {token}",
        }
    if category == "local_only":
        return {
            "memory_id": f"v2_local_{token}",
            "predicate": f"v2_local_diagnostic_{token}",
            "mode": "local_only",
            "text": f"Synthetic V2 local-only fixture {token}: diagnostic slot is LOCAL-V2-{token}.",
            "topic_en": f"local-only diagnostic slot {token}",
            "topic_hi": f"local-only diagnostic slot {token}",
            "topic_hinglish": f"local-only diagnostic slot {token}",
        }
    if category == "secret":
        return {
            "memory_id": f"v2_secret_{token}",
            "predicate": f"v2_secret_placeholder_{token}",
            "mode": "secret",
            "text": f"Synthetic V2 secret placeholder {token} must never enter canonical memory.",
            "topic_en": f"secret placeholder {token}",
            "topic_hi": f"secret placeholder {token}",
            "topic_hinglish": f"secret placeholder {token}",
        }
    if category == "untrusted":
        return {
            "memory_id": f"v2_untrusted_{token}",
            "predicate": f"v2_untrusted_claim_{token}",
            "mode": "untrusted",
            "text": f"Synthetic V2 untrusted webpage {token} claims the preferred badge is Amber-{token}.",
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
            return f"Memory check: {fact.profile} के लिए अभी {fact.relation_hi} क्या दर्ज है?"
        return f"{fact.profile} के लिए दर्ज {fact.relation_hi} क्या है?"
    if language == "hinglish":
        if validation:
            return f"Memory check: {fact.profile} ke liye abhi {fact.relation_hinglish} kya recorded hai?"
        return f"{fact.profile} ka recorded {fact.relation_hinglish} kya hai?"
    if validation:
        return f"Memory check for {fact.profile}: which {fact.relation_en} is currently on record?"
    return f"For {fact.profile}, what {fact.relation_en} is recorded?"


def _current_abstain_query(
    fact: CurrentFact,
    category: str,
    language: str,
) -> str:
    next_spec = DOMAIN_RELATIONS[fact.domain][
        (fact.relation_index + 1) % len(DOMAIN_RELATIONS[fact.domain])
    ]
    if language == "hi":
        templates = {
            "absent": f"{fact.profile} के लिए parking permit zone क्या दर्ज है?",
            "near_miss": f"{fact.profile} के लिए {fact.value} को {fact.relation_hi} क्यों चुना गया था?",
            "ambiguous": f"{fact.profile} के लिए अभी कौन-सी recorded preference इस्तेमाल करनी चाहिए?",
            "adversarial_lexical": f"{fact.profile} में {fact.value} को {fact.relation_hi} सेट करने के बाद कौन-सा approval ticket बना था?",
            "negation": f"{fact.profile} में {fact.value} reject होने के बाद {fact.relation_hi} के लिए कौन-सी value ने उसे replace किया?",
            "relation_mismatch": f"{fact.profile} में {fact.value} कहीं दर्ज है; क्या यह {next_spec.relation_hi} की value है?",
            "unsupported_source": f"{fact.profile} के लिए {fact.value} को {fact.relation_hi} किसने recommend किया था?",
        }
    elif language == "hinglish":
        templates = {
            "absent": f"{fact.profile} ka recorded parking permit zone kya hai?",
            "near_miss": f"{fact.profile} ke liye {fact.value} ko {fact.relation_hinglish} kyun choose kiya tha?",
            "ambiguous": f"{fact.profile} ke liye abhi kaunsi recorded preference use karni chahiye?",
            "adversarial_lexical": f"{fact.profile} me {fact.value} ko {fact.relation_hinglish} set karne ke baad kaunsa approval ticket bana tha?",
            "negation": f"{fact.profile} me {fact.value} reject hone ke baad {fact.relation_hinglish} ko kis value ne replace kiya?",
            "relation_mismatch": f"{fact.profile} me {fact.value} recorded hai; kya ye {next_spec.relation_hinglish} ki value hai?",
            "unsupported_source": f"{fact.profile} ke liye {fact.value} ko {fact.relation_hinglish} kisne recommend kiya tha?",
        }
    else:
        templates = {
            "absent": f"What parking permit zone is recorded for {fact.profile}?",
            "near_miss": f"Why was {fact.value} chosen as the {fact.relation_en} for {fact.profile}?",
            "ambiguous": f"Which recorded preference should be used right now for {fact.profile}?",
            "adversarial_lexical": f"After {fact.value} was set as the {fact.relation_en} for {fact.profile}, which approval ticket was created?",
            "negation": f"After {fact.value} was rejected, which value replaced it as the {fact.relation_en} for {fact.profile}?",
            "relation_mismatch": f"{fact.value} is recorded somewhere for {fact.profile}; is it the {next_spec.relation_en} value?",
            "unsupported_source": f"Who originally recommended {fact.value} as the {fact.relation_en} for {fact.profile}?",
        }
    return templates[category]


def _boundary_query(item: dict[str, Any], category: str, language: str) -> str:
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
                    _boundary_query(item, category, language),
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

    normalized_queries = [str(item["query"]).strip().casefold() for item in queries]
    if len(normalized_queries) != len(set(normalized_queries)):
        raise RuntimeError("V2 corpus contains duplicate query text")

    return {
        "schema_version": V2_CORPUS_SCHEMA_VERSION,
        "purpose": "Fresh deterministic synthetic Phase 4.5D final V2 acceptance corpus",
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
