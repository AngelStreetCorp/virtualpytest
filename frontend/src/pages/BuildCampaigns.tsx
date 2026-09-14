import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { Save as SaveIcon, Add as AddIcon, Edit as EditIcon, Delete as DeleteIcon } from '@mui/icons-material';

import { ExecutableTypeToggle } from '../components/common/ExecutableTypeToggle';
import { VersionHistoryDialog, VersionHistoryRow } from '../components/common/VersionHistoryDialog';
import { ScriptSequenceBuilder } from '../components/campaigns/ScriptSequenceBuilder';
import { UnifiedExecutableSelector, ExecutableItem } from '../components/common/UnifiedExecutableSelector';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { useCampaign } from '../hooks/pages/useCampaign';
import { useToast } from '../hooks/useToast';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';
import {
  getCachedCampaignExecutableList,
  getCachedExecutableList,
  invalidateCampaignExecutableListCache,
} from '../utils/executionListCache';
import { getCampaignBadge } from '../config/constants';

interface CampaignExecutableListItem {
  id: string;
  source: 'db' | 'file';
  name: string;
  description?: string;
}

const BuildCampaigns: React.FC = () => {
  const { isMobile, isTablet } = useResponsiveMode();
  const isCompact = isMobile || isTablet;
  const { showSuccess, showError } = useToast();
  const {
    campaignConfig,
    updateCampaignConfig,
    resetCampaignConfig,
    aiTestCasesInfo,
    addScript,
    removeScript,
    reorderScripts,
    updateScriptConfiguration,
    scriptAnalysisCache,
    loadScriptAnalysis,
    error,
  } = useCampaign();

  const [namePrefix, setNamePrefix] = useState('');
  const [savingCampaign, setSavingCampaign] = useState(false);
  const [selectorTypeFilter, setSelectorTypeFilter] = useState<string | null>(isCompact ? null : 'script');
  const [existingCampaigns, setExistingCampaigns] = useState<CampaignExecutableListItem[]>([]);
  const [existingCampaignFilter, setExistingCampaignFilter] = useState<'db' | 'file'>('db');
  const [existingCampaignNames, setExistingCampaignNames] = useState<Set<string>>(new Set());
  const [executableMetaMap, setExecutableMetaMap] = useState<Record<string, ExecutableItem>>({});
  const [editingCampaignId, setEditingCampaignId] = useState<string | null>(null);
  const [loadingCampaign, setLoadingCampaign] = useState<string | null>(null);
  const [loadedCampaignSnapshot, setLoadedCampaignSnapshot] = useState<string | null>(null);
  const [versionDialogOpen, setVersionDialogOpen] = useState(false);
  const [versionRows, setVersionRows] = useState<VersionHistoryRow[]>([]);
  const [loadingVersions, setLoadingVersions] = useState(false);
  const [restoringVersion, setRestoringVersion] = useState<number | null>(null);
  const [deletingCampaign, setDeletingCampaign] = useState(false);

  const normalizeScriptConfigurationsForCompare = (scripts: any[] = []) => (
    scripts.map((script, index) => ({
      script_name: script.script_name || '',
      script_type: script.testcase_id ? 'testcase' : 'script',
      testcase_id: script.testcase_id || undefined,
      description: script.description || '',
      parameters: script.parameters || {},
      order: typeof script.order === 'number' ? script.order : index,
    }))
  );

  useEffect(() => {
    loadExistingCampaigns();
    loadExecutableMetadata();
  }, []);

  useEffect(() => {
    setSelectorTypeFilter(isCompact ? null : 'script');
  }, [isCompact]);

  const loadExistingCampaigns = async () => {
    try {
      const response = await getCachedCampaignExecutableList(buildServerUrl('/server/campaigns/listExecutables'));
      const executables = response.executables || [];
      setExistingCampaigns(executables);
      setExistingCampaignNames(
        new Set(
          executables
            .filter((item: CampaignExecutableListItem) => item.source === 'db')
            .map((item: CampaignExecutableListItem) => item.name.trim().toLowerCase()),
        ),
      );
    } catch (loadError) {
      console.error('[@BuildCampaigns] Failed to load existing campaigns:', loadError);
    }
  };

  const loadExecutableMetadata = async () => {
    try {
      const payload = await getCachedExecutableList(buildServerUrl('/server/executable/list'));
      if (!payload?.success) {
        throw new Error(payload?.error || 'Failed to load executables');
      }
      const nextMap: Record<string, ExecutableItem> = {};
      (payload.folders || []).forEach((folder: any) => {
        (folder.items || []).forEach((item: ExecutableItem) => {
          nextMap[item.id] = item;
          nextMap[item.name] = item;
        });
      });
      setExecutableMetaMap(nextMap);
    } catch (loadError) {
      console.error('[@BuildCampaigns] Failed to load executable metadata:', loadError);
    }
  };

  const hydrateCampaignEditor = (campaignId: string, c: any) => {
    setEditingCampaignId(campaignId);
    setNamePrefix('');
    updateCampaignConfig({
      name: c.name || c.campaign_name || '',
      description: c.description || '',
      execution_config: {
        continue_on_failure: c.execution_config?.continue_on_failure ?? true,
        timeout_minutes: c.execution_config?.timeout_minutes ?? 120,
        parallel: c.execution_config?.parallel ?? false,
      },
      script_configurations: c.script_configurations || [],
    });
    setLoadedCampaignSnapshot(JSON.stringify({
      name: (c.name || c.campaign_name || '').trim(),
      description: c.description || '',
      timeout_minutes: c.execution_config?.timeout_minutes ?? 120,
      script_configurations: normalizeScriptConfigurationsForCompare(c.script_configurations || []),
    }));
  };

  const loadCampaignById = async (campaignId: string) => {
    setLoadingCampaign(campaignId);
    try {
      const response = await api.get<any>(buildServerUrl(`/server/campaigns/getCampaign/${campaignId}`));
      if (!response?.success || !response?.campaign) {
        throw new Error(response?.error || 'Failed to load campaign');
      }
      hydrateCampaignEditor(campaignId, response.campaign);
    } catch (loadErr) {
      showError(loadErr instanceof Error ? loadErr.message : 'Failed to load campaign');
    } finally {
      setLoadingCampaign(null);
    }
  };

  const loadCampaignForEditing = async (item: CampaignExecutableListItem) => {
    if (item.source !== 'db') return;
    await loadCampaignById(item.id);
  };

  const loadCampaignVersions = async () => {
    if (!editingCampaignId) return;
    setLoadingVersions(true);
    try {
      const response = await api.get<{ success: boolean; versions: VersionHistoryRow[] }>(
        buildServerUrl(`/server/campaigns/${editingCampaignId}/history`),
      );
      if (!response?.success) {
        throw new Error('Failed to load version history');
      }
      setVersionRows(response.versions || []);
      setVersionDialogOpen(true);
    } catch (loadError) {
      showError(loadError instanceof Error ? loadError.message : 'Failed to load version history');
    } finally {
      setLoadingVersions(false);
    }
  };

  const handleRestoreCampaignVersion = async (versionNumber: number) => {
    if (!editingCampaignId) return;
    const confirmed = window.confirm(`Restore campaign version ${versionNumber} as the new latest version?`);
    if (!confirmed) return;

    setRestoringVersion(versionNumber);
    try {
      const response = await api.post<any>(buildServerUrl(`/server/campaigns/${editingCampaignId}/restore/${versionNumber}`));
      if (!response?.success) {
        throw new Error(response?.error || 'Failed to restore campaign version');
      }
      await loadCampaignById(editingCampaignId);
      await loadCampaignVersions();
      await loadExistingCampaigns();
      showSuccess(`Restored version ${versionNumber} as version ${response.new_version}`);
    } catch (restoreError) {
      showError(restoreError instanceof Error ? restoreError.message : 'Failed to restore campaign version');
    } finally {
      setRestoringVersion(null);
    }
  };

  const handleDeleteCampaign = async () => {
    if (!editingCampaignId) return;
    const campaignName = existingCampaigns.find((c) => c.id === editingCampaignId)?.name || 'this campaign';
    const confirmed = window.confirm(`Delete "${campaignName}"? This action cannot be undone.`);
    if (!confirmed) return;

    setDeletingCampaign(true);
    try {
      const response = await api.delete<any>(buildServerUrl(`/server/campaigns/deleteCampaign/${editingCampaignId}`));
      if (response && response.success === false) {
        throw new Error(response.error || 'Failed to delete campaign');
      }
      showSuccess(`Campaign "${campaignName}" deleted`);
      invalidateCampaignExecutableListCache();
      setEditingCampaignId(null);
      setLoadedCampaignSnapshot(null);
      setNamePrefix('');
      resetCampaignConfig();
      await loadExistingCampaigns();
    } catch (deleteError) {
      showError(deleteError instanceof Error ? deleteError.message : 'Failed to delete campaign');
    } finally {
      setDeletingCampaign(false);
    }
  };

  const handleNewCampaign = () => {
    setEditingCampaignId(null);
    setLoadedCampaignSnapshot(null);
    setNamePrefix('');
    resetCampaignConfig();
  };

  const fullCampaignName = useMemo(() => {
    const prefix = namePrefix.trim();
    const name = (campaignConfig.name || '').trim();
    if (!prefix) return name;
    if (!name) return prefix;
    return `${prefix} ${name}`;
  }, [campaignConfig.name, namePrefix]);

  const editingCampaignName = useMemo(
    () => existingCampaigns.find((c) => c.id === editingCampaignId)?.name?.trim().toLowerCase() || null,
    [existingCampaigns, editingCampaignId],
  );

  const nameConflict = useMemo(
    () => Boolean(
      fullCampaignName &&
      existingCampaignNames.has(fullCampaignName.toLowerCase()) &&
      fullCampaignName.toLowerCase() !== editingCampaignName
    ),
    [existingCampaignNames, fullCampaignName, editingCampaignName],
  );

  const inferredUserinterface = useMemo(() => {
    const values = (campaignConfig.script_configurations || [])
      .map((script) => executableMetaMap[script.script_name]?.userinterface)
      .filter(Boolean) as string[];
    const uniqueValues = Array.from(new Set(values));
    return uniqueValues.length === 1 ? uniqueValues[0] : '';
  }, [campaignConfig.script_configurations, executableMetaMap]);

  const compatibilityFlags = useMemo(() => {
    const flags = new Set<string>();

    (campaignConfig.script_configurations || []).forEach((script) => {
      if (script.script_type === 'testcase' || script.testcase_id) {
        flags.add('Device');
        flags.add('All OS');
        flags.add('All models');
        return;
      }

      const meta = executableMetaMap[script.script_name];
      const rules = meta?.target_rules;
      if (!rules) return;

      flags.add(rules.target_type === 'host' ? 'Host' : 'Device');
      if (rules.host_os === 'all' || !rules.host_os) {
        flags.add('All OS');
      } else {
        flags.add(rules.host_os);
      }
      if (rules.device_model === 'all' || !rules.device_model) {
        flags.add('All models');
      } else {
        flags.add(rules.device_model);
      }
    });

    if (inferredUserinterface) {
      flags.add(`UI: ${inferredUserinterface}`);
    }

    return Array.from(flags);
  }, [campaignConfig.script_configurations, executableMetaMap, inferredUserinterface]);

  const selectedExecutableItems = useMemo<ExecutableItem[]>(() => (
    (campaignConfig.script_configurations || []).map((script) => {
      const executableId = script.testcase_id || script.script_name;
      const mappedItem = executableMetaMap[executableId] || executableMetaMap[script.script_name];

      if (mappedItem) {
        return mappedItem;
      }

      return {
        id: executableId,
        name: script.script_name,
        type: script.testcase_id ? 'testcase' : 'script',
      } as ExecutableItem;
    })
  ), [campaignConfig.script_configurations, executableMetaMap]);

  const filteredExistingCampaigns = useMemo(() => {
    return existingCampaigns.filter((item) => item.source === existingCampaignFilter);
  }, [existingCampaignFilter, existingCampaigns]);

  const isDirty = useMemo(() => {
    if (!editingCampaignId) {
      return true;
    }
    if (!loadedCampaignSnapshot) {
      return false;
    }
    const currentSnapshot = JSON.stringify({
      name: fullCampaignName.trim(),
      description: campaignConfig.description || '',
      timeout_minutes: campaignConfig.execution_config?.timeout_minutes ?? 120,
      script_configurations: normalizeScriptConfigurationsForCompare(campaignConfig.script_configurations || []),
    });
    return currentSnapshot !== loadedCampaignSnapshot;
  }, [campaignConfig.description, campaignConfig.execution_config?.timeout_minutes, campaignConfig.script_configurations, editingCampaignId, fullCampaignName, loadedCampaignSnapshot]);

  const canSave = Boolean(fullCampaignName.trim()) && !nameConflict && (campaignConfig.script_configurations?.length || 0) > 0 && (!editingCampaignId || isDirty);

  const handleAddExecutable = (item: ExecutableItem) => {
    addScript(
      item.id,
      item.type,
      item.type === 'testcase' ? item.name : undefined,
    );
  };

  const handleSave = async () => {
    if (!canSave) {
      showError(nameConflict ? 'Campaign name already exists' : 'Campaign name and at least one script are required');
      return;
    }

    setSavingCampaign(true);
    try {
      const normalizedScriptConfigurations = (campaignConfig.script_configurations || []).map((script) => ({
        ...script,
        script_type: script.testcase_id ? 'testcase' : 'script',
      }));

      const payload = {
        name: fullCampaignName.trim(),
        description: campaignConfig.description || '',
        userinterface_name: inferredUserinterface,
        execution_config: {
          continue_on_failure: campaignConfig.execution_config?.continue_on_failure ?? true,
          timeout_minutes: campaignConfig.execution_config?.timeout_minutes ?? 120,
          parallel: campaignConfig.execution_config?.parallel ?? false,
        },
        callback_url: '',
        callback_on_script_complete: false,
        callback_on_campaign_complete: false,
        script_configurations: normalizedScriptConfigurations,
      };

      let response: any;
      if (editingCampaignId) {
        response = await api.put<any>(buildServerUrl(`/server/campaigns/updateCampaign/${editingCampaignId}`), payload);
      } else {
        response = await api.post<any>(buildServerUrl('/server/campaigns/createCampaign'), payload);
      }

      if (!response?.success || !response?.campaign) {
        throw new Error(response?.error || 'Failed to save campaign');
      }

      showSuccess(`Campaign "${fullCampaignName.trim()}" ${editingCampaignId ? 'updated' : 'saved'}`);
      invalidateCampaignExecutableListCache();
      setEditingCampaignId(null);
      setLoadedCampaignSnapshot(null);
      setNamePrefix('');
      resetCampaignConfig();
      await loadExistingCampaigns();
    } catch (saveError) {
      showError(saveError instanceof Error ? saveError.message : 'Failed to save campaign');
    } finally {
      setSavingCampaign(false);
    }
  };

  return (
    <Box sx={{ p: isMobile ? 0.25 : isTablet ? 0.75 : 1 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: isCompact ? 'flex-start' : 'center', mb: 2, gap: 1, flexDirection: isCompact ? 'column' : 'row' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="h4">Build Campaign</Typography>
          {editingCampaignId ? (
            <Chip size="small" label="Editing" color="warning" icon={<EditIcon />} />
          ) : null}
        </Box>
        {editingCampaignId ? (
          <Stack direction="row" spacing={1}>
            <Button size="small" variant="outlined" onClick={loadCampaignVersions}>
              Versions
            </Button>
            <Button
              size="small"
              variant="outlined"
              color="error"
              startIcon={<DeleteIcon />}
              onClick={handleDeleteCampaign}
              disabled={deletingCampaign}
            >
              {deletingCampaign ? 'Deleting...' : 'Delete'}
            </Button>
            <Button size="small" startIcon={<AddIcon />} onClick={handleNewCampaign} variant="outlined">
              New
            </Button>
          </Stack>
        ) : null}
      </Box>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      ) : null}

      <Grid container spacing={2}>
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
                <Box sx={{ display: 'flex', gap: 1, flexDirection: isCompact ? 'column' : 'row', alignItems: isCompact ? 'stretch' : 'flex-start' }}>
                  <TextField
                    size="small"
                    label="Prefix"
                    placeholder="Optional"
                    value={namePrefix}
                    onChange={(event) => setNamePrefix(event.target.value)}
                    sx={{ width: isCompact ? '100%' : 180 }}
                  />
                  <TextField
                    size="small"
                    label="Campaign Name"
                    value={campaignConfig.name || ''}
                    onChange={(event) => updateCampaignConfig({ name: event.target.value })}
                    sx={{ flex: isCompact ? undefined : '0 1 34%' }}
                    error={nameConflict}
                    helperText={nameConflict ? 'A DB campaign with this name already exists' : undefined}
                  />
                  <TextField
                    size="small"
                    label="Description"
                    placeholder="Optional"
                    value={campaignConfig.description || ''}
                    onChange={(event) => updateCampaignConfig({ description: event.target.value })}
                    sx={{ flex: isCompact ? undefined : '1 1 46%', minWidth: 0 }}
                  />
                  <TextField
                    size="small"
                    label="Timeout (min)"
                    type="number"
                    value={campaignConfig.execution_config?.timeout_minutes ?? 120}
                    onChange={(event) => {
                      const rawValue = Number(event.target.value);
                      updateCampaignConfig({
                        execution_config: {
                          continue_on_failure: campaignConfig.execution_config?.continue_on_failure ?? true,
                          timeout_minutes: Number.isFinite(rawValue) && rawValue > 0 ? rawValue : 120,
                          parallel: campaignConfig.execution_config?.parallel ?? false,
                        },
                      });
                    }}
                    inputProps={{ min: 1, step: 1 }}
                    sx={{ width: isCompact ? '100%' : 160, flexShrink: 0 }}
                  />
                </Box>

                <Box sx={{ p: 1.25, bgcolor: 'action.hover', borderRadius: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <UnifiedExecutableSelector
                    value={null}
                    onChange={() => {}}
                    selectedItems={selectedExecutableItems}
                    onItemClick={(item) => {
                      handleAddExecutable(item);
                    }}
                    onSelectAllVisible={(items) => items.forEach((item) => handleAddExecutable(item))}
                    utilityLabel={`${campaignConfig.script_configurations?.length || 0} items`}
                    placeholder="Search by name..."
                    filters={{ folders: true, tags: true, search: true }}
                    itemFilter={(item) => {
                      if (item.folder === 'test_campaign') {
                        return false;
                      }
                      return selectorTypeFilter ? item.type === selectorTypeFilter : true;
                    }}
                    collapseIcon={!isCompact ? (
                      <ExecutableTypeToggle
                        value={selectorTypeFilter}
                        onChange={setSelectorTypeFilter}
                        options={[
                          { id: 'script', label: 'S', color: 'primary' },
                          { id: 'testcase', label: 'TC', color: 'secondary' },
                        ]}
                      />
                    ) : undefined}
                  />
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                    <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', alignItems: 'center', minWidth: 0, flex: 1 }}>
                      {compatibilityFlags.map((flag) => (
                        <Chip key={flag} size="small" label={flag} />
                      ))}
                    </Box>
                  </Box>
                </Box>

                <ScriptSequenceBuilder
                  scripts={campaignConfig.script_configurations || []}
                  availableScripts={[]}
                  aiTestCasesInfo={aiTestCasesInfo}
                  scriptAnalysisCache={scriptAnalysisCache}
                  userinterfaceName={inferredUserinterface}
                  onAddScript={addScript}
                  onRemoveScript={removeScript}
                  onMoveScript={reorderScripts}
                  onUpdateScript={updateScriptConfiguration}
                  onLoadScriptAnalysis={loadScriptAnalysis}
                  hideAddButton
                  matchRunTestsStyle
                />

                <Box sx={{ display: 'flex', alignItems: isCompact ? 'stretch' : 'center', justifyContent: 'space-between', gap: 1, flexDirection: isCompact ? 'column' : 'row' }}>
                  <Box sx={{ display: 'flex', gap: 1, width: isCompact ? '100%' : 'auto' }}>
                    <Button
                      variant="contained"
                      startIcon={<SaveIcon />}
                      onClick={handleSave}
                      disabled={!canSave || savingCampaign}
                      fullWidth={isCompact}
                    >
                      {savingCampaign ? 'Saving...' : editingCampaignId ? 'Update' : 'Save'}
                    </Button>
                  </Box>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1, gap: 1, flexDirection: isCompact ? 'column' : 'row' }}>
                <Typography variant="subtitle1">Existing Campaigns</Typography>
                <ExecutableTypeToggle
                  value={existingCampaignFilter}
                  onChange={(value) => setExistingCampaignFilter(value as 'db' | 'file')}
                  options={[
                    { id: 'file', label: 'S', color: 'primary' },
                    { id: 'db', label: 'TP', color: 'secondary' },
                  ]}
                />
              </Box>

              {filteredExistingCampaigns.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  No campaigns found.
                </Typography>
              ) : (
                <Stack spacing={0.5} sx={{ maxHeight: 520, overflow: 'auto' }}>
                  {filteredExistingCampaigns.map((item) => {
                    const badge = getCampaignBadge(item.source);

                    return (
                      <Paper
                        key={`${item.source}-${item.id}`}
                        variant="outlined"
                        sx={{
                          px: 1,
                          py: 0.75,
                          borderColor: editingCampaignId === item.id ? 'warning.main' : undefined,
                        }}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, width: '100%', minWidth: 0 }}>
                          <Chip
                            size="small"
                            label={badge.label}
                            color={badge.color}
                            sx={{ height: '16px', fontSize: '0.6rem', minWidth: '24px' }}
                          />
                          <Typography
                            variant="body2"
                            sx={{
                              fontWeight: 600,
                              fontSize: '0.82rem',
                              flex: 1,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {item.name}
                          </Typography>
                          {item.description ? (
                            <Typography
                              variant="caption"
                              color="text.secondary"
                              sx={{
                                maxWidth: isCompact ? 80 : 180,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {item.description}
                            </Typography>
                          ) : null}
                          {item.source === 'db' ? (
                            <Button
                              size="small"
                              variant={editingCampaignId === item.id ? 'contained' : 'outlined'}
                              color="warning"
                              onClick={() => loadCampaignForEditing(item)}
                              disabled={loadingCampaign === item.id}
                              sx={{ py: 0, px: 0.75, minWidth: 48, fontSize: '0.7rem', flexShrink: 0 }}
                            >
                              {loadingCampaign === item.id ? '...' : editingCampaignId === item.id ? 'Editing' : 'Load'}
                            </Button>
                          ) : null}
                        </Box>
                      </Paper>
                    );
                  })}
                </Stack>
              )}
            </CardContent>
          </Card>
      </Grid>
    </Grid>

      <VersionHistoryDialog
        open={versionDialogOpen}
        onClose={() => setVersionDialogOpen(false)}
        title="Campaign Versions"
        rows={versionRows}
        loading={loadingVersions}
        currentVersion={versionRows[0]?.version_number ?? null}
        restoringVersion={restoringVersion}
        emptyMessage="Save the campaign to create the first version."
        onRestore={handleRestoreCampaignVersion}
      />
    </Box>
  );
};

export default BuildCampaigns;
