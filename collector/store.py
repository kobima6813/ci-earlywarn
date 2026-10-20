import sqlite3, json, time
SCHEMA = """
CREATE TABLE IF NOT EXISTS beacons(id INTEGER PRIMARY KEY, tenant TEXT, runner_os TEXT, image_os TEXT, image_version TEXT,
  conclusion TEXT, step_category TEXT, toolchain TEXT, ts INTEGER);
CREATE INDEX IF NOT EXISTS ix_img ON beacons(image_os, image_version);
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, kind TEXT, key TEXT UNIQUE, payload TEXT, ts INTEGER);
"""
ALLOWED = {"tenant", "runner_os", "image_os", "image_version", "conclusion", "step_category", "toolchain", "ts", "mode", "actions"}
MODES = {"all", "failures_only"}
HEX16 = __import__("re").compile(r"^[0-9a-f]{8,32}$")
CONCLUSIONS = {"success", "failure", "cancelled", "unknown"}

def migrate(db):
    cols = {r[1] for r in db.execute("PRAGMA table_info(beacons)")}
    if "mode" not in cols: db.execute("ALTER TABLE beacons ADD COLUMN mode TEXT DEFAULT 'all'")
    if "actions" not in cols: db.execute("ALTER TABLE beacons ADD COLUMN actions TEXT DEFAULT '[]'")
    db.commit()

def connect(path=":memory:"):
    db = sqlite3.connect(path, check_same_thread=False); db.executescript(SCHEMA); migrate(db)
    from . import security; security.init(db); return db

def validate(b):
    if not isinstance(b, dict): raise ValueError("object expected")
    extra = set(b) - ALLOWED - {"v"}
    if extra: raise ValueError(f"unexpected fields: {sorted(extra)}")
    for k in ("tenant", "image_os", "image_version", "conclusion"):
        if not isinstance(b.get(k), str) or not b[k] or len(b[k]) > 64: raise ValueError(f"bad {k}")
    if b["conclusion"] not in CONCLUSIONS: raise ValueError("bad conclusion")
    tc = b.get("toolchain") or {}
    if not isinstance(tc, dict) or len(json.dumps(tc)) > 300: raise ValueError("bad toolchain")
    if b.get("mode", "all") not in MODES: raise ValueError("bad mode")
    acts = b.get("actions") or []
    if not isinstance(acts, list) or len(acts) > 20 or not all(isinstance(a, str) and HEX16.match(a) for a in acts): raise ValueError("bad actions")
    return b

def insert(db, b):
    validate(b)
    db.execute("INSERT INTO beacons(tenant,runner_os,image_os,image_version,conclusion,step_category,toolchain,ts,mode,actions) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (b["tenant"], b.get("runner_os", ""), b["image_os"], b["image_version"], b["conclusion"], b.get("step_category", "none"),
                json.dumps(b.get("toolchain") or {}), int(b.get("ts") or time.time()),
                b.get("mode", "all"), json.dumps(sorted(set(b.get("actions") or [])))))
    db.commit()

def add_alert(db, kind, key, payload):
    try:
        db.execute("INSERT INTO alerts(kind,key,payload,ts) VALUES(?,?,?,?)", (kind, key, json.dumps(payload), int(time.time()))); db.commit(); return True
    except sqlite3.IntegrityError:
        return False

def alerts(db, limit=50):
    return [dict(kind=k, key=key, ts=ts, **json.loads(p)) for k, key, p, ts in db.execute("SELECT kind,key,payload,ts FROM alerts ORDER BY ts DESC, id DESC LIMIT ?", (limit,))]
