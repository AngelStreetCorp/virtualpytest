import React, { useState, useRef, useEffect } from 'react';
import {
  Box,
  Paper,
  InputBase,
  IconButton,
  Chip,
  Fade,
  Backdrop,
  Menu,
  MenuItem,
  Typography,
  Tooltip
} from '@mui/material';
import {
  AutoAwesome as SparkleIcon,
  KeyboardReturn as EnterIcon,
  KeyboardArrowDown as ArrowDownIcon,
  OpenInNew as RedirectIcon,
  LinkOff as RedirectOffIcon
} from '@mui/icons-material';
import { useAIContext } from '../../contexts/AIContext';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

// Available agents with agent-specific tips
const AVAILABLE_AGENTS = [
  {
    id: 'assistant',
    nickname: 'Atlas',
    description: 'General AI Assistant',
    color: '#d4af37', // palette: agent-specific brand colour used by chip fill
    tips: ['Explore the sauce-demo app', 'Run testcase TC_AUTH_01', 'Create a testcase for login']
  },
];

export const AICommandBar: React.FC = () => {
  const P = useAgentChatPalette();
  const {
    isCommandOpen,
    closeCommand,
    selectedAgentId,
    setSelectedAgentId,
    sendMessage,
    allowAutoNavigation,
    setAllowAutoNavigation
  } = useAIContext();
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const chipRef = useRef<HTMLDivElement>(null);
  const [agentMenuOpen, setAgentMenuOpen] = useState(false);
  
  const selectedAgent = AVAILABLE_AGENTS.find(a => a.id === selectedAgentId) || AVAILABLE_AGENTS[0];

  // Focus input when opened
  useEffect(() => {
    if (isCommandOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
    // Close menu when command bar closes
    if (!isCommandOpen) {
      setAgentMenuOpen(false);
    }
  }, [isCommandOpen]);

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!input.trim()) return;

    const message = input.trim();
    
    // Send message directly via AIContext - executes in place without navigation
    sendMessage(message, selectedAgentId);
    
    // Clear input and close command bar
    setInput('');
    setAgentMenuOpen(false);
    closeCommand();
  };

  if (!isCommandOpen) return null;

  return (
    <>
      {/* Dimmed Background */}
      <Backdrop
        open={isCommandOpen}
        onClick={closeCommand}
        sx={{ zIndex: 9998, bgcolor: 'rgba(0,0,0,0.5)' }}
      />

      {/* Floating Command Input */}
      <Fade in={isCommandOpen}>
        <Box
          sx={{
            position: 'fixed',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            width: '100%',
            maxWidth: '600px',
            zIndex: 9999,
            pointerEvents: 'auto'
          }}
        >
          <Paper
            elevation={24}
            component="form"
            onSubmit={handleSubmit}
            sx={{
              p: '2px 4px',
              display: 'flex',
              alignItems: 'center',
              width: '100%',
              bgcolor: 'background.paper',
              borderRadius: 3,
              border: '1px solid',
              borderColor: P.accent,
              boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
              overflow: 'hidden'
            }}
          >
            <Box sx={{ p: 1.5, display: 'flex', alignItems: 'center', color: P.accentText }}>
              <SparkleIcon fontSize="medium" />
            </Box>
            
            {/* Agent Selector Chip */}
            <Chip
              ref={chipRef}
              label={selectedAgent.nickname}
              size="small"
              onClick={() => setAgentMenuOpen(true)}
              onDelete={() => setAgentMenuOpen(true)}
              deleteIcon={<ArrowDownIcon sx={{ fontSize: 16 }} />}
              sx={{
                height: 28,
                bgcolor: `${selectedAgent.color}20`,
                color: selectedAgent.color,
                border: `1px solid ${selectedAgent.color}40`,
                fontWeight: 600,
                fontSize: '0.8rem',
                cursor: 'pointer',
                transition: 'all 0.15s',
                '& .MuiChip-deleteIcon': {
                  color: selectedAgent.color,
                  '&:hover': { color: selectedAgent.color }
                },
                '&:hover': {
                  bgcolor: `${selectedAgent.color}30`,
                  borderColor: `${selectedAgent.color}60`,
                }
              }}
            />
            
            <InputBase
              inputRef={inputRef}
              sx={{ ml: 1.5, flex: 1, fontSize: '1.1rem' }}
              placeholder="Ask AI Agent to do something..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') closeCommand();
              }}
            />
            
            <Box sx={{ display: 'flex', alignItems: 'center', pr: 1, gap: 0.5 }}>
              {/* Auto-redirect toggle */}
              <Tooltip
                title={allowAutoNavigation ? "Auto-redirect ON - Click to disable" : "Auto-redirect OFF - Click to enable"}
                arrow
                placement="top"
                slotProps={{ popper: { sx: { zIndex: 10001 } } }}
              >
                <IconButton
                  onClick={() => setAllowAutoNavigation(!allowAutoNavigation)}
                  sx={{
                    p: 0.75,
                    color: allowAutoNavigation ? P.accentText : P.textMuted,
                    bgcolor: allowAutoNavigation ? `${P.accent}1f` : 'transparent',
                    border: '1px solid',
                    borderColor: allowAutoNavigation ? `${P.accent}4d` : 'transparent',
                    borderRadius: 1.5,
                    transition: 'all 0.2s ease',
                    '&:hover': {
                      bgcolor: allowAutoNavigation ? `${P.accent}33` : `${P.hoverBg}`,
                      color: allowAutoNavigation ? P.accentText : P.textSecondary,
                    }
                  }}
                  aria-label="toggle auto-redirect"
                >
                  {allowAutoNavigation ? <RedirectIcon sx={{ fontSize: 18 }} /> : <RedirectOffIcon sx={{ fontSize: 18 }} />}
                </IconButton>
              </Tooltip>
              
              <IconButton type="submit" sx={{ p: 1 }} aria-label="send">
                <EnterIcon />
              </IconButton>
            </Box>
          </Paper>
          
          {/* Agent-specific suggestions - hide when dropdown is open */}
          <Fade in={!agentMenuOpen} timeout={150}>
            <Box sx={{ mt: 1.5, display: 'flex', justifyContent: 'center', gap: 1, flexWrap: 'wrap' }}>
              {selectedAgent.tips.map((tip) => (
                <Chip
                  key={tip}
                  label={tip}
                  size="small"
                  onClick={() => setInput(tip)}
                  sx={{
                    bgcolor: P.hoverBg,
                    color: P.textSecondary,
                    fontSize: '0.75rem',
                    height: 26,
                    border: '1px solid',
                    borderColor: P.borderColor,
                    backdropFilter: 'blur(4px)',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                    '&:hover': {
                      bgcolor: P.surface,
                      color: P.textPrimary,
                      borderColor: P.accent
                    }
                  }}
                />
              ))}
            </Box>
          </Fade>
        </Box>
      </Fade>
      
      {/* Agent Selection Menu */}
      <Menu
        anchorEl={chipRef.current}
        open={agentMenuOpen && isCommandOpen}
        onClose={() => setAgentMenuOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        disableScrollLock
        disableAutoFocusItem
        transitionDuration={150}
        sx={{ zIndex: 10000 }}
        slotProps={{
          paper: {
            sx: {
              bgcolor: P.surface,
              border: '1px solid',
              borderColor: P.borderColor,
              borderRadius: 2,
              mt: 0.5,
              minWidth: 220,
              boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
              py: 0.5,
              overflow: 'hidden',
            }
          }
        }}
      >
        {AVAILABLE_AGENTS.map((agent) => (
          <MenuItem
            key={agent.id}
            onClick={() => {
              setSelectedAgentId(agent.id);
              setAgentMenuOpen(false);
              inputRef.current?.focus();
            }}
            selected={agent.id === selectedAgentId}
            sx={{
              py: 0.75,
              px: 1.5,
              minHeight: 'auto',
              '&:hover': { bgcolor: P.hoverBg },
              '&.Mui-selected': {
                bgcolor: P.hoverBg,
                '&:hover': { bgcolor: P.hoverBg }
              },
            }}
          >
            <Box sx={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              bgcolor: agent.color,
              flexShrink: 0
            }} />
            <Typography sx={{ fontWeight: 600, color: P.textPrimary, fontSize: '0.85rem', ml: 1.5 }}>
              {agent.nickname}
            </Typography>
            <Typography sx={{ color: P.textMuted, fontSize: '0.75rem', ml: 'auto', pl: 2 }}>
              {agent.description}
            </Typography>
          </MenuItem>
        ))}
      </Menu>
    </>
  );
};

