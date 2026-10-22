"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { searchParameters, searchProductions } from "@/lib/search-api";
import type { SearchPage, SearchRequest, SearchResult } from "@/lib/search-api";

const defaultFilters = { institution: "", type: "", publication_year: "", sort: "relevance" as const, page: 1 };
const examples = ["Segurança do paciente", "Saneamento rural", "Gestão de resíduos"];

function sourceUrl(value: string | null): string | undefined {
  if (!value) return undefined;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? value : undefined; }
  catch { return undefined; }
}

function ResultCard({ result }: { result: SearchResult }) {
  const url = sourceUrl(result.source.source_url);
  const hasContributions = result.validated_contributions.length > 0;
  return (
    <article className="search-result">
      <div className="search-result__meta">
        <span>{result.type === "thesis" ? "Tese" : "Dissertação"}</span>
        <span>{result.publication_year}</span>
        <span>{result.institutions.join(" · ") || result.source.name || "Instituição não informada"}</span>
      </div>
      <h3>{result.title}</h3>
      {result.authors.length > 0 && <p className="search-result__authors">{result.authors.join("; ")}</p>}
      <p className="search-result__excerpt">{result.abstract ? `${result.abstract.slice(0, 320)}${result.abstract.length > 320 ? "…" : ""}` : "Resumo não informado pela fonte. Consulte o trabalho original para conhecer seu conteúdo."}</p>
      <div className="search-result__status">
        <span className={hasContributions ? "validation-tag validation-tag--approved" : "validation-tag"}>
          {hasContributions ? "Com contribuições validadas" : "Metadados da fonte"}
        </span>
        {!hasContributions && <span>Interpretação científica pendente</span>}
      </div>
      {hasContributions && <div className="search-insights">
        {result.validated_contributions.map(contribution => (
          <div key={contribution.scientific_contribution_id}>
            <p className="search-insights__title">Contribuição validada</p>
            <p>{String(contribution.scientific_values.description || contribution.scientific_values.problem_or_phenomenon || "Consulte os fundamentos desta contribuição.")}</p>
            {([ ["Evidências", "evidence_results"], ["Barreiras e limites", "barriers_limitations"], ["Aplicabilidade", "applicability"] ] as const).map(([label, key]) => contribution.scientific_values[key] ? (
              <p key={key}><strong>{label}: </strong>{String(contribution.scientific_values[key])}</p>
            ) : null)}
            {contribution.source_warning && <p className="search-source-warning">{contribution.source_warning}</p>}
            <a href={`/contribuicoes/${contribution.scientific_contribution_id}`}>Ver evidências e validação →</a>
          </div>
        ))}
      </div>}
      <details className="search-result__details">
        <summary>Ver resumo completo e termos encontrados</summary>
        <p>{result.abstract || "Resumo não disponível na fonte."}</p>
        {result.keywords.length > 0 && <p><strong>Palavras-chave: </strong>{result.keywords.join("; ")}</p>}
        <p className="search-match">Termos encontrados: {result.matched_terms.join(", ")}. A correspondência textual ajuda a localizar trabalhos; a aplicabilidade precisa ser examinada.</p>
      </details>
      {url && <a className="search-result__source" href={url} target="_blank" rel="noopener noreferrer">Acessar fonte original <span aria-hidden="true">↗</span></a>}
      {!url && <p className="search-match">Link da fonte não disponível neste registro.</p>}
      {result.source.access_status === "unavailable" && url && <p className="search-match">O registro foi sinalizado como indisponível na fonte; o link é preservado para referência.</p>}
    </article>
  );
}

export function SearchExperience() {
  const [expression, setExpression] = useState("");
  const [applied, setApplied] = useState<SearchRequest | null>(null);
  const [results, setResults] = useState<SearchPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const resultsTitle = useRef<HTMLHeadingElement>(null);

  const runSearch = useCallback(async (request: SearchRequest, updateUrl = true) => {
    controller.current?.abort();
    const activeController = new AbortController();
    controller.current = activeController;
    const id = ++sequence.current;
    setApplied(request); setLoading(true); setError(null);
    if (updateUrl) window.history.pushState({}, "", `/?${searchParameters(request)}`);
    try {
      const response = await searchProductions(request, activeController.signal);
      if (id !== sequence.current) return;
      setResults(response);
    } catch (reason) {
      if (id !== sequence.current || activeController.signal.aborted) return;
      setError(reason instanceof Error && reason.message.startsWith("Use uma expressão") ? reason.message : "Não foi possível realizar a busca agora. Tente novamente.");
    } finally {
      if (id === sequence.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    function restore() {
      const params = new URLSearchParams(window.location.search);
      const q = params.get("q") || "";
      setExpression(q);
      if (q.trim().length < 2) {
        controller.current?.abort(); sequence.current++; setApplied(null); setResults(null); setError(null); setLoading(false);
        return;
      }
      const parsedPage = Number(params.get("page") || "1");
      void runSearch({ q, institution: params.get("institution") || "", type: params.get("type") || "",
        publication_year: params.get("publication_year") || "", sort: params.get("sort") === "recent" ? "recent" : "relevance",
        page: Number.isInteger(parsedPage) && parsedPage > 0 && parsedPage <= 1000000 ? parsedPage : 1 }, false);
    }
    restore();
    window.addEventListener("popstate", restore);
    return () => { controller.current?.abort(); sequence.current++; window.removeEventListener("popstate", restore); };
  }, [runSearch]);

  function submit(q: string) {
    const trimmed = q.trim();
    setExpression(q);
    if (trimmed.length < 2) { setError("Digite uma expressão com pelo menos duas letras."); return; }
    void runSearch({ q: trimmed, ...defaultFilters });
  }

  function refine(field: keyof SearchRequest, value: string) {
    if (applied) void runSearch({ ...applied, [field]: value, page: 1 });
  }

  const hasFilters = applied && (applied.institution || applied.type || applied.publication_year || applied.sort !== "relevance");
  const lastPage = results ? Math.max(1, Math.ceil(results.total / results.page_size)) : 1;

  return (
    <div className={`search-experience${applied ? " search-experience--active" : ""}`}>
      <section className="search-hero" aria-labelledby="search-heading">
        <p className="eyebrow">Ciência de Pernambuco ao seu alcance</p>
        <h1 id="search-heading">Uma busca.<br /><span>Novas possibilidades.</span></h1>
        <p className="search-hero__intro">Encontre teses, dissertações e contribuições científicas a partir de um problema, tema ou expressão.</p>
        <form className="expression-form" role="search" onSubmit={event => { event.preventDefault(); submit(expression); }}>
          <label className="sr-only" htmlFor="search-expression">Expressão de busca</label>
          <div className="expression-field">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.5" /><path d="m16 16 4.5 4.5" /></svg>
            <input id="search-expression" type="search" value={expression} onChange={event => setExpression(event.target.value)} placeholder="Ex.: filas de espera na saúde" maxLength={300} required minLength={2} autoComplete="off" />
            <button type="submit" className="search-submit">Buscar <span aria-hidden="true">→</span></button>
          </div>
        </form>
        {!applied && <div className="search-examples"><span>Experimente:</span>{examples.map(example => <button type="button" key={example} onClick={() => submit(example)}>{example}</button>)}</div>}
        {!applied && <p className="search-corpus">Teses e dissertações · Instituições públicas de Pernambuco · 2016–2025</p>}
      </section>

      {applied && <section className="search-results-region" aria-labelledby="results-heading" aria-busy={loading}>
        <div className="search-results-heading">
          <div><p className="eyebrow">Conhecimento para explorar</p><h2 id="results-heading" ref={resultsTitle} tabIndex={-1}>Resultados da busca</h2></div>
          {!loading && !error && results && <p role="status">{results.total.toLocaleString("pt-BR")} resultado{results.total === 1 ? "" : "s"}</p>}
        </div>
        {results && <div className="search-filters" aria-label="Filtros opcionais">
          <label>Instituição<select aria-label="Instituição" value={applied.institution} disabled={loading} onChange={event => refine("institution", event.target.value)}>
            <option value="">Todas as instituições</option>{results.facets.institutions.map(institution => <option key={institution} value={institution}>{institution}</option>)}
          </select></label>
          <label>Tipo de trabalho<select aria-label="Tipo de trabalho" value={applied.type} disabled={loading} onChange={event => refine("type", event.target.value)}>
            <option value="">Teses e dissertações</option><option value="thesis">Tese</option><option value="dissertation">Dissertação</option>
          </select></label>
          <label>Ano<select aria-label="Ano" value={applied.publication_year} disabled={loading} onChange={event => refine("publication_year", event.target.value)}>
            <option value="">2016–2025</option>{results.facets.years.map(year => <option key={year} value={year}>{year}</option>)}
          </select></label>
          <label>Ordenar por<select aria-label="Ordenar por" value={applied.sort} disabled={loading} onChange={event => refine("sort", event.target.value)}>
            <option value="relevance">Relevância textual</option><option value="recent">Mais recentes</option>
          </select></label>
          {hasFilters && <button className="search-clear" type="button" disabled={loading} onClick={() => void runSearch({ q: applied.q, ...defaultFilters })}>Limpar filtros</button>}
        </div>}
        {loading && <div className="search-loading" role="status"><span className="loading-dot" aria-hidden="true" />Buscando trabalhos relacionados…</div>}
        {!loading && !error && results && <>
          {results.total === 0 ? <div className="search-empty"><h3>Nenhum resultado encontrado</h3><p>Tente uma expressão mais ampla{hasFilters ? " ou remova os filtros" : ""}. O resultado se refere ao acervo disponível nesta ferramenta.</p></div> : <div className="search-result-list">{results.items.map(item => <ResultCard key={item.id} result={item} />)}</div>}
          {results.total > 0 && results.items.length === 0 && <div className="search-empty"><p>Esta página está além dos resultados disponíveis.</p><button type="button" onClick={() => void runSearch({ ...applied, page: 1 })}>Voltar à primeira página</button></div>}
          {lastPage > 1 && <nav className="search-pagination" aria-label="Páginas dos resultados">
            <button type="button" disabled={results.page <= 1} onClick={() => { void runSearch({ ...applied, page: applied.page - 1 }); resultsTitle.current?.focus(); }}>← Anterior</button>
            <span>Página {results.page} de {lastPage}</span>
            <button type="button" disabled={results.page >= lastPage} onClick={() => { void runSearch({ ...applied, page: applied.page + 1 }); resultsTitle.current?.focus(); }}>Próxima →</button>
          </nav>}
        </>}
      </section>}
      {error && <div className="error-box search-error" role="alert"><p>{error}</p>{applied && <button type="button" onClick={() => void runSearch(applied, false)}>Tentar novamente</button>}</div>}
    </div>
  );
}
