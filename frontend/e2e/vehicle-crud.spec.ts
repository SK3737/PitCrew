import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

const BACKEND_DIR = path.resolve(__dirname, "../../backend");
const SEED_SCRIPT = path.resolve(__dirname, "seed.py");

// Matches frontend/e2e/seed.py's mechanic fixture - mechanic holds
// write_service unrestricted by ownership, so this only exercises the "add
// vehicle" / "log service" UI plumbing itself, not the owner-scoping rules
// (those are covered by backend/tests/test_owner_scoping.py).
const EMAIL = "e2e-mechanic@pitcrew.dev";
const PASSWORD = "pitcrew-e2e-password";
const VEHICLE_ID = `E2E_CRUD_${Date.now()}`;

test.beforeAll(() => {
  execFileSync("python", [SEED_SCRIPT], { cwd: BACKEND_DIR, stdio: "inherit" });
});

test.describe("vehicle add + log service", () => {
  test("add a vehicle, log a service event, and see both reflected on the dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(EMAIL);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);

    await page.getByRole("link", { name: "Add vehicle" }).click();
    await expect(page).toHaveURL(/\/dashboard\/vehicles\/new$/);

    await page.getByLabel("Vehicle ID / plate").fill(VEHICLE_ID);
    await page.getByLabel("Make").fill("Tesla");
    await page.getByLabel("Model").fill("Model 3");
    await page.getByLabel("Year").fill("2023");
    await page.getByLabel("Fuel type").selectOption("electric");
    await page.getByRole("button", { name: "Add vehicle" }).click();

    await expect(page).toHaveURL(/\/dashboard$/);
    const newRow = page.getByRole("row", { name: new RegExp(VEHICLE_ID) });
    await expect(newRow).toBeVisible();
    await expect(newRow.getByText("No vehicles found.")).toHaveCount(0);

    await newRow.getByRole("link", { name: "Log service" }).click();
    await expect(page).toHaveURL(new RegExp(`/dashboard/vehicles/${VEHICLE_ID}/service$`));

    await page.getByLabel("Service date").fill("2026-01-15");
    await page.getByLabel("Odometer (km)").fill("12000");
    await page.getByLabel("Service type").selectOption("oil_change");
    await page.getByRole("button", { name: "Log service" }).click();

    await expect(page).toHaveURL(/\/dashboard$/);
    const updatedRow = page.getByRole("row", { name: new RegExp(VEHICLE_ID) });
    await expect(updatedRow).toContainText("Jan 15, 2026");
    await expect(updatedRow).toContainText("12,000");
  });

  test("submitting a duplicate vehicle ID shows an inline error instead of crashing", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(EMAIL);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);

    await page.goto("/dashboard/vehicles/new");
    await page.getByLabel("Vehicle ID / plate").fill(VEHICLE_ID);
    await page.getByRole("button", { name: "Add vehicle" }).click();

    await expect(page).toHaveURL(/\/dashboard\/vehicles\/new$/);
    await expect(page.locator('p[role="alert"]')).toContainText(/already exists/i);
  });
});
