"use client";

import { useEffect, useState } from "react";
import type { InternalApi, SupervisionDetail } from "@/lib/internal-api";
import { SupervisionWorkbench } from "./SupervisionWorkbench";

export function SupervisionQueue({ api }: { api: InternalApi }) {
  const [items, setItems] = useState<Array<{ id: string; version: number; status: string }>>([]);
  const [active, setActive] = useState<SupervisionDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.publicationQueue().then((result) => setItems(result.items)).catch(() => setItems([])); }, [api]);
  async function open(id: string) { setError(""); try { setActive(await api.supervisionDetail(id)); } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível abrir a contribuição."); } }
  if (active) return <SupervisionWorkbench version={active} api={api} />;
  return <section aria-labelledby="supervision-queue-title"><h2 id="supervision-queue-title">Fila de supervisão</h2>{items.length === 0 ? <p className="muted">Nenhuma contribuição aguardando supervisão.</p> : <ul className="queue-list">{items.map((item) => <li key={item.id}><span>Versão {item.version} · {item.status}</span><button className="secondary-button" onClick={() => open(item.id)}>Supervisionar</button></li>)}</ul>}{error && <p role="alert" className="error-box">{error}</p>}</section>;
}
