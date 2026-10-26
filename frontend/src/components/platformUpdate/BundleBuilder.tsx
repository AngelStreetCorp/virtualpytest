import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import UploadFileIcon from '@mui/icons-material/UploadFile';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { findCoreTag, useBundleSources, type BundleInfo, type UploadedZip } from '../../hooks/platformUpdate/useBundleSources';
import type { RunStep, UpdateRun } from '../../hooks/platformUpdate/usePlatformUpdateRun';
import { TYPOGRAPHY } from '../../constants/typography';

export type CoreKind = 'github' | 'zip';
export type OverlayKind = 'gitlab' | 'github' | 'zip' | 'none';

interface Props {
  run: UpdateRun | null;
  step: RunStep;
  locked: boolean;
  busy: boolean;
  build: (body: Record<string, unknown>) => Promise<unknown>;
  /** The page's own source list (loaded on page load, so the header knows the requested build before a run starts). */
  bundleSources: ReturnType<typeof useBundleSources>;
  /** Tells the page which sources are picked, so the prerequisites are checked for them. */
  onSourcesChange?: (core: CoreKind, overlay: OverlayKind, tag: string) => void;
}

const LOG_LINES = 6;
const EXAMPLE_PROJECT = 'group/customer-overlay';
const EXAMPLE_URL = 'https://github.com/org/overlay';
const SHA_LABEL = 'sha256';

const formatSize = (bytes: number): string => `${(bytes / (1024 * 1024)).toFixed(1)} MB`;

/** Step 2: pick the core and the overlay, build the archive on this server, show what was built. */
export const BundleBuilder: React.FC<Props> = ({ run, step, locked, busy, build, bundleSources, onSourcesChange }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const src = bundleSources;
  const { load } = src;
  const [coreKind, setCoreKind] = useState<CoreKind>('github');
  const [tag, setTag] = useState('');
  const [coreZip, setCoreZip] = useState<UploadedZip | null>(null);
  const [overlayKind, setOverlayKind] = useState<OverlayKind>('none');
  const [project, setProject] = useState('');
  const [ref, setRef] = useState('');
  const [ghUrl, setGhUrl] = useState('');
  const [ghRef, setGhRef] = useState('prod');
  const [overlayZip, setOverlayZip] = useState<UploadedZip | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const coreInput = useRef<HTMLInputElement | null>(null);
  const overlayInput = useRef<HTMLInputElement | null>(null);

  const running = step.state === 'running';
  const frozen = locked || running;
  const bundle = step.data.bundle as BundleInfo | undefined;

  useEffect(() => {
    if (!locked && !src.sources) void load();
  }, [locked, load, src.sources]);

  const tags = src.sources?.core.github.refs ?? [];
  const branches = src.sources?.overlay.gitlab.refs ?? [];
  const gitlab = src.sources?.gitlab_instance;
  // ?to=<build number> (from Release Notes → Compare → Roll out) preselects the matching release tag.
  const [searchParams] = useSearchParams();
  const wanted = searchParams.get('to');
  const wantedTag = findCoreTag(tags, wanted);
  // A requested build with no tag on the core remote preselects nothing (no silent fallback to the newest tag).
  const effectiveTag = tag || wantedTag || (wanted ? '' : tags[0]?.ref) || '';

  useEffect(() => {
    onSourcesChange?.(coreKind, overlayKind, coreKind === 'github' ? effectiveTag : '');
  }, [coreKind, overlayKind, effectiveTag, onSourcesChange]);

  const upload = async (file: File | undefined, set: (z: UploadedZip) => void) => {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      set(await src.uploadZip(file));
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const coreBody = coreKind === 'github' ? { kind: 'github', tag: effectiveTag } : { kind: 'zip', upload_id: coreZip?.id };
  const overlayBody =
    overlayKind === 'gitlab' ? { kind: 'gitlab', project, ref }
    : overlayKind === 'github' ? { kind: 'github', url: ghUrl, ref: ghRef }
    : overlayKind === 'zip' ? { kind: 'zip', upload_id: overlayZip?.id }
    : { kind: 'none' };

  const ready =
    (coreKind === 'github' ? Boolean(effectiveTag) : Boolean(coreZip)) &&
    (overlayKind === 'gitlab' ? Boolean(project && ref)
      : overlayKind === 'github' ? Boolean(ghUrl && ghRef)
      : overlayKind === 'zip' ? Boolean(overlayZip)
      : true);

  const coreArg = coreKind === 'github' ? `github:${effectiveTag || '<tag>'}` : 'zip:<core.zip>';
  const overlayArg =
    overlayKind === 'gitlab' ? `gitlab:${project || '<group/overlay>'}@${ref || '<branch>'}`
    : overlayKind === 'github' ? `github:${ghUrl || '<url>'}@${ghRef}`
    : overlayKind === 'zip' ? 'zip:<overlay.zip>'
    : 'none';
  const cliCommand = `python3 setup/proxmox/node/lib/customer_bundle.py build --core ${coreArg} --overlay ${overlayArg} --format zip`;

  const jobLines = (run?.log ?? []).filter((l) => l.includes('[step 2] ')).slice(-LOG_LINES);

  const showNote = async () => {
    if (!run) return;
    try {
      setNote(await src.fetchDeliveryNote(run.id));
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Request failed');
    }
  };

  const picker = (label: string, value: string, onChange: (v: string) => void, children: React.ReactNode, minWidth = 220) => (
    <TextField select size="small" label={label} value={value} onChange={(e) => onChange(e.target.value)} disabled={frozen} sx={{ minWidth }}>
      {children}
    </TextField>
  );

  const zipButton = (zip: UploadedZip | null, input: React.RefObject<HTMLInputElement>, set: (z: UploadedZip) => void) => (
    <>
      <input ref={input} type="file" accept=".zip" hidden onChange={(e) => { void upload(e.target.files?.[0], set); e.target.value = ''; }} />
      <Button variant="outlined" size="small" startIcon={<UploadFileIcon />} disabled={frozen || uploading} onClick={() => input.current?.click()}>
        {zip ? zip.name : t('Choose a ZIP')}
      </Button>
    </>
  );

  const section = (title: string, children: React.ReactNode) => (
    <Box sx={{ mb: 1.5 }}>
      <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.body.size, mb: 0.75 }}>{title}</Typography>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>{children}</Box>
    </Box>
  );

  return (
    <>
      {src.error ? <Alert severity="warning" sx={{ mb: 1 }}>{src.error}</Alert> : null}
      {uploadError ? <Alert severity="error" sx={{ mb: 1 }} onClose={() => setUploadError(null)}>{uploadError}</Alert> : null}

      {section(t('Core'), (
        <>
          {picker(t('Source'), coreKind, (v) => setCoreKind(v as CoreKind), [
            <MenuItem key="github" value="github">{t('GitHub release tag')}</MenuItem>,
            <MenuItem key="zip" value="zip">{t('ZIP upload')}</MenuItem>,
          ], 180)}
          {coreKind === 'github' ? (
            src.sources && !src.sources.core.github.usable ? (
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.error }}>
                {t('GitHub not reachable: {error}', { error: src.sources.core.github.error })}
              </Typography>
            ) : picker(t('Release tag'), effectiveTag, setTag, tags.map((r) => (
              <MenuItem key={r.ref} value={r.ref}>{r.ref}</MenuItem>
            )), 300)
          ) : zipButton(coreZip, coreInput, setCoreZip)}
        </>
      ))}

      {section(t('Overlay'), (
        <>
          {picker(t('Source'), overlayKind, (v) => setOverlayKind(v as OverlayKind), [
            <MenuItem key="gitlab" value="gitlab">{t('GitLab (this server)')}</MenuItem>,
            <MenuItem key="github" value="github">{t('GitHub link')}</MenuItem>,
            <MenuItem key="zip" value="zip">{t('ZIP upload')}</MenuItem>,
            <MenuItem key="none" value="none">{t('None (platform only)')}</MenuItem>,
          ], 180)}
          {overlayKind === 'gitlab' ? (
            gitlab && !gitlab.configured ? (
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.warning }}>
                {t('No GitLab configured. Add one or pick another source.')}
              </Typography>
            ) : (
              <>
                <TextField size="small" label={t('GitLab project')} placeholder={EXAMPLE_PROJECT} value={project} disabled={frozen}
                  onChange={(e) => setProject(e.target.value)} onBlur={() => project && void load(project)} sx={{ minWidth: 260 }} />
                {branches.length > 0 ? picker(t('Branch'), ref, setRef, branches.map((b) => <MenuItem key={b} value={b}>{b}</MenuItem>), 160) : (
                  <TextField size="small" label={t('Branch')} value={ref} disabled={frozen} onChange={(e) => setRef(e.target.value)} sx={{ minWidth: 160 }} />
                )}
              </>
            )
          ) : null}
          {overlayKind === 'github' ? (
            <>
              <TextField size="small" label={t('GitHub URL')} placeholder={EXAMPLE_URL} value={ghUrl} disabled={frozen}
                onChange={(e) => setGhUrl(e.target.value)} sx={{ minWidth: 320 }} />
              <TextField size="small" label={t('Ref')} value={ghRef} disabled={frozen} onChange={(e) => setGhRef(e.target.value)} sx={{ minWidth: 120 }} />
            </>
          ) : null}
          {overlayKind === 'zip' ? zipButton(overlayZip, overlayInput, setOverlayZip) : null}
        </>
      ))}

      <Box component="pre" sx={{ m: 0, mb: 1.5, p: 1, bgcolor: P.hoverBg, borderRadius: 1, fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: P.textPrimary }}>
        {cliCommand}
      </Box>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
        <Button
          variant="contained"
          size="small"
          disabled={frozen || busy || !ready || uploading}
          onClick={() => void build({ action: 'build', core: coreBody, overlay: overlayBody, format: 'zip' })}
        >
          {t('Build zip')}
        </Button>
        {running ? <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.accentText }}>{t('Building...')}</Typography> : null}
      </Box>

      {/* Reserved space: the bar and the log tail occupy the same height whether or not a build runs. */}
      <Box sx={{ height: 4, mb: 1 }}>
        {running ? <LinearProgress sx={{ height: 4, borderRadius: 2, bgcolor: P.hoverBg, '& .MuiLinearProgress-bar': { bgcolor: P.accent } }} /> : null}
      </Box>
      <Box sx={{ height: 112, overflow: 'hidden', fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, bgcolor: P.hoverBg, borderRadius: 1, p: 1, mb: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
        {jobLines.join('\n')}
      </Box>

      {step.state === 'failed' && step.detail ? (
        <Alert severity="error" sx={{ mb: 1 }}>{step.detail}</Alert>
      ) : null}

      {step.state === 'done' && bundle ? (
        <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 1, p: 1.25 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, color: P.success, mb: 0.5 }}>
            <CheckCircleOutlineIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
            <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: P.success }}>{t('Bundle ready')}</Typography>
          </Box>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', color: P.textPrimary }}>{bundle.name} ({formatSize(bundle.size)})</Typography>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', color: P.textMuted, wordBreak: 'break-all' }}>{SHA_LABEL} {bundle.sha256}</Typography>
          {bundle.delivery_note ? (
            <Button size="small" variant="text" sx={{ mt: 0.5, px: 0 }} onClick={() => void showNote()}>{t('Open the delivery note')}</Button>
          ) : null}
        </Box>
      ) : null}

      <Dialog open={note !== null} onClose={() => setNote(null)} maxWidth="md" fullWidth>
        <DialogTitle>{t('Delivery note')}</DialogTitle>
        <DialogContent>
          <Box component="pre" sx={{ m: 0, fontSize: TYPOGRAPHY.caption.size, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: P.textPrimary }}>{note}</Box>
        </DialogContent>
        <DialogActions><Button onClick={() => setNote(null)}>{t('Close')}</Button></DialogActions>
      </Dialog>
    </>
  );
};
