#!/bin/sh
# Write the runtime config, then serve.
#
# Vite bakes VITE_* into the bundle at build time, so a built image could otherwise only
# serve the address it was built for — which is why there was no publishable frontend
# image. This writes /app/dist/config.js from the container's own environment on every
# start; index.html loads it before the app module and getEnv() (src/config/constants.ts)
# prefers it over the baked-in value.
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
  const out = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (k.startsWith("VITE_") && v !== undefined && v !== "") out[k] = v;
  }
  fs.writeFileSync(process.argv[1],
    "// Generated at container start by frontend/docker/entrypoint.sh — do not edit.\n" +
    "window.__VPT_CONFIG__ = " + JSON.stringify(out, null, 2) + ";\n");
  const keys = Object.keys(out);
  console.log(keys.length
    ? "runtime config: " + keys.length + " VITE_* value(s) -> " + keys.sort().join(", ")
    : "runtime config: no VITE_* in the environment, using the values baked into the build");
' "$CONFIG"

exec serve -s /app/dist -l 5073 --no-clipboard
