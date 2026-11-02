import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  NaviganLifecycle,
  LIFECYCLE_DURATION_MS,
} from "@/shared/components/navigan-lifecycle";
import { PostLoginIntro } from "@/shared/auth/post-login-intro";
import {
  clearPendingLifecycleIntro,
  hasPendingLifecycleIntro,
  markLifecycleIntroPending,
} from "@/shared/auth/lifecycle-intro-state";

let frame: FrameRequestCallback | undefined;
let clock = 0;
let reduce = false;
const request = vi.fn((callback: FrameRequestCallback) => {
  frame = callback;
  return 1;
});
const cancel = vi.fn(() => {
  frame = undefined;
});
function advance(ms: number) {
  act(() => {
    clock += ms;
    const callback = frame;
    frame = undefined;
    callback?.(clock);
  });
}
beforeEach(() => {
  frame = undefined;
  clock = 0;
  reduce = false;
  sessionStorage.clear();
  vi.spyOn(performance, "now").mockImplementation(() => clock);
  vi.stubGlobal("requestAnimationFrame", request);
  vi.stubGlobal("cancelAnimationFrame", cancel);
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: reduce,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Shared Navigan lifecycle", () => {
  it("plays the connected scene, pauses, resumes and replays without completing twice", () => {
    const complete = vi.fn();
    render(<NaviganLifecycle onComplete={complete} />);
    fireEvent.click(screen.getByRole("button", { name: "Play animation" }));
    advance(3000);
    expect(
      screen.getByText("Manage clusters and plan workload migration."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(frame).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    advance(LIFECYCLE_DURATION_MS);
    expect(complete).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("region", { name: "Navigan lifecycle overview" }),
    ).toHaveAttribute("data-complete", "true");
    fireEvent.click(screen.getByRole("button", { name: "Replay animation" }));
    advance(LIFECYCLE_DURATION_MS);
    expect(complete).toHaveBeenCalledTimes(2);
  });
  it("only plays automatically for the login transition", () => {
    const { unmount } = render(<NaviganLifecycle />);
    expect(
      screen.getByRole("button", { name: "Play animation" }),
    ).toBeInTheDocument();
    expect(frame).toBeUndefined();
    unmount();
    render(<NaviganLifecycle autoPlay />);
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });
  it("blocks workspace mounting until skipped, clears the flag, and does not replay on refresh", () => {
    markLifecycleIntroPending();
    const { unmount } = render(
      <PostLoginIntro>
        <div>Workspace</div>
      </PostLoginIntro>,
    );
    expect(screen.queryByText("Workspace")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Skip and continue" }));
    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(hasPendingLifecycleIntro()).toBe(false);
    unmount();
    render(<PostLoginIntro>Workspace after reload</PostLoginIntro>);
    expect(screen.getByText("Workspace after reload")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Navigan lifecycle overview" }),
    ).not.toBeInTheDocument();
  });
  it("automatically opens the workspace when the full sequence finishes", () => {
    markLifecycleIntroPending();
    render(<PostLoginIntro>Workspace</PostLoginIntro>);
    advance(LIFECYCLE_DURATION_MS);
    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(hasPendingLifecycleIntro()).toBe(false);
  });
  it("bypasses login motion and retains a static About scene for reduced motion", () => {
    reduce = true;
    markLifecycleIntroPending();
    const { unmount } = render(<PostLoginIntro>Workspace</PostLoginIntro>);
    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(frame).toBeUndefined();
    unmount();
    render(<NaviganLifecycle />);
    expect(
      screen.getByRole("region", { name: "Navigan lifecycle overview" }),
    ).toHaveAttribute("data-complete", "true");
    expect(
      screen.queryByRole("button", { name: "Play animation" }),
    ).not.toBeInTheDocument();
  });
  it("unmounting cancels the outstanding frame without firing completion", () => {
    const complete = vi.fn();
    const { unmount } = render(
      <NaviganLifecycle autoPlay onComplete={complete} />,
    );
    unmount();
    expect(frame).toBeUndefined();
    expect(complete).not.toHaveBeenCalled();
  });
  it("does not block sign-in when session storage is disabled", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => markLifecycleIntroPending()).not.toThrow();
    expect(hasPendingLifecycleIntro()).toBe(false);
    expect(() => clearPendingLifecycleIntro()).not.toThrow();
    render(<PostLoginIntro>Workspace</PostLoginIntro>);
    expect(screen.getByText("Workspace")).toBeInTheDocument();
  });
});
