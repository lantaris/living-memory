import type { Plugin } from "@opencode-ai/plugin"
import { createHooks } from "./hooks.js"

export const OpenCodeMemoryPlugin: Plugin = async (input, options) => createHooks(input, options)

export default OpenCodeMemoryPlugin
