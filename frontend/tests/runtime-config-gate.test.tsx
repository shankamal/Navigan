import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { RuntimeConfigGate } from "@/shared/config/runtime-config-gate";

const load = vi.hoisted(() => vi.fn());
vi.mock("@/shared/config/runtime-config", () => ({ loadRuntimeConfig: load }));
beforeEach(() => load.mockReset());

it("does not mount session-dependent content before configuration is ready", async () => {
  let resolve!: () => void;
  load.mockReturnValue(
    new Promise<void>((done) => {
      resolve = done;
    }),
  );
  render(
    <RuntimeConfigGate>
      <div>Authenticated application</div>
    </RuntimeConfigGate>,
  );
  expect(
    screen.queryByText("Authenticated application"),
  ).not.toBeInTheDocument();
  await act(async () => {
    resolve();
  });
  expect(screen.getByText("Authenticated application")).toBeInTheDocument();
});

it("shows a retry after bootstrap failure and never bypasses the configuration gate", async () => {
  load.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({});
  render(
    <RuntimeConfigGate>
      <div>Application content</div>
    </RuntimeConfigGate>,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Unable to load application settings",
  );
  expect(screen.queryByText("Application content")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("Application content")).toBeInTheDocument();
});
