"""Search: FTS5 path, LIKE fallback escaping, malformed input safety."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from store import MemoryStore  # noqa: E402


def _seed(store: MemoryStore) -> None:
    store.append_message("user", "Мы решили взять SQLite для хранения данных.")
    store.append_message("assistant", "Хороший выбор — SQLite прост в деплое.")
    store.append_message("user", "Проценты: 100% времени и подчёркивания _test_ в тексте.")


def test_search_finds_tokens_and_survives_syntax(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path / "store"))
    _seed(store)

    assert len(store.search("SQLite")) == 2
    hits = store.search("взять SQLite")
    assert len(hits) == 1
    assert "SQLite" in hits[0]["content"]

    hits = store.search("100%")
    assert len(hits) == 1

    # FTS5 syntax characters must never crash the search
    for weird in ("%", "(", '"', "-", "AND", "NEAR("):
        assert isinstance(store.search(weird), list)


def test_search_like_fallback_escapes_metacharacters(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path / "store"))
    _seed(store)
    con = store._connect()
    try:
        con.execute("DROP TABLE history_fts")
        con.commit()
    finally:
        con.close()

    assert len(store.search("обычный-такого-нет")) == 0
    assert len(store.search("SQLite")) == 2
    hits = store.search("100%")
    assert len(hits) == 1
    # literal "%" must match exactly the one row containing it, not everything
    assert len(store.search("%")) == 1
    # literal "_" matches only the row containing "_test_" (unescaped it would
    # match every row, since _ is a single-character wildcard in LIKE)
    assert len(store.search("_")) == 1
