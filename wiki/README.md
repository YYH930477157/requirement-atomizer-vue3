# Requirement Atomizer Wiki

Requirement Atomizer 是一个本地化的技术标准需求原子化工具：把 DOCX/XLSX/PDF 形式的
客户技术标准（如 DLMS/COSEM 智能电表规范）解析、抽取、评审为研发可落地的原子需求，
最终产出实现规格与软件需求交付物。

- 桌面产品：**Vue3 + Electron** 前端（`ui/`）+ Python 后端
- 核心理念：**确定性骨架 + 护栏化 LLM** —— 数字/编码/结构永远走确定性通道，LLM 只做判断与叙述，每一步可溯源、可回归

## 目录

| 页面 | 内容 |
|---|---|
| [01 项目概述](./01-overview.md) | 定位、能力边界、双轨流水线（A 轨 / B 轨） |
| [02 安装与运行环境](./02-install.md) | 依赖安装、测试命令、环境注意事项 |
| [03 CLI 使用指南](./03-cli-guide.md) | `ratomizer` 命令、全链流水线、退出码契约 |
| [04 桌面应用](./04-desktop-app.md) | Vue3 + Electron 应用的开发运行与打包 |
| [05 知识库](./05-knowledge-base.md) | Obsidian Vault、运行时 KB 编译与检索 |
| [06 LLM 配置](./06-llm-config.md) | 模型路由、API Key 与预算控制 |
| [07 输出产物说明](./07-outputs.md) | 输出目录结构、result-package 布局与关键文件 |

## 延伸阅读（仓库内文档）

- CLI 机器契约：`docs/cli-contract.md`
- 平台设计：`docs/requirement-atomizer-platform-overview-design.md`
- 系统架构地图：`ARCHITECTURE.md`
- 数据契约：`schemas/`（JSON Schema draft-2020-12）
