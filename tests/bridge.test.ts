import { test } from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { MemoryBridge } from "../src/bridge.js"
import { resolveConfig } from "../src/config.js"

function tempDir(prefix: string): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix))
}

test("bridge: status, append, context, search, compact-if-full", async () => {
  const dataDir = tempDir("ocm-bridge-")
  const config = resolveConfig(process.cwd(), { dataDir, provider: "mock" })
  const bridge = new MemoryBridge(config)

  const status = await bridge.status()
  assert.equal(status.ok, true, status.ok ? "" : status.error)
  if (status.ok) {
    assert.match(status.data.python, /^3\.(1[0-9]|[2-9][0-9])/)
    assert.equal(status.data.provider, "mock")
    assert.equal(status.data.recent, 0)
  }

  const appended = await bridge.append("user", "Меня зовут Иван, я люблю Python.")
  assert.equal(appended.ok, true, appended.ok ? "" : appended.error)
  if (appended.ok) assert.equal(appended.data.recent, 1)

  const context = await bridge.context()
  assert.equal(context.ok, true)
  if (context.ok) {
    assert.match(context.data.prompt, /Иван/)
    assert.match(context.data.prompt, /CORE MEMORY/)
  }

  const found = await bridge.search("Иван")
  assert.equal(found.ok, true)
  if (found.ok) {
    assert.equal(found.data.results.length, 1)
    assert.match(found.data.results[0].text, /Иван/)
    assert.equal(found.data.results[0].indexed, true)
  }

  const compact = await bridge.compactIfFull()
  assert.equal(compact.ok, true)
  if (compact.ok) assert.equal(compact.data.compressed, false)

  const direct = await bridge.compact()
  assert.equal(direct.ok, true)
  if (direct.ok) assert.equal(direct.data.compressed, false)
})

test("bridge: append --batch writes several messages in one call", async () => {
  const dataDir = tempDir("ocm-batch-")
  const config = resolveConfig(process.cwd(), { dataDir, provider: "mock" })
  const bridge = new MemoryBridge(config)

  const result = await bridge.appendBatch([
    { role: "user", content: "Первый вопрос про хранилище." },
    { role: "assistant", content: "Ответ про SQLite." },
    { role: "user", content: "Второй вопрос про деплой." },
  ])
  assert.equal(result.ok, true, result.ok ? "" : result.error)
  if (result.ok) {
    assert.equal(result.data.appended, 3)
    assert.equal(result.data.recent, 3)
  }

  const found = await bridge.search("деплой")
  assert.equal(found.ok, true)
  if (found.ok) assert.equal(found.data.results.length, 1)
})

test("bridge: full window triggers compression and flush clears it", async () => {
  const dataDir = tempDir("ocm-bridge2-")
  const config = resolveConfig(process.cwd(), { dataDir, provider: "mock", recentLimit: 10 })
  const bridge = new MemoryBridge(config)

  for (let i = 1; i <= 10; i += 1) {
    await bridge.append("user", `Тема: шаг ${i}. Решили: продолжаем шаг ${i}.`)
  }
  const compact = await bridge.compactIfFull()
  assert.equal(compact.ok, true)
  if (compact.ok) assert.equal(compact.data.compressed, true)

  for (let i = 1; i <= 3; i += 1) {
    await bridge.append("assistant", `Осталось: доработать хвост ${i}.`)
  }
  const flushed = await bridge.flush()
  assert.equal(flushed.ok, true)
  if (flushed.ok) assert.equal(flushed.data.flushed, true)

  const status = await bridge.status()
  if (status.ok) assert.equal(status.data.recent, 0)
})

test("bridge: engine errors surface with their message, not an exit code", async () => {
  const base = tempDir("ocm-err-")
  const filePath = path.join(base, "not-a-dir")
  fs.writeFileSync(filePath, "x")
  try {
    const config = resolveConfig(process.cwd(), { dataDir: filePath, provider: "mock" })
    const bridge = new MemoryBridge(config)
    const status = await bridge.status()
    assert.equal(status.ok, false)
    if (!status.ok) {
      assert.match(status.error, /Error/)
      assert.doesNotMatch(status.error, /exited with code/)
    }
  } finally {
    fs.rmSync(base, { recursive: true, force: true })
  }
})

test("bridge: missing python degrades gracefully with a clear message", async () => {
  const config = resolveConfig(process.cwd(), {
    dataDir: tempDir("ocm-nopy-"),
    pythonBin: "definitely-not-a-python-binary",
  })
  const bridge = new MemoryBridge(config)
  const status = await bridge.status()
  assert.equal(status.ok, false)
  if (!status.ok) assert.match(status.error, /Python 3\.10\+/)
})
