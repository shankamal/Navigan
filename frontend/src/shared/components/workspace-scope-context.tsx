"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type WorkspaceScope = {
  customerId: string;
  environmentId: string;
  setCustomerId: (value: string) => void;
  setEnvironmentId: (value: string) => void;
};

const CUSTOMER_KEY = "navigan.scope.customerId";
const ENVIRONMENT_KEY = "navigan.scope.environmentId";

const WorkspaceScopeContext = createContext<WorkspaceScope | null>(null);

export function WorkspaceScopeProvider({ children }: { children: ReactNode }) {
  const [customerId, setCustomer] = useState("all");
  const [environmentId, setEnvironment] = useState("all");

  useEffect(() => {
    setCustomer(window.localStorage.getItem(CUSTOMER_KEY) || "all");
    setEnvironment(window.localStorage.getItem(ENVIRONMENT_KEY) || "all");
  }, []);

  const value = useMemo<WorkspaceScope>(
    () => ({
      customerId,
      environmentId,
      setCustomerId: (next) => {
        setCustomer(next);
        window.localStorage.setItem(CUSTOMER_KEY, next);
      },
      setEnvironmentId: (next) => {
        setEnvironment(next);
        window.localStorage.setItem(ENVIRONMENT_KEY, next);
      },
    }),
    [customerId, environmentId],
  );

  return (
    <WorkspaceScopeContext.Provider value={value}>
      {children}
    </WorkspaceScopeContext.Provider>
  );
}

export function useWorkspaceScope() {
  const value = useContext(WorkspaceScopeContext);
  if (!value)
    throw new Error(
      "useWorkspaceScope must be used inside WorkspaceScopeProvider",
    );
  return value;
}

export function useOptionalWorkspaceScope() {
  return useContext(WorkspaceScopeContext);
}
