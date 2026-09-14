import {
  Box,
  DialogTitle,
  DialogContent,
  DialogActions,
  Snackbar,
  Alert,
  Typography,
  Button,
} from '@mui/material';
import React, { useEffect, useCallback, useRef, useState, useMemo } from 'react';
import { useParams, useLocation } from 'react-router-dom';
import { DEFAULT_DEVICE_RESOLUTION } from '../config/deviceResolutions';
import ReactFlow, {
  Background,
  Controls,
  ReactFlowProvider,
  MiniMap,
  ConnectionLineType,
  BackgroundVariant,
  MarkerType,

} from 'reactflow';
import 'reactflow/dist/style.css';

// Auto-layout utility
import { getLayoutedElements } from '../components/testcase/ai/autoLayout';

// Import extracted components and hooks
import { RemotePanel } from '../components/controller/remote/RemotePanel';
import { DesktopPanel } from '../components/controller/desktop/DesktopPanel';
import { WebPanel } from '../components/controller/web/WebPanel';
import { VNCStream } from '../components/controller/av/VNCStream';
import { HDMIStream } from '../components/controller/av/HDMIStream';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { StyledDialog } from '../components/common/StyledDialog';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { NavigationBreadcrumbCompact } from '../components/navigation/NavigationBreadcrumbCompact';
import { EdgeEditDialog } from '../components/navigation/Navigation_EdgeEditDialog';
import { AIGenerationModal } from '../components/navigation/AIGenerationModal';
import { ValidationReadyPrompt } from '../components/navigation/ValidationReadyPrompt';
import { ValidationModal } from '../components/navigation/ValidationModal';
import { EdgeSelectionPanel } from '../components/navigation/Navigation_EdgeSelectionPanel';
import { MetricsNotification } from '../components/navigation/MetricsNotification';
import { MetricsModal } from '../components/navigation/MetricsModal';
import { NavigationEditorHeader } from '../components/navigation/Navigation_EditorHeader';
import { NavigationEdgeComponent } from '../components/navigation/Navigation_NavigationEdge';
import { UINavigationNode } from '../components/navigation/Navigation_NavigationNode';
import { UIActionNode } from '../components/navigation/Navigation_ActionNode';
import { NodeEditDialog } from '../components/navigation/Navigation_NodeEditDialog';
import { NodeGotoPanel } from '../components/navigation/Navigation_NodeGotoPanel';
import { NodeSelectionPanel } from '../components/navigation/Navigation_NodeSelectionPanel';
import { NavigationScreenshotProvider } from '../contexts/navigation/NavigationScreenshotContext';
import { useTheme } from '../contexts/ThemeContext';
import { useDeviceData } from '../contexts/device/DeviceDataContext';
import { useHostControl } from '../hooks/useHostManager';
import {
  NavigationConfigProvider,
  useNavigationConfig,
} from '../contexts/navigation/NavigationConfigContext';
import { NavigationPreviewCacheProvider } from '../contexts/navigation/NavigationPreviewCacheContext';
import { useNavigation } from '../contexts/navigation/NavigationContext';
import { NavigationEditorProvider } from '../contexts/navigation/NavigationEditorProvider';
import {
  NavigationStackProvider,
  useNavigationStack,
} from '../contexts/navigation/NavigationStackContext';
import { useNavigationEditor } from '../hooks/navigation/useNavigationEditor';
import { useGlobalFocusNodes } from '../hooks/navigation/useGlobalFocusNodes';
import { useNavigationBreadcrumb } from '../hooks/navigation/useNavigationBreadcrumb';
import { useNestedNavigation } from '../hooks/navigation/useNestedNavigation';
import { useEdge } from '../hooks/navigation/useEdge';
import { useMetrics } from '../hooks/navigation/useMetrics';
import { useResolvedTree } from '../hooks/navigation/useResolvedTree';
import {
  parseVariantList,
  composeNodeOverrides,
  composeEdgeOverrides,
  detectCompositionConflicts,
} from '../utils/navigation/variantResolver';
import { reanchorEdgeToDrawnHandles } from '../utils/navigation/navigationUtils';
import { useUserInterface } from '../hooks/pages/useUserInterface';
import { useUserInterfaceVariants } from '../hooks/userinterface/useUserInterfaceVariants';
import { useDeviceCompatibilityGuard } from '../hooks/navigation/useDeviceCompatibilityGuard';
import { useToast } from '../hooks/useToast';
import {
  NodeForm,
  EdgeForm,
  UINavigationNode as UINavigationNodeType,
} from '../types/pages/Navigation_Types';
import { getZIndex } from '../utils/zIndexUtils';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';
import {
  TRANSLATE_EXTENT,
  NODE_EXTENT,
  SNAP_GRID,
  REACT_FLOW_STYLE,
  NODE_ORIGIN,
  DEFAULT_VIEWPORT,
  AUTO_LAYOUT_BUTTON_TOP,
  AUTO_LAYOUT_BUTTON_LEFT,
} from '../utils/navigation/navigationLayoutConstants';

// Node types for React Flow - defined outside component to prevent recreation on every render
const nodeTypes = {
  screen: UINavigationNode,
  menu: UINavigationNode,
  action: UIActionNode,
  entry: UINavigationNode, // Entry nodes use the same component as screen nodes but with different styling
};

const edgeTypes = {
  navigation: NavigationEdgeComponent,
  smoothstep: NavigationEdgeComponent,
};

// Default options - defined outside component to prevent recreation
const defaultEdgeOptions = {
  type: 'navigation',
  animated: false,
  style: { strokeWidth: 2, stroke: '#b1b1b7' },
  markerEnd: {
    type: MarkerType.ArrowClosed,
    width: 20,
    height: 20,
    color: '#b1b1b7',
  },
};


const proOptions = { hideAttribution: true };

// MiniMap nodeColor function - defined outside component to prevent recreation
const miniMapNodeColor = (node: any) => {
  // Check if this is the current position node
  const isCurrentPosition = node.data?.isCurrentPosition;

  // Check if this is part of navigation route
  const isOnNavigationRoute = node.data?.isOnNavigationRoute;

  // Current position gets bright purple
  if (isCurrentPosition) {
    return '#9c27b0'; // Bright purple for current position
  }

  // Navigation route nodes get orange/amber
  if (isOnNavigationRoute) {
    return '#ff9800'; // Orange for navigation route
  }

  // Default colors based on node type
  switch (node.data?.type) {
    case 'screen':
      return '#3b82f6';
    case 'dialog':
      return '#8b5cf6';
    case 'popup':
      return '#f59e0b';
    case 'overlay':
      return '#10b981';
    case 'menu':
      return '#ffc107';
    case 'entry':
      return '#ef4444'; // Red for entry points
    default:
      return '#6b7280';
  }
};

// Helper function removed - was unused

// Exported for embedding in ContentViewer
export const NavigationEditorContent: React.FC<{ treeName: string }> = ({ treeName }) => {

    // Get theme context for dynamic styling
    const { actualMode } = useTheme();

    // Get navigation stack for nested navigation
    const { currentLevel, isNested, stack } = useNavigationStack();

    // Get current node ID from NavigationContext
    const { currentNodeId } = useNavigation();

    // Shared navigation breadcrumb functionality (no code duplication)
    const { handleNavigateBack, handleNavigateToLevel, handleNavigateToRoot } = useNavigationBreadcrumb();

      // Get the actual tree ID from NavigationConfigContext
  const navigationConfig = useNavigationConfig();
  const { actualTreeId, setActualTreeId } = navigationConfig;

    // Get navigation context for nested navigation
    const navigation = useNavigation();

    // Dynamic miniMapStyle based on theme - black background in dark mode, white in light mode
    const miniMapStyle = useMemo(
      () => ({
        backgroundColor: actualMode === 'dark' ? '#1f2937' : '#ffffff',
        border: `1px solid ${actualMode === 'dark' ? '#374151' : '#e5e7eb'}`,
        borderRadius: '8px',
        boxShadow:
          actualMode === 'dark'
            ? '0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -1px rgba(0, 0, 0, 0.2)'
            : '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
      }),
      [actualMode],
    );

    // Use the restored navigation editor hook
    const {
      // State
      nodes,
      edges,
      isLoadingInterface,
      selectedNode,
      selectedEdge,
      isNodeDialogOpen,
      isEdgeDialogOpen,
      nodeForm,
      edgeForm,
      success,
      reactFlowWrapper,

      hasUnsavedChanges,
      isDiscardDialogOpen,
      userInterface,

      // View state for single-level navigation

      // Tree filtering state
      focusNodeId,
      maxDisplayDepth,
      allNodes,
      setDisplayDepth,
      resetFocus,

      // Setters
      setIsNodeDialogOpen,
      setIsEdgeDialogOpen,
      setNodeForm,
      setEdgeForm,
      setIsDiscardDialogOpen,

      // Event handlers
      onNodesChange,
      onEdgesChange,
      onConnect,
      onNodeClick,
      onEdgeClick,
      onPaneClick,

      // New normalized API
      saveTreeWithStateUpdate,
      isLocked,
      saveNodeWithStateUpdate,
      saveEdgeWithStateUpdate,
      addNewNode,
      cancelNodeChanges,
      discardChanges,
      performDiscardChanges,
      closeSelectionPanel,
      fitView,
      deleteSelected,
      resetNode,
      setUserInterfaceFromProps,

      // Additional setters we need
      setNodes,
      setSelectedNode,
      setReactFlowInstance,
      setHasUnsavedChanges,
      setEdges,
      // setSelectedEdge, // Removed - not used without handleUpdateEdge

      // Error state
      error,

      // Host data (filtered by userInterface models)
      availableHosts,
      
      // API methods
      loadTreeByUserInterface,
      loadTreeData,

      // Confirmation dialog state and handlers
      confirmDialogState,
      confirmDialogHandleConfirm,
      confirmDialogHandleCancel,
    } = useNavigationEditor();

    // treeName is available from useParams and used for userInterface resolution

    // Initialize nested navigation hook for unified double-click handling
    const nestedNavigation = useNestedNavigation({
      setNodes,
      setEdges,
      openNodeDialog: navigation.openNodeDialog,
    });

    // Cross-tree focus: list every node across root + all subtrees and, on
    // selection, redirect into the owning subtree (rebuilding the breadcrumb)
    // before focusing the node on the canvas.
    const { globalFocusNodes, focusSelectValue, selectFocusNode } = useGlobalFocusNodes(
      userInterface?.id || null,
    );

    // Get host manager from context (excluding availableHosts - we get that from useNavigationEditor)
    const {
      selectedHost,
      selectedDeviceId,
      isControlActive,
      isRemotePanelOpen,
      showRemotePanel,
      showAVPanel,
      handleDeviceSelect,
      handleControlStateChange,
      handleToggleRemotePanel,
      handleDisconnectComplete,
    } = useHostControl();

    // ─── Canvas viewing scope ──────────────────────────────────────────────
    // null = Base view; non-null = variant name. Declared early because
    // useEdge / NodeGotoPanel / loadTreeByUserInterface all consume it.
    // Persisted to localStorage per userInterface.id so refresh doesn't
    // snap the canvas back to base — see restore/persist effects below.
    const [viewingScope, setViewingScope] = useState<string | null>(null);
    // When viewing a single variant, toggles whether rows DISABLED on that
    // variant render ghosted (grey + transparent, selectable) instead of being
    // filtered off the canvas. Lets the author re-select a "deleted" row and hit
    // "Reset variant" to restore it. Default off keeps the canvas clean.
    const [showDisabledOnVariant, setShowDisabledOnVariant] = useState(false);
    // Tracks the userInterface.id we've already hydrated viewingScope for,
    // so the persist effect doesn't fire (with the initial `null`) before
    // restore has run — that would silently wipe the stored value.
    const viewingScopeRestoredForUi = useRef<string | null>(null);

    // viewingScope may be a single variant name OR a canonical composition
    // ('a+b') chosen via the multi-select chip. Parse it into components.
    // (Declared up here because authoring callbacks below reference these.)
    const viewingComponents = useMemo(() => parseVariantList(viewingScope), [viewingScope]);
    const isComposition = viewingComponents.length > 1;
    // The single variant that authoring (Add/Delete/Edit) targets. A composition
    // is a read-only preview, so there is no edit scope then.
    const editScope = viewingComponents.length === 1 ? viewingComponents[0] : null;

    // Publish the active viewing scope to NavigationContext so edge Runs
    // triggered from selection panels / edit dialogs (their useEdge instances
    // don't receive a `variant` prop) are stamped with the variant the canvas
    // is showing, instead of silently falling back to base.
    const { setRunVariant } = navigation;
    useEffect(() => {
      setRunVariant(viewingScope);
    }, [viewingScope, setRunVariant]);

    // Initialize edge hook - always call but with proper parameters
    const edgeHook = useEdge({
      selectedHost: selectedEdge ? (selectedHost || null) : null,
      selectedDeviceId: selectedEdge ? (selectedDeviceId || null) : null,
      isControlActive: selectedEdge ? isControlActive : false,
      treeId: actualTreeId, // Always pass actualTreeId for proper navigation context
      variant: viewingScope, // Active canvas viewing scope, stamped onto every Run
    });

    // Initialize metrics hook
    const [preloadedMetrics, setPreloadedMetrics] = useState<any>(null);
    const metricsHook = useMetrics({
      treeId: actualTreeId,
      nodes,
      edges,
      enabled: true, // Always enabled for confidence tracking
      preloadedMetrics, // Pass metrics from combined endpoint
    });

    // Track the last loaded tree ID to prevent unnecessary reloads
    const lastLoadedTreeId = useRef<string | null>(null);
    
    // Track the last resolved treeName to prevent duplicate userInterface resolution
    const lastResolvedTreeName = useRef<string | null>(null);

    const {
      variants: registeredVariants,
      updateVariantOverrides,
      refresh: refreshVariants,
    } = useUserInterfaceVariants(userInterface?.id || null);
    const { showSuccess: showToastSuccess, showError: showToastError } = useToast();
    // Separate confirm dialog instance for the scope-aware Delete dialog
    // (existing useNavigationEditor confirmDialogState is reserved for its own
    // delete confirms; we don't want to thrash it).
    const variantConfirm = useConfirmDialog();

    // AV panel collapsed state for other UI elements (keeping for backwards compatibility)
    const [isAVPanelCollapsed, setIsAVPanelCollapsed] = useState(true);

    // AV panel minimized state for overlay coordination
    const [isAVPanelMinimized, setIsAVPanelMinimized] = useState(false);

    // Capture mode state for coordinating between AV and Remote panels
    const [captureMode, setCaptureMode] = useState<'stream' | 'screenshot' | 'video'>('stream');

    // Mobile orientation state for coordinating video aspect ratio
    const [isMobileOrientationLandscape, setIsMobileOrientationLandscape] = useState(false);

    // Calculate verification editor visibility based on capture mode (same logic as AV components)
    const isVerificationVisible = captureMode === 'screenshot' || captureMode === 'video';

    // Goto panel state
    const [showGotoPanel, setShowGotoPanel] = useState(false);
    const [selectedNodeForGoto, setSelectedNodeForGoto] = useState<UINavigationNodeType | null>(
      null,
    );

    // AI Generation modal state
    const [isAIGenerationOpen, setIsAIGenerationOpen] = useState(false);
    
    // Validation Ready Prompt state
    const [showValidationPrompt, setShowValidationPrompt] = useState(false);
    const [validationNodesCount, setValidationNodesCount] = useState(0);
    const [validationEdgesCount, setValidationEdgesCount] = useState(0);
    const [explorationId, setExplorationId] = useState<string | null>(null);
    const [explorationHostName, setExplorationHostName] = useState<string | null>(null);
    
    // Validation Modal state
    const [isValidationModalOpen, setIsValidationModalOpen] = useState(false);
    const [applyAutoLayoutFlag, setApplyAutoLayoutFlag] = useState(false);

    // Metrics state
    const [showMetricsModal, setShowMetricsModal] = useState(false);

    // Modifier key state for conditional edge creation
    const [isShiftHeld, setIsShiftHeld] = useState(false);

    // Phase 4 the variant authoring rules — ref to scope-aware delete (defined later, populated below).
    // Lets the keyboard handler use the latest variant-aware delete without
    // re-binding the listener every render.
    const wrappedDeleteSelectedRef = useRef<(() => Promise<any> | void) | null>(null);

    // Keyboard event listeners for modifier keys
    useEffect(() => {
      const handleKeyDown = (e: KeyboardEvent) => {
        // Check if user is focused on an input field (TextField, textarea, contenteditable)
        const target = e.target as HTMLElement;
        const isInputField = 
          target.tagName === 'INPUT' || 
          target.tagName === 'TEXTAREA' || 
          target.isContentEditable ||
          target.closest('input') !== null ||
          target.closest('textarea') !== null;
        
        if (e.shiftKey) {
          setIsShiftHeld(true);
        }
        
        // DELETE/BACKSPACE key - delete selected node/edge with protection
        // Phase 4 the variant authoring rules routing happens inside wrappedDeleteSelected.
        if ((e.key === 'Delete' || e.key === 'Backspace') && !isInputField) {
          e.preventDefault();
          wrappedDeleteSelectedRef.current?.();
        }
        
        // Undo/Redo shortcuts - only when NOT in input fields
        if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key === 'z' && !isInputField) {
          e.preventDefault();
          navigation.undo();
        }
        if ((e.ctrlKey || e.metaKey) && (e.shiftKey && e.key === 'z' || e.key === 'y') && !isInputField) {
          e.preventDefault();
          navigation.redo();
        }
        
        // Copy/Paste shortcuts - only when NOT in input fields (allow normal text copy/paste)
        if ((e.ctrlKey || e.metaKey) && e.key === 'c' && !isInputField) {
          // Let the browser handle native copy when the user has a text selection
          if (window.getSelection()?.toString()) {
            return;
          }
          e.preventDefault();
          navigation.copyNode();
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 'v' && !isInputField) {
          e.preventDefault();
          navigation.pasteNode();
        }
      };

      const handleKeyUp = (e: KeyboardEvent) => {
        if (!e.shiftKey) {
          setIsShiftHeld(false);
        }
      };

      window.addEventListener('keydown', handleKeyDown);
      window.addEventListener('keyup', handleKeyUp);

      return () => {
        window.removeEventListener('keydown', handleKeyDown);
        window.removeEventListener('keyup', handleKeyUp);
      };
    }, [navigation]);

    // AI Generation handler
    const handleToggleAIGeneration = useCallback(() => {
      setIsAIGenerationOpen(true);
    }, []);

    // Handle AI generation completion
    const handleAIGenerated = useCallback(() => {
      // Refresh the navigation tree after AI generation
      const refreshData = async () => {
        try {
          if (userInterface?.id) {
            // Pause history recording during AI generation refresh
            navigation.pauseHistoryRecording();

            // CRITICAL: Invalidate cache FIRST to force fresh fetch from DB
            // This ensures we see the newly created _temp nodes immediately
            console.log('[@NavigationEditor:handleAIGenerated] 🗑️ Invalidating cache for interface:', userInterface.id);
            navigationConfig.invalidateTreeCache(userInterface.id);

            // Reload the CURRENT tree (root or subtree) - actualTreeId points to what was modified
            const treeType = navigation.parentChain.length > 0 ? 'subtree' : 'root tree';
            console.log(`[@NavigationEditor:handleAIGenerated] 🔄 Reloading ${treeType}: ${actualTreeId}`);

            try {
              if (actualTreeId) {
                // Simple: Just reload the current tree that was modified
                await loadTreeData(actualTreeId);
                console.log(`[@NavigationEditor:handleAIGenerated] ✅ ${treeType} reloaded successfully`);

                // Apply auto-layout after nodes are loaded
                setApplyAutoLayoutFlag(true);
              } else {
                console.error('[@NavigationEditor:handleAIGenerated] ❌ Cannot reload - actualTreeId is undefined');
              }
            } catch (error) {
              console.error(`[@NavigationEditor:handleAIGenerated] ❌ Failed to reload ${treeType}:`, error);
            }
          }
        } catch (error) {
          console.error('[@NavigationEditor:handleAIGenerated] Failed to refresh tree data:', error);
        } finally {
          // Always resume history recording
          navigation.resumeHistoryRecording();
        }
      };
      refreshData();
    }, [userInterface?.id, loadTreeData, navigationConfig, actualTreeId, navigation.parentChain.length, navigation]);

    // Wrap the original click handlers to close goto panel
    const wrappedOnNodeClick = useCallback(
      (event: React.MouseEvent, node: any) => {
        // Close goto panel if it's open
        if (showGotoPanel) {
          setShowGotoPanel(false);
          setSelectedNodeForGoto(null);
        }
        // Call the original handler
        onNodeClick(event, node);
      },
      [onNodeClick, showGotoPanel],
    );

    const wrappedOnEdgeClick = useCallback(
      (event: React.MouseEvent, edge: any) => {
        // Close goto panel if it's open
        if (showGotoPanel) {
          setShowGotoPanel(false);
          setSelectedNodeForGoto(null);
        }
        // Call the original handler
        onEdgeClick(event, edge);
      },
      [onEdgeClick, showGotoPanel],
    );

    // Wrap the pane click handler to also close goto panel
    const wrappedOnPaneClick = useCallback(() => {
      // Close goto panel if it's open
      if (showGotoPanel) {
        setShowGotoPanel(false);
        setSelectedNodeForGoto(null);
      }
      // Call the original handler
      onPaneClick();
    }, [onPaneClick, showGotoPanel]);

    // ─── Phase 4 the variant authoring rules — variant-only overrides envelope ───────────────────
    // Used by Add Node / Add Edge wrappers when authoring on a single variant.
    // ADDITIVE model (see docs/agent/navigation/VARIANT.md "Composition"): a new variant-
    // only row (`hidden_in_base: true`) is turned ON for its owning variant by
    // writing `{enabled: true}` into THAT variant's own overrides. No other
    // variant is touched — additive default is "off", so the row stays hidden
    // everywhere the owner isn't applied, and it composes cleanly with other
    // variants (no leftover cross-disables to poison a composition).
    // ─── Staged variant-override edits (the "yellow Save" model) ───
    // ALL variant-scope authoring (enable/disable markers, per-variant
    // action_set content, marker removals) stages HERE instead of writing to
    // the server immediately — exactly like base edits and variant node
    // positions: the Save button turns yellow, Save flushes everything in ONE
    // write per variant (see flushVariantChanges), Discard drops it. An entry
    // value of `null` stages a key DELETION. Rendering composes from the
    // effective (persisted + staged) maps, so staged edits are visible
    // instantly — no optimistic side-channel needed — and a variant marker can
    // never persist ahead of its base row again (both land on the same Save).
    const [stagedOverrideEdits, setStagedOverrideEdits] = useState<
      Record<
        string,
        {
          node_overrides: Record<string, any | null>;
          edge_overrides: Record<string, any | null>;
        }
      >
    >({});
    const stagedOverrideEditsRef = useRef(stagedOverrideEdits);
    useEffect(() => {
      stagedOverrideEditsRef.current = stagedOverrideEdits;
    }, [stagedOverrideEdits]);

    const stageOverrideEdit = useCallback(
      (
        rowKind: 'node' | 'edge',
        variantName: string,
        edits: Record<string, any | null>,
      ) => {
        if (Object.keys(edits).length === 0) return;
        const kind = rowKind === 'node' ? 'node_overrides' : 'edge_overrides';
        setStagedOverrideEdits((prev) => {
          const cur = prev[variantName] || { node_overrides: {}, edge_overrides: {} };
          return {
            ...prev,
            [variantName]: { ...cur, [kind]: { ...cur[kind], ...edits } },
          };
        });
        setHasUnsavedChanges(true);
      },
      [setHasUnsavedChanges],
    );

    // Remove a staged edit WITHOUT staging anything (≠ staging null, which
    // stages a deletion). Used when the Edit dialog persists an override
    // directly — the staged copy is then stale and would clobber the freshly
    // saved entry on the next canvas Save flush.
    const clearStagedOverrideEdit = useCallback(
      (rowKind: 'node' | 'edge', variantName: string, rowId: string) => {
        const kind = rowKind === 'node' ? 'node_overrides' : 'edge_overrides';
        setStagedOverrideEdits((prev) => {
          const cur = prev[variantName];
          if (!cur || !(rowId in cur[kind])) return prev;
          const nextKind = { ...cur[kind] };
          delete nextKind[rowId];
          return { ...prev, [variantName]: { ...cur, [kind]: nextKind } };
        });
      },
      [],
    );

    // Persisted map with staged edits applied (null = key removed).
    const effectiveOverrideMap = useCallback(
      (
        variantName: string,
        kind: 'node_overrides' | 'edge_overrides',
      ): Record<string, any> => {
        const v = registeredVariants.find((x) => x.name === variantName);
        const persisted = ((v?.[kind] as any) || {}) as Record<string, any>;
        const edits = stagedOverrideEdits[variantName]?.[kind];
        if (!edits || Object.keys(edits).length === 0) return persisted;
        const out: Record<string, any> = { ...persisted };
        for (const [id, entry] of Object.entries(edits)) {
          if (entry === null) delete out[id];
          else out[id] = entry;
        }
        return out;
      },
      [registeredVariants, stagedOverrideEdits],
    );

    const enableOnVariant = useCallback(
      (rowKind: 'node' | 'edge', rowId: string, activeVariant: string): void => {
        stageOverrideEdit(rowKind, activeVariant, { [rowId]: { enabled: true } });
      },
      [stageOverrideEdit],
    );

    // Effective (persisted + staged) per-variant override entries for the
    // SELECTED edge. The Edit dialog seeds its variant scopes from this so a
    // staged-but-unsaved override (e.g. from a redraw over a variant-deleted
    // edge) shows its real content instead of the stale persisted entry.
    const selectedEdgeEffectiveOverrides = useMemo(() => {
      const id = selectedEdge?.id;
      if (!id) return undefined;
      const out: Record<string, any> = {};
      for (const v of registeredVariants) {
        const entry = effectiveOverrideMap(v.name, 'edge_overrides')[id];
        if (entry) out[v.name] = entry;
      }
      return out;
    }, [selectedEdge?.id, registeredVariants, effectiveOverrideMap]);

    // Wrap onConnect to pass modifier key state for conditional edges and
    // to mark new edges variant-only when a variant is being viewed. With
    // the per-variant overrides model, this means setting `hidden_in_base:
    // true` on the new edge AND writing `{disabled: true}` to every OTHER
    // registered variant's `edge_overrides` for the new edge id.
    const wrappedOnConnect = useCallback(
      (connection: any) => {
        const src = connection?.source;
        const tgt = connection?.target;

        // ── Scope-aware reveal of an EXISTING but HIDDEN edge (BUG-0014) ──
        // A hidden_in_base=true edge is invisible in Base (and on any variant
        // that disables it), so the user can neither see nor reach it and
        // drawing over it dead-ends them. Reveal it — but NEVER by blindly
        // flipping hidden_in_base, which would leak a variant-only edge into
        // Base. Resolve per current scope. See docs/agent/navigation/VARIANT.md.
        if (src && tgt && src !== tgt) {
          const existingHidden = edges.find(
            (e) =>
              ((e.source === src && e.target === tgt) ||
                (e.source === tgt && e.target === src)) &&
              (e.data as any)?.hidden_in_base === true,
          );
          if (existingHidden) {
            const existingId = existingHidden.id;

            // Composition preview is read-only — pick a single scope to author.
            if (isComposition) {
              showToastError('Pick a single variant or Base to reveal this edge.');
              return;
            }

            // Whatever scope reveals the edge, it must come back anchored to the
            // handles the user JUST drew — never the row's stale stored sides
            // (the "drew right→left, edge appears left→right" swap). Null when
            // the drawn handles already match.
            const anchor = reanchorEdgeToDrawnHandles(existingHidden as any, connection);
            const withAnchor = (e: any, extraData: Record<string, any> = {}) => ({
              ...e,
              ...(anchor || {}),
              data: { ...(e.data || {}), ...(anchor || {}), ...extraData },
            });

            if (editScope === null) {
              // BASE scope: PROMOTE the variant-only edge to a Base edge.
              // Duplicates are blocked, so the user could never link these
              // nodes in Base while a variant owned the edge. Un-hide it and
              // drop every variant's visibility marker for it (`enabled` is a
              // no-op on a base edge; a leftover `disabled` would keep it
              // hidden on that variant after promotion). Per-variant CONTENT
              // overrides (action_sets replacements) are kept. Silent — the
              // edge appearing in Base is the feedback. hidden_in_base=false
              // persists on Save, like any base-row change.
              const revealed = edges.map((e) =>
                e.id === existingId ? withAnchor(e, { hidden_in_base: false }) : e,
              );
              setEdges(revealed as any);
              navigation.setSelectedEdge(
                (revealed.find((e) => e.id === existingId) as any) || null,
              );
              setHasUnsavedChanges(true);
              for (const v of registeredVariants) {
                const entry = ((v.edge_overrides as any) || {})[existingId];
                if (!entry) continue;
                if (Array.isArray(entry.action_sets) && entry.action_sets.length > 0)
                  continue; // keep content overrides
                stageOverrideEdit('edge', v.name, { [existingId]: null });
              }
              return;
            }

            // VARIANT scope: reveal WITHIN the variant (mark it enabled, which
            // clears any `{disabled:true}`); leave hidden_in_base untouched so
            // Base is never affected. Staged — visible instantly, persists on
            // Save. Silent: the edge appearing is the feedback. Re-anchoring is
            // safe here: a hidden_in_base row never renders in Base, so the
            // handle change can't move a line Base is showing.
            const updatedEdges = anchor
              ? edges.map((e) => (e.id === existingId ? withAnchor(e) : e))
              : edges;
            if (anchor) {
              setEdges(updatedEdges as any);
              setHasUnsavedChanges(true);
            }
            enableOnVariant('edge', existingId, editScope);
            navigation.setSelectedEdge(
              (updatedEdges.find((e) => e.id === existingId) as any) || null,
            );
            return;
          }

          // ── Redraw over a BASE edge the ACTIVE variant deleted ──
          // A live base edge with `{disabled:true}` in this variant's
          // edge_overrides is invisible here, yet still occupies the pair
          // (one bidirectional row per pair) — so without this the draw
          // dead-ends in the duplicate check / an invisible re-anchor.
          // Drawing over it makes the VARIANT take ownership: stage a content
          // override (the base action-set structure with EMPTIED actions), so
          // the edge comes back as a variant edge — v chip, its own empty
          // actions to author — while Base keeps its edge and actions
          // untouched. NOT a bare un-disable (that resurrected the BASE edge
          // with base actions and no chip). A content entry also survives
          // compose, which drops marker-only `{enabled:true}` entries — the
          // chip keys off the composed map. Staged, silent.
          if (editScope !== null) {
            const existingAny = edges.find(
              (e) =>
                (e.source === src && e.target === tgt) ||
                (e.source === tgt && e.target === src),
            );
            const entry = existingAny
              ? effectiveOverrideMap(editScope, 'edge_overrides')[existingAny.id]
              : undefined;
            if (existingAny && entry?.disabled === true) {
              const emptiedBaseSets: any[] = (
                ((existingAny.data as any)?.action_sets || []) as any[]
              ).map((as: any) => ({
                ...as,
                actions: [],
                retry_actions: [],
                failure_actions: [],
              }));
              // Drawn against the base row's stored direction → remember it on
              // the entry so this variant's selection panels present the
              // drawn direction first (display only; see EdgeVariantOverride).
              const drawnReversed = existingAny.source !== src;
              // The drawn handles go on the VARIANT entry (per-variant routing,
              // like node positions) — never on the shared base row, which Base
              // renders (base_5.28 re-routing incident, 2026-07-24).
              const anchor = reanchorEdgeToDrawnHandles(existingAny as any, connection);
              stageOverrideEdit('edge', editScope, {
                [existingAny.id]: {
                  ...(emptiedBaseSets.length > 0
                    ? { action_sets: JSON.parse(JSON.stringify(emptiedBaseSets)) }
                    : { enabled: true }),
                  ...(drawnReversed ? { drawn_reversed: true } : {}),
                  ...(anchor || {}),
                },
              });
              navigation.setSelectedEdge(existingAny as any);
              return;
            }

            // ── Visible SHARED base edge redrawn while on a variant ──
            // Store the drawn handles + direction on the VARIANT's override
            // entry, NEVER on the base row. Falling through to onConnect's
            // duplicate re-anchor rewrote the shared row's handles, re-routing
            // Base's canvas (persisted in the base_5.28 incident, 2026-07-24).
            // Per-variant node layouts make per-variant routing legitimate —
            // same rationale as per-variant node positions.
            if (existingAny && (existingAny.data as any)?.hidden_in_base !== true) {
              const prevEntry = (entry || {}) as any;
              // Compare against what THIS variant currently renders (its own
              // handle override if present, else the row's) so redrawing back
              // to the row's sides clears correctly instead of no-opping.
              const anchor = reanchorEdgeToDrawnHandles(
                {
                  source: existingAny.source,
                  sourceHandle: prevEntry.sourceHandle ?? existingAny.sourceHandle,
                  targetHandle: prevEntry.targetHandle ?? existingAny.targetHandle,
                },
                connection,
              );
              const drawnReversed = existingAny.source !== src;
              const nextEntry: any = { ...prevEntry, ...(anchor || {}) };
              if (drawnReversed) nextEntry.drawn_reversed = true;
              else delete nextEntry.drawn_reversed;
              if (JSON.stringify(nextEntry) !== JSON.stringify(prevEntry)) {
                stageOverrideEdit('edge', editScope, { [existingAny.id]: nextEntry });
              }
              navigation.setSelectedEdge(existingAny as any);
              return;
            }
          }
        }

        // Pass isConditional flag based on Shift key state
        const enhancedConnection = {
          ...connection,
          isConditional: isShiftHeld, // Hold Shift to create conditional edge (BLUE, shared actions)
        };

        if (isShiftHeld) {
          console.log('[@NavigationEditor] 🔷 Creating CONDITIONAL edge (Shift held) - will share actions with siblings');
        } else {
          console.log('[@NavigationEditor] ⚪ Creating REGULAR edge - unique action sets');
        }

        // onConnect returns the ids of the edge(s) it actually created ([] when
        // it rejected the connection). The ids MUST come from this return value:
        // a previous build tried to collect them from inside a setEdges updater
        // and read them on the next line — React runs updaters at flush, not
        // inline, so the list was always empty and the whole variant block
        // below silently never ran (BUG-0014's "invisible edge, no toast").
        const createPromise = onConnect(enhancedConnection);

        // editScope is the single variant being authored (null for base, and
        // null during a composition preview — which is read-only, so onConnect
        // won't fire then anyway). New edges become variant-only via the
        // additive `{enabled: true}` marker on that variant.
        if (editScope !== null) {
          void (async () => {
            const newEdgeIds = (await createPromise) || [];
            if (newEdgeIds.length === 0) return;

            // Mark the new edge(s) hidden_in_base=true — this is what makes the
            // row variant-only, drives the "v" badge, and is captured correctly
            // if the user saves immediately.
            (setEdges as any)((current: any[]) => {
              if (!Array.isArray(current)) return current;
              return current.map((e: any) =>
                newEdgeIds.includes(e.id)
                  ? { ...e, data: { ...(e.data || {}), hidden_in_base: true } }
                  : e,
              );
            });
            // Stage the `{enabled:true}` marker on the active variant. The
            // marker is REQUIRED — composeEdgeOverrides hides a hidden_in_base
            // edge that no applied variant enables. Staged edits feed the
            // compose input directly, so the edge is visible IMMEDIATELY with
            // its "v" badge, and the marker persists on the SAME Save as the
            // edge row (no more marker-without-row / row-without-marker skew).
            const enableEdits: Record<string, any> = {};
            for (const id of newEdgeIds) enableEdits[id] = { enabled: true };
            stageOverrideEdit('edge', editScope, enableEdits);
          })();
        }
      },
      [onConnect, isShiftHeld, edges, editScope, isComposition, registeredVariants, navigation, enableOnVariant, stageOverrideEdit, effectiveOverrideMap, setEdges, setHasUnsavedChanges, showToastError]
    );

    // Memoize the AV panel collapsed change handler to prevent infinite loops
    const handleAVPanelCollapsedChange = useCallback((isCollapsed: boolean) => {
      setIsAVPanelCollapsed(isCollapsed);
    }, []);

    // Handle capture mode changes from AV components
    const handleCaptureModeChange = useCallback((mode: 'stream' | 'screenshot' | 'video') => {
      setCaptureMode(mode);
      console.log('[@NavigationEditor] Capture mode changed to:', mode);
    }, []);

    // Handle AV panel minimized changes
    const handleAVPanelMinimizedChange = useCallback((isMinimized: boolean) => {
      setIsAVPanelMinimized(isMinimized);
      console.log('[@NavigationEditor] AV panel minimized changed to:', isMinimized);
    }, []);

    // Handle mobile orientation changes
    const handleMobileOrientationChange = useCallback((isLandscape: boolean) => {
      setIsMobileOrientationLandscape(isLandscape);
    }, []);



    // Handle opening goto panel
    const handleOpenGotoPanel = useCallback((node: UINavigationNodeType) => {
      setSelectedNodeForGoto(node);
      setShowGotoPanel(true);
    }, []);

    // Handle closing goto panel
    const handleCloseGotoPanel = useCallback(() => {
      setShowGotoPanel(false);
      setSelectedNodeForGoto(null);
    }, []);

    // Handle metrics modal
    const handleOpenMetricsModal = useCallback(() => {
      setShowMetricsModal(true);
    }, []);

    const handleCloseMetricsModal = useCallback(() => {
      setShowMetricsModal(false);
    }, []);

    // Handle metrics notification actions
    const handleCloseMetricsNotification = useCallback(() => {
      // This will be called when the toast is minimized
      // No action needed - the toast component handles minimization internally
    }, []);

    // Helper functions using new normalized API
    const loadTreeForUserInterface = useCallback(
      async (userInterfaceId: string) => {
        try {
          // Pause history recording during tree load to prevent system changes from being undoable
          navigation.pauseHistoryRecording();

          // Use the hook's loadTreeByUserInterface which includes metrics
          // for the active viewing scope (NULL = base, otherwise the variant).
          const result = await loadTreeByUserInterface(userInterfaceId, {
            includeMetrics: true,
            variant: viewingScope,
          });

          // If metrics were included, store them for useMetrics hook
          if (result?.metrics) {
            console.log('[@NavigationEditor:loadTreeForUserInterface] ✅ Capturing metrics from combined endpoint');
            setPreloadedMetrics(result.metrics);
          }

          // Reset history for the new tree (prevents cross-tree undo operations)
          navigation.resetHistory();
        } catch (error) {
          console.error('[@NavigationEditor:loadTreeForUserInterface] Error loading tree:', error);
        } finally {
          // Always resume history recording
          navigation.resumeHistoryRecording();
        }
      },
      [loadTreeByUserInterface, setPreloadedMetrics, navigation, viewingScope],
    );

    // When the canvas viewing scope changes (Base ↔ variant), refetch ONLY the
    // metrics so the Edge Selection panel and node confidence reflect the
    // active scope's averages. Switching the variant chip is a pure VIEW change
    // — the variant overrides are already applied client-side by useResolvedTree
    // from data in memory — so we must NOT reload the tree topology here. Using
    // loadTreeByUserInterface would call setNodes/setActualTreeId and snap the
    // canvas back to the ROOT tree, leaving the breadcrumb stranded in whatever
    // subtree the user was in. loadTreeMetricsByUserInterface returns just the
    // per-scope metrics map and never touches the displayed tree, so the user
    // stays exactly where they are (root or nested). Seed the ref with the
    // initial viewingScope so the initial-load effect handles mount on its own
    // — this effect should only run for genuine scope *changes*.
    const lastFetchedVariantRef = useRef<string | null>(viewingScope);
    useEffect(() => {
      if (!userInterface?.id) return;
      if (lastFetchedVariantRef.current === viewingScope) return;
      lastFetchedVariantRef.current = viewingScope;

      (async () => {
        try {
          const metrics = await navigationConfig.loadTreeMetricsByUserInterface(
            userInterface.id,
            viewingScope,
          );
          setPreloadedMetrics(metrics ?? null);
        } catch (err) {
          console.error('[@NavigationEditor:viewingScope-refetch] Error:', err);
        }
      })();
    }, [viewingScope, userInterface?.id, navigationConfig, setPreloadedMetrics]);

    // Restore viewingScope from localStorage on userInterface load. Keyed per UI
    // so each interface remembers its own last-used variant. Does NOT depend on
    // registeredVariants (validation lives in a separate reactive effect below)
    // — async list arrivals must not re-trigger this restore-on-load.
    useEffect(() => {
      const uiId = userInterface?.id;
      if (!uiId) return;
      if (viewingScopeRestoredForUi.current === uiId) return;
      viewingScopeRestoredForUi.current = uiId;
      try {
        const stored = localStorage.getItem(`nav-editor-variant:${uiId}`);
        if (stored) setViewingScope(stored);
      } catch {
        // localStorage unavailable (private mode / storage quota) — fall back to base.
      }
    }, [userInterface?.id]);

    // Drop the restored variant if it's no longer registered (e.g. deleted from
    // another tab). Skip while the list is still empty — that's the loading
    // state, not a confirmed "no variants exist" — otherwise a slow variants
    // fetch would clobber a valid stored value.
    useEffect(() => {
      if (!viewingScope) return;
      if (registeredVariants.length === 0) return;
      // viewingScope may be a composition ('a+b'); every component must still
      // exist. Drop only the components that no longer exist (re-canonicalize),
      // so deleting one variant of a composition keeps the rest.
      const names = new Set(registeredVariants.map((v) => v.name));
      const stillValid = parseVariantList(viewingScope).filter((c) => names.has(c));
      const next = stillValid.length ? [...stillValid].sort().join('+') : null;
      if (next !== viewingScope) setViewingScope(next);
    }, [viewingScope, registeredVariants]);

    // Persist viewingScope to localStorage. Gated on restore having run for the
    // current UI so the initial `null` doesn't overwrite a stored value before
    // the restore effect has had a chance to read it.
    useEffect(() => {
      const uiId = userInterface?.id;
      if (!uiId) return;
      if (viewingScopeRestoredForUi.current !== uiId) return;
      try {
        if (viewingScope) {
          localStorage.setItem(`nav-editor-variant:${uiId}`, viewingScope);
        } else {
          localStorage.removeItem(`nav-editor-variant:${uiId}`);
        }
      } catch {
        // localStorage unavailable — drop silently; restore on next mount will simply yield base.
      }
    }, [viewingScope, userInterface?.id]);


    // Memoize the selectedHost to prevent unnecessary re-renders
    const stableSelectedHost = useMemo(() => selectedHost, [selectedHost]);

    // Centralized reference management - both verification references and actions
    const { setControlState, setUserinterfaceName } = useDeviceData();

    // Set control state in device data context when it changes
    useEffect(() => {
      setControlState(stableSelectedHost, selectedDeviceId, isControlActive);
    }, [stableSelectedHost, selectedDeviceId, isControlActive, setControlState]);

    // Set userinterface name for optimal reference filtering
    useEffect(() => {
      if (userInterface?.name) {
        console.log('[@NavigationEditor] Setting userinterface name for optimal filtering:', userInterface.name);
        setUserinterfaceName(userInterface.name);
      }
      return () => {
        // Clear on unmount
        setUserinterfaceName(null);
      };
    }, [userInterface?.name, setUserinterfaceName]);

    // Auto-guard against incompatible device selections when userInterface changes
    useDeviceCompatibilityGuard({
      userInterface,
      selectedHost,
      selectedDeviceId,
      isControlActive,
      onReleaseControl: handleDisconnectComplete,
      onClearSelection: () => handleDeviceSelect(null, null),
    });

    // Focus node view handler — center ONCE per focus target, and ONLY when the destination
    // is in a subtree (we had to enter it to show the node). Without this it re-fired on every
    // `nodes` rebuild (each screenshot-context reload recreates `nodes`) → an endless recenter
    // loop, and it yanked the user's view even for nodes already in the current/root tree.
    const focusCenteredRef = useRef<string | null>(null);
    useEffect(() => {
      if (!focusNodeId || !navigation.reactFlowInstance) return;
      if (focusCenteredRef.current === focusNodeId) return; // already handled this target
      const focusedNode = nodes.find((node) => node.id === focusNodeId);
      if (!focusedNode) return; // not in the current tree yet (mid subtree switch) — wait for reload
      focusCenteredRef.current = focusNodeId; // mark handled before centering so rebuilds don't refire

      // Only recenter when the destination lives in a subtree; never force-move the view for a
      // node already shown in the current/root tree.
      if (navigation.parentChain.length === 0) return;

      console.log(`[@NavigationEditor] Focusing view on subtree node: ${focusedNode.data.label || focusNodeId}`);
      const nodeWidth = (focusedNode as any).width || 200;
      const nodeHeight = (focusedNode as any).height || 100;
      setTimeout(() => {
        navigation.reactFlowInstance?.setCenter(
          focusedNode.position.x + nodeWidth / 2,
          focusedNode.position.y + nodeHeight / 2,
          { zoom: 1.2, duration: 800 }
        );
      }, 100);
    }, [focusNodeId, nodes, navigation.reactFlowInstance, navigation.parentChain.length]);

    // ========================================
    // 1. INITIALIZATION & REFERENCES
    // ========================================

    // Unified save function - works for both root and nested trees
    const handleSaveToConfig = useCallback(
      async () => {
        try {
          const treeType = isNested && currentLevel ? 'nested' : 'root';
          const contextInfo = navigation.parentChain.length > 0 
            ? `(subtree depth: ${navigation.parentChain.length})` 
            : '(root level)';
          
          console.log(`[@NavigationEditor] 💾 Saving ${treeType} tree: ${actualTreeId} ${contextInfo}`);
          console.log(`[@NavigationEditor] 💾 Tree contains: ${nodes.length} nodes, ${edges.length} edges`);

          // Persist ALL staged variant changes (override edits + node positions)
          // alongside the base tree save (they live in the variant override maps).
          const variantPosOk = await flushVariantPositionsRef.current();

          // All tree saves now use the same unified batch API - saves to actualTreeId (current tree context)
          await saveTreeWithStateUpdate(actualTreeId!);

          // saveTreeWithStateUpdate clears the unsaved flag; if a variant position
          // PUT failed, re-arm it so the user knows to retry.
          if (!variantPosOk) setHasUnsavedChanges(true);

          console.log(`[@NavigationEditor] ✅ ${treeType} tree saved successfully: ${actualTreeId}`);
        } catch (error) {
          console.error('Error saving tree:', error);
          throw error;
        }
      },
      [isNested, currentLevel, actualTreeId, nodes.length, edges.length, saveTreeWithStateUpdate, setHasUnsavedChanges, navigation.parentChain.length],
    );

    // Wrapper for the header component (matches expected signature)
    const handleSaveForHeader = useCallback(() => {
      return handleSaveToConfig();
    }, [handleSaveToConfig]);



    // Lifecycle refs to prevent unnecessary re-renders

    // Clean approach: Resolve userInterface by name from treeName
    const { getUserInterfaceByName } = useUserInterface();
    const location = useLocation();
    const seededInterface = (location.state as { userInterface?: { id: string; name: string; models: string[]; mode?: 'dev' | 'prod' } } | null)?.userInterface;
    // Dev/prod scope: the name is shared between both rows, so deep links carry
    // ?mode=prod. Route state (mode on the seeded interface) wins when present.
    const uiMode: 'dev' | 'prod' =
      seededInterface?.mode === 'prod' ||
      new URLSearchParams(location.search).get('mode') === 'prod'
        ? 'prod'
        : 'dev';
    const isProdView = uiMode === 'prod';

    useEffect(() => {
      const resolveUserInterface = async () => {
        if (!treeName) return;

        // Resolution key includes the mode: dev and prod share a name, and
        // toggling the scope must re-resolve to the other row's id.
        const resolveKey = `${treeName}::${uiMode}`;

        // Prevent duplicate resolution for the same treeName+mode
        if (lastResolvedTreeName.current === resolveKey) return;

        // If we already have the correct userInterface, skip
        if (userInterface?.name === treeName && (userInterface.mode || 'dev') === uiMode) return;

        // Skip the network round-trip when the caller already handed us the userInterface via route state
        if (seededInterface && seededInterface.name === treeName && (seededInterface.mode || 'dev') === uiMode) {
          lastResolvedTreeName.current = resolveKey;
          setUserInterfaceFromProps(seededInterface);
          console.log(`[@component:NavigationEditor] Using userInterface from route state: ${seededInterface.name} (ID: ${seededInterface.id}, mode: ${uiMode})`);
          return;
        }

        try {
          console.log(`[@component:NavigationEditor] Resolving userInterface for treeName: ${treeName} (mode: ${uiMode})`);

          // Mark as being resolved to prevent duplicates
          lastResolvedTreeName.current = resolveKey;

          const resolvedInterface = await getUserInterfaceByName(treeName, uiMode);
          setUserInterfaceFromProps(resolvedInterface);

          console.log(`[@component:NavigationEditor] Successfully resolved userInterface: ${resolvedInterface.name} (ID: ${resolvedInterface.id}, mode: ${uiMode})`);
        } catch (error) {
          console.error(`[@component:NavigationEditor] Failed to resolve userInterface for treeName ${treeName} (mode: ${uiMode}):`, error);
          // Reset on error so we can retry
          lastResolvedTreeName.current = null;
        }
      };

      resolveUserInterface();
    }, [treeName, userInterface?.name, userInterface?.mode, uiMode, setUserInterfaceFromProps, seededInterface]);

    // Clean approach: treeName is guaranteed to exist from NavigationEditor

    // Effect to load tree when tree name changes
    useEffect(() => {
      // Only load if we have a tree name and userInterface is loaded
      if (userInterface?.id && !isLoadingInterface) {
        // Check if we already loaded this userInterface to prevent infinite loops
        if (lastLoadedTreeId.current === userInterface.id) {
          return;
        }
        
        if (isNested && navigation.parentChain.some(t => t.treeId === userInterface.id)) {
          console.log(`[@component:NavigationEditor] Tree already in parent chain: ${userInterface.id}`);
          lastLoadedTreeId.current = userInterface.id;
          return;
        }
        
        lastLoadedTreeId.current = userInterface.id;

        console.log(`[@component:NavigationEditor] Loading tree for userInterface: ${userInterface.id}`);
        loadTreeForUserInterface(userInterface.id).then((result: any) => {
          if (result?.tree?.id && !isNested && stack.length === 0) {
            const actualTreeUuid = result.tree.id;
            setActualTreeId(actualTreeUuid);
          }
        }).catch((error: any) => {
          console.error(`[@component:NavigationEditor] Failed to load tree:`, error);
        });

        // No auto-unlock for navigation tree - keep it locked for editing session
      }
    }, [userInterface?.id, isLoadingInterface, loadTreeForUserInterface, navigation, isNested, stack.length, setActualTreeId]);

    // Simple update handlers - complex validation logic moved to device control component
    const handleUpdateNode = useCallback(
      (nodeId: string, updatedData: any) => {
        // A capture (the patch carries `screenshot`) made while viewing a variant
        // is persisted to THAT variant's node_overrides entry, never base — so
        // variants don't contaminate each other (and the R2 object is already
        // variant-suffixed). The local update below is display-only; base
        // node.data is persisted solely by the variant-aware dialog save.
        if (viewingScope && 'screenshot' in updatedData) {
          const v = registeredVariants.find((x) => x.name === viewingScope);
          if (v) {
            const nextMap: Record<string, any> = { ...((v.node_overrides as any) || {}) };
            const entry: any = { ...(nextMap[nodeId] || {}) };
            for (const k of ['screenshot', 'screenshot_timestamp', 'fingerprint', 'dom']) {
              if (updatedData[k] !== undefined) entry[k] = updatedData[k];
            }
            nextMap[nodeId] = entry;
            void updateVariantOverrides(viewingScope, { node_overrides: nextMap });
          }
        }
        const updatedNodes = nodes.map((node) =>
          node.id === nodeId ? { ...node, data: { ...node.data, ...updatedData } } : node,
        );
        setNodes(updatedNodes);
        if (selectedNode?.id === nodeId) {
          setSelectedNode({ ...selectedNode, data: { ...selectedNode.data, ...updatedData } });
        }
        setHasUnsavedChanges(true);
      },
      [
        nodes,
        setNodes,
        setSelectedNode,
        setHasUnsavedChanges,
        selectedNode,
        viewingScope,
        registeredVariants,
        updateVariantOverrides,
      ],
    );

    // Wrapper for node form submission to handle the form data
    const handleNodeFormSubmitWrapper = useCallback(() => {
      if (nodeForm) {
        console.log(
          '[@component:NavigationEditor] Submitting node form with verifications:',
          nodeForm.verifications?.length || 0,
          nodeForm.verifications,
        );
        saveNodeWithStateUpdate(nodeForm);
        console.log('[@component:NavigationEditor] Node form submitted successfully');
      }
    }, [nodeForm, saveNodeWithStateUpdate]);

    // Scope-aware Add Node. With the per-variant overrides model:
    //   - Base scope: row is born with `hidden_in_base: false` (default).
    //   - Variant scope X: row is born with `hidden_in_base: true`, AND
    //     every OTHER registered variant's `node_overrides[<new_id>]` is set
    //     to `{disabled: true}` so the row is invisible everywhere except X.
    const handleAddNewNodeWrapper = useCallback(() => {
      // A composition is a read-only preview — there is no single variant to
      // own a new row. Authors must pick one variant to add to.
      if (isComposition) {
        showToastError('Select a single variant (not a composition) to add a node.');
        return;
      }
      const isVariantScope = editScope !== null;

      // Drop the new node at the center of what the user is currently looking
      // at, instead of a fixed off-screen position. Convert the viewport
      // center (screen coords) into flow coords via the ReactFlow instance.
      let position = { x: 250, y: 250 };
      const instance = navigation.reactFlowInstance;
      const wrapper = reactFlowWrapper.current;
      if (instance && wrapper) {
        const bounds = wrapper.getBoundingClientRect();
        position = instance.screenToFlowPosition({
          x: bounds.left + bounds.width / 2,
          y: bounds.top + bounds.height / 2,
        });
      }

      const newId: string = addNewNode(
        'screen',
        position,
        isVariantScope ? { hidden_in_base: true } : undefined,
      );
      if (isVariantScope && editScope && newId) {
        // Stage the enable marker — node visible immediately (compose hides a
        // hidden_in_base row until its variant enables it), persists on Save.
        enableOnVariant('node', newId, editScope);
        showToastSuccess(
          `Added node visible only on variant '${editScope}'.`,
        );
      }
    }, [
      addNewNode,
      isComposition,
      editScope,
      enableOnVariant,
      showToastSuccess,
      showToastError,
      navigation.reactFlowInstance,
      reactFlowWrapper,
    ]);

    // A row is "variant-only on the current viewing scope" when it is visible
    // ONLY while `currentVariant` is applied — deleting it there removes it from
    // everywhere, so we DB-delete instead of just hiding. Handles BOTH models
    // (see docs/agent/navigation/VARIANT.md "Composition"):
    //   - new-style (additive): no OTHER variant ENABLES the row (an entry with
    //     `enabled: true` or non-empty content).
    //   - legacy (cross-disable): no OTHER variant is an owner — i.e. for a row
    //     disabled somewhere, an absent entry means that variant owns/shows it.
    // We bias toward "disable on this scope" (safe — leaves a hidden orphan) and
    // only DB-delete when confident the row is exclusive to this variant.
    const isVariantOnlyOnCurrentScope = useCallback(
      (
        rowKind: 'node' | 'edge',
        rowId: string,
        rowData: { hidden_in_base?: boolean } | undefined | null,
        currentVariant: string,
      ): boolean => {
        if (rowData?.hidden_in_base !== true) return false;
        const mapOf = (v: any) =>
          (rowKind === 'node' ? v?.node_overrides : v?.edge_overrides) || {};
        const contentKey = rowKind === 'node' ? 'verifications' : 'action_sets';
        const enables = (entry: any) =>
          !!entry &&
          entry.disabled !== true &&
          (entry.enabled === true ||
            (Array.isArray(entry[contentKey]) && entry[contentKey].length > 0));

        const currentVar = registeredVariants.find((v) => v.name === currentVariant);
        const currentEntry = mapOf(currentVar)[rowId];
        if (currentEntry && currentEntry.disabled === true) return false;

        // Legacy detection needs to know if the row is cross-disabled anywhere.
        const crossDisabled = registeredVariants.some(
          (v) => mapOf(v)[rowId]?.disabled === true,
        );

        for (const v of registeredVariants) {
          if (!v?.name || v.name === currentVariant) continue;
          const entry = mapOf(v)[rowId];
          if (enables(entry)) return false; // new-style: another variant shows it
          if (crossDisabled && !entry) return false; // legacy: absent = co-owner
        }
        return true;
      },
      [registeredVariants],
    );

    // Scope-aware per-ACTION-SET delete for the Edge Selection panel's trash
    // icons. The base `deleteEdgeDirection` is variant-blind (it mutates the
    // base edge and saves it, deleting the whole base edge when both directions
    // empty). Under a variant / composition scope we must instead remove that
    // one action_set from EACH selected variant's `edge_overrides` full-
    // replacement `action_sets` array — base and other variants untouched.
    //   - variant has no entry yet → start from a deep copy of the base
    //     action_sets, drop the target set.
    //   - result still non-empty → write `{action_sets: [...]}` (drop any
    //     stale `disabled` — the two are mutually exclusive server-side).
    //   - result empty (deleted the last direction) → an empty array would
    //     fall through to base (resolver rule), so hide the edge on the variant
    //     with `{disabled: true}` instead.
    // Matches VARIANT.md: variant data is a full per-variant `action_sets`
    // replacement; topology (conditional links, endpoints) stays base-only, so
    // — unlike the base path — we do NOT touch conditional siblings here.
    const deleteEdgeDirectionScoped = useCallback(
      (edgeId: string, actionSetId: string) => {
        // Base scope → existing base behaviour unchanged.
        if (viewingComponents.length === 0) {
          return navigation.deleteEdgeDirection(edgeId, actionSetId);
        }
        const edge = edges.find((e) => e.id === edgeId);
        if (!edge) return undefined;
        const baseActionSets: any[] = (edge.data as any)?.action_sets || [];

        const targets = viewingComponents;

        // An action set with no actions at all is an empty husk — an edge
        // whose remaining sets are ALL empty is useless and should go away
        // entirely, not linger as a bare line with stale panels.
        const isEmptyActionSet = (as: any) =>
          (!as?.actions || as.actions.length === 0) &&
          (!as?.retry_actions || as.retry_actions.length === 0) &&
          (!as?.failure_actions || as.failure_actions.length === 0);

        // No confirm dialog — the base-scope direction delete doesn't ask
        // either, and the panel's Delete button is explicit enough. All
        // mutations STAGE (yellow Save) and persist on Save.

        // Variant-only edge left with no real actions after this delete →
        // remove the WHOLE edge (it exists nowhere else): local removal +
        // staged marker cleanup, everything persists on Save.
        if (
          targets.length === 1 &&
          isVariantOnlyOnCurrentScope('edge', edgeId, edge.data as any, targets[0])
        ) {
          const existingEntry = effectiveOverrideMap(targets[0], 'edge_overrides')[edgeId];
          const currentActionSets: any[] =
            existingEntry &&
            Array.isArray(existingEntry.action_sets) &&
            existingEntry.action_sets.length > 0
              ? existingEntry.action_sets
              : baseActionSets;
          const remaining = currentActionSets.filter((as) => as?.id !== actionSetId);
          if (remaining.every(isEmptyActionSet) && remaining.length !== currentActionSets.length) {
            (setEdges as any)((current: any[]) =>
              Array.isArray(current) ? current.filter((e) => e.id !== edgeId) : current,
            );
            navigation.setSelectedEdge(null);
            setHasUnsavedChanges(true);
            for (const vv of registeredVariants) {
              if (edgeId in effectiveOverrideMap(vv.name, 'edge_overrides')) {
                stageOverrideEdit('edge', vv.name, { [edgeId]: null });
              }
            }
            return undefined;
          }
        }

        let hiddenOnScope = false;
        for (const name of targets) {
          const existingMap = effectiveOverrideMap(name, 'edge_overrides');
          const existingEntry = existingMap[edgeId];
          // Current resolved action_sets for this variant: its own
          // override if it already replaces base, else base.
          const currentActionSets: any[] =
            existingEntry &&
            Array.isArray(existingEntry.action_sets) &&
            existingEntry.action_sets.length > 0
              ? existingEntry.action_sets
              : baseActionSets;
          // CLEAR the deleted direction in place — do NOT remove it.
          // action_sets is positional (index 0 = forward source→target,
          // index 1 = reverse) and the panels label directions by index;
          // filtering the set out slid the surviving reverse set into
          // index 0, so it displayed with INVERTED direction labels.
          // Matches the base-scope delete, which also clears in place.
          let matched = false;
          const nextActionSets = currentActionSets.map((as) => {
            if (as?.id !== actionSetId) return as;
            matched = true;
            return { ...as, actions: [], retry_actions: [], failure_actions: [] };
          });
          // Nothing matched (e.g. the phantom 'fallback' reverse) → skip
          // so we don't mint a spurious override / "v" chip.
          if (!matched) continue;

          let nextEntry: any;
          if (nextActionSets.some((as) => !isEmptyActionSet(as))) {
            nextEntry = {
              ...(existingEntry || {}),
              action_sets: JSON.parse(JSON.stringify(nextActionSets)),
            };
            delete nextEntry.disabled;
          } else {
            // No real actions left in any direction → hide the edge on
            // this variant instead of keeping an empty husk.
            nextEntry = { disabled: true };
            hiddenOnScope = true;
          }
          stageOverrideEdit('edge', name, { [edgeId]: nextEntry });
        }
        // The edge is gone from this scope — close its lingering panels.
        if (hiddenOnScope) navigation.setSelectedEdge(null);
        return undefined;
      },
      [
        viewingComponents,
        edges,
        navigation,
        registeredVariants,
        effectiveOverrideMap,
        stageOverrideEdit,
        isVariantOnlyOnCurrentScope,
        setEdges,
        setHasUnsavedChanges,
      ],
    );

    const wrappedDeleteSelected = useCallback(async () => {
      // Composition (>1 variant): whole-edge/node delete disables the row on
      // EACH selected variant (base and unselected variants keep it). Per-
      // action-set deletes go through deleteEdgeDirectionScoped instead.
      if (isComposition) {
        const node = selectedNode;
        const edge = selectedEdge;
        if (!node && !edge) return deleteSelected();
        const target: 'node' | 'edge' = node ? 'node' : 'edge';
        const id = node?.id || edge?.id || '?';
        variantConfirm.confirm({
          title: `Disable ${target} on ${viewingComponents.length} variants?`,
          message: `This ${target} will be hidden on ${viewingComponents.join(
            ', ',
          )}. Base and other variants keep it.`,
          confirmText: `Disable on ${viewingComponents.length} variants`,
          confirmColor: 'warning',
          showDismiss: true,
          onConfirm: () => {
            // Staged — persists on Save, Discard reverts.
            for (const name of viewingComponents) {
              stageOverrideEdit(target, name, { [id]: { disabled: true } });
            }
            if (node) setSelectedNode(null);
            if (edge) navigation.setSelectedEdge(null);
          },
        });
        return undefined;
      }
      // Base scope or no selection → fall through to existing behaviour.
      if (editScope === null) {
        return deleteSelected();
      }
      const node = selectedNode;
      const edge = selectedEdge;
      if (!node && !edge) {
        return deleteSelected();
      }

      const target: 'node' | 'edge' = node ? 'node' : 'edge';
      const id = node?.id || edge?.id || '?';
      const data = (node?.data || edge?.data || {}) as any;
      const variantOnly = isVariantOnlyOnCurrentScope(target, id, data, editScope);

      if (variantOnly) {
        // The row only exists on this variant — deleting it from here means it
        // disappears entirely. DB delete via the existing path.
        variantConfirm.confirm({
          title: `Delete ${target}?`,
          message: `This ${target} only exists on variant '${editScope}' and will be removed entirely.`,
          confirmText: 'Delete',
          confirmColor: 'error',
          showDismiss: true,
          onConfirm: () => {
            deleteSelected();
          },
        });
        return undefined;
      }

      // Row is visible to base or another variant — just disable on this scope.
      variantConfirm.confirm({
        title: `Disable ${target} on '${editScope}'?`,
        message: `Other variants and base will keep seeing this ${target}.`,
        confirmText: `Disable on '${editScope}'`,
        confirmColor: 'warning',
        showDismiss: true,
        onConfirm: () => {
          // Staged — persists on Save, Discard reverts.
          stageOverrideEdit(target, editScope, { [id]: { disabled: true } });
          if (node) setSelectedNode(null);
          if (edge) navigation.setSelectedEdge(null);
        },
      });
      return undefined;
    }, [
      isComposition,
      viewingComponents,
      editScope,
      selectedNode,
      selectedEdge,
      deleteSelected,
      variantConfirm,
      setSelectedNode,
      navigation,
      stageOverrideEdit,
      isVariantOnlyOnCurrentScope,
    ]);

    // Keep the ref pointing at the latest wrappedDeleteSelected so the
    // keyboard listener can use it without re-binding.
    useEffect(() => {
      wrappedDeleteSelectedRef.current = wrappedDeleteSelected;
    }, [wrappedDeleteSelected]);

    // Auto-layout handler - vertical layout (top to bottom)
    const handleAutoLayout = useCallback(() => {
      const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
        nodes as any,
        edges as any,
        { direction: 'TB' } // Top to Bottom
      );
      setNodes(layoutedNodes as any);
      setEdges(layoutedEdges as any);
      setHasUnsavedChanges(true);
      
      // Fit view after layout
      if (navigation.reactFlowInstance) {
        setTimeout(() => {
          navigation.reactFlowInstance?.fitView({ padding: 0.2, duration: 300 });
        }, 100);
      }
    }, [nodes, edges, setNodes, setEdges, setHasUnsavedChanges, navigation.reactFlowInstance]);

    // Effect to trigger auto-layout after AI generation
    useEffect(() => {
      if (applyAutoLayoutFlag && nodes.length > 0 && actualTreeId) {
        const treeType = navigation.parentChain.length > 0 ? 'subtree' : 'root tree';
        const treeInfo = navigation.parentChain.length > 0 
          ? `subtree (${actualTreeId}, depth: ${navigation.parentChain.length})` 
          : `root tree (${actualTreeId})`;
        
        console.log(`[@NavigationEditor] 🎨 Triggering auto-layout after AI generation for ${treeInfo}`);
        console.log(`[@NavigationEditor] 🎨 Layout will be applied to ${nodes.length} nodes and ${edges.length} edges`);
        
        setTimeout(() => {
          handleAutoLayout();
          setApplyAutoLayoutFlag(false); // Reset flag
          
          // Auto-save after layout is applied to the CURRENT tree (root or subtree)
          console.log(`[@NavigationEditor] 💾 Auto-saving ${treeType} after layout to tree: ${actualTreeId}`);
          setTimeout(() => {
            if (!actualTreeId) {
              console.error(`[@NavigationEditor] ❌ Cannot save - actualTreeId is undefined!`);
              return;
            }
            
            handleSaveToConfig()
              .then(() => {
                console.log(`[@NavigationEditor] ✅ Auto-save completed for ${treeType}: ${actualTreeId}`);
              })
              .catch((error) => {
                console.error(`[@NavigationEditor] ❌ Auto-save failed for ${treeType}:`, error);
              });
          }, 2000); // Wait 2s to ensure layout positions are fully applied to ReactFlow
        }, 1000); // Small delay to ensure nodes are rendered
      } else if (applyAutoLayoutFlag && !actualTreeId) {
        console.error('[@NavigationEditor] ❌ Cannot apply auto-layout - actualTreeId is undefined!');
        setApplyAutoLayoutFlag(false);
      }
    }, [applyAutoLayoutFlag, nodes.length, edges.length, handleAutoLayout, handleSaveToConfig, actualTreeId, navigation.parentChain.length]);

    // ─── Per-variant node position (canvas-only topology override) ───────────
    // Position (x,y) is the ONE topology field that legitimately differs per
    // variant — the runtime NetworkX graph never reads it, so a per-variant
    // layout changes nothing about execution (see docs/agent/navigation/VARIANT.md
    // "Per-variant node position"). In a single-variant scope, a SHARED row is
    // draggable (useResolvedTree stamps `_variant_position_editable`); the drop
    // persists to that variant's `node_overrides[id].position` instead of the
    // pure base row.
    //
    // `variantPositionDraft` is the in-flight render overlay: while dragging a
    // shared node we drive its position through this local state (fed back into
    // the resolver below) so it follows the cursor WITHOUT mutating the base
    // `nodes` state. On drop we persist to the override and, once the refetched
    // variant carries the position, drop the draft entry (persisted value = the
    // single source of truth).
    const [variantPositionDraft, setVariantPositionDraft] = useState<
      Record<string, { x: number; y: number }>
    >({});

    // Node ids that, in the CURRENT scope, are repositionable into the variant
    // override rather than the base row: a single-variant scope (not base, not
    // composition), the row is shared (not `hidden_in_base` — those own their
    // position via the base save path), and not disabled on this variant.
    const positionEditableNodeIds = useMemo(() => {
      const set = new Set<string>();
      if (editScope === null || isComposition) return set;
      const v = registeredVariants.find((x) => x.name === editScope);
      const overrides = (v?.node_overrides as any) || {};
      for (const n of nodes as any[]) {
        if ((n.data as any)?.hidden_in_base === true) continue;
        if (overrides[n.id]?.disabled === true) continue;
        set.add(n.id);
      }
      return set;
    }, [editScope, isComposition, registeredVariants, nodes]);

    // Staged variant node-position moves, keyed by variant name → node id → pos.
    // Unlike base moves (which stage into `nodes`), variant positions belong to
    // the variant's override map — we accumulate the drops here and persist them
    // only when the user clicks Save (see flushVariantChanges, wired into
    // handleSaveToConfig), exactly like base. Keyed per-variant so switching the
    // canvas scope with unsaved moves never drops another variant's staged
    // positions. Discard clears this along with the render drafts.
    const pendingPosRef = useRef<Record<string, Record<string, { x: number; y: number }>>>({});
    // Persist ALL staged variant changes — override edits (enable/disable
    // markers, content, removals) AND node positions — in ONE PUT per variant,
    // merging over each variant's persisted maps so a co-edit never clobbers a
    // sibling (avoids the N-sequential-PUT race — see
    // docs/agent/navigation/VARIANT.md pitfall #5). Wired into
    // handleSaveToConfig; returns true only if every variant flushed cleanly.
    const flushVariantChanges = useCallback(async (): Promise<boolean> => {
      const pendingPos = pendingPosRef.current;
      pendingPosRef.current = {};
      const stagedEdits = stagedOverrideEditsRef.current;
      const variantNames = [
        ...new Set([...Object.keys(pendingPos), ...Object.keys(stagedEdits)]),
      ];
      if (variantNames.length === 0) return true;
      let allOk = true;
      const flushedPosIds: string[] = [];
      const flushedVariants: string[] = [];
      for (const variantName of variantNames) {
        const posMap = pendingPos[variantName] || {};
        const edits = stagedEdits[variantName];
        const hasEdits =
          !!edits &&
          (Object.keys(edits.node_overrides).length > 0 ||
            Object.keys(edits.edge_overrides).length > 0);
        if (Object.keys(posMap).length === 0 && !hasEdits) continue;
        const v = registeredVariants.find((x) => x.name === variantName);
        const nodeMap: Record<string, any> = { ...((v?.node_overrides as any) || {}) };
        const edgeMap: Record<string, any> = { ...((v?.edge_overrides as any) || {}) };
        if (edits) {
          for (const [id, entry] of Object.entries(edits.node_overrides)) {
            if (entry === null) delete nodeMap[id];
            else nodeMap[id] = entry;
          }
          for (const [id, entry] of Object.entries(edits.edge_overrides)) {
            if (entry === null) delete edgeMap[id];
            else edgeMap[id] = entry;
          }
        }
        for (const [id, pos] of Object.entries(posMap)) {
          nodeMap[id] = { ...(nodeMap[id] || {}), position: pos };
        }
        try {
          await updateVariantOverrides(
            variantName,
            { node_overrides: nodeMap, edge_overrides: edgeMap },
            { skipRefresh: true },
          );
          flushedPosIds.push(...Object.keys(posMap));
          flushedVariants.push(variantName);
        } catch (err) {
          console.error('[NavigationEditor] Failed to persist variant changes', err);
          showToastError(`Failed to save changes on variant '${variantName}'.`);
          allOk = false;
          // Re-stage this variant's positions so the next Save retries them
          // (its staged override edits are kept below — only flushed variants
          // are cleared).
          pendingPosRef.current[variantName] = {
            ...(pendingPosRef.current[variantName] || {}),
            ...posMap,
          };
        }
      }
      if (flushedVariants.length > 0) {
        await refreshVariants();
        // Persisted maps now carry these edits → drop the staged copies (the
        // refetched variant is the single source of truth).
        setStagedOverrideEdits((prev) => {
          const next = { ...prev };
          for (const name of flushedVariants) delete next[name];
          return next;
        });
      }
      // Same for flushed position drafts; failed ids keep their draft so the
      // node stays where the user dropped it.
      if (flushedPosIds.length) {
        setVariantPositionDraft((prev) => {
          const next = { ...prev };
          for (const id of flushedPosIds) delete next[id];
          return next;
        });
      }
      return allOk;
    }, [registeredVariants, updateVariantOverrides, refreshVariants, showToastError]);
    // Latest-flush ref so handleSaveToConfig (declared earlier) can invoke it
    // without a forward reference in its dependency array.
    const flushVariantPositionsRef = useRef(flushVariantChanges);
    useEffect(() => {
      flushVariantPositionsRef.current = flushVariantChanges;
    }, [flushVariantChanges]);

    // Discard drops ALL staged variant changes — moves, their render overlay,
    // and staged override edits — so the canvas reverts to the last-persisted
    // variant overrides, then runs the base discard.
    const handlePerformDiscard = useCallback(() => {
      pendingPosRef.current = {};
      setVariantPositionDraft({});
      setStagedOverrideEdits({});
      performDiscardChanges();
    }, [performDiscardChanges]);

    // Wrap onNodesChange to track position changes as unsaved changes.
    // Plain clicks emit `dragging: false` too, so we only flip the
    // unsaved-changes flag on the true→false transition that follows an
    // actual drag. The "structural changes apply to base" toast was removed
    // (added noise without value — the user can see the drag result and the
    // unsaved-changes indicator).
    //
    // Shared-node position drags in a variant scope are split off: they drive
    // the local draft (render) and persist to the variant override, and are
    // NEVER forwarded to the base `onNodesChange` (base rows stay position-pure).
    const isDraggingRef = useRef<boolean>(false);
    // Ref mirror of the draft overlay so the DROP handler can read the last
    // dragged coordinate synchronously: ReactFlow's drag-END change carries NO
    // `position` field ({type:'position', dragging:false}), so the drop must
    // fall back to the final cursor-follow position captured during the drag.
    // (Requiring `c.position` to classify the change used to send the drop
    // event down the base path — nothing was ever staged, the Save button
    // never armed, and Save persisted nothing while the canvas looked moved.)
    const variantPosLastRef = useRef<Record<string, { x: number; y: number }>>({});
    const wrappedOnNodesChange = useCallback(
      (changes: any) => {
        const variantPosChanges: any[] = [];
        const baseChanges: any[] = [];
        for (const c of changes) {
          if (c.type === 'position' && positionEditableNodeIds.has(c.id)) {
            variantPosChanges.push(c);
          } else {
            baseChanges.push(c);
          }
        }

        if (baseChanges.length) onNodesChange(baseChanges);

        if (variantPosChanges.length) {
          // Follow the cursor via the draft overlay (no base mutation).
          const moved = variantPosChanges.filter((c) => c.position);
          if (moved.length) {
            for (const c of moved) {
              variantPosLastRef.current[c.id] = { x: c.position.x, y: c.position.y };
            }
            setVariantPositionDraft((prev) => {
              const next = { ...prev };
              for (const c of moved) {
                next[c.id] = { x: c.position.x, y: c.position.y };
              }
              return next;
            });
          }
          // Stage the drop into the variant's pending map and arm the unsaved
          // indicator — mirroring base moves. Nothing is written back until the
          // user clicks Save (flushVariantChanges) or reverts via Discard.
          const drops = variantPosChanges.filter((c) => c.dragging === false);
          if (drops.length && editScope) {
            const map = pendingPosRef.current[editScope] || {};
            let staged = false;
            for (const c of drops) {
              const pos = c.position
                ? { x: c.position.x, y: c.position.y }
                : variantPosLastRef.current[c.id];
              if (!pos) continue; // plain click (no drag happened) — nothing to stage
              delete variantPosLastRef.current[c.id]; // consume: a later click can't re-stage it
              map[c.id] = pos;
              staged = true;
            }
            if (staged) {
              pendingPosRef.current[editScope] = map;
              setHasUnsavedChanges(true);
            }
          }
        }

        // Base-scope drag → unsaved-changes flag on drop. (Variant drags arm the
        // same flag from their own staging block above.)
        const startedDragging = baseChanges.some(
          (c: any) => c.type === 'position' && c.dragging === true,
        );
        if (startedDragging) {
          isDraggingRef.current = true;
        }

        const finishedDragging =
          isDraggingRef.current &&
          baseChanges.some((c: any) => c.type === 'position' && c.dragging === false);

        if (finishedDragging) {
          isDraggingRef.current = false;
          setHasUnsavedChanges(true);
        }
      },
      [
        onNodesChange,
        setHasUnsavedChanges,
        positionEditableNodeIds,
        editScope,
      ]
    );

    // ========================================
    // 7. RENDER
    // ========================================

    // State for edge labels
    const [edgeLabels, setEdgeLabels] = useState<{ fromLabel: string; toLabel: string }>({
      fromLabel: '',
      toLabel: '',
    });

    // Phase 4 §3.5 — apply variant resolution to canvas data when a variant
    // scope is selected. When viewingScope is null we render `nodes`/`edges`
    // verbatim (only `data.hidden_in_base` hides rows from base). When it is
    // a variant name, the resolver consults the variant's `node_overrides`
    // and `edge_overrides` maps — purely a view, never written back.
    // Compose the applied variants' override maps into ONE merged map (the same
    // pre-pass the backend runs). Routing single AND composite viewing through
    // compose keeps the canvas consistent with execution: new-style variant-only
    // rows don't leak into variants that don't enable them. compose([X]) is
    // equivalent to X's raw map for legacy data. See docs/agent/navigation/VARIANT.md.
    const activeVariantOverrides = useMemo(() => {
      if (viewingComponents.length === 0) return { nodeMap: null, edgeMap: null };
      // hidden_in_base ids from the raw canvas rows.
      const hiddenNodeIds = new Set<string>();
      const hiddenEdgeIds = new Set<string>();
      for (const n of nodes as any[]) if ((n.data as any)?.hidden_in_base === true) hiddenNodeIds.add(n.id);
      for (const e of edges as any[]) if ((e.data as any)?.hidden_in_base === true) hiddenEdgeIds.add(e.id);
      // EFFECTIVE maps (persisted + staged edits) everywhere — staged edits
      // are visible instantly and persist on Save. Rows any variant disables
      // = legacy "disable-on-others" rows; computed from effective maps too so
      // a staged marker removal also leaves the legacy cross-disable set.
      const crossDisabledNodeIds = new Set<string>();
      const crossDisabledEdgeIds = new Set<string>();
      for (const v of registeredVariants) {
        for (const [rid, entry] of Object.entries(effectiveOverrideMap(v.name, 'node_overrides')))
          if ((entry as any)?.disabled) crossDisabledNodeIds.add(rid);
        for (const [rid, entry] of Object.entries(effectiveOverrideMap(v.name, 'edge_overrides')))
          if ((entry as any)?.disabled) crossDisabledEdgeIds.add(rid);
      }
      // Applied maps in CANONICAL (sorted) order so 'last wins' is deterministic.
      const sorted = [...viewingComponents].sort();
      const appliedNode = sorted.map((n) => effectiveOverrideMap(n, 'node_overrides'));
      const appliedEdge = sorted.map((n) => effectiveOverrideMap(n, 'edge_overrides'));
      const nodeMap = composeNodeOverrides(appliedNode, hiddenNodeIds, crossDisabledNodeIds);
      // Overlay any in-flight position drafts so a shared node being dragged
      // follows the cursor (the persisted override catches up on drop). Drafts
      // only exist in a single-variant scope; nodeMap is always a fresh object.
      if (nodeMap) {
        for (const [id, pos] of Object.entries(variantPositionDraft)) {
          nodeMap[id] = { ...(nodeMap[id] || {}), position: pos } as any;
        }
      }
      return {
        nodeMap,
        edgeMap: composeEdgeOverrides(appliedEdge, hiddenEdgeIds, crossDisabledEdgeIds),
      };
    }, [viewingComponents, registeredVariants, nodes, edges, variantPositionDraft, effectiveOverrideMap]);

    // Conflict lint for the composition preview (content collisions /
    // enable-vs-disable on the same row). Surfaced as a banner; never blocks.
    const compositionConflicts = useMemo(() => {
      if (!isComposition) return [];
      const sorted = [...viewingComponents].sort();
      const byName = new Map(registeredVariants.map((v) => [v.name, v]));
      const applied = sorted
        .map((n) => byName.get(n))
        .filter(Boolean)
        .map((v: any) => ({ name: v.name, node_overrides: v.node_overrides, edge_overrides: v.edge_overrides }));
      return detectCompositionConflicts(applied);
    }, [isComposition, viewingComponents, registeredVariants]);

    const resolvedTree = useResolvedTree(
      nodes as any,
      edges as any,
      activeVariantOverrides.nodeMap,
      activeVariantOverrides.edgeMap,
      isComposition,
      showDisabledOnVariant,
    );
    const renderNodes = resolvedTree.nodes as any;
    const renderEdges = resolvedTree.edges as any;

    // Keep the open edge-selection panel in sync with the composed graph.
    // `selectedEdge` is a snapshot taken at click time (onEdgeClick stores the
    // composed renderEdges object). A variant-scope action-set delete rewrites
    // that variant's edge_overrides and recomposes renderEdges, but nothing
    // re-points selectedEdge at the fresh edge — so the panel keeps showing the
    // pre-delete action_sets until the edge is clicked again. The base-scope
    // delete re-syncs selectedEdge itself (deleteEdgeDirection), which is why
    // Base updated live and variants didn't. Re-point selectedEdge at its
    // recomposed counterpart whenever its action_sets actually change (guarded
    // by content, so it's a no-op once they match — no render loop). If the edge
    // is gone from the composed graph (fully hidden/removed), the delete path
    // already nulls the selection, so nothing to do here.
    useEffect(() => {
      if (!selectedEdge) return;
      const fresh = (renderEdges as any[]).find((e) => e.id === selectedEdge.id);
      if (!fresh) return;
      const freshSets = JSON.stringify((fresh.data as any)?.action_sets ?? []);
      const curSets = JSON.stringify((selectedEdge.data as any)?.action_sets ?? []);
      if (freshSets !== curSets) navigation.setSelectedEdge(fresh);
    }, [renderEdges, selectedEdge, navigation]);

    return (
      <NavigationScreenshotProvider nodes={nodes}>
        <Box
          sx={{
            position: 'fixed',
            top: 64,
            left: 0,
            right: 0,
            bottom: 32, // Leave space for shared Footer (minHeight 24 + py 8 = 32px)
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {/* Header with NavigationEditorHeader component */}
          <NavigationEditorHeader
          hasUnsavedChanges={hasUnsavedChanges}
          focusNodeId={focusSelectValue}
          availableFocusNodes={globalFocusNodes}
          maxDisplayDepth={maxDisplayDepth}
          totalNodes={allNodes.length}
          visibleNodes={nodes.length}
          isLoading={isLoadingInterface}
          error={error}
          isLocked={(isLocked ?? false) || isProdView}
          treeId={actualTreeId || ''}
          selectedHost={selectedHost}
          selectedDeviceId={selectedDeviceId}
          isRemotePanelOpen={isRemotePanelOpen}
          availableHosts={availableHosts}
          onAddNewNode={handleAddNewNodeWrapper}
          onFitView={fitView}
          onSaveToConfig={handleSaveForHeader}
          onDiscardChanges={discardChanges}
          onDepthChange={setDisplayDepth}
          onResetFocus={resetFocus}
          onFocusNodeChange={selectFocusNode}
          onToggleRemotePanel={handleToggleRemotePanel}
          onControlStateChange={handleControlStateChange}
          onDeviceSelect={handleDeviceSelect}
          onToggleAIGeneration={handleToggleAIGeneration}
          userInterfaceId={userInterface?.id || null}
          viewingScope={viewingScope}
          onViewingScopeChange={setViewingScope}
          showDisabledOnVariant={showDisabledOnVariant}
          onToggleShowDisabledOnVariant={() => setShowDisabledOnVariant((v) => !v)}
        />

        {/* Compact Breadcrumb - positioned below header, aligned left */}
        <NavigationBreadcrumbCompact
          onNavigateBack={handleNavigateBack}
          onNavigateToLevel={handleNavigateToLevel}
          onNavigateToRoot={handleNavigateToRoot}
        />

        {/* Composition override-conflict warning only (the read-only preview
            nag was removed). See docs/agent/navigation/VARIANT.md "Composition". */}
        {isComposition && compositionConflicts.length > 0 && (
          <Box sx={{ px: 1, py: 0.5 }}>
            <Alert
              severity="warning"
              sx={{ py: 0, fontSize: '0.75rem', '& .MuiAlert-message': { py: 0.5 } }}
            >
              {`Composition has ${compositionConflicts.length} override conflict(s): ` +
                compositionConflicts
                  .slice(0, 4)
                  .map(
                    (c) =>
                      `${c.scope} ${c.id.slice(0, 8)} (${c.kind}: ${c.variants.join(', ')})`,
                  )
                  .join('; ') +
                (compositionConflicts.length > 4 ? ' …' : '') +
                '. Last-sorted wins for content; disable wins for visibility.'}
            </Alert>
          </Box>
        )}

        {/* Main Container with side-by-side layout */}
        <Box
          sx={{
            flex: 1,
            display: 'flex',
            overflow: 'hidden',
          }}
        >
          {/* Main Editor Area */}
          <Box
            sx={{
              flex: 1,
              position: 'relative',
              overflow: 'hidden',
              transition: 'margin-right',
              marginRight: '0px', // Remote panel managed by header
            }}
          >
            <>
              <div
                ref={reactFlowWrapper}
                style={{
                  width: '100%',
                  height: '100%',
                  position: 'relative',
                }}
              >
                {/* Read-Only Overlay - locked by someone else, or viewing the
                    published prod snapshot */}
                {(isLocked || isProdView) && (
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 10,
                      right: 10,
                      zIndex: getZIndex('READ_ONLY_INDICATOR'),
                      backgroundColor: 'warning.light',
                      color: 'warning.contrastText',
                      px: 1,
                      py: 0.5,
                      borderRadius: 1,
                      boxShadow: 2,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1,
                      fontSize: '0.675rem',
                      fontWeight: 'medium',
                    }}
                  >
                    🔒 READ-ONLY MODE
                    <Typography variant="caption" sx={{ opacity: 0.8 }}>
                      {isProdView
                        ? 'Production version — switch to DEV to edit, then Publish'
                        : 'Tree locked by another user'}
                    </Typography>
                  </Box>
                )}

                <ReactFlow
                  nodes={renderNodes}
                  edges={renderEdges}
                  onNodesChange={wrappedOnNodesChange}
                  onEdgesChange={onEdgesChange}
                  onConnect={wrappedOnConnect}
                  onNodeClick={wrappedOnNodeClick}
                  onEdgeClick={wrappedOnEdgeClick}
                  onNodeDoubleClick={nestedNavigation.handleNodeDoubleClick}
                  onPaneClick={wrappedOnPaneClick}
                  deleteKeyCode={null}
                  /* Double-click is OURS: it enters the node's subtree
                     (handleNodeDoubleClick). ReactFlow's default pane-zoom on
                     double-click must stay off in EVERY scope, otherwise a
                     double-click on a non-draggable node (every shared node in
                     a variant scope — see useResolvedTree) leaks through to the
                     pane's d3-zoom and zooms instead of entering the subtree.
                     Keeping this false makes variant navigation identical to
                     base. */
                  zoomOnDoubleClick={false}
                  /* Topology guards: when the canvas viewer is on a variant
                     scope, disable structural editing on the canvas
                     (drag / connect / edge updates). Add Node still works
                     and creates a variant-only row via handleAddNewNodeWrapper.
                     See docs/agent/ENHANCE_VARIANT.md §3.8. */
                  // Per-node `draggable` / `connectable` and per-edge `updatable`
                  // flags are set inside useResolvedTree so a variant scope can
                  // still allow drag/connect on the variant-only rows it owns.
                  // Globals stay `true`; the per-node flag overrides per node.
                  nodesDraggable
                  nodesConnectable
                  edgesUpdatable
                  onInit={(instance) => {
                    console.log(`[@NavigationEditor] ReactFlow onInit called`);
                    setReactFlowInstance(instance);
                    // Restore viewport if pending
                    const pendingViewport = navigation.pendingViewport;
                    console.log(`[@NavigationEditor] Checking pendingViewport:`, pendingViewport);
                    if (pendingViewport) {
                      console.log(`[@NavigationEditor] Restoring viewport on ReactFlow init:`, pendingViewport);
                      instance.setViewport(pendingViewport);
                      navigation.setPendingViewport(null); // Clear after restoration
                    } else {
                      console.log(`[@NavigationEditor] No pending viewport to restore`);
                    }
                  }}
                  nodeTypes={nodeTypes}
                  edgeTypes={edgeTypes}
                  defaultEdgeOptions={defaultEdgeOptions}
                  connectionLineType={ConnectionLineType.SmoothStep}
                  connectionRadius={50}
                  defaultViewport={DEFAULT_VIEWPORT}
                  translateExtent={TRANSLATE_EXTENT}
                  nodeExtent={NODE_EXTENT}
                  snapToGrid={true}
                  snapGrid={SNAP_GRID}
                  style={REACT_FLOW_STYLE}
                  nodeOrigin={NODE_ORIGIN}
                  proOptions={proOptions}
                >
                  <Background variant={BackgroundVariant.Dots} gap={15} size={1} />
                  <Controls position="top-left" />
                  
                  {/* Auto Layout Button - matching TestCaseBuilder positioning */}
                  <button
                    onClick={handleAutoLayout}
                    title="Auto Layout"
                    style={{
                      position: 'absolute',
                      top: `${AUTO_LAYOUT_BUTTON_TOP}px`,
                      left: `${AUTO_LAYOUT_BUTTON_LEFT}px`,
                      width: '26px',
                      height: '26px',
                      padding: '0',
                      background: '#ffffff',
                      border: `0px solid ${actualMode === 'dark' ? '#334155' : '#e2e8f0'}`,
                      borderRadius: '0',
                      cursor: 'pointer',
                      fontSize: '16px',
                      color: '#000000',
                      zIndex: 5,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow: 'rgba(0, 0, 0, 0.1) 0px 0px 0px 1px',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = '#f1f5f9';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = '#ffffff';
                    }}
                  >
                    <svg 
                      width="16" 
                      height="16" 
                      viewBox="0 0 24 24" 
                      fill="none" 
                      stroke="currentColor" 
                      strokeWidth="2"
                      strokeLinecap="round" 
                      strokeLinejoin="round"
                    >
                      {/* Grid layout icon */}
                      <rect x="3" y="3" width="7" height="7" />
                      <rect x="14" y="3" width="7" height="7" />
                      <rect x="14" y="14" width="7" height="7" />
                      <rect x="3" y="14" width="7" height="7" />
                    </svg>
                  </button>
                  
                  <MiniMap
                    style={miniMapStyle}
                    nodeColor={miniMapNodeColor}
                    maskColor="rgba(255, 255, 255, 0.2)"
                    pannable
                    zoomable
                    position="top-right"
                  />
                </ReactFlow>
              </div>

              {/* Side Panels */}
              {selectedNode ? (
                      <>
                      {/* Node Selection Panel */}
                      <NodeSelectionPanel
                        selectedNode={selectedNode}
                        nodes={nodes}
                        onClose={closeSelectionPanel}
                        onDelete={wrappedDeleteSelected}
                        setNodeForm={setNodeForm as React.Dispatch<React.SetStateAction<NodeForm>>}
                        setIsNodeDialogOpen={setIsNodeDialogOpen}
                        onReset={resetNode}
                        onUpdateNode={handleUpdateNode}
                        isControlActive={isControlActive}
                        selectedHost={selectedHost || undefined}
                        selectedDeviceId={selectedDeviceId || undefined}
                        treeId={actualTreeId || ''}
                        currentNodeId={currentNodeId || undefined}
                        onOpenGotoPanel={handleOpenGotoPanel}
                        nodeMetrics={metricsHook.getNodeMetrics(selectedNode.id)}
                        variant={viewingScope}
                      />
                    </>
              ) : null}
              
              {selectedEdge ? (
                    <>
                      {/* Edge Selection Panels - show panels for both edges if bidirectional */}
                      {(() => {
                        // Post-migration: Only show the selected edge, no bidirectional logic
                        const edgesToShow = [selectedEdge];

                        let panelIndexOffset = 0;

                        return edgesToShow.map((edge) => {
                          const panels = [];

                          // Use filtered action sets for display - only forward direction for action edges
                          const displayActionSets = edgeHook?.getDisplayActionSets(edge) || [];

                          if (displayActionSets.length > 0) {
                            // Render panels for each display action set. panelIndex 0 sits at
                            // the far RIGHT; higher indices stack to the LEFT — so REVERSE the
                            // index to put the forward set (source → target) on the LEFT and
                            // the reverse set (target → source) on the RIGHT.
                            // EXCEPT when this variant drew the edge AGAINST the base row's
                            // stored direction (`drawn_reversed` on the variant's override
                            // entry): then the DRAWN direction — the row's reverse set — takes
                            // the LEFT card, so the panels read the way the user linked the
                            // nodes on this variant. Display only; set↔direction mapping is
                            // unchanged.
                            const drawnReversed =
                              editScope !== null &&
                              (effectiveOverrideMap(editScope, 'edge_overrides')[edge.id] as any)
                                ?.drawn_reversed === true;
                            displayActionSets.forEach((actionSet: any, actionSetIndex: number) => {
                              const edgeMetrics = metricsHook.getEdgeDirectionMetrics(edge.id, actionSet.id);
                              panels.push(
                                <EdgeSelectionPanel
                                  key={`${edge.id}-${actionSet.id}-${panelIndexOffset + actionSetIndex}`}
                                  selectedEdge={edge}
                                  actionSet={actionSet}
                                  panelIndex={
                                    panelIndexOffset +
                                    (drawnReversed
                                      ? actionSetIndex
                                      : displayActionSets.length - 1 - actionSetIndex)
                                  }
                                  onClose={closeSelectionPanel}
                                  onEdit={() => {}}
                                  onDelete={() => deleteEdgeDirectionScoped(edge.id, actionSet.id)}
                                  setEdgeForm={setEdgeForm as React.Dispatch<React.SetStateAction<EdgeForm>>}
                                  setIsEdgeDialogOpen={setIsEdgeDialogOpen}
                                  isControlActive={isControlActive}
                                  selectedHost={selectedHost || undefined}
                                  selectedDeviceId={selectedDeviceId || undefined}
                                  onEditWithLabels={(fromLabel, toLabel) =>
                                    setEdgeLabels({ fromLabel, toLabel })
                                  }
                                  currentEdgeForm={edgeForm}
                                  edgeMetrics={edgeMetrics}
                                  treeId={actualTreeId}
                                />
                              );
                            });
                            
                            // Add fallback panel only for non-action edges that have less than 2 action sets
                            // Action edges should only show forward direction - no fallback for missing reverse
                            const isActionEdge = edgeHook?.isActionEdge(edge) || false;
                            if (!isActionEdge && edge.data.action_sets.length < 2) {
                              panels.push(
                                <EdgeSelectionPanel
                                  key={`${edge.id}-fallback`}
                                  selectedEdge={edge}
                                  actionSet={null}
                                  panelIndex={panelIndexOffset + displayActionSets.length}
                                  onClose={closeSelectionPanel}
                                  onEdit={() => {}}
                                  onDelete={() => deleteEdgeDirectionScoped(edge.id, 'fallback')}
                                  setEdgeForm={setEdgeForm as React.Dispatch<React.SetStateAction<EdgeForm>>}
                                  setIsEdgeDialogOpen={setIsEdgeDialogOpen}
                                  isControlActive={isControlActive}
                                  selectedHost={selectedHost || undefined}
                                  selectedDeviceId={selectedDeviceId || undefined}
                                  onEditWithLabels={(fromLabel, toLabel) =>
                                    setEdgeLabels({ fromLabel, toLabel })
                                  }
                                  currentEdgeForm={edgeForm}
                                  edgeMetrics={metricsHook.getEdgeMetrics(edge.id)}
                                  treeId={actualTreeId}
                                />
                              );
                              panelIndexOffset += 2; // Always reserve space for 2 panels (defined + fallback)
                            } else {
                              panelIndexOffset += displayActionSets.length; // Use filtered count
                            }
                          } else {
                            // Fallback for edges with empty or missing action_sets
                            panels.push(
                              <EdgeSelectionPanel
                                key={`${edge.id}-fallback`}
                                selectedEdge={edge}
                                actionSet={null}
                                panelIndex={panelIndexOffset}
                                onClose={closeSelectionPanel}
                                onEdit={() => {}}
                                onDelete={wrappedDeleteSelected}
                                setEdgeForm={setEdgeForm as React.Dispatch<React.SetStateAction<EdgeForm>>}
                                setIsEdgeDialogOpen={setIsEdgeDialogOpen}
                                isControlActive={isControlActive}
                                selectedHost={selectedHost || undefined}
                                selectedDeviceId={selectedDeviceId || undefined}
                                onEditWithLabels={(fromLabel, toLabel) =>
                                  setEdgeLabels({ fromLabel, toLabel })
                                }
                                currentEdgeForm={edgeForm}
                                edgeMetrics={metricsHook.getEdgeMetrics(edge.id)}
                                treeId={actualTreeId}
                              />
                            );
                            panelIndexOffset += 1;
                          }

                          return panels;
                        }).flat();
                      })()}
                    </>
              ) : null}
            </>
          </Box>

          {/* Remote Control Panel is now handled by NavigationEditorDeviceControl component */}
        </Box>

        {/* Autonomous Panels - Now self-positioning with configurable layouts */}
        {/* Remote/Desktop Panel - follows RecHostStreamModal pattern */}
        {showRemotePanel && selectedHost && selectedDeviceId && isControlActive && (() => {
          const selectedDevice = selectedHost.devices?.find((d) => d.device_id === selectedDeviceId);
          const isDesktopDevice = selectedDevice?.device_model === 'host_vnc';
          const remoteCapability = selectedDevice?.device_capabilities?.remote;
          const hasMultipleRemotes = Array.isArray(remoteCapability) || selectedDevice?.device_model === 'fire_tv';
          
          if (isDesktopDevice) {
            // For desktop devices, render both DesktopPanel and WebPanel together
            return (
              <>
                <DesktopPanel
                  host={selectedHost}
                  deviceId={selectedDeviceId}
                  deviceModel={selectedDevice?.device_model || 'host_vnc'}
                  isConnected={isControlActive}
                  onReleaseControl={handleDisconnectComplete}
                  initialCollapsed={true}
                />
                <WebPanel
                  host={selectedHost}
                  deviceId={selectedDeviceId}
                  deviceModel={selectedDevice?.device_model || 'host_vnc'}
                  isConnected={isControlActive}
                  onReleaseControl={handleDisconnectComplete}
                  initialCollapsed={true}
                />
              </>
            );
          } else if (hasMultipleRemotes && selectedDevice?.device_model === 'fire_tv') {
            // For Fire TV devices, render both AndroidTvRemote and InfraredRemote side by side
            return (
              <Box
                sx={{
                  display: 'flex',
                  flexDirection: 'row',
                  gap: 2,
                  position: 'absolute',
                  right: 20,
                  top: 100,
                  zIndex: 1000,
                  height: 'auto',
                }}
              >
                <RemotePanel
                  host={selectedHost}
                  deviceId={selectedDeviceId}
                  deviceModel={selectedDevice?.device_model || 'fire_tv'}
                  remoteType="android_tv"
                  isConnected={isControlActive}
                  onReleaseControl={handleDisconnectComplete}
                  deviceResolution={DEFAULT_DEVICE_RESOLUTION}
                  streamCollapsed={isAVPanelCollapsed}
                  streamMinimized={false}
                  streamHidden={showAVPanel} // Hide overlay when AV panel is active (screenshot/video mode)
                  captureMode="stream"
                  initialCollapsed={true}
                />
                <RemotePanel
                  host={selectedHost}
                  deviceId={selectedDeviceId}
                  deviceModel={selectedDevice?.device_model || 'fire_tv'}
                  remoteType="ir_remote"
                  isConnected={isControlActive}
                  onReleaseControl={handleDisconnectComplete}
                  deviceResolution={DEFAULT_DEVICE_RESOLUTION}
                  streamCollapsed={isAVPanelCollapsed}
                  streamMinimized={false}
                  streamHidden={showAVPanel} // Hide overlay when AV panel is active (screenshot/video mode)
                  captureMode="stream"
                  initialCollapsed={true}
                />
              </Box>
            );
          } else if (hasMultipleRemotes) {
            // For other devices with multiple remote controllers - render side by side
            const remoteTypes = Array.isArray(remoteCapability) ? remoteCapability : [remoteCapability];
            return (
              <Box
                sx={{
                  display: 'flex',
                  flexDirection: 'row',
                  gap: 2,
                  position: 'absolute',
                  right: 20,
                  top: 100,
                  zIndex: 1000,
                  height: 'auto',
                }}
              >
                {remoteTypes.filter(Boolean).map((remoteType: string, index: number) => (
                  <RemotePanel
                    key={`${selectedDeviceId}-${remoteType}`}
                    host={selectedHost}
                    deviceId={selectedDeviceId}
                    deviceModel={selectedDevice?.device_model || 'unknown'}
                    remoteType={remoteType}
                    isConnected={isControlActive}
                    onReleaseControl={handleDisconnectComplete}
                    deviceResolution={DEFAULT_DEVICE_RESOLUTION}
                    streamCollapsed={isAVPanelCollapsed}
                    streamMinimized={false}
                    captureMode="stream"
                    initialCollapsed={index > 0}
                  />
                ))}
              </Box>
            );
          } else {
            // For single remote devices, render only one RemotePanel
            return (
              <RemotePanel
                host={selectedHost}
                deviceId={selectedDeviceId}
                deviceModel={selectedDevice?.device_model || 'unknown'}
                isConnected={isControlActive}
                onReleaseControl={handleDisconnectComplete}
                deviceResolution={DEFAULT_DEVICE_RESOLUTION}
                streamCollapsed={isAVPanelCollapsed}
                streamMinimized={isAVPanelMinimized}
                captureMode={captureMode}
                isVerificationVisible={isVerificationVisible}
                isNavigationEditorContext={true}
                onOrientationChange={handleMobileOrientationChange}
              />
            );
          }
        })()}

        {/* AV Panel - device-specific stream rendering */}
        {showAVPanel && selectedHost && selectedDeviceId && (() => {
          const selectedDevice = selectedHost.devices?.find((d) => d.device_id === selectedDeviceId);
          const deviceModel = selectedDevice?.device_model;
          
          if (deviceModel === 'host_vnc') {
            return (
              <VNCStream
                host={selectedHost}
                deviceId={selectedDeviceId}
                deviceModel={deviceModel}
                isControlActive={isControlActive}
                userinterfaceName={treeName} // Use treeName directly from URL (always available, no race condition)
                onCollapsedChange={handleAVPanelCollapsedChange}
                onMinimizedChange={handleAVPanelMinimizedChange}
                onCaptureModeChange={handleCaptureModeChange}
              />
            );
          } else {
            return (
              <HDMIStream
                host={selectedHost}
                deviceId={selectedDeviceId}
                deviceModel={deviceModel}
                isControlActive={isControlActive}
                userinterfaceName={treeName} // Use treeName directly from URL (always available, no race condition)
                onCollapsedChange={handleAVPanelCollapsedChange}
                onMinimizedChange={handleAVPanelMinimizedChange}
                onCaptureModeChange={handleCaptureModeChange}
                deviceResolution={DEFAULT_DEVICE_RESOLUTION}
                isLandscape={isMobileOrientationLandscape}
              />
            );
          }
        })()}

        {/* Node Goto Panel */}
        {showGotoPanel && selectedNodeForGoto && actualTreeId && (
          <NodeGotoPanel
            selectedNode={selectedNodeForGoto}
            nodes={nodes}
            treeId={actualTreeId || ''}
            onClose={handleCloseGotoPanel}
            currentNodeId={currentNodeId || undefined}
            selectedHost={selectedHost || undefined}
            selectedDeviceId={selectedDeviceId || undefined}
            isControlActive={isControlActive}
            variant={viewingScope}
            edgeMetrics={metricsHook.edgeMetrics}
            nodeMetrics={metricsHook.nodeMetrics}
            onGotoArrived={(_navigationPath, finalNodeId) => {
              // Follow a goto into the landing node's tree via the GLOBAL focus
              // hierarchy — it knows every node's tree independent of the goto path,
              // so it also works for the dispatch / arrived-on-sibling case where the
              // node isn't in the path at all (e.g. apps_netflix under the apps
              // subtree). selectFocusNode switches the canvas + breadcrumb into the
              // owning tree and centers the node; it no-ops when already on that tree.
              const target = globalFocusNodes.find((n) => n.nodeId === finalNodeId);
              if (target) {
                selectFocusNode(`${target.treeId}::${target.nodeId}`);
              }
            }}
          />
        )}

        {/* Node Edit Dialog */}
        {isNodeDialogOpen && (
          <NodeEditDialog
            isOpen={isNodeDialogOpen}
            nodeForm={nodeForm}
            nodes={nodes}
            setNodeForm={setNodeForm as (form: NodeForm | null) => void}
            onSubmit={handleNodeFormSubmitWrapper}
            onClose={cancelNodeChanges}
            onResetNode={() => selectedNode && resetNode(selectedNode.id)}
            onUpdateNode={handleUpdateNode}
            model={userInterface?.models?.[0] || 'android_mobile'}
            isControlActive={isControlActive}
            selectedHost={selectedHost}
            selectedDeviceId={selectedDeviceId || undefined}
            initialVariantScope={editScope}
          />
        )}

        {/* Edge Edit Dialog */}
        {isEdgeDialogOpen && selectedHost && (
          <EdgeEditDialog
            isOpen={isEdgeDialogOpen}
            edgeForm={edgeForm}
            setEdgeForm={setEdgeForm as any}
                            onSubmit={saveEdgeWithStateUpdate}
            onClose={() => setIsEdgeDialogOpen(false)}
            selectedEdge={selectedEdge}
            isControlActive={isControlActive}
            selectedHost={selectedHost}
            selectedDeviceId={selectedDeviceId}
            fromLabel={edgeLabels.fromLabel}
            toLabel={edgeLabels.toLabel}
            model={userInterface?.models?.[0] || 'android_mobile'}
            initialVariantScope={editScope}
            effectiveEdgeOverrides={selectedEdgeEffectiveOverrides}
            onVariantOverrideCommitted={(variantName, edgeId) =>
              clearStagedOverrideEdit('edge', variantName, edgeId)
            }
          />
        )}

        {/* AI Generation Modal - Only mount when user opens it or validation prompt is active */}
        {(isAIGenerationOpen || showValidationPrompt) && isControlActive && selectedHost && selectedDeviceId && actualTreeId && (
          <AIGenerationModal
            isOpen={isAIGenerationOpen}
            onClose={() => setIsAIGenerationOpen(false)}
            treeId={actualTreeId}
            selectedHost={selectedHost}
            selectedDeviceId={selectedDeviceId}
            userinterfaceName={userInterface?.name}
            onStructureCreated={async (nodesCount, edgesCount, explId, explHostName) => {
              // Show ValidationReadyPrompt after structure creation
              setValidationNodesCount(nodesCount);
              setValidationEdgesCount(edgesCount);
              setExplorationId(explId);
              setExplorationHostName(explHostName);
              setShowValidationPrompt(true);
              
              // ✅ CRITICAL: Reload tree data BEFORE triggering auto-layout
              // This ensures the newly created nodes/edges are fetched and displayed
              const treeType = navigation.parentChain.length > 0 ? 'subtree' : 'root tree';
              const treeContext = navigation.parentChain.length > 0 
                ? `(subtree: ${actualTreeId}, depth: ${navigation.parentChain.length})` 
                : `(root tree: ${actualTreeId})`;
              
              console.log(`[@NavigationEditor] 🔄 Reloading ${treeType} data after structure creation ${treeContext}`);
              
              if (actualTreeId) {
                try {
                  // Invalidate cache to force fresh fetch
                  if (userInterface?.id) {
                    navigationConfig.invalidateTreeCache(userInterface.id);
                  }
                  
                  // ✅ Reload CURRENT tree (preserves subtree context if in subtree)
                  console.log(`[@NavigationEditor] 🔄 Loading tree: ${actualTreeId}`);
                  await loadTreeData(actualTreeId);
                  
                  console.log(`[@NavigationEditor] ✅ Tree data reloaded for ${treeType} - triggering auto-layout`);
                  
                  // Small delay to ensure React state has updated before triggering auto-layout
                  setTimeout(() => {
                    setApplyAutoLayoutFlag(true);
                  }, 100);
                } catch (error) {
                  console.error(`[@NavigationEditor] ❌ Failed to reload ${treeType} data:`, error);
                }
              } else {
                console.error('[@NavigationEditor] ❌ Cannot reload tree - actualTreeId is undefined!');
              }
            }}
            onFinalized={handleAIGenerated}
            onCleanupTemp={() => {
              // Pause history recording during cleanup
              navigation.pauseHistoryRecording();

              try {
                // Clean up _temp nodes from frontend state (match by label, not ID)
                const tempNodes = nodes.filter(node => node.data?.label?.endsWith('_temp'));
                const tempNodeIds = new Set(tempNodes.map(n => n.id));

                // Clean up edges connected to _temp nodes
                const tempEdges = edges.filter(edge =>
                  tempNodeIds.has(edge.source) || tempNodeIds.has(edge.target)
                );

                if (tempNodes.length > 0 || tempEdges.length > 0) {
                  console.log(`[@NavigationEditor] Cleaning up ${tempNodes.length} _temp nodes and ${tempEdges.length} edges from React Flow...`);

                  // Remove edges first (to avoid orphaned edges)
                  const remainingEdges = edges.filter(edge =>
                    !tempNodeIds.has(edge.source) && !tempNodeIds.has(edge.target)
                  );
                  setEdges(remainingEdges);

                  // Remove nodes
                  const remainingNodes = nodes.filter(node => !node.data?.label?.endsWith('_temp'));
                  setNodes(remainingNodes);

                  console.log(`[@NavigationEditor] ✅ Cleaned up ${tempNodes.length} _temp nodes and ${tempEdges.length} _temp edges from React Flow`);
                } else {
                  console.log('[@NavigationEditor] No _temp nodes found to clean up');
                }
              } finally {
                // Always resume history recording
                navigation.resumeHistoryRecording();
              }
            }}
          />
        )}

        {/* Validation Ready Prompt - Show after structure creation */}
        {showValidationPrompt && (
          <ValidationReadyPrompt
            nodesCreated={validationNodesCount}
            edgesCreated={validationEdgesCount}
            onStartValidation={() => {
              console.log('[@NavigationEditor] Start validation clicked - opening ValidationModal');
              setShowValidationPrompt(false);
              setIsValidationModalOpen(true);
            }}
            onCancel={async () => {
              // Delete all _temp nodes/edges using frontend state
              console.log('[@NavigationEditor] Cancel validation - cleaning up _temp nodes');
              
              // Find all _temp nodes in current ReactFlow state
              const tempNodes = nodes.filter(node => node.id.endsWith('_temp'));
              const tempEdges = edges.filter(edge => edge.id.includes('_temp'));
              
              console.log(`[@NavigationEditor] Found ${tempNodes.length} _temp nodes and ${tempEdges.length} _temp edges to delete`);
              
              if (tempNodes.length > 0 || tempEdges.length > 0) {
                // Delete edges first
                const remainingEdges = edges.filter(edge => !edge.id.includes('_temp'));
                setEdges(remainingEdges);
                
                // Then delete nodes
                const remainingNodes = nodes.filter(node => !node.id.endsWith('_temp'));
                setNodes(remainingNodes);
                
                setHasUnsavedChanges(true);
                
                console.log(`[@NavigationEditor] Deleted ${tempNodes.length} nodes and ${tempEdges.length} edges from frontend state`);
                
                // Refresh to sync with backend
                handleAIGenerated();
              }
              
              setShowValidationPrompt(false);
            }}
          />
        )}

        {/* Validation Modal - Phase 2b: Validation */}
        {isValidationModalOpen && explorationId && explorationHostName && actualTreeId && selectedDeviceId && (
          <ValidationModal
            isOpen={isValidationModalOpen}
            onClose={() => {
              // Cancel button clicked - delete _temp nodes/edges
              console.log('[@NavigationEditor] User cancelled - deleting _temp nodes/edges');
              setIsValidationModalOpen(false);

              // Pause history recording during cleanup
              navigation.pauseHistoryRecording();

              try {
                // Clean up _temp nodes from frontend state
                const tempNodes = nodes.filter(node => node.id.endsWith('_temp'));
                const tempEdges = edges.filter(edge => edge.id.includes('_temp'));

                if (tempNodes.length > 0 || tempEdges.length > 0) {
                  const remainingEdges = edges.filter(edge => !edge.id.includes('_temp'));
                  setEdges(remainingEdges);

                  const remainingNodes = nodes.filter(node => !node.id.endsWith('_temp'));
                  setNodes(remainingNodes);

                  setHasUnsavedChanges(true);
                  console.log(`[@NavigationEditor] Deleted ${tempNodes.length} _temp nodes and ${tempEdges.length} _temp edges`);
                }

                // Reset exploration state
                setExplorationId(null);
                setExplorationHostName(null);

                // Refresh to sync with backend
                handleAIGenerated();
              } finally {
                navigation.resumeHistoryRecording();
              }
            }}
            explorationId={explorationId}
            explorationHostName={explorationHostName}
            treeId={actualTreeId}
            selectedDeviceId={selectedDeviceId}
            onValidationStarted={() => {
              console.log('[@NavigationEditor] Validation started');
            }}
            onValidationComplete={async () => {
              // Confirm button clicked - rename _temp to permanent
              console.log('[@NavigationEditor] User confirmed - renaming _temp nodes/edges');
              
              // Call backend to rename _temp nodes/edges
              try {
                await api.post(buildServerUrl(`/server/ai-generation/finalize-structure`), {
                  exploration_id: explorationId,
                  host_name: explorationHostName,
                  tree_id: actualTreeId,
                });
                console.log('[@NavigationEditor] Structure finalized - _temp suffix removed');
              } catch (err) {
                console.error('[@NavigationEditor] Error finalizing structure:', err);
              }
              
              // ✅ Refresh tree to show renamed nodes (same as old onGenerated callback)
              await handleAIGenerated();
              
              // Close modal
              setIsValidationModalOpen(false);
              
              // Reset exploration state
              setExplorationId(null);
              setExplorationHostName(null);
            }}
          />
        )}

        {/* Discard Changes Confirmation Dialog */}
        <StyledDialog
          open={isDiscardDialogOpen}
          onClose={() => setIsDiscardDialogOpen(false)}
          sx={{ zIndex: getZIndex('NAVIGATION_CONFIRMATION') }}
        >
          <DialogTitle>Discard Changes?</DialogTitle>
          <DialogContent>
            <Typography>
              You have unsaved changes. Are you sure you want to discard them and revert to the last
              saved state?
            </Typography>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setIsDiscardDialogOpen(false)}>Cancel</Button>
            <Button onClick={handlePerformDiscard} color="warning" variant="contained">
              Discard Changes
            </Button>
          </DialogActions>
        </StyledDialog>

        {/* Metrics Notification */}
        <MetricsNotification
          notificationData={metricsHook.notificationData}
          onViewDetails={handleOpenMetricsModal}
          onClose={handleCloseMetricsNotification}
        />

        {/* Metrics Modal */}
        <MetricsModal
          open={showMetricsModal}
          onClose={handleCloseMetricsModal}
          lowConfidenceItems={metricsHook.lowConfidenceItems}
          globalConfidence={metricsHook.globalConfidence}
          isLoading={metricsHook.isLoading}
        />

        {/* Success/Error Messages */}
        {success && (
          <Snackbar
            open={!!success}
            autoHideDuration={3000}
            onClose={() => {}}
            anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
          >
            <Alert severity="success" sx={{ width: '100%' }}>
              {success}
            </Alert>
          </Snackbar>
        )}

        {/* Confirmation Dialog - replaces window.confirm */}
        <ConfirmDialog
          open={confirmDialogState.open}
          title={confirmDialogState.title}
          message={confirmDialogState.message}
          confirmText={confirmDialogState.confirmText}
          cancelText={confirmDialogState.cancelText}
          confirmColor={confirmDialogState.confirmColor}
          onConfirm={confirmDialogHandleConfirm}
          onCancel={confirmDialogHandleCancel}
        />

        {/* Phase 4 the variant authoring rules — scope-aware delete confirm (variant scope only) */}
        <ConfirmDialog
          open={variantConfirm.dialogState.open}
          title={variantConfirm.dialogState.title}
          message={variantConfirm.dialogState.message}
          confirmText={variantConfirm.dialogState.confirmText}
          cancelText={variantConfirm.dialogState.cancelText}
          confirmColor={variantConfirm.dialogState.confirmColor}
          onConfirm={variantConfirm.handleConfirm}
          onCancel={variantConfirm.handleCancel}
        />
        </Box>
      </NavigationScreenshotProvider>
    );
};

const NavigationEditor: React.FC = () => {
  // Clean approach: Get treeName from URL parameters only
  const { treeName } = useParams<{ treeName: string }>();

  if (!treeName) {
    return (
      <Box sx={{ p: 2 }}>
        <Typography variant="h6" color="error">
          Invalid URL: Missing tree name
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Expected format: /navigation-editor/[treeName]
        </Typography>
      </Box>
    );
  }

  // Always render with full providers - no conditionals
  return (
    <ReactFlowProvider>
      <NavigationConfigProvider>
        <NavigationPreviewCacheProvider>
          <NavigationEditorProvider>
            <NavigationStackProvider>
              <NavigationEditorContent treeName={treeName} />
            </NavigationStackProvider>
          </NavigationEditorProvider>
        </NavigationPreviewCacheProvider>
      </NavigationConfigProvider>
    </ReactFlowProvider>
  );
};

export default NavigationEditor;
