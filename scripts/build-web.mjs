import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
for (const [cmd, args] of [
  [process.execPath, ["scripts/compile-workflow.mjs"]],
  ["npm", ["--prefix", "web-ui", "run", "build"]],
]) {
  const result = spawnSync(cmd, args, { cwd: root, stdio: "inherit" });
  if (result.status !== 0) process.exit(result.status || 1);
}
