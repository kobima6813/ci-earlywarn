"""Flags an image version whose cross-tenant failure rate jumps vs the previous version of the same image_os."""
import json
from dataclasses import dataclass

@dataclass
class Thresholds:
    min_tenants: int = 5          # distinct tenants seen on the new version
    min_failing_tenants: int = 3  # distinct tenants with >=1 failure on the new version
    min_jump: float = 0.15        # absolute increase in tenant-failure share
    ratio: float = 2.0            # and at least this multiple of the previous share
    window_s: int = 72 * 3600     # only beacons within this window after first sighting

def version_key(v):
    return tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in str(v).replace("-", ".").split("."))

def tenant_failure_share(rows):
    """rows: (tenant, conclusion). Share of tenants whose failure rate on this version is >=50% of their runs."""
    per = {}
    for t, c in rows:
        s = per.setdefault(t, [0, 0]); s[1] += 1; s[0] += c == "failure"
    if not per: return 0.0, 0, 0
    failing = sum(1 for f, n in per.values() if f / n >= 0.5)
    return failing / len(per), len(per), failing

def _stats(rows, ok, pred):
    """rows: (tenant, conclusion, actions_json). Per-tenant (failures, runs) for runs matching pred(actions)."""
    per = {}
    for t, c, acts in rows:
        a = json.loads(acts or "[]")
        if ok(t) and a and pred(a):
            x = per.setdefault(t, [0, 0]); x[1] += 1; x[0] += c == "failure"
    n = len(per); f = sum(1 for a, b in per.values() if a / b >= 0.5)
    return dict(tenants=n, failing_tenants=f, share=round(f / n, 3) if n else None)

def classify(db, image_os, prev, cur, t_from, t_to, failing, eligible=None, min_share=0.6, min_n=2):
    """Label a suspected regression: 'likely action breakage' | 'likely image regression' | 'ambiguous' | 'unclear'.
    Stratified test for the candidate action hash H (one action@version, shared by most failing tenants on `cur`):
      action evidence: H fails for >=2 tenants on OTHER image versions, or on `cur` runs WITHOUT H pass (>=2 tenants).
      image evidence:  on `cur`, runs WITHOUT H also fail (>=2 tenants), or on `prev`, runs WITH H pass (>=2 tenants).
    Both or neither (e.g. new image and new action release landed together and every tenant took both) -> 'ambiguous'.
    Without action data: image split (failing tenants that passed on `prev` in the same window) decides."""
    ok = (lambda t: True) if eligible is None else (lambda t: t in eligible)
    failing = set(failing)
    passed_prev = {t for (t,) in db.execute("SELECT DISTINCT tenant FROM beacons WHERE image_os=? AND image_version=? AND conclusion='success' AND ts BETWEEN ? AND ?",
                                            (image_os, prev, t_from, t_to)) if t in failing}
    split = len(passed_prev) / len(failing) if failing else 0.0
    Q = "SELECT tenant, conclusion, actions FROM beacons WHERE image_os=? AND image_version=? AND conclusion IN ('success','failure') AND ts BETWEEN ? AND ?"
    cur_rows = db.execute(Q, (image_os, cur, t_from, t_to)).fetchall()
    per_hash = {}
    for t, c, acts in cur_rows:
        if c == "failure" and t in failing:
            for h in json.loads(acts or "[]"): per_hash.setdefault(h, set()).add(t)
    reporting = {t for ts_ in per_hash.values() for t in ts_}
    H = None
    if reporting:
        h, ts_ = max(per_hash.items(), key=lambda kv: (len(kv[1]), kv[0]))
        if len(ts_) >= max(2, min_share * len(reporting)): H = h
    out = dict(image_split=round(split, 3), tenants_passing_on_prev=len(passed_prev), action_reporting_tenants=len(reporting),
               suspect_action_hash=None, candidate_action_hash=H, suspect_cross_version_failing_tenants=0)
    if H is None:
        out["label"] = "likely image regression" if split >= 0.5 else "unclear"; return out
    has, hasnt = (lambda a: H in a), (lambda a: H not in a)
    other = db.execute("SELECT tenant, conclusion, actions FROM beacons WHERE NOT (image_os=? AND image_version=?) AND conclusion IN ('success','failure') AND ts BETWEEN ? AND ?",
                       (image_os, cur, t_from, t_to)).fetchall()
    st = dict(cur_with=_stats(cur_rows, ok, has), cur_without=_stats(cur_rows, ok, hasnt),
              prev_with=_stats(db.execute(Q, (image_os, prev, t_from, t_to)).fetchall(), ok, has), other_with=_stats(other, ok, has))
    first = db.execute("SELECT MIN(ts) FROM beacons WHERE actions LIKE ?", (f'%"{H}"%',)).fetchone()[0]
    out.update(strata=st, candidate_action_first_seen=first, candidate_action_new_in_window=first is not None and first >= t_from - 24 * 3600)
    cw, cwo, pw, ow = st["cur_with"], st["cur_without"], st["prev_with"], st["other_with"]
    cur_bad = (cw["share"] or 0) >= 0.5
    action_ev = ow["failing_tenants"] >= min_n or (cur_bad and cwo["tenants"] >= min_n and cwo["share"] < 0.5)
    image_ev = (cwo["tenants"] >= min_n and cwo["share"] >= 0.5) or (cur_bad and pw["tenants"] >= min_n and pw["share"] < 0.5)
    out["suspect_cross_version_failing_tenants"] = ow["failing_tenants"]
    if action_ev and not image_ev: out["label"] = "likely action breakage"; out["suspect_action_hash"] = H
    elif image_ev and not action_ev: out["label"] = "likely image regression"
    else:
        out["label"] = "ambiguous"
        out["ambiguous_reason"] = ("image and action both implicated (possibly an interaction)" if action_ev else
                                   "confounded: failing tenants all moved to the new image and this action version together; no run isolates either")
    return out

def evaluate(db, th=Thresholds(), eligible=None):
    """eligible: optional set of tenant keys allowed to count toward wave thresholds (sybil resistance)."""
    out = []
    for (image_os,) in db.execute("SELECT DISTINCT image_os FROM beacons"):
        vers = sorted({v for (v,) in db.execute("SELECT DISTINCT image_version FROM beacons WHERE image_os=?", (image_os,))}, key=version_key)
        for prev, cur in zip(vers, vers[1:]):
            first = db.execute("SELECT MIN(ts) FROM beacons WHERE image_os=? AND image_version=?", (image_os, cur)).fetchone()[0]
            # failures-only beacons have no pass baseline: excluded from shares, counted only as extra failing tenants.
            q = "SELECT tenant, conclusion FROM beacons WHERE image_os=? AND image_version=? AND conclusion IN ('success','failure') AND COALESCE(mode,'all')!='failures_only'"
            fo = {t for (t,) in db.execute("SELECT DISTINCT tenant FROM beacons WHERE image_os=? AND image_version=? AND conclusion='failure' AND mode='failures_only' AND ts<=?",
                                           (image_os, cur, first + th.window_s))}
            cur_rows = db.execute(q + " AND ts<=?", (image_os, cur, first + th.window_s)).fetchall()
            prev_rows = db.execute(q, (image_os, prev)).fetchall()
            if eligible is not None:
                cur_rows = [r for r in cur_rows if r[0] in eligible]; prev_rows = [r for r in prev_rows if r[0] in eligible]
                fo = {t for t in fo if t in eligible}
            ps, pn, pf = tenant_failure_share(prev_rows); cs, cn, cf = tenant_failure_share(cur_rows)
            per = {}
            for t, c in cur_rows:
                x = per.setdefault(t, [0, 0]); x[1] += 1; x[0] += c == "failure"
            failing = {t for t, (f, n) in per.items() if f / n >= 0.5}
            fo_extra = fo - set(per)                 # failures-only tenants not already counted via full-mode jobs
            flagged = (cn >= th.min_tenants and cf + len(fo_extra) >= th.min_failing_tenants and cs - ps >= th.min_jump and cs >= max(ps * th.ratio, 1e-9))
            cats = dict(db.execute("SELECT step_category, COUNT(*) FROM beacons WHERE image_os=? AND image_version=? AND conclusion='failure' GROUP BY 1", (image_os, cur)).fetchall())
            out.append(dict(image_os=image_os, prev_version=prev, version=cur, prev_share=round(ps, 3), share=round(cs, 3),
                            tenants=cn, failing_tenants=cf, prev_tenants=pn, flagged=flagged, failure_categories=cats,
                            failures_only_tenants=len(fo_extra)))
            if flagged:
                out[-1]["diagnosis"] = classify(db, image_os, prev, cur, first, first + th.window_s, failing | fo_extra, eligible)
    return out
