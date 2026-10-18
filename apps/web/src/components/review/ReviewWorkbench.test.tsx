import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { ReviewWorkbench } from "./ReviewWorkbench";

const reviewCase = {
  id: "case-1",
  kind: "candidate" as const,
  sourceTitle: "Gestão de medicamentos na atenção básica",
  sourceKind: "abstract" as const,
  sourceText: "A pesquisa propõe um modelo de previsão de demanda para reduzir faltas.",
  fields: [{ name: "description", label: "Descrição", value: "Modelo de previsão de demanda", confidence: 0.82, groundingIds: ["g-1"] }],
  groundings: [{ id: "g-1", text: "modelo de previsão de demanda", page: null }],
};

const assignment = { id: "assignment-1", reviewCaseId: "case-1", lane: "primary" as const };

it("requires a foundation before accepting a field and warns about abstract-only evidence", async () => {
  const user = userEvent.setup();
  const api = { decideField: vi.fn() } as never;
  render(<ReviewWorkbench reviewCase={reviewCase} assignment={assignment} api={api} />);

  expect(screen.getByText(/somente no resumo/i)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Aceitar campo" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Selecione ao menos um trecho de fundamento.");
  expect((api as { decideField: ReturnType<typeof vi.fn> }).decideField).not.toHaveBeenCalled();
});

it("preserves a correction after a recoverable API failure", async () => {
  const user = userEvent.setup();
  const api = { decideField: vi.fn().mockRejectedValue(new Error("indisponível")) } as never;
  render(<ReviewWorkbench reviewCase={reviewCase} assignment={assignment} api={api} />);

  await user.click(screen.getByRole("checkbox", { name: /modelo de previsão/i }));
  await user.clear(screen.getByLabelText("Valor validado"));
  await user.type(screen.getByLabelText("Valor validado"), "Protocolo de previsão revisado");
  await user.type(screen.getByLabelText(/justificativa/i), "Adequação ao trecho-fonte");
  await user.click(screen.getByRole("button", { name: "Corrigir campo" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/indisponível/i);
  expect(screen.getByLabelText("Valor validado")).toHaveValue("Protocolo de previsão revisado");
});

it("shows both anonymous independent decisions during adjudication", () => {
  render(<ReviewWorkbench reviewCase={reviewCase} assignment={{ ...assignment, lane: "adjudication" }} adjudicationContext={{ reviews: [
    { review: 1, fields: [{ name: "description", action: "accept", value: "Modelo de previsão", groundingIds: ["g-1"] }] },
    { review: 2, fields: [{ name: "description", action: "reject", reason: "Evidência insuficiente", groundingIds: [] }] },
  ], disagreements: ["description"] }} api={{ decideField: vi.fn() } as never} />);

  expect(screen.getByText(/comparação das revisões independentes/i)).toBeVisible();
  expect(screen.getByText(/accept: modelo de previsão/i)).toBeVisible();
  expect(screen.getByText(/reject: evidência insuficiente/i)).toBeVisible();
  expect(screen.queryByText(/person-/i)).not.toBeInTheDocument();
});

it("labels a returned revision without presenting its value as an AI confidence", () => {
  render(<ReviewWorkbench reviewCase={{ ...reviewCase, kind: "return_correction", correctionReason: "Rever o fundamento", draftVersion: 2 }} assignment={{ ...assignment, lane: "single" }} api={{ decideField: vi.fn() } as never} />);

  expect(screen.getByText(/versão 2 devolvida para correção/i)).toBeVisible();
  expect(screen.getByText(/valor da versão devolvida/i)).toBeVisible();
  expect(screen.queryByText(/confiança da IA/i)).not.toBeInTheDocument();
});
