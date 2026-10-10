# Changelog

## 1.0.0 — 2026-10-10

Первый релиз living-memory: слоистая «живая» память для кодинг-агентов —
OpenCode (TS-плагин) и Hermes (MemoryProvider-плагин) поверх одного движка.

**Память**
- Слои: ядро (факты о пользователе), задачи (по сессиям), хвост последних
  сообщений по сессиям, полный индекс истории (SQLite FTS5), журнал потерь,
  очередь подтверждения.
- Сжатие диалога LLM в конспект с нормализацией ответа (лимиты, дедуп, капы
  задач per-session), операция `forget` для отзыва устаревших фактов
  (журналируется: `forgotten:core.*`).
- Инструменты агента: `memory_search` (FTS5, LIKE-фолбэк), `memory_pending`
  (list/approve/reject); CLI `pending add|list|approve|reject`.
- Маркеры injection-safety `[living-memory:begin/end]`; детект uncertain-дублей;
  пер-сессионные хвосты и изоляция subagent-сессий.

**Платформы**
- OpenCode: плагин (`chat.message`, `event`, `system.transform`,
  `session.compacting`, инструменты); синхронные батч-записи; живой прогон на
  1.18.31: запись → сжатие через `opencode run --pure --format json` → инъекция
  (доказана на новой сессии) → `memory_search`.
- Hermes: MemoryProvider-плагин (prefetch раз на турн, `sync_turn`,
  `on_pre_compress`, `on_memory_write` → очередь, read-only скилл); сжатие —
  хостовой моделью (`ctx.llm`, двухфазно `compact-prepare`/`compact-apply`);
  живой прогон в изолированном HERMES_HOME.
- Общий каталог проекта `<project>/.living-memory/` — одна память на оба
  агента (сценарий «OpenCode пишет → Hermes читает» проверен вживую).

**Надёжность**
- Без внешних зависимостей (stdlib); замок — SQLite `BEGIN IMMEDIATE`
  (+ `_ensure_wal` с ретраями); ретраи `os.replace` на Windows; UTF-8 везде;
  автоопределение интерпретатора; убийство дерева процессов по таймауту.
- Тесты: 16 node + 24 python (портированные прототипные сценарии,
  конкурентность, контракты CLI, семантика сжатия).

**Известные ограничения**: см. README «Честные ограничения». Публикация в npm и
публичный репозиторий — по решению владельца; пока установка — из каталога проекта.
