import type { ReactNode } from "react";
import styles from "./migration-experience.module.css";

/** One predictable navigation area; form and row actions stay with their data. */
export function MigrationActions({
  back,
  status,
  children,
}: {
  back?: ReactNode;
  status?: ReactNode;
  children: ReactNode;
}) {
  return (
    <nav className={styles.actionBar} aria-label="Migration step actions">
      <div className={styles.back}>{back}</div>
      <div className={styles.actionStatus}>{status}</div>
      <div className={styles.next}>{children}</div>
    </nav>
  );
}
