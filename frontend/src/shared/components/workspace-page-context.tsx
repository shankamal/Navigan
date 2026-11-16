"use client";
import { createContext, useContext, useState, type ReactNode } from "react";
const PageContext = createContext<{
  label: string;
  setLabel: (label: string) => void;
  headerTarget: HTMLDivElement | null;
  setHeaderTarget: (target: HTMLDivElement | null) => void;
}>({
  label: "",
  setLabel: () => {},
  headerTarget: null,
  setHeaderTarget: () => {},
});
export function WorkspacePageProvider({ children }: { children: ReactNode }) {
  const [label, setLabel] = useState("");
  const [headerTarget, setHeaderTarget] = useState<HTMLDivElement | null>(null);
  return (
    <PageContext.Provider
      value={{ label, setLabel, headerTarget, setHeaderTarget }}
    >
      {children}
    </PageContext.Provider>
  );
}
export function useWorkspacePage() {
  return useContext(PageContext);
}
