import { statusLabels, cloudProviders } from "../model/policy";
import type { CustomerStatus } from "../model/types";
export function StatusBadge({ status }: { status: CustomerStatus }) {
  return (
    <span className={`status-badge status-${status.toLowerCase()}`}>
      {statusLabels[status]}
    </span>
  );
}
const providerLogos: Record<string, string> = {
  AWS: "amazonwebservices",
  AZURE: "microsoftazure",
  GCP: "googlecloud",
  OCI: "oracle",
};
export function ProviderBadges({
  codes,
  compact = false,
}: {
  codes: string[];
  compact?: boolean;
}) {
  return (
    <div className="provider-badges">
      {codes.length ? (
        codes.map((code) => (
          <span
            key={code}
            className={`provider-badge${compact ? " provider-logo" : ""}`}
            title={cloudProviders.find((p) => p.code === code)?.name ?? code}
          >
            {providerLogos[code] && (
              <img
                src={`/logos/${providerLogos[code]}.svg`}
                alt={
                  compact
                    ? (cloudProviders.find((p) => p.code === code)?.name ??
                      code)
                    : ""
                }
                width={22}
                height={22}
              />
            )}
            {(!compact || !providerLogos[code]) &&
              (cloudProviders.find((p) => p.code === code)?.shortName ?? code)}
          </span>
        ))
      ) : (
        <span className="muted">Not selected</span>
      )}
    </div>
  );
}
