from __future__ import annotations
import json, tempfile
from pathlib import Path
from .engine import Engine
from .operations import Operations
from .workflows import WorkflowExtensions
from .baseline import DomainBaseline
from .rules import DomainRules
from .domain import GreenhouseControl

class GreenhouseService(Engine):
    def __init__(self, database: str=":memory:") -> None:
        super().__init__(database)
        self.baseline=DomainBaseline(self)
        self.rules=DomainRules()
        self.operations=Operations(self)
        self.workflows=WorkflowExtensions(self)
        self.domain=GreenhouseControl(self)
    def export(self, fmt: str="json") -> str:
        return self.export_csv() if fmt.lower()=="csv" else self.operations.json_snapshot()

def demo() -> None:
    with tempfile.TemporaryDirectory(prefix="greenhouse-") as folder:
        service=GreenhouseService(str(Path(folder)/"demo.db"))
        first=service.create("demo-primary",priority=92,quantity=3,tags=["demo"])
        service.create("demo-secondary",priority=45,quantity=2)
        service.transition(first.id,service.STATES[1],"demo","normal flow")
        print(json.dumps({"dashboard":service.dashboard(),"plan":service.build_plan(),"baseline":service.baseline.contract(),"health":service.health()},ensure_ascii=False,indent=2))
        service.close()
