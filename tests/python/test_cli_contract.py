"""CLI contract tests: tolerant batch parsing, empty input, damaged tails, ids."""

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


def test_batch_skips_malformed_lines_instead_of_losing_the_batch(tmp_path: Path) -> None:
    data_dir = tmp_path / "store"
    stdin = (
        '{"role": "user", "content": "первое"}\n'
        "не json вовсе\n"
        '{"role": "user", "content": "второе"}\n'
        "[1, 2]\n"
    )
    proc = _run(data_dir, ["append", "--batch"], stdin)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _payload(proc)
    assert payload["ok"] is True
    assert payload["appended"] == 2
    assert payload["skipped"] == 2
    status = _payload(_run(data_dir, ["status"]))
    assert status["recent"] == 2


def test_empty_single_append_is_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "store"
    proc = _run(data_dir, ["append", "--role", "user", "--stdin"], "")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = _payload(proc)
    assert payload["ok"] is False
    assert "empty" in payload["error"]
    status = _payload(_run(data_dir, ["status"]))
    assert status["recent"] == 0


def test_damaged_recent_line_does_not_kill_status_and_context(tmp_path: Path) -> None:
    data_dir = tmp_path / "store"
    assert _run(data_dir, ["append", "--role", "user", "--stdin"], "живое сообщение").returncode == 0
    recent = data_dir / "memory" / "recent.jsonl"
    with recent.open("a", encoding="utf-8") as fh:
        fh.write("{сломано\n")
    status = _run(data_dir, ["status"])
    assert status.returncode == 0, status.stdout + status.stderr
    assert _payload(status)["recent"] == 1
    assert "skipping malformed" in status.stderr
    context = _run(data_dir, ["context"])
    assert context.returncode == 0
    assert "живое сообщение" in _payload(context)["prompt"]


def test_session_file_names_do_not_collide(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "python"))
    from store import _safe_session_name

    assert _safe_session_name("ses_ab12cd") == "ses_ab12cd"
    assert _safe_session_name("a b") != _safe_session_name("a/b")


def test_create_if_missing_never_truncates(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "python"))
    from store import MemoryStore

    existing = tmp_path / "existing.jsonl"
    existing.write_text("живое содержимое", encoding="utf-8")
    MemoryStore._create_if_missing(existing, "новое содержимое")
    assert existing.read_text(encoding="utf-8") == "живое содержимое"

    fresh = tmp_path / "fresh.jsonl"
    MemoryStore._create_if_missing(fresh, "текст")
    assert fresh.read_text(encoding="utf-8") == "текст"

