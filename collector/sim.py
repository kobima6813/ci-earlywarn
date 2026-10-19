"""Simulated beacon streams (used by demo and replay)."""
import random
def stream(rng, n_tenants, t0, prev_v, new_v, image_os="ubuntu24", affected_frac=0.3, runs_per_day=3.0,
           base_fail=0.03, broken_fail=0.9, rollout_h=48.0, horizon_h=96.0, cat="build"):
    ev = []
    tenants = [f"t{i:03d}" for i in range(n_tenants)]
    affected = set(rng.sample(tenants, max(1, round(n_tenants * affected_frac))))
    for t in tenants:
        switch = t0 + rng.uniform(0, rollout_h) * 3600
        ts = t0 - 48 * 3600
        while ts < t0 + horizon_h * 3600:
            ts += rng.expovariate(runs_per_day / 86400)
            v = new_v if ts >= switch else prev_v
            p = broken_fail if (v == new_v and t in affected) else base_fail
            fail = rng.random() < p
            ev.append({"tenant": t, "runner_os": "Linux", "image_os": image_os, "image_version": v,
                       "conclusion": "failure" if fail else "success", "step_category": cat if fail else "none", "ts": int(ts)})
    return sorted(ev, key=lambda e: e["ts"]), affected
