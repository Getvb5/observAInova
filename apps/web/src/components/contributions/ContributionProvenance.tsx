import type { PublicContribution } from "@/lib/contribution-api";

function dateLabel(value?: string | null) {
  return value ? new Intl.DateTimeFormat("pt-BR", { dateStyle: "long", timeZone: "America/Recife" }).format(new Date(value)) : "data não informada";
}

export function ContributionProvenance({ contribution }: { contribution: PublicContribution }) {
  const production = contribution.production_type === "thesis" ? "Tese" : contribution.production_type === "dissertation" ? "Dissertação" : "Produção acadêmica";
  return (
    <details className="provenance">
      <summary>Proveniência e fonte</summary>
      <dl>
        <div><dt>Instituição</dt><dd>{contribution.institution ?? "Não informada"}</dd></div>
        <div><dt>Documento</dt><dd>{production}{contribution.publication_year ? ` · ${contribution.publication_year}` : ""}</dd></div>
        <div><dt>Versão pública</dt><dd>Versão {contribution.version} · publicada em {dateLabel(contribution.published_at)}</dd></div>
        <div><dt>Validação humana</dt><dd>{dateLabel(contribution.validated_at)}</dd></div>
      </dl>
      {contribution.original_url ? <a className="source-link" href={contribution.original_url} rel="noreferrer" target="_blank">Abrir documento original</a> : <p className="warning">Documento original indisponível nesta projeção.</p>}
    </details>
  );
}
