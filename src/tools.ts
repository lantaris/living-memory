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
