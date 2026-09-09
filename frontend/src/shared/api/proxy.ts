const actions = [
  "submit",
  "resubmit",
  "review/start",
  "approve",
  "reject",
  "activate",
  "suspend",
  "reactivate",
  "deactivate",
];
export function isAllowedRoute(method: string, path: string[]): boolean {
  if (path[0] === "environments") {
    if (path.length === 1) return ["GET", "POST"].includes(method);
    if (path.length === 2 && path[1] === "metadata") return method === "GET";
    if (path.length === 3 && path[1] === "discover" && path[2] === "aws")
      return method === "POST";
    if (path.length === 4 && path[1] === "configuration-schemas")
      return (
        method === "GET" &&
        ["EKS", "AKS", "GKE", "OKE"].includes(path[2]) &&
        path[3] === "1.0"
      );
    if (!/^ENV-[A-Za-z0-9-]+$/.test(path[1])) return false;
    if (path.length === 2) return ["GET", "PUT"].includes(method);
    if (path.length === 4 && path[2] === "versions")
      return method === "GET" && /^[1-9][0-9]*$/.test(path[3]);
    if (path.length !== 3) return false;
    if (path[2] === "status") return method === "PATCH";
    if (
      ["versions", "status-history", "reviews", "audit-log"].includes(path[2])
    )
      return method === "GET";
    return method === "POST" && [...actions, "review"].includes(path[2]);
  }
  if (path[0] !== "customers") return false;
  if (path.length === 1) return ["GET", "POST"].includes(method);
  if (!/^CUS-[A-Za-z0-9-]+$/.test(path[1])) return false;
  if (path.length === 2) return ["GET", "PUT"].includes(method);
  const suffix = path.slice(2).join("/");
  if (suffix === "cloud-providers") return ["GET", "PUT"].includes(method);
  if (["status-history", "reviews", "audit-log"].includes(suffix))
    return method === "GET";
  return method === "POST" && actions.includes(suffix);
}
export function upstreamUrl(path: string[], query: string): URL {
  const origin = new URL(
    process.env.NAVIGAN_API_ORIGIN ||
      "https://q0i8bcekw1.execute-api.ap-south-1.amazonaws.com",
  );
  if (
    origin.protocol !== "https:" ||
    origin.username ||
    origin.password ||
    origin.pathname !== "/" ||
    origin.search ||
    origin.hash
  )
    throw new Error("Invalid API origin configuration");
  const base = process.env.NAVIGAN_API_BASE_PATH || "/v1/api/v1";
  if (!/^\/[A-Za-z0-9/_-]+$/.test(base))
    throw new Error("Invalid API base path");
  const url = new URL(
    `${base.replace(/\/$/, "")}/${path.map(encodeURIComponent).join("/")}`,
    origin,
  );
  url.search = query;
  return url;
}
export async function forwardRequest(
  request: Request,
  path: string[],
): Promise<Response> {
  const correlationId = crypto.randomUUID();
  const fail = (status: number, code: string, message: string) =>
    Response.json(
      { error: { code, message, details: {}, correlationId } },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  if (!isAllowedRoute(request.method, path))
    return fail(404, "ROUTE_NOT_FOUND", "Endpoint not found.");
  const auth = request.headers.get("authorization");
  if (
    !auth ||
    !/^Bearer [A-Za-z0-9._~+/-]+=*$/.test(auth) ||
    auth.length > 16384
  )
    return fail(401, "UNAUTHENTICATED", "A valid access token is required.");
  const headers = new Headers({
    Authorization: auth,
    Accept: "application/json",
    "X-Correlation-ID": correlationId,
  });
  for (const name of ["if-match", "idempotency-key"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  let body: string | undefined;
  if (request.method !== "GET") {
    if (
      !request.headers
        .get("content-type")
        ?.toLowerCase()
        .startsWith("application/json")
    )
      return fail(400, "INVALID_CONTENT_TYPE", "Use application/json.");
    const reader = request.body?.getReader();
    if (!reader) return fail(400, "INVALID_JSON", "A JSON object is required.");
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 65536) {
        await reader.cancel();
        return fail(413, "PAYLOAD_TOO_LARGE", "Request body exceeds 64 KiB.");
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    body = new TextDecoder().decode(bytes);
    try {
      const parsed: unknown = JSON.parse(body);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error();
    } catch {
      return fail(400, "INVALID_JSON", "A JSON object is required.");
    }
    headers.set("Content-Type", "application/json");
  }
  try {
    const response = await fetch(
      upstreamUrl(path, new URL(request.url).search),
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        redirect: "manual",
        signal: AbortSignal.timeout(30_000),
      },
    );
    if (response.status >= 300 && response.status < 400)
      return fail(
        502,
        "UPSTREAM_REDIRECT",
        "The API returned an unexpected redirect.",
      );
    const outgoing = new Headers({
      "Content-Type":
        response.headers.get("content-type") || "application/json",
      "Cache-Control": "no-store",
    });
    for (const name of [
      "etag",
      "x-correlation-id",
      "idempotency-replayed",
      "retry-after",
    ]) {
      const value = response.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    if (!response.ok)
      console.error("Navigan upstream failure", {
        status: response.status,
        correlationId,
      });
    return new Response(response.body, {
      status: response.status,
      headers: outgoing,
    });
  } catch {
    console.error("Navigan upstream unavailable", { correlationId });
    return fail(
      502,
      "UPSTREAM_UNAVAILABLE",
      "Unable to reach the platform API.",
    );
  }
}
