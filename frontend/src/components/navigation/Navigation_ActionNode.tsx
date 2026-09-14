import React, { useState, useEffect } from 'react';
import { Handle, Position, NodeProps, useReactFlow } from 'reactflow';

import { NODE_TYPE_COLORS, UI_BADGE_COLORS } from '../../config/validationColors';
import { ScreenshotModal } from '../common/ScreenshotModal';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useNodeScreenshot } from '../../contexts/navigation/NavigationScreenshotContext';
import { getZIndex } from '../../utils/zIndexUtils';

import { useValidationColors } from '../../hooks/validation/useValidationColors';
import { useMetrics } from '../../hooks/navigation/useMetrics';
import type { UINavigationNode as UINavigationNodeType, UINavigationEdge } from '../../types/pages/Navigation_Types';

export const UIActionNode: React.FC<NodeProps<UINavigationNodeType['data']>> = ({
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
    return `${baseUrl}?v=${timestamp}&key=${randomKey}&cb=${Date.now()}`;
    }
  }, [r2ScreenshotUrl, data.screenshot_timestamp, imageKey]);

  // Listen for screenshot update events and force immediate refresh
  useEffect(() => {
    const handleScreenshotUpdate = (event: CustomEvent) => {
      if (event.detail.nodeId === id) {
        console.log(
          `[@component:UIActionNode] Screenshot updated for node ${id}, forcing refresh`,
        );

        // Use cache-buster from event for immediate refresh
        if (event.detail.cacheBuster) {
          setImageKey(event.detail.cacheBuster);
        } else {
          setImageKey(Date.now().toString() + Math.random().toString(36).substr(2, 9));
        }
      }
    };

    // TypeScript-compatible event listener
    const listener = handleScreenshotUpdate as EventListener;
    window.addEventListener('screenshotUpdated', listener);

    return () => {
      window.removeEventListener('screenshotUpdated', listener);
    };
  }, [id]);

  // Check if this is the current position
  const isCurrentPosition = currentNodeId === id;

  // Get dynamic colors based on validation status
  const nodeColors = getNodeColors(data.type, nodeMetrics);

  // Action node colors from validationColors
  const actionColors = NODE_TYPE_COLORS.action;

  // Current position styling - purple theme (same as navigation node)
  const currentPositionStyle = {
    border: '3px solid #9c27b0',
    boxShadow: 'none', // Remove shadow
    animation: 'currentPositionPulse 2s ease-in-out infinite',
  };

  const handleScreenshotDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent node double-click from triggering
    e.preventDefault(); // Prevent default double-click behavior
    e.nativeEvent.stopImmediatePropagation(); // Stop all event propagation immediately

    console.log('[@component:UIActionNode] Screenshot double-clicked, preventing node focus');

    if (screenshotUrl) {
      setIsScreenshotModalOpen(true);
    }
  };

  // Verification indicators (same as navigation node)
  const showVerificationBadge = data.verifications && data.verifications.length > 0;
  const verificationCount = data.verifications?.length || 0;

  // Sub-tree indicators (same as navigation node)
  const showSubtreeBadge = data.has_subtree && data.subtree_count && data.subtree_count > 0;

  return (
    <>
      <div
        style={{
          // Rectangle shape — identical to the screen/menu navigation node so
          // action nodes share the exact same look & behaviour. The orange
          // action color (background + border) is the only distinguisher.
          background: actionColors.background,
          border: isCurrentPosition
            ? currentPositionStyle.border // Purple border for current position (highest priority)
            : `2px dashed ${nodeColors.border}`, // Dashed stroke distinguishes action nodes from solid-bordered screen/menu nodes
          borderRadius: '8px',
          padding: '12px',
          minWidth: '200px',
          maxWidth: '200px',
          minHeight: '180px',
          fontSize: '12px',
          color: actionColors.textColor,
          boxShadow: 'none !important', // Remove all shadows (same as navigation node)
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
        data-node-type="action"
        data-node-id={id}
        title={`Action: ${data.label}${data.description ? `\n${data.description}` : ''}`}
      >
        {/* Variant marker — single 'v' top-right when the *active* variant
            view has an entry on this row. Base view never shows it. The flag
            is computed in useResolvedTree.ts with full viewingScope context.
            Same as the screen/menu navigation node. */}
        {data._show_variant_chip && (
          <div
            style={{
              position: 'absolute',
              top: '4px',
              right: '4px',
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

        {/* Verification badge - top left (same as navigation node) */}
        {showVerificationBadge && (
          <div
            style={{
              position: 'absolute',
              top: '-6px',
              left: '-6px',
              minWidth: '18px',
              height: '18px',
              borderRadius: '50%',
              backgroundColor: UI_BADGE_COLORS.verification,
              color: 'white',
              fontSize: '10px',
              fontWeight: 'bold',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '2px solid white',
              zIndex: getZIndex('NAVIGATION_NODE_BADGES'), // Same as navigation node badges
            }}
            title={`${verificationCount} verification${verificationCount !== 1 ? 's' : ''}`}
          >
            {verificationCount}
          </div>
        )}

        {/* Subtree badge - bottom left (same as navigation node) */}
        {showSubtreeBadge && (
          <div
            style={{
              position: 'absolute',
              bottom: '-6px',
              left: '-6px',
              minWidth: '18px',
              height: '18px',
              borderRadius: '50%',
              backgroundColor: UI_BADGE_COLORS.subtree,
              color: 'white',
              fontSize: '10px',
              fontWeight: 'bold',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '2px solid white',
              zIndex: getZIndex('NAVIGATION_NODE_BADGES'), // Same as navigation node badges
            }}
            title={`${data.subtree_count} subtree${data.subtree_count !== 1 ? 's' : ''}`}
          >
            {data.subtree_count}
          </div>
        )}

        {/* Node handles - EXACT same IDs as navigation node for compatibility */}
        {/* Left Handles - Overlapping for Bidirectional Effect */}
        {/* Left: TARGET for receiving connections */}
        <Handle
          type="target"
          position={Position.Left}
          id="left-target"
          isConnectable={true}
          isConnectableStart={false}
          isConnectableEnd={true}
          style={{
            background: '#1976d2',
            border: '2px solid #fff',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            left: -7,
            top: '50%',
            transform: 'translateY(-50%)',
            cursor: 'crosshair',
            zIndex: getZIndex('NAVIGATION_NODE_HANDLES'),
          }}
        />

        {/* Left: SOURCE for sending connections - same position, lower z-index */}
        <Handle
          type="source"
          position={Position.Left}
          id="left-source"
          isConnectable={true}
          isConnectableStart={true}
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
            zIndex: getZIndex('NAVIGATION_NODE_BADGES'),
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
            background: '#ff5722',
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
            background: '#1976d2',
            border: '2px solid #fff',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            right: -7,
            top: '50%',
            transform: 'translateY(-50%)',
            cursor: 'crosshair',
            zIndex: getZIndex('NAVIGATION_NODE_BADGES'),
            opacity: 0,
          }}
        />

        {/* VERTICAL HANDLES - Simple IDs for database edges */}
        {/* Top target - for incoming edges from below */}
        <Handle
          type="target"
          position={Position.Top}
          id="top-right-menu-target"
          isConnectable={true}
          isConnectableStart={false}
          isConnectableEnd={true}
          style={{
            background: '#4caf50',
            border: '2px solid #fff',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            left: '50%',
            transform: 'translateX(-50%)',
            top: -7,
            cursor: 'crosshair',
            zIndex: getZIndex('NAVIGATION_NODE_HANDLES'),
          }}
        />

        {/* Bottom source - for outgoing edges downward */}
        <Handle
          type="source"
          position={Position.Bottom}
          id="bottom-right-menu-source"
          isConnectable={true}
          isConnectableStart={true}
          isConnectableEnd={false}
          style={{
            background: '#1976d2',
            border: '2px solid #fff',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            left: '50%',
            transform: 'translateX(-50%)',
            bottom: -7,
            cursor: 'crosshair',
            zIndex: getZIndex('NAVIGATION_NODE_HANDLES'),
          }}
        />

        {/* Top Handles - Overlapping */}
        {/* Top: SOURCE for menu connections */}
        <Handle
          type="source"
          position={Position.Bottom}
          id="top-left-menu-source"
          isConnectable={true}
          isConnectableStart={true}
          isConnectableEnd={false}
          style={{
            background: '#ff5722',
            border: '2px solid #fff',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            left: '50%',
            transform: 'translateX(-50%)',
            top: -7,
            cursor: 'crosshair',
            zIndex: getZIndex('NAVIGATION_NODE_HANDLES'),
          }}
        />

        {/* Top: TARGET for menu connections - same position, lower z-index */}
        <Handle
          type="target"
          position={Position.Top}
          id="top-right-menu-target"
          isConnectable={true}
          isConnectableStart={false}
          isConnectableEnd={true}
          style={{
            background: '#4caf50',
            border: '2px solid #fff',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            left: '50%',
            transform: 'translateX(-50%)',
            top: -7,
            cursor: 'crosshair',
            zIndex: getZIndex('NAVIGATION_NODE_BADGES'),
            opacity: 0,
          }}
        />

        {/* Bottom Handles - Overlapping */}
        {/* Bottom: TARGET for menu connections */}
        <Handle
          type="target"
          position={Position.Top}
          id="bottom-left-menu-target"
          isConnectable={true}
          isConnectableStart={false}
          isConnectableEnd={true}
          style={{
            background: '#9c27b0',
            border: '2px solid #fff',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            left: '50%',
            transform: 'translateX(-50%)',
            bottom: -7,
            cursor: 'crosshair',
            zIndex: getZIndex('NAVIGATION_NODE_HANDLES'),
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
            background: '#ff5722',
            border: '2px solid #fff',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            left: '50%',
            transform: 'translateX(-50%)',
            bottom: -7,
            cursor: 'crosshair',
            zIndex: getZIndex('NAVIGATION_NODE_BADGES'),
            opacity: 0,
          }}
        />

      {/* Header with node name — same layout as the screen/menu navigation node */}
      <div
        style={{
          padding: '4px',
          borderBottom: `1px solid ${actionColors.border}`,
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
            color: actionColors.textColor,
            marginBottom: '0px',
            fontSize: '18px',
          }}
        >
          {data.label}
        </div>
      </div>

      {/* Screenshot area — identical behaviour to the navigation node:
          `contain` so the full frame shows as a thumbnail (not cropped), with
          double-click to open the full-size modal. Transparent background keeps
          the orange action fill visible when there is no screenshot. */}
      <div
        style={{
          flex: 1,
          backgroundColor: 'transparent',
          backgroundImage: screenshotUrl ? `url(${screenshotUrl})` : 'none',
          backgroundSize: 'contain',
          backgroundRepeat: 'no-repeat',
          backgroundPosition: 'center',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative',
          cursor: screenshotUrl ? 'pointer' : 'default',
        }}
        onDoubleClick={handleScreenshotDoubleClick}
        title={screenshotUrl ? 'Double-click to view full size' : 'Double-click to explore actions'}
      >
        {!screenshotUrl && (
          <div
            style={{
              fontSize: '11px',
              color: actionColors.textColor,
              textAlign: 'center',
              opacity: 0.7,
            }}
          >
            Double-click to explore
          </div>
        )}
      </div>
      </div>

      {/* Shared full-screen screenshot viewer (portal + Esc + cross + click-out) */}
      <ScreenshotModal
        open={isScreenshotModalOpen}
        screenshotUrl={screenshotUrl}
        alt={`Screenshot for ${data.label}`}
        onClose={() => setIsScreenshotModalOpen(false)}
      />
    </>
  );
};