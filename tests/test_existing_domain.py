import unittest
from greenhouse.service import GreenhouseService

class ExistingGreenhouseTests(unittest.TestCase):
    def setUp(self):
        self.s=GreenhouseService()
        for asset,kind in [("z1","zone"),("z2","zone"),("p1","probe"),("v1","irrigation_valve"),("np1","nutrient_pump"),("b1","crop_batch")]: self.s.baseline.register_asset(asset,kind)
    def tearDown(self): self.s.close()
    def test_climate_cycle_persists_independent_strategy(self): self.assertEqual(self.s.domain.climate_cycle("c1","z1",{"air_temperature":22})["payload"]["strategy"],"independent-thresholds")
    def test_probe_and_manual_action_are_evidence(self):
        self.s.baseline.record_signal("p1","humidity",70,calibration_version="v3"); self.assertEqual(self.s.domain.latest_probe("p1","humidity")["calibration_version"],"v3"); self.assertEqual(self.s.domain.manual_action("z1","op","inspection")["actor"],"op")
    def test_power_plan_keeps_input_order(self): self.assertEqual([x["id"] for x in self.s.domain.static_power_plan([{"id":"a","power_kw":4},{"id":"b","power_kw":4}],5)["accepted"]],["a"])
    def test_irrigation_job_is_idempotent(self):
        first=self.s.domain.irrigation_cycle("i1",["z1"],{"z1":12}); second=self.s.domain.irrigation_cycle("i1",["z1"],{"z1":99}); self.assertFalse(first["duplicate"]); self.assertTrue(second["duplicate"])
    def test_climate_actions_are_independent(self): self.assertEqual(self.s.domain.climate_actions({"air_temperature":18,"humidity":40},{"air_temperature":22,"humidity":70}),["heat"])
    def test_lighting_is_a_persistent_fixed_clock_job(self): self.assertEqual(self.s.domain.lighting_schedule("l1","z1",3)["payload"]["policy"],"fixed-clock")
    def test_sampling_policy_is_versioned(self): self.assertEqual(self.s.domain.sampling_policy(2)["payload"]["default_seconds"],300)
    def test_energy_allocation_records_rated_power_basis(self): self.assertEqual(self.s.domain.energy_allocation("e1",[{"asset_id":"z1","rated_kw":3},{"asset_id":"z2","rated_kw":1}])["payload"]["shares"]["z1"],0.75)
    def test_nutrient_adjustment_records_action_and_job(self): self.assertFalse(self.s.domain.nutrient_adjustment("n1","np1",1,2)["payload"]["ph_checked"])
    def test_valve_service_uses_action_history(self): self.assertEqual(self.s.domain.valve_service("vjob","v1")["payload"]["recorded_actions"],0)
    def test_precool_is_a_batch_job(self): self.assertEqual(self.s.domain.precool_batch("pc1","b1",25)["payload"]["stage"],"fast")
    def test_incident_is_persisted_by_zone(self): self.assertEqual(self.s.domain.environment_incident("x1","z1",{"kind":"co2"})["payload"]["group_key"],"z1")
