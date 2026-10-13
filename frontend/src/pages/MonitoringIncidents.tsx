import {
  CheckCircle as ResolvedIcon,
  Error as ActiveIcon,
  KeyboardArrowDown as ExpandMoreIcon,
  KeyboardArrowRight as ExpandLessIcon,
  Person as ManualIcon,
  CheckCircle as CheckedIcon,
  Help as UnknownIcon,
  Comment as CommentIcon,
  Visibility as DetailsIcon,
  VisibilityOff as HideDetailsIcon,
  Warning as DiscardedIcon,
  Check as ValidIcon,
  Delete as DeleteIcon,
  RemoveCircleOutline as SkippedIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  CircularProgress,
  Alert as MuiAlert,
  Grid,
  IconButton,
  Collapse,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Tooltip,
  Switch,
  FormControlLabel,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import type { TriageStats } from '../hooks/pages/useAlerts';
import { PageTitle, Palette, StatTiles, pageSurfaceSx, segmentedSx } from '../components/common/PageChrome';
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';

import { AIIcon as AiIcon } from '../components/common/icons/CustomIcons';
import { HeatMapFreezeModal } from '../components/heatmap/HeatMapFreezeModal';
import { R2Image } from '../components/common/R2Image';
import { StyledDialog } from '../components/common/StyledDialog';
import DesktopOnlyPlaceholder from '../components/mobile/DesktopOnlyPlaceholder';
import { useAlerts } from '../hooks/pages/useAlerts';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { Alert } from '../types/pages/Monitoring_Types';
import { parseIncidentFocus, findFocusedAlert } from '../utils/incidentFocus';


/** Section count next to a title; tinted when it carries a colour (e.g. active alerts). */
const CountPill: React.FC<{ count: number; color?: string; P: Palette }> = ({ count, color, P }) => (
  <Box component="span" sx={{ fontSize: '0.72rem', fontWeight: 600, lineHeight: 1.7, px: 1, borderRadius: 999, color: color || P.textSecondary, bgcolor: color ? `${color}22` : P.hoverBg }}>
    {count}
  </Box>
);

/** Incident type as a tinted pill (open: by severity; closed: muted with a green tick). */
const IncidentTag: React.FC<{ label: string; color: string; icon: React.ReactElement; muted?: boolean }> = ({ label, color, icon, muted }) => (
  <Box
    component="span"
    sx={{
      display: 'inline-flex', alignItems: 'center', gap: 0.5, px: 1, py: 0.25, borderRadius: 999,
      fontSize: '0.75rem', fontWeight: 600, whiteSpace: 'nowrap',
      color: muted ? 'text.secondary' : color, bgcolor: muted ? 'transparent' : `${color}1f`,
      border: `1px solid ${color}${muted ? '55' : '66'}`,
      '& .MuiSvgIcon-root': { fontSize: 14, color },
    }}
  >
    {icon}
    {label}
  </Box>
);

// ai_calls.error_type of a failed triage request, in words for the "Triage unavailable" line.
const TRIAGE_FAILURE: Record<string, string> = {
  no_credit: 'no credit on the model account (HTTP 402)',
  auth: 'model API key refused',
  rate_limit: 'rate limited by the model provider',
  timeout: 'model timed out',
  connection: 'model endpoint unreachable',
  server: 'model provider error',
  bad_request: 'request rejected by the model',
  other: 'model call failed',
};

const MonitoringIncidents: React.FC = () => {
  const P = useAgentChatPalette();
  const { isMobile } = useResponsiveMode();
  const { getAllAlerts, updateCheckedStatus, updateDiscardStatus, deleteAllAlerts, deleteAlert, getTriageStats } = useAlerts();
  const [triage, setTriage] = useState<TriageStats | null>(null);
  const [activeAlerts, setActiveAlerts] = useState<Alert[]>([]);
  const [closedAlerts, setClosedAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Today's triage activity (model calls, failures, tokens, discards by screen memory), refreshed every minute.
  useEffect(() => {
    let alive = true;
    const load = () => getTriageStats().then((t) => alive && t.success && setTriage(t)).catch(() => undefined);
    load();
    const timer = setInterval(load, 60000);
    return () => { alive = false; clearInterval(timer); };
  }, [getTriageStats]);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [discardModalOpen, setDiscardModalOpen] = useState(false);
  const [selectedDiscardComment, setSelectedDiscardComment] = useState<{
    comment: string;
    alert: Alert;
  } | null>(null);
  const [showDetailedColumns, setShowDetailedColumns] = useState(false);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [freezeModalOpen, setFreezeModalOpen] = useState(false);
  const [freezeModalAlert, setFreezeModalAlert] = useState<Alert | null>(null);
  const [imageModalOpen, setImageModalOpen] = useState(false);
  const [imageModalUrl, setImageModalUrl] = useState<string | null>(null);

  // Deep link from the Heatmap analysis table (?host=&device=&type=&at=): once alerts are
  // loaded, expand + scroll to + highlight the matching incident. Resolved once per page
  // load — later refreshes (check/discard toggles) must not yank the scroll position again.
  const [searchParams] = useSearchParams();
  const incidentFocus = parseIncidentFocus(searchParams);
  const [focusedAlertId, setFocusedAlertId] = useState<string | null>(null);
  const [focusMiss, setFocusMiss] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'closed'>('all');
  const [weekOnly, setWeekOnly] = useState(false);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const focusResolvedRef = useRef(false);
  const focusedRowRef = useRef<HTMLTableRowElement | null>(null);

  // Load alerts data function - extracted for reuse
  const loadAlerts = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Single API call to get all alerts
      const allAlerts = await getAllAlerts();

      // Client-side filtering
      const active = allAlerts.filter((alert) => alert.status === 'active');
      const closed = allAlerts.filter((alert) => alert.status === 'resolved');

      setActiveAlerts(active);
      setClosedAlerts(closed);

      console.log(
        `[@component:MonitoringIncidents] Loaded ${allAlerts.length} total alerts: ${active.length} active, ${closed.length} closed`,
      );
    } catch (err) {
      console.error('[@component:MonitoringIncidents] Error loading alerts:', err);
      setError(err instanceof Error ? err.message : 'Failed to load alerts');
    } finally {
      setLoading(false);
    }
  }, [getAllAlerts]);

  // Load alerts data on component mount - optimized single query
  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  useEffect(() => {
    if (!incidentFocus || loading || focusResolvedRef.current) return;
    focusResolvedRef.current = true;
    const match = findFocusedAlert([...activeAlerts, ...closedAlerts], incidentFocus);
    if (!match) {
      setFocusMiss(true);
      return;
    }
    setFocusedAlertId(match.id);
    setExpandedRows((prev) => new Set(prev).add(match.id));
  }, [incidentFocus, loading, activeAlerts, closedAlerts]);

  // Scroll once the focused row is in the DOM (it may sit in the Closed table further down).
  useEffect(() => {
    if (!focusedAlertId) return;
    const row = focusedRowRef.current;
    if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusedAlertId]);

  const focusedRowSx = (alertId: string) =>
    alertId === focusedAlertId
      ? {
          outline: '2px solid',
          outlineColor: 'error.main',
          outlineOffset: '-2px',
        }
      : {};

  // Calculate stats
  const totalActiveAlerts = activeAlerts.length;
  const totalClosedAlerts = closedAlerts.length;

  // Calculate this week's alerts (last 7 days)
  const oneWeekAgo = new Date();
  oneWeekAgo.setDate(oneWeekAgo.getDate() - 7);
  const alertsThisWeek = [...activeAlerts, ...closedAlerts].filter(
    (alert) => new Date(alert.start_time) >= oneWeekAgo,
  ).length;

  // Get most common incident type
  const incidentTypeCounts = [...activeAlerts, ...closedAlerts].reduce(
    (acc, alert) => {
      acc[alert.incident_type] = (acc[alert.incident_type] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  const mostCommonIncidentType =
    Object.entries(incidentTypeCounts).sort(([, a], [, b]) => b - a)[0]?.[0] || 'N/A';

  const toggleStatus = (v: 'active' | 'closed') => setStatusFilter((cur) => (cur === v ? 'all' : v));
  const toggleType = (v: string) => setTypeFilter((cur) => (cur === v ? null : v));
  const matchesFilters = (a: Alert) =>
    (!typeFilter || a.incident_type === typeFilter) && (!weekOnly || new Date(a.start_time) >= oneWeekAgo);
  const shownActive = activeAlerts.filter(matchesFilters);
  const shownClosed = closedAlerts.filter(matchesFilters);
  const typeOptions = ['freeze', 'audio_loss', 'blackscreen'];

  // Format duration between two dates
  const formatDuration = (startTime: string, endTime?: string): string => {
    try {
      // Parse dates with better error handling
      const start = new Date(startTime);
      const end = endTime ? new Date(endTime) : new Date();

      // Validate dates
      if (isNaN(start.getTime())) {
        console.warn(`[@component:MonitoringIncidents] Invalid start time: ${startTime}`);
        return 'Invalid Date';
      }

      if (endTime && isNaN(end.getTime())) {
        console.warn(`[@component:MonitoringIncidents] Invalid end time: ${endTime}`);
        return 'Invalid Date';
      }

      // Check for unreasonable future dates (likely parsing error)
      const currentYear = new Date().getFullYear();
      if (start.getFullYear() > currentYear + 1) {
        console.warn(
          `[@component:MonitoringIncidents] Start time appears to be in the future (${start.getFullYear()}): ${startTime}`,
        );
        return 'Future Date';
      }

      const durationMs = end.getTime() - start.getTime();

      if (durationMs < 0) {
        console.warn(`[@component:MonitoringIncidents] Negative duration detected:`);
        console.warn(`  - startTime: ${startTime} -> ${start.toISOString()} (${start.getTime()})`);
        console.warn(`  - endTime: ${endTime || 'now'} -> ${end.toISOString()} (${end.getTime()})`);
        console.warn(`  - duration: ${durationMs}ms`);
        console.warn(`  - Current local time: ${new Date().toLocaleString()}`);
        console.warn(`  - Current UTC time: ${new Date().toISOString()}`);

        // For negative durations, try to show absolute value with warning
        const absDuration = Math.abs(durationMs);
        const seconds = Math.floor(absDuration / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);

        if (hours > 0) {
          return `~${hours}h ${minutes % 60}m (time sync issue)`;
        } else if (minutes > 0) {
          return `~${minutes}m ${seconds % 60}s (time sync issue)`;
        } else {
          return `~${seconds}s (time sync issue)`;
        }
      }

      const seconds = Math.floor(durationMs / 1000);
      const minutes = Math.floor(seconds / 60);
      const hours = Math.floor(minutes / 60);
      const days = Math.floor(hours / 24);

      if (days > 0) {
        return `${days}d ${hours % 24}h`;
      } else if (hours > 0) {
        return `${hours}h ${minutes % 60}m`;
      } else if (minutes > 0) {
        return `${minutes}m ${seconds % 60}s`;
      } else {
        return `${seconds}s`;
      }
    } catch (error) {
      console.error(`[@component:MonitoringIncidents] Error formatting duration:`, error);
      return 'Error';
    }
  };

  // Format date helper with better error handling
  const formatDate = (dateString: string): string => {
    try {
      const date = new Date(dateString);
      if (isNaN(date.getTime())) {
        return 'Invalid Date';
      }

      // Check for unreasonable future dates
      const currentYear = new Date().getFullYear();
      if (date.getFullYear() > currentYear + 1) {
        return `${date.toLocaleDateString()} (Future?)`;
      }

      return date.toLocaleDateString() + ', ' + date.toLocaleTimeString();
    } catch (error) {
      console.error(`[@component:MonitoringIncidents] Error formatting date: ${dateString}`, error);
      return 'Error';
    }
  };

  // Get incident type chip color
  function getIncidentTypeColor(incidentType: string): 'error' | 'warning' | 'info' {
    switch (incidentType.toLowerCase()) {
      case 'blackscreen':
      case 'freeze':
        return 'error';
      case 'audio_loss':
        return 'warning';
      default:
        return 'info';
    }
  }

  // Handle checked status toggle
  const handleCheckedToggle = async (alert: Alert) => {
    try {
      const newChecked = !alert.checked;
      await updateCheckedStatus(alert.id, newChecked);
      
      // Update local state
      const updateAlert = (alerts: Alert[]) => 
        alerts.map(a => a.id === alert.id ? { ...a, checked: newChecked, check_type: 'manual' } : a);
      
      setActiveAlerts(updateAlert);
      setClosedAlerts(updateAlert);
    } catch (error) {
      console.error('Failed to update checked status:', error);
      setError('Failed to update checked status');
    }
  };

  // Handle discard status toggle
  const handleDiscardToggle = async (alert: Alert) => {
    try {
      const newDiscard = !alert.discard;
      const checkType = alert.check_type === 'ai' ? 'ai_and_human' : 'manual';
      
      await updateDiscardStatus(alert.id, newDiscard, undefined, checkType);
      
      // Update local state
      const updateAlert = (alerts: Alert[]) => 
        alerts.map(a => a.id === alert.id ? { ...a, discard: newDiscard, check_type: checkType } : a);
      
      setActiveAlerts(updateAlert);
      setClosedAlerts(updateAlert);
    } catch (error) {
      console.error('Failed to update discard status:', error);
      setError('Failed to update discard status');
    }
  };

  const handleDeleteOne = async (alert: Alert) => {
    try {
      await deleteAlert(alert.id);
      setActiveAlerts((a) => a.filter((x) => x.id !== alert.id));
      setClosedAlerts((a) => a.filter((x) => x.id !== alert.id));
    } catch (error) {
      console.error('Failed to delete alert:', error);
      setError('Failed to delete incident');
    }
  };

  // Discard = checked + discarded (false positive); again = back to valid
  const handleDiscardOne = async (alert: Alert) => {
    try {
      if (alert.discard) {
        await handleDiscardToggle(alert);
        return;
      }
      if (!alert.checked) await updateCheckedStatus(alert.id, true);
      await updateDiscardStatus(alert.id, true, undefined, 'manual');
      const upd = (alerts: Alert[]) =>
        alerts.map((a) => (a.id === alert.id ? { ...a, checked: true, discard: true, check_type: 'manual' } : a));
      setActiveAlerts(upd);
      setClosedAlerts(upd);
    } catch (error) {
      console.error('Failed to discard alert:', error);
      setError('Failed to discard incident');
    }
  };

  const renderRowActions = (alert: Alert) => (
    <TableCell sx={{ py: 0.5, whiteSpace: 'nowrap' }} align="right">
      <Tooltip title={alert.discard ? 'Discarded: click to mark valid again' : 'Discard (false positive)'}>
        <IconButton size="small" onClick={() => handleDiscardOne(alert)} sx={{ color: alert.discard ? P.warning : P.textMuted }}>
          <DiscardedIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Delete this incident">
        <IconButton size="small" onClick={() => handleDeleteOne(alert)} sx={{ color: P.textMuted, '&:hover': { color: P.error } }}>
          <DeleteIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </TableCell>
  );

  // Get individual discard analysis components
  const getCheckedStatus = (alert: Alert) => {
    if (alert.check_type === 'ai_strategy_skip') {
      return (
        <Chip
          icon={<SkippedIcon />}
          label="Skipped"
          color="default"
          size="small"
          variant="outlined"
        />
      );
    }
    if (alert.checked === undefined || alert.checked === null) {
      return (
        <Chip
          icon={<UnknownIcon />}
          label="Pending"
          color="default"
          size="small"
          variant="outlined"
          clickable
          onClick={() => handleCheckedToggle(alert)}
        />
      );
    }
    return (
      <Chip
        icon={<CheckedIcon />}
        label={alert.checked ? 'Checked' : 'Unchecked'}
        color={alert.checked ? 'success' : 'default'}
        size="small"
        clickable
        onClick={() => handleCheckedToggle(alert)}
      />
    );
  };

  const getDiscardStatus = (alert: Alert) => {
    if (alert.check_type === 'ai_strategy_skip') {
      return (
        <Typography variant="body2" color="text.disabled">
          -
        </Typography>
      );
    }
    if (!alert.checked) {
      return (
        <Typography variant="body2" color="text.disabled">
          -
        </Typography>
      );
    }
    return (
      <Chip
        icon={alert.discard ? <DiscardedIcon /> : <ValidIcon />}
        label={alert.discard ? 'Discarded' : 'Valid'}
        color={alert.discard ? 'warning' : 'success'}
        size="small"
        clickable
        onClick={() => handleDiscardToggle(alert)}
      />
    );
  };

  const getCheckType = (alert: Alert) => {
    if (!alert.check_type) {
      return (
        <Typography variant="body2" color="text.disabled">
          -
        </Typography>
      );
    }
    if (alert.check_type === 'ai_strategy_skip') {
      return (
        <Typography variant="body2" color="text.disabled" sx={{ fontStyle: 'italic' }}>
          Skipped
        </Typography>
      );
    }
    const isAI = alert.check_type === 'ai';
    return (
      <Chip
        icon={isAI ? <AiIcon /> : <ManualIcon />}
        label={isAI ? 'AI' : 'Manual'}
        color="primary"
        size="small"
        variant="outlined"
      />
    );
  };

  const getDiscardType = (alert: Alert) => {
    if (!alert.discard_type) {
      return (
        <Typography variant="body2" color="text.disabled">
          -
        </Typography>
      );
    }
    return (
      <Chip
        label={alert.discard_type}
        size="small"
        variant="outlined"
        sx={{ color: P.textSecondary, borderColor: P.borderColor }}
      />
    );
  };

  const getDiscardComment = (alert: Alert) => {
    if (!alert.discard_comment) {
      return (
        <Typography variant="body2" color="text.disabled">
          -
        </Typography>
      );
    }
    return (
      <Tooltip title="View full comment">
        <IconButton
          size="small"
          onClick={() => handleDiscardCommentClick(alert)}
          sx={{ p: 0.25 }}
        >
          <CommentIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    );
  };

  // Handle discard comment modal
  const handleDiscardCommentClick = (alert: Alert) => {
    if (alert.discard_comment) {
      setSelectedDiscardComment({
        comment: alert.discard_comment,
        alert: alert,
      });
      setDiscardModalOpen(true);
    }
  };

  const handleCloseDiscardModal = () => {
    setDiscardModalOpen(false);
    setSelectedDiscardComment(null);
  };

  // Handle freeze modal
  const handleFreezeClick = (alert: Alert) => {
    const hasFreezeImages = (alert.metadata?.r2_images?.thumbnail_urls?.length ?? 0) > 0;
    
    if (hasFreezeImages) {
      setFreezeModalAlert(alert);
      setFreezeModalOpen(true);
    }
  };

  const handleCloseFreezeModal = () => {
    setFreezeModalOpen(false);
    setFreezeModalAlert(null);
  };

  const handleImageModalOpen = (url?: string | null) => {
    if (!url) return;
    setImageModalUrl(url);
    setImageModalOpen(true);
  };

  const handleImageModalClose = () => {
    setImageModalOpen(false);
    setImageModalUrl(null);
  };


  // Handle clear all alerts
  const handleClearAllAlerts = async () => {
    try {
      setIsDeleting(true);
      setError(null);
      
      const result = await deleteAllAlerts();
      
      if (result.success) {
        console.log(`[@component:MonitoringIncidents] Successfully deleted ${result.deleted_count} alerts`);
        
        // Refresh data from server to ensure consistency
        await loadAlerts();
        
        // Clear expanded rows
        setExpandedRows(new Set());
      } else {
        setError('Failed to delete alerts');
      }
      
      setClearConfirmOpen(false);
    } catch (err) {
      console.error('[@component:MonitoringIncidents] Error deleting alerts:', err);
      setError(err instanceof Error ? err.message : 'Failed to delete alerts');
    } finally {
      setIsDeleting(false);
    }
  };

  // Toggle expanded row
  const toggleRowExpansion = (alertId: string) => {
    setExpandedRows((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(alertId)) {
        newSet.delete(alertId);
      } else {
        newSet.add(alertId);
      }
      return newSet;
    });
  };

  // Get image URLs from alert metadata
  const getAlertImageUrls = (alert: Alert) => {
    const r2Images = alert.metadata?.r2_images;
    
    // Freeze incidents have thumbnail_urls (plural - array)
    if (r2Images?.thumbnail_urls && r2Images.thumbnail_urls.length > 0) {
      return {
        originalUrl: r2Images.thumbnail_urls[0],
        thumbnailUrl: r2Images.thumbnail_urls[0],
        closureUrl: null, // Freeze doesn't have separate closure
        hasR2Images: true,
      };
    }
    
    // Blackscreen/Macroblocks have thumbnail_url (singular) + optional closure_url
    if (r2Images && r2Images.thumbnail_url) {
      return {
        originalUrl: r2Images.thumbnail_url,
        thumbnailUrl: r2Images.thumbnail_url,
        closureUrl: r2Images.closure_url || null,
        hasR2Images: true,
      };
    }
    
    return {
      originalUrl: null,
      thumbnailUrl: null,
      closureUrl: null,
      hasR2Images: false,
    };
  };

  // Render expandable row content - minimalist design
  const renderExpandedContent = (alert: Alert) => {
    const imageUrls = getAlertImageUrls(alert);
    const r2Images = alert.metadata?.r2_images;
    const freezeDiffs = alert.metadata?.freeze_diffs || [];
    const freezeImageUrls = r2Images?.thumbnail_urls || [];

    return (
      <Box sx={{ p: 1 }}>
        {/* Freeze Detection Analysis - All frames in one row */}
        {alert.incident_type === 'freeze' && freezeImageUrls.length > 0 && (
          <Box>
            <Grid container spacing={2} alignItems="flex-start">
              {/* Start Image */}
              {imageUrls.hasR2Images && (
                <Grid item>
                  <Box sx={{ textAlign: 'center' }}>
                    <Typography variant="caption" display="block" sx={{ mb: 1, color: 'text.secondary' }}>
                      Start
                    </Typography>
                    <R2Image
                      src={imageUrls.thumbnailUrl}
                      alt="Alert start"
                      showLoading={false}
                      sx={{
                        width: 120,
                        height: 90,
                        borderRadius: 1,
                        border: '1px solid',
                        borderColor: 'divider',
                        cursor: 'pointer',
                        '&:hover': { opacity: 0.8 },
                      }}
                      onClick={() => handleFreezeClick(alert)}
                    />
                  </Box>
                </Grid>
              )}

              {/* 3 Freeze Frames - using R2 thumbnail URLs */}
              {freezeImageUrls.map((imageUrl, index) => {
                const diff = freezeDiffs[index];
                const isCurrentFrame = index === 2;

                return (
                  <Grid item key={index}>
                    <Box sx={{ textAlign: 'center' }}>
                      <Typography
                        variant="caption"
                        display="block"
                        sx={{
                          mb: 1,
                          color: isCurrentFrame ? 'error.main' : 'text.secondary',
                          fontWeight: isCurrentFrame ? 'bold' : 'normal',
                        }}
                      >
                        {index === 0 ? 'Frame -2' : index === 1 ? 'Frame -1' : 'Current'}
                      </Typography>
                      <R2Image
                        src={imageUrl}
                        alt={`Freeze frame ${index + 1}`}
                        showLoading={false}
                        sx={{
                          width: 120,
                          height: 90,
                          borderRadius: 1,
                          border: isCurrentFrame ? '2px solid' : '1px solid',
                          borderColor: isCurrentFrame ? 'error.main' : 'divider',
                          cursor: 'pointer',
                          '&:hover': { opacity: 0.8 },
                        }}
                        onClick={() => handleFreezeClick(alert)}
                      />
                      {index > 0 && diff !== undefined && (
                        <Typography
                          variant="caption"
                          display="block"
                          sx={{
                            mt: 0.5,
                            color: diff < 0.5 ? 'error.main' : 'success.main',
                            fontWeight: 'bold',
                          }}
                        >
                          Diff: {diff.toFixed(1)}
                        </Typography>
                      )}
                    </Box>
                  </Grid>
                );
              })}

              {/* End Image (if resolved and has closure) */}
              {alert.status === 'resolved' && imageUrls.closureUrl && (
                <Grid item>
                  <Box sx={{ textAlign: 'center' }}>
                    <Typography variant="caption" display="block" sx={{ mb: 1, color: 'text.secondary' }}>
                      End
                    </Typography>
                    <R2Image
                      src={imageUrls.closureUrl}
                      alt="Alert end"
                      showLoading={false}
                      sx={{
                        width: 120,
                        height: 90,
                        borderRadius: 1,
                        border: '1px solid',
                        borderColor: 'divider',
                        cursor: 'pointer',
                        '&:hover': { opacity: 0.8 },
                      }}
                    />
                  </Box>
                </Grid>
              )}

              {/* Threshold info */}
              <Grid item>
                <Box sx={{ ml: 2, p: 1, bgcolor: 'rgba(255, 0, 0, 0.1)', borderRadius: 1 }}>
                  <Typography variant="caption" color="error.main" fontWeight="bold">
                    Threshold: 0.5
                  </Typography>
                  <Typography variant="caption" display="block" color="text.secondary">
                    All diffs below = freeze
                  </Typography>
                </Box>
              </Grid>
            </Grid>
          </Box>
        )}

        {/* Regular alert images (skip for freeze - shown above) */}
        {imageUrls.hasR2Images && alert.incident_type !== 'freeze' && (
          <Box>
            <Grid container spacing={3} alignItems="center">
              {/* Start Image */}
              <Grid item>
                <Box sx={{ textAlign: 'center' }}>
                  <Typography
                    variant="caption"
                    display="block"
                    sx={{ mb: 1, color: 'text.secondary' }}
                  >
                    Start
                  </Typography>
                  <R2Image
                    src={imageUrls.thumbnailUrl}
                    alt="Alert start"
                    showLoading={false}
                    sx={{
                      width: 120,
                      height: 'auto',
                      borderRadius: 1,
                      border: '1px solid',
                      borderColor: 'divider',
                      cursor: 'pointer',
                      '&:hover': { opacity: 0.8 },
                    }}
                    onClick={() => handleImageModalOpen(imageUrls.thumbnailUrl)}
                  />
                </Box>
              </Grid>

              {/* End Image (if resolved) */}
              {alert.status === 'resolved' && imageUrls.closureUrl && (
                <Grid item>
                  <Box sx={{ textAlign: 'center' }}>
                    <Typography
                      variant="caption"
                      display="block"
                      sx={{ mb: 1, color: 'text.secondary' }}
                    >
                      End
                    </Typography>
                    <R2Image
                      src={imageUrls.closureUrl}
                      alt="Alert end"
                      showLoading={false}
                      sx={{
                        width: 120,
                        height: 'auto',
                        borderRadius: 1,
                        border: '1px solid',
                        borderColor: 'divider',
                        cursor: 'pointer',
                        '&:hover': { opacity: 0.8 },
                      }}
                    onClick={() => handleImageModalOpen(imageUrls.closureUrl)}
                    />
                  </Box>
                </Grid>
              )}
            </Grid>
          </Box>
        )}

        {/* No data state */}
        {freezeImageUrls.length === 0 && !imageUrls.hasR2Images && (
          <Box sx={{ textAlign: 'center', color: 'text.secondary' }}>
            <Typography variant="body2">No additional data available for this alert</Typography>
          </Box>
        )}
      </Box>
    );
  };

  // Loading state component
  const LoadingState = () => (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
      <CircularProgress />
    </Box>
  );

  // Empty state component
  const EmptyState = ({ message, colSpan }: { message: string; colSpan: number }) => (
    <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
      <TableCell colSpan={colSpan} sx={{ textAlign: 'center', py: 4 }}>
        <Typography variant="body2" color="textSecondary">
          {message}
        </Typography>
      </TableCell>
    </TableRow>
  );

  if (isMobile) {
    return <DesktopOnlyPlaceholder title="Alerts" />;
  }

  return (
    <Box
      sx={{
        ...(pageSurfaceSx(P) as object),
        '& .MuiSwitch-switchBase.Mui-checked': { color: P.accent },
        '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': { bgcolor: P.accent },
      }}
    >
      <PageTitle
        title="Alerts"
        subtitle="Incidents the monitor opened on each device: what is happening now and what was resolved"
        right={
          <>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={typeFilter}
          onChange={(_, v) => setTypeFilter(v)}
          sx={segmentedSx(P, 'sm')}
        >
          {typeOptions.map((t) => (
            <ToggleButton key={t} value={t}>{t.replace('_', ' ')}</ToggleButton>
          ))}
        </ToggleButtonGroup>
        {(typeFilter || weekOnly || statusFilter !== 'all') && (
          <Button size="small" sx={{ textTransform: 'none' }} onClick={() => { setTypeFilter(null); setWeekOnly(false); setStatusFilter('all'); }}>
            Clear filters
          </Button>
        )}
          <Tooltip title="Clear all alerts from database">
            <span>
              <Button
                variant="outlined"
                color="error"
                size="small"
                startIcon={<DeleteIcon />}
                onClick={() => setClearConfirmOpen(true)}
                disabled={loading || totalActiveAlerts + totalClosedAlerts === 0}
                sx={{ textTransform: 'none' }}
              >
                Clear all
              </Button>
            </span>
          </Tooltip>
          </>
        }
      />

      {error && (
        <MuiAlert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </MuiAlert>
      )}

      {incidentFocus && focusMiss && (
        <MuiAlert severity="warning" sx={{ mb: 1 }} onClose={() => setFocusMiss(false)}>
          No {incidentFocus.type} incident found for {incidentFocus.host} / {incidentFocus.device} around{' '}
          {new Date(incidentFocus.at).toLocaleString()} — the monitor may not have opened one for that frame.
        </MuiAlert>
      )}

      {/* Quick Stats */}
      <StatTiles
        large
        tiles={[
          { label: 'Active alerts', value: totalActiveAlerts, color: totalActiveAlerts > 0 ? P.error : P.success, active: statusFilter === 'active', onClick: () => toggleStatus('active'), title: 'Click to show only active alerts, click again to clear' },
          { label: 'This week', value: alertsThisWeek, active: weekOnly, onClick: () => setWeekOnly((w) => !w), title: 'Click to show only the last 7 days, click again to clear' },
          { label: 'Most common', value: mostCommonIncidentType || '-', active: typeFilter === mostCommonIncidentType, onClick: () => mostCommonIncidentType !== 'N/A' && toggleType(mostCommonIncidentType), title: 'Click to filter on this incident type, click again to clear' },
          { label: 'Closed', value: totalClosedAlerts, active: statusFilter === 'closed', onClick: () => toggleStatus('closed'), title: 'Click to show only closed alerts, click again to clear' },
        ]}
      />

      {triage && (
        <Typography variant="caption" sx={{ display: 'block', color: P.textMuted, mb: 1 }} title="Alert triage today (UTC): model calls, failed calls, tokens, and alerts discarded by a known screen without a model call">
          Triage today: {triage.calls} model calls ({triage.errors} failed), {(triage.tokens_in + triage.tokens_out).toLocaleString()} tokens
          {' · '}{triage.avoided} discarded by screen memory
          {' · '}{triage.screens.expected} expected / {triage.screens.bad} bad / {triage.screens.unknown} unknown screens
        </Typography>
      )}
      {triage?.unavailable && (
        <Typography variant="caption" sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: P.error, mb: 1 }} title="The last alert-triage model request failed; alerts wait unchecked and the cost rules keep running until a call answers again">
          <ActiveIcon sx={{ fontSize: 14 }} />
          Triage unavailable: {TRIAGE_FAILURE[triage.unavailable.reason] || triage.unavailable.reason} (last try {new Date(triage.unavailable.since).toLocaleTimeString()})
        </Typography>
      )}

      <Grid container spacing={1}>
        {/* Alerts In Progress */}
        {statusFilter !== 'closed' && <Grid item xs={12}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="h6" component="h2" sx={{ my: 0, display: 'flex', alignItems: 'center', gap: 1 }}>
                  In progress
                  <CountPill count={shownActive.length} color={shownActive.length ? P.error : undefined} P={P} />
                </Typography>
                <FormControlLabel
                  control={
                    <Switch
                      checked={showDetailedColumns}
                      onChange={(e) => setShowDetailedColumns(e.target.checked)}
                      size="small"
                    />
                  }
                  label={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {showDetailedColumns ? <HideDetailsIcon /> : <DetailsIcon />}
                      <Typography variant="body2">
                        {showDetailedColumns ? 'Hide' : 'Show'} Discard Analysis Details
                      </Typography>
                    </Box>
                  }
                />
              </Box>

              <TableContainer
                component={Paper}
                variant="outlined"
                sx={{
                  '& .MuiTableRow-root:hover': {
                    backgroundColor: 'transparent !important',
                  },
                }}
              >
                <Table size="small" sx={{ tableLayout: 'fixed', minWidth: showDetailedColumns ? 1520 : 900, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col style={{ width: 190 }} /><col /><col style={{ width: 130 }} /><col style={{ width: 195 }} /><col style={{ width: 100 }} /><col style={{ width: 110 }} />{showDetailedColumns && (<><col style={{ width: 90 }} /><col style={{ width: 90 }} /><col style={{ width: 120 }} /><col style={{ width: 120 }} /><col style={{ width: 200 }} /></>)}</colgroup>
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>Incident</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>Host</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>Device</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>Start</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>Duration</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }} align="right">
                        <strong>Actions</strong>
                      </TableCell>
                      {showDetailedColumns && (
                        <>
                          <TableCell sx={{ py: 0.5 }}>
                            <strong>Checked</strong>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <strong>Discard</strong>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <strong>Check Type</strong>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <strong>Discard Type</strong>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <strong>Comment</strong>
                          </TableCell>
                        </>
                      )}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading ? (
                      <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                        <TableCell colSpan={showDetailedColumns ? 11 : 6}>
                          <LoadingState />
                        </TableCell>
                      </TableRow>
                    ) : shownActive.length === 0 ? (
                      <EmptyState message="No active alerts" colSpan={showDetailedColumns ? 11 : 6} />
                    ) : (
                      shownActive.map((alert) => (
                        <React.Fragment key={alert.id}>
                          <TableRow
                            ref={alert.id === focusedAlertId ? focusedRowRef : undefined}
                            sx={{
                              '&:hover': {
                                backgroundColor: 'transparent !important',
                              },
                              height: '48px', // Fixed height for main rows
                              ...focusedRowSx(alert.id),
                            }}
                          >
                            <TableCell sx={{ py: 0.5, pl: 0.5, whiteSpace: 'nowrap' }}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                <IconButton
                                  size="small"
                                  onClick={() => toggleRowExpansion(alert.id)}
                                  sx={{ p: 0.5 }}
                                >
                                  {expandedRows.has(alert.id) ? <ExpandMoreIcon /> : <ExpandLessIcon />}
                                </IconButton>
                              <IncidentTag
                                label={alert.incident_type}
                                color={{ error: P.error, warning: P.warning, info: P.textSecondary }[getIncidentTypeColor(alert.incident_type)]}
                                icon={<ActiveIcon />}
                              />
                              </Box>
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>{alert.host_name}</TableCell>
                            <TableCell sx={{ py: 0.5 }}>{alert.device_id}</TableCell>
                            <TableCell sx={{ py: 0.5, whiteSpace: 'nowrap' }}>{formatDate(alert.start_time)}</TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              {formatDuration(alert.start_time)}
                            </TableCell>
                            {renderRowActions(alert)}
                            {showDetailedColumns && (
                              <>
                                <TableCell sx={{ py: 0.5 }}>
                                  {getCheckedStatus(alert)}
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  {getDiscardStatus(alert)}
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  {getCheckType(alert)}
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  {getDiscardType(alert)}
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  {getDiscardComment(alert)}
                                </TableCell>
                              </>
                            )}
                          </TableRow>
                          {expandedRows.has(alert.id) && (
                            <TableRow
                              sx={{
                                '&:hover': {
                                  backgroundColor: 'transparent !important',
                                },
                              }}
                            >
                              <TableCell colSpan={showDetailedColumns ? 11 : 6} sx={{ p: 0, borderBottom: 0 }}>
                                <Collapse
                                  in={expandedRows.has(alert.id)}
                                  timeout="auto"
                                  unmountOnExit
                                >
                                  <Box sx={{ backgroundColor: P.hoverBg }}>
                                    {renderExpandedContent(alert)}
                                  </Box>
                                </Collapse>
                              </TableCell>
                            </TableRow>
                          )}
                        </React.Fragment>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </CardContent>
          </Card>
        </Grid>}

        {/* Alerts Closed */}
        {statusFilter !== 'active' && <Grid item xs={12}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="h6" component="h2" sx={{ my: 0, display: 'flex', alignItems: 'center', gap: 1 }}>
                  Closed
                  <CountPill count={shownClosed.length} P={P} />
                </Typography>
                <FormControlLabel
                  control={
                    <Switch
                      checked={showDetailedColumns}
                      onChange={(e) => setShowDetailedColumns(e.target.checked)}
                      size="small"
                    />
                  }
                  label={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {showDetailedColumns ? <HideDetailsIcon /> : <DetailsIcon />}
                      <Typography variant="body2">
                        {showDetailedColumns ? 'Hide' : 'Show'} Discard Analysis Details
                      </Typography>
                    </Box>
                  }
                />
              </Box>

              <TableContainer
                component={Paper}
                variant="outlined"
                sx={{
                  '& .MuiTableRow-root:hover': {
                    backgroundColor: 'transparent !important',
                  },
                }}
              >
                <Table size="small" sx={{ tableLayout: 'fixed', minWidth: showDetailedColumns ? 1620 : 1000, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col style={{ width: 190 }} /><col /><col style={{ width: 130 }} /><col style={{ width: 195 }} /><col style={{ width: 195 }} /><col style={{ width: 130 }} /><col style={{ width: 110 }} />{showDetailedColumns && (<><col style={{ width: 90 }} /><col style={{ width: 90 }} /><col style={{ width: 120 }} /><col style={{ width: 120 }} /><col style={{ width: 200 }} /></>)}</colgroup>
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>Incident</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>Host</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>Device</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>Start</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>End</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }}>
                        <strong>Total Duration</strong>
                      </TableCell>
                      <TableCell sx={{ py: 0.5 }} align="right">
                        <strong>Actions</strong>
                      </TableCell>
                      {showDetailedColumns && (
                        <>
                          <TableCell sx={{ py: 0.5 }}>
                            <strong>Checked</strong>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <strong>Discard</strong>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <strong>Check Type</strong>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <strong>Discard Type</strong>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <strong>Comment</strong>
                          </TableCell>
                        </>
                      )}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading ? (
                      <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                        <TableCell colSpan={showDetailedColumns ? 11 : 6}>
                          <LoadingState />
                        </TableCell>
                      </TableRow>
                    ) : shownClosed.length === 0 ? (
                      <EmptyState message="No closed alerts" colSpan={showDetailedColumns ? 11 : 6} />
                    ) : (
                      shownClosed.map((alert) => (
                        <React.Fragment key={alert.id}>
                          <TableRow
                            ref={alert.id === focusedAlertId ? focusedRowRef : undefined}
                            sx={{
                              '&:hover': {
                                backgroundColor: 'transparent !important',
                              },
                              height: '48px', // Fixed height for main rows
                              ...focusedRowSx(alert.id),
                            }}
                          >
                            <TableCell sx={{ py: 0.5, pl: 0.5, whiteSpace: 'nowrap' }}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                <IconButton
                                  size="small"
                                  onClick={() => toggleRowExpansion(alert.id)}
                                  sx={{ p: 0.5 }}
                                >
                                  {expandedRows.has(alert.id) ? <ExpandMoreIcon /> : <ExpandLessIcon />}
                                </IconButton>
                              <IncidentTag label={alert.incident_type} color={P.success} icon={<ResolvedIcon />} muted />
                              </Box>
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>{alert.host_name}</TableCell>
                            <TableCell sx={{ py: 0.5 }}>{alert.device_id}</TableCell>
                            <TableCell sx={{ py: 0.5, whiteSpace: 'nowrap' }}>{formatDate(alert.start_time)}</TableCell>
                            <TableCell sx={{ py: 0.5, whiteSpace: 'nowrap' }}>
                              {alert.end_time ? formatDate(alert.end_time) : 'N/A'}
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              {alert.end_time
                                ? formatDuration(alert.start_time, alert.end_time)
                                : 'N/A'}
                            </TableCell>
                            {renderRowActions(alert)}
                            {showDetailedColumns && (
                              <>
                                <TableCell sx={{ py: 0.5 }}>
                                  {getCheckedStatus(alert)}
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  {getDiscardStatus(alert)}
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  {getCheckType(alert)}
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  {getDiscardType(alert)}
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  {getDiscardComment(alert)}
                                </TableCell>
                              </>
                            )}
                          </TableRow>
                          {expandedRows.has(alert.id) && (
                            <TableRow
                              sx={{
                                '&:hover': {
                                  backgroundColor: 'transparent !important',
                                },
                              }}
                            >
                              <TableCell colSpan={showDetailedColumns ? 11 : 6} sx={{ p: 0, borderBottom: 0 }}>
                                <Collapse
                                  in={expandedRows.has(alert.id)}
                                  timeout="auto"
                                  unmountOnExit
                                >
                                  <Box sx={{ backgroundColor: P.hoverBg }}>
                                    {renderExpandedContent(alert)}
                                  </Box>
                                </Collapse>
                              </TableCell>
                            </TableRow>
                          )}
                        </React.Fragment>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </CardContent>
          </Card>
        </Grid>}
      </Grid>

      {/* Discard Comment Modal */}
      <StyledDialog
        open={discardModalOpen}
        onClose={handleCloseDiscardModal}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <CommentIcon />
            AI Analysis Comment
          </Box>
        </DialogTitle>
        <DialogContent>
          {selectedDiscardComment && (
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>
                Alert: {selectedDiscardComment.alert.incident_type} on {selectedDiscardComment.alert.device_id}
              </Typography>
              <Typography variant="subtitle2" sx={{ mb: 2, color: 'text.secondary' }}>
                Analysis Type: {selectedDiscardComment.alert.check_type === 'ai' ? 'AI Analysis' : 'Manual Review'}
                {selectedDiscardComment.alert.discard_type && ` • Category: ${selectedDiscardComment.alert.discard_type}`}
              </Typography>
              <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap' }}>
                {selectedDiscardComment.comment}
              </Typography>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDiscardModal} color="primary">
            Close
          </Button>
        </DialogActions>
      </StyledDialog>

      {/* Clear All Alerts Confirmation Dialog */}
      <StyledDialog
        open={clearConfirmOpen}
        onClose={() => !isDeleting && setClearConfirmOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <DeleteIcon color="error" />
            Clear All Alerts
          </Box>
        </DialogTitle>
        <DialogContent>
          <MuiAlert severity="warning" sx={{ mb: 2 }}>
            This action cannot be undone!
          </MuiAlert>
          <Typography variant="body1">
            Are you sure you want to delete all {totalActiveAlerts + totalClosedAlerts} alerts from the database?
          </Typography>
          <Typography variant="body2" sx={{ mt: 2, color: 'text.secondary' }}>
            This will permanently remove:
          </Typography>
          <Box component="ul" sx={{ mt: 1, pl: 3 }}>
            <Typography component="li" variant="body2" color="text.secondary">
              {totalActiveAlerts} active alerts
            </Typography>
            <Typography component="li" variant="body2" color="text.secondary">
              {totalClosedAlerts} closed alerts
            </Typography>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button 
            onClick={() => setClearConfirmOpen(false)} 
            disabled={isDeleting}
          >
            Cancel
          </Button>
          <Button 
            onClick={handleClearAllAlerts} 
            color="error" 
            variant="contained"
            disabled={isDeleting}
            startIcon={isDeleting ? <CircularProgress size={16} /> : <DeleteIcon />}
          >
            {isDeleting ? 'Deleting...' : 'Delete All'}
          </Button>
        </DialogActions>
      </StyledDialog>

      {/* Freeze Modal */}
      <HeatMapFreezeModal
        freezeModalOpen={freezeModalOpen}
        hostName={freezeModalAlert?.host_name || ''}
        deviceId={freezeModalAlert?.device_id || ''}
        thumbnailUrls={freezeModalAlert?.metadata?.r2_images?.thumbnail_urls || []}
        freezeDiffs={freezeModalAlert?.metadata?.freeze_diffs || []}
        timestamp={freezeModalAlert?.start_time}
        onClose={handleCloseFreezeModal}
      />

      {/* Generic Image Modal for non-freeze incidents (e.g., audio_loss) */}
      <StyledDialog
        open={imageModalOpen}
        onClose={handleImageModalClose}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Incident Image</DialogTitle>
        <DialogContent>
          {imageModalUrl && (
            <R2Image
              src={imageModalUrl}
              alt="Incident"
              showLoading={false}
              sx={{
                width: '100%',
                height: 'auto',
                borderRadius: 1,
                border: '1px solid',
                borderColor: 'divider',
              }}
            />
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleImageModalClose}>Close</Button>
        </DialogActions>
      </StyledDialog>
    </Box>
  );
};

export default MonitoringIncidents;
