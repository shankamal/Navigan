"use client";
import { createContext, useContext, useState, type ReactNode } from "react";
const PageContext = createContext<{
  label: string;
  setLabel: (label: string) => void;
}>({ label: "", setLabel: () => {} });
export function WorkspacePageProvider({ children }: { children: ReactNode }) {
  const [label, setLabel] = useState("");
  return (
    <PageContext.Provider value={{ label, setLabel }}>
      {children}
    </PageContext.Provider>
  );
}
export function useWorkspacePage() {
  return useContext(PageContext);
}
