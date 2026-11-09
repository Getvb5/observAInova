import { act, render, screen, waitFor } from "@testing-library/react";
import { ResearchAnswer } from "@/components/search/ResearchAnswer";
import type { SearchRequest } from "@/lib/search-api";

const request: SearchRequest = { q: "saneamento rural", institution: "", type: "", publication_year: "", sort: "relevance", page: 1 };
const statement = { text: "A aplicação depende de manutenção e de avaliação no município.", basis: "inference", citations: [{ excerpt_id: "S1-E1", quote: "Os filtros exigem manutenção periódica." }] };
const answer = {
  query: request.q, status: "ready", total_matches: 12, validation_status: "automated_unreviewed",
  message: "Síntese automática preliminar, sem revisão humana.",
  sources: [{ id: "S1", production_id: "1", production_version_id: "v1", text_version_id: null,
    title: "Pesquisa de teste sobre filtros", authors: ["Autora de teste"], year: 2023,
    url: "https://repository.example/1", reading_scope: "abstract_only",
    excerpts: [{ id: "S1-E1", text: "Os filtros exigem manutenção periódica.", page: null }] }],
  analysis: { outcome: "conditional", context: [statement], feasibility: [statement], pathways: [statement], potentials: [], limitations: [statement] },
};
afterEach(() => { vi.unstubAllGlobals(); });
it("automatically answers with citations and explicit reading limits", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json(answer));
  vi.stubGlobal("fetch", fetcher);
  render(<ResearchAnswer request={request} />);
  expect(await screen.findByText(/síntese automática preliminar/i)).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "É possível?" })).toBeInTheDocument();
  expect(screen.getAllByText(/possibilidade de aplicação/i)[0]).toBeInTheDocument();
  expect(screen.getByText(/leitura de resumo/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /pesquisa de teste/i })).toHaveAttribute("href", answer.sources[0].url);
  expect(screen.getAllByRole("link", { name: /conferir trecho/i })[0]).toHaveAttribute("href", "#answer-S1-E1");
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toEqual({ q: request.q });
});
it("keeps the answer across pagination and sorting but reanalyzes filters", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json(answer));
  vi.stubGlobal("fetch", fetcher);
  const { rerender } = render(<ResearchAnswer request={request} />);
  await screen.findByText(/síntese automática preliminar/i);
  rerender(<ResearchAnswer request={{ ...request, page: 2, sort: "recent" }} />);
  expect(fetcher).toHaveBeenCalledTimes(1);
  rerender(<ResearchAnswer request={{ ...request, type: "thesis" }} />);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(JSON.parse(fetcher.mock.calls[1][1]!.body as string).type).toBe("thesis");
});
it("ignores stale responses after the problem changes", async () => {
  let finishFirst!: (response: Response) => void;
  const first = new Promise<Response>(resolve => { finishFirst = resolve; });
  vi.stubGlobal("fetch", vi.fn().mockReturnValueOnce(first).mockResolvedValueOnce(Response.json({ ...answer, query: "resíduos", message: "Resposta sobre resíduos" })));
  const { rerender } = render(<ResearchAnswer request={request} />);
  rerender(<ResearchAnswer request={{ ...request, q: "resíduos" }} />);
  await screen.findByText("Resposta sobre resíduos");
  await act(async () => { finishFirst(Response.json(answer)); });
  expect(screen.getByText("Resposta sobre resíduos")).toBeInTheDocument();
  expect(screen.queryByText(answer.message)).not.toBeInTheDocument();
});
it("explains unavailable synthesis without fabricating conclusions", async () => {
  vi.stubGlobal("fetch", async () => Response.json({ ...answer, status: "unavailable", analysis: null, sources: [], message: "A síntese científica ainda não está ativada." }));
  render(<ResearchAnswer request={request} />);
  await screen.findByText(/a síntese científica ainda não está ativada/i);
  expect(screen.queryByRole("heading", { name: "É possível?" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /tentar gerar a resposta/i })).toBeInTheDocument();
});
it("does not equate missing evidence to impossibility or render unsafe source links", async () => {
  vi.stubGlobal("fetch", async () => Response.json({ ...answer, status: "insufficient_evidence", analysis: null, message: "Evidência insuficiente não significa impossibilidade.", sources: [{ ...answer.sources[0], url: "javascript:alert(1)" }] }));
  render(<ResearchAnswer request={request} />);
  await screen.findByText(/não significa impossibilidade/i);
  expect(screen.queryByRole("link", { name: /pesquisa de teste/i })).not.toBeInTheDocument();
});
