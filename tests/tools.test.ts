import { test } from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { MemoryBridge } from "../src/bridge.js"
import { resolveConfig } from "../src/config.js"
import { bundledSkillPath, installSkill } from "../src/skill.js"
import { createMemorySearchTool } from "../src/tools.js"

function tempDir(prefix: string): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix))
}

function fakeToolContext() {
  return {
    sessionID: "session",
    messageID: "message",
    agent: "build",
    directory: "/tmp",
    worktree: "/tmp",
    abort: new AbortController().signal,
    metadata: () => {},
    ask: async () => {},
  } as never
}

function outputOf(result: unknown): string {
  if (typeof result === "string") return result
  return (result as { output: string }).output
}

test("memory_search returns raw hits from the index", async () => {
  const config = resolveConfig(process.cwd(), { dataDir: tempDir("ocm-tool-"), provider: "mock" })
  const bridge = new MemoryBridge(config)
  await bridge.append("user", "Меня зовут Иван, я не люблю ORM.")
  const searchTool = createMemorySearchTool(bridge, () => {})
  const result = await searchTool.execute({ query: "Иван" }, fakeToolContext())
  const output = outputOf(result)
  assert.match(output, /Иван/)
  assert.match(output, /\[user @/)
})

test("memory_search reports an empty result without inventing facts", async () => {
  const config = resolveConfig(process.cwd(), { dataDir: tempDir("ocm-tool2-"), provider: "mock" })
  const bridge = new MemoryBridge(config)
  await bridge.append("user", "Совершенно другая фраза про деплой.")
  const searchTool = createMemorySearchTool(bridge, () => {})
  const result = await searchTool.execute({ query: "несуществующее-слово-xyz" }, fakeToolContext())
  assert.match(outputOf(result), /No matching messages/)
})

test("memory_search degrades without throwing when python is missing", async () => {
  const config = resolveConfig(process.cwd(), {
    dataDir: tempDir("ocm-tool3-"),
    pythonBin: "definitely-not-a-python-binary",
  })
  const bridge = new MemoryBridge(config)
  const searchTool = createMemorySearchTool(bridge, () => {})
  const result = await searchTool.execute({ query: "что угодно" }, fakeToolContext())
  assert.match(outputOf(result), /unavailable/)
})

test("skill: installs, is idempotent, updates when content changes", () => {
  const project = tempDir("ocm-skill-")
  const packageRoot = process.cwd()
  const target = path.join(project, ".opencode", "skills", "living-memory", "SKILL.md")
  const bundled = fs.readFileSync(bundledSkillPath(packageRoot), "utf8")

  const first = installSkill(packageRoot, project)
  assert.equal(first.status, "created")
  assert.ok(fs.existsSync(target))
  assert.equal(fs.readFileSync(target, "utf8"), bundled)

  const second = installSkill(packageRoot, project)
  assert.equal(second.status, "unchanged")

  fs.writeFileSync(target, "stale content")
  const third = installSkill(packageRoot, project)
  assert.equal(third.status, "updated")
  assert.equal(fs.readFileSync(target, "utf8"), bundled)
})

test("skill: missing bundled skill fails gracefully", () => {
  const project = tempDir("ocm-skill2-")
  const result = installSkill(tempDir("ocm-empty-"), project)
  assert.equal(result.status, "failed")
  assert.match(result.error ?? "", /not found/)
})
