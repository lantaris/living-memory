import type { Hooks, PluginInput, PluginOptions } from "@opencode-ai/plugin"
import type { Part } from "@opencode-ai/sdk"
import { MemoryBridge } from "./bridge.js"
import { log, resolveConfig, type MemoryPluginOptions } from "./config.js"
import { installSkill } from "./skill.js"
import { createMemorySearchTool } from "./tools.js"

class SessionTracker {
  private sessions = new Map<string, string | undefined>()
  private seen = new Map<string, Set<string>>()
  private ignored = new Set<string>()

  register(sessionID: string, label?: string): void {
    if (this.ignored.has(sessionID)) return
    if (label) this.sessions.set(sessionID, label)
    else if (!this.sessions.has(sessionID)) this.sessions.set(sessionID, undefined)
    if (!this.seen.has(sessionID)) this.seen.set(sessionID, new Set())
  }

  ignore(sessionID: string): void {
    this.ignored.add(sessionID)
    this.sessions.delete(sessionID)
  }

  isIgnored(sessionID: string): boolean {
    return this.ignored.has(sessionID)
  }

  has(sessionID: string): boolean {
    return this.sessions.has(sessionID)
  }

  label(sessionID: string): string | undefined {
    return this.sessions.get(sessionID)
  }

  updateLabel(sessionID: string, label?: string): void {
    if (label && this.sessions.has(sessionID)) this.sessions.set(sessionID, label)
  }

  unregister(sessionID: string): void {
    this.sessions.delete(sessionID)
  }

  activeSessions(): Array<[string, string | undefined]> {
    return [...this.sessions.entries()]
  }

  markSeen(sessionID: string, messageID: string): void {
    this.register(sessionID, this.sessions.get(sessionID))
    this.seen.get(sessionID)!.add(messageID)
  }

  isSeen(sessionID: string, messageID: string): boolean {
    return this.seen.get(sessionID)?.has(messageID) ?? false
  }
}

function createQueue() {
  let tail: Promise<unknown> = Promise.resolve()
  return function enqueue<T>(task: () => Promise<T>): Promise<T> {
    const result = tail.then(task, task)
    tail = result.then(
      () => undefined,
      () => undefined,
    )
    return result
  }
}

function partsText(parts: Part[]): string {
  return parts
    .filter((part) => part.type === "text")
    .map((part) => (part as { text: string }).text)
    .join("\n")
    .trim()
}

function extractMessages(data: unknown): Array<{ id: string; role: "user" | "assistant"; text: string }> {
  if (!Array.isArray(data)) return []
  const messages: Array<{ id: string; role: "user" | "assistant"; text: string }> = []
  for (const entry of data) {
    const info = (entry as { info?: { id?: string; role?: string } })?.info
    const parts = ((entry as { parts?: Part[] })?.parts ?? []) as Part[]
    if (!info?.id || (info.role !== "user" && info.role !== "assistant")) continue
    const text = partsText(parts)
    if (text) messages.push({ id: info.id, role: info.role, text })
  }
  return messages
}

type HookContext = {
  input: PluginInput
  bridge: MemoryBridge
  tracker: SessionTracker
  logLine: (message: string) => void
  debug: boolean
  enqueue: <T>(task: () => Promise<T>) => Promise<T>
}

async function syncSession(context: HookContext, sessionID: string, write: boolean): Promise<void> {
  const { input, bridge, tracker, logLine } = context
  let response: Awaited<ReturnType<typeof input.client.session.messages>>
  try {
    response = await input.client.session.messages({ path: { id: sessionID } })
  } catch (error) {
    logLine(`sync failed (messages): ${String(error)}`)
    return
  }
  const messages = extractMessages(response.data)
  if (context.debug) logLine(`sync: ${sessionID} write=${write} messages=${messages.length}`)
  const sessionRef = { sessionId: sessionID, sessionLabel: tracker.label(sessionID) }
  for (const message of messages) {
    if (tracker.isSeen(sessionID, message.id)) continue
    if (write) {
      const result = await bridge.append(message.role, message.text, sessionRef)
      if (!result.ok) {
        logLine(`append failed: ${result.error}`)
        return
      }
      if (context.debug) logLine(`appended ${message.role} ${message.id} recent=${result.data.recent}`)
    }
    tracker.markSeen(sessionID, message.id)
  }
}

async function ensureSessionTracked(
  context: HookContext,
  sessionID: string,
  fallbackLabel?: string,
): Promise<boolean> {
  const { input, tracker, logLine } = context
  if (tracker.has(sessionID)) return true
  if (tracker.isIgnored(sessionID)) return false
  try {
    const response = await input.client.session.get({ path: { id: sessionID } })
    const info = response.data as { parentID?: string; title?: string } | undefined
    if (info?.parentID) {
      tracker.ignore(sessionID)
      if (context.debug) logLine(`ignored subagent session ${sessionID}`)
      return false
    }
    tracker.register(sessionID, info?.title ?? fallbackLabel)
  } catch (error) {
    logLine(`session lookup failed for ${sessionID}: ${String(error)}`)
    tracker.register(sessionID, fallbackLabel)
  }
  await syncSession(context, sessionID, false)
  return true
}

export async function createHooks(input: PluginInput, options?: PluginOptions): Promise<Hooks> {
  const config = resolveConfig(input.directory, (options ?? {}) as MemoryPluginOptions)
  if (config.disabled) {
    console.error("[living-memory] disabled by MEMORY_PLUGIN_DISABLE=1")
    return {}
  }

  const bridge = new MemoryBridge(config)
  const tracker = new SessionTracker()
  const enqueue = createQueue()
  const logLine = (message: string) => log(config, message)
  const context: HookContext = {
    input,
    bridge,
    tracker,
    logLine,
    debug: config.debug,
    enqueue,
  }

  const status = await bridge.status()
  if (!status.ok) {
    logLine(`degraded: ${status.error}`)
  } else {
    logLine(
      `ready: python ${status.data.python}, data ${status.data.data_dir}, provider ${status.data.provider}`,
    )
  }

  if (config.debug) logLine(`plugin input keys: ${Object.keys(input).join(", ")}`)
  const skill = installSkill(config.packageRoot, input.directory)
  if (skill.status === "failed") {
    logLine(`skill install failed: ${skill.error}`)
  } else {
    logLine(`skill ${skill.status}: ${skill.target}`)
  }

  const sessionRef = (sessionID: string) => ({
    sessionId: sessionID,
    sessionLabel: tracker.label(sessionID),
  })

  const hooks: Hooks = {
    tool: {
      memory_search: createMemorySearchTool(bridge, logLine, config.debug),
    },

    event: async ({ event }) => {
      try {
        if (event.type === "session.created") {
          const info = event.properties.info
          if (info.parentID) {
            tracker.ignore(info.id)
            return
          }
          tracker.register(info.id, info.title)
          await enqueue(async () => {
            await syncSession(context, info.id, false)
            logLine(`session.created ${info.id} (${info.title ?? "no title"})`)
          })
          return
        }
        if (event.type === "session.updated") {
          const info = event.properties.info
          tracker.updateLabel(info.id, info.title)
          return
        }
        if (event.type === "session.idle") {
          const sessionID = event.properties.sessionID
          if (!tracker.has(sessionID)) return
          await enqueue(async () => {
            await syncSession(context, sessionID, true)
            const compact = await bridge.compactIfFull(sessionRef(sessionID))
            if (compact.ok && compact.data.compressed) {
              logLine(`compacted on idle: ${compact.data.notes ?? "no notes"}`)
            } else if (!compact.ok) {
              logLine(`compact skipped: ${compact.error}`)
            }
          })
          return
        }
        if (event.type === "session.deleted") {
          const info = event.properties.info
          if (!tracker.has(info.id)) return
          await enqueue(async () => {
            await syncSession(context, info.id, true)
            const flushed = await bridge.flush(sessionRef(info.id))
            if (!flushed.ok) logLine(`flush failed: ${flushed.error}`)
            else logLine(`flushed on session end: ${info.id}`)
            tracker.unregister(info.id)
          })
        }
      } catch (error) {
        logLine(`event hook error: ${String(error)}`)
      }
    },

    "chat.message": async (input_, output) => {
      try {
        const sessionID = input_.sessionID
        const text = partsText(output.parts)
        if (config.debug) {
          logLine(
            `chat.message: session=${sessionID} messageID=${input_.messageID ?? output.message?.id ?? "?"} parts=${output.parts.length} textLen=${text.length}`,
          )
        }
        if (!sessionID) return
        const tracked = await ensureSessionTracked(context, sessionID)
        if (!tracked) return
        if (!text) return
        const messageID = input_.messageID ?? output.message?.id
        await enqueue(async () => {
          const result = await bridge.append("user", text, sessionRef(sessionID))
          if (!result.ok) {
            logLine(`append failed: ${result.error}`)
            return
          }
          if (config.debug) logLine(`appended user via chat.message recent=${result.data.recent}`)
          if (messageID) tracker.markSeen(sessionID, messageID)
        })
      } catch (error) {
        logLine(`chat.message hook error: ${String(error)}`)
      }
    },

    "experimental.chat.system.transform": async (input_, output) => {
      try {
        const sessionID = input_.sessionID
        if (!sessionID || !tracker.has(sessionID)) return
        const result = await bridge.context(sessionRef(sessionID))
        if (!result.ok) {
          logLine(`context failed: ${result.error}`)
          return
        }
        if (result.data.prompt) output.system.push(result.data.prompt)
      } catch (error) {
        logLine(`system.transform hook error: ${String(error)}`)
      }
    },

    "experimental.session.compacting": async (input_, output) => {
      try {
        if (!tracker.has(input_.sessionID)) return
        const result = await bridge.context(sessionRef(input_.sessionID))
        if (!result.ok) {
          logLine(`compaction context failed: ${result.error}`)
          return
        }
        if (result.data.prompt) {
          output.context.push("# Layered memory (living-memory)\n" + result.data.prompt)
          logLine(`compaction context injected for ${input_.sessionID}`)
        }
      } catch (error) {
        logLine(`compacting hook error: ${String(error)}`)
      }
    },

    dispose: async () => {
      try {
        const active = tracker.activeSessions()
        if (active.length === 0) {
          const flushed = await enqueue(() => bridge.flush())
          if (!flushed.ok) logLine(`dispose flush failed: ${flushed.error}`)
          return
        }
        for (const [sessionID] of active) {
          const flushed = await enqueue(() => bridge.flush(sessionRef(sessionID)))
          if (!flushed.ok) logLine(`dispose flush failed: ${flushed.error}`)
        }
      } catch (error) {
        logLine(`dispose hook error: ${String(error)}`)
      }
    },
  }

  return hooks
}
