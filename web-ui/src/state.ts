import type { Data } from "./api";
export const emptySettings = {
  name: "new-skill",
  goal: "",
  builder: { provider: "", model: "", reasoning_effort: null } as {
    provider: string;
    model: string;
    reasoning_effort: string | null;
  },
  executors: [] as {
    provider: string;
    model: string;
    reasoning_effort: string | null;
  }[],
  max_rounds: 3,
  repetitions: 1,
  minimum_score: 0.8,
  agent_timeout_seconds: 600,
  parsing_timeout_seconds: 600,
};
export function settingsFrom(options: Data) {
  return Object.fromEntries(
    Object.keys(emptySettings).map((key) => [
      key,
      options[key] ?? emptySettings[key as keyof typeof emptySettings],
    ]),
  ) as typeof emptySettings;
}
