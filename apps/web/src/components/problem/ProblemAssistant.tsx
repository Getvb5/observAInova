"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { ProblemHandoff } from "@/components/problem/ProblemHandoff";
import { ProblemReview } from "@/components/problem/ProblemReview";
import {
  type AnswerProblemRequest,
  type ProblemApi,
  ProblemApiError,
  type ProblemState,
  problemApi,
} from "@/lib/problem-api";

const SESSION_KEY = "observainova.problem-session.v1";

interface ProblemSession {
  problemId: string;
  editToken: string;
}

interface ProblemAssistantProps {
  api?: ProblemApi;
}

type PendingAction =
  | { kind: "read" }
  | { kind: "create"; description: string }
  | { kind: "answer"; answer: AnswerProblemRequest }
  | { kind: "confirm" };

function loadSession(): ProblemSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ProblemSession>;
    if (typeof parsed.problemId !== "string" || typeof parsed.editToken !== "string") {
      sessionStorage.removeItem(SESSION_KEY);
      return null;
    }
    return { problemId: parsed.problemId, editToken: parsed.editToken };
  } catch {
    sessionStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export function ProblemAssistant({ api = problemApi }: ProblemAssistantProps) {
  const [session, setSession] = useState<ProblemSession | null>(null);
  const [state, setState] = useState<ProblemState | null>(null);
  const [description, setDescription] = useState("");
  const [answer, setAnswer] = useState("");
  const [loadingSession, setLoadingSession] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const questionRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const stored = loadSession();
    if (!stored) {
      setLoadingSession(false);
      return;
    }

    setSession(stored);
    api
      .read(stored.problemId, stored.editToken)
      .then(setState)
      .catch((reason: unknown) => {
        if (reason instanceof ProblemApiError && reason.status === 404) {
          sessionStorage.removeItem(SESSION_KEY);
          setSession(null);
          return;
        }
        setPendingAction({ kind: "read" });
        setError("Não foi possível recuperar esta formulação agora. Tente novamente.");
      })
      .finally(() => setLoadingSession(false));
  }, [api]);

  useEffect(() => {
    if (state?.next_question) {
      questionRef.current?.focus();
    }
  }, [state?.next_question]);

  async function perform(action: PendingAction): Promise<void> {
    setBusy(true);
    setError(null);
    setPendingAction(action);
    try {
      if (action.kind === "create") {
        const created = await api.create(action.description);
        const createdSession = {
          problemId: created.problem_id,
          editToken: created.edit_token,
        };
        sessionStorage.setItem(SESSION_KEY, JSON.stringify(createdSession));
        setSession(createdSession);
        setState(created.state);
        setDescription("");
      } else {
        if (!session) throw new Error("Missing problem session");
        const nextState =
          action.kind === "read"
            ? await api.read(session.problemId, session.editToken)
            : action.kind === "answer"
            ? await api.answer(session.problemId, session.editToken, action.answer)
            : await api.confirm(session.problemId, session.editToken);
        setState(nextState);
        if (action.kind === "answer") setAnswer("");
      }
      setPendingAction(null);
    } catch {
      setError("Não foi possível concluir esta etapa. Sua resposta foi preservada.");
    } finally {
      setBusy(false);
    }
  }

  function submitDescription(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const value = description.trim();
    if (value) void perform({ kind: "create", description: value });
  }

  function submitAnswer(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!state?.next_question || !answer.trim()) return;
    const field = state.next_question.field;
    void perform({
      kind: "answer",
      answer: {
        field,
        value: answer.trim(),
        knowledge_status: field === "perceived_causes" ? "perception" : "reported_fact",
      },
    });
  }

  function answerUnknown(): void {
    if (!state?.next_question) return;
    void perform({
      kind: "answer",
      answer: {
        field: state.next_question.field,
        value: null,
        knowledge_status: "unknown",
      },
    });
  }

  if (loadingSession) {
    return (
      <section className="panel loading-panel" aria-live="polite">
        <span className="loading-dot" aria-hidden="true" />
        Recuperando sua formulação…
      </section>
    );
  }

  if (state?.status === "confirmed") {
    if (!session) return null;
    return <ProblemHandoff api={api} problemId={session.problemId} editToken={session.editToken} />;
  }

  if (state?.ready_to_confirm) {
    return (
      <>
        <ProblemReview state={state} busy={busy} onConfirm={() => void perform({ kind: "confirm" })} />
        {error ? (
          <div className="error-box" role="alert">
            <p>{error}</p>
            <button type="button" onClick={() => pendingAction && void perform(pendingAction)}>
              Tentar novamente
            </button>
          </div>
        ) : null}
      </>
    );
  }

  if (!state) {
    return (
      <section className="hero" aria-labelledby="start-title">
        <div className="hero__content">
          <p className="eyebrow">Ciência orientada por problemas públicos</p>
          <h1 id="start-title">Qual problema público você precisa enfrentar?</h1>
          <p className="hero__support">
            Descreva a situação com suas palavras. Vamos organizar o contexto antes de
            buscar caminhos fundamentados na produção científica.
          </p>
          <form className="start-form" onSubmit={submitDescription}>
            <fieldset disabled={busy}>
              <legend className="sr-only">Descrição inicial do problema público</legend>
              <label htmlFor="problem-description">Descreva o problema público</label>
              <textarea
                id="problem-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={5}
                maxLength={5000}
                placeholder="Ex.: A população espera muitos meses por consultas especializadas…"
                required
              />
              <button className="primary-button" type="submit" disabled={!description.trim()}>
                {busy ? "Iniciando…" : "Começar"}
              </button>
            </fieldset>
          </form>
          {error ? (
            <div className="error-box" role="alert">
              <p>{error}</p>
              <button type="button" onClick={() => pendingAction && void perform(pendingAction)}>
                Tentar novamente
              </button>
            </div>
          ) : null}
        </div>
        <aside className="method-card" aria-label="Como a formulação funciona">
          <span className="method-card__index">01</span>
          <h2>Primeiro, compreender</h2>
          <p>
            O assistente registra contexto, consequências, percepções e limites sem
            completar lacunas por conta própria.
          </p>
          <ul>
            <li>Seu texto permanece fiel</li>
            <li>Incertezas ficam explícitas</li>
            <li>Você confirma antes do mapeamento</li>
          </ul>
        </aside>
      </section>
    );
  }

  const question = state.next_question;
  if (!question) return null;

  return (
    <section className="panel question-panel" aria-labelledby="question-title">
      <div className="progress-row">
        <span className="eyebrow">Compreendendo o contexto</span>
        <span>{8 - state.missing_fields.length + 1} de 8</span>
      </div>
      <div className="progress-track" aria-hidden="true">
        <span style={{ width: `${((9 - state.missing_fields.length) / 8) * 100}%` }} />
      </div>
      <h1 id="question-title" ref={questionRef} tabIndex={-1}>
        {question.prompt}
      </h1>
      <p className="question-context">Problema relatado: “{state.description}”</p>
      <form className="answer-form" onSubmit={submitAnswer}>
        <fieldset disabled={busy}>
          <legend className="sr-only">Resposta à pergunta atual</legend>
          <label htmlFor="problem-answer">Sua resposta</label>
          <textarea
            id="problem-answer"
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            rows={4}
            maxLength={5000}
            autoFocus
          />
          <div className="button-row">
            <button className="primary-button" type="submit" disabled={!answer.trim()}>
              {busy ? "Registrando…" : "Continuar"}
            </button>
            {question.accepts_unknown ? (
              <button className="text-button" type="button" onClick={answerUnknown}>
                Não sei informar
              </button>
            ) : null}
          </div>
        </fieldset>
      </form>
      <div aria-live="polite">
        {error ? (
          <div className="error-box" role="alert">
            <p>{error}</p>
            <button type="button" onClick={() => pendingAction && void perform(pendingAction)}>
              Tentar novamente
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
