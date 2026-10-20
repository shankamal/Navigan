"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Box, X } from "lucide-react";
import styles from "./deployment-evidence-panel.module.css";

/** On-demand evidence view; focus returns to the workload that opened it. */
export function EvidenceDrawer({
  title,
  subtitle,
  onClose,
  children,
  variant = "evidence",
  closeLabel = "Close workload evidence",
  wide = false,
  footer,
}: {
  title: string;
  subtitle: string;
  onClose: () => void;
  children: ReactNode;
  variant?: "evidence" | "connections" | "recovery";
  closeLabel?: string;
  wide?: boolean;
  footer?: ReactNode;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.current?.focus();
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
      }
      if (event.key !== "Tab") return;
      const elements = Array.from(
        dialog.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]',
        ) ?? [],
      ).filter((el) => el.getClientRects().length > 0);
      const first = elements[0],
        last = elements.at(-1);
      if (!first) {
        event.preventDefault();
        dialog.current?.focus();
        return;
      }
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          document.activeElement === dialog.current)
      ) {
        event.preventDefault();
        last?.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          document.activeElement === dialog.current)
      ) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", keydown);
    // Keep keyboard and assistive-technology navigation inside the modal.
    const roots = Array.from(document.body.children).filter(
      (el) => el instanceof HTMLElement && !el.contains(dialog.current),
    ) as HTMLElement[];
    const oldInert = roots.map((el) => el.inert);
    roots.forEach((el) => {
      el.inert = true;
    });
    return () => {
      document.removeEventListener("keydown", keydown);
      document.body.style.overflow = priorOverflow;
      roots.forEach((el, index) => {
        el.inert = oldInert[index];
      });
      previous?.focus();
    };
  }, []);
  return createPortal(
    <div className={styles.drawerLayer}>
      <div
        className={styles.drawerBackdrop}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={dialog}
        className={`${styles.drawer} ${variant === "recovery" ? styles.recoveryWindow : ""} ${variant === "connections" ? `${styles.connectionWindow} ${wide ? styles.connectionWindowWide : ""}` : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="workload-evidence-title"
        aria-describedby="workload-evidence-subtitle"
        tabIndex={-1}
      >
        <header className={styles.drawerHeader}>
          <Box size={25} />
          <div>
            <h2 id="workload-evidence-title">{title}</h2>
            <p id="workload-evidence-subtitle">{subtitle}</p>
          </div>
          <button onClick={onClose} aria-label={closeLabel}>
            <X size={21} />
          </button>
        </header>
        <div className={styles.drawerBody}>{children}</div>
        <footer className={styles.drawerFooter}>
          {footer ?? (
            <button onClick={onClose}>
              {variant === "connections" ? "Done" : "Close"}
            </button>
          )}
        </footer>
      </div>
    </div>,
    document.body,
  );
}
