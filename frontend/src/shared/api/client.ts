import axios from "axios";
import { z } from "zod";
import {
  accessToken,
  authConfigured,
  authManager,
} from "@/shared/auth/session";
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public correlationId?: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
const errorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    correlationId: z.string().optional(),
    details: z.record(z.string(), z.unknown()).optional(),
  }),
});
export function normalizeApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? 0;
    const parsed = errorSchema.safeParse(error.response?.data);
    if (parsed.success) {
      const value = parsed.data.error;
      return new ApiError(
        value.message,
        status,
        value.code,
        value.correlationId,
        value.details,
      );
    }
    const message =
      status === 401
        ? "Your session has expired. Sign in again."
        : status === 403
          ? "You do not have permission for this action."
          : status === 404
            ? "This customer is unavailable or outside your access scope."
            : status === 429
              ? "Too many requests. Wait a moment and try again."
              : status >= 500
                ? "The service is temporarily unavailable. Please try again."
                : "Unable to reach the service. Check your connection and try again.";
    return new ApiError(
      message,
      status,
      status ? "HTTP_ERROR" : "NETWORK_ERROR",
    );
  }
  return new ApiError(
    "An unexpected response was received. Please try again.",
    0,
    "CLIENT_ERROR",
  );
}
export const apiClient = axios.create({
  baseURL: "/api/platform",
  timeout: 35_000,
  headers: { Accept: "application/json" },
});
apiClient.interceptors.request.use(async (config) => {
  const token = await accessToken();
  if (!token)
    throw new ApiError("Sign in to access Navigan.", 401, "UNAUTHENTICATED");
  config.headers.set("Authorization", `Bearer ${token}`);
  config.headers.set("X-Correlation-ID", crypto.randomUUID());
  return config;
});
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const normalized = normalizeApiError(error);
    if (normalized.status === 401 && authConfigured)
      await authManager().removeUser();
    // Metadata only: never log tokens, customer bodies, contacts or raw Axios errors.
    console.error("Navigan API request failed", {
      status: normalized.status,
      code: normalized.code,
      correlationId: normalized.correlationId,
    });
    return Promise.reject(normalized);
  },
);
export interface WriteOptions {
  key: string;
  version?: number;
}
export function writeHeaders(options: WriteOptions): Record<string, string> {
  return {
    "Idempotency-Key": options.key,
    ...(options.version !== undefined
      ? { "If-Match": String(options.version) }
      : {}),
  };
}
export function parseResponse<T>(schema: z.ZodType<T>, data: unknown): T {
  const result = schema.safeParse(data);
  if (!result.success)
    throw new ApiError(
      "The service returned an incompatible response. Contact your platform administrator.",
      502,
      "INVALID_RESPONSE",
    );
  return result.data;
}
