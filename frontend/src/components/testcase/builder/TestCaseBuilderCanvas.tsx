import React from 'react';
import {
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
} from 'reactflow';
import 'reactflow/dist/style.css';

interface TestCaseBuilderCanvasProps {
  actualMode: 'light' | 'dark';
  isSidebarOpen: boolean;
  onAutoLayout?: () => void;
  
  // 🗑️ REMOVED: Execution Overlay props - no longer needed
}

export const TestCaseBuilderCanvas: React.FC<TestCaseBuilderCanvasProps> = ({
  actualMode,
  isSidebarOpen,
  onAutoLayout,
}) => {
  const autoLayoutLeft = isSidebarOpen ? '306px' : '26px';
  const controlsLeft = isSidebarOpen ? '290px' : '10px';

  const miniMapNodeColor = (node: any): string => {
    const colorMap: Record<string, string> = {
      start: '#2196f3',
      success: '#10b981',
      failure: '#ef4444',
      navigation: '#8b5cf6',
      action: '#f97316',
      verification: '#3b82f6',
      loop: '#6b7280',
      sleep: '#6b7280',
      get_current_time: '#6b7280',
      condition: '#6b7280',
      set_variable: '#6b7280',
      api_call: '#06b6d4',
    };
    return colorMap[node.type as string] || '#6b7280';
  };

  return (
    <>
      <Background
        variant={BackgroundVariant.Dots}
        gap={15}
        size={1}
        color={actualMode === 'dark' ? '#334155' : '#cbd5e1'}
      />
      <Controls
        showInteractive={false}
        position="top-left"
        style={{
          background: actualMode === 'dark' ? '#1e293b' : '#ffffff',
          border: `1px solid ${actualMode === 'dark' ? '#334155' : '#e2e8f0'}`,
          borderRadius: '8px',
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
      )}
      
      <MiniMap
        nodeColor={miniMapNodeColor}
        style={{
          background: actualMode === 'dark' ? '#1e293b' : '#ffffff',
          border: `1px solid ${actualMode === 'dark' ? '#334155' : '#e2e8f0'}`,
          borderRadius: '8px',
        }}
        position="top-right"
      />
    </>
  );
};

