# HANDOFF — living-memory

Правила файла: верхняя часть — справочная (обновляется по мере необходимости), нижняя — хронология (только дописывание в конец, записи не редактируются). Задачи — в `PLAN.md`.

---

## Справочная часть

### Что это

`living-memory` — планируемый продукт: один Python-движок слоистой «живой» памяти (core / задачи / хвост сессии / индекс полной истории / журнал потерь / очередь «на подтверждение») + два адаптера: TS-плагин OpenCode и MemoryProvider-плагин Hermes. Родословная — `opencode-memory` v0.2.0 (аудит-клон в `D:\WRK\opencode-memory`, не трогать). Задачи — `PLAN.md`, контекст/замеры/решения/приёмка — `DESIGN.md` в этом каталоге.

### Окружение (проверено 2026-10-10)

| Что | Значение |
|---|---|
| Рабочее дерево продукта | `D:\WRK\living-memory` — локальный git-репо (коммиты `9df86c9` M0, `3c8aa34` M1, `1aa9382` доки; будет ещё «фиксы после аудита»); remote не настроен — GitHub по решению владельца пока не трогаем |
| Аудит-клон исходника | `D:\WRK\opencode-memory` (HEAD 7e31288, чистый; READ-ONLY) |
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

- Что там: манифест Автора (`MANIFEST.author.md`; в доливе был `AGENTS.md`, переименован при M0), `SPECIFICATION.md` (форматы/политики/алгоритмы), `NOTES.md` §1–§14 (протоколы решений и экспериментов), код прототипа, `sandbox/` (артефакты прогонов), 7 тестовых скриптов (plain-assert, без unittest). `store.py` был побайтово идентичен пакетному на момент долива (после M1 движок изменён — SQLite-мьютекс).
- Статус материала (слово владельца, 2026-10-10): это **анализ прошлой работы, а не правила и не ограничения** для living-memory; манифест Автора — исторический документ. Манифест переименован в `MANIFEST.author.md` (M0, коммит `9df86c9`) — при переносе повторять не нужно.
- Карта NOTES: §6 потеря/конфликт фактов, §8 flush / журнал потерь / смена модели / pending, §9 retention v1 (стоимость 95% от истории), §10 нормализация (67%, паритет на важных фактах, калибровка метрик), §11 упаковка плагина, §12 `memory_search` + скилл, §13 git и системная установка, §14 мультисессионность + инциденты.
- Наши прогоны (заглушка `fcntl`, python 3.14, mock): `test_scenario` 24/24 ✅, `test_session` ✅, `test_loss_conflict` ✅, `test_model_swap --modes A` ✅, `test_normalization --tests unit` ✅; `test_multi_session` — 3 падения: гонка `os.replace` (`WinError 5`) — Windows-баг движка, не теста (вылечено в M1: retry + SQLite-мьютекс).
- `*.mystery-0706.bak` (compress/inject/test_scenario) — сторонние подмены 07:05–07:06 неизвестного происхождения: монолитная версия идеи (всё в одном `compress.py`, без store/normalize/llm). НЕ интегрировать без слова владельца.
- Инциденты в истории репо: runtime-данные попадали в git дважды (`628f3b9` и ранний `.demo/`) — в living-memory `.gitignore` с первого коммита.
- Проверенный путь системной установки OpenCode (NOTES §13.2): `~/.config/opencode` — родной npm-проект плагинов; `npm install github:lantaris/opencode-memory` там + относительный путь в глобальном `opencode.jsonc` (для living-memory — аналогично).
- Наблюдение (§11.3): OpenCode переинициализирует плагин после хода (повторный `ready` в том же pid); дубли гасит прайм-синхронизация по messageID (уже в коде).

### Зависимости (проверено в регистрах, не в прозе)

- `filelock` 4.1.0, MIT — рассматривался как замена `fcntl`; **отклонён при исполнении M1** (движок без внешних зависимостей, SQLite-мьютекс).
- `portalocker` 4.4.0, BSD-3 — тоже не понадобился.
- npm: `opencode-memory` — ЗАНЯТО чужим пакетом (tomako, github.com/shuans/opencode-memory, v2.0.1). `living-memory` — свободно. GitHub `lantaris/living-memory` — свободно. `@lantaris/opencode-memory` — свободно (для scoped-варианта).
- `@opencode-ai/plugin` — текущий 1.18.35; локальный CLI 1.18.31 (обновить для live-тестов).

### Грабли этой машины/сессии

- `web_extract` на этом хосте не работает (ddgs — только поиск); веб — через `mcp__duckduckgo__fetch_content`/`search`.
- `$TMPDIR` в bash указывает на `C:\Users\user\AppData\Local\Temp`, а не на hermes scratch; не путать при копировании/скидывании файлов.
- `which python3` находит заглушку Microsoft Store, но она НЕ запускает python (exit 9009 при spawn) — движку нужен `python`/`py -3`.
- Тесты opencode-memory на этой машине «как есть»: 7/13 (6 падений из-за отсутствия рабочего `python3`), 13/13 с тестовой заглушкой `fcntl` — доказано, что ломает платформа, не логика.
- `write_file` не перезаписывает файл, который был прочитан постранично; план писать чанками через маркер + `patch`.
- `PRAGMA journal_mode=WAL` не подчиняется `busy_timeout`: при одновременном старте двух процессов по одному каталогу — мгновенный «database is locked» (поймано гонкой 9/20). Решение: однократное переключение с ретраями (`python/store.py::_ensure_wal`), в `_connect` прагма не выполняется.
- Dev-стек на стенде: `npm install` (node_modules уже стоят), `python -m venv .venv` + `pip install pytest`; прогоны — `npm test`; `./.venv/Scripts/python -m pytest tests/python -q`.
- Мост при таймауте убивает всё дерево процессов: на Windows `taskkill /T /F` (механизм проверен синтетическим внуком: alive/alive → dead/dead); POSIX-внуки потребуют процесс-группу — в задачи M3.
- Hermes: `HERMES_HOME` передавать только нативным путём (`C:/...`); MSYS-форма `/c/...` превращается в `\c\...` и уводит состояние в `D:\c\...` (инцидент 2026-10-10 — мусорное дерево было удалено; основной дом не тронут). Для изолированного дома — `HERMES_DISABLE_LAZY_INSTALLS=1` (иначе ленивая сборка рантайма) и копия `.env` (ключи провайдеров берутся из окружения, не из auth.json).
- Memory-провайдер Hermes: `ctx`, полученный в `register()` — сокращённый коллектор без `.llm` (и без прочих не-`register_*` атрибутов); фасад строится как `PluginLlm(plugin_id="living-memory")`. Ключ aux-задачи — только `[a-z0-9_]`. Daemon-поток гибнет на выходе one-shot сессии → сжатие догоняется синхронно в `on_session_end` (плюс lock от двойного триггера). `agent_workspace` может прийти относительным — резолвить от cwd.

### Открытые решения (гейты)

Закрыты 2026-10-10: **D1** — GitHub пока не трогаем (работаем локально), npm-публикация позже, пакет локально `living-memory` 0.3.0; **D2** — общий каталог `<проект>/.living-memory/`; **D3–D5** — приняты по рекомендации (каталог Hermes после 1.0; 1.0 без MCP; README русский + EN-блок). Подробно — `DESIGN.md` §3.

---

## Хронология

- **2026-10-10** — Аудит `opencode-memory` (клон, только чтение): сильные стороны — сквозная деградация без падения агента, аккуратная конкурентность (flock + атомарные записи + сжатие LLM вне блокировки, применение под блокировкой с перечиткой, удаление из хвоста по id), нормализация ответов LLM отдельным слоем, журнал потерь + полный индекс, пер-сессионная изоляция. Дефекты: имя на npm занято чужим пакетом (README-инструкция ставит чужой код); Windows структурно сломан (`fcntl` + `python3`; 7/13 тестов); очередь `pending.jsonl` без потребителя (`resolve_pending` не вызывается ниоткуда); ядро Python без тестов в репо; мёртвые `full_history_text`/`get_default_provider`; argv-транспорт и локальные кодировки как мины портативности; в публичной истории git остались runtime-данные из коммита 628f3b9. Отчёт по аудиту — в чате от 2026-10-10.
- **2026-10-10** — Исследование хостов и написание плана. Проверено: ABC MemoryProvider и контракты Hermes (локальный исходник git-инсталляции), `ctx.llm` и aux-задачи, типы OpenCode 1.18.35 (npm pack), `opencode run --help`, доступность имён npm/GitHub, лицензии filelock/portalocker, отсутствие коллизии `memory_search` в Hermes. Создан каталог `D:\WRK\living-memory`; написан `PLAN.md` (гейты D1–D5, probe-этап M0b, милстоуны M0–M6, приёмка, риски). Код не трогался; исходный репо и аудит-клон не изменялись.
- **2026-10-10** — Владелец долил в репо `experements/memory-prototype/` (коммит 7e31288). Разобрано и проверено: `store.py` идентичен пакетному; mock-тесты прототипа на нашем стенде (заглушка `fcntl`, python 3.14) — scenario 24/24, session, loss_conflict, model_swap A, normalization unit зелёные; `test_multi_session` вскрыл Windows-баг движка (`os.replace` → `WinError 5` под конкуренцией). NOTES §9–§10 закрывают вопрос «конспект vs полная история» числами (67% стоимости, паритет на важных фактах). План обновлён: M1 + порт прототипных тестов и retry для `os.replace`; M2 + постобработка uncertain-дублей; M3 + проверенный путь системной установки; §6 + два риска; §5 + пункт приёмки; в справочной части — раздел о прототипе.
- **2026-10-10** — `PLAN.md` приведён к правилам проекта (только актуальные задачи, чек-лист с краткими описаниями); контекст, замеры, решения-гейты, детали этапов, приёмка и риски вынесены в новый `DESIGN.md`; указатели в HANDOFF обновлены.
- **2026-10-10** — Зафиксировано владельцем: файлы репозитория `opencode-memory` (включая `experements/`, манифест Автора) — только материал анализа, не правила и не ограничения; продукт делаем релизного уровня для реальной работы с агентами. Внесено: DESIGN (предупреждение после контрактов, «Уровень» в шапке, первый принцип в §4, FTS5 в §5/M2), PLAN (M0 — нейтрализация архива; M2 — FTS5), HANDOFF (статус материала).
- **2026-10-10** — По вопросу владельца о токенах сверены протоколы прототипа (test_retention.py: измерялся размер запроса к модели-ответчику на конце 104-сообщений, tiktoken; стоимость самих сжатий не учтена). В план добавлен probe P6 — замер реальной стоимости в живой сессии (с памятью и без).
- **2026-10-10** — Гейты закрыты (ответы владельца): GitHub не трогаем, npm позже, память — общий каталог `.living-memory/`. Начато исполнение.
- **2026-10-10** — **M0 выполнен (локально).** Рабочее дерево `D:\WRK\living-memory`: git init + импорт v0.2.0; переименование в `living-memory` 0.3.0 (пакет, скилл, пути, префиксы логов); архив нейтрализован (`MANIFEST.author.md` + шапка); CI-файл; README-установка. Коммит `9df86c9`.
- **2026-10-10** — **M1 выполнен.** Ядро кросс-платформенное: замок — SQLite `BEGIN IMMEDIATE` (без filelock), транспорт stdin/`--batch` (содержимое не в argv), UTF-8 (`PYTHONUTF8=1`, `encoding="utf-8"`), автодетект интерпретатора (`python3`→`python`→`py -3`), retry `os.replace`; батч-синк на idle. Порт 6 прототипных тестов в pytest + новые (гонка двух процессов, длинное сообщение через stdin). Результаты: `npm test` 14/14, `pytest` 8/8, гонка 9/20→0/20. Коммит `3c8aa34`.
- **2026-10-10** — Независимый аудит (2 субагента, read-only, 10 мин). Результаты M1 воспроизведены полностью (14/14 ×2, 8/8 ×5, гонка 0/20; механизм WAL-фикса подтверждён контрастным экспериментом: 17/20 сбоев без ретрая). Находки: код — F1 (мост теряет текст ошибки CLI), F2 (частичный хвост при сбое batch), F3 (TOCTOU инициализации), F4–F8 (устойчивость/мелочи), С2 (в npm-пак утекали `.pyc` — исправлено `python/.npmignore`); документы — К1–К3, С1–С6, Н1–Н6 (дрейф после M1). Дрейф документов исправлен этим коммитом; код-фиксы F1–F8 и Н6 — в PLAN (раздел «Фиксы после аудита»). Замер синка: 20 одиночных append 3.64 с → один batch 0.21 с.
- **2026-10-10** — Находки аудита закрыты (F1–F8, Н6), коммит `a32e562`. F1: мост читает error-JSON движка из stdout (был «python exited with code 1»); F2: batch пропускает битые строки (`skipped` + предупреждение в stderr) и guard в store; F3: инициализация через `O_EXCL` (`_create_if_missing` — TOCTOU закрыт); F4: пустой `--stdin` отклоняется; F5: битые строки recent пропускаются, `status`/`context` живы; F6: таймаут убивает дерево (проверено синтетическим внуком); F7: имена файлов сессий при санитизации получают хеш-суффикс (коллизии «a b»/«a/b» закрыты); F8: `_atomic_write` чистит tmp на любом исключении, `_index` принимает только лок-соединение, удалён мёртвый `get_default_provider`, комментарий про перезапись SKILL.md; Н6: `@opencode-ai/sdk` — devDependency. Тесты: node **15/15** (новый F1-тест), pytest **13/13** (4 CLI-контрактных + init-тест). Поправка к аудиту: `history_count` НЕ мёртв — используется прототипным сценарием, оставлен.
- **2026-10-10** — **M2 выполнен** (коммит `8e17b50`). Потребитель очереди: CLI `pending list|approve|reject` + `pending: N` в `status` + инструмент `memory_pending` (approve пишет в core/tasks, повторный approve — чистый отказ). Forget-операции: промпт/normalize/`apply_forget`, удалённое журналируется (`forgotten:core.*`). Капы задач — per-session. Детект uncertain-дублей (`patch:uncertain:duplicate_of_core`, без молчаливой чистки). Маркеры `[living-memory:begin/end]` вокруг инъекции (system.transform + компакция). `--private` — решено: движковая возможность, адаптеры пока не выставляют (Hermes-поток — M4). Поиск переведён на FTS5 (LIKE-фолбэк с экранированием метасимволов). Тесты: node **16/16**, pytest **20/20**.
- **2026-10-10** — M0b (OpenCode-часть) и **M3 live**. P3: `system.transform` — 2–3 вызова на `opencode run` (заголовок + основной), свежий `output.system` каждый раз, дублей нет; политика «раз на ход» не нужна. P4: промпт вложенного `opencode run` — через **stdin** (позиционный аргумент >~32 КБ → `WinError 206`); `-f` съедает следующий токен (сообщение — до флага); `--pure` выключает плагины целиком; `--format json` = JSONL (ответ в `part.text` событий `type=text`, токены в step-событиях). Провайдер `llm.py` переведён на `opencode run --pure --format json` + stdin + извлечение текста из событий — **flush заработал живьём** (core: `user.name=Эд`, likes `["Rust"]`, dislikes `["ORM"]`, хвост очищен). Инъекция доказана на новой сессии с пустой историей («Тебя зовут Эд, и ты не любишь ORM»); `memory_search` вызван агентом и вернул записи с меткой сессии. Побочные наблюдения: dispose→flush = 1 LLM-вызов на каждый завершённый run (кандидат — порог); `--command compact` в CLI не существует; запуск из несуществующего каталога → `Unexpected server error` до первого хука. Скилл-референс `agent-plugin-development` обновлён рантайм-наблюдениями.
- **2026-10-10** — **M4 выполнен (ядро)**: Hermes-адаптер (MemoryProvider) собран и проверен в изолированном HERMES_HOME. `plugins doctor` OK; `memory status` = Provider living-memory / available; live: prefetch 1×/турн (540 символов), sync_turn батчем, **сжатие через хостовый `ctx.llm` применено** (core: likes ["Windows"], compressions 2; хвост 10→5), pending-зеркало `on_memory_write` (4 записи), `hermes living-memory status` работает. Архитектура: движок — единственный владелец состояния, связь через CLI-subprocess (движок в процесс Hermes не импортируем — имена `store`/`cli` затенят модули хоста); сжатие двухфазное (`compact-prepare` → ctx.llm → `compact-apply`), движок получил эти команды (`python/compress.py`: prepare/apply, `cli.py`). Инциденты и грабли — в справочной части. Скилл-референс обновлён.
