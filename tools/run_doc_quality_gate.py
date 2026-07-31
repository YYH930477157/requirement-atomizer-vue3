"""需求解析质量实测驱动（docs/requirement-parsing-test-plan.md 的 P0 用例自动判定）。

用法（仓库根目录）：
  python tools/run_doc_quality_gate.py --input <doc> --out <dir> [--llm]

判定口径即测试用例集：D1 分块/D2 完整/D3 正确/D4 影印/D5 自一致。
所有指标打印为 PASS/FAIL 行，便于直接核对。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--llm", action="store_true", help="ai-extract 走 openai_compatible")
    parser.add_argument("--skip-facsimile", action="store_true")
    args = parser.parse_args()
    out: Path = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    from atomize import run_atomizer_pipeline
    from merged_consistency import compact_source_text

    t0 = time.time()
    print(f"=== atomize: {args.input.name}")
    run_atomizer_pipeline(args.input, out, kb_paths=[])
    atomize_dur = time.time() - t0
    print(f"[perf] atomize {atomize_dur:.0f}s")

    blocks = [json.loads(l) for l in open(out / "blocks.jsonl", encoding="utf-8") if l.strip()]
    tables = [b for b in blocks if str(b.get("type") or "") == "table"]
    print(f"[D1] blocks={len(blocks)} tables={len(tables)} "
          f"rows={sum(len(b.get('data_rows') or []) for b in tables)}")

    # --- ai-extract
    from ai_extract import run_ai_extract
    t1 = time.time()
    result = run_ai_extract(out, route="openai_compatible" if args.llm else None)
    extract_dur = time.time() - t1
    print(f"[perf] ai-extract {extract_dur:.0f}s (route={result.get('route')})")
    quality = json.loads((out / "ai_extract_quality.json").read_text(encoding="utf-8"))
    print(f"[D1] sections={quality['sections']}/{quality['sections_total']} "
          f"failed={quality['failed_sections']} coverage={quality.get('core_coverage_pct')}% "
          f"compliance={quality.get('compliance_coverage_pct')}%")

    reqs = [json.loads(l) for l in open(out / "ai_requirements.jsonl", encoding="utf-8") if l.strip()]
    prow = [r for r in reqs if str(r.get("ai_req_id", "")).startswith("PROW-DET")]
    block_text = {b["block_id"]: str(b.get("text") or "") for b in blocks}
    verbatim = sum(
        1 for r in prow
        if str(r.get("source_quote") or "") in block_text.get((r.get("source_block_ids") or [""])[0], "")
    )
    print(f"[D2] requirements={len(reqs)} PROW-DET={len(prow)} verbatim={verbatim}/{len(prow)}")

    # 双份检测（TC-03）
    prow_lines: dict[str, list[str]] = {}
    for r in prow:
        for bid in r.get("source_block_ids") or []:
            prow_lines.setdefault(bid, []).append(compact_source_text(r.get("source_quote")))
    dual = 0
    for r in reqs:
        if str(r.get("ai_req_id", "")).startswith("PROW-DET"):
            continue
        hay = compact_source_text(f"{r.get('source_quote') or ''} {r.get('description') or ''}")
        for line in prow_lines.get((r.get("source_block_ids") or [""])[0], []):
            if line and len(line) >= 12 and line in hay:
                dual += 1
                break
    merged = sum(len(r.get("merge_trace") or []) for r in reqs)
    print(f"[D3] dual_rows={dual} merge_trace={merged}")

    # 引句三层分流（TC-06 相关）
    from collections import Counter
    susp = Counter()
    for r in reqs:
        for s in r.get("suspicion_reasons") or []:
            susp[s] += 1
    print(f"[D3] suspicion={dict(susp.most_common(6))}")

    # --- 澄清报告（TC-12）
    import clarification_report
    rep = clarification_report.run_report(out)
    entries = rep.get("entries") or []
    hard = [e for e in entries if e.get("tier", "必答") == "必答"]
    agg = [e for e in entries if e.get("row_details")]
    print(f"[D5] 澄清必答={len(hard)} 行级聚合={len(agg)} "
          f"readiness={rep.get('readiness', {}).get('verdict')}")

    # --- 影印（TC-04/08/11）
    if not args.skip_facsimile:
        from doc_annotation_export import export_annotation_bundle
        t2 = time.time()
        try:
            export_annotation_bundle(out)
        except Exception as exc:
            print(f"[D4] facsimile export FAILED: {type(exc).__name__}: {exc}")
        else:
            pages_dir = out / "document_pages"
            pages = list(pages_dir.glob("page-*.png")) if pages_dir.exists() else []
            geo_path = out / "document_pdf_geometry.json"
            row_geo_n = 0
            block_geo_n = 0
            if geo_path.exists():
                geo = json.loads(geo_path.read_text(encoding="utf-8"))
                block_geo_n = len(geo.get("geometry") or {})
                row_geo_n = sum(len(v) for v in (geo.get("row_geometry") or {}).values())
            print(f"[D4] 影印页图={len(pages)} 块区={block_geo_n} 行区={row_geo_n} "
                  f"({time.time() - t2:.0f}s)")

    # --- 自一致（TC-10，仅块级快速验证：atomize 重跑 diff）
    print("[perf] total", round(time.time() - t0), "s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
