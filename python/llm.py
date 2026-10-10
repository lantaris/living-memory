from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def summarize(self, core: dict, tasks: list, messages: list, session_label: str | None = None) -> dict:
        raise NotImplementedError


_TOPIC_RE = re.compile(r"Тема\s*[:\-—]\s*([^.!?\n]+)", re.IGNORECASE)
_NAME_RE = re.compile(
    r"(?:меня зовут|моё имя|мое имя)\s*[—:-]?\s*([A-ZА-ЯЁ][\w\-]+)", re.IGNORECASE
)
_ROLE_RE = re.compile(
    r"я\s+([а-яё-]*(?:разработчик|инженер|дизайнер|менеджер|аналитик))", re.IGNORECASE
)
_DISLIKE_RE = re.compile(
    r"(?:не\s+люблю|ненавижу|не\s+переношу|не\s+нравится)\s+(.+?)(?=\s+и\s+|,\s+|$)",
    re.IGNORECASE,
)
_LIKE_RE = re.compile(
    r"(?:люблю|обожаю|предпочитаю|нравится)\s+(.+?)(?=\s+и\s+|,\s+|$)", re.IGNORECASE
)
_SWITCH_RE = re.compile(
    r"(?:перешёл|перешел|перехожу|переехал|переключился|больше\s+не\s+использую)"
    r"\s+(?:на\s+)?([A-ZА-ЯЁ][\w#+.-]*)",
    re.IGNORECASE,
)
_GOAL_RE = re.compile(r"(?:моя цель|цель)\s*[:\-—]\s*(.+)", re.IGNORECASE)
_RESOLVED_RE = re.compile(
    r"(?:решили|договорились|постановили)\s*[:\-—]?\s*(.+)", re.IGNORECASE
)
_OPEN_RE = re.compile(
    r"(?:осталось|остаётся|остается|надо ещё|нужно ещё|следующий шаг)"
    r"\s*[:\-—]?\s*(.+)",
    re.IGNORECASE,
)
_STYLE_RE = re.compile(r"(?:отвечай|пиши|говори)\s+(.+)", re.IGNORECASE)
_UNCERTAIN_RE = re.compile(
    r"(?:возможно|наверное|может быть|может,|скорее всего|стоит ли|"
    r"не уверен[аы]?|пока не ясно|под вопросом)\s*[,:]?\s*(.+)",
    re.IGNORECASE,
)
_UNCERTAIN_CLEANUP_RE = re.compile(
    r"\s*[—–-]\s*(?:пока\s+)?не\s+уверен\w*\s*$", re.IGNORECASE
)
_GOAL_VERB_RE = re.compile(
    r"(?:добав|сдела|выпуст|выпущ|попробу|перейд|внедр|хочу|план|цель)", re.IGNORECASE
)


def _split_clauses(content: str) -> list:
    return [c.strip() for c in re.split(r"[.!?;]\s+|\n+", content) if c.strip()]


def _clean_uncertain(text: str) -> str:
    text = text.strip(" .,;:—-")
    text = _UNCERTAIN_CLEANUP_RE.sub("", text)
    return text.strip(" .,;:—-")


def _uncertain_kind(text: str) -> str:
    if _GOAL_VERB_RE.search(text):
        return "goal"
    if re.search(r"(?:не\s+нравится|не\s+люблю|ненавижу)", text, re.IGNORECASE):
        return "dislike"
    if re.search(r"(?:люблю|нравится|предпочитаю)", text, re.IGNORECASE):
        return "like"
    return "task"


class MockProvider(LLMProvider):
    def summarize(self, core: dict, tasks: list, messages: list, session_label: str | None = None) -> dict:
        patch = {"user": {}, "preferences": {"likes": [], "dislikes": []}, "goals": []}
        topics: list = []
        index: dict = {}
        used: list = []
        uncertain: list = []
        current = {"entry": None}

        def ensure_topic(name: str) -> dict:
            name = name.strip().rstrip(".,;:")
            key = name.lower()
            if key not in index:
                entry = {"topic": name, "status": "open", "resolved": None, "open": None}
                index[key] = entry
                topics.append(entry)
            current["entry"] = index[key]
            return index[key]

        def append_unique(bucket: list, value: str) -> None:
            value = value.strip(" .,;:—-")
            if value and value not in bucket:
                bucket.append(value)

        def merge_into(entry: dict, field: str, value: str) -> None:
            value = value.strip(" .,;:—-")
            if not value:
                return
            items = entry.get(field)
            if not isinstance(items, list):
                items = []
                entry[field] = items
            if value not in items:
                items.append(value)

        for position, message in enumerate(messages, start=1):
            if message.get("private"):
                continue
            content = message["content"]
            message_used = False
            topic_match = _TOPIC_RE.search(content)
            if topic_match:
                ensure_topic(topic_match.group(1))
                message_used = True
            clauses = _split_clauses(content)
            for clause in clauses:
                uncertainty = _UNCERTAIN_RE.search(clause)
                if uncertainty and message["role"] == "user":
                    text = _clean_uncertain(uncertainty.group(1))
                    if text:
                        uncertain.append({"kind": _uncertain_kind(text), "text": text})
                        message_used = True
                    continue
                if message["role"] == "user":
                    m = _NAME_RE.search(clause)
                    if m:
                        patch["user"]["name"] = m.group(1)
                        message_used = True
                    m = _ROLE_RE.search(clause)
                    if m:
                        patch["user"]["role"] = m.group(1)
                        message_used = True
                dislike_free = clause
                for m in _DISLIKE_RE.finditer(clause):
                    append_unique(patch["preferences"]["dislikes"], m.group(1))
                    message_used = True
                dislike_free = _DISLIKE_RE.sub(" ", clause)
                for m in _LIKE_RE.finditer(dislike_free):
                    append_unique(patch["preferences"]["likes"], m.group(1))
                    message_used = True
                m = _SWITCH_RE.search(clause)
                if m:
                    append_unique(patch["preferences"]["likes"], m.group(1))
                    message_used = True
                m = _GOAL_RE.search(clause)
                if m:
                    append_unique(patch["goals"], m.group(1))
                    message_used = True
                if message["role"] == "user":
                    m = _STYLE_RE.search(clause)
                    if m:
                        patch["user"]["style"] = m.group(1).strip(" .,;:—-")
                        message_used = True
                m = _RESOLVED_RE.search(clause)
                if m:
                    target = current["entry"] or ensure_topic("общее")
                    merge_into(target, "resolved", m.group(1))
                    target["status"] = "in-progress"
                    message_used = True
                m = _OPEN_RE.search(clause)
                if m:
                    target = current["entry"] or ensure_topic("общее")
                    merge_into(target, "open", m.group(1))
                    if target["status"] == "open":
                        target["status"] = "in-progress"
                    message_used = True
            if message_used:
                used.append(position)

        facts = []
        name = patch["user"].get("name")
        if name:
            facts.append(f"имя: {name}")
        role = patch["user"].get("role")
        if role:
            facts.append(f"роль: {role}")
        if patch["preferences"]["likes"]:
            facts.append("предпочтения: " + ", ".join(patch["preferences"]["likes"]))
        if patch["preferences"]["dislikes"]:
            facts.append("не любит: " + ", ".join(patch["preferences"]["dislikes"]))
        if patch["goals"]:
            facts.append("цели: " + ", ".join(patch["goals"]))
        if topics:
            facts.append("темы: " + ", ".join(t["topic"] for t in topics))
        if uncertain:
            facts.append("неуверенное: " + ", ".join(u["text"] for u in uncertain))
        notes = f"Сжато сообщений: {len(messages)}. Тем в конспекте: {len(topics)}."
        if facts:
            notes += " " + "; ".join(facts[:3]) + "."
        return {
            "core": patch,
            "tasks": topics,
            "uncertain": uncertain,
            "used": used,
            "notes": notes,
        }


class OpencodeCLIProvider(LLMProvider):
    def __init__(self, model: str | None = None, timeout: int = 600):
        self.model = model or os.environ.get("MEMORY_LLM_MODEL")
        self.timeout = timeout

    def summarize(self, core: dict, tasks: list, messages: list, session_label: str | None = None) -> dict:
        from compress import build_compression_prompt

        prompt = build_compression_prompt(core, tasks, messages, session_label)
        cmd = [shutil.which("opencode") or "opencode", "run"]
        if self.model:
            cmd += ["--model", self.model]
        cmd.append(prompt)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"opencode run failed: {proc.stderr.strip()}")
        return extract_json(proc.stdout)


def extract_json(text: str) -> dict:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in LLM output")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        for open_pos in range(start, end):
            if text[open_pos] != "{":
                continue
            for close_pos in range(end, open_pos, -1):
                if text[close_pos] != "}":
                    continue
                try:
                    return json.loads(text[open_pos : close_pos + 1])
                except json.JSONDecodeError:
                    continue
        raise


def get_default_provider() -> LLMProvider:
    if os.environ.get("MEMORY_LLM_PROVIDER", "mock").lower() == "opencode":
        return OpencodeCLIProvider()
    return MockProvider()
