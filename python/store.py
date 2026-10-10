from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_CORE = {
    "user": {"name": None, "role": None, "style": None},
    "preferences": {"likes": [], "dislikes": []},
    "goals": [],
    "meta": {"version": 1, "updated_at": None, "compressions": 0},
}

DEFAULT_SESSION = "default"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_session_name(session_id: str) -> str:
    """Map a session id to a safe file name; collision-resistant.

    Ids that are already safe stay as they are (existing files keep working);
    anything the sanitizer rewrites or truncates gets a short hash of the
    original id, so "a b" and "a/b" can no longer share one tail file.
    """
    text = str(session_id)
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    if cleaned and cleaned == text and len(text) <= 96:
        return text
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    base = cleaned[:72].strip("._-") or "session"
    return f"{base}-{digest}"


class MemoryStore:
    def __init__(self, base_dir, recent_limit: int = 10):
        self.base_dir = Path(base_dir)
        self.memory_dir = self.base_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.core_path = self.memory_dir / "core.json"
        self.tasks_path = self.memory_dir / "tasks.json"
        self.recent_path = self.memory_dir / "recent.jsonl"
        self.recent_dir = self.memory_dir / "recent"
        self.loss_log_path = self.memory_dir / "loss_log.jsonl"
        self.pending_path = self.memory_dir / "pending.jsonl"
        self.db_path = self.memory_dir / "index.db"
        self.recent_limit = recent_limit
        self.recent_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_defaults()
        self._init_db()

    def _ensure_defaults(self):
        self._create_if_missing(self.core_path, json.dumps(DEFAULT_CORE, ensure_ascii=False, indent=2))
        self._create_if_missing(self.tasks_path, "[]")
        self._create_if_missing(self.recent_path)
        self._create_if_missing(self.loss_log_path)
        self._create_if_missing(self.pending_path)

    @staticmethod
    def _create_if_missing(path: Path, text: str = "") -> None:
        """Create a file atomically, never truncating an existing one.

        ``exists() + write_text`` is a TOCTOU race: two processes initializing the
        same fresh data dir could truncate a tail the other just wrote. O_EXCL
        makes creation the atomic winner-takes-all step instead.
        """
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return
        try:
            if text:
                os.write(fd, text.encode("utf-8"))
        finally:
            os.close(fd)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.execute("PRAGMA busy_timeout=10000")
        return con

    def _ensure_wal(self, con: sqlite3.Connection) -> None:
        """Switch the database to WAL once, tolerating concurrent first-time writers.

        ``PRAGMA journal_mode=WAL`` needs a quiet moment and does NOT honour the
        busy handler, so two processes initializing the same fresh data dir can get
        "database is locked" here; retry briefly instead of failing the call.
        """
        mode = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if mode == "wal":
            return
        deadline = time.monotonic() + 10.0
        while True:
            try:
                con.execute("PRAGMA journal_mode=WAL")
                return
            except sqlite3.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def _init_db(self):
        con = self._connect()
        try:
            self._ensure_wal(con)
            has_history = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'history'"
            ).fetchone()
            if not has_history:
                con.execute(
                    "CREATE TABLE IF NOT EXISTS history ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "role TEXT NOT NULL,"
                    "content TEXT NOT NULL,"
                    "ts REAL NOT NULL,"
                    "private INTEGER NOT NULL DEFAULT 0,"
                    "session_id TEXT,"
                    "session_label TEXT)"
                )
            columns = {row[1] for row in con.execute("PRAGMA table_info(history)")}
            if "session_id" not in columns:
                con.execute("ALTER TABLE history ADD COLUMN session_id TEXT")
            if "session_label" not in columns:
                con.execute("ALTER TABLE history ADD COLUMN session_label TEXT")
            has_index = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_history_ts'"
            ).fetchone()
            if not has_index:
                con.execute("CREATE INDEX IF NOT EXISTS idx_history_ts ON history(ts)")
            try:
                has_fts = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'history_fts'"
                ).fetchone()
                if not has_fts:
                    con.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5("
                        "content, content='history', content_rowid='id', tokenize='unicode61')"
                    )
                    # index everything written before the FTS table existed
                    con.execute("INSERT INTO history_fts(history_fts) VALUES('rebuild')")
                con.execute(
                    "CREATE TRIGGER IF NOT EXISTS history_fts_ai AFTER INSERT ON history BEGIN "
                    "INSERT INTO history_fts(rowid, content) VALUES (new.id, new.content); END"
                )
            except sqlite3.OperationalError:
                # SQLite built without FTS5 - search() falls back to LIKE
                pass
            con.commit()
        finally:
            con.close()

    @contextmanager
    def locked(self):
        """Cross-process single-writer lock that works on Windows, Linux and macOS.

        The mutex is a SQLite ``BEGIN IMMEDIATE`` write transaction: no
        platform-specific file locking is needed, and every writer that opens the
        same index.db (e.g. two agents on one project) serializes on it. The
        yielded connection must be used for SQLite writes inside the section.
        Do not nest ``locked()`` within itself - a second connection in the same
        process would wait for the lock it already holds.
        """
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
        except BaseException:
            con.close()
            raise
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def _atomic_write(self, path: Path, text: str) -> None:
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:6]}")
        tmp.write_text(text, encoding="utf-8")
        delay = 0.05
        last_error: PermissionError | None = None
        try:
            for _ in range(8):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError as exc:
                    # Windows: the destination may be briefly open by a concurrent
                    # reader/writer; retry with backoff instead of failing the op.
                    last_error = exc
                    time.sleep(delay)
                    delay = min(delay * 2, 1.0)
        except BaseException:
            self._remove_quietly(tmp)
            raise
        self._remove_quietly(tmp)
        if last_error is not None:
            raise last_error

    @staticmethod
    def _remove_quietly(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def read_core(self) -> dict:
        return json.loads(self.core_path.read_text(encoding="utf-8"))

    def write_core(self, data: dict) -> None:
        self._atomic_write(self.core_path, json.dumps(data, ensure_ascii=False, indent=2))

    def read_tasks(self) -> list:
        return json.loads(self.tasks_path.read_text(encoding="utf-8"))

    def write_tasks(self, data: list) -> None:
        self._atomic_write(self.tasks_path, json.dumps(data, ensure_ascii=False, indent=2))

    def session_recent_path(self, session_id: str | None) -> Path:
        if not session_id or session_id == DEFAULT_SESSION:
            return self.recent_path
        return self.recent_dir / f"{_safe_session_name(session_id)}.jsonl"

    def read_recent(self, session_id: str | None = None) -> list:
        path = self.session_recent_path(session_id)
        if not path.exists():
            return []
        messages = []
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                sys.stderr.write(
                    f"living-memory: skipping malformed recent line {index + 1} in {path.name}\n"
                )
                continue
            if not isinstance(message, dict):
                sys.stderr.write(
                    f"living-memory: skipping non-object recent line {index + 1} in {path.name}\n"
                )
                continue
            if "id" not in message:
                message["id"] = f"legacy-{message.get('ts', f'{index}')}-{index}"
            messages.append(message)
        return messages

    def write_recent(self, messages: list, session_id: str | None = None) -> None:
        path = self.session_recent_path(session_id)
        body = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages)
        self._atomic_write(path, body)

    def append_message(
        self,
        role: str,
        content: str,
        private: bool = False,
        session_id: str | None = None,
        session_label: str | None = None,
    ) -> dict:
        with self.locked() as con:
            msg = self._append_locked(con, role, content, private, session_id, session_label)
        return msg

    def append_messages(
        self,
        items: list,
        session_id: str | None = None,
        session_label: str | None = None,
    ) -> int:
        """Append a batch of ``{role, content, private?}`` records in one locked pass.

        Used by the bridge so a session tail sync costs one Python process, not
        one per message. Returns the number of records actually appended.
        """
        appended = 0
        with self.locked() as con:
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                role = item.get("role")
                content = item.get("content")
                if role not in ("user", "assistant") or not isinstance(content, str) or not content:
                    continue
                self._append_locked(
                    con, role, content, bool(item.get("private")), session_id, session_label
                )
                appended += 1
        return appended

    def _append_locked(self, con, role, content, private, session_id, session_label) -> dict:
        msg = {
            "id": uuid.uuid4().hex[:12],
            "role": role,
            "content": content,
            "ts": time.time(),
        }
        if private:
            msg["private"] = True
        recent = self.read_recent(session_id)
        recent.append(msg)
        recent = recent[-self.recent_limit:]
        self.write_recent(recent, session_id)
        if not private:
            self._index(con, role, content, msg["ts"], session_id, session_label)
        return msg

    def _index(
        self,
        con: "sqlite3.Connection",
        role: str,
        content: str,
        ts: float,
        session_id: str | None = None,
        session_label: str | None = None,
    ) -> None:
        """Insert one history row; must run on the locked connection."""
        con.execute(
            "INSERT INTO history (role, content, ts, private, session_id, session_label)"
            " VALUES (?, ?, ?, 0, ?, ?)",
            (role, content, ts, session_id, session_label),
        )

    def history_count(self) -> int:
        with self._connect() as con:
            return con.execute("SELECT COUNT(*) FROM history").fetchone()[0]

    @staticmethod
    def _fts_query(query: str) -> str:
        """Quote every token so user input can never be FTS5 syntax."""
        tokens = [token for token in re.split(r"\s+", query.strip()) if token]
        return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)

    @staticmethod
    def _like_pattern(query: str) -> str:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    def search(self, query: str, limit: int = 5) -> list:
        """Full-text search over the history (FTS5), falling back to LIKE.

        LIKE stays for SQLite builds without FTS5; metacharacters are escaped
        there, so a "%" in the query is a literal, not a wildcard.
        """
        query = (query or "").strip()
        if not query:
            return []
        with self._connect() as con:
            has_fts = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'history_fts'"
            ).fetchone()
            if has_fts and self._fts_query(query):
                try:
                    rows = con.execute(
                        "SELECT h.id, h.role, h.content, h.ts, h.session_id, h.session_label "
                        "FROM history_fts f JOIN history h ON h.id = f.rowid "
                        "WHERE h.private = 0 AND history_fts MATCH ? ORDER BY rank LIMIT ?",
                        (self._fts_query(query), limit),
                    ).fetchall()
                    return [self._search_row(row) for row in rows]
                except sqlite3.OperationalError:
                    pass  # query unsupported by this build -> LIKE below
            rows = con.execute(
                "SELECT id, role, content, ts, session_id, session_label FROM history "
                "WHERE private = 0 AND content LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT ?",
                (self._like_pattern(query), limit),
            ).fetchall()
        return [self._search_row(row) for row in rows]

    @staticmethod
    def _search_row(row) -> dict:
        return {
            "id": row[0],
            "role": row[1],
            "content": row[2],
            "ts": row[3],
            "session_id": row[4],
            "session_label": row[5],
        }

    def log_loss(self, role: str, text: str, reason: str, indexed: bool) -> dict:
        record = {
            "ts": time.time(),
            "role": role,
            "text": text,
            "reason": reason,
            "indexed": indexed,
        }
        with self.loss_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def read_loss_log(self) -> list:
        return self._read_jsonl(self.loss_log_path)

    def append_pending(self, items: list) -> list:
        records = self.read_pending()
        next_id = max((r.get("id", 0) for r in records), default=0) + 1
        now = time.time()
        for item in items:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            records.append(
                {
                    "id": next_id,
                    "ts": now,
                    "kind": (item.get("kind") or "other").strip(),
                    "text": text,
                    "status": "pending",
                }
            )
            next_id += 1
        self.write_pending(records)
        return records

    def read_pending(self) -> list:
        return self._read_jsonl(self.pending_path)

    def write_pending(self, records: list) -> None:
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        self._atomic_write(self.pending_path, body)

    def resolve_pending(self, pending_id: int, approve: bool) -> dict | None:
        with self.locked():
            records = self.read_pending()
            target = None
            for record in records:
                if record.get("id") == pending_id and record.get("status") == "pending":
                    target = record
                    break
            if target is None:
                return None
            if approve:
                self._apply_pending(target)
            target["status"] = "approved" if approve else "rejected"
            target["resolved_at"] = time.time()
            self.write_pending(records)
            return target

    def _apply_pending(self, item: dict) -> None:
        kind = (item.get("kind") or "").lower()
        text = item.get("text") or ""
        if not text:
            return
        if kind == "goal":
            core = self.read_core()
            goals = core.setdefault("goals", [])
            if text not in goals:
                goals.append(text)
            self.write_core(core)
        elif kind in ("like", "dislike"):
            core = self.read_core()
            preferences = core.setdefault("preferences", {})
            bucket = preferences.setdefault("likes" if kind == "like" else "dislikes", [])
            if text not in bucket:
                bucket.append(text)
            self.write_core(core)
        elif kind == "task":
            tasks = self.read_tasks()
            key = text.strip().lower()
            existing = next(
                (t for t in tasks if t["topic"].strip().lower() == key), None
            )
            if existing is None:
                tasks.append(
                    {
                        "topic": text,
                        "status": "open",
                        "resolved": None,
                        "open": None,
                        "updated_at": _iso_now(),
                    }
                )
            self.write_tasks(tasks)
        else:
            item["note"] = "kind not mapped to core/tasks (approved as is)"

    def _read_jsonl(self, path: Path) -> list:
        records = []
        if not path.exists():
            return records
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records
