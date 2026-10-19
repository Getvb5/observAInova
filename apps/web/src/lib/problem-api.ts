export const PROBLEM_FIELDS = [
  "territory",
  "affected_population_or_service",
  "observed_consequences",
  "perceived_causes",
  "attempted_actions",
  "available_resources",
  "constraints",
  "desired_outcome",
] as const;

export type ProblemField = (typeof PROBLEM_FIELDS)[number];
export type KnowledgeStatus = "reported_fact" | "perception" | "unknown";
export type ProblemStatus = "draft" | "confirmed";

export interface ProblemAnswer {
  value: string | null;
  knowledge_status: KnowledgeStatus;
}

export interface ProblemState {
  problem_id: string;
  status: ProblemStatus;
  description: string;
  fields: Record<ProblemField, ProblemAnswer | null>;
  next_question: {
    field: ProblemField;
    prompt: string;
    accepts_unknown: boolean;
  } | null;
  missing_fields: ProblemField[];
  ready_to_confirm: boolean;
  current_version: number;
  structured_summary: string | null;
  map_status: "not_ready" | "awaiting_validated_contributions";
}

export interface CreateProblemResponse {
  problem_id: string;
  edit_token: string;
  state: ProblemState;
}

export interface AnswerProblemRequest {
  field: ProblemField;
  value: string | null;
  knowledge_status: KnowledgeStatus;
}

export interface ProblemEvidenceMapItem {
  scientific_contribution_id: string;
  contribution_type: string | null;
  description: string | null;
  problem_or_phenomenon: string | null;
  evidence_results: string | null;
  barriers_limitations: string | null;
  applicability: string | null;
  institution: string | null;
  publication_year: number | null;
  source_scope: string | null;
  match_score: number;
  matched_terms: string[];
  explanation: string;
}

export interface ProblemEvidenceMap {
  problem_id: string;
  problem_version: number;
  status: "ready" | "no_validated_evidence";
  query_summary: string;
  items: ProblemEvidenceMapItem[];
}

export interface ProblemApi {
  create(description: string): Promise<CreateProblemResponse>;
  read(problemId: string, editToken: string): Promise<ProblemState>;
  answer(
    problemId: string,
    editToken: string,
    request: AnswerProblemRequest,
  ): Promise<ProblemState>;
  confirm(problemId: string, editToken: string): Promise<ProblemState>;
  reopen(problemId: string, editToken: string): Promise<ProblemState>;
  evidenceMap(problemId: string, editToken: string): Promise<ProblemEvidenceMap>;
}

export class ProblemApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`Problem API request failed with status ${status}`);
    this.name = "ProblemApiError";
  }
}

const configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
const baseUrl =
  configuredBaseUrl ??
  (process.env.NODE_ENV === "development" ? "http://localhost:8000/api/v1" : "/api/v1");

async function request<T>(
  path: string,
  options: RequestInit = {},
  editToken?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (editToken) {
    headers.set("X-Problem-Token", editToken);
  }

  const response = await fetch(`${baseUrl}${path}`, { ...options, headers });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ProblemApiError(response.status, body);
  }
  return body as T;
}

export const problemApi: ProblemApi = {
  create(description) {
    return request<CreateProblemResponse>("/problems", {
      method: "POST",
      body: JSON.stringify({ description }),
    });
  },
  read(problemId, editToken) {
    return request<ProblemState>(`/problems/${problemId}`, {}, editToken);
  },
  answer(problemId, editToken, answer) {
    return request<ProblemState>(
      `/problems/${problemId}/answers`,
      { method: "POST", body: JSON.stringify(answer) },
      editToken,
    );
  },
  confirm(problemId, editToken) {
    return request<ProblemState>(
      `/problems/${problemId}/confirm`,
      { method: "POST" },
      editToken,
    );
  },
  reopen(problemId, editToken) {
    return request<ProblemState>(
      `/problems/${problemId}/revisions`,
      { method: "POST" },
      editToken,
    );
  },
  evidenceMap(problemId, editToken) {
    return request<ProblemEvidenceMap>(
      `/problems/${problemId}/evidence-map`,
      {},
      editToken,
    );
  },
};
