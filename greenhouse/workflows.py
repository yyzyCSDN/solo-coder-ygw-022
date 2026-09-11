from __future__ import annotations

from typing import Any

from .engine import Engine


class WorkflowExtensions:
    """Thin adapter that keeps baseline workflow state and device evidence together."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def open(self, flow: str, request_id: str, asset_ids: list[str], **payload: Any) -> dict[str, Any]:
        return self.engine.baseline.create_job(flow, request_id, asset_ids, **payload)

    def start(self, job_id: int) -> dict[str, Any]:
        return self.engine.baseline.advance_job(job_id, "running")

    def complete(self, job_id: int) -> dict[str, Any]:
        return self.engine.baseline.advance_job(job_id, "completed")

    def fail(self, job_id: int, reason: str) -> dict[str, Any]:
        job = self.engine.baseline.advance_job(job_id, "failed")
        self.engine.events.publish("domain-baseline", "job-failed", str(job_id), {"reason": reason})
        return job

    def observe(self, asset_id: str, signal: str, value: float, **evidence: Any) -> dict[str, Any]:
        return self.engine.baseline.record_signal(asset_id, signal, value, **evidence).__dict__

    def command_once(self, asset_id: str, action: str, idempotency_key: str, **parameters: Any) -> dict[str, Any]:
        return self.engine.baseline.issue_action(asset_id, action, idempotency_key, **parameters)
