from __future__ import annotations

import json
import sqlite3


def _same_session(task: dict, session_id: str | None) -> bool:
    stored = task.get("session_id")
    if session_id in (None, "default"):
        return stored in (None, "default")
    return stored == session_id


def _session_label_for(task: dict) -> str:
    label = task.get("session_label") or task.get("session_id")
    if not label:
        return "shared"
    text = str(label).strip()
    return text[:48] if len(text) > 48 else text


def build_system_prompt(store, session_id: str | None = None, session_label: str | None = None) -> str:
    core = store.read_core()
    tasks = store.read_tasks()
    recent = store.read_recent(session_id)

    if session_id is None:
        open_tasks = [t for t in tasks if t.get("status") != "done"]
        closed_tasks = [t for t in tasks if t.get("status") == "done"]
        parts = [
            "You are a conversational assistant with layered memory. "
            "CORE holds stable facts about the user, OPEN TASKS holds active topics, "
            "CLOSED TOPICS holds decisions already made, "
            "RECENT MESSAGES is the live dialogue tail. These sections are your only memory."
        ]
        parts.append("# CORE MEMORY\n" + json.dumps(core, ensure_ascii=False, indent=2))
        parts.append("# OPEN TASKS\n" + json.dumps(open_tasks, ensure_ascii=False, indent=2))
        if closed_tasks:
            lines = [
                f"- {t['topic']}: {t.get('resolved') or 'закрыто'}" for t in closed_tasks
            ]
            parts.append("# CLOSED TOPICS (decisions already made)\n" + "\n".join(lines))
    else:
        label = session_label or session_id
        my_open = [
            t for t in tasks if _same_session(t, session_id) and t.get("status") != "done"
        ]
        my_closed = [
            t for t in tasks if _same_session(t, session_id) and t.get("status") == "done"
        ]
        other_tasks = [t for t in tasks if not _same_session(t, session_id)]
        parts = [
            "You are a conversational assistant with layered memory. Your memory is split "
            "by session: this session has its own tasks and live dialogue tail, other "
            "sessions are visible in summary for shared context. Never modify other "
            "sessions' tasks."
        ]
        parts.append("# CORE MEMORY (shared)\n" + json.dumps(core, ensure_ascii=False, indent=2))
        parts.append(
            f"# MY TASKS (session: {label})\n"
            + json.dumps(my_open, ensure_ascii=False, indent=2)
        )
        if my_closed:
            lines = [
                f"- {t['topic']}: {t.get('resolved') or 'закрыто'}" for t in my_closed
            ]
            parts.append("# CLOSED TOPICS (this session)\n" + "\n".join(lines))
        if other_tasks:
            lines = [
                f"- [{_session_label_for(t)}] {t.get('topic')} — {t.get('status')}"
                for t in other_tasks
            ]
            parts.append(
                "# OTHER SESSIONS (read-only context, do not modify)\n" + "\n".join(lines)
            )

    if recent:
        tail = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
    else:
        tail = "(no recent messages)"
    suffix = " (this session)" if session_id is not None else ""
    parts.append(f"# RECENT MESSAGES{suffix}\n" + tail)
    return "\n\n".join(parts)


def full_history_text(store) -> str:
    with sqlite3.connect(store.db_path) as con:
        rows = con.execute(
            "SELECT role, content FROM history WHERE private = 0 ORDER BY id"
        ).fetchall()
    return "\n".join(f"{role}: {content}" for role, content in rows)
