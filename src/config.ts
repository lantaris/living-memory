import fs from "node:fs"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"

export type MemoryPluginOptions = {
  dataDir?: string
  pythonBin?: string
  provider?: "opencode" | "mock"
  recentLimit?: number
}

export type ResolvedConfig = {
  packageRoot: string
  pythonDir: string
  pythonBin: string
  pythonArgs: string[]
  dataDir: string
  provider: "opencode" | "mock"
  recentLimit: number
  logFile: string
  disabled: boolean
  debug: boolean
}

const bundledPackageRoot = fileURLToPath(new URL("../../", import.meta.url))
const bundledPythonDir = path.join(bundledPackageRoot, "python")

const MIN_PYTHON: [number, number] = [3, 10]
const PYTHON_PROBE = "import sys; print('%d.%d' % sys.version_info[:2])"

export type PythonCommand = { bin: string; args: string[] }

let cachedPython: PythonCommand | undefined

function splitCommand(value: string): PythonCommand {
  const parts = value.trim().split(/\s+/).filter(Boolean)
  return parts.length > 0 ? { bin: parts[0], args: parts.slice(1) } : { bin: value, args: [] }
}

function probePython(command: PythonCommand): boolean {
  const result = spawnSync(command.bin, [...command.args, "-c", PYTHON_PROBE], {
    encoding: "utf8",
    windowsHide: true,
    timeout: 10_000,
  })
  if (result.error || result.status !== 0) return false
  const match = (result.stdout ?? "").trim().match(/^(\d+)\.(\d+)$/)
  if (!match) return false
  const major = Number(match[1])
  const minor = Number(match[2])
  return major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1])
}

/**
 * Pick the Python interpreter for the engine. An explicit option or
 * MEMORY_PLUGIN_PYTHON wins as-is; otherwise probe `python3`, `python`, then the
 * Windows launcher `py -3` (plain `python3` is a Microsoft Store stub on Windows).
 */
export function resolvePythonCommand(explicit?: string): PythonCommand {
  const configured = explicit ?? process.env.MEMORY_PLUGIN_PYTHON
  if (configured) return splitCommand(configured)
  if (cachedPython) return cachedPython
  const candidates: PythonCommand[] = [
    { bin: "python3", args: [] },
    { bin: "python", args: [] },
    { bin: "py", args: ["-3"] },
  ]
  for (const candidate of candidates) {
    if (probePython(candidate)) {
      cachedPython = candidate
      return candidate
    }
  }
  cachedPython = candidates[0]
  return cachedPython
}

export function resolveConfig(directory: string, options: MemoryPluginOptions = {}): ResolvedConfig {
  const dataDir = path.resolve(
    options.dataDir ?? path.join(directory, ".living-memory"),
  )
  const python = resolvePythonCommand(options.pythonBin)
  return {
    packageRoot: bundledPackageRoot,
    pythonDir: bundledPythonDir,
    pythonBin: python.bin,
    pythonArgs: python.args,
    dataDir,
    provider: options.provider ?? "opencode",
    recentLimit: options.recentLimit ?? 10,
    logFile: path.join(dataDir, "plugin.log"),
    disabled: process.env.MEMORY_PLUGIN_DISABLE === "1",
    debug: process.env.MEMORY_PLUGIN_DEBUG === "1",
  }
}

export function log(config: ResolvedConfig, message: string): void {
  const line = `[living-memory pid=${process.pid}] ${new Date().toISOString()} ${message}`
  try {
    fs.mkdirSync(config.dataDir, { recursive: true })
    fs.appendFileSync(config.logFile, line + "\n")
  } catch {
    // logging must never break the session
  }
  console.error(line)
}
