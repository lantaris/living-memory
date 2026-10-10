from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from compress import maybe_compress
from inject import build_system_prompt, full_history_text
from llm import OpencodeCLIProvider
from store import MemoryStore

BASE = Path(__file__).parent
SANDBOX = BASE / "sandbox" / "retention"
RECENT_LIMIT = 10
HYBRID_HISTORY = 20

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
REFUSAL_RE = re.compile(
    r"не знаю|не помню|не уверен|не могу знать|нет информаци|не упоминал|"
    r"неизвестно|не сказано|не рассказывал|не обсуждали|не сохранил|"
    r"don't know|do not know|not sure|no information|unknown|cannot say|"
    r"can't say|not mentioned|unclear|no memory",
    re.IGNORECASE,
)

DIALOGUE = [
    ("user", "Привет! Хочу начать проект — личный трекер расходов. Поможешь спланировать?"),
    ("assistant", "Привет! Конечно, давай. Расскажи, что уже есть и что хочешь получить."),
    ("user", "Пока ничего нет, только идея. Хочу простой веб-трекер для одного человека."),
    ("assistant", "Понял. Тогда начнём с базы: какие категории трат обычно нужны?"),
    ("user", "Кстати, меня зовут Иван. Категории — еда, транспорт, жильё, развлечения."),
    ("assistant", "Приятно познакомиться, Иван. Набор категорий хороший — добавим возможность создавать свои."),
    ("user", "Думаю про структуру: расходы, категории, даты. Что посоветуешь?"),
    ("assistant", "Классика: таблица трат с суммой, датой, категорией и заметкой. Плюс отдельная таблица категорий."),
    ("user", "Обсуждал с другом: он советует Postgres, но я сомневаюсь. Решили: беру SQLite — для одного пользователя хватит."),
    ("assistant", "Для однопользовательского приложения SQLite действительно проще: без сервера, база — файл рядом."),
    ("user", "Ок, тогда коннектор через стандартную библиотеку sqlite3."),
    ("assistant", "Верно, и никаких внешних сервисов. Потом легко сделать резервную копию файлом."),
    ("user", "Что по деньгам? Проект будет абсолютно бесплатным для меня?"),
    ("assistant", "Да, SQLite и локальная разработка бесплатны; хостинг потом — минимальный."),
    ("user", "Хорошо. Осталось: спроектировать схему таблиц — суммы, валюты, даты."),
    ("assistant", "Предлагаю expenses(id, amount, currency, category_id, date, note) и categories(id, name, icon)."),
    ("user", "Валюту пока одну — рубль, но поле оставлю на будущее."),
    ("assistant", "Разумно: поле есть, логики конвертации нет — YAGNI в действии."),
    ("user", "Слушай, отвлекусь: у меня дома живёт кот Персик — вечно спит на клавиатуре."),
    ("assistant", "Понимаю :) Значит, автосохранение — обязательная фича, чтобы ничего не потерять."),
    ("user", "Согласен. Вернёмся к схеме: индексы по дате сразу заложить?"),
    ("assistant", "Да, индекс на expenses.date пригодится для сводок по месяцам."),
    ("user", "Ок. Ещё подумаю про подкатегории, но позже."),
    ("assistant", "Подкатегории — нормальная эволюция; сейчас не усложняй схему."),
    ("user", "Чуть не забыл представиться нормально: по профессии я бэкенд-разработчик."),
    ("assistant", "Отлично, тогда тебе будет просто: это типичная CRUD-задача с парой отчётов."),
    ("user", "Да, CRUD я делал много раз. Интересна именно память проекта — как не потерять контекст."),
    ("assistant", "Для этого и ведём документированные решения: схема, стек, договорённости."),
    ("user", "Ладно. Тогда зафиксируй: API будет JSON по /api/expenses."),
    ("assistant", "Записал. Пагинация сразу или потом?"),
    ("user", "Решили: собираем Docker-образ на python:3.12-slim — минимальный размер."),
    ("assistant", "Хорошо: slim-образ плюс слой зависимостей отдельно — кэш сборки будет работать."),
    ("user", "Угу. А база в volume, чтобы переживала пересборку."),
    ("assistant", "Да, volume на /data и путь к базе через переменную окружения."),
    ("user", "Ещё осталось: настроить CI через GitHub Actions — тесты на каждый пуш."),
    ("assistant", "Можно начать с одного job: установка зависимостей, pytest, линтер. Деплой добавишь позже."),
    ("user", "План принят. Пока без деплоя — сначала локально стабильно."),
    ("assistant", "Согласен, лучше не смешивать CI и CD на первом этапе."),
    ("user", "Что по тестам? Хочу покрыть хотя бы операции с тратами."),
    ("assistant", "Начни с CRUD тестов и пары расчётных: сумма за месяц, распределение по категориям."),
    ("user", "Вчера досмотрел сериал про космос — затянуло, до трёх ночи смотрел."),
    ("assistant", "Знакомо :) Тогда сегодня без ночного кодинга — силы пригодятся."),
    ("user", "Обещаю :) Вернёмся к отчётам: хочу график по месяцам."),
    ("assistant", "Для графиков потом подключишь библиотеку на фронте; на бэке — агрегаты по месяцам."),
    ("user", "Кстати, люблю Python — на нём и напишу. Знаю, что для трекера это оверкилл."),
    ("assistant", "Python для такого проекта — отличный выбор: быстро писать, легко читать."),
    ("user", "Ещё думаю про CLI-версию как бонус."),
    ("assistant", "CLI можно сделать поверх тех же функций, потом — тонкой обёрткой."),
    ("user", "Ок. Куда положить бизнес-логику, чтобы CLI и веб её пересекли?"),
    ("assistant", "Отдельный модуль core: чистые функции над базой, без веба и CLI."),
    ("user", "Решили про деплой: Docker + Fly.io. Для MVP этого достаточно."),
    ("assistant", "Согласен: Fly.io разворачивается из Dockerfile одной командой, дешёвый старт."),
    ("user", "А конфиги через переменные окружения — DATABASE_PATH и SECRET_KEY."),
    ("assistant", "Да, и не забудь добавить .env.example, чтобы не закоммитить секреты."),
    ("user", "Точно. Ещё хочу healthcheck endpoint для Fly."),
    ("assistant", "Легко: /healthz, который проверяет соединение с базой."),
    ("user", "Осталось: написать middleware для авторизации — проверка cookie на защищённых роутах."),
    ("assistant", "Хорошо: один общий декоратор, никаких ролевых моделей."),
    ("user", "Да, роли не нужны — пользователь один. Как хранить пароль?"),
    ("assistant", "Не храни пароль в коде: переменная окружения плюс сравнение с хэшем при входе."),
    ("user", "Кстати, пробовал на днях кофе из Эфиопии — очень необычный вкус, ягодный."),
    ("assistant", "Звучит интересно. Эфиопия — классика для светлой обжарки, действительно ягодной."),
    ("user", "Вернёмся к делу. Как выпускать обновления без простоев?"),
    ("assistant", "Для MVP — минута даунтайма не критична: остановил, задеплоил, поднял. Позже сделаешь rolling."),
    ("user", "Ок, без оверинжиниринга. Что с бэкапами?"),
    ("assistant", "Ежедневная копия файла базы в объектное хранилище — просто и достаточно."),
    ("user", "Ещё: не люблю ORM из-за магии. Буду писать запросы руками."),
    ("assistant", "Понимаю: явные SQL-запросы проще отлаживать, особенно на маленькой схеме."),
    ("user", "И миграции руками, простыми SQL-файлами, без Alembic."),
    ("assistant", "Тогда таблица schema_version и скрипт, который применяет файлы по порядку."),
    ("user", "Решили: авторизация — один пароль из env плюс подписанная cookie. Минимум."),
    ("assistant", "Хороший минимум для одного пользователя: без регистрации и сессий на сервере."),
    ("user", "Пароль себе сохраню в менеджере паролей, не в коде."),
    ("assistant", "Правильно. Значение пароля пусть приходит только через окружение."),
    ("user", "Ещё вопрос: логирование? Хочу понять, если что-то падает."),
    ("assistant", "Стандартный logging с уровнями; в продакшене — ротация файлов."),
    ("user", "Осталось: продумать тёмную тему интерфейса — глазам приятнее."),
    ("assistant", "Для MVP хватит CSS-переменных: одна светлая тема, одна тёмная, переключатель не обязателен."),
    ("user", "Ок, сделаю как систему токенов сразу."),
    ("assistant", "Тогда смена темы в будущем будет однострочной."),
    ("user", "Пока темы хватит. Что по мелочам: favicon, метатеги?"),
    ("assistant", "Нужны базовые метатеги и favicon — иначе во вкладках будет пусто."),
    ("user", "Кстати, купил механическую клавиатуру — печатать стало заметно приятнее."),
    ("assistant", "Класс: с хорошей клавиатурой рефакторинг не так страшен :)"),
    ("user", "Точно :) Ладно, давай к релизу. Что осталось по минимуму?"),
    ("assistant", "По минимуму: CRUD, авторизация, миграции, Dockerfile, CI. Это и есть MVP."),
    ("user", "Моя цель — выпустить MVP за два месяца. Укладываемся?"),
    ("assistant", "Вполне: если не расширять скоуп, два месяца с запасом."),
    ("user", "Договорились. Ещё хочу документацию: README и схему базы."),
    ("assistant", "Сделаем: README с запуском и таблицу-описание схемы прямо в нём."),
    ("user", "Ок. Как назовём проект? Пусть будет «Копилка»."),
    ("assistant", "Название хорошее. Домены не нужны — Fly.io даст поддомен."),
    ("user", "Решили: экспорт в CSV делаем после MVP-схемы — во вторую волну."),
    ("assistant", "Согласен: сначала стабильная схема, потом выгрузки. sqlite3 отдаёт CSV почти бесплатно."),
    ("user", "Ещё бы импорт из банковских выписок, но это мечты."),
    ("assistant", "Позже: начнёшь с CSV-импорта формата дата, сумма, категория — уже полезно."),
    ("user", "Осталось: добавить индексы по дате в expenses — отчёты станут быстрее."),
    ("assistant", "Один индекс по date и составной по (category_id, date), если понадобится."),
    ("user", "Понял. Кстати, что решили по валютам? Только рубль?"),
    ("assistant", "Да, поле есть, конвертации нет; при необходимости добавишь позже."),
    ("user", "Ок. Кажется, план полный. Что-нибудь забыли?"),
    ("assistant", "Может, страница статистики с суммой за сегодня и за месяц — дешёво и полезно."),
    ("user", "В детстве я собирал модели самолётов — любовь к деталям оттуда."),
    ("assistant", "Похоже, поэтому и проект делаешь аккуратно, шаг за шагом. Рад помочь."),
]

FACTS = [
    {"id": 1, "category": "user", "label": "имя: Иван", "markers": [r"\bиван\b|\bivan\b"]},
    {"id": 2, "category": "user", "label": "роль: бэкенд-разработчик", "markers": [r"бэкенд|бекенд|backend"]},
    {"id": 3, "category": "user", "label": "предпочтение: Python", "markers": [r"python"]},
    {"id": 4, "category": "user", "label": "антипатия: ORM", "markers": [r"\borm\b|о\.?р\.?м"]},
    {"id": 5, "category": "user", "label": "цель: MVP", "markers": [r"mvp"]},
    {"id": 6, "category": "decision", "label": "решение: SQLite", "markers": [r"sqlite"]},
    {"id": 7, "category": "decision", "label": "решение: Docker + Fly.io", "markers": [r"fly\.?io|\bfly\b"]},
    {"id": 8, "category": "decision", "label": "решение: пароль из env + cookie", "markers": [r"\benv\b|cookie|переменн\w+ окружения"]},
    {"id": 9, "category": "decision", "label": "решение: экспорт CSV", "markers": [r"csv", r"вторую волну|второй волн"]},
    {"id": 10, "category": "decision", "label": "решение: образ python:3.12-slim", "markers": [r"slim|3\.12"]},
    {"id": 11, "category": "task", "label": "задача: схема таблиц", "markers": [r"схем|schema|\bтаблиц|модель данных|data model|структур\w+ данных"]},
    {"id": 12, "category": "task", "label": "задача: CI GitHub Actions", "markers": [r"github|actions|\bci\b", r"workflow|pipeline|пайплайн"]},
    {"id": 13, "category": "task", "label": "задача: middleware авторизации", "markers": [r"middleware|мидлвар|проверк\w+ (?:cookie|куки)"]},
    {"id": 14, "category": "task", "label": "задача: тёмная тема", "markers": [r"тёмн|темн|dark|theming|теминг|токен\w*\s+тем|систем\w+\s+тем"]},
    {"id": 15, "category": "task", "label": "задача: индексы по дате", "markers": [r"индекс|index"]},
    {"id": 16, "category": "incidental", "label": "мимоходное: кот Персик", "markers": [r"персик|persik", r"кот\w*.*(?:клавиатур|keyboard)|(?:клавиатур|keyboard).*кот"]},
    {"id": 17, "category": "incidental", "label": "мимоходное: сериал про космос", "markers": [r"космос|space|космическ"]},
    {"id": 18, "category": "incidental", "label": "мимоходное: кофе из Эфиопии", "markers": [r"эфиоп|ethiop"]},
    {"id": 19, "category": "incidental", "label": "мимоходное: механическая клавиатура", "markers": [r"механическ\w+ клавиатур|keyboard|механическ"]},
    {"id": 20, "category": "incidental", "label": "мимоходное: модели самолётов", "markers": [r"самолёт|самолет|airplane|авиамодел"]},
]

QUESTIONS_V1 = [
    "Как меня зовут?",
    "Какая у меня профессия?",
    "Какой язык программирования я люблю?",
    "Какие инструменты или подходы я не люблю?",
    "Какая у меня цель по проекту?",
    "Какое хранилище мы выбрали для проекта?",
    "Что мы решили про хостинг и деплой?",
    "Как мы решили сделать авторизацию?",
    "Что мы решили про экспорт данных?",
    "Какой Docker-образ мы решили использовать для сборки?",
    "Что осталось сделать по схеме данных?",
    "Что осталось сделать по непрерывной интеграции?",
    "Что осталось сделать по авторизации?",
    "Что осталось сделать по оформлению интерфейса?",
    "Что осталось сделать для ускорения отчётов?",
    "Рассказывал ли я что-то про домашнего питомца? Если да, то что именно?",
    "Про что был сериал, который я недавно досмотрел?",
    "Откуда был кофе, который меня недавно удивил?",
    "Какую покупку для компьютера я недавно сделал?",
    "Чем я увлекался в детстве?",
]

QUESTIONS_V2 = [
    "Назови, пожалуйста, моё имя.",
    "Какая у меня специальность?",
    "Какой язык программирования мне нравится?",
    "Что мне не нравится в инструментах разработки?",
    "Какова моя цель по проекту?",
    "На каком хранилище мы остановились?",
    "Что мы решили насчёт выкладывания проекта в интернет?",
    "Как мы решили устроить вход в приложение?",
    "Что мы решили насчёт выгрузки данных?",
    "На какой базе мы решили собирать Docker-образ?",
    "Какая задача осталась по структуре базы?",
    "Какая задача осталась по автоматическим проверкам кода?",
    "Какая задача осталась по защите защищённых страниц?",
    "Какая задача осталась по внешнему виду приложения?",
    "Какая задача осталась для ускорения запросов к базе?",
    "Был ли у меня рассказ про домашнее животное? Если да, то какой?",
    "О чём был сериал, который я недавно посмотрел?",
    "Кофе из какой страны меня недавно удивил?",
    "Что я недавно купил для работы за компьютером?",
    "Чем я занимался в детстве?",
]

QUESTIONS_V3 = [
    "Моё имя — как меня зовут?",
    "Кем я работаю?",
    "Что из языков программирования мне по душе?",
    "Какие технологии меня раздражают?",
    "Какую цель я поставил по выпуску проекта?",
    "На чём мы решили хранить данные?",
    "Как планируем публиковать проект?",
    "Как устроим доступ к приложению?",
    "Что с экспортом данных?",
    "Что решили по базовому образу сборки?",
    "Что ещё не сделано по таблицам?",
    "Что ещё не сделано в пайплайне проверок?",
    "Что ещё не сделано для защиты страниц?",
    "Что ещё не сделано в оформлении?",
    "Что ещё не сделано для ускорения выборок?",
    "Какой питомец живёт у меня дома?",
    "О чём я смотрел сериал в последнее время?",
    "Из какой страны был кофе, который меня удивил?",
    "Чем я улучшил рабочее место?",
    "Что я собирал в детстве?",
]

QUESTION_SETS = {1: QUESTIONS_V1, 2: QUESTIONS_V2, 3: QUESTIONS_V3}

_ENCODER = None


def count_tokens(text: str) -> int:
    global _ENCODER
    if _ENCODER is None:
        try:
            import tiktoken

            _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENCODER = False
    if _ENCODER:
        return len(_ENCODER.encode(text))
    return max(1, round(len(text) / 3.5))


def info(name: str, detail: str = "") -> None:
    print(f"[ИНФО] {name}" + (f" — {detail}" if detail else ""))


def signal(name: str, detail: str = "") -> None:
    print(f"[СИГНАЛ] {name}" + (f" — {detail}" if detail else ""))


def clean_cli_output(text: str) -> str:
    lines = []
    for line in text.splitlines():
        clean = ANSI_RE.sub("", line).strip()
        if not clean or clean.startswith("> build"):
            continue
        lines.append(clean)
    return "\n".join(lines).strip()


def ask_llm(prompt: str, timeout: int = 600) -> str:
    cmd = [shutil.which("opencode") or "opencode", "run"]
    model = os.environ.get("MEMORY_LLM_MODEL")
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"opencode run failed: {proc.stderr.strip()}")
    return clean_cli_output(proc.stdout)


def last_history_messages(store: MemoryStore, count: int) -> str:
    import sqlite3

    with sqlite3.connect(store.db_path) as con:
        rows = con.execute(
            "SELECT role, content FROM history WHERE private = 0 ORDER BY id DESC LIMIT ?",
            (count,),
        ).fetchall()
    rows.reverse()
    return "\n".join(f"{role}: {content}" for role, content in rows)


def build_mode_contexts(store: MemoryStore) -> dict:
    history = full_history_text(store)
    memory = build_system_prompt(store)
    hybrid = memory + (
        f"\n\n# EXTENDED HISTORY (last {HYBRID_HISTORY} messages)\n"
        + last_history_messages(store, HYBRID_HISTORY)
    )
    return {
        "A": "# FULL CONVERSATION HISTORY\n" + history,
        "B": memory,
        "C": hybrid,
    }


def build_question_block(questions: list) -> str:
    lines = [
        "Ответь на вопросы, используя ТОЛЬКО информацию из предоставленного выше контекста.",
        'Если ответа в контексте нет — ответь ровно "не знаю", не выдумывай.',
        "Отвечай кратко, по-русски, формат: номер. ответ (одна строка на вопрос).",
        "ВОПРОСЫ:",
    ]
    for index, question in enumerate(questions, start=1):
        lines.append(f"{index}. {question}")
    return "\n".join(lines)


def parse_answers(text: str, count: int) -> dict:
    answers = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"^\s*(\d{1,2})\s*[.):]\s*(.*)$", line)
        if match and 1 <= int(match.group(1)) <= count:
            current = int(match.group(1))
            answers[current] = match.group(2).strip()
            continue
        if current is not None and line.strip():
            answers[current] += " " + line.strip()
    return answers


def evaluate(answers: dict) -> list:
    rows = []
    for fact in FACTS:
        answer = answers.get(fact["id"], "")
        if any(re.search(marker, answer, re.IGNORECASE) for marker in fact["markers"]):
            verdict = "correct"
        elif REFUSAL_RE.search(answer):
            verdict = "refusal"
        else:
            verdict = "incorrect"
        rows.append({"id": fact["id"], "category": fact["category"], "answer": answer, "verdict": verdict})
    return rows


def summarize(rows: list) -> dict:
    def tally(category=None):
        subset = [r for r in rows if category is None or r["category"] == category]
        return {
            "correct": sum(1 for r in subset if r["verdict"] == "correct"),
            "refusal": sum(1 for r in subset if r["verdict"] == "refusal"),
            "incorrect": sum(1 for r in subset if r["verdict"] == "incorrect"),
            "total": len(subset),
        }

    return {
        "all": tally(),
        "important": {
            "correct": tally("user")["correct"] + tally("decision")["correct"] + tally("task")["correct"],
            "refusal": tally("user")["refusal"] + tally("decision")["refusal"] + tally("task")["refusal"],
            "incorrect": tally("user")["incorrect"] + tally("decision")["incorrect"] + tally("task")["incorrect"],
            "total": 15,
        },
        "incidental": tally("incidental"),
    }


def run_pipeline(store: MemoryStore, provider) -> int:
    compressions = 0
    patch_log: list = []
    for role, content in DIALOGUE:
        store.append_message(role, content)
        result = maybe_compress(store, provider)
        if result:
            compressions += 1
            patch_log.append(
                {
                    "notes": result.get("notes"),
                    "tasks": result.get("tasks"),
                    "core": result.get("core"),
                }
            )
    log_path = store.base_dir / "compressions.jsonl"
    with log_path.open("w", encoding="utf-8") as f:
        for index, entry in enumerate(patch_log, start=1):
            entry["patch"] = index
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return compressions


def run_session(run_number: int) -> None:
    questions = QUESTION_SETS[run_number]
    print(f"\n===== RETENTION RUN {run_number} (вопросы, вариант {run_number}) =====")
    base = SANDBOX / f"run{run_number}"
    if base.exists():
        shutil.rmtree(base)
    store = MemoryStore(base, recent_limit=RECENT_LIMIT)
    provider = OpencodeCLIProvider()

    print(f"диалог: {len(DIALOGUE)} сообщений, сжатие реальной LLM...")
    compressions = run_pipeline(store, provider)
    info("сжатий выполнено", str(compressions))
    info("в ядре/задачах", f"goals={len(store.read_core()['goals'])}, tasks={len(store.read_tasks())}")

    contexts = build_mode_contexts(store)
    question_block = build_question_block(questions)
    results = {"run": run_number, "compressions": compressions, "modes": {}}

    for mode in ("A", "B", "C"):
        prompt = contexts[mode] + "\n\n" + question_block
        tokens = count_tokens(prompt)
        info(f"режим {mode}: запрос к LLM", f"{tokens} токенов (оценка), {len(prompt)} символов")
        raw = ask_llm(prompt)
        answers = parse_answers(raw, len(FACTS))
        if len(answers) < len(FACTS):
            signal(f"режим {mode}: распознано ответов", f"{len(answers)} из {len(FACTS)}")
        rows = evaluate(answers)
        summary = summarize(rows)
        results["modes"][mode] = {
            "tokens": tokens,
            "chars": len(prompt),
            "answers": {str(r["id"]): r["answer"] for r in rows},
            "verdicts": {str(r["id"]): r["verdict"] for r in rows},
            "summary": summary,
        }
        all_s = summary["all"]
        print(f"  режим {mode}: верно {all_s['correct']}/{all_s['total']}, "
              f"отказы {all_s['refusal']}, неверно {all_s['incorrect']}, "
              f"токенов {tokens}")

    results_path = SANDBOX / f"results_run{run_number}.json"
    results_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    info("результаты сохранены", str(results_path))


def report() -> None:
    files = sorted(SANDBOX.glob("results_run*.json"))
    if not files:
        print("нет результатов: сначала выполните --run 1|2|3")
        return
    runs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    for run_data in runs:
        for mode in ("A", "B", "C"):
            answers = {int(k): v for k, v in run_data["modes"][mode]["answers"].items()}
            rows = evaluate(answers)
            run_data["modes"][mode]["summary"] = summarize(rows)
            run_data["modes"][mode]["verdicts"] = {str(r["id"]): r["verdict"] for r in rows}

    print("\n===== ТОЧНОСТЬ (верно из 20) =====")
    print(f"{'прогон':>7} | {'A':>7} | {'B':>7} | {'C':>7}")
    totals = {"A": 0, "B": 0, "C": 0}
    for r in runs:
        row = [r["modes"][m]["summary"]["all"]["correct"] for m in ("A", "B", "C")]
        for m, v in zip(("A", "B", "C"), row):
            totals[m] += v
        print(f"{r['run']:>7} | {row[0]:>7} | {row[1]:>7} | {row[2]:>7}")
    n = len(runs)
    print(f"{'средн.':>7} | {totals['A']/n:>7.1f} | {totals['B']/n:>7.1f} | {totals['C']/n:>7.1f}")

    print("\n===== ПО СРЕЗАМ (важные 15 / мимоходные 5) =====")
    print(f"{'прогон':>7} | {'A важн':>6} | {'A мим':>6} | {'B важн':>6} | {'B мим':>6} | {'C важн':>6} | {'C мим':>6}")
    for r in runs:
        cells = []
        for m in ("A", "B", "C"):
            s = r["modes"][m]["summary"]
            cells.append(f"{s['important']['correct']:>6}")
            cells.append(f"{s['incidental']['correct']:>6}")
        print(f"{r['run']:>7} | " + " | ".join(cells))

    print("\n===== ОТКАЗЫ (из 20) =====")
    print(f"{'прогон':>7} | {'A':>7} | {'B':>7} | {'C':>7}")
    for r in runs:
        row = [r["modes"][m]["summary"]["all"]["refusal"] for m in ("A", "B", "C")]
        print(f"{r['run']:>7} | {row[0]:>7} | {row[1]:>7} | {row[2]:>7}")

    print("\n===== ГАЛЛЮЦИНАЦИИ/НЕВЕРНО (из 20) =====")
    print(f"{'прогон':>7} | {'A':>7} | {'B':>7} | {'C':>7}")
    for r in runs:
        row = [r["modes"][m]["summary"]["all"]["incorrect"] for m in ("A", "B", "C")]
        print(f"{r['run']:>7} | {row[0]:>7} | {row[1]:>7} | {row[2]:>7}")

    print("\n===== ТОКЕНЫ (оценка, вход) =====")
    print(f"{'прогон':>7} | {'A':>7} | {'B':>7} | {'C':>7}")
    for r in runs:
        row = [r["modes"][m]["tokens"] for m in ("A", "B", "C")]
        print(f"{r['run']:>7} | {row[0]:>7} | {row[1]:>7} | {row[2]:>7}")
    avg_a = sum(r["modes"]["A"]["tokens"] for r in runs) / n
    avg_b = sum(r["modes"]["B"]["tokens"] for r in runs) / n
    print(f"средн.: A={avg_a:.0f}, B={avg_b:.0f} ({100*avg_b/avg_a:.0f}% от A)")

    print("\n===== ДЕТАЛИ ПО ФАКТАМ (по прогонам) =====")
    for r in runs:
        print(f"\nпрогон {r['run']}:")
        for mode in ("A", "B", "C"):
            verdicts = r["modes"][mode]["verdicts"]
            lost = [f["label"] for f in FACTS if verdicts.get(str(f["id"])) != "correct"]
            if lost:
                print(f"  {mode}: неверно/отказ -> " + "; ".join(lost))


def main() -> int:
    parser = argparse.ArgumentParser(description="Retention-тест: A/B/C, 20 фактов")
    parser.add_argument("--run", type=int, choices=(1, 2, 3), help="номер прогона")
    parser.add_argument("--report", action="store_true", help="собрать отчёт по прогонам")
    args = parser.parse_args()
    if args.report:
        report()
        return 0
    if not args.run:
        parser.print_help()
        return 1
    run_session(args.run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
