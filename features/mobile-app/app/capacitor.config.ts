import type { CapacitorConfig } from '@capacitor/cli';

// One APK for every deployment: the bundled web build (frontend/dist) is generic, and the
// server/Supabase URLs are injected at runtime from native SharedPreferences — see
// MainActivity.kt and frontend/src/config/runtimeConfig.ts. Do not hard-code a server here.
const config: CapacitorConfig = {
  appId: 'io.virtualpytest.app',
  appName: 'VirtualPyTest',
  webDir: '../../../frontend/dist',
  android: {
    // LAN hosts (host_api_url) are plain http:// — mixed content must be allowed.
    allowMixedContent: true,
  },
};

export default config;
