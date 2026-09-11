from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .engine import Engine, ValidationError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SPEC = {"domain":"温室环控与灌溉","asset_types":["zone","crop_batch","probe","heater","dehumidifier","co2_unit","fan","irrigation_valve","pump","grow_light","nutrient_pump","cooling_unit"],"signal_names":["air_temperature","humidity","co2","soil_moisture","manifold_pressure","power_kw","light_integral","ec","ph","runtime_hours"],"action_names":["heat","dehumidify","ventilate","inject_co2","open_valve","close_valve","manual_hold","dose_nutrient","start_light","stop_light","service_hold"],"flow_names":["climate_cycle","zone_irrigation","crop_stage_plan","lighting_schedule","energy_allocation","nutrient_adjustment","valve_service","precool_batch","environment_incident"],"config_names":["probe_calibration","climate_targets","irrigation_limits","power_budget","sampling_policy","lighting_policy","service_policy"]}


@dataclass(frozen=True)
class Asset:
    asset_id: str
    kind: str
    state: str
    metadata: dict[str, Any]
    updated_at: str


@dataclass(frozen=True)
class SignalSample:
    sequence: int
    asset_id: str
    name: str
    value: float
    quality: str
    source: str
    calibration_version: str
    observed_at: str


class DomainBaseline:
    """Persistent assets, signals, actions, configurations and jobs."""

    JOB_STATES = ("pending", "running", "completed", "failed", "cancelled")

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.conn = engine.store.conn
        self.lock = engine.store.lock
        with self.lock, self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS baseline_assets(
                    asset_id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
                    metadata TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS baseline_signals(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT NOT NULL,
                    name TEXT NOT NULL, value REAL NOT NULL, quality TEXT NOT NULL,
                    source TEXT NOT NULL, calibration_version TEXT NOT NULL,
                    observed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS baseline_actions(
                    action_id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT UNIQUE NOT NULL,
                    asset_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL,
                    parameters TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS baseline_configs(
                    name TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
                    active INTEGER NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(name, version));
                CREATE TABLE IF NOT EXISTS baseline_jobs(
                    job_id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL,
                    flow TEXT NOT NULL, state TEXT NOT NULL, asset_ids TEXT NOT NULL,
                    payload TEXT NOT NULL, updated_at TEXT NOT NULL);
            """)

    def contract(self) -> dict[str, Any]:
        return json.loads(json.dumps(SPEC))

    def register_asset(self, asset_id: str, kind: str, state: str = "available", **metadata: Any) -> Asset:
        if kind not in SPEC["asset_types"]:
            raise ValidationError(f"unsupported asset type: {kind}")
        stamp = _now()
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO baseline_assets VALUES(?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET kind=excluded.kind,state=excluded.state,metadata=excluded.metadata,updated_at=excluded.updated_at",
                (asset_id, kind, state, json.dumps(metadata, ensure_ascii=False, sort_keys=True), stamp),
            )
        return Asset(asset_id, kind, state, metadata, stamp)

    def asset(self, asset_id: str) -> Asset | None:
        row = self.conn.execute("SELECT * FROM baseline_assets WHERE asset_id=?", (asset_id,)).fetchone()
        return Asset(row["asset_id"], row["kind"], row["state"], json.loads(row["metadata"]), row["updated_at"]) if row else None

    def record_signal(self, asset_id: str, name: str, value: float, *, quality: str = "good", source: str = "device", calibration_version: str = "v1", observed_at: str | None = None) -> SignalSample:
        if self.asset(asset_id) is None:
            raise ValidationError(f"unknown asset: {asset_id}")
        if name not in SPEC["signal_names"]:
            raise ValidationError(f"unsupported signal: {name}")
        stamp = observed_at or _now()
        with self.lock, self.conn:
            cursor = self.conn.execute(
                "INSERT INTO baseline_signals(asset_id,name,value,quality,source,calibration_version,observed_at) VALUES(?,?,?,?,?,?,?)",
                (asset_id, name, float(value), quality, source, calibration_version, stamp),
            )
        self.engine.events.publish("domain-baseline", "signal-recorded", asset_id, {"name": name, "quality": quality})
        return SignalSample(cursor.lastrowid, asset_id, name, float(value), quality, source, calibration_version, stamp)

    def signal_history(self, *, asset_id: str | None = None, name: str | None = None) -> list[SignalSample]:
        clauses, values = [], []
        if asset_id is not None: clauses.append("asset_id=?"); values.append(asset_id)
        if name is not None: clauses.append("name=?"); values.append(name)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute("SELECT * FROM baseline_signals" + where + " ORDER BY sequence", values).fetchall()
        return [SignalSample(**dict(row)) for row in rows]

    def issue_action(self, asset_id: str, action: str, idempotency_key: str, *, actor: str = "controller", **parameters: Any) -> dict[str, Any]:
        if self.asset(asset_id) is None:
            raise ValidationError(f"unknown asset: {asset_id}")
        if action not in SPEC["action_names"]:
            raise ValidationError(f"unsupported action: {action}")
        existing = self.conn.execute("SELECT * FROM baseline_actions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if existing:
            result = dict(existing); result["parameters"] = json.loads(result["parameters"]); result["duplicate"] = True; return result
        with self.lock, self.conn:
            cursor = self.conn.execute(
                "INSERT INTO baseline_actions(idempotency_key,asset_id,action,actor,parameters,created_at) VALUES(?,?,?,?,?,?)",
                (idempotency_key, asset_id, action, actor, json.dumps(parameters, ensure_ascii=False, sort_keys=True), _now()),
            )
        self.engine.events.publish("domain-baseline", "action-issued", asset_id, {"action": action, "idempotency_key": idempotency_key})
        return {"action_id": cursor.lastrowid, "idempotency_key": idempotency_key, "asset_id": asset_id, "action": action, "actor": actor, "parameters": parameters, "duplicate": False}

    def publish_config(self, name: str, version: int, payload: dict[str, Any], *, active: bool = False) -> dict[str, Any]:
        if name not in SPEC["config_names"]:
            raise ValidationError(f"unsupported config: {name}")
        with self.lock, self.conn:
            if active: self.conn.execute("UPDATE baseline_configs SET active=0 WHERE name=?", (name,))
            self.conn.execute("INSERT INTO baseline_configs VALUES(?,?,?,?,?)", (name, int(version), json.dumps(payload, ensure_ascii=False, sort_keys=True), int(active), _now()))
        return {"name": name, "version": int(version), "payload": payload, "active": active}

    def create_job(self, flow: str, request_id: str, asset_ids: list[str], **payload: Any) -> dict[str, Any]:
        if flow not in SPEC["flow_names"]:
            raise ValidationError(f"unsupported flow: {flow}")
        missing = [asset_id for asset_id in asset_ids if self.asset(asset_id) is None]
        if missing: raise ValidationError(f"unknown assets: {missing}")
        existing = self.conn.execute("SELECT * FROM baseline_jobs WHERE request_id=?", (request_id,)).fetchone()
        if existing: return self._job(existing, duplicate=True)
        with self.lock, self.conn:
            cursor = self.conn.execute("INSERT INTO baseline_jobs(request_id,flow,state,asset_ids,payload,updated_at) VALUES(?,?,?,?,?,?)", (request_id, flow, "pending", json.dumps(asset_ids), json.dumps(payload, ensure_ascii=False, sort_keys=True), _now()))
        row = self.conn.execute("SELECT * FROM baseline_jobs WHERE job_id=?", (cursor.lastrowid,)).fetchone()
        return self._job(row, duplicate=False)

    def advance_job(self, job_id: int, state: str) -> dict[str, Any]:
        if state not in self.JOB_STATES: raise ValidationError(f"unsupported job state: {state}")
        with self.lock, self.conn:
            self.conn.execute("UPDATE baseline_jobs SET state=?,updated_at=? WHERE job_id=?", (state, _now(), int(job_id)))
        row = self.conn.execute("SELECT * FROM baseline_jobs WHERE job_id=?", (int(job_id),)).fetchone()
        if row is None: raise ValidationError(f"unknown job: {job_id}")
        return self._job(row, duplicate=False)

    @staticmethod
    def _job(row: Any, *, duplicate: bool) -> dict[str, Any]:
        result = dict(row); result["asset_ids"] = json.loads(result["asset_ids"]); result["payload"] = json.loads(result["payload"]); result["duplicate"] = duplicate; return result

    def snapshot(self) -> dict[str, Any]:
        return {
            "contract": self.contract(),
            "assets": [dict(row) for row in self.conn.execute("SELECT * FROM baseline_assets ORDER BY asset_id")],
            "signals": [asdict(row) for row in self.signal_history()],
            "actions": [dict(row) for row in self.conn.execute("SELECT * FROM baseline_actions ORDER BY action_id")],
            "configs": [dict(row) for row in self.conn.execute("SELECT * FROM baseline_configs ORDER BY name,version")],
            "jobs": [self._job(row, duplicate=False) for row in self.conn.execute("SELECT * FROM baseline_jobs ORDER BY job_id")],
        }
