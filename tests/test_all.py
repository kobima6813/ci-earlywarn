import json, os, time, random, sys, threading, unittest, urllib.request, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "action"))
from collector import store, detector, alerts as A, app, sim, bootstrap, security
import beacon

class Beacon(unittest.TestCase):
    def test_anonymized_and_minimal(self):
        env = {"EW_SALT": "s3cr3t", "GITHUB_REPOSITORY": "acme/payments", "RUNNER_OS": "Linux", "ImageOS": "ubuntu24",
               "ImageVersion": "20261012.1", "EW_STATUS": "Failure", "EW_STEP": "Run unit tests", "EW_TOOLCHAIN": "false"}
        b = beacon.build(env, toolchain=False)
        s = json.dumps(b)
        self.assertNotIn("acme", s); self.assertNotIn("payments", s); self.assertNotIn("s3cr3t", s)
        self.assertEqual(b["step_category"], "test"); self.assertEqual(b["conclusion"], "failure")
        store.validate(b)
    def test_hash_depends_on_salt(self):
        self.assertNotEqual(beacon.tenant_hash("a", "o/r"), beacon.tenant_hash("b", "o/r"))
        self.assertEqual(beacon.tenant_hash("a", "o/r1"), beacon.tenant_hash("a", "o/r2"))  # org-level tenant
    def test_categories(self):
        self.assertEqual(beacon.categorize(""), "none"); self.assertEqual(beacon.categorize("npm ci install"), "install")
        self.assertEqual(beacon.categorize("weird"), "other")

class Store(unittest.TestCase):
    def test_rejects_extra_fields_and_logs(self):
        db = store.connect()
        with self.assertRaises(ValueError): store.insert(db, {"tenant": "t", "image_os": "u", "image_version": "1", "conclusion": "failure", "log": "secret"})
        with self.assertRaises(ValueError): store.insert(db, {"tenant": "t", "image_os": "u", "image_version": "1", "conclusion": "exploded"})
    def test_alert_dedupe(self):
        db = store.connect(); self.assertTrue(store.add_alert(db, "k", "x", {})); self.assertFalse(store.add_alert(db, "k", "x", {}))

def feed(db, ev):
    for e in ev: store.insert(db, e)

class Detector(unittest.TestCase):
    def test_flags_injected_regression(self):
        db = store.connect(); ev, _ = sim.stream(random.Random(1), 20, 1_000_000, "20260101.1", "20260108.1", affected_frac=0.3)
        feed(db, ev); r = [x for x in detector.evaluate(db) if x["version"] == "20260108.1"][0]
        self.assertTrue(r["flagged"]); self.assertGreaterEqual(r["failing_tenants"], 3)
    def test_no_false_alarm_on_healthy(self):
        for seed in range(5):
            db = store.connect(); ev, _ = sim.stream(random.Random(seed), 20, 1_000_000, "20260101.1", "20260108.1", affected_frac=0.0)
            feed(db, ev); self.assertFalse(any(x["flagged"] for x in detector.evaluate(db)))
    def test_min_tenants(self):
        db = store.connect(); ev, _ = sim.stream(random.Random(2), 3, 1_000_000, "20260101.1", "20260108.1", affected_frac=1.0)
        feed(db, ev); self.assertFalse(any(x["flagged"] for x in detector.evaluate(db)))
    def test_version_sort(self):
        self.assertLess(detector.version_key("20260101.9"), detector.version_key("20260101.10"))

def _img(db, tenants, ver, concl, t0, n=3, mode=None, actions=None):
    for t in tenants:
        for i in range(n):
            b = {"tenant": t, "image_os": "u", "image_version": ver, "conclusion": concl, "ts": t0 + i}
            if mode: b["mode"] = mode
            if actions is not None: b["actions"] = actions
            store.insert(db, b)

class V11(unittest.TestCase):
    T = [f"t{i}" for i in range(8)]
    def test_old_beacons_still_valid_and_migration(self):
        import sqlite3, tempfile
        p = tempfile.mktemp(); raw = sqlite3.connect(p)
        raw.executescript("CREATE TABLE beacons(id INTEGER PRIMARY KEY, tenant TEXT, runner_os TEXT, image_os TEXT, image_version TEXT, conclusion TEXT, step_category TEXT, toolchain TEXT, ts INTEGER);")
        raw.execute("INSERT INTO beacons(tenant,image_os,image_version,conclusion,ts) VALUES('a','u','1','success',1)"); raw.commit(); raw.close()
        db = store.connect(p); store.insert(db, {"v": 2, "tenant": "b", "image_os": "u", "image_version": "1", "conclusion": "failure"})
        self.assertEqual(db.execute("SELECT COUNT(*) FROM beacons WHERE COALESCE(mode,'all')='all'").fetchone()[0], 2)
    def test_rejects_bad_new_fields(self):
        db = store.connect(); base = {"tenant": "t", "image_os": "u", "image_version": "1", "conclusion": "failure"}
        for bad in ({"mode": "x"}, {"actions": ["actions/checkout@v4"]}, {"actions": "ab" * 8}, {"actions": ["0123456789abcdef"] * 21}):
            with self.assertRaises(ValueError): store.insert(db, {**base, **bad})
        store.insert(db, {**base, "mode": "failures_only", "actions": ["0123456789abcdef"]})
    def test_failures_only_tenants_do_not_inflate_share(self):
        db = store.connect(); t0 = 1_000_000
        _img(db, self.T, "1", "success", t0)                       # 8 full tenants healthy on both versions
        _img(db, self.T, "2", "success", t0 + 100)
        fo = [f"fo{i}" for i in range(6)]
        _img(db, fo, "1", "failure", t0, n=1, mode="failures_only")  # their normal background failures
        _img(db, fo, "2", "failure", t0 + 100, n=1, mode="failures_only")
        r = [x for x in detector.evaluate(db) if x["version"] == "2"][0]
        self.assertFalse(r["flagged"]); self.assertEqual(r["share"], 0.0); self.assertEqual(r["tenants"], 8)
        self.assertEqual(r["failures_only_tenants"], 6)
    def test_failures_only_tenants_count_toward_min_failing(self):
        db = store.connect(); t0 = 1_000_000
        _img(db, self.T, "1", "success", t0)
        _img(db, self.T[:2], "2", "failure", t0 + 100); _img(db, self.T[2:], "2", "success", t0 + 100)
        r = [x for x in detector.evaluate(db) if x["version"] == "2"][0]; self.assertFalse(r["flagged"])  # only 2 failing
        _img(db, ["fo1"], "2", "failure", t0 + 200, n=1, mode="failures_only")
        r = [x for x in detector.evaluate(db) if x["version"] == "2"][0]; self.assertTrue(r["flagged"])
    def test_image_regression_label(self):
        db = store.connect(); t0 = 1_000_000; A1 = "aaaaaaaaaaaaaaaa"
        _img(db, self.T, "2", "failure", t0, actions=[A1, "bbbbbbbbbbbbbbbb"])        # new version fails
        _img(db, self.T, "1", "success", t0 - 1000, actions=[A1])                     # baseline
        _img(db, self.T, "1", "success", t0 + 10, actions=[A1])                       # same tenants on old version still pass
        r = [x for x in detector.evaluate(db) if x["version"] == "2"][0]
        self.assertTrue(r["flagged"]); self.assertEqual(r["diagnosis"]["label"], "likely image regression")
        self.assertEqual(r["diagnosis"]["suspect_action_hash"], None)
        self.assertNotIn("action breakage", A.regression_payload(r)["title"])
    def test_action_breakage_label(self):
        db = store.connect(); t0 = 1_000_000; BAD = "dddddddddddddddd"
        _img(db, self.T, "1", "success", t0 - 1000, actions=["cccccccccccccccc"])
        _img(db, self.T, "2", "failure", t0, actions=[BAD, "cccccccccccccccc"])
        _img(db, self.T[:4], "1", "failure", t0 + 10, actions=[BAD])                  # same action fails on the old image too
        for t in self.T[:4]:
            store.insert(db, {"tenant": t, "image_os": "w", "image_version": "9", "conclusion": "failure", "ts": t0 + 20, "actions": [BAD]})
        r = [x for x in detector.evaluate(db) if x["version"] == "2"][0]
        self.assertTrue(r["flagged"]); self.assertEqual(r["diagnosis"]["label"], "likely action breakage")
        self.assertEqual(r["diagnosis"]["suspect_action_hash"], BAD)
        self.assertIn("action breakage", A.regression_payload(r)["title"])
    def test_status_page_shows_label(self):
        db = store.connect(); t0 = 1_000_000
        _img(db, self.T, "1", "success", t0 - 1000); _img(db, self.T, "2", "failure", t0); _img(db, self.T, "1", "success", t0 + 10)
        self.assertIn("likely image regression", app.status_html(db, detector.evaluate(db)))

class Alerts(unittest.TestCase):
    def test_formats(self):
        r = {"image_os": "ubuntu24", "version": "2", "prev_version": "1", "failing_tenants": 4, "tenants": 20, "share": .2, "prev_share": 0}
        p = A.regression_payload(r); self.assertIn("text", A.slack(p)); self.assertIn("subject", A.email(p))
        os.environ.pop("EW_WEBHOOK_URL", None); self.assertFalse(A.send_webhook(p))

class Bootstrap(unittest.TestCase):
    def test_poll_with_fixtures(self):
        def fetch(url):
            if "releases" in url: return [{"tag_name": "ubuntu24/20261012.1", "published_at": "2026-10-12T10:00:00Z", "html_url": "u"}]
            return {"items": [{"number": 1, "title": "Java broke", "created_at": "2026-10-13T00:00:00Z", "html_url": "i",
                               "body": "Version: 20261012.1\n### Is it regression?\n\nYes, worked on 20261005.1"},
                              {"number": 2, "title": "q", "created_at": "2026-10-13T00:00:00Z", "body": "### Is it regression?\n\nNo"}]}
        db = store.connect(); new = bootstrap.poll(db, "2026-10-10T00:00:00Z", fetch=fetch)
        self.assertEqual(len(new), 2); self.assertEqual(bootstrap.poll(db, "2026-10-10T00:00:00Z", fetch=fetch), [])

def _post(base, path, body=b"{}", headers=None):
    return urllib.request.urlopen(urllib.request.Request(base + path, data=body, headers=headers or {}))

class API(unittest.TestCase):
    def setUp(self):
        self.cfg = app.Config(jwks=None)
        self.srv, self.db = app.serve(":memory:", 0, cfg=self.cfg); threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
    def tearDown(self): self.srv.shutdown()
    def test_http_roundtrip_with_token(self):
        tok = json.load(_post(self.base, "/v1/signup"))["token"]; self.assertTrue(tok.startswith("ewt_"))
        ok = {"tenant": "spoofed", "image_os": "u", "image_version": "1", "conclusion": "success", "ts": 1}
        self.assertEqual(_post(self.base, "/v1/beacon", json.dumps(ok).encode(), {"Authorization": "Bearer " + tok}).status, 202)
        t = self.db.execute("SELECT tenant FROM beacons").fetchone()[0]; self.assertTrue(t.startswith("tn_"))  # server-assigned
        with self.assertRaises(urllib.error.HTTPError) as c: _post(self.base, "/v1/beacon", b"x" * 5000)
        self.assertEqual(c.exception.code, 413)
        page = urllib.request.urlopen(self.base + "/").read().decode()
        self.assertIn("runner image health", page); self.assertIn("UTC", page); self.assertIn("Asia/Jerusalem", page)
    def test_401_without_or_bad_token(self):
        for h in ({}, {"Authorization": "Bearer ewt_nope"}):
            with self.assertRaises(urllib.error.HTTPError) as c: _post(self.base, "/v1/beacon", b"{}", h)
            self.assertEqual(c.exception.code, 401)
    def test_signup_rate_limit(self):
        codes = []
        for _ in range(5):
            try: codes.append(_post(self.base, "/v1/signup").status)
            except urllib.error.HTTPError as e: codes.append(e.code)
        self.assertEqual(codes[:3], [201] * 3); self.assertEqual(codes[3:], [429, 429])

class Concurrency(unittest.TestCase):
    def test_parallel_beacons_no_5xx(self):
        from concurrent.futures import ThreadPoolExecutor
        srv, db = app.serve(":memory:", 0, cfg=app.Config(token_rate=1e6, token_burst=1e6, ip_rate=1e6, ip_burst=1e6))
        threading.Thread(target=srv.serve_forever, daemon=True).start(); base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            tok = json.load(_post(base, "/v1/signup"))["token"]
            b = json.dumps({"image_os": "u", "image_version": "20261019.1", "conclusion": "success", "ts": 1}).encode()
            def one(_):
                try: return _post(base, "/v1/beacon", b, {"Authorization": "Bearer " + tok}).status
                except urllib.error.HTTPError as e: return e.code
                except Exception: return -1
            with ThreadPoolExecutor(20) as ex: codes = list(ex.map(one, range(100)))
            self.assertEqual(codes, [202] * 100)
        finally: srv.shutdown()
    def test_version_key_mixed(self):
        self.assertEqual(sorted(["20261019.1", "1", "abc", "20261005.2"], key=detector.version_key)[0], "1")

class IPKey(unittest.TestCase):
    def test_ipv6_prefix(self):
        self.assertEqual(app.ip_key("2a09:bac5:37ab:4aa::77:7b"), app.ip_key("2a09:bac5:37ab:26be::3dc:71"))
        self.assertEqual(app.ip_key("1.2.3.4"), "1.2.3.4"); self.assertEqual(app.ip_key("junk"), "junk")

class RateLimit(unittest.TestCase):
    def test_bucket(self):
        rl = security.RateLimiter(1.0, 2)
        self.assertEqual([rl.allow("k", 100), rl.allow("k", 100), rl.allow("k", 100)], [True, True, False])
        self.assertTrue(rl.allow("other", 100)); self.assertTrue(rl.allow("k", 101.5))
    def test_token_limit_http(self):
        srv, db = app.serve(":memory:", 0, cfg=app.Config(token_rate=0.001, token_burst=2)); threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            tok = json.load(_post(base, "/v1/signup"))["token"]; b = json.dumps({"image_os": "u", "image_version": "1", "conclusion": "success", "ts": 1}).encode()
            codes = []
            for _ in range(3):
                try: codes.append(_post(base, "/v1/beacon", b, {"Authorization": "Bearer " + tok}).status)
                except urllib.error.HTTPError as e: codes.append(e.code)
            self.assertEqual(codes, [202, 202, 429])
        finally: srv.shutdown()

def _jwt(key, kid, claims, alg="RS256"):
    import base64, hashlib
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    e = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    h = e(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode()); p = e(json.dumps(claims).encode())
    sig = key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{h}.{p}.{e(sig)}"

def _jwks(key, kid):
    import base64
    n = key.public_key().public_numbers(); e = lambda i: base64.urlsafe_b64encode(i.to_bytes((i.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
    return {"keys": [{"kty": "RSA", "kid": kid, "alg": "RS256", "n": e(n.n), "e": e(n.e)}]}

class OIDC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives.asymmetric import rsa
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.evil = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwks = _jwks(cls.key, "k1")
    def claims(self, **kw):
        now = int(time.time()); c = {"iss": security.ISSUER, "aud": "ci-earlywarn", "iat": now, "nbf": now - 5, "exp": now + 300,
             "repository_owner_id": "4242", "repository": "acme/app"}; c.update(kw); return c
    def test_valid(self):
        self.assertEqual(security.verify_github_oidc(_jwt(self.key, "k1", self.claims()), "ci-earlywarn", jwks=self.jwks)["repository_owner_id"], "4242")
    def test_rejects(self):
        bad = [_jwt(self.evil, "k1", self.claims()), _jwt(self.key, "k1", self.claims(aud="other")),
               _jwt(self.key, "k1", self.claims(exp=int(time.time()) - 3600)), _jwt(self.key, "k1", self.claims(iss="https://evil")),
               _jwt(self.key, "k2", self.claims()), _jwt(self.key, "k1", self.claims(repository_owner_id=None))]
        hs = _jwt(self.key, "k1", self.claims()).split("."); import base64
        hs[0] = base64.urlsafe_b64encode(json.dumps({"alg": "none", "kid": "k1"}).encode()).rstrip(b"=").decode(); bad.append(".".join(hs))
        for t in bad:
            with self.assertRaises(security.OIDCError): security.verify_github_oidc(t, "ci-earlywarn", jwks=self.jwks)
    def test_http_verify_collapses_owner(self):
        srv, db = app.serve(":memory:", 0, cfg=app.Config(jwks=self.jwks, owner_salt="s")); threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            toks = [json.load(_post(base, "/v1/signup"))["token"] for _ in range(2)]
            for t in toks:
                r = json.load(_post(base, "/v1/verify", b"{}", {"Authorization": "Bearer " + t, "X-GitHub-OIDC": _jwt(self.key, "k1", self.claims())}))
                self.assertTrue(r["verified"])
            el = security.eligible_tenants(db, 7); self.assertEqual(len(el), 1)  # two tokens, one GitHub owner = one tenant
            self.assertNotIn("4242", json.dumps(db.execute("SELECT * FROM tenants").fetchall()))  # only salted hash stored
            t3 = json.load(_post(base, "/v1/signup"))["token"]
            with self.assertRaises(urllib.error.HTTPError) as c:
                _post(base, "/v1/verify", b"{}", {"Authorization": "Bearer " + t3, "X-GitHub-OIDC": _jwt(self.evil, "k1", self.claims())})
            self.assertEqual(c.exception.code, 403)
        finally: srv.shutdown()

class Sybil(unittest.TestCase):
    def test_eligibility_by_age(self):
        db = store.connect(); now = 1_800_000_000
        old, _ = security.signup(db, now - 10 * 86400); new, _ = security.signup(db, now - 86400)
        self.assertEqual(security.eligible_tenants(db, 7, now), {old})
    def test_fresh_sybils_cannot_trigger_alert(self):
        db = store.connect(); t0 = 1_800_000_000
        ids = [security.signup(db, t0)[0] for _ in range(10)]   # 10 brand-new tenants all reporting failure
        for i, tid in enumerate(ids):
            store.insert(db, {"tenant": tid, "image_os": "u", "image_version": "2", "conclusion": "failure", "ts": t0 + i})
            store.insert(db, {"tenant": tid, "image_os": "u", "image_version": "1", "conclusion": "success", "ts": t0 - 100 + i})
        th = detector.Thresholds()
        self.assertTrue(any(r["flagged"] for r in detector.evaluate(db, th)))  # without filter: would alert
        el = security.eligible_tenants(db, 7, t0 + 3600)
        self.assertFalse(any(r["flagged"] for r in detector.evaluate(db, th, el)))

class Retention(unittest.TestCase):
    def test_purge_90d(self):
        db = store.connect(); now = 1_800_000_000
        for age in (1, 89, 91, 200):
            store.insert(db, {"tenant": "t", "image_os": "u", "image_version": "1", "conclusion": "success", "ts": now - age * 86400})
        self.assertEqual(security.purge(db, 90, now), 2); self.assertEqual(db.execute("SELECT COUNT(*) FROM beacons").fetchone()[0], 2)

class TZ(unittest.TestCase):
    def test_status_times(self):
        s = app.fmt_times("Asia/Jerusalem"); self.assertIn("UTC", s); self.assertIn("Asia/Jerusalem", s); self.assertNotIn("CEST", s)

class JSAction(unittest.TestCase):
    def test_node_tests(self):
        import subprocess, shutil
        node = shutil.which("node") or "/usr/local/bin/node"
        if not os.path.exists(node): self.skipTest("node not found")
        r = subprocess.run([node, "--test", os.path.join(os.path.dirname(__file__), "..", "action", "js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

if __name__ == "__main__": unittest.main()
