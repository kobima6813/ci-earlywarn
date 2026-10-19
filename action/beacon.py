"""Builds and sends an anonymized beacon. Never fails the job. Stdlib only."""
import hashlib, json, os, re, subprocess, time, urllib.request

CATEGORIES = [("install", r"install|setup|deps|restore|bootstrap"), ("build", r"build|compile|bundle|make|cmake"),
              ("test", r"test|spec|e2e|pytest|jest"), ("lint", r"lint|format|check|typecheck"),
              ("deploy", r"deploy|publish|release|push"), ("cache", r"cache"), ("docker", r"docker|image|container")]

def categorize(step: str) -> str:
    s = (step or "").lower()
    if not s: return "none"
    for cat, pat in CATEGORIES:
        if re.search(pat, s): return cat
    return "other"

def tenant_hash(salt: str, repo: str) -> str:
    org = repo.split("/")[0] if repo else ""
    return hashlib.sha256((salt + "|" + org).encode()).hexdigest()[:16]

def ver(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        m = re.search(r"(\d+\.\d+)", out.stdout + out.stderr)
        return m.group(1) if m else None
    except Exception:
        return None

def build(env=os.environ, toolchain=True):
    b = {"v": 1, "tenant": tenant_hash(env.get("EW_SALT", ""), env.get("GITHUB_REPOSITORY", "")),
         "runner_os": env.get("RUNNER_OS", ""), "image_os": env.get("ImageOS", ""), "image_version": env.get("ImageVersion", ""),
         "conclusion": (env.get("EW_STATUS") or "unknown").lower(), "step_category": categorize(env.get("EW_STEP", "")),
         "ts": int(time.time())}
    if toolchain and env.get("EW_TOOLCHAIN", "true") == "true":
        b["toolchain"] = {k: v for k, v in {"node": ver(["node", "--version"]), "python": ver(["python3", "--version"]),
                          "java": ver(["java", "-version"]), "go": ver(["go", "version"])}.items() if v}
    return b

if __name__ == "__main__":
    b = build()
    if not os.environ.get("EW_ENDPOINT"): raise SystemExit(0)
    req = urllib.request.Request(os.environ["EW_ENDPOINT"], data=json.dumps(b).encode(), headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + os.environ["EW_TOKEN"]} if os.environ.get("EW_TOKEN") else {})})
    try: urllib.request.urlopen(req, timeout=5)
    except Exception as e: print("beacon not delivered:", type(e).__name__)
