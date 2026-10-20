// Pure helpers (unit-tested with node --test). No dependencies.
const CATEGORIES = [["install", /install|setup|deps|restore|bootstrap/], ["build", /build|compile|bundle|make|cmake/],
  ["test", /test|spec|e2e|pytest|jest/], ["lint", /lint|format|check|typecheck/], ["deploy", /deploy|publish|release|push/],
  ["cache", /cache/], ["docker", /docker|image|container/]];
function categorize(step) {
  const s = (step || "").toLowerCase();
  if (!s) return "none";
  for (const [c, re] of CATEGORIES) if (re.test(s)) return c;
  return "other";
}
// Pick the current job from the jobs API response and return the first failed step name (never sent; only categorized).
function failedStepFromJobs(jobs, { runnerName, jobName }) {
  const list = (jobs && jobs.jobs) || [];
  const job = list.find(j => runnerName && j.runner_name === runnerName && j.status !== "completed")
           || list.find(j => jobName && j.name === jobName) || null;
  if (!job) return "";
  const st = (job.steps || []).find(s => s.conclusion === "failure");
  return st ? st.name : "";
}
// Extract `uses:` refs of one job from a workflow YAML (indentation-based; no YAML dependency).
// Returns normalized "owner/repo[/path]@ref" strings; local (./) and docker:// refs are skipped.
function usesForJob(yaml, jobId) {
  const lines = String(yaml || "").split(/\r?\n/);
  let jobsIndent = -1, jobIndent = -1, inJob = false; const out = [];
  for (const raw of lines) {
    const line = raw.replace(/\s+#.*$/, ""); if (!line.trim()) continue;
    const ind = line.length - line.trimStart().length, t = line.trim();
    if (jobsIndent < 0) { if (/^jobs:\s*$/.test(t)) jobsIndent = ind; continue; }
    if (ind <= jobsIndent) break;                                     // left the jobs: block
    const key = /^["']?([A-Za-z0-9_-]+)["']?:\s*$/.exec(t);
    if (jobIndent < 0 || ind === jobIndent) { if (key) { jobIndent = ind; inJob = key[1] === jobId; } continue; }
    if (!inJob) continue;
    const m = /^(?:-\s*)?uses:\s*["']?([^"'\s]+)["']?/.exec(t);
    if (m && !m[1].startsWith("./") && !m[1].startsWith("docker://") && m[1].includes("@")) {
      const [name, ref] = [m[1].slice(0, m[1].lastIndexOf("@")), m[1].slice(m[1].lastIndexOf("@") + 1)];
      out.push(`${name.toLowerCase()}@${ref}`);
    }
  }
  return [...new Set(out)];
}
// Network-wide salt: identical for every tenant so the same action hashes the same everywhere.
// It is public (in this file), so it hides names from casual readers only; well-known actions can be guessed by hashing them.
const ACTION_SALT = "ci-earlywarn-actions-v1";
function hashAction(ref, salt = ACTION_SALT) {
  return require("crypto").createHash("sha256").update(`${salt}:${ref}`).digest("hex").slice(0, 16);
}
function buildBeacon(env, failedStep, toolchain, extra = {}) {
  const b = { v: 2, runner_os: env.RUNNER_OS || "", image_os: env.ImageOS || "", image_version: env.ImageVersion || "",
    conclusion: (env.INPUT_JOB_STATUS || env["INPUT_JOB-STATUS"] || "unknown").toLowerCase(),
    step_category: categorize(failedStep), ts: Math.floor(Date.now() / 1000) };
  if (!["success", "failure", "cancelled"].includes(b.conclusion)) b.conclusion = "unknown";
  if (toolchain && Object.keys(toolchain).length) b.toolchain = toolchain;
  if (extra.failuresOnly) b.mode = "failures_only";
  if (extra.actions && extra.actions.length) b.actions = extra.actions.slice(0, 20).map(a => hashAction(a));
  return b;
}
module.exports = { categorize, failedStepFromJobs, buildBeacon, usesForJob, hashAction, ACTION_SALT };
