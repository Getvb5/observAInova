import type { PublicContribution } from "@/lib/contribution-api";

export interface SearchRequest {
  q: string;
  institution: string;
  type: string;
  publication_year: string;
  sort: "relevance" | "recent";
  page: number;
}

export interface SearchResult {
  id: string;
  title: string;
  abstract: string | null;
  publication_year: number | null;
  type: string | null;
  authors: string[];
  institutions: string[];
  keywords: string[];
  source: { name: string | null; source_url: string | null; access_status: string };
  matched_terms: string[];
  validated_contributions: PublicContribution[];
}

export interface SearchPage {
  query: string;
  items: SearchResult[];
  total: number;
  page: number;
  page_size: number;
  facets: { institutions: string[]; years: number[] };
}

export function searchParameters(request: SearchRequest): URLSearchParams {
  const params = new URLSearchParams({ q: request.q, page: String(request.page) });
  for (const field of ["institution", "type", "publication_year"] as const) {
    if (request[field]) params.set(field, request[field]);
  }
  if (request.sort !== "relevance") params.set("sort", request.sort);
  return params;
}

export async function searchProductions(request: SearchRequest, signal: AbortSignal): Promise<SearchPage> {
  const response = await fetch(`/api/v1/productions/search?${searchParameters(request)}`, {
    signal, headers: { Accept: "application/json" }, cache: "no-store",
  });
  if (!response.ok) {
    if (response.status === 422) throw new Error("Use uma expressão com termos relevantes, como ‘segurança do paciente’.");
    throw new Error("Não foi possível realizar a busca agora. Tente novamente.");
  }
  return response.json() as Promise<SearchPage>;
}
