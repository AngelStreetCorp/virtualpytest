import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';
import { defineConfig, loadEnv } from 'vite';
import type { Plugin } from 'vite';

// Load .env file for vite.config.ts (Vite only auto-loads for client code)
const env = loadEnv('development', process.cwd(), 'VITE_');

// Read VERSION.txt for build-time version display.
// Support both repo-root builds and frontend-only build contexts.
const versionFileCandidates = [
  path.resolve(process.cwd(), '..', 'VERSION.txt'),
  path.resolve(process.cwd(), '..', 'version.txt'),
  path.resolve(process.cwd(), 'VERSION.txt'),
  path.resolve(process.cwd(), 'version.txt'),
  path.resolve(process.cwd(), 'public', 'version.txt'),
];

let appVersionRaw = 'unknown';
let appVersionDisplay = 'unknown';

for (const versionFilePath of versionFileCandidates) {
  try {
    if (!fs.existsSync(versionFilePath)) {
      continue;
    }

    const versionContent = fs.readFileSync(versionFilePath, 'utf8');
    const lines = versionContent.split(/\r?\n/).map((line) => line.trim());
    const firstNonEmpty = lines.find((line) => line.length > 0);
    if (!firstNonEmpty) {
      continue;
    }

    const currentLine = lines.find((line) => /^current\s*:/i.test(line));
    const explicitDisplayLine = lines.find((line) => /^(semver|version|readable)\s*:/i.test(line));

    if (currentLine) {
      const value = currentLine.split(':').slice(1).join(':').trim();
      appVersionRaw = value || firstNonEmpty;
      appVersionDisplay = appVersionRaw;
    } else if (explicitDisplayLine) {
      const value = explicitDisplayLine.split(':').slice(1).join(':').trim();
      appVersionRaw = firstNonEmpty;
      appVersionDisplay = value || appVersionRaw;
    } else {
      appVersionRaw = firstNonEmpty;
      appVersionDisplay = appVersionRaw;
    }

    console.log(`📦 Frontend version source: ${versionFilePath}`);
    break;
  } catch {
    // Try the next candidate.
  }
}

// Server URLs from .env (with localhost defaults for local dev)
const serverUrl = env.VITE_SERVER_URL || 'http://localhost:5109';
const hostUrl = env.VITE_HOST_URL || 'http://localhost:6109';

// HTTPS control via env var (default: true for noVNC compatibility)
const useHttps = env.VITE_HTTPS !== 'false';

// Only enable Vite proxy for localhost (local development)
const isLocalDev = serverUrl.includes('localhost') || serverUrl.includes('127.0.0.1');

console.log(`🔗 Server URL: ${serverUrl}`);
console.log(`🔒 HTTPS: ${useHttps ? 'enabled' : 'disabled'}`);
console.log(`📡 Vite proxy: ${isLocalDev ? 'enabled (local dev)' : 'disabled (external URL)'}`);

const shouldUseHttps = serverUrl.startsWith('https://');

// Detect if we're running locally
const isLocalDevelopment = !process.env.CI && isLocalDev;

// Get user home directory dynamically
const userHome = process.env.HOME || process.env.USERPROFILE || process.cwd();

// Certificate paths - check multiple locations
const certificatePaths = [
  // User-specific certificate paths (dynamic)
  {
    cert: `${userHome}/vite-certs/fullchain.pem`,
    key: `${userHome}/vite-certs/privkey.pem`
  },
  {
    cert: `${userHome}/.ssl/cert.pem`,
    key: `${userHome}/.ssl/key.pem`
  },
  // Project-relative certificate paths
  {
    cert: 'cert.pem',
    key: 'key.pem'
  },
  {
    cert: 'ssl/cert.pem',
    key: 'ssl/key.pem'
  },
  {
    cert: 'certs/cert.pem',
    key: 'certs/key.pem'
  },
  // Environment-specific paths
  {
    cert: process.env.SSL_CERT_PATH || '',
    key: process.env.SSL_KEY_PATH || ''
  },
  // System certificate paths
  {
    cert: '/etc/ssl/certs/server.crt',
    key: '/etc/ssl/private/server.key'
  }
];

// Find available and readable certificates
let certPath = '';
let keyPath = '';
let hasCertificates = false;

for (const paths of certificatePaths) {
  // Skip empty paths from environment variables
  if (!paths.cert || !paths.key) {
    continue;
  }
  if (fs.existsSync(paths.cert) && fs.existsSync(paths.key)) {
    // Check if we can actually read the files (permission check)
    try {
      fs.accessSync(paths.cert, fs.constants.R_OK);
      fs.accessSync(paths.key, fs.constants.R_OK);
      certPath = paths.cert;
      keyPath = paths.key;
      hasCertificates = true;
      console.log(`✅ SSL certificates found and readable: ${certPath}`);
      break;
    } catch {
      console.log(`⚠️ SSL certificates found but not readable: ${paths.cert} (permission denied)`);
      // Continue to next path
    }
  }
}

if (!hasCertificates) {
  console.log('ℹ️ Using auto-generated self-signed certificate (basicSsl plugin)');
}

// Kill any process using port 5073 synchronously
// Only run this during dev mode (npm run dev), not during build
const killPort5073 = () => {
  // Skip in production build or if lsof command doesn't exist
  if (process.env.NODE_ENV === 'production' || process.argv.includes('build')) {
    return;
  }

  try {
    const pids = execSync('lsof -ti:5073', { encoding: 'utf8' }).trim();
    if (pids) {
      console.log('🛑 Killing processes on port 5073...');
      execSync(`kill -9 ${pids}`, { encoding: 'utf8' });
      console.log('✅ Port 5073 is now available');
      // Wait a moment for the port to be fully released
      execSync('sleep 1');
    } else {
      console.log('✅ Port 5073 is already available');
    }
  } catch (error) {
    // No processes found on port 5073 or lsof command not available (e.g., Vercel)
    // Both cases are fine - just continue
  }
};

// Kill port before starting dev server - this will block until complete
killPort5073();

// Define registered frontend routes (must match your React Router routes)
const registeredRoutes = [
  '/',
  '/device-control',
  '/test-plan/test-cases',
  '/test-plan/campaigns',
  '/test-plan/collections',
  '/test-execution/run-tests',
  '/test-execution/monitoring',
  '/test-results/reports',
  '/test-results/model-reports',
  '/test-results/dependency-report',
  '/configuration',
  '/configuration/',
  '/configuration/devices',
  '/configuration/models',
  '/configuration/interface',
  '/configuration/controller',
  '/configuration/library',
  '/configuration/environment',
  // AI Agent routes
  '/ai-agent',
  '/agent-dashboard',
  // Dynamic routes patterns
  '/navigation-editor', // Will match /navigation-editor/* paths
  '/docs', // Will match /docs/* paths for documentation including security reports
];

// Load local overrides if they exist (git-ignored file for user-specific config)
let localOverrides: {
  allowedHosts?: string[];
  cspFrameAncestors?: string[];
  corsOrigin?: boolean | string | string[];
} = {};

try {
  const localConfigPath = path.resolve(process.cwd(), 'vite.config.local.json');
  if (fs.existsSync(localConfigPath)) {
    const localConfig = fs.readFileSync(localConfigPath, 'utf8');
    localOverrides = JSON.parse(localConfig);
    console.log('✅ Loaded local config overrides from vite.config.local.json');
  }
} catch (error) {
  console.log('ℹ️ No local config overrides found (vite.config.local.json)');
}

// ─── Optional features (docs/technical/FEATURES.md) ──────────────────────────
// Generates the `virtual:vpt-features` module consumed by src/config/features.ts:
// one static import per `features/<name>/frontend/routes.tsx` whose folder has a
// manifest.json and whose name is not in VITE_DISABLED_FEATURES. Disabled features
// are never imported, so their pages are not part of the bundle.
function vptFeaturesPlugin(): Plugin {
  const VIRTUAL_ID = 'virtual:vpt-features';
  const RESOLVED_ID = '\0' + VIRTUAL_ID;
  const frontendRoot = path.resolve(process.cwd());
  const featuresDir = path.resolve(frontendRoot, '..', 'features');
  const disabledRaw = process.env.VITE_DISABLED_FEATURES ?? env.VITE_DISABLED_FEATURES ?? '';
  const disabled = new Set(disabledRaw.split(',').map((s) => s.trim()).filter(Boolean));

  const entries: { name: string; file: string }[] = [];
  if (fs.existsSync(featuresDir)) {
    for (const name of fs.readdirSync(featuresDir).sort()) {
      const manifest = path.join(featuresDir, name, 'manifest.json');
      const routes = path.join(featuresDir, name, 'frontend', 'routes.tsx');
      if (!fs.existsSync(manifest) || !fs.existsSync(routes)) continue;
      if (disabled.has(name)) {
        console.log(`⏭️  Feature "${name}" disabled via VITE_DISABLED_FEATURES — not bundled`);
        continue;
      }
      entries.push({ name, file: routes });
    }
  }
  if (entries.length) console.log(`🧩 Features bundled: ${entries.map((e) => e.name).join(', ')}`);

  return {
    name: 'vpt-features',
    async resolveId(source, importer, options) {
      if (source === VIRTUAL_ID) return RESOLVED_ID;
      // Feature files live outside frontend/, so bare imports (react, @mui/...) would not
      // find frontend/node_modules by walking up. Resolve them as if imported from src/.
      if (
        importer &&
        importer.startsWith(featuresDir) &&
        !source.startsWith('.') &&
        !source.startsWith('/') &&
        !source.startsWith('\0')
      ) {
        return this.resolve(source, path.join(frontendRoot, 'src', 'main.tsx'), {
          ...options,
          skipSelf: true,
        });
      }
      return null;
    },
    load(id) {
      if (id !== RESOLVED_ID) return null;
      const imports = entries
        .map((e, i) => `import f${i} from ${JSON.stringify(e.file)};`)
        .join('\n');
      const list = entries.map((e, i) => `{ name: ${JSON.stringify(e.name)}, entry: f${i} }`).join(', ');
      return `${imports}\nexport const features = [${list}];\n`;
    },
  };
}

// ─── Runtime config for the mobile app (features/mobile-app) ───────────────────
// Emits dist/runtime-config.json with the PUBLIC values the web bundle already ships
// (Supabase URL + anon key, project name). The Android app scans a QR that carries only
// the server URL and fetches this file, which keeps the QR small enough for a phone
// camera. Nothing secret goes here — these strings are in the JS bundle anyway.
function vptRuntimeConfigPlugin(): Plugin {
  const FILE = 'runtime-config.json';
  const body = () =>
    JSON.stringify(
      {
        v: 1,
        supabase_url: process.env.VITE_SUPABASE_URL ?? env.VITE_SUPABASE_URL ?? '',
        supabase_anon_key: process.env.VITE_SUPABASE_ANON_KEY ?? env.VITE_SUPABASE_ANON_KEY ?? '',
        project_name: (process.env.VITE_PROJECT_NAME ?? env.VITE_PROJECT_NAME ?? '').trim() || 'VirtualPyTest',
        server_url: process.env.VITE_SERVER_URL ?? env.VITE_SERVER_URL ?? '',
      },
      null,
      2,
    );
  return {
    name: 'vpt-runtime-config',
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: FILE, source: body() });
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split('?')[0] === `/${FILE}`) {
          res.setHeader('Content-Type', 'application/json');
          res.end(body());
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(appVersionDisplay),
    __APP_VERSION_RAW__: JSON.stringify(appVersionRaw),
  },
  plugins: [
    react(),
    vptFeaturesPlugin(),
    vptRuntimeConfigPlugin(),
    // Auto-generate self-signed SSL certificate for HTTPS dev server
    // Required for noVNC to work (needs secure context for Web Crypto API)
    // Controlled by VITE_HTTPS env var (default: true)
    ...(useHttps ? [basicSsl()] : []),
    // Custom plugin for route validation
    {
      name: 'route-validator',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const url = req.url || '';

          // Skip static assets, API routes, and other proxied paths
          if (
            url.startsWith('/assets/') ||
            url.startsWith('/server/') ||
            url.startsWith('/host/') ||
            url.startsWith('/stream/') || // HLS stream proxy
            url.startsWith('/websockify') ||
            url.startsWith('/docs/') ||  
            url.includes('.') // Static files (js, css, images, etc.)
          ) {
            return next();
          }
          

          // Check if the route is registered
          const isRegisteredRoute = registeredRoutes.some((route) => {
            if (route === url) return true;
            if (route.endsWith('/') && url.startsWith(route)) return true;
            if (route === '/navigation-editor' && url.startsWith('/navigation-editor/'))
              return true;
            if (route === '/docs' && url.startsWith('/docs/'))
              return true;
            return false;
          });

          if (!isRegisteredRoute) {
            // Return 404 for unregistered routes
            res.statusCode = 404;
            res.setHeader('Content-Type', 'text/html');
            res.end(`
              <!DOCTYPE html>
              <html>
                <head>
                  <title>404 - Page Not Found</title>
                  <meta name="robots" content="noindex">
                </head>
                <body>
                  <h1>404 - Page Not Found</h1>
                  <p>The requested page does not exist.</p>
                  <a href="/">Return to Dashboard</a>
                </body>
              </html>
            `);
            return;
          }

          next();
        });
      },
    },
  ],
  server: {
    host: '0.0.0.0',
    port: 5073,
    strictPort: true, // Don't try other ports if 5073 is unavailable
    allowedHosts: [
      'virtualpytest.com',
      'www.virtualpytest.com',
      'dev.virtualpytest.com',
      'virtualpytest.angelstreet.io',
      'virtualpytest-server.onrender.com',
      'virtualpytest.vercel.app',
      '*.vercel.app',
      'localhost',
      '127.0.0.1',
      '192.168.1.103',
      '192.168.1.34',
      'virtualpytest.qualiai.io',
      // Merge in local overrides from vite.config.local.json
      ...(localOverrides.allowedHosts || [])
    ],
    // HTTPS controlled by VITE_HTTPS env var (default: true for noVNC)
    // Set VITE_HTTPS=false in .env to disable
    ...(useHttps
      ? { https: hasCertificates ? { key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) } : {} }
      : {}),
    // HMR configuration - check VITE_HMR_PORT env var first, then fallback to defaults
    hmr: {
      clientPort: env.VITE_HMR_PORT ? parseInt(env.VITE_HMR_PORT) : (isLocalDevelopment ? 5073 : 443),
    },
    // Configure how the dev server handles routing
    // strict:true (Vite default) keeps the dev server's file-read boundary at
    // the project root — strict:false let a remote request read arbitrary
    // files off disk (e.g. /etc/services, /proc/1/environ) via the module
    // transform pipeline. Never disable this on an internet-reachable server.
    fs: {
      strict: true,
    },
    // Configure CORS headers for cross-origin requests (including Grafana embedding)
    cors: {
      origin: localOverrides.corsOrigin !== undefined ? localOverrides.corsOrigin : true, // Allow all origins in development (can override in vite.config.local.json)
      credentials: true, // Allow cookies to be sent with requests
    },
    // Add headers to support embedding in iframes and mixed content
    headers: {
      'X-Frame-Options': 'SAMEORIGIN',
      // Local dev: Remove upgrade-insecure-requests to allow HTTP
      'Content-Security-Policy': (() => {
        const defaultFrameAncestors = shouldUseHttps
          ? "'self' http://localhost:3000 https://localhost:3000 https://dev.virtualpytest.com https://virtualpytest.com"
          : "'self' http://localhost:3000 http://localhost:6109";

        // Merge local overrides for frame-ancestors
        const customFrameAncestors = localOverrides.cspFrameAncestors?.join(' ') || '';
        const frameAncestors = customFrameAncestors
          ? `${defaultFrameAncestors} ${customFrameAncestors}`
          : defaultFrameAncestors;

        return shouldUseHttps
          ? `frame-ancestors ${frameAncestors}; upgrade-insecure-requests`
          : `frame-ancestors ${frameAncestors}`;
      })(),
    },
    // Proxy configuration for local development only
    // When using external URL (nginx), frontend calls that URL directly
    ...(isLocalDev ? {
      proxy: {
        // HLS stream files (m3u8, ts segments) from backend_host
        '/stream': {
          target: hostUrl,
          changeOrigin: true,
          secure: false,
          rewrite: (path) => `/host${path}`,
        },
        // Server API routes
        '/server': {
          target: serverUrl,
          changeOrigin: true,
          secure: false,
        },
        // Host API routes
        '/host': {
          target: hostUrl,
          changeOrigin: true,
          secure: false,
        },
      },
    } : {}),
  },
  // Configure build for proper SPA handling
  build: {
    rollupOptions: {
      input: {
        main: './index.html',
      },
      output: {
        // Split out the vendor libraries that the always-mounted app shell
        // (providers in App.tsx/main.tsx) pulls in eagerly, so they land in
        // their own cacheable chunks instead of inflating the single `main`
        // entry chunk. Deliberately NOT a catch-all `node_modules` bucket —
        // libraries only used by lazy-loaded pages (reactflow, dagre,
        // hls.js, ...) should stay wherever Rollup's automatic chunking
        // already puts them, so they keep loading only when that page does.
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;
          if (id.includes('@mui') || id.includes('@emotion')) return 'vendor-mui';
          if (id.includes('/react-router')) return 'vendor-router';
          if (id.includes('/react/') || id.includes('/react-dom/') || id.includes('/scheduler/')) {
            return 'vendor-react';
          }
          if (id.includes('@tanstack')) return 'vendor-query';
          if (id.includes('@supabase')) return 'vendor-supabase';
          if (id.includes('socket.io-client') || id.includes('engine.io-client')) return 'vendor-socket';
          return undefined;
        },
      },
    },
  },
});
