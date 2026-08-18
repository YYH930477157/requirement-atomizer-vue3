"""M2 §4.2（去原子化修复方案，2026-08-15）：功能级定向重抽。

直抽模式（target store=functional_requirements.json）下 claim queue 的执行体：
从受影响块扩展到完整条款族（``extract_units.clause_key`` 两级族键，宁多勿漏），
只对受影响条款族重新真实抽取，删旧留新合并，全量重算 anchors+conservation，
**只有 execution_status=ok 且 conservation.ok=true 才原子替换产物**，随后走
``publish_b_track_shadow`` 重新发布 B 轨 shadow（发布内部自带 effective fold）。

纪律（与仓库硬约束同源）：
- CAS：当前产物 fingerprint != expected_product_fingerprint 即响亮 abort，不写任何文件；
- stub/mixed/partial/失败/不守恒一律 ``FunctionalReextractUnhealthy`` 响亮 raise，
  健康产物分毫不动（不得把失败记成功、不得伪装 LLM 输出）；
- 原子替换复用 ``functional_extract._replace_with_retry``（tmp + os.replace +
  PermissionError 线性重试——Windows 读者会短暂阻塞替换）；
- 未受影响 FRE 逐字节保留（不重排、不改写），锚/UID 只做幂等重算；
- ``functional_extract.py`` 本模块只 import 不修改（另一线程拥有该文件）。
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("requirement_atomizer")

FUNCTIONAL_REEXTRACT_VERSION = "functional-reextract-v1"
FUNCTIONAL_REEXTRACT_PATCH_SCHEMA = "functional-reextract-patch/v1"
FUNCTIONAL_REEXTRACT_MUTATION_SCHEMA = "claim-reextract-mutation/v1"


class FunctionalReextractError(RuntimeError):
    """定向重抽失败（基类）。"""


class FunctionalReextractConflict(FunctionalReextractError):
    """产物 CAS 失配——当前 functional 产物已不是请求时看到的那份。"""


class FunctionalReextractUnhealthy(FunctionalReextractError):
    """重抽产物不健康（stub/mixed/partial/failed/不守恒）——不得覆盖健康产物。"""


class FunctionalReextractCacheRefreshError(FunctionalReextractError):
    """复审三轮 P1-1：产品替换**前**的缓存行失效无法确认——产物未动即失败，
    CAS 干净重试，不产生半提交状态（产品已变而 WAL 未记的窗口已消除）。"""


def _cache_row_matches(payload: dict[str, Any], expected: dict[str, Any]) -> bool:
    """读回校验：缓存行载荷与期望合并产物逐键一致（含 reextract 留痕/版本）。"""
    if not isinstance(payload, dict):
        return False
    keys = ("fingerprint", "execution_status", "reextract_version",
            "functional_requirements", "items", "conservation")
    return all(payload.get(key) == expected.get(key) for key in keys)


def _invalidate_cache_entry(root: Path, fingerprint: str) -> bool:
    """删除指定指纹的缓存行；成功 True（行本就不存在也算成功）。"""
    import json as _json
    import os as _os
    import tempfile as _tempfile

    import functional_extract as fe
    from process_file_lock import process_file_lock
    from result_package import governed_artifact_path

    path = fe._cache_path(root, for_write=True)
    lock_path = governed_artifact_path(
        root, "functional_extract_cache.lock", category="cache", for_write=True)
    tmp: Path | None = None
    try:
        with process_file_lock(lock_path, timeout_s=10.0, label="functional_reextract_cache"):
            if path.is_file():
                kept = [
                    line for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                    and _json.loads(line).get("fingerprint") != fingerprint
                ]
                with _tempfile.NamedTemporaryFile(
                    mode="w", dir=path.parent, prefix=".functional_extract_cache.",
                    suffix=".tmp", delete=False, encoding="utf-8", newline="\n",
                ) as handle:
                    tmp = Path(handle.name)
                    for line in kept:
                        handle.write(line + "\n")
                    handle.flush()
                    _os.fsync(handle.fileno())
                fe._replace_with_retry(tmp, path)
                tmp = None
        return True
    except Exception:  # noqa: BLE001 — 删不掉就交给调用方判定
        return False
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _invalidate_cache_entry_verified(root: Path, fingerprint: str) -> None:
    """产品替换**前**严格失效旧缓存行：删除 → 读回确认消失 → 重试 → 仍失败响亮 raise。

    失败发生在产物变化之前——CAS 干净重试，不产生半提交（复审三轮 P1-1）。
    """
    import time

    import functional_extract as fe

    for attempt in range(3):
        if not _invalidate_cache_entry(root, fingerprint):
            break
        if fingerprint not in fe._read_cache(root):
            return
        time.sleep(0.02 * (attempt + 1))
    raise FunctionalReextractCacheRefreshError(
        f"产品替换前缓存行失效失败（fingerprint={fingerprint[:16]}…）"
        "——产物未动，请检查缓存卷后重试"
    )


def _write_cache_best_effort(
    root: Path, fingerprint: str, payload: dict[str, Any],
) -> bool:
    """产品提交+WAL 之后的缓存行写入：读回校验，失败保持 miss（非致命）。

    缓存 miss 的后果只是后续普通直抽走全量真实抽取（正确但付费）；确定性恢复
    负责其后的 Claim 重发布与 fold——此处任何失败都不再影响队列终态。
    """
    import time

    import functional_extract as fe

    for attempt in range(3):
        try:
            # 写入异常不在此处判定成败——``_write_cache_entry`` 可能吞错，
            # 唯一可信判据是**读回校验**。
            fe._write_cache_entry(root, fingerprint, payload)
        except Exception:  # noqa: BLE001 — 由读回校验裁决
            pass
        row = fe._read_cache(root).get(fingerprint)
        if row is not None and _cache_row_matches(dict(row.get("payload") or {}), payload):
            return True
        time.sleep(0.02 * (attempt + 1))
    return False


def functional_product_path(out_dir: Path | str, *, for_write: bool = False) -> Path:
    """解析 functional 产物路径（读：governed 优先、根目录兜底；写：governed）。"""
    from functional_extract import FUNCTIONAL_REQUIREMENTS_FILENAME
    from result_package import governed_artifact_path

    root = Path(out_dir).expanduser().resolve()
    if for_write:
        return governed_artifact_path(
            root, FUNCTIONAL_REQUIREMENTS_FILENAME, category="pipeline",
        )
    governed = governed_artifact_path(
        root, FUNCTIONAL_REQUIREMENTS_FILENAME, category="pipeline", for_write=False,
    )
    if governed.is_file() or governed == root / FUNCTIONAL_REQUIREMENTS_FILENAME:
        return governed
    legacy = root / FUNCTIONAL_REQUIREMENTS_FILENAME
    return legacy if legacy.is_file() else governed


def functional_product_fingerprint(out_dir: Path | str) -> str:
    """当前 functional 产物的 product fingerprint（文件 sha256；缺席为空串）。"""
    from claim_artifacts import file_sha256

    path = functional_product_path(out_dir, for_write=False)
    return file_sha256(path) if path.is_file() else ""


def _read_current_payload(root: Path) -> tuple[Path, dict[str, Any]]:
    """读当前直抽产物（governed 优先、根目录兜底，与 _read_functional_requirements_payload 同口径）。"""
    path = functional_product_path(root, for_write=False)
    if not path.is_file():
        raise FunctionalReextractConflict(
            "functional product is absent; nothing to re-extract against"
        )
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FunctionalReextractConflict(
            f"functional product is not readable JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict) or not str(payload.get("producer") or "").startswith(
        "functional-extract"
    ):
        raise FunctionalReextractConflict(
            "functional product producer is not the functional-extract family; "
            "refusing to patch a foreign store"
        )
    items = payload.get("items")
    if not isinstance(items, list):
        raise FunctionalReextractConflict("functional product has no items list")
    return path, payload


def _affected_clause_family(
    sections: list[dict[str, Any]],
    affected_block_ids: list[str],
) -> list[dict[str, Any]]:
    """受影响块 → 完整条款族（两级族键同 extract_units.clause_key，宁多勿漏）。

    族 = 命中块所在条款 + 与之共享两级族键的全部条款（4.6.1 Requirements 与
    4.6.2 Test 是一个需求整体）。无编号条款（key=None）只含命中条款自身。
    """
    from extract_units import clause_key

    affected = {str(value) for value in affected_block_ids if str(value)}
    if not affected:
        raise FunctionalReextractError("affected_block_ids must not be empty")
    hit = {
        index
        for index, section in enumerate(sections)
        if affected & {str(b) for b in (section.get("block_ids") or []) if str(b)}
    }
    if not hit:
        raise FunctionalReextractError(
            "affected blocks do not belong to any clause under the output directory: "
            + ", ".join(sorted(affected))
        )
    family_keys = {
        key
        for key in (clause_key(sections[index]) for index in hit)
        if key is not None
    }
    family: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        key = clause_key(section)
        if index in hit or (key is not None and key in family_keys):
            family.append(section)
    return family


def _item_block_ids(item: dict[str, Any]) -> set[str]:
    """item 声明/锚定的块集合（锚优先，source_block_ids 兜底）。"""
    blocks: set[str] = set()
    anchors = item.get("evidence_anchors")
    if isinstance(anchors, list):
        for anchor in anchors:
            if isinstance(anchor, dict):
                blocks.update(
                    str(b) for b in (anchor.get("block_ids") or []) if str(b)
                )
    blocks.update(
        str(b) for b in (item.get("source_block_ids") or []) if str(b)
    )
    return blocks


def _patch_supplement_id(
    *,
    affected_block_ids: list[str],
    family_section_ids: list[str],
    replaced_ids: list[str],
    new_ids: list[str],
    request_idempotency_key: str,
) -> str:
    """确定性补丁身份。WAL 合同（claim_reextract_attempt.schema.json）要求
    ``^SUP-[0-9a-f]{12}$``——功能级补丁沿用该格式（patch 自身的 schema 字段
    ``functional-reextract-patch/v1`` 才是形态判别），不改持久化读合同。"""
    from claim_artifacts import hash_json

    return "SUP-" + hash_json(
        FUNCTIONAL_REEXTRACT_PATCH_SCHEMA,
        {
            "version": FUNCTIONAL_REEXTRACT_VERSION,
            "affected_block_ids": sorted(str(b) for b in affected_block_ids),
            "family_section_ids": list(family_section_ids),
            "replaced_requirement_ids": sorted(replaced_ids),
            "new_requirement_ids": sorted(new_ids),
            "request_idempotency_key": str(request_idempotency_key or ""),
        },
    ).removeprefix("sha256:")[:12]


def republish_functional_claim_shadow(
    out_dir: Path | str,
    *,
    route: str | None,
) -> dict[str, Any]:
    """直抽模式 claim shadow 重发布（确定性、零 LLM）。

    与 ``desktop_tasks._publish_functional_claim_shadow`` 同一调用形态：目录来自
    解析产物，coverage target = FRE 条目；``publish_b_track_shadow`` 内部自带
    effective fold（fold 失败只记日志不阻断——base generation 已权威提交，
    队列 finalize 阶段会再次 fold 并校验新鲜度）。
    """
    import claim_ledger
    from claim_artifacts import FUNCTIONAL_REQUIREMENTS_STORE
    from claim_catalog import build_catalog_from_directory
    from requirements_analysis_rules import _read_functional_requirements_payload

    root = Path(out_dir).expanduser().resolve()
    payload = _read_functional_requirements_payload(root) or {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    published = claim_ledger.publish_b_track_shadow(
        root,
        run_id=uuid.uuid4().hex,
        route_mode="stub" if route == "stub" else "llm",
        extraction_status="success",
        catalog_build=build_catalog_from_directory(root, scope="full"),
        requirements=[row for row in items if isinstance(row, dict)],
        requirements_store=FUNCTIONAL_REQUIREMENTS_STORE,
    )
    generation = dict(published.get("generation_meta") or {})
    return {
        "kind": "functional-claim-shadow-republish",
        "store": FUNCTIONAL_REQUIREMENTS_STORE,
        "generation_run_id": generation.get("run_id"),
        "requirements_sha256": generation.get("requirements_sha256"),
        "catalog_count": generation.get("catalog_count"),
    }


def functional_targeted_reextract(
    out_dir: Path | str,
    *,
    affected_block_ids: list[str],
    expected_product_fingerprint: str,
    route: str,
    chat: Callable[[str, str], dict[str, Any]] | None = None,
    request_idempotency_key: str = "",
    pre_publish_check: Callable[[], None] | None = None,
    on_supplement_persisted: Callable[[dict[str, Any]], None] | None = None,
    on_publication_prepared: Callable[[dict[str, Any]], None] | None = None,
    on_requirements_published: Callable[[list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    """§4.2 功能级定向重抽：只重抽受影响条款族，健康才原子替换，替换后重发布。

    ``chat`` 注入用于测试（真实路径由调用方包装 route config 与预算）；四个回调
    与原子级 ``targeted_reextract`` 的 claim_execution 钩子同族：
    ``pre_publish_check``（付费响应后、发布前的 CAS 复核）、
    ``on_supplement_persisted``（补丁意图先进 attempt WAL）、
    ``on_publication_prepared``（产品替换**前**把 publication 事实的恢复原料
    ——target store + 新旧产品哈希——先进 attempt WAL；复审四轮 P1-1）、
    ``on_requirements_published``（产物提交后立即记账，恢复路径依赖）。
    """
    import functional_extract as fe

    root = Path(out_dir).expanduser().resolve()
    sections = list(fe.load_clauses(root))
    if not sections:
        raise FunctionalReextractError("no clauses are available for re-extraction")

    product_path, payload = _read_current_payload(root)
    # §17 unit 路由同口径：产物在 clause_family 路由下生成时，重抽的条款池与守恒基线
    # 用当前代码确定性重算路由（不信产物记录的清单——与守恒永远现算同纪律）；legacy
    # 产物零变化。指向被路由出表格块的 claim 会找不到条款族 → 如实报错（表格归 A 轨）。
    if str(payload.get("context_pack_strategy") or "legacy") == "clause_family":
        sections, _routing_meta = fe.apply_unit_routing(
            sections, blocks=fe._load_blocks(root), out_dir=root)
        if not sections:
            raise FunctionalReextractError(
                "all clauses are routed out of the B track by unit routing; "
                "there is no functional scope to re-extract")

    family = _affected_clause_family(sections, list(affected_block_ids))
    family_block_ids = {
        str(b)
        for section in family
        for b in (section.get("block_ids") or [])
        if str(b)
    }

    from claim_artifacts import file_sha256

    current_fingerprint = file_sha256(product_path)
    if (
        str(expected_product_fingerprint or "").strip()
        and current_fingerprint != expected_product_fingerprint
    ):
        raise FunctionalReextractConflict(
            "functional product changed since the paid confirmation "
            f"(expected sha256 {expected_product_fingerprint}, "
            f"current {current_fingerprint}); refresh before re-extraction"
        )
    items = [row for row in payload.get("items") or [] if isinstance(row, dict)]

    # 真实重抽（注入 chat 或真实 route；宁多勿漏的完整条款族上下文）。
    # 2026-08-18：策略随产物走——clause_family 产物的重抽也用 clause_family 包
    # （条款整文进包 + prompt v4 保真落数），legacy 切片重抽丢表号会让重试白付。
    payload_strategy = str(payload.get("context_pack_strategy") or "legacy")
    new_items, executed_route = fe.extract_functional_requirements(
        family,
        chat=chat,
        route=route,
        blocks=fe._load_blocks(root),
        strategy=payload_strategy,
    )
    status = fe.execution_status(
        route, executed_route,
        requested_label=fe._resolve_route_label(route, chat),
    )
    if status != "ok":
        raise FunctionalReextractUnhealthy(
            f"functional targeted re-extraction did not complete cleanly "
            f"(execution_status={status}, route={executed_route}, "
            f"route_requested={route}); the healthy product is left untouched"
        )
    if not new_items:
        raise FunctionalReextractUnhealthy(
            "functional targeted re-extraction produced no items; "
            "the healthy product is left untouched"
        )

    # 删旧留新：与受影响条款族相交（锚或声明块）的旧 FRE 整体替换，其余逐字节保留。
    kept_flags = [
        not (_item_block_ids(item) & family_block_ids)
        for item in items
    ]
    kept = [item for item, keep in zip(items, kept_flags) if keep]
    replaced = [item for item, keep in zip(items, kept_flags) if not keep]
    merged = [*kept, *new_items]

    # 全量重算（幂等）：UID 按全量 sections 的条款序号定位，锚/守恒对合并集重算。
    fe.assign_stable_uids(merged, sections)
    fe.assign_evidence_anchors(merged, sections)
    conservation = fe.conservation_report(sections, merged, blocks=fe._load_blocks(root))
    if conservation.get("ok") is not True:
        categories = conservation.get("failure_categories") or []
        raise FunctionalReextractUnhealthy(
            "functional targeted re-extraction broke conservation "
            f"(failure_categories={categories}); the healthy product is left untouched"
        )

    kept_ids = [str(row.get("functional_requirement_id") or "") for row in kept]
    replaced_ids = [str(row.get("functional_requirement_id") or "") for row in replaced]
    new_ids = [str(row.get("functional_requirement_id") or "") for row in new_items]
    family_section_ids = [str(section.get("section_id") or "") for section in family]
    supplement_id = _patch_supplement_id(
        affected_block_ids=list(affected_block_ids),
        family_section_ids=family_section_ids,
        replaced_ids=replaced_ids,
        new_ids=new_ids,
        request_idempotency_key=request_idempotency_key,
    )
    patch = {
        "schema": FUNCTIONAL_REEXTRACT_PATCH_SCHEMA,
        "supplement_id": supplement_id,
        "version": FUNCTIONAL_REEXTRACT_VERSION,
        "affected_block_ids": [str(b) for b in affected_block_ids],
        "family_section_ids": family_section_ids,
        "replaced_requirement_ids": replaced_ids,
        "new_requirement_ids": new_ids,
        "kept_requirement_ids": kept_ids,
        "origin": {
            "kind": "claim_queue",
            "request_idempotency_key": str(request_idempotency_key or ""),
        },
        "route_requested": route,
        "route": executed_route,
    }

    # 补丁意图先进 WAL（require_published_attempt 要求 supplement 在 publication 之前）。
    if callable(on_supplement_persisted):
        on_supplement_persisted(patch)

    # 付费响应之后的发布前 CAS 复核（与原子路径同款两段 CAS）。
    if callable(pre_publish_check):
        pre_publish_check()

    new_payload = dict(payload)
    new_payload.update({
        "route_requested": route,
        "route": executed_route,
        "execution_status": status,
        "draft": executed_route == "stub",
        "clause_count": len(sections),
        "functional_requirements": len(merged),
        "conservation": conservation,
        "items": merged,
        # 复审三轮 P1-1：lineage 键必须在序列化前进 update 块——随产物文件、
        # 缓存行与 claim 文件哈希绑定链全程携带。
        "reextract_version": FUNCTIONAL_REEXTRACT_VERSION,
        # 定向重抽留痕：合并 provenance（替换/保留清单 + 幂等键），不伪装成整跑。
        "reextract": {
            "schema": FUNCTIONAL_REEXTRACT_PATCH_SCHEMA,
            "supplement_id": supplement_id,
            "version": FUNCTIONAL_REEXTRACT_VERSION,
            "affected_block_ids": [str(b) for b in affected_block_ids],
            "family_section_ids": family_section_ids,
            "replaced_requirement_ids": replaced_ids,
            "kept_requirement_ids": kept_ids,
            "request_idempotency_key": str(request_idempotency_key or ""),
            "executed_route": executed_route,
        },
    })
    # §17：路由审计块随重抽刷新（确定性重算的当前事实；legacy 产物本就无此块）。
    if isinstance(payload.get("unit_routing"), dict):
        new_payload["unit_routing"] = _routing_meta

    import json

    from claim_artifacts import sha256_bytes
    from input_completeness import attach_input_completeness

    attach_input_completeness(new_payload, root)

    # 复审三轮 P1-1：提交顺序重排，消除半提交状态——
    #   ① 产品替换**前**严格失效旧缓存行（读回确认该行消失；失败 → 产物分毫
    #      未动，CAS 干净重试；失效后旧缓存 miss，绝不恢复重抽前产物）；
    #   ①' 产品替换**前**持久化 publication_prepared（target store + 新旧产品
    #      哈希，新哈希对即将写入的确切字节计算）——此后"产品已替换、
    #      requirements_published 未落账"的任何中断（WAL 追加失败/进程崩溃）
    #      都能由恢复侧按当前产品哈希确定性路由（复审四轮 P1-1）；
    #   ② 产品原子替换；
    #   ③ 立即记录 requirements_published WAL（此后任何中断走确定性恢复）；
    #   ④ 新缓存行**尽力而为**写入（失败 = 保持 cache miss，交由确定性恢复完成
    #      Claim 重发布与 fold）——不再存在"产品已变、WAL 未记"却把队列拖入
    #      failed 终态的路径（同幂等键重放不再卡死在 failed）。
    cache_fingerprint = str(new_payload.get("fingerprint") or "")
    if cache_fingerprint:
        _invalidate_cache_entry_verified(root, cache_fingerprint)

    # 确切字节：序列化一次、哈希与落盘共用——publication_prepared 的新哈希
    # 严格等于即将写入文件的 sha256（write_bytes 不做换行翻译）。
    content = (
        json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    if callable(on_publication_prepared):
        on_publication_prepared({
            "target_store": "functional_requirements.json",
            "requirements_sha256": sha256_bytes(content),
            "previous_requirements_sha256": current_fingerprint,
            "supplement_id": supplement_id,
        })

    tmp = product_path.with_suffix(product_path.suffix + ".tmp")
    tmp.write_bytes(content)
    fe._replace_with_retry(tmp, product_path)

    if callable(on_requirements_published):
        on_requirements_published(merged)

    if cache_fingerprint:
        _write_cache_best_effort(root, cache_fingerprint, new_payload)

    republish = republish_functional_claim_shadow(root, route=route)
    return {
        "schema": FUNCTIONAL_REEXTRACT_MUTATION_SCHEMA,
        "store": "functional_requirements.json",
        "supplement": patch,
        "requirements": len(new_items),
        "replaced_count": len(replaced),
        "effective_count": len(merged),
        "execution_status": status,
        "conservation_ok": True,
        "republish": republish,
        "written": [str(product_path)],
    }
