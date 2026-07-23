import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const BACKEND_DIR = path.resolve(__dirname, "../backend");

/**
 * Runs the whole stack for e2e: FastAPI (against the already-running
 * docker-compose `db`) + a Next.js *production* build, per the Phase 4
 * acceptance gate ("run against a production build"). Both are declared as
 * `webServer` entries so `npx playwright test` alone is enough to exercise
 * the real thing - reusing either one if it's already running locally.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  webServer: [
    {
      name: "backend",
      command: "python -m uvicorn app.main:app --port 8000",
      cwd: BACKEND_DIR,
      url: "http://localhost:8000/health",
      reuseExistingServer: true,
      timeout: 30_000,
      stdout: "pipe",
      env: {
        // Pinned explicitly (matches the default in app.config.Settings)
        // so this e2e run can never accidentally hit a live LLM API even
        // if a developer's local .env happens to set LLM_BACKEND=groq -
        // per the project-wide constraint, no paid LLM API is ever called
        // anywhere in this codebase, including in e2e tests.
        LLM_BACKEND: "replay",
        // assistant.spec.ts asks the committed golden knowledge question
        // (see frontend/e2e/seed.py's docstring) - CASSETTE_DIR points
        // ReplayClient at backend/cassettes/golden/ specifically, since
        // ReplayClient never searches subdirectories of its default
        // backend/cassettes/ root.
        CASSETTE_DIR: path.resolve(BACKEND_DIR, "cassettes", "golden"),
      },
    },
    {
      name: "frontend",
      command: "npm run build && npm run start",
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 180_000,
      stdout: "pipe",
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
