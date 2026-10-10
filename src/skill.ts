import fs from "node:fs"
import path from "node:path"

export type SkillInstallResult = {
  status: "created" | "updated" | "unchanged" | "failed"
  target: string
  error?: string
}

const SKILL_NAME = "living-memory"

export function installSkill(packageRoot: string, projectDirectory: string): SkillInstallResult {
  const source = path.join(packageRoot, "skills", SKILL_NAME, "SKILL.md")
  const target = path.join(projectDirectory, ".opencode", "skills", SKILL_NAME, "SKILL.md")
  try {
    if (!fs.existsSync(source)) {
      return { status: "failed", target, error: `bundled skill not found at ${source}` }
    }
    const content = fs.readFileSync(source, "utf8")
    if (fs.existsSync(target)) {
      const existing = fs.readFileSync(target, "utf8")
      if (existing === content) return { status: "unchanged", target }
      fs.writeFileSync(target, content)
      return { status: "updated", target }
    }
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.writeFileSync(target, content)
    return { status: "created", target }
  } catch (error) {
    return { status: "failed", target, error: String(error) }
  }
}

export function bundledSkillPath(packageRoot: string): string {
  return path.join(packageRoot, "skills", SKILL_NAME, "SKILL.md")
}
