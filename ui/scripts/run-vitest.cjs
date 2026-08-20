"use strict"
/**
 * worktree 下 ui/node_modules 常是指向主检出的 junction。
 * 从 worktree cwd 直接跑 vitest 会把 describe 注册到另一套文件身份（No test suite found）。
 * 这里把 cwd 切到 node_modules 的真实父目录（junction 时即主检出 ui/），
 * 仍用本目录的 config 与 --dir 跑 worktree 用例。
 */
const fs = require("node:fs")
const path = require("node:path")
const { spawnSync } = require("node:child_process")

const worktreeUi = path.resolve(__dirname, "..")
const nm = fs.realpathSync(path.join(worktreeUi, "node_modules"))
const hostUi = path.dirname(nm)
const vitest = path.join(nm, "vitest", "vitest.mjs")
const config = path.join(worktreeUi, "vitest.config.ts")
const result = spawnSync(
  process.execPath,
  [vitest, "run", "--config", config, "--dir", worktreeUi, ...process.argv.slice(2)],
  { cwd: hostUi, stdio: "inherit", env: process.env },
)
process.exit(result.status === null ? 1 : result.status)
