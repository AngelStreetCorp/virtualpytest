/**
 * GitLab feature — the page.
 *
 * Minimal by request: a health strip, the project's files and README, and a link out to
 * GitLab. It deliberately does not re-implement GitLab's UI — anything deeper (merge requests,
 * issues, CI/CD editor) is one click away on the customer's own instance.
 *
 * One instance is the normal case, so it is picked implicitly. With several projects the
 * operator chooses one, and the choice is stored server-side so the page opens on it next time.
 *
 * This page is a GitLab BROWSER and nothing else: the projects, their files, their README and a
 * link out to GitLab. It carries no packaging, archive or "build a delivery" panel. Packaging was
 * moved out of this feature into the rollout on 2026-10-13 — it is
 * `setup/proxmox/node/lib/customer_bundle.py`, an operator-run CLI, and it has no UI at all. The
 * `/server/gitlab/package/*` routes and `PackagePanel.tsx` were deleted rather than hidden, so the
 * page says nothing about pins, overlays, zip or tar.gz. Do not re-add it without asking.
 *
 * Styling follows docs/agent/platform/UI_STYLE.md: palette tokens via useAgentChatPalette, page
 * building blocks from PageChrome, no literal colours.
 */
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  InputAdornment,
  Link,
  Menu,
  MenuItem,
  TextField,
  Tooltip,
  Typography,
  useTheme,
} from '@mui/material';
import {
  AccessTime as ClockIcon,
  ArrowBack as BackIcon,
  Check as CheckIcon,
  ContentCopy as CopyIcon,
  Code as CodeIcon,
  Description as ReadmeIcon,
  ExpandMore as ChevronDownIcon,
  ChevronRight as ChevronRightIcon,
  Folder as FolderIcon,
  AccountTree as BranchIcon,
  InsertDriveFile as FileIcon,
  OpenInNew as ExternalIcon,
  Search as SearchIcon,
  Settings as SettingsIcon,
} from '@mui/icons-material';
import { ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';

import { GitLabMark } from './GitLabMark';

import { useAgentChatPalette } from '../../../frontend/src/constants/agentChatTheme';
import {
  PageTitle,
  goldButtonSx,
  pageSurfaceSx,
} from '../../../frontend/src/components/common/PageChrome';
import { usePermissions } from '../../../frontend/src/hooks/auth/usePermissions';
import { toPublicGitLabUrl } from '../../../frontend/src/utils/gitlabUrl';
import {
  Branch,
  CommitSummary,
  GitLabProject,
  ProjectOverview,
  RepoFile,
  TreeEntry,
  gitlabApi,
} from './gitlabApi';


/** Files bigger than this are shown as a notice instead of dumping the content. */
const MAX_PREVIEW_BYTES = 200_000;

type Palette = ReturnType<typeof useAgentChatPalette>;

/** Palette keys, not CSS colours: 'textMuted' is the palette's neutral, there is no 'muted'. */
type Tone = 'success' | 'error' | 'warning' | 'textMuted';

const STATUS_TONE = (status?: string | null): Tone => {
  switch ((status || '').toLowerCase()) {
    case 'success':
      return 'success';
    case 'failed':
    case 'canceled':
      return 'error';
    case 'running':
    case 'pending':
    case 'created':
      return 'warning';
    default:
      return 'textMuted';
  }
};

/** GitHub-style relative date: "3 days ago", "just now". */
function ago(iso?: string | null): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  const units: [string, number][] = [
    ['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60],
  ];
  for (const [name, size] of units) {
    const n = Math.floor(secs / size);
    if (n >= 1) return `${n} ${name}${n > 1 ? 's' : ''} ago`;
  }
  return 'just now';
}

/** The page sits centred at this width instead of hugging the left. */
const CONTENT_MAX = 1280;

const LIST_KEY = 'virtualpytest:gitlab-file-list';

const STATUS_WORD: Record<string, string> = { success: 'passed', failed: 'failed', canceled: 'canceled' };

function PipelineState({ status, P }: { status?: string | null; P: Palette }) {
  if (!status) return null;
  const color = P[STATUS_TONE(status)];
  return (
    <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, color, fontSize: '0.78rem' }}>
      {status === 'success'
        ? <CheckIcon sx={{ fontSize: 14 }} />
        : <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: color }} />}
      {STATUS_WORD[status] || status}
    </Box>
  );
}

/**
 * A README, or anything ending .md/.markdown/.mdx, renders as Markdown. Everything else
 * renders as plain text: pushing a shell script or a customer.conf through ReactMarkdown
 * collapses its newlines into one run-on paragraph, which is precisely the kind of file
 * this explorer exists to show.
 */
const MARKDOWN_PATH = /(\.md|\.markdown|\.mdx)$/i;

function isMarkdownDoc(doc: RepoFile): boolean {
  return MARKDOWN_PATH.test(doc.path) || /(^|\/)readme(\.[^/]*)?$/i.test(doc.path);
}

/**
 * Type scale for rendered Markdown, per docs/agent/platform/UI_STYLE.md §3.
 *
 * Without it the browser's own Markdown defaults apply inside the panel: an h1 at 32px/700 that
 * outshouts the page title (1.5rem), 16px body — LARGER than the rest of the app and larger than
 * the plain-text files right next to it, which render at 0.78rem — and weight 700, which the
 * contract does not allow (400 and 600 only). The result read as a foreign document dropped into
 * the page rather than a file being previewed.
 *
 * The measure is the other half. A README is prose: left unconstrained, 13.6px text runs to roughly
 * 100 characters a line in this panel, well past the ~70 that stays comfortable to read. GitHub
 * constrains the same column for the same reason.
 */
const CODE_FONT = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';

/** Themed thin scrollbar: native bars ignore the palette and show a white track in dark mode. */
function scrollbarSx(P: Palette, dark: boolean) {
  return {
    colorScheme: dark ? 'dark' : 'light',
    scrollbarWidth: 'thin',
    scrollbarColor: `${P.borderColor} transparent`,
    '&::-webkit-scrollbar': { height: 8, width: 8, background: 'transparent' },
    '&::-webkit-scrollbar-track': { background: 'transparent' },
    '&::-webkit-scrollbar-thumb': { background: P.borderColor, borderRadius: 4 },
  };
}

/** A fenced block with a GitHub-style copy button, shown on hover. */
function CodeBlock({ P, dark, children }: { P: Palette; dark: boolean; children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const [el, setEl] = useState<HTMLPreElement | null>(null);
  const copy = () => {
    const text = el?.innerText ?? '';
    navigator.clipboard?.writeText(text.replace(/\n$/, '')).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <Box className="code-block" sx={{ position: 'relative', my: 2 }}>
      <Box component="pre" ref={setEl} sx={{ my: 0, ...scrollbarSx(P, dark) }}>{children}</Box>
      <IconButton
        className="copy-btn"
        size="small"
        aria-label="Copy code"
        onClick={copy}
        sx={{
          position: 'absolute', top: 8, right: 8, p: 0.5, opacity: 0, transition: 'opacity .15s',
          color: copied ? P.success : P.textMuted, bgcolor: P.background,
          border: `1px solid ${P.borderColor}`, borderRadius: '6px',
          '&:hover': { bgcolor: P.hoverBg },
        }}
      >
        {copied ? <CheckIcon sx={{ fontSize: 16 }} /> : <CopyIcon sx={{ fontSize: 16 }} />}
      </IconButton>
    </Box>
  );
}

function markdownSx(P: Palette, dark: boolean) {
  return {
    ...scrollbarSx(P, dark),
    '& .code-block:hover .copy-btn, & .copy-btn:focus-visible': { opacity: 1 },
    // `fontSize` first, and it is not cosmetic: `ch` resolves against the element's OWN font. The
    // measure below is declared on the TEXT elements, not here, so this is what `ch` measures
    // against — without it 72ch is 72ch of 16px MUI body and the prose runs ~94 characters wide.
    //
    // The measure is deliberately on `p/ul/ol/blockquote` and NOT on this container: a README's
    // code blocks and tables are the parts that need the extra width. Capping the whole column
    // clipped `git remote add origin <url>` mid-string (visible on a clone command), which is the
    // one line a reader most needs whole. GitHub breaks those out of the prose column for the
    // same reason.
    fontSize: '0.85rem',
    color: P.textSecondary,
    '& p, & ul, & ol, & blockquote': { maxWidth: '72ch' },
    // A README's own H1 must sit BELOW the page title, not compete with it.
    '& h1': {
      fontSize: '1.15rem', fontWeight: 600, color: P.textPrimary,
      lineHeight: 1.35, mt: 0, mb: 1.5,
    },
    '& h2': {
      fontSize: '1rem', fontWeight: 600, color: P.textPrimary,
      lineHeight: 1.4, mt: 2.5, mb: 1, pb: 0.5,
      borderBottom: `1px solid ${P.borderColor}`,
    },
    '& h3, & h4, & h5, & h6': {
      fontSize: '0.9rem', fontWeight: 600, color: P.textPrimary, lineHeight: 1.4, mt: 2, mb: 0.75,
    },
    '& p': { fontSize: '0.85rem', lineHeight: 1.5, mb: 1.25 },
    '& ul, & ol': { fontSize: '0.85rem', lineHeight: 1.5, pl: 2.5, mb: 1.25 },
    '& li': { mb: 0.5 },
    '& li > ul, & li > ol': { my: 0.5 },
    // A gold link with no underline reads as ordinary emphasised text. The hairline underline
    // carries the affordance and keeps the gold, so it stays on-palette.
    '& a': {
      color: P.accentText, textDecoration: 'none',
      borderBottom: `1px solid ${P.accentText}66`,
      '&:hover': { borderBottomColor: P.accentText },
    },
    '& strong': { color: P.textPrimary, fontWeight: 600 },
    // Inline code and fenced blocks follow github-markdown-css: neutral tint, normal text colour.
    '& code': {
      fontFamily: CODE_FONT, fontSize: '85%', color: P.textPrimary, bgcolor: P.hoverBg,
      px: '0.4em', py: '0.2em', borderRadius: '6px',
    },
    '& pre': {
      overflow: 'auto', maxWidth: '100%', bgcolor: P.hoverBg, color: P.textPrimary,
      borderRadius: '6px', p: '16px', fontFamily: CODE_FONT, fontSize: '85%', lineHeight: 1.45,
    },
    '& pre code': {
      fontSize: '100%', color: 'inherit', whiteSpace: 'pre', bgcolor: 'transparent', p: 0, borderRadius: 0,
    },
    '& blockquote': {
      borderLeft: `3px solid ${P.accent}`, pl: 1.5, my: 1.5,
      color: P.textMuted, fontSize: '0.85rem',
    },
    '& hr': { border: 0, borderTop: `1px solid ${P.borderColor}`, my: 2.5 },
    '& img': { maxWidth: '100%', borderRadius: 1 },
    // GFM tables ship with a README and were completely unstyled: no borders, default 16px.
    '& table': {
      borderCollapse: 'collapse', width: '100%', my: 1.5, fontSize: '0.8rem',
      display: 'block', overflowX: 'auto',
    },
    '& th, & td': {
      border: `1px solid ${P.borderColor}`, px: 1, py: 0.75, textAlign: 'left',
    },
    '& th': { color: P.textPrimary, fontWeight: 600, bgcolor: P.hoverBg },
  };
}

function Markdown({ doc, P }: { doc: RepoFile; P: Palette }) {
  const dark = useTheme().palette.mode === 'dark';
  if (doc.binary || doc.content === null) {
    return (
      <Typography variant="body2" sx={{ color: P.textMuted }}>
        {doc.path} is binary or too large to preview here — open it on GitLab.
      </Typography>
    );
  }
  if (doc.content.length > MAX_PREVIEW_BYTES) {
    return (
      <Typography variant="body2" sx={{ color: P.textMuted }}>
        {doc.path} is {(doc.content.length / 1024).toFixed(0)} KB — open it on GitLab.
      </Typography>
    );
  }
  if (!isMarkdownDoc(doc)) {
    return (
      <Box
        component="pre"
        sx={{
          m: 0,
          p: 1.5,
          maxHeight: 460,
          overflow: 'auto',
          bgcolor: P.background,
          color: P.textSecondary,
          border: `1px solid ${P.borderColor}`,
          borderRadius: 1,
          fontFamily: CODE_FONT,
          fontSize: '0.78rem',
          lineHeight: 1.45,
          ...scrollbarSx(P, dark),
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        {doc.content}
      </Box>
    );
  }
  return (
    <Box sx={markdownSx(P, dark)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={{ pre: ({ children }) => <CodeBlock P={P} dark={dark}>{children}</CodeBlock> }}
      >
        {doc.content}
      </ReactMarkdown>
    </Box>
  );
}

export default function GitLabPage() {
  const P = useAgentChatPalette();
  const { canAccess } = usePermissions();
  const canManage = canAccess?.('plugins.gitlab:manage') ?? false;

  const [health, setHealth] = useState<Awaited<ReturnType<typeof gitlabApi.health>> | null>(null);
  const [projects, setProjects] = useState<GitLabProject[]>([]);
  const [instanceId, setInstanceId] = useState<string>('');
  const [instanceName, setInstanceName] = useState('');
  const [project, setProject] = useState<string>('');
  const [ref, setRef] = useState('main');
  const [branches, setBranches] = useState<Branch[]>([]);
  const [overview, setOverview] = useState<ProjectOverview | null>(null);
  const [path, setPath] = useState('');
  const [entries, setEntries] = useState<TreeEntry[]>([]);
  const [readme, setReadme] = useState<RepoFile | null>(null);
  const [openFile, setOpenFile] = useState<RepoFile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [runnersOnline, setRunnersOnline] = useState(0);
  const [showSetup, setShowSetup] = useState(false);
  const [formUrl, setFormUrl] = useState('');
  const [formToken, setFormToken] = useState('');
  const [formName, setFormName] = useState('');
  const [filter, setFilter] = useState('');
  const [menu, setMenu] = useState<{ kind: 'project' | 'branch' | 'code'; el: HTMLElement } | null>(null);
  const [copied, setCopied] = useState('');
  const [listOpen, setListOpen] = useState(() => {
    try { return localStorage.getItem(LIST_KEY) !== 'closed'; } catch { return true; }
  });
  const toggleList = () => {
    setListOpen((v) => {
      try { localStorage.setItem(LIST_KEY, v ? 'closed' : 'open'); } catch { /* storage blocked */ }
      return !v;
    });
  };

  // ── boot ────────────────────────────────────────────────────────────────────
  // Re-reads everything for the CURRENT server. Every field is cleared first, on purpose: a
  // server without a GitLab must land on the empty state with nothing left over from the server
  // before it. Keeping the previous server's projects, files and README on screen while the
  // picker names a different server is the bug this replaced.
  const boot = useCallback(async () => {
    setInstanceId('');
    setInstanceName('');
    setProject('');
    setProjects([]);
    setBranches([]);
    setOverview(null);
    setPath('');
    setFilter('');
    setEntries([]);
    setReadme(null);
    setOpenFile(null);
    setError(null);
    try {
      const h = await gitlabApi.health();
      setHealth(h);
      const instance = h.instances?.[0];
      if (instance) {
        setInstanceId(instance.id);
        setInstanceName(instance.name);
        setProject(instance.project || '');
        setRef(instance.ref || 'main');
        setFormUrl(instance.base_url);
        setFormName(instance.name);
      }
      if (h.configured) {
        const { projects: rows } = await gitlabApi.projects();
        setProjects(rows);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    boot();
  }, [boot]);

  // A GitLab instance is configured PER SERVER, so the page has to be re-read whenever the picker
  // moves. Reading once at mount left the page showing the previous server's instance, projects,
  // files and README under the new server's name in the picker.
  useEffect(() => {
    const onServerChanged = () => { boot(); };
    window.addEventListener('vpt:server-changed', onServerChanged);
    return () => window.removeEventListener('vpt:server-changed', onServerChanged);
  }, [boot]);

  // One project is the normal case: no picking needed. With several and none remembered, open the first.
  useEffect(() => {
    if (!project && projects.length > 0) {
      setProject(projects[0].path);
      setRef(projects[0].default_branch || 'main');
    }
  }, [projects, project]);

  // ── repository loading ──────────────────────────────────────────────────────
  const loadRepo = useCallback(
    async (proj: string, branch: string, dir: string) => {
      if (!proj) return;
      setBusy(true);
      setError(null);
      try {
        // The tree and the README are independent: one Promise.all meant a repository with no
        // README rejected the pair and blanked the file list too, so "no README" read as
        // "empty repository". Each failure is handled on its own.
        const [tree, doc] = await Promise.allSettled([
          gitlabApi.tree(proj, branch, dir),
          dir === '' ? gitlabApi.readme(proj, branch) : Promise.resolve({ readme: null }),
        ]);
        if (tree.status === 'fulfilled') {
          setEntries(tree.value.entries);
        } else {
          setEntries([]);
          setError((tree.reason as Error).message);
        }
        if (doc.status === 'fulfilled') {
          setReadme(doc.value.readme);
        } else {
          setReadme(null);
        }
        setOpenFile(null);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (project) loadRepo(project, ref, path);
  }, [project, ref, path, loadRepo]);

  useEffect(() => {
    if (!project) return;
    gitlabApi
      .branches(project)
      .then(({ branches: b }) => setBranches(b))
      .catch(() => setBranches([]));
  }, [project]);

  useEffect(() => {
    if (!project) return;
    gitlabApi
      .overview(project, ref)
      .then(({ overview: o }) => setOverview(o))
      .catch(() => setOverview(null));
  }, [project, ref]);

  const chooseProject = async (row: GitLabProject) => {
    setProject(row.path);
    setRef(row.default_branch || 'main');
    setPath('');
    setFilter('');
    if (instanceId) {
      try {
        await gitlabApi.selectProject(instanceId, row.path, row.default_branch || 'main');
      } catch (e) {
        setError((e as Error).message);
      }
    }
  };

  // Closing always drops the typed token and puts name/URL back to what is saved.
  const closeSetup = () => {
    setShowSetup(false);
    setFormToken('');
    const saved = instanceId;
    if (saved) {
      gitlabApi.instances().then(({ instances }) => {
        const inst = instances.find((i) => i.id === saved);
        if (inst) { setFormUrl(inst.base_url); setFormName(inst.name); }
      }).catch(() => undefined);
    } else {
      setFormUrl('');
      setFormName('');
    }
  };

  const saveSetup = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await gitlabApi.saveInstance({
        id: instanceId || undefined,
        name: formName || formUrl,
        base_url: formUrl,
        token: formToken || undefined,
      });
      setShowSetup(false);
      setFormToken('');
      setInstanceId(res.instance.id);
      setInstanceName(res.instance.name);
      setHealth({
        success: true, configured: true, base_url: res.instance.base_url, version: res.version,
        instances: [res.instance],
      });
      const { projects: rows } = await gitlabApi.projects();
      setProjects(rows);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const configured = Boolean(health?.configured);
  const hasToken = Boolean(health?.instances?.[0]?.has_token);

  useEffect(() => {
    if (!configured) {
      setRunnersOnline(0);
      return;
    }
    gitlabApi
      .runners()
      .then(({ runners }) => setRunnersOnline(runners.filter((r) => r.status === 'online').length))
      .catch(() => setRunnersOnline(0));
  }, [configured, project]);

  // The configured base_url and GitLab's own `web_url` are internal addresses only the VPT server
  // can reach, so a browser handed either one gets a link that times out off-LAN. The proxy VM
  // serves the instance on our own domain under /gitlab.
  const selected = projects.find((p) => p.path === project);
  const openInGitLab = toPublicGitLabUrl(health?.base_url, selected?.web_url || overview?.web_url);
  const gitlabPage = (suffix: string) => (openInGitLab ? `${openInGitLab}${suffix}` : undefined);

  const latestCommit: CommitSummary | null = branches.find((b) => b.name === ref)?.commit ?? null;

  // Folders first, then files, each alphabetical — GitHub's order. The filter is "Go to file".
  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return [...entries]
      .filter((e) => !q || e.name.toLowerCase().includes(q))
      .sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'tree' ? -1 : 1));
  }, [entries, filter]);

  const topBranches = useMemo(() => {
    const def = overview?.default_branch || selected?.default_branch || 'main';
    return [...branches]
      .sort((a, b) => {
        if (a.name === def) return -1;
        if (b.name === def) return 1;
        return (b.commit?.committed_date || '').localeCompare(a.commit?.committed_date || '');
      })
      .slice(0, 4);
  }, [branches, overview, selected]);

  const copy = async (label: string, text?: string | null) => {
    setMenu(null);
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      window.setTimeout(() => setCopied(''), 2500);
    } catch {
      setError('Copy failed — your browser blocked clipboard access.');
    }
  };

  const goTo = (dir: string) => { setPath(dir); setFilter(''); };
  const crumbs = path ? path.split('/') : [];

  const btnSx = {
    height: 36, textTransform: 'none', color: P.textPrimary, borderColor: P.borderColor,
    bgcolor: P.surface, fontWeight: 600, '&:hover': { borderColor: P.borderColor, bgcolor: P.hoverBg },
  } as const;

  const settingsDialog = (
    <Dialog open={showSetup} onClose={closeSetup} fullWidth maxWidth="xs"
            PaperProps={{ sx: { borderRadius: 3, border: `1px solid ${P.borderColor}` } }}>
      <DialogTitle sx={{ pb: 0.5 }}>
        GitLab instance
        <Typography variant="body2" sx={{ color: P.textMuted, mt: 0.5 }}>
          {configured
            ? `${health?.reachable === false ? 'Unreachable' : 'Connected'}${health?.version ? ` · v${health.version}` : ''}${hasToken ? ' · token saved' : ''}`
            : 'Not connected yet'}
        </Typography>
      </DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mt: 1 }} onClose={() => setError(null)}>{error}</Alert>}
        <Box component="form" autoComplete="off" onSubmit={(e) => e.preventDefault()}
             sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          <TextField size="small" fullWidth label="Name" name="gl-instance-label" autoComplete="off"
                     value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="Customer GitLab" />
          <TextField size="small" fullWidth label="Base URL" name="gl-instance-address" autoComplete="off"
                     value={formUrl} onChange={(e) => setFormUrl(e.target.value)} placeholder="http://gitlab.internal" />
          <TextField size="small" fullWidth label="Token" name="gl-instance-secret" autoComplete="new-password"
                     type="password" value={formToken} onChange={(e) => setFormToken(e.target.value)}
                     placeholder={instanceId && hasToken ? '••••••••  (saved)' : undefined}
                     InputLabelProps={{ shrink: true }} />
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button disabled={busy} onClick={closeSetup} sx={{ color: P.accentText, fontWeight: 600 }}>Cancel</Button>
        <Button sx={goldButtonSx(P)} disabled={busy || !formUrl} onClick={saveSetup}>Save</Button>
      </DialogActions>
    </Dialog>
  );

  const sectionTitle = { fontWeight: 600, fontSize: '0.95rem', color: P.textPrimary } as const;
  const side = {
    display: 'flex', flexDirection: 'column', gap: 1.25, pb: 2, borderBottom: `1px solid ${P.borderColor}`,
  } as const;

  return (
    <Box sx={pageSurfaceSx(P)}>
      <Box sx={{ maxWidth: CONTENT_MAX, mx: 'auto' }}>
      <PageTitle
        title="GitLab"
        subtitle={
          configured
            ? `${instanceName || 'GitLab'}${health?.version ? ` · v${health.version}` : ''} · ${projects.length} project${projects.length === 1 ? '' : 's'} · ${runnersOnline} runner${runnersOnline === 1 ? '' : 's'} online`
            : 'Connect a self-hosted GitLab to browse its projects, files and README'
        }
        right={
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            {openInGitLab && (
              <Button
                variant="outlined"
                endIcon={<ExternalIcon fontSize="small" />}
                component={Link}
                href={openInGitLab}
                target="_blank"
                rel="noopener noreferrer"
                sx={{ ...btnSx, color: P.textSecondary }}
              >
                Open in GitLab
              </Button>
            )}
            {canManage && configured && (
              <Tooltip title="Instance settings">
                <IconButton
                  aria-label="Settings"
                  onClick={() => setShowSetup(true)}
                  sx={{
                    width: 36, height: 36, borderRadius: 2, border: '1px solid',
                    borderColor: showSetup ? P.accent : P.borderColor,
                    bgcolor: showSetup ? `${P.accent}26` : 'transparent',
                    color: showSetup ? P.accentText : P.textSecondary,
                  }}
                >
                  <SettingsIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
          </Box>
        }
      />

      {/* Gate on "the answer has not arrived", never on "not configured": before /health resolves
          the page would otherwise paint the empty state and then flip to the configured page. */}
      {!health && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress size={26} />
        </Box>
      )}

      {health && error && !showSetup && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      {copied && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setCopied('')}>
          Copied {copied}
        </Alert>
      )}

      {/* ── connect ───────────────────────────────────────────────────────── */}
      {health && !configured && (
        <Card sx={{ maxWidth: 560, mx: 'auto' }}>
          <CardContent sx={{ py: 4, textAlign: 'center' }}>
            {/* The tanuki in its own three colours, not the wordmark: the asset is transparent, so one file
                reads on the dark and the light card alike, and at hero size the logo needs no word
                beside it. Same component the navbar uses, at hero size. */}
            <Box sx={{ display: 'flex', justifyContent: 'center', mb: 2 }}>
              <GitLabMark fontSize={44} />
            </Box>
            <Typography variant="h6" sx={{ mb: canManage ? 2.5 : 0, color: P.textPrimary }}>
              Connect to GitLab
            </Typography>
            {!canManage && (
              <Typography variant="body2" sx={{ color: P.textMuted }}>
                An admin has to connect the instance.
              </Typography>
            )}
            {canManage && (
              <Button sx={goldButtonSx(P)} onClick={() => setShowSetup(true)}>
                Setup
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── repo bar ──────────────────────────────────────────────────────── */}
      {configured && project && (
        <>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, flexWrap: 'wrap', mb: 2.25 }}>
            <Button variant="outlined" startIcon={<FolderIcon fontSize="small" />}
                    endIcon={<ChevronDownIcon fontSize="small" />} sx={btnSx}
                    onClick={(e) => setMenu({ kind: 'project', el: e.currentTarget })}>
              {project}
            </Button>
            {overview?.visibility && (
              <Box component="span" sx={{
                fontSize: '0.75rem', px: 1, py: 0.25, borderRadius: 999,
                border: `1px solid ${P.borderColor}`, color: P.textSecondary, textTransform: 'capitalize',
              }}>
                {overview.visibility}
              </Box>
            )}
            <Box sx={{ flexGrow: 1 }} />
            <Button variant="outlined" startIcon={<BranchIcon fontSize="small" />}
                    endIcon={<ChevronDownIcon fontSize="small" />} sx={btnSx}
                    onClick={(e) => setMenu({ kind: 'branch', el: e.currentTarget })}>
              {ref}
            </Button>
            <Link href={gitlabPage('/-/branches')} target="_blank" rel="noopener noreferrer" underline="hover"
                  sx={{ color: P.textSecondary, fontSize: '0.85rem' }}>
              <b style={{ color: P.textPrimary }}>{branches.length}</b> branches
            </Link>
            <Link href={gitlabPage('/-/tags')} target="_blank" rel="noopener noreferrer" underline="hover"
                  sx={{ color: P.textSecondary, fontSize: '0.85rem' }}>
              <b style={{ color: P.textPrimary }}>{overview?.tag_count ?? 0}</b> tags
            </Link>
            <TextField
              size="small"
              placeholder="Go to file"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              name="gl-file-filter"
              autoComplete="off"
              sx={{ width: 220, '& .MuiInputBase-root': { height: 36 } }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>
                ),
              }}
            />
            <Button sx={{ ...goldButtonSx(P), height: 36 }} startIcon={<CodeIcon fontSize="small" />}
                    endIcon={<ChevronDownIcon fontSize="small" />}
                    onClick={(e) => setMenu({ kind: 'code', el: e.currentTarget })}>
              Code
            </Button>
          </Box>

          <Menu anchorEl={menu?.el} open={menu?.kind === 'project'} onClose={() => setMenu(null)}>
            {projects.map((row) => (
              <MenuItem key={row.id} selected={row.path === project}
                        onClick={() => { setMenu(null); chooseProject(row); }}>
                {row.path_with_namespace || row.path}
              </MenuItem>
            ))}
          </Menu>
          <Menu anchorEl={menu?.el} open={menu?.kind === 'branch'} onClose={() => setMenu(null)}>
            {(branches.length ? branches : [{ name: ref, commit: null } as Branch]).map((b) => (
              <MenuItem key={b.name} selected={b.name === ref}
                        onClick={() => { setMenu(null); setRef(b.name); setPath(''); }}
                        sx={{ display: 'flex', justifyContent: 'space-between', gap: 3 }}>
                <span>{b.name}</span>
                <Typography variant="caption" sx={{ color: P.textMuted }}>{ago(b.commit?.committed_date)}</Typography>
              </MenuItem>
            ))}
          </Menu>
          <Menu anchorEl={menu?.el} open={menu?.kind === 'code'} onClose={() => setMenu(null)}>
            <MenuItem disabled={!overview?.http_url} onClick={() => copy('HTTPS clone URL', overview?.http_url)}>
              Copy HTTPS clone URL
            </MenuItem>
            <MenuItem disabled={!overview?.ssh_url} onClick={() => copy('SSH clone URL', overview?.ssh_url)}>
              Copy SSH clone URL
            </MenuItem>
            <MenuItem component="a" href={gitlabPage('')} target="_blank" rel="noopener noreferrer"
                      disabled={!openInGitLab} onClick={() => setMenu(null)}>
              Open in GitLab
            </MenuItem>
          </Menu>

          {/* ── two columns ─────────────────────────────────────────────── */}
          <Box sx={{
            display: 'grid', gap: 3, alignItems: 'start',
            gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'minmax(0, 1fr) 280px' },
          }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.25, minWidth: 0 }}>
              <Box sx={{
                border: `1px solid ${P.borderColor}`, borderRadius: 2.5, overflow: 'hidden', bgcolor: P.surface,
              }}>
                {/* latest-commit bar */}
                <Box sx={{
                  display: 'flex', alignItems: 'center', gap: 1.25, px: 1.5, py: 1.25,
                  bgcolor: P.hoverBg, borderBottom: listOpen ? `1px solid ${P.borderColor}` : 0,
                  fontSize: '0.85rem',
                }}>
                  <IconButton size="small" aria-label="Collapse file list" onClick={toggleList}
                              sx={{ color: P.textSecondary }}>
                    {listOpen ? <ChevronDownIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
                  </IconButton>
                  {latestCommit ? (
                    <>
                      <Box component="span" sx={{
                        width: 22, height: 22, borderRadius: '50%', bgcolor: `${P.accent}26`, color: P.accentText,
                        fontSize: 11, fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0,
                      }}>
                        {(latestCommit.author_name || '?').split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()}
                      </Box>
                      <Box component="b" sx={{ fontWeight: 600, color: P.textPrimary }}>{latestCommit.author_name}</Box>
                      <Box component="span" sx={{
                        color: P.textSecondary, flex: 1, minWidth: 0, overflow: 'hidden',
                        textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>
                        {latestCommit.title}
                      </Box>
                      <PipelineState status={overview?.last_pipeline?.status} P={P} />
                      <Box component="code" sx={{ fontSize: '0.78rem', color: P.textMuted }}>{latestCommit.short_id}</Box>
                      <Box component="span" sx={{ color: P.textMuted, whiteSpace: 'nowrap' }}>
                        {ago(latestCommit.committed_date)}
                      </Box>
                      {overview?.commit_count != null && (
                        <Link href={gitlabPage(`/-/commits/${encodeURIComponent(ref)}`)} target="_blank"
                              rel="noopener noreferrer" underline="hover"
                              sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: P.textPrimary,
                                    fontWeight: 600, fontSize: '0.82rem', whiteSpace: 'nowrap' }}>
                          <ClockIcon sx={{ fontSize: 14 }} />{overview.commit_count} commits
                        </Link>
                      )}
                    </>
                  ) : (
                    <Box component="span" sx={{ color: P.textMuted, flex: 1 }}>
                      {busy ? 'Loading…' : ref}
                    </Box>
                  )}
                </Box>

                {listOpen && (
                  <>
                    {path && (
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, px: 2, py: 1,
                                 borderBottom: `1px solid ${P.borderColor}`, fontSize: '0.85rem' }}>
                        <Link component="button" underline="hover" onClick={() => goTo('')}
                              sx={{ color: P.accentText }}>{project.split('/').pop()}</Link>
                        {crumbs.map((c, i) => (
                          <Box key={c + i} component="span" sx={{ display: 'flex', gap: 0.75, color: P.textMuted }}>
                            /
                            {i === crumbs.length - 1 ? (
                              <Box component="span" sx={{ color: P.textPrimary }}>{c}</Box>
                            ) : (
                              <Link component="button" underline="hover"
                                    onClick={() => goTo(crumbs.slice(0, i + 1).join('/'))}
                                    sx={{ color: P.accentText }}>{c}</Link>
                            )}
                          </Box>
                        ))}
                      </Box>
                    )}
                    {rows.map((e) => (
                      <Box
                        key={e.path}
                        onClick={() => (e.type === 'tree' ? goTo(e.path) : openEntry(e, ref))}
                        sx={{
                          display: 'grid', gridTemplateColumns: '26px minmax(0, 1.1fr) minmax(0, 2fr) 120px',
                          alignItems: 'center', gap: 1, px: 2, py: 1.1, cursor: 'pointer',
                          borderBottom: `1px solid ${P.borderColor}`, '&:last-of-type': { borderBottom: 0 },
                          '&:hover': { bgcolor: 'transparent', '& .gl-name': { textDecoration: 'underline' } },
                        }}
                      >
                        {e.type === 'tree'
                          ? <FolderIcon fontSize="small" sx={{ color: P.accentText }} />
                          : <FileIcon fontSize="small" sx={{ color: P.textSecondary }} />}
                        <Box className="gl-name" sx={{ color: P.textPrimary, fontSize: '0.88rem', overflow: 'hidden',
                                                      textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.name}</Box>
                        <Box sx={{ color: P.textMuted, fontSize: '0.85rem', overflow: 'hidden',
                                   textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {e.last_commit?.title}
                        </Box>
                        <Box sx={{ color: P.textMuted, fontSize: '0.8rem', textAlign: 'right' }}>
                          {ago(e.last_commit?.committed_date)}
                        </Box>
                      </Box>
                    ))}
                    {rows.length === 0 && (
                      <Box sx={{ px: 2, py: 1.5, color: P.textMuted, fontSize: '0.85rem' }}>
                        {busy ? 'Loading…' : filter ? 'No file matches' : 'Empty directory'}
                      </Box>
                    )}
                  </>
                )}
              </Box>

              {/* file view or README */}
              {(openFile || readme) && (
                <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2.5, bgcolor: P.surface }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2, pt: 1.5,
                             borderBottom: `1px solid ${P.borderColor}` }}>
                    {openFile ? (
                      <>
                        <Button size="small" startIcon={<BackIcon fontSize="small" />}
                                onClick={() => setOpenFile(null)} sx={{ mb: 1 }}>Back</Button>
                        <FileIcon fontSize="small" sx={{ color: P.textMuted, mb: 1 }} />
                        <Typography variant="subtitle2" sx={{ color: P.textPrimary, mb: 1 }}>{openFile.path}</Typography>
                      </>
                    ) : (
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, fontWeight: 600,
                                 borderBottom: `2px solid ${P.accent}`, pb: 1.25, mb: '-1px' }}>
                        <ReadmeIcon fontSize="small" sx={{ color: P.textPrimary }} />
                        <span style={{ fontSize: '0.88rem' }}>README</span>
                      </Box>
                    )}
                  </Box>
                  <Box sx={{ px: 4, py: 3 }}>
                    <Markdown doc={(openFile || readme) as RepoFile} P={P} />
                  </Box>
                </Box>
              )}
              {!openFile && !readme && !busy && path === '' && (
                <Typography variant="body2" sx={{ color: P.textMuted }}>No README on this branch.</Typography>
              )}
            </Box>

            {/* ── sidebar ──────────────────────────────────────────────── */}
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Box sx={side}>
                <Typography sx={sectionTitle}>About</Typography>
                <Typography variant="body2" sx={{ color: P.textSecondary }}>
                  {overview?.description || 'No description'}
                </Typography>
                <Typography variant="body2" sx={{ color: P.textSecondary }}>
                  Default branch{' '}
                  <b style={{ color: P.textPrimary }}>{overview?.default_branch || selected?.default_branch || '—'}</b>
                </Typography>
                <Typography variant="body2" sx={{ color: P.textSecondary }}>
                  Last activity{' '}
                  <b style={{ color: P.textPrimary }}>{ago(overview?.last_activity_at) || '—'}</b>
                </Typography>
              </Box>
              <Box sx={side}>
                <Typography sx={sectionTitle}>Branches</Typography>
                {topBranches.map((b) => (
                  <Box key={b.name} sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, fontSize: '0.85rem' }}>
                    <Link component="button" underline="hover" onClick={() => { setRef(b.name); setPath(''); }}
                          sx={{ color: b.name === ref ? P.textPrimary : P.accentText,
                                fontWeight: b.name === ref ? 600 : 400, textAlign: 'left' }}>
                      {b.name}
                    </Link>
                    <Box component="span" sx={{ color: P.textMuted }}>{ago(b.commit?.committed_date)}</Box>
                  </Box>
                ))}
                <Link href={gitlabPage('/-/branches')} target="_blank" rel="noopener noreferrer" underline="hover"
                      sx={{ fontSize: '0.85rem', color: P.accentText }}>
                  All {branches.length} branches →
                </Link>
              </Box>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
                <Typography sx={sectionTitle}>Pipelines</Typography>
                <Box sx={{ fontSize: '0.85rem', color: P.textSecondary, display: 'flex', gap: 0.75, alignItems: 'center' }}>
                  {overview?.last_pipeline ? (
                    <>
                      <PipelineState status={overview.last_pipeline.status} P={P} />
                      <span>{ref} · {ago(overview.last_pipeline.created_at)}</span>
                    </>
                  ) : 'No pipeline on this branch'}
                </Box>
                <Box sx={{ fontSize: '0.85rem', color: P[runnersOnline ? 'success' : 'warning'],
                           display: 'flex', gap: 0.75, alignItems: 'center' }}>
                  <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%',
                                              bgcolor: P[runnersOnline ? 'success' : 'warning'] }} />
                  <span style={{ color: P.textSecondary }}>{runnersOnline} runner{runnersOnline === 1 ? '' : 's'} online</span>
                </Box>
              </Box>
            </Box>
          </Box>
        </>
      )}
      </Box>
      {settingsDialog}
    </Box>
  );

  async function openEntry(entry: TreeEntry, branch: string) {
    try {
      const { file } = await gitlabApi.file(project, branch, entry.path);
      if (file) setOpenFile(file);
    } catch (e) {
      setError((e as Error).message);
    }
  }
}
