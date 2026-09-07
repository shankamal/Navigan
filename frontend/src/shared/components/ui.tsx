"use client";
import {
  useEffect,
  useId,
  useRef,
  type ReactNode,
  type ButtonHTMLAttributes,
} from "react";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  LoaderCircle,
  X,
} from "lucide-react";
import { ApiError } from "@/shared/api/client";
export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
}) {
  return (
    <button {...props} className={`button button-${variant} ${className}`} />
  );
}
export function Loading({ label = "Loading customers…" }: { label?: string }) {
  return (
    <div className="loading-panel" role="status">
      <LoaderCircle className="animate-spin" size={24} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
export function ErrorNotice({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const value =
    error instanceof Error
      ? error.message
      : "Something went wrong. Please try again.";
  const conflict =
    error instanceof ApiError &&
    error.status === 409 &&
    ["CONCURRENT_UPDATE", "IDEMPOTENCY_CONFLICT"].includes(error.code);
  return (
    <div className="notice notice-error" role="alert">
      <AlertCircle size={20} aria-hidden="true" />
      <div>
        <strong>
          {conflict
            ? "This record has changed"
            : "We couldn’t complete this request"}
        </strong>
        <p>{value}</p>
        {conflict && (
          <p>
            Your changes have not been overwritten. Reload the latest record and
            review your changes before saving again.
          </p>
        )}
        {error instanceof ApiError && error.correlationId && (
          <p className="metadata break-all">Reference: {error.correlationId}</p>
        )}
        {onRetry && (
          <Button variant="secondary" onClick={onRetry}>
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}
export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon?: ReactNode;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-icon">{icon}</div>}
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="muted">{description}</p>}
      </div>
      {action && <div className="heading-actions">{action}</div>}
    </div>
  );
}
export function Pagination({
  page,
  pageSize,
  totalElements,
  totalPages,
  onChange,
  disabled = false,
}: {
  page: number;
  pageSize: number;
  totalElements: number;
  totalPages: number;
  onChange: (page: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="pagination">
      <p>
        {totalElements
          ? `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, totalElements)} of ${totalElements} records`
          : "0 records"}
      </p>
      <nav aria-label="Pagination">
        <Button
          variant="secondary"
          aria-label="Previous page"
          disabled={disabled || page === 0}
          onClick={() => onChange(page - 1)}
        >
          <ArrowLeft size={16} />
          Previous
        </Button>
        <span>
          Page {page + 1} of {Math.max(1, totalPages)}
        </span>
        <Button
          variant="secondary"
          aria-label="Next page"
          disabled={disabled || page + 1 >= totalPages}
          onClick={() => onChange(page + 1)}
        >
          Next
          <ArrowRight size={16} />
        </Button>
      </nav>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  busy = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const el = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    el?.showModal();
    return () => {
      el?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={id}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <div className="modal-heading">
        <h2 id={id}>{title}</h2>
        <Button
          variant="ghost"
          aria-label="Close dialog"
          disabled={busy}
          onClick={onClose}
        >
          <X size={20} />
        </Button>
      </div>
      {children}
    </dialog>
  );
}
export const formatDate = (value?: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        timeZone: "Asia/Kolkata",
      }).format(date);
};
export const formatDateTime = (value?: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Kolkata",
        timeZoneName: "short",
      }).format(date);
};
