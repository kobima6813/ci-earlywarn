# Railway deploy plan (v0.1 plan; see README for the live deploy)
1. New Railway project `ci-earlywarn` (one service, Python 3.12, start: `python3 -m collector.app`; Railway sets `PORT`, app then binds 0.0.0.0).
2. Volume mounted at `/data`; env `EW_DB=/data/earlywarn.db`. Optional env `EW_WEBHOOK_URL` (secret).
3. Cron service (Railway cron, every 30 min): `python3 -m collector.bootstrap` for bootstrap polling (unauthenticated GitHub, ~2 calls/run, within 60/h).
4. Generate a Railway domain; put status page at `/`. Add per-tenant ingest tokens + rate limit before public launch.
5. Publish Action: separate public repo `<org>/ci-earlywarn-action`, tag `v0`, Marketplace listing — only after approval.
Cost estimate: hobby plan, single small service + volume (~$5–10/mo at v0 volumes).

## v0.2 (not executed)
Add env `EW_OWNER_SALT` (random secret), optional `EW_TRUST_PROXY=1` (use first X-Forwarded-For hop for per-IP limits), `EW_MIN_TENANT_AGE_DAYS=7`, `EW_RETENTION_DAYS=90`; add a daily cron service running `python3 -m collector.retention`.
