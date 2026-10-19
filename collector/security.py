"""Tenant tokens, rate limits, GitHub OIDC verification (stdlib RSA), sybil eligibility, retention."""
import base64, hashlib, hmac, json, os, secrets, threading, time, urllib.request

TENANT_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants(id TEXT PRIMARY KEY, token_hash TEXT UNIQUE, created INTEGER,
  verified INTEGER DEFAULT 0, owner_hash TEXT, verified_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_owner ON tenants(owner_hash);
"""
def init(db): db.executescript(TENANT_SCHEMA)

def _h(s): return hashlib.sha256(s.encode()).hexdigest()

def signup(db, now=None):
    """Returns (tenant_id, token). Only the token hash is stored."""
    tok = "ewt_" + secrets.token_urlsafe(32); tid = "tn_" + secrets.token_hex(8)
    db.execute("INSERT INTO tenants(id,token_hash,created) VALUES(?,?,?)", (tid, _h(tok), int(now or time.time()))); db.commit()
    return tid, tok

def tenant_for_token(db, tok):
    if not tok or not tok.startswith("ewt_"): return None
    r = db.execute("SELECT id, owner_hash FROM tenants WHERE token_hash=?", (_h(tok),)).fetchone()
    return r and {"id": r[0], "owner_hash": r[1]}

def canonical_tenant(t):
    """Verified tenants collapse to their GitHub owner: many tokens for one org = one tenant."""
    return "own_" + t["owner_hash"][:16] if t.get("owner_hash") else t["id"]

def eligible_tenants(db, min_age_days=7, now=None):
    now = now or time.time(); out = set()
    for tid, created, verified, owner in db.execute("SELECT id, created, verified, owner_hash FROM tenants"):
        if verified and owner: out.add("own_" + owner[:16])
        elif created <= now - min_age_days * 86400: out.add(tid)
    return out

class RateLimiter:
    """Token bucket per key. rate per second, burst capacity."""
    def __init__(self, rate, burst):
        self.rate, self.burst, self.b, self.lock = rate, burst, {}, threading.Lock()
    def allow(self, key, now=None):
        now = now or time.monotonic()
        with self.lock:
            tokens, last = self.b.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < 1: self.b[key] = (tokens, now); return False
            self.b[key] = (tokens - 1, now); return True

# ---- GitHub Actions OIDC -------------------------------------------------
ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = ISSUER + "/.well-known/jwks"
_jwks_cache = {"t": 0, "keys": {}}

def _b64d(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
def _int(b): return int.from_bytes(_b64d(b), "big")

def fetch_jwks(url=JWKS_URL, ttl=3600):
    if time.time() - _jwks_cache["t"] < ttl and _jwks_cache["keys"]: return _jwks_cache["keys"]
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ci-earlywarn"}), timeout=10))
    _jwks_cache.update(t=time.time(), keys={k["kid"]: k for k in d["keys"] if k.get("kty") == "RSA"}); return _jwks_cache["keys"]

_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
def rsa_verify_pkcs1_sha256(n, e, msg, sig):
    k = (n.bit_length() + 7) // 8
    if len(sig) != k: return False
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    t = _SHA256_PREFIX + hashlib.sha256(msg).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)

class OIDCError(ValueError): pass

def verify_github_oidc(token, audience, jwks=None, now=None, leeway=60):
    try: h64, p64, s64 = token.split(".")
    except Exception: raise OIDCError("malformed")
    try: hdr, claims = json.loads(_b64d(h64)), json.loads(_b64d(p64))
    except Exception: raise OIDCError("malformed")
    if hdr.get("alg") != "RS256": raise OIDCError("alg")
    keys = jwks if jwks is not None else fetch_jwks()
    if "keys" in keys and isinstance(keys["keys"], list): keys = {k["kid"]: k for k in keys["keys"] if k.get("kty") == "RSA"}
    k = keys.get(hdr.get("kid"))
    if not k: raise OIDCError("unknown kid")
    if not rsa_verify_pkcs1_sha256(_int(k["n"]), _int(k["e"]), f"{h64}.{p64}".encode(), _b64d(s64)): raise OIDCError("signature")
    now = now or time.time()
    if claims.get("iss") != ISSUER: raise OIDCError("iss")
    aud = claims.get("aud"); aud = aud if isinstance(aud, list) else [aud]
    if audience not in aud: raise OIDCError("aud")
    if not (claims.get("nbf", 0) - leeway <= now < claims.get("exp", 0) + leeway): raise OIDCError("expired")
    if not claims.get("repository_owner_id"): raise OIDCError("no owner")
    return claims

def mark_verified(db, tenant_id, claims, salt):
    """Store only a salted hash of the GitHub owner id; never the repo name or token."""
    owner_hash = _h(salt + "|" + str(claims["repository_owner_id"]))
    db.execute("UPDATE tenants SET verified=1, owner_hash=?, verified_at=? WHERE id=?", (owner_hash, int(time.time()), tenant_id)); db.commit()
    return owner_hash

def purge(db, days=90, now=None):
    cut = int((now or time.time()) - days * 86400)
    n = db.execute("DELETE FROM beacons WHERE ts < ?", (cut,)).rowcount; db.commit(); return n
