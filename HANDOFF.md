# HANDOFF — living-memory

Правила файла: верхняя часть — справочная (обновляется по мере необходимости), нижняя — хронология (только дописывание в конец, записи не редактируются). Задачи — в `PLAN.md`.

---

## Справочная часть

### Что это

`living-memory` — планируемый продукт: один Python-движок слоистой «живой» памяти (core / задачи / хвост сессии / индекс полной истории / журнал потерь / очередь «на подтверждение») + два адаптера: TS-плагин OpenCode и MemoryProvider-плагин Hermes. Родословная — `opencode-memory` v0.2.0 (аудит-клон в `D:\WRK\opencode-memory`, не трогать). Задачи — `PLAN.md`, контекст/замеры/решения/приёмка — `DESIGN.md` в этом каталоге.

### Окружение (проверено 2026-10-10)

| Что | Значение |
|---|---|
| Каталог плана/проекта | `D:\WRK\living-memory` (не git-репо; не инициализировать, пока не попросят) |
| Аудит-клон исходника | `D:\WRK\opencode-memory` (HEAD c9c35e2, чистый; READ-ONLY) |
| Hermes (git-install) | `C:\Users\user\AppData\Local\hermes\hermes-agent` (+ venv; `venv\Scripts\hermes.exe`) |
| HERMES_HOME | `C:\Users\user\AppData\Local\hermes` (активный профиль default) |
| opencode | 1.18.31 (`C:\Users\user\AppData\Roaming\npm\opencode`); в npm актуальный 1.18.35 |
| Интерпретаторы | `python` = 3.14.7 (Hermes tools, в PATH), `py -3` = 3.12.7; `python3` = заглушка Microsoft Store |
| node / npm | 26.7.0 / 11.19.0 |
| gh | залогинен как `lantaris` (scopes: repo, gist, read:org) |
| npm | **не залогинен** — публикация невозможна до аккаунта владельца |
| Временный каталог | `$TMPDIR` в bash = `C:\Users\user\AppData\Local\Temp` (НЕ hermes scratch, как могло казаться) |

### Контракты хостов — где лежит истина

Hermes (локальный исходник — самый свежий источник):

- `...\hermes-agent\agent\memory_provider.py` — **ABC MemoryProvider** (read: name, is_available, initialize, system_prompt_block, prefetch, queue_prefetch, recall_status, sync_turn, get_tool_schemas, handle_tool_call, shutdown, on_turn_start, on_session_end, on_session_switch, on_pre_compress, on_delegation, get_config_schema, save_config, on_memory_write, backup_paths; helper'ы `spawn_context_thread`/`ctx_bound`).
- `...\hermes-agent\website\docs\developer-guide\memory-provider-plugin.md` — контракт, discovery (`$HERMES_HOME/plugins/<name>/`), single-provider, checkpoint API v2 (`compression.checkpoint_required`), threading-требования.
- `...\website\docs\developer-guide\plugins\index.md` — общий контракт плагинов: register(ctx), hooks (`pre_llm_call` с инъекцией в user message, pre/post_tool_call, on_session_*…), `ctx.register_tool/command/cli_command/skill`, manifest v2, Plugin Doctor, capabilities, «спиллинг» больших выводов хуков.
- `...\website\docs\developer-guide\plugin-llm-access.md` — `ctx.llm.complete/complete_structured` (host-owned credentials), `ctx.register_auxiliary_task(name, inherit_from="compression")`, trust gate (provider/model overrides denied by default).
- `...\hermes-agent\plugins\AGENTS.md` — политика: «Plugins never touch core», сторонние провайдеры не берут в core, каталог плагинов = единственный канал out-of-tree, пин SHA.
- `...\hermes-agent\plugins\memory\holographic\` — живой пример bundled MemoryProvider (plugin.yaml + __init__.py).
- CLI: `hermes memory setup|status|off|reset`; `hermes plugins install|validate|doctor|list|enable|…`.
- Факты из кода: `PluginContext.llm` — ленивый `PluginLlm` (plugins.py:377); `register_memory_provider` — инертный для общего менеджера (plugins.py:723), активация только через `memory.provider`; `memory_search` как имя инструмента в Hermes не занято.

OpenCode:

- `https://opencode.ai/docs/plugins/` — загрузка плагинов (npm через bun → `~/.cache/opencode/node_modules`; scoped-имена ок; локальные файлы `.opencode/plugins/`, `~/.config/opencode/plugins/`), события, `tool()`.
- `https://opencode.ai/docs/skills/` — `.opencode/skills/<name>/SKILL.md` (+ `~/.config/opencode/skills/`, `.claude/`, `.agents/`), frontmatter `name`/`description`, `metadata`: `opencode/slash`, `opencode/autoinvoke`.
- Типы `@opencode-ai/plugin@1.18.35` (получены `npm pack opencode-ai-plugin-1.18.35.tgz`, `dist/index.d.ts`): Hooks — `dispose`, `event`, `config`, `tool`, `auth`, `provider`, `chat.message`, `chat.params`, `chat.headers`, `permission.ask`, `command.execute.before`, `tool.execute.before/after`, `shell.env`, `experimental.chat.messages.transform`, `experimental.chat.system.transform` (output `{system: string[]}`), `experimental.provider.small_model`, `experimental.session.compacting` (output `{context: string[], prompt?}`), `experimental.compaction.autocontinue`.
- `opencode run` — неинтерактивный режим: позиционный message, `-m provider/model`, `--pure` (без внешних плагинов), `-f/--file` (вложения), `--format json`, `--dir`, `--title`, `--attach`.

### Прототип и эксперименты (`experements/memory-prototype`, долив 2026-10-10)

- Что там: манифест Автора (`AGENTS.md` — как получен), `SPECIFICATION.md` (форматы/политики/алгоритмы), `NOTES.md` §1–§14 (протоколы решений и экспериментов), код прототипа, `sandbox/` (артефакты прогонов), 7 тестовых скриптов (plain-assert, без unittest). `store.py` побайтово идентичен пакетному `python/store.py` (diff пуст).
- Статус материала (слово владельца, 2026-10-10): это **анализ прошлой работы, а не правила и не ограничения** для living-memory; манифест Автора — исторический документ. При переносе в новый репо `AGENTS.md` архива переименовать, чтобы агенты не приняли его за инструкции.
- Карта NOTES: §6 потеря/конфликт фактов, §8 flush / журнал потерь / смена модели / pending, §9 retention v1 (стоимость 95% от истории), §10 нормализация (67%, паритет на важных фактах, калибровка метрик), §11 упаковка плагина, §12 `memory_search` + скилл, §13 git и системная установка, §14 мультисессионность + инциденты.
- Наши прогоны (заглушка `fcntl`, python 3.14, mock): `test_scenario` 24/24 ✅, `test_session` ✅, `test_loss_conflict` ✅, `test_model_swap --modes A` ✅, `test_normalization --tests unit` ✅; `test_multi_session` — 3 падения: гонка `os.replace` (`WinError 5`) — Windows-баг движка, не теста (лечится в M1: retry + filelock).
- `*.mystery-0706.bak` (compress/inject/test_scenario) — сторонние подмены 07:05–07:06 неизвестного происхождения: монолитная версия идеи (всё в одном `compress.py`, без store/normalize/llm). НЕ интегрировать без слова владельца.
- Инциденты в истории репо: runtime-данные попадали в git дважды (`628f3b9` и ранний `.demo/`) — в living-memory `.gitignore` с первого коммита.
- Проверенный путь системной установки OpenCode (NOTES §13.2): `~/.config/opencode` — родной npm-проект плагинов; `npm install github:lantaris/opencode-memory` там + относительный путь в глобальном `opencode.jsonc` (для living-memory — аналогично).
- Наблюдение (§11.3): OpenCode переинициализирует плагин после хода (повторный `ready` в том же pid); дубли гасит прайм-синхронизация по messageID (уже в коде).

### Зависимости (проверено в регистрах, не в прозе)

- `filelock` 4.1.0, MIT, py≥3.10, zero-dep — выбран для кросс-платформенного лока (замена `fcntl`). Пин: `>=3.13,<5`.
- `portalocker` 4.4.0, BSD-3 — запасная альтернатива.
- npm: `opencode-memory` — ЗАНЯТО чужим пакетом (tomako, github.com/shuans/opencode-memory, v2.0.1). `living-memory` — свободно. GitHub `lantaris/living-memory` — свободно. `@lantaris/opencode-memory` — свободно (для scoped-варианта).
- `@opencode-ai/plugin` — текущий 1.18.35; локальный CLI 1.18.31 (обновить для live-тестов).

### Грабли этой машины/сессии

- `web_extract` на этом хосте не работает (ddgs — только поиск); веб — через `mcp__duckduckgo__fetch_content`/`search`.
- `$TMPDIR` в bash указывает на `C:\Users\user\AppData\Local\Temp`, а не на hermes scratch; не путать при копировании/скидывании файлов.
- `which python3` находит заглушку Microsoft Store, но она НЕ запускает python (exit 9009 при spawn) — движку нужен `python`/`py -3`.
- Тесты opencode-memory на этой машине «как есть»: 7/13 (6 падений из-за отсутствия рабочего `python3`), 13/13 с тестовой заглушкой `fcntl` — доказано, что ломает платформа, не логика.
- `write_file` не перезаписывает файл, который был прочитан постранично; план писать чанками через маркер + `patch`.

### Открытые решения (гейты)

См. `DESIGN.md` §3: D1 (имя/публикация), D2 (общий или раздельный каталог памяти), D3 (каталог плагинов Hermes), D4 (объём 1.0 без MCP), D5 (язык README). Ответы владельца после закрытия — дописать под этим разделом.

---

## Хронология

- **2026-10-10** — Аудит `opencode-memory` (клон, только чтение): сильные стороны — сквозная деградация без падения агента, аккуратная конкурентность (flock + атомарные записи + сжатие LLM вне блокировки, применение под блокировкой с перечиткой, удаление из хвоста по id), нормализация ответов LLM отдельным слоем, журнал потерь + полный индекс, пер-сессионная изоляция. Дефекты: имя на npm занято чужим пакетом (README-инструкция ставит чужой код); Windows структурно сломан (`fcntl` + `python3`; 7/13 тестов); очередь `pending.jsonl` без потребителя (`resolve_pending` не вызывается ниоткуда); ядро Python без тестов в репо; мёртвые `full_history_text`/`get_default_provider`; argv-транспорт и локальные кодировки как мины портативности; в публичной истории git остались runtime-данные из коммита 628f3b9. Отчёт по аудиту — в чате от 2026-10-10.
- **2026-10-10** — Исследование хостов и написание плана. Проверено: ABC MemoryProvider и контракты Hermes (локальный исходник git-инсталляции), `ctx.llm` и aux-задачи, типы OpenCode 1.18.35 (npm pack), `opencode run --help`, доступность имён npm/GitHub, лицензии filelock/portalocker, отсутствие коллизии `memory_search` в Hermes. Создан каталог `D:\WRK\living-memory`; написан `PLAN.md` (гейты D1–D5, probe-этап M0b, милстоуны M0–M6, приёмка, риски). Код не трогался; исходный репо и аудит-клон не изменялись.
- **2026-10-10** — Владелец долил в репо `experements/memory-prototype/` (коммит 7e31288). Разобрано и проверено: `store.py` идентичен пакетному; mock-тесты прототипа на нашем стенде (заглушка `fcntl`, python 3.14) — scenario 24/24, session, loss_conflict, model_swap A, normalization unit зелёные; `test_multi_session` вскрыл Windows-баг движка (`os.replace` → `WinError 5` под конкуренцией). NOTES §9–§10 закрывают вопрос «конспект vs полная история» числами (67% стоимости, паритет на важных фактах). План обновлён: M1 + порт прототипных тестов и retry для `os.replace`; M2 + постобработка uncertain-дублей; M3 + проверенный путь системной установки; §6 + два риска; §5 + пункт приёмки; в справочной части — раздел о прототипе.
- **2026-10-10** — `PLAN.md` приведён к правилам проекта (только актуальные задачи, чек-лист с краткими описаниями); контекст, замеры, решения-гейты, детали этапов, приёмка и риски вынесены в новый `DESIGN.md`; указатели в HANDOFF обновлены.
- **2026-10-10** — Зафиксировано владельцем: файлы репозитория `opencode-memory` (включая `experements/`, манифест Автора) — только материал анализа, не правила и не ограничения; продукт делаем релизного уровня для реальной работы с агентами. Внесено: DESIGN (предупреждение после контрактов, «Уровень» в шапке, первый принцип в §4, FTS5 в §5/M2), PLAN (M0 — нейтрализация архива; M2 — FTS5), HANDOFF (статус материала).
- **2026-10-10** — По вопросу владельца о токенах сверены протоколы прототипа (test_retention.py: измерялся размер запроса к модели-ответчику на конце 104-сообщений, tiktoken; стоимость самих сжатий не учтена). В план добавлен probe P6 — замер реальной стоимости в живой сессии (с памятью и без).
