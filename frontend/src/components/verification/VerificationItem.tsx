import {
  Close as CloseIcon,
  KeyboardArrowUp as KeyboardArrowUpIcon,
  KeyboardArrowDown as KeyboardArrowDownIcon,
  PlayArrow as PlayArrowIcon,
  CameraAlt as CameraAltIcon,
} from '@mui/icons-material';
import {
  Box,
  FormControl,
  FormControlLabel,
  Checkbox,
  InputLabel,
  Select,
  MenuItem,
  IconButton,
  TextField,
  InputAdornment,
  Tooltip,
  CircularProgress,
} from '@mui/material';
import React from 'react';

import {
  Verification,
  Verifications,
  ModelReferences,
} from '../../types/verification/Verification_Types';

import { SearchableSelect, SearchableSelectOption } from '../common/SearchableSelect';
import { ReferenceImagePreview } from './ReferenceImagePreview';
import { VerificationControls, VerificationControlsLinkProps } from './VerificationControls';
import { VerificationTestResults } from './VerificationTestResults';

interface VerificationItemProps {
  verification: Verification;
  index: number;
  availableVerifications: Verifications;
  modelReferences: ModelReferences;
  referencesLoading: boolean;
  testResult?: Verification;
  onVerificationSelect: (index: number, command: string) => void;
  onReferenceSelect: (index: number, referenceName: string) => void;
  onImageFilterChange: (index: number, filter: 'none' | 'greyscale' | 'binary') => void;
  onTextFilterChange: (index: number, filter: 'none' | 'greyscale' | 'binary') => void;
  onUpdateVerification: (index: number, updates: Partial<Verification>) => void;
  onRemoveVerification: (index: number) => void;
  onMoveUp: (index: number) => void;
  onMoveDown: (index: number) => void;
  onImageClick: (
    sourceUrl: string,
    referenceUrl: string,
    overlayUrl?: string,
    userThreshold?: number,
    matchingResult?: number,
    resultType?: 'PASS' | 'FAIL' | 'ERROR',
    imageFilter?: 'none' | 'greyscale' | 'binary',
    focusScore?: number,
    focusThreshold?: number,
  ) => void;
  onSourceImageClick: (
    searchedText: string,
    extractedText: string,
    sourceUrl?: string,
    resultType?: 'PASS' | 'FAIL' | 'ERROR',
    detectedLanguage?: string,
    languageConfidence?: number,
    imageFilter?: 'none' | 'greyscale' | 'binary',
    focusScore?: number,
    focusThreshold?: number,
  ) => void;
  processImageUrl: (url: string) => string;
  getCacheBustedUrl: (url: string) => string;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onRun?: (index: number) => void;
  canRun?: boolean;
  isRunning?: boolean;
  disabled?: boolean;
  onTextChange?: (index: number, text: string) => void;
  // Locks Search Text + X/Y/W/H. Those edits set text_modified /
  // area_modified, which the dialog save propagates to the reference asset
  // via /server/verification/text/saveText — overwriting it for every node
  // and edge that uses it. Reference authoring belongs to VerificationEditor.
  referenceReadOnly?: boolean;
  // Escape hatch for referenceReadOnly, scoped to TEXT references only. When
  // true (Node Edit dialog), the Search Text field and the X/Y/W/H of a TEXT
  // verification become editable, and the dialog save writes the change back
  // to the reference row (text_helpers.save_text_reference) so the node's
  // inline snapshot and the verifications_references row stay in lockstep —
  // no round-trip through the VerificationEditor. Image references stay locked
  // (their stored crop can't be updated without a fresh frame; use Recapture).
  allowReferenceEdit?: boolean;
  // When provided, render a "Recapture" camera icon next to the image
  // reference select. Click takes a fresh screenshot and overwrites the
  // reference image using its existing area (box + fuzzy), no re-drag.
  // Requires an active device; the parent owns the confirmation + execution.
  onRecaptureReference?: (index: number) => void;
  isRecapturing?: boolean;
  recaptureDisabled?: boolean;
  // Optional per-field data-linking (TestCase builder inline editor only).
  // Undefined in the navigation Node/Edge dialogs → no behavior change.
  linkProps?: VerificationControlsLinkProps;
}

export const VerificationItem: React.FC<VerificationItemProps> = ({
  verification,
  index,
  availableVerifications,
  modelReferences,
  referencesLoading: _referencesLoading,
  testResult,
  onVerificationSelect,
  onReferenceSelect,
  onImageFilterChange: _onImageFilterChange,
  onTextFilterChange: _onTextFilterChange,
  onUpdateVerification,
  onRemoveVerification,
  onMoveUp,
  onMoveDown,
  onImageClick,
  onSourceImageClick,
  processImageUrl,
  getCacheBustedUrl,
  canMoveUp,
  canMoveDown,
  onRun,
  canRun = false,
  isRunning = false,
  disabled = false,
  onTextChange,
  referenceReadOnly = false,
  allowReferenceEdit = false,
  onRecaptureReference,
  isRecapturing = false,
  recaptureDisabled = false,
  linkProps,
}) => {
  // Text references can be edited inline (and propagated on save) when the
  // host dialog opts in via allowReferenceEdit. Image references stay locked
  // by referenceReadOnly regardless — editing their area without re-cropping
  // would desync the stored crop from the area.
  const textRefEditable = allowReferenceEdit && verification.verification_type === 'text';
  const effectiveReferenceReadOnly = referenceReadOnly && !textRefEditable;

  // Reference lists can hold hundreds of entries — feed them to
  // SearchableSelect (type-to-filter + Enter picks top match).
  const buildReferenceOptions = (type: 'text' | 'image'): SearchableSelectOption[] =>
    Object.entries(modelReferences)
      .filter(([_internalKey, ref]) => ref.type === type)
      .sort(([aKey, aRef], [bKey, bRef]) =>
        (aRef.name || aKey).toLowerCase().localeCompare((bRef.name || bKey).toLowerCase()),
      )
      .map(([internalKey, ref]) => ({
        value: internalKey,
        label: ref.name || internalKey,
        icon: type === 'text' ? '📝' : '🖼️',
      }));
  const textReferenceOptions = React.useMemo(
    () => buildReferenceOptions('text'),
    [modelReferences],
  );
  const imageReferenceOptions = React.useMemo(
    () => buildReferenceOptions('image'),
    [modelReferences],
  );
  return (
    <Box
      sx={{
        mb: 0.5,
        px: 0.5,
        py: 0.5,
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
      }}
    >
      {/* Line 1: Verification dropdown */}
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', mb: 0.5 }}>
        <FormControl size="small" sx={{ flex: 1, minWidth: 200, maxWidth: 300 }}>
          <InputLabel>Verification</InputLabel>
          <Select
            value={verification.command}
            onChange={(e) => onVerificationSelect(index, e.target.value)}
            label="Verification"
            size="small"
            disabled={disabled}
            sx={{
              '& .MuiSelect-select': {
                fontSize: '0.8rem',
                py: 0.5,
              },
            }}
            renderValue={(selected) => {
              // Find the selected verification and return its formatted name
              const selectedVerification = Object.values(availableVerifications)
                .flat()
                .find((verif) => verif.command === selected);
              if (selectedVerification) {
                return selectedVerification.command
                  .replace(/_/g, ' ')
                  .replace(/([A-Z])/g, ' $1')
                  .trim();
              }
              return selected;
            }}
          >
            {Object.entries(availableVerifications).map(([category, verifications]) => {
              // Ensure verifications is an array
              if (!Array.isArray(verifications)) {
                console.warn(
                  `[@component:VerificationItem] Invalid verifications for category ${category}:`,
                  verifications,
                );
                return null;
              }

              return [
                <MenuItem
                  key={`header-${category}`}
                  disabled
                  sx={{ fontWeight: 'bold', fontSize: '0.65rem', minHeight: '20px' }}
                >
                  {category.replace(/_/g, ' ').toUpperCase()}
                </MenuItem>,
                ...verifications.map((verification, vIndex) => (
                  <MenuItem
                    key={`${category}-${verification.command}-${vIndex}`}
                    value={verification.command}
                    sx={{ pl: 3, fontSize: '0.7rem', minHeight: '24px' }}
                  >
                    {verification.command
                      ? verification.command
                          .replace(/_/g, ' ')
                          .replace(/([A-Z])/g, ' $1')
                          .trim()
                      : 'Unknown Command'}
                  </MenuItem>
                )),
              ];
            })}
          </Select>
        </FormControl>

        {onRun && (
          <Tooltip title="Run this verification">
            <span>
              <IconButton
                size="small"
                onClick={() => onRun(index)}
                disabled={!canRun || disabled}
                sx={{ p: 0.5, minWidth: 24, width: 24, height: 24, ml: 0.25 }}
              >
                {isRunning ? <CircularProgress size={14} /> : <PlayArrowIcon sx={{ fontSize: '1rem' }} />}
              </IconButton>
            </span>
          </Tooltip>
        )}

        {/* Move buttons */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          <IconButton
            size="small"
            onClick={() => onMoveUp(index)}
            disabled={!canMoveUp || disabled}
            sx={{ p: 0.25, minWidth: 0, width: 20, height: 16 }}
          >
            <KeyboardArrowUpIcon sx={{ fontSize: '0.8rem' }} />
          </IconButton>
          <IconButton
            size="small"
            onClick={() => onMoveDown(index)}
            disabled={!canMoveDown || disabled}
            sx={{ p: 0.25, minWidth: 0, width: 20, height: 16 }}
          >
            <KeyboardArrowDownIcon sx={{ fontSize: '0.8rem' }} />
          </IconButton>
        </Box>

        {/* Remove button */}
        <IconButton
          size="small"
          onClick={() => onRemoveVerification(index)}
          disabled={disabled}
          sx={{ p: 0.25, minWidth: 0, width: 20, height: 20 }}
        >
          <CloseIcon sx={{ fontSize: '0.8rem' }} />
        </IconButton>
      </Box>

      {/* Line 2: Text Reference + Search Text - side by side */}
      {verification.command && verification.verification_type === 'text' && (
        <Box sx={{ display: 'flex', gap: 1, mb: 0.5 }}>
          {/* LEFT: Text Reference Dropdown */}
          <SearchableSelect
            label="Text Reference"
            value={verification.params?.reference_name || ''}
            onChange={(referenceName) => onReferenceSelect(index, referenceName)}
            options={textReferenceOptions}
            disabled={disabled}
            emptyText="No text references available"
            sx={{ flex: 1 }}
          />

          {/* RIGHT: Search Text Field - Editable */}
          <TextField
            size="small"
            label="Search Text"
            value={verification.params?.text || ''}
            onChange={(e) => {
              if (onTextChange) {
                onTextChange(index, e.target.value);
              }
            }}
            disabled={disabled}
            sx={{
              flex: 1,
              '& .MuiInputBase-input': {
                fontSize: '0.8rem',
              },
            }}
            InputProps={{
              readOnly: effectiveReferenceReadOnly,
              endAdornment: (
                <InputAdornment position="end">
                  <span style={{ fontSize: '0.9rem' }}>🔍</span>
                </InputAdornment>
              ),
            }}
          />

          {/* Focus: same as image — also verify the element is focused/selected.
              Lets you see (and require) whether the text reference was captured
              with the focus highlight in its area. See docs/agent/devices/image.md. */}
          {verification.command === 'waitForTextToAppear' &&
            (() => {
              const selectedRef = verification.params?.reference_name
                ? modelReferences[verification.params.reference_name]
                : undefined;
              return (
                <Tooltip title="Also verify the element is focused/selected. Tick, then recapture to learn the highlight accent (border / underline / fill) from a fresh frame.">
                  <FormControlLabel
                    control={
                      <Checkbox
                        size="small"
                        checked={Boolean(
                          verification.params?.check_focus ?? (selectedRef?.area as any)?.focus,
                        )}
                        onChange={(e) =>
                          onUpdateVerification(index, {
                            params: { ...verification.params, check_focus: e.target.checked },
                          })
                        }
                        disabled={disabled}
                        sx={{ p: 0.25 }}
                      />
                    }
                    label="Focus"
                    sx={{
                      ml: 0.25,
                      mr: 0,
                      flexShrink: 0,
                      '& .MuiFormControlLabel-label': { fontSize: '0.7rem' },
                    }}
                  />
                </Tooltip>
              );
            })()}
        </Box>
      )}

      {/* Icon verification: pick a built-in transport glyph (no R2 reference).
          The OSD area is drawn/edited via VerificationControls below, same as image. */}
      {verification.command &&
        (verification.command === 'waitForIconToAppear' ||
          verification.command === 'waitForIconToDisappear' ||
          verification.command === 'waitForIconToAppearThenDisappear') && (
          <Box sx={{ mb: 0.5, display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <FormControl size="small" sx={{ width: 250 }}>
              <InputLabel>Icon</InputLabel>
              <Select
                value={(verification.params as any)?.icon || 'play'}
                onChange={(e) =>
                  onUpdateVerification(index, {
                    params: { ...(verification.params as any), icon: e.target.value },
                  })
                }
                label="Icon"
                size="small"
                disabled={disabled}
                sx={{ '& .MuiSelect-select': { fontSize: '0.8rem', py: 0.5 } }}
              >
                {['play', 'pause', 'stop', 'fast_forward', 'rewind', 'question_mark'].map(
                  (name) => (
                    <MenuItem key={name} value={name} sx={{ fontSize: '0.75rem' }}>
                      {name.replace(/_/g, ' ')}
                    </MenuItem>
                  ),
                )}
              </Select>
            </FormControl>
          </Box>
        )}

      {verification.command &&
        verification.verification_type === 'image' &&
        verification.command !== 'waitForIconToAppear' &&
        verification.command !== 'waitForIconToDisappear' &&
        verification.command !== 'waitForIconToAppearThenDisappear' &&
        (() => {
        const selectedRefKey = verification.params?.reference_name || '';
        const selectedRef = selectedRefKey ? modelReferences[selectedRefKey] : undefined;
        const previewUrl =
          selectedRef && selectedRef.type === 'image' && selectedRef.url
            ? selectedRef.url
            : null;
        return (
          <Box sx={{ mb: 0.5, display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <SearchableSelect
              label="Image Reference"
              value={selectedRefKey}
              onChange={(referenceName) => onReferenceSelect(index, referenceName)}
              options={imageReferenceOptions}
              disabled={disabled}
              emptyText="No image references available"
              sx={{ width: 250 }}
            />
            {previewUrl && <ReferenceImagePreview referenceUrl={previewUrl} disabled={disabled} />}
            {onRecaptureReference && (
              <Tooltip title="Recapture: take a fresh screenshot and overwrite this reference using its current area">
                <span>
                  <IconButton
                    size="small"
                    onClick={() => onRecaptureReference(index)}
                    disabled={disabled || recaptureDisabled || isRecapturing || !selectedRefKey}
                    sx={{ p: 0.5, minWidth: 24, width: 24, height: 24 }}
                  >
                    {isRecapturing ? (
                      <CircularProgress size={14} />
                    ) : (
                      <CameraAltIcon sx={{ fontSize: '1rem' }} />
                    )}
                  </IconButton>
                </span>
              </Tooltip>
            )}
            {/* Focus: only meaningful for "wait For Image To Appear" — also verify
                the element is selected/focused. Ticking it then recapturing learns
                the highlight accent (border / underline / fill). The reference area
                must include the focus indicator. See docs/agent/devices/image.md. */}
            {verification.command === 'waitForImageToAppear' && (
              <Tooltip title="Also verify the element is focused/selected. Tick, then recapture to learn the highlight accent (border / underline / fill) from a fresh frame.">
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={Boolean(
                        verification.params?.check_focus ?? (selectedRef?.area as any)?.focus,
                      )}
                      onChange={(e) =>
                        onUpdateVerification(index, {
                          params: { ...verification.params, check_focus: e.target.checked },
                        })
                      }
                      disabled={disabled}
                      sx={{ p: 0.25 }}
                    />
                  }
                  label="Focus"
                  sx={{
                    ml: 0.25,
                    mr: 0,
                    '& .MuiFormControlLabel-label': { fontSize: '0.7rem' },
                  }}
                />
              </Tooltip>
            )}
          </Box>
        );
      })()}

      {/* Verification Controls */}
      <VerificationControls
        verification={verification}
        onUpdateVerification={onUpdateVerification}
        index={index}
        disabled={disabled}
        referenceReadOnly={effectiveReferenceReadOnly}
        linkProps={linkProps}
      />

      {/* Test Results Display using extracted component */}
      {testResult && (
        <VerificationTestResults
          verification={verification}
          testResult={testResult}
          onImageClick={onImageClick}
          onSourceImageClick={onSourceImageClick}
          processImageUrl={processImageUrl}
          getCacheBustedUrl={getCacheBustedUrl}
        />
      )}
    </Box>
  );
};
