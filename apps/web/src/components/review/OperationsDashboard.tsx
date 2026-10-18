"use client";

import { useEffect, useState } from "react";
import type { InternalApi } from "@/lib/internal-api";

export function OperationsDashboard({ api }: { api: InternalApi }) {
  const [data, setData] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  useEffect(() => { api.dashboard().then(setData).catch((cause: Error) => setError(cause.message)); }, [api]);
  return <section aria-labelledby="operations-title"><h2 id="operations-title">Visão operacional</h2>{error && <p role="alert" className="error-box">{error}</p>}<div className="metric-grid"><article><strong>{String(data.review_pending ?? "—")}</strong><span>revisões pendentes</span></article><article><strong>{String(data.publication_pending ?? "—")}</strong><span>publicações pendentes</span></article><article><strong>{Object.values((data.documents as object) ?? {}).reduce<number>((sum, value) => sum + Number(value), 0) || "—"}</strong><span>documentos acompanhados</span></article></div></section>;
}
