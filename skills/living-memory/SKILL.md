---
name: living-memory
description: Use when the user asks about something from earlier in a long conversation that is not in your current context — facts, decisions, or details from past sessions. Not needed for short exchanges.
---

# Working with living memory

You have persistent memory across sessions, provided by the `living-memory`
plugin. It works in three layers, all already present in your context:

- **Core** (who the user is) — `# CORE MEMORY`.
- **Tasks** (what is open or closed) — `# OPEN TASKS` / `# CLOSED TOPICS`.
- **Hot tail** (recent messages) — `# RECENT MESSAGES`.

These layers update automatically. Do not manage, restate, or duplicate them.

## When to use `memory_search`

Call `memory_search` when:

- the user asks about something from earlier that is not in your context;
- you need to verify a detail you are not sure about;
- the user says things like "we discussed this before" or "remember when".

Do NOT call it:

- for recent messages (they are in the hot tail);
- for facts already visible in core or tasks;
- on every turn — that wastes tokens.

## What `memory_search` returns

Raw messages from the full history index: role, timestamp, and text. They are
not summarized. If a result contains the answer, use it. If not, say you don't
know — do not guess.

## Limits

- Details dropped by compression (transient facts, side remarks such as pets,
  series, food, small talk) are NOT in core or tasks, but ARE in the index.
  Use `memory_search` to find them.
- If the index has nothing either, the fact is truly lost. Say so honestly.
- If the tool reports "Memory search is unavailable", continue without it and
  tell the user that memory search is degraded.
