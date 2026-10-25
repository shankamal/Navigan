import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it } from "vitest";
import { HelpTip } from "../src/shared/components/help-tip";

it("keeps explanation absent until the circled information control is hovered", () => {
  render(
    <HelpTip label="Image copying">
      Copies pinned container content to private storage.
    </HelpTip>,
  );
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  fireEvent.mouseEnter(
    screen.getByRole("button", { name: "About Image copying" }),
  );
  expect(screen.getByRole("tooltip")).toHaveTextContent(
    "Copies pinned container content",
  );
  expect(screen.getByRole("button")).toHaveAttribute(
    "aria-describedby",
    screen.getByRole("tooltip").id,
  );
});
it("opens on keyboard focus and dismisses on Escape without moving focus", () => {
  render(
    <HelpTip label="Record coverage">
      Active records are not runtime health.
    </HelpTip>,
  );
  const trigger = screen.getByRole("button", { name: "About Record coverage" });
  trigger.focus();
  fireEvent.focus(trigger);
  expect(screen.getByRole("tooltip")).toBeVisible();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});
it("allows hovering the popup and closes after the pointer leaves or clicks outside", async () => {
  render(<HelpTip label="Storage">Saved files remain private.</HelpTip>);
  const trigger = screen.getByRole("button");
  fireEvent.mouseEnter(trigger);
  const tip = screen.getByRole("tooltip");
  fireEvent.mouseLeave(trigger);
  fireEvent.mouseEnter(tip);
  expect(tip).toBeVisible();
  fireEvent.mouseLeave(tip);
  await waitFor(() =>
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument(),
  );
  fireEvent.click(trigger);
  expect(screen.getByRole("tooltip")).toBeVisible();
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
