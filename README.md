# CI Early-Warn

**Live status page:** https://collector-production-5b85.up.railway.app/ · API: `/v1/status`, `/v1/alerts`

Get early warning when a new GitHub-hosted runner image starts breaking builds across many repos, often days before a public issue shows up. Opt-in, anonymized and MIT-licensed.

## Install (3 lines)
```bash
curl -s -X POST https://collector-production-5b85.up.railway.app/v1/signup   # -> {"token": "ewt_..."}; save as repo secret EW_TOKEN
# add `permissions: {actions: read, id-token: write}` to your workflow, then as the LAST step of a job:
- {if: always(), uses: kobima6813/ci-earlywarn/action/js@v0.2.1, with: {endpoint: "https://collector-production-5b85.up.railway.app/v1/beacon", token: "${{ secrets.EW_TOKEN }}", job-status: "${{ job.status }}"}}
```
A full example is in `examples/smoke.yml`.


Neutral cross-tenant early warning for GitHub-hosted runner-image regressions.

## Components
- `action/` – opt-in composite GitHub Action (`action.yml` + `beacon.py`, stdlib only). Add as the LAST step of a job:
  ```yaml
  - uses: kobima6813/ci-earlywarn/action@v0.2.1   # composite fallback (needs python3 on the runner)
    if: always()
    with:
      endpoint: ${{ vars.EW_ENDPOINT }}
      tenant-salt: ${{ secrets.EW_SALT }}
      job-status: ${{ job.status }}
      failed-step: ""          # optional; only a category is sent
  ```
  Sends: salted org hash, RUNNER_OS, ImageOS, ImageVersion, job conclusion, failing-step category, optional toolchain major.minor versions, timestamp. Never fails the job.
- `collector/app.py` – stdlib HTTP API + SQLite: `POST /v1/beacon`, `GET /v1/status`, `GET /v1/alerts`, `GET /` status page, `/healthz`. Strict schema (unknown fields rejected, 2 KB body cap).
- `collector/detector.py` – flags image version N when, versus N-1 of the same ImageOS: ≥5 tenants seen, ≥3 failing tenants (≥50% failing runs), failing-tenant share +15 pts and ≥2× previous. Thresholds configurable.
- `collector/alerts.py` – Slack-compatible webhook (only if `EW_WEBHOOK_URL` set), email-ready JSON.
- `collector/bootstrap.py` – zero-customer signal: polls public runner-images releases + new "Is it regression? Yes" issues (unauthenticated).
- `replay.py` – r108 backtest timings through the real detector. `demo.py` – 20-tenant end-to-end demo over HTTP.

## Run
```
python3 -m unittest -v tests/test_all.py
python3 demo.py        # writes out/status.html, out/demo_alerts.json
python3 replay.py      # writes out/replay.json
EW_DB=data/earlywarn.db python3 -m collector.app   # localhost:8787
```

## v0.2 hardening (local only)
- `POST /v1/signup` → per-tenant `ewt_` token (hash-only storage, signup rate-limited per IP). Beacons require `Authorization: Bearer`; the server assigns the tenant id (client `tenant` ignored).
- Rate limits: per IP and per token (token bucket) → 429.
- Sybil resistance: only *eligible* tenants count toward wave thresholds: ≥7 days old (`EW_MIN_TENANT_AGE_DAYS`) or verified by a GitHub Actions OIDC token (`X-GitHub-OIDC` header, aud `ci-earlywarn`, RS256 vs GitHub JWKS, stdlib RSA). Verified tokens of the same GitHub owner collapse to one tenant. Set `EW_OWNER_SALT` in prod (verification refused without it when `PORT` is set).
- Retention: `python3 -m collector.retention` (default 90 days, `EW_RETENTION_DAYS`).
- JS action `action/js` (node20, no deps): finds the failed step via `GET /repos/{repo}/actions/runs/{id}/attempts/{n}/jobs` with read-only `GITHUB_TOKEN`, categorizes locally, attaches OIDC if `id-token: write`. Composite action kept as fallback (now accepts `token`).
```yaml
permissions: {actions: read, id-token: write}
steps:
  - if: always()
    uses: ./action/js
    with: {endpoint: "https://<collector>/v1/beacon", token: "${{ secrets.EW_TOKEN }}", job-status: "${{ job.status }}"}
```
- Status page shows UTC and Asia/Jerusalem (`EW_TZ`). Drafts: TERMS_DRAFT.md, DPA_DRAFT.md.
