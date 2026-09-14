import React, { useState, useEffect } from 'react';
import { Handle, Position, NodeProps, useReactFlow } from 'reactflow';

import { NODE_TYPE_COLORS, UI_BADGE_COLORS } from '../../config/validationColors';
import { ScreenshotModal } from '../common/ScreenshotModal';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useNodeScreenshot } from '../../contexts/navigation/NavigationScreenshotContext';

import { useValidationColors } from '../../hooks/validation/useValidationColors';
import { useMetrics } from '../../hooks/navigation/useMetrics';
import type { UINavigationNode as UINavigationNodeType, UINavigationEdge } from '../../types/pages/Navigation_Types';
import { getZIndex } from '../../utils/zIndexUtils';

export const UINavigationNode: React.FC<NodeProps<UINavigationNodeType['data']>> = ({
  data,
  selected: _selected,
  id,
}) => {
  const { currentNodeId } = useNavigation();

  const [isScreenshotModalOpen, setIsScreenshotModalOpen] = useState(false);
  const [imageKey, setImageKey] = useState<string | number>(0); // Key to force image refresh
  const { getEdges } = useReactFlow();
  const currentEdges = getEdges();
  const { getNodeColors } = useValidationColors(currentEdges as UINavigationEdge[]);
  
  // Get metrics for this node
  const metricsHook = useMetrics();
  const nodeMetrics = metricsHook.getNodeMetrics(id);

  // Use batched screenshot context for efficient URL loading
  const r2ScreenshotUrl = useNodeScreenshot(id);

  // Use screenshot URL with cache-busting for updated screenshots
  const screenshotUrl = React.useMemo(() => {
    if (!r2ScreenshotUrl) return null;

    // Use timestamp for cache-busting when screenshot is updated
    const baseUrl = r2ScreenshotUrl.split('?')[0]; // Get base URL without query params
    const timestamp = data.screenshot_timestamp || Date.now();
    const randomKey = imageKey || Math.random().toString(36).substr(2, 9);

    // For signed URLs, do NOT append cache-busting params as it invalidates the signature
    if (r2ScreenshotUrl.includes('X-Amz-Signature')) {
      return r2ScreenshotUrl;
    } else {
      // Public URL - use query string for cache-busting
    return `${baseUrl}?v=${timestamp}&key=${randomKey}&cb=${Date.now()}`;
    }
  }, [r2ScreenshotUrl, data.screenshot_timestamp, imageKey]);

  // Listen for screenshot update events and force immediate refresh
  useEffect(() => {
    const handleScreenshotUpdate = (event: CustomEvent) => {
      if (event.detail.nodeId === id) {
        console.log(
          `[@component:UINavigationNode] Screenshot updated for node ${id}, forcing refresh`,
        );

        // Use cache-buster from event for immediate refresh
        if (event.detail.cacheBuster) {
          setImageKey(event.detail.cacheBuster);
        } else {
          setImageKey(Date.now().toString() + Math.random().toString(36).substr(2, 9));
        }
      }
    };

    window.addEventListener('nodeScreenshotUpdated', handleScreenshotUpdate as EventListener);
    return () => {
      window.removeEventListener('nodeScreenshotUpdated', handleScreenshotUpdate as EventListener);
    };
  }, [id]);

  // Check if this node is a root node (should only be true for actual root nodes)
  const isRootNode = data.is_root === true;
  // Check if this is an entry point node
  const isEntryNode = data.type === 'entry';
  // Check if this is a menu node
  const isMenuNode = data.type === 'menu';
  // Context node check removed since shadows are disabled
  // Check if this is the current position
  const isCurrentPosition = currentNodeId === id;

  // Get dynamic colors based on validation status
  const nodeColors = getNodeColors(data.type, nodeMetrics);

  // Entry node styling - small circular point
  if (isEntryNode) {
    const entryColors = NODE_TYPE_COLORS.entry;
    return (
      <div
        style={{
          width: '40px',
          height: '40px',
          borderRadius: '50%',
          background: entryColors.background,
          border: isCurrentPosition ? '3px solid #9c27b0' : `3px solid ${entryColors.border}`,
          boxShadow: 'none', // Remove shadow from entry nodes
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: entryColors.textColor,
          fontSize: '16px',
          fontWeight: 'bold',
          position: 'relative',
          cursor: 'pointer',
          animation: isCurrentPosition ? 'currentPositionPulse 2s ease-in-out infinite' : 'none',
        }}
        title={
          isCurrentPosition
            ? 'Entry Point - Current Position'
            : 'Entry Point - Click to edit entry method'
        }
      >
        ⚡{/* Single source handle for outgoing connections */}
        <Handle
          type="source"
          position={Position.Right}
          id="entry-source"
          isConnectable={false}
          isConnectableStart={false}
          isConnectableEnd={false}
          style={{
            background: entryColors.border,
            width: '8px',
            height: '8px',
            border: '2px solid #fff',
            borderRadius: '50%',
            right: -4,
            top: '50%',
            transform: 'translateY(-50%)',
            opacity: 1,
            cursor: 'not-allowed',
          }}
        />
      </div>
    );
  }

  // Root node styling - more prominent than normal nodes
  const rootNodeStyle = {
    background: 'linear-gradient(135deg, #ffebee 0%, #ffcdd2 100%)',
    border: '2px solid #d32f2f',
    boxShadow: 'none', // Remove shadow
  };

  // Current position styling - purple theme
  const currentPositionStyle = {
    border: '3px solid #9c27b0',
    boxShadow: 'none', // Remove shadow
    animation: 'currentPositionPulse 2s ease-in-out infinite',
  };

  // Normal node styling - based on node type
  const getNodeColor = (type: string) => {
    switch (type) {
      case 'screen':
        return '#e3f2fd';
      case 'dialog':
        return '#f3e5f5';
      case 'popup':
        return '#fff3e0';
      case 'overlay':
        return '#e8f5e8';
      case 'menu':
        return '#fff8e1';
      default:
        return '#f5f5f5';
    }
  };

  const handleScreenshotDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent node double-click from triggering
    e.preventDefault(); // Prevent default double-click behavior
    e.nativeEvent.stopImmediatePropagation(); // Stop all event propagation immediately

    console.log('[@component:UINavigationNode] Screenshot double-clicked, preventing node focus');

    if (screenshotUrl) {
      setIsScreenshotModalOpen(true);
    }
  };

  return (
    <>
      <div
        style={{
          background: isRootNode ? rootNodeStyle.background : getNodeColor(data.type),
          border: isCurrentPosition
            ? currentPositionStyle.border // Blue border for current position (highest priority)
            : `1px solid ${nodeColors.border}`, // Use validation colors for border (includes verification results)
          borderRadius: '8px',
          padding: '12px',
          minWidth: '200px',
          maxWidth: '200px',
          minHeight: '180px',
          fontSize: '12px',
          color: '#333',
          boxShadow: 'none !important', // Remove all shadows
          WebkitBoxShadow: 'none !important',
          MozBoxShadow: 'none !important',
          filter: 'none !important',
          WebkitFilter: 'none !important',
          position: 'relative',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          cursor: 'pointer',
          opacity: 1,
          animation: isCurrentPosition ? currentPositionStyle.animation : 'none',
        }}
        className={nodeColors.className || ''}
      >
      {/* Root Node Indicator */}
      {isRootNode && (
        <div
          style={{
            position: 'absolute',
            top: '4px',
            left: '4px', // Always stay in top-left position
            backgroundColor: UI_BADGE_COLORS.root.background,
            color: UI_BADGE_COLORS.root.textColor,
            fontSize: '10px',
            fontWeight: 'bold',
            padding: '2px 6px',
            borderRadius: '4px',
            zIndex: getZIndex('NAVIGATION_NODE_BADGES'),
          }}
        >
          ROOT
        </div>
      )}

      {/* Menu Type Indicator */}
      {isMenuNode && (
        <div
          style={{
            position: 'absolute',
            top: '4px',
            right: '4px',
            backgroundColor: UI_BADGE_COLORS.menu.background,
            color: UI_BADGE_COLORS.menu.textColor,
            fontSize: '10px',
            fontWeight: 'bold',
            padding: '2px 6px',
            borderRadius: '4px',
            zIndex: getZIndex('NAVIGATION_NODE_BADGES'),
          }}
        >
          MENU
        </div>
      )}

      {/* Variant marker — single 'v' top-right when the *active* variant
          view has an entry on this row. Base view never shows it. The flag
          is computed in useResolvedTree.ts with full viewingScope context. */}
      {data._show_variant_chip && (
        <div
          style={{
            position: 'absolute',
            top: '4px',
            right: isMenuNode ? '52px' : '4px',
            backgroundColor: '#1976d2',
            color: '#fff',
            fontSize: '10px',
            fontWeight: 'bold',
            padding: '2px 6px',
            borderRadius: '4px',
            zIndex: getZIndex('NAVIGATION_NODE_BADGES'),
          }}
        >
          v
        </div>
      )}

      {/* Left Handles - Overlapping for Bidirectional Effect */}
      {/* Root node: left handle is reserved for the entry→root edge, so new
          connections are refused (the existing entry edge still renders). */}
      {/* Left: TARGET for receiving connections */}
      <Handle
        type="target"
        position={Position.Left}
        id="left-target"
        isConnectable={!isRootNode}
        isConnectableStart={false}
        isConnectableEnd={!isRootNode}
        style={{
          background: data.is_root ? '#ffc107' : '#1976d2',
          border: '2px solid #fff',
          width: '16px',
          height: '16px',
          borderRadius: '50%',
          left: -7,
          top: '50%',
          transform: 'translateY(-50%)',
          cursor: isRootNode ? 'not-allowed' : 'crosshair',
          zIndex: getZIndex('NAVIGATION_NODE_HANDLES'),
        }}
      />

      {/* Left: SOURCE for sending connections - same position, lower z-index */}
      <Handle
        type="source"
        position={Position.Left}
        id="left-source"
        isConnectable={!isRootNode}
        isConnectableStart={!isRootNode}
        isConnectableEnd={false}
        style={{
          background: '#ff5722',
          border: '2px solid #fff',
          width: '16px',
          height: '16px',
          borderRadius: '50%',
          left: -7,
          top: '50%',
          transform: 'translateY(-50%)',
          cursor: 'crosshair',
          zIndex: 10,
          opacity: 0,
        }}
      />

      {/* Right Handles - Overlapping for Bidirectional Effect */}
      {/* Right: SOURCE for sending connections */}
      <Handle
        type="source"
        position={Position.Right}
        id="right-source"
        isConnectable={true}
        isConnectableStart={true}
        isConnectableEnd={false}
        style={{
          background: '#1976d2',
          border: '2px solid #fff',
          width: '16px',
          height: '16px',
          borderRadius: '50%',
          right: -7,
          top: '50%',
          transform: 'translateY(-50%)',
          cursor: 'crosshair',
          zIndex: getZIndex('NAVIGATION_NODE_HANDLES'),
        }}
      />

      {/* Right: TARGET for receiving connections - same position, lower z-index */}
      <Handle
        type="target"
        position={Position.Right}
        id="right-target"
        isConnectable={true}
        isConnectableStart={false}
        isConnectableEnd={true}
        style={{
          background: '#ff5722',
          border: '2px solid #fff',
          width: '16px',
          height: '16px',
          borderRadius: '50%',
          right: -7,
          top: '50%',
          transform: 'translateY(-50%)',
          cursor: 'crosshair',
          zIndex: 10,
          opacity: 0,
        }}
      />

      {/* MENU NAVIGATION HANDLES - Overlapping for Bidirectional Effect */}
      {/* Top Handles - Overlapping */}
      {/* Top: SOURCE for menu connections */}
      <Handle
        type="source"
        position={Position.Top}
        id="top-left-menu-source"
        isConnectable={true}
        isConnectableStart={true}
        isConnectableEnd={false}
        style={{
          background: '#9c27b0',
          border: '10px solid transparent',
          width: '16px',
          height: '16px',
          borderRadius: '50%',
          left: '50%',
          transform: 'translateX(-50%)',
          top: -7,
          cursor: 'crosshair',
          zIndex: 10,
          boxShadow: '0 0 0 2px #fff',
        }}
      />

      {/* Top: TARGET for menu connections - same position, higher z-index */}
      <Handle
        type="target"
        position={Position.Top}
        id="top-right-menu-target"
        isConnectable={true}
        isConnectableStart={false}
        isConnectableEnd={true}
        style={{
          background: '#4caf50',
          border: '10px solid transparent',
          width: '16px',
          height: '16px',
          borderRadius: '50%',
          left: '50%',
          transform: 'translateX(-50%)',
          top: -7,
          cursor: 'crosshair',
          zIndex: getZIndex('NAVIGATION_NODE_HANDLES'),
          opacity: 0,
          boxShadow: '0 0 0 2px #fff',
        }}
      />

      {/* Bottom Handles - Overlapping */}
      {/* Bottom: TARGET for menu connections */}
      <Handle
        type="target"
        position={Position.Bottom}
        id="bottom-left-menu-target"
        isConnectable={true}
        isConnectableStart={false}
        isConnectableEnd={true}
        style={{
          background: '#9c27b0',
          border: '10px solid transparent',
          width: '16px',
          height: '16px',
          borderRadius: '50%',
          left: '50%',
          transform: 'translateX(-50%)',
          bottom: -7,
          cursor: 'crosshair',
          zIndex: getZIndex('NAVIGATION_NODE_HANDLES'),
          boxShadow: '0 0 0 2px #fff',
        }}
      />

      {/* Bottom: SOURCE for menu connections - same position, lower z-index */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="bottom-right-menu-source"
        isConnectable={true}
        isConnectableStart={true}
        isConnectableEnd={false}
        style={{
          background: '#4caf50',
          border: '10px solid transparent',
          width: '16px',
          height: '16px',
          borderRadius: '50%',
          left: '50%',
          transform: 'translateX(-50%)',
          bottom: -7,
          cursor: 'crosshair',
          zIndex: 10,
          opacity: 0,
          boxShadow: '0 0 0 2px #fff',
        }}
      />

      {/* Header with node name and type */}
      <div
        style={{
          padding: '4px',
          borderBottom: isRootNode ? '1px solid #ef5350' : '1px solid #eee',
          minHeight: '10px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            fontWeight: 'bold',
            textAlign: 'center',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            color: isRootNode ? '#d32f2f' : 'black',
            marginBottom: '0px',
            fontSize: '18px',
          }}
        >
          {data.label}
        </div>
      </div>

      {/* Screenshot area */}
      <div
        style={{
          flex: 1,
          backgroundColor: screenshotUrl ? 'transparent' : '#f5f5f5',
          backgroundImage: screenshotUrl ? `url(${screenshotUrl})` : 'none',
          backgroundSize: 'contain',
          backgroundRepeat: 'no-repeat',
          backgroundPosition: 'center',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative',
          cursor: screenshotUrl ? 'pointer' : data.type === 'menu' ? 'pointer' : 'default',
        }}
        onDoubleClick={handleScreenshotDoubleClick}
        title={
          screenshotUrl
            ? 'Double-click to view full size'
            : data.type === 'entry'
              ? ''
              : 'Double-click to explore actions'
        }
      >
        {!screenshotUrl && (
          <div
            style={{
              fontSize: '11px',
              color: '#666',
              textAlign: 'center',
            }}
          >
            {data.type === 'entry' ? 'Entry Point' : 'Double-click to explore'}
          </div>
        )}
      </div>
    </div>

    {/* Shared full-screen screenshot viewer (portal + Esc + cross + click-out) */}
    <ScreenshotModal
      open={isScreenshotModalOpen}
      screenshotUrl={screenshotUrl}
      alt={`Screenshot of ${data.label}`}
      onClose={() => setIsScreenshotModalOpen(false)}
    />
  </>
  );
};
