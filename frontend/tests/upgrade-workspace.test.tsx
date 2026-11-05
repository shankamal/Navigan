import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { UpgradeWorkspace } from "../src/modules/upgrade-management/upgrade-workspace";

describe("Upgrade workspace", () => {
  it("presents the approved readiness workspace without live execution claims", () => {
    render(<UpgradeWorkspace />);

    expect(
      screen.getByRole("heading", { name: "Upgrades & Patching" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Experience preview.")).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /Upgrade Centre/i }),
    ).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByText("payments-prod-eu")).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: /Refresh inventory/i }),
    ).toBeDisabled();
  });

  it("uses the approved workspace names", () => {
    render(<UpgradeWorkspace />);

    for (const label of [
      "Upgrade Centre",
      "Container Upgrades",
      "System Utilities",
      "Maintenance Schedule",
      "Plans & History",
    ]) {
      expect(
        screen.getByRole("tab", { name: new RegExp(label, "i") }),
      ).toBeInTheDocument();
    }
    expect(
      screen.queryByText("Upgrade Command Centre"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Calendar & Campaigns")).not.toBeInTheDocument();
    expect(screen.queryByText("Upgrade Overview")).not.toBeInTheDocument();
    expect(screen.queryByText("Upgrade Readiness")).not.toBeInTheDocument();
  });

  it("opens and navigates the guided upgrade plan", () => {
    render(<UpgradeWorkspace />);

    fireEvent.click(
      screen.getByRole("button", { name: "Create upgrade plan" }),
    );
    expect(
      screen.getByRole("heading", { name: "Create upgrade plan" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Confirm upgrade scope" }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /Continue to target version/i }),
    );
    expect(
      screen.getByRole("heading", { name: "Select a supported target" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: /Continue to 1.35/i }),
    ).toBeChecked();

    fireEvent.click(
      screen.getByRole("button", { name: /Continue to readiness/i }),
    );
    expect(
      screen.getByRole("heading", { name: "Review readiness evidence" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Blocked")).toHaveLength(2);
  });

  it("opens supporting capability tabs without exposing cloud actions", () => {
    render(<UpgradeWorkspace />);

    fireEvent.click(screen.getByRole("tab", { name: /System Utilities/i }));
    expect(
      screen.getByRole("heading", { name: "System utility upgrades" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Upgrade now/i }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Maintenance Schedule/i }));
    const section = screen
      .getByRole("heading", { name: "Maintenance schedule" })
      .closest("section");
    expect(section).not.toBeNull();
    expect(
      within(section!).getByText(/sandbox, non-production and production/i),
    ).toBeInTheDocument();
  });
});
