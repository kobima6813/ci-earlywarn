# Privacy & security note (v0.1)
- Opt-in only: nothing is sent unless a repo adds the step and sets an endpoint.
- Sent fields (complete list): `tenant` (sha256(salt|org)[:16], salt is the customer's own secret, never sent), `runner_os`, `image_os`, `image_version`, `conclusion`, `step_category` (one of install/build/test/lint/deploy/cache/docker/other/none — step names are NOT sent), optional `toolchain` major.minor versions, `ts`.
- Never sent: code, logs, step names, repo names, usernames, secrets, IPs are not stored by the collector.
- Collector rejects any unknown field (so a modified client cannot smuggle logs), caps body at 2 KB, validates lengths.
- Org-level hashing: repos of one org count as ONE tenant, so one big org cannot fake a cross-tenant wave alone.
- Known gaps before launch: rate limiting/auth tokens per tenant (Sybil resistance), TLS termination (Railway provides), retention policy (proposal: 90 days raw, aggregates forever), DPA/terms text, abuse review of the Action's code by a third party.
- Webhooks are off by default; secrets only via env vars, none in code.

## v0.2
See DPA_DRAFT.md. Tokens hashed, IP only in memory for rate limits, OIDC tokens verified then discarded, owner id stored only salted-hashed, 90-day retention job.
