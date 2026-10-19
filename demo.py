"""End-to-end local demo: start collector on localhost, POST a simulated 20-tenant stream with an injected regression over HTTP."""
import json, random, threading, urllib.request, os, sys
from collector import app, sim, alerts as A
os.environ.pop("EW_WEBHOOK_URL", None)  # no outbound webhooks in demo
# demo: loopback load generator, so raise rate limits; production defaults live in app.Config
cfg = app.Config(ip_rate=1e6, ip_burst=1e6, token_rate=1e6, token_burst=1e6, signup_burst=1e6)
srv, db = app.serve(db_path=":memory:", port=0, cfg=cfg)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
rng = random.Random(7); t0 = 1_790_000_000
ev, affected = sim.stream(rng, 20, t0, "20261005.1", "20261012.1", affected_frac=0.3, horizon_h=72)
ev2, _ = sim.stream(random.Random(8), 20, t0, "20261005.2", "20261012.2", image_os="win25", affected_frac=0.0, horizon_h=72)
tokens = {}
def token_for(name):
    if name not in tokens:
        r = json.load(urllib.request.urlopen(urllib.request.Request(base + "/v1/signup", data=b"{}")))
        tokens[name] = r["token"]
        db.execute("UPDATE tenants SET created=created-30*86400 WHERE id=?", (r["tenant_id"],)); db.commit()  # simulate 30d history (eligible)
    return tokens[name]
first_alert = None
for e in sorted(ev + ev2, key=lambda x: x["ts"]):
    urllib.request.urlopen(urllib.request.Request(base + "/v1/beacon", data=json.dumps({k: v for k, v in e.items() if k != "tenant"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token_for((e["image_os"], e["tenant"]))}))
    if first_alert is None and json.load(urllib.request.urlopen(base + "/v1/alerts")):
        first_alert = (e["ts"] - t0) / 3600
al = json.load(urllib.request.urlopen(base + "/v1/alerts"))
os.makedirs("out", exist_ok=True)
open("out/status.html", "w").write(urllib.request.urlopen(base + "/").read().decode())
json.dump({"alerts": al, "slack": [A.slack(a) for a in al], "email": [A.email(a) for a in al]}, open("out/demo_alerts.json", "w"), indent=1)
print(f"beacons={len(ev)+len(ev2)} affected_tenants={len(affected)} alerts={len(al)} first_alert_h_after_rollout_start={first_alert and round(first_alert,1)}")
print([a["title"] for a in al])
srv.shutdown()
