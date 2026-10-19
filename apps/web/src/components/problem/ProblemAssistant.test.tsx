import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ProblemAssistant } from "@/components/problem/ProblemAssistant";
import type {
  ProblemApi,
  ProblemField,
  ProblemState,
} from "@/lib/problem-api";
import { ProblemApiError } from "@/lib/problem-api";

const problemId = "00000000-0000-4000-8000-000000000001";
const editToken = "test-edit-token-that-must-stay-private";
const emptyFields: ProblemState["fields"] = {
  territory: null,
  affected_population_or_service: null,
  observed_consequences: null,
  perceived_causes: null,
  attempted_actions: null,
  available_resources: null,
  constraints: null,
  desired_outcome: null,
};

function stateWithNextQuestion(field: ProblemField): ProblemState {
  const prompts: Record<ProblemField, string> = {
    territory: "Em qual território ou unidade administrativa isso acontece?",
    affected_population_or_service: "Qual população, serviço ou organização é mais afetado?",
    observed_consequences: "Quais consequências você observa?",
    perceived_causes: "Quais causas são percebidas?",
    attempted_actions: "O que já foi tentado e qual foi o resultado?",
    available_resources: "Quais recursos ou capacidades já estão disponíveis?",
    constraints: "Quais restrições precisam ser respeitadas?",
    desired_outcome: "Que resultado concreto você deseja alcançar?",
  };
  const keys = Object.keys(emptyFields) as ProblemField[];
  return {
    problem_id: problemId,
    status: "draft",
    description: "As pessoas aguardam muito por consultas especializadas",
    fields: { ...emptyFields },
    next_question: {
      field,
      prompt: prompts[field],
      accepts_unknown: true,
    },
    missing_fields: keys.slice(keys.indexOf(field)),
    ready_to_confirm: false,
    current_version: 0,
    structured_summary: null,
    map_status: "not_ready",
  };
}

function completeProblemState(values: { constraints: string }): ProblemState {
  const fields = Object.fromEntries(
    (Object.keys(emptyFields) as ProblemField[]).map((field) => [
      field,
      {
        value: field === "constraints" ? values.constraints : `resposta para ${field}`,
        knowledge_status: field === "perceived_causes" ? "perception" : "reported_fact",
      },
    ]),
  ) as ProblemState["fields"];
  return {
    ...stateWithNextQuestion("territory"),
    fields,
    next_question: null,
    missing_fields: [],
    ready_to_confirm: true,
    structured_summary: "Formulação pronta para confirmação",
  };
}

function confirmedProblemState(): ProblemState {
  return {
    ...completeProblemState({ constraints: "Sem aumento de equipe" }),
    status: "confirmed",
    current_version: 1,
    map_status: "awaiting_validated_contributions",
  };
}

function fakeApi(overrides: Partial<ProblemApi> = {}): ProblemApi {
  return {
    create: vi.fn(),
    read: vi.fn(),
    answer: vi.fn(),
    confirm: vi.fn(),
    reopen: vi.fn(),
    evidenceMap: vi.fn().mockResolvedValue({
      problem_id: problemId,
      problem_version: 1,
      status: "no_validated_evidence",
      query_summary: "Formulação confirmada",
      items: [],
    }),
    ...overrides,
  };
}

function seedProblemSession(): void {
  sessionStorage.setItem(
    "observainova.problem-session.v1",
    JSON.stringify({ problemId, editToken }),
  );
}

it("starts with the public problem instead of a catalog", () => {
  render(<ProblemAssistant api={fakeApi()} />);

  expect(
    screen.getByRole("heading", {
      name: "Qual problema público você precisa enfrentar?",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("group", { name: "Descrição inicial do problema público" }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/lista de teses/i)).not.toBeInTheDocument();
});

it("lets the user answer unknown without invented text", async () => {
  seedProblemSession();
  const api = fakeApi({
    read: vi.fn().mockResolvedValue(stateWithNextQuestion("territory")),
    answer: vi
      .fn()
      .mockResolvedValue(stateWithNextQuestion("affected_population_or_service")),
  });
  const user = userEvent.setup();
  render(<ProblemAssistant api={api} />);
  await screen.findByText("Em qual território ou unidade administrativa isso acontece?");

  await user.click(screen.getByRole("button", { name: "Não sei informar" }));

  expect(api.answer).toHaveBeenCalledWith(problemId, editToken, {
    field: "territory",
    value: null,
    knowledge_status: "unknown",
  });
  expect(screen.queryByText(/território provável/i)).not.toBeInTheDocument();
});

it("reviews exact user wording before confirmation", async () => {
  seedProblemSession();
  const api = fakeApi({
    read: vi
      .fn()
      .mockResolvedValue(completeProblemState({ constraints: "Sem aumento de equipe" })),
  });
  render(<ProblemAssistant api={api} />);

  expect(await screen.findByText("Sem aumento de equipe")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Confirmar formulação" })).toBeEnabled();
});

it("never renders the private edit token", async () => {
  seedProblemSession();
  const api = fakeApi({
    read: vi.fn().mockResolvedValue(stateWithNextQuestion("territory")),
  });
  render(<ProblemAssistant api={api} />);

  await screen.findByText("Em qual território ou unidade administrativa isso acontece?");
  expect(document.body.textContent).not.toContain(editToken);
});

it("clears an invalid session after a 404", async () => {
  seedProblemSession();
  const api = fakeApi({
    read: vi.fn().mockRejectedValue(new ProblemApiError(404, { detail: "Problem not found" })),
  });
  render(<ProblemAssistant api={api} />);

  expect(
    await screen.findByRole("heading", {
      name: "Qual problema público você precisa enfrentar?",
    }),
  ).toBeInTheDocument();
  expect(sessionStorage.getItem("observainova.problem-session.v1")).toBeNull();
});

it("recovers a saved formulation after a temporary load failure", async () => {
  seedProblemSession();
  const read = vi
    .fn()
    .mockRejectedValueOnce(new ProblemApiError(503, { detail: "Unavailable" }))
    .mockResolvedValueOnce(stateWithNextQuestion("territory"));
  const user = userEvent.setup();
  render(<ProblemAssistant api={fakeApi({ read })} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(/não foi possível recuperar/i);
  await user.click(screen.getByRole("button", { name: "Tentar novamente" }));

  expect(
    await screen.findByText("Em qual território ou unidade administrativa isso acontece?"),
  ).toBeInTheDocument();
  expect(read).toHaveBeenCalledTimes(2);
});

it("preserves the typed answer and retries after a submission failure", async () => {
  seedProblemSession();
  const answer = vi
    .fn()
    .mockRejectedValueOnce(new ProblemApiError(503, { detail: "Unavailable" }))
    .mockResolvedValueOnce(stateWithNextQuestion("affected_population_or_service"));
  const api = fakeApi({
    read: vi.fn().mockResolvedValue(stateWithNextQuestion("territory")),
    answer,
  });
  const user = userEvent.setup();
  render(<ProblemAssistant api={api} />);
  const input = await screen.findByLabelText("Sua resposta");
  await user.type(input, "Caruaru");

  await user.click(screen.getByRole("button", { name: "Continuar" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/não foi possível/i);
  expect(input).toHaveValue("Caruaru");
  await user.click(screen.getByRole("button", { name: "Tentar novamente" }));
  expect(
    await screen.findByText("Qual população, serviço ou organização é mais afetado?"),
  ).toBeInTheDocument();
  expect(answer).toHaveBeenCalledTimes(2);
});

it("moves keyboard focus to the next assistant question", async () => {
  seedProblemSession();
  const api = fakeApi({
    read: vi.fn().mockResolvedValue(stateWithNextQuestion("territory")),
    answer: vi
      .fn()
      .mockResolvedValue(stateWithNextQuestion("affected_population_or_service")),
  });
  const user = userEvent.setup();
  render(<ProblemAssistant api={api} />);
  await screen.findByText("Em qual território ou unidade administrativa isso acontece?");
  await user.type(screen.getByLabelText("Sua resposta"), "Caruaru");

  await user.click(screen.getByRole("button", { name: "Continuar" }));

  const nextQuestion = await screen.findByText(
    "Qual população, serviço ou organização é mais afetado?",
  );
  await waitFor(() => expect(nextQuestion).toHaveFocus());
});

it("confirms the problem without fabricating solution paths", async () => {
  seedProblemSession();
  const api = fakeApi({
    read: vi
      .fn()
      .mockResolvedValue(completeProblemState({ constraints: "Sem aumento de equipe" })),
    confirm: vi.fn().mockResolvedValue(confirmedProblemState()),
  });
  const user = userEvent.setup();
  render(<ProblemAssistant api={api} />);
  await screen.findByText("Sem aumento de equipe");

  await user.click(screen.getByRole("button", { name: "Confirmar formulação" }));

  expect(
    await screen.findByRole("heading", { name: "Problema confirmado" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/somente com contribuições científicas validadas/i)).toBeInTheDocument();
  expect(screen.queryByText(/caminho recomendado/i)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Revisar formulação" })).not.toBeInTheDocument();
});

it("shows only validated scientific contributions related to the confirmed problem", async () => {
  seedProblemSession();
  const contributionId = "00000000-0000-4000-8000-000000000099";
  const api = fakeApi({
    read: vi.fn().mockResolvedValue(confirmedProblemState()),
    evidenceMap: vi.fn().mockResolvedValue({
      problem_id: problemId,
      problem_version: 1,
      status: "ready",
      query_summary: "Espera por consultas de cardiologia em Caruaru",
      items: [
        {
          scientific_contribution_id: contributionId,
          contribution_type: "method",
          description: "Método de regulação da fila de cardiologia",
          problem_or_phenomenon: "Espera por consultas de cardiologia",
          evidence_results: "Redução do tempo de espera",
          barriers_limitations: "Depende da qualidade dos dados da agenda",
          applicability: "Serviços públicos de regulação ambulatorial",
          institution: "UFPE",
          publication_year: 2024,
          source_scope: "full_text",
          match_score: 0.42,
          matched_terms: ["cardiologia", "consultas", "espera"],
          explanation:
            "Correspondência inicial com termos do problema confirmado: cardiologia, consultas, espera.",
        },
      ],
    }),
  });

  render(<ProblemAssistant api={api} />);

  expect(
    await screen.findByRole("heading", { name: "Contribuições científicas relacionadas" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Método de regulação da fila de cardiologia")).toBeInTheDocument();
  expect(screen.getByText("Redução do tempo de espera")).toBeInTheDocument();
  expect(screen.getByText(/depende da qualidade dos dados/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Examinar fundamento científico" })).toHaveAttribute(
    "href",
    `/contribuicoes/${contributionId}`,
  );
  expect(api.evidenceMap).toHaveBeenCalledWith(problemId, editToken);
});
