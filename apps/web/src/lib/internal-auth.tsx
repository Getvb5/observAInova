"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AuthProvider, useAuth } from "react-oidc-context";
import { WebStorageStateStore } from "oidc-client-ts";

import { createInternalApi, type InternalApi } from "./internal-api";

interface InternalAuthContextValue {
  api: InternalApi;
  signOut(): Promise<void>;
}

const InternalAuthContext = createContext<InternalAuthContextValue | null>(null);

function OidcSessionGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const redirectStarted = useRef(false);
  const [redirectError, setRedirectError] = useState("");
  const api = useMemo(() => createInternalApi(() => auth.user?.access_token), [auth.user?.access_token]);

  useEffect(() => {
    if (auth.isAuthenticated) redirectStarted.current = false;
    if (auth.isLoading || auth.isAuthenticated || auth.activeNavigator || auth.error || redirectStarted.current) return;
    redirectStarted.current = true;
    void auth.signinRedirect().catch((cause: unknown) => {
      redirectStarted.current = false;
      setRedirectError(cause instanceof Error ? cause.message : "Não foi possível iniciar a autenticação.");
    });
  }, [auth]);

  async function retry() {
    setRedirectError("");
    redirectStarted.current = true;
    try {
      await auth.clearStaleState();
      await auth.signinRedirect();
    } catch (cause) {
      redirectStarted.current = false;
      setRedirectError(cause instanceof Error ? cause.message : "Não foi possível reiniciar a autenticação.");
    }
  }

  if (auth.error || redirectError) {
    return <section className="workbench" aria-labelledby="auth-error-title"><h1 id="auth-error-title">Não foi possível entrar</h1><p role="alert" className="error-box">{redirectError || auth.error?.message}</p><button className="primary-button" type="button" onClick={retry}>Tentar novamente</button></section>;
  }
  if (auth.isLoading || auth.activeNavigator || !auth.isAuthenticated || !auth.user?.access_token) {
    return <p role="status" className="muted">Acessando o ambiente seguro…</p>;
  }
  const value: InternalAuthContextValue = {
    api,
    signOut: async () => { await auth.signoutRedirect(); },
  };
  return <InternalAuthContext.Provider value={value}>{children}</InternalAuthContext.Provider>;
}

function LocalSessionBridge({ children }: { children: ReactNode }) {
  const api = useMemo(
    () => createInternalApi(() => typeof window === "undefined" ? undefined : window.sessionStorage.getItem("observainova.local_token") ?? undefined),
    [],
  );
  const value = useMemo<InternalAuthContextValue>(() => ({
    api,
    signOut: async () => {
      window.sessionStorage.removeItem("observainova.local_token");
      window.location.assign("/");
    },
  }), [api]);
  return <InternalAuthContext.Provider value={value}>{children}</InternalAuthContext.Provider>;
}

export function InternalAuthProvider({ children }: { children: ReactNode }) {
  const local = process.env.NEXT_PUBLIC_INTERNAL_AUTH_MODE === "local";
  if (local && process.env.NODE_ENV !== "development" && process.env.NODE_ENV !== "test") {
    throw new Error("O modo de autenticação local não pode ser usado em produção.");
  }
  if (local) return <LocalSessionBridge>{children}</LocalSessionBridge>;

  const authority = process.env.NEXT_PUBLIC_OIDC_AUTHORITY?.trim();
  const clientId = process.env.NEXT_PUBLIC_OIDC_CLIENT_ID?.trim();
  if (!authority || !clientId) {
    return <section className="workbench"><h1>Autenticação não configurada</h1><p role="alert" className="error-box">Defina a autoridade e o cliente OIDC do ambiente interno.</p></section>;
  }
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const sessionStore = typeof window === "undefined" ? undefined : new WebStorageStateStore({ store: window.sessionStorage });
  return (
    <AuthProvider
      authority={authority}
      client_id={clientId}
      redirect_uri={`${origin}/equipe`}
      post_logout_redirect_uri={`${origin}/`}
      response_type="code"
      scope={process.env.NEXT_PUBLIC_OIDC_SCOPE ?? "openid profile email"}
      disablePKCE={false}
      automaticSilentRenew
      userStore={sessionStore}
      stateStore={sessionStore}
      onSigninCallback={() => window.history.replaceState({}, document.title, "/equipe")}
      matchSignoutCallback={(args) => window.location.href.startsWith(args.post_logout_redirect_uri ?? `${origin}/`)}
      onSignoutCallback={() => window.location.assign("/")}
    >
      <OidcSessionGate>{children}</OidcSessionGate>
    </AuthProvider>
  );
}

export function useInternalAuth(): InternalAuthContextValue {
  const value = useContext(InternalAuthContext);
  if (!value) throw new Error("InternalAuthProvider ausente.");
  return value;
}

export function useInternalApi(): InternalApi {
  return useInternalAuth().api;
}
