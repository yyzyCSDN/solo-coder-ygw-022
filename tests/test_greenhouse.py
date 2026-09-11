import tempfile
import unittest
from greenhouse import GreenhouseService
class ExpandedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.service=GreenhouseService(self.temp.name+"/data.db")
    def tearDown(self):
        self.service.close(); self.temp.cleanup()
    def test_create_search_and_persist(self):
        item=self.service.create("primary",priority=90,tags=["test"])
        self.assertEqual(self.service.get(item.id).name,"primary")
        self.assertEqual(len(self.service.search("PRIMARY")),1)
        self.assertTrue(self.service.operations.consistency()["ok"])
    def test_transition_and_events(self):
        item=self.service.create("flow")
        self.service.transition(item.id,"scheduled","tester")
        self.assertEqual(self.service.get(item.id).state,"scheduled")
        self.assertEqual(self.service.events.statistics()["total"],2)
    def test_plan_simulation_and_exports(self):
        for i in range(4): self.service.create("job-"+str(i),priority=40+i)
        self.assertEqual(len(self.service.build_plan()["slots"]),4)
        self.assertEqual(self.service.simulate(3)["created"],3)
        self.assertIn("id,name,state",self.service.export("csv"))
if __name__=="__main__": unittest.main()



