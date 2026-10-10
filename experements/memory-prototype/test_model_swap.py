from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from compress import flush, maybe_compress
from llm import MockProvider, OpencodeCLIProvider
from store import MemoryStore

BASE = Path(__file__).parent
SANDBOX = BASE / "sandbox" / "model_swap"
RECENT_LIMIT = 10

USER_TURNS = [
    "Привет! Меня зовут Иван, я бэкенд-разработчик. Собираю трекер расходов.",
    "Тема: выбор хранилища. Люблю Python. Что выбрать — SQLite или Postgres?",
    "Решили: беру SQLite. Осталось: схема таблиц и миграции.",
    "Моя цель — выпустить MVP за два месяца.",
    "Тема: деплой. Смотрю на Fly.io и VPS с Docker.",
    "Решили: Docker + Fly.io. Осталось: Dockerfile и CI.",
    "Не люблю ORM, хочу сырой SQL.",
    "Тема: авторизация. Решили: пароль из env. Осталось: middleware.",
]

SCRIPTED_REPLIES = [
    "Привет, Иван! Расскажи, какие требования к проекту.",
    "Для одного пользователя SQLite проще: база — это файл рядом, без сервера.",
    "Ок, схема: expenses и categories, миграции через schema_version.",
    "За два месяца реально, если не расширять скоуп.",
    "Для MVP бери Fly.io: деплой из Dockerfile одной командой.",
    "Хорошо, Dockerfile на slim-образе плюс volume для базы.",
    "Сырой SQL — понятный выбор для такого размера проекта.",
    "Один пароль из env и подписанная cookie — разумный минимум.",
]

MARKERS = {
    "имя (Иван/Ivan)": ("иван", "ivan"),
    "Python": ("python",),
    "SQLite": ("sqlite",),
    "цель MVP": ("mvp",),
    "тема деплоя": ("деплой", "deploy", "fly"),
    "нелюбовь к ORM": ("orm", "орм"),
}

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

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


def clean_cli_output(text: str) -> str:
    lines = []
    for line in text.splitlines():
        clean = ANSI_RE.sub("", line).strip()
        if not clean or clean.startswith("> build"):
            continue
        lines.append(clean)
    return "\n".join(lines).strip()


def generate_reply(user_turns: list, timeout: int = 180) -> str:
    context = "\n".join(f"Пользователь: {t}" for t in user_turns[:-1])
    prompt = (
        "Ты ассистент разработчика в деловом диалоге про пет-проект. "
        "Ответь на последнюю реплику пользователя одним-двумя короткими предложениями. "
        "Без списков, заголовков и приветствий.\n"
        + (f"Контекст переписки:\n{context}\n" if context else "")
        + f"Последняя реплика: {user_turns[-1]}\nОтвет:"
    )
    cmd = [shutil.which("opencode") or "opencode", "run"]
    model = os.environ.get("MEMORY_LLM_MODEL")
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"reply generation failed: {proc.stderr.strip()}")
    return clean_cli_output(proc.stdout)


def find_markers(store: MemoryStore) -> dict:
    blob = (
        json_dump(store.read_core()) + " " + json_dump(store.read_tasks())
    ).lower()
    return {
        name: any(variant in blob for variant in variants)
        for name, variants in MARKERS.items()
    }


def run_mode(mode: str, compression_provider, live_dialog: bool) -> dict:
    label = {
        "A": "мок-диалог + мок-сжатие",
        "B": "живой диалог (LLM) + мок-сжатие",
        "C": "мок-диалог + LLM-сжатие",
    }[mode]
    print(f"\n===== РЕЖИМ {mode}: {label} =====")
    base = SANDBOX / f"mode_{mode}"
    if base.exists():
        shutil.rmtree(base)
    store = MemoryStore(base, recent_limit=RECENT_LIMIT)

    dialog = []
    user_turns: list = []
    message_no = 0
    compression_count = 0
    compression_results: list = []

    def compress(step_note: str) -> None:
        nonlocal compression_count
        result = maybe_compress(store, compression_provider)
        if result:
            compression_count += 1
            compression_results.append({"after": step_note, **result})
            info(f"сжатие {compression_count} после сообщения {step_note}",
                 f"в оперативке осталось {len(store.read_recent())}")

    for index, user_text in enumerate(USER_TURNS):
        message_no += 1
        store.append_message("user", user_text)
        dialog.append({"role": "user", "content": user_text})
        user_turns.append(user_text)
        compress(message_no)
        if live_dialog:
            reply = generate_reply(user_turns)
            print(f"  LLM-ответ {index + 1}: {reply[:100]}")
        else:
            reply = SCRIPTED_REPLIES[index]
        message_no += 1
        store.append_message("assistant", reply)
        dialog.append({"role": "assistant", "content": reply})
        compress(message_no)

    result = flush(store, compression_provider)
    if result:
        compression_count += 1
        compression_results.append({"after": "flush", **result})

    log_path = base / "compressions.jsonl"
    with log_path.open("w", encoding="utf-8") as f:
        for entry in compression_results:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    info("сжатий всего", str(compression_count))
    for i, entry in enumerate(compression_results, start=1):
        notes = entry.get("notes") or ""
        if notes:
            print(f"  патч {i} ({entry.get('after')}): {notes[:160]}")

    dialog_path = base / "dialog.jsonl"
    with dialog_path.open("w", encoding="utf-8") as f:
        for message in dialog:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    markers = find_markers(store)
    print(f"  конспект: {json_dump(store.read_core())}")
    print(f"  задачи:   {json_dump(store.read_tasks())}")
    found = [name for name, ok in markers.items() if ok]
    missing = [name for name, ok in markers.items() if not ok]
    info("маркеры найдены", ", ".join(found) if found else "нет")
    if missing:
        info("маркеры не найдены", ", ".join(missing))
    return markers


def main() -> int:
    parser = argparse.ArgumentParser(description="Смена модели сжатия: режимы A/B/C")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("A", "B", "C"),
        default=["A"],
        help="A: мок/мок, B: диалог LLM + мок-сжатие, C: мок-диалог + LLM-сжатие",
    )
    args = parser.parse_args()

    mock = MockProvider()
    results: dict = {}
    for mode in args.modes:
        if mode == "A":
            results[mode] = run_mode(mode, mock, live_dialog=False)
        elif mode == "B":
            results[mode] = run_mode(mode, mock, live_dialog=True)
        else:
            results[mode] = run_mode(mode, OpencodeCLIProvider(), live_dialog=False)

    if len(results) > 1:
        print("\n===== СРАВНЕНИЕ РЕЖИМОВ =====")
        header = "маркер".ljust(18) + "".join(f"| {m} " for m in results)
        print(header)
        for name in MARKERS:
            row = name.ljust(18) + "".join(
                f"| {'да' if results[m][name] else 'НЕТ'} " for m in results
            )
            print(row)
        baseline = results.get("A")
        if baseline:
            for mode, markers in results.items():
                if mode == "A":
                    continue
                lost = [n for n, ok in markers.items() if baseline[n] and not ok]
                if lost:
                    signal(f"Режим {mode} потерял факты относительно A", ", ".join(lost))
                else:
                    info(f"Режим {mode}: все факты A на месте")
        hard("Режим A сохраняет все ключевые факты",
             all(results.get("A", {}).values()))

    print()
    if hard_fails:
        print(f"ИТОГ: провалено обязательных проверок: {len(hard_fails)}")
        for name in hard_fails:
            print(f"  - {name}")
        return 1
    print("ИТОГ: обязательные проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
