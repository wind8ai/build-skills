import { test, expect } from "@playwright/test";
import path from "node:path";
import fs from "node:fs/promises";
import os from "node:os";
const repo = path.resolve("..");
test("questions, draft reload, confirmation, immutable delivery and download", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".workflow-card")).toHaveCount(11);
  await page
    .locator(".upload-box input")
    .setInputFiles(path.join(repo, "examples/web/materials/copy-text.md"));
  await page.getByRole("checkbox", { name: /copy-text.md/ }).check();
  await page.getByRole("button", { name: "导入所选文件", exact: true }).click();
  await page
    .getByRole("button", { name: "解析并核对材料", exact: true })
    .click();
  await page
    .getByRole("checkbox", { name: "我已核对文字和遗漏，确认采用这些材料" })
    .check();
  await page
    .getByRole("button", { name: "采用材料并生成草案", exact: true })
    .click();
  const answer = page.getByPlaceholder("填写你的决定、范围或规则");
  await answer.fill("Preserve all whitespace exactly.");
  await page.reload();
  await expect(answer).toHaveValue("Preserve all whitespace exactly.");
  await page
    .getByRole("button", { name: "提交回答并更新草案", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "根据修改意见更新草案", exact: true }),
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
  await expect(
    page.getByRole("button", { name: "重试开发失败项", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await page
    .getByRole("button", { name: "重试开发失败项", exact: true })
    .click();
  await expect(
    page.getByText("Skill 已通过最终验证", { exact: true }),
  ).toBeVisible({ timeout: 30000 });
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "下载 Skill ZIP", exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/^skill-.*\.zip$/);
  await page.reload();
  await expect(
    page.getByText("Skill 已通过最终验证", { exact: true }),
  ).toBeVisible();
});
test("direct URL import presents a tree before selection", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "文件链接", exact: true }).click();
  await page
    .getByRole("textbox", { name: "直接文件链接", exact: true })
    .fill("http://127.0.0.1:8323/__fixture/notes.md");
  await page
    .getByRole("button", { name: "读取来源文件树", exact: true })
    .click();
  const checkbox = page.getByRole("checkbox", { name: /notes.md/ });
  await expect(checkbox).not.toBeChecked();
  await checkbox.check();
  await page.getByRole("button", { name: "导入所选文件", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "构建目标", exact: true }),
  ).toBeVisible();
});
test("small screen retains a vertical actionable workflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator(".canvas-shell")).toBeHidden();
  await expect(page.locator(".mobile-flow")).toBeVisible();
  await expect(page.getByText("选择本地文件", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("folder tree preserves relative paths and uploads only selected files", async ({
  page,
}) => {
  const folder = await fs.mkdtemp(path.join(os.tmpdir(), "skill-folder-"));
  try {
    await fs.mkdir(path.join(folder, "a"));
    await fs.mkdir(path.join(folder, "b"));
    await fs.writeFile(
      path.join(folder, "a", "notes.md"),
      "selected public text",
    );
    await fs.writeFile(path.join(folder, "b", "notes.md"), "not selected");
    await fs.writeFile(path.join(folder, ".env"), "synthetic test secret");
    await page.goto("/");
    await page.getByRole("button", { name: "文件夹", exact: true }).click();
    await page.locator(".upload-box input").setInputFiles(folder);
    await expect(page.getByRole("checkbox", { name: /.env/ })).toBeDisabled();
    await page.getByRole("checkbox", { name: /a\/notes.md/ }).check();
    await page
      .getByRole("button", { name: "导入所选文件", exact: true })
      .click();
    await page
      .getByRole("textbox", { name: "Skill 名称", exact: true })
      .fill("folder-draft");
    await page.reload();
    await expect(
      page.getByRole("textbox", { name: "Skill 名称", exact: true }),
    ).toHaveValue("folder-draft");
    await page
      .getByRole("button", { name: "解析并核对材料", exact: true })
      .click();
    await expect(
      page.getByText("selected public text", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("not selected", { exact: true })).toHaveCount(
      0,
    );
  } finally {
    await fs.rm(folder, { recursive: true, force: true });
  }
});

test("cancel a parsing call and retry in the same frozen task", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator(".upload-box input").setInputFiles({
    name: "sample.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("synthetic PDF fixture"),
  });
  await page.getByRole("checkbox", { name: /sample.pdf/ }).check();
  await page.getByRole("button", { name: "导入所选文件", exact: true }).click();
  await page
    .getByRole("button", { name: "解析并核对材料", exact: true })
    .click();
  await page.getByRole("button", { name: "取消当前调用", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "重新解析材料", exact: true }),
  ).toBeVisible();
  const job = page.url();
  await page.getByRole("button", { name: "重新解析材料", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "采用材料并生成草案", exact: true }),
  ).toBeVisible({ timeout: 20000 });
  expect(page.url()).toBe(job);
});
