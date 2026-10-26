/**
 * Prompt Presets Component
 *
 * Displays categorized prompt presets with variable substitution.
 * Elegant inline design matching AgentChat tips styling.
 */

import React, { useState, useMemo } from 'react';
import { Box, Chip, Collapse, Tooltip } from '@mui/material';
import { ExpandMore } from '@mui/icons-material';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

export interface PromptPreset {
  name: string;
  template: string;
}

export interface PromptPresetCategory {
  category: string;
  prompts: PromptPreset[];
}

export interface PromptPresetsProps {
  presets: PromptPresetCategory[];
  onSelectPreset: (prompt: string) => void;
  context: {
    device_id?: string;
    device_name?: string;
    host_name?: string;
    userinterface_name?: string;
    testcase_id?: string;
    testcase_name?: string;
    campaign_id?: string;
    campaign_name?: string;
  };
}

export const PromptPresets: React.FC<PromptPresetsProps> = ({
  presets,
  onSelectPreset,
  context,
}) => {
  const P = useAgentChatPalette();
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  // Variable substitution function
  const substituteVariables = (template: string): string => {
    let result = template;

    const variableMap: Record<string, string> = {
      '{device_id}': context.device_id || 'device',
      '{device_name}': context.device_name || 'device',
      '{host_name}': context.host_name || 'host',
      '{userinterface_name}': context.userinterface_name || 'interface',
      '{testcase_id}': context.testcase_id || 'testcase',
      '{testcase_name}': context.testcase_name || 'test case',
      '{campaign_id}': context.campaign_id || 'campaign',
      '{campaign_name}': context.campaign_name || 'campaign',
    };

    Object.entries(variableMap).forEach(([variable, value]) => {
      result = result.replace(new RegExp(variable, 'g'), value);
    });

    return result;
  };

  // Get unique categories
  const categories = useMemo(() => presets.map(p => p.category), [presets]);

  // Get presets for selected category
  const currentPresets = useMemo(() => {
    if (!selectedCategory) return [];
    return presets.find(p => p.category === selectedCategory)?.prompts || [];
  }, [presets, selectedCategory]);

  const handleCategoryClick = (category: string) => {
    setSelectedCategory(selectedCategory === category ? null : category);
  };

  const handlePresetClick = (template: string) => {
    const substitutedPrompt = substituteVariables(template);
    onSelectPreset(substitutedPrompt);
    setSelectedCategory(null); // Close after selection
  };

  if (!presets || presets.length === 0) return null;

  // Shared chip style (matching tips styling)
  const chipStyle = {
    bgcolor: P.hoverBg,
    border: '1px solid',
    borderColor: P.borderColor,
    borderRadius: 2,
    fontSize: TYPOGRAPHY.body.size,
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    '&:hover': {
      borderColor: P.accent,
    },
  };

  return (
    <Box sx={{ mt: 2.5, pt: 2, borderTop: '1px solid', borderColor: P.borderColor }}>
      {/* Label + Category chips - single line */}
      <Box sx={{
        display: 'flex',
        gap: 1,
        justifyContent: 'flex-start',
        alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <Box
          component="span"
          sx={{
            fontSize: TYPOGRAPHY.caption.size,
            fontWeight: 600,
            color: P.accentText,
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
            mr: 0.5,
          }}
        >
          Presets
        </Box>
        {categories.map((category) => {
          const isOpen = selectedCategory === category;
          const promptCount =
            presets.find((p) => p.category === category)?.prompts.length || 0;

          return (
            <Box
              key={category}
              component="button"
              type="button"
              onClick={() => handleCategoryClick(category)}
              aria-expanded={isOpen}
              aria-label={`${category} presets, ${promptCount} prompts`}
              sx={{
                ...chipStyle,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 1,
                px: 1.25,
                py: 0.5,
                fontFamily: 'inherit',
                color: P.textPrimary,
                lineHeight: 1.4,
                ...(isOpen && {
                  borderColor: P.accent,
                  bgcolor: `${P.accent}1f`,
                }),
                '&:focus-visible': {
                  outline: `2px solid ${P.accent}`,
                  outlineOffset: '2px',
                },
              }}
            >
              <span>{category}</span>
              <Box
                component="span"
                sx={{
                  fontSize: TYPOGRAPHY.microMeta.size,
                  fontFamily: '"JetBrains Mono", ui-monospace, monospace',
                  fontWeight: 600,
                  color: isOpen ? P.accent : P.textSecondary,
                  bgcolor: isOpen ? `${P.accent}29` : 'rgba(255, 255, 255, 0.05)',
                  borderRadius: '4px',
                  px: 0.75,
                  py: 0.1,
                  lineHeight: 1.4,
                  minWidth: 18,
                  textAlign: 'center',
                }}
              >
                {promptCount}
              </Box>
              <ExpandMore
                fontSize="small"
                sx={{
                  color: isOpen ? P.accent : P.textSecondary,
                  transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                  transition: 'transform 0.2s ease',
                  ml: -0.25,
                }}
              />
            </Box>
          );
        })}
      </Box>

      {/* Preset chips - expand below when category selected, indented under a left rail
          so the hierarchy between category and its prompts is obvious */}
      <Collapse in={!!selectedCategory} timeout={150}>
        <Box sx={{
          display: 'flex',
          gap: 0.75,
          justifyContent: 'flex-start',
          flexWrap: 'wrap',
          mt: 1.5,
          ml: 1.5,
          pl: 2,
          borderLeft: `2px solid ${P.borderColor}`,
          position: 'relative',
        }}>
          {currentPresets.map((preset, index) => {
            const substitutedPrompt = substituteVariables(preset.template);

            return (
              <Tooltip
                key={`${preset.name}-${index}`}
                title={substitutedPrompt}
                placement="top"
                arrow
                enterDelay={300}
              >
                <Chip
                  label={preset.name}
                  size="small"
                  onClick={() => handlePresetClick(preset.template)}
                  sx={{
                    ...chipStyle,
                    fontSize: TYPOGRAPHY.caption.size,
                    height: 26,
                    '& .MuiChip-label': {
                      px: 1.25,
                    },
                  }}
                />
              </Tooltip>
            );
          })}
        </Box>
      </Collapse>
    </Box>
  );
};