import { expect, test } from "@playwright/test";
import { loginAs } from "./auth";

test("analyst: queue → review → publish, with reasons enforced", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "review is a desktop task");
  await loginAs(page, "analyst");
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
  const first = page.locator("table tbody tr a").first();
  await expect(first).toBeVisible();
  await first.click();
  await expect(page.getByRole("heading", { name: "What moved the score" })).toBeVisible();

  // A reason is required to reject.
  await page.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByText("Write a reason of at least 10 characters.")).toBeVisible();

  await page.getByRole("button", { name: /^Publish/ }).click();
  await expect(page.getByRole("status")).toContainText("Published");
});
