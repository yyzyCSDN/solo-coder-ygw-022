import unittest
from greenhouse.rules import DomainRules
class DomainRuleTests(unittest.TestCase):
    def test_target_validation(self): self.assertEqual(DomainRules.validate_target("humidity",70),70)
    def test_zone_is_required(self):
        with self.assertRaises(ValueError): DomainRules.normalize_zone(" ")
