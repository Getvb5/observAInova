import { isPilotAuthorized } from "@/lib/pilot-access";

describe("private pilot access", () => {
  it("accepts only the configured HTTP Basic credentials", () => {
    const header = `Basic ${btoa("observainova:segredo-forte")}`;

    expect(
      isPilotAuthorized(header, "observainova", "segredo-forte"),
    ).toBe(true);
    expect(isPilotAuthorized(header, "observainova", "outra-senha")).toBe(false);
  });

  it("rejects absent, malformed, and bearer credentials", () => {
    expect(isPilotAuthorized(null, "observainova", "segredo-forte")).toBe(false);
    expect(isPilotAuthorized("Bearer token", "observainova", "segredo-forte")).toBe(
      false,
    );
    expect(isPilotAuthorized("Basic !!!", "observainova", "segredo-forte")).toBe(
      false,
    );
  });
});
