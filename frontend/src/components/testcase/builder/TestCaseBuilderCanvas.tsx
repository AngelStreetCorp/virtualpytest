import React from 'react';
import {
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../../constants/typography';

interface TestCaseBuilderCanvasProps {
  isSidebarOpen: boolean;
  onAutoLayout?: () => void;
  
  // 🗑️ REMOVED: Execution Overlay props - no longer needed
}

export const TestCaseBuilderCanvas: React.FC<TestCaseBuilderCanvasProps> = ({
  isSidebarOpen,
  onAutoLayout,
}) => {
  const autoLayoutLeft = isSidebarOpen ? '306px' : '26px';
  const controlsLeft = isSidebarOpen ? '290px' : '10px';

  const P = useAgentChatPalette();

  const miniMapNodeColor = (node: any): string => {
    const colorMap: Record<string, string> = {
      start: P.accent,
      success: P.success,
      failure: P.error,
      navigation: '#7c3aed',
      action: '#ea580c',
      verification: P.series[1],
      api_call: '#06b6d4',
    };
    return colorMap[node.type as string] || P.textMuted;
  };

  const controlSx = `
    .testcase-canvas-controls .react-flow__controls-button {
      background: ${P.surfaceSolid};
      border-bottom: 1px solid ${P.borderColor};
      color: ${P.textSecondary};
      fill: ${P.textSecondary};
    }
    .testcase-canvas-controls .react-flow__controls-button:hover { background: ${P.hoverBg}; color: ${P.accentText}; fill: ${P.accentText}; }
    .testcase-canvas-controls .react-flow__controls-button svg { fill: currentColor; }
  `;

  return (
    <>
      <style>{controlSx}</style>
      <Background
        variant={BackgroundVariant.Dots}
        gap={15}
        size={1}
        color={P.borderColor}
      />
      <Controls
        showInteractive={false}
        position="top-left"
        className="testcase-canvas-controls"
        style={{
          background: P.surfaceSolid,
          border: `1px solid ${P.borderColor}`,
          borderRadius: '8px',
          overflow: 'hidden',
          left: controlsLeft,
          transition: 'left 0.3s ease',
        }}
      />
      
      {/* Auto Layout Button */}
      {onAutoLayout && (
        <button
          onClick={onAutoLayout}
          title="Auto Layout"
          style={{
            position: 'absolute',
            top: '98px',
            left: autoLayoutLeft,
            transition: 'left 0.3s ease',
            width: '26px',
            height: '26px',
            padding: '0',
            background: P.surfaceSolid,
            border: `1px solid ${P.borderColor}`,
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: TYPOGRAPHY.navbarItem.size,
            color: P.textSecondary,
            zIndex: 5,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = P.hoverBg;
            e.currentTarget.style.color = P.accentText;
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = P.surfaceSolid;
            e.currentTarget.style.color = P.textSecondary;
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
      )}
      
      <MiniMap
        nodeColor={miniMapNodeColor}
        maskColor={`${P.background}b3`}
        style={{
          background: P.surfaceSolid,
          border: `1px solid ${P.borderColor}`,
          borderRadius: '8px',
        }}
        position="top-right"
      />
    </>
  );
};

