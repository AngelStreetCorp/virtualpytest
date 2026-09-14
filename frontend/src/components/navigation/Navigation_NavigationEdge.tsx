import React from 'react';
import { EdgeLabelRenderer, EdgeProps, getSmoothStepPath, getBezierPath, useReactFlow } from 'reactflow';

import { useMetrics } from '../../hooks/navigation/useMetrics';
import { useValidationColors } from '../../hooks/validation';
import { UINavigationEdge as UINavigationEdgeType } from '../../types/pages/Navigation_Types';

export const NavigationEdgeComponent: React.FC<EdgeProps<UINavigationEdgeType['data']>> = (
  props,
) => {
  const {
    id,
    source,
    target,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    selected,
    data,
  } = props;
  const { getNodes } = useReactFlow();

  // Get metrics for this edge
  const metricsHook = useMetrics();
  const edgeMetrics = metricsHook.getEdgeMetrics(id);

  // Get edge colors based on validation status with metrics (direct call)
  const { getEdgeColors } = useValidationColors([]);
  let edgeColors = getEdgeColors(id, edgeMetrics);

  // 🎨 CONDITIONAL EDGE DETECTION (structural, computed in useResolvedTree)
  // `data._conditional` is stamped by the resolver: true when 2+ edges leave
  // this source sharing the same forward default_action_set_id to DISTINCT
  // targets. It is recomputed over the whole edge set on every edge change, so
  // both members of a group recolour the instant the group forms — unlike a
  // per-edge getEdges() probe here, which never re-runs on the *sibling* edge
  // when a new conditional edge is added (the "needs refresh" bug).
  const isConditionalEdge = (data as any)?._conditional === true;
  // 'main' = action owner, 'sibling' = borrower (stamped in useResolvedTree).
  const conditionalRole = (data as any)?._conditionalRole as 'main' | 'sibling' | null | undefined;

  // 🎨 OVERRIDE: Conditional edges are always BLUE. The borrowing SIBLING is
  // drawn dashed so it's visually distinct from the action-owning MAIN (solid).
  if (isConditionalEdge) {
    edgeColors = {
      stroke: '#2196f3',
      strokeWidth: 3,
      strokeDasharray: conditionalRole === 'sibling' ? '6,4' : '',
      opacity: 1,
    };
  }

  // Get current nodes to check types
  const nodes = getNodes();
  const sourceNode = nodes.find((node) => node.id === source);
  const targetNode = nodes.find((node) => node.id === target);

  // Edges connecting to root nodes are rendered in gold.
  if (targetNode?.data?.is_root === true) {
    edgeColors = {
      stroke: '#ffc107',
      strokeWidth: 3,
      strokeDasharray: '',
      opacity: 1,
    };
  }

  // Ghost: disabled on the active variant (or touching a disabled node). Wins
  // over every colour rule above — grey + dashed + transparent so it reads as
  // "hidden here, click to restore". Stamped by useResolvedTree when the
  // canvas "show disabled" toggle is on. See docs/agent/navigation/VARIANT.md §5.
  const isVariantDisabled = (data as any)?._variant_disabled === true;
  if (isVariantDisabled) {
    edgeColors = {
      ...edgeColors,
      stroke: '#9e9e9e',
      strokeDasharray: '4,4',
      opacity: 0.35,
    };
  }

  // Check if this is an entry-to-home connection
  const isEntryToHome =
    sourceNode?.data?.type === 'entry' &&
    (targetNode?.data?.is_root === true || targetNode?.data?.label?.toLowerCase() === 'home');

  // Render the edge in the REAL direction the user drew: source handle → target
  // handle. React Flow already gives sourceX/Y + sourcePosition from the
  // connected source handle and targetX/Y + targetPosition from the target
  // handle, so the smooth-step router elbows out of the exact side the user
  // connected and into the exact side on the other node.
  //
  // No coordinate normalization. It existed for the PRE-migration model where a
  // bidirectional pair was TWO rows (A→B and B→A) that had to collapse onto one
  // visual line, so both were forced to render from the lexicographically
  // smaller node id. Post-migration there is exactly ONE edge row per pair
  // (both directions live in `action_sets`), so there is no second row to keep
  // on the same path — normalizing only flipped the drawn handles, routing the
  // line through the wrong sides and overlapping edges from other node pairs.
  // See docs/agent/navigation/VARIANT.md.
  const pathSourceX = sourceX;
  const pathSourceY = sourceY;
  const pathTargetX = targetX;
  const pathTargetY = targetY;
  const pathSourcePosition = sourcePosition;
  const pathTargetPosition = targetPosition;

  // Choose path type based on edge type
  let edgePath: string;

  if (isEntryToHome) {
    // Use bezier path for entry-to-home connections
    [edgePath] = getBezierPath({
      sourceX: pathSourceX,
      sourceY: pathSourceY,
      sourcePosition: pathSourcePosition,
      targetX: pathTargetX,
      targetY: pathTargetY,
      targetPosition: pathTargetPosition,
    });
  } else {
    // Use smooth step path for all other connections
    [edgePath] = getSmoothStepPath({
      sourceX: pathSourceX,
      sourceY: pathSourceY,
      sourcePosition: pathSourcePosition,
      targetX: pathTargetX,
      targetY: pathTargetY,
      targetPosition: pathTargetPosition,
    });
  }

  return (
    <g className={edgeColors.className}>
      {/* Invisible thick overlay for better selectability */}
      <path
        id={`${id}-selectable`}
        style={{
          ...edgeColors,
          strokeWidth: 15,
          fill: 'none',
          stroke: 'transparent',
          cursor: 'pointer',
        }}
        className="react-flow__edge-interaction"
        d={edgePath}
      />

      {/* Visible edge path without arrow */}
      <path
        id={id}
        style={{
          ...edgeColors,
          fill: 'none',
          strokeWidth: edgeColors.strokeWidth || 2,
          cursor: 'pointer',
        }}
        className="react-flow__edge-path"
        d={edgePath}
      />

      {/* Selection indicator */}
      {selected && (
        <path
          style={{
            ...edgeColors,
            stroke: '#555',
            strokeWidth: (edgeColors.strokeWidth || 2) + 2,
            fill: 'none',
            strokeDasharray: '5,5',
            opacity: 0.8,
          }}
          className="react-flow__edge-path"
          d={edgePath}
        />
      )}

      {/* Variant marker — single 'v' at edge midpoint when the *active*
          variant view has an entry on this row. Base view never shows it. */}
      {data?._show_variant_chip && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${(pathSourceX + pathTargetX) / 2}px, ${(pathSourceY + pathTargetY) / 2}px)`,
              backgroundColor: '#1976d2',
              color: '#fff',
              fontSize: '10px',
              fontWeight: 'bold',
              padding: '2px 6px',
              borderRadius: '4px',
              whiteSpace: 'nowrap',
              border: '1px solid rgba(0,0,0,0.1)',
              pointerEvents: 'none',
              opacity: isVariantDisabled ? 0.45 : 1,
            }}
            className="nodrag nopan"
          >
            v
          </div>
        </EdgeLabelRenderer>
      )}
    </g>
  );
};
