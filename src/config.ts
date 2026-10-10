import fs from "node:fs"
import path from "node:path"
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
  dataDir: string
  provider: "opencode" | "mock"
  recentLimit: number
  logFile: string
  disabled: boolean
  debug: boolean
}

const bundledPackageRoot = fileURLToPath(new URL("../../", import.meta.url))
const bundledPythonDir = path.join(bundledPackageRoot, "python")

export function resolveConfig(directory: string, options: MemoryPluginOptions = {}): ResolvedConfig {
  const dataDir = path.resolve(
    options.dataDir ?? path.join(directory, ".living-memory"),
  )
  return {
    packageRoot: bundledPackageRoot,
    pythonDir: bundledPythonDir,
    pythonBin: options.pythonBin ?? process.env.MEMORY_PLUGIN_PYTHON ?? "python3",
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
