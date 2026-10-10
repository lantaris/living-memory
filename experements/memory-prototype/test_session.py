from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from compress import flush, maybe_compress
from inject import build_system_prompt
from llm import MockProvider, OpencodeCLIProvider
from store import MemoryStore

BASE = Path(__file__).parent
SANDBOX = BASE / "sandbox"
RECENT_LIMIT = 10
MOBILE_MARKERS = ("мобильное", "mobile")

FLUSH_WAVE_1 = [
    ("user", "Продолжаем трекер расходов."),
    ("assistant", "Хорошо, на чём остановились?"),
    ("user", "Обсуждали схему таблиц."),
    ("assistant", "Да, expenses и categories — рабочая схема."),
    ("user", "Ок."),
    ("assistant", "Если что, спрашивай."),
    ("user", "Напомни, мы что-то решили по экспорту?"),
    ("assistant", "Решили: CSV позже, после базовой схемы."),
    ("user", "Ладно, продолжаем."),
    ("assistant", "Давай."),
]

FLUSH_WAVE_2 = [
    ("user", "Моя цель — выпустить MVP за два месяца."),
    ("assistant", "Записал: MVP за два месяца, постараемся."),
    ("user", "Тема: деплой. Решили: Docker + Fly.io."),
]

LOSS_WAVE_1 = [
    ("user", "Меня зовут Иван."),
    ("assistant", "Привет, Иван! Чем займёмся?"),
    ("user", "Тема: хранилище. Решили: беру SQLite."),
    ("assistant", "Хороший выбор для одного пользователя."),
    ("user", "Кстати, вчера смотрел новый сериал — затягивает."),
    ("assistant", "Бывает :) Вернёмся к схеме таблиц?"),
    ("user", "Да. Осталось: миграции и индексы."),
    ("assistant", "Сделаем schema_version и SQL-файлы."),
    ("user", "Спасибо, погнали дальше."),
    ("assistant", "Дай знать, если будут вопросы."),
]

LOSS_WAVE_2 = [
    ("user", "Ещё вопрос про иконки категорий."),
    ("assistant", "Можно emoji или статические SVG."),
    ("user", "Ок, выберу позже."),
    ("assistant", "Договорились."),
    ("user", "Спасибо!"),
]

PENDING_DIALOGUE = [
    ("user", "Продолжаем трекер расходов."),
    ("assistant", "Хорошо."),
    ("user", "Схема таблиц согласована."),
    ("assistant", "Отлично."),
    ("user", "Осталось доделать миграции."),
    ("assistant", "Сделаем."),
    ("user", "И подумать про графики."),
    ("assistant", "Позже обсудим."),
    ("user", "Ладно."),
    ("assistant", "Дальше?"),
    ("user", "Возможно, добавлю экспорт в PDF — пока не уверен."),
    ("assistant", "Понял, вернёмся к этому позже."),
    ("user", "Что там по вёрстке?"),
    ("assistant", "Проверим после главного."),
    ("user", "Наверное, выпущу мобильное приложение позже."),
    ("assistant", "Хорошо, зафиксировал на потом."),
    ("user", "Обсудим графики на следующей неделе."),
    ("assistant", "Договорились."),
    ("user", "Спасибо!"),
    ("assistant", "На связи."),
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


def has_mobile(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in MOBILE_MARKERS)


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


def test_flush(provider, is_mock: bool) -> None:
    print("\n===== ТЕСТ 1: FLUSH НА ГРАНИЦЕ СЕССИИ =====")
    store = fresh_store("session_flush")
    log: list = []
    feed(store, provider, FLUSH_WAVE_1, log)
    feed(store, provider, FLUSH_WAVE_2, log)

    goals_before = json_dump(store.read_core()["goals"])
    recent_before = len(store.read_recent())
    info("до flush: goals", goals_before or "[]")
    info("до flush: сообщений в оперативке", str(recent_before))
    hard("Факт из хвоста ещё не в ядре", "MVP" not in goals_before)

    result = flush(store, provider)
    hard("Flush выполнил сжатие", result is not None)
    if result and result.get("notes"):
        info("flush notes", result["notes"])

    core = store.read_core()
    goals = json_dump(core["goals"])
    tasks = json_dump(store.read_tasks())
    hard("После flush: цель MVP в ядре", "MVP" in goals, goals)
    hard("После flush: тема деплоя в задачах", "Fly.io" in tasks or "деплой" in tasks.lower())
    hard("После flush: оперативка пуста", len(store.read_recent()) == 0)

    session2 = MemoryStore(store.base_dir, recent_limit=RECENT_LIMIT)
    prompt = build_system_prompt(session2)
    hard("Новая сессия: MVP доступен через ядро (не только поиск)", "MVP" in prompt)
    hard("Новая сессия: деплой доступен через задачи", "Fly.io" in prompt)
    hard("Новая сессия: оперативка пуста", len(session2.read_recent()) == 0)
    info("проверка обратимости", f"search('MVP') находит записей: {len(session2.search('MVP'))}")


def test_loss_log(provider, is_mock: bool) -> None:
    print("\n===== ТЕСТ 2: ЖУРНАЛ ПОТЕРЬ =====")
    store = fresh_store("session_loss")
    log: list = []
    feed(store, provider, LOSS_WAVE_1, log)
    feed(store, provider, LOSS_WAVE_2, log)
    info("сжатий выполнено", str(len(log)))

    losses = store.read_loss_log()
    lost_texts = [r["text"] for r in losses]
    print("журнал потерь:")
    for record in losses:
        print(f"  - [{record['role']}] {record['text']}  (reason: {record['reason']}, indexed: {record['indexed']})")
    for i, result in enumerate(log, start=1):
        info(f"патч {i}: used", str(result.get("used")))

    expected = {LOSS_WAVE_1[4][1], LOSS_WAVE_1[8][1]}
    if is_mock:
        hard("Журнал содержит ровно потерянные сообщения",
             set(lost_texts) == expected,
             f"ожидалось {len(expected)}, получено {len(lost_texts)}")
    else:
        expired_user = [
            content for role, content in LOSS_WAVE_1 if role == "user"
        ]
        subset = set(lost_texts) <= set(expired_user)
        hard("Все записи журнала — вытесненные реплики пользователя", subset)
        if set(lost_texts) != expected:
            signal("Состав журнала отличается от мок-ожидания",
                   f"записей: {len(lost_texts)}; проверь, что модель пометила в used")

    hard("Все потери помечены как доступные через индекс",
         all(r["indexed"] for r in losses))
    for text in lost_texts:
        keyword = "сериал" if "сериал" in text else ("погнали" if "погнали" in text else text[:8])
        hard(f"Потерянный факт возвращается из index.db ({keyword})",
             bool(store.search(keyword)))
    if is_mock:
        used_messages = [LOSS_WAVE_1[0][1], LOSS_WAVE_1[2][1], LOSS_WAVE_1[6][1]]
        hard("Использованные сообщения не попали в журнал",
             all(m not in lost_texts for m in used_messages))


def test_pending(provider, is_mock: bool) -> None:
    print("\n===== ТЕСТ 3: ЗАПРОС ПОМОЩИ (UNCERTAIN -> PENDING) =====")
    store = fresh_store("session_pending")
    log: list = []
    feed(store, provider, PENDING_DIALOGUE, log)
    info("сжатий выполнено", str(len(log)))

    pending = store.read_pending()
    print("очередь подтверждения:")
    for record in pending:
        print(f"  #{record['id']} [{record['kind']}] {record['text']} ({record['status']})")

    memory = memory_text(store)
    if not pending:
        signal("Сжатие не вернуло неуверенных фактов",
               "модель была уверена во всех фактах — очередь пуста")
        return

    hard("Неуверенный факт в очереди (не потерян)",
         any("PDF" in r["text"] for r in pending))
    if "PDF" in memory:
        if is_mock:
            hard("Мок не дублирует неуверенный факт в конспект", False,
                 "PDF найден в ядре/задачах")
        else:
            signal("Модель продублировала неуверенный факт в конспект",
                   "вопреки правилу never duplicate uncertain in core/tasks")
    else:
        info("Неуверенный факт не продублирован в ядро/задачи")

    mobile_in_pending = any(has_mobile(r["text"]) for r in pending)
    if is_mock:
        hard("Мобильная цель в очереди", mobile_in_pending)
    elif not mobile_in_pending:
        signal("Модель не пометила мобильную цель как неуверенную",
               "reject-механика проверена только на моке")
    if is_mock:
        hard("Мобильная цель не в ядре/задачах молча", not has_mobile(memory))
    elif has_mobile(memory):
        signal("Мобильная цель продублирована в конспект",
               "модель положила uncertain-факт и в pending, и в core/tasks")

    pdf_id = next((r["id"] for r in pending if "PDF" in r["text"]), None)
    mobile_record = next((r for r in pending if has_mobile(r["text"])), None)

    if pdf_id is not None:
        resolved = store.resolve_pending(pdf_id, approve=True)
        applied = "PDF" in json_dump(store.read_core()) or "PDF" in json_dump(store.read_tasks())
        hard("Подтверждение применено (PDF записан в слой)",
             resolved is not None and resolved["status"] == "approved" and applied)
        if resolved:
            info("запись PDF применена", f"kind={resolved.get('kind')}")
    if mobile_record is not None:
        memory_before_resolve = json_dump(store.read_core()) + json_dump(store.read_tasks())
        resolved = store.resolve_pending(mobile_record["id"], approve=False)
        final = store.read_pending()
        mobile_final = next(r for r in final if r["id"] == mobile_record["id"])
        hard("Отклонение зафиксировано (статус rejected)",
             resolved is not None and mobile_final["status"] == "rejected")
        hard("Отклонённый факт не удалён из очереди (не потерян)",
             has_mobile(mobile_final["text"]))
        memory_after = json_dump(store.read_core()) + json_dump(store.read_tasks())
        hard("Отклонение не изменило конспект", memory_after == memory_before_resolve)
        if has_mobile(memory_after) and is_mock:
            hard("Отклонённый факт не в конспекте", False,
                 "мок положил факт и в конспект, и в очередь")

    losses = json_dump(store.read_loss_log())
    if is_mock:
        hard("Неуверенные факты не попали в журнал потерь",
             "PDF" not in losses and "мобильное" not in losses)
    elif "PDF" in losses:
        signal("Модель сочла PDF-факт отброшенным, а не неуверенным",
               "журнал потерь содержит PDF")


def build_provider(name: str):
    if name == "opencode":
        return OpencodeCLIProvider()
    return MockProvider()


def main() -> int:
    parser = argparse.ArgumentParser(description="Тесты готовности к сессиям агента")
    parser.add_argument(
        "--provider",
        choices=("mock", "opencode"),
        default=os.environ.get("MEMORY_LLM_PROVIDER", "mock"),
    )
    parser.add_argument(
        "--tests",
        choices=("1", "2", "3", "all"),
        default="all",
        help="какой тест запускать",
    )
    args = parser.parse_args()
    provider = build_provider(args.provider)
    is_mock = args.provider == "mock"

    print(f"Провайдер: {args.provider} ({type(provider).__name__})")
    if args.tests in ("1", "all"):
        test_flush(provider, is_mock)
    if args.tests in ("2", "all"):
        test_loss_log(provider, is_mock)
    if args.tests in ("3", "all"):
        test_pending(provider, is_mock)

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
