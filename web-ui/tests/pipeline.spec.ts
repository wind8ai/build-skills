import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const definition = JSON.parse(
  await fs.readFile(
    path.resolve("../src/build_skills/web/workflows/skill_build.json"),
    "utf8",
  ),
);

test("sidebar inspection remains at the selected step after delivered job polling", async ({
  page,
}) => {
  await page.route("**/api/jobs/nav-test", (route) =>
    route.fulfill({
      json: {
        id: "nav-test",
        status: "delivered",
        busy: false,
        approval: "frozen",
        round: 1,
        calls: 6,
        delivery: "/tmp/synthetic-delivery",
        workflow: definition,
        settings: {
          goal: "Synthetic navigation test",
          builder: { model: "fixture" },
          executors: [],
        },
        nodes: Object.fromEntries(
          definition.nodes.map((n: { id: string }) => [
            n.id,
            { status: n.id === "improve" ? "skipped" : "success", actions: [] },
          ]),
        ),
      },
    }),
  );
  await page.goto("/?job=nav-test");
  await expect(
    page.getByText("Skill 已通过最终验证", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "流程节点" })
    .getByRole("button", { name: /导入材料/ })
    .click();
  const selected = page.locator(".workflow-card.expanded");
  await expect(selected).toContainText("导入材料");
  const poll = page.waitForResponse((r) =>
    r.url().endsWith("/api/jobs/nav-test"),
  );
  await poll;
  await expect(selected).toContainText("导入材料", { timeout: 1000 });
  const box = await selected.boundingBox();
  const viewport = page.viewportSize()!;
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(220);
  expect(box!.y).toBeGreaterThanOrEqual(85);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
});

test("main steps share one pipeline axis with only improvement branching off", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".workflow-card")).toHaveCount(11);
  const cards = page.locator(".workflow-card");
  const boxes = await cards.evaluateAll((nodes) =>
    nodes.map((n) => ({
      title: n.querySelector("strong")?.textContent,
      x: n.getBoundingClientRect().x,
      y: n.getBoundingClientRect().y,
    })),
  );
  const main = boxes.filter((b) => b.title !== "重构 Skill");
  expect(
    Math.max(...main.map((b) => b.x)) - Math.min(...main.map((b) => b.x)),
  ).toBeLessThan(2);
  for (let i = 1; i < main.length; i++)
    expect(main[i].y).toBeGreaterThan(main[i - 1].y);
});

test("a fast approval failure opens the actionable failed step rather than build", async ({
  page,
}) => {
  let approved = false;
  const scenario = {
    id: "copy",
    task: "Copy input.txt to output.txt",
    files: { "input.txt": "hello" },
    checks: [{ path: "output.txt", equals: "hello" }],
  };
  await page.route("**/api/jobs/fast-failure", (route) =>
    route.fulfill({
      json: {
        id: "fast-failure",
        busy: false,
        approval: approved ? "frozen" : null,
        status: approved ? "failed" : "awaiting_approval",
        round: approved ? 1 : 0,
        calls: approved ? 5 : 1,
        error: approved ? "Synthetic failed execution" : null,
        operation: { id: "approval" },
        workflow: definition,
        brief: {
          scope: "Copy text",
          criteria: ["Exact copy"],
          questions: [],
          development: [scenario],
          holdout: [{ ...scenario, id: "new" }],
        },
        brief_digest: "synthetic",
        settings: {
          goal: "Navigation test",
          builder: { model: "fixture" },
          executors: [],
        },
        allowed_actions: approved
          ? ["retry_development"]
          : ["review", "approve"],
        nodes: Object.fromEntries(
          definition.nodes.map((n: { id: string }) => [
            n.id,
            {
              status:
                approved && n.id === "execute"
                  ? "failed"
                  : n.id === "approve"
                    ? "ready"
                    : "success",
              actions:
                approved && n.id === "execute" ? ["retry_development"] : [],
            },
          ]),
        ),
      },
    }),
  );
  await page.route("**/api/jobs/fast-failure/approve", (route) => {
    approved = true;
    return route.fulfill({ json: { id: "fast-failure" } });
  });
  await page.goto("/?job=fast-failure");
  await expect(
    page.getByRole("navigation", { name: "流程节点" }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "流程节点" })
    .getByRole("button", { name: /确认范围/ })
    .click();
  await page
    .getByRole("checkbox", { name: "我已审阅范围、标准和两类场景" })
    .check();
  await page
    .getByRole("button", { name: "确认并开始构建", exact: true })
    .click();
  await expect(page.locator(".workflow-card.expanded")).toContainText(
    "开发执行",
  );
  await expect(
    page.getByRole("button", { name: "重试开发失败项", exact: true }),
  ).toBeVisible();
});
