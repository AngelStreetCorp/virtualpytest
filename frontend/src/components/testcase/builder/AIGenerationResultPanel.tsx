/**
 * AIGenerationResultPanel Component
 * 
 * Compact draggable panel showing AI generation results
 * Order: Prompt → AI Analysis → Stats → Block Breakdown
 */

import React, { useState, useRef, useEffect } from 'react';
import { Box, Typography, IconButton, Tooltip, Collapse, Chip } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import RefreshIcon from '@mui/icons-material/Refresh';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import { useTheme } from '../../../contexts/ThemeContext';

interface AIGenerationResult {
  success: boolean;
  graph: {
    nodes: any[];
    edges: any[];
  };
  analysis?: string;
  prompt?: string; // Original user prompt
  execution_time: number;
  generation_stats?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    block_counts?: {
      navigation: number;
      action: number;
      verification: number;
      other: number;
      total: number;
    };
  };
}

interface AIGenerationResultPanelProps {
  result: AIGenerationResult;
  onClose: () => void;
  onRegenerate: () => void;
  originalPrompt: string; // Pass from parent
}

export const AIGenerationResultPanel: React.FC<AIGenerationResultPanelProps> = ({
  result,
  onClose,
  onRegenerate,
  originalPrompt,
}) => {
  const { actualMode } = useTheme();
  const [isAnalysisExpanded, setIsAnalysisExpanded] = useState(true);
  const [isStatsExpanded, setIsStatsExpanded] = useState(true); // Expanded by default
  
  // Draggable state - start centered
  const [position, setPosition] = useState({ 
    x: window.innerWidth / 2 - 300, // Center (600px width)
    y: 60 // Smaller top margin
  });
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startY: number; initialX: number; initialY: number } | null>(null);

  // Cleanup on unmount - ensure drag state is released
  useEffect(() => {
    return () => {
      if (isDragging) {
        console.log('[AIGenerationResultPanel] Component unmounting - releasing drag');
      }
    };
  }, []);

  // Global ESC key handler - always active to catch ESC even during drag
  useEffect(() => {
    const handleEscKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isDragging) {
        console.log('[AIGenerationResultPanel] ESC key pressed - force releasing drag');
        setIsDragging(false);
        dragRef.current = null;
        e.preventDefault();
        e.stopPropagation();
      }
    };

    window.addEventListener('keydown', handleEscKey, true); // Use capture phase
    return () => {
      window.removeEventListener('keydown', handleEscKey, true);
    };
  }, [isDragging]);

  // Parse analysis
  const parseAnalysis = (analysis?: string) => {
    if (!analysis) return { goal: '', thinking: '', isDirectMatch: false };
    
    // Check if this is a direct match (no AI)
    const isDirectMatch = analysis.includes('Direct Match Found') || analysis.includes('🎯');
    
    const lines = analysis.split('\n');
    let goal = '';
    let thinking = '';
    for (const line of lines) {
      if (line.startsWith('Goal:')) goal = line.replace('Goal:', '').trim();
      else if (line.startsWith('Thinking:')) thinking = line.replace('Thinking:', '').trim();
    }
    
    // If no Goal/Thinking format, use full text as thinking
    if (!goal && !thinking) {
      thinking = analysis;
    }
    
    return { goal, thinking, isDirectMatch };
  };

  const { goal, thinking, isDirectMatch } = parseAnalysis(result.analysis);

  // Calculate block counts
  const blockCounts = result.generation_stats?.block_counts || {
    navigation: result.graph.nodes.filter(n => n.type === 'navigation').length,
    action: result.graph.nodes.filter(n => n.type === 'action').length,
    verification: result.graph.nodes.filter(n => n.type === 'verification').length,
    other: result.graph.nodes.filter(n => !['start', 'success', 'failure', 'navigation', 'action', 'verification'].includes(n.type)).length,
    total: result.graph.nodes.length,
  };

  // Draggable handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.drag-handle')) {
      setIsDragging(true);
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        initialX: position.x,
        initialY: position.y,
      };
      e.preventDefault();
    }
  };

  // Dragging effect with failsafes for stuck drag state
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isDragging && dragRef.current) {
        const deltaX = e.clientX - dragRef.current.startX;
        const deltaY = e.clientY - dragRef.current.startY;
        setPosition({
          x: dragRef.current.initialX + deltaX,
          y: dragRef.current.initialY + deltaY,
        });
      }
    };

    const handleMouseUp = () => {
      if (isDragging) {
        console.log('[AIGenerationResultPanel] Mouse up - releasing drag');
        setIsDragging(false);
        dragRef.current = null;
      }
    };

    // Failsafe: Release drag when mouse leaves the window
    const handleMouseLeave = (e: MouseEvent) => {
      if (isDragging && (e.clientY <= 0 || e.clientX <= 0 || 
          e.clientX >= window.innerWidth || e.clientY >= window.innerHeight)) {
        console.log('[AIGenerationResultPanel] Mouse left window - releasing drag');
        setIsDragging(false);
        dragRef.current = null;
      }
    };

    // Failsafe: Release drag when window loses focus
    const handleBlur = () => {
      if (isDragging) {
        console.log('[AIGenerationResultPanel] Window blur - releasing drag');
        setIsDragging(false);
        dragRef.current = null;
      }
    };

    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.addEventListener('mouseleave', handleMouseLeave);
      window.addEventListener('blur', handleBlur);
      
      // Capture phase for iframes
      document.addEventListener('mouseup', handleMouseUp, true);
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.removeEventListener('mouseleave', handleMouseLeave);
      window.removeEventListener('blur', handleBlur);
      document.removeEventListener('mouseup', handleMouseUp, true);
    };
  }, [isDragging]);

  return (
    <Box
      onMouseDown={handleMouseDown}
      sx={{
        position: 'fixed',
        top: `${position.y}px`,
        left: `${position.x}px`,
        zIndex: 1100,
        width: 600,
        backgroundColor: actualMode === 'dark' ? '#1f2937' : '#ffffff',
        borderRadius: 1,
        boxShadow: isDragging ? '0 12px 24px rgba(0, 0, 0, 0.4)' : '0 8px 16px rgba(0, 0, 0, 0.3)',
        border: '2px solid #10b981',
        cursor: isDragging ? 'grabbing' : 'default',
        userSelect: isDragging ? 'none' : 'auto',
        transition: isDragging ? 'none' : 'box-shadow 0.2s ease',
      }}
    >
      {/* Header - COMPACT */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 1.5,
          py: 0.75,
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
          <Box 
            className="drag-handle" 
            sx={{ 
              cursor: isDragging ? 'grabbing' : 'grab', 
              display: 'flex', 
              color: isDragging ? 'primary.main' : 'text.secondary',
              '&:hover': {
                color: 'text.primary',
              },
              '&:active': {
                cursor: 'grabbing',
              },
            }}
          >
            <DragIndicatorIcon fontSize="small" />
          </Box>
          <CheckCircleIcon sx={{ color: '#10b981', fontSize: 18 }} />
          <Typography variant="caption" fontWeight="bold" color="#10b981">
            AI GENERATION COMPLETE
          </Typography>
        </Box>
        
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Chip 
            label={`${blockCounts.total} blocks`}
            size="small"
            sx={{ 
              height: 20,
              fontSize: '0.7rem',
              fontWeight: 'bold',
              backgroundColor: 'rgba(59, 130, 246, 0.15)',
              color: '#3b82f6',
            }}
          />
          <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
            {result.execution_time.toFixed(2)}s
          </Typography>
          <IconButton size="small" onClick={onClose} sx={{ p: 0.5 }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>
      </Box>

      {/* 1. ORIGINAL PROMPT - COMPACT */}
      <Box sx={{ px: 1.5, py: 0.75, borderBottom: 1, borderColor: 'divider', backgroundColor: actualMode === 'dark' ? 'rgba(59, 130, 246, 0.05)' : 'rgba(59, 130, 246, 0.03)' }}>
        <Typography variant="caption" fontWeight="bold" sx={{ color: '#3b82f6', display: 'block', mb: 0.25 }}>
          📝 Original Prompt
        </Typography>
        <Typography variant="caption" sx={{ color: 'text.secondary', lineHeight: 1.4 }}>
          {originalPrompt}
        </Typography>
      </Box>

      {/* 2. AI ANALYSIS - COMPACT */}
      {(goal || thinking) && (
        <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              px: 1.5,
              py: 0.5,
              cursor: 'pointer',
              backgroundColor: actualMode === 'dark' ? 'rgba(16, 185, 129, 0.05)' : 'rgba(16, 185, 129, 0.03)',
              '&:hover': { backgroundColor: actualMode === 'dark' ? 'rgba(16, 185, 129, 0.08)' : 'rgba(16, 185, 129, 0.05)' },
            }}
            onClick={() => setIsAnalysisExpanded(!isAnalysisExpanded)}
          >
            <Typography variant="caption" fontWeight="bold" color="text.secondary">
              {isDirectMatch ? '🎯 DIRECT MATCH' : '🤖 AI REASONING'}
            </Typography>
            <IconButton size="small" sx={{ p: 0.25 }}>
              {isAnalysisExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
            </IconButton>
          </Box>
          
          <Collapse in={isAnalysisExpanded}>
            <Box sx={{ px: 1.5, py: 0.75 }}>
              {goal && (
                <Box sx={{ mb: 0.5 }}>
                  <Typography variant="caption" fontWeight="bold" sx={{ color: '#3b82f6', display: 'inline', mr: 0.5 }}>
                    🎯
                  </Typography>
                  <Typography variant="caption" sx={{ color: 'text.secondary', lineHeight: 1.4 }}>
                    {goal}
                  </Typography>
                </Box>
              )}
              {thinking && (
                <Box>
                  <Typography variant="caption" fontWeight="bold" sx={{ color: '#10b981', display: 'inline', mr: 0.5 }}>
                    💭
                  </Typography>
                  <Typography variant="caption" sx={{ color: 'text.secondary', lineHeight: 1.4 }}>
                    {thinking}
                  </Typography>
                </Box>
              )}
            </Box>
          </Collapse>
        </Box>
      )}

      {/* 3. GENERATION STATS - COMPACT, COLLAPSED BY DEFAULT */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            px: 1.5,
            py: 0.5,
            cursor: 'pointer',
            '&:hover': { backgroundColor: actualMode === 'dark' ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)' },
          }}
          onClick={() => setIsStatsExpanded(!isStatsExpanded)}
        >
          <Typography variant="caption" fontWeight="bold" color="text.secondary">
            📊 STATS
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.7rem' }}>
              🧭 {blockCounts.navigation} • ⚡ {blockCounts.action} • ✓ {blockCounts.verification} • 🔤 {result.generation_stats?.prompt_tokens || 0}/{result.generation_stats?.completion_tokens || 0}
            </Typography>
            <IconButton size="small" sx={{ p: 0.25 }}>
              {isStatsExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
            </IconButton>
          </Box>
        </Box>
        
        <Collapse in={isStatsExpanded}>
          <Box sx={{ px: 1.5, py: 0.75 }}>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 0.5 }}>
              <Box sx={{ p: 0.5, borderRadius: 0.5, backgroundColor: actualMode === 'dark' ? 'rgba(59, 130, 246, 0.1)' : 'rgba(59, 130, 246, 0.05)' }}>
                <Typography variant="caption" sx={{ fontSize: '0.7rem' }}>🧭 Navigation</Typography>
                <Typography variant="caption" fontWeight="bold" sx={{ color: '#3b82f6', display: 'block' }}>{blockCounts.navigation}</Typography>
              </Box>
              <Box sx={{ p: 0.5, borderRadius: 0.5, backgroundColor: actualMode === 'dark' ? 'rgba(139, 92, 246, 0.1)' : 'rgba(139, 92, 246, 0.05)' }}>
                <Typography variant="caption" sx={{ fontSize: '0.7rem' }}>⚡ Action</Typography>
                <Typography variant="caption" fontWeight="bold" sx={{ color: '#8b5cf6', display: 'block' }}>{blockCounts.action}</Typography>
              </Box>
              <Box sx={{ p: 0.5, borderRadius: 0.5, backgroundColor: actualMode === 'dark' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(16, 185, 129, 0.05)' }}>
                <Typography variant="caption" sx={{ fontSize: '0.7rem' }}>✓ Verification</Typography>
                <Typography variant="caption" fontWeight="bold" sx={{ color: '#10b981', display: 'block' }}>{blockCounts.verification}</Typography>
              </Box>
              <Box sx={{ p: 0.5, borderRadius: 0.5, backgroundColor: actualMode === 'dark' ? 'rgba(245, 158, 11, 0.1)' : 'rgba(245, 158, 11, 0.05)' }}>
                <Typography variant="caption" sx={{ fontSize: '0.7rem' }}>🔤 Tokens</Typography>
                <Typography variant="caption" fontWeight="bold" sx={{ color: '#f59e0b', display: 'block' }}>{result.generation_stats?.prompt_tokens}/{result.generation_stats?.completion_tokens}</Typography>
              </Box>
            </Box>
          </Box>
        </Collapse>
      </Box>

      {/* Action Buttons - COMPACT */}
      <Box sx={{ px: 1.5, py: 0.75, display: 'flex', gap: 0.75, justifyContent: 'flex-end' }}>
        <Tooltip title="Generate a new test case">
          <IconButton
            size="small"
            onClick={onRegenerate}
            sx={{
              color: '#3b82f6',
              border: '1px solid #3b82f6',
              borderRadius: 0.5,
              px: 1,
              py: 0.25,
              '&:hover': { backgroundColor: 'rgba(59, 130, 246, 0.1)' },
            }}
          >
            <RefreshIcon fontSize="small" sx={{ mr: 0.5 }} />
            <Typography variant="caption" fontWeight="bold">Regenerate</Typography>
          </IconButton>
        </Tooltip>

        <Tooltip title="Keep graph and close">
          <IconButton
            size="small"
            onClick={onClose}
            sx={{
              color: '#10b981',
              border: '1px solid #10b981',
              borderRadius: 0.5,
              px: 1,
              py: 0.25,
              backgroundColor: 'rgba(16, 185, 129, 0.1)',
              '&:hover': { backgroundColor: 'rgba(16, 185, 129, 0.2)' },
            }}
          >
            <Typography variant="caption" fontWeight="bold">Close & Keep</Typography>
          </IconButton>
        </Tooltip>
      </Box>
    </Box>
  );
};

