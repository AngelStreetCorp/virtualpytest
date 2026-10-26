import { Box, Button, Card, CardContent, FormControl, MenuItem, Select, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import ViewTimeline from '@mui/icons-material/ViewTimeline';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { PageTitle, goldButtonSx, pageSurfaceSx, segmentedSx } from '../components/common/PageChrome';
import { RecHostStreamModal } from '../components/rec/RecHostStreamModal';
import { FlagFilter, TimelineGrid, fmtTod } from '../components/timeline/TimelineGrid';
import { TimelinePositionBar } from '../components/timeline/TimelinePositionBar';
import { MAX_WINDOW, SlotWindow, TimelineLayout, TimelineScroller } from '../components/timeline/TimelineScroller';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { DeviceDataProvider } from '../contexts/device/DeviceDataContext';
import { HostManagerProvider } from '../contexts/HostManagerProvider';
import { useI18n } from '../i18n/useI18n';
import { TimelineCell, TimelineLevel, useTimeline } from '../hooks/useTimeline';
import { supportKey, useTimelineSupport } from '../hooks/useTimelineSupport';
import { useHostData } from '../hooks/useHostManager';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { Device, Host } from '../types/common/Host_Types';
import { TYPOGRAPHY } from '../constants/typography';

const COLUMNS: Record<TimelineLevel, number> = { day: 12, hour: 12, ten: 10 };
const LAYOUT_KEY = 'virtualpytest:timeline-layout';

const readLayout = (): TimelineLayout => {
  try {
    return localStorage.getItem(LAYOUT_KEY) === 'strip' ? 'strip' : 'grid';
  } catch {
    return 'grid';
  }
};

const TimelineContent: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const navigate = useNavigate();
  const { isMobile } = useResponsiveMode();
  const { getAllHosts, getHostByName } = useHostData();
  const [params, setParams] = useSearchParams();

  // Devices that record video (they have a capture path); only those the host has built a Timeline for are listed (a link to a
  // device without one still opens it, with the message that says how to turn it on).
  const candidates = useMemo(
    () =>
      getAllHosts().flatMap((h) =>
        (h.devices || []).filter((d) => d.video_capture_path).map((d) => ({ host: h, device: d })),
      ),
    [getAllHosts],
  );
  const { supported, checking } = useTimelineSupport(candidates);
  const wantedHost = params.get('host') || '';
  const wantedDevice = params.get('device') || '';
  const choices = useMemo(
    () =>
      candidates.filter(
        (c) => supported.has(supportKey(c.host.host_name, c.device.device_id)) || (c.host.host_name === wantedHost && c.device.device_id === wantedDevice),
      ),
    [candidates, supported, wantedHost, wantedDevice],
  );
  const hostName = wantedHost || choices[0]?.host.host_name || '';
  const deviceId = wantedDevice || (wantedHost ? '' : choices[0]?.device.device_id) || '';
  const host = hostName ? getHostByName(hostName) : null;
  const device = host?.devices?.find((d) => d.device_id === deviceId) || null;

  const tl = useTimeline(host, device?.device_id);
  const { slots, ensureTracks } = tl;

  // Opens on the last finished 10 minutes; zoom out goes 1 h, then 24 h.
  const [level, setLevel] = useState<TimelineLevel>('ten');
  const [layout, setLayout] = useState<TimelineLayout>(readLayout);
  const [hour, setHour] = useState<number | null>(null);
  const [win, setWin] = useState<SlotWindow | null>(null);
  const [visible, setVisible] = useState<number | null>(null);
  const [jump, setJump] = useState<{ slot: number; nonce: number } | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [playerAt, setPlayerAt] = useState<number | null>(null);
  const startedRef = useRef(false);
  const nonce = useRef(0);

  // Show a slot at the top of the 10 min scroll (opens a window around it).
  const goToSlot = useCallback(
    (slot: number) => {
      if (!slots.length) return;
      const s = Math.max(0, Math.min(slots.length - 1, slot));
      const from = Math.max(0, s - 1);
      setWin({ from, to: Math.min(slots.length - 1, from + MAX_WINDOW - 1) });
      nonce.current += 1;
      setJump({ slot: s, nonce: nonce.current });
      setVisible(s);
    },
    [slots.length],
  );

  // Start on the newest finished chunk (the growing one has no pictures yet).
  useEffect(() => {
    if (startedRef.current || !slots.length) return;
    const now = Date.now() / 1000;
    // older than 3 min: the service has had time to build it (it builds a chunk 90 s after it ends, every minute)
    const finished = tl.chunks.filter((c) => now - c.endEpoch > 180);
    const start = finished[finished.length - 1] ?? tl.chunks[tl.chunks.length - 1];
    const idx = slots.findIndex((s) => s.hour === start.hour && s.chunkIndex === start.chunkIndex);
    startedRef.current = true;
    setHour(start.hour);
    goToSlot(idx >= 0 ? idx : slots.length - 1);
  }, [slots, tl.chunks, goToSlot]);

  // Flags of every chunk: they colour the position bar and the tiles.
  useEffect(() => {
    ensureTracks(tl.chunks.map((c) => ({ hour: c.hour, chunkIndex: c.chunkIndex })));
  }, [tl.chunks, ensureTracks]);

  const cellsFor = useCallback((slot: { hour: number; chunkIndex: number }) => tl.tenCells(slot.hour, slot.chunkIndex), [tl]);

  const cells: TimelineCell[] = useMemo(() => {
    if (level === 'day') return tl.dayCells();
    if (level === 'hour') return hour === null ? [] : tl.hourCells(hour);
    if (!win) return [];
    return slots.slice(win.from, win.to + 1).flatMap(cellsFor);
  }, [level, hour, win, slots, tl, cellsFor]);

  // Event filter: the options follow the profile, an event type only listed when the device's tracks carry it
  // (ad breaks need the ad-meter profile; freeze / black screen are plain monitoring).
  const [only, setOnly] = useState<FlagFilter>('all');
  const hasAds = useMemo(() => cells.some((c) => (c.flags?.ad ?? 0) > 0), [cells]);
  useEffect(() => { if (only === 'ad' && !hasAds) setOnly('all'); }, [only, hasAds]);

  const sel = selectedKey !== null ? cells.find((c) => c.key === selectedKey) ?? null : null;
  const columns = isMobile && level !== 'ten' ? 6 : COLUMNS[level];
  const visibleSlot = visible !== null ? slots[visible] : undefined;

  const changeLayout = (l: TimelineLayout) => {
    setLayout(l);
    try {
      localStorage.setItem(LAYOUT_KEY, l);
    } catch {
      /* the choice just is not remembered */
    }
  };

  const switchLevel = (l: TimelineLevel) => {
    setSelectedKey(null);
    if (l === 'ten' && visible !== null) goToSlot(visible);
    if (l === 'hour' && hour === null && visibleSlot) setHour(visibleSlot.hour);
    if (l === 'hour' && level === 'ten' && visibleSlot) setHour(visibleSlot.hour);
    setLevel(l);
  };

  const zoomIn = useCallback(
    (key: string) => {
      const c = cells.find((x) => x.key === key);
      if (!c) return;
      if (level === 'day') {
        setHour(c.hour);
        setLevel('hour');
      } else if (level === 'hour') {
        const idx = slots.findIndex((s) => s.hour === c.hour && s.chunkIndex === c.chunkIndex);
        if (idx >= 0) goToSlot(idx);
        setLevel('ten');
      } else {
        return;
      }
      setSelectedKey(null);
    },
    [cells, level, slots, goToSlot],
  );

  const zoomOut = useCallback(() => {
    setSelectedKey(null);
    if (level === 'ten') {
      if (visibleSlot) setHour(visibleSlot.hour);
      setLevel('hour');
    } else {
      setLevel('day');
    }
  }, [level, visibleSlot]);

  const step = useCallback(
    (dir: -1 | 1) => {
      setSelectedKey(null);
      if (level === 'ten') {
        if (visible !== null) goToSlot(visible + dir);
      } else if (level === 'hour' && hour !== null) {
        const at = tl.hours.indexOf(hour);
        const n = tl.hours[at + dir];
        if (n !== undefined) setHour(n);
      }
    },
    [level, visible, hour, tl.hours, goToSlot],
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!cells.length) return;
    const at = selectedKey !== null ? cells.findIndex((c) => c.key === selectedKey) : 0;
    const move = (n: number) => setSelectedKey(cells[Math.max(0, Math.min(cells.length - 1, n))].key);
    const vertical = columns;
    if (e.key === 'ArrowRight') move(at + 1);
    else if (e.key === 'ArrowLeft') move(at - 1);
    else if (e.key === 'ArrowDown' && vertical) move(at + vertical);
    else if (e.key === 'ArrowUp' && vertical) move(at - vertical);
    else if (e.key === 'Enter' && selectedKey !== null) zoomIn(selectedKey);
    else if (e.key === 'Escape') zoomOut();
    else if (e.key === 'PageDown') step(1);
    else if (e.key === 'PageUp') step(-1);
    else return;
    e.preventDefault();
  };

  const pick = (h: Host, d: Device) => {
    setParams({ host: h.host_name, device: d.device_id });
    setLevel('ten');
    setHour(null);
    setWin(null);
    setVisible(null);
    setJump(null);
    startedRef.current = false;
    setSelectedKey(null);
  };

  // The position bar's frame: the 10 min on screen, or the hour.
  const frame = useMemo(() => {
    if (level === 'ten') return visible !== null ? { from: visible, to: visible } : null;
    if (level === 'hour' && hour !== null) {
      const idx = slots.map((s, i) => (s.hour === hour ? i : -1)).filter((i) => i >= 0);
      return idx.length ? { from: idx[0], to: idx[idx.length - 1] } : null;
    }
    return null;
  }, [level, visible, hour, slots]);

  const onBarJump = (i: number) => {
    setSelectedKey(null);
    if (level === 'ten') goToSlot(i);
    else if (slots[i]) setHour(slots[i].hour);
  };

  // The window on screen, shown next to the title: it is the one thing the header has to say.
  const windowLabel =
    level === 'day'
      ? t('Last 24 h')
      : level === 'hour'
        ? `${String(hour ?? 0).padStart(2, '0')}:00 – ${String(((hour ?? 0) + 1) % 24).padStart(2, '0')}:00`
        : visibleSlot
          ? `${fmtTod(visibleSlot.hour * 3600 + visibleSlot.chunkIndex * 600, false)} – ${fmtTod(visibleSlot.hour * 3600 + visibleSlot.chunkIndex * 600 + 600, false)}`
          : '';

  const barVertical = layout === 'grid' && !isMobile;
  const rowLabels = useMemo(() => {
    const rows = Math.ceil(cells.length / columns);
    return Array.from({ length: rows }, (_, r) => (cells[r * columns] ? fmtTod(cells[r * columns].tod, level !== 'day') : ''));
  }, [cells, columns, level]);

  // No device at all with a Timeline (checked, none found): say how to turn one on, instead of an empty picker.
  // Each flavour shows as a centered card (icon, heading, one short line, one gold CTA) so the user
  // gets one thing to click. The CTA label matches what action will actually do: docs page,
  // sibling monitoring page, or nothing for a load error.
  const noneSupported = !device && !checking && choices.length === 0;
  const emptyState: { heading: string; body: string; ctaLabel?: string; ctaTo?: string } | null = noneSupported
    ? {
        heading: t('No Timeline yet'),
        body: t('24 h of thumbnail strips, built per device by vpt-timeline on the host.'),
        ctaLabel: t('How to enable'),
        ctaTo: '/docs/platform/timeline',
      }
    : tl.error === 'no_archive'
      ? {
          heading: t('No archive'),
          body: t('This host keeps no 24 h archive.'),
          ctaLabel: t('Open Heatmap'),
          ctaTo: '/monitoring/heatmap',
        }
      : tl.error
        ? {
            heading: t('Could not load'),
            body: t('Could not load the archive.'),
          }
        : tl.built === false
          ? {
              heading: t('Timeline not built'),
              body: t('Timeline is not built for this device. Turn it on in the host .env (DEVICE{N}_TIMELINE=true) and restart vpt-timeline.'),
              ctaLabel: t('How to enable'),
              ctaTo: '/docs/platform/timeline',
            }
          : null;

  const isEmpty = emptyState !== null;
  const showBar = level !== 'day' && !isEmpty && slots.length > 0;

  return (
    <Box sx={pageSurfaceSx(P)}>
      <PageTitle
        title={
          <>
            {t('Timeline')}
            {windowLabel && (
              <Box component="span" data-testid="timeline-window" sx={{ ml: 2, fontWeight: 500, color: P.accentText, fontVariantNumeric: 'tabular-nums' }}>
                {windowLabel}
              </Box>
            )}
          </>
        }
        subtitle={
          device
            ? `${hostName} · ${device.device_name}${sel ? ` · ${t('Selected')} ${fmtTod(sel.tod, true)} – ${fmtTod(sel.tod + sel.spanS, true)}` : ''}`
            : undefined
        }
        right={
          isEmpty ? (
            // Empty: picker / level / layout / filter / Open in player all do nothing.
            // Keep sibling monitoring navigation so the user can pivot without going back.
            <>
              <Button size="small" onClick={() => navigate('/monitoring/heatmap')}>{t('Heatmap')}</Button>
              <Button size="small" onClick={() => navigate('/monitoring/incidents')}>{t('Incidents')}</Button>
            </>
          ) : (
            <>
              <FormControl size="small" sx={{ minWidth: 200 }}>
                <Select
                  value={device ? `${hostName}|${deviceId}` : ''}
                  displayEmpty
                  onChange={(e) => {
                    const [hn, did] = String(e.target.value).split('|');
                    const c = choices.find((x) => x.host.host_name === hn && x.device.device_id === did);
                    if (c) pick(c.host, c.device);
                  }}
                >
                  {choices.map((c) => (
                    <MenuItem key={`${c.host.host_name}|${c.device.device_id}`} value={`${c.host.host_name}|${c.device.device_id}`}>
                      {c.host.host_name} · {c.device.device_name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <ToggleButtonGroup exclusive size="small" value={level} onChange={(_, v) => v && switchLevel(v)} sx={segmentedSx(P)}>
                <ToggleButton value="ten" disabled={!slots.length}>{t('10 min')}</ToggleButton>
                <ToggleButton value="hour" disabled={!slots.length}>{t('1 h')}</ToggleButton>
                <ToggleButton value="day">{t('24 h')}</ToggleButton>
              </ToggleButtonGroup>
              <ToggleButtonGroup exclusive size="small" value={layout} onChange={(_, v) => v && changeLayout(v)} sx={segmentedSx(P)} aria-label={t('Layout')}>
                <ToggleButton value="grid">{t('Vertical')}</ToggleButton>
                <ToggleButton value="strip">{t('Horizontal')}</ToggleButton>
              </ToggleButtonGroup>
              <FormControl size="small" sx={{ minWidth: 150 }}>
                <Select value={only} onChange={(e) => setOnly(e.target.value as FlagFilter)} aria-label={t('Event filter')} displayEmpty>
                  <MenuItem value="all">{t('All events')}</MenuItem>
                  <MenuItem value="freeze">{t('Freeze')}</MenuItem>
                  <MenuItem value="blackscreen">{t('Black screen')}</MenuItem>
                  {hasAds && <MenuItem value="ad">{t('Ad breaks')}</MenuItem>}
                </Select>
              </FormControl>
              <Button variant="contained" size="small" disabled={!sel || !sel.sprite} sx={goldButtonSx(P)} onClick={() => sel && setPlayerAt(sel.tod)}>
                {t('Open in player')}
              </Button>
              <Button size="small" onClick={() => navigate('/monitoring/heatmap')}>{t('Heatmap')}</Button>
              <Button size="small" onClick={() => navigate('/monitoring/incidents')}>{t('Incidents')}</Button>
            </>
          )
        }
      />

      {showBar && !barVertical && <TimelinePositionBar slots={slots} frame={frame} onJump={onBarJump} />}

      <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}>
      <Box
        tabIndex={0}
        onKeyDown={onKeyDown}
        sx={{ flex: 1, minWidth: 0, outline: 'none', bgcolor: P.surface, border: `1px solid ${P.borderColor}`, borderRadius: 2, p: 1, minHeight: 240 }}
      >
        {emptyState ? (
          <Card sx={{ maxWidth: 560, mx: 'auto', mt: 2 }}>
            <CardContent sx={{ py: 4, textAlign: 'center', '&:last-child': { pb: 4 } }}>
              <Box sx={{ display: 'flex', justifyContent: 'center', mb: 2, color: P.accentText }}>
                <ViewTimeline sx={{ fontSize: TYPOGRAPHY.displayKpi.size }} />
              </Box>
              <Typography variant="h6" sx={{ fontSize: TYPOGRAPHY.navbarItem.size, fontWeight: 600, mb: 1, color: P.textPrimary }}>
                {emptyState.heading}
              </Typography>
              <Typography variant="body2" sx={{ color: P.textMuted, mb: emptyState.ctaLabel ? 3 : 0 }}>
                {emptyState.body}
              </Typography>
              {emptyState.ctaLabel && emptyState.ctaTo && (
                <Button variant="contained" size="small" sx={goldButtonSx(P)} onClick={() => navigate(emptyState.ctaTo!)}>
                  {emptyState.ctaLabel}
                </Button>
              )}
            </CardContent>
          </Card>
        ) : (tl.loading && !slots.length) || (!device && checking) ? (
          <Typography sx={{ color: P.textMuted, p: 2 }}>{t('Loading…')}</Typography>
        ) : !slots.length ? (
          <Typography sx={{ color: P.textMuted, p: 2 }}>{t('No archive for this device yet.')}</Typography>
        ) : level === 'ten' ? (
          win && (
            <TimelineScroller
              slots={slots}
              win={win}
              layout={layout}
              cellsFor={cellsFor}
              selectedKey={selectedKey}
              onSelect={setSelectedKey}
              only={only}
              onWindow={setWin}
              onVisible={setVisible}
              jump={jump}
            />
          )
        ) : (
          <Box sx={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '44px 1fr', gap: 0.75 }}>
            {!isMobile && (
              <Box sx={{ display: 'grid', gridTemplateRows: `repeat(${rowLabels.length}, 1fr)`, fontSize: TYPOGRAPHY.microMeta.size, color: P.textSecondary, fontVariantNumeric: 'tabular-nums' }}>
                {rowLabels.map((l, i) => <Box key={i}>{l}</Box>)}
              </Box>
            )}
            <Box>
              <TimelineGrid cells={cells} columns={columns} selectedKey={selectedKey} withSeconds={level !== 'day'} onSelect={setSelectedKey} onZoom={zoomIn} only={only} />
            </Box>
          </Box>
        )}
      </Box>
      {showBar && barVertical && (
        <TimelinePositionBar slots={slots} frame={frame} onJump={onBarJump} orientation="vertical" height="calc(100vh - 380px)" />
      )}
      </Box>

      {host && device && playerAt !== null && (
        <RecHostStreamModal host={host} device={device} isOpen onClose={() => setPlayerAt(null)} initialArchiveTime={playerAt} />
      )}
    </Box>
  );
};

const Timeline: React.FC = () => (
  <HostManagerProvider>
    <DeviceDataProvider>
      <TimelineContent />
    </DeviceDataProvider>
  </HostManagerProvider>
);

export default Timeline;
