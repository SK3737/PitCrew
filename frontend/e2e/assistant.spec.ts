import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

const BACKEND_DIR = path.resolve(__dirname, "../../backend");
const SEED_SCRIPT = path.resolve(__dirname, "seed.py");

// Same seeded user dashboard.spec.ts uses - "mechanic" holds `use_assistant`
// (see backend/app/auth/rbac.py).
const EMAIL = "e2e-mechanic@pitcrew.dev";
const PASSWORD = "pitcrew-e2e-password";

// The knowledge golden scenario from backend/cassettes/golden/ (see
// backend/tests/test_replay_mode.py's GOLDEN_KNOWLEDGE_QUESTION and
// task-7-report.md) - chosen over the diagnostics golden scenario because
// diagnostics was recorded against a hand-fixed VehicleServiceSnapshot
// (months_driven=5.0 etc, see task-7-report.md), which a live
// RepositoryVehicleDataProvider reading the real, date-drifting seeded DB
// would never reproduce byte-for-byte. The knowledge scenario has no such
// dependency - it's answered entirely from the static, checked-in KB
// corpus - so it replays deterministically against this real stack.
const GOLDEN_KNOWLEDGE_QUESTION = "How often should I flush the coolant on a BMW 3 Series?";

test.beforeAll(() => {
  // Idempotent: seeds the fleet fixture, the e2e mechanic user, and a
  // freshly re-ingested KB corpus (see seed.py's docstring for why the KB
  // step re-ingests from a clean slate on every run, not just once) against
  // whatever DB the backend webServer is running against.
  execFileSync("python", [SEED_SCRIPT], { cwd: BACKEND_DIR, stdio: "inherit" });
});

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.describe("assistant", () => {
  test("asking the golden knowledge question streams a cited answer with a visible agent trace", async ({
    page,
  }) => {
    // The RAG pipeline's local models load lazily on the first real request
    // a freshly started backend serves (see the cold-start note below) -
    // `test.slow()` triples this test's timeout to absorb that one-time
    // cost instead of racing it.
    test.slow();
    await login(page);

    await page.getByRole("link", { name: "Assistant" }).click();
    await expect(page).toHaveURL(/\/assistant$/);

    await page.getByLabel("Question").fill(GOLDEN_KNOWLEDGE_QUESTION);
    await page.getByRole("button", { name: "Ask" }).click();

    const conversation = page.getByRole("log", { name: "Conversation" });
    await expect(conversation.getByText(GOLDEN_KNOWLEDGE_QUESTION)).toBeVisible();

    // Streamed answer: waits for the recorded golden answer's exact wording
    // (see backend/cassettes/golden/ - the Knowledge specialist's scripted
    // completion) to appear as `token` events arrive - proves the answer
    // actually streamed in via SSE rather than only ever checking a final
    // snapshot.
    // Generous timeout: the RAG pipeline's local embedder/cross-encoder
    // models (app.agents.embeddings) are loaded lazily and cached at
    // module scope in the backend process - the first real request that
    // reaches the Knowledge specialist in a freshly started backend pays a
    // one-time cold-start cost loading them from the local Hugging Face
    // cache (seconds, not the sub-second cost of every later request).
    // `.first()`: the same phrase also appears verbatim inside the source
    // card's grounding chunk text rendered further down by <Sources> -
    // this assertion is only about the streamed answer bubble.
    await expect(conversation.getByText(/BMW's factory long-life coolant/).first()).toBeVisible({
      timeout: 45_000,
    });

    // Once streaming settles, the button's label reverts from
    // "Thinking..." back to "Ask" (it stays disabled until the next
    // question is typed - see components/Chat.tsx's `!question.trim()`
    // guard - so this checks the label, not the enabled state).
    await expect(page.getByRole("button", { name: "Ask" })).toBeVisible();

    // Inline citation: the answer's `[1]` marker renders as a linked badge
    // (see components/Sources.tsx's AnswerWithCitations) pointing at the
    // BMW Coolant Service source card below it.
    await expect(conversation.getByRole("link", { name: "1" })).toBeVisible();

    // Sources: at least one citation card, grounded in the real BMW KB doc.
    await expect(conversation.getByText("Sources")).toBeVisible();
    await expect(conversation.getByText(/BMW 3 Series.*Coolant Service/)).toBeVisible();

    // Agent trace: Supervisor -> Knowledge specialist steps, each with a
    // real timing (proving these are the actual `trace` SSE events, not
    // placeholder text).
    const trace = page.getByRole("complementary", { name: "Agent trace" });
    await expect(trace.getByText("Supervisor - classify intent")).toBeVisible();
    await expect(trace.getByText("Knowledge specialist")).toBeVisible();
    await expect(trace.getByText(/\d+ ms/).first()).toBeVisible();
  });

  test("unauthenticated access to the assistant redirects to login", async ({ page }) => {
    await page.goto("/assistant");
    await expect(page).toHaveURL(/\/login$/);
  });
});
