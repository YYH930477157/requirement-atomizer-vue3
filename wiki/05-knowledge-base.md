# 05 知识库

知识库以 Obsidian Vault 为人类编辑源，编译为运行时 JSON：

```text
obsidian-vault/             # 人类维护的 Markdown 源
knowledge_bases/*.json      # 运行时 KB 文件
requirement_kb/             # 可复用 Python 包
```

## 双轨 KB 约定（勿“统一”）

- **运行时默认**（CLI 默认 + GUI 预设）：单个
  `knowledge_bases/compiled_from_obsidian.json`
- **黄金基准**：三个种子 KB（`energy_metering.json`、
  `energy_metering_protocol_layer.json`、`energy_metering_cosem_classes.json`）
  + domain-pack，用于再生成 `out/abnt_nbr_16968_atomizer_v5/` 基线

用错 KB 会造成假漂移，二者是刻意分离的。

## 编译 Vault

```powershell
python -m requirement_kb.obsidian compile `
  --vault ".\obsidian-vault" `
  --out ".\knowledge_bases\compiled_from_obsidian.json" `
  --kb-id "obsidian_energy_metering"
```

## 检索与校验

```powershell
python -m requirement_kb.cli info
python -m requirement_kb.cli search "class 8"
python -m requirement_kb.cli search "Profile Generic" --scope class
python -m requirement_kb.cli search "1-0:99.1.0.255" --scope object
python -m requirement_kb.schema ".\knowledge_bases\energy_metering.json"   # 校验
```

`--scope` 支持 `concept` / `protocol` / `class` / `object`，
用于在单个编译 KB 内划分逻辑层边界。

## 本地 HTTP API

```powershell
python -m requirement_kb.server --host 127.0.0.1 --port 8765
```

外部工具应依赖 `requirement_kb` 包，而不是旧的根级 KB 脚本。

## 蓝皮书覆盖度

编译后的 Obsidian KB 内置蓝皮书种子知识（DLMS UA 1000-1 Ed. 16：
Part 1 OBIS 结构、Part 2 COSEM 接口类）。刷新覆盖度报表：

```powershell
python -m requirement_kb.cli blue-book-report `
  --kb ".\knowledge_bases\compiled_from_obsidian.json" `
  --out ".\docs\blue-book-kb-coverage-report.json"
```

## 检索哲学

所有知识注入（模板知识 / 蓝皮书 / 裁决样本库）均为**确定性词面匹配，
零向量语义**——宁漏勿错。基线可被跨条款引用、术语定义、澄清答复有据扩展，
绝不被模板默认值或范例扩展（防搬运）。
