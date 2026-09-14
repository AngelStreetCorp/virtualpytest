import React from 'react';
import { Box, Chip, TextField, Tooltip } from '@mui/material';
import LinkIcon from '@mui/icons-material/Link';

import { Verification } from '../../types/verification/Verification_Types';

// Output→input data link for one param, as stored in a block's data.paramLinks.
export interface ParamLink {
  sourceBlockId: string;
  sourceOutputName: string;
  sourceOutputType: string;
}

// Optional linking surface. When provided (TestCase builder inline editor),
// scalar fields become drop targets for upstream block outputs and render a
// "← source" pill when linked. When undefined (navigation Node/Edge dialogs),
// rendering is unchanged.
export interface VerificationControlsLinkProps {
  paramLinks?: Record<string, ParamLink>;
  draggedOutput?: { blockId: string; outputName: string; outputType: string } | null;
  onLinkDrop?: (paramKey: string, drag: { blockId: string; outputName: string; outputType: string }) => void;
  onUnlink?: (paramKey: string) => void;
}

interface VerificationControlsProps {
  verification: Verification;
  index: number;
  onUpdateVerification: (index: number, updates: Partial<Verification>) => void;
  disabled?: boolean;
  // Locks X/Y/Width/Height. Editing them sets area_modified, which the
  // owning dialog's save would forward to /server/verification/text/saveText
  // and overwrite the reference asset shared by every other node/edge that
  // uses it. Reference authoring belongs to VerificationEditor.
  referenceReadOnly?: boolean;
  // Optional per-field data-linking (TestCase builder inline editor only).
  linkProps?: VerificationControlsLinkProps;
}

export const VerificationControls: React.FC<VerificationControlsProps> = ({
  verification,
  index,
  onUpdateVerification,
  disabled = false,
  referenceReadOnly = false,
  linkProps,
}) => {
  // Wrap a scalar field so it can receive an output→input link. Linked params
  // render a "key ← source" pill (with unlink) instead of the input. Unlinked
  // params render the field inside a drop target. No-op when linkProps absent.
  const withLink = (paramKey: string, field: React.ReactNode): React.ReactNode => {
    if (!linkProps) return field;
    const link = linkProps.paramLinks?.[paramKey];
    if (link) {
      return (
        <Chip
          key={paramKey}
          size="small"
          icon={<LinkIcon sx={{ fontSize: 14 }} />}
          label={`${paramKey} ← ${link.sourceOutputName}`}
          onDelete={disabled ? undefined : () => linkProps.onUnlink?.(paramKey)}
          sx={{ fontSize: '0.75rem', height: 26, borderColor: '#10b981', color: '#10b981' }}
          variant="outlined"
        />
      );
    }
    return (
      <Tooltip key={paramKey} title="Drop an output here to link" disableHoverListener={!linkProps.draggedOutput}>
        <Box
          onDragOver={(e) => {
            if (linkProps.draggedOutput) {
              e.preventDefault();
              e.stopPropagation();
            }
          }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            if (linkProps.draggedOutput) {
              linkProps.onLinkDrop?.(paramKey, linkProps.draggedOutput);
            }
          }}
          sx={{
            display: 'inline-flex',
            borderRadius: 1,
            outline: linkProps.draggedOutput ? '1px dashed #10b981' : 'none',
            outlineOffset: 2,
          }}
        >
          {field}
        </Box>
      </Tooltip>
    );
  };

  return (
    // flexWrap lets the Timeout/Threshold/X/Y/W/H fields wrap instead of
    // overflowing a narrow container (inline TestCase block). Additive — in the
    // wider Node/Edge dialogs there is enough room that nothing wraps.
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, alignItems: 'center', mb: 0, px: 0, mx: 0 }}>
      {verification.command && withLink('timeout',
        <TextField
          size="small"
          type="number"
          label="Timeout (ms)"
          value={verification.params?.timeout !== undefined ? verification.params.timeout : 0}
          autoComplete="off"
          disabled={disabled}
          onChange={(e) => {
            const value = parseInt(e.target.value, 10);
            onUpdateVerification(index, {
              params: {
                ...verification.params,
                timeout: isNaN(value) ? 0 : value,
              },
            });
          }}
          sx={{
            // Wide enough for the full "Timeout (ms)" label (MUI clips the
            // outlined label to the field width → "Timeout…" at 80px) and a
            // 5-digit value like 12000.
            width: 110,
            '& .MuiInputBase-input': {
              padding: '4px 8px',
              fontSize: '0.8rem',
            },
          }}
          inputProps={{ min: 0, max: 30000, step: 500 }}
        />
      )}

      {verification.command && (verification.verification_type === 'adb' || verification.verification_type === 'web') && (
        <TextField
          size="small"
          label="Element Criteria"
          placeholder="text=Button"
          value={
            typeof verification.params?.search_term === 'string'
              ? verification.params.search_term
              : ''
          }
          autoComplete="off"
          disabled={disabled}
          onChange={(e) =>
            onUpdateVerification(index, {
              params: { ...verification.params, search_term: e.target.value },
            })
          }
          sx={{
            flex: 1,
            '& .MuiInputBase-input': {
              padding: '4px 8px',
              fontSize: '0.8rem',
            },
          }}
        />
      )}

      {/* Threshold — image similarity threshold AND OCR match score threshold.
          Text uses the same 0.0-1.0 scale (1.0 = exact substring, partial
          matches scored by difflib). Floor differs: image 0.1, text 0.7
          (project convention — recapture references rather than dropping
          below 0.7; the backend also clamps server-side). */}
      {verification.command &&
        (verification.verification_type === 'image' ||
          verification.verification_type === 'text') && withLink('threshold',
          <TextField
            size="small"
            type="number"
            label="Threshold"
            value={verification.params?.threshold ?? 0.8}
            autoComplete="off"
            disabled={disabled}
            onChange={(e) =>
              onUpdateVerification(index, {
                params: {
                  ...verification.params,
                  threshold: parseFloat(e.target.value) || 0.8,
                },
              })
            }
            sx={{
              width: 80,
              '& .MuiInputBase-input': {
                padding: '4px 8px',
                fontSize: '0.8rem',
              },
            }}
            inputProps={{
              min: verification.verification_type === 'text' ? 0.7 : 0.1,
              max: 1.0,
              step: 0.05,
            }}
          />
        )}

      {verification.command &&
        (verification.verification_type === 'image' ||
          verification.verification_type === 'text') && (
          <>
            <TextField
              size="small"
              type="number"
              label="X"
              value={Math.round(verification.params?.area?.x || 0)}
              autoComplete="off"
              disabled={disabled}
              onChange={(e) =>
                onUpdateVerification(index, {
                  params: {
                    ...verification.params,
                    area: {
                      ...(verification.params?.area || { x: 0, y: 0, width: 100, height: 100 }),
                      x: Math.round(parseFloat(e.target.value) || 0),
                    },
                    area_modified: true, // Mark area as modified for reference update
                  },
                })
              }
              sx={{
                width: 70,
                '& .MuiInputBase-input': {
                  padding: '4px 8px',
                  fontSize: '0.8rem',
                },
              }}
              inputProps={{ min: 0, step: 1, readOnly: referenceReadOnly }}
            />
            <TextField
              size="small"
              type="number"
              label="Y"
              value={Math.round(verification.params?.area?.y || 0)}
              autoComplete="off"
              disabled={disabled}
              onChange={(e) =>
                onUpdateVerification(index, {
                  params: {
                    ...verification.params,
                    area: {
                      ...(verification.params?.area || { x: 0, y: 0, width: 100, height: 100 }),
                      y: Math.round(parseFloat(e.target.value) || 0),
                    },
                    area_modified: true, // Mark area as modified for reference update
                  },
                })
              }
              sx={{
                width: 70,
                '& .MuiInputBase-input': {
                  padding: '4px 8px',
                  fontSize: '0.8rem',
                },
              }}
              inputProps={{ min: 0, step: 1, readOnly: referenceReadOnly }}
            />
            <TextField
              size="small"
              type="number"
              label="Width"
              value={Math.round(verification.params?.area?.width || 100)}
              autoComplete="off"
              disabled={disabled}
              onChange={(e) =>
                onUpdateVerification(index, {
                  params: {
                    ...verification.params,
                    area: {
                      ...(verification.params?.area || { x: 0, y: 0, width: 100, height: 100 }),
                      width: Math.round(parseFloat(e.target.value) || 100),
                    },
                    area_modified: true, // Mark area as modified for reference update
                  },
                })
              }
              sx={{
                width: 80,
                '& .MuiInputBase-input': {
                  padding: '4px 8px',
                  fontSize: '0.8rem',
                },
              }}
              inputProps={{ min: 1, step: 1, readOnly: referenceReadOnly }}
            />
            <TextField
              size="small"
              type="number"
              label="Height"
              value={Math.round(verification.params?.area?.height || 100)}
              autoComplete="off"
              disabled={disabled}
              onChange={(e) =>
                onUpdateVerification(index, {
                  params: {
                    ...verification.params,
                    area: {
                      ...(verification.params?.area || { x: 0, y: 0, width: 100, height: 100 }),
                      height: Math.round(parseFloat(e.target.value) || 100),
                    },
                    area_modified: true, // Mark area as modified for reference update
                  },
                })
              }
              sx={{
                width: 80,
                '& .MuiInputBase-input': {
                  padding: '4px 8px',
                  fontSize: '0.8rem',
                },
              }}
              inputProps={{ min: 1, step: 1, readOnly: referenceReadOnly }}
            />
          </>
        )}
    </Box>
  );
};
