import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const isolated = path.join(root, ".tmp/toolchains/go/bin/go");
const go =
  process.env.BUILD_SKILLS_GO || (existsSync(isolated) ? isolated : "go");
const source = path.join(
  root,
  "src/build_skills/web/workflows/skill_build.star",
);
const destination = source.replace(/\.star$/, ".json");
const run = spawnSync(go, ["run", ".", source], {
  cwd: path.join(root, "tools/workflow-compiler"),
  encoding: "utf8",
  timeout: 120000,
});
if (run.error || run.status !== 0) {
  process.stderr.write(run.stderr || String(run.error));
  process.exit(1);
}
JSON.parse(run.stdout);
if (process.argv.includes("--check")) {
  if (
    !existsSync(destination) ||
    readFileSync(destination, "utf8") !== run.stdout
  ) {
    console.error(
      "Compiled workflow is stale. Run node scripts/compile-workflow.mjs.",
    );
    process.exit(1);
  }
} else writeFileSync(destination, run.stdout);
