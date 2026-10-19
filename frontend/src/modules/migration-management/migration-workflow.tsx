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
}: {
  active: number;
  completed?: number[];
  available?: number[];
  onSelect?: (step: number) => void;
}) {
  return (
    <ol className={styles.workflow} aria-label="Migration workflow">
      {migrationWorkflowSteps.map((label, index) => {
        const step = index + 1;
        return (
          <li key={label} aria-current={active === step ? "step" : undefined}>
            <button
              type="button"
              className={styles.workflowButton}
              disabled={!onSelect || !available.includes(step)}
              onClick={() => onSelect?.(step)}
            >
              <span>
                {completed.includes(step) ? <Check size={16} /> : step}
              </span>
              {label}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
