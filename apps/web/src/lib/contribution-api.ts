export interface PublicContribution {
  id: string;
  scientific_contribution_id: string;
  contribution_version_id: string;
  production_id: string;
  version: number;
  contribution_type: string | null;
  scientific_values: Record<string, unknown>;
  approved_groundings: Array<{ text?: string; page?: number | null; quote?: string; page_number?: number | null; location?: string }>;
  institution: string | null;
  publication_year: number | null;
  source_scope: string | null;
  production_type: string | null;
  source_warning: string | null;
  validated_at?: string | null;
  published_at?: string | null;
  original_url?: string | null;
}

export interface ContributionApi { get(contributionId: string): Promise<PublicContribution> }

export function createContributionApi(): ContributionApi {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return { async get(contributionId) {
    const response = await fetch(`${baseUrl}/contributions/${encodeURIComponent(contributionId)}`, { next: { revalidate: 60 } });
    if (response.status === 404) throw new ContributionNotFoundError();
    if (!response.ok) throw new Error("Não foi possível carregar a contribuição científica.");
    return response.json() as Promise<PublicContribution>;
  } };
}

export class ContributionNotFoundError extends Error {}
