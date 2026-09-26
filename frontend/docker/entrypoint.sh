#!/bin/sh
# Write the runtime config, then serve.
#
# Vite bakes VITE_* into the bundle at build time, so a built image could otherwise only
# serve the address it was built for — which is why there was no publishable frontend
# image. This writes /app/dist/config.js from the container's own environment on every
# start; index.html loads it before the app module and getEnv() (src/config/constants.ts)
# prefers it over the baked-in value.
# The script URL includes a hash of the generated config so browsers with an older
# cached config.js fetch the new one after a container configuration change.
#
# Every VITE_* variable present in the environment is passed through, so a new setting
# needs no change here. An unset variable is simply absent, and getEnv falls back to
# whatever the build had.
set -eu

CONFIG=/app/dist/config.js

# node, not shell, so values containing quotes, backslashes or newlines are escaped
# correctly rather than producing a JS syntax error that blanks the whole page.
node -e '
  const fs = require("fs");
  const crypto = require("crypto");
  const out = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (k.startsWith("VITE_") && v !== undefined && v !== "") out[k] = v;
  }
  const config =
    "// Generated at container start by frontend/docker/entrypoint.sh — do not edit.\n" +
    "window.__VPT_CONFIG__ = " + JSON.stringify(out, null, 2) + ";\n";
  fs.writeFileSync(process.argv[1], config);
  const version = crypto.createHash("sha256").update(config).digest("hex").slice(0, 12);
  const indexPath = "/app/dist/index.html";
  const index = fs.readFileSync(indexPath, "utf8");
  const scriptTag = /<script src="\/config\.js(?:\?v=[^"]*)?"><\/script>/;
  if (!scriptTag.test(index)) throw new Error("Runtime config script tag missing from index.html");
  fs.writeFileSync(indexPath, index.replace(scriptTag, `<script src="/config.js?v=${version}"></script>`));
  const keys = Object.keys(out);
  console.log(keys.length
    ? "runtime config: " + keys.length + " VITE_* value(s) -> " + keys.sort().join(", ")
    : "runtime config: no VITE_* in the environment, using the values baked into the build");
' "$CONFIG"

exec serve -s /app/dist -l 5073 --no-clipboard
