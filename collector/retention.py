"""Retention job: delete raw beacons older than EW_RETENTION_DAYS (default 90). Run daily (Railway cron)."""
import os
from . import store, security
if __name__ == "__main__":
    db = store.connect(os.environ.get("EW_DB", "data/earlywarn.db"))
    print("purged", security.purge(db, int(os.environ.get("EW_RETENTION_DAYS", "90"))))
