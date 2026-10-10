"""M2 semantics: forget/replace, per-session caps, uncertain-duplicate detection."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from compress import apply_core_updates, apply_forget, run_compression  # noqa: E402
from normalize import enforce_task_caps, normalize_patch  # noqa: E402
from store import MemoryStore  # noqa: E402


def _core(likes=None, dislikes=None, goals=None):
    return {
        "user": {"name": None, "role": None, "style": None},
        "preferences": {"likes": likes or [], "dislikes": dislikes or []},
        "goals": goals or [],
        "meta": {"version": 1, "updated_at": None, "compressions": 0},
    }


def test_forget_removes_superseded_preference():
    core = _core(likes=["Python"], dislikes=["ORM"])
    patch = {
        "forget": {"likes": ["Python"]},
        "core": {"preferences": {"likes": ["Rust (switched from Python)"]}},
    }
    clean, logs = normalize_patch(patch, core, [])
    assert clean["forget"] == {"likes": ["Python"]}
    removed = apply_forget(core, clean["forget"])
    core = apply_core_updates(core, clean["core"])
    assert removed == [("likes", "Python")]
    assert core["preferences"]["likes"] == ["Rust (switched from Python)"]
    assert core["preferences"]["dislikes"] == ["ORM"]


class _ForgetProvider:
    def summarize(self, core, tasks, messages, session_label=None):
        return {
            "forget": {"likes": ["Python"]},
            "core": {"preferences": {"likes": ["Rust (switched from Python)"]}},
            "used": list(range(1, len(messages) + 1)),
        }


def test_compression_applies_forget_and_logs_it(tmp_path: Path):
    store = MemoryStore(str(tmp_path / "store"), recent_limit=5)
    core = store.read_core()
    core["preferences"]["likes"] = ["Python"]
    store.write_core(core)
    for index in range(6):
        store.append_message("user", f"шаг {index}: переходим на Rust, переписываем конспект")
    run_compression(store, _ForgetProvider())
    updated = store.read_core()
    assert "Python" not in updated["preferences"]["likes"]
    assert "Rust (switched from Python)" in updated["preferences"]["likes"]
    losses = [r for r in store.read_loss_log() if r["reason"] == "forgotten:core.likes"]
    assert [r["text"] for r in losses] == ["Python"]


def test_task_caps_are_per_session():
    def task(topic: str, session: str, updated: str) -> dict:
        return {"topic": topic, "status": "open", "updated_at": updated, "session_id": session}

    tasks = [task(f"a{i}", "alpha", f"2026-10-{i + 1:02d}T00:00:00+00:00") for i in range(12)]
    tasks += [task(f"b{i}", "beta", f"2026-10-{i + 1:02d}T00:00:00+00:00") for i in range(12)]
    kept, logs = enforce_task_caps(tasks)
    alpha = [t for t in kept if t["session_id"] == "alpha"]
    beta = [t for t in kept if t["session_id"] == "beta"]
    assert len(alpha) == 10 and len(beta) == 10
    assert {t["topic"] for t in alpha} == {f"a{i}" for i in range(2, 12)}
    assert {t["topic"] for t in beta} == {f"b{i}" for i in range(2, 12)}
    assert len(logs) == 4


class _DuplicateProvider:
    def summarize(self, core, tasks, messages, session_label=None):
        return {
            "core": {"preferences": {"likes": ["Python"]}},
            "uncertain": [{"kind": "like", "text": "Python"}],
            "used": list(range(1, len(messages) + 1)),
        }


def test_uncertain_duplicate_is_detected_and_logged(tmp_path: Path):
    store = MemoryStore(str(tmp_path / "store"), recent_limit=4)
    for index in range(5):
        store.append_message("user", f"сообщение {index} о предпочтениях в языках")
    run_compression(store, _DuplicateProvider())
    losses = [r for r in store.read_loss_log() if r["reason"] == "patch:uncertain:duplicate_of_core"]
    assert [r["text"] for r in losses] == ["Python"]
    pending = [r for r in store.read_pending() if r["status"] == "pending"]
    assert [r["text"] for r in pending] == ["Python"]
