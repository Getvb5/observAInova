import { notFound } from "next/navigation";
import { ContributionDetail } from "@/components/contributions/ContributionDetail";
import { ContributionNotFoundError, createContributionApi } from "@/lib/contribution-api";

export default async function ContributionPage({ params }: { params: Promise<{ contributionId: string }> }) {
  const { contributionId } = await params;
  try { return <ContributionDetail contribution={await createContributionApi().get(contributionId)} />; }
  catch (error) { if (error instanceof ContributionNotFoundError) notFound(); throw error; }
}
