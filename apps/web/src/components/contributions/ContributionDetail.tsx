import type { PublicContribution } from "@/lib/contribution-api";
import { ContributionProvenance } from "./ContributionProvenance";

const sections = [
  { title: "O que esta contribuição ajuda a compreender ou fazer?", keys: ["description", "mechanism", "contribution_type"] },
  { title: "A qual problema público se relaciona?", keys: ["problem_or_phenomenon"] },
  { title: "Que evidências a sustentam?", keys: ["evidence_results", "methodology"] },
  { title: "Em quais condições pode ser aplicada?", keys: ["applicability", "territory", "population", "service", "required_resources"] },
  { title: "Quais são os limites, riscos ou barreiras?", keys: ["barriers_limitations", "risks_contraindications", "maturity"] },
];

function firstValue(values: Record<string, unknown>, keys: string[]) {
  for (const key of keys) if (values[key] !== undefined && values[key] !== null && String(values[key]).trim()) return String(values[key]);
  return "A validação não identificou informação suficiente para responder a esta pergunta.";
}

export function ContributionDetail({ contribution }: { contribution: PublicContribution }) {
  const abstractOnly = contribution.source_scope === "abstract_only";
  return (
    <article className="contribution-detail">
      <header className="contribution-hero"><span className="eyebrow">Contribuição científica validada</span><h1>Conhecimento que pode apoiar uma resposta pública</h1><p>Esta é uma contribuição potencialmente útil para análise e ação. Sua aplicação exige avaliação do contexto, dos limites e das evidências apresentadas.</p><div className="contribution-meta"><span>{contribution.institution ?? "Instituição não informada"}</span><span>Versão {contribution.version}</span></div></header>
      {(abstractOnly || contribution.source_warning) && <p className="warning">{contribution.source_warning ?? "Evidência limitada ao resumo"}</p>}
      <div className="question-stack">{sections.map((section) => <section key={section.title}><h2>{section.title}</h2><p>{firstValue(contribution.scientific_values, section.keys)}</p></section>)}</div>
      <section className="evidence-box" aria-labelledby="evidence-title"><h2 id="evidence-title">Trechos que fundamentam a contribuição</h2>{contribution.approved_groundings.length ? <blockquote>{contribution.approved_groundings.map((item, index) => { const page = item.page ?? item.page_number; return <p key={index}>“{item.text ?? item.quote}”{page ? <cite> p. {page}</cite> : null}</p>; })}</blockquote> : <p>Nenhum trecho pode ser exibido publicamente.</p>}</section>
      <ContributionProvenance contribution={contribution} />
    </article>
  );
}
