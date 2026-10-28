"use client";
import { Check } from "lucide-react";
import styles from "./source-migration-workspace.module.css";

export const migrationWorkflowSteps = [
  "Source connection",
  "Discovery & assessment",
  "Migration scope",
  "Target & compatibility",
  "Review & approval",
  "Execute",
] as const;
export function MigrationWorkflow({
  active,
  completed = [],
  onSelect,
  available = [],
  hideConnection = false,
}: {
  active: number;
  hideConnection?: boolean;
  completed?: number[];
  available?: number[];
  onSelect?: (step: number) => void;
}) {
  return (
    <ol
      className={styles.workflow}
      data-stages={hideConnection ? 5 : 6}
      aria-label="Migration workflow"
    >
      {migrationWorkflowSteps.map((label, index) => {
        const step = index + 1;
        if (hideConnection && step === 1) return null;
        return (
          <li key={label} aria-current={active === step ? "step" : undefined}>
            <button
              type="button"
              className={styles.workflowButton}
              disabled={!onSelect || !available.includes(step)}
              onClick={() => onSelect?.(step)}
            >
              <span>
                {completed.includes(step) ? (
                  <Check size={16} />
                ) : hideConnection ? (
                  step - 1
                ) : (
                  step
                )}
              </span>{" "}
              {label}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
