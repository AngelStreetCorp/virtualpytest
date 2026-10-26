import {
  Article as LogsIcon,
  ExpandMore as ExpandMoreIcon,
  MoreVert as MoreIcon,
} from '@mui/icons-material';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  CircularProgress,
  IconButton,
  Menu,
  MenuItem,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useMemo, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { StatusDot, StatusDotTone } from '../common/StatusDot';
import { buildHostServices, ProfileInput, RawService, ServiceGroup, ServiceRow } from './hostServices';
import { TYPOGRAPHY } from '../../constants/typography';

export type ServiceAction = 'start' | 'stop' | 'restart';

interface Props {
  hostName: string;
  services: RawService[];
  profiles: ProfileInput;
  /** Status shown right after an action, before the next poll (Dashboard's optimisticStatus). */
  optimisticStatus: Record<string, string>;
  /** Single-service action in flight (shows the header spinner). */
  pending: boolean;
  /** Anything else running on the host or another action pending: menu actions stay disabled. */
  busy: boolean;
  canControl: boolean;
  onLogs: (service: RawService) => void;
  onAction: (service: RawService, action: ServiceAction) => Promise<void> | void;
  onRestartHostApi: () => void;
}

const NOT_RUNNING = ['stopped', 'inactive', 'not_installed'];

export const HostServicesAccordion: React.FC<Props> = ({
  hostName, services, profiles, optimisticStatus, pending, busy, canControl, onLogs, onAction, onRestartHostApi,
}) => {
  const { t, tn } = useI18n();
  const P = useAgentChatPalette();
  const [showMissing, setShowMissing] = useState(false);
  const [showOptional, setShowOptional] = useState(false);
  const [menu, setMenu] = useState<{ anchor: HTMLElement; row: ServiceRow } | null>(null);

  const shown = useMemo(
    () => services.map((s) => ({ ...s, status: optimisticStatus[`${hostName}::${s.name}`] ?? s.status })),
    [services, optimisticStatus, hostName],
  );
  const model = useMemo(() => buildHostServices(shown, profiles), [shown, profiles]);
  const { counts } = model;

  const reasonText = (r: string) => {
    switch (r) {
      case 'no device needs it': return t('no device needs it');
      case 'tv_lite: monitoring off': return t('tv_lite: monitoring off');
      case 'not needed on this host': return t('not needed on this host');
      default: return r;
    }
  };
  const wordText = (w: string) => {
    switch (w) {
      case 'active': return t('active');
      case 'idle': return t('idle');
      case 'down': return t('down');
      case 'stuck': return t('stuck');
      case 'not installed': return t('not installed');
      default: return w;
    }
  };

  const labelText = (l: string) => {
    switch (l) {
      case 'Image': return t('Image');
      case 'Audio': return t('Audio');
      case 'Subtitle': return t('Subtitle');
      case 'VNC': return t('VNC');
      default: return l;
    }
  };

  const renderRow = (row: ServiceRow) => {
    const tone = row.state === 'active' ? 'success' : row.state === 'down' ? 'error' : 'muted';
    // Optional / Not-installed rows never render an inline subtitle — the dashboard
    // cards have no width for "tv_lite: monitoring off" / "no device needs it" /
    // "not needed on this host", and those long reasons used to truncate to "v_lite: mo…"
    // / "not neede…" inside Core/Monitoring. Idle rows now collapse to Optional
    // (see hostServices.ts) and stay tight here: label + status word only.
    const extra = row.group === 'optional'
      ? ''
      : [
          row.deviceCount !== null && row.group === 'monitoring' && row.deviceCount > 0
            ? tn(row.deviceCount, '{count} device', '{count} devices')
            : '',
          reasonText(row.reason),
        ].filter(Boolean).join(' · ');
    // Wrap the service name in a Tooltip when the row has a description — the
    // standalone info icon is gone (was visual noise), the description now
    // surfaces on hover of the name itself. Underline + cursor hint the user
    // that the name is interactive.
    const nameLabel = labelText(row.label);
    const nameTypography = (
      <Typography
        variant="body2"
        noWrap
        sx={{
          flexShrink: 0,
          fontWeight: 500,
          fontSize: TYPOGRAPHY.body.size,
          color: row.state === 'idle' ? P.textMuted : undefined,
          textDecoration: row.description ? 'underline dotted' : 'none',
          textUnderlineOffset: '3px',
          cursor: row.description ? 'help' : 'default',
        }}
      >
        {nameLabel}
      </Typography>
    );
    return (
      <Box
        key={row.key}
        sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 12px 24px', alignItems: 'center', columnGap: 0.75, py: 0.25, minHeight: 24 }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
          {row.description ? (
            <Tooltip title={row.description} placement="top">
              <Box sx={{ minWidth: 0, display: 'flex' }}>{nameTypography}</Box>
            </Tooltip>
          ) : (
            nameTypography
          )}
          {extra && (
            <Typography variant="caption" noWrap sx={{ color: P.textMuted, ml: 0.5, minWidth: 0 }} title={extra}>
              {extra}
            </Typography>
          )}
        </Box>
        {/* LED only — the state word lives on the dot tooltip. Keeps the row quiet
            when most services are active (the common case for a healthy host). */}
        <Tooltip title={wordText(row.word)}>
          <Box sx={{ justifySelf: 'start' }}>
            <StatusDot tone={tone} word="" />
          </Box>
        </Tooltip>
        <IconButton
          size="small"
          aria-label={t('Actions for {service}', { service: nameLabel })}
          sx={{ p: 0.25, color: P.textSecondary, opacity: 0.6, '&:hover': { opacity: 1 } }}
          onClick={(e) => setMenu({ anchor: e.currentTarget, row })}
        >
          <MoreIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />
        </IconButton>
      </Box>
    );
  };

  const renderGroup = (group: ServiceGroup, title: string) => {
    const rows = model.groups[group];
    if (!rows.length) return null;
    return (
      <Box key={group} sx={{ mb: 0.25 }}>
        <Typography
          variant="caption"
          sx={{ display: 'block', fontWeight: 600, color: P.textSecondary, textTransform: 'none' }}
        >
          {title}
        </Typography>
        {rows.map(renderRow)}
      </Box>
    );
  };

  /** Same as renderGroup but without the group-header Typography. Used for the
   *  Optional toggle, which already labels the section as "Optional (N)" — adding
   *  a second "Optional" header inside the expanded body would be redundant. */
  const renderGroupRows = (group: ServiceGroup) => {
    const rows = model.groups[group];
    if (!rows.length) return null;
    return <Box key={group} sx={{ mb: 0.25 }}>{rows.map(renderRow)}</Box>;
  };

  /** A small caption that explains the overall health LED in the summary: "6 running" /
   *  "4 running · 2 down". Hidden when every service is "active" — the green LED is enough
   *  for the common case. Reuses the existing "{count} running" key for the alive count
   *  so we don't ship a parallel "alive" string just for the summary. */
  const overallCaption = (() => {
    const { running, down, idle } = counts;
    if (down === 0 && idle === 0) return null;
    const parts: string[] = [];
    if (running > 0) parts.push(tn(running, '{count} running', '{count} running'));
    if (down > 0) parts.push(tn(down, '{count} down', '{count} down'));
    if (idle > 0) parts.push(tn(idle, '{count} idle', '{count} idle'));
    return parts.join(' · ');
  })();

  /** Overall LED tone for the summary — green when everything is active, red when any
   *  service is down. Idle = off on purpose (not needed here), so it never turns the LED amber. */
  const overallTone: StatusDotTone = counts.down > 0 ? 'error' : 'success';

  // Menu: every member service gets its own logs entry; start/stop/restart apply to all members.
  const menuRow = menu?.row;
  const members = menuRow?.members ?? [];
  const multi = members.length > 1;
  const allActive = members.every((m) => m.status === 'active');
  const allStopped = members.every((m) => m.status === 'stopped');
  const controllable = members.filter((m) => m.controllable);
  const hostApi = members.length === 1 && members[0].name === 'vpt-host';
  const close = () => setMenu(null);
  const run = (fn: () => void) => () => { close(); fn(); };
  // Remote view acts on two services: one after the other, so the second does not start while the first is pending.
  const runAll = async (action: ServiceAction) => { for (const m of controllable) await onAction(m, action); };

  return (
    <Accordion
      sx={{
        mb: 1.5,
        boxShadow: 'none',
        border: `1px solid ${P.borderColor}`,
        borderRadius: '8px',
        backgroundColor: P.background,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        // Same tightening as the Devices / Details accordions on the dashboard
        // card: 24 px min height, 0 px content margin, so the "Services (N)" title
        // sits on one tight line.
        sx={{
          minHeight: '24px',
          backgroundColor: 'transparent',
          '& .MuiAccordionSummary-content': { margin: '0px' },
          '& .MuiAccordionSummary-content.Mui-expanded': { margin: '0px' },
          '& .MuiAccordionSummary-root.Mui-expanded': { minHeight: '24px' },
          px: 1,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', minWidth: 0 }}>
          {/* "Services (N)" matches the dashboard's "Devices (N)" count style — same
              parenthetical pattern. The LED next to the title is the overall health
              indicator; the per-row LED reports each service. */}
          <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>{t('Services ({count})', { count: counts.running + counts.idle + counts.down })}</Typography>
          <Tooltip title={overallCaption || tn(counts.running, '{count} running', '{count} running')}>
            <Box sx={{ display: 'inline-flex' }}>
              <StatusDot tone={overallTone} />
            </Box>
          </Tooltip>
          {overallCaption && (
            <Typography variant="caption" sx={{ color: P.textSecondary }}>
              {overallCaption}
            </Typography>
          )}
          {pending && <CircularProgress size={14} thickness={5} />}
        </Box>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0, pb: 0.5, px: 1, backgroundColor: 'transparent', '&.MuiAccordionDetails-root': { pt: 0, pb: 0.5 } }}>
        {services.length === 0 ? (
          <Typography variant="caption" color="textSecondary">{t('Service details not available')}</Typography>
        ) : (
          <>
            {/* Core (left) and Monitoring (right) share a 2-column grid. Each column
                carries its own group header so the eye can scan them in parallel. */}
            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 1.5 }}>
              <Box>{renderGroup('core', t('Core'))}</Box>
              <Box>{renderGroup('monitoring', t('Monitoring'))}</Box>
            </Box>
            {/* Optional is collapsed by default — on a 24-device card it's the row that
                adds the most vertical space while being checked the least. Same chevron
                pattern as "Not installed" below so the two read as a pair. */}
            {model.groups.optional.length > 0 && (
              <Box sx={{ mt: 0.5 }}>
                <Box
                  component="button"
                  type="button"
                  onClick={() => setShowOptional((v) => !v)}
                  aria-expanded={showOptional}
                  sx={{ all: 'unset', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 0.5, color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}
                >
                  <ExpandMoreIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, transform: showOptional ? 'rotate(180deg)' : 'none' }} />
                  {t('Optional ({count})', { count: model.groups.optional.length })}
                </Box>
                {showOptional && (
                  <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 1.5 }}>
                    <Box>{renderGroupRows('optional')}</Box>
                  </Box>
                )}
              </Box>
            )}
            {model.notInstalled.length > 0 && (
              <Box sx={{ mt: 0.5 }}>
                <Box
                  component="button"
                  type="button"
                  onClick={() => setShowMissing((v) => !v)}
                  aria-expanded={showMissing}
                  sx={{ all: 'unset', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 0.5, color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}
                >
                  <ExpandMoreIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, transform: showMissing ? 'rotate(180deg)' : 'none' }} />
                  {t('Not installed ({count})', { count: model.notInstalled.length })}
                </Box>
                {showMissing && model.notInstalled.map((name) => (
                  // Same flush-left / white / body2 sizing as the Optional rows above.
                  // The "Not installed" toggle label is the only thing distinguishing
                  // these from a live service row — visual parity keeps the eye from
                  // reading the indent as a hierarchy signal.
                  <Typography key={name} variant="body2" sx={{ display: 'block', lineHeight: 1.7 }}>
                    {name}
                  </Typography>
                ))}
              </Box>
            )}
          </>
        )}
      </AccordionDetails>
      <Menu
        anchorEl={menu?.anchor}
        open={!!menu}
        onClose={close}
        slotProps={{ paper: { sx: { border: `1px solid ${P.borderColor}`, boxShadow: 'none', minWidth: 160 } } }}
      >
        {members.map((m) => {
          const stopped = NOT_RUNNING.includes(m.status);
          return (
            <MenuItem key={`logs-${m.name}`} dense disabled={stopped} onClick={run(() => onLogs(m))}>
              <LogsIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, mr: 1 }} />
              {multi ? t('Logs: {service}', { service: m.label }) : stopped ? t('No logs — service is not running') : t('View logs')}
            </MenuItem>
          );
        })}
        {canControl && (hostApi || controllable.length > 0) && [
          ...(hostApi ? [] : [
            <MenuItem key="start" dense disabled={busy || allActive} onClick={run(() => { void runAll('start'); })}>
              {t('Start')}
            </MenuItem>,
            <MenuItem key="stop" dense disabled={busy || allStopped} onClick={run(() => { void runAll('stop'); })}>
              {t('Stop')}
            </MenuItem>,
          ]),
          <MenuItem
            key="restart"
            dense
            disabled={busy}
            onClick={run(() => (hostApi ? onRestartHostApi() : void runAll('restart')))}
          >
            {t('Restart')}
          </MenuItem>,
        ]}
      </Menu>
    </Accordion>
  );
};
