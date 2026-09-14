/**
 * Prompt Presets Component
 *
 * Displays categorized prompt presets with variable substitution.
 * Elegant inline design matching AgentChat tips styling.
 */

import React, { useState, useMemo } from 'react';
import { Box, Chip, Collapse, Tooltip } from '@mui/material';
import { AGENT_CHAT_PALETTE as PALETTE } from '../../constants/agentChatTheme';

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
  isDarkMode?: boolean;
}

export const PromptPresets: React.FC<PromptPresetsProps> = ({
  presets,
  onSelectPreset,
  context,
  isDarkMode = false,
}) => {
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
    bgcolor: isDarkMode ? PALETTE.surface : 'grey.100',
    border: '1px solid',
    borderColor: isDarkMode ? PALETTE.borderColor : 'grey.200',
    borderRadius: 2,
    fontSize: '0.8rem',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    '&:hover': { 
      borderColor: PALETTE.accent,
    },
  };

  return (
    <Box sx={{ mt: 2.5, pt: 2, borderTop: '1px solid', borderColor: isDarkMode ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)' }}>
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
            fontSize: '0.7rem',
            fontWeight: 600,
            color: PALETTE.accent,
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
            mr: 0.5,
          }}
        >
          Presets
        </Box>
        {categories.map((category) => (
          <Chip
            key={category}
            label={category}
            size="small"
            onClick={() => handleCategoryClick(category)}
            sx={{
              ...chipStyle,
              ...(selectedCategory === category && {
                borderColor: PALETTE.accent,
                bgcolor: isDarkMode ? PALETTE.inputBg : 'grey.200',
              }),
            }}
          />
        ))}
      </Box>

      {/* Preset chips - expand below when category selected */}
      <Collapse in={!!selectedCategory} timeout={150}>
        <Box sx={{
          display: 'flex',
          gap: 0.75,
          justifyContent: 'flex-start',
          flexWrap: 'wrap',
          mt: 1.5,
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
                    fontSize: '0.75rem',
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