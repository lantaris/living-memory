"""Engine-level checks that have no prototype equivalent: locking and transport.

Two CLI processes append concurrently into the same data dir; every message must
land in the history index exactly once (the SQLite-mutex guarantees single-writer
serialization). The second test pins the stdin/batch transport: no message text
travels through argv.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "python" / "cli.py"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    return env


def test_concurrent_batch_appends_do_not_lose_messages(tmp_path: Path) -> None:
    data_dir = tmp_path / "store"
    workers = 2
    per_worker = 20
    procs: list[subprocess.Popen[str]] = []
    for _ in range(workers):
        procs.append(
            subprocess.Popen(
                [sys.executable, str(CLI), "--data-dir", str(data_dir), "append", "--batch"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=_env(),
            )
        )
    for worker, proc in enumerate(procs):
        payload = "".join(
            json.dumps({"role": "user", "content": f"w{worker}-{i} сообщение конкурентного теста."}) + "\n"
            for i in range(per_worker)
        )
        assert proc.stdin is not None
        proc.stdin.write(payload)
        proc.stdin.close()
    for proc in procs:
        assert proc.stdout is not None and proc.stderr is not None
        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        assert proc.wait() == 0, stderr
        last_line = stdout.strip().splitlines()[-1]
        payload = json.loads(last_line)
        assert payload["ok"] is True
        assert payload["appended"] == per_worker

    con = sqlite3.connect(data_dir / "memory" / "index.db")
    try:
        count = con.execute("SELECT COUNT(*) FROM history WHERE role = 'user'").fetchone()[0]
    finally:
        con.close()
    assert count == workers * per_worker


def test_long_message_travels_via_stdin(tmp_path: Path) -> None:
    data_dir = tmp_path / "store"
    content = "Длинный текст: " + "слово " * 40_000  # ~240 KB, far beyond any argv limit
    proc = subprocess.run(
        [sys.executable, str(CLI), "--data-dir", str(data_dir), "append", "--role", "user", "--stdin"],
        input=content,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_env(),
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["recent"] == 1
