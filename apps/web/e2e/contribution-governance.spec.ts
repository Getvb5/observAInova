import { expect, test } from "@playwright/test";

test("keeps discovery expression-first and exposes the restricted operations view", async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("observainova.local_token", "e2e-curator-token"));
  await page.route("**/api/v1/internal/dashboard", (route) => route.fulfill({ json: { review_pending: 1, publication_pending: 1, documents: { text_extracted: 1 } } }));
  await page.route("**/api/v1/internal/review-queue", (route) => route.fulfill({ json: { items: [], total: 0 } }));

  await page.goto("/");
  await expect(page.getByRole("searchbox", { name: "Expressão de busca" })).toBeVisible();
  await page.goto("/equipe");
  await expect(page.getByRole("heading", { name: "Equipe central" })).toBeVisible();
  await expect(page.getByText("1", { exact: true })).toHaveCount(3);
  await expect(page.getByText(/curadoria humana, supervisão independente/i)).toBeVisible();
});
