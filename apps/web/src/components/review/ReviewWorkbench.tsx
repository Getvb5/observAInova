"use client";

import { useMemo, useState, type ReactNode } from "react";
import type { AdjudicationContext, FieldDecisionAction, InternalApi, ReviewAssignmentDetail, ReviewCaseDetail } from "@/lib/internal-api";

export interface ReviewWorkbenchProps {
  reviewCase: ReviewCaseDetail;
  assignment: ReviewAssignmentDetail;
  adjudicationContext?: AdjudicationContext;
  api: InternalApi;
}

export function ReviewWorkbench({ reviewCase, assignment, adjudicationContext, api }: ReviewWorkbenchProps) {
  const [fieldIndex, setFieldIndex] = useState(0);
  const field = reviewCase.fields[fieldIndex];
  const [value, setValue] = useState(field?.value ?? "");
  const [selected, setSelected] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [decided, setDecided] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const source = useMemo(() => {
    let content: ReactNode[] = [reviewCase.sourceText];
    for (const grounding of reviewCase.groundings.filter((item) => selected.includes(item.id))) {
      const parts = reviewCase.sourceText.split(grounding.text);
      if (parts.length === 2) content = [parts[0], <mark key={grounding.id}>{grounding.text}</mark>, parts[1]];
    }
    return content;
  }, [reviewCase, selected]);

  if (!field) return <p>Não há campos candidatos neste caso.</p>;

  async function decide(action: FieldDecisionAction) {
    setError(""); setSaved("");
    if (action !== "reject" && action !== "insufficient" && selected.length === 0) {
      setError("Selecione ao menos um trecho de fundamento."); return;
    }
    if (["correct", "reject", "insufficient"].includes(action) && !reason.trim()) {
      setError("Informe o motivo da correção ou decisão negativa."); return;
    }
    try {
      await api.decideField(assignment.id, { field: field.name, action, value: action === "accept" || action === "correct" ? value : undefined, grounding_ids: selected, reason: reason.trim() || undefined });
      setSaved("Decisão registrada.");
      setDecided((items) => new Set(items).add(field.name));
      const next = Math.min(fieldIndex + 1, reviewCase.fields.length - 1);
      setFieldIndex(next); setValue(reviewCase.fields[next]?.value ?? ""); setSelected([]); setReason("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível registrar a decisão.");
    }
  }

  async function complete() {
    setError("");
    try {
      await api.completeAssignment(assignment.id);
      if (assignment.lane === "single" || assignment.lane === "adjudication") await api.materializeCase(reviewCase.id);
      setSaved(assignment.lane === "primary" || assignment.lane === "secondary" ? "Revisão independente concluída; aguardando adjudicação." : "Contribuição validada e enviada à supervisão.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível concluir a revisão."); }
  }

  return (
    <section className="workbench" aria-labelledby="review-title">
      <header><span className="eyebrow">Curadoria científica</span><h2 id="review-title">{reviewCase.sourceTitle}</h2></header>
      {reviewCase.kind === "return_correction" && <p className="warning">Versão {reviewCase.draftVersion} devolvida para correção: {reviewCase.correctionReason}</p>}
      {reviewCase.sourceKind === "abstract" && <p className="warning">Evidência disponível somente no resumo. A validação deve registrar essa limitação.</p>}
      {assignment.lane === "adjudication" && adjudicationContext && <AdjudicationComparison context={adjudicationContext} />}
      <div className="workbench__columns">
        <article className="source-reader" aria-label="Fonte documental"><h3>Texto-fonte</h3><p>{source}</p></article>
        <form className="field-editor" onSubmit={(event) => event.preventDefault()}>
          <div className="field-editor__progress">Campo {fieldIndex + 1} de {reviewCase.fields.length}{reviewCase.kind === "candidate" ? ` · confiança da IA ${Math.round(field.confidence * 100)}%` : " · valor da versão devolvida"}</div>
          <label htmlFor="validated-value">{field.label}</label>
          <textarea id="validated-value" aria-label="Valor validado" value={value} onChange={(event) => setValue(event.target.value)} />
          <fieldset><legend>Trechos de fundamento</legend>{reviewCase.groundings.filter((grounding) => field.groundingIds.includes(grounding.id)).map((grounding) => (
            <label className="grounding" key={grounding.id}><input type="checkbox" checked={selected.includes(grounding.id)} onChange={() => setSelected((items) => items.includes(grounding.id) ? items.filter((id) => id !== grounding.id) : [...items, grounding.id])} /> {grounding.text}{grounding.page ? ` · p. ${grounding.page}` : ""}</label>
          ))}</fieldset>
          <label htmlFor="decision-reason">Justificativa para correção ou decisão negativa</label><textarea id="decision-reason" value={reason} onChange={(event) => setReason(event.target.value)} />
          {error && <p className="error-box" role="alert">{error}</p>}{saved && <p className="success" role="status">{saved}</p>}
          <div className="button-row"><button className="primary-button" type="button" onClick={() => decide("accept")}>Aceitar campo</button><button className="secondary-button" type="button" onClick={() => decide("correct")}>Corrigir campo</button><button className="text-button" type="button" onClick={() => decide("reject")}>Rejeitar</button><button className="text-button" type="button" onClick={() => decide("insufficient")}>Informação insuficiente</button></div>
          {decided.size === reviewCase.fields.length && <button className="primary-button" type="button" onClick={complete}>Concluir revisão</button>}
        </form>
      </div>
    </section>
  );
}

function AdjudicationComparison({ context }: { context: AdjudicationContext }) {
  const fieldNames = Array.from(new Set(context.reviews.flatMap((review) => review.fields.map((field) => field.name))));
  return <section aria-labelledby="adjudication-comparison"><h3 id="adjudication-comparison">Comparação das revisões independentes</h3><p>As identidades permanecem ocultas. Divergências exigem uma decisão fundamentada.</p><div className="table-shell"><table><thead><tr><th>Campo</th><th>Revisão 1</th><th>Revisão 2</th></tr></thead><tbody>{fieldNames.map((name) => <tr key={name}><th>{name.replaceAll("_", " ")}{context.disagreements.includes(name) ? " · divergência" : ""}</th>{context.reviews.map((review) => { const decision = review.fields.find((item) => item.name === name); return <td key={review.review}>{decision ? `${decision.action}: ${decision.value ?? decision.reason ?? "sem valor"}` : "sem decisão"}</td>; })}</tr>)}</tbody></table></div></section>;
}
