from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from normalize import enforce_task_caps, normalize_patch, topic_key, topics_similar


COMPRESSION_PROMPT = """You are the memory compressor of a conversational AI.
You get: CORE (durable user model), TASKS (open and closed topics) and MESSAGES to compress.
Extract only durable meaning: facts about the user, preference changes, decisions,
new or changed goals, open questions. Do not retell the dialogue; write meeting notes.
Never include anything marked private.
If new information contradicts what CORE or TASKS already contain, the newer fact
wins; make the change explicit, e.g. "Rust (switched from Python)".
When a CORE item is no longer true (the user changed their mind or it was
superseded), list its exact current text in "forget" so it is removed, and put the
replacement into the normal fields. Use "forget" only with text that literally
appears in CORE.

Strict categorization:
- Decisions (technology or approach choices) go ONLY into tasks[].resolved.
- Open items go ONLY into tasks[].open.
- A topic may be marked done ONLY when its open list is empty. Never move an
  unfinished item into resolved just to close a topic.
- User preferences (what the user likes or dislikes) go ONLY into preferences.likes/dislikes.
- Never set user.style: communication style is meta, not a durable fact.
- Never store small talk or incidental trivia. Examples of what NOT to store:
  a pet, a TV series, food or drinks, a keyboard or gadget purchase, childhood hobbies.
- Topics: keep one topic per workstream (e.g. storage, schema, deployment, auth).
  Reuse an existing topic name only when the item belongs to that same workstream;
  never merge unrelated decisions into one topic. Never create a synonym or a
  translation of an existing topic.

Hard limits: each goal/like/dislike <= 100 chars; each topic <= 60 chars;
each element of resolved/open <= 120 chars. At most 10 open and 10 closed tasks.

Return STRICT JSON only, no markdown fences:
{
  "core": {"user": {"name": "...", "role": "..."}, "preferences": {"likes": [...], "dislikes": [...]}, "goals": [...]},
  "tasks": [{"topic": "...", "status": "open|in-progress|done", "resolved": ["..."], "open": ["..."]}],
  "forget": {"likes": ["..."], "dislikes": ["..."], "goals": ["..."]},
  "uncertain": [{"kind": "goal|like|dislike|task", "text": "..."}],
  "used": [1, 2],
  "notes": "2-3 lines: what was learned, what changed in the user model"
}
- "uncertain": facts that look important but you are not sure about (tentative,
  ambiguous, second-hand). They go to a pending queue for the user to confirm;
  never duplicate them in core/tasks.
- "used": numbers of MESSAGES (1-based) you extracted any fact or topic from.
  Messages not listed may be dropped from the dialogue window.
- "forget": exact CORE texts that are no longer true. Example: the user switched
  from Python to Rust -> "forget": {"likes": ["Python"]} together with
  "core": {"preferences": {"likes": ["Rust (switched from Python)"]}}.
Omit keys that have no updates. Mark a topic as done when it is fully closed."""

LOSS_MIN_CHARS = 15
STOPWORDS = {
    "это", "если", "что", "как", "для", "или", "его", "её", "еще", "ещё",
    "при", "над", "под", "про", "без", "всё", "все", "мне", "меня", "тоже",
    "очень", "когда", "тогда", "чтобы", "там", "так", "они", "она", "оно",
    "the", "and", "for", "with", "that", "this", "not", "you", "your",
    "are", "was", "were", "have", "has", "will", "from",
}


SESSION_NOTE = """Session context: you are compressing the memory of ONE session (workstream).
TASKS may include tasks that belong to OTHER sessions. Never modify, rename, translate
or merge into tasks of other sessions — they are read-only context for you.
New and updated tasks belong to the current session: "{label}"."""


def build_compression_prompt(
    core: dict, tasks: list, messages: list, session_label: str | None = None
) -> str:
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    prefix = COMPRESSION_PROMPT
    if session_label:
        prefix += "\n\n" + SESSION_NOTE.format(label=session_label)
    return (
        prefix
        + "\n\nCORE:\n"
        + json.dumps(core, ensure_ascii=False, indent=2)
        + "\n\nTASKS:\n"
        + json.dumps(tasks, ensure_ascii=False, indent=2)
        + "\n\nMESSAGES:\n"
        + transcript
    )


def deep_merge(base: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if value is None:
            continue
        if isinstance(value, dict):
            target = base.get(key)
            if not isinstance(target, dict):
                target = {}
                base[key] = target
            deep_merge(target, value)
        elif isinstance(value, list):
            if not value:
                continue
            current = base.get(key)
            if not isinstance(current, list):
                current = []
                base[key] = current
            for item in value:
                if item not in current:
                    current.append(item)
        else:
            base[key] = value
    return base


def apply_core_updates(core: dict, patch: dict) -> dict:
    clean_patch = {
        key: value for key, value in patch.items() if key not in ("meta", "forget")
    }
    return deep_merge(core, clean_patch)


def apply_forget(core: dict, forget: dict) -> list:
    """Remove explicitly outdated items from CORE ("the newer fact wins").

    Accepts the normalized ``forget`` section; returns the removed (key, text)
    pairs so the caller can write them into the loss log - the texts stay
    findable in the full history index.
    """
    removed: list = []
    if not isinstance(forget, dict):
        return removed
    preferences = core.get("preferences")
    for key in ("likes", "dislikes"):
        stale = forget.get(key) or []
        if not stale or not isinstance(preferences, dict):
            continue
        bucket = preferences.get(key)
        if not isinstance(bucket, list):
            continue
        for item in stale:
            if item in bucket:
                bucket.remove(item)
                removed.append((key, item))
    stale_goals = forget.get("goals") or []
    goals = core.get("goals")
    if stale_goals and isinstance(goals, list):
        for item in stale_goals:
            if item in goals:
                goals.remove(item)
                removed.append(("goals", item))
    return removed


def _belongs_to_session(entry: dict, session_id: str | None) -> bool:
    if session_id is None:
        return True
    return entry.get("session_id") == session_id


def apply_task_updates(
    tasks: list,
    updates: list,
    session_id: str | None = None,
    session_label: str | None = None,
) -> list:
    index = {
        topic_key(entry["topic"]): entry
        for entry in tasks
        if _belongs_to_session(entry, session_id)
    }
    for update in updates:
        topic = (update.get("topic") or "").strip()
        if not topic:
            continue
        key = topic_key(topic)
        entry = index.get(key)
        if entry is None:
            for existing_key, existing_entry in index.items():
                if topics_similar(key, existing_key):
                    entry = existing_entry
                    break
        if entry is None:
            entry = {"topic": topic, "status": "open", "resolved": None, "open": None}
            if session_id is not None:
                entry["session_id"] = session_id
                if session_label:
                    entry["session_label"] = session_label
            tasks.append(entry)
            index[key] = entry
        if update.get("status"):
            entry["status"] = update["status"]
        for field in ("resolved", "open"):
            value = update.get(field)
            if not value:
                continue
            incoming = value if isinstance(value, list) else [value]
            current = entry.get(field)
            if not isinstance(current, list):
                current = [current] if current else []
            for item in incoming:
                if item not in current:
                    current.append(item)
            entry[field] = current
        entry["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return tasks


def prepare_compression(
    store,
    session_id: str | None = None,
    session_label: str | None = None,
    keep_recent: int | None = None,
) -> dict | None:
    """Snapshot one compression pass: the messages to compress + the LLM prompt.

    Split out of :func:`run_compression` so an external LLM (e.g. the host's own
    ``ctx.llm`` in the Hermes plugin) can run the call itself. ``prompt`` is None
    when only private messages are involved; the whole call returns None when
    there is nothing to compress at all.
    """
    recent = store.read_recent(session_id)
    if keep_recent is None:
        keep_recent = max(1, store.recent_limit // 2)
    if keep_recent:
        if len(recent) <= keep_recent:
            return None
        to_compress = recent[:-keep_recent]
    else:
        if not recent:
            return None
        to_compress = list(recent)
    public_messages = [m for m in to_compress if not m.get("private")]
    core = store.read_core()
    tasks = store.read_tasks()
    prompt = (
        build_compression_prompt(core, tasks, public_messages, session_label)
        if public_messages
        else None
    )
    return {
        "core": core,
        "tasks": tasks,
        "all": to_compress,
        "messages": public_messages,
        "prompt": prompt,
        "session_id": session_id,
        "session_label": session_label,
    }


def run_compression(
    store,
    provider,
    keep_recent: int | None = None,
    session_id: str | None = None,
    session_label: str | None = None,
):
    prep = prepare_compression(
        store, session_id=session_id, session_label=session_label, keep_recent=keep_recent
    )
    if prep is None:
        return None
    if prep["prompt"] is not None:
        result = provider.summarize(
            prep["core"], prep["tasks"], prep["messages"], session_label
        )
    else:
        result = None
    return apply_compression_result(store, prep, result)


def apply_compression_result(store, prep: dict, result: dict | None):
    """Apply the LLM's patch from a :func:`prepare_compression` snapshot.

    Re-reads current state under the lock and removes only the snapshotted ids -
    messages that arrived while the LLM was working are kept. ``result=None``
    means "only private messages": nothing to apply, the pass only touches meta.
    """
    to_compress = prep["all"]
    public_messages = prep["messages"]
    session_id = prep.get("session_id")
    session_label = prep.get("session_label")
    if result is None:
        result = {"core": {}, "tasks": [], "notes": "нечего сжимать (только приватное)"}

    with store.locked():
        current = store.read_recent(session_id)
        compressed_ids = {m["id"] for m in to_compress}
        remaining = [m for m in current if m.get("id") not in compressed_ids]
        remaining = remaining[-store.recent_limit :]

        core = store.read_core()
        tasks = store.read_tasks()
        clean_result, patch_logs = normalize_patch(result, core, tasks)
        for entry in patch_logs:
            store.log_loss(
                role="patch", text=entry["text"], reason=entry["reason"], indexed=False
            )
        removed = apply_forget(core, clean_result.get("forget") or {})
        for key, text in removed:
            store.log_loss(
                role="patch", text=text, reason=f"forgotten:core.{key}", indexed=True
            )
        core = apply_core_updates(core, clean_result.get("core") or {})
        tasks = apply_task_updates(
            tasks,
            clean_result.get("tasks") or [],
            session_id=session_id,
            session_label=session_label,
        )
        tasks, cap_logs = enforce_task_caps(tasks)
        for entry in cap_logs:
            store.log_loss(
                role="patch", text=entry["text"], reason=entry["reason"], indexed=False
            )
        uncertain_items = clean_result.get("uncertain") or []
        if uncertain_items:
            for duplicate in _uncertain_duplicates(uncertain_items, core, tasks):
                store.log_loss(
                    role="patch",
                    text=duplicate.get("text") or "",
                    reason="patch:uncertain:duplicate_of_core",
                    indexed=False,
                )
            store.append_pending(uncertain_items)
        _record_losses(store, public_messages, result, core, tasks)
        core.setdefault("meta", {})
        core["meta"]["compressions"] = core["meta"].get("compressions", 0) + 1
        core["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        store.write_core(core)
        store.write_tasks(tasks)
        store.write_recent(remaining, session_id)
    return result


def flush(store, provider, session_id: str | None = None, session_label: str | None = None):
    return run_compression(
        store,
        provider,
        keep_recent=0,
        session_id=session_id,
        session_label=session_label,
    )


def maybe_compress(store, provider, session_id: str | None = None, session_label: str | None = None):
    if len(store.read_recent(session_id)) >= store.recent_limit:
        return run_compression(
            store,
            provider,
            session_id=session_id,
            session_label=session_label,
        )
    return None


def _record_losses(store, public_messages: list, result: dict, core: dict, tasks: list) -> None:
    used = result.get("used")
    used_positions = None
    if isinstance(used, list):
        used_positions = set()
        for value in used:
            if isinstance(value, (int, float)) and 1 <= int(value) <= len(public_messages):
                used_positions.add(int(value))
    summary_blob = (
        json.dumps(core, ensure_ascii=False) + " " + json.dumps(tasks, ensure_ascii=False)
    ).lower()
    for position, message in enumerate(public_messages, start=1):
        if message.get("role") != "user":
            continue
        text = message.get("content") or ""
        if len(text) < LOSS_MIN_CHARS:
            continue
        if used_positions is not None:
            kept = position in used_positions
        else:
            kept = _lexically_used(text, summary_blob)
        if not kept:
            store.log_loss(
                role="user",
                text=text,
                reason="not_used_by_compression",
                indexed=True,
            )


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _uncertain_duplicates(uncertain_items: list, core: dict, tasks: list) -> list:
    """Uncertain facts the model ALSO wrote into core/tasks despite the prompt.

    Detected and logged (silent cleanup would need semantics we do not have);
    the item still goes to the confirmation queue.
    """
    blob = _normalize_for_match(
        json.dumps(core, ensure_ascii=False) + " " + json.dumps(tasks, ensure_ascii=False)
    )
    duplicates = []
    for item in uncertain_items:
        norm = _normalize_for_match((item or {}).get("text") or "")
        if norm and norm in blob:
            duplicates.append(item)
    return duplicates


def _lexically_used(text: str, summary_blob: str) -> bool:
    tokens = {
        token
        for token in re.findall(r"[а-яёa-z]{4,}", text.lower())
        if token not in STOPWORDS
    }
    if not tokens:
        return False
    return any(token in summary_blob for token in tokens)
