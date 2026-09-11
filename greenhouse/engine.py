from __future__ import annotations
import csv, hashlib, io, json, random, sqlite3, threading, uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlparse

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def ident(prefix: str) -> str:
    return prefix + "-" + uuid.uuid4().hex[:12]

@dataclass
class Entity:
    id: str
    name: str
    state: str
    priority: int = 50
    quantity: float = 1.0
    value: float = 0.0
    owner: str = "system"
    category: str = "default"
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    version: int = 1
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
        if not self.name: raise ValueError("name is required")
        self.priority = max(0, min(100, int(self.priority)))
        self.quantity = max(0.0, float(self.quantity))
        self.tags = sorted({str(x).strip().lower() for x in self.tags if str(x).strip()})
        self.metadata, self.history = dict(self.metadata or {}), list(self.history or [])

    @classmethod
    def create(cls, prefix: str, name: str, state: str, **values: Any) -> "Entity":
        return cls(ident(prefix), name, state, **values)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Entity":
        fields = {"id","name","state","priority","quantity","value","owner","category",
                  "created_at","updated_at","version","tags","metadata","history"}
        return cls(**{key: data[key] for key in fields if key in data})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def touch(self) -> None:
        self.updated_at = now()

    def transition(self, state: str, actor: str, reason: str = "") -> None:
        old = self.state
        self.state = state
        self.version += 1
        self.history.append({"at": now(), "from": old, "to": state, "actor": actor,
                             "reason": reason, "version": self.version})
        self.touch()

    def annotate(self, key: str, value: Any, actor: str = "system") -> None:
        self.metadata[str(key)] = value
        self.history.append({"at": now(), "annotation": str(key), "actor": actor})
        self.version += 1
        self.touch()

    def add_tag(self, tag: str) -> None:
        value = str(tag).strip().lower()
        if value and value not in self.tags: self.tags.append(value); self.tags.sort(); self.touch()

    def remove_tag(self, tag: str) -> None:
        value = str(tag).strip().lower()
        self.tags = [x for x in self.tags if x != value]; self.touch()

    def age(self) -> float:
        try: return max(0.0, (datetime.now(timezone.utc)-datetime.fromisoformat(self.created_at)).total_seconds())
        except ValueError: return 0.0

    def urgency(self) -> float:
        extra = 20 if self.state in {"alarm","fault","blocked","exception","invalid"} else 0
        return min(100.0, self.priority * .7 + min(30, self.age()/60) + extra)

    def matches(self, text: str) -> bool:
        return str(text).lower().strip() in json.dumps(self.to_dict(), ensure_ascii=False).lower()

class DomainError(Exception): pass
class NotFound(DomainError): pass
class ValidationError(DomainError): pass
class InvalidTransition(DomainError): pass

class Events:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.handlers: defaultdict[str, list[Callable[[dict[str,Any]],None]]] = defaultdict(list)
        self.dead: list[dict[str, Any]] = []
        self.sequence = 0
        self.lock = threading.RLock()

    def subscribe(self, topic: str, handler: Callable[[dict[str,Any]],None]) -> None:
        with self.lock:
            if handler not in self.handlers[topic]: self.handlers[topic].append(handler)

    def publish(self, topic: str, kind: str, entity_id: str, payload: dict[str,Any]|None=None) -> dict[str,Any]:
        with self.lock:
            self.sequence += 1
            event = {"sequence":self.sequence,"topic":topic,"kind":kind,"entity_id":entity_id,
                     "payload":dict(payload or {}),"at":now()}
            self.items.append(event); handlers=list(self.handlers[topic])+list(self.handlers["*"])
        for handler in handlers:
            try: handler(event)
            except Exception as exc: self.dead.append({"event":event,"error":str(exc)})
        return event

    def history(self, topic: str|None=None, kind: str|None=None) -> list[dict[str,Any]]:
        return [x for x in self.items if (topic is None or x["topic"]==topic) and (kind is None or x["kind"]==kind)]

    def replay(self, events: Iterable[dict[str,Any]], handler: Callable[[dict[str,Any]],None]) -> int:
        count=0
        for event in events: handler(event); count+=1
        return count

    def statistics(self) -> dict[str,Any]:
        return {"total":len(self.items),"by_kind":dict(Counter(x["kind"] for x in self.items)),
                "dead_letters":len(self.dead)}

    def clear(self) -> None:
        self.items.clear(); self.dead.clear(); self.sequence=0

class Metrics:
    def __init__(self) -> None:
        self.counters: defaultdict[str,float] = defaultdict(float)
        self.samples: defaultdict[str,list[float]] = defaultdict(list)

    def inc(self, name: str, amount: float=1.0, **labels: str) -> float:
        key=name+"|"+",".join(f"{k}={v}" for k,v in sorted(labels.items()))
        self.counters[key]+=amount; self.samples[name].append(self.counters[key]); return self.counters[key]

    def observe(self, name: str, value: float) -> None:
        self.samples[name].append(float(value))

    def summary(self, name: str|None=None) -> dict[str,Any]:
        values=[v for key,seq in self.samples.items() if name is None or key==name for v in seq]
        if not values: return {"count":0,"mean":0.0,"min":0.0,"max":0.0}
        return {"count":len(values),"mean":round(sum(values)/len(values),3),"min":min(values),"max":max(values)}

    def export(self) -> dict[str,Any]:
        return {"counters":dict(self.counters),"samples":{key:self.summary(key) for key in self.samples}}

class Store:
    def __init__(self, path: str=":memory:") -> None:
        self.conn=sqlite3.connect(path,check_same_thread=False); self.conn.row_factory=sqlite3.Row
        self.lock=threading.RLock()
        with self.conn:
            self.conn.execute("CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY,state TEXT,category TEXT,priority INTEGER,payload TEXT,created_at TEXT,updated_at TEXT)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS state_idx ON entities(state)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS priority_idx ON entities(priority)")

    def save(self, entity: Entity) -> Entity:
        payload=json.dumps(entity.to_dict(),ensure_ascii=False,sort_keys=True)
        with self.lock,self.conn:
            self.conn.execute("""INSERT INTO entities VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET state=excluded.state,category=excluded.category,
                priority=excluded.priority,payload=excluded.payload,updated_at=excluded.updated_at""",
                (entity.id,entity.state,entity.category,entity.priority,payload,entity.created_at,entity.updated_at))
        return entity

    def get(self, entity_id: str) -> Entity|None:
        row=self.conn.execute("SELECT payload FROM entities WHERE id=?",(entity_id,)).fetchone()
        return Entity.from_dict(json.loads(row["payload"])) if row else None

    def list(self, state: str|None=None, category: str|None=None, minimum_priority: int|None=None,
             limit: int=5000, offset: int=0) -> list[Entity]:
        clauses=[]; values=[]
        if state is not None: clauses.append("state=?"); values.append(state)
        if category is not None: clauses.append("category=?"); values.append(category)
        if minimum_priority is not None: clauses.append("priority>=?"); values.append(minimum_priority)
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        values += [max(1,min(5000,limit)),max(0,offset)]
        rows=self.conn.execute("SELECT payload FROM entities"+where+" ORDER BY priority DESC,updated_at DESC LIMIT ? OFFSET ?",values).fetchall()
        return [Entity.from_dict(json.loads(row["payload"])) for row in rows]

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0])

    def delete(self, entity_id: str) -> bool:
        with self.lock,self.conn:
            return self.conn.execute("DELETE FROM entities WHERE id=?",(entity_id,)).rowcount>0

    def snapshot(self) -> list[dict[str,Any]]: return [x.to_dict() for x in self.list()]
    def restore(self, values: Iterable[dict[str,Any]]) -> int:
        count=0
        for value in values: self.save(Entity.from_dict(value)); count+=1
        return count
    def close(self) -> None: self.conn.close()

class Planner:
    def __init__(self) -> None:
        self.slots=[]; self.sequence=0

    def build(self, entities: Iterable[Entity]) -> list[dict[str,Any]]:
        self.slots=[]; ends={"primary":0,"secondary":0}
        for entity in sorted(entities,key=lambda x:(x.urgency(),x.priority),reverse=True):
            lane=min(ends,key=ends.get); self.sequence+=1
            duration=max(5,min(180,5+int(entity.quantity*3)+(100-entity.priority)//8))
            slot={"id":f"slot-{self.sequence:04d}","entity_id":entity.id,"resource":lane,
                  "start":ends[lane],"duration":duration,"score":round(entity.urgency(),2),"status":"proposed"}
            self.slots.append(slot); ends[lane]+=duration
        return list(self.slots)

    def conflicts(self) -> list[tuple[str,str]]:
        result=[]
        for left in self.slots:
            for right in self.slots:
                if left["id"]>=right["id"] or left["resource"]!=right["resource"]: continue
                if left["start"]<right["start"]+right["duration"] and right["start"]<left["start"]+left["duration"]:
                    result.append((left["id"],right["id"]))
        return result

    def summary(self) -> dict[str,Any]:
        return {"total":len(self.slots),"statuses":dict(Counter(x["status"] for x in self.slots)),
                "conflicts":len(self.conflicts())}

class Engine:
    STATES=["draft","scheduled","active","watering","completed","alarm"]
    DEFAULT_STATE="draft"
    DOMAIN="sensor-driven greenhouse climate and irrigation"

    def __init__(self, database: str=":memory:") -> None:
        self.store=Store(database); self.events=Events(); self.metrics=Metrics(); self.planner=Planner()
        self.random=random.Random(19); self.events.subscribe("domain",self._metric)

    def _metric(self,event: dict[str,Any]) -> None: self.metrics.inc("events",kind=event["kind"])

    def validate(self, entity: Entity) -> None:
        if entity.state not in self.STATES: raise ValidationError("unknown state")
        if not entity.name or not 0<=entity.priority<=100: raise ValidationError("invalid entity")

    def create(self,name: str,**values: Any) -> Entity:
        entity=Entity.create("greenhouse",name,values.pop("state",self.DEFAULT_STATE),**values)
        self.validate(entity); self.store.save(entity)
        self.events.publish("domain","created",entity.id,{"state":entity.state}); self.metrics.inc("created")
        return entity

    def get(self,entity_id: str) -> Entity:
        entity=self.store.get(entity_id)
        if entity is None: raise NotFound(entity_id)
        return entity

    def entities(self,**filters: Any) -> list[Entity]: return self.store.list(**filters)

    def list_entities(self,page: int=1,size: int=50,**filters: Any) -> dict[str,Any]:
        page=max(1,int(page)); size=max(1,min(500,int(size)))
        return {"page":page,"size":size,"total":self.store.count(),
                "items":[x.to_dict() for x in self.store.list(limit=size,offset=(page-1)*size,**filters)]}

    def search(self,text: str) -> list[dict[str,Any]]:
        return [x.to_dict() for x in self.store.list() if x.matches(text)]

    def transition(self,entity_id: str,next_state: str,actor: str="system",reason: str="") -> Entity:
        entity=self.get(entity_id)
        index=self.STATES.index(entity.state) if entity.state in self.STATES else -1
        allowed={self.STATES[min(index+1,len(self.STATES)-1)],"alarm","fault","blocked","exception","rejected","cancelled"}
        if next_state not in self.STATES or next_state not in allowed: raise InvalidTransition(f"{entity.state}->{next_state}")
        entity.transition(next_state,actor,reason); self.store.save(entity)
        self.events.publish("domain","transitioned",entity.id,{"state":next_state,"actor":actor})
        self.metrics.inc("transitions",state=next_state); return entity

    def annotate(self,entity_id: str,key: str,value: Any,actor: str="system") -> Entity:
        entity=self.get(entity_id); entity.annotate(key,value,actor); self.store.save(entity)
        self.events.publish("domain","annotated",entity.id,{"key":key}); return entity

    def evaluate(self,entity_id: str,context: dict[str,Any]|None=None) -> dict[str,Any]:
        entity=self.get(entity_id); context=context or {}; reasons=[]; actions=[]
        if entity.priority>=80: reasons.append("high-priority"); actions.append("expedite")
        if context.get("maintenance"): reasons.append("maintenance"); actions.append("hold")
        if context.get("capacity",float("inf"))<entity.quantity: reasons.append("capacity"); actions.append("reschedule")
        return {"allowed":"capacity" not in reasons,"score":round(entity.urgency(),2),"reasons":reasons,"actions":actions}

    def build_plan(self) -> dict[str,Any]:
        slots=self.planner.build(self.entities()); self.metrics.observe("plan_size",len(slots))
        self.events.publish("domain","plan-built","planner",{"slots":len(slots)})
        return {"slots":slots,"conflicts":self.planner.conflicts(),"summary":self.planner.summary()}

    def dashboard(self) -> dict[str,Any]:
        rows=self.entities(); states=Counter(x.state for x in rows)
        risks=[{"id":x.id,"name":x.name,"risk":round(x.urgency(),2)} for x in rows if x.urgency()>=60]
        return {"domain":self.DOMAIN,"total":len(rows),"states":dict(states),
                "categories":dict(Counter(x.category for x in rows)),
                "risks":sorted(risks,key=lambda x:x["risk"],reverse=True),"plan":self.planner.summary()}

    def health(self) -> dict[str,Any]:
        return {"status":"ok","domain":self.DOMAIN,"entities":self.store.count(),
                "events":self.events.statistics(),"metrics":self.metrics.summary()}

    def simulate(self,count: int=5) -> dict[str,Any]:
        ids=[]
        for index in range(max(0,count)):
            entity=self.create(f"sim-{index+1:03d}",priority=self.random.randint(20,98),
                quantity=round(self.random.uniform(1,20),2),value=round(self.random.uniform(10,1000),2),
                owner="simulator",category="simulation",tags=["generated"],
                metadata={"signal":round(self.random.random(),4)})
            ids.append(entity.id)
        return {"created":len(ids),"ids":ids,"dashboard":self.dashboard()}

    def export_csv(self) -> str:
        out=io.StringIO(); fields=["id","name","state","priority","quantity","value","owner","category","updated_at"]
        writer=csv.DictWriter(out,fieldnames=fields); writer.writeheader()
        for entity in self.entities(): writer.writerow({key:getattr(entity,key) for key in fields})
        return out.getvalue()

    def snapshot(self) -> dict[str,Any]:
        return {"domain":self.DOMAIN,"entities":self.store.snapshot(),"events":self.events.history(),"metrics":self.metrics.export()}

    def restore(self,snapshot: dict[str,Any]) -> int:
        count=self.store.restore(snapshot.get("entities",[])); self.metrics.inc("restored"); return count
    def close(self) -> None: self.store.close()

def serve(engine: Engine,host: str="127.0.0.1",port: int=8080) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def send_json(self,status: int,payload: Any) -> None:
            raw=json.dumps(payload,ensure_ascii=False,default=str).encode()
            self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def do_GET(self) -> None:
            parsed=urlparse(self.path); query=parse_qs(parsed.query)
            try:
                if parsed.path=="/health": body=engine.health()
                elif parsed.path=="/dashboard": body=engine.dashboard()
                elif parsed.path=="/metrics": body=engine.metrics.export()
                elif parsed.path=="/events": body={"events":engine.events.history()}
                elif parsed.path=="/entities": body=engine.list_entities(state=query.get("state",[None])[0])
                else: self.send_json(404,{"error":"not_found"}); return
                self.send_json(200,body)
            except Exception as exc: self.send_json(400,{"error":type(exc).__name__,"message":str(exc)})
        def do_POST(self) -> None:
            length=int(self.headers.get("Content-Length","0")); body=json.loads(self.rfile.read(length) or b"{}")
            try:
                if self.path=="/entities": result=engine.create(**body).to_dict()
                elif self.path=="/plan": result=engine.build_plan()
                elif self.path=="/simulate": result=engine.simulate(int(body.get("count",5)))
                else: self.send_json(404,{"error":"not_found"}); return
                self.send_json(201,result)
            except Exception as exc: self.send_json(400,{"error":type(exc).__name__,"message":str(exc)})
        def log_message(self,*args: Any) -> None: return
    return ThreadingHTTPServer((host,port),Handler)



