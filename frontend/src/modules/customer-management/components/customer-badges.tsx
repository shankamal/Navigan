import { statusLabels, cloudProviders } from "../model/policy";
import type { CustomerStatus } from "../model/types";
export function StatusBadge({ status }: { status: CustomerStatus }) {
  return (
    <span className={`status-badge status-${status.toLowerCase()}`}>
      {statusLabels[status]}
    </span>
  );
}
export function ProviderBadges({ codes }: { codes: string[] }) {
  return (
    <div className="provider-badges">
      {codes.length ? (
        codes.map((code) => (
          <span key={code} className="provider-badge">
            {cloudProviders.find((p) => p.code === code)?.shortName ?? code}
          </span>
        ))
      ) : (
        <span className="muted">Not selected</span>
      )}
    </div>
  );
}
