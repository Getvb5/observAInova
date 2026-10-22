import { expect, test } from "@playwright/test";

const result = {
  query: "segurança do paciente", total: 1, page: 1, page_size: 10,
  facets: { institutions: ["Instituição de teste"], years: [2023] },
  items: [{ id: "fixture-record", title: "Estudo de teste: segurança do paciente na atenção básica",
    abstract: "Este registro é uma fixture exclusiva de testes da interface. Não integra o acervo publicado. Permite verificar a apresentação do resumo, a consulta à fonte e a distinção entre metadados e contribuições validadas.",
    publication_year: 2023, type: "dissertation", authors: ["Autoria de teste"], institutions: ["Instituição de teste"], keywords: ["saúde"],
    source: { name: "Repositório de teste", source_url: "https://repository.example/item/1", access_status: "available" },
    matched_terms: ["seguranca", "paciente"], validated_contributions: [] }],
};

test("one expression opens results; filters refine without a questionnaire", async ({ page }, testInfo) => {
  const requests: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/v1/")) requests.push(request.url()); });
  await page.route("**/api/v1/productions/search?**", async route => {
    const url = new URL(route.request().url());
    await route.fulfill({ json: url.searchParams.get("type") === "thesis" ? { ...result, items: [], total: 0 } : result });
  });
  await page.goto("/");
  await expect(page.getByRole("searchbox", { name: "Expressão de busca" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("search-home-desktop.png"), fullPage: true });
  await page.getByRole("searchbox").fill("segurança do paciente");
  await page.getByRole("searchbox").press("Enter");
  await expect(page.getByRole("heading", { name: result.items[0].title })).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0]).toContain("/productions/search?");
  await expect(page.getByRole("button", { name: "Confirmar formulação" })).toHaveCount(0);
  await expect(page.getByText("Interpretação científica pendente")).toBeVisible();
  await expect(page.getByRole("link", { name: /acessar fonte/i })).toHaveAttribute("href", "https://repository.example/item/1");
  await page.screenshot({ path: testInfo.outputPath("search-results-desktop.png"), fullPage: true });
  await page.getByLabel("Tipo de trabalho").selectOption("thesis");
  await expect(page.getByRole("heading", { name: "Nenhum resultado encontrado" })).toBeVisible();
  await page.getByRole("button", { name: "Limpar filtros" }).click();
  await expect(page.getByRole("heading", { name: result.items[0].title })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: result.items[0].title })).toBeVisible();
});

test("search and results fit a mobile viewport", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/productions/search?**", route => route.fulfill({ json: result }));
  await page.goto("/");
  await page.screenshot({ path: testInfo.outputPath("search-home-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "Segurança do paciente", exact: true }).click();
  await expect(page.getByRole("heading", { name: result.items[0].title })).toBeVisible();
  await expect(page.getByRole("searchbox")).toHaveValue("Segurança do paciente");
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflows).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("search-results-mobile.png"), fullPage: true });
});
