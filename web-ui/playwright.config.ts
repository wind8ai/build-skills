import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export default defineConfig({
  testDir: "tests",
  timeout: 60000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8323",
    ...devices["Desktop Chrome"],
    trace: "retain-on-failure",
  },
  webServer: {
    command: "uv run python scripts/run-test-server.py",
    cwd: root,
    url: "http://127.0.0.1:8323/api/options",
    reuseExistingServer: false,
    timeout: 30000,
  },
});
