export type PlatformRole =
  | "CLOUD_ENGINEER"
  | "PLATFORM_ARCHITECT"
  | "PLATFORM_ADMINISTRATOR"
  | "SERVICE";
export interface Identity {
  subject: string;
  displayName: string;
  roles: PlatformRole[];
  customerIds: string[];
  platformScope: boolean;
  canCreate: boolean;
  privileges?: string[];
  authorizationRevision?: number;
  authorizationSource?: "DYNAMIC" | "LEGACY_CLAIMS";
}
function strings(value: unknown): string[] {
  if (Array.isArray(value))
    return value.filter((item): item is string => typeof item === "string");
  if (typeof value !== "string") return [];
  if (value.startsWith("[")) {
    try {
      return strings(JSON.parse(value));
    } catch {
      return [];
    }
  }
  return value.split(/\s+/).filter(Boolean);
}
export function isHumanReadableDisplayName(
  value: unknown,
  subject = "",
): value is string {
  if (typeof value !== "string" || !value.trim()) return false;
  const normalized = value.trim();
  return (
    normalized !== subject &&
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      normalized,
    )
  );
}
// Display/action affordances only. API Gateway verifies JWTs and Lambda enforces all authorization.
export function identityFromClaims(claims: Record<string, unknown>): Identity {
  const roles = strings(claims.roles).filter((role): role is PlatformRole =>
    [
      "CLOUD_ENGINEER",
      "PLATFORM_ARCHITECT",
      "PLATFORM_ADMINISTRATOR",
      "SERVICE",
    ].includes(role),
  );
  const subject = typeof claims.sub === "string" ? claims.sub : "";
  const fullName = [claims.given_name, claims.family_name]
    .filter((value): value is string => typeof value === "string" && !!value.trim())
    .join(" ")
    .trim();
  const displayNameCandidates = [
    claims.name,
    fullName,
    claims.email,
    claims.preferred_username,
    claims["cognito:username"],
    claims.username,
  ];
  return {
    subject,
    roles,
    customerIds: strings(claims.customer_ids),
    displayName:
      displayNameCandidates.find((value) =>
        isHumanReadableDisplayName(value, subject),
      )?.toString().trim() || "Platform user",
    platformScope: String(claims.platform_scope).toLowerCase() === "true",
    canCreate: String(claims.customer_create).toLowerCase() === "true",
  };
}
export function readAccessClaims(token: string): Record<string, unknown> {
  try {
    const segment = token.split(".")[1];
    const bytes = Uint8Array.from(
      atob(segment.replace(/-/g, "+").replace(/_/g, "/")),
      (c) => c.charCodeAt(0),
    );
    const result: unknown = JSON.parse(new TextDecoder().decode(bytes));
    return result && typeof result === "object" && !Array.isArray(result)
      ? (result as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}
