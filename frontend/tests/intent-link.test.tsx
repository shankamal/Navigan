import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { IntentLink } from "@/shared/components/intent-link";

vi.mock("next/link", () => ({
  default: ({
    prefetch,
    ...props
  }: ComponentProps<"a"> & { prefetch?: boolean | null }) => (
    <a {...props} data-prefetch={prefetch === false ? "off" : "automatic"} />
  ),
}));

describe("Navigation prefetch intent", () => {
  it.each(["mouseEnter", "focus", "touchStart"] as const)(
    "waits for %s before enabling prefetch",
    (event) => {
      const handler = vi.fn();
      render(
        <IntentLink
          href="/migrations"
          onMouseEnter={handler}
          onFocus={handler}
          onTouchStart={handler}
        >
          Migrations
        </IntentLink>,
      );
      const link = screen.getByRole("link", { name: "Migrations" });
      expect(link).toHaveAttribute("href", "/migrations");
      expect(link).toHaveAttribute("data-prefetch", "off");
      fireEvent[event](link);
      expect(link).toHaveAttribute("data-prefetch", "automatic");
      expect(handler).toHaveBeenCalledOnce();
    },
  );
  it("retains normal click navigation and does not intercept modified clicks", () => {
    const click = vi.fn((event) => event.preventDefault());
    render(
      <IntentLink
        href="/migrations/new"
        onClick={click}
        aria-label="New assessment"
      >
        Create
      </IntentLink>,
    );
    const link = screen.getByRole("link", { name: "New assessment" });
    fireEvent.click(link, { ctrlKey: true });
    expect(click).toHaveBeenCalledOnce();
    expect(click.mock.calls[0][0].ctrlKey).toBe(true);
    expect(link).toHaveAttribute("href", "/migrations/new");
  });
});
