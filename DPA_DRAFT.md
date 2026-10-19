# CI Early-Warn — Data Processing Summary (DRAFT v0.2, not legal advice)
## 1. Roles & purpose
Sole purpose: detect GitHub-hosted runner image regressions across tenants and alert subscribers. No profiling, advertising or resale.
## 2. Data received per beacon
`runner_os, image_os, image_version, conclusion, step_category (one of 9 fixed words), optional toolchain major.minor, timestamp`.
Not received: repository/org names, step names, logs, code, secrets, user identities. The failing step name is read inside the runner via a read-only `GITHUB_TOKEN` and reduced to a category locally; the name never leaves the runner.
## 3. Tenant data
Random tenant id; SHA-256 hash of the token; creation time. If the tenant verifies with a GitHub Actions OIDC token: a salted SHA-256 of the numeric `repository_owner_id` and the verification time. The OIDC token itself is verified and discarded, never stored.
## 4. Network metadata
Client IP is held in memory only for rate limiting (token buckets) and is not written to disk.
## 5. Retention
Raw beacons deleted after 90 days (`python3 -m collector.retention`, run daily). Alerts (aggregates only) kept for the service history. Tenant records deleted on token revocation request.
## 6. Security
TLS in transit (platform), least-privilege Action (`actions: read`, optional `id-token: write`), secrets only via env vars, field allowlist + 2 KB body cap, per-IP / per-token / per-IP-signup rate limits.
## 7. Sub-processors
Hosting provider [TBD, e.g. Railway]; optional webhook targets configured by the subscriber.
## 8. Requests
Delete-my-data: send tenant id; we delete the tenant row and its beacons within 30 days.
