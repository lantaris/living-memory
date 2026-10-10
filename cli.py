"""``hermes living-memory ...`` commands built on the bundled engine CLI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_ENGINE_CLI = Path(__file__).resolve().parent / "python" / "cli.py"


def _load_plugin_config() -> dict:
    try:
        from hermes_cli.config import cfg_get, load_config_readonly  # type: ignore

        return cfg_get(load_config_readonly(), "plugins", "living-memory", default={}) or {}
    except Exception:
        return {}


def _find_project_root(start: Path) -> Path:
    current = start
    for _ in range(30):
        if (current / ".git").exists() or (current / ".living-memory").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return start


def _data_dir() -> Path:
    """Same resolution as the provider: explicit option, else project root from cwd."""
    explicit = str((_load_plugin_config() or {}).get("data_dir") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return _find_project_root(Path.cwd()) / ".living-memory"


def _engine(args: list, stdin: str | None = None) -> dict | None:
    cmd = [sys.executable, str(_ENGINE_CLI), "--data-dir", str(_data_dir()), *args]
    proc = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def register_cli(subparser: argparse.ArgumentParser) -> None:
    """Build the ``hermes living-memory`` argparse tree (called at plugin load)."""
    subs = subparser.add_subparsers(dest="living_memory_command")
    subs.add_parser("status", help="store status (recent tail, pending queue)")
    p_search = subs.add_parser("search", help="search the full history")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=5)
    p_pending = subs.add_parser("pending", help="confirmation queue")
    p_pending.add_argument("action", choices=("list", "approve", "reject", "add"))
    p_pending.add_argument("--id", type=int)
    p_pending.add_argument("--text")
    p_pending.add_argument("--kind", default="fact")
    subparser.set_defaults(func=_handle)


def _handle(args) -> int:
    command = getattr(args, "living_memory_command", None)
    if command == "status":
        payload = _engine(["status"])
    elif command == "search":
        payload = _engine(["search", "--query", args.query, "--limit", str(args.limit)])
    elif command == "pending":
        extra: list = []
        if args.id is not None:
            extra += ["--id", str(args.id)]
        if args.text:
            extra += ["--text", args.text, "--kind", args.kind]
        payload = _engine(["pending", args.action, *extra])
    else:
        payload = None
    if payload is None:
        print("living-memory: engine unavailable", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
