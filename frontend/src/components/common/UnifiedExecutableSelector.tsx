import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Box, Chip, Typography, CircularProgress, Paper,
  List, ListItem, ListItemButton,
} from '@mui/material';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { getCachedExecutableList } from '../../utils/executionListCache';
import { SelectorFilterBar } from './SelectorFilterBar';
import { useIdentityMap } from '../../hooks/useIdentityMap';

export interface ExecutableItem {
  type: 'script' | 'testcase';
  id: string;
  name: string;
  description?: string;
  tags?: string[];
  userinterface?: string;
  folder?: string;
  target_rules?: {
    target_type?: 'all' | 'host' | 'device';
    host_os?: 'all' | 'linux' | 'windows' | 'mac';
    device_model?: string;
  };
  badgeLabel?: string;
  badgeColor?: 'primary' | 'secondary' | 'success';
  // DB-stored Python (Virtual Scripts). Same execution path as a disk script,
  // but the run must carry virtual_script_id (the host materializes the source).
  is_virtual?: boolean;
  virtual_script_id?: string;
  // Lifecycle: per-environment row ids (dev always present; test/prod created on
  // promote) so a run resolves the right version from the environment selector.
  virtual_script_env_ids?: { dev: string | null; test: string | null; prod: string | null };
  prod_version?: number | null;
}

export interface UnifiedExecutableSelectorProps {
  value: ExecutableItem | null;
  onChange: (item: ExecutableItem) => void;
  onItemClick?: (item: ExecutableItem, event: React.MouseEvent<HTMLDivElement>) => void;
  selectedItems?: ExecutableItem[];
  label?: string;
  placeholder?: string;
  filters?: {
    search?: boolean;
    folders?: boolean;
    tags?: boolean;
  };
  allowedTypes?: ('script' | 'testcase')[];
  collapseIcon?: React.ReactNode;
  /** Rendered above the filter bar. Where a control goes when the bar is too narrow
   *  to hold it beside the search/folder/tags fields. */
  topContent?: React.ReactNode;
  compatibilityFilter?: (item: ExecutableItem) => boolean;
  onSelectAllVisible?: (items: ExecutableItem[]) => void;
  onUnselectAllVisible?: (items: ExecutableItem[]) => void;
  utilityLabel?: string;
  maxListHeight?: number | string;
  dataKey?: string;
  items?: ExecutableItem[];
  loading?: boolean;
  error?: string | null;
  folderOptions?: string[];
  tagOptions?: Array<{ name: string; color: string }>;
  emptyStateText?: string;
  itemFilter?: (item: ExecutableItem) => boolean;
  disableInternalScroll?: boolean;
}

export const UnifiedExecutableSelector: React.FC<UnifiedExecutableSelectorProps> = ({
  value,
  onChange,
  selectedItems = [],
  placeholder = 'Search by name...',
  filters = { folders: true, tags: true, search: true },
  allowedTypes,
  collapseIcon,
  topContent,
  compatibilityFilter,
  onItemClick,
  onSelectAllVisible,
  onUnselectAllVisible,
  utilityLabel,
  maxListHeight = 200,
  dataKey,
  items,
  loading: externalLoading,
  error: externalError,
  folderOptions,
  tagOptions,
  emptyStateText = 'No executables found',
  itemFilter,
  disableInternalScroll = false,
}) => {
  const { resolveScript } = useIdentityMap();
  const [internalLoading, setInternalLoading] = useState(true);
  const [internalError, setInternalError] = useState<string | null>(null);
  const [allItems, setAllItems] = useState<ExecutableItem[]>([]);
  const [allFolderNames, setAllFolderNames] = useState<string[]>([]);
  const [allTags, setAllTags] = useState<Array<{ name: string; color: string }>>([]);

  // Filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<string | null>('All');

  const normalizedFolderOptions = useMemo(
    () => allFolderNames.filter((folderName) => folderName !== 'Root' && folderName !== '(Root)'),
    [allFolderNames],
  );

  const resolvedItems = items ?? allItems;
  const resolvedFolderOptions = folderOptions ?? normalizedFolderOptions;
  const resolvedTagOptions = tagOptions ?? allTags;
  const loading = externalLoading ?? (items ? false : internalLoading);
  const error = externalError ?? (items ? null : internalError);

  useEffect(() => {
    setSearchQuery('');
    setSelectedTags([]);
    setSelectedFolder('All');
  }, [dataKey]);

  // Load executables once per component instance. Parent-driven prop changes
  // (e.g. `items` flipping between undefined and [] as the user toggles tabs)
  // previously re-triggered the load — the inflight cache dedup meant the
  // network request was shared, but each call still walked the logging path
  // and scheduled another setState round. Ref-guarded so mount-time is the
  // only trigger, regardless of how the `items` prop evolves later.
  const hasLoadedRef = useRef(false);
  useEffect(() => {
    if (items) return;
    if (hasLoadedRef.current) return;
    hasLoadedRef.current = true;
    console.log('[@UnifiedExecutableSelector] Component mounted, loading executables...');
    loadExecutables();
  }, [items]);

  const loadExecutables = async () => {
    try {
      console.log('[@UnifiedExecutableSelector] Loading executables from API...');
      setInternalLoading(true);
      setInternalError(null);

      const data = await getCachedExecutableList(buildServerUrl('/server/executable/list'));

      console.log('[@UnifiedExecutableSelector] API response:', {
        success: data.success,
        foldersCount: data.folders?.length,
      });

      if (data.success) {
        // Flatten all items from all folders
        const items: ExecutableItem[] = [];
        data.folders.forEach((folder: any) => {
          folder.items.forEach((item: any) => {
            items.push({
              ...item,
              folder: folder.name, // Add folder info to each item
            });
          });
        });

        setAllItems(items);
        setAllFolderNames(data.all_folders || []);
        setAllTags(data.all_tags || []);
        console.log('[@UnifiedExecutableSelector] ✅ Loaded', items.length, 'items');
      } else {
        throw new Error(data.error || 'Failed to load executables');
      }
    } catch (err) {
      console.error('[@UnifiedExecutableSelector] ❌ Error loading executables:', err);
      setInternalError(err instanceof Error ? err.message : 'Failed to load executables');
    } finally {
      setInternalLoading(false);
      console.log('[@UnifiedExecutableSelector] Loading complete');
    }
  };

  // Filter items
  const filteredItems = useMemo(() => {
    let items = [...resolvedItems];

    // Apply type filter
    if (allowedTypes && allowedTypes.length > 0) {
      items = items.filter(item => allowedTypes.includes(item.type));
    }

    if (compatibilityFilter) {
      items = items.filter((item) => compatibilityFilter(item));
    }

    if (itemFilter) {
      items = items.filter((item) => itemFilter(item));
    }

    // Apply folder filter
    if (selectedFolder && selectedFolder !== 'All') {
      items = items.filter((item: any) => item.folder === selectedFolder);
    }

    // Apply search filter (matches name, description, identity display_name, and prefix)
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      items = items.filter(item => {
        if (item.name.toLowerCase().includes(query)) return true;
        if (item.description?.toLowerCase().includes(query)) return true;
        const id = resolveScript(item.id);
        if (id.display_name?.toLowerCase().includes(query)) return true;
        if (id.prefix?.toLowerCase().includes(query)) return true;
        return false;
      });
    }

    // Apply tag filter
    if (selectedTags.length > 0) {
      items = items.filter(item =>
        item.tags && item.tags.some(tag => selectedTags.includes(tag))
      );
    }

    return items;
  }, [resolvedItems, searchQuery, selectedTags, selectedFolder, allowedTypes, compatibilityFilter, itemFilter, resolveScript]);

  const selectedVisibleCount = useMemo(() => {
    if (selectedItems.length === 0 || filteredItems.length === 0) {
      return 0;
    }
    const selectedIds = new Set(selectedItems.map((item) => item.id));
    return filteredItems.filter((item) => selectedIds.has(item.id)).length;
  }, [filteredItems, selectedItems]);

  const selectedItemIds = useMemo(
    () => new Set(selectedItems.map((item) => item.id)),
    [selectedItems],
  );

  const selectedItemCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    selectedItems.forEach((item) => {
      counts[item.id] = (counts[item.id] || 0) + 1;
    });
    return counts;
  }, [selectedItems]);

  const toggleFolderFilter = (folderName?: string) => {
    if (!folderName || folderName === 'All') {
      return;
    }
    setSelectedFolder((prev) => (prev === folderName ? 'All' : folderName));
  };

  const toggleTagFilter = (tagName: string) => {
    setSelectedTags((prev) => (
      prev.includes(tagName)
        ? prev.filter((existing) => existing !== tagName)
        : [...prev, tagName]
    ));
  };

  // Handle item selection
  const handleItemSelect = (item: ExecutableItem, event?: React.MouseEvent<HTMLDivElement>) => {
    console.log('[@UnifiedExecutableSelector] 🎯 Item selected:', item.name);
    if (onItemClick && event) {
      onItemClick(item, event);
      return;
    }
    onChange(item);
  };

  return (
    <Box>
      {topContent ? <Box sx={{ mb: 0.75 }}>{topContent}</Box> : null}
      <SelectorFilterBar
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        selectedFolder={selectedFolder}
        onSelectedFolderChange={setSelectedFolder}
        folderOptions={resolvedFolderOptions}
        selectedTags={selectedTags}
        onSelectedTagsChange={setSelectedTags}
        tagOptions={resolvedTagOptions}
        searchPlaceholder={placeholder}
        showSearch={Boolean(filters.search)}
        showFolders={Boolean(filters.folders)}
        showTags={Boolean(filters.tags)}
        rightContent={collapseIcon}
      />

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.75, px: 0.25, flexWrap: 'wrap' }}>
        <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500 }}>
          {utilityLabel || `${filteredItems.length} item${filteredItems.length !== 1 ? 's' : ''}`}
        </Typography>
        <Typography
          variant="caption"
          color={onSelectAllVisible && filteredItems.length > 0 ? 'primary.main' : 'text.disabled'}
          sx={{ cursor: onSelectAllVisible && filteredItems.length > 0 ? 'pointer' : 'default' }}
          onClick={onSelectAllVisible && filteredItems.length > 0 ? () => onSelectAllVisible(filteredItems) : undefined}
        >
          select all
        </Typography>
        <Typography variant="caption" color="text.disabled">-</Typography>
        <Typography
          variant="caption"
          color={onUnselectAllVisible && selectedVisibleCount > 0 ? 'primary.main' : 'text.disabled'}
          sx={{ cursor: onUnselectAllVisible && selectedVisibleCount > 0 ? 'pointer' : 'default' }}
          onClick={onUnselectAllVisible && selectedVisibleCount > 0 ? () => onUnselectAllVisible(filteredItems) : undefined}
        >
          unselect all
        </Typography>
      </Box>

      {/* Flat Item List - Full width */}
      <Box>
          <Paper
            variant="outlined"
            sx={{
              maxHeight: disableInternalScroll ? 'none' : maxListHeight,
              minHeight: disableInternalScroll ? 'auto' : maxListHeight,
              overflow: disableInternalScroll ? 'visible' : 'auto',
            }}
          >
            {loading ? (
              <Box
                sx={{
                  height: disableInternalScroll ? 'auto' : '100%',
                  minHeight: disableInternalScroll ? 120 : maxListHeight,
                  display: 'flex',
                  justifyContent: 'center',
                  alignItems: 'center',
                }}
              >
                <CircularProgress size={24} />
              </Box>
            ) : error ? (
              <Box sx={{ p: 2 }}>
                <Typography color="error">{error}</Typography>
              </Box>
            ) : filteredItems.length === 0 ? (
              <Box sx={{ p: 2, textAlign: 'center' }}>
                <Typography variant="body2" color="text.secondary">
                  {emptyStateText}
                </Typography>
              </Box>
            ) : (
              <List dense disablePadding>
                {filteredItems.map(item => {
                  const isFocused = value?.id === item.id;
                  const isSelected = selectedItemIds.has(item.id);
                  const isHighlighted = isFocused || isSelected;
                  const badgeLabel = item.badgeLabel || (item.is_virtual ? 'VS' : item.type === 'script' ? 'S' : 'TC');
                  const badgeColor = item.badgeColor || (item.is_virtual ? 'success' : item.type === 'script' ? 'primary' : 'secondary');
                  const identity = resolveScript(item.id);
                  const folderLabel = item.folder && item.folder !== 'All' ? item.folder : '';
                  return (
                    <ListItem
                      key={item.id}
                      disablePadding
                      sx={{
                        bgcolor: isHighlighted ? 'action.selected' : 'transparent',
                        '&:hover': { bgcolor: isHighlighted ? 'action.selected' : 'action.hover' },
                        borderLeft: isHighlighted ? '3px solid' : 'none',
                        borderColor: 'primary.light'
                      }}
                    >
                      <ListItemButton
                        onClick={(event) => handleItemSelect(item, event)}
                        selected={isHighlighted}
                        title={item.description && !item.description.startsWith('Execute ') ? item.description : undefined}
                        sx={{
                          py: 0.25,
                          pl: isHighlighted ? 0.75 : 1,
                          pr: 1,
                          minHeight: 28,
                          color: 'inherit'
                        }}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', minWidth: 0 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flex: '1 1 48%', minWidth: 0 }}>
                            <Chip
                              label={badgeLabel}
                              size="small"
                              color={badgeColor}
                              sx={{
                                height: '16px',
                                fontSize: '0.6rem',
                                minWidth: '24px',
                                '.MuiChip-label': { px: 0.5 },
                                opacity: isHighlighted ? 0.95 : 1,
                              }}
                            />
                            {identity.prefix && (
                              <Chip
                                label={identity.prefix}
                                size="small"
                                sx={{
                                  height: 16,
                                  fontSize: '0.6rem',
                                  fontFamily: 'monospace',
                                  flexShrink: 0,
                                  '.MuiChip-label': { px: 0.5 },
                                }}
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
                                fontWeight: isHighlighted ? 600 : 'normal'
                              }}
                            >
                              {identity.display_name || item.name}
                            </Typography>
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
                                  toggleFolderFilter(folderLabel);
                                }}
                              >
                                {folderLabel}
                              </Typography>
                            ) : null}
                          </Box>

                          <Box sx={{ display: 'flex', gap: 0.25, flex: '0 1 28%', minWidth: 0, justifyContent: 'flex-end', flexWrap: 'nowrap', overflow: 'hidden', alignItems: 'center' }}>
                            {selectedItemCounts[item.id] >= 2 ? (
                              <Chip
                                label={`×${selectedItemCounts[item.id]}`}
                                size="small"
                                color="primary"
                                sx={{
                                  height: '16px',
                                  fontSize: '0.6rem',
                                  minWidth: '24px',
                                  flexShrink: 0,
                                  '.MuiChip-label': { px: 0.5 },
                                }}
                              />
                            ) : null}
                            {item.tags && item.tags.length > 0 ? item.tags.slice(0, 2).map(tagName => {
                              const tag = resolvedTagOptions.find(t => t.name === tagName);
                              const tagSelected = selectedTags.includes(tagName);
                              return (
                                <Chip
                                  key={tagName}
                                  label={tagName}
                                  size="small"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    toggleTagFilter(tagName);
                                  }}
                                  title={item.tags && item.tags.length > 2 ? item.tags.join(', ') : undefined}
                                  sx={{
                                    height: '14px',
                                    fontSize: '0.55rem',
                                    backgroundColor: tag?.color || '#9e9e9e',
                                    color: 'white',
                                    cursor: 'pointer',
                                    flexShrink: 0,
                                    opacity: tagSelected ? 1 : (isHighlighted ? 0.9 : 1),
                                    outline: tagSelected ? '1px solid rgba(255,255,255,0.9)' : 'none',
                                  }}
                                />
                              );
                            }) : null}
                          </Box>
                        </Box>
                      </ListItemButton>
                    </ListItem>
                  );
                })}
              </List>
            )}
          </Paper>
      </Box>

      {/* Summary - Compact */}
      <Box sx={{ mt: 0.5, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
          {filteredItems.length} items
          {selectedFolder && selectedFolder !== 'All' && ` in ${selectedFolder}`}
          {selectedTags.length > 0 && ` • ${selectedTags.join(', ')}`}
          {searchQuery && ` • "${searchQuery}"`}
        </Typography>
      </Box>
    </Box>
  );
};
