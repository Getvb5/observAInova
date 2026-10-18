"use client";

import { useState } from "react";
import type { InternalApi, PublicationAction, SupervisionDetail } from "@/lib/internal-api";

export interface SupervisionWorkbenchProps { version: SupervisionDetail; api: InternalApi }

export function SupervisionWorkbench({ version, api }: SupervisionWorkbenchProps) {
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const sameActor = version.validatedBy.includes(version.currentActor);

  async function decide(action: PublicationAction) {
    setError(""); setMessage("");
    if (["return", "supersede", "revoke"].includes(action) && !reason.trim()) { setError("Informe o motivo da decisão."); return; }
    if (action === "revoke" && confirmation !== "REVOGAR") { setError("Digite REVOGAR para confirmar a retirada pública."); return; }
    try { await api.decidePublication(version.id, { action, reason: reason.trim() || undefined }); setMessage("Decisão de supervisão registrada."); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível registrar a decisão."); }
  }

  return (
    <section className="workbench supervision" aria-labelledby="supervision-title">
      <span className="eyebrow">Supervisão e publicação</span><h2 id="supervision-title">Contribuição validada · versão {version.version}</h2>
      {version.sourceWarning && <p className="warning">{version.sourceWarning}</p>}
      <dl className="validated-values">{Object.entries(version.scientificValues).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{String(value)}</dd></div>)}</dl>
      <h3>Fundamentos aprovados</h3><ul>{version.approvedGroundings.map((item, index) => <li key={index}>{item.text}{item.page ? ` · p. ${item.page}` : ""}</li>)}</ul>
      {sameActor && <p className="warning">Separação de funções: outra pessoa deve tomar qualquer decisão de supervisão sobre esta contribuição.</p>}
      <label htmlFor="supervision-reason">Motivo para devolução, substituição ou revogação</label><textarea id="supervision-reason" value={reason} onChange={(event) => setReason(event.target.value)} />
      <label htmlFor="revoke-confirmation">Confirmação de revogação</label><input id="revoke-confirmation" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder="Digite REVOGAR" />
      {error && <p role="alert" className="error-box">{error}</p>}{message && <p role="status" className="success">{message}</p>}
      <div className="button-row">{version.status !== "published" && <><button className="primary-button" disabled={sameActor} onClick={() => decide("publish")}>Publicar contribuição</button><button className="secondary-button" disabled={sameActor} onClick={() => decide("return")}>Devolver à curadoria</button><button className="secondary-button" disabled={sameActor} onClick={() => decide("supersede")}>Publicar como substituição</button></>}{version.status === "published" && <button className="danger-button" disabled={sameActor} onClick={() => decide("revoke")}>Revogar publicação</button>}</div>
    </section>
  );
}
