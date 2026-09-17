import {
  CheckCircle as ResolvedIcon,
  Error as ActiveIcon,
  Visibility as MonitorIcon,
  KeyboardArrowDown as ExpandMoreIcon,
  KeyboardArrowRight as ExpandLessIcon,
  SmartToy as AiIcon,
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
} from '@mui/material';
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';

import { HeatMapFreezeModal } from '../components/heatmap/HeatMapFreezeModal';
import { R2Image } from '../components/common/R2Image';
import { StyledDialog } from '../components/common/StyledDialog';
import DesktopOnlyPlaceholder from '../components/mobile/DesktopOnlyPlaceholder';
import { useAlerts } from '../hooks/pages/useAlerts';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { Alert } from '../types/pages/Monitoring_Types';
import { parseIncidentFocus, findFocusedAlert } from '../utils/incidentFocus';

const MonitoringIncidents: React.FC = () => {
  const { isMobile } = useResponsiveMode();
  const { getAllAlerts, updateCheckedStatus, updateDiscardStatus, deleteAllAlerts } = useAlerts();
  const [activeAlerts, setActiveAlerts] = useState<Alert[]>([]);
  const [closedAlerts, setClosedAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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
        color="info"
        size="small"
        variant="outlined"
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
    <Box>
      <Box sx={{ mb: 0.5 }}>
        <Typography variant="h4" sx={{ mb: 1 }}>
          Alerts
        </Typography>
      </Box>

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
      <Box sx={{ mb: 1 }}>
        <Card>
          <CardContent sx={{ py: 0.5 }}>
            <Box display="flex" alignItems="center" justifyContent="space-between">
              <Box display="flex" alignItems="center" gap={1}>
                <MonitorIcon color="primary" />
                <Typography variant="h6" sx={{ my: 0 }}>Incident Summary</Typography>
              </Box>

              <Box display="flex" alignItems="center" gap={4}>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Active Alerts</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {totalActiveAlerts}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">This Week</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {alertsThisWeek}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Common Type</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {mostCommonIncidentType}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Total Closed</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {totalClosedAlerts}
                  </Typography>
                </Box>
                <Tooltip title="Clear all alerts from database">
                  <Button
                    variant="outlined"
                    color="error"
                    size="small"
                    startIcon={<DeleteIcon />}
                    onClick={() => setClearConfirmOpen(true)}
                    disabled={loading || totalActiveAlerts + totalClosedAlerts === 0}
                  >
                    Clear All
                  </Button>
                </Tooltip>
              </Box>
            </Box>
          </CardContent>
        </Card>
      </Box>

      <Grid container spacing={1}>
        {/* Alerts In Progress */}
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="h6" sx={{ my: 0 }}>
                  In Progress
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
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ py: 0.5, width: 50 }}>
                        <strong>Expand</strong>
                      </TableCell>
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
                    ) : activeAlerts.length === 0 ? (
                      <EmptyState message="No active alerts" colSpan={showDetailedColumns ? 11 : 6} />
                    ) : (
                      activeAlerts.map((alert) => (
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
                            <TableCell sx={{ py: 0.5 }}>
                              <IconButton
                                size="small"
                                onClick={() => toggleRowExpansion(alert.id)}
                                sx={{ p: 0.5 }}
                              >
                                {expandedRows.has(alert.id) ? (
                                  <ExpandMoreIcon />
                                ) : (
                                  <ExpandLessIcon />
                                )}
                              </IconButton>
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              <Chip
                                icon={<ActiveIcon />}
                                label={alert.incident_type}
                                color={getIncidentTypeColor(alert.incident_type)}
                                size="small"
                              />
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>{alert.host_name}</TableCell>
                            <TableCell sx={{ py: 0.5 }}>{alert.device_id}</TableCell>
                            <TableCell sx={{ py: 0.5 }}>{formatDate(alert.start_time)}</TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              {formatDuration(alert.start_time)}
                            </TableCell>
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
                                  <Box sx={{ backgroundColor: 'rgba(0, 0, 0, 0.02)' }}>
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
        </Grid>

        {/* Alerts Closed */}
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="h6" sx={{ my: 0 }}>
                  Closed
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
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ py: 0.5, width: 50 }}>
                        <strong>Expand</strong>
                      </TableCell>
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
                        <TableCell colSpan={showDetailedColumns ? 12 : 7}>
                          <LoadingState />
                        </TableCell>
                      </TableRow>
                    ) : closedAlerts.length === 0 ? (
                      <EmptyState message="No closed alerts" colSpan={showDetailedColumns ? 12 : 7} />
                    ) : (
                      closedAlerts.map((alert) => (
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
                            <TableCell sx={{ py: 0.5 }}>
                              <IconButton
                                size="small"
                                onClick={() => toggleRowExpansion(alert.id)}
                                sx={{ p: 0.5 }}
                              >
                                {expandedRows.has(alert.id) ? (
                                  <ExpandMoreIcon />
                                ) : (
                                  <ExpandLessIcon />
                                )}
                              </IconButton>
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              <Chip
                                icon={<ResolvedIcon />}
                                label={alert.incident_type}
                                color="success"
                                size="small"
                                variant="outlined"
                              />
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>{alert.host_name}</TableCell>
                            <TableCell sx={{ py: 0.5 }}>{alert.device_id}</TableCell>
                            <TableCell sx={{ py: 0.5 }}>{formatDate(alert.start_time)}</TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              {alert.end_time ? formatDate(alert.end_time) : 'N/A'}
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              {alert.end_time
                                ? formatDuration(alert.start_time, alert.end_time)
                                : 'N/A'}
                            </TableCell>
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
                              <TableCell colSpan={showDetailedColumns ? 12 : 7} sx={{ p: 0, borderBottom: 0 }}>
                                <Collapse
                                  in={expandedRows.has(alert.id)}
                                  timeout="auto"
                                  unmountOnExit
                                >
                                  <Box sx={{ backgroundColor: 'rgba(0, 0, 0, 0.02)' }}>
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
        </Grid>
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
