from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .engine import Engine


class Operations:
    """Read-only operational views over the core engine and domain baseline."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def overview(self) -> dict[str, Any]:
        core = self.engine.dashboard()
        baseline = self.engine.baseline.snapshot()
        return {
            "domain": baseline["contract"]["domain"],
            "entities": core["total"],
            "assets": len(baseline["assets"]),
            "signals": len(baseline["signals"]),
            "actions": len(baseline["actions"]),
            "jobs": len(baseline["jobs"]),
        }

    def capacity(self, limit: float) -> dict[str, Any]:
        used = sum(entity.quantity for entity in self.engine.entities())
        limit = max(0.0, float(limit))
        return {"used": round(used, 3), "limit": limit, "remaining": round(max(0.0, limit-used), 3), "over": used > limit}

    def consistency(self) -> dict[str, Any]:
        entities = self.engine.entities()
        entity_ids = [entity.id for entity in entities]
        assets = self.engine.baseline.snapshot()["assets"]
        asset_ids = [asset["asset_id"] for asset in assets]
        problems = []
        if len(entity_ids) != len(set(entity_ids)): problems.append("duplicate entity id")
        if len(asset_ids) != len(set(asset_ids)): problems.append("duplicate asset id")
        invalid = [entity.id for entity in entities if entity.state not in self.engine.STATES]
        if invalid: problems.append("invalid entity states: " + ",".join(invalid))
        return {"ok": not problems, "problems": problems}

    def time_report(self) -> dict[str, Any]:
        current = datetime.now(timezone.utc)
        ages = [max(0.0, (current-datetime.fromisoformat(entity.created_at)).total_seconds()) for entity in self.engine.entities()]
        return {"count": len(ages), "oldest": round(max(ages, default=0.0), 2), "average": round(sum(ages)/len(ages), 2) if ages else 0.0}

    def json_snapshot(self) -> str:
        return json.dumps({"engine": self.engine.snapshot(), "baseline": self.engine.baseline.snapshot()}, ensure_ascii=False, indent=2)

    def scorecard(self) -> dict[str, Any]:
        jobs = self.engine.baseline.snapshot()["jobs"]
        return {"entity_states": dict(Counter(entity.state for entity in self.engine.entities())), "job_states": dict(Counter(job["state"] for job in jobs)), "consistent": self.consistency()["ok"]}
