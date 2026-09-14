import { GpsFixed as TargetIcon, Close as CloseIcon } from '@mui/icons-material';
import {
  Box,
  CircularProgress,
  IconButton,
  Popover,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useCallback, useRef, useState } from 'react';

import { buildServerUrl } from '../../utils/buildUrlUtils';

export interface LocalizeCandidate {
  node_id: string;
  label: string;
  confidence: number;
}

interface LocalizeResult {
  success?: boolean;
  candidates?: LocalizeCandidate[];
  excluded_count?: number;
  total?: number;
  variant?: string | null;
  error?: string;
  /** Named capture-side state when no UI node is on screen ('no_signal' | 'blackscreen'). */
  state?: string;
  state_label?: string;
  state_hint?: string;
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
}

/**
 * Localize: identify which navigation node the live device screen matches, by
 * perceptual-hash + focus fingerprint (probabilistic, by exclusion). Self-
 * contained — owns its API call and result popover. Used in the nav editor
 * toolbar and the device-control stream header.
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
}) => {
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<LocalizeResult | null>(null);

  const runLocalize = useCallback(async () => {
    if (!hostName || !deviceId || !userinterfaceName) return;
    setOpen(true);
    setLoading(true);
    setResult(null);
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

  const cands = result?.candidates ?? [];
  const headline = result?.state
    ? `⚠ ${result.state_label ?? result.state}`
    : cands.length === 1
      ? `Localized: ${cands[0].label}`
      : cands.length > 1
        ? 'Possibly one of:'
        : result?.success
          ? 'No confident match'
          : null;

  return (
    <>
      <Tooltip
        arrow
        title={disabled ? disabledTitle || 'Localize unavailable' : 'Localize — identify current screen'}
      >
        {/* span keeps the tooltip working while the button is disabled */}
        <span>
          <IconButton
            ref={anchorRef}
            onClick={runLocalize}
            disabled={disabled}
            aria-label="Localize current screen"
            sx={sx}
          >
            <TargetIcon />
          </IconButton>
        </span>
      </Tooltip>

      <Popover
        open={open}
        anchorEl={anchorRef.current}
        onClose={() => setOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        PaperProps={{
          sx: {
            mt: 0.5,
            border: '2px solid',
            borderColor: 'divider',
            borderRadius: 2,
            boxShadow: 6,
          },
        }}
      >
        {/* Fixed width so the right-anchored popover doesn't shift left/right
            as the content changes between loading and the candidate list. */}
        <Box sx={{ p: 1.5, width: 280 }}>
          {/* Header: title + close X (always present) */}
          <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 0.5 }}>
            <Typography variant="subtitle2" sx={{ pr: 1 }}>
              {loading ? 'Localize' : headline ?? 'Localize'}
            </Typography>
            <IconButton
              size="small"
              aria-label="Close"
              onClick={() => setOpen(false)}
              sx={{ p: 0.25, mt: -0.5, mr: -0.5 }}
            >
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>

          {loading ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <CircularProgress size={16} />
              <Typography variant="body2">Capturing & matching…</Typography>
            </Box>
          ) : result?.error || result?.success === false ? (
            <Typography variant="body2" color="error">
              {result?.error || 'Localize failed'}
            </Typography>
          ) : result?.state ? (
            <>
              <Typography variant="body2" color="warning.main">
                {result.state_hint ?? ''}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                Excluded {result?.excluded_count ?? 0} of {result?.total ?? 0} nodes
                {result?.variant ? ` · scope: ${result.variant}` : ' · scope: base'}
              </Typography>
            </>
          ) : (
            <>
              {cands.map((c) => (
                <Box
                  key={c.node_id}
                  sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, py: 0.25, pl: 1.5 }}
                >
                  <Typography variant="body2" sx={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {c.label}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {Math.round(c.confidence * 100)}%
                  </Typography>
                </Box>
              ))}
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                Excluded {result?.excluded_count ?? 0} of {result?.total ?? 0} nodes
                {result?.variant ? ` · scope: ${result.variant}` : ' · scope: base'}
              </Typography>
            </>
          )}
        </Box>
      </Popover>
    </>
  );
};

export default LocalizeButton;
