import { describe, it, expect } from "vitest";
import { settingsFrom } from "./state";
describe("API model settings boundary", () => {
  it("excludes catalog and storage metadata from task payloads", () => {
    const values = settingsFrom({
      name: "copy",
      goal: "copy files",
      builder: { provider: "codex", model: "model", reasoning_effort: "high" },
      executors: [
        { provider: "qoder", model: "other", reasoning_effort: null },
      ],
      catalog: [{ command: ["unsafe"] }],
      connections: {},
      storage: "/private/local",
      defaults_path: "local.json",
    });
    expect(values.name).toBe("copy");
    expect(values).not.toHaveProperty("catalog");
    expect(values).not.toHaveProperty("storage");
    expect(values).not.toHaveProperty("connections");
    expect(values.executors).toHaveLength(1);
    expect(values.agent_timeout_seconds).toBe(600);
  });
});
