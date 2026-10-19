import { buildBackendRequest } from "@/lib/backend-proxy";

describe("private backend proxy", () => {
  it("keeps the problem token and does not leak pilot Basic credentials", async () => {
    const incoming = new Request("https://pilot.example/api/v1/problems/abc", {
      method: "POST",
      headers: {
        Authorization: `Basic ${btoa("pilot:secret")}`,
        "Content-Type": "application/json",
        "X-Problem-Token": "private-problem-token",
      },
      body: JSON.stringify({ description: "Fila na saúde" }),
    });

    const outgoing = await buildBackendRequest(
      incoming,
      "http://api.railway.internal:8000",
      ["problems", "abc"],
    );

    expect(outgoing.url).toBe(
      "http://api.railway.internal:8000/api/v1/problems/abc",
    );
    expect(outgoing.headers.get("authorization")).toBeNull();
    expect(outgoing.headers.get("x-problem-token")).toBe("private-problem-token");
    expect(await outgoing.text()).toBe(JSON.stringify({ description: "Fila na saúde" }));
  });

  it("preserves an internal bearer token for the central team", async () => {
    const incoming = new Request("https://pilot.example/api/v1/internal/dashboard", {
      headers: { Authorization: "Bearer curator-token" },
    });

    const outgoing = await buildBackendRequest(
      incoming,
      "http://api.railway.internal:8000/",
      ["internal", "dashboard"],
    );

    expect(outgoing.headers.get("authorization")).toBe("Bearer curator-token");
  });
});
