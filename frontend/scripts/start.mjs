import { spawn } from "node:child_process";
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const standalone = join(frontend, ".next", "standalone");
const runtime = join(frontend, `.standalone-runtime-${process.pid}`);
const builtServer = join(standalone, "server.js");

if (!existsSync(builtServer)) {
  console.error("Production build not found. Run `npm run build` first.");
  process.exit(1);
}

cpSync(standalone, runtime, { recursive: true, force: true });

const copyDirectory = (source, destination) => {
  if (!existsSync(source)) return;
  mkdirSync(destination, { recursive: true });
  cpSync(source, destination, { recursive: true, force: true });
};

copyDirectory(
  join(frontend, ".next", "static"),
  join(runtime, ".next", "static"),
);
copyDirectory(join(frontend, "public"), join(runtime, "public"));
for (const name of [
  ".env",
  ".env.local",
  ".env.production",
  ".env.production.local",
]) {
  const source = join(frontend, name);
  if (existsSync(source)) cpSync(source, join(runtime, name), { force: true });
}

const child = spawn(process.execPath, [join(runtime, "server.js")], {
  cwd: runtime,
  stdio: "inherit",
  env: {
    ...process.env,
    HOSTNAME: process.env.HOSTNAME || "0.0.0.0",
    PORT: process.env.PORT || "3000",
  },
});

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
