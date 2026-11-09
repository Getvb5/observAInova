"use client";

import { useEffect, useState } from "react";
import { answerParameters, getResearchAnswer } from "@/lib/answer-api";
import type { AnswerSource, AnswerStatement, ResearchAnswerData } from "@/lib/answer-api";
import type { SearchRequest } from "@/lib/search-api";

const sections = [
  ["context", "O que as pesquisas mostram"], ["feasibility", "É possível?"],
  ["pathways", "Como avançar"], ["potentials", "Potenciais"], ["limitations", "Condições e limites"],
] as const;
function safeUrl(value: string | null) {
  try { const url = new URL(value || ""); return ["https:", "http:"].includes(url.protocol) ? value! : undefined; }
  catch { return undefined; }
}
function Statement({ statement }: { statement: AnswerStatement }) {
  return <p className="research-answer__statement">
    {statement.text}{" "}
    {statement.citations.map((citation, index) => <a key={`${citation.excerpt_id}-${index}`} className="research-answer__citation"
      href={`#answer-${citation.excerpt_id}`} aria-label={`Conferir trecho ${citation.excerpt_id}`}
      onClick={() => { const detail = document.getElementById(`answer-${citation.excerpt_id}`); if (detail instanceof HTMLDetailsElement) detail.open = true; }}>
      [{citation.excerpt_id}]
    </a>)}
    {statement.basis === "inference" && <span className="research-answer__inference">Possibilidade de aplicação — depende de avaliação local</span>}
  </p>;
}
function Sources({ sources }: { sources: AnswerSource[] }) {
  return <div className="research-answer__sources"><h3>Trabalhos e trechos usados</h3>
    {sources.map(source => <div className="research-answer__source" key={source.id}>
      <p><strong>[{source.id}] </strong>{safeUrl(source.url)
        ? <a href={safeUrl(source.url)} target="_blank" rel="noopener noreferrer">{source.title} ↗</a>
        : <strong>{source.title}</strong>}</p>
      <p className="research-answer__scope">{source.authors.join("; ")}{source.year ? ` · ${source.year}` : ""} · {source.reading_scope === "abstract_only" ? "Leitura de resumo" : "Leitura de trechos do texto integral"}</p>
      {source.excerpts.map(excerpt => <details id={`answer-${excerpt.id}`} key={excerpt.id}>
        <summary>Trecho {excerpt.id}{excerpt.page ? ` · página ${excerpt.page}` : ""}</summary>
        <blockquote>{excerpt.text}</blockquote>
      </details>)}
    </div>)}
  </div>;
}
export function ResearchAnswer({ request }: { request: SearchRequest }) {
  const key = answerParameters(request);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ key: string; answer: ResearchAnswerData | null; failed: boolean } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setState(null);
    const timeout = window.setTimeout(() => {
      controller.abort();
      if (active) setState({ key, answer: null, failed: true });
    }, 95000);
    void getResearchAnswer(key, controller.signal).then(answer => {
      if (active && !controller.signal.aborted) setState({ key, answer, failed: false });
    }).catch(() => {
      if (active && !controller.signal.aborted) setState({ key, answer: null, failed: true });
    }).finally(() => window.clearTimeout(timeout));
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [key, attempt]);
  const current = state?.key === key ? state : null;
  const answer = current?.answer;
  const loading = !current;
  return <section className="research-answer" aria-labelledby="research-answer-heading" aria-busy={loading}>
    <p className="eyebrow">Do problema às possibilidades</p><h2 id="research-answer-heading">Como enfrentar este problema?</h2>
    {loading && <p role="status" className="research-answer__notice"><span className="loading-dot" aria-hidden="true" /> Analisando os textos disponíveis nos trabalhos recuperados…</p>}
    {current?.failed && <p role="status">Não foi possível gerar a resposta agora. Os trabalhos encontrados continuam disponíveis abaixo.</p>}
    {answer && <>
      <p className="research-answer__notice" role="status">{answer.message}</p>
      {answer.analysis && <div className="research-answer__body">
        {sections.map(([field, title]) => answer.analysis![field].length > 0 && <div key={field}>
          <h3>{title}</h3>{answer.analysis![field].map((statement, index) => <Statement key={index} statement={statement} />)}
        </div>)}
        {answer.analysis.potentials.length === 0 && answer.status === "ready" && <p>Os trechos analisados não permitem detalhar outros potenciais.</p>}
      </div>}
      {answer.sources.length > 0 && <>
        <p className="research-answer__coverage">Base da análise: {answer.sources.length} trabalho{answer.sources.length === 1 ? "" : "s"} entre {answer.total_matches} encontrado{answer.total_matches === 1 ? "" : "s"}. A seleção usa relevância textual e não constitui uma revisão exaustiva. O tipo de leitura está indicado em cada fonte.</p>
        <Sources sources={answer.sources} />
      </>}
    </>}
    {(current?.failed || answer?.status === "unavailable") && <button className="research-answer__retry" type="button" onClick={() => setAttempt(value => value + 1)}>Tentar gerar a resposta novamente</button>}
  </section>;
}
