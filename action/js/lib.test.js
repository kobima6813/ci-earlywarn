const test = require("node:test"), assert = require("node:assert");
const { categorize, failedStepFromJobs, buildBeacon } = require("./lib");
test("categorize", () => { assert.equal(categorize("Run unit tests"), "test"); assert.equal(categorize(""), "none"); assert.equal(categorize("zzz"), "other"); });
test("finds failed step of current job by runner name", () => {
  const jobs = { jobs: [{ name: "lint", runner_name: "r1", status: "completed", steps: [{ name: "Lint", conclusion: "failure" }] },
                       { name: "build", runner_name: "r2", status: "in_progress", steps: [{ name: "Checkout", conclusion: "success" }, { name: "Compile app", conclusion: "failure" }] }] };
  assert.equal(failedStepFromJobs(jobs, { runnerName: "r2" }), "Compile app");
  assert.equal(failedStepFromJobs({ jobs: [] }, { runnerName: "r2" }), "");
});
test("beacon has no repo/step name and normalizes status", () => {
  const b = buildBeacon({ RUNNER_OS: "Linux", ImageOS: "ubuntu24", ImageVersion: "20261012.1", INPUT_JOB_STATUS: "Failure", GITHUB_REPOSITORY: "acme/payments" }, "Compile secret-project", {});
  const s = JSON.stringify(b);
  assert.ok(!s.includes("acme") && !s.includes("secret-project")); assert.equal(b.step_category, "build"); assert.equal(b.conclusion, "failure");
  assert.equal(buildBeacon({ INPUT_JOB_STATUS: "weird" }, "", {}).conclusion, "unknown");
});
