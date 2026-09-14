import { PlayArrow, Pause, Delete, Add, Link as LinkIcon, Edit, Save, Cancel, OpenInNew, ExpandMore, ChevronRight, PauseCircle, PlayCircleOutline, DeleteSweep, Check, Close } from '@mui/icons-material';
import {
  Box, Typography, Card, CardContent, Button, Grid, TextField, Select, MenuItem,
  FormControl, InputLabel, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Paper, IconButton, Chip, Dialog, DialogTitle, DialogContent, DialogActions, Tooltip, Collapse,
  Checkbox, ListSubheader, ListItemText
} from '@mui/material';
import React, { useState, useEffect, useRef } from 'react';
import { io, Socket } from 'socket.io-client';
import { UserinterfaceSelector } from '../components/common/UserinterfaceSelector';
import { ScriptParameterRow } from '../components/common/ParameterInput/ScriptParameterRow';
import { CronHelper } from '../components/common/CronHelper';
import { RecHostStreamModal } from '../components/rec/RecHostStreamModal';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { useHostData } from '../hooks/useHostManager';
import { useToast } from '../hooks/useToast';
import { useDeployment, Deployment } from '../hooks/useDeployment';
import { useRun } from '../hooks/useRun';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { getLogsUrl } from '../utils/executionUtils';
import { openR2Url } from '../utils/infrastructure/cloudflareUtils';
import { getUserTimezone, formatToLocalTime } from '../utils/dateUtils';
import { validateCronExpression, cronToHuman } from '../utils/cronUtils';
import { Host, Device } from '../types/common/Host_Types';
import { useResponsiveMode } from '../hooks/useResponsiveMode';

const Deployments: React.FC = () => {
  const { isMobile, isTablet } = useResponsiveMode();
  const isCompact = isMobile || isTablet;
  // Get Grafana URL from environment variable
  const grafanaUrl = (import.meta as any).env?.VITE_GRAFANA_URL || 'http://localhost/grafana';
  
  const {
    createDeployment,
    listDeployments,
    updateDeployment,
    pauseDeployment,
    resumeDeployment,
    deleteDeployment,
    getRecentExecutions,
    runDeploymentNow,
  } = useDeployment();
  const { getAllHosts, getDevicesFromHost, getHostByName } = useHostData();
  const { showSuccess, showError } = useToast();

  // Confirmation dialog
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const [showCreate, setShowCreate] = useState(false);
  const [showAdvancedSchedule, setShowAdvancedSchedule] = useState(false);
  const [selectedScript, setSelectedScript] = useState('');

  // Selected deployment targets: Map of "hostName:deviceId" -> userinterface
  const [selectedDevices, setSelectedDevices] = useState<Map<string, string>>(new Map());

  // Cron-based scheduling
  const [cronExpression, setCronExpression] = useState('*/10 * * * *'); // Default: every 10 min
  const [cronError, setCronError] = useState<string>('');

  // Optional constraints with smart defaults
  const [startDateOption, setStartDateOption] = useState<'now' | '1hour' | '6hours' | 'tomorrow' | 'nextMonday' | 'custom'>('now');
  const [startDateCustom, setStartDateCustom] = useState<string>('');
  const [endDateOption, setEndDateOption] = useState<'never' | '1day' | '7days' | '30days' | '90days' | 'custom'>('never');
  const [endDateCustom, setEndDateCustom] = useState<string>('');
  const [maxExecutions, setMaxExecutions] = useState<string>(''); // Empty by default (unlimited)

  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [executions, setExecutions] = useState<any[]>([]);
  const [scripts, setScripts] = useState<string[]>([]);
  
  // Edit deployment state
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingDeployment, setEditingDeployment] = useState<Deployment | null>(null);
  const [editCron, setEditCron] = useState('');
  const [editParameters, setEditParameters] = useState('');
  const [editStartDate, setEditStartDate] = useState('');
  const [editEndDate, setEditEndDate] = useState('');
  const [editMaxExecutions, setEditMaxExecutions] = useState('');
  const [inlineEditDeploymentId, setInlineEditDeploymentId] = useState<string | null>(null);
  const [inlineEditParameters, setInlineEditParameters] = useState('');
  const [inlineEditSaving, setInlineEditSaving] = useState(false);

  // Stream modal state
  const [streamModalOpen, setStreamModalOpen] = useState(false);
  const [streamModalHost, setStreamModalHost] = useState<Host | null>(null);
  const [streamModalDevice, setStreamModalDevice] = useState<Device | null>(null);

  // Grouped table state: track which scripts and devices are expanded
  const [expandedScripts, setExpandedScripts] = useState<Set<string>>(new Set());
  const [expandedDevices, setExpandedDevices] = useState<Set<string>>(new Set());
  const [runningScripts, setRunningScripts] = useState<Set<string>>(new Set());
  const deploymentsRefreshDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hosts = getAllHosts();
  const userTimezone = getUserTimezone();
  
  // Open R2 URL with automatic signed URL generation (handles both public and private modes)
  const handleOpenR2Url = async (url: string) => {
    try {
      await openR2Url(url);
    } catch (error) {
      console.error('[@Deployments] Failed to open R2 URL:', error);
    }
  };
  
  // Validate cron expression
  useEffect(() => {
    if (cronExpression) {
      const { valid, error } = validateCronExpression(cronExpression);
      setCronError(valid ? '' : (error || 'Invalid cron expression'));
    }
  }, [cronExpression]);

  // Helper functions to convert dropdown options to dates
  const getStartDate = (): string | null => {
    if (startDateOption === 'now') return null; // Start immediately
    if (startDateOption === 'custom') return startDateCustom ? new Date(startDateCustom).toISOString() : null;
    
    const now = new Date();
    switch (startDateOption) {
      case '1hour':
        now.setHours(now.getHours() + 1);
        break;
      case '6hours':
        now.setHours(now.getHours() + 6);
        break;
      case 'tomorrow':
        now.setDate(now.getDate() + 1);
        now.setHours(0, 0, 0, 0);
        break;
      case 'nextMonday':
        const daysUntilMonday = (8 - now.getDay()) % 7 || 7;
        now.setDate(now.getDate() + daysUntilMonday);
        now.setHours(0, 0, 0, 0);
        break;
    }
    return now.toISOString();
  };

  const getEndDate = (): string | null => {
    if (endDateOption === 'never') return null; // Run forever
    if (endDateOption === 'custom') return endDateCustom ? new Date(endDateCustom).toISOString() : null;
    
    const now = new Date();
    switch (endDateOption) {
      case '1day':
        now.setDate(now.getDate() + 1);
        break;
      case '7days':
        now.setDate(now.getDate() + 7);
        break;
      case '30days':
        now.setDate(now.getDate() + 30);
        break;
      case '90days':
        now.setDate(now.getDate() + 90);
        break;
    }
    return now.toISOString();
  };
  
  // For useRun hook, use first selected target for parameter analysis
  const firstSelectedDevice = React.useMemo(() => {
    if (selectedDevices.size === 0) {
      return { hostName: '', deviceId: '', deviceModel: 'unknown' };
    }
    const firstKey = Array.from(selectedDevices.keys())[0];
    const [hostName, deviceId] = firstKey.split(':');
    if (deviceId) {
      const hostDevices = getDevicesFromHost(hostName);
      const device = hostDevices.find(d => d.device_id === deviceId);
      return { hostName, deviceId, deviceModel: device?.device_model || 'unknown' };
    }
    return { hostName, deviceId: '', deviceModel: 'unknown' };
  }, [selectedDevices]);

  const { scriptAnalysis, parameterValues, handleParameterChange } = useRun({
    selectedScript,
    selectedDevice: firstSelectedDevice.deviceId,
    selectedHost: firstSelectedDevice.hostName,
    showWizard: showCreate
  });

  // Framework parameters with dedicated UI widgets at the top (host, device only)
  // userinterface_name is shown inline if script declares it
  const FRAMEWORK_PARAMS = ['host', 'device'];
  const displayParameters = scriptAnalysis?.parameters.filter(p => !FRAMEWORK_PARAMS.includes(p.name)) || [];
  
  // Check if the selected script requires a device parameter (host-only scripts don't)
  const scriptRequiresDevice = scriptAnalysis?.parameters.some(p => p.name === 'device') ?? true;
  
  // Check if script declares userinterface_name parameter
  const scriptDeclaresUserinterface = scriptAnalysis?.parameters.some(p => p.name === 'userinterface_name');

  // Clear targets when script changes (requirements may differ between host-only and device scripts)
  useEffect(() => {
    setSelectedDevices(new Map());
  }, [selectedScript]);

  useEffect(() => {
    loadScripts();
    loadDeployments();
    loadExecutions();

    const socket: Socket = io(`${window.location.origin}/system`, {
      transports: ['websocket'],
      reconnection: true,
    });

    const scheduleRefresh = () => {
      if (deploymentsRefreshDebounceRef.current) {
        clearTimeout(deploymentsRefreshDebounceRef.current);
      }
      deploymentsRefreshDebounceRef.current = setTimeout(() => {
        loadDeployments();
        loadExecutions();
      }, 300);
    };

    socket.on('system_update', (event: any) => {
      const eventType = String(event?.type || '');
      if (event?.domain === 'deployment' || eventType.startsWith('deployment_')) {
        scheduleRefresh();
      }
    });

    socket.on('connect', scheduleRefresh);

    return () => {
      if (deploymentsRefreshDebounceRef.current) {
        clearTimeout(deploymentsRefreshDebounceRef.current);
        deploymentsRefreshDebounceRef.current = null;
      }
      socket.disconnect();
    };
  }, []);

  const loadScripts = async () => {
    try {
      const res = await fetch(buildServerUrl('/server/script/list'));
      const data = await res.json();
      if (data.success) setScripts(data.scripts);
    } catch (error) {
      showError('Failed to load scripts');
      console.error('Error loading scripts:', error);
    }
  };

  const loadDeployments = async () => {
    const res = await listDeployments();
    if (res.success) setDeployments(res.deployments);
  };

  const loadExecutions = async () => {
    const res = await getRecentExecutions();
    if (res.success) {
      setExecutions([
        ...(res.running_executions || []),
        ...(res.queued_executions || []),
        ...(res.completed_executions || []),
      ]);
    }
  };

  // Handle multi-select target change
  const handleTargetSelectionChange = (event: any) => {
    const values = (typeof event.target.value === 'string' ? event.target.value.split(',') : event.target.value) as string[];
    setSelectedDevices(prev => {
      const newMap = new Map<string, string>();
      values.forEach(key => newMap.set(key, prev.get(key) || ''));
      return newMap;
    });
  };

  // Display name for a target key
  const getTargetDisplayName = (key: string): string => {
    const [hostName, deviceId] = key.split(':');
    if (!deviceId) return hostName;
    const hostDevices = getDevicesFromHost(hostName);
    const device = hostDevices.find(d => d.device_id === deviceId);
    return `${hostName} → ${device?.device_name || deviceId}`;
  };

  const formatHostDeviceLabel = (hostName?: string, deviceId?: string, deviceDisplayName?: string): string => {
    if (!hostName) return '-';
    if (!deviceId || deviceId === 'host') return hostName;
    return `${hostName}:${deviceDisplayName || deviceId}`;
  };

  // Update userinterface for a selected device
  const updateDeviceUserinterface = (deviceKey: string, userinterface: string) => {
    setSelectedDevices(prev => {
      const newMap = new Map(prev);
      newMap.set(deviceKey, userinterface);
      return newMap;
    });
  };

  const handleCreate = async () => {
    // Validate cron expression
    const { valid, error } = validateCronExpression(cronExpression);
    if (!valid) {
      showError(`Invalid cron expression: ${error}`);
      return;
    }

    if (selectedDevices.size === 0 || !selectedScript) {
      showError('Please select at least one target and a script');
      return;
    }

    // Check if script requires userinterface and validate
    if (scriptDeclaresUserinterface) {
      const missingUserinterface = Array.from(selectedDevices.entries()).filter(([, ui]) => !ui);
      if (missingUserinterface.length > 0) {
        showError('Please select userinterface for all devices');
        return;
      }
    }

    // Build params string, excluding userinterface_name (sent separately to API)
    const params = displayParameters
      .filter(p => p.name !== 'userinterface_name')
      .map(p => `--${p.name} ${parameterValues[p.name] || ''}`)
      .join(' ');

    // Prepare optional constraints using helper functions
    const deploymentData: any = {
      cron_expression: cronExpression,
    };

    const startDate = getStartDate();
    if (startDate) {
      deploymentData.start_date = startDate;
    }

    const endDate = getEndDate();
    if (endDate) {
      deploymentData.end_date = endDate;
    }

    if (maxExecutions && parseInt(maxExecutions) > 0) {
      deploymentData.max_executions = parseInt(maxExecutions);
    }

    // Create deployments for all selected devices
    let successCount = 0;
    for (const [deviceKey, userinterface] of Array.from(selectedDevices.entries())) {
      const [hostName, deviceId] = deviceKey.split(':');
      const resolvedDeviceId = deviceId || 'host';

      // Generate unique short ID: timestamp with milliseconds + random suffix
      const now = Date.now();
      const randomSuffix = Math.floor(Math.random() * 1000);
      const deploymentName = `${selectedScript}_${now}${randomSuffix}`;

      const res = await createDeployment({
        name: deploymentName,
        host_name: hostName,
        device_id: resolvedDeviceId,
        script_name: selectedScript,
        userinterface_name: userinterface,
        parameters: params,
        ...deploymentData
      });

      if (res.success) {
        successCount++;
      } else {
        showError(`Failed to create deployment for ${hostName}:${resolvedDeviceId}`);
      }

      // Small delay to ensure unique timestamps
      await new Promise(resolve => setTimeout(resolve, 10));
    }

    if (successCount > 0) {
      showSuccess(`Created ${successCount} deployment${successCount > 1 ? 's' : ''} successfully`);
      setShowCreate(false);
      setSelectedDevices(new Map());
      setCronExpression('*/10 * * * *');
      setStartDateOption('now');
      setStartDateCustom('');
      setEndDateOption('never');
      setEndDateCustom('');
      setMaxExecutions('');
      loadDeployments();
    }
  };

  const handlePause = async (id: string) => {
    await pauseDeployment(id);
    loadDeployments();
  };

  const handleResume = async (id: string) => {
    await resumeDeployment(id);
    loadDeployments();
  };

  const handleDelete = async (id: string, deploymentName: string) => {
    confirm({
      title: 'Confirm Delete',
      message: `Are you sure you want to delete deployment "${deploymentName}"?\n\nThis action cannot be undone.`,
      confirmColor: 'error',
      onConfirm: async () => {
        await deleteDeployment(id);
        loadDeployments();
      },
    });
  };

  const handleEditOpen = (deployment: Deployment) => {
    setEditingDeployment(deployment);
    setEditCron(deployment.cron_expression);
    setEditParameters(deployment.parameters || '');
    setEditStartDate(deployment.start_date || '');
    setEditEndDate(deployment.end_date || '');
    setEditMaxExecutions(deployment.max_executions?.toString() || '');
    setEditDialogOpen(true);
  };

  const handleEditClose = () => {
    setEditDialogOpen(false);
    setEditingDeployment(null);
  };

  const handleEditSave = async () => {
    if (!editingDeployment) return;

    const { valid } = validateCronExpression(editCron);
    if (!valid) {
      showError('Invalid cron expression');
      return;
    }

    try {
      const updateData: any = {
        cron_expression: editCron,
        parameters: editParameters,
        start_date: editStartDate || null,
        end_date: editEndDate || null,
        max_executions: editMaxExecutions ? parseInt(editMaxExecutions) : null,
      };

      const data = await updateDeployment(editingDeployment.id, updateData);
      if (data.success) {
        if (data.deployment) {
          setDeployments((current) => current.map((deployment) => (
            deployment.id === editingDeployment.id ? data.deployment : deployment
          )));
        }
        showSuccess('Deployment updated successfully');
        handleEditClose();
        await loadDeployments();
      } else {
        showError(data.error || 'Failed to update deployment');
      }
    } catch (error) {
      showError('Failed to update deployment');
      console.error('Error updating deployment:', error);
    }
  };

  const handleInlineParameterEditOpen = (deployment: Deployment) => {
    setInlineEditDeploymentId(deployment.id);
    setInlineEditParameters(deployment.parameters || '');
  };

  const handleInlineParameterEditCancel = () => {
    setInlineEditDeploymentId(null);
    setInlineEditParameters('');
    setInlineEditSaving(false);
  };

  const handleInlineParameterSave = async (deploymentId: string) => {
    try {
      setInlineEditSaving(true);
      const res = await fetch(buildServerUrl(`/server/deployment/update/${deploymentId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parameters: inlineEditParameters }),
      });

      const data = await res.json();
      if (data.success) {
        showSuccess('Parameters updated');
        setDeployments(prev => prev.map(dep => (
          dep.id === deploymentId ? { ...dep, parameters: inlineEditParameters } : dep
        )));
        handleInlineParameterEditCancel();
      } else {
        showError(data.error || 'Failed to update parameters');
      }
    } catch (error) {
      showError('Failed to update parameters');
      console.error('Error updating deployment parameters:', error);
    } finally {
      setInlineEditSaving(false);
    }
  };

  const handleDeviceClick = (hostName: string, deviceId: string) => {
    const realHost = getHostByName(hostName);
    if (!realHost) return;

    const hostDevices = getDevicesFromHost(hostName);
    const realDevice = hostDevices.find(d => d.device_id === deviceId);
    if (!realDevice) return;

    setStreamModalHost(realHost);
    setStreamModalDevice(realDevice);
    setStreamModalOpen(true);
  };

  // Toggle script group expansion
  const toggleScriptExpand = (scriptName: string) => {
    setExpandedScripts(prev => {
      const newSet = new Set(prev);
      if (newSet.has(scriptName)) {
        newSet.delete(scriptName);
        // Also collapse all devices under this script
        const deviceKeysToRemove = Array.from(expandedDevices).filter(key => key.startsWith(`${scriptName}:`));
        deviceKeysToRemove.forEach(key => expandedDevices.delete(key));
        setExpandedDevices(new Set(expandedDevices));
      } else {
        newSet.add(scriptName);
      }
      return newSet;
    });
  };

  // Toggle device group expansion
  const toggleDeviceExpand = (scriptName: string, deviceKey: string) => {
    const fullKey = `${scriptName}:${deviceKey}`;
    setExpandedDevices(prev => {
      const newSet = new Set(prev);
      if (newSet.has(fullKey)) {
        newSet.delete(fullKey);
      } else {
        newSet.add(fullKey);
      }
      return newSet;
    });
  };

  // Group deployments by script name, then by device
  const groupedDeployments = React.useMemo(() => {
    const scriptGroups = new Map<string, Map<string, Deployment[]>>();

    deployments.forEach(d => {
      const scriptName = d.script_name;
      const deviceKey = `${d.host_name}:${d.device_id}`;

      if (!scriptGroups.has(scriptName)) {
        scriptGroups.set(scriptName, new Map());
      }
      const scriptGroup = scriptGroups.get(scriptName)!;

      if (!scriptGroup.has(deviceKey)) {
        scriptGroup.set(deviceKey, []);
      }
      scriptGroup.get(deviceKey)!.push(d);
    });

    return scriptGroups;
  }, [deployments]);

  const latestDeviceExecutions = React.useMemo(() => {
    const latestByDevice = new Map<string, any>();
    executions.forEach(e => {
      const hostName = e.deployments?.host_name || 'unknown-host';
      const deviceId = e.deployments?.device_id || 'unknown-device';
      const deviceKey = `${hostName}:${deviceId}`;
      const current = latestByDevice.get(deviceKey);
      if (!current) {
        latestByDevice.set(deviceKey, e);
        return;
      }
      const currentTime = new Date(current.started_at || 0).getTime();
      const nextTime = new Date(e.started_at || 0).getTime();
      if (nextTime > currentTime) {
        latestByDevice.set(deviceKey, e);
      }
    });
    const list = Array.from(latestByDevice.values());
    list.sort((a, b) => new Date(b.started_at || 0).getTime() - new Date(a.started_at || 0).getTime());
    return list;
  }, [executions]);

  // Bulk actions for script groups
  const handlePauseAll = async (scriptName: string) => {
    const deploymentsToPause = deployments.filter(d => d.script_name === scriptName && d.status === 'active');
    for (const d of deploymentsToPause) {
      await pauseDeployment(d.id);
    }
    loadDeployments();
    showSuccess(`Paused ${deploymentsToPause.length} deployment(s)`);
  };

  const handleResumeAll = async (scriptName: string) => {
    const deploymentsToResume = deployments.filter(d => d.script_name === scriptName && d.status === 'paused');
    for (const d of deploymentsToResume) {
      await resumeDeployment(d.id);
    }
    loadDeployments();
    showSuccess(`Resumed ${deploymentsToResume.length} deployment(s)`);
  };

  const handleDeleteAll = async (scriptName: string) => {
    const deploymentsToDelete = deployments.filter(d => d.script_name === scriptName);

    confirm({
      title: 'Confirm Delete All',
      message: `Are you sure you want to delete ${deploymentsToDelete.length} deployment(s) for script "${scriptName}"?\n\nThis action cannot be undone.`,
      confirmColor: 'error',
      onConfirm: async () => {
        for (const d of deploymentsToDelete) {
          await deleteDeployment(d.id);
        }
        loadDeployments();
        showSuccess(`Deleted ${deploymentsToDelete.length} deployment(s)`);
      },
    });
  };

  const handleRunNowScript = async (scriptName: string) => {
    if (runningScripts.has(scriptName)) {
      return;
    }

    const activeDeployments = deployments.filter(d => d.script_name === scriptName && d.status === 'active');
    if (activeDeployments.length === 0) {
      showError('No active deployments available to run');
      return;
    }

    setRunningScripts(prev => {
      const next = new Set(prev);
      next.add(scriptName);
      return next;
    });

    try {
      for (const deployment of activeDeployments) {
        const response = await runDeploymentNow(deployment.id);
        if (!response?.success) {
          throw new Error('Backend rejected run request');
        }
      }
      await loadDeployments();
      await loadExecutions();
      showSuccess(`Triggered ${activeDeployments.length} execution(s) for ${scriptName}`);
    } catch (error) {
      console.error('[@Deployments] Failed to trigger deployments:', error);
      showError('Failed to trigger deployment run. Please try again.');
    } finally {
      setRunningScripts(prev => {
        const next = new Set(prev);
        next.delete(scriptName);
        return next;
      });
    }
  };

  return (
    <Box sx={{ p: isMobile ? 0.25 : isTablet ? 0.75 : 1 }}>
      <Typography variant={isCompact ? 'h6' : 'h5'} sx={{ mb: 1 }}>Deployments</Typography>
      {isCompact ? (
        <Card variant="outlined" sx={{ mb: 1 }}>
          <CardContent sx={{ py: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {deployments.length} active deployment{deployments.length !== 1 ? 's' : ''} • {latestDeviceExecutions.length} recent device results
            </Typography>
          </CardContent>
        </Card>
      ) : null}

      <Grid container spacing={2}>
        {/* Create Deployment */}
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="h6">Create Deployment</Typography>
                <Tooltip title="Open Script Results Dashboard">
                  <IconButton
                    onClick={() => window.open(`${grafanaUrl}/d/2a3b060a-7820-4a6e-aa2a-adcbf5408bd3/script-results?orgId=1&from=now-30d&to=now&timezone=browser&var-user_interface=$__all&var-host=$__all&var-device_name=$__all&var-script_name=$__all&var-success=$__all`, '_blank')}
                    color="primary"
                    size="small"
                  >
                    <OpenInNew fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Box>
              {!showCreate ? (
                <Button variant="contained" startIcon={<Add />} onClick={() => setShowCreate(true)}>
                  New Deployment
                </Button>
              ) : (
                <>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {/* Script + Targets + Parameters - one row */}
                    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: isCompact ? 'stretch' : 'center' }}>
                      <FormControl size="small" sx={{ minWidth: isCompact ? 0 : 200, width: isCompact ? '100%' : 'auto' }}>
                        <InputLabel>Script</InputLabel>
                        <Select value={selectedScript} label="Script" onChange={e => setSelectedScript(e.target.value)}>
                          {scripts.map(s => <MenuItem key={s} value={s}>{s}</MenuItem>)}
                        </Select>
                      </FormControl>

                      {/* Multi-select target dropdown */}
                      <FormControl size="small" sx={{ minWidth: isCompact ? 0 : 300, width: isCompact ? '100%' : 'auto' }}>
                        <InputLabel>Targets</InputLabel>
                        <Select
                          multiple
                          value={Array.from(selectedDevices.keys())}
                          label="Targets"
                          onChange={handleTargetSelectionChange}
                          renderValue={(selected) => (
                            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                              {(selected as string[]).map(key => (
                                <Chip key={key} label={getTargetDisplayName(key)} size="small" />
                              ))}
                            </Box>
                          )}
                          MenuProps={{ PaperProps: { style: { maxHeight: 400 } } }}
                        >
                          {scriptRequiresDevice ? (
                            hosts.flatMap(host => {
                              const hostDevices = getDevicesFromHost(host.host_name);
                              return [
                                <ListSubheader key={`header-${host.host_name}`}>{host.host_name}</ListSubheader>,
                                ...hostDevices.map(d => {
                                  const key = `${host.host_name}:${d.device_id}`;
                                  return (
                                    <MenuItem key={key} value={key}>
                                      <Checkbox checked={selectedDevices.has(key)} size="small" />
                                      <ListItemText primary={`${d.device_name} (${d.device_model})`} />
                                    </MenuItem>
                                  );
                                })
                              ];
                            })
                          ) : (
                            hosts.map(host => {
                              const key = `${host.host_name}:`;
                              return (
                                <MenuItem key={key} value={key}>
                                  <Checkbox checked={selectedDevices.has(key)} size="small" />
                                  <ListItemText primary={host.host_name} />
                                </MenuItem>
                              );
                            })
                          )}
                        </Select>
                      </FormControl>

                      {displayParameters.map(p => {
                        // Per-target UserinterfaceSelectors are rendered in their own
                        // row below (one per selected device), so don't double-render here.
                        if (p.name === 'userinterface_name' || p.name === 'userinterface') return null;
                        return (
                          <Box key={p.name} sx={{ minWidth: isCompact ? 0 : 150, width: isCompact ? '100%' : 'auto' }}>
                            <ScriptParameterRow
                              param={p}
                              value={parameterValues[p.name] || ''}
                              onChange={(value) => handleParameterChange(p.name, value)}
                              allValues={parameterValues}
                              scriptName={(selectedScript || '').replace(/\.py$/, '')}
                              deviceModel={firstSelectedDevice.deviceModel}
                            />
                          </Box>
                        );
                      })}
                    </Box>

                    {/* Userinterface selectors for selected targets (only if script declares it) */}
                    {scriptDeclaresUserinterface && selectedDevices.size > 0 && (
                      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
                        {Array.from(selectedDevices.entries()).map(([key, userinterface]) => {
                          const [hostName, deviceId] = key.split(':');
                          if (!deviceId) return null;
                          const hostDevices = getDevicesFromHost(hostName);
                          const device = hostDevices.find(d => d.device_id === deviceId);
                          return (
                            <Box key={key} sx={{ display: 'flex', alignItems: isCompact ? 'stretch' : 'center', gap: 0.5, flexDirection: isCompact ? 'column' : 'row', width: isCompact ? '100%' : 'auto' }}>
                              <Typography variant="caption" color="text.secondary">{getTargetDisplayName(key)}:</Typography>
                              <Box sx={{ minWidth: isCompact ? 0 : 160, width: isCompact ? '100%' : 'auto' }}>
                                <UserinterfaceSelector
                                  deviceModel={device?.device_model || ''}
                                  value={userinterface}
                                  onChange={(newUi) => updateDeviceUserinterface(key, newUi)}
                                  label="UI"
                                  size="small"
                                  fullWidth
                                />
                              </Box>
                            </Box>
                          );
                        })}
                      </Box>
                    )}

                    {/* Schedule - Everything on ONE line */}
                    <Box>
                      <Typography variant="subtitle2" sx={{ mb: 1 }}>Schedule</Typography>
                      <Box sx={{ display: 'flex', gap: 1, alignItems: isCompact ? 'stretch' : 'center', flexWrap: 'wrap', flexDirection: isCompact ? 'column' : 'row' }}>
                        {/* Cron pattern selector with editable expression */}
                        <CronHelper 
                          value={cronExpression} 
                          onChange={setCronExpression}
                          error={cronError}
                        />
                        {isCompact ? (
                          <Box
                            component="span"
                            onClick={() => setShowAdvancedSchedule(!showAdvancedSchedule)}
                            sx={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 0.5,
                              cursor: 'pointer',
                              color: 'text.secondary',
                              typography: 'caption',
                              userSelect: 'none',
                              '&:hover': { color: 'text.primary' }
                            }}
                          >
                            {showAdvancedSchedule ? <ExpandMore fontSize="small" /> : <ChevronRight fontSize="small" />}
                            Start/end limits
                          </Box>
                        ) : null}
                      </Box>
                      <Collapse in={!isCompact || showAdvancedSchedule}>
                        <Box sx={{ display: 'flex', gap: 1, mt: 1, alignItems: isCompact ? 'stretch' : 'center', flexWrap: 'wrap', flexDirection: isCompact ? 'column' : 'row' }}>
                          {/* Start constraint */}
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, width: isCompact ? '100%' : 'auto' }}>
                            <Typography variant="body2" sx={{ minWidth: 40 }}>Start</Typography>
                            <FormControl size="small" sx={{ minWidth: isCompact ? 0 : 120, width: isCompact ? '100%' : 'auto' }}>
                              <Select
                                value={startDateOption}
                                onChange={e => setStartDateOption(e.target.value as any)}
                                displayEmpty
                              >
                                <MenuItem value="now">Now</MenuItem>
                                <MenuItem value="1hour">In 1 hour</MenuItem>
                                <MenuItem value="6hours">In 6 hours</MenuItem>
                                <MenuItem value="tomorrow">Tomorrow 00:00</MenuItem>
                                <MenuItem value="nextMonday">Next Monday</MenuItem>
                                <MenuItem value="custom">Pick date...</MenuItem>
                              </Select>
                            </FormControl>
                            {startDateOption === 'custom' && (
                              <TextField
                                type="datetime-local"
                                size="small"
                                value={startDateCustom}
                                onChange={e => setStartDateCustom(e.target.value)}
                                sx={{ width: isCompact ? '100%' : 200 }}
                              />
                            )}
                          </Box>

                          {/* End constraint */}
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, width: isCompact ? '100%' : 'auto' }}>
                            <Typography variant="body2" sx={{ minWidth: 30 }}>End</Typography>
                            <FormControl size="small" sx={{ minWidth: isCompact ? 0 : 120, width: isCompact ? '100%' : 'auto' }}>
                              <Select
                                value={endDateOption}
                                onChange={e => setEndDateOption(e.target.value as any)}
                                displayEmpty
                              >
                                <MenuItem value="never">No end</MenuItem>
                                <MenuItem value="1day">+1 day</MenuItem>
                                <MenuItem value="7days">+7 days</MenuItem>
                                <MenuItem value="30days">+30 days</MenuItem>
                                <MenuItem value="90days">+90 days</MenuItem>
                                <MenuItem value="custom">Pick date...</MenuItem>
                              </Select>
                            </FormControl>
                            {endDateOption === 'custom' && (
                              <TextField
                                type="datetime-local"
                                size="small"
                                value={endDateCustom}
                                onChange={e => setEndDateCustom(e.target.value)}
                                sx={{ width: isCompact ? '100%' : 200 }}
                              />
                            )}
                          </Box>

                          {/* Max executions */}
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, width: isCompact ? '100%' : 'auto' }}>
                            <Typography variant="body2" sx={{ minWidth: 30 }}>Max</Typography>
                            <TextField
                              type="number"
                              size="small"
                              value={maxExecutions}
                              onChange={e => setMaxExecutions(e.target.value)}
                              placeholder="unlimited"
                              inputProps={{ min: 1 }}
                              sx={{ width: isCompact ? '100%' : 100 }}
                            />
                            <Typography variant="body2" color="text.secondary">runs</Typography>
                          </Box>
                        </Box>
                      </Collapse>
                    </Box>
                  </Box>

                  <Box display="flex" gap={1} flexDirection={isCompact ? 'column' : 'row'}>
                    <Button
                      variant="contained"
                      onClick={handleCreate}
                      disabled={selectedDevices.size === 0 || !selectedScript}
                      fullWidth={isCompact}
                    >
                      Create {selectedDevices.size > 1 ? `${selectedDevices.size} Deployments` : 'Deployment'}
                    </Button>
                    <Button variant="outlined" onClick={() => {
                      setShowCreate(false);
                      setSelectedDevices(new Map());
                      setCronExpression('*/10 * * * *');
                      setStartDateOption('now');
                      setStartDateCustom('');
                      setEndDateOption('never');
                      setEndDateCustom('');
                      setMaxExecutions('');
                    }} fullWidth={isCompact}>Cancel</Button>
                  </Box>
                </>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Active Deployments - Grouped View */}
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>
                Active Deployments
                <Chip label={deployments.length} size="small" sx={{ ml: 1 }} />
              </Typography>
              {isCompact ? (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {Array.from(groupedDeployments.entries()).map(([scriptName, deviceGroups]) => {
                    const scriptDeployments = deployments.filter(d => d.script_name === scriptName);
                    const activeCount = scriptDeployments.filter(d => d.status === 'active').length;
                    const pausedCount = scriptDeployments.filter(d => d.status === 'paused').length;
                    const isScriptRunning = runningScripts.has(scriptName);

                    return (
                      <Card key={scriptName} variant="outlined">
                        <CardContent sx={{ py: 1.25 }}>
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                            <Typography variant="subtitle2">{scriptName}</Typography>
                            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                              <Chip label={`${scriptDeployments.length}`} size="small" variant="outlined" />
                              {activeCount > 0 ? <Chip label={`${activeCount} active`} size="small" color="success" /> : null}
                              {pausedCount > 0 ? <Chip label={`${pausedCount} paused`} size="small" /> : null}
                            </Box>
                          </Box>

                          <Box sx={{ mt: 0.75, display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            <Button size="small" variant="outlined" onClick={() => handleRunNowScript(scriptName)} disabled={isScriptRunning}>
                              Run Now
                            </Button>
                            {activeCount > 0 ? (
                              <Button size="small" variant="outlined" onClick={() => handlePauseAll(scriptName)}>
                                Pause All
                              </Button>
                            ) : null}
                            {pausedCount > 0 ? (
                              <Button size="small" variant="outlined" onClick={() => handleResumeAll(scriptName)}>
                                Resume All
                              </Button>
                            ) : null}
                            <Button size="small" variant="outlined" color="error" onClick={() => handleDeleteAll(scriptName)}>
                              Delete All
                            </Button>
                          </Box>

                          <Box sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 0.75 }}>
                            {Array.from(deviceGroups.entries()).flatMap(([deviceKey, deviceDeployments]) => {
                              const [hostName, deviceId] = deviceKey.split(':');
                              const hostDevices = getDevicesFromHost(hostName);
                              const deviceObject = hostDevices.find(device => device.device_id === deviceId);
                              const deviceDisplayName = deviceObject?.device_name || deviceId;

                              return deviceDeployments.map((d) => (
                                <Card key={d.id} variant="outlined">
                                  <CardContent sx={{ py: 1 }}>
                                    <Typography
                                      variant="body2"
                                      sx={{
                                        color: 'primary.main',
                                        cursor: 'pointer',
                                        '&:hover': { textDecoration: 'underline' },
                                      }}
                                      onClick={() => handleDeviceClick(hostName, deviceId)}
                                    >
                                      {formatHostDeviceLabel(hostName, deviceId, deviceDisplayName)}
                                    </Typography>
                                    <Typography
                                      variant="caption"
                                      color="text.secondary"
                                      display="block"
                                      sx={{ overflowWrap: 'anywhere' }}
                                    >
                                      {d.parameters && d.parameters.trim() ? d.parameters : '-'}
                                    </Typography>
                                    <Typography variant="caption" display="block" color="text.secondary">
                                      {d.cron_expression} • {cronToHuman(d.cron_expression)}
                                    </Typography>
                                    <Box sx={{ mt: 0.5, display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                                      <Chip label={d.status} color={d.status === 'active' ? 'success' : 'default'} size="small" />
                                      <Button size="small" variant="outlined" onClick={() => handleEditOpen(d)}>Edit</Button>
                                      {d.status === 'active' ? (
                                        <Button size="small" variant="outlined" onClick={() => handlePause(d.id)}>Pause</Button>
                                      ) : (
                                        <Button size="small" variant="outlined" onClick={() => handleResume(d.id)}>Resume</Button>
                                      )}
                                      <Button size="small" variant="outlined" color="error" onClick={() => handleDelete(d.id, d.name)}>Delete</Button>
                                    </Box>
                                  </CardContent>
                                </Card>
                              ));
                            })}
                          </Box>
                        </CardContent>
                      </Card>
                    );
                  })}
                </Box>
              ) : (
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ width: '40%' }}>Script / Device</TableCell>
                      <TableCell>Parameters</TableCell>
                      <TableCell>Schedule</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {Array.from(groupedDeployments.entries()).map(([scriptName, deviceGroups]) => {
                      const scriptDeployments = deployments.filter(d => d.script_name === scriptName);
                      const activeCount = scriptDeployments.filter(d => d.status === 'active').length;
                      const pausedCount = scriptDeployments.filter(d => d.status === 'paused').length;
                      const isScriptRunning = runningScripts.has(scriptName);
                      const isScriptExpanded = expandedScripts.has(scriptName);

                      return (
                        <React.Fragment key={scriptName}>
                          {/* Script-Level Row */}
                          <TableRow
                            sx={{
                              backgroundColor: 'rgba(0, 0, 0, 0.08)',
                              cursor: 'pointer',
                              '&:hover': { backgroundColor: 'rgba(0, 0, 0, 0.12) !important' }
                            }}
                            onClick={() => toggleScriptExpand(scriptName)}
                          >
                            <TableCell colSpan={3}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <IconButton size="small">
                                  {isScriptExpanded ? <ExpandMore /> : <ChevronRight />}
                                </IconButton>
                                <Typography variant="body1" sx={{ fontWeight: 'bold' }}>
                                  {scriptName}
                                </Typography>
                                <Chip label={`${scriptDeployments.length} deployment${scriptDeployments.length !== 1 ? 's' : ''}`} size="small" />
                              </Box>
                            </TableCell>
                            <TableCell>
                              <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                                {activeCount > 0 && (
                                  <Chip label={`${activeCount} active`} color="success" size="small" />
                                )}
                                {pausedCount > 0 && (
                                  <Chip label={`${pausedCount} paused`} color="default" size="small" />
                                )}
                                {activeCount === 0 && pausedCount === 0 && (
                                  <Chip label="idle" size="small" />
                                )}
                              </Box>
                            </TableCell>
                            <TableCell>
                              <Box sx={{ display: 'flex', gap: 0.5 }}>
                                <Tooltip title="Run Now">
                                  <IconButton
                                    size="small"
                                    color="primary"
                                    disabled={isScriptRunning}
                                    onClick={(e) => { e.stopPropagation(); handleRunNowScript(scriptName); }}
                                  >
                                    <PlayArrow fontSize="small" />
                                  </IconButton>
                                </Tooltip>
                                {activeCount > 0 && (
                                  <Tooltip title="Pause All">
                                    <IconButton
                                      size="small"
                                      onClick={(e) => { e.stopPropagation(); handlePauseAll(scriptName); }}
                                    >
                                      <PauseCircle fontSize="small" />
                                    </IconButton>
                                  </Tooltip>
                                )}
                                {pausedCount > 0 && (
                                  <Tooltip title="Resume All">
                                    <IconButton
                                      size="small"
                                      onClick={(e) => { e.stopPropagation(); handleResumeAll(scriptName); }}
                                    >
                                      <PlayCircleOutline fontSize="small" />
                                    </IconButton>
                                  </Tooltip>
                                )}
                                <Tooltip title="Delete All">
                                  <IconButton
                                    size="small"
                                    onClick={(e) => { e.stopPropagation(); handleDeleteAll(scriptName); }}
                                    color="error"
                                  >
                                    <DeleteSweep fontSize="small" />
                                  </IconButton>
                                </Tooltip>
                              </Box>
                            </TableCell>
                          </TableRow>

                          {/* Device-Level Rows (shown when script is expanded) */}
                          {isScriptExpanded && Array.from(deviceGroups.entries()).map(([deviceKey, deviceDeployments]) => {
                            const isDeviceExpanded = expandedDevices.has(`${scriptName}:${deviceKey}`);
                            const [hostName, deviceId] = deviceKey.split(':');
                            const hostDevices = getDevicesFromHost(hostName);
                            const deviceObject = hostDevices.find(device => device.device_id === deviceId);
                            const deviceDisplayName = deviceObject?.device_name || deviceId;

                            return (
                              <React.Fragment key={`${scriptName}:${deviceKey}`}>
                                {/* Device Group Row */}
                                <TableRow
                                  sx={{
                                    backgroundColor: 'rgba(0, 0, 0, 0.04)',
                                    cursor: 'pointer',
                                    '&:hover': { backgroundColor: 'rgba(0, 0, 0, 0.06) !important' }
                                  }}
                                  onClick={() => toggleDeviceExpand(scriptName, deviceKey)}
                                >
                                  <TableCell colSpan={3}>
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, ml: 4 }}>
                                      <IconButton size="small">
                                        {isDeviceExpanded ? <ExpandMore fontSize="small" /> : <ChevronRight fontSize="small" />}
                                      </IconButton>
                                      <Typography
                                        variant="body2"
                                        sx={{
                                          fontWeight: 'medium',
                                          cursor: 'pointer',
                                          color: 'primary.main',
                                          '&:hover': { textDecoration: 'underline' }
                                        }}
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          handleDeviceClick(hostName, deviceId);
                                        }}
                                      >
                                        {formatHostDeviceLabel(hostName, deviceId, deviceDisplayName)}
                                      </Typography>
                                      <Chip label={`${deviceDeployments.length}`} size="small" variant="outlined" />
                                    </Box>
                                  </TableCell>
                                  <TableCell></TableCell>
                                  <TableCell></TableCell>
                                </TableRow>

                                {/* Individual Deployment Rows (shown when device is expanded) */}
                                {isDeviceExpanded && deviceDeployments.map(d => (
                                  <TableRow
                                    key={d.id}
                                    sx={{ '&:hover': { backgroundColor: 'rgba(0, 0, 0, 0.02) !important' } }}
                                  >
                                    <TableCell>
                                      <Box sx={{ ml: 8 }} />
                                    </TableCell>
                                    <TableCell>
                                      {inlineEditDeploymentId === d.id ? (
                                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, minWidth: 260 }}>
                                          <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 0.5 }}>
                                            <Tooltip title="Save parameters">
                                              <span>
                                                <IconButton
                                                  size="small"
                                                  color="primary"
                                                  disabled={inlineEditSaving}
                                                  onClick={() => handleInlineParameterSave(d.id)}
                                                >
                                                  <Check fontSize="small" />
                                                </IconButton>
                                              </span>
                                            </Tooltip>
                                            <Tooltip title="Cancel">
                                              <IconButton
                                                size="small"
                                                disabled={inlineEditSaving}
                                                onClick={handleInlineParameterEditCancel}
                                              >
                                                <Close fontSize="small" />
                                              </IconButton>
                                            </Tooltip>
                                          </Box>
                                          <TextField
                                            value={inlineEditParameters}
                                            onChange={(e) => setInlineEditParameters(e.target.value)}
                                            size="small"
                                            placeholder="--param value"
                                            sx={{
                                              minWidth: 220,
                                              '& .MuiInputBase-input': {
                                                fontFamily: 'monospace',
                                                fontSize: '0.75rem'
                                              }
                                            }}
                                          />
                                        </Box>
                                      ) : (
                                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, minWidth: 260 }}>
                                          <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                                            <Tooltip title="Edit parameters inline">
                                              <IconButton
                                                size="small"
                                                onClick={() => handleInlineParameterEditOpen(d)}
                                              >
                                                <Edit fontSize="inherit" />
                                              </IconButton>
                                            </Tooltip>
                                          </Box>
                                          <Typography
                                            variant="caption"
                                            sx={{
                                              fontFamily: 'monospace',
                                              fontSize: '0.75rem',
                                              whiteSpace: 'nowrap',
                                              overflow: 'hidden',
                                              textOverflow: 'ellipsis'
                                            }}
                                            title={d.parameters && d.parameters.trim() ? d.parameters : '-'}
                                          >
                                            {d.parameters && d.parameters.trim() ? d.parameters : '-'}
                                          </Typography>
                                        </Box>
                                      )}
                                    </TableCell>
                                    <TableCell>
                                      <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                                        {d.cron_expression}
                                      </Typography>
                                      <Typography variant="caption" display="block" color="text.secondary">
                                        {cronToHuman(d.cron_expression)}
                                      </Typography>
                                      {d.execution_count > 0 && (
                                        <Typography variant="caption" display="block" color="primary">
                                          Runs: {d.execution_count}{d.max_executions ? `/${d.max_executions}` : ''}
                                        </Typography>
                                      )}
                                    </TableCell>
                                    <TableCell>
                                      <Chip
                                        label={d.status}
                                        color={d.status === 'active' ? 'success' : 'default'}
                                        size="small"
                                      />
                                    </TableCell>
                                    <TableCell>
                                      <IconButton size="small" onClick={() => handleEditOpen(d)} title="Edit schedule/options"><Edit /></IconButton>
                                      {d.status === 'active' ? (
                                        <IconButton size="small" onClick={() => handlePause(d.id)} title="Pause"><Pause /></IconButton>
                                      ) : (
                                        <IconButton size="small" onClick={() => handleResume(d.id)} title="Resume"><PlayArrow /></IconButton>
                                      )}
                                      <IconButton size="small" onClick={() => handleDelete(d.id, d.name)} title="Delete"><Delete /></IconButton>
                                    </TableCell>
                                  </TableRow>
                                ))}
                              </React.Fragment>
                            );
                          })}
                        </React.Fragment>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Recent Executions */}
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>Recent Executions (Latest per device)</Typography>
              {isCompact ? (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {latestDeviceExecutions.map(e => {
                    const hostName = e.deployments?.host_name;
                    const deviceId = e.deployments?.device_id;
                    let deviceDisplayName = deviceId;

                    if (hostName && deviceId) {
                      const hostDevices = getDevicesFromHost(hostName);
                      const deviceObject = hostDevices.find(device => device.device_id === deviceId);
                      deviceDisplayName = deviceObject?.device_name || deviceId;
                    }

                    return (
                      <Card key={e.id} variant="outlined">
                        <CardContent sx={{ py: 1.25 }}>
                          <Typography variant="subtitle2">{e.deployments?.script_name}</Typography>
                          <Typography
                            variant="body2"
                            sx={{
                              cursor: hostName && deviceId ? 'pointer' : 'default',
                              color: hostName && deviceId ? 'primary.main' : 'inherit',
                              '&:hover': hostName && deviceId ? { textDecoration: 'underline' } : {},
                            }}
                            onClick={() => hostName && deviceId && handleDeviceClick(hostName, deviceId)}
                          >
                            {formatHostDeviceLabel(hostName, deviceId, deviceDisplayName)}
                          </Typography>
                          <Typography variant="caption" display="block" color="text.secondary">
                            {formatToLocalTime(e.started_at)} ({userTimezone})
                          </Typography>
                          <Typography variant="caption" display="block" color="text.secondary">
                            Duration: {e.completed_at ? `${Math.round((new Date(e.completed_at).getTime() - new Date(e.started_at).getTime()) / 1000)}s` : '-'}
                          </Typography>
                          <Box sx={{ mt: 0.5, display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            <Chip label={e.success ? 'Success' : e.completed_at ? 'Failed' : 'Running'} color={e.success ? 'success' : e.completed_at ? 'error' : 'warning'} size="small" />
                            {e.report_url ? (
                              <Chip
                                label="Report"
                                clickable
                                size="small"
                                icon={<LinkIcon />}
                                color="primary"
                                variant="outlined"
                                onClick={() => handleOpenR2Url(e.report_url)}
                              />
                            ) : null}
                            {e.report_url ? (
                              <Chip
                                icon={<LinkIcon />}
                                label="Logs"
                                size="small"
                                clickable
                                onClick={() => handleOpenR2Url(getLogsUrl(e.report_url))}
                                color="secondary"
                                variant="outlined"
                              />
                            ) : null}
                          </Box>
                        </CardContent>
                      </Card>
                    );
                  })}
                </Box>
              ) : (
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Script</TableCell>
                      <TableCell>Host:Device</TableCell>
                      <TableCell>Started</TableCell>
                      <TableCell>Duration</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Report</TableCell>
                      <TableCell>Logs</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {latestDeviceExecutions.map(e => {
                      const hostName = e.deployments?.host_name;
                      const deviceId = e.deployments?.device_id;
                      let deviceDisplayName = deviceId;
                      
                      if (hostName && deviceId) {
                        const hostDevices = getDevicesFromHost(hostName);
                        const deviceObject = hostDevices.find(device => device.device_id === deviceId);
                        deviceDisplayName = deviceObject?.device_name || deviceId;
                      }
                      
                      return (
                        <TableRow 
                          key={e.id}
                          sx={{
                            '&:hover': {
                              backgroundColor: 'rgba(0, 0, 0, 0.04) !important',
                            },
                          }}
                        >
                          <TableCell>{e.deployments?.script_name}</TableCell>
                          <TableCell 
                            sx={{ 
                              cursor: hostName && deviceId ? 'pointer' : 'default', 
                              color: hostName && deviceId ? 'primary.main' : 'inherit', 
                              '&:hover': hostName && deviceId ? { textDecoration: 'underline' } : {} 
                            }}
                            onClick={() => hostName && deviceId && handleDeviceClick(hostName, deviceId)}
                          >
                            {formatHostDeviceLabel(hostName, deviceId, deviceDisplayName)}
                          </TableCell>
                          <TableCell>
                            {formatToLocalTime(e.started_at)}
                            <Typography variant="caption" display="block" color="text.secondary">
                              {userTimezone}
                            </Typography>
                          </TableCell>
                          <TableCell>{e.completed_at ? `${Math.round((new Date(e.completed_at).getTime() - new Date(e.started_at).getTime()) / 1000)}s` : '-'}</TableCell>
                          <TableCell><Chip label={e.success ? 'Success' : e.completed_at ? 'Failed' : 'Running'} color={e.success ? 'success' : e.completed_at ? 'error' : 'warning'} size="small" /></TableCell>
                          <TableCell>
                            {e.report_url ? (
                              <Chip
                                label="View Report"
                                clickable
                                size="small"
                                sx={{ cursor: 'pointer' }}
                                icon={<LinkIcon />}
                                color="primary"
                                variant="outlined"
                                onClick={() => handleOpenR2Url(e.report_url)}
                              />
                            ) : (
                              <Chip label="No Report" size="small" variant="outlined" disabled />
                            )}
                          </TableCell>
                          <TableCell>
                            {e.report_url ? (
                              <Chip
                                icon={<LinkIcon />}
                                label="Logs"
                                size="small"
                                clickable
                                onClick={() => handleOpenR2Url(getLogsUrl(e.report_url))}
                                color="secondary"
                                variant="outlined"
                              />
                            ) : (
                              <Chip label="No Logs" size="small" variant="outlined" disabled />
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Edit Deployment Dialog */}
      <Dialog
        open={editDialogOpen}
        onClose={handleEditClose}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: {
            border: '1px solid',
            borderColor: 'rgba(255, 255, 255, 0.2)',
            backgroundImage: 'linear-gradient(140deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02))',
            backdropFilter: 'blur(8px)',
            boxShadow: '0 24px 80px rgba(0, 0, 0, 0.45)',
            borderRadius: 2.5,
            overflow: 'hidden'
          }
        }}
      >
        <DialogTitle sx={{ borderBottom: '1px solid rgba(255, 255, 255, 0.12)', pb: 1.5 }}>
          Edit Deployment: {editingDeployment?.name}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 2 }}>
            {/* Script Parameters */}
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>Script Parameters</Typography>
              <TextField
                value={editParameters}
                onChange={(e) => setEditParameters(e.target.value)}
                size="small"
                fullWidth
                multiline
                minRows={2}
                placeholder="e.g. --dns example.com --password secret123"
                helperText="Edit CLI arguments passed to the script"
                sx={{
                  '& .MuiInputBase-input': {
                    fontFamily: 'monospace',
                    fontSize: '0.85rem'
                  }
                }}
              />
            </Box>

            {/* Schedule */}
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>Schedule</Typography>
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                <TextField
                  label="Cron Expression"
                  value={editCron}
                  onChange={(e) => setEditCron(e.target.value)}
                  size="small"
                  fullWidth
                  helperText={cronToHuman(editCron)}
                />
              </Box>
            </Box>

            {/* Start Date */}
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>Start Date (Optional)</Typography>
              <TextField
                type="datetime-local"
                value={editStartDate ? new Date(editStartDate).toISOString().slice(0, 16) : ''}
                onChange={(e) => setEditStartDate(e.target.value ? new Date(e.target.value).toISOString() : '')}
                size="small"
                fullWidth
                helperText="Leave empty to start immediately"
              />
            </Box>

            {/* End Date */}
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>End Date (Optional)</Typography>
              <TextField
                type="datetime-local"
                value={editEndDate ? new Date(editEndDate).toISOString().slice(0, 16) : ''}
                onChange={(e) => setEditEndDate(e.target.value ? new Date(e.target.value).toISOString() : '')}
                size="small"
                fullWidth
                helperText="Leave empty for no end date"
              />
            </Box>

            {/* Max Executions */}
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>Max Executions (Optional)</Typography>
              <TextField
                type="number"
                value={editMaxExecutions}
                onChange={(e) => setEditMaxExecutions(e.target.value)}
                size="small"
                fullWidth
                placeholder="Unlimited"
                inputProps={{ min: 1 }}
                helperText="Leave empty for unlimited executions"
              />
            </Box>
          </Box>
        </DialogContent>
        <DialogActions sx={{ borderTop: '1px solid rgba(255, 255, 255, 0.12)', px: 3, py: 2 }}>
          <Button onClick={handleEditClose} startIcon={<Cancel />}>Cancel</Button>
          <Button onClick={handleEditSave} variant="contained" startIcon={<Save />}>Save Changes</Button>
        </DialogActions>
      </Dialog>

      {/* Stream Modal */}
      {streamModalHost && streamModalDevice && (
        <RecHostStreamModal
          host={streamModalHost}
          device={streamModalDevice}
          isOpen={streamModalOpen}
          onClose={() => {
            setStreamModalOpen(false);
            setStreamModalHost(null);
            setStreamModalDevice(null);
          }}
          showRemoteByDefault={false}
        />
      )}

      {/* Confirmation Dialog */}
      <ConfirmDialog
        open={dialogState.open}
        title={dialogState.title}
        message={dialogState.message}
        confirmText={dialogState.confirmText}
        cancelText={dialogState.cancelText}
        confirmColor={dialogState.confirmColor}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </Box>
  );
};

export default Deployments;
