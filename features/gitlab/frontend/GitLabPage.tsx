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
 * Styling follows docs/agent/platform/UI_STYLE.md: palette tokens via useAgentChatPalette, page
 * building blocks from PageChrome, no literal colours.
 */
import {
  Alert,
  Box,
  Button,
  Collapse,
  Link,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import {
  ArrowBack as BackIcon,
  Description as ReadmeIcon,
  Folder as FolderIcon,
  InsertDriveFile as FileIcon,
  OpenInNew as ExternalIcon,
  Settings as SettingsIcon,
} from '@mui/icons-material';
import { useCallback, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';

import { useAgentChatPalette } from '../../../frontend/src/constants/agentChatTheme';
import {
  PageTitle,
  StatTiles,
  goldButtonSx,
  pageSurfaceSx,
} from '../../../frontend/src/components/common/PageChrome';
import { usePermissions } from '../../../frontend/src/hooks/auth/usePermissions';
import {
  GitLabProject,
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

function when(iso?: string | null): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} d ago`;
}

function StatusPill({ status, P }: { status?: string | null; P: Palette }) {
  if (!status) return <span style={{ color: P.textMuted }}>no pipeline</span>;
  const color = P[STATUS_TONE(status)];
  return (
    <Box
      component="span"
      sx={{
        display: 'inline-block',
        px: 1,
        py: 0.25,
        borderRadius: '10px',
        fontSize: '0.75rem',
        color,
        background: `${color}1f`,
        border: `1px solid ${color}66`,
        textTransform: 'lowercase',
      }}
    >
      {status}
    </Box>
  );
}

function Markdown({ doc, P }: { doc: RepoFile; P: Palette }) {
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
  return (
    <Box sx={{ '& h1, & h2': { color: P.textPrimary }, '& p, & li': { color: P.textSecondary },
               '& code': { color: P.accentText }, '& a': { color: P.accentText } }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
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
  const [branches, setBranches] = useState<string[]>([]);
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

  // ── boot ────────────────────────────────────────────────────────────────────
  useEffect(() => {
    (async () => {
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
    })();
  }, []);

  // One project is the normal case: no picking needed.
  useEffect(() => {
    if (!project && projects.length === 1) {
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
        const [tree, doc] = await Promise.all([
          gitlabApi.tree(proj, branch, dir),
          dir === '' ? gitlabApi.readme(proj, branch) : Promise.resolve({ readme: null }),
        ]);
        setEntries(tree.entries);
        setReadme(doc.readme);
        setOpenFile(null);
      } catch (e) {
        setError((e as Error).message);
        setEntries([]);
        setReadme(null);
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

  const chooseProject = async (row: GitLabProject) => {
    setProject(row.path);
    setRef(row.default_branch || 'main');
    setPath('');
    if (instanceId) {
      try {
        await gitlabApi.selectProject(instanceId, row.path, row.default_branch || 'main');
      } catch (e) {
        setError((e as Error).message);
      }
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
      setHealth({ success: true, configured: true, base_url: res.instance.base_url, version: res.version });
      const { projects: rows } = await gitlabApi.projects();
      setProjects(rows);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const configured = Boolean(health?.configured);

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

  const openInGitLab = projects.find((p) => p.path === project)?.web_url;

  return (
    <Box sx={{ p: 2 }}>
      <PageTitle
        title="GitLab"
        subtitle={health?.base_url || 'not configured'}
        right={
          <Box sx={{ display: 'flex', gap: 1 }}>
            {openInGitLab && (
              <Button
                size="small"
                variant="outlined"
                endIcon={<ExternalIcon fontSize="small" />}
                component={Link}
                href={openInGitLab}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open in GitLab
              </Button>
            )}
            {canManage && (
              <Button size="small" variant="outlined" startIcon={<SettingsIcon fontSize="small" />}
                      onClick={() => setShowSetup((v) => !v)}>
                Settings
              </Button>
            )}
          </Box>
        }
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {configured && (
        <Box sx={{ ...pageSurfaceSx(P), mb: 2, p: 2 }}>
          <StatTiles
            tiles={[
              { label: 'Version', value: health?.version || 'unknown' },
              { label: 'Projects', value: projects.length },
              { label: 'Runners online', value: runnersOnline },
              { label: 'Instance', value: instanceName || '—' },
            ]}
          />
        </Box>
      )}

      {/* ── setup ─────────────────────────────────────────────────────────── */}
      {!configured && !showSetup && (
        <Box sx={{ ...pageSurfaceSx(P), p: 3 }}>
          <Typography variant="h6" sx={{ mb: 1, color: P.textPrimary }}>
            Connect a GitLab
          </Typography>
          <Typography variant="body2" sx={{ mb: 2, color: P.textSecondary }}>
            Base URL of your GitLab and a Personal Access Token with the <code>api</code> scope
            (User Settings → Access Tokens). Plain HTTP instances are fine.
          </Typography>
          {canManage && (
            <Button sx={goldButtonSx(P)} onClick={() => setShowSetup(true)}>
              Set up GitLab
            </Button>
          )}
        </Box>
      )}

      {showSetup && (
        <Box sx={{ ...pageSurfaceSx(P), p: 2, mb: 2 }}>
          <Typography variant="subtitle1" sx={{ mb: 1, color: P.textPrimary }}>
            {instanceId ? 'Edit instance' : 'New instance'}
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <TextField size="small" label="Name" value={formName} onChange={(e) => setFormName(e.target.value)} />
            <TextField size="small" label="Base URL" value={formUrl}
                       onChange={(e) => setFormUrl(e.target.value)} placeholder="http://10.10.41.52" />
            <TextField size="small" label={instanceId ? 'Token (leave blank to keep)' : 'Token'}
                       type="password" value={formToken} onChange={(e) => setFormToken(e.target.value)} />
            <Button sx={goldButtonSx(P)} disabled={busy || !formUrl} onClick={saveSetup}>
              Save
            </Button>
          </Box>
        </Box>
      )}

      {/* ── project picker ────────────────────────────────────────────────── */}
      {configured && !project && projects.length > 1 && (
        <Box sx={{ ...pageSurfaceSx(P) }}>
          <Typography variant="subtitle1" sx={{ p: 2, pb: 1, color: P.textPrimary }}>
            Select a project
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Project</TableCell>
                <TableCell>Branch</TableCell>
                <TableCell>Last pipeline</TableCell>
                <TableCell>Activity</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {projects.map((row) => (
                <TableRow key={row.id} hover onClick={() => chooseProject(row)} sx={{ cursor: 'pointer' }}>
                  <TableCell>
                    <Box sx={{ color: P.textPrimary }}>{row.name}</Box>
                    <Typography variant="caption" sx={{ color: P.textMuted }}>
                      {row.path_with_namespace}
                    </Typography>
                  </TableCell>
                  <TableCell sx={{ color: P.textSecondary }}>{row.default_branch}</TableCell>
                  <TableCell><StatusPill status={row.last_pipeline?.status} P={P} /></TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{when(row.last_activity_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}

      {/* ── project ───────────────────────────────────────────────────────── */}
      {configured && project && (
        <Box sx={{ ...pageSurfaceSx(P), p: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
            {path && (
              <Button size="small" startIcon={<BackIcon fontSize="small" />} onClick={() => setPath('')}>
                Root
              </Button>
            )}
            <Typography variant="subtitle1" sx={{ color: P.textPrimary }}>
              {project}{path ? ` / ${path}` : ''}
            </Typography>
            <Box sx={{ flex: 1 }} />
            <Select size="small" value={ref} onChange={(e) => setRef(String(e.target.value))} sx={{ minWidth: 140 }}>
              {(branches.length ? branches : [ref]).map((b) => (
                <MenuItem key={b} value={b}>{b}</MenuItem>
              ))}
            </Select>
          </Box>

          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
            <Box sx={{ flex: '1 1 320px', minWidth: 280 }}>
              <Table size="small">
                <TableBody>
                  {entries.map((e) => (
                    <TableRow
                      key={e.path}
                      hover
                      sx={{ cursor: 'pointer' }}
                      onClick={() => (e.type === 'tree' ? setPath(e.path) : openEntry(e, ref))}
                    >
                      <TableCell sx={{ width: 28, color: P.textMuted }}>
                        {e.type === 'tree' ? <FolderIcon fontSize="small" /> : <FileIcon fontSize="small" />}
                      </TableCell>
                      <TableCell sx={{ color: P.textPrimary }}>{e.name}</TableCell>
                    </TableRow>
                  ))}
                  {entries.length === 0 && (
                    <TableRow>
                      <TableCell sx={{ color: P.textMuted }}>
                        {busy ? 'Loading…' : 'Empty directory'}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </Box>

            <Box sx={{ flex: '2 1 420px', minWidth: 320 }}>
              <Collapse in={Boolean(openFile)}>
                {openFile && (
                  <Box sx={{ mb: 2 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                      <FileIcon fontSize="small" sx={{ color: P.textMuted, mr: 1 }} />
                      <Typography variant="subtitle2" sx={{ color: P.textPrimary }}>
                        {openFile.path}
                      </Typography>
                    </Box>
                    <Markdown doc={openFile} P={P} />
                  </Box>
                )}
              </Collapse>
              {!openFile && (
                <>
                  <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                    <ReadmeIcon fontSize="small" sx={{ color: P.accentText, mr: 1 }} />
                    <Typography variant="subtitle2" sx={{ color: P.textPrimary }}>
                      {readme?.path || 'README'}
                    </Typography>
                  </Box>
                  {readme ? <Markdown doc={readme} P={P} /> : (
                    <Typography variant="body2" sx={{ color: P.textMuted }}>
                      No README on this branch.
                    </Typography>
                  )}
                </>
              )}
            </Box>
          </Box>
        </Box>
      )}
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