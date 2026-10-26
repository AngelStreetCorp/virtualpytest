/** Data contract of the LoL overlay: docs/agent/game/lol/OVERLAY_CONTRACT.md (coordinates normalised 0..1). */

export type LolZoneLevel = 'danger' | 'caution' | 'safe';

export interface LolZone {
  id: string;
  kind: string;
  level: LolZoneLevel;
  shape: 'circle' | 'polygon';
  /** circle: centre, r relative to the frame WIDTH */
  x?: number;
  y?: number;
  r?: number;
  /** polygon: normalised points */
  points?: [number, number][];
  reason?: string;
}

export type LolInputKind = 'left_click' | 'right_click' | 'key' | 'minimap' | 'move' | 'type_text';

export interface LolInput {
  kind: LolInputKind;
  x?: number;
  y?: number;
  key?: string;
}

export interface LolFrame {
  w: number;
  h: number;
}

export interface LolTurnState {
  hp?: number;
  hp_max?: number;
  mana?: number;
  mana_max?: number;
  level?: number;
  gold?: number;
  cs?: number;
  ad?: number;
  armor?: number;
  mr?: number;
  attack_speed?: number;
  move_speed?: number;
  items?: string[];
  pos_minimap?: [number, number];
  mode?: string;
  spells?: LolSpells;
}

export interface LolSpell {
  rank?: number | null;
  cooldown_s?: number | null;
  ready_in_s?: number | null;
  casting_for_s?: number | null;
  name?: string;
}

export type LolSpellSlot = 'Q' | 'W' | 'E' | 'R' | 'D' | 'F';
export const LOL_SPELL_SLOTS: LolSpellSlot[] = ['Q', 'W', 'E', 'R', 'D', 'F'];

export type LolSpells = Partial<Record<LolSpellSlot, LolSpell>> & {
  auto?: { attack_period_s?: number | null; next_auto_in_s?: number | null };
};

export interface LolWorldUnit {
  id: string;
  kind: 'enemy_minion' | 'ally_minion' | 'enemy_champion' | 'ally_champion' | 'enemy_turret' | 'ally_turret';
  hp_frac?: number | null;
  hp_exact?: number | null;
  selected?: boolean;
  x: number;
  y: number;
  dist_units?: number | null;
  in_attack_range?: boolean;
  walk_eta_s?: number | null;
  type?: 'melee' | 'caster' | 'cannon' | null;
  type_source?: string;
  champion?: string;
  level?: number | null;
}

export interface LolWorld {
  units?: LolWorldUnit[];
  summary?: {
    counts?: Record<string, number>;
    within_500_units?: Record<string, number>;
  };
}

export interface LolDecision {
  choice?: string;
  options?: { id: string; p: number }[];
  reason?: string;
}

export interface LolZonesLine {
  t: number;
  frame?: LolFrame;
  zones: LolZone[];
}

export interface LolOutcome {
  event: string;
  value: number;
  t?: number;
  cause_turn?: number;
  cause_action?: string;
  confidence?: number;
}

export interface LolTurnLine {
  /** Scored runs only: */
  reward?: number;
  return_8s?: number;
  outcomes?: LolOutcome[];
  t: number;
  turn?: number;
  state?: LolTurnState;
  decision?: LolDecision;
  inputs?: LolInput[];
  world?: LolWorld;
}

/** An input to draw, with its age in seconds (markers fade out by LOL_MARKER_TTL_S). */
export interface LolMarker extends LolInput {
  age: number;
}

/** Content of lol-overlay-live.json. */
export interface LolLiveData {
  t: number;
  frame?: LolFrame;
  zones: LolZone[];
  recent_inputs: (LolInput & { age_s: number })[];
  state?: LolTurnState;
  decision?: LolDecision;
  world?: LolWorld;
}

export const LOL_MARKER_TTL_S = 1.5;
/** Garen's feet on the 1920x1200 frame (camera locked on him). */
export const LOL_GAREN_FEET: [number, number] = [868 / 1920, 545 / 1200];
