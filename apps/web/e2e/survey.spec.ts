import { expect, test } from "@playwright/test";
import { loginAs } from "./auth";

test("resident: consent → home block → answers on a flaky network → thanks", async ({ page, context }, info) => {
  test.skip(info.project.name !== "mobile", "the survey runs once, on the phone layout");
  await loginAs(page, "resident");
  await page.goto("/survey/pilot-2026");
  await expect(page.getByRole("heading", { name: "Before you start" })).toBeVisible();
  await page.getByRole("button", { name: "I agree" }).click();

  await expect(page.getByRole("heading", { name: "Roughly where do you live?" })).toBeVisible();
  await expect(page.locator('[data-ready="true"]')).toBeVisible();
  const canvas = page.locator('[data-ready="true"] canvas');
  const box = await canvas.boundingBox();
  if (!box) throw new Error("no map");
  await canvas.tap({ position: { x: box.width / 2, y: box.height / 2 } });
  await expect(page.getByRole("button", { name: "This is my block" })).toBeEnabled();
  await page.getByRole("button", { name: "This is my block" }).click();

  // One question per screen, progress as "n of total".
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();
  for (let i = 0; i < 20; i++) {
    if (await page.getByRole("button", { name: "Send my answers" }).isVisible()) break;
    await page.locator("fieldset label").first().click();
    await page.getByRole("button", { name: "Next" }).click();
  }
  await page.locator("fieldset label").first().click();

  // Answers survive a reload (saved on the phone).
  await page.reload();
  await expect(page.getByRole("button", { name: "Send my answers" })).toBeVisible();

  await context.setOffline(true);
  await page.getByRole("button", { name: "Send my answers" }).click();
  await expect(page.getByText(/You're offline/)).toBeVisible();
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(page.getByRole("heading", { name: "Thank you" })).toBeVisible();
  await expect(page.getByText(/once 20 people nearby have answered/)).toBeVisible();
});
