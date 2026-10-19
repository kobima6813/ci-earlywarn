"""Flags an image version whose cross-tenant failure rate jumps vs the previous version of the same image_os."""
from dataclasses import dataclass

@dataclass
class Thresholds:
    min_tenants: int = 5          # distinct tenants seen on the new version
    min_failing_tenants: int = 3  # distinct tenants with >=1 failure on the new version
    min_jump: float = 0.15        # absolute increase in tenant-failure share
    ratio: float = 2.0            # and at least this multiple of the previous share
    window_s: int = 72 * 3600     # only beacons within this window after first sighting

def version_key(v):
    return tuple(int(x) if x.isdigit() else x for x in v.replace("-", ".").split("."))

def tenant_failure_share(rows):
    """rows: (tenant, conclusion). Share of tenants whose failure rate on this version is >=50% of their runs."""
    per = {}
    for t, c in rows:
        s = per.setdefault(t, [0, 0]); s[1] += 1; s[0] += c == "failure"
    if not per: return 0.0, 0, 0
    failing = sum(1 for f, n in per.values() if f / n >= 0.5)
    return failing / len(per), len(per), failing

def evaluate(db, th=Thresholds(), eligible=None):
    """eligible: optional set of tenant keys allowed to count toward wave thresholds (sybil resistance)."""
    out = []
    for (image_os,) in db.execute("SELECT DISTINCT image_os FROM beacons"):
        vers = sorted({v for (v,) in db.execute("SELECT DISTINCT image_version FROM beacons WHERE image_os=?", (image_os,))}, key=version_key)
        for prev, cur in zip(vers, vers[1:]):
            first = db.execute("SELECT MIN(ts) FROM beacons WHERE image_os=? AND image_version=?", (image_os, cur)).fetchone()[0]
            q = "SELECT tenant, conclusion FROM beacons WHERE image_os=? AND image_version=? AND conclusion IN ('success','failure')"
            cur_rows = db.execute(q + " AND ts<=?", (image_os, cur, first + th.window_s)).fetchall()
            prev_rows = db.execute(q, (image_os, prev)).fetchall()
            if eligible is not None:
                cur_rows = [r for r in cur_rows if r[0] in eligible]; prev_rows = [r for r in prev_rows if r[0] in eligible]
            ps, pn, pf = tenant_failure_share(prev_rows); cs, cn, cf = tenant_failure_share(cur_rows)
            flagged = (cn >= th.min_tenants and cf >= th.min_failing_tenants and cs - ps >= th.min_jump and cs >= max(ps * th.ratio, 1e-9))
            cats = dict(db.execute("SELECT step_category, COUNT(*) FROM beacons WHERE image_os=? AND image_version=? AND conclusion='failure' GROUP BY 1", (image_os, cur)).fetchall())
            out.append(dict(image_os=image_os, prev_version=prev, version=cur, prev_share=round(ps, 3), share=round(cs, 3),
                            tenants=cn, failing_tenants=cf, prev_tenants=pn, flagged=flagged, failure_categories=cats))
    return out
