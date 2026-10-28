"use client";
import {
  useEffect,
  useLayoutEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";
import styles from "./help-tip.module.css";

/** Explanatory help only. Errors and operational status stay in the page. */
export function HelpTip({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLSpanElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({
    left: 12,
    top: 0,
    above: false,
    width: 300,
  });
  function cancelClose() {
    if (timer.current) clearTimeout(timer.current);
  }
  function show() {
    cancelClose();
    setOpen(true);
  }
  function scheduleClose() {
    cancelClose();
    timer.current = setTimeout(() => setOpen(false), 100);
  }
  useLayoutEffect(() => {
    if (!open) return;
    function positionTip() {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(320, window.innerWidth - 24);
      const above = window.innerHeight - rect.bottom < 190 && rect.top > 190;
      setPosition({
        width,
        above,
        left: Math.max(
          12,
          Math.min(rect.left - 12, window.innerWidth - width - 12),
        ),
        top: above ? rect.top - 8 : rect.bottom + 8,
      });
    }
    function dismiss(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    function outside(event: PointerEvent) {
      if (
        !trigger.current?.contains(event.target as Node) &&
        !popup.current?.contains(event.target as Node)
      )
        setOpen(false);
    }
    positionTip();
    window.addEventListener("resize", positionTip);
    window.addEventListener("scroll", positionTip, true);
    document.addEventListener("keydown", dismiss);
    document.addEventListener("pointerdown", outside);
    return () => {
      window.removeEventListener("resize", positionTip);
      window.removeEventListener("scroll", positionTip, true);
      document.removeEventListener("keydown", dismiss);
      document.removeEventListener("pointerdown", outside);
    };
  }, [open]);
  useEffect(() => () => cancelClose(), []);
  return (
    <span className={[styles.host, className].filter(Boolean).join(" ")}>
      <button
        ref={trigger}
        className={styles.trigger}
        type="button"
        aria-label={`About ${label}`}
        aria-describedby={open ? id : undefined}
        onMouseEnter={show}
        onMouseLeave={scheduleClose}
        onFocus={show}
        onBlur={scheduleClose}
        onClick={show}
      >
        <Info size={14} aria-hidden="true" />
      </button>
      {open &&
        createPortal(
          <span
            ref={popup}
            id={id}
            role="tooltip"
            className={styles.popup}
            style={{
              left: position.left,
              top: position.top,
              width: position.width,
              transform: position.above ? "translateY(-100%)" : undefined,
            }}
            onMouseEnter={cancelClose}
            onMouseLeave={scheduleClose}
          >
            {children}
          </span>,
          document.body,
        )}
    </span>
  );
}
