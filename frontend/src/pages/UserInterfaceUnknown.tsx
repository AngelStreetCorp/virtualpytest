import {
  ArrowBack as ArrowBackIcon,
  ImageOutlined as ImageIcon,
} from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { ReferenceImagePreview } from '../components/verification/ReferenceImagePreview';
import { goldButtonSx, pageSurfaceSx, StatTiles } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import {
  UnknownScreen,
  UnknownScreenType,
  useUserInterfaceUnknown,
} from '../hooks/pages/useUserInterfaceUnknown';
import { TYPOGRAPHY } from '../constants/typography';

/**
 * A header cell never runs into its neighbour: it ellipsises on purpose and
 * the full text stays in the title (UI_STYLE S9).
 */
const headCellSx = {
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
} as const;

const thumbSx = (borderColor: string, textMuted: string) => ({
  width: 64,
  height: 36,
  borderRadius: '5px',
  border: `1px solid ${borderColor}`,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: textMuted,
  bgcolor: 'transparent',
  overflow: 'hidden',
});

/** Small muted caption under a value — the "signal" / "what it is" lines. */
const subSx = (P: ReturnType<typeof useAgentChatPalette>) => ({
  fontSize: TYPOGRAPHY.caption.size,
  color: P.textMuted,
  mt: 0.25,
  lineHeight: 1.45,
});

const typePillSx = (P: ReturnType<typeof useAgentChatPalette>, type: UnknownScreenType) =>
  type === 'nav_row'
    ? { bgcolor: P.hoverBg, color: P.textSecondary, borderColor: 'transparent' }
    : { bgcolor: `${P.accent}1f`, color: P.accentText, borderColor: `${P.accent}66` };

const pillBaseSx = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 0.5,
  fontSize: TYPOGRAPHY.caption.size,
  fontWeight: 500,
  px: 1,
  py: 0.2,
  borderRadius: 999,
  border: '1px solid transparent',
  whiteSpace: 'nowrap' as const,
};

const UserInterfaceUnknown: React.FC = () => {
  const P = useAgentChatPalette();
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const decodedName = name ? decodeURIComponent(name) : '';

  const { data, loading, error, refetch, acceptScreen, dismissScreen, pendingAction } =
    useUserInterfaceUnknown(decodedName);

  // Proposed names are editable in place; a rename is only sent when the reviewer
  // actually changed one, so the server keeps its own proposed_name otherwise.
  const [names, setNames] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);

  // What the server said back about the last action, and the rows it refused to
  // accept because their device has no tree at all — those must not offer Accept.
  const [notice, setNotice] = useState<{
    severity: 'success' | 'info' | 'warning' | 'error';
    text: string;
  } | null>(null);
  const [blocked, setBlocked] = useState<Record<string, string>>({});

  useEffect(() => {
    setNames({});
    setEditingId(null);
  }, [decodedName]);

  useEffect(() => {
    setBlocked({});
    setNotice(null);
  }, [decodedName]);

  const displayName = (s: UnknownScreen) => names[s.id] ?? s.proposedName;

  const handleRename = (id: string, value: string) =>
    setNames((prev) => ({ ...prev, [id]: value }));

  const editedLabel = (screen: UnknownScreen): string | undefined => {
    const edited = (names[screen.id] ?? '').trim();
    return edited && edited !== screen.proposedName ? edited : undefined;
  };

  const handleAccept = async (
    screen: UnknownScreen,
    mode: 'accept' | 'create_ui' | 'merge',
  ) => {
    const result = await acceptScreen(screen.id, mode, editedLabel(screen));

    if (result.ok) {
      const named = result.label || displayName(screen) || screen.id;
      setNotice({
        severity: 'success',
        text:
          mode === 'merge'
            ? `Merged as “${named}”.`
            : `Accepted as “${named}”${result.nodeId ? ` (${result.nodeId})` : ''}.`,
      });
      refetch();
      return;
    }

    if (result.needs === 'create_userinterface') {
      // Different device, no tree exists: remember it so the row stops offering Accept.
      const reason = result.message ?? 'This screen came from a device with no navigation tree.';
      setBlocked((prev) => ({ ...prev, [screen.id]: reason }));
      setNotice({ severity: 'error', text: reason });
      return;
    }

    if (result.needs === 'create_tree') {
      setNotice({ severity: 'error', text: result.message ?? 'Create a tree before accepting.' });
      return;
    }

    const message = result.message ?? 'The action failed.';
    // A partial success (node created, row not resolved) is a warning, not a failure —
    // saying so plainly beats hiding it.
    const partial = /row could not be marked resolved/i.test(message);
    // "already accepted" and "no fingerprint stored" are not the reviewer's mistake:
    // the row's state moved without them, so report it and re-read the list.
    const informational = /already .*nothing to do|no fingerprint stored/i.test(message);
    setNotice({
      severity: partial ? 'warning' : informational ? 'info' : 'error',
      text: message,
    });
    refetch();
  };

  const handleDismiss = async (screen: UnknownScreen) => {
    const result = await dismissScreen(screen.id);
    if (result.ok) {
      setNotice({ severity: 'success', text: 'Dismissed — it will not come back.' });
      refetch();
      return;
    }
    setNotice({ severity: 'error', text: result.message ?? 'Failed to dismiss this screen.' });
    refetch();
  };

  const renderThumb = (screen: { hasStill: boolean; thumbnailUrl?: string }) =>
    screen.hasStill ? (
      screen.thumbnailUrl ? (
        <ReferenceImagePreview
          referenceUrl={screen.thumbnailUrl}
          thumbnail
          thumbnailMaxWidth={64}
          thumbnailMaxHeight={36}
        />
      ) : (
        // A still exists but no image URL came back — keep the frame.
        <Box component="span" sx={thumbSx(P.borderColor, P.textMuted)}>
          <ImageIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
        </Box>
      )
    ) : null;

  const needsNameRows = () => {
    if (loading) {
      return (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 4, justifyContent: 'center' }}>
          <CircularProgress size={24} />
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>
            Scanning captures for unknown screens…
          </Typography>
        </Box>
      );
    }

    if (data.needsName.length === 0) {
      return (
        <Box sx={{ py: 4, textAlign: 'center' }}>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>
            Every screen this device shows has a node in its tree.
          </Typography>
        </Box>
      );
    }

    return (
      <TableContainer>
        {/* Column widths follow the content, not a percentage of the screen
            (UI_STYLE S3): the name column takes the rest, the others get the
            width their content needs. Below the table's own width the container
            scrolls sideways, so on a phone the headers no longer run into their
            neighbour (BUG-0813). */}
        <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 560 }}>
          <colgroup>
            <col style={{ width: 96 }} />
            <col />
            <col style={{ width: 96 }} />
            <col style={{ width: 64 }} />
            <col style={{ width: 116 }} />
          </colgroup>
          <TableHead>
            <TableRow>
              <TableCell align="center" sx={headCellSx} title="Screen">
                <strong>Screen</strong>
              </TableCell>
              <TableCell align="center" sx={headCellSx} title="Proposed name">
                <strong>Proposed name</strong>
              </TableCell>
              <TableCell align="center" sx={headCellSx} title="Type">
                <strong>Type</strong>
              </TableCell>
              <TableCell align="center" sx={headCellSx} title="Frames">
                <strong>Frames</strong>
              </TableCell>
              <TableCell align="center" sx={headCellSx} title="Actions">
                <strong>Actions</strong>
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.needsName.map((screen) => {
              // Set once the server refused to accept this row: its device has no tree.
              const blockedReason = blocked[screen.id];
              // A screen from a device with no tree cannot become a node — Accept is not
              // offered for it, before the first click or after the server says so.
              const crossDevice = Boolean(blockedReason) || screen.action === 'create_ui';
              const isBusy = pendingAction === screen.id;
              const busy = pendingAction !== null;
              const outlinedSx = {
                fontSize: TYPOGRAPHY.caption.size,
                py: 0.4,
                borderColor: P.borderColor,
                color: 'text.secondary',
                textTransform: 'none' as const,
              };

              return (
                <TableRow key={screen.id}>
                  <TableCell align="center">{renderThumb(screen)}</TableCell>
                  <TableCell>
                    {editingId === screen.id ? (
                      <TextField
                        size="small"
                        autoFocus
                        fullWidth
                        value={displayName(screen)}
                        onChange={(e) => handleRename(screen.id, e.target.value)}
                        onBlur={() => setEditingId(null)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') setEditingId(null);
                          if (e.key === 'Escape') {
                            setNames((prev) => {
                              const next = { ...prev };
                              delete next[screen.id];
                              return next;
                            });
                            setEditingId(null);
                          }
                        }}
                        sx={{
                          '& .MuiInputBase-root': { height: '30px' },
                          '& .MuiInputBase-input': { fontSize: TYPOGRAPHY.caption.size, p: '4px 6px' },
                        }}
                      />
                    ) : (
                      <Box
                        onClick={() => setEditingId(screen.id)}
                        sx={{ cursor: 'text', '&:hover': { color: P.accentText } }}
                        title="Click to rename"
                      >
                        <Typography
                          sx={{
                            fontFamily: 'monospace',
                            fontSize: TYPOGRAPHY.caption.size,
                            fontWeight: 600,
                            wordBreak: 'break-word',
                            color: displayName(screen) ? undefined : P.textMuted,
                          }}
                        >
                          {displayName(screen) || 'No name'}
                        </Typography>
                      </Box>
                    )}
                    {screen.summary && <Typography sx={subSx(P)}>{screen.summary}</Typography>}
                  </TableCell>
                  <TableCell align="center">
                    <Box component="span" sx={{ ...pillBaseSx, ...typePillSx(P, screen.type) }}>
                      {screen.type}
                    </Box>
                  </TableCell>
                  <TableCell align="center" sx={{ fontSize: TYPOGRAPHY.body.size }}>{screen.frames}</TableCell>
                  <TableCell align="center">
                    <Box
                      sx={{
                        display: 'flex',
                        gap: 0.5,
                        justifyContent: 'center',
                        flexWrap: 'wrap',
                      }}
                    >
                      <Tooltip
                        title={
                          crossDevice
                            ? 'Create the navigation tree for this other device, then add the screen.'
                            : 'Add this screen to the tree under the proposed name (capture fingerprint).'
                        }
                      >
                        <span>
                          <Button
                            size="small"
                            variant="contained"
                            disabled={busy}
                            onClick={() => handleAccept(screen, crossDevice ? 'create_ui' : 'accept')}
                            startIcon={
                              isBusy ? <CircularProgress size={11} color="inherit" /> : undefined
                            }
                            sx={{ ...(goldButtonSx(P) as object), fontSize: TYPOGRAPHY.caption.size, py: 0.4 }}
                          >
                            {crossDevice ? 'Create UI' : 'Accept'}
                          </Button>
                        </span>
                      </Tooltip>
                      {!crossDevice && (
                        <Tooltip title="Merge this screen into an existing node that already fingerprints the same view.">
                          <span>
                            <Button
                              size="small"
                              variant="outlined"
                              disabled={busy}
                              onClick={() => handleAccept(screen, 'merge')}
                              sx={outlinedSx}
                            >
                              Merge
                            </Button>
                          </span>
                        </Tooltip>
                      )}
                      <Tooltip title="Mark this screen as not a screen we care about. It will not be reported again.">
                        <span>
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={busy}
                            onClick={() => handleDismiss(screen)}
                            sx={outlinedSx}
                          >
                            Dismiss
                          </Button>
                        </span>
                      </Tooltip>
                    </Box>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
    );
  };

  return (
    <Box sx={pageSurfaceSx(P)}>
      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: 1.5 }}>
        <Tooltip title="Back to Interfaces">
          <IconButton
            onClick={() => navigate('/configuration/interface')}
            size="small"
            aria-label="Back to Interfaces"
            sx={{ color: 'text.secondary', mt: 0.25 }}
          >
            <ArrowBackIcon />
          </IconButton>
        </Tooltip>
        <Box sx={{ minWidth: 0 }}>
          <Typography
            component="h1"
            sx={{ fontSize: TYPOGRAPHY.pageTitle.size, fontWeight: 600, lineHeight: 1.3 }}
          >
            Unknown screens
          </Typography>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>
            {decodedName} — screens this device shows that have no node in its tree.
          </Typography>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}

      {notice && (
        <Alert severity={notice.severity} sx={{ mb: 1.5 }} onClose={() => setNotice(null)}>
          {notice.text}
        </Alert>
      )}

      {/* A failed load is not an empty report: an interface that does not exist
          must not read as "every screen has a node in its tree" (BUG-0795). */}
      {error ? null : (
        <>
      <StatTiles
        tiles={[
          {
            label: 'Needs a name',
            value: data.needsName.length,
            color: data.needsName.length > 0 ? P.warning : P.success,
          },
          { label: 'Filtered out', value: data.contentFilteredCount, color: P.textMuted },
          { label: 'Captures', value: data.capturesProcessed.toLocaleString() },
          { label: 'Last scan', value: data.lastScan },
        ]}
      />

      <Card sx={{ mb: 1.5, textAlign: 'center' }}>
        <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
          <Typography variant="h6" sx={{ mb: 0.5 }}>
            Needs a name
          </Typography>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 1.5 }}>
            Names come from <Box component="span" sx={{ fontFamily: 'monospace' }}>vision.dom</Box> — click a proposed name to change it.
          </Typography>
          {needsNameRows()}
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mt: 1.5, lineHeight: 1.6 }}>
            Names follow the existing{' '}
            <Box component="span" sx={{ fontFamily: 'monospace' }}>menu_submenu</Box> /{' '}
            <Box component="span" sx={{ fontFamily: 'monospace' }}>popup_A</Box> /{' '}
            <Box component="span" sx={{ fontFamily: 'monospace' }}>splashscreen_1</Box> convention.
            Accepting captures the fingerprint immediately — the scan runs in the background, so this
            list grows on its own.
          </Typography>
        </CardContent>
      </Card>

      <Card sx={{ mb: 1.5, textAlign: 'center' }}>
        <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
          <Typography variant="h6" sx={{ mb: 1.5 }}>
            Excluded as content
          </Typography>
          <TableContainer>
            <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 520 }}>
              <colgroup>
                <col style={{ width: 96 }} />
                <col />
                <col style={{ width: 140 }} />
                <col style={{ width: 64 }} />
              </colgroup>
              <TableHead>
                <TableRow>
                  <TableCell sx={headCellSx} title="Screen">
                    <strong>Screen</strong>
                  </TableCell>
                  <TableCell sx={headCellSx} title="What it is">
                    <strong>What it is</strong>
                  </TableCell>
                  <TableCell sx={headCellSx} title="Classification">
                    <strong>Classification</strong>
                  </TableCell>
                  <TableCell sx={headCellSx} title="Frames">
                    <strong>Frames</strong>
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.excludedAsContent.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      {renderThumb(row) ?? (
                        // No still was kept for this content cluster.
                        <Typography
                          component="span"
                          sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}
                        >
                          —
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Typography sx={{ fontSize: TYPOGRAPHY.body.size }}>{row.what}</Typography>
                    </TableCell>
                    <TableCell>
                      <Box
                        component="span"
                        sx={{
                          ...pillBaseSx,
                          bgcolor: P.hoverBg,
                          color: P.textSecondary,
                        }}
                      >
                        content · excluded
                      </Box>
                    </TableCell>
                    <TableCell sx={{ fontSize: TYPOGRAPHY.body.size }}>{row.frames}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, lineHeight: 1.6 }}>
        Rows come from the scan, read live from{' '}
        <Box component="span" sx={{ fontFamily: 'monospace' }}>
          /server/userinterface/getUnknownScreens
        </Box>
        . The scan runs in the background, so this list fills in on its own.
      </Typography>
        </>
      )}
    </Box>
  );
};

export default UserInterfaceUnknown;