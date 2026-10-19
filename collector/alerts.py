import json, os, urllib.request

def regression_payload(r):
    return {"title": f"Runner image regression suspected: {r['image_os']} {r['version']}",
            "image_os": r["image_os"], "version": r["version"], "prev_version": r["prev_version"],
            "failing_tenants": r["failing_tenants"], "tenants": r["tenants"], "share": r["share"], "prev_share": r["prev_share"],
            "categories": r.get("failure_categories", {}),
            "advice": f"Consider pinning to {r['image_os']} {r['prev_version']}-equivalent label or adding a workaround; watch status page."}

def slack(p):
    lines = [f"*{p['title']}*"] + [f"• {k}: {v}" for k, v in p.items() if k != "title"]
    return {"text": p["title"], "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]}}]}

def email(p):
    return {"subject": "[CI Early-Warn] " + p["title"], "text": "\n".join(f"{k}: {v}" for k, v in p.items()), "json": p}

def send_webhook(p, url=None):
    url = url or os.environ.get("EW_WEBHOOK_URL")
    if not url: return False   # disabled unless explicitly configured
    req = urllib.request.Request(url, data=json.dumps(slack(p)).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5); return True
