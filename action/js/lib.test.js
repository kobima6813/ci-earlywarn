const test = require("node:test"), assert = require("node:assert");
const { categorize, failedStepFromJobs, buildBeacon } = require("./lib");
const { usesForJob, hashAction } = require("./lib");
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
test("usesForJob picks only the current job's remote actions", () => {
  const y = `name: x\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4 # c\n      - name: n\n        uses: "Actions/Setup-Node@v4"\n      - uses: ./local\n      - uses: docker://alpine:3\n      - run: echo uses: fake@1\n  other:\n    steps:\n      - uses: evil/thing@v1\n`;
  assert.deepEqual(usesForJob(y, "build"), ["actions/checkout@v4", "actions/setup-node@v4"]);
  assert.deepEqual(usesForJob(y, "other"), ["evil/thing@v1"]);
  assert.deepEqual(usesForJob("", "build"), []);
});
test("failures-only mode and hashed actions in beacon", () => {
  const b = buildBeacon({ INPUT_JOB_STATUS: "failure" }, "", {}, { failuresOnly: true, actions: ["actions/checkout@v4"] });
  assert.equal(b.mode, "failures_only"); assert.equal(b.actions[0], hashAction("actions/checkout@v4"));
  assert.ok(!JSON.stringify(b).includes("checkout")); assert.match(b.actions[0], /^[0-9a-f]{16}$/);
  const old = buildBeacon({ INPUT_JOB_STATUS: "success" }, "", {});
  assert.ok(!("mode" in old) && !("actions" in old));
});
