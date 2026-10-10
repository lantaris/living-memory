import { spawn } from "node:child_process"
import path from "node:path"
import type { ResolvedConfig } from "./config.js"

export type BridgeResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string }

export type StatusData = {
  ok: boolean
  python: string
  data_dir: string
  recent: number
  provider: string
  session: string | null
}

export type ContextData = {
  ok: boolean
  prompt: string
  recent: number
}

export type CompactData = {
  ok: boolean
  compressed: boolean
  notes?: string | null
}

export type FlushData = {
  ok: boolean
  flushed: boolean
  notes?: string | null
}

export type SearchHit = {
  text: string
  role: string
  ts: number
  indexed: boolean
  session_id?: string | null
  session_label?: string | null
  score?: number
}

export type SearchData = {
  ok: boolean
  results: SearchHit[]
}

export type SessionRef = {
  sessionId?: string
  sessionLabel?: string
}

export type AppendOptions = SessionRef & {
  private?: boolean
}

const DEFAULT_TIMEOUT_MS = 600_000

export class MemoryBridge {
  constructor(private readonly config: ResolvedConfig) {}

  status(session?: SessionRef): Promise<BridgeResult<StatusData>> {
    return this.run<StatusData>(["status"], 15_000, session)
  }

  append(
    role: "user" | "assistant",
    content: string,
    options: AppendOptions = {},
  ): Promise<BridgeResult<{ ok: boolean; recent: number }>> {
    const args = ["append", "--role", role, "--content", content]
    if (options.private) args.push("--private")
    return this.run(args, 15_000, options)
  }

  context(session?: SessionRef): Promise<BridgeResult<ContextData>> {
    return this.run<ContextData>(["context"], 15_000, session)
  }

  compactIfFull(session?: SessionRef): Promise<BridgeResult<CompactData>> {
    return this.run<CompactData>(["compact", "--if-full"], DEFAULT_TIMEOUT_MS, session)
  }

  compact(session?: SessionRef): Promise<BridgeResult<CompactData>> {
    return this.run<CompactData>(["compact"], DEFAULT_TIMEOUT_MS, session)
  }

  flush(session?: SessionRef): Promise<BridgeResult<FlushData>> {
    return this.run<FlushData>(["flush"], DEFAULT_TIMEOUT_MS, session)
  }

  search(query: string, limit = 5): Promise<BridgeResult<SearchData>> {
    return this.run<SearchData>(["search", "--query", query, "--limit", String(limit)], 15_000)
  }

  private run<T>(
    commandArgs: string[],
    timeoutMs: number,
    session?: SessionRef,
  ): Promise<BridgeResult<T>> {
    const { pythonBin, pythonDir, dataDir, provider, recentLimit } = this.config
    const args = [
      path.join(pythonDir, "cli.py"),
      "--data-dir",
      dataDir,
      "--provider",
      provider,
      "--recent-limit",
      String(recentLimit),
    ]
    if (session?.sessionId) {
      args.push("--session", session.sessionId)
    }
    if (session?.sessionLabel) {
      args.push("--session-label", session.sessionLabel)
    }
    args.push(...commandArgs)
    return new Promise((resolve) => {
      let stdout = ""
      let stderr = ""
      let settled = false

      const child = spawn(pythonBin, args, {
        env: { ...process.env, MEMORY_PLUGIN_DISABLE: "1" },
        stdio: ["ignore", "pipe", "pipe"],
      })

      const timer = setTimeout(() => {
        if (settled) return
        settled = true
        child.kill()
        resolve({ ok: false, error: `python timed out after ${timeoutMs}ms` })
      }, timeoutMs)

      child.stdout.on("data", (chunk) => {
        stdout += String(chunk)
      })
      child.stderr.on("data", (chunk) => {
        stderr += String(chunk)
      })
      child.on("error", (error) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        resolve({ ok: false, error: formatSpawnError(error) })
      })
      child.on("close", (code) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        if (code !== 0) {
          resolve({ ok: false, error: stderr.trim() || `python exited with code ${code}` })
          return
        }
        const lastLine = stdout.trim().split("\n").pop() ?? ""
        try {
          resolve({ ok: true, data: JSON.parse(lastLine) as T })
        } catch {
          resolve({ ok: false, error: `invalid JSON from python: ${lastLine.slice(0, 200)}` })
        }
      })
    })
  }
}

function formatSpawnError(error: Error): string {
  const code = (error as NodeJS.ErrnoException).code
  if (code === "ENOENT") {
    return "Python 3.10+ was not found. Install Python and make sure `python3` is on PATH (or set options.pythonBin / MEMORY_PLUGIN_PYTHON)."
  }
  return `${code ?? "spawn error"}: ${error.message}`
}
