"""Replay r108 backtest timings through the real detector with simulated subscriber beacons."""
import json, re, random, statistics as st, sys
from datetime import datetime as D
from collector import store, detector, sim
P = lambda s: D.fromisoformat(s.replace("Z", "+00:00")).timestamp()
rel = {}
for r in json.load(open("data/releases.json")):
    m = re.search(r"(\d{8}\.\d+)", r["tag"] or "")
    if m and r["published"]: rel.setdefault(m.group(1), []).append(P(r["published"]))
cases = []
for i in json.load(open("data/reg.json")):
    for v in re.findall(r"(\d{8}\.\d+)(?:\.\d+)?", i["body"]):
        if v in rel:
            R = min(rel[v]); F = P(i["created"]); lag = (F - R) / 3600
            if -24 < lag < 24 * 60: cases.append((i["n"], v, R, F)); break
def alert_time(n, affected, seed):
    rng = random.Random(seed); R = 1_700_000_000
    ev, _ = sim.stream(rng, n, R, "20990101.1", "20990108.1", affected_frac=affected, horizon_h=24 * 20)
    db = store.connect(); th = detector.Thresholds()
    for k, e in enumerate(ev):
        store.insert(db, e)
        if e["conclusion"] == "failure" and e["ts"] >= R and k % 3 == 0:
            if any(r["flagged"] for r in detector.evaluate(db, th)): return (e["ts"] - R) / 3600
    return None
out = {}
for n in (20, 50):
    for aff in (0.1, 0.3):
        leads = []; miss = 0; alerts_h = []
        for j, (num, v, R, F) in enumerate(cases):
            a = alert_time(n, aff, seed=j)
            if a is None: miss += 1; continue
            alerts_h.append(a); leads.append((F - R) / 3600 - a)
        out[f"n{n}_aff{aff}"] = {"cases": len(cases), "missed": miss, "alert_after_release_med_h": round(st.median(alerts_h), 1),
            "lead_vs_first_public_med_h": round(st.median(leads), 1), "lead_p25_h": round(sorted(leads)[len(leads)//4], 1),
            "share_alert_before_public": round(sum(l > 0 for l in leads) / len(leads), 2)}
        print(f"n={n} affected={aff}:", out[f"n{n}_aff{aff}"], flush=True)
json.dump(out, open("out/replay.json", "w"), indent=1)
