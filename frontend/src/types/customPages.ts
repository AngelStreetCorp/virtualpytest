/** Custom pages (TASK-139): a saved page is a list of catalogue blocks, validated by the server. */

export type BlockType =
  | 'device_picker'
  | 'node_goto'
  | 'localize_result'
  | 'stream'
  | 'recent_runs'
  | 'report'
  | 'text';

export interface PageBlock {
  id: string;
  type: BlockType;
  /** First column (0..5) and width (1..6) on the 6-column grid. */
  x: number;
  w: number;
  settings: Record<string, string | number | boolean>;
}

export interface PageDefinition {
  schema_version: number;
  blocks: PageBlock[];
}

export type PageAccess = 'owner' | 'edit' | 'view';

export interface BlockState {
  available: boolean;
  missing: string[];
}

export interface CustomPageSummary {
  id: string;
  title: string;
  owner_id: string;
  status: 'draft' | 'saved';
  visibility: 'private' | 'team';
  access: PageAccess;
  block_count: number;
  created_at?: string;
  updated_at?: string;
}

export interface CustomPage extends CustomPageSummary {
  definition: PageDefinition;
  /** Per block id: may the current viewer use it (their own rights), and what is missing. */
  block_states: Record<string, BlockState>;
}

export type SettingSpec =
  | { type: 'enum'; values: string[]; default?: string }
  | { type: 'string'; max: number; default?: string }
  | { type: 'int'; min: number; max: number; default?: number }
  | { type: 'bool'; default?: boolean }
  | { type: 'uuid'; required?: boolean }
  | { type: 'ref'; ref_type: BlockType; optional?: boolean };

export interface CatalogueBlock {
  type: BlockType;
  title: string;
  description: string;
  requires: string[];
  default_width: number;
  settings: Record<string, SettingSpec>;
  /** Locked blocks only: the permissions the caller lacks, and the reason shown to them. */
  missing?: string[];
  reason?: string;
}

export interface Catalogue {
  available: CatalogueBlock[];
  unavailable: CatalogueBlock[];
  grid_columns: number;
  schema_version: number;
}

export interface SharingMember {
  user_id: string;
  name: string;
  email?: string | null;
  role?: string | null;
  shared: boolean;
  can_edit: boolean;
  /** How many of the page's blocks this person would see locked (null: unknown). */
  locked_blocks: number | null;
}

export interface Sharing {
  visibility: 'private' | 'team';
  status: 'draft' | 'saved';
  block_count: number;
  members: SharingMember[];
  team_locked_max: number;
}

export type PageOp =
  | { op: 'add_block'; type: BlockType; settings?: PageBlock['settings']; x?: number; w?: number; id?: string }
  | { op: 'remove_block'; id: string }
  | { op: 'set_setting'; id: string; key: string; value: string | number | boolean }
  | { op: 'move_block'; id: string; x?: number; w?: number; to_index?: number };
