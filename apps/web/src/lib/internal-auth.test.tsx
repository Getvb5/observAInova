import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  auth: {} as Record<string, unknown>,
  provider: vi.fn((props: { children: ReactNode }) => props.children),
}));

vi.mock("react-oidc-context", () => ({
  AuthProvider: mocks.provider,
  useAuth: () => mocks.auth,
}));

import { InternalAuthProvider, useInternalAuth } from "./internal-auth";

function authenticatedState() {
  return {
    isLoading: false,
    isAuthenticated: true,
    activeNavigator: undefined,
    error: undefined,
    user: { access_token: "access-token" },
    signinRedirect: vi.fn().mockResolvedValue(undefined),
    signoutRedirect: vi.fn().mockResolvedValue(undefined),
    clearStaleState: vi.fn().mockResolvedValue(undefined),
  };
}

function SessionActions() {
  const { signOut } = useInternalAuth();
  return <button onClick={() => void signOut()}>Encerrar</button>;
}

describe("InternalAuthProvider", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_INTERNAL_AUTH_MODE", "oidc");
    vi.stubEnv("NEXT_PUBLIC_OIDC_AUTHORITY", "https://identity.example");
    vi.stubEnv("NEXT_PUBLIC_OIDC_CLIENT_ID", "observainova-web");
    mocks.auth = authenticatedState();
    mocks.provider.mockClear();
  });

  it("starts the authorization-code redirect for an anonymous session", async () => {
    mocks.auth = { ...authenticatedState(), isAuthenticated: false, user: null };
    render(<InternalAuthProvider><p>Conteúdo restrito</p></InternalAuthProvider>);

    expect(screen.queryByText("Conteúdo restrito")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/ambiente seguro/i);
    await waitFor(() => expect(mocks.auth.signinRedirect).toHaveBeenCalledTimes(1));
  });

  it("configures code flow with PKCE and session-scoped transaction state", () => {
    render(<InternalAuthProvider><p>Conteúdo restrito</p></InternalAuthProvider>);

    const props = mocks.provider.mock.calls[0][0] as Record<string, unknown>;
    expect(props.response_type).toBe("code");
    expect(props.disablePKCE).toBe(false);
    expect(props.userStore).toBeDefined();
    expect(props.stateStore).toBeDefined();
    expect(props.post_logout_redirect_uri).toBe(`${window.location.origin}/`);
  });

  it("shows a recoverable callback error and restarts sign-in", async () => {
    const user = userEvent.setup();
    const state = { ...authenticatedState(), isAuthenticated: false, user: null, error: new Error("state inválido") };
    mocks.auth = state;
    render(<InternalAuthProvider><p>Conteúdo restrito</p></InternalAuthProvider>);

    expect(screen.getByRole("alert")).toHaveTextContent("state inválido");
    await user.click(screen.getByRole("button", { name: /tentar novamente/i }));
    expect(state.clearStaleState).toHaveBeenCalledTimes(1);
    expect(state.signinRedirect).toHaveBeenCalledTimes(1);
  });

  it("exposes a real OIDC logout action to authenticated screens", async () => {
    const user = userEvent.setup();
    const state = authenticatedState();
    mocks.auth = state;
    render(<InternalAuthProvider><SessionActions /></InternalAuthProvider>);

    await user.click(screen.getByRole("button", { name: "Encerrar" }));
    expect(state.signoutRedirect).toHaveBeenCalledTimes(1);
  });
});
