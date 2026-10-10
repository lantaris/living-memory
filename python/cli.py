#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compress import flush as flush_memory, maybe_compress, run_compression
from inject import build_system_prompt
from llm import MockProvider, OpencodeCLIProvider
from store import MemoryStore

MIN_PYTHON = (3, 10)


def build_provider(name: str):
    if name == "mock":
        return MockProvider()
    return OpencodeCLIProvider()


def read_stdin_text() -> str:
    try:
        sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass
    return sys.stdin.read()


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        print(json.dumps({"ok": False, "error": "Python 3.10+ is required"}))
        return 1

    parser = argparse.ArgumentParser(prog="living-memory")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--provider", default="opencode", choices=("opencode", "mock"))
    parser.add_argument("--recent-limit", type=int, default=10)
    parser.add_argument("--session", default=None)
    parser.add_argument("--session-label", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p_append = sub.add_parser("append")
    p_append.add_argument("--role", choices=("user", "assistant"))
    p_append.add_argument("--content")
    p_append.add_argument("--stdin", action="store_true", help="read the message text from stdin (UTF-8)")
    p_append.add_argument(
        "--batch",
        action="store_true",
        help="read JSONL {role, content, private?} records from stdin and append in one pass",
    )
    p_append.add_argument("--private", action="store_true")

    p_compact = sub.add_parser("compact")
    p_compact.add_argument("--if-full", action="store_true")

    sub.add_parser("flush")
    sub.add_parser("context")
    sub.add_parser("status")

    p_search = sub.add_parser("search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=5)

    args = parser.parse_args()
    store = MemoryStore(args.data_dir, recent_limit=args.recent_limit)
    session_id = args.session
    session_label = args.session_label
    exit_code = 0

    if args.command == "status":
        payload = {
            "ok": True,
            "python": sys.version.split()[0],
            "data_dir": str(Path(args.data_dir).resolve()),
            "recent": len(store.read_recent(session_id)),
            "provider": args.provider,
            "session": session_id,
        }
    elif args.command == "append":
        if args.batch:
            items = []
            for line in read_stdin_text().splitlines():
                line = line.strip()
                if line:
                    items.append(json.loads(line))
            appended = store.append_messages(items, session_id=session_id, session_label=session_label)
            payload = {"ok": True, "appended": appended, "recent": len(store.read_recent(session_id))}
        elif args.role in ("user", "assistant") and (args.stdin or args.content is not None):
            content = read_stdin_text() if args.stdin else args.content
            store.append_message(
                args.role,
                content,
                private=args.private,
                session_id=session_id,
                session_label=session_label,
            )
            payload = {"ok": True, "recent": len(store.read_recent(session_id))}
        else:
            payload = {"ok": False, "error": "append requires --role and one of --content / --stdin / --batch"}
            exit_code = 1
    elif args.command == "context":
        payload = {
            "ok": True,
            "prompt": build_system_prompt(store, session_id, session_label),
            "recent": len(store.read_recent(session_id)),
        }
    elif args.command == "compact":
        provider = build_provider(args.provider)
        if args.if_full:
            result = maybe_compress(store, provider, session_id=session_id, session_label=session_label)
        else:
            result = run_compression(store, provider, session_id=session_id, session_label=session_label)
        payload = {
            "ok": True,
            "compressed": result is not None,
            "notes": (result or {}).get("notes"),
        }
    elif args.command == "flush":
        provider = build_provider(args.provider)
        result = flush_memory(store, provider, session_id=session_id, session_label=session_label)
        payload = {
            "ok": True,
            "flushed": len(store.read_recent(session_id)) == 0,
            "notes": (result or {}).get("notes"),
        }
    elif args.command == "search":
        results = [
            {
                "text": hit["content"],
                "role": hit["role"],
                "ts": hit["ts"],
                "indexed": True,
                "session_id": hit.get("session_id"),
                "session_label": hit.get("session_label"),
            }
            for hit in store.search(args.query, limit=args.limit)
        ]
        payload = {"ok": True, "results": results}
    else:
        payload = {"ok": False, "error": f"unknown command: {args.command}"}
        exit_code = 1

    print(json.dumps(payload, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        sys.exit(1)
