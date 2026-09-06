export type PlatformRole = "CLOUD_ENGINEER" | "PLATFORM_ARCHITECT" | "SERVICE";
export interface Identity {
  subject: string;
  displayName: string;
  roles: PlatformRole[];
  customerIds: string[];
  platformScope: boolean;
  canCreate: boolean;
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
// Display/action affordances only. API Gateway verifies JWTs and Lambda enforces all authorization.
export function identityFromClaims(claims: Record<string, unknown>): Identity {
  const roles = strings(claims.roles).filter((role): role is PlatformRole =>
    ["CLOUD_ENGINEER", "PLATFORM_ARCHITECT", "SERVICE"].includes(role),
  );
  const subject = typeof claims.sub === "string" ? claims.sub : "";
  return {
    subject,
    roles,
    customerIds: strings(claims.customer_ids),
    displayName:
      typeof claims.name === "string"
        ? claims.name
        : typeof claims.email === "string"
          ? claims.email
          : "Platform user",
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
