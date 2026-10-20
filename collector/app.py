"""Collector API v0.3 (stdlib). POST /v1/signup, POST /v1/verify, POST /v1/beacon, GET /v1/status, /v1/alerts, /, /healthz."""
import json, os, html, time, datetime, threading
from zoneinfo import ZoneInfo
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from . import store, detector, alerts as A, security as S

MAX_BODY = 2048
DB_LOCK = threading.Lock()   # one shared sqlite connection: serialize requests and background jobs
class Config:
    def __init__(self, **kw):
        self.audience = os.environ.get("EW_OIDC_AUDIENCE", "ci-earlywarn")
        self.owner_salt = os.environ.get("EW_OWNER_SALT", "")      # set in prod via env; empty only for local dev
        self.min_age_days = float(os.environ.get("EW_MIN_TENANT_AGE_DAYS", "7"))
        self.tz = os.environ.get("EW_TZ", "Asia/Jerusalem")
        self.token_rate, self.token_burst = 1.0, 30     # per token: 1 req/s sustained, burst 30
        self.ip_rate, self.ip_burst = 2.0, 60           # per IP
        self.signup_rate, self.signup_burst = 1 / 600, 3  # per IP: 3 signups, then 1 per 10 min
        self.jwks = None                                  # tests inject a dict; None = fetch GitHub JWKS
        self.require_eligibility = True
        self.__dict__.update(kw)

def ip_key(ip):
    """Rate-limit key: IPv4 as-is, IPv6 collapsed to its /48 (clients can rotate addresses inside their prefix)."""
    import ipaddress
    try:
        a = ipaddress.ip_address(ip)
        return str(ipaddress.ip_network(f"{a}/48", strict=False)) if a.version == 6 else str(a)
    except ValueError: return ip

def eligible(db, cfg):
    return S.eligible_tenants(db, cfg.min_age_days) if cfg.require_eligibility else None

def run_detector(db, th=detector.Thresholds(), notify=True, eligible_set=None):
    res = detector.evaluate(db, th, eligible_set); new = []
    for r in res:
        if r["flagged"]:
            p = A.regression_payload(r)
            if store.add_alert(db, "regression", f"{r['image_os']}:{r['version']}", p):
                new.append(p)
                if notify:
                    try: A.send_webhook(p)
                    except Exception: pass
    return res, new

def fmt_times(tz):
    now = datetime.datetime.now(datetime.timezone.utc)
    return f"{now:%Y-%m-%d %H:%M} UTC · {now.astimezone(ZoneInfo(tz)):%Y-%m-%d %H:%M} {tz}"

def status_html(db, res, tz="Asia/Jerusalem"):
    rows = "".join(f"<tr class={'bad' if r['flagged'] else 'ok'}><td>{html.escape(r['image_os'])}</td><td>{html.escape(r['version'])}</td>"
                   f"<td>{r['tenants']}</td><td>{r['failing_tenants']}</td><td>{r['share']:.0%}</td><td>{r['prev_share']:.0%}</td>"
                   f"<td>{('REGRESSION: ' + html.escape((r.get('diagnosis') or {}).get('label', ''))) if r['flagged'] else 'healthy'}</td></tr>" for r in res)
    al = "".join(f"<li><b>{html.escape(a['kind'])}</b> {html.escape(a.get('title',''))}</li>" for a in store.alerts(db, 20))
    return f"""<!doctype html><html><head><meta charset=utf-8><title>CI Early-Warn status</title><style>
body{{font-family:system-ui,Arial;margin:24px}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 8px}}
tr.bad{{background:#fdd}}tr.ok{{background:#efe}}</style></head><body><h1>CI Early-Warn — runner image health</h1>
<p>Cross-tenant failure share per image version (eligible tenants with ≥50% failing runs). Generated {fmt_times(tz)}.</p>
<table><tr><th>Image</th><th>Version</th><th>Tenants</th><th>Failing</th><th>Fail share</th><th>Prev share</th><th>State</th></tr>{rows}</table>
<h2>Recent alerts</h2><ul>{al or '<li>none</li>'}</ul></body></html>"""

def make_handler(db, th, cfg):
    tok_rl = S.RateLimiter(cfg.token_rate, cfg.token_burst); ip_rl = S.RateLimiter(cfg.ip_rate, cfg.ip_burst)
    su_rl = S.RateLimiter(cfg.signup_rate, cfg.signup_burst)
    lock = DB_LOCK
    class H(BaseHTTPRequestHandler):
        timeout = 10   # drop slow clients so they cannot hold the DB lock
        def do_POST(self):
            with lock: return self._post()
        def do_GET(self):
            with lock: return self._get()
        def log_message(self, *a): pass
        _logged = [False]
        def _ip(self):
            if not H._logged[0]:   # one-time diagnostic: header NAMES only, never values
                H._logged[0] = True
                print("proxy trust:", os.environ.get("EW_TRUST_PROXY") == "1", "fwd headers:", sorted(k for k in self.headers.keys() if "forward" in k.lower() or "real" in k.lower() or k.lower().startswith("x-envoy")), flush=True)
            return ip_key(self._ip_inner())
        def _ip_inner(self):  # behind Railway proxy use first X-Forwarded-For hop only when EW_TRUST_PROXY=1
            if os.environ.get("EW_TRUST_PROXY") == "1":
                if self.headers.get("X-Real-IP"): return self.headers["X-Real-IP"].strip()
                if self.headers.get("X-Forwarded-For"): return self.headers["X-Forwarded-For"].split(",")[0].strip()
            return self.client_address[0]
        def _send(self, code, body, ctype="application/json"):
            b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n < 0 or n > MAX_BODY: raise OverflowError
            return json.loads(self.rfile.read(n) or b"{}")
        def _tenant(self):
            a = self.headers.get("Authorization", "")
            return S.tenant_for_token(db, a[7:].strip()) if a.startswith("Bearer ") else None
        def _maybe_verify(self, t):
            oidc = self.headers.get("X-GitHub-OIDC")
            if not oidc or t.get("owner_hash"): return t
            if not cfg.owner_salt and os.environ.get("PORT"): return t   # refuse to verify in prod without a salt
            try:
                claims = S.verify_github_oidc(oidc, cfg.audience, jwks=cfg.jwks)
                t["owner_hash"] = S.mark_verified(db, t["id"], claims, cfg.owner_salt)
            except Exception: pass   # unverified tenants still accepted; they just age into eligibility
            return t
        def _post(self):
            ip = self._ip()
            if not ip_rl.allow(ip): return self._send(429, {"error": "rate limit (ip)"})
            try: body = self._body()
            except OverflowError: return self._send(413, {"error": "size"})
            except Exception: return self._send(400, {"error": "json"})
            if self.path == "/v1/signup":
                if not su_rl.allow(ip): return self._send(429, {"error": "signup rate limit"})
                tid, tok = S.signup(db); return self._send(201, {"tenant_id": tid, "token": tok, "note": "store as secret EW_TOKEN; shown once"})
            t = self._tenant()
            if not t: return self._send(401, {"error": "token required"})
            if not tok_rl.allow(t["id"]): return self._send(429, {"error": "rate limit (token)"})
            t = self._maybe_verify(t)
            if self.path == "/v1/verify":
                return self._send(200 if t.get("owner_hash") else 403, {"verified": bool(t.get("owner_hash"))})
            if self.path != "/v1/beacon": return self._send(404, {"error": "not found"})
            body["tenant"] = S.canonical_tenant(t)          # server-assigned; client cannot choose its tenant id
            try: store.insert(db, body)
            except Exception as e: return self._send(400, {"error": str(e)[:100]})
            run_detector(db, th, eligible_set=eligible(db, cfg)); self._send(202, {"ok": True, "verified": bool(t.get("owner_hash"))})
        def _get(self):
            if not ip_rl.allow(self._ip()): return self._send(429, {"error": "rate limit (ip)"})
            el = eligible(db, cfg)
            if self.path == "/v1/status": return self._send(200, detector.evaluate(db, th, el))
            if self.path == "/v1/alerts": return self._send(200, store.alerts(db))
            if self.path in ("/", "/status"): return self._send(200, status_html(db, detector.evaluate(db, th, el), cfg.tz), "text/html; charset=utf-8")
            if self.path == "/healthz": return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})
    return H

def serve(db_path=None, port=None, th=detector.Thresholds(), cfg=None):
    cfg = cfg or Config()
    db = store.connect(db_path or os.environ.get("EW_DB", "data/earlywarn.db"))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    srv = ThreadingHTTPServer((host, int(port if port is not None else os.environ.get("PORT", 8787))), make_handler(db, th, cfg))
    return srv, db

if __name__ == "__main__":
    srv, _ = serve(); print("listening", srv.server_address); srv.serve_forever()
