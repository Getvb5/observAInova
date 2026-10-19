"use client";

import { useEffect, useState } from "react";

import type { ProblemApi, ProblemEvidenceMap } from "@/lib/problem-api";

interface ProblemHandoffProps {
  api: ProblemApi;
  problemId: string;
  editToken: string;
}

export function ProblemHandoff({ api, problemId, editToken }: ProblemHandoffProps) {
  const [map, setMap] = useState<ProblemEvidenceMap | null>(null);
  const [error, setError] = useState(false);

  function load(): void {
    setError(false);
    void api
      .evidenceMap(problemId, editToken)
      .then(setMap)
      .catch(() => setError(true));
  }

  useEffect(load, [api, problemId, editToken]);

  return (
    <section className="panel handoff-panel" aria-labelledby="handoff-title">
      <div className="confirmation-mark" aria-hidden="true">
        ✓
      </div>
      <p className="eyebrow">Formulação registrada</p>
      <h1 id="handoff-title">Problema confirmado</h1>
      <p className="handoff-copy">
        O mapa é construído somente com contribuições científicas validadas pela equipe central. Nenhuma
        sugestão automática é apresentada como evidência.
      </p>

      {!map && !error ? (
        <div className="evidence-status" aria-live="polite">
          <span className="loading-dot" aria-hidden="true" />
          Buscando contribuições científicas validadas…
        </div>
      ) : null}

      {error ? (
        <div className="error-box" role="alert">
          <p>Não foi possível construir o mapa agora. Sua formulação permanece salva.</p>
          <button type="button" onClick={load}>
            Tentar novamente
          </button>
        </div>
      ) : null}

      {map?.status === "no_validated_evidence" ? (
        <div className="evidence-gap" aria-live="polite">
          <p className="eyebrow">Lacuna de evidência</p>
          <h2>Ainda não há contribuição validada para este problema</h2>
          <p>
            A ausência é exibida de forma explícita. Novos resultados só aparecerão depois da
            análise documental e da validação humana integral.
          </p>
        </div>
      ) : null}

      {map?.status === "ready" ? (
        <div className="evidence-map" aria-live="polite">
          <div className="evidence-map__heading">
            <div>
              <p className="eyebrow">Mapa inicial de evidências</p>
              <h2>Contribuições científicas relacionadas</h2>
            </div>
            <span>{map.items.length} validada{map.items.length === 1 ? "" : "s"}</span>
          </div>
          <p className="evidence-map__summary">{map.query_summary}</p>
          <div className="evidence-list">
            {map.items.map((item) => (
              <article className="evidence-card" key={item.scientific_contribution_id}>
                <div className="evidence-card__meta">
                  <span>{item.institution ?? "Instituição não informada"}</span>
                  <span>{item.publication_year ?? "Ano não informado"}</span>
                  <span>{item.contribution_type ?? "Contribuição científica"}</span>
                </div>
                <h3>{item.description ?? item.problem_or_phenomenon ?? "Contribuição validada"}</h3>
                <p className="match-explanation">{item.explanation}</p>
                <dl className="evidence-card__details">
                  {item.evidence_results ? (
                    <div>
                      <dt>Evidência observada</dt>
                      <dd>{item.evidence_results}</dd>
                    </div>
                  ) : null}
                  {item.barriers_limitations ? (
                    <div>
                      <dt>Barreiras e limites</dt>
                      <dd>{item.barriers_limitations}</dd>
                    </div>
                  ) : null}
                  {item.applicability ? (
                    <div>
                      <dt>Condições de aplicação</dt>
                      <dd>{item.applicability}</dd>
                    </div>
                  ) : null}
                </dl>
                <a
                  className="evidence-link"
                  href={`/contribuicoes/${item.scientific_contribution_id}`}
                >
                  Examinar fundamento científico
                </a>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
