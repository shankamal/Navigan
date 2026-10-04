import crypto from "node:crypto";
import http from "node:http";
import os from "node:os";
import { URL } from "node:url";

const port = Number(process.env.PORT || 3100);
const apiBase = requiredUrl("NAVIGAN_API_BASE_URL");
const instanceId =
  process.env.GATEWAY_INSTANCE_ID || `${os.hostname()}:${process.pid}`;
const tunnels = new Map();
const pending = new Map();
const maxBodyBytes = 8 * 1024 * 1024;
const toolPaths = new Map([
  ["headlamp", "HEADLAMP"],
  ["grafana", "GRAFANA"],
  ["prometheus", "PROMETHEUS"],
  ["argocd", "ARGOCD"],
  ["webkubectl", "WEBKUBECTL"],
]);

function requiredUrl(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  const parsed = new URL(value);
  if (parsed.protocol !== "https:" || parsed.username || parsed.password)
    throw new Error(`${name} must be an HTTPS URL without credentials`);
  return value.replace(/\/$/, "");
}

function json(res, status, value) {
  const body = JSON.stringify(value);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  res.end(body);
}

function readBody(req, limit = maxBodyBytes) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(new Error("request body too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

async function platformRequest(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    redirect: "manual",
    signal: AbortSignal.timeout(10_000),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error("platform request failed");
    error.status = response.status;
    throw error;
  }
  return body;
}

function parseCookies(req) {
  return Object.fromEntries(
    String(req.headers.cookie || "")
      .split(";")
      .map((item) => item.trim().split("="))
      .filter(([name, value]) => name && value)
      .map(([name, value]) => [name, decodeURIComponent(value)]),
  );
}

function sessionCookie(sessionId, accessToken) {
  return Buffer.from(JSON.stringify({ sessionId, accessToken })).toString(
    "base64url",
  );
}

function decodeSessionCookie(value) {
  try {
    const parsed = JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
    if (
      !/^KTS-[a-f0-9]{32}$/.test(parsed.sessionId) ||
      !/^[A-Za-z0-9_-]{40,100}$/.test(parsed.accessToken)
    )
      return null;
    return parsed;
  } catch {
    return null;
  }
}

function toolSessionCookieName(clusterId, toolPath) {
  if (!/^CLU-[A-Za-z0-9-]{1,46}$/.test(clusterId))
    throw new Error("invalid cluster cookie");
  if (!toolPaths.has(toolPath)) throw new Error("unsupported tool cookie");
  return `navigan_tool_session_${clusterId
    .toLowerCase()
    .replaceAll("-", "_")}_${toolPath}`;
}

class WebSocketPeer {
  constructor(socket, initialData, onMessage, onClose) {
    this.socket = socket;
    this.buffer = initialData || Buffer.alloc(0);
    this.onMessage = onMessage;
    this.onClose = onClose;
    this.closed = false;
    socket.on("data", (chunk) => {
      this.buffer = Buffer.concat([this.buffer, chunk]);
      this.parse();
    });
    socket.on("close", () => this.close());
    socket.on("error", () => this.close());
    this.parse();
  }

  send(value) {
    if (this.closed) throw new Error("tunnel is closed");
    const payload = Buffer.from(JSON.stringify(value));
    this.socket.write(frame(payload, 0x1));
  }

  parse() {
    while (this.buffer.length >= 2) {
      const first = this.buffer[0];
      const second = this.buffer[1];
      const opcode = first & 0x0f;
      const masked = Boolean(second & 0x80);
      if (!masked) return this.close();
      let length = second & 0x7f;
      let offset = 2;
      if (length === 126) {
        if (this.buffer.length < 4) return;
        length = this.buffer.readUInt16BE(2);
        offset = 4;
      } else if (length === 127) {
        if (this.buffer.length < 10) return;
        const wide = this.buffer.readBigUInt64BE(2);
        if (wide > BigInt(maxBodyBytes)) return this.close();
        length = Number(wide);
        offset = 10;
      }
      const maskBytes = masked ? 4 : 0;
      if (this.buffer.length < offset + maskBytes + length) return;
      const mask = masked
        ? this.buffer.subarray(offset, offset + 4)
        : Buffer.alloc(0);
      offset += maskBytes;
      const payload = Buffer.from(this.buffer.subarray(offset, offset + length));
      this.buffer = this.buffer.subarray(offset + length);
      if (masked) {
        for (let index = 0; index < payload.length; index += 1)
          payload[index] ^= mask[index % 4];
      }
      if (opcode === 0x8) return this.close();
      if (opcode === 0x9) {
        this.socket.write(frame(payload, 0x0a));
        continue;
      }
      if (opcode !== 0x1) continue;
      try {
        this.onMessage(JSON.parse(payload.toString("utf8")));
      } catch {
        this.close();
      }
    }
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.socket.destroy();
    this.onClose();
  }
}

function frame(payload, opcode) {
  if (payload.length < 126)
    return Buffer.concat([Buffer.from([0x80 | opcode, payload.length]), payload]);
  if (payload.length <= 65535) {
    const header = Buffer.alloc(4);
    header[0] = 0x80 | opcode;
    header[1] = 126;
    header.writeUInt16BE(payload.length, 2);
    return Buffer.concat([header, payload]);
  }
  const header = Buffer.alloc(10);
  header[0] = 0x80 | opcode;
  header[1] = 127;
  header.writeBigUInt64BE(BigInt(payload.length), 2);
  return Buffer.concat([header, payload]);
}

function safeRequestHeaders(headers) {
  const allowed = [
    "accept",
    "accept-encoding",
    "accept-language",
    "content-type",
    "if-none-match",
    "if-modified-since",
    "range",
    "user-agent",
    "grpc-timeout",
    "origin",
    "x-grpc-web",
    "x-user-agent",
  ];
  return Object.fromEntries(
    allowed
      .filter((name) => typeof headers[name] === "string")
      .map((name) => [name, headers[name]]),
  );
}

function safeResponseHeaders(headers = {}) {
  const blocked = new Set([
    "connection",
    "content-length",
    "content-security-policy",
    "set-cookie",
    "transfer-encoding",
    "upgrade",
  ]);
  return Object.fromEntries(
    Object.entries(headers).filter(
      ([name]) => !blocked.has(name.toLowerCase()),
    ),
  );
}

async function exchangeSession(req, res) {
  const body = await readBody(req, 8192);
  const form = new URLSearchParams(body.toString("utf8"));
  const sessionId = form.get("sessionId") || "";
  const exchangeToken = form.get("exchangeToken") || "";
  if (
    !/^KTS-[a-f0-9]{32}$/.test(sessionId) ||
    !/^[A-Za-z0-9_-]{40,100}$/.test(exchangeToken)
  )
    return json(res, 400, { error: "Invalid tool session." });
  const session = await platformRequest(
    `/tool-sessions/${encodeURIComponent(sessionId)}/exchange`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exchangeToken }),
    },
  );
  const toolPath = String(session.toolCode || "").toLowerCase();
  const toolRoot = `/tools/clusters/${encodeURIComponent(
    session.clusterId,
  )}/${toolPath}`;
  const location = `${toolRoot}/`;
  res.writeHead(303, {
    Location: location,
    "Set-Cookie": `${toolSessionCookieName(
      session.clusterId,
      toolPath,
    )}=${encodeURIComponent(
      sessionCookie(session.sessionId, session.accessToken),
    )}; Path=/; Max-Age=1800; HttpOnly; Secure; SameSite=None`,
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
  });
  res.end();
}

async function validateBrowserSession(
  req,
  clusterId,
  toolPath,
  toolCode,
  requestedPath,
) {
  const cookies = parseCookies(req);
  const cookie = decodeSessionCookie(
    cookies[toolSessionCookieName(clusterId, toolPath)],
  );
  if (!cookie) {
    console.warn(
      JSON.stringify({
        event: "tool_session_cookie_missing",
        clusterId,
        tool: toolPath,
        path: requestedPath,
        cookieNames: Object.keys(cookies).filter((name) =>
          name.startsWith("navigan_tool_session_"),
        ),
      }),
    );
    return null;
  }
  const session = await platformRequest(
    `/tool-sessions/${encodeURIComponent(cookie.sessionId)}/validate`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${cookie.accessToken}` },
    },
  );
  if (session.clusterId !== clusterId || session.toolCode !== toolCode)
    return null;
  return session;
}

function forwardThroughTunnel(tunnel, request) {
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timeout = setTimeout(() => {
      pending.delete(id);
      reject(new Error("tunnel request timed out"));
    }, 30_000);
    pending.set(id, {
      clusterId: tunnel.clusterId,
      resolve: (value) => {
        clearTimeout(timeout);
        resolve(value);
      },
      reject: (error) => {
        clearTimeout(timeout);
        reject(error);
      },
    });
    try {
      tunnel.peer.send({ type: "request", id, ...request });
    } catch (error) {
      pending.delete(id);
      clearTimeout(timeout);
      reject(error);
    }
  });
}

async function proxyTool(req, res, url) {
  const match = url.pathname.match(
    /^\/tools\/clusters\/(CLU-[A-Za-z0-9-]{1,46})\/(headlamp|grafana|prometheus|argocd|webkubectl)(\/.*)?$/,
  );
  if (!match) return json(res, 404, { error: "Tool route not found." });
  const [, clusterId, toolPath] = match;
  const toolCode = toolPaths.get(toolPath);
  const session = await validateBrowserSession(
    req,
    clusterId,
    toolPath,
    toolCode,
    url.pathname,
  );
  if (!session) return json(res, 401, { error: "Tool session is invalid." });
  const tunnel = tunnels.get(clusterId);
  if (!tunnel) return json(res, 503, { error: "Cluster tunnel is unavailable." });
  const body = await readBody(req);
  const response = await forwardThroughTunnel(tunnel, {
    tool: toolPath,
    method: req.method,
    path: url.pathname,
    query: url.search.slice(1),
    headers: safeRequestHeaders(req.headers),
    body: body.toString("base64"),
  });
  if ((response.status || 502) >= 400) {
    console.warn(
      JSON.stringify({
        event: "tool_upstream_error",
        clusterId,
        tool: toolPath,
        path: url.pathname,
        status: response.status || 502,
      }),
    );
  }
  const responseBody = Buffer.from(response.body || "", "base64");
  res.writeHead(response.status || 502, {
    ...safeResponseHeaders(response.headers),
    "Content-Length": responseBody.length,
    "Cache-Control": response.headers?.["cache-control"] || "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  res.end(responseBody);
}

function handleTunnelMessage(tunnel, message) {
  if (message.type === "heartbeat") {
    tunnel.lastSeen = Date.now();
    return;
  }
  if (message.type !== "response" || typeof message.id !== "string") return;
  const request = pending.get(message.id);
  if (!request || request.clusterId !== tunnel.clusterId) return;
  pending.delete(message.id);
  request.resolve(message);
}

async function reportTunnel(connectorId, token, status) {
  await platformRequest(
    `/connectors/${encodeURIComponent(connectorId)}/tools/status`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ status, gatewayInstanceId: instanceId }),
    },
  );
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", "http://gateway.local");
    if (url.pathname === "/healthz")
      return json(res, 200, {
        status: "ok",
        instanceId,
        connectedClusters: tunnels.size,
      });
    if (req.method === "POST" && url.pathname === "/tools/session/exchange")
      return await exchangeSession(req, res);
    if (url.pathname.startsWith("/tools/clusters/"))
      return await proxyTool(req, res, url);
    return json(res, 404, { error: "Route not found." });
  } catch (error) {
    console.error(
      JSON.stringify({
        event: "gateway_request_failed",
        errorType: error?.constructor?.name || "Error",
      }),
    );
    return json(res, error.status || 502, { error: "Tool gateway unavailable." });
  }
});

server.on("upgrade", async (req, socket, head) => {
  const connectorId = String(req.headers["x-navigan-connector-id"] || "");
  const authorization = String(req.headers.authorization || "");
  const token = authorization.startsWith("Bearer ")
    ? authorization.slice(7)
    : "";
  try {
    console.log(
      JSON.stringify({
        event: "tools_tunnel_upgrade_received",
        connectorId: /^KCC-[a-f0-9]{32}$/.test(connectorId)
          ? connectorId
          : "invalid",
        path: req.url,
      }),
    );
    if (
      req.url !== "/tools/tunnel" ||
      !/^KCC-[a-f0-9]{32}$/.test(connectorId) ||
      !/^[A-Za-z0-9_-]{40,100}$/.test(token) ||
      String(req.headers.upgrade || "").toLowerCase() !== "websocket" ||
      String(req.headers["sec-websocket-version"] || "") !== "13"
    )
      throw new Error("invalid tunnel request");
    const authorized = await platformRequest(
      `/connectors/${encodeURIComponent(connectorId)}/tools/authorize`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const key = req.headers["sec-websocket-key"];
    if (!key) throw new Error("websocket key missing");
    socket.write(
      "HTTP/1.1 101 Switching Protocols\r\n" +
        "Upgrade: websocket\r\n" +
        "Connection: Upgrade\r\n" +
        `Sec-WebSocket-Accept: ${crypto
          .createHash("sha1")
          .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
          .digest("base64")}\r\n\r\n`,
    );
    const tunnel = {
      connectorId,
      token,
      clusterId: authorized.clusterId,
      lastSeen: Date.now(),
    };
    tunnel.peer = new WebSocketPeer(
      socket,
      head,
      (message) => handleTunnelMessage(tunnel, message),
      () => {
        if (tunnels.get(tunnel.clusterId) === tunnel)
          tunnels.delete(tunnel.clusterId);
        for (const [id, request] of pending) {
          if (request.clusterId !== tunnel.clusterId) continue;
          pending.delete(id);
          request.reject(new Error("cluster tunnel disconnected"));
        }
        reportTunnel(connectorId, token, "DISCONNECTED").catch(() => {});
      },
    );
    tunnels.get(tunnel.clusterId)?.peer.close();
    tunnels.set(tunnel.clusterId, tunnel);
    await reportTunnel(connectorId, token, "CONNECTED");
    console.log(
      JSON.stringify({
        event: "tools_tunnel_connected",
        connectorId,
        clusterId: tunnel.clusterId,
        instanceId,
      }),
    );
  } catch (error) {
    console.error(
      JSON.stringify({
        event: "tools_tunnel_rejected",
        connectorId: /^KCC-[a-f0-9]{32}$/.test(connectorId)
          ? connectorId
          : "invalid",
        errorType: error?.constructor?.name || "Error",
        platformStatus: error?.status || null,
      }),
    );
    socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
    socket.destroy();
  }
});

setInterval(() => {
  for (const tunnel of tunnels.values()) {
    if (Date.now() - tunnel.lastSeen > 90_000) {
      tunnel.peer.close();
      continue;
    }
    tunnel.peer.send({ type: "ping", at: Date.now() });
    reportTunnel(tunnel.connectorId, tunnel.token, "CONNECTED").catch(() =>
      tunnel.peer.close(),
    );
  }
}, 30_000).unref();

server.listen(port, "0.0.0.0", () => {
  console.log(
    JSON.stringify({ event: "tools_gateway_started", port, instanceId }),
  );
});
