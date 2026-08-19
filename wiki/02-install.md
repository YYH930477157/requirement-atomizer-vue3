# 02 安装与运行环境

## 环境要求

| 组件 | 要求 |
|---|---|
| Python | >= 3.11（`pyproject.toml` 声明；请勿硬依赖更高版本特性） |
| Node.js | 推荐 LTS 22（Node 24 会破坏 electron 安装，见下方坑位） |
| 操作系统 | Windows 为主（桌面打包与部分测试依赖本机路径） |

## 安装后端依赖

```powershell
pip install -r .\requirements.txt
```

运行时依赖只有六个：`python-docx`、`PyYAML`、`openpyxl`、`pdfplumber`、
`jsonschema`、`pywin32`（仅 Windows）。

如需桌面打包（PyInstaller）：

```powershell
pip install -e .[package]
```

## 安装前端依赖

```powershell
cd .\ui
npm install
```

## 运行测试

后端（在仓库根目录）：

```powershell
python -m unittest discover -s tests
```

> 注意：本项目**没有安装 pytest**，README 中的 `python -m pytest -q` 已过时。
> 测试必须是 `unittest.TestCase`，模块级 `def test_*` 会被静默跳过。

前端（在 `ui/` 目录）：

```powershell
npm test         # vitest
npm run build    # vue-tsc --noEmit + vite build（类型检查在这里）
```

> 若 PowerShell 执行策略阻止 `npm.ps1`，可用 `cmd /c "npm test"` 代替，
> 该问题同样影响 `npm run desktop:pack`。

## 已知环境坑位

- **Node 24 破坏 `extract-zip`**：electron 安装会静默失败。修复方法是把
  `%LOCALAPPDATA%\electron\Cache\<hash>\` 下缓存的 electron zip 用
  `Expand-Archive` 解压到 `ui/node_modules/electron/dist`，并写入
  `ui/node_modules/electron/path.txt`（内容为 `electron.exe`）。
  根治方案：使用 Node LTS 22。electron-builder 打包不受影响。
- **GUI 测试**：未安装 PySide6 时自动跳过（`gui/` 已冻结，不影响主流程）。
- **API Key**：只允许放在环境变量（如 `RATOMIZER_LLM_API_KEY`），
  配置文件里只存变量名，绝不明文入库。
