import {
  Camera as CameraIcon,
  KeyboardArrowDown as ArrowDownIcon,
  KeyboardArrowRight as ArrowRightIcon,
} from '@mui/icons-material';
import {
  Box,
  Button,
  Typography,
  TextField,
  Collapse,
  IconButton,
  FormControlLabel,
  RadioGroup,
  Radio,
  Checkbox,
  Tooltip,
} from '@mui/material';
import React, { useRef, useMemo } from 'react';

import { UseVerificationEditorType } from '../../../hooks/verification/useVerificationEditor';
import { useR2Url } from '../../../hooks/storage/useR2Url';
import { AGENT_CHAT_PALETTE } from '../../../constants/agentChatTheme';

interface DragArea {
  x: number;
  y: number;
  width: number;
  height: number;
  // Fuzzy search area (optional)
  fx?: number;
  fy?: number;
  fwidth?: number;
  fheight?: number;
}

interface VerificationCaptureProps {
  verification: UseVerificationEditorType;
  selectedArea: DragArea | null;
  onAreaSelected?: (area: DragArea) => void;
  captureHeight: number;
  isMobileModel: boolean;
}

export const VerificationCapture: React.FC<VerificationCaptureProps> = ({
  verification,
  selectedArea,
  onAreaSelected,
  captureHeight,
  isMobileModel,
}) => {
  const captureContainerRef = useRef<HTMLDivElement>(null);

  const {
    captureCollapsed,
    setCaptureCollapsed,
    capturedReferenceImage,
    successMessage,
    selectedReferenceImage,
    selectedReferenceInfo,
    referenceType,
    handleReferenceTypeChange,
    imageProcessingOptions,
    setImageProcessingOptions,
    referenceText,
    setReferenceText,
    checkFocus,
    setCheckFocus,
    detectedTextData: _detectedTextData,
    handleAutoDetectText,
    validateRegex,
    referenceName,
    setReferenceName,
    canCapture,
    handleCaptureReference,
    canSave,
    pendingSave,
    handleSaveReference,
    allowSelection,
    saveSuccess,
  } = verification;

  // Use processed URL directly from backend
  const processedCapturedReferenceImage = capturedReferenceImage || '';

  // Use R2Url hook to handle signed URLs for private bucket reference images
  const { url: r2ReferenceUrl, loading: r2Loading } = useR2Url(selectedReferenceImage || null);
  
  // Debug: log URL transformation
  console.log('[@component:VerificationCapture] Reference URL debug:', {
    inputUrl: selectedReferenceImage,
    r2ReferenceUrl,
    r2Loading,
  });
  
  // Process the reference URL with proper handling for signed vs public URLs
  // Same pattern as Navigation_NavigationNode.tsx for consistency
  const processedSelectedReferenceImage = useMemo(() => {
    if (!r2ReferenceUrl) return '';
    
    // For signed URLs, do NOT append cache-busting params as it invalidates the signature
    if (r2ReferenceUrl.includes('X-Amz-Signature')) {
      console.log('[@component:VerificationCapture] Using signed URL for reference image:', r2ReferenceUrl.substring(0, 100) + '...');
      return r2ReferenceUrl;
    }
    
    // Public URL - add cache-busting
    const baseUrl = r2ReferenceUrl.split('?')[0];
    const timestamp = Date.now();
    console.log('[@component:VerificationCapture] Using public URL with cache-busting for reference image:', baseUrl);
    return `${baseUrl}?v=${timestamp}`;
  }, [r2ReferenceUrl]);

  return (
    <Box>
      {/* Capture Section Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
        <IconButton
          size="small"
          onClick={() => setCaptureCollapsed(!captureCollapsed)}
          sx={{ p: 0.25, mr: 0.5 }}
        >
          {captureCollapsed ? (
            <ArrowRightIcon sx={{ fontSize: '1rem' }} />
          ) : (
            <ArrowDownIcon sx={{ fontSize: '1rem' }} />
          )}
        </IconButton>
        <Typography variant="subtitle2" sx={{ fontSize: '0.8rem', fontWeight: 600 }}>
          Capture
        </Typography>
      </Box>

      {/* Collapsible Capture Content */}
      <Collapse in={!captureCollapsed}>
        <Box>
          {/* 1. Capture Container (Reference Image Preview) */}
          <Box>
            <Box
              ref={captureContainerRef}
              sx={{
                position: 'relative',
                width: '100%',
                height: captureHeight,
                border: '2px dashed #444',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: 1,
                bgcolor: 'rgba(255,255,255,0.05)',
                overflow: 'hidden',
                mb: 1.5,
              }}
            >
              {processedCapturedReferenceImage ? (
                <>
                  <img
                    src={processedCapturedReferenceImage}
                    alt="Captured Reference"
                    style={{
                      width: '100%',
                      height: '100%',
                      objectFit: 'contain',
                      maxHeight: isMobileModel ? 'none' : '100%',
                    }}
                  />
                  {/* Success message overlay */}
                  {successMessage && (
                    <Box
                      sx={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        right: 0,
                        bottom: 0,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        backgroundColor: 'rgba(0, 0, 0, 0.7)',
                        zIndex: 10,
                      }}
                    >
                      <Typography
                        variant="body2"
                        sx={{
                          color: '#4caf50',
                          fontSize: '0.9rem',
                          fontWeight: 600,
                          textAlign: 'center',
                          textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
                        }}
                      >
                        {successMessage}
                      </Typography>
                    </Box>
                  )}
                </>
              ) : processedSelectedReferenceImage ? (
                <>
                  <img
                    src={processedSelectedReferenceImage}
                    alt="Selected Reference"
                    style={{
                      width: '100%',
                      height: '100%',
                      objectFit: 'contain',
                      maxHeight: isMobileModel ? 'none' : '100%',
                    }}
                    onLoad={() =>
                      console.log(
                        '[@component:VerificationCapture] Selected reference image loaded successfully',
                      )
                    }
                    onError={(e) =>
                      console.error(
                        '[@component:VerificationCapture] Selected reference image failed to load:',
                        e,
                      )
                    }
                  />
                  {/* Reference info overlay */}
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 4,
                      left: 4,
                      backgroundColor: 'rgba(0, 0, 0, 0.7)',
                      borderRadius: 1,
                      padding: '2px 6px',
                      zIndex: 5,
                    }}
                  >
                    <Typography
                      variant="caption"
                      sx={{
                        color: '#90caf9',
                        fontSize: '0.65rem',
                        fontWeight: 600,
                      }}
                    >
                      📁 {selectedReferenceInfo?.name}
                    </Typography>
                  </Box>
                </>
              ) : (
                <Typography
                  variant="body2"
                  sx={{
                    color: 'rgba(255,255,255,0.7)',
                    fontSize: '0.65rem',
                    textAlign: 'center',
                    px: 0.5,
                  }}
                >
                  {allowSelection ? 'Drag area on main image' : 'No image'}
                </Typography>
              )}
            </Box>
          </Box>

          {/* 2. Drag Area Info (Selection Info) - Exact and Fuzzy Areas */}
          <Box sx={{ mb: 0.5 }}>
            {selectedArea ? (
              <>
                {/* Exact Area Label */}
                <Typography
                  variant="caption"
                  sx={{
                    fontSize: '0.65rem',
                    fontWeight: 600,
                    color: 'rgba(255,255,255,0.9)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 0.5,
                    mb: 0.3,
                  }}
                >
                  ⬜ Exact Reference Area
                </Typography>

                {/* Exact Area Fields - Row 1 */}
                <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 0.5, mb: 0.5 }}>
                  <TextField
                    size="small"
                    label="X"
                    type="number"
                    value={Math.round(selectedArea.x)}
                    autoComplete="off"
                    onChange={(e) => {
                      const newX = parseFloat(e.target.value) || 0;
                      if (onAreaSelected) {
                        onAreaSelected({
                          ...selectedArea,
                          x: newX,
                        });
                      }
                    }}
                    sx={{
                      height: '28px',
                      '& .MuiInputBase-root': {
                        height: '28px',
                        minHeight: '28px',
                        maxHeight: '28px',
                        overflow: 'hidden',
                      },
                      '& .MuiInputBase-input': {
                        fontSize: '0.65rem',
                        padding: '2px 6px',
                        height: '100%',
                        boxSizing: 'border-box',
                      },
                      '& .MuiInputLabel-root': {
                        fontSize: '0.65rem',
                        transform: 'translate(10px, 6px) scale(1)',
                        '&.Mui-focused, &.MuiFormLabel-filled': {
                          transform: 'translate(10px, -9px) scale(0.75)',
                        },
                      },
                    }}
                  />
                  <TextField
                    size="small"
                    label="Y"
                    type="number"
                    value={Math.round(selectedArea.y)}
                    autoComplete="off"
                    onChange={(e) => {
                      const newY = parseFloat(e.target.value) || 0;
                      if (onAreaSelected) {
                        onAreaSelected({
                          ...selectedArea,
                          y: newY,
                        });
                      }
                    }}
                    sx={{
                      height: '28px',
                      '& .MuiInputBase-root': {
                        height: '28px',
                        minHeight: '28px',
                        maxHeight: '28px',
                        overflow: 'hidden',
                      },
                      '& .MuiInputBase-input': {
                        fontSize: '0.65rem',
                        padding: '2px 6px',
                        height: '100%',
                        boxSizing: 'border-box',
                      },
                      '& .MuiInputLabel-root': {
                        fontSize: '0.65rem',
                        transform: 'translate(10px, 6px) scale(1)',
                        '&.Mui-focused, &.MuiFormLabel-filled': {
                          transform: 'translate(10px, -9px) scale(0.75)',
                        },
                      },
                    }}
                  />
                  <TextField
                    size="small"
                    label="W"
                    type="number"
                    value={Math.round(selectedArea.width)}
                    autoComplete="off"
                    onChange={(e) => {
                      const newWidth = parseFloat(e.target.value) || 0;
                      if (onAreaSelected) {
                        onAreaSelected({
                          ...selectedArea,
                          width: newWidth,
                        });
                      }
                    }}
                    sx={{
                      height: '28px',
                      '& .MuiInputBase-root': {
                        height: '28px',
                        minHeight: '28px',
                        maxHeight: '28px',
                        overflow: 'hidden',
                      },
                      '& .MuiInputBase-input': {
                        fontSize: '0.65rem',
                        padding: '2px 6px',
                        height: '100%',
                        boxSizing: 'border-box',
                      },
                      '& .MuiInputLabel-root': {
                        fontSize: '0.65rem',
                        transform: 'translate(10px, 6px) scale(1)',
                        '&.Mui-focused, &.MuiFormLabel-filled': {
                          transform: 'translate(10px, -9px) scale(0.75)',
                        },
                      },
                    }}
                  />
                  <TextField
                    size="small"
                    label="H"
                    type="number"
                    value={Math.round(selectedArea.height)}
                    autoComplete="off"
                    onChange={(e) => {
                      const newHeight = parseFloat(e.target.value) || 0;
                      if (onAreaSelected) {
                        onAreaSelected({
                          ...selectedArea,
                          height: newHeight,
                        });
                      }
                    }}
                    sx={{
                      height: '28px',
                      '& .MuiInputBase-root': {
                        height: '28px',
                        minHeight: '28px',
                        maxHeight: '28px',
                        overflow: 'hidden',
                      },
                      '& .MuiInputBase-input': {
                        fontSize: '0.65rem',
                        padding: '2px 6px',
                        height: '100%',
                        boxSizing: 'border-box',
                      },
                      '& .MuiInputLabel-root': {
                        fontSize: '0.65rem',
                        transform: 'translate(10px, 6px) scale(1)',
                        '&.Mui-focused, &.MuiFormLabel-filled': {
                          transform: 'translate(10px, -9px) scale(0.75)',
                        },
                      },
                    }}
                  />
                </Box>

                {/* Fuzzy Search Area — image only (text verification does not use fuzzy) */}
                {referenceType !== 'text' && (
                  <>
                {/* Fuzzy Search Area Label */}
                <Typography
                  variant="caption"
                  sx={{
                    fontSize: '0.65rem',
                    fontWeight: 600,
                    color: AGENT_CHAT_PALETTE.gold,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 0.5,
                    mb: 0.3,
                  }}
                >
                  🟨 Fuzzy Search Area (hold Shift to drag)
                </Typography>

                {/* Fuzzy Area Fields - Row 2 */}
                <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 0.5 }}>
                  <TextField
                    size="small"
                    label="FX"
                    type="number"
                    value={Math.round(selectedArea.fx || 0)}
                    autoComplete="off"
                    onChange={(e) => {
                      const newFX = parseFloat(e.target.value) || 0;
                      if (onAreaSelected) {
                        onAreaSelected({
                          ...selectedArea,
                          fx: newFX,
                        });
                      }
                    }}
                    sx={{
                      height: '28px',
                      '& .MuiInputBase-root': {
                        height: '28px',
                        minHeight: '28px',
                        maxHeight: '28px',
                        overflow: 'hidden',
                        borderColor: selectedArea.fx !== undefined ? AGENT_CHAT_PALETTE.gold : undefined,
                      },
                      '& .MuiInputBase-input': {
                        fontSize: '0.65rem',
                        padding: '2px 6px',
                        height: '100%',
                        boxSizing: 'border-box',
                      },
                      '& .MuiInputLabel-root': {
                        fontSize: '0.65rem',
                        color: selectedArea.fx !== undefined ? AGENT_CHAT_PALETTE.gold : undefined,
                        transform: 'translate(10px, 6px) scale(1)',
                        '&.Mui-focused, &.MuiFormLabel-filled': {
                          transform: 'translate(10px, -9px) scale(0.75)',
                        },
                      },
                    }}
                  />
                  <TextField
                    size="small"
                    label="FY"
                    type="number"
                    value={Math.round(selectedArea.fy || 0)}
                    autoComplete="off"
                    onChange={(e) => {
                      const newFY = parseFloat(e.target.value) || 0;
                      if (onAreaSelected) {
                        onAreaSelected({
                          ...selectedArea,
                          fy: newFY,
                        });
                      }
                    }}
                    sx={{
                      height: '28px',
                      '& .MuiInputBase-root': {
                        height: '28px',
                        minHeight: '28px',
                        maxHeight: '28px',
                        overflow: 'hidden',
                      },
                      '& .MuiInputBase-input': {
                        fontSize: '0.65rem',
                        padding: '2px 6px',
                        height: '100%',
                        boxSizing: 'border-box',
                      },
                      '& .MuiInputLabel-root': {
                        fontSize: '0.65rem',
                        color: selectedArea.fy !== undefined ? AGENT_CHAT_PALETTE.gold : undefined,
                        transform: 'translate(10px, 6px) scale(1)',
                        '&.Mui-focused, &.MuiFormLabel-filled': {
                          transform: 'translate(10px, -9px) scale(0.75)',
                        },
                      },
                    }}
                  />
                  <TextField
                    size="small"
                    label="FW"
                    type="number"
                    value={Math.round(selectedArea.fwidth || 0)}
                    autoComplete="off"
                    onChange={(e) => {
                      const newFWidth = parseFloat(e.target.value) || 0;
                      if (onAreaSelected) {
                        onAreaSelected({
                          ...selectedArea,
                          fwidth: newFWidth,
                        });
                      }
                    }}
                    sx={{
                      height: '28px',
                      '& .MuiInputBase-root': {
                        height: '28px',
                        minHeight: '28px',
                        maxHeight: '28px',
                        overflow: 'hidden',
                      },
                      '& .MuiInputBase-input': {
                        fontSize: '0.65rem',
                        padding: '2px 6px',
                        height: '100%',
                        boxSizing: 'border-box',
                      },
                      '& .MuiInputLabel-root': {
                        fontSize: '0.65rem',
                        color: selectedArea.fwidth !== undefined ? AGENT_CHAT_PALETTE.gold : undefined,
                        transform: 'translate(10px, 6px) scale(1)',
                        '&.Mui-focused, &.MuiFormLabel-filled': {
                          transform: 'translate(10px, -9px) scale(0.75)',
                        },
                      },
                    }}
                  />
                  <TextField
                    size="small"
                    label="FH"
                    type="number"
                    value={Math.round(selectedArea.fheight || 0)}
                    autoComplete="off"
                    onChange={(e) => {
                      const newFHeight = parseFloat(e.target.value) || 0;
                      if (onAreaSelected) {
                        onAreaSelected({
                          ...selectedArea,
                          fheight: newFHeight,
                        });
                      }
                    }}
                    sx={{
                      height: '28px',
                      '& .MuiInputBase-root': {
                        height: '28px',
                        minHeight: '28px',
                        maxHeight: '28px',
                        overflow: 'hidden',
                      },
                      '& .MuiInputBase-input': {
                        fontSize: '0.65rem',
                        padding: '2px 6px',
                        height: '100%',
                        boxSizing: 'border-box',
                      },
                      '& .MuiInputLabel-root': {
                        fontSize: '0.65rem',
                        color: selectedArea.fheight !== undefined ? AGENT_CHAT_PALETTE.gold : undefined,
                        transform: 'translate(10px, 6px) scale(1)',
                        '&.Mui-focused, &.MuiFormLabel-filled': {
                          transform: 'translate(10px, -9px) scale(0.75)',
                        },
                      },
                    }}
                  />
                </Box>
                  </>
                )}
              </>
            ) : (
              <Typography
                variant="caption"
                sx={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.8)' }}
              >
                No area selected
              </Typography>
            )}
          </Box>

          {/* 3. Reference Type Selection with Image Processing Options */}
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 0, flexWrap: 'wrap' }}>
            <RadioGroup
              row
              value={referenceType}
              onChange={(e) => {
                handleReferenceTypeChange(e.target.value as 'image' | 'text');
              }}
              sx={{
                gap: 1,
                '& .MuiFormControlLabel-root': {
                  margin: 0,
                  '& .MuiFormControlLabel-label': {
                    fontSize: '0.7rem',
                  },
                },
              }}
            >
              <FormControlLabel value="image" control={<Radio size="small" />} label="Image" />
              <FormControlLabel value="text" control={<Radio size="small" />} label="Text" />
            </RadioGroup>

            {/* Image Processing Options (only for image type) */}
            {referenceType === 'image' && (
              <>
                <FormControlLabel
                  control={
                    <input
                      type="checkbox"
                      checked={imageProcessingOptions.autocrop}
                      onChange={(e) =>
                        setImageProcessingOptions((prev) => ({
                          ...prev,
                          autocrop: e.target.checked,
                        }))
                      }
                      style={{ transform: 'scale(0.8)' }}
                    />
                  }
                  label="Auto-crop"
                  sx={{
                    margin: 0,
                    '& .MuiFormControlLabel-label': {
                      fontSize: '0.7rem',
                      color: 'rgba(255,255,255,0.9)',
                    },
                  }}
                />
                <FormControlLabel
                  control={
                    <input
                      type="checkbox"
                      checked={imageProcessingOptions.removeBackground}
                      onChange={(e) =>
                        setImageProcessingOptions((prev) => ({
                          ...prev,
                          removeBackground: e.target.checked,
                        }))
                      }
                      style={{ transform: 'scale(0.8)' }}
                    />
                  }
                  label="Remove background"
                  sx={{
                    margin: 0,
                    '& .MuiFormControlLabel-label': {
                      fontSize: '0.7rem',
                      color: 'rgba(255,255,255,0.9)',
                    },
                  }}
                />
              </>
            )}
          </Box>

          {/* 4. Text Input and Auto-Detect (only for text type) */}
          {referenceType === 'text' && (
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-end', mb: 0.5 }}>
              <TextField
                size="small"
                label="Text / Regex Pattern"
                placeholder="Enter text to find or regex pattern"
                value={referenceText}
                autoComplete="off"
                onChange={(e) => setReferenceText(e.target.value)}
                error={!!(referenceText && !validateRegex(referenceText))}
                helperText={
                  referenceText && !validateRegex(referenceText) ? 'Invalid regex pattern' : ''
                }
                sx={{
                  flex: 1,
                  '& .MuiInputBase-input': {
                    fontSize: '0.75rem',
                  },
                  '& .MuiInputLabel-root': {
                    fontSize: '0.75rem',
                  },
                  '& .MuiFormHelperText-root': {
                    fontSize: '0.65rem',
                  },
                }}
              />
              <Button
                size="small"
                variant="outlined"
                onClick={handleAutoDetectText}
                disabled={!selectedArea}
                sx={{
                  fontSize: '0.7rem',
                  whiteSpace: 'nowrap',
                }}
              >
                Auto-Detect
              </Button>
              {/* Focus: also verify the label is selected/focused. On save we learn
                  the highlight colour accent (coloured underline / border / pill /
                  glyphs) from the captured frame — the area is auto-padded by 30px
                  so an underline just outside the text box is still covered. */}
              <Tooltip title="Also verify the text is focused/selected. On save, the highlight colour accent (underline / border / pill / coloured text) is learned from this frame (area is padded 30px to catch an underline just outside the text).">
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={Boolean(checkFocus)}
                      onChange={(e) => setCheckFocus(e.target.checked)}
                      sx={{ p: 0.25 }}
                    />
                  }
                  label="Focus"
                  sx={{
                    ml: 0.25,
                    mr: 0,
                    whiteSpace: 'nowrap',
                    '& .MuiFormControlLabel-label': { fontSize: '0.7rem' },
                  }}
                />
              </Tooltip>
            </Box>
          )}

          {/* 6. Reference Name + Action Buttons */}
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-end', mb: 0.5 }}>
            {/* Reference Name Input */}
            <TextField
              size="small"
              placeholder="Reference name"
              value={referenceName}
              autoComplete="off"
              onChange={(e) => setReferenceName(e.target.value)}
              sx={{
                flex: 1,
                '& .MuiInputBase-input': {
                  fontSize: '0.75rem',
                },
              }}
            />

            {/* Action Buttons */}
            {referenceType === 'image' && (
              <Button
                size="small"
                startIcon={<CameraIcon sx={{ fontSize: '1rem' }} />}
                variant="contained"
                onClick={handleCaptureReference}
                disabled={!canCapture}
                sx={{
                  bgcolor: '#1976d2',
                  fontSize: '0.75rem',
                  '&:hover': {
                    bgcolor: '#1565c0',
                  },
                  '&:disabled': {
                    bgcolor: '#333',
                    color: 'rgba(255,255,255,0.3)',
                  },
                }}
              >
                Capture
              </Button>
            )}

            <Button
              size="small"
              variant="contained"
              onClick={handleSaveReference}
              disabled={!canSave || pendingSave}
              sx={{
                bgcolor: saveSuccess ? '#4caf50' : pendingSave ? '#666' : '#4caf50',
                fontSize: '0.75rem',
                color: saveSuccess ? '#fff' : pendingSave ? 'rgba(255,255,255,0.7)' : '#fff',
                fontWeight: saveSuccess ? 'bold' : 'normal',
                '&:hover': {
                  bgcolor: saveSuccess ? '#4caf50' : pendingSave ? '#666' : '#45a049',
                },
                '&:disabled': {
                  bgcolor: '#333',
                  color: 'rgba(255,255,255,0.3)',
                },
                transition: 'all 0.3s ease',
                minWidth: '80px', // Ensure consistent width
                boxShadow: saveSuccess ? '0 0 8px rgba(76, 175, 80, 0.6)' : 'none',
              }}
            >
              {saveSuccess ? '✓ Saved!' : pendingSave ? 'Saving...' : 'Save'}
            </Button>
          </Box>
        </Box>
      </Collapse>
    </Box>
  );
};

export default VerificationCapture;
