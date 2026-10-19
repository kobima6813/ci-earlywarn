"""Zero-customer signal: poll public runner-images releases and new regression issues (unauthenticated)."""
import json, re, urllib.request, urllib.parse
from . import store
API = "https://api.github.com"
def _get(url, fetch=None):
    if fetch: return fetch(url)
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ci-earlywarn"}), timeout=20))

def poll(db, since_iso, fetch=None):
    """Returns new early-signal alerts. `fetch` lets tests inject fixtures."""
    new = []
    for r in _get(f"{API}/repos/actions/runner-images/releases?per_page=30", fetch):
        if (r.get("published_at") or "") >= since_iso:
            p = {"title": f"New runner image rolling out: {r['tag_name']}", "tag": r["tag_name"], "published": r["published_at"], "url": r.get("html_url")}
            if store.add_alert(db, "image_release", r["tag_name"], p): new.append(p)
    q = urllib.parse.quote(f'repo:actions/runner-images is:issue "Is it regression?" created:>={since_iso[:10]}')
    for i in _get(f"{API}/search/issues?per_page=50&q={q}", fetch).get("items", []):
        body = i.get("body") or ""
        m = re.search(r"Is it regression\?\s*\n+\s*(.+)", body)
        if m and m.group(1).strip().lower().startswith("yes"):
            vers = re.findall(r"(\d{8}\.\d+)", body)
            p = {"title": f"Early signal: public regression report #{i['number']}: {i['title'][:100]}", "issue": i["number"],
                 "created": i["created_at"], "image_versions": sorted(set(vers))[:5], "url": i.get("html_url")}
            if store.add_alert(db, "early_signal", f"issue:{i['number']}", p): new.append(p)
    return new

if __name__ == "__main__":
    import os, datetime
    db = store.connect(os.environ.get("EW_DB", "data/earlywarn.db"))
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for a in poll(db, since): print(a["title"])
