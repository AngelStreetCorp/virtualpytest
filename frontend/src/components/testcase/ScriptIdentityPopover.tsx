/**
 * ScriptIdentityPopover
 *
 * Compact editor for an executable's TCnnn prefix and display name, anchored to
 * the prefix chip on the Test Cases page. Writes to the executable_identity
 * table via useIdentityMap().saveScriptIdentity — this replaces hand-editing
 * test_scripts/script_identity_map.json (BUG-0066).
 *
 * Clearing both fields removes the identity entirely.
 */

import { Box, Button, Popover, TextField, Typography } from '@mui/material';
import React, { useEffect, useState } from 'react';

interface ScriptIdentityPopoverProps {
  open: boolean;
  anchorEl: HTMLElement | null;
  scriptRef: string;
  initialPrefix?: string;
  initialDisplayName?: string;
  saving?: boolean;
  warning?: string | null;
  onSave: (prefix: string, displayName: string) => void;
  onClose: () => void;
}

export const ScriptIdentityPopover: React.FC<ScriptIdentityPopoverProps> = ({
  open,
  anchorEl,
  scriptRef,
  initialPrefix,
  initialDisplayName,
  saving = false,
  warning,
  onSave,
  onClose,
}) => {
  const [prefix, setPrefix] = useState('');
  const [displayName, setDisplayName] = useState('');

  // Reset from props on open only — reading them on every render would fight
  // the user's typing once the optimistic cache update lands.
  useEffect(() => {
    if (!open) return;
    setPrefix(initialPrefix ?? '');
    setDisplayName(initialDisplayName ?? '');
  }, [open, scriptRef]);

  const submit = () => onSave(prefix.trim(), displayName.trim());

  const handleKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation();
    if (e.key === 'Enter') {
      e.preventDefault();
      submit();
    }
  };

  return (
    <Popover
      open={open}
      anchorEl={anchorEl}
      onClose={onClose}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      transformOrigin={{ vertical: 'top', horizontal: 'left' }}
      onClick={(e) => e.stopPropagation()}
    >
      <Box sx={{ p: 1.5, width: 340 }} onKeyDown={handleKeyDown}>
        <Typography
          variant="caption"
          sx={{
            display: 'block',
            mb: 1,
            fontFamily: 'monospace',
            color: 'text.secondary',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={scriptRef}
        >
          {scriptRef}
        </Typography>

        <Box sx={{ display: 'flex', gap: 1 }}>
          <TextField
            label="Prefix"
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
            size="small"
            autoFocus
            placeholder="TC021"
            inputProps={{ maxLength: 32, style: { fontFamily: 'monospace' } }}
            sx={{ width: 110 }}
          />
          <TextField
            label="Display name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            size="small"
            placeholder="Superping"
            inputProps={{ maxLength: 255 }}
            sx={{ flex: 1 }}
          />
        </Box>

        {warning && (
          <Typography variant="caption" sx={{ display: 'block', mt: 1, color: 'warning.main' }}>
            {warning}
          </Typography>
        )}

        <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, mt: 1.5 }}>
          <Button
            size="small"
            color="inherit"
            disabled={saving || (!prefix && !displayName)}
            onClick={() => onSave('', '')}
          >
            Clear
          </Button>
          <Button size="small" variant="contained" disabled={saving} onClick={submit}>
            Save
          </Button>
        </Box>
      </Box>
    </Popover>
  );
};
