/**
 * Alerts Viewer - Embedded alerts monitoring for AgentChat
 *
 * Shows only the "In Progress" incidents from MonitoringIncidents page.
 * Excludes closed alerts, history, and analysis sections for clean viewing.
 */

import React, { useState, useEffect, useCallback } from 'react';
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
  IconButton,
  Collapse,
  Grid,
  Switch,
  FormControlLabel,
} from '@mui/material';
import {
  Error as ActiveIcon,
  KeyboardArrowDown as ExpandMoreIcon,
  KeyboardArrowRight as ExpandLessIcon,
  SmartToy as AiIcon,
  Person as ManualIcon,
  CheckCircle as CheckedIcon,
  Help as UnknownIcon,
  Visibility as DetailsIcon,
  VisibilityOff as HideDetailsIcon,
  Warning as DiscardedIcon,
  Check as ValidIcon,
  RemoveCircleOutline as SkippedIcon,
} from '@mui/icons-material';

import { HeatMapFreezeModal } from '../../components/heatmap/HeatMapFreezeModal';
import { R2Image } from '../../components/common/R2Image';
import { useAlerts } from '../../hooks/pages/useAlerts';
import { Alert } from '../../types/pages/Monitoring_Types';

const AlertsViewerContent: React.FC = () => {
  const { getAllAlerts, updateCheckedStatus, updateDiscardStatus } = useAlerts();

  const [activeAlerts, setActiveAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [showDetailedColumns, setShowDetailedColumns] = useState(false);

  // Modal states
  const [freezeModalOpen, setFreezeModalOpen] = useState(false);
  const [freezeModalAlert, setFreezeModalAlert] = useState<Alert | null>(null);

  // Load alerts data function
  const loadAlerts = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const allAlerts = await getAllAlerts();

      // Filter for only active alerts (in progress)
      const active = allAlerts.filter((alert) => alert.status === 'active');

      setActiveAlerts(active);

      console.log(`[@AlertsViewer] Loaded ${active.length} active alerts`);
    } catch (err) {
      console.error('[@AlertsViewer] Error loading alerts:', err);
      setError(err instanceof Error ? err.message : 'Failed to load alerts');
    } finally {
      setLoading(false);
    }
  }, [getAllAlerts]);

  // Load alerts on mount
  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  // Calculate stats
  const totalActiveAlerts = activeAlerts.length;

  // Calculate this week's alerts (last 7 days)
  const oneWeekAgo = new Date();
  oneWeekAgo.setDate(oneWeekAgo.getDate() - 7);
  const alertsThisWeek = activeAlerts.filter(
    (alert) => new Date(alert.start_time) >= oneWeekAgo,
  ).length;

  // Get most common incident type
  const incidentTypeCounts = activeAlerts.reduce(
    (acc, alert) => {
      acc[alert.incident_type] = (acc[alert.incident_type] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  const mostCommonIncidentType =
    Object.entries(incidentTypeCounts).sort(([, a], [, b]) => b - a)[0]?.[0] || 'N/A';

  // Format duration between two dates
  const formatDuration = (startTime: string): string => {
    try {
      const start = new Date(startTime);
      const end = new Date();

      if (isNaN(start.getTime())) {
        return 'Invalid Date';
      }

      const durationMs = end.getTime() - start.getTime();

      if (durationMs < 0) {
        return 'Time sync issue';
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
      return 'Error';
    }
  };

  // Format date helper
  const formatDate = (dateString: string): string => {
    try {
      const date = new Date(dateString);
      if (isNaN(date.getTime())) {
        return 'Invalid Date';
      }
      return date.toLocaleDateString() + ', ' + date.toLocaleTimeString();
    } catch (error) {
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

      setActiveAlerts((alerts) =>
        alerts.map((a) =>
          a.id === alert.id ? { ...a, checked: newChecked, check_type: 'manual' } : a,
        ),
      );
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

      setActiveAlerts((alerts) =>
        alerts.map((a) =>
          a.id === alert.id ? { ...a, discard: newDiscard, check_type: checkType } : a,
        ),
      );
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
      return <Typography variant="body2" color="text.disabled">-</Typography>;
    }
    if (!alert.checked) {
      return <Typography variant="body2" color="text.disabled">-</Typography>;
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
      return <Typography variant="body2" color="text.disabled">-</Typography>;
    }
    if (alert.check_type === 'ai_strategy_skip') {
      return <Typography variant="body2" color="text.disabled" sx={{ fontStyle: 'italic' }}>Skipped</Typography>;
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
      return <Typography variant="body2" color="text.disabled">-</Typography>;
    }
    return (
      <Chip label={alert.discard_type} color="info" size="small" variant="outlined" />
    );
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

    if (r2Images?.thumbnail_urls && r2Images.thumbnail_urls.length > 0) {
      return {
        originalUrl: r2Images.thumbnail_urls[0],
        thumbnailUrl: r2Images.thumbnail_urls[0],
        closureUrl: null,
        hasR2Images: true,
      };
    }

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

  // Render expandable row content
  const renderExpandedContent = (alert: Alert) => {
    const imageUrls = getAlertImageUrls(alert);
    const r2Images = alert.metadata?.r2_images;
    const freezeDiffs = alert.metadata?.freeze_diffs || [];
    const freezeImageUrls = r2Images?.thumbnail_urls || [];

    return (
      <Box sx={{ p: 1 }}>
        {alert.incident_type === 'freeze' && freezeImageUrls.length > 0 && (
          <Box>
            <Grid container spacing={2} alignItems="flex-start">
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

        {imageUrls.hasR2Images && alert.incident_type !== 'freeze' && (
          <Box>
            <Grid container spacing={3} alignItems="center">
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
                      height: 'auto',
                      borderRadius: 1,
                      border: '1px solid',
                      borderColor: 'divider',
                    }}
                  />
                </Box>
              </Grid>

              {imageUrls.closureUrl && (
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
                        height: 'auto',
                        borderRadius: 1,
                        border: '1px solid',
                        borderColor: 'divider',
                      }}
                    />
                  </Box>
                </Grid>
              )}
            </Grid>
          </Box>
        )}

        {!imageUrls.hasR2Images && (
          <Box sx={{ textAlign: 'center', color: 'text.secondary' }}>
            <Typography variant="body2">No additional data available for this alert</Typography>
          </Box>
        )}
      </Box>
    );
  };

  // Loading state
  const LoadingState = () => (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
      <CircularProgress />
    </Box>
  );

  // Empty state
  const EmptyState = () => (
    <Box sx={{ textAlign: 'center', py: 4 }}>
      <Typography variant="body2" color="textSecondary">
        No active alerts
      </Typography>
    </Box>
  );

  return (
    <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
      {error && (
        <MuiAlert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </MuiAlert>
      )}

      {/* Stats Header */}
      <Box sx={{ mb: 1 }}>
        <Card>
          <CardContent sx={{ py: 1, px: 2, height: '30px !important' }}>
            <Box display="flex" alignItems="center" justifyContent="space-between">
              <Box display="flex" alignItems="center" gap={1}>
                <ActiveIcon color="error" sx={{ fontSize: 16 }} />
                <Typography variant="subtitle2" fontWeight={600}>
                  Active Alerts
                </Typography>
                <Typography variant="caption" sx={{ mx: 1 }}>
                  Active: {totalActiveAlerts}
                </Typography>
                <Typography variant="caption" sx={{ mx: 1 }}>
                  This Week: {alertsThisWeek}
                </Typography>
                <Typography variant="caption" sx={{ mx: 1 }}>
                  Common Type: {mostCommonIncidentType}
                </Typography>
           
          
              </Box>
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
                    <Typography variant="caption">
                      {showDetailedColumns ? 'Hide' : 'Show'} Analysis Details
                    </Typography>
                  </Box>
                }
              />
            </Box>
          </CardContent>
        </Card>
      </Box>

      {/* Alerts Table */}
      <Box sx={{ flex: 1, overflow: 'auto' }}>
        <Card>
          <CardContent sx={{ p: 0 }}>

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
                    <TableCell sx={{ py: 0.25, width: 50 }}>
                      <strong>Expand</strong>
                    </TableCell>
                    <TableCell sx={{ py: 0.25 }}>
                      <strong>Incident</strong>
                    </TableCell>
                    <TableCell sx={{ py: 0.25 }}>
                      <strong>Host</strong>
                    </TableCell>
                    <TableCell sx={{ py: 0.25 }}>
                      <strong>Device</strong>
                    </TableCell>
                    <TableCell sx={{ py: 0.25 }}>
                      <strong>Start</strong>
                    </TableCell>
                    <TableCell sx={{ py: 0.25 }}>
                      <strong>Duration</strong>
                    </TableCell>
                    {showDetailedColumns && (
                      <>
                        <TableCell sx={{ py: 0.25 }}>
                          <strong>Checked</strong>
                        </TableCell>
                        <TableCell sx={{ py: 0.25 }}>
                          <strong>Discard</strong>
                        </TableCell>
                        <TableCell sx={{ py: 0.25 }}>
                          <strong>Check Type</strong>
                        </TableCell>
                        <TableCell sx={{ py: 0.25 }}>
                          <strong>Discard Type</strong>
                        </TableCell>
                      </>
                    )}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {loading ? (
                    <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                      <TableCell colSpan={showDetailedColumns ? 10 : 6}>
                        <LoadingState />
                      </TableCell>
                    </TableRow>
                  ) : activeAlerts.length === 0 ? (
                    <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                      <TableCell colSpan={showDetailedColumns ? 10 : 6}>
                        <EmptyState />
                      </TableCell>
                    </TableRow>
                  ) : (
                    activeAlerts.map((alert) => (
                      <React.Fragment key={alert.id}>
                        <TableRow
                          sx={{
                            '&:hover': {
                              backgroundColor: 'transparent !important',
                            },
                            height: '30px', // Compact height for main rows
                          }}
                        >
                          <TableCell sx={{ py: 0.25 }}>
                            <IconButton
                              size="small"
                              onClick={() => toggleRowExpansion(alert.id)}
                              sx={{ p: 0.25 }}
                            >
                              {expandedRows.has(alert.id) ? <ExpandMoreIcon /> : <ExpandLessIcon />}
                            </IconButton>
                          </TableCell>
                          <TableCell sx={{ py: 0.25 }}>
                              <Chip
                                icon={<ActiveIcon />}
                                label={alert.incident_type}
                                color={getIncidentTypeColor(alert.incident_type)}
                                size="small"
                                sx={{ height: '24px', fontSize: '0.75rem' }}
                              />
                          </TableCell>
                          <TableCell sx={{ py: 0.25 }}>{alert.host_name}</TableCell>
                          <TableCell sx={{ py: 0.25 }}>{alert.device_id}</TableCell>
                          <TableCell sx={{ py: 0.25 }}>{formatDate(alert.start_time)}</TableCell>
                          <TableCell sx={{ py: 0.25 }}>{formatDuration(alert.start_time)}</TableCell>
                          {showDetailedColumns && (
                            <>
                              <TableCell sx={{ py: 0.25 }}>{getCheckedStatus(alert)}</TableCell>
                              <TableCell sx={{ py: 0.25 }}>{getDiscardStatus(alert)}</TableCell>
                              <TableCell sx={{ py: 0.25 }}>{getCheckType(alert)}</TableCell>
                              <TableCell sx={{ py: 0.25 }}>{getDiscardType(alert)}</TableCell>
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
                            <TableCell colSpan={showDetailedColumns ? 10 : 6} sx={{ p: 0, borderBottom: 0 }}>
                              <Collapse in={expandedRows.has(alert.id)} timeout="auto" unmountOnExit>
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
      </Box>

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
    </Box>
  );
};

// Main component
export const AlertsViewer: React.FC = () => {
  return <AlertsViewerContent />;
};

export default AlertsViewer;
