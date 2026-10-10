import { spawn, spawnSync } from "node:child_process"
import type { ChildProcess } from "node:child_process"
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
  pending: number
  provider: string
  session: string | null
}

export type PendingRecord = {
  id: number
  ts?: number
  kind?: string
  text: string
  status: string
  resolved_at?: number
  note?: string
}

export type PendingListData = {
  ok: boolean
  pending: PendingRecord[]
  count: number
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

export type AppendItem = {
  role: "user" | "assistant"
  content: string
  private?: boolean
}

export type AppendResult = { ok: boolean; recent: number }
export type AppendBatchResult = { ok: boolean; appended: number; recent: number }

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
  ): Promise<BridgeResult<AppendResult>> {
    const args = ["append", "--role", role, "--stdin"]
    if (options.private) args.push("--private")
    return this.run<AppendResult>(args, 15_000, options, content)
  }

  /**
   * Append several messages with ONE Python process (content travels on stdin
   * as JSONL). Message text never goes into argv: argv has hard length limits
   * (~32 KB command line on Windows, ~128 KB per argument on Linux).
   */
  appendBatch(
    items: AppendItem[],
    session: SessionRef = {},
  ): Promise<BridgeResult<AppendBatchResult>> {
    const body =
      items.map((item) => JSON.stringify(item)).join("\n") + (items.length > 0 ? "\n" : "")
    return this.run<AppendBatchResult>(["append", "--batch"], 60_000, session, body)
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

  pendingList(): Promise<BridgeResult<PendingListData>> {
    return this.run<PendingListData>(["pending", "list"], 15_000)
  }

  pendingResolve(
    id: number,
    approve: boolean,
  ): Promise<BridgeResult<{ ok: boolean; record: PendingRecord }>> {
    return this.run(["pending", approve ? "approve" : "reject", "--id", String(id)], 15_000)
  }

  private run<T>(
    commandArgs: string[],
    timeoutMs: number,
    session?: SessionRef,
    stdinData?: string,
  ): Promise<BridgeResult<T>> {
    const { pythonBin, pythonArgs, pythonDir, dataDir, provider, recentLimit } = this.config
    const args = [
      ...pythonArgs,
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
        // PYTHONUTF8=1 keeps Russian text intact regardless of the Windows locale;
        // MEMORY_PLUGIN_DISABLE=1 is inherited by nested `opencode run` calls so the
        // memory plugin cannot recurse into itself during compression.
        env: { ...process.env, MEMORY_PLUGIN_DISABLE: "1", PYTHONUTF8: "1" },
        stdio: stdinData === undefined ? ["ignore", "pipe", "pipe"] : ["pipe", "pipe", "pipe"],
        windowsHide: true,
      })

      if (stdinData !== undefined && child.stdin) {
        child.stdin.on("error", () => {
          // the child may exit before consuming stdin; the close handler reports it
        })
        child.stdin.end(stdinData, "utf8")
      }

      const timer = setTimeout(() => {
        if (settled) return
        settled = true
        killProcessTree(child)
        resolve({ ok: false, error: `python timed out after ${timeoutMs}ms` })
      }, timeoutMs)

      child.stdout?.on("data", (chunk) => {
        stdout += String(chunk)
      })
      child.stderr?.on("data", (chunk) => {
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
          resolve({ ok: false, error: pythonErrorMessage(stdout, stderr, code) })
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

function pythonErrorMessage(stdout: string, stderr: string, code: number | null): string {
  // cli.py reports engine errors as an error-JSON line on stdout (stderr stays
  // empty), so read that line instead of reporting a bare exit code.
  const lastLine = stdout.trim().split("\n").pop() ?? ""
  if (lastLine) {
    try {
      const payload = JSON.parse(lastLine) as { ok?: boolean; error?: unknown }
      if (payload && payload.ok === false && typeof payload.error === "string" && payload.error.trim()) {
        return payload.error.trim()
      }
    } catch {
      // not the CLI error JSON - fall through to stderr
    }
  }
  return stderr.trim() || `python exited with code ${code}`
}

function killProcessTree(child: ChildProcess): void {
  // TerminateProcess does not cascade on Windows: a hung `opencode run` grandchild
  // (spawned by the compression provider) would survive child.kill(). taskkill /T
  // takes the whole tree. POSIX grandchildren would need a process group - planned
  // with the live M3 checks.
  if (child.pid && process.platform === "win32") {
    try {
      spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true })
    } catch {
      // fall through to the plain kill below
    }
  }
  try {
    child.kill("SIGKILL")
  } catch {
    // already gone
  }
}

function formatSpawnError(error: Error): string {
  const code = (error as NodeJS.ErrnoException).code
  if (code === "ENOENT") {
    return "Python 3.10+ was not found (tried `python3`, `python`, `py -3`). Install Python and make sure it is on PATH, or set options.pythonBin / MEMORY_PLUGIN_PYTHON."
  }
  return `${code ?? "spawn error"}: ${error.message}`
}
