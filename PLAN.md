# living-memory — текущие задачи

**Статус:** в работе; M0 (локально) и M1 выполнены — см. хронологию HANDOFF. Ничего не пушилось и не публиковалось.
**Контекст, замеры, решения и приёмка — `DESIGN.md`; окружение, зависимости и хронология — `HANDOFF.md`.**
Результаты замеров и вспомогательная информация — в DESIGN.md или HANDOFF.md, здесь только задачи.
Выполненная задача удаляется из этого файла (и записывается в хронологию HANDOFF.md).

## M0 — Гейты, переименование, CI (остаток)

- [ ] (ждёт команды владельца) GitHub: репо `lantaris/living-memory` (переименовать существующий или создать новый), запушить, включить CI и добиться зелёного прогона; затем `repository`/`homepage` в `package.json`.
- [ ] README: раздел установки Hermes — вместе с адаптером (M4); финальная сверка всех инструкций — M5.

## M0b — Probe-этап (детали и критерии — DESIGN.md §5/M0b)

- [ ] P1: проверить `ctx.llm` из фонового потока (Hermes-плагин, `spawn_context_thread`).
- [ ] P2: замерить частоту `prefetch` на ход и стоимость инъекции (Hermes).
- [ ] P3: замерить частоту `experimental.chat.system.transform` на ход (OpenCode).
- [ ] P4: проверить `opencode run` с длинным промптом (argv vs `--file`, `--pure`, `--format json`).
- [ ] P5: посмотреть, что остаётся после встроенной компакции (оба агента).
- [ ] P6: замерить реальную стоимость (токены + вызовы сжатия) в живой длинной сессии — с памятью и без.
- [ ] Записать результаты замеров в DESIGN.md (§5/M0b).

## Фиксы после аудита (2026-10-10, 2 независимых аудитора)

- [ ] F1: `src/bridge.ts` при exit≠0 теряет текст ошибки CLI (тот печатает error-JSON в stdout) — при неуспехе вытаскивать error-JSON из последней строки stdout, stderr как fallback; тест.
- [ ] F2: `append --batch`: сбой на элементе k оставляет первые k−1 сообщений в хвосте (файловые записи не в транзакции) — единый контракт: битые элементы пропускать (как в store) или откатывать батч; тест.
- [ ] F3: `_ensure_defaults` — TOCTOU на свежем каталоге (создание файлов без лока) — под лок или атомарное «создать-если-нет»; тест двух процессов.
- [ ] F4: `append --stdin` с пустым вводом пишет пустое сообщение (в batch пустые отбрасываются) — симметрия + тест.
- [ ] F5: `read_recent` — битая строка JSONL роняет `status`/`context` целиком → пропускать с записью в лог; тест.
- [ ] F6: таймаут моста не убивает процесс-внук (`opencode run`) — убивать дерево (Windows: `taskkill /T`); проверить live в M3.
- [ ] F7: `_safe_session_name` — коллизии id («a b» vs «a/b» → один файл) → хэш-суффикс; тест.
- [ ] F8: чистка: мёртвые `history_count`/`get_default_provider`/ветка `_index(con=None)`; tmp в `_atomic_write` при не-PermissionError; решение по молчаливой перезаписи SKILL.md.
- [ ] Н6: `@opencode-ai/sdk` (только типы) объявить devDependency явно.

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

- [ ] Верифицировать переименование (grep `opencode-memory` в активном дереве пуст — сделано в M0/M1) и актуальность типов `@opencode-ai/plugin` ^1.18.35.
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
