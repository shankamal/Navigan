import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PageHeading } from "@/shared/components/ui";
import { WorkspaceHeading } from "@/shared/components/workspace-heading";
import {
  WorkspacePageProvider,
  useWorkspacePage,
} from "@/shared/components/workspace-page-context";
function Host() {
  const { setHeaderTarget } = useWorkspacePage();
  return (
    <header aria-label="Capability header">
      <nav aria-label="Breadcrumb">Home / Environments</nav>
      <div ref={setHeaderTarget} />
    </header>
  );
}
describe("Shared capability header", () => {
  it("merges the page title/actions into the shell header and preserves action handlers", () => {
    const action = vi.fn();
    render(
      <WorkspacePageProvider>
        <Host />
        <main>
          <PageHeading
            title="Environment Management"
            description="Reusable environments"
            action={<button onClick={action}>Refresh environments</button>}
          />
        </main>
      </WorkspacePageProvider>,
    );
    const header = screen.getByRole("banner", { name: "Capability header" });
    expect(
      within(header).getByRole("navigation", { name: "Breadcrumb" }),
    ).toBeInTheDocument();
    expect(
      within(header).getByRole("heading", { name: "Environment Management" }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("main")).queryByRole("heading"),
    ).not.toBeInTheDocument();
    fireEvent.click(
      within(header).getByRole("button", { name: "Refresh environments" }),
    );
    expect(action).toHaveBeenCalledOnce();
  });
  it("supports custom planner headings without leaving a duplicate in page content", () => {
    render(
      <WorkspacePageProvider>
        <Host />
        <main>
          <WorkspaceHeading>
            <header>
              <h2>Create Upgrade Plan</h2>
            </header>
          </WorkspaceHeading>
        </main>
      </WorkspacePageProvider>,
    );
    expect(
      within(
        screen.getByRole("banner", { name: "Capability header" }),
      ).getByRole("heading", { name: "Create Upgrade Plan" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("heading", { name: "Create Upgrade Plan" }),
    ).toHaveLength(1);
  });
  it("cleans up the previous title when the active capability changes", () => {
    function View({ title }: { title: string }) {
      return (
        <WorkspacePageProvider>
          <Host />
          <PageHeading key={title} title={title} />
        </WorkspacePageProvider>
      );
    }
    const { rerender } = render(<View title="Customers" />);
    rerender(<View title="Migrations" />);
    expect(
      screen.queryByRole("heading", { name: "Customers" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Migrations" }),
    ).toBeInTheDocument();
  });
  it("still renders standalone headings without a shell provider", () => {
    render(<PageHeading title="Standalone heading" />);
    expect(
      screen.getByRole("heading", { name: "Standalone heading" }),
    ).toBeInTheDocument();
  });
});
