"""End-to-end: append -> compact(mock) -> pending list -> approve -> context."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "python" / "cli.py"


def _run(data_dir: Path, args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(CLI), "--data-dir", str(data_dir), *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )


def _payload(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_pending_cycle_end_to_end(tmp_path: Path) -> None:
    data_dir = tmp_path / "store"
    assert _run(data_dir, ["append", "--role", "user", "--stdin"], "Привет, мне важна тёмная тема.").returncode == 0
    assert _run(data_dir, ["--provider", "mock", "compact"]).returncode == 0

    # The heuristic mock may or may not produce uncertain items; seed the queue
    # through the engine so the consumer (the M2 part) is what gets exercised.
    sys.path.insert(0, str(ROOT / "python"))
    from store import MemoryStore

    MemoryStore(str(data_dir)).append_pending([{"kind": "like", "text": "Тёмная тема в интерфейсах"}])

    listed = _payload(_run(data_dir, ["pending", "list"]))
    assert listed["count"] == 1
    record_id = listed["pending"][0]["id"]

    approved = _payload(_run(data_dir, ["pending", "approve", "--id", str(record_id)]))
    assert approved["ok"] is True
    assert approved["record"]["status"] == "approved"

    # resolving twice is a clean error, not a crash
    again = _run(data_dir, ["pending", "approve", "--id", str(record_id)])
    assert again.returncode == 1
    assert _payload(again)["ok"] is False

    context = _payload(_run(data_dir, ["context"]))
    assert "Тёмная тема в интерфейсах" in context["prompt"]

    status = _payload(_run(data_dir, ["status"]))
    assert status["pending"] == 0
