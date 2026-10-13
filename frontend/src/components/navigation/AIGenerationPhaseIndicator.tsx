import React from 'react';
import { Box, Typography, Stepper, Step, StepLabel } from '@mui/material';
import {
  Search as DetectIcon,
  Analytics as AnalyzeIcon,
  Build as BuildIcon,
  CheckCircle as FinalizeIcon
} from '@mui/icons-material';
import type { ExplorationPhase } from '../../types/exploration';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

interface AIGenerationPhaseIndicatorProps {
  currentPhase: ExplorationPhase | null;
  strategy?: string | null;
}

const phases = [
  { id: 'phase0', label: 'Detect Strategy', icon: DetectIcon },
  { id: 'phase1', label: 'Analyze & Plan', icon: AnalyzeIcon },
  { id: 'phase2', label: 'Build & Test', icon: BuildIcon },
  { id: 'phase3', label: 'Finalize', icon: FinalizeIcon }
];

export const AIGenerationPhaseIndicator: React.FC<AIGenerationPhaseIndicatorProps> = ({
  currentPhase,
  strategy
}) => {
  const P = useAgentChatPalette();
  const getActiveStep = () => {
    if (!currentPhase) return -1;
    return phases.findIndex(p => p.id === currentPhase);
  };

  const activeStep = getActiveStep();

  return (
    <Box sx={{ width: '100%', mb: 3 }}>
      <Stepper activeStep={activeStep} alternativeLabel>
        {phases.map((phase, index) => {
          const Icon = phase.icon;
          const isActive = index === activeStep;
          const isCompleted = index < activeStep;

          return (
            <Step key={phase.id} completed={isCompleted}>
              <StepLabel
                StepIconComponent={() => (
                  <Box
                    sx={{
                      width: 40,
                      height: 40,
                      borderRadius: '50%',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      bgcolor: isCompleted
                        ? P.success
                        : isActive
                        ? P.accent
                        : P.hoverBg,
                      color: isActive || isCompleted ? 'primary.contrastText' : P.textSecondary,
                      border: `1px solid ${isActive ? P.accent : P.borderColor}`,
                    }}
                  >
                    <Icon fontSize="small" />
                  </Box>
                )}
              >
                <Typography variant="caption" sx={{ fontWeight: isActive ? 'bold' : 'normal' }}>
                  {phase.label}
                </Typography>
                {phase.id === 'phase0' && isCompleted && strategy && (
                  <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
                    ({strategy})
                  </Typography>
                )}
              </StepLabel>
            </Step>
          );
        })}
      </Stepper>
    </Box>
  );
};

