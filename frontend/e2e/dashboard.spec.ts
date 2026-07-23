import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

const BACKEND_DIR = path.resolve(__dirname, "../../backend");
const SEED_SCRIPT = path.resolve(__dirname, "seed.py");

// Matches frontend/e2e/seed.py - a "mechanic" (not "owner") so the seeded
// fleet (which has no owner_id set on any vehicle) is actually visible.
const EMAIL = "e2e-mechanic@pitcrew.dev";
const PASSWORD = "pitcrew-e2e-password";

test.beforeAll(() => {
  // Idempotent: seeds the fleet fixture (if empty) + the e2e login user
  // (if missing) directly against whatever DB the backend webServer is
  // running against. See seed.py's docstring for why this can't go through
  // POST /auth/register instead.
  execFileSync("python", [SEED_SCRIPT], { cwd: BACKEND_DIR, stdio: "inherit" });
});

test.describe("dashboard", () => {
  test("login renders the KPIs and vehicles table with real seeded data", async ({ page }) => {
    await page.goto("/login");

    await page.getByLabel("Email").fill(EMAIL);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(/\/dashboard$/);

    // KPI tiles
    await expect(page.getByText("Total vehicles")).toBeVisible();
    await expect(page.getByText("Overdue")).toBeVisible();

    // Vehicles table, populated from Postgres (not a placeholder/empty state)
    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    await expect(page.getByRole("row", { name: /TEST_V001/ })).toBeVisible();
    await expect(table.locator("tbody tr")).not.toHaveCount(0);
  });

  test("unauthenticated access to the dashboard redirects to login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login$/);
  });
});
