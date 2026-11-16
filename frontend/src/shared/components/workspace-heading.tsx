"use client";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import { useWorkspacePage } from "./workspace-page-context";

/** Keeps React context/event handlers while the shell owns one sticky heading. */
export function WorkspaceHeading({ children }: { children: ReactNode }) {
  const { headerTarget } = useWorkspacePage();
  return headerTarget ? (
    createPortal(
      <div className="workspace-title-content">{children}</div>,
      headerTarget,
    )
  ) : (
    <>{children}</>
  );
}
