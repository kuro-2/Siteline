import { expect, test } from "@playwright/test";

test("landing → explore → cell report with sources and sign-off", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Thinking of opening a shop?" })).toBeVisible();
  await page.getByRole("link", { name: /Explore Zoo Road/ }).click();
  await expect(page).toHaveURL(/\/explore\/pilot/);
  await expect(page.getByRole("heading", { level: 1, name: "Zoo Road" })).toBeVisible();

  // Reviewed picks are a ranked list; open the first.
  const first = page.locator("ol li a").first();
  await expect(first).toBeVisible();
  await first.click();
  await expect(page).toHaveURL(/\/cell\/[0-9a-f]{15}/);
  await expect(page.locator("#report-headline")).toBeVisible();
  await expect(page.getByText(/^Score \d+/)).toBeVisible();
  await expect(page.getByText(/Reviewed by .+ on /)).toBeVisible();
  await expect(page.getByRole("heading", { name: "What we can't see" })).toBeVisible();
  await page.getByRole("button", { name: "How we know" }).click();
  await expect(page.getByText(/WorldPop, \d{4}/)).toBeVisible();
});

test("category switcher and list view reach every block without the map", async ({ page }) => {
  await page.goto("/explore/pilot");
  await page.getByRole("radio", { name: "Salon" }).first().click();
  await expect(page).toHaveURL(/c=salon/);
  await page.getByRole("button", { name: /list/i }).first().click();
  const rows = page.locator("table tbody tr");
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThan(20);
  await rows.first().getByRole("link").click();
  await expect(page.locator("#report-headline")).toBeVisible();
});

test("check my idea: a pin outside the area gets a clear error", async ({ page, request }) => {
  const res = await request.post(`${process.env.API_URL ?? "http://localhost:8000"}/v1/check`, {
    data: { lat: 10, lng: 77, category: "pharmacy" },
  });
  expect(res.status()).toBe(422);
  expect((await res.json()).error.message).toContain("Move it inside the outlined area");
  await page.goto("/check");
  await expect(page.getByRole("heading", { name: "Check my idea" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Check this spot" })).toBeDisabled();
});
