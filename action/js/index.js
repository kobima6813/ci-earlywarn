// CI Early-Warn JS action. Never fails the job: all errors are swallowed and logged as a notice.
const { execFileSync } = require("child_process");
const { failedStepFromJobs, buildBeacon } = require("./lib");
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
(async () => {
  try {
    const status = inp("job-status").toLowerCase();
    const step = status === "failure" ? await failedStep() : "";
    const tc = inp("send-toolchain") === "true" ? Object.fromEntries(Object.entries({
      node: ver("node", ["--version"]), python: ver("python3", ["--version"]), java: ver("java", ["-version"]), go: ver("go", ["version"]) }).filter(([, v]) => v)) : {};
    const b = buildBeacon({ ...process.env, INPUT_JOB_STATUS: status }, step, tc);
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${inp("token")}` };
    const o = await oidcToken().catch(() => ""); if (o) headers["X-GitHub-OIDC"] = o;
    const r = await fetch(inp("endpoint"), { method: "POST", headers, body: JSON.stringify(b) });
    let verified = false; try { verified = !!(await r.json()).verified; } catch (_) {}
    console.log(`ci-earlywarn beacon: ${r.status} (step category: ${b.step_category}, oidc attached: ${!!o}, tenant verified: ${verified})`);
  } catch (e) { console.log(`::notice::ci-earlywarn beacon skipped: ${e.name}`); }
})();
