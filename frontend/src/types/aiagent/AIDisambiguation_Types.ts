/**
 * AI Prompt Disambiguation Types
 * 
 * Types for the AI validation and learning system that handles
 * ambiguous navigation node references in user prompts.
 */

/**
 * Single ambiguous reference with suggested matches
 */
export interface Ambiguity {
  original: string;           // The ambiguous phrase (e.g., "live fullscreen")
  suggestions: string[];      // Suggested node names
  step_index?: number;        // Which step in the plan (for post-validation)
}

/**
 * Auto-correction that was applied
 */
export interface AutoCorrection {
  from: string;              // Original phrase
  to: string;                // Corrected node name
  source: 'learned' | 'fuzzy'; // How it was corrected
}

/**
 * Disambiguation data from pre-processing
 */
export interface DisambiguationData {
  status: 'needs_disambiguation';
  original_prompt: string;
  ambiguities: Ambiguity[];
  auto_corrections?: AutoCorrection[];
  available_nodes?: string[];  // For manual edit mode
}

/**
 * Auto-correction notification data
 */
export interface AutoCorrectionData {
  status: 'auto_corrected';
  original_prompt: string;
  corrected_prompt: string;
  corrections: AutoCorrection[];
}

/**
 * Learned mapping from database
 */
export interface LearnedMapping {
  id: string;
  user_phrase: string;
  resolved_node: string;
  usage_count: number;
  last_used_at: string;
  created_at: string;
  userinterface_name: string;
  team_id: string;
}

/**
 * User selection for disambiguation
 */
export interface DisambiguationSelection {
  phrase: string;
  resolved: string;
}

/**
 * Analysis response from backend
 */
export interface PromptAnalysisResponse {
  success: boolean;
  analysis?: DisambiguationData | AutoCorrectionData | { status: 'clear'; prompt: string };
  available_nodes?: string[];
  error?: string;
}

/**
 * Save disambiguation response
 */
export interface SaveDisambiguationResponse {
  success: boolean;
  saved_count: number;
  message?: string;
  error?: string;
}

/**
 * Get mappings response
 */
export interface GetMappingsResponse {
  success: boolean;
  mappings: LearnedMapping[];
  stats?: {
    total_mappings: number;
    team_id: string;
    userinterface_name: string;
  };
  error?: string;
}
