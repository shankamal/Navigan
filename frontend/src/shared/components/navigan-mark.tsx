import { Compass, Navigation2 } from "lucide-react";
import styles from "./navigan-mark.module.css";

export function NaviganMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`${styles.mark} ${compact ? styles.compact : ""}`} aria-hidden="true">
      <Compass className={styles.compass} strokeWidth={1.55} />
      <Navigation2 className={styles.pointer} strokeWidth={2.5} />
    </span>
  );
}
