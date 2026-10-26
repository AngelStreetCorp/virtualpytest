/**
 * Prompt Disambiguation Component
 * 
 * Standalone modal component for resolving ambiguous navigation node references.
 * - Shows top 2 suggestions per ambiguity
 * - First suggestion is pre-selected as default
 * - User can confirm default or choose alternative
 * - "Edit Prompt" button to go back and modify the original prompt
 * - All choices are automatically saved to database for future auto-correction
 */

import React, { useState } from 'react';
import {
  Box,
  Typography,
  Button,
  Modal,
  Backdrop,
} from '@mui/material';
import { getZIndex } from '../../utils/zIndexUtils';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import type { Ambiguity, AutoCorrection } from '../../types/aiagent/AIDisambiguation_Types';
import { AppIcon } from '../../constants/icons';
import { TYPOGRAPHY } from '../../constants/typography';

interface Props {
  ambiguities: Ambiguity[];
  autoCorrections?: AutoCorrection[];
  availableNodes?: string[];
  onResolve: (selections: Record<string, string>, saveToDb: boolean) => void;
  onCancel: () => void;
  onEditPrompt?: () => void; // Go back to prompt input
}

export const PromptDisambiguation: React.FC<Props> = ({
  ambiguities,
  onResolve,
  onCancel,
  onEditPrompt
}) => {
  const P = useAgentChatPalette();
  // Pre-select defaults (first suggestion for each ambiguity)
  const defaultSelections = React.useMemo(() => {
    const defaults: Record<string, string> = {};
    ambiguities.forEach(amb => {
      if (amb.suggestions.length > 0) {
        defaults[amb.original] = amb.suggestions[0]; // Default to first suggestion
      }
    });
    return defaults;
  }, [ambiguities]);

  const [selections, setSelections] = useState<Record<string, string>>(defaultSelections);

  const handleConfirm = () => {
    // Always save to DB (saveToDb = true by default)
    onResolve(selections, true);
  };

  const handleEditPrompt = () => {
    if (onEditPrompt) {
      onEditPrompt();
    } else {
      onCancel(); // Fallback to cancel if no edit handler
    }
  };

  return (
    <Modal
      open
      onClose={onCancel}
      closeAfterTransition
      slots={{ backdrop: Backdrop }}
      slotProps={{
        backdrop: {
          timeout: 300,
          sx: {
            backgroundColor: 'rgba(0, 0, 0, 0.85)',
            backdropFilter: 'blur(4px)',
            zIndex: getZIndex('AI_DISAMBIGUATION_MODAL') - 1,
          }
        }
      }}
    >
      <Box
        sx={{
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: getZIndex('AI_DISAMBIGUATION_MODAL'),
          width: '85%',
          maxWidth: 600,
          maxHeight: '80vh',
          bgcolor: P.surface,
          borderRadius: 2,
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.9)',
          border: '1px solid',
          borderColor: P.borderColor,
          outline: 'none',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <Box sx={{ px: 2, py: 1.5, borderBottom: '1px solid', borderColor: P.borderColor }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, color: P.textPrimary, fontSize: TYPOGRAPHY.navbarItem.size }}>
            <AppIcon name="thinking" /> Clarify Navigation Nodes
          </Typography>
        </Box>

        {/* Content - Compact, simple selection only */}
        <Box sx={{ px: 2, py: 1.5, maxHeight: 'calc(80vh - 120px)', overflowY: 'auto' }}>
          {/* Selection mode - Compact, max 2 choices, first is default */}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            {ambiguities.map((amb, idx) => {
              const defaultChoice = amb.suggestions[0]; // First is always default
              return (
                <Box key={idx} sx={{ px: 1.5, py: 1, bgcolor: P.background, border: '1px solid', borderColor: P.borderColor, borderRadius: 1 }}>
                  <Typography variant="caption" sx={{ mb: 1, fontWeight: 500, color: P.textSecondary, display: 'block', fontSize: TYPOGRAPHY.body.size }}>
                    We found:{' '}
                    <Typography component="span" sx={{ color: P.accentText, fontFamily: 'monospace', fontWeight: 'bold', fontSize: TYPOGRAPHY.body.size }}>
                      "{amb.original}"
                    </Typography>
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
                    {/* Show max 2 suggestions, first is default */}
                    {amb.suggestions.slice(0, 2).map((sugg) => {
                      const isSelected = selections[amb.original] === sugg;
                      const isDefault = sugg === defaultChoice;
                      return (
                        <Button
                          key={sugg}
                          onClick={() => setSelections({ ...selections, [amb.original]: sugg })}
                          variant={isSelected ? 'contained' : 'outlined'}
                          size="small"
                          sx={{
                            justifyContent: 'space-between',
                            textTransform: 'none',
                            fontFamily: 'monospace',
                            py: 0.75,
                            fontSize: TYPOGRAPHY.body.size,
                            bgcolor: isSelected ? P.accent : 'transparent',
                            borderColor: isSelected ? P.accent : P.borderColor,
                            color: isSelected ? 'primary.contrastText' : P.textSecondary,
                            '&:hover': {
                              bgcolor: isSelected ? P.accentHover : `${P.accent}1a`,
                              borderColor: P.accent,
                            }
                          }}
                        >
                          <span>{sugg}</span>
                          {isDefault && (
                            <Typography component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, color: isSelected ? 'primary.contrastText' : P.success, ml: 1 }}>
                              <AppIcon name="star" /> default
                            </Typography>
                          )}
                        </Button>
                      );
                    })}
                  </Box>
                </Box>
              );
            })}
          </Box>
        </Box>

        {/* Footer - Compact */}
        <Box
          sx={{
            px: 2,
            py: 1.5,
            borderTop: '1px solid',
            borderColor: P.borderColor,
            bgcolor: P.background,
            display: 'flex',
            justifyContent: 'space-between',
            gap: 1.5,
          }}
        >
          {/* Left side - Edit Prompt */}
          <Button
            onClick={handleEditPrompt}
            variant="text"
            size="small"
            sx={{
              textTransform: 'none',
              fontSize: TYPOGRAPHY.body.size,
              color: P.textMuted,
              '&:hover': {
                color: P.accentText,
                bgcolor: 'transparent',
              }
            }}
          >
            <AppIcon name="edit" /> Edit Prompt
          </Button>

          {/* Right side - Cancel & Confirm */}
          <Box sx={{ display: 'flex', gap: 1.5 }}>
            <Button
              onClick={onCancel}
              variant="outlined"
              size="small"
              sx={{
                textTransform: 'none',
                fontSize: TYPOGRAPHY.body.size,
                borderColor: P.borderColor,
                color: P.textSecondary,
                '&:hover': { borderColor: P.textSecondary, color: P.textPrimary, bgcolor: P.hoverBg, }
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={handleConfirm}
              variant="contained"
              size="small"
              sx={{
                textTransform: 'none',
                fontSize: TYPOGRAPHY.body.size,
                minWidth: 100,
                bgcolor: P.accent,
                color: 'primary.contrastText',
                '&:hover': {
                  bgcolor: P.accentHover,
                }
              }}
            >
              Confirm
            </Button>
          </Box>
        </Box>
      </Box>
    </Modal>
  );
};