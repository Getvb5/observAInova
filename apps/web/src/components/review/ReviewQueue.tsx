"use client";

import { useEffect, useState } from "react";
import type { AdjudicationContext, InternalApi, ReviewAssignmentDetail, ReviewCaseDetail } from "@/lib/internal-api";
import { ReviewWorkbench } from "./ReviewWorkbench";

export function ReviewQueue({ api }: { api: InternalApi }) {
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);
  const [active, setActive] = useState<{ reviewCase: ReviewCaseDetail; assignment: ReviewAssignmentDetail; adjudicationContext?: AdjudicationContext } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.reviewQueue().then((result) => setItems(result.items)).catch(() => setItems([])); }, [api]);
  async function claim() { setError(""); try { const assignment = await api.claimReview(); setActive(await api.reviewAssignment(assignment.id)); } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível assumir um caso."); } }
  if (active) return <ReviewWorkbench reviewCase={active.reviewCase} assignment={active.assignment} adjudicationContext={active.adjudicationContext} api={api} />;
  return <section aria-labelledby="queue-title"><h2 id="queue-title">Fila de curadoria</h2><p>{items.length} atribuição(ões) aguardando revisão.</p><button className="primary-button" type="button" onClick={claim}>Assumir próximo caso</button>{error && <p role="alert" className="error-box">{error}</p>}</section>;
}
