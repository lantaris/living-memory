from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from compress import maybe_compress
from inject import build_system_prompt
from llm import MockProvider, OpencodeCLIProvider
from store import MemoryStore

BASE = Path(__file__).parent
SANDBOX = BASE / "sandbox"
RECENT_LIMIT = 10
KOT_MARKERS = ("Персик", "Persik", "Persic")
PYTHON_FACT = "Предпочитаю Python"
RUST_FACT = "Перешёл на Rust"

WAVE_1 = [
    ("user", "Продолжаем трекер расходов. Сначала добавлю категории по умолчанию."),
    ("assistant", "Хорошо: еда, транспорт, жильё, развлечения — стартовый набор категорий."),
    ("user", "Кстати, у меня дома живёт кот Персик — вечно спит на клавиатуре."),
    ("assistant", "Понял, вернёмся к категориям: их лучше держать отдельной таблицей."),
    ("user", "Согласен, отдельная таблица categories. Ещё подумаю про экспорт в CSV."),
    ("assistant", "CSV получается просто: sqlite3 умеет, останется обернуть в endpoint."),
    ("user", "Ок. Ещё надо решить, где хранить иконки категорий."),
    ("assistant", "Можно положить статические файлы в /static и ссылаться по имени."),
    ("user", "Пусть так. Позже проверю вёрстку на телефоне."),
    ("assistant", "Главный риск — таблица расходов на узком экране, проверь её."),
]

WAVE_2 = [
    ("user", "Вернусь к экспорту CSV: нужен ли фильтр по дате?"),
    ("assistant", "Для MVP хватит диапазона from/to, больше не усложняй."),
    ("user", "Тогда так. И посмотрю на FTS в SQLite, может пригодится."),
    ("assistant", "FTS тут избыточен, но попробовать можно — миграция лёгкая."),
    ("user", "Понял, откладываю. Вернёмся к вёрстке позже."),
]

WAVE_A = [
    ("user", "Предпочитаю Python для бэкенда."),
    ("assistant", "Записал, учту в примерах кода."),
    ("user", "Ещё открыт вопрос по схеме таблиц."),
    ("assistant", "Схема из прошлой сессии подходит: expenses и categories."),
    ("user", "Ок, заверни в миграцию."),
    ("assistant", "Сделаю пару SQL-файлов и таблицу schema_version."),
    ("user", "И не забудь про индексы по дате."),
    ("assistant", "Добавлю индекс на expenses.date."),
    ("user", "Хорошо. Дальше по плану."),
    ("assistant", "Держи план: миграции, CSV-экспорт, вёрстка."),
]

WAVE_B = [
    ("user", "Перешёл на Rust."),
    ("assistant", "Понял: теперь основной язык Rust, примеры буду давать на нём."),
    ("user", "Да. И подбери библиотеку для SQLite — rusqlite?"),
    ("assistant", "Для синхронного доступа rusqlite подходит, для async есть sqlx."),
    ("user", "Возьму rusqlite для MVP."),
]

WAVE_C = [
    ("user", "Ещё подумай про обработку ошибок в rusqlite."),
    ("assistant", "Оборачивай в Result и логируй через env_logger."),
    ("user", "Ок. Обновлять ли Docker-образ под Rust?"),
    ("assistant", "Да: rust:1.79-slim как builder, distroless для рантайма."),
    ("user", "В целом план не меняется, меняется только стек."),
]

hard_fails: list[str] = []


def hard(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        hard_fails.append(name)


def info(name: str, detail: str = "") -> None:
    print(f"[ИНФО] {name}" + (f" — {detail}" if detail else ""))


def signal(name: str, detail: str = "") -> None:
    print(f"[СИГНАЛ] {name}" + (f" — {detail}" if detail else ""))


def json_dump(data) -> str:
    return json.dumps(data, ensure_ascii=False)


def memory_text(store: MemoryStore) -> str:
    return json_dump(store.read_core()) + "\n" + json_dump(store.read_tasks())


def recent_text(store: MemoryStore) -> str:
    return "\n".join(m["content"] for m in store.read_recent())


def contains_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in KOT_MARKERS)


def feed(store: MemoryStore, provider, messages: list, log: list) -> int:
    compressions = 0
    for role, content in messages:
        store.append_message(role, content)
        result = maybe_compress(store, provider)
        if result:
            compressions += 1
            log.append(result)
    return compressions


def fresh_store(name: str) -> MemoryStore:
    base = SANDBOX / name
    if base.exists():
        shutil.rmtree(base)
    return MemoryStore(base, recent_limit=RECENT_LIMIT)


def print_summaries(log: list) -> None:
    for i, result in enumerate(log, start=1):
        notes = result.get("notes", "")
        if notes:
            print(f"  сжатие {i}: {notes}")


def test_quiet_loss(provider, is_mock: bool) -> None:
    print("\n===== ТЕСТ 1: ТИХАЯ ПОТЕРЯ =====")
    print("Факт, который по правилам сжатия не должен попасть в конспект:")
    print(f"  «{WAVE_1[2][1]}»")
    store = fresh_store("loss")
    log: list = []
    compressions = feed(store, provider, WAVE_1 + WAVE_2, log)
    info("сжатий выполнено", str(compressions))
    print_summaries(log)

    prompt = build_system_prompt(store)
    in_index = bool(store.search(KOT_MARKERS[0]))
    in_memory = contains_marker(memory_text(store))
    in_recent = contains_marker(recent_text(store))
    in_prompt = contains_marker(prompt)

    hard("Факт сохранён в index.db (обратимость)", in_index)
    hard("Факт вытеснен из оперативки", not in_recent)
    hard("Контекст согласован с конспектом", in_prompt == in_memory,
         f"в промпте: {in_prompt}, в конспекте: {in_memory}")

    if in_memory and is_mock:
        hard("Мок не сохраняет мимоходный факт", False, "мок сохранил факт в конспект")
    elif in_memory:
        signal("Конспект сохранил мимоходный факт",
               "граница «что важно» у модели шире эвристики мока")
        print("ВЕРДИКТ: сжатие сохранило больше ожидаемого — ядро может раздуваться")
    else:
        info("Конспект потерял мимоходный факт (ожидаемо)")
        if in_index:
            print("ВЕРДИКТ: тихая потеря — факт не виден модели, но обратим через store.search")
        else:
            print("ВЕРДИКТ: безвозвратная потеря — БАГ")


def test_conflict(provider, is_mock: bool) -> None:
    print("\n===== ТЕСТ 2: КОНФЛИКТ ФАКТОВ =====")
    print(f"Факт A: «{WAVE_A[0][1]}» -> сжатие -> Факт B: «{WAVE_B[0][1]}» (после вытеснения A)")
    store = fresh_store("conflict")
    log: list = []

    feed(store, provider, WAVE_A, log)
    likes_after_a = store.read_core()["preferences"]["likes"]
    info("ядро после первого сжатия", json_dump(likes_after_a))
    python_first = any("Python" in x for x in likes_after_a)
    if not python_first:
        info("Python не зафиксирован первым сжатием — конфликт вырожденный")

    feed(store, provider, WAVE_B + WAVE_C, log)
    print_summaries(log)

    core = store.read_core()
    likes = core["preferences"]["likes"]
    python_final = any("Python" in x for x in likes)
    rust_final = any("Rust" in x for x in likes)

    hard("Оба исходных сообщения в index.db",
         bool(store.search(PYTHON_FACT)) and bool(store.search(RUST_FACT)))
    info("ядро после конфликта", json_dump(likes))

    if rust_final and not python_final:
        verdict = "UPDATED"
        print("ВЕРДИКТ: ядро обновилось в пользу свежего факта (правильно)")
    elif rust_final and python_final:
        verdict = "ACCUMULATED"
        print("ВЕРДИКТ: ядро накопило оба факта (приемлемо при наличии пометки о смене)")
    elif python_first and not rust_final:
        verdict = "IGNORED"
        if is_mock:
            hard("Конфликт обработан", False, "осталось только старое значение")
        else:
            signal("Новое значение проигнорировано", "модель не перенесла смену в конспект")
            print("ВЕРДИКТ: новое проигнорировано — задокументировать как ограничение")
    else:
        verdict = "EMPTY"
        print("ВЕРДИКТ: ни один из фактов не в конспекте — сжатие не сработало")

    marked = any(
        ("Rust" in x)
        and any(k in x.lower() for k in ("switched", "previously", "переш", "раньше", "замен", "сменил"))
        for x in likes
    )
    if verdict == "ACCUMULATED":
        if marked:
            info("пометка о смене предпочтения есть")
        else:
            info("пометки о смене предпочтения нет", "видно два значения без хронологии")
    info("итоговый вердикт", verdict)


def build_provider(name: str):
    if name == "opencode":
        return OpencodeCLIProvider()
    return MockProvider()


def main() -> int:
    parser = argparse.ArgumentParser(description="Тесты границ сжатия памяти")
    parser.add_argument(
        "--provider",
        choices=("mock", "opencode"),
        default=os.environ.get("MEMORY_LLM_PROVIDER", "mock"),
    )
    parser.add_argument(
        "--tests",
        choices=("1", "2", "all"),
        default="all",
        help="какой тест запускать",
    )
    args = parser.parse_args()
    provider = build_provider(args.provider)
    is_mock = args.provider == "mock"

    print(f"Провайдер: {args.provider} ({type(provider).__name__})")
    if args.tests in ("1", "all"):
        test_quiet_loss(provider, is_mock)
    if args.tests in ("2", "all"):
        test_conflict(provider, is_mock)

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
