import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/answers", route => route.fulfill({ json: {
    query: "segurança do paciente", status: "unavailable", total_matches: 1,
    message: "A síntese científica ainda não está ativada.", sources: [], analysis: null,
    validation_status: "automated_unreviewed",
  } }));
});

test("a problem receives a preliminary answer with a clickable source excerpt", async ({ page }) => {
  const statement = { text: "A pesquisa sugere examinar as condições locais antes de aplicar a proposta.", basis: "inference", citations: [{ excerpt_id: "S1-E1", quote: "Este trecho é sintético e exclusivo do teste da interface." }] };
  await page.route("**/api/v1/productions/search?**", route => route.fulfill({ json: {
    query: "saneamento", items: [], total: 0, page: 1, page_size: 10, facets: { institutions: [], years: [] },
  } }));
  await page.route("**/api/v1/answers", route => route.fulfill({ json: {
    query: "saneamento", status: "ready", total_matches: 1, validation_status: "automated_unreviewed",
    message: "Síntese automática preliminar, sem revisão humana.",
    analysis: { outcome: "conditional", context: [statement], feasibility: [statement], pathways: [statement], potentials: [], limitations: [statement] },
    sources: [{ id: "S1", title: "Pesquisa sintética para teste", authors: ["Autoria de teste"], year: 2023,
      url: "https://repository.example/item/1", reading_scope: "abstract_only",
      excerpts: [{ id: "S1-E1", text: "Este trecho é sintético e exclusivo do teste da interface.", page: null }] }],
  } }));
  await page.goto("/");
  await page.getByRole("searchbox").fill("saneamento");
  await page.getByRole("searchbox").press("Enter");
  await expect(page.getByRole("heading", { name: "É possível?" })).toBeVisible();
  await page.getByRole("link", { name: "Conferir trecho S1-E1" }).first().click();
  await expect(page.locator("#answer-S1-E1 blockquote")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

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
  expect(requests).toHaveLength(2);
  expect(requests.some(url => url.includes("/productions/search?"))).toBe(true);
  expect(requests.some(url => url.endsWith("/answers"))).toBe(true);
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
