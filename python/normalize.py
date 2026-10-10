from __future__ import annotations

import json
import re

MAX_PREFERENCE = 100
MAX_GOAL = 100
MAX_TOPIC = 60
MAX_TASK_FIELD = 120
MAX_OPEN_TASKS = 10
MAX_CLOSED_TASKS = 10

TOPIC_STOPWORDS = {
    "тема", "topic", "задача", "вопрос", "выбор", "the", "and", "for", "with",
    "про", "для", "по", "и", "или",
}

_TOPIC_PREFIX_RE = re.compile(r"^(?:тема|topic|задача|вопрос)\s*[:\-—]?\s*", re.IGNORECASE)
_TOPIC_TRIM_RE = re.compile(r"[«»\"'`()\[\]]")
_WHITESPACE_RE = re.compile(r"\s+")


def truncate_text(value, limit: int) -> tuple[str, bool]:
    text = _WHITESPACE_RE.sub(" ", str(value)).strip()
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-—-"), True


def topic_key(topic: str) -> str:
    text = _TOPIC_PREFIX_RE.sub("", str(topic).strip().lower())
    text = _TOPIC_TRIM_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip(" .,:;-—")


def _topic_tokens(key: str) -> set:
    return {
        word
        for word in re.findall(r"\w+", key)
        if len(word) > 3 and word not in TOPIC_STOPWORDS
    }


def topics_similar(key_a: str, key_b: str) -> bool:
    if not key_a or not key_b:
        return False
    if key_a == key_b:
        return True
    tokens_a, tokens_b = _topic_tokens(key_a), _topic_tokens(key_b)
    if not tokens_a or not tokens_b:
        return False
    common = tokens_a & tokens_b
    if not common:
        return False
    return len(common) / min(len(tokens_a), len(tokens_b)) >= 0.5


def _log(text: str, reason: str) -> dict:
    return {"text": text, "reason": reason}


def _clean_list(items: list, limit: int, label: str, logs: list) -> list:
    cleaned = []
    for item in items:
        value, truncated = truncate_text(item, limit)
        if not value:
            logs.append(_log(f"{label}: {item}", "patch:rejected:empty"))
            continue
        if truncated:
            logs.append(_log(f"{label}: {item}", f"patch:truncated:{label}({limit})"))
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


def _clean_task_items(value, limit: int, label: str, logs: list) -> list:
    if isinstance(value, str):
        raw_items = [part for part in value.split(";") if part.strip()]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = [str(value)]
    cleaned = []
    for item in raw_items:
        text, truncated = truncate_text(item, limit)
        if not text:
            logs.append(_log(f"{label}: {item}", "patch:rejected:empty"))
            continue
        if truncated:
            logs.append(_log(f"{label}: {item}", f"patch:truncated:{label}({limit})"))
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def normalize_patch(patch: dict, core: dict, tasks: list) -> tuple[dict, list]:
    logs: list = []
    clean: dict = {}

    core_patch = dict(patch.get("core") or {})
    cleaned_core: dict = {}

    user_patch = dict(core_patch.get("user") or {})
    if "style" in user_patch:
        logs.append(
            _log(f"user.style: {user_patch.pop('style')}", "patch:rejected:style_is_meta")
        )
    for key in ("name", "role"):
        if user_patch.get(key):
            value, truncated = truncate_text(user_patch[key], MAX_PREFERENCE)
            if truncated:
                logs.append(_log(f"user.{key}: {user_patch[key]}", f"patch:truncated:user.{key}({MAX_PREFERENCE})"))
            user_patch[key] = value
    if user_patch:
        cleaned_core["user"] = user_patch

    preferences = dict(core_patch.get("preferences") or {})
    cleaned_preferences: dict = {}
    for key in ("likes", "dislikes"):
        items = preferences.get(key) or []
        cleaned = _clean_list(items, MAX_PREFERENCE, key, logs)
        if cleaned:
            cleaned_preferences[key] = cleaned
    if cleaned_preferences:
        cleaned_core["preferences"] = cleaned_preferences

    goals = core_patch.get("goals") or []
    cleaned_goals = _clean_list(goals, MAX_GOAL, "goals", logs)
    if cleaned_goals:
        cleaned_core["goals"] = cleaned_goals

    for unknown_key in core_patch:
        if unknown_key not in ("user", "preferences", "goals"):
            logs.append(
                _log(
                    f"core.{unknown_key}: {json.dumps(core_patch[unknown_key], ensure_ascii=False)}",
                    "patch:rejected:unknown_key",
                )
            )

    clean["core"] = cleaned_core

    cleaned_tasks = []
    for entry in patch.get("tasks") or []:
        topic = str(entry.get("topic") or "").strip()
        if not topic:
            logs.append(_log(json.dumps(entry, ensure_ascii=False), "patch:rejected:no_topic"))
            continue
        topic, truncated = truncate_text(topic, MAX_TOPIC)
        if truncated:
            logs.append(_log(f"topic: {entry['topic']}", f"patch:truncated:topic({MAX_TOPIC})"))
        cleaned_entry = {"topic": topic, "status": entry.get("status")}
        for field in ("resolved", "open"):
            value = entry.get(field)
            if value:
                cleaned_entry[field] = _clean_task_items(value, MAX_TASK_FIELD, field, logs)
        cleaned_tasks.append(cleaned_entry)
    clean["tasks"] = cleaned_tasks

    clean["uncertain"] = patch.get("uncertain") or []
    clean["used"] = patch.get("used")
    clean["notes"] = patch.get("notes")
    return clean, logs


def enforce_task_caps(tasks: list) -> tuple[list, list]:
    logs: list = []

    def cap_group(group: list, cap: int, label: str) -> list:
        if len(group) <= cap:
            return group
        ordered = sorted(
            group, key=lambda t: t.get("updated_at") or "", reverse=True
        )
        kept = ordered[:cap]
        for entry in ordered[cap:]:
            logs.append(
                _log(entry.get("topic") or "", f"patch:rejected:task_cap:{label}")
            )
        return kept

    open_tasks = [t for t in tasks if t.get("status") != "done"]
    closed_tasks = [t for t in tasks if t.get("status") == "done"]
    return cap_group(open_tasks, MAX_OPEN_TASKS, "open") + cap_group(
        closed_tasks, MAX_CLOSED_TASKS, "closed"
    ), logs
