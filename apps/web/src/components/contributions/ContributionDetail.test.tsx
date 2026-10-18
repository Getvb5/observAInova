import { render, screen } from "@testing-library/react";

import { ContributionDetail } from "./ContributionDetail";
import type { PublicContribution } from "@/lib/contribution-api";

const contribution: PublicContribution = {
  id: "projection-1", scientific_contribution_id: "contribution-1", contribution_version_id: "version-1", production_id: "production-1", version: 2,
  contribution_type: "modelo", institution: "UFPE", publication_year: 2024, source_scope: "full_text", production_type: "dissertation",
  scientific_values: { problem_or_phenomenon: "Desabastecimento de medicamentos", description: "Modelo de previsão de demanda", evidence_results: "Redução de perdas no estudo de caso", applicability: "Série histórica de consumo", barriers_limitations: "Qualidade desigual dos dados" },
  approved_groundings: [{ text: "o modelo reduziu perdas por vencimento", page: 87 }], source_warning: null,
  validated_at: "2026-10-15T10:00:00Z", published_at: "2026-10-16T10:00:00Z", original_url: "https://repositorio.example/item/1",
};

it("presents a contribution as potentially useful, not as a guaranteed solution", () => {
  render(<ContributionDetail contribution={contribution} />);
  expect(screen.getByText(/contribuição potencialmente útil/i)).toBeVisible();
  expect(screen.queryByText(/resolve definitivamente/i)).not.toBeInTheDocument();
  expect(screen.getAllByText(/versão 2/i).length).toBeGreaterThan(0);
});

it("labels evidence derived only from the abstract", () => {
  render(<ContributionDetail contribution={{ ...contribution, source_scope: "abstract_only", source_warning: "Evidência limitada ao resumo" }} />);
  expect(screen.getByText("Evidência limitada ao resumo")).toBeVisible();
});

it("exposes provenance without internal confidence or review notes", () => {
  render(<ContributionDetail contribution={contribution} />);
  expect(screen.getByText("Proveniência e fonte")).toBeVisible();
  expect(screen.queryByText(/confiança da ia/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/nota interna/i)).not.toBeInTheDocument();
});
