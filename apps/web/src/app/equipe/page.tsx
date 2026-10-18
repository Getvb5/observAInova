"use client";

import { OperationsDashboard } from "@/components/review/OperationsDashboard";
import { ReviewQueue } from "@/components/review/ReviewQueue";
import { SupervisionQueue } from "@/components/review/SupervisionQueue";
import { InternalAuthProvider, useInternalAuth } from "@/lib/internal-auth";

function Console() { const { api, signOut } = useInternalAuth(); return <div className="team-console"><header className="console-heading"><span className="eyebrow">Ambiente restrito</span><h1>Equipe central</h1><p>Curadoria humana, supervisão independente e rastreabilidade de cada contribuição científica.</p><button className="text-button" type="button" onClick={() => void signOut()}>Sair com segurança</button></header><OperationsDashboard api={api} /><ReviewQueue api={api} /><SupervisionQueue api={api} /></div>; }

export default function TeamPage() { return <InternalAuthProvider><Console /></InternalAuthProvider>; }
