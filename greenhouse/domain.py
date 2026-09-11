from __future__ import annotations
from typing import Any

class GreenhouseControl:
    """Operational greenhouse workflows backed by persistent jobs, actions and evidence."""
    def __init__(self, service: Any) -> None: self.service=service

    def climate_cycle(self, request_id: str, zone: str, targets: dict[str,float]) -> dict:
        return self.service.baseline.create_job("climate_cycle",request_id,[zone],targets=dict(targets),strategy="independent-thresholds")
    def climate_actions(self, readings: dict[str,float], targets: dict[str,float]) -> list[str]:
        actions=[]
        if readings.get("air_temperature",0)<targets.get("air_temperature",0): actions.append("heat")
        if readings.get("humidity",0)>targets.get("humidity",100): actions.append("dehumidify")
        if readings.get("co2",0)<targets.get("co2",0): actions.append("inject_co2")
        return actions
    def irrigation_cycle(self, request_id: str, zones: list[str], liters: dict[str,float]) -> dict:
        return self.service.baseline.create_job("zone_irrigation",request_id,zones,liters=dict(liters),scheduling="fixed-order")
    def manual_action(self, asset_id: str, actor: str, reason: str) -> dict:
        return self.service.baseline.issue_action(asset_id,"manual_hold",f"hold:{asset_id}:{actor}:{reason}",actor=actor,reason=reason)
    def latest_probe(self, probe_id: str, signal: str) -> dict|None:
        usable=[row for row in self.service.baseline.signal_history(asset_id=probe_id,name=signal) if row.quality!="bad"]
        return usable[-1].__dict__ if usable else None
    def static_power_plan(self, actions: list[dict], budget_kw: float) -> dict:
        accepted=[]; used=0.0
        for action in actions:
            if used+float(action["power_kw"])<=budget_kw: accepted.append(action); used+=float(action["power_kw"])
        return {"accepted":accepted,"used_kw":used,"budget_kw":float(budget_kw)}
    def lighting_schedule(self, request_id: str, zone: str, weekday: int) -> dict:
        start=6 if 0<=int(weekday)<=4 else 8
        return self.service.baseline.create_job("lighting_schedule",request_id,[zone],on_hour=start,off_hour=start+12,policy="fixed-clock")
    def sampling_policy(self, version: int, seconds: int=300) -> dict:
        return self.service.baseline.publish_config("sampling_policy",version,{"default_seconds":int(seconds)},active=True)
    def energy_allocation(self, request_id: str, assets: list[dict]) -> dict:
        ids=[row["asset_id"] for row in assets]; total=sum(float(row.get("rated_kw",0)) for row in assets) or 1.0
        shares={row["asset_id"]:round(float(row.get("rated_kw",0))/total,4) for row in assets}
        return self.service.baseline.create_job("energy_allocation",request_id,ids,shares=shares,basis="rated-power")
    def nutrient_adjustment(self, request_id: str, pump: str, ec: float, target: float) -> dict:
        seconds=max(0,round((float(target)-float(ec))*10))
        action=self.service.baseline.issue_action(pump,"dose_nutrient",request_id,seconds=seconds,basis="ec-only")
        return self.service.baseline.create_job("nutrient_adjustment",request_id+":job",[pump],action_id=action["action_id"],ph_checked=False)
    def valve_service(self, request_id: str, valve: str) -> dict:
        count=self.service.baseline.conn.execute("SELECT COUNT(*) FROM baseline_actions WHERE asset_id=?",(valve,)).fetchone()[0]
        return self.service.baseline.create_job("valve_service",request_id,[valve],recorded_actions=count,service_due=count>=500)
    def precool_batch(self, request_id: str, batch: str, temperature: float) -> dict:
        stage="fast" if float(temperature)>18 else "idle"
        return self.service.baseline.create_job("precool_batch",request_id,[batch],stage=stage,intake_temperature=float(temperature))
    def environment_incident(self, request_id: str, zone: str, event: dict) -> dict:
        return self.service.baseline.create_job("environment_incident",request_id,[zone],group_key=zone,event=dict(event))
