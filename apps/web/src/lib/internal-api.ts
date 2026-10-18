export type FieldDecisionAction = "accept" | "correct" | "reject" | "insufficient";
export type PublicationAction = "return" | "publish" | "supersede" | "revoke";

export interface ReviewAssignmentDetail {
  id: string;
  reviewCaseId: string;
  lane: "single" | "primary" | "secondary" | "adjudication";
}

export interface Grounding {
  id: string;
  text: string;
  page: number | null;
}

export interface CandidateField {
  name: string;
  label: string;
  value: string;
  confidence: number;
  groundingIds: string[];
}

export interface ReviewCaseDetail {
  id: string;
  kind: "candidate" | "return_correction";
  correctionReason?: string | null;
  correctionBaseVersionId?: string | null;
  draftVersion?: number | null;
  sourceTitle: string;
  sourceKind: "full_text" | "abstract";
  sourceText: string;
  fields: CandidateField[];
  groundings: Grounding[];
}

export interface AdjudicationContext {
  reviews: Array<{
    review: number;
    fields: Array<{
      name: string;
      action: FieldDecisionAction;
      value?: string | null;
      reason?: string | null;
      groundingIds: string[];
    }>;
  }>;
  disagreements: string[];
}

export interface SupervisionDetail {
  id: string;
  version: number;
  validatedBy: string[];
  currentActor: string;
  scientificValues: Record<string, unknown>;
  approvedGroundings: Array<{ text: string; page: number | null }>;
  status: string;
  sourceWarning?: string | null;
}

export interface InternalApi {
  dashboard(): Promise<Record<string, unknown>>;
  reviewQueue(): Promise<{ items: Array<Record<string, unknown>>; total: number }>;
  claimReview(): Promise<ReviewAssignmentDetail>;
  reviewAssignment(id: string): Promise<{ reviewCase: ReviewCaseDetail; assignment: ReviewAssignmentDetail; adjudicationContext?: AdjudicationContext }>;
  completeAssignment(id: string): Promise<unknown>;
  materializeCase(id: string): Promise<unknown>;
  publicationQueue(): Promise<{ items: Array<{ id: string; version: number; status: string }>; total: number }>;
  supervisionDetail(id: string): Promise<SupervisionDetail>;
  decideField(assignmentId: string, body: {
    field: string;
    action: FieldDecisionAction;
    value?: string;
    grounding_ids: string[];
    reason?: string;
  }): Promise<unknown>;
  decidePublication(versionId: string, body: { action: PublicationAction; reason?: string }): Promise<unknown>;
}

export function createInternalApi(getToken: () => string | undefined): InternalApi {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const token = getToken();
    if (!token) throw new Error("Sessão interna ausente ou expirada.");
    const response = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...init?.headers },
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => null) as { detail?: unknown } | null;
      throw new Error(typeof detail?.detail === "string" ? detail.detail : `Falha na operação (${response.status}).`);
    }
    return response.json() as Promise<T>;
  }
  return {
    dashboard: () => request("/internal/dashboard"),
    reviewQueue: () => request("/internal/review-queue"),
    claimReview: async () => mapAssignment(await request<RawAssignment>("/internal/review-queue/claim", { method: "POST" })),
    reviewAssignment: async (id) => {
      const response = await request<{ assignment: RawAssignment; review_case: RawReviewCase; adjudication_context?: RawAdjudicationContext }>(`/internal/review-assignments/${id}`);
      return { assignment: mapAssignment(response.assignment), reviewCase: mapReviewCase(response.review_case), adjudicationContext: response.adjudication_context ? mapAdjudicationContext(response.adjudication_context) : undefined };
    },
    completeAssignment: (id) => request(`/internal/review-assignments/${id}/complete`, { method: "POST" }),
    materializeCase: (id) => request(`/internal/review-cases/${id}/materialize`, { method: "POST" }),
    publicationQueue: () => request("/internal/publication-queue"),
    supervisionDetail: async (id) => mapSupervision(await request<RawSupervision>(`/internal/contribution-versions/${id}`)),
    decideField: (id, body) => request(`/internal/review-assignments/${id}/field-decisions`, { method: "POST", body: JSON.stringify(body) }),
    decidePublication: (id, body) => request(`/internal/contribution-versions/${id}/publication-decisions`, { method: "POST", body: JSON.stringify(body) }),
  };
}

interface RawAssignment { id: string; review_case_id: string; lane: ReviewAssignmentDetail["lane"] }
interface RawReviewCase {
  id: string; kind: "candidate" | "return_correction"; correction_reason?: string | null; correction_base_version_id?: string | null; draft_version?: number | null;
  source_title: string; source_kind: "full_text" | "abstract_only"; source_text: string;
  fields: Array<{ name: string; label: string; value: string; confidence: number; grounding_ids: string[] }>;
  groundings: Grounding[];
}
interface RawAdjudicationContext {
  reviews: Array<{ review: number; fields: Array<{ name: string; action: FieldDecisionAction; value?: string | null; reason?: string | null; grounding_ids: string[] }> }>;
  disagreements: string[];
}
interface RawSupervision {
  id: string; version: number; validated_by: string[]; current_actor: string;
  scientific_values: Record<string, unknown>; approved_groundings: Array<{ text: string; page: number | null }>;
  status: string; source_warning?: string | null;
}
function mapAssignment(item: RawAssignment): ReviewAssignmentDetail { return { id: item.id, reviewCaseId: item.review_case_id, lane: item.lane }; }
function mapReviewCase(item: RawReviewCase): ReviewCaseDetail { return { id: item.id, kind: item.kind, correctionReason: item.correction_reason, correctionBaseVersionId: item.correction_base_version_id, draftVersion: item.draft_version, sourceTitle: item.source_title, sourceKind: item.source_kind === "full_text" ? "full_text" : "abstract", sourceText: item.source_text, fields: item.fields.map((field) => ({ ...field, groundingIds: field.grounding_ids })), groundings: item.groundings }; }
function mapAdjudicationContext(item: RawAdjudicationContext): AdjudicationContext { return { reviews: item.reviews.map((review) => ({ ...review, fields: review.fields.map((field) => ({ ...field, groundingIds: field.grounding_ids })) })), disagreements: item.disagreements }; }
function mapSupervision(item: RawSupervision): SupervisionDetail { return { id: item.id, version: item.version, validatedBy: item.validated_by, currentActor: item.current_actor, scientificValues: item.scientific_values, approvedGroundings: item.approved_groundings, status: item.status, sourceWarning: item.source_warning }; }
