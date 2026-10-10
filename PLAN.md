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
- [ ] P5: живой прогон встроенной компакции (TUI/длинный диалог; CLI-путь не существует).
- [ ] P6: замер стоимости на длинном диалоге «с памятью vs без» (токены доступны через `--format json`).
- [ ] Записать результаты замеров в DESIGN.md (§5/M0b).

## M3 — Адаптер OpenCode v2 (детали — DESIGN.md §5/M3)

- [ ] Решить с версией CLI: локальный opencode 1.18.31 при типах ^1.18.35 (апгрейд или пин типов на 1.18.31).
- [ ] README: описать системный путь установки (`~/.config/opencode` — npm-проект плагинов) и проверить его руками.

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
