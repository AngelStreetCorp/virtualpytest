/**
 * Live-TV companion result (TASK-05): what features/companion/backend_host/companion.py
 * result() returns, served by POST /server/companion/latest.
 */

export type CompanionScreen =
  | 'home'
  | 'menu'
  | 'settings'
  | 'live_tv'
  | 'vod_playback'
  | 'advertisement'
  | 'loading'
  | 'error_no_signal';

/** A scoring event, shaped like Labox's MatchEvent (labox-website/src/lib/scoresFixtures.ts);
 * the type set is per sport profile (soccer goal, rugby try / conversion / penalty / penalty_try). */
export interface CompanionMatchEvent {
  minute: number;
  type: 'goal' | 'yellow_card' | 'red_card' | 'try' | 'conversion' | 'penalty' | 'penalty_try' | string;
  home: boolean;
  points?: number;
  player: string | null; // not read from the score bug; filled by a later level
  penalty?: boolean;
}

/** Live match state, shaped like Labox's ScoreFixture plus a 'paused' status (bug hidden / ad). */
export interface CompanionFixture {
  id: string;
  league: string;
  homeTeam: string;
  awayTeam: string;
  homeScore: number;
  awayScore: number;
  minute: number | null;
  clock?: string | null;
  period?: string | null; // 'HT', 'Q4', 'OT'... when the bug shows one
  status: 'scheduled' | 'live' | 'finished' | 'paused';
  events: CompanionMatchEvent[];
}

/** Facts looked up on the web once per programme. A fact is either sourced or null. */
export interface CompanionFacts {
  status: 'pending' | 'ready' | 'failed' | 'skipped';
  facts: Record<string, string | string[] | null>;
  sources: { url: string; title?: string }[];
  error?: string;
}

/** One scored sentence from the live meter (TASK-45). */
export interface CompanionMeterSentence {
  text: string;
  scores: {
    factual_claim?: number;
    evasive?: number;
    contradicts_self?: number;
    emotional_appeal?: number;
    dodged_question?: number;
  };
  speaker: string | null;
  speaker_p?: number | null;
  t?: number;
  end_at?: number;
  ms?: number;
  check?: CompanionClaim['check'];
}

/** Per-speaker running averages shown in the side panels. */
export interface CompanionMeterSpeaker {
  name: string;
  n: number;
  avg: CompanionMeterSentence['scores'];
  /** 0-100 index = mean of evasive / emotional_appeal / contradicts_self / dodged_question. */
  index: number;
}

/** The live meter payload returned with the companion result (TASK-45). */
export interface CompanionMeter {
  sentences: CompanionMeterSentence[];
  speakers: CompanionMeterSpeaker[];
  /** Jev latency (ms) of the newest scored sentence. */
  last_ms?: number;
}

export interface CompanionResult {
  screen?: CompanionScreen;
  category?: string | null; // sport | movie | series | news | ... (playback screens only)
  subcategory?: string | null; // soccer | rugby | ...
  entity?: Record<string, string>; // title, home_team, away_team, competition, season, episode, year
  banner?: Record<string, string> | null;
  confidence?: number | null;
  profile?: string | null; // e.g. 'sport/soccer'
  template?: 'match' | 'title' | 'summary' | 'debate' | 'label';
  ts?: number | null; // unix seconds of the identify call (the verdict may be older than the frame)
  changed_at?: number;
  error?: string;
  /** Set while the companion waits before calling the model again (saturated or failing). */
  backoff?: { reason: 'busy' | 'error' | null; retry_in_s: number };
  facts?: CompanionFacts;
  live?: CompanionFixture;
  /** Films / series on linear TV: position in the broadcast slot read from the banner. */
  progress?: { start: string; end: string; total_min: number; elapsed_min: number; remaining_min: number };
  /** Text the broadcaster shows: lower third (who is on screen), headline strap, ticker. */
  on_screen?: { lower_third: { name: string; role: string | null } | null; headline: string | null; ticker: string | null };
  /** Everyone named by a lower third during this programme. */
  roster?: { name: string; role: string | null }[];
  /** Topic straps the channel showed (debate / news), newest first. */
  topics?: { text: string; first_seen: number; last_seen: number }[];
  /** Digest of the last minutes of transcript + on-screen text: news stories, or a debate digest. */
  digest?: {
    at: number;
    window_min: number;
    lines: number;
    // news
    stories?: CompanionStory[];
    sensitive?: { flag: boolean; reason: string | null };
    // debate
    topic?: string | null;
    positions?: { speaker: string | null; stance: string }[];
    claims?: CompanionClaim[];
  };
  /** Sentence meter (TASK-45): per-sentence Jev scores + per-speaker averages. */
  meter?: CompanionMeter;
}

/** A claim from a debate digest; `check` is set when fact checking is on for the device. */
export interface CompanionClaim {
  text: string;
  speaker: string | null;
  checkable: boolean;
  at?: number;
  check?: {
    status: 'pending' | 'done' | 'failed' | 'capped' | 'skipped';
    /** Why the Jev gate skipped this claim (TASK-45): ``vague`` when P(specific) was below the
     * threshold, ``repeat`` when the claim restates an already-checked one. Only present when
     * status is ``skipped``. */
    reason?: 'vague' | 'repeat';
    /** supported / contradicted always come with at least one source; anything else is unverified. */
    verdict?: 'supported' | 'contradicted' | 'unverified';
    note?: string | null;
    sources?: { url: string; title: string }[];
  };
}

export interface CompanionStory {
  headline: string;
  summary: string;
  people: string[];
  places: string[];
  orgs: string[];
  first_seen?: number;
  updated?: number;
}
