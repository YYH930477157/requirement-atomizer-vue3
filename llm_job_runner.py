"""LLMJobRunner：统一 single-shot/batch 付费调用机械（方案 §18，M8 完整版）。

把散落在各消费者里的调用机械收拢到一个可审计入口：
- route/model 解析复用既有权威（``ai_extract.config_for_route``）；
- request identity（``fingerprint``）→ ``PaidCacheStore`` 命中/写入（successful-only）；
- 预算：``LLMRequestBudget`` 透传 ``chat_json_with_meta``（同一记账钩）；
- JSON repair/截断升级由 ``llm_client`` 既有机制承担，meta.call_count>1 如实落账；
- retry 分类：连接/远端错误 → ``retry_kind=connection|remote``（可重试），其余 failed；
- usage/provenance：prompt/completion/total tokens、duration、cache、model 全记录；
- **attempt ledger**：每次尝试（含 cache_hit）一行 governed
  ``llm_job_attempts.jsonl``，携带 stage/processor/unit_id（经 ``call_context``
  同步进 llm_trace 的 context 键——遥测与 trace 同源）；
- 统一失败语义：``execution_status ∈ ok/partial/failed``（§3.5；single-shot 只有
  ok/failed，partial 留给 batch 部分成功）。

红线：本 runner 只做机械统一，不改写任何领域 prompt/guards；tool-loop
（``chat_with_tools``）暂不纳入（§18：第一版只接 budget/telemetry）；消费者迁移
逐个进行，未迁移者行为零变化。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from artifact_store import ArtifactStore
from claim_artifacts import hash_json
from paid_cache_store import PaidCacheStore

LLM_JOB_RUNNER_VERSION = "llm-job-runner-v1"
LLM_JOB_ATTEMPT_SCHEMA = "llm-job-attempt/v1"
LLM_JOB_ATTEMPTS_FILENAME = "llm_job_attempts.jsonl"

EXECUTION_OK = "ok"
EXECUTION_PARTIAL = "partial"
EXECUTION_FAILED = "failed"


def _stable_attempt_id(fingerprint: str, salt: str) -> str:
    return "ATT-" + hash_json("llm-job-attempt",
                              {"fingerprint": fingerprint, "salt": salt})[len("sha256:"):][:20]


@dataclass
class LLMJob:
    """一次可缓存的付费调用单元（single-shot）。"""
    stage: str
    processor: str
    unit_id: str
    system_prompt: str
    user_prompt: str
    route: str
    fingerprint: str = ""          # 空 → 由 runner 按内容权威指纹派生
    purpose: str = ""              # apply_min_tokens 用途键（空=不调下限）
    parent_attempt_id: str = ""

    def resolved_fingerprint(self) -> str:
        if self.fingerprint:
            return self.fingerprint
        return hash_json("llm-job-request", {
            "stage": self.stage, "processor": self.processor,
            "system": self.system_prompt, "user": self.user_prompt,
        })


@dataclass
class LLMJobResult:
    job_fingerprint: str
    execution_status: str
    data: dict[str, Any] | None = None
    error: str = ""
    from_cache: bool = False
    usage: dict[str, int] = field(default_factory=dict)
    call_count: int = 0
    failed_call_count: int = 0
    model: str = ""
    duration_s: float = 0.0
    attempt_id: str = ""
    # 失败时的原始异常（内存态，不持久化）——调用方需要原始异常类型驱动自己的
    # 控制流（如 spec_enrich 的 LLMConnectionError 熔断计数）时按需重抛
    exception: BaseException | None = None

    @property
    def ok(self) -> bool:
        return self.execution_status == EXECUTION_OK


class LLMJobRunner:
    """single-shot 权威入口；batch = run_many（并发经 submit_with_context 保上下文）。"""

    def __init__(self, out_dir, *, route_config: Any | None = None,
                 cache: PaidCacheStore | None = None,
                 request_budget: Any | None = None,
                 chat_with_meta: Callable[..., tuple[dict[str, Any], dict[str, Any]]] | None = None,
                 ledger: ArtifactStore | None = None) -> None:
        from pathlib import Path

        self._root = Path(out_dir).expanduser().resolve()
        self._route_config = route_config
        self._cache = cache
        self._request_budget = request_budget
        self._chat_with_meta = chat_with_meta
        self._ledger = ledger or ArtifactStore(self._root, category="logs")
        self._attempt_seq = 0

    # ---- 解析 ------------------------------------------------------------
    def _resolve_config(self, route: str) -> Any:
        if self._route_config is not None:
            return self._route_config
        from ai_extract import config_for_route

        config = config_for_route(route)
        if config is None:
            raise ValueError(f"无法解析 LLM 路由配置: {route}")
        return config

    def _resolve_chat(self):
        if self._chat_with_meta is not None:
            return self._chat_with_meta
        from llm_client import chat_json_with_meta

        return chat_json_with_meta

    # ---- attempt ledger ----------------------------------------------------
    def _record_attempt(self, row: dict[str, Any]) -> None:
        self._attempt_seq += 1
        row = {
            "schema": LLM_JOB_ATTEMPT_SCHEMA,
            "runner_version": LLM_JOB_RUNNER_VERSION,
            "ts": time.time(),
            "seq": self._attempt_seq,
            **row,
        }
        with self._ledger.locked():
            self._ledger.append_jsonl(LLM_JOB_ATTEMPTS_FILENAME, row)

    # ---- single-shot -------------------------------------------------------
    def run(self, job: LLMJob, *, salt: str = "1") -> LLMJobResult:
        from llm_client import LLMConnectionError, LLMBudgetExceeded, call_context

        fingerprint = job.resolved_fingerprint()
        attempt_id = _stable_attempt_id(fingerprint, salt)
        started = time.time()

        def _finish(result: LLMJobResult, *, outcome: str, retry_kind: str = "none",
                    error: str = "") -> LLMJobResult:
            self._record_attempt({
                "attempt_id": attempt_id,
                "parent_attempt_id": job.parent_attempt_id or "",
                "fingerprint": fingerprint,
                "stage": job.stage,
                "processor": job.processor,
                "unit_id": job.unit_id,
                "route": job.route,
                "outcome": outcome,             # cache_hit|initial|json_repair|truncation|error
                "retry_kind": retry_kind,       # none|connection|remote
                "prompt_tokens": result.usage.get("prompt_tokens", 0),
                "completion_tokens": result.usage.get("completion_tokens", 0),
                "total_tokens": result.usage.get("total_tokens", 0),
                "call_count": result.call_count,
                "failed_call_count": result.failed_call_count,
                "duration_s": round(result.duration_s, 3),
                "cache": "hit" if result.from_cache else
                         ("write" if result.ok and self._cache is not None else "miss"),
                "model": result.model,
                "execution_status": result.execution_status,
                "error": error[:300],
            })
            return result

        # 1) 缓存命中：零 provider 调用
        if self._cache is not None:
            hit = self._cache.lookup(fingerprint)
            if hit is not None:
                payload = hit.get("payload") or {}
                result = LLMJobResult(
                    job_fingerprint=fingerprint, execution_status=EXECUTION_OK,
                    data=payload.get("data") if isinstance(payload.get("data"), dict) else payload,
                    from_cache=True, model=str(payload.get("model") or ""),
                    attempt_id=attempt_id,
                    duration_s=round(time.time() - started, 4))
                return _finish(result, outcome="cache_hit")

        # 2) 真实调用（context 归属 → llm_trace 同源）
        config = self._resolve_config(job.route)
        chat = self._resolve_chat()
        usage: dict[str, int] = {}
        call_count = failed_count = 0
        try:
            with call_context(stage=job.stage, processor=job.processor,
                              unit_id=job.unit_id,
                              parent_attempt_id=job.parent_attempt_id):
                data, meta = chat(config, job.system_prompt, job.user_prompt,
                                  request_budget=self._request_budget)
            meta = meta or {}
            usage = dict(meta.get("usage") or {})
            call_count = int(meta.get("call_count") or 1)
            failed_count = int(meta.get("failed_call_count") or 0)
        except LLMConnectionError as exc:
            if self._cache is not None:
                self._cache.record_failure(fingerprint, str(exc))
            result = LLMJobResult(
                job_fingerprint=fingerprint, execution_status=EXECUTION_FAILED,
                error=f"LLMConnectionError: {exc}", call_count=max(call_count, 1),
                failed_call_count=max(failed_count, 1), model=getattr(config, "model", ""),
                duration_s=round(time.time() - started, 4), attempt_id=attempt_id,
                exception=exc)
            return _finish(result, outcome="error", retry_kind="connection",
                           error=result.error)
        except LLMBudgetExceeded:
            # 预算耗尽是控制流信号不是作业失败：穿透给调用方执行其既有降级语义
            # （文档预算单消费者各自决定 unavailable/NEEDS WORK——不吞）
            raise
        except Exception as exc:  # noqa: BLE001 — 分类落账，不吞错
            if self._cache is not None:
                self._cache.record_failure(fingerprint, str(exc))
            result = LLMJobResult(
                job_fingerprint=fingerprint, execution_status=EXECUTION_FAILED,
                error=f"{type(exc).__name__}: {exc}", call_count=max(call_count, 0),
                failed_call_count=max(failed_count, 1), model=getattr(config, "model", ""),
                duration_s=round(time.time() - started, 4), attempt_id=attempt_id,
                exception=exc)
            return _finish(result, outcome="error", retry_kind="remote",
                           error=result.error)

        # 3) 成功：successful-only 写缓存 + 落账（call_count>1 = repair/截断升级轮）
        if self._cache is not None:
            self._cache.record(fingerprint, {"data": data, "model": getattr(config, "model", "")},
                               meta={"stage": job.stage, "processor": job.processor,
                                     "unit_id": job.unit_id})
        result = LLMJobResult(
            job_fingerprint=fingerprint, execution_status=EXECUTION_OK, data=data,
            usage=usage, call_count=call_count, failed_call_count=failed_count,
            model=getattr(config, "model", ""),
            duration_s=round(time.time() - started, 4), attempt_id=attempt_id)
        outcome = "initial" if call_count <= 1 else "json_repair"
        return _finish(result, outcome=outcome)

    # ---- batch ---------------------------------------------------------------
    def run_many(self, jobs: Iterable[LLMJob], *, concurrency: int = 1,
                 progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from context_submit import submit_with_context

        job_list = list(jobs)
        results: list[LLMJobResult] = [None] * len(job_list)  # type: ignore[list-item]
        tokens = 0
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            futures = {
                submit_with_context(executor, self.run, job): index
                for index, job in enumerate(job_list)
            }
            done_count = 0
            for future in as_completed(futures):
                index = futures[future]
                results[index] = future.result()
                tokens += results[index].usage.get("total_tokens", 0)
                done_count += 1
                if progress is not None:
                    progress(done_count, len(job_list))
        ok_count = sum(1 for result in results if result.ok)
        failed_count = len(results) - ok_count
        cached_count = sum(1 for result in results if result.from_cache)
        status = (EXECUTION_OK if failed_count == 0
                  else EXECUTION_PARTIAL if ok_count else EXECUTION_FAILED)
        return {
            "schema": "llm-job-batch/v1",
            "runner_version": LLM_JOB_RUNNER_VERSION,
            "execution_status": status,
            "total": len(results),
            "ok": ok_count,
            "failed": failed_count,
            "cached": cached_count,
            "total_tokens": tokens,
            "results": results,
        }
