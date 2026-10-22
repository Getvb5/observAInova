import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import Home from "@/app/page";

const result = {
  query: "segurança do paciente", total: 1, page: 1, page_size: 10,
  facets: { institutions: ["Universidade Federal de Pernambuco"], years: [2023] },
  items: [{ id: "record-1", title: "Segurança do paciente na atenção básica", abstract: "Estudo sobre organização do cuidado.",
    publication_year: 2023, publication_date: null, type: "dissertation", authors: ["Autoria de teste"],
    institutions: ["Universidade Federal de Pernambuco"], keywords: ["saúde"], language: "pt-BR",
    identifiers: {}, publishers: [], rights: null, full_text_available: false, territory_relations: [],
    source: { code: "fixture", name: "Fonte de teste", source_identifier: "test", source_url: "https://repository.example/item/1", access_status: "available" },
    quality: { missing_fields: [] }, matched_terms: ["seguranca", "paciente"], validated_contributions: [] }],
};

beforeEach(() => { window.history.replaceState({}, "", "/"); });
afterEach(() => { vi.unstubAllGlobals(); });

it("shows research after one expression and Enter, without a formulation questionnaire", async () => {
  vi.stubGlobal("fetch", async (url: string) => {
    const request = new URL(url, "http://localhost");
    if (request.pathname !== "/api/v1/productions/search" || request.searchParams.get("q") !== "segurança do paciente") throw new Error("Unexpected request");
    return Response.json(result);
  });
  const user = userEvent.setup();
  render(<Home />);
  await user.type(screen.getByRole("searchbox", { name: "Expressão de busca" }), "segurança do paciente{Enter}");
  expect(await screen.findByRole("heading", { name: result.items[0].title })).toBeInTheDocument();
  expect(screen.getByText(/interpretação científica pendente/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /acessar fonte/i })).toHaveAttribute("href", "https://repository.example/item/1");
  expect(screen.queryByText(/em qual território/i)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Confirmar formulação" })).not.toBeInTheDocument();
});

it("keeps the expression and offers retry after a network failure", async () => {
  let fail = true;
  vi.stubGlobal("fetch", async () => { if (fail) throw new Error("Network unavailable"); return Response.json(result); });
  const user = userEvent.setup();
  render(<Home />);
  await user.type(screen.getByRole("searchbox"), "segurança do paciente{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent(/não foi possível/i);
  expect(screen.getByRole("searchbox")).toHaveValue("segurança do paciente");
  fail = false;
  await user.click(screen.getByRole("button", { name: "Tentar novamente" }));
  expect(await screen.findByRole("heading", { name: result.items[0].title })).toBeInTheDocument();
});

it("restores a search from the URL and refines it with optional filters", async () => {
  window.history.replaceState({}, "", "/?q=seguranca&page=2");
  vi.stubGlobal("fetch", async (url: string) => {
    const request = new URL(url, "http://localhost");
    const filtered = request.searchParams.get("type") === "thesis";
    if (filtered && request.searchParams.get("page") !== "1") throw new Error("Filter did not reset pagination");
    return Response.json(filtered ? { ...result, items: [], total: 0 } : { ...result, total: 11, page: 2 });
  });
  const user = userEvent.setup();
  render(<Home />);
  await screen.findByRole("heading", { name: result.items[0].title });
  await user.selectOptions(screen.getByLabelText("Tipo de trabalho"), "thesis");
  expect(await screen.findByText(/nenhum resultado encontrado/i)).toBeInTheDocument();
  expect(screen.getByRole("searchbox")).toHaveValue("seguranca");
});
