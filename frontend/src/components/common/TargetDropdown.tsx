import {
  Box,
  Typography,
  Button,
  Checkbox,
  ListItemText,
  Chip,
  TextField,
  InputAdornment,
  IconButton,
  Popover,
  MenuItem,
} from "@mui/material";
import { Lock as LockIcon, Search as SearchIcon, Clear as ClearIcon, Star as StarIcon, ExpandMore as ExpandMoreIcon } from "@mui/icons-material";
import React, { useMemo, useState } from "react";

import { useAgentChatPalette } from "../../constants/agentChatTheme";
import { DeviceKey, useDeviceFavorites } from "../../hooks/useDeviceFavorites";
import { useI18n } from "../../i18n/useI18n";
import { TYPOGRAPHY } from "../../constants/typography";
import { AppIcon } from "../../constants/icons";
import { DeviceFavoriteGroupHeader } from "./DeviceFavoriteGroupHeader";
import { DeviceFavoriteStar } from "./DeviceFavoriteStar";
import { DeviceMaintenanceBadge } from "./DeviceMaintenanceBadge";

export interface TargetDropdownProps {
  /** Selected target labels. Single mode keeps at most one entry. */
  selected: string[];
  onChange: (value: string[]) => void;
  /** Target labels to choose from. */
  options: string[];
  /** Target label -> the (host, device) it stands for. Enables favorites and the host rail. */
  keys?: Record<string, DeviceKey>;
  /** Multi-select (device-control filter) or single-select (pickers that need one target). Default true. */
  multiple?: boolean;
  placeholder?: string;
  /** Closed-control width; the popover keeps its own size. Default 200. */
  width?: number;
  /** Locked targets show a lock icon and a "(Locked)" tag in the list and on the closed control. */
  isLocked?: (label: string) => boolean;
  /** Accent border and an AI icon on the closed control, e.g. when the AI picked the target. */
  highlight?: boolean;
}

// Targets popover: a host rail on the left (one row per host, never wraps, names capped by
// TARGET_HOST_MAX_CHARS) and that host's devices on the right. Tall enough to show a real list.
// One rule governs every select control in here (BUG-0822): the bar under the
// search box always means the WHOLE list (Select all takes every target, Clear
// drops every target), and the host's own Select all / Clear all sit on the
// right panel's host header, next to the list they apply to. A rail click cycles
// show -> select all -> clear, so one click never both navigates and edits the
// selection the operator was reading.
const TARGET_POPOVER_WIDTH = 580;
const TARGET_POPOVER_HEIGHT = 'min(560px, 70vh)';
const TARGET_RAIL_WIDTH = 230;
const TARGET_HOST_MAX_CHARS = 22;
// Tight rows: the default MenuItem + Checkbox padding gives ~42px per device.
export const TARGET_ROW_SX = { maxWidth: '100%', minHeight: 28, py: 0, px: 1 };
export const TARGET_CHECKBOX_SX = { flexShrink: 0, p: 0.25, mr: 0.75 };

// Closed-control text: none -> allLabel, one -> its name, several -> a count (the full list is the
// hover title) so a long selection never gets cut off mid-name.
export const renderSelectedValues = (selected: string[], allLabel: string, countLabel: (n: number) => string) => {
  if (selected.length === 0) return allLabel;
  if (selected.length === 1) return selected[0];
  return <span title={selected.join(", ")}>{countLabel(selected.length)}</span>;
};

export const TargetDropdown: React.FC<TargetDropdownProps> = ({
  selected,
  onChange,
  options,
  keys,
  multiple = true,
  placeholder = "All Targets",
  width = 200,
  isLocked,
  highlight = false,
}) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const favorites = useDeviceFavorites();
  const isFavoriteTarget = (option: string) => {
    const key = keys?.[option];
    return !!key && favorites.isFavorite(key.host_name, key.device_id);
  };
  // Free-text search lives *inside* the Targets dropdown so it costs no
  // horizontal row space. It narrows the option list shown; selection still
  // happens via the checkboxes below.
  const [targetSearch, setTargetSearch] = useState('');
  const [targetAnchor, setTargetAnchor] = useState<HTMLElement | null>(null);
  const [activeHost, setActiveHost] = useState<string | null>(null);
  const visibleTargetOptions = useMemo(() => {
    const q = targetSearch.trim().toLowerCase();
    if (!q) return options;
    return options.filter((option) => option.toLowerCase().includes(q));
  }, [options, targetSearch]);

  // Favorites chip (TASK-99): first click selects every favorite, a second click clears them.
  // Counts every favorite of the list, not only the ones a search leaves visible.
  const favoriteOptions = useMemo(
    () => options.filter(isFavoriteTarget),
    [options, keys, favorites.isFavorite],
  );
  const allFavoritesSelected =
    favoriteOptions.length > 0 && favoriteOptions.every((option) => selected.includes(option));
  const handleToggleFavorites = () => {
    if (allFavoritesSelected) {
      const removed = new Set(favoriteOptions);
      onChange(selected.filter((option) => !removed.has(option)));
    } else {
      onChange(Array.from(new Set([...selected, ...favoriteOptions])));
    }
  };
  const visibleFavorites = visibleTargetOptions.filter(isFavoriteTarget);
  const visibleOthers = visibleTargetOptions.filter((option) => !isFavoriteTarget(option));

  // Single mode: picking a target replaces the selection and closes the popover.
  const toggleTarget = (option: string) => {
    if (!multiple) {
      onChange([option]);
      setTargetAnchor(null);
      setTargetSearch("");
      return;
    }
    onChange(
      selected.includes(option) ? selected.filter((o) => o !== option) : [...selected, option],
    );
  };

  // `host` set = the host's own list: the " - host" suffix is dropped, it is the rail's selected row.
  const renderTargetOption = (option: string, host?: string) => {
    const key = keys?.[option];
    const suffix = host ? ` - ${host}` : '';
    const label = suffix && option.endsWith(suffix) ? option.slice(0, -suffix.length) : option;
    const locked = !!isLocked?.(option);
    return (
      <MenuItem key={option} dense selected={!multiple && selected.includes(option)} onClick={() => toggleTarget(option)} sx={{ ...TARGET_ROW_SX, opacity: locked ? 0.85 : 1 }}>
        {multiple && <Checkbox size="small" checked={selected.includes(option)} sx={TARGET_CHECKBOX_SX} />}
        <ListItemText
          primary={label}
          title={option}
          primaryTypographyProps={{ variant: 'body2', noWrap: true }}
          sx={{ minWidth: 0 }}
        />
        {locked && <LockIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: "warning.main", ml: 0.5 }} />}
        {locked && <Typography variant="caption" color="warning.main" sx={{ ml: 0.5, whiteSpace: "nowrap" }}>{t("(Locked)")}</Typography>}
        <DeviceMaintenanceBadge target={option} size={14} />
        {key && (
          <Box sx={{ ml: 'auto', pl: 1, display: 'flex' }}>
            <DeviceFavoriteStar hostName={key.host_name} deviceId={key.device_id} />
          </Box>
        )}
      </MenuItem>
    );
  };

  // Group targets by host so a single click can toggle every device on that
  // host. Targets are formatted as "device_name - host_name" for regular
  // devices, or just "device_name" (no " - host") for host-only entries
  // (VNC desktops, *_Host) — getDeviceTargetLabel strips the host suffix
  // for those because there is exactly one device per host. For those
  // entries we look up the real host_name through keys (BUG-0580),
  // so a host with a single host_vnc device still groups under its host
  // and shows up in the pill row.
  const TARGET_HOST_SEP = ' - ';
  const hostGroups = useMemo(() => {
    const byHost = new Map<string, string[]>();
    options.forEach((option) => {
      const idx = option.lastIndexOf(TARGET_HOST_SEP);
      let host: string;
      if (idx >= 0) {
        host = option.slice(idx + TARGET_HOST_SEP.length);
      } else {
        // host_vnc / *_Host target: label == device_name, no host suffix.
        // Resolve through keys so the pill row shows the actual host.
        host = keys?.[option]?.host_name ?? option;
      }
      if (!byHost.has(host)) byHost.set(host, []);
      byHost.get(host)!.push(option);
    });
    // Narrow the displayed pills to hosts with at least one target that
    // matches the active search. The pill still owns the full host's target
    // list so a click toggles the complete rack even when only some targets
    // are currently visible — see handleToggleTargets. Without this filter the
    // pill row contradicts the search box: typing "mf1" would still show
    // pills for vpt-pi1 / vpt-pi3 alongside the vpt-mf1 result.
    const visibleSet = new Set(visibleTargetOptions);
    return Array.from(byHost.entries())
      // Show even single-target hosts: a Windows host with only its
      // host_vnc device (no other captures) should still appear so the
      // user can filter by it. The host is the only way to target that
      // device, so dropping it makes the host unfilterable.
      .filter(([, targets]) => targets.length >= 1)
      .filter(([, targets]) => targets.some((t) => visibleSet.has(t)))
      .map(([host, targets]) => ({
        host,
        targets,
        selectedCount: targets.filter((t) => selected.includes(t)).length,
      }))
      .sort((a, b) => a.host.localeCompare(b.host));
  }, [options, visibleTargetOptions, selected, keys]);

  // `activeHostKey` is the rail row that is really active: "All hosts" (null)
  // owns the fallback, so a host filtered out by the search falls back to it
  // instead of leaving the rail and the panel disagreeing.
  const activeHostKey = hostGroups.some((g) => g.host === activeHost) ? activeHost : null;
  const shownHost = hostGroups.find((g) => g.host === activeHostKey) ?? null;

  // Two levels, two places, one meaning each (BUG-0822 follow-up — owner:
  // "keep select all to select everything, clear to clear everything; the
  // host's own select all / clear all live on the right panel"):
  //
  //  - the bar under the search box is ALWAYS the whole list. "Select all"
  //    takes every target, "Clear" drops every target, whatever host is open.
  //    No context, no exception, nothing to reason about.
  //  - the right panel carries the host's own pair, on the host's own header
  //    row, so a scoped action sits next to the list it applies to.
  const allTargetsSelected = options.length > 0 && options.every((option) => selected.includes(option));
  const handleSelectEverything = () => onChange(Array.from(new Set([...selected, ...options])));
  const handleClearEverything = () => onChange([]);

  const hostTargets = shownHost?.targets ?? [];
  const allHostSelected = hostTargets.length > 0 && hostTargets.every((t) => selected.includes(t));
  const handleSelectHost = () => onChange(Array.from(new Set([...selected, ...hostTargets])));
  const handleClearHost = () => {
    const host = new Set(hostTargets);
    onChange(selected.filter((t) => !host.has(t)));
  };

  // Toggle a whole target list: empty or partial → select all, filled → clear
  // all. Shared by the rail cycle and the panel header row.
  const handleToggleTargets = (targets: string[]) => {
    const allSelected = targets.length > 0 && targets.every((t) => selected.includes(t));
    if (allSelected) {
      const removed = new Set(targets);
      onChange(selected.filter((t) => !removed.has(t)));
    } else {
      onChange(Array.from(new Set([...selected, ...targets])));
    }
  };

  // Rail click cycles in three steps so one click never both navigates and
  // mutates the selection (BUG-0822): 1st shows that host's devices, 2nd
  // selects them all, 3rd unselects them all. A row that is not active yet is
  // navigation only. Single-select pickers keep navigation only — a cycle that
  // rewrites a one-target selection would be meaningless there.
  const handleRailClick = (host: string | null) => {
    if (host !== activeHostKey) {
      setActiveHost(host);
      return;
    }
    if (!multiple) return;
    handleToggleTargets(host === null ? options : hostGroups.find((g) => g.host === host)?.targets ?? []);
  };

  const visibleSet = useMemo(() => new Set(visibleTargetOptions), [visibleTargetOptions]);

  return (
    <>
      <Button
        variant="outlined"
        size="small"
        onClick={(e) => setTargetAnchor(e.currentTarget)}
        startIcon={highlight ? <AppIcon name="ai" /> : undefined}
        endIcon={<ExpandMoreIcon fontSize="small" sx={{ transform: targetAnchor ? 'rotate(180deg)' : 'none' }} />}
        sx={{
          width,
          height: 40,
          flexShrink: 0,
          justifyContent: 'space-between',
          textTransform: 'none',
          fontSize: TYPOGRAPHY.body.size,
          fontWeight: 400,
          color: P.textPrimary,
          borderColor: targetAnchor || highlight ? P.accent : P.borderColor,
          ...(highlight ? { boxShadow: `0 0 0 1px ${P.accent}40` } : {}),
          '& .MuiButton-endIcon': { ml: 0.5 },
        }}
      >
        <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {selected.length === 1 && isLocked?.(selected[0]) && <LockIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: "warning.main", mr: 0.5, verticalAlign: "middle" }} />}
          {renderSelectedValues(selected, t(placeholder), (n) => t('{count} targets', { count: n }))}
        </Box>
      </Button>
      <Popover
        open={!!targetAnchor}
        anchorEl={targetAnchor}
        onClose={() => { setTargetAnchor(null); setTargetSearch(''); }}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        slotProps={{ paper: { sx: { width: TARGET_POPOVER_WIDTH, maxWidth: 'calc(100vw - 16px)', height: TARGET_POPOVER_HEIGHT, display: 'flex', flexDirection: 'column', overflow: 'hidden' } } }}
      >
        <Box sx={{ p: 1, pb: 0.5, flexShrink: 0 }}>
          <TextField
            size="small"
            autoFocus
            fullWidth
            placeholder={t('Search targets...')}
            value={targetSearch}
            onChange={(e) => setTargetSearch(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" sx={{ color: 'text.secondary' }} />
                </InputAdornment>
              ),
              endAdornment: targetSearch ? (
                <InputAdornment position="end">
                  <IconButton size="small" edge="end" onClick={() => setTargetSearch('')}>
                    <ClearIcon fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ) : undefined,
            }}
          />
        </Box>
        {multiple && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, px: 1, pb: 0.5, flexShrink: 0, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Button
            size="small"
            data-testid="targets-select-all"
            onClick={handleSelectEverything}
            disabled={options.length === 0 || allTargetsSelected}
            sx={{ minWidth: 0, px: 1, fontSize: TYPOGRAPHY.caption.size }}
          >
            {t('Select all')}
          </Button>
          <Button
            size="small"
            data-testid="targets-clear"
            onClick={handleClearEverything}
            disabled={selected.length === 0}
            sx={{ minWidth: 0, px: 1, fontSize: TYPOGRAPHY.caption.size }}
          >
            {t('Clear')}
          </Button>
          {favoriteOptions.length > 0 && (
            <Chip
              size="small"
              icon={<StarIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: `${P.gold} !important` }} />}
              label={`${t('Favorites')} ${favoriteOptions.length}`}
              onClick={handleToggleFavorites}
              variant={allFavoritesSelected ? 'filled' : 'outlined'}
              sx={{
                ml: 'auto',
                height: 22,
                fontSize: TYPOGRAPHY.caption.size,
                borderColor: P.gold,
                color: P.textPrimary,
                ...(allFavoritesSelected ? { bgcolor: P.hoverBg } : {}),
              }}
            />
          )}
        </Box>
        )}
        {visibleTargetOptions.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
            {t('No matching targets')}
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flex: 1, minHeight: 0 }}>
            {/* Host rail: one row per host, never wraps; long names are cut with an ellipsis. */}
            <Box sx={{ width: TARGET_RAIL_WIDTH, flexShrink: 0, overflowY: 'auto', borderRight: '1px solid', borderColor: 'divider' }}>
              {[{ host: null as string | null, targets: visibleTargetOptions, selectedCount: selected.length }, ...hostGroups].map((g) => {
                const total = g.host === null ? options.length : g.targets.length;
                const active = g.host === activeHostKey;
                const hostLabel = g.host === null ? t('All hosts') : g.host;
                // Hover text carries the count the row is cycling through, so the
                // second-click "select them all" step is discoverable without a
                // new translated string.
                const rowTitle = `${hostLabel} · ${g.selectedCount}/${total}`;
                return (
                  <Box
                    key={g.host ?? '__all'}
                    role="button"
                    tabIndex={0}
                    title={rowTitle}
                    onClick={() => handleRailClick(g.host)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        handleRailClick(g.host);
                      }
                    }}
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 0.75,
                      px: 1.25,
                      py: 0.4,
                      cursor: 'pointer',
                      borderLeft: '2px solid',
                      borderLeftColor: active ? 'primary.main' : 'transparent',
                      bgcolor: active ? 'action.selected' : 'transparent',
                      '&:hover': { bgcolor: 'action.hover' },
                    }}
                  >
                    <Typography
                      component="span"
                      sx={{ flex: 1, minWidth: 0, fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: `${TARGET_HOST_MAX_CHARS}ch` }}
                    >
                      {hostLabel}
                    </Typography>
                    <Typography
                      component="span"
                      sx={{
                        flexShrink: 0,
                        px: 0.5,
                        borderRadius: 0.75,
                        bgcolor: g.selectedCount > 0 ? 'primary.main' : 'action.selected',
                        color: g.selectedCount > 0 ? 'primary.contrastText' : 'text.secondary',
                        fontFamily: 'monospace',
                        fontSize: TYPOGRAPHY.microMeta.size,
                        lineHeight: 1.6,
                      }}
                    >
                      {`${g.selectedCount}/${total}`}
                    </Typography>
                  </Box>
                );
              })}
            </Box>
            <Box sx={{ flex: 1, minWidth: 0, overflowY: 'auto' }}>
              {shownHost ? (
                <>
                  {/* Host header: identity + count on the left, the host's OWN select
                      all / clear all on the right. The scoped pair sits on the list it
                      applies to, so the bar above (always the whole list) and this row
                      (always this host) can never be confused (BUG-0822). */}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, pr: 1, borderBottom: '1px solid', borderColor: 'divider', position: 'sticky', top: 0, bgcolor: 'background.paper', zIndex: 1 }}>
                    <MenuItem dense onClick={() => multiple && handleToggleTargets(shownHost.targets)} sx={{ ...TARGET_ROW_SX, flex: 1, minWidth: 0 }}>
                      {multiple && (
                      <Checkbox
                        size="small"
                        checked={shownHost.selectedCount === shownHost.targets.length}
                        indeterminate={shownHost.selectedCount > 0 && shownHost.selectedCount < shownHost.targets.length}
                        sx={TARGET_CHECKBOX_SX}
                      />
                      )}
                      <ListItemText
                        primary={`${shownHost.host} (${shownHost.targets.length})`}
                        primaryTypographyProps={{ variant: 'body2', noWrap: true, fontWeight: 600 }}
                        sx={{ minWidth: 0 }}
                      />
                    </MenuItem>
                    {multiple && (
                      <>
                        <Button
                          size="small"
                          data-testid="targets-host-select-all"
                          onClick={handleSelectHost}
                          disabled={allHostSelected}
                          title={t('Select all')}
                          sx={{ minWidth: 0, px: 0.75, fontSize: TYPOGRAPHY.caption.size }}
                        >
                          {t('Select all')}
                        </Button>
                        <Button
                          size="small"
                          data-testid="targets-host-clear-all"
                          onClick={handleClearHost}
                          disabled={shownHost.selectedCount === 0}
                          title={t('Clear all')}
                          sx={{ minWidth: 0, px: 0.75, fontSize: TYPOGRAPHY.caption.size }}
                        >
                          {t('Clear all')}
                        </Button>
                      </>
                    )}
                  </Box>
                  {shownHost.targets.filter((o) => visibleSet.has(o)).map((o) => renderTargetOption(o, shownHost.host))}
                </>
              ) : (
                [
                  ...(visibleFavorites.length > 0
                    ? [
                        <DeviceFavoriteGroupHeader key="__favorites" kind="favorites" />,
                        ...visibleFavorites.map((o) => renderTargetOption(o)),
                        ...(visibleOthers.length > 0 ? [<DeviceFavoriteGroupHeader key="__all" kind="all" />] : []),
                      ]
                    : []),
                  ...visibleOthers.map((o) => renderTargetOption(o)),
                ]
              )}
            </Box>
          </Box>
        )}
      </Popover>
    </>
  );
};
