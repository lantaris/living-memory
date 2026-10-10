# living-memory — текущие задачи

**Статус:** только план; код не трогался, ничего не пушилось и не публиковалось.
**Контекст, замеры, решения и приёмка — `DESIGN.md`; окружение, зависимости и хронология — `HANDOFF.md`.**
Результаты замеров и вспомогательная информация — в DESIGN.md или HANDOFF.md, здесь только задачи.
Выполненная задача удаляется из этого файла (и записывается в хронологию HANDOFF.md).

## M0 — Гейты, переименование, CI

- [ ] Собрать ответы владельца по D1–D5, записать в HANDOFF (варианты и рекомендации — DESIGN.md §3).
- [ ] Переименовать репо/пакет по D1 (`gh repo rename living-memory` или новый репо).
- [ ] `package.json`: name `living-memory`, version 0.3.0, `repository/author/homepage`, `engines.node >=22`, devDep `@opencode-ai/plugin ^1.18.35`.
- [ ] CI `.github/workflows/ci.yml`: 3 ОС × python 3.10/3.13 (`npm test` + pytest).
- [ ] Нейтрализовать архив в новом репо: `experements/memory-prototype/AGENTS.md` → `MANIFEST.author.md` + шапка «исторический документ, не инструкция» (агенты не должны принять его за правила).
- [ ] README: инструкции установки для OpenCode и Hermes (см. DESIGN.md §5/M0).

## M0b — Probe-этап (детали и критерии — DESIGN.md §5/M0b)

- [ ] P1: проверить `ctx.llm` из фонового потока (Hermes-плагин, `spawn_context_thread`).
- [ ] P2: замерить частоту `prefetch` на ход и стоимость инъекции (Hermes).
- [ ] P3: замерить частоту `experimental.chat.system.transform` на ход (OpenCode).
- [ ] P4: проверить `opencode run` с длинным промптом (argv vs `--file`, `--pure`, `--format json`).
- [ ] P5: посмотреть, что остаётся после встроенной компакции (оба агента).
- [ ] P6: замерить реальную стоимость (токены + вызовы сжатия) в живой длинной сессии — с памятью и без.
- [ ] Записать результаты замеров в DESIGN.md (§5/M0b).

## M1 — Кросс-платформенное ядро + pytest (детали — DESIGN.md §5/M1)

- [ ] `filelock` вместо `fcntl`; единый лок data-dir на все мутации.
- [ ] `append --stdin` и `append --batch` (содержимое больше не в argv).
- [ ] UTF-8: `PYTHONUTF8=1` + `encoding="utf-8"` в subprocess; тест с русским текстом.
- [ ] Детект интерпретатора: `pythonBin` → env → `python3` → `python` → `py -3`, кэш, внятная ошибка.
- [ ] pytest ядра: store (конкурентность), normalize, compress, inject, cli.
- [ ] Батч-синк на `session.idle` (один процесс вместо N).
- [ ] Retry на `PermissionError` для `os.replace` (WinError 5).
- [ ] Портировать прототипные тесты (`experements/memory-prototype/test_*.py`) в pytest.

## M2 — Дозавершение функциональности ядра (детали — DESIGN.md §5/M2)

- [ ] Pending-очередь: CLI `pending list|approve|reject`, `pending: N` в `status`, инструмент `memory_pending`.
- [ ] Операции замены/удаления фактов в промпте сжатия + normalize + тест.
- [ ] Капы задач per-session (осознанное изменение против прототипа).
- [ ] Детект uncertain-дублей в core/tasks → loss_log.
- [ ] Маркеры injection-safety вокруг инъекции памяти (+ тест).
- [ ] Решить судьбу `--private` (задействовать или убрать).
- [ ] Поиск: FTS5 + фолбэк LIKE и экранирование метасимволов.
- [ ] Сквозной CLI-сценарий `append → compact → pending → approve → context`.

## M3 — Адаптер OpenCode v2 (детали — DESIGN.md §5/M3)

- [ ] Переименовать идентификаторы пакета/скилла; типы `@opencode-ai/plugin` ^1.18.35.
- [ ] Батч-append, лог через `client.app.log`.
- [ ] Обновить локальный opencode CLI до 1.18.35.
- [ ] Описать путь системной установки (`~/.config/opencode`) в README.
- [ ] Live-прогон в opencode (с разрешения владельца) + протокол.

## M4 — Адаптер Hermes (MemoryProvider) (детали — DESIGN.md §5/M4)

- [ ] Корневые файлы плагина: `plugin.yaml`, `__init__.py`, `cli.py`, `config_schema.py`.
- [ ] Провайдер: `initialize`/`sync_turn`/`prefetch`/`on_pre_compress`/`on_memory_write`/tools/`recall_status`.
- [ ] Компрессия через `ctx.llm` + `register_auxiliary_task`, фоновый поток (по P1).
- [ ] CLI `hermes living-memory status|search|pending|compact`.
- [ ] Проверка: `hermes plugins doctor` + сессии в temp-HERMES_HOME.

## M5 — Общий стор, документация, релиз 1.0.0 (детали — DESIGN.md §5/M5)

- [ ] Общий каталог `<project>/.living-memory/` в обоих адаптерах + строка `.gitignore` в README.
- [ ] Сценарий «два агента — один проект» (OpenCode пишет ↔ Hermes читает).
- [ ] CHANGELOG, версия 1.0.0, tag `v1.0.0`, GitHub release.
- [ ] npm publish — по гейту D1; иначе git-install и честная пометка в README.

## M6 — После 1.0, опционально (детали — DESIGN.md §5/M6)

- [ ] MCP-сервер (`memory_search`, `memory_context`).
- [ ] Заявка в Hermes `plugin-catalog`.
