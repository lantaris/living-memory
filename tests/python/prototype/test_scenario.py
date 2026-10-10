from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from compress import maybe_compress
from inject import build_system_prompt, full_history_text
from llm import MockProvider
from store import MemoryStore

BASE = Path(__file__).parent
SECRET = "ПАРОЛЬ-СЕКРЕТ"

DIALOGUE = [
    ("user", "Привет! Меня зовут Иван, я бэкенд-разработчик на Python. Начал пет-проект — трекер расходов. Хочу, чтобы ты помог с архитектурой."),
    ("assistant", "Привет, Иван! Давай разберём архитектуру. Какие требования: веб, мобильное приложение, однопользовательский режим?"),
    ("user", "Веб, однопользовательский. Тема: выбор хранилища. Я люблю Python и не люблю Java. Думаю между SQLite и Postgres."),
    ("assistant", "Для однопользовательского веба SQLite проще: сервер не нужен, база — это просто файл рядом с приложением. Postgres имеет смысл, только если будет много конкурентных записей."),
    ("user", "Тема: выбор хранилища. Решили: беру SQLite. Осталось: продумать схему таблиц расходов и миграции."),
    ("assistant", "Отличный выбор. Схема: таблицы categories и expenses с полями amount, category_id, date, note. Для миграций подойдёт таблица schema_version и пара SQL-файлов."),
    ("user", "Моя цель — выпустить MVP за два месяца. Не люблю ORM из-за магии, хочу сырой SQL."),
    ("assistant", "Понял, сырой SQL через sqlite3. Тогда миграции — простой скрипт поверх schema_version. Стек прозрачный и без лишних слоёв."),
    ("user", "Тема: деплой. Где хостить MVP? Смотрю на Fly.io и VPS с Docker."),
    ("assistant", "Для MVP Fly.io проще: деплой из Dockerfile одной командой. VPS дешевле на длинной дистанции, но требует ручной настройки сервера."),
    ("user", "Тема: деплой. Решили: Docker + Fly.io. Осталось: написать Dockerfile и настроить CI через GitHub Actions."),
    ("assistant", "Хорошо. Dockerfile на python:3.12-slim, volume для файла SQLite. CI: тесты на каждый пуш, деплой на тег."),
    ("user", f"Кстати, не сохраняй это в память: {SECRET} от продовой базы — qwerty123.", True),
    ("user", "И ещё: предпочитаю тёмную тему в интерфейсах. Отвечай коротко, без воды."),
    ("assistant", "Запомню: тёмная тема и лаконичность. По CI — в Actions добавь виртуальное окружение и запускай тесты до деплоя."),
    ("user", "Тема: авторизация. Нужен ли логин, если пользователь один?"),
    ("assistant", "Если приложение доступно из интернета — да, минимально: один пароль в переменной окружения и подписанная cookie. Полноценные пользователи не нужны."),
    ("user", "Тема: авторизация. Решили: один пароль из env плюс подписанная cookie. Осталось: генерация секретного ключа и middleware."),
    ("assistant", "Добавь ключ в переменные Fly и проверку cookie во всех защищённых роутах."),
    ("user", "И ещё моя цель — open-source, выложить на GitHub под MIT."),
    ("assistant", "Отлично, MIT — самый простой вариант. Добавлю в план README с инструкцией запуска и скриншотами."),
]

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def main() -> int:
    memory_dir = BASE / "memory"
    if memory_dir.exists():
        shutil.rmtree(memory_dir)
    store = MemoryStore(BASE, recent_limit=10)
    provider = MockProvider()

    public_messages = []
    max_recent = 0
    compressions = 0

    print(f"Диалог: {len(DIALOGUE)} сообщений (включая 1 приватное)\n")
    print(f"{'#':>2} {'роль':>9} | {'recent':>6} | сжатие")
    print("-" * 40)

    for i, item in enumerate(DIALOGUE, start=1):
        role, content = item[0], item[1]
        private = len(item) > 2 and bool(item[2])
        store.append_message(role, content, private=private)
        if not private:
            public_messages.append((role, content))
        compressed = maybe_compress(store, provider)
        if compressed:
            compressions += 1
        len_recent = len(store.read_recent())
        max_recent = max(max_recent, len_recent)
        tag = "да" if compressed else ""
        priv = " (private)" if private else ""
        print(f"{i:>2} {role:>9} | {len_recent:>6} | {tag}{priv}")

    core = store.read_core()
    tasks = store.read_tasks()
    prompt = build_system_prompt(store)
    history = full_history_text(store)

    print("\n== КОНСПЕКТ (core.json) ==")
    print(json_dumps(core))
    print("\n== ЗАДАЧИ (tasks.json) ==")
    print(json_dumps(tasks))

    print("\n== ПРОВЕРКИ ==")
    check("Полная история в index.db", store.history_count() == len(public_messages),
          f"{store.history_count()} из {len(public_messages)}")
    check("Оперативка не растёт бесконечно", max_recent <= 10, f"максимум {max_recent} сообщений")
    check("Сжатие запускалось", compressions >= 2, f"{compressions} сжатий")

    name_ok = core["user"].get("name") == "Иван"
    check("Ядро: имя пользователя", name_ok, str(core["user"].get("name")))
    likes = " ".join(core["preferences"]["likes"])
    dislikes = " ".join(core["preferences"]["dislikes"])
    check("Ядро: предпочтение Python", "Python" in likes, likes)
    check("Ядро: неприязнь к Java", "Java" in dislikes, dislikes)
    goals = " ".join(core["goals"])
    check("Ядро: цель MVP (из ранних сообщений)", "MVP" in goals, goals)
    check("Свежая цель open-source доступна модели из оперативки", "MIT" in prompt or "open-source" in prompt.lower())

    topics = {t["topic"].lower(): t for t in tasks}
    check("Задачи: тема хранилища (сжата)", "выбор хранилища" in topics)
    check("Задачи: тема деплоя (сжата)", "деплой" in topics)
    check("Свежая тема авторизации доступна модели из оперативки", "авторизация" in prompt.lower())
    resolved_ok = all(topics[k]["resolved"] and topics[k]["open"] for k in topics)
    check("Задачи: у каждой темы есть resolved и open", resolved_ok)

    first_message_gone = not any(m["content"].startswith("Привет! Меня зовут Иван") for m in store.read_recent())
    check("Первое сообщение выпало из оперативки", first_message_gone)
    check("Имя доступно только через ядро", "Иван" in prompt and first_message_gone)
    check("Решение про SQLite доступно через задачи", "SQLite" in prompt)
    check("История деплоя доступна через задачи", "Fly.io" in prompt or "Docker" in prompt)
    check("Инъекция короче полной истории", len(prompt) < len(history),
          f"контекст {len(prompt)} симв. против истории {len(history)} симв.")

    found = store.search("SQLite")
    check("Деталь возвращается из index.db", len(found) > 0, f"найдено записей: {len(found)}")

    check("Приватное не в индексе", len(store.search("qwerty123")) == 0)
    check("Приватное не в контексте", "qwerty123" not in prompt)
    check("Приватное не в ядре/задачах",
          "qwerty123" not in json_dump(core) and "qwerty123" not in json_dump(tasks))

    print("\n== МАСШТАБИРОВАНИЕ (диалог повторяется ещё дважды) ==")
    base_prompt, base_history = len(prompt), len(history)
    for round_no in (2, 3):
        for item in DIALOGUE:
            role, content = item[0], item[1]
            private = len(item) > 2 and bool(item[2])
            store.append_message(role, content, private=private)
            maybe_compress(store, provider)
        round_prompt = len(build_system_prompt(store))
        round_history = len(full_history_text(store))
        print(f"круг {round_no}: в истории {store.history_count()} сообщ., "
              f"контекст {round_prompt} симв., история {round_history} симв.")
    check("Контекст не растёт вместе с историей", round_prompt <= base_prompt * 1.5,
          f"{base_prompt} -> {round_prompt} симв. при 3-кратном росте диалога")
    check("Доля контекста в истории падает", round_prompt / round_history <= 0.4,
          f"контекст — {round(100 * round_prompt / round_history)}% истории")
    check("История растёт линейно, конспект — нет", round_history >= base_history * 2,
          f"{base_history} -> {round_history} симв.")

    prompt = build_system_prompt(store)
    history = full_history_text(store)

    print("\n== МЕТРИКИ ==")
    total_compressions = store.read_core()["meta"]["compressions"]
    print(f"Сжатий: {total_compressions} (из них {compressions} за первые 21 сообщение)")
    print(f"Сообщений в index.db: {store.history_count()}")
    print(f"Максимум сообщений в оперативке: {max_recent} (лимит 10)")
    print(f"Контекст (инъекция): {len(prompt)} символов")
    print(f"Полная история: {len(history)} символов")
    print(f"Сжатие контекста: {100 - round(len(prompt) * 100 / max(len(history), 1))}%")

    failed = [name for name, ok, _ in results if not ok]
    print()
    if failed:
        print(f"ИТОГ: провалено проверок: {len(failed)} из {len(results)}")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"ИТОГ: все {len(results)} проверок пройдены")
    return 0


def json_dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def json_dump(data) -> str:
    return json.dumps(data, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
