/**
 * QuickTestInputsBar — thin "Variables" chip-bar above the QuickTest step list.
 *
 * Each chip is one input variable (name = default [type]); clicking it opens a
 * small popover to edit name / type / default. Variables are also auto-created
 * when a step references an unknown {name}, so this bar is mostly a place to
 * SEE and tune them — deliberately NOT the visual builder's ScriptIOSections.
 *
 * Protected inputs (host_name & co., added when a testcase round-trips through
 * the visual builder) are preserved in state but hidden here.
 */

import { Add as AddIcon } from '@mui/icons-material';
import {
  Box,
  Button,
  Chip,
  MenuItem,
  Popover,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useState } from 'react';

import { ScriptInput } from '../../../../frontend/src/types/testcase/TestCase_Types';

const INPUT_TYPES = [
  { value: 'node', label: 'Node' },
  { value: 'string', label: 'Text' },
  { value: 'number', label: 'Number' },
];

interface NavNodeOption {
  node_id?: string;
  label?: string;
  node_type?: string;
}

interface QuickTestInputsBarProps {
  inputs: ScriptInput[];
  /** Names referenced by at least one step — their chips can't be deleted. */
  referencedNames: Set<string>;
  navNodes: NavNodeOption[];
  onAdd: (input: ScriptInput) => void;
  onUpdate: (name: string, patch: Partial<ScriptInput>) => void;
  onRemove: (name: string) => void;
  disabled?: boolean;
}

interface EditorState {
  anchor: HTMLElement;
  /** null = creating a new variable. */
  original: ScriptInput | null;
  draft: ScriptInput;
}

const NEW_INPUT: ScriptInput = { name: '', type: 'node', required: true, default: '' };

export const QuickTestInputsBar: React.FC<QuickTestInputsBarProps> = ({
  inputs,
  referencedNames,
  navNodes,
  onAdd,
  onUpdate,
  onRemove,
  disabled,
}) => {
  const [editor, setEditor] = useState<EditorState | null>(null);

  const visibleInputs = inputs.filter((input) => !input.protected);
  const nodeOptions = navNodes.filter((n) => n.label && n.node_type !== 'entry');

  const openEditor = (anchor: HTMLElement, input: ScriptInput | null) =>
    setEditor({ anchor, original: input, draft: input ? { ...input } : { ...NEW_INPUT } });

  const closeEditor = () => setEditor(null);

  const nameTaken =
    !!editor &&
    editor.draft.name !== editor.original?.name &&
    inputs.some((i) => i.name === editor.draft.name);
  const draftValid = !!editor && !!editor.draft.name.trim() && !nameTaken;

  const commitEditor = () => {
    if (!editor || !draftValid) return;
    const draft = { ...editor.draft, name: editor.draft.name.trim() };
    if (editor.original) {
      onUpdate(editor.original.name, draft);
    } else {
      onAdd(draft);
    }
    closeEditor();
  };

  const renderDefaultField = () => {
    if (!editor) return null;
    const { draft } = editor;
    const onChange = (value: string) =>
      setEditor((prev) => (prev ? { ...prev, draft: { ...prev.draft, default: value } } : prev));

    if (draft.type === 'node' && nodeOptions.length > 0) {
      return (
        <TextField
          select
          size="small"
          fullWidth
          label="Default node"
          value={draft.default || ''}
          onChange={(e) => onChange(e.target.value)}
        >
          {nodeOptions.map((n) => (
            <MenuItem key={n.node_id || n.label} value={n.label!}>
              {n.label}
            </MenuItem>
          ))}
        </TextField>
      );
    }
    return (
      <TextField
        size="small"
        fullWidth
        label="Default value"
        type={draft.type === 'number' ? 'number' : 'text'}
        value={draft.default ?? ''}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  };

  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
      <Typography variant="caption" sx={{ fontWeight: 600, opacity: 0.7 }}>
        Variables:
      </Typography>

      {visibleInputs.map((input) => {
        const referenced = referencedNames.has(input.name);
        const missingDefault = input.required && !String(input.default ?? '').trim();
        const chip = (
          <Chip
            key={input.name}
            size="small"
            variant="outlined"
            color={missingDefault ? 'warning' : 'secondary'}
            label={`${input.name} = ${String(input.default ?? '') || '—'}`}
            onClick={(e) => openEditor(e.currentTarget, input)}
            onDelete={referenced || disabled ? undefined : () => onRemove(input.name)}
          />
        );
        return referenced ? (
          <Tooltip key={input.name} title="Used by a step — remove the {reference} first to delete">
            {chip}
          </Tooltip>
        ) : (
          chip
        );
      })}

      <Button
        size="small"
        startIcon={<AddIcon />}
        disabled={disabled}
        onClick={(e) => openEditor(e.currentTarget, null)}
      >
        Variable
      </Button>

      <Popover
        open={!!editor}
        anchorEl={editor?.anchor}
        onClose={closeEditor}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      >
        <Box sx={{ p: 2, width: 280 }}>
          <Stack spacing={1.5}>
            <TextField
              autoFocus
              size="small"
              fullWidth
              label="Name"
              value={editor?.draft.name ?? ''}
              error={nameTaken}
              helperText={nameTaken ? 'A variable with this name already exists' : undefined}
              onChange={(e) =>
                setEditor((prev) =>
                  prev ? { ...prev, draft: { ...prev.draft, name: e.target.value } } : prev,
                )
              }
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitEditor();
              }}
            />
            <TextField
              select
              size="small"
              fullWidth
              label="Type"
              value={editor?.draft.type ?? 'node'}
              onChange={(e) =>
                setEditor((prev) =>
                  prev
                    ? { ...prev, draft: { ...prev.draft, type: e.target.value, default: '' } }
                    : prev,
                )
              }
            >
              {INPUT_TYPES.map((t) => (
                <MenuItem key={t.value} value={t.value}>
                  {t.label}
                </MenuItem>
              ))}
            </TextField>
            {renderDefaultField()}
            <Stack direction="row" spacing={1} justifyContent="flex-end">
              <Button size="small" onClick={closeEditor}>
                Cancel
              </Button>
              <Button size="small" variant="contained" disabled={!draftValid} onClick={commitEditor}>
                {editor?.original ? 'Update' : 'Add'}
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Popover>
    </Stack>
  );
};
