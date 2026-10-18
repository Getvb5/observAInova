import { expect, test } from "@playwright/test";

test("confirms a public problem without showing an unsupported solution", async ({ page }) => {
  await page.goto("/");
  await page
    .getByLabel("Descreva o problema público")
    .fill("As pessoas aguardam muito por consultas especializadas");
  await page.getByRole("button", { name: "Começar" }).click();

  const answers = [
    "Caruaru",
    "adultos aguardando cardiologia",
    "espera superior a 90 dias",
    "oferta insuficiente, segundo a equipe",
    "remanejamento manual de vagas",
    "equipe de regulação e dados de agenda",
    "sem aumento de equipe",
    "reduzir a espera preservando equidade",
  ];
  for (const answer of answers) {
    await page.getByLabel("Sua resposta").fill(answer);
    await page.getByRole("button", { name: "Continuar" }).click();
  }

  await expect(
    page.getByRole("heading", { name: "Foi isso que você quis dizer?" }),
  ).toBeVisible();
  await expect(page.getByText("sem aumento de equipe", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Confirmar formulação" }).click();
  await expect(page.getByRole("heading", { name: "Problema confirmado" })).toBeVisible();
  await expect(
    page.getByText(/somente com contribuições científicas validadas/i),
  ).toBeVisible();
  await expect(page.getByText(/caminho recomendado/i)).toHaveCount(0);
});
