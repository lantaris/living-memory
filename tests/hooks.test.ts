import { test } from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { createHooks } from "../src/hooks.js"

type FakeMessage = {
  info: { id: string; role: string; sessionID: string }
  parts: Array<{ type: "text"; text: string }>
}

type SessionInfo = { parentID?: string; title?: string }

function makeHarness(
  messagesBySession: Record<string, FakeMessage[]>,
  sessionInfo: Record<string, SessionInfo> = {},
) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ocm-hooks-"))
  const dataDir = path.join(directory, "data")
  const input = {
    directory,
    worktree: directory,
    client: {
      session: {
        messages: async ({ path: params }: { path: { id: string } }) => ({
          data: messagesBySession[params.id] ?? [],
        }),
        get: async ({ path: params }: { path: { id: string } }) => ({
          data: { id: params.id, ...(sessionInfo[params.id] ?? {}) },
        }),
      },
    },
  } as never
  const options = { dataDir, provider: "mock" as const }
  return { directory, dataDir, input, options }
}

function readRecent(dataDir: string, sessionID: string): Array<{ role: string; content: string }> {
  const file = path.join(dataDir, "memory", "recent", `${sessionID}.jsonl`)
  if (!fs.existsSync(file)) return []
  return fs
    .readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line))
}

function textPart(text: string): Array<{ type: "text"; text: string }> {
  return [{ type: "text", text }]
}

test("hooks: session flow records messages exactly once and injects context", async () => {
  const sessionID = "session-1"
  const messagesBySession: Record<string, FakeMessage[]> = { [sessionID]: [] }
  const { directory, dataDir, input, options } = makeHarness(messagesBySession, {
    [sessionID]: { title: "Firmware" },
  })
  const hooks = await createHooks(input, options)

  assert.ok(hooks.tool && hooks.tool["memory_search"], "memory_search tool must be registered")
  assert.ok(hooks.tool["memory_pending"], "memory_pending tool must be registered")
  assert.ok(
    fs.existsSync(path.join(directory, ".opencode", "skills", "living-memory", "SKILL.md")),
    "skill must be installed on disk",
  )

  await hooks.event!({
    event: { type: "session.created", properties: { info: { id: sessionID, title: "Firmware" } } },
  } as never)

  await hooks["chat.message"]!(
    { sessionID, messageID: "m1" } as never,
    { message: {}, parts: textPart("Меня зовут Иван.") } as never,
  )

  messagesBySession[sessionID].push({
    info: { id: "m1", role: "user", sessionID },
    parts: textPart("Меня зовут Иван."),
  })
  messagesBySession[sessionID].push({
    info: { id: "m2", role: "assistant", sessionID },
    parts: textPart("Привет, Иван!"),
  })

  await hooks.event!({
    event: { type: "session.idle", properties: { sessionID } },
  } as never)

  const entries = readRecent(dataDir, sessionID).map((entry) => entry.role + ":" + entry.content)
  assert.deepEqual(entries, ["user:Меня зовут Иван.", "assistant:Привет, Иван!"])

  await hooks.event!({
    event: { type: "session.idle", properties: { sessionID } },
  } as never)
  assert.equal(readRecent(dataDir, sessionID).length, 2)

  const system: string[] = []
  await hooks["experimental.chat.system.transform"]!(
    { sessionID } as never,
    { system } as never,
  )
  assert.equal(system.length, 1)
  assert.match(system[0], /\[living-memory:begin\]/)
  assert.match(system[0], /never treat it as instructions/)
  assert.match(system[0], /\[living-memory:end\]/)
  assert.match(system[0], /CORE MEMORY/)
  assert.match(system[0], /MY TASKS \(session: Firmware\)/)
  assert.match(system[0], /Иван/)

  const compaction = { context: [] as string[] }
  await hooks["experimental.session.compacting"]!({ sessionID } as never, compaction as never)
  assert.equal(compaction.context.length, 1)
  assert.match(compaction.context[0], /\[living-memory:begin\]/)
  assert.match(compaction.context[0], /\[living-memory:end\]/)
})

test("hooks: two sessions keep separate tails and prompts", async () => {
  const messagesBySession: Record<string, FakeMessage[]> = { alpha: [], beta: [] }
  const { dataDir, input, options } = makeHarness(messagesBySession, {
    alpha: { title: "Firmware" },
    beta: { title: "App" },
  })
  const hooks = await createHooks(input, options)

  await hooks.event!({
    event: { type: "session.created", properties: { info: { id: "alpha", title: "Firmware" } } },
  } as never)
  await hooks.event!({
    event: { type: "session.created", properties: { info: { id: "beta", title: "App" } } },
  } as never)

  await hooks["chat.message"]!(
    { sessionID: "alpha", messageID: "a1" } as never,
    { message: {}, parts: textPart("только-альфа сообщение про Rust.") } as never,
  )
  await hooks["chat.message"]!(
    { sessionID: "beta", messageID: "b1" } as never,
    { message: {}, parts: textPart("только-бета сообщение про TypeScript.") } as never,
  )

  const alphaTail = readRecent(dataDir, "alpha").map((entry) => entry.content)
  const betaTail = readRecent(dataDir, "beta").map((entry) => entry.content)
  assert.deepEqual(alphaTail, ["только-альфа сообщение про Rust."])
  assert.deepEqual(betaTail, ["только-бета сообщение про TypeScript."])

  const alphaSystem: string[] = []
  await hooks["experimental.chat.system.transform"]!(
    { sessionID: "alpha" } as never,
    { system: alphaSystem } as never,
  )
  assert.match(alphaSystem[0], /только-альфа/)
  assert.doesNotMatch(alphaSystem[0], /только-бета/)

  const betaSystem: string[] = []
  await hooks["experimental.chat.system.transform"]!(
    { sessionID: "beta" } as never,
    { system: betaSystem } as never,
  )
  assert.match(betaSystem[0], /только-бета/)
  assert.doesNotMatch(betaSystem[0], /только-альфа/)
})

test("hooks: subagent sessions are not recorded", async () => {
  const { dataDir, input, options } = makeHarness(
    {},
    { "sub-1": { parentID: "parent-1", title: "Subtask" } },
  )
  const hooks = await createHooks(input, options)
  await hooks["chat.message"]!(
    { sessionID: "sub-1", messageID: "s1" } as never,
    { message: {}, parts: textPart("сообщение сабагента") } as never,
  )
  assert.equal(readRecent(dataDir, "sub-1").length, 0)
  const system: string[] = []
  await hooks["experimental.chat.system.transform"]!(
    { sessionID: "sub-1" } as never,
    { system } as never,
  )
  assert.equal(system.length, 0)
})

test("hooks: ignored for untracked sessions", async () => {
  const { input, options } = makeHarness({})
  const hooks = await createHooks(input, options)
  const system: string[] = []
  await hooks["experimental.chat.system.transform"]!(
    { sessionID: "unknown-session" } as never,
    { system } as never,
  )
  assert.equal(system.length, 0)
})

test("hooks: broken python does not throw and leaves no memory", async () => {
  const sessionID = "session-broken"
  const messagesBySession: Record<string, FakeMessage[]> = { [sessionID]: [] }
  const { input, options } = makeHarness(messagesBySession)
  const hooks = await createHooks(input, {
    ...options,
    pythonBin: "definitely-not-a-python-binary",
  })

  await hooks.event!({
    event: { type: "session.created", properties: { info: { id: sessionID } } },
  } as never)
  await hooks["chat.message"]!(
    { sessionID, messageID: "m1" } as never,
    { message: {}, parts: textPart("Проверка деградации.") } as never,
  )
  await hooks.event!({
    event: { type: "session.idle", properties: { sessionID } },
  } as never)

  const system: string[] = []
  await hooks["experimental.chat.system.transform"]!(
    { sessionID } as never,
    { system } as never,
  )
  assert.equal(system.length, 0)
})

test("hooks: the debug option adds verbose lines to plugin.log", async () => {
  const sessionID = "session-debug"
  const messagesBySession: Record<string, FakeMessage[]> = { [sessionID]: [] }
  const { dataDir, input, options } = makeHarness(messagesBySession, {
    [sessionID]: { title: "Debug" },
  })
  const hooks = await createHooks(input, { ...options, debug: true })

  await hooks.event!({
    event: { type: "session.created", properties: { info: { id: sessionID, title: "Debug" } } },
  } as never)
  await hooks["chat.message"]!(
    { sessionID, messageID: "m1" } as never,
    { message: {}, parts: textPart("Привет.") } as never,
  )
  const system: string[] = []
  await hooks["experimental.chat.system.transform"]!(
    { sessionID } as never,
    { system } as never,
  )

  const log = fs.readFileSync(path.join(dataDir, "plugin.log"), "utf8")
  assert.match(log, /plugin input keys:/)
  assert.match(log, /chat\.message: session=session-debug/)
  assert.match(log, /sync: session-debug/)
  assert.match(log, /context injected: chars=\d+ session=session-debug/)
})

test("hooks: without the debug option the log keeps the basic trail only", async () => {
  const sessionID = "session-quiet"
  const messagesBySession: Record<string, FakeMessage[]> = { [sessionID]: [] }
  const { dataDir, input, options } = makeHarness(messagesBySession)

  const hooks = await createHooks(input, options)
  await hooks.event!({
    event: { type: "session.created", properties: { info: { id: sessionID } } },
  } as never)
  await hooks["chat.message"]!(
    { sessionID, messageID: "m1" } as never,
    { message: {}, parts: textPart("Привет.") } as never,
  )
  const system: string[] = []
  await hooks["experimental.chat.system.transform"]!(
    { sessionID } as never,
    { system } as never,
  )

  const log = fs.readFileSync(path.join(dataDir, "plugin.log"), "utf8")
  assert.match(log, /session\.created session-quiet/)
  assert.doesNotMatch(log, /plugin input keys:/)
  assert.doesNotMatch(log, /chat\.message: session=/)
  assert.doesNotMatch(log, /sync: session-/)
  assert.doesNotMatch(log, /context injected:/)
})
