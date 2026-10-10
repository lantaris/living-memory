from __future__ import annotations

import json
import shutil
import sys
import threading
from pathlib import Path

from compress import run_compression
from inject import build_system_prompt
from llm import MockProvider
from store import MemoryStore

BASE = Path(__file__).parent
SANDBOX = BASE / "sandbox"

FW = "fw"
APP = "app"
FW_LABEL = "Firmware"
APP_LABEL = "App"

FW_MESSAGES = [
    ("user", "Тема: настройка. Решили: прошивка на Rust."),
    ("assistant", "Принято."),
    ("user", "Уточню: сборка через cargo."),
    ("assistant", "Ок."),
    ("user", "Ещё вопрос про отладку."),
    ("assistant", "Слушаю."),
    ("user", "Используем defmt для логов."),
    ("assistant", "Хорошо."),
    ("user", "Согласен."),
    ("assistant", "Дальше?"),
]

APP_MESSAGES = [
    ("user", "Тема: настройка. Решили: приложение на TypeScript."),
    ("assistant", "Принято."),
    ("user", "Ещё думаю про сборщик."),
    ("assistant", "Ок."),
    ("user", "Продолжим завтра."),
    ("assistant", "Слушаю."),
    ("user", "Лишь бы не сломать прод."),
    ("assistant", "Хорошо."),
    ("user", "Согласен."),
    ("assistant", "Дальше?"),
]

hard_fails: list[str] = []


def hard(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        hard_fails.append(name)


def info(name: str, detail: str = "") -> None:
    print(f"[ИНФО] {name}" + (f" — {detail}" if detail else ""))


def fresh_store(name: str) -> MemoryStore:
    base = SANDBOX / name
    if base.exists():
        shutil.rmtree(base)
    return MemoryStore(base, recent_limit=10)


def feed(store: MemoryStore, provider, session_id, session_label, messages) -> int:
    compressions = 0
    for role, content in messages:
        store.append_message(role, content, session_id=session_id, session_label=session_label)
        if run_compression_if_full(store, provider, session_id, session_label):
            compressions += 1
    return compressions


def run_compression_if_full(store, provider, session_id, session_label):
    if len(store.read_recent(session_id)) >= store.recent_limit:
        return run_compression(store, provider, session_id=session_id, session_label=session_label)
    return None


def session_tasks(store: MemoryStore, session_id: str) -> list:
    return [t for t in store.read_tasks() if t.get("session_id") == session_id]


def test_separate_tails_and_tasks() -> None:
    print("\n===== ТЕСТ 1: раздельные хвосты и задачи =====")
    store = fresh_store("ms_tails")
    provider = MockProvider()

    fw_compressions = feed(store, provider, FW, FW_LABEL, FW_MESSAGES)
    app_compressions = feed(store, provider, APP, APP_LABEL, APP_MESSAGES)
    info("сжатий", f"fw={fw_compressions}, app={app_compressions}")

    fw_recent = store.read_recent(FW)
    app_recent = store.read_recent(APP)
    legacy_recent = store.read_recent()
    hard("Хвост fw и app раздельны", len(fw_recent) == 5 and len(app_recent) == 5,
         f"fw={len(fw_recent)}, app={len(app_recent)}")
    hard("Legacy-хвост не затронут", len(legacy_recent) == 0)
    hard("Файлы хвостов существуют",
         (store.memory_dir / "recent" / f"{FW}.jsonl").exists()
         and (store.memory_dir / "recent" / f"{APP}.jsonl").exists())

    fw_tasks = session_tasks(store, FW)
    app_tasks = session_tasks(store, APP)
    hard("У fw своя задача", len(fw_tasks) == 1 and "Rust" in json.dumps(fw_tasks, ensure_ascii=False))
    hard("У app своя задача", len(app_tasks) == 1 and "TypeScript" in json.dumps(app_tasks, ensure_ascii=False))
    hard("Фаззи-дедуп не слил темы между сессиями", len(store.read_tasks()) == 2,
         f"всего задач: {len(store.read_tasks())}")
    hard("Метка сессии сохранена",
         fw_tasks[0].get("session_label") == FW_LABEL and app_tasks[0].get("session_label") == APP_LABEL)

    prompt_fw = build_system_prompt(store, FW, FW_LABEL)
    prompt_app = build_system_prompt(store, APP, APP_LABEL)
    hard("Промпт fw: MY TASKS содержит Rust", "MY TASKS (session: Firmware)" in prompt_fw and "Rust" in prompt_fw)
    hard("Промпт fw: OTHER SESSIONS со сводкой app", "[App]" in prompt_fw)
    hard("Промпт fw: детали app не подмешаны", "TypeScript" not in prompt_fw)
    hard("Промпт app: MY TASKS содержит TypeScript", "TypeScript" in prompt_app)
    hard("Промпт app: Rust только в сводке", "Rust" not in prompt_app)
    hard("Промпт fw: хвост только fw",
         "прошивка на Rust" in prompt_fw and "приложение на TypeScript" not in prompt_fw)

    second = run_compression(store, provider, session_id=FW, session_label=FW_LABEL)
    hard("Повторное сжатие fw не тронуло app-задачу",
         session_tasks(store, APP)[0]["resolved"] == ["приложение на TypeScript"])


def test_search_labels() -> None:
    print("\n===== ТЕСТ 2: поиск с метками сессий =====")
    store = fresh_store("ms_search")
    provider = MockProvider()
    feed(store, provider, FW, FW_LABEL, FW_MESSAGES)
    feed(store, provider, APP, APP_LABEL, APP_MESSAGES)

    rust_hits = store.search("Rust")
    ts_hits = store.search("TypeScript")
    hard("Поиск находит сообщение fw с меткой",
         len(rust_hits) > 0 and rust_hits[0]["session_id"] == FW and rust_hits[0]["session_label"] == FW_LABEL,
         json.dumps(rust_hits[:1], ensure_ascii=False))
    hard("Поиск находит сообщение app с меткой",
         len(ts_hits) > 0 and ts_hits[0]["session_id"] == APP)


def test_rotate_keeps_concurrent_append() -> None:
    print("\n===== ТЕСТ 3: append во время сжатия не теряется =====")
    store = fresh_store("ms_race")
    for role, content in FW_MESSAGES:
        store.append_message(role, content, session_id=FW, session_label=FW_LABEL)
    before = store.read_recent(FW)
    hard("До сжатия хвост полный", len(before) == 10)

    class ConcurrentWriteProvider(MockProvider):
        def __init__(self, target_store, session_id, session_label):
            self.target_store = target_store
            self.session_id = session_id
            self.session_label = session_label

        def summarize(self, core, tasks, messages, session_label=None):
            self.target_store.append_message(
                "user", "Это сообщение пришло во время сжатия.", session_id=self.session_id,
                session_label=self.session_label,
            )
            return super().summarize(core, tasks, messages, session_label)

    provider = ConcurrentWriteProvider(store, FW, FW_LABEL)
    run_compression(store, provider, keep_recent=5, session_id=FW, session_label=FW_LABEL)

    after = store.read_recent(FW)
    contents = [m["content"] for m in after]
    ids = [m["id"] for m in after]
    hard("Свежее сообщение сохранилось в хвосте",
         any("во время сжатия" in c for c in contents), json.dumps(contents, ensure_ascii=False))
    hard("Хвост не потерял лимит", len(after) <= 10, f"{len(after)}")
    hard("Дубликатов по id нет", len(ids) == len(set(ids)))


def test_parallel_compression() -> None:
    print("\n===== ТЕСТ 4: параллельные сжатия двух сессий =====")
    store = fresh_store("ms_parallel")
    provider = MockProvider()
    for role, content in FW_MESSAGES:
        store.append_message(role, content, session_id=FW, session_label=FW_LABEL)
    for role, content in APP_MESSAGES:
        store.append_message(role, content, session_id=APP, session_label=APP_LABEL)

    errors: list = []

    def worker(session_id, session_label):
        try:
            run_compression(store, provider, session_id=session_id, session_label=session_label)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{session_id}: {exc}")

    threads = [
        threading.Thread(target=worker, args=(FW, FW_LABEL)),
        threading.Thread(target=worker, args=(APP, APP_LABEL)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    hard("Параллельные сжатия без ошибок", not errors, "; ".join(errors))
    tasks = store.read_tasks()
    hard("Обе задачи сохранились после гонки", len(tasks) == 2,
         json.dumps(tasks, ensure_ascii=False)[:200])
    meta = store.read_core()["meta"]
    hard("Оба инкремента счётчика сохранены (нет lost update)", meta["compressions"] == 2,
         f"compressions={meta['compressions']}")


def main() -> int:
    test_separate_tails_and_tasks()
    test_search_labels()
    test_rotate_keeps_concurrent_append()
    test_parallel_compression()

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
