import tempfile
import unittest

from greenhouse import GreenhouseService


class BaselineContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = GreenhouseService(self.temp.name + "/baseline.db")

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_domain_contract_is_real_and_persistent(self):
        baseline = self.service.baseline
        self.assertIn("zone", baseline.contract()["asset_types"])
        self.assertIn("crop_stage_plan", baseline.contract()["flow_names"])
        self.assertIn("power_kw", baseline.contract()["signal_names"])
        baseline.register_asset("asset-a", "zone", state="available")
        baseline.register_asset("asset-b", "crop_batch", state="available")
        sample = baseline.record_signal("asset-a", "air_temperature", 12.5, quality="suspect", calibration_version="v2")
        self.assertEqual(sample.quality, "suspect")
        baseline.publish_config("probe_calibration", 1, {"enabled": True}, active=True)
        job = baseline.create_job("climate_cycle", "request-1", ["asset-a", "asset-b"], reason="baseline")
        self.assertEqual(job["state"], "pending")
        first = baseline.issue_action("asset-a", "heat", "action-1", actor="tester")
        second = baseline.issue_action("asset-a", "heat", "action-1", actor="tester")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(baseline.signal_history(asset_id="asset-a")), 1)


if __name__ == "__main__":
    unittest.main()
