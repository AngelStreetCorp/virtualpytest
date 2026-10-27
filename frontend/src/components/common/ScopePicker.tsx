/**
 * ScopePicker — one header control for Server, Workspace and Project.
 *
 * Closed it is a fixed-width chip: the server name plus a filter badge (funnel + count of picked workspace/project) when a workspace
 * and/or project is picked (the names are in the tooltip and the popover). Open it is a
 * three-column popover, one column per scope. Server switching (incl. the needs-auth sign-in)
 * lives in `useServerPicker`; workspace and project keep their own contexts.
 */
import React, { useMemo, useState } from 'react';
import { Box, ButtonBase, CircularProgress, Divider, Popover, Tooltip, Typography } from '@mui/material';
import {
  Check as CheckIcon,
  FilterAlt as FilterIcon,
  KeyboardArrowDown as CaretIcon,
  Lock as LockIcon,
  Public as PublicIcon,
} from '@mui/icons-material';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { useServerPicker } from '../../hooks/useServerPicker';
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { useCurrentProject } from '../../hooks/common/useCurrentProject';
import { ALL_SERVERS_SENTINEL, isAllServersSentinel } from '../../lib/allServer/scope';
import { TYPOGRAPHY } from '../../constants/typography';

// Fixed, so picking a workspace or project never moves the nav items to its right.
const CHIP_WIDTH = 190;

interface RowProps {
  selected: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
  trailing?: React.ReactNode;
}

const Row: React.FC<RowProps> = ({ selected, disabled, onClick, children, trailing }) => {
  const P = useAgentChatPalette();
  return (
    <ButtonBase
      onClick={onClick}
      disabled={disabled}
      sx={{
        width: '100%',
        justifyContent: 'space-between',
        gap: 1,
        px: 1,
        py: 0.5,
        borderRadius: 1,
        fontSize: TYPOGRAPHY.body.size,
        textAlign: 'left',
        color: selected ? P.selectedText : P.textPrimary,
        bgcolor: selected ? P.selectedBg : 'transparent',
        '&:hover': { bgcolor: selected ? P.selectedBg : P.hoverBg },
        // The rows of the open picker are buttons too: they say where the
        // keyboard is (BUG-0799).
        '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: -2 },
        '&.Mui-disabled': { color: P.error, opacity: 1 },
      }}
    >
      <Box sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{children}</Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexShrink: 0 }}>
        {trailing}
        {selected && <CheckIcon sx={{ fontSize: TYPOGRAPHY.body.size }} />}
      </Box>
    </ButtonBase>
  );
};

const Column: React.FC<{ title: string; last?: boolean; children: React.ReactNode }> = ({ title, last, children }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      sx={{
        width: 210,
        p: 1,
        display: 'flex',
        flexDirection: 'column',
        gap: 0.25,
        borderRight: last ? 'none' : `1px solid ${P.borderColor}`,
        maxHeight: 340,
        overflowY: 'auto',
      }}
    >
      <Typography sx={{ fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted, px: 1, pb: 0.5 }}>{title}</Typography>
      {children}
    </Box>
  );
};

const ScopePicker: React.FC = () => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const server = useServerPicker();
  const { userWorkspaces, activeWorkspace, setActiveWorkspace } = useWorkspaceContext();
  const { projects, currentProject, setCurrentProject, isLoading, isOnScopeAwarePage } = useCurrentProject();

  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  const workspaces = useMemo(() => {
    const seen = new Set<string>();
    return userWorkspaces.filter((ws) => {
      if (seen.has(ws.id)) return false;
      seen.add(ws.id);
      return true;
    });
  }, [userWorkspaces]);

  const serverLabel = isAllServersSentinel(server.selectedServer ?? '')
    ? t('All servers')
    : server.selectedServer
    ? server.labelFor(server.selectedServer)
    : t('No server');
  const scopeParts = [activeWorkspace?.name, currentProject?.name].filter(Boolean) as string[];
  const filterCount = scopeParts.length;
  const showScopeWarning = isOnScopeAwarePage && !currentProject;
  const open = Boolean(anchor);

  const chip = (
    <ButtonBase
      onClick={(e) => setAnchor(e.currentTarget)}
      disabled={server.isServerChanging}
      aria-haspopup="true"
      aria-expanded={open}
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 0.75,
        width: CHIP_WIDTH,
        minWidth: CHIP_WIDTH,
        px: 1.25,
        py: 0.5,
        fontSize: TYPOGRAPHY.body.size,
        // No border, no box-shadow, no background. The chip is a transparent label with
        // a caret, the same as every other item in the bar. UIUX.md "no bar chrome" rule.
        border: 'none',
        boxShadow: 'none',
        color: P.textPrimary,
        opacity: server.isServerChanging ? 0.7 : 1,
        flexShrink: 0,
        '&:hover': { color: P.accent },
        // The chip is the first tab stop of the app, so it has to show where the
        // keyboard is. The button base resets the outline, and without this the
        // focus was invisible (BUG-0799).
        '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: 2 },
      }}
    >
      {/* Closed: the name is centred in the chip. Open: it stays left-aligned, like the popover rows. */}
      <Box component="span" sx={{ flex: 1, minWidth: 0, textAlign: open ? 'left' : 'center', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {serverLabel}
      </Box>
      {filterCount > 0 && (
        <Box
          component="span"
          sx={{ flexShrink: 0, display: 'inline-flex', alignItems: 'center', gap: 0.25, fontSize: TYPOGRAPHY.microMeta.size, lineHeight: '1rem', color: P.accent, fontWeight: 600 }}
        >
          <FilterIcon sx={{ fontSize: TYPOGRAPHY.microMeta.size }} />
          {filterCount}
        </Box>
      )}
      {server.isServerChanging ? <CircularProgress size={14} /> : <CaretIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size, flexShrink: 0 }} />}
    </ButtonBase>
  );

  return (
    <>
      <Tooltip
        title={showScopeWarning ? t('Pick a project to scope this page') : scopeParts.length > 0 ? `${serverLabel} · ${scopeParts.join(' / ')}` : serverLabel}
        placement="bottom"
        arrow
      >
        <span>{chip}</span>
      </Tooltip>

      <Popover
        open={open}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        slotProps={{ paper: { sx: { mt: 0.5 } } }}
      >
        <Box sx={{ display: 'flex' }}>
          <Column title={t('Server')}>
            {/* TASK-113 PR-C + BUG-0577: the desktop scope picker only
                shows the "All servers" row when 2+ configured servers
                exist. A single-server deployment has nothing to federate,
                so the row collapses to "the only thing there is" and
                would only waste a click. Mirrors the mobile
                ServerSelector behaviour. */}
            {server.availableServers.length > 1 && (
              <>
                <Row
                  key={ALL_SERVERS_SENTINEL}
                  selected={isAllServersSentinel(server.selectedServer ?? '')}
                  onClick={() => {
                    server.handleChange(ALL_SERVERS_SENTINEL);
                    setAnchor(null);
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, fontWeight: 600 }}>
                    <PublicIcon sx={{ fontSize: TYPOGRAPHY.body.size, opacity: 0.85 }} />
                    {t('All servers')}
                  </Box>
                </Row>
                <Divider sx={{ my: 0.5 }} />
              </>
            )}
            {server.availableServers.map((url) => {
              const failed = server.failedServers.has(url);
              const needsAuth = server.serverAuthStates[url] === 'needs-auth';
              return (
                <Row
                  key={url}
                  selected={url === server.selectedServer}
                  disabled={failed}
                  onClick={() => {
                    server.handleChange(url);
                    setAnchor(null);
                  }}
                  trailing={
                    failed ? (
                      <Typography sx={{ fontSize: TYPOGRAPHY.microMeta.size, color: P.error }}>{t('Offline')}</Typography>
                    ) : needsAuth ? (
                      <LockIcon sx={{ fontSize: TYPOGRAPHY.body.size, opacity: 0.7 }} />
                    ) : undefined
                  }
                >
                  {server.labelFor(url)}
                </Row>
              );
            })}
          </Column>

          <Column title={t('Workspace')}>
            <Row selected={!activeWorkspace} onClick={() => setActiveWorkspace(null)}>{t('All')}</Row>
            {workspaces.map((ws) => (
              <Row key={ws.id} selected={activeWorkspace?.id === ws.id} onClick={() => setActiveWorkspace(ws.id)}>
                {ws.name}
              </Row>
            ))}
          </Column>

          <Column title={t('Project')} last>
            <Row selected={!currentProject} onClick={() => setCurrentProject(null)}>{t('All')}</Row>
            {isLoading && projects.length === 0 && (
              <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted, px: 1 }}>{t('Loading…')}</Typography>
            )}
            {projects.map((p) => (
              <Row key={p.id} selected={currentProject?.id === p.id} onClick={() => setCurrentProject(p.id)}>
                {p.name}
              </Row>
            ))}
          </Column>
        </Box>

      </Popover>

      {server.authDialog}
    </>
  );
};

export default ScopePicker;
