import React, { useState, useEffect, useMemo, forwardRef, useImperativeHandle } from 'react';
import {
  Box, Chip, Typography, CircularProgress, Paper,
  List, ListItem, ListItemButton, IconButton,
} from '@mui/material';
import {
  Delete as DeleteIcon,
  Campaign as CampaignIcon,
  Visibility as VisibilityIcon,
  VisibilityOff as VisibilityOffIcon,
} from '@mui/icons-material';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { useResponsiveMode } from '../../hooks/useResponsiveMode';
import { ExecutableTypeToggle } from '../common/ExecutableTypeToggle';
import { SelectorFilterBar } from '../common/SelectorFilterBar';
import { getCachedCampaignExecutableList, invalidateCampaignExecutableListCache } from '../../utils/executionListCache';
import { getCampaignBadge } from '../../config/constants';
import type { CampaignExecutableSource } from '../../config/constants';
import { useIdentityMap } from '../../hooks/useIdentityMap';

export interface CampaignItem {
  id: string;
  source: CampaignExecutableSource;
  campaign_id?: string;
  campaign_name: string;
  description?: string;
  environment?: 'dev' | 'test' | 'prod';
  current_version?: number;
  execution_count?: number;
  last_execution_success?: boolean;
  folder?: string;
  tags?: string[];
  created_at?: string;
  updated_at?: string;
}

export interface CampaignSelectorProps {
  onLoad: (campaignId: string) => void;
  onDelete?: (campaignId: string, campaignName: string) => Promise<void>;
  selectedCampaignId?: string | null;
  showHidden?: boolean;
}

export const CampaignSelector = forwardRef<{ refresh: () => void }, CampaignSelectorProps>(({
  onLoad,
  onDelete,
  selectedCampaignId,
  showHidden = false,
}, ref) => {
  const { isMobile, isTablet } = useResponsiveMode();
  const { resolveCampaign } = useIdentityMap();
  const isCompact = isMobile || isTablet;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [allCampaigns, setAllCampaigns] = useState<CampaignItem[]>([]);
  const [allFolderNames, setAllFolderNames] = useState<string[]>([]);
  const [allTags, setAllTags] = useState<Array<{ name: string; color: string }>>([]);
  const [hiddenKeys, setHiddenKeys] = useState<Set<string>>(new Set());

  // Filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<string>('All');
  const [selectedType, setSelectedType] = useState<string | null>(isCompact ? null : 'file');

  // Ref to prevent duplicate API calls in React Strict Mode
  const isLoadingRef = React.useRef(false);

  // Expose refresh method to parent via ref
  useImperativeHandle(ref, () => ({
    refresh: loadAll,
  }));

  // Load campaigns on mount
  useEffect(() => {
    // Prevent duplicate calls in React Strict Mode
    if (isLoadingRef.current) {
      console.log('[@CampaignSelector] Load already in progress, skipping duplicate call');
      return;
    }

    console.log('[@CampaignSelector] Loading campaigns...');
    loadAll();
  }, []);

  useEffect(() => {
    setSelectedType(isCompact ? null : 'file');
  }, [isCompact]);

  const loadAll = async () => {
    // Prevent concurrent calls
    if (isLoadingRef.current) {
      return;
    }

    isLoadingRef.current = true;

    try {
      setLoading(true);
      setError(null);

      const campaignsData = await getCachedCampaignExecutableList(
        buildServerUrl('/server/campaigns/listExecutables?include_hidden=true'),
      );

      const visibilityResponse = await fetch(
        buildServerUrl('/server/library-visibility/list?entity_type=campaign')
      );
      const visibilityData = await visibilityResponse.json();

      // Load folders and tags
      const foldersTagsResponse = await fetch(buildServerUrl('/server/testcase/folders-tags'));
      const foldersTagsData = await foldersTagsResponse.json();

      const dbCampaigns: CampaignItem[] = (campaignsData.campaigns || []).map((campaign: any) => ({
        ...campaign,
        id: campaign.id || campaign.campaign_id,
        source: 'db',
        campaign_name: campaign.name || campaign.campaign_name || campaign.campaign_id || 'Campaign',
        folder: campaign.folder || 'Root',
      }));

      const fileCampaigns: CampaignItem[] = (campaignsData.scripts || []).map((campaign: any) => ({
        id: campaign.id,
        source: 'file',
        campaign_name: campaign.name || campaign.script_name || campaign.id,
        description: campaign.description || '',
        folder: 'Root',
        tags: [],
      }));

      const campaigns: CampaignItem[] = [...fileCampaigns, ...dbCampaigns];

      if (campaignsData.success) {
        setAllCampaigns(campaigns);
        console.log('[@CampaignSelector] ✅ Loaded', campaigns.length, 'campaigns');
      } else {
        throw new Error(campaignsData.error || 'Failed to load campaigns');
      }

      if (foldersTagsData.success) {
        setAllFolderNames(foldersTagsData.folders?.map((f: any) => f.name) || []);
        setAllTags(foldersTagsData.tags || []);
      }

      if (visibilityData.success) {
        setHiddenKeys(new Set<string>(
          (visibilityData.items || [])
            .filter((item: any) => item.is_visible === false)
            .map((item: any) => item.entity_key)
        ));
      } else {
        setHiddenKeys(new Set());
      }
    } catch (err) {
      console.error('[@CampaignSelector] ❌ Error loading:', err);
      setError(err instanceof Error ? err.message : 'Failed to load campaigns');
    } finally {
      setLoading(false);
      isLoadingRef.current = false;
    }
  };

  // Filter campaigns
  const filteredCampaigns = useMemo(() => {
    let campaigns = [...allCampaigns];

    if (!showHidden) {
      campaigns = campaigns.filter((campaign) => !hiddenKeys.has(campaign.id));
    }

    if (selectedType) {
      campaigns = campaigns.filter((campaign) => campaign.source === selectedType);
    }

    // Apply folder filter
    if (selectedFolder && selectedFolder !== 'All') {
      campaigns = campaigns.filter(campaign => campaign.folder === selectedFolder);
    }

    // Apply search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      campaigns = campaigns.filter(campaign =>
        campaign.campaign_name.toLowerCase().includes(query) ||
        campaign.description?.toLowerCase().includes(query)
      );
    }

    // Apply tag filter
    if (selectedTags.length > 0) {
      campaigns = campaigns.filter(campaign =>
        campaign.tags && campaign.tags.some(tag => selectedTags.includes(tag))
      );
    }

    return campaigns;
  }, [allCampaigns, hiddenKeys, searchQuery, selectedTags, selectedFolder, selectedType, showHidden]);

  // Handle campaign selection
  const handleCampaignSelect = (campaign: CampaignItem) => {
    if (!campaign.campaign_id) {
      console.log('[@CampaignSelector] ℹ️ File campaign listed for filtering only:', campaign.id);
      return;
    }
    console.log('[@CampaignSelector] 🎯 Campaign selected:', campaign.campaign_id);
    onLoad(campaign.campaign_id);
  };

  // Handle delete click
  const handleDeleteClick = (e: React.MouseEvent, campaign: CampaignItem) => {
    e.stopPropagation();

    const campaignId = campaign.campaign_id;
    if (!onDelete || !campaignId) {
      return;
    }

    // Call the parent delete handler (opens confirmation dialog)
    onDelete(campaignId, campaign.campaign_name);
  };

  const toggleVisibility = async (e: React.MouseEvent, campaign: CampaignItem) => {
    e.stopPropagation();
    const entityKey = campaign.id;
    const isHidden = hiddenKeys.has(entityKey);
    const endpoint = isHidden ? '/server/library-visibility/show' : '/server/library-visibility/hide';

    // Optimistic update — flip the key immediately, no full reload
    setHiddenKeys((prev) => {
      const next = new Set(prev);
      if (isHidden) next.delete(entityKey);
      else next.add(entityKey);
      return next;
    });

    try {
      const response = await fetch(buildServerUrl(endpoint), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entity_type: 'campaign',
          entity_key: entityKey,
        }),
      });
      const result = await response.json();
      if (!result.success) {
        // Revert on failure
        setHiddenKeys((prev) => {
          const next = new Set(prev);
          if (isHidden) next.add(entityKey);
          else next.delete(entityKey);
          return next;
        });
        throw new Error(result.error || 'Failed to update visibility');
      }

      invalidateCampaignExecutableListCache();
    } catch (err) {
      console.error('[@CampaignSelector] ❌ Visibility update failed:', err);
      setError(err instanceof Error ? err.message : 'Failed to update visibility');
    }
  };

  // Render loading state
  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress size={24} />
      </Box>
    );
  }

  // Render error state
  if (error) {
    return (
      <Box sx={{ p: 2, bgcolor: 'error.light', borderRadius: 1 }}>
        <Typography color="error">{error}</Typography>
      </Box>
    );
  }

  return (
    <Box>
      <SelectorFilterBar
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        selectedFolder={selectedFolder}
        onSelectedFolderChange={(value) => setSelectedFolder(value || 'All')}
        folderOptions={allFolderNames}
        selectedTags={selectedTags}
        onSelectedTagsChange={setSelectedTags}
        tagOptions={allTags}
        rightContent={!isCompact ? (
          <ExecutableTypeToggle
            value={selectedType}
            onChange={setSelectedType}
            options={[
              { id: 'file', label: 'S', color: 'primary' },
              { id: 'db', label: 'TP', color: 'secondary' },
            ]}
          />
        ) : undefined}
      />

      {/* Campaign List - Compact format for single-line layout */}
      <Box>
        <Paper variant="outlined" sx={{ maxHeight: 400, overflow: 'auto' }}>
          {filteredCampaigns.length === 0 ? (
            <Box sx={{ p: 3, textAlign: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                {allCampaigns.length === 0
                  ? 'No campaigns found. Create one first!'
                  : 'No campaigns match your filters'
                }
              </Typography>
            </Box>
          ) : (
            <List dense disablePadding>
              {filteredCampaigns.map(campaign => {
                const campaignId = campaign.campaign_id || campaign.id;
                const isSelected = selectedCampaignId === campaign.campaign_id;
                const isHidden = hiddenKeys.has(campaign.id);
                const badge = getCampaignBadge(campaign.source);
                const folderLabel = campaign.folder && campaign.folder !== 'All' && campaign.folder !== 'Root' ? campaign.folder : '';

                return (
                  <ListItem
                    key={campaignId}
                    disablePadding
                    sx={{
                      borderBottom: 1,
                      borderColor: 'divider',
                      '&:last-child': { borderBottom: 0 },
                      bgcolor: isSelected ? 'action.selected' : 'transparent',
                      '&:hover': { bgcolor: isSelected ? 'action.selected' : 'action.hover' },
                      opacity: isHidden ? 0.58 : 1,
                      borderLeft: isSelected ? '3px solid' : 'none',
                      borderLeftColor: isSelected ? 'primary.light' : undefined,
                    }}
                  >
                    <ListItemButton
                      onClick={() => handleCampaignSelect(campaign)}
                      selected={isSelected}
                      sx={{
                        py: 0.25,
                        pl: isSelected ? 0.75 : 1,
                        pr: 1,
                        display: 'flex',
                        flexDirection: 'row',
                        alignItems: 'center',
                        gap: 1,
                        minHeight: 28,
                        color: 'inherit'
                      }}
                    >
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', minWidth: 0 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flex: '1 1 48%', minWidth: 0 }}>
                          <Chip
                            icon={campaign.source === 'db' ? <CampaignIcon /> : undefined}
                            label={badge.label}
                            size="small"
                            color={badge.color}
                            sx={{
                              height: '16px',
                              fontSize: '0.6rem',
                              minWidth: badge.label.length > 2 ? '30px' : '24px',
                              '.MuiChip-label': { px: 0.5 },
                              opacity: isSelected ? 0.95 : 1,
                            }}
                          />
                          {(() => {
                            const identity = resolveCampaign(campaign.campaign_name);
                            const label = identity.display_name ?? campaign.campaign_name;
                            return (
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0, overflow: 'hidden' }}>
                                {identity.prefix && (
                                  <Chip
                                    label={identity.prefix}
                                    size="small"
                                    sx={{ fontSize: '0.6rem', height: 16, flexShrink: 0, fontFamily: 'monospace', px: 0.25 }}
                                  />
                                )}
                                <Typography
                                  variant="body2"
                                  sx={{
                                    fontSize: '0.8rem',
                                    minWidth: 0,
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap',
                                    fontWeight: isSelected ? 600 : 'normal',
                                  }}
                                >
                                  {label}
                                </Typography>
                              </Box>
                            );
                          })()}
                        </Box>

                        <Box sx={{ flex: '0 1 24%', minWidth: 0 }}>
                          {folderLabel ? (
                            <Typography
                              variant="caption"
                              color={selectedFolder === folderLabel ? 'primary.main' : 'text.secondary'}
                              sx={{
                                display: 'block',
                                fontSize: '0.68rem',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                cursor: 'pointer',
                              }}
                              onClick={(event) => {
                                event.stopPropagation();
                                setSelectedFolder((prev) => (prev === folderLabel ? 'All' : folderLabel));
                              }}
                            >
                              {folderLabel}
                            </Typography>
                          ) : null}
                        </Box>

                        <Box sx={{ display: 'flex', gap: 0.25, flex: '0 1 28%', minWidth: 0, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                          {campaign.tags?.map((tagName) => {
                            const tag = allTags.find((candidate) => candidate.name === tagName);
                            const tagSelected = selectedTags.includes(tagName);
                            return (
                              <Chip
                                key={tagName}
                                label={tagName}
                                size="small"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setSelectedTags((prev) => (
                                    prev.includes(tagName)
                                      ? prev.filter((existing) => existing !== tagName)
                                      : [...prev, tagName]
                                  ));
                                }}
                                sx={{
                                  height: '14px',
                                  fontSize: '0.55rem',
                                  backgroundColor: tag?.color || '#9e9e9e',
                                  color: 'white',
                                  cursor: 'pointer',
                                  opacity: tagSelected ? 1 : (isSelected ? 0.9 : 1),
                                  outline: tagSelected ? '1px solid rgba(255,255,255,0.9)' : 'none',
                                }}
                              />
                            );
                          })}
                        </Box>

                        <IconButton
                          size="small"
                          onClick={(e) => toggleVisibility(e, campaign)}
                          sx={{
                            p: 0.5,
                            ml: 'auto',
                            flexShrink: 0,
                            color: isSelected ? 'primary.contrastText' : 'text.secondary',
                            '&:hover': {
                              bgcolor: isSelected ? 'rgba(255,255,255,0.2)' : 'action.hover'
                            },
                          }}
                        >
                          {isHidden ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                        </IconButton>

                        {/* Delete Button */}
                        {campaign.campaign_id && onDelete && (
                          <IconButton
                            size="small"
                            onClick={(e) => handleDeleteClick(e, campaign)}
                            sx={{
                              p: 0.5,
                              flexShrink: 0,
                              color: isSelected ? 'primary.contrastText' : 'error.main',
                              '&:hover': {
                                bgcolor: isSelected ? 'rgba(255,255,255,0.2)' : 'error.light'
                              },
                            }}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        )}
                      </Box>
                    </ListItemButton>
                  </ListItem>
                );
              })}
            </List>
          )}
        </Paper>
      </Box>

      {/* Summary Footer */}
      <Box sx={{ mt: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.75rem' }}>
          {filteredCampaigns.length} campaign{filteredCampaigns.length !== 1 ? 's' : ''}
          {selectedType && ` • ${selectedType === 'file' ? 'S' : 'TP'}`}
          {selectedFolder && selectedFolder !== 'All' && ` in ${selectedFolder}`}
          {selectedTags.length > 0 && ` • ${selectedTags.join(', ')}`}
          {searchQuery && ` • "${searchQuery}"`}
        </Typography>
        {(searchQuery || selectedTags.length > 0 || (selectedFolder && selectedFolder !== 'All') || selectedType) && (
          <Typography
            variant="caption"
            color="primary"
            sx={{ cursor: 'pointer', textDecoration: 'underline', fontSize: '0.75rem' }}
            onClick={() => {
              setSearchQuery('');
              setSelectedTags([]);
              setSelectedFolder('All');
              setSelectedType(isCompact ? null : 'file');
            }}
          >
            Clear filters
          </Typography>
        )}
      </Box>
    </Box>
  );
});
