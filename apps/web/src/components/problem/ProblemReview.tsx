import type { ProblemField, ProblemState } from "@/lib/problem-api";

const fieldLabels: Record<ProblemField, string> = {
  territory: "Território ou unidade administrativa",
  affected_population_or_service: "População, serviço ou organização afetada",
  observed_consequences: "Consequências observadas",
  perceived_causes: "Causas percebidas",
  attempted_actions: "Ações já tentadas",
  available_resources: "Recursos e capacidades disponíveis",
  constraints: "Restrições",
  desired_outcome: "Resultado desejado",
};

const statusLabels = {
  reported_fact: "Informado",
  perception: "Percepção",
  unknown: "Não informado",
} as const;

interface ProblemReviewProps {
  state: ProblemState;
  busy: boolean;
  onConfirm: () => void;
}

export function ProblemReview({ state, busy, onConfirm }: ProblemReviewProps) {
  return (
    <section className="panel review-panel" aria-labelledby="review-title">
      <p className="eyebrow">Revisão fiel</p>
      <h1 id="review-title">Foi isso que você quis dizer?</h1>
      <p className="section-intro">
        Confira sua formulação. O sistema preserva o que foi informado e explicita o
        que ainda não é conhecido.
      </p>

      <dl className="review-list">
        <div className="review-item review-item--description">
          <dt>Problema público</dt>
          <dd>{state.description}</dd>
        </div>
        {(Object.keys(fieldLabels) as ProblemField[]).map((field) => {
          const answer = state.fields[field];
          return (
            <div className="review-item" key={field}>
              <dt>{fieldLabels[field]}</dt>
              <dd>{answer?.value ?? "Não sei informar"}</dd>
              <dd className={`status status--${answer?.knowledge_status ?? "unknown"}`}>
                {statusLabels[answer?.knowledge_status ?? "unknown"]}
              </dd>
            </div>
          );
        })}
      </dl>

      <button className="primary-button" type="button" onClick={onConfirm} disabled={busy}>
        {busy ? "Confirmando…" : "Confirmar formulação"}
      </button>
    </section>
  );
}
