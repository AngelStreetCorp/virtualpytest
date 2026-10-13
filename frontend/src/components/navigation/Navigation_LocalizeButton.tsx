import {
  GpsFixed as TargetIcon,
  Close as CloseIcon,
  ErrorOutline as ErrorIcon,
  WarningAmber as WarnIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  Check as CheckIcon,
} from '@mui/icons-material';
import {
  Box,
  Button,
  ButtonBase,
  CircularProgress,
  IconButton,
  LinearProgress,
  MenuItem,
  Popover,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useCallback, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { buildServerUrl, openHostUrl } from '../../utils/buildUrlUtils';

export interface LocalizeCandidate {
  node_id: string;
  label: string;
  confidence: number;
  /** Hamming distance between the live frame and the stored fingerprint, in dHash bits. */
  dhash_dist?: number;
  /** Region distance used by the v5/v6 matcher: the BEST region's distance, out of 256 bits. */
  dist?: number;
}

/** Per-frame fields the monitor's `localize` worker writes to analysis_data (FINGERPRINT.md "Tier-2 add-ons"). */
interface ClassifierDiagnostics {
  motion?: { kind?: string; pct?: number };
  freeze?: boolean;
  loaded?: string;
  overlay?: string;
  playback?: string;
  error?: string;
}

/** A fingerprint as the matcher sees it (dhash, 5 regions, focus, crop, title). Copied as JSON. */
type Fingerprint = { dhash?: string } & Record<string, unknown>;

interface LocalizeResult {
  success?: boolean;
  candidates?: LocalizeCandidate[];
  /**
   * Top-N of the FULL ranking (match_fingerprint_v5 `_preview`). Display-only:
   * `candidates` stays the matcher's verdict, and `ranked[0]` is the node
   * `best_excluded` reports. Absent on a host that predates the preview key — the
   * popover falls back to `candidates`, which is usually a single row.
   */
  ranked?: LocalizeCandidate[];
  best_excluded?: LocalizeCandidate | null;
  /** A single low-confidence answer the second opinion did not confirm (turned into "unknown"). */
  unconfirmed_candidate?: LocalizeCandidate | null;
  classifier_diagnostics?: ClassifierDiagnostics | null;
  excluded_count?: number;
  total?: number;
  variant?: string | null;
  error?: string;
  /** Reason the matcher abstained (verbose; shown in step 2). */
  reason?: string;
  state?: string;
  state_label?: string;
  state_hint?: string;
  /** Public URL of the captured frame (already in the executor's result). */
  frame_url?: string | null;
  /** The live frame's fingerprint and the top node's stored one (TASK-88 row 9). */
  live_fingerprint?: Fingerprint | null;
  matched_fingerprint?: Fingerprint | null;
  /** Every fingerprinted node, for "Which screen was it?". */
  nodes?: { node_id: string; label: string }[];
}

interface LocalizeButtonProps {
  hostName?: string;
  deviceId?: string | null;
  userinterfaceName?: string | null;
  variant?: string | null;
  disabled?: boolean;
  /** Tooltip when disabled (e.g. "Take control first"). */
  disabledTitle?: string;
  /** sx applied to the IconButton — lets callers match the dark rec header. */
  sx?: object;
  /** Called with the ranked candidates (e.g. to highlight nodes on a canvas). */
  onCandidates?: (candidates: LocalizeCandidate[]) => void;
  /** Step 1 width (the ranked list). Sized per call site — see TASK-88 "The three call sites". */
  width?: number;
  /** Step 2 width (frame, closest match, fingerprints, "Wrong screen?"). */
  expandedWidth?: number;
}

/** Max ranked rows in the popover — keeps its height bounded on a 60-node interface. */
const MAX_ROWS = 5;
/** Dropdown value for "the true screen is not in this tree". */
const UNKNOWN = '__unknown__';

/**
 * Localize: identify which navigation node the live device screen matches, by
 * perceptual-hash + focus fingerprint (probabilistic, by exclusion). Self-
 * contained — owns its API call and result popover. Used in the nav editor
 * toolbar, the device-control stream header and the rec preview tiles.
 *
 * One anchored popover, two steps (TASK-88) — two of the three call sites are a 16-18px
 * icon on a preview tile or in a modal header, so nothing overlays the stream:
 *   - Step 1: interface/variant, the ranked screens with a bar and %, the scope count.
 *   - Step 2 (More): the captured frame, the closest match and its %, the two fingerprints to copy,
 *     and "Wrong screen?" → which screen it was, with "Unknown screen" first.
 *
 * Where a "wrong screen" answer is stored is not decided yet (TASK-88 row 12), so Save
 * copies a report to the clipboard and says so — it never claims to have stored anything.
 *
 * The popover never re-judges the verdict with its own confidence threshold: the
 * matcher already drops candidates below FP_MIN_CONFIDENCE, so `candidates.length`
 * IS the answer.
 */
export const LocalizeButton: React.FC<LocalizeButtonProps> = ({
  hostName,
  deviceId,
  userinterfaceName,
  variant,
  disabled,
  disabledTitle,
  sx,
  onCandidates,
  width = 300,
  expandedWidth = 380,
}) => {
  const P = useAgentChatPalette();
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<LocalizeResult | null>(null);
  const [asking, setAsking] = useState(false);
  const [pick, setPick] = useState<string>(UNKNOWN);
  const [answered, setAnswered] = useState<{ ok: boolean; text: string } | null>(null);

  const runLocalize = useCallback(async () => {
    if (!hostName || !deviceId || !userinterfaceName) return;
    setOpen(true);
    setLoading(true);
    setResult(null);
    setAsking(false);
    setAnswered(null);
    setPick(UNKNOWN);
    try {
      const resp = await fetch(buildServerUrl('/server/navigation/localize'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host_name: hostName,
          device_id: deviceId,
          userinterface_name: userinterfaceName,
          variant: variant ?? undefined,
        }),
      });
      const data: LocalizeResult = await resp.json();
      setResult(data);
      if (data.success && data.candidates && onCandidates) {
        onCandidates(data.candidates);
      }
    } catch (e) {
      setResult({ success: false, error: e instanceof Error ? e.message : 'Request failed' });
    } finally {
      setLoading(false);
    }
  }, [hostName, deviceId, userinterfaceName, variant, onCandidates]);

  // `candidates` IS the verdict (after all six doors); `ranked` is the matcher's raw region
  // ranking from BEFORE the title / narrowing / confidence doors, with region-based confidence.
  // So the verdict rows come first with their own confidence, then what they beat. Crowning
  // ranked[0] instead would crown the wrong node on a nav menu, where the title decides.
  const cands = result?.candidates ?? [];
  const verdictIds = new Set(cands.map((c) => c.node_id));
  const rows = [...cands, ...(result?.ranked ?? []).filter((r) => !verdictIds.has(r.node_id))].slice(0, MAX_ROWS);
  const matched = cands.length > 0;
  // More than one candidate is a genuine ambiguity, a real answer: the matcher never guesses
  // between them, so neither does the popover.
  const tied = cands.length > 1;
  const crowned = cands.length === 1;
  // The one card step 2 shows: the verdict when there is one, else the closest node.
  const closest: LocalizeCandidate | null =
    (matched ? cands[0] : null) ?? result?.unconfirmed_candidate ?? result?.ranked?.[0] ?? result?.best_excluded ?? null;
  const abstainText = abstainReason(result?.reason);

  const scopeLabel = `${userinterfaceName ?? '—'} · ${variant ?? 'base'} variant`;
  const hasResult = !!result && !loading;
  const total = result?.total ?? 0;
  const excluded = result?.excluded_count ?? 0;
  const inScope = Math.max(0, total - excluded);

  // The dropdown: Unknown first (the most common honest answer), then the runners-up the
  // matcher ranked, then the rest of the tree.
  const rankedIds = new Set(rows.map((r) => r.node_id));
  const others = (result?.nodes ?? []).filter((n) => !rankedIds.has(n.node_id) && n.node_id !== closest?.node_id);
  const labelOf = (id: string) =>
    rows.find((r) => r.node_id === id)?.label ?? result?.nodes?.find((n) => n.node_id === id)?.label ?? id;

  const saveAnswer = async () => {
    const report = {
      userinterface: userinterfaceName,
      variant: variant ?? 'base',
      host: hostName,
      device: deviceId,
      frame_url: result?.frame_url ?? null,
      matched: closest ? { node_id: closest.node_id, label: closest.label, confidence: closest.confidence } : null,
      true_screen: pick === UNKNOWN ? 'unknown' : { node_id: pick, label: labelOf(pick) },
      live_fingerprint: result?.live_fingerprint ?? null,
      matched_fingerprint: result?.matched_fingerprint ?? null,
    };
    let copied = false;
    try {
      await navigator.clipboard.writeText(JSON.stringify(report, null, 2));
      copied = true;
    } catch {
      copied = false;
    }
    setAsking(false);
    setAnswered(
      copied
        ? { ok: true, text: `${pick === UNKNOWN ? 'Unknown screen' : labelOf(pick)} — report copied` }
        : { ok: false, text: 'The browser blocked the clipboard — the report was not copied' },
    );
  };

  const footer =
    total > 0 ? (
      <Box
        sx={{
          borderTop: `1px solid ${P.borderColor}`,
          px: 1.75,
          py: 0.75,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1,
        }}
      >
        {expanded && hasResult && !asking ? (
          <ButtonBase
            onClick={() => {
              setAsking(true);
              setAnswered(null);
            }}
            sx={{
              fontSize: 11.5,
              color: P.textSecondary,
              textDecoration: 'underline',
              textUnderlineOffset: 2,
              textDecorationColor: P.borderColor,
              '&:hover, &.Mui-focusVisible': { color: P.error, textDecorationColor: P.error },
            }}
          >
            Wrong screen?
          </ButtonBase>
        ) : (
          <Typography sx={{ fontSize: 11.5, color: P.textMuted, fontVariantNumeric: 'tabular-nums' }}>
            {inScope} {inScope === 1 ? 'screen' : 'screens'} in scope · {excluded} excluded
          </Typography>
        )}
        {hasResult && (
          <ButtonBase
            onClick={() => setExpanded((v) => !v)}
            sx={{ fontSize: 11.5, color: P.accentText, gap: 0.25, flexShrink: 0 }}
          >
            {expanded ? 'Less' : 'More'}
            {expanded ? <ExpandLessIcon sx={{ fontSize: 15 }} /> : <ExpandMoreIcon sx={{ fontSize: 15 }} />}
          </ButtonBase>
        )}
      </Box>
    ) : null;

  const ranked = (
    <Box sx={{ px: 1, pb: 1.25 }}>
      {rows.map((c, i) => {
        const pct = Math.max(0, Math.min(100, Math.round(c.confidence * 100)));
        // A tie crowns nobody, and neither does an abstain: both top rows stay
        // plain, so the popover never claims a match the matcher refused to make.
        const winner = crowned && i === 0;
        const strong = winner || (tied && verdictIds.has(c.node_id));
        return (
          <Box
            key={c.node_id}
            sx={{
              px: 1,
              py: 0.75,
              borderRadius: 1,
              ...(winner ? { background: `${P.accent}1f`, boxShadow: `inset 0 0 0 1px ${P.accent}47` } : {}),
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 1.5 }}>
              <Typography
                noWrap
                title={c.label}
                sx={{ fontSize: 13, color: winner ? P.accentText : P.textPrimary, fontWeight: strong ? 600 : 400 }}
              >
                {c.label}
              </Typography>
              <Typography
                sx={{
                  fontSize: 12,
                  fontVariantNumeric: 'tabular-nums',
                  color: winner ? P.accentText : strong ? P.textPrimary : P.textSecondary,
                  fontWeight: strong ? 600 : 400,
                  flexShrink: 0,
                }}
              >
                {pct}%
              </Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={pct}
              sx={{
                mt: 0.75,
                height: 3,
                borderRadius: 2,
                background: P.hoverBg,
                '& .MuiLinearProgress-bar': { background: winner ? P.accent : P.textMuted, borderRadius: 2 },
              }}
            />
          </Box>
        );
      })}
    </Box>
  );

  const frameName = result?.frame_url ? result.frame_url.split('?')[0].split('/').pop() : null;

  const detail = (
    <Box sx={{ px: 1.75, pb: 1.25, display: 'flex', flexDirection: 'column', gap: 1 }}>
      {result?.frame_url && (
        /* Click opens the full frame: openHostUrl mints the host-session cookie first (BUG-0477). */
        <ButtonBase
          onClick={() => void openHostUrl(result.frame_url as string)}
          title="Open the captured frame"
          sx={{
            position: 'relative',
            display: 'block',
            borderRadius: 1.5,
            overflow: 'hidden',
            border: `1px solid ${P.borderColor}`,
            aspectRatio: '16 / 9',
            background: P.hoverBg,
          }}
        >
          <Box
            component="img"
            src={result.frame_url}
            alt="Captured frame"
            sx={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
          />
          {frameName && (
            <Box
              component="span"
              sx={{
                position: 'absolute',
                left: 7,
                bottom: 6,
                maxWidth: 'calc(100% - 14px)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontSize: 10,
                fontFamily: 'monospace',
                color: '#e6e9ec',
                background: 'rgba(0,0,0,.55)',
                borderRadius: 0.5,
                px: 0.75,
              }}
            >
              {frameName}
            </Box>
          )}
        </ButtonBase>
      )}

      {closest && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 1.5,
            px: 1.375,
            py: 1.125,
            borderRadius: 1.5,
            ...(crowned
              ? { background: `${P.accent}1f`, boxShadow: `inset 0 0 0 1px ${P.accent}47` }
              : { background: P.hoverBg, border: `1px solid ${P.borderColor}` }),
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            {!crowned && (
              <Typography sx={{ fontSize: 10.5, color: P.textMuted }}>
                {tied
                  ? `Tie between ${cands.length} screens`
                  : !matched && closest.node_id === result?.unconfirmed_candidate?.node_id
                    ? 'Low confidence, not confirmed'
                    : 'Closest, not matched'}
              </Typography>
            )}
            <Typography
              noWrap
              title={closest.label}
              sx={{ fontSize: 14.5, fontWeight: 600, color: crowned ? P.accentText : P.textPrimary }}
            >
              {closest.label}
            </Typography>
          </Box>
          <Typography
            sx={{
              fontSize: 16,
              fontWeight: 600,
              fontVariantNumeric: 'tabular-nums',
              color: crowned ? P.accentText : P.textSecondary,
              flexShrink: 0,
            }}
          >
            {Math.round((closest.confidence ?? 0) * 100)}%
          </Typography>
        </Box>
      )}

      {!matched && abstainText && (
        <Typography sx={{ fontSize: 11.5, color: P.textSecondary, overflowWrap: 'anywhere' }}>
          {abstainText}
        </Typography>
      )}

      {diagLine(result?.classifier_diagnostics) && (
        <Typography sx={{ fontSize: 11.5, color: P.textSecondary }}>
          <Box component="span" sx={{ color: P.textMuted }}>
            Screen state{' '}
          </Box>
          {diagLine(result?.classifier_diagnostics)}
        </Typography>
      )}

      {(result?.live_fingerprint || result?.matched_fingerprint) && (
        <>
          <Typography sx={{ fontSize: 11, color: P.textSecondary, mt: 0.25 }}>Fingerprints</Typography>
          <FingerprintRow who="What the camera saw" fp={result?.live_fingerprint} />
          <FingerprintRow who="What was saved" fp={result?.matched_fingerprint} />
        </>
      )}
    </Box>
  );

  const question = (
    <Box
      sx={{
        borderTop: `1px solid ${P.borderColor}`,
        px: 1.75,
        py: 1.375,
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
      }}
    >
      <Typography sx={{ fontSize: 12, fontWeight: 600 }}>Which screen was it?</Typography>
      <TextField
        select
        size="small"
        value={pick}
        onChange={(e) => setPick(e.target.value)}
        SelectProps={{ MenuProps: { PaperProps: { sx: { maxHeight: 320 } } } }}
        sx={{ '& .MuiInputBase-root': { fontSize: 12.5 } }}
      >
        <MenuItem value={UNKNOWN} sx={{ fontSize: 12.5 }}>
          Unknown screen (not in this tree)
        </MenuItem>
        {rows
          .filter((r) => r.node_id !== closest?.node_id)
          .map((r) => (
            <MenuItem key={r.node_id} value={r.node_id} sx={{ fontSize: 12.5 }}>
              {r.label}
            </MenuItem>
          ))}
        {others.map((n) => (
          <MenuItem key={n.node_id} value={n.node_id} sx={{ fontSize: 12.5, color: P.textSecondary }}>
            {n.label}
          </MenuItem>
        ))}
      </TextField>
      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
        <Button size="small" onClick={() => setAsking(false)} sx={{ color: P.textSecondary }}>
          Cancel
        </Button>
        <Button size="small" variant="contained" onClick={() => void saveAnswer()}>
          Copy report
        </Button>
      </Box>
    </Box>
  );

  return (
    <>
      <Tooltip
        arrow
        title={disabled ? disabledTitle || 'Localize unavailable' : 'Localize — identify current screen'}
      >
        {/* span keeps the tooltip working while the button is disabled */}
        <span>
          <IconButton
            size="large"
            ref={anchorRef}
            onClick={runLocalize}
            disabled={disabled}
            aria-label="Localize current screen"
            sx={sx}
          >
            <TargetIcon fontSize="medium" />
          </IconButton>
        </span>
      </Tooltip>

      <Popover
        open={open}
        anchorEl={anchorRef.current}
        onClose={() => setOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{
          paper: {
            sx: {
              mt: 0.5,
              background: P.surface,
              color: P.textPrimary,
              border: `1px solid ${P.borderColor}`,
              borderRadius: 2,
              boxShadow: 6,
              overflow: 'hidden',
            },
          },
        }}
      >
        {/* Fixed width per step so the right-anchored popover doesn't shift as the
            content changes between loading, the ranked list and the empty states. */}
        <Box sx={{ width: expanded && hasResult ? expandedWidth : width, maxWidth: 'calc(100vw - 32px)' }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              gap: 2,
              px: 1.75,
              pt: 1.5,
              pb: 1.25,
            }}
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography sx={{ fontSize: 11, fontWeight: 600, letterSpacing: '.08em', color: P.accentText }}>
                Localize
              </Typography>
              <Typography
                title={scopeLabel}
                sx={{
                  fontSize: 12,
                  color: P.textSecondary,
                  mt: 0.25,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {scopeLabel}
              </Typography>
            </Box>
            <IconButton
              size="small"
              aria-label="Close"
              onClick={() => setOpen(false)}
              sx={{ p: 0.25, mt: -0.5, mr: -0.5, color: P.textMuted, flexShrink: 0 }}
            >
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>

          {loading ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, px: 1.75, pb: 1.75 }}>
              <CircularProgress size={16} sx={{ color: P.accent }} />
              <Typography sx={{ fontSize: 12.5, color: P.textSecondary }}>Capturing &amp; matching…</Typography>
            </Box>
          ) : result?.error || result?.success === false ? (
            <Notice
              icon={<ErrorIcon fontSize="small" />}
              color={P.error}
              title="Localize failed"
              body={result?.error || 'Localize failed'}
            />
          ) : expanded ? (
            <>
              {result?.state && (
                <Notice
                  icon={<WarnIcon fontSize="small" />}
                  color={P.warning}
                  title={result.state_label ?? result.state}
                  body={result.state_hint}
                />
              )}
              {detail}
              {asking && question}
              {answered && (
                <Box
                  sx={{
                    borderTop: `1px solid ${P.borderColor}`,
                    px: 1.75,
                    py: 1,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 0.75,
                    background: `${answered.ok ? P.success : P.error}1f`,
                    color: answered.ok ? P.success : P.error,
                  }}
                >
                  {answered.ok ? <CheckIcon sx={{ fontSize: 15 }} /> : <ErrorIcon sx={{ fontSize: 15 }} />}
                  <Typography sx={{ fontSize: 12 }}>{answered.text}</Typography>
                </Box>
              )}
            </>
          ) : result?.state ? (
            <Notice
              icon={<WarnIcon fontSize="small" />}
              color={P.warning}
              title={result.state_label ?? result.state}
              body={result.state_hint}
            />
          ) : result?.success && !matched ? (
            /* An abstain says so first — the near-miss rows below it are what it rejected. */
            <>
              <Notice
                icon={<TargetIcon fontSize="small" />}
                color={P.textSecondary}
                title="No match"
                body={abstainText ?? "No screen scored above the matcher's confidence floor."}
              />
              {rows.length > 0 && ranked}
            </>
          ) : rows.length > 0 ? (
            ranked
          ) : null}

          {footer}
        </Box>
      </Popover>
    </>
  );
};

/** One of the two fingerprints: a plain-words label, a short prefix, Copy = the whole JSON. */
const FingerprintRow: React.FC<{ who: string; fp?: Fingerprint | null }> = ({ who, fp }) => {
  const P = useAgentChatPalette();
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(fp, null, 2));
      setState('copied');
    } catch {
      setState('failed');
    }
    setTimeout(() => setState('idle'), 1400);
  };
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        px: 1.125,
        py: 0.75,
        borderRadius: 1,
        border: `1px solid ${P.borderColor}`,
        background: P.hoverBg,
        minWidth: 0,
      }}
    >
      <Typography sx={{ fontSize: 11.5, color: P.textSecondary, width: 118, flexShrink: 0 }}>{who}</Typography>
      <Typography
        sx={{
          fontSize: 11,
          fontFamily: 'monospace',
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          color: fp ? P.textPrimary : P.textMuted,
        }}
      >
        {fp?.dhash ? `${fp.dhash.slice(0, 12)}…` : '—'}
      </Typography>
      <Button
        size="small"
        variant="outlined"
        disabled={!fp}
        onClick={() => void copy()}
        sx={{
          minWidth: 0,
          px: 1,
          py: 0,
          fontSize: 10.5,
          flexShrink: 0,
          color: state === 'copied' ? P.success : P.textSecondary,
          borderColor: state === 'copied' ? P.success : P.borderColor,
        }}
      >
        {state === 'copied' ? 'Copied' : state === 'failed' ? 'Blocked' : 'Copy'}
      </Button>
    </Box>
  );
};

/** The matcher's abstain reason in plain words for doors 1-3; doors 4-6 keep their own sentence. */
const abstainReason = (reason?: string): string | null => {
  if (!reason) return null;
  if (reason === 'low-content frame')
    return 'The frame is nearly empty (black, asleep or fading), so there is nothing to recognise.';
  if (reason === 'nav underline matched no node') return 'The highlighted menu tab does not match any saved screen.';
  if (reason.startsWith('nav underline far from chrome'))
    return 'A menu highlight was found, but the menu title did not confirm any saved screen.';
  return reason;
};

/** The classifier's per-frame answers on one line, skipping the ones it could not answer. */
const diagLine = (d?: ClassifierDiagnostics | null): string | null => {
  if (!d) return null;
  const known = (v?: string) => !!v && v !== 'unknown' && v !== 'not_applicable';
  const parts: string[] = [];
  if (d.motion?.kind) parts.push(`${d.motion.kind}${d.motion.pct != null ? ` ${d.motion.pct.toFixed(1)}%` : ''}`);
  if (d.freeze) parts.push('frozen');
  // Values from shared/src/lib/ai/screen_state_cv.py: loaded yes|no, overlay none|popup|tooltip|
  // keyboard|notification, playback playing|paused|stopped, error none|visible.
  if (known(d.loaded)) parts.push(d.loaded === 'yes' ? 'loaded' : 'still drawing');
  if (known(d.overlay)) parts.push(d.overlay === 'none' ? 'no overlay' : `overlay: ${d.overlay}`);
  if (known(d.playback)) parts.push(d.playback as string);
  if (known(d.error)) parts.push(d.error === 'visible' ? 'error on screen' : 'no error');
  return parts.length ? parts.join(' · ') : null;
};

/** Capture-side / failure message: coloured icon + title + one line of detail. */
const Notice: React.FC<{
  icon: React.ReactNode;
  color: string;
  title: string;
  body?: string;
}> = ({ icon, color, title, body }) => (
  <Box sx={{ display: 'flex', gap: 1.25, alignItems: 'flex-start', px: 1.75, pb: 1.75 }}>
    <Box sx={{ color, display: 'flex', mt: '1px', flexShrink: 0 }}>{icon}</Box>
    <Box sx={{ minWidth: 0 }}>
      <Typography sx={{ fontSize: 12.5, fontWeight: 600, color }}>{title}</Typography>
      {body && (
        <Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.25, overflowWrap: 'anywhere' }}>
          {body}
        </Typography>
      )}
    </Box>
  </Box>
);

export default LocalizeButton;
