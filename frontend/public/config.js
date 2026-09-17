// Runtime configuration — overwritten by the container at start.
//
// Vite bakes `VITE_*` into the bundle at build time, which means a built image can only
// ever serve the address it was built for. This file breaks that: index.html loads it
// before the app module, and `getEnv()` in src/config/constants.ts prefers what it finds
// here over the baked-in value.
//
// Empty is the correct default: nothing is overridden, so a build made with a .env keeps
// behaving exactly as it did. The Docker image's entrypoint
// (frontend/docker/entrypoint.sh) rewrites this file from its environment, which is what
// lets one published image serve any PUBLIC_HOST.
window.__VPT_CONFIG__ = {};
