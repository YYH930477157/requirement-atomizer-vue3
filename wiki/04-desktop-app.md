# 04 桌面应用

官方桌面产品是 **Vue3 + Electron** UI（`ui/`）+ Python 后端。
`gui/` 下的 PySide6 旧界面自 2026-06-27 起**冻结**：保持可运行但不再扩展，
新的 UI 工作一律进 `ui/`。

## 开发运行

```powershell
cd .\ui
npm install
npm run desktop:dev
```

渲染层构建与测试：

```powershell
npm test
npm run build
```

## 打包便携版

```powershell
npm run desktop:pack
```

打包流程：

1. 先用 PyInstaller 构建后端 `dist-backend/ratomizer-desktop.exe`
   （需要先 `pip install -e .[package]`）
2. electron-builder 将后端可执行文件与运行时资产一起打包：
   `requirement_kb/`、`parsers/`、`domain_packs/`、`knowledge_bases/`、`llm_agents/`
3. 打包后的应用优先使用内嵌后端，仅开发期回退到本机 Python

> 已知坑：Node 24 下 electron 安装会静默失败（`extract-zip` 问题），
> 请使用 Node LTS 22，或手工解压 electron 缓存（见 [02 安装与运行环境](./02-install.md)）。
> 若 PowerShell 执行策略阻止 `npm.ps1`，用 `cmd /c "npm run desktop:pack"`。

## 桌面端工作方式

- Electron 主进程通过任务桥（`desktop_tasks.py`）调起 Python 后端子命令
- 流水线全链由 `desktop_tasks chain` 单命令驱动，UI 只发命令并渲染进度
- 评审会话走本地 API（`api_server.py`），专家批注、裁决、澄清都在 UI 内完成
- 新运行输出遵循 result-package 布局（见 [07 输出产物说明](./07-outputs.md)）
