import React, { useState, useEffect, useMemo, forwardRef, useImperativeHandle } from 'react';
import {
  Box, Chip, Typography, CircularProgress, Paper,
  List, ListItem, ListItemButton, IconButton, Tooltip, Alert,
} from '@mui/material';
import {
  Delete as DeleteIcon,
  PlayArrow as ScriptIcon,
  Visibility as VisibilityIcon,
  VisibilityOff as VisibilityOffIcon,
  CloudSync as CloudSyncIcon,
} from '@mui/icons-material';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { getCachedTestCaseList, invalidateTestCaseListCache } from '../../utils/testcaseCache';
import { invalidateExecutableListCache } from '../../utils/executionListCache';
import { api } from '../../utils/apiClient';
import { useResponsiveMode } from '../../hooks/useResponsiveMode';
import { useIdentityMap } from '../../hooks/useIdentityMap';
import { useToast } from '../../hooks/useToast';
import { ExecutableTypeToggle } from '../common/ExecutableTypeToggle';
import { LifecycleChips } from '../common/LifecycleChips';
import { isFeatureEnabled } from '../../config/features';
import { SelectorFilterBar } from '../common/SelectorFilterBar';
import { ScriptIdentityPopover } from './ScriptIdentityPopover';

export interface TestCaseItem {
  testcase_id: string;
  testcase_name: string;
  description?: string;
  userinterface_name?: string;
  environment?: 'dev' | 'test' | 'prod';
  current_version?: number;
  execution_count?: number;
  last_execution_success?: boolean;
  folder?: string;
  tags?: string[];
  graph_json?: {
    nodes?: any[];
  };
  created_at?: string;
  updated_at?: string;
  type: 'testcase'; // NEW: Type discriminator
}

// NEW: Script item interface
export interface ScriptItem {
  script_name: string;
  folder?: string;
  tags?: string[];
  type: 'script'; // NEW: Type discriminator
}

// A virtual script: Python source stored in the database, editable in-app with a
// dev/test/prod lifecycle. Optional feature (`features/virtual-scripts/`) — the rows are
// only fetched when it is enabled, so a build with DISABLED_FEATURES=virtual-scripts shows
// the same page minus the VS toggle.
export interface VirtualScriptItem {
  id: string;
  name: string;
  description?: string;
  /** Which env rows exist, from /server/virtual-script/list. */
  environments?: Partial<Record<'dev' | 'test' | 'prod', unknown>>;
  prod_version?: number | null;
  folder?: string;
  tags?: string[];
  created_at?: string;
  updated_at?: string;
  type: 'virtual';
}

// Unified item type
export type ExecutableItem = TestCaseItem | ScriptItem | VirtualScriptItem;

export interface TestCaseSelectorProps {
  onLoad: (testcaseId: string) => void;
  onDelete?: (testcaseId: string, testcaseName: string) => Promise<void>;
  selectedTestCaseId?: string | null;
  testCasesOnly?: boolean; // If true, only show test cases (no scripts)
  showHidden?: boolean;
}

export const TestCaseSelector = forwardRef<{ refresh: () => void }, TestCaseSelectorProps>(({
  onLoad,
  onDelete,
  selectedTestCaseId,
  testCasesOnly = false,
  showHidden = false,
}, ref) => {
  const { isMobile, isTablet } = useResponsiveMode();
  const { resolveScript, saveScriptIdentity, normalizeRef } = useIdentityMap();
  const { showSuccess, showError } = useToast();
  const isCompact = isMobile || isTablet;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [allItems, setAllItems] = useState<ExecutableItem[]>([]); // Changed to unified list
  const [allFolderNames, setAllFolderNames] = useState<string[]>([]);
  const [allTags, setAllTags] = useState<Array<{ name: string; color: string }>>([]);
  const [hiddenKeys, setHiddenKeys] = useState<Set<string>>(new Set());
  // Name of the disk script currently being converted to a virtual script (dev row).
  const [convertingScript, setConvertingScript] = useState<string | null>(null);
  // Prefix / display-name editor anchored to the clicked TC chip.
  const [identityTarget, setIdentityTarget] = useState<
    { anchorEl: HTMLElement; scriptRef: string } | null
  >(null);
  const [identitySaving, setIdentitySaving] = useState(false);
  const [identityWarning, setIdentityWarning] = useState<string | null>(null);

  // Filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<string>('All');
  // Evaluated once: the feature set is fixed at build time (vite `vpt-features` plugin).
  const virtualScriptsEnabled = isFeatureEnabled('virtual-scripts');

  const [selectedType, setSelectedType] = useState<string | null>(
    testCasesOnly ? 'testcase' : (isCompact ? null : 'script'),
  );

  // Ref to prevent duplicate API calls in React Strict Mode
  const isLoadingRef = React.useRef(false);

  // Expose refresh method to parent via ref
  useImperativeHandle(ref, () => ({
    refresh: loadAll,
  }));

  // Load test cases AND scripts on mount
  useEffect(() => {
    // Prevent duplicate calls in React Strict Mode
    if (isLoadingRef.current) {
      console.log('[@TestCaseSelector] Load already in progress, skipping duplicate call');
      return;
    }
    
    console.log('[@TestCaseSelector] Loading test cases and scripts...');
    loadAll();
  }, []);

  useEffect(() => {
    if (testCasesOnly) {
      setSelectedType('testcase');
      return;
    }
    setSelectedType(isCompact ? null : 'script');
  }, [isCompact, testCasesOnly]);

  const loadAll = async () => {
    // Prevent concurrent calls
    if (isLoadingRef.current) {
      return;
    }
    
    isLoadingRef.current = true;
    
    try {
      setLoading(true);
      setError(null);

      // Load test cases (with shared cache)
      const testCasesData = await getCachedTestCaseList(
        buildServerUrl('/server/testcase/list?include_hidden=true')
      );

      // Load scripts
      const scriptsResponse = await fetch(
        buildServerUrl('/server/script/list?include_hidden=true')
      );
      const scriptsData = await scriptsResponse.json();

      const visibilityResponse = await fetch(
        buildServerUrl('/server/library-visibility/list')
      );
      const visibilityData = await visibilityResponse.json();

      // Load folders and tags
      const foldersTagsResponse = await fetch(
        buildServerUrl('/server/testcase/folders-tags')
      );
      const foldersTagsData = await foldersTagsResponse.json();

      const testCases: TestCaseItem[] = (testCasesData.testcases || []).map((tc: any) => ({
        ...tc,
        type: 'testcase' as const,
      }));

      const scripts: ScriptItem[] = (scriptsData.scripts || [])
        .filter((script: string) => !script.startsWith('test_campaign/'))
        .map((script: string) => ({
          script_name: script,
          type: 'script' as const,
          folder: 'Root',
          tags: [],
        }));

      // Virtual scripts come from the optional feature. Fetched only when it is enabled,
      // and a failure here is non-fatal: the page still lists testcases and disk scripts.
      let virtualScripts: VirtualScriptItem[] = [];
      if (virtualScriptsEnabled && !testCasesOnly) {
        try {
          const vsResponse = await fetch(buildServerUrl('/server/virtual-script/list'));
          if (vsResponse.ok) {
            const vsData = await vsResponse.json();
            virtualScripts = (vsData.scripts || [])
              // Libraries (utils_/lib_/common_) are sources other scripts pull in
              // via _script_libs, not runnable entries — this list feeds Run Tests.
              // Edit them on the Virtual Scripts page, which lists them all.
              .filter((vs: any) => !vs.is_library)
              .map((vs: any) => ({
                ...vs,
                type: 'virtual' as const,
                folder: vs.folder || 'Root',
                tags: vs.tags || [],
              }));
          }
        } catch (vsError) {
          console.warn('[@TestCaseSelector] virtual scripts unavailable:', vsError);
        }
      }

      // Combine test cases and scripts (filter scripts if testCasesOnly is true)
      const combined: ExecutableItem[] = testCasesOnly
        ? testCases
        : [...testCases, ...scripts, ...virtualScripts];

      if (testCasesData.success) {
        setAllItems(combined);
        console.log('[@TestCaseSelector] ✅ Loaded', testCases.length, 'test cases,',
          scripts.length, 'scripts,', virtualScripts.length, 'virtual scripts');
      } else {
        throw new Error(testCasesData.error || 'Failed to load test cases');
      }

      if (foldersTagsData.success) {
        setAllFolderNames(foldersTagsData.folders?.map((f: any) => f.name) || []);
        setAllTags(foldersTagsData.tags || []);
      }

      if (visibilityData.success) {
        setHiddenKeys(new Set<string>(
          (visibilityData.items || [])
            .filter((item: any) => item.is_visible === false)
            .filter((item: any) => item.entity_type === 'script' || item.entity_type === 'testcase')
            .map((item: any) => item.entity_key)
        ));
      } else {
        setHiddenKeys(new Set());
      }
    } catch (err) {
      console.error('[@TestCaseSelector] ❌ Error loading:', err);
      setError(err instanceof Error ? err.message : 'Failed to load test cases and scripts');
    } finally {
      setLoading(false);
      isLoadingRef.current = false;
    }
  };

  // Three item kinds now share this list, so identity and label go through helpers —
  // the previous `type === 'testcase' ? … : item.script_name` shape silently produced
  // `undefined` for a virtual script.
  const itemKey = (item: ExecutableItem) =>
    item.type === 'testcase' ? item.testcase_id
    : item.type === 'virtual' ? item.id
    : item.script_name;

  const itemLabel = (item: ExecutableItem) =>
    item.type === 'testcase' ? item.testcase_name
    : item.type === 'virtual' ? item.name
    : item.script_name;

  // Identity (TCnnn prefix / display name) is keyed on the canonical script_ref —
  // the same namespace as script_results.script_name, so a converted disk script
  // keeps its prefix under its new virtual-script name.
  const identityRef = (item: ExecutableItem) => normalizeRef(itemLabel(item) || '');

  const getVisibilityKey = (item: ExecutableItem) =>
    item.type === 'testcase' ? item.testcase_id
    : item.type === 'virtual' ? `virtual:${item.id}`
    : `${item.script_name}.py`;

  // Filter items (test cases + scripts)
  const filteredItems = useMemo(() => {
    let items = [...allItems];

    if (!showHidden) {
      items = items.filter((item) => !hiddenKeys.has(getVisibilityKey(item)));
    }

    // Apply type filter
    if (selectedType) {
      items = items.filter(item => item.type === selectedType);
    }

    // Apply folder filter
    if (selectedFolder && selectedFolder !== 'All') {
      items = items.filter(item => item.folder === selectedFolder);
    }

    // Apply search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      items = items.filter(item => {
        if (item.type === 'testcase') {
          return item.testcase_name.toLowerCase().includes(query) ||
                 item.description?.toLowerCase().includes(query) ||
                 item.userinterface_name?.toLowerCase().includes(query);
        }
        if (item.type === 'virtual') {
          return item.name.toLowerCase().includes(query) ||
                 item.description?.toLowerCase().includes(query);
        }
        return item.script_name.toLowerCase().includes(query);
      });
    }

    // Apply tag filter
    if (selectedTags.length > 0) {
      items = items.filter(item =>
        item.tags && item.tags.some(tag => selectedTags.includes(tag))
      );
    }

    return items;
  }, [allItems, hiddenKeys, searchQuery, selectedTags, selectedFolder, selectedType, showHidden]);

  // Handle item selection
  const handleItemSelect = (item: ExecutableItem) => {
    if (item.type === 'testcase') {
      console.log('[@TestCaseSelector] 🎯 Test case selected:', item.testcase_id);
      onLoad(item.testcase_id);
      return;
    }
    if (item.type === 'virtual') {
      // A virtual script is edited on the feature's own page, which is a different editor
      // from the testcase builder. Opened in a new tab so an in-progress selection here is
      // not lost — and with noopener, since window.open otherwise hands the new page a
      // reference back to this one.
      console.log('[@TestCaseSelector] 🐍 Virtual script selected:', item.id);
      window.open(`/builder/virtual-scripts?script=${encodeURIComponent(item.id)}`, '_blank', 'noopener');
      return;
    }
    // Script selected - scripts can't be loaded in test case builder
    console.log('[@TestCaseSelector] ℹ️ Script selected (not loadable):', item.script_name);
  };

  // Handle delete click - just call parent handler, don't refresh
  const handleDeleteClick = (e: React.MouseEvent, item: ExecutableItem) => {
    e.stopPropagation();
    
    if (item.type === 'script') {
      console.log('[@TestCaseSelector] Scripts cannot be deleted from here');
      return;
    }

    if (item.type === 'virtual') {
      // Deleting a virtual script removes all three env rows and its version history, so it
      // stays on the feature's own page where that consequence is visible. The parent's
      // onDelete only knows how to delete a testcase.
      console.log('[@TestCaseSelector] Virtual scripts are deleted from the Virtual Scripts page');
      return;
    }

    if (onDelete) {
      // Call the parent delete handler (opens confirmation dialog)
      // Parent will call refresh() via ref after successful deletion
      onDelete(item.testcase_id, item.testcase_name);
    }
  };

  const toggleVisibility = async (e: React.MouseEvent, item: ExecutableItem) => {
    e.stopPropagation();

    const entityKey = getVisibilityKey(item);
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
        body: JSON.stringify({ entity_type: item.type, entity_key: entityKey }),
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
      invalidateTestCaseListCache();
    } catch (err) {
      console.error('[@TestCaseSelector] ❌ Visibility update failed:', err);
      setError(err instanceof Error ? err.message : 'Failed to update visibility');
    }
  };

  // Save the TCnnn prefix / display name for the row whose chip was clicked.
  // Empty on both fields clears the identity. A duplicate prefix comes back as a
  // non-blocking warning and keeps the popover open so it can be corrected.
  const handleSaveIdentity = async (prefix: string, displayName: string) => {
    if (!identityTarget) return;
    setIdentitySaving(true);
    try {
      const res = await saveScriptIdentity(identityTarget.scriptRef, {
        prefix,
        display_name: displayName,
      });
      if (!res.success) {
        showError(res.error || 'Failed to save identity');
        return;
      }
      if (res.warning) {
        setIdentityWarning(res.warning);
        showSuccess(`Saved — ${res.warning}`);
        return;
      }
      showSuccess(prefix || displayName ? 'Identity saved' : 'Identity cleared');
      setIdentityTarget(null);
    } finally {
      setIdentitySaving(false);
    }
  };

  // Convert a disk script into a virtual script (dev row, editable in-app, no redeploy).
  const handleConvertToVirtual = async (e: React.MouseEvent, item: ScriptItem) => {
    e.stopPropagation();
    setConvertingScript(item.script_name);
    try {
      const res = await api.post<{
        success: boolean;
        error?: string;
        action?: 'created' | 'updated';
        name?: string;
        units?: Array<{ name: string; folder: string; is_helper: boolean; warnings?: string[] }>;
        errors?: Array<{ ref: string; code: string; message: string }>;
      }>(buildServerUrl('/server/virtual-script/convert'), { script_name: item.script_name });
      if (res?.success) {
        // Convert also pulls in any test_scripts.* helper the script imports, as
        // its own virtual script declared in _script_libs — say so, otherwise the
        // extra entries appearing in the list look like a bug.
        const root = res.units?.find((u) => !u.is_helper);
        const helpers = res.units?.filter((u) => u.is_helper) ?? [];
        const helperNote = helpers.length
          ? ` + ${helpers.length} librar${helpers.length === 1 ? 'y' : 'ies'} (${helpers
              .map((h) => h.name)
              .join(', ')})`
          : '';
        const folderNote = root?.folder && root.folder !== '(Root)' ? ` in folder ${root.folder}` : '';
        showSuccess(
          `${res.action === 'updated' ? 'Updated' : 'Created'} virtual script "${res.name || item.script_name}"${helperNote}${folderNote} (dev). Promote it from the Virtual Scripts page.`,
        );
        invalidateExecutableListCache();
      } else {
        const detail = res?.errors?.length
          ? res.errors.map((e) => `${e.ref}: ${e.message}`).join(' · ')
          : res?.error;
        showError(detail || 'Convert failed');
      }
    } catch (err) {
      showError(`Convert failed: ${err instanceof Error ? err.message : 'unknown error'}`);
    } finally {
      setConvertingScript(null);
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
      <Alert severity="error">{error}</Alert>
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
        rightContent={!testCasesOnly && !isCompact ? (
          <ExecutableTypeToggle
            value={selectedType}
            onChange={setSelectedType}
            options={[
              { id: 'script', label: 'S', color: 'primary' },
              { id: 'testcase', label: 'TC', color: 'secondary' },
              // VS only exists when the virtual-scripts feature is deployed.
              ...(virtualScriptsEnabled
                ? [{ id: 'virtual', label: 'VS', color: 'primary' as const }]
                : []),
            ]}
          />
        ) : undefined}
      />

      {/* Item List - Compact format for test cases and scripts */}
      <Box>
        <Paper variant="outlined" sx={{ maxHeight: 400, overflow: 'auto' }}>
          {filteredItems.length === 0 ? (
            <Box sx={{ p: 3, textAlign: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                {allItems.length === 0 
                  ? 'No test cases or scripts found. Click the + button to create one!'
                  : 'No items match your filters'
                }
              </Typography>
            </Box>
          ) : (
            <List dense disablePadding>
              {filteredItems.map(item => {
                const isTestCase = item.type === 'testcase';
                const itemId = itemKey(item);
                const isSelected = selectedTestCaseId === itemId;
                const isHidden = hiddenKeys.has(getVisibilityKey(item));
                const folderLabel = item.folder && item.folder !== 'All' && item.folder !== 'Root' ? item.folder : '';
                
                return (
                  <ListItem
                    key={itemId}
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
                      onClick={() => handleItemSelect(item)}
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
                        color: 'inherit',
                      }}
                    >
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', minWidth: 0 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flex: isMobile ? '1 1 70%' : '1 1 48%', minWidth: 0 }}>
                          <Chip
                            icon={item.type === 'script' ? <ScriptIcon /> : undefined}
                            label={item.type === 'testcase' ? 'TC' : item.type === 'virtual' ? 'VS' : 'S'}
                            size="small"
                            color={item.type === 'testcase' ? 'secondary' : 'primary'}
                            sx={{
                              height: '16px',
                              fontSize: '0.6rem',
                              minWidth: '24px',
                              '.MuiChip-label': { px: 0.5 },
                              opacity: isSelected ? 0.95 : 1,
                            }}
                          />
                          {(() => {
                            const rawName = itemLabel(item);
                            const ref = identityRef(item);
                            const identity = resolveScript(ref);
                            const label = identity.display_name ?? rawName;
                            // The chip is the edit affordance. Unset rows get a faint
                            // "+TC" placeholder so every row is clickable, rather than
                            // adding a fourth icon to the action group.
                            const openIdentityEditor = (e: React.MouseEvent<HTMLElement>) => {
                              e.stopPropagation();
                              setIdentityWarning(null);
                              setIdentityTarget({ anchorEl: e.currentTarget, scriptRef: ref });
                            };
                            return (
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0, overflow: 'hidden' }}>
                                <Tooltip title="Edit prefix / display name">
                                  <Chip
                                    label={identity.prefix || '+TC'}
                                    size="small"
                                    onClick={openIdentityEditor}
                                    sx={{
                                      fontSize: '0.6rem',
                                      height: 16,
                                      flexShrink: 0,
                                      fontFamily: 'monospace',
                                      px: 0.25,
                                      cursor: 'pointer',
                                      opacity: identity.prefix ? 1 : 0.35,
                                    }}
                                  />
                                </Tooltip>
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

                        <Box sx={{ flex: '0 1 24%', minWidth: 0, display: isMobile ? 'none' : 'block' }}>
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

                        {/* dev/test/prod lifecycle. A testcase carries a single `environment`
                            plus `current_version`; a virtual script carries the set of env rows
                            that exist plus `prod_version`. A disk script has neither — a file has
                            no lifecycle — so its slot stays empty rather than showing three greys. */}
                        <Box sx={{ flex: '0 0 auto', display: 'flex', alignItems: 'center', mr: 1 }}>
                          {item.type === 'virtual' ? (
                            <LifecycleChips
                              size="tiny"
                              environments={{
                                dev: !!item.environments?.dev,
                                test: !!item.environments?.test,
                                prod: !!item.environments?.prod,
                              }}
                              prodVersion={item.prod_version}
                            />
                          ) : item.type === 'testcase' && item.environment ? (
                            <LifecycleChips
                              size="tiny"
                              environments={{ [item.environment]: true }}
                              currentVersion={item.current_version}
                            />
                          ) : null}
                        </Box>

                        <Box sx={{ display: 'flex', gap: 0.25, flex: '0 1 28%', minWidth: 0, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                          {item.tags?.map((tagName) => {
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

                        {/* Convert a disk script into a virtual script (dev row).
                            Gated on type === 'script', not !isTestCase: the list now also
                            holds virtual scripts, which are already virtual and whose rows
                            have no `script_name` for the convert call to send. Also gated
                            on the feature, since /server/virtual-script/* is not registered
                            on a deploy with DISABLED_FEATURES=virtual-scripts. */}
                        {item.type === 'script' && virtualScriptsEnabled && (
                          <Tooltip title="Save this disk script as a virtual script (editable in-app, no redeploy). Creates/updates its dev version.">
                            <span>
                              <IconButton
                                size="small"
                                onClick={(e) => handleConvertToVirtual(e, item as ScriptItem)}
                                disabled={convertingScript === item.script_name}
                                sx={{
                                  p: 0.5,
                                  flexShrink: 0,
                                  color: isSelected ? 'primary.contrastText' : 'text.secondary',
                                  '&:hover': {
                                    bgcolor: isSelected ? 'rgba(255,255,255,0.2)' : 'action.hover'
                                  },
                                }}
                              >
                                {convertingScript === item.script_name
                                  ? <CircularProgress size={14} />
                                  : <CloudSyncIcon fontSize="small" />}
                              </IconButton>
                            </span>
                          </Tooltip>
                        )}

                        {/* Visibility/delete are power-user row actions with no room on
                            mobile — hidden there so the actual name has space to show. */}
                        {!isMobile && (
                          <IconButton
                            size="small"
                            onClick={(e) => toggleVisibility(e, item)}
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
                        )}

                        {/* Delete Button (Test Cases only) */}
                        {!isMobile && isTestCase && onDelete && (
                          <IconButton
                            size="small"
                            onClick={(e) => handleDeleteClick(e, item)}
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
          {filteredItems.length} item{filteredItems.length !== 1 ? 's' : ''}
          {selectedType && ` • ${selectedType === 'script' ? 'S' : selectedType === 'virtual' ? 'VS' : 'TC'}`}
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
              setSelectedType(testCasesOnly ? 'testcase' : (isCompact ? null : 'script'));
            }}
          >
            Clear filters
          </Typography>
        )}
      </Box>

      {identityTarget && (() => {
        const current = resolveScript(identityTarget.scriptRef);
        return (
          <ScriptIdentityPopover
            open
            anchorEl={identityTarget.anchorEl}
            scriptRef={identityTarget.scriptRef}
            initialPrefix={current.prefix}
            initialDisplayName={current.display_name}
            saving={identitySaving}
            warning={identityWarning}
            onSave={handleSaveIdentity}
            onClose={() => setIdentityTarget(null)}
          />
        );
      })()}
    </Box>
  );
});
