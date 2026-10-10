from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from compress import apply_task_updates, maybe_compress
from llm import MockProvider, OpencodeCLIProvider
from normalize import (
    MAX_CLOSED_TASKS,
    MAX_GOAL,
    MAX_OPEN_TASKS,
    MAX_PREFERENCE,
    MAX_TASK_FIELD,
    MAX_TOPIC,
    enforce_task_caps,
    normalize_patch,
)
from store import MemoryStore

BASE = Path(__file__).parent
SANDBOX = BASE / "sandbox"
RECENT_LIMIT = 10
LONG_GOAL = (
    "выпустить стабильную версию продукта с полным набором функций, "
    "документацией, автотестами и поддержкой пользователей в течение года"
)
LONG_RESOLVED = (
    "беру SQLite, потому что это простой файл, не нужен сервер, легко делать "
    "резервные копии копированием файла, удобно тестировать локально, "
    "и всё это без Docker и сетевых зависимостей"
)
LONG_TOPIC = (
    "очень длинная тема про архитектурные решения проекта и их последствия "
    "во всех подробностях"
)

DIRTY_DIALOGUE = [
    ("user", "Привет! Меня зовут Пётр. Тема: выбор базы данных для трекера."),
    ("assistant", "Привет, Пётр! Для небольшого проекта обычно советуют SQLite — файл рядом, без сервера."),
    ("user", f"Решили: {LONG_RESOLVED}."),
    ("assistant", "Отличный выбор. Схема: expenses и categories, плюс schema_version для миграций."),
    ("user", "Отвечай мне, пожалуйста, очень коротко и только по делу."),
    ("assistant", "Хорошо. Что дальше?"),
    ("user", "Тема: база данных. Осталось: добавить индексы и продумать миграции для будущих версий схемы."),
    ("assistant", "Индексы по дате — первый шаг. Миграции ведём через schema_version."),
    ("user", "Кстати, у меня есть кот Барсик — тоже любит спать на ноутбуке."),
    ("assistant", "Понимаю :) Автосохранение спасёт."),
    ("user", "Ок. А что решили про графики? Хочу диаграмму по месяцам."),
    ("assistant", "Позже добавишь библиотеку на фронте; данные уже будут в базе."),
    ("user", "Хорошо. Ещё: не храни мои шутки, это неважно."),
    ("assistant", "Договорились."),
    ("user", "Спасибо!"),
]

hard_fails: list[str] = []


def hard(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        hard_fails.append(name)


def info(name: str, detail: str = "") -> None:
    print(f"[ИНФО] {name}" + (f" — {detail}" if detail else ""))


def json_dump(data) -> str:
    return json.dumps(data, ensure_ascii=False)


def check_limits(store: MemoryStore, label: str) -> None:
    core = store.read_core()
    tasks = store.read_tasks()
    bad: list[str] = []
    for goal in core.get("goals", []):
        if len(goal) > MAX_GOAL:
            bad.append(f"goal({len(goal)}): {goal[:50]}")
    for key in ("likes", "dislikes"):
        for item in core.get("preferences", {}).get(key, []):
            if len(item) > MAX_PREFERENCE:
                bad.append(f"{key}({len(item)}): {item[:50]}")
    for entry in tasks:
        if len(entry["topic"]) > MAX_TOPIC:
            bad.append(f"topic({len(entry['topic'])}): {entry['topic'][:50]}")
        for field in ("resolved", "open"):
            value = entry.get(field)
            if not value:
                continue
            items = value if isinstance(value, list) else [value]
            for item in items:
                if len(item) > MAX_TASK_FIELD:
                    bad.append(f"{field}({len(item)}): {item[:50]}")
    hard(f"{label}: все элементы в лимитах длины", not bad, "; ".join(bad[:3]))
    open_count = sum(1 for t in tasks if t.get("status") != "done")
    closed_count = sum(1 for t in tasks if t.get("status") == "done")
    hard(f"{label}: открытых задач <= {MAX_OPEN_TASKS}", open_count <= MAX_OPEN_TASKS,
         f"{open_count}")
    hard(f"{label}: закрытых задач <= {MAX_CLOSED_TASKS}", closed_count <= MAX_CLOSED_TASKS,
         f"{closed_count}")
    hard(f"{label}: user.style не хранится",
         not store.read_core().get("user", {}).get("style"))


def test_unit() -> None:
    print("\n===== UNIT: нормализация грязного патча =====")
    dirty_patch = {
        "core": {
            "user": {"name": "Пётр", "style": "очень коротко и сухо"},
            "preferences": {"likes": ["Python", "x" * 150], "dislikes": []},
            "goals": [LONG_GOAL, "вторая цель"],
            "meta": {"version": 99},
        },
        "tasks": [
            {"topic": LONG_TOPIC, "status": "open", "resolved": "", "open": "индексы"},
            {"topic": "", "status": "open", "resolved": "мусор"},
            {"topic": "хранилище", "status": "done", "resolved": LONG_RESOLVED},
        ],
        "used": [1],
        "notes": "тест",
    }
    clean, logs = normalize_patch(dirty_patch, {}, [])
    reasons = {entry["reason"] for entry in logs}
    print("логи нормализации:")
    for entry in logs:
        print(f"  - {entry['reason']}: {entry['text'][:70]}")

    hard("Стиль удалён из патча", "style" not in clean["core"].get("user", {}))
    hard("Стиль залогирован", "patch:rejected:style_is_meta" in reasons)
    hard("Лишний ключ core залогирован", "patch:rejected:unknown_key" in reasons)
    hard("Пустой topic отклонён", "patch:rejected:no_topic" in reasons)
    long_like = clean["core"]["preferences"]["likes"][1]
    hard("Длинный like обрезан до лимита", len(long_like) <= MAX_PREFERENCE,
         f"{len(long_like)} симв.")
    hard("Обрезка залогирована", any(r.startswith("patch:truncated:likes") for r in reasons))
    goal = clean["core"]["goals"][0]
    hard("Длинная goal обрезана", len(goal) <= MAX_GOAL, f"{len(goal)} симв.")
    topic = clean["tasks"][0]["topic"]
    hard("Длинный topic обрезан", len(topic) <= MAX_TOPIC, f"{len(topic)} симв.")
    resolved = clean["tasks"][1]["resolved"][0]
    hard("Длинный resolved обрезан", len(resolved) <= MAX_TASK_FIELD,
         f"{len(resolved)} симв.")
    hard("Все логи имеют причину patch:*", all(r.startswith("patch:") for r in reasons))

    print("\n===== UNIT: дедупликация тем =====")
    tasks = [
        {"topic": "Выбор хранилища", "status": "in-progress",
         "resolved": ["SQLite"], "open": ["миграции"], "updated_at": "2026-01-01T00:00:00"},
        {"topic": "storage choice", "status": "open",
         "resolved": None, "open": ["indexes"], "updated_at": "2026-01-01T00:00:00"},
    ]
    updates = [
        {"topic": "выбор хранилища", "status": "in-progress", "resolved": ["SQLite ok"]},
        {"topic": "Storage decision", "status": "in-progress", "resolved": ["SQLite chosen"]},
    ]
    tasks = apply_task_updates(tasks, updates)
    hard("Точный дубль слит (регистр/пробелы)", len(tasks) == 2,
         f"тем: {len(tasks)}")
    fuzzy = next((t for t in tasks if "storage" in t["topic"].lower()), None)
    hard("Фаззи-дубль слит по ключевым словам",
         fuzzy is not None and fuzzy["resolved"] == ["SQLite chosen"],
         json_dump(fuzzy))
    exact = next((t for t in tasks if t["topic"] == "Выбор хранилища"), None)
    hard("Решения накапливаются (union, без потери)",
         exact is not None and exact["resolved"] == ["SQLite", "SQLite ok"],
         json_dump(exact))

    print("\n===== UNIT: лимиты количества задач =====")
    many_open = [
        {"topic": f"тема {i}", "status": "open", "updated_at": f"2026-01-{i:02d}T00:00:00"}
        for i in range(1, 13)
    ]
    capped, caps_logs = enforce_task_caps(many_open)
    hard("Открытые урезаны до 10", len(capped) == MAX_OPEN_TASKS, f"{len(capped)}")
    dropped = {entry["text"] for entry in caps_logs}
    hard("Вытеснены самые старые темы", dropped == {"тема 1", "тема 2"},
         json_dump(sorted(dropped)))
    hard("Вытеснение залогировано",
         len(caps_logs) == 2 and all("task_cap:open" in entry["reason"] for entry in caps_logs))

    many_closed = [
        {"topic": f"закрытая {i}", "status": "done", "updated_at": f"2026-01-{i:02d}T00:00:00"}
        for i in range(1, 13)
    ]
    capped, caps_logs = enforce_task_caps(many_closed)
    hard("Закрытые урезаны до 10", len(capped) == MAX_CLOSED_TASKS, f"{len(capped)}")


def test_e2e(provider, is_mock: bool) -> None:
    print(f"\n===== E2E ({'мок' if is_mock else 'реальная LLM'}) =====")
    base = SANDBOX / ("normalization_mock" if is_mock else "normalization_llm")
    if base.exists():
        shutil.rmtree(base)
    store = MemoryStore(base, recent_limit=RECENT_LIMIT)
    compressions = 0
    for role, content in DIRTY_DIALOGUE:
        store.append_message(role, content)
        if maybe_compress(store, provider):
            compressions += 1
    info("сжатий", str(compressions))

    check_limits(store, "конспект")

    patch_logs = [r for r in store.read_loss_log() if r["role"] == "patch"]
    print("журнал нормализации:")
    for record in patch_logs:
        print(f"  - {record['reason']}: {record['text'][:80]}")
    hard("Каждая нормализация залогирована с причиной",
         all(r["reason"].startswith("patch:") for r in patch_logs))
    hard("Стиль не сохранён (провокация 'отвечай коротко')",
         not store.read_core().get("user", {}).get("style"))
    if not patch_logs:
        info("LLM вернула уже чистый патч",
             "нормализация не потребовалась ни разу")

    tasks = store.read_tasks()
    storage_topics = [t["topic"] for t in tasks if "баз" in t["topic"].lower() or "storage" in t["topic"].lower()]
    info("темы про базу", json_dump(storage_topics))
    hard("Тема базы не размножилась (<=2 записи)", len(storage_topics) <= 2,
         f"{len(storage_topics)}")


def build_provider(name: str):
    if name == "opencode":
        return OpencodeCLIProvider()
    return MockProvider()


def main() -> int:
    parser = argparse.ArgumentParser(description="Тесты нормализации патчей сжатия")
    parser.add_argument("--provider", choices=("mock", "opencode"),
                        default=os.environ.get("MEMORY_LLM_PROVIDER", "mock"))
    parser.add_argument("--tests", choices=("unit", "e2e", "all"), default="all")
    args = parser.parse_args()
    provider = build_provider(args.provider)
    is_mock = args.provider == "mock"

    if args.tests in ("unit", "all"):
        test_unit()
    if args.tests in ("e2e", "all"):
        test_e2e(provider, is_mock)

    print()
    if hard_fails:
        print(f"ИТОГ: провалено обязательных проверок: {len(hard_fails)}")
        for name in hard_fails:
            print(f"  - {name}")
        return 1
    print("ИТОГ: все обязательные проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
