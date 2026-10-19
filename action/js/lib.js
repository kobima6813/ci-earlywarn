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
function buildBeacon(env, failedStep, toolchain) {
  const b = { v: 2, runner_os: env.RUNNER_OS || "", image_os: env.ImageOS || "", image_version: env.ImageVersion || "",
    conclusion: (env.INPUT_JOB_STATUS || env["INPUT_JOB-STATUS"] || "unknown").toLowerCase(),
    step_category: categorize(failedStep), ts: Math.floor(Date.now() / 1000) };
  if (!["success", "failure", "cancelled"].includes(b.conclusion)) b.conclusion = "unknown";
  if (toolchain && Object.keys(toolchain).length) b.toolchain = toolchain;
  return b;
}
module.exports = { categorize, failedStepFromJobs, buildBeacon };
