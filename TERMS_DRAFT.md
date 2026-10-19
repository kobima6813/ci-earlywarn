# CI Early-Warn — Terms of Service (DRAFT v0.2, not legal advice, not in force)
1. **Service.** CI Early-Warn ("we") runs a collector that receives opt-in, anonymized CI health beacons and publishes aggregate runner-image health signals and alerts.
2. **Opt-in.** You choose to install the Action and may remove it at any time. Revoking your token stops collection.
3. **What you send.** Only the fields listed in DPA_DRAFT.md §2. You must not modify the Action to send source code, logs, secrets or personal data.
4. **Tokens.** Tokens are per tenant, shown once, and stored by us only as a hash. Keep them secret; we may revoke abused tokens.
5. **Acceptable use.** No fake tenants, replayed or fabricated beacons, attempts to trigger false alerts, scraping beyond rate limits, or probing the service.
6. **Signals are advisory.** Alerts are statistical and may be wrong or late. No warranty; service provided "as is". Liability limited to fees paid in the prior 12 months (zero on the free tier).
7. **Aggregate data.** We may publish aggregate, non-identifying statistics (e.g. failure share per image version with ≥5 tenants). Never per-tenant data.
8. **Changes / termination.** We may change these terms with 30 days' notice, or end the service with 30 days' notice and delete data per DPA_DRAFT.md.
9. **Contact.** [TBD before launch]. Governing law: [TBD].
