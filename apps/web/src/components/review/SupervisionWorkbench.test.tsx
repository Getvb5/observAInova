import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { SupervisionWorkbench } from "./SupervisionWorkbench";

const version = {
  id: "version-1",
  version: 1,
  validatedBy: ["person-1"],
  currentActor: "person-1",
  scientificValues: { problema_publico: "Falta de medicamentos" },
  approvedGroundings: [{ text: "reduzir faltas", page: 42 }],
  status: "validated",
};

it("prevents every self-supervision action in the interface and explains the rule", () => {
  render(<SupervisionWorkbench version={version} api={{ decidePublication: vi.fn() } as never} />);
  expect(screen.getByRole("button", { name: "Publicar contribuição" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Devolver à curadoria" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Publicar como substituição" })).toBeDisabled();
  expect(screen.getByText(/outra pessoa deve tomar qualquer decisão/i)).toBeVisible();
});

it("offers only revocation when a warned contribution is already published", () => {
  render(<SupervisionWorkbench version={{ ...version, status: "published", currentActor: "person-2", sourceWarning: "Fonte atualizada" }} api={{ decidePublication: vi.fn() } as never} />);
  expect(screen.getByText("Fonte atualizada")).toBeVisible();
  expect(screen.getByRole("button", { name: "Revogar publicação" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Publicar contribuição" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Devolver à curadoria" })).not.toBeInTheDocument();
});

it("requires a reason before returning a contribution", async () => {
  const user = userEvent.setup();
  render(<SupervisionWorkbench version={{ ...version, currentActor: "person-2" }} api={{ decidePublication: vi.fn() } as never} />);
  await user.click(screen.getByRole("button", { name: "Devolver à curadoria" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/informe o motivo/i);
});
