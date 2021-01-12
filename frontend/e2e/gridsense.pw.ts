import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("/api/demo/reset");
});

test("dashboard, responsive layout, and real CSV export", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Every watt, accounted for." }),
  ).toBeVisible();
  await expect(
    page.getByText("SIMULATED ENERGY DATA", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Energy through the day" }),
  ).toBeVisible();
  const observations = page.locator(".chart-footer > span").first();
  const initialCount = Number(
    (await observations.innerText()).match(/\d+/)?.[0],
  );
  await page.getByRole("button", { name: "72 hours", exact: true }).click();
  await expect
    .poll(async () =>
      Number((await observations.innerText()).match(/\d+/)?.[0]),
    )
    .toBeGreaterThan(initialCount * 2);
  await page.getByRole("button", { name: "24 hours", exact: true }).click();
  await expect
    .poll(async () =>
      Number((await observations.innerText()).match(/\d+/)?.[0]),
    )
    .toBe(initialCount);
  await page.screenshot({
    path: `../docs/${info.project.name === "desktop" ? "dashboard" : "mobile"}.png`,
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("gridsense-readings.csv");
  expect(await file.failure()).toBeNull();
  expect(errors).toEqual([]);
});

test("offline shell and IndexedDB queue survive reload and replay", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Energy through the day" }),
  ).toBeVisible();
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.getByRole("button", { name: "Devices", exact: true }).click();
  await page
    .getByRole("button", { name: "Disconnect uplink", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Collect sample", exact: true })
    .click();
  await expect(page.getByText("1 pending")).toBeVisible();
  await context.setOffline(true);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(
    page.getByText("Connection lost. Showing the last saved demo snapshot."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Devices", exact: true }).click();
  await expect(page.getByText("1 pending")).toBeVisible();
  await page
    .getByRole("button", { name: "Collect sample", exact: true })
    .click();
  await expect(page.getByText("2 pending")).toBeVisible();
  await context.setOffline(false);
  await page.getByRole("button", { name: "Sync queue", exact: true }).click();
  await expect(page.getByText("0 pending")).toBeVisible();
  await expect(
    page.getByText("2 queued readings acknowledged by the server."),
  ).toBeVisible();
});

test("outage simulation changes persisted telemetry", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Run scenario" }).click();
  await expect(
    page.getByText("Grid interrupted", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Outages", exact: false })
    .first()
    .click();
  await expect(page.getByText("Ongoing", { exact: true })).toBeVisible();
});
