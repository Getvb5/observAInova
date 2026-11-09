import type { SearchRequest } from "@/lib/search-api";

export interface AnswerStatement {
  text: string;
  basis: "finding" | "inference";
  citations: { excerpt_id: string; quote: string }[];
}
export interface AnswerSource {
  id: string;
  production_id: string;
  production_version_id: string;
  text_version_id: string | null;
  title: string;
  authors: string[];
  year: number | null;
  url: string | null;
  reading_scope: "abstract_only" | "full_text_excerpts";
  excerpts: { id: string; text: string; page: number | null }[];
}
export interface ResearchAnswerData {
  query: string;
  status: "ready" | "insufficient_evidence" | "unavailable";
  message: string;
  total_matches: number;
  sources: AnswerSource[];
  validation_status: "automated_unreviewed";
  analysis: {
    outcome: "supported_in_study" | "conditional" | "insufficient";
    context: AnswerStatement[];
    feasibility: AnswerStatement[];
    pathways: AnswerStatement[];
    potentials: AnswerStatement[];
    limitations: AnswerStatement[];
  } | null;
}
export function answerParameters(request: SearchRequest): string {
  return JSON.stringify({ q: request.q,
    ...(request.institution ? { institution: request.institution } : {}),
    ...(request.type ? { type: request.type } : {}),
    ...(request.publication_year ? { publication_year: Number(request.publication_year) } : {}),
  });
}
export async function getResearchAnswer(body: string, signal: AbortSignal): Promise<ResearchAnswerData> {
  const response = await fetch("/api/v1/answers", {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
    body, signal, cache: "no-store",
  });
  if (!response.ok) throw new Error("answer_unavailable");
  const answer = await response.json() as ResearchAnswerData;
  if (!["ready", "insufficient_evidence", "unavailable"].includes(answer.status)) throw new Error("answer_invalid");
  return answer;
}
