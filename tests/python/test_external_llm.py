"""External-LLM compaction: prepare/apply halves (what the Hermes adapter uses)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "python" / "cli.py"
sys.path.insert(0, str(ROOT / "python"))

from compress import apply_compression_result, prepare_compression  # noqa: E402
from store import MemoryStore  # noqa: E402


def _run(data_dir: Path, args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(CLI), "--data-dir", str(data_dir), *args],
        input=stdin, capture_output=True, text=True, encoding="utf-8", env=env, timeout=120,
    )


def _payload(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_prepare_apply_unit(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path / "store"), recent_limit=5)
    for index in range(6):
        store.append_message("user", f"сообщение {index} про хранилище SQLite")
    prep = prepare_compression(store)
    assert prep is not None and prep["prompt"]
    fake = {
        "core": {"preferences": {"likes": ["SQLite"]}},
        "tasks": [],
        "used": list(range(1, len(prep["messages"]) + 1)),
    }
    applied = apply_compression_result(store, prep, fake)
    assert applied is fake
    assert store.read_core()["preferences"]["likes"] == ["SQLite"]
    assert len(store.read_recent()) == 2  # keep_recent = 5 // 2


def test_prepare_none_when_nothing_to_compress(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path / "store"), recent_limit=10)
    store.append_message("user", "одно сообщение")
    assert prepare_compression(store) is None


def test_cli_external_compact_roundtrip(tmp_path: Path) -> None:
    data_dir = tmp_path / "store"
    batch = "".join(
        json.dumps({"role": "user", "content": f"шаг {i}: решили взять SQLite для хранения"}) + "\n"
        for i in range(10)
    )
    assert _payload(_run(data_dir, ["append", "--batch"], batch))["appended"] == 10
    prepared = _payload(_run(data_dir, ["compact-prepare"]))
    assert prepared["ok"] is True and prepared["prepared"] is True
    assert "CORE:" in prepared["prompt"]
    result = {
        "core": {"preferences": {"likes": ["SQLite"]}},
        "tasks": [{"topic": "storage", "status": "in-progress", "resolved": ["взять SQLite"], "open": []}],
        "used": list(range(1, len(prepared["messages"]) + 1)),
    }
    applied = _payload(_run(data_dir, ["compact-apply"], json.dumps({"messages": prepared["messages"], "result": result})))
    assert applied["ok"] is True
    context = _payload(_run(data_dir, ["context"]))
    assert "SQLite" in context["prompt"]
    core_only = _payload(_run(data_dir, ["context", "--no-tail"]))
    assert "# RECENT MESSAGES" not in core_only["prompt"]
    assert _payload(_run(data_dir, ["status"]))["recent"] == 5  # keep_recent = 10 // 2


def test_pending_add_cli(tmp_path: Path) -> None:
    data_dir = tmp_path / "store"
    added = _payload(_run(data_dir, ["pending", "add", "--kind", "like", "--text", "тёмная тема"]))
    assert added["ok"] is True and added["record"]["text"] == "тёмная тема"
    listed = _payload(_run(data_dir, ["pending", "list"]))
    assert listed["count"] == 1
