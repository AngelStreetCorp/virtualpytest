import { createClient } from '@supabase/supabase-js';

// Get environment variables (lazy evaluation)
// Option 1: Add to frontend/.env: VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
// Option 2: Leave empty to disable auth completely (no login required)
const getSupabaseUrl = () => (import.meta as any).env?.VITE_SUPABASE_URL || '';
const getSupabaseAnonKey = () => (import.meta as any).env?.VITE_SUPABASE_ANON_KEY || '';

// Check if auth is enabled (credentials provided) - lazy evaluation
export const isAuthEnabled = !!(getSupabaseUrl() && getSupabaseAnonKey());

if (!isAuthEnabled) {
  console.error(
    '[SECURITY][OPEN_MODE] Supabase authentication is DISABLED: missing VITE_SUPABASE_URL and/or VITE_SUPABASE_ANON_KEY. ' +
      'Frontend -> Server API requests will be sent without JWT Authorization headers.'
  );
} else {
  console.info('[SECURITY] Supabase authentication enabled. Frontend -> Server API requests can use JWT.');
}

// Create Supabase client (with dummy values if auth disabled)
export const supabase = createClient(
  getSupabaseUrl() || 'https://placeholder.supabase.co',
  getSupabaseAnonKey() || 'placeholder-key',
  {
    auth: {
      autoRefreshToken: isAuthEnabled,
      persistSession: isAuthEnabled,
      detectSessionInUrl: isAuthEnabled,
    },
  }
);

// Database types for better type safety
export type Database = {
  public: {
    Tables: {
      profiles: {
        Row: {
          id: string;
          email: string | null;
          full_name: string | null;
          avatar_url: string | null;
          role: 'admin' | 'tester' | 'viewer';
          permissions: string[];
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id: string;
          email?: string | null;
          full_name?: string | null;
          avatar_url?: string | null;
          role?: 'admin' | 'tester' | 'viewer';
          permissions?: string[];
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          id?: string;
          email?: string | null;
          full_name?: string | null;
          avatar_url?: string | null;
          role?: 'admin' | 'tester' | 'viewer';
          permissions?: string[];
          created_at?: string;
          updated_at?: string;
        };
      };
    };
  };
};
