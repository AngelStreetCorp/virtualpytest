// Simple model interface matching database
export interface Model {
  id: string;
  name: string;
  types: string[];
  version: string;
  description: string;
  is_default?: boolean; // Flag to indicate if model is a system default
  created_at?: string;
  updated_at?: string;
}

// Create payload type
export interface ModelCreatePayload {
  name: string;
  types: string[];
  version: string;
  description: string;
}
