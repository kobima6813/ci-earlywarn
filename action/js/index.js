// CI Early-Warn JS action. Never fails the job: all errors are swallowed and logged as a notice.
const { execFileSync } = require("child_process");
const { failedStepFromJobs, buildBeacon, usesForJob } = require("./lib");
const fs = require("fs"), path = require("path");
const inp = (n) => process.env[`INPUT_${n.replace(/ /g, "_").toUpperCase()}`] || "";
function ver(cmd, args) {
  try { const o = execFileSync(cmd, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 5000 });
        const m = /(\d+\.\d+)/.exec(o); return m ? m[1] : null; } catch (e) {
        const m = /(\d+\.\d+)/.exec(String(e.stderr || "")); return m ? m[1] : null; }
}
async function failedStep() {
  const tok = inp("github-token"), repo = process.env.GITHUB_REPOSITORY, run = process.env.GITHUB_RUN_ID, att = process.env.GITHUB_RUN_ATTEMPT || "1";
  if (!tok || !repo || !run) return "";
  const r = await fetch(`${process.env.GITHUB_API_URL || "https://api.github.com"}/repos/${repo}/actions/runs/${run}/attempts/${att}/jobs?per_page=100`,
    { headers: { Authorization: `Bearer ${tok}`, Accept: "application/vnd.github+json", "User-Agent": "ci-earlywarn" } });
  if (!r.ok) return "";
  return failedStepFromJobs(await r.json(), { runnerName: process.env.RUNNER_NAME, jobName: process.env.GITHUB_JOB });
}
async function oidcToken() {
  const url = process.env.ACTIONS_ID_TOKEN_REQUEST_URL, t = process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN;
  if (inp("oidc") !== "true" || !url || !t) return "";
  const r = await fetch(`${url}&audience=ci-earlywarn`, { headers: { Authorization: `Bearer ${t}` } });
  return r.ok ? (await r.json()).value : "";
}
// The current job's `uses:` refs, from the workflow file of this run (GITHUB_WORKFLOW_REF = owner/repo/<path>@ref).
// Prefer the checked-out file; else read it via the contents API (needs contents: read). Never throws.
async function jobActions() {
  const wr = process.env.GITHUB_WORKFLOW_REF || "", job = process.env.GITHUB_JOB || "";
  const m = /^([^/]+\/[^/]+)\/(.+?)@(.+)$/.exec(wr); if (!m || !job) return [];
  const [, repo, file, ref] = m; let yaml = "";
  const local = path.join(process.env.GITHUB_WORKSPACE || "", file);
  if (repo === process.env.GITHUB_REPOSITORY && process.env.GITHUB_WORKSPACE && fs.existsSync(local)) yaml = fs.readFileSync(local, "utf8");
  else if (inp("github-token")) {
    const r = await fetch(`${process.env.GITHUB_API_URL || "https://api.github.com"}/repos/${repo}/contents/${file}?ref=${encodeURIComponent(ref)}`,
      { headers: { Authorization: `Bearer ${inp("github-token")}`, Accept: "application/vnd.github.raw", "User-Agent": "ci-earlywarn" } });
    if (r.ok) yaml = await r.text();
  }
  return usesForJob(yaml, job);
}
(async () => {
  try {
    const status = inp("job-status").toLowerCase();
    if (!process.env.ImageOS || !process.env.ImageVersion) { console.log("ci-earlywarn beacon: not sent (no ImageOS/ImageVersion: self-hosted or non-GitHub runner image)"); return; }
    const failuresOnly = inp("failures-only") === "true";
    if (failuresOnly && status !== "failure") { console.log("ci-earlywarn beacon: not sent (failures-only mode, job did not fail)"); return; }
    const actions = inp("report-actions") === "true" ? await jobActions().catch(() => []) : [];
    const step = status === "failure" ? await failedStep() : "";
    const tc = inp("send-toolchain") === "true" ? Object.fromEntries(Object.entries({
      node: ver("node", ["--version"]), python: ver("python3", ["--version"]), java: ver("java", ["-version"]), go: ver("go", ["version"]) }).filter(([, v]) => v)) : {};
    const b = buildBeacon({ ...process.env, INPUT_JOB_STATUS: status }, step, tc, { failuresOnly, actions });
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${inp("token")}` };
    const o = await oidcToken().catch(() => ""); if (o) headers["X-GitHub-OIDC"] = o;
    const r = await fetch(inp("endpoint"), { method: "POST", headers, body: JSON.stringify(b) });
    let verified = false; try { verified = !!(await r.json()).verified; } catch (_) {}
    console.log(`ci-earlywarn beacon: ${r.status} (step category: ${b.step_category}, oidc attached: ${!!o}, tenant verified: ${verified}, mode: ${b.mode || "all"}, actions hashed: ${(b.actions || []).length})`);
  } catch (e) { console.log(`::notice::ci-earlywarn beacon skipped: ${e.name}`); }
})();
