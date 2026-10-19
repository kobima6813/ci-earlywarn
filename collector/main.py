"""Production entrypoint: collector API + background GitHub bootstrap poller (every 30 min) + daily retention purge."""
import os, threading, time, datetime, traceback
from . import app, bootstrap, security

def _since(days):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

def background(db):
    first, last_purge = True, 0
    while True:
        try:
            with app.DB_LOCK: new = bootstrap.poll(db, _since(14 if first else 2))
            first = False
            print(f"bootstrap: {len(new)} new alerts", flush=True)
        except Exception: traceback.print_exc()
        if time.time() - last_purge > 86400:
            try:
                with app.DB_LOCK: n = security.purge(db, int(os.environ.get("EW_RETENTION_DAYS", "90")))
                print("retention purged", n, flush=True); last_purge = time.time()
            except Exception: traceback.print_exc()
        time.sleep(int(os.environ.get("EW_POLL_SECONDS", "1800")))

if __name__ == "__main__":
    srv, db = app.serve()
    if os.environ.get("EW_BOOTSTRAP", "1") == "1":
        threading.Thread(target=background, args=(db,), daemon=True).start()
    print("listening", srv.server_address, flush=True); srv.serve_forever()
