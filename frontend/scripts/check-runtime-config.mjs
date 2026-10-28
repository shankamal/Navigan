// One compiled standalone artifact, two fresh processes, no rebuild in between.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import net from "node:net";
import { fileURLToPath } from "node:url";

const server = fileURLToPath(
  new URL("../.next/standalone/server.js", import.meta.url),
);
const digest = async () =>
  createHash("sha256")
    .update(await readFile(server))
    .digest("hex");
const original = await digest();
for (const name of ["dev", "prod"]) {
  const reservation = net.createServer();
  await new Promise((resolve) => reservation.listen(0, "127.0.0.1", resolve));
  const port = reservation.address().port;
  await new Promise((resolve, reject) =>
    reservation.close((error) => (error ? reject(error) : resolve())),
  );
  const child = spawn(process.execPath, [server], {
    env: {
      ...process.env,
      NODE_ENV: "production",
      HOSTNAME: "127.0.0.1",
      PORT: String(port),
      NAVIGAN_PUBLIC_OIDC_AUTHORITY: `https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_${name}Fixture`,
      NAVIGAN_PUBLIC_OIDC_CLIENT_ID: `${name}fixtureclient`,
      NAVIGAN_PUBLIC_APP_URL: `https://${name}.example.invalid`,
    },
    stdio: "ignore",
  });
  try {
    let config;
    const deadline = Date.now() + 60_000;
    while (Date.now() < deadline) {
      assert.equal(
        child.exitCode,
        null,
        "Standalone server exited before verification",
      );
      try {
        const response = await fetch(
          `http://127.0.0.1:${port}/api/runtime-config`,
          { signal: AbortSignal.timeout(2000) },
        );
        if (response.ok) {
          config = await response.json();
          break;
        }
      } catch {
        /* wait for startup */
      }
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    assert.equal(config?.oidcClientId, `${name}fixtureclient`);
    assert.equal(config?.appUrl, `https://${name}.example.invalid`);
    assert.equal(config?.migrationUiPreview, false);
    assert.equal((await fetch(`http://127.0.0.1:${port}/healthz`)).status, 200);
    assert.equal((await fetch(`http://127.0.0.1:${port}/login`)).status, 200);
    assert.equal(await digest(), original);
  } finally {
    if (child.exitCode === null) {
      child.kill("SIGTERM");
      await new Promise((resolve) => child.once("exit", resolve));
    }
  }
}
console.log(
  "Same standalone artifact passed DEV and PROD fixture runtime configuration checks; no AWS deployment.",
);
