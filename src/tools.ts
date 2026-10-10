import { tool } from "@opencode-ai/plugin"
import type { MemoryBridge } from "./bridge.js"

export function createMemorySearchTool(
  bridge: MemoryBridge,
  logLine: (message: string) => void,
  debug = false,
) {
  return tool({
    description:
      "Search past session history for facts, decisions, or details not in current context. " +
      "Use when the user asks about something from earlier that isn't in your memory. " +
      "Do NOT use for recent messages (they are in the hot tail) or core facts (always visible).",
    args: {
      query: tool.schema
        .string()
        .describe("What to search for in past sessions: facts, decisions, details."),
      limit: tool.schema
        .number()
        .optional()
        .describe("Maximum results to return (default 5)."),
    },
    async execute(args) {
      const limit =
        typeof args.limit === "number" && args.limit > 0 ? Math.min(args.limit, 20) : 5
      if (debug) logLine(`memory_search called: query=${JSON.stringify(args.query)} limit=${limit}`)
      const result = await bridge.search(args.query, limit)
      if (!result.ok) {
        logLine(`memory_search failed: ${result.error}`)
        return {
          title: `memory_search: ${args.query}`,
          output: `Memory search is unavailable (${result.error}). Continue without it.`,
        }
      }
      const hits = result.data.results
      if (hits.length === 0) {
        return {
          title: `memory_search: ${args.query}`,
          output: "No matching messages in past session history.",
        }
      }
      const lines = hits.map((hit) => {
        const stamp = new Date(hit.ts * 1000).toISOString()
        const where = hit.session_label ?? hit.session_id ?? "shared"
        return `[${hit.role} @ ${stamp} | ${where}] ${hit.text}`
      })
      return {
        title: `memory_search: ${args.query} (${hits.length})`,
        output: lines.join("\n"),
      }
    },
  })
}

export function createMemoryPendingTool(
  bridge: MemoryBridge,
  logLine: (message: string) => void,
  debug = false,
) {
  return tool({
    description:
      "Memory confirmation queue: list facts the memory is unsure about, then approve (write into core memory) or reject them. " +
      "Use when the user asks what memory is unsure about, or confirms/denies a fact recorded tentatively.",
    args: {
      action: tool.schema.string().describe("One of: list, approve, reject."),
      id: tool.schema
        .number()
        .optional()
        .describe("Queue record id for approve/reject (from list)."),
    },
    async execute(args) {
      const action = args.action
      if (debug) logLine(`memory_pending called: action=${action} id=${args.id ?? "-"}`)
      if (action === "list") {
        const result = await bridge.pendingList()
        if (!result.ok) {
          logLine(`memory_pending list failed: ${result.error}`)
          return {
            title: "memory_pending: list",
            output: `Memory queue is unavailable (${result.error}). Continue without it.`,
          }
        }
        const items = result.data.pending
        if (items.length === 0) {
          return { title: "memory_pending: list", output: "The confirmation queue is empty." }
        }
        const lines = items.map((item) => `#${item.id} [${item.kind ?? "other"}] ${item.text}`)
        return { title: `memory_pending: list (${items.length})`, output: lines.join("\n") }
      }
      if (action !== "approve" && action !== "reject") {
        return {
          title: "memory_pending",
          output: `Unknown action '${action}'. Use list, approve or reject.`,
        }
      }
      const id = typeof args.id === "number" && Number.isFinite(args.id) ? args.id : null
      if (id === null) {
        return {
          title: `memory_pending: ${action}`,
          output: `Action '${action}' needs the record id (see list).`,
        }
      }
      const result = await bridge.pendingResolve(id, action === "approve")
      if (!result.ok) {
        logLine(`memory_pending ${action} failed: ${result.error}`)
        return { title: `memory_pending: ${action} ${id}`, output: `Queue action failed (${result.error}).` }
      }
      const record = result.data.record
      const verb = action === "approve" ? "Approved" : "Rejected"
      return {
        title: `memory_pending: ${action} ${id}`,
        output: `${verb} #${id} [${record.kind ?? "other"}]: ${record.text}`,
      }
    },
  })
}
