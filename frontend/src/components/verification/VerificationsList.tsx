import { Add as AddIcon } from '@mui/icons-material';
import {
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  Select,
  MenuItem,
  Tooltip,
  Typography,
  CircularProgress,
} from '@mui/material';
import React, { useState, useCallback, useRef } from 'react';

import { Host } from '../../types/common/Host_Types';
import {
  Verification,
  Verifications,
  ModelReferences,
} from '../../types/verification/Verification_Types';
import { buildVerificationResultUrl } from '../../utils/buildUrlUtils';

import { VerificationImageComparisonDialog } from './VerificationImageComparisonDialog';
import { VerificationItem } from './VerificationItem';
import { VerificationControlsLinkProps } from './VerificationControls';
import { VerificationTextComparisonDialog } from './VerificationTextComparisonDialog';

export interface VerificationsListProps {
  verifications: Verification[];
  availableVerifications: Verifications;
  onVerificationsChange: (verifications: Verification[]) => void;
  loading: boolean;
  model: string;
  onTest?: () => void;  // Optional: when undefined, Test button is hidden (e.g., for KPI measurements)
  testResults: Verification[];
  onReferenceSelected: (referenceName: string, referenceData: any) => void;
  selectedHost?: Host;
  modelReferences: ModelReferences;
  referencesLoading: boolean;
  showCollapsible: boolean;
  title: string;
  passCondition?: 'all' | 'any'; // NEW: Verification pass condition from node data
  onPassConditionChange?: (condition: 'all' | 'any') => void; // NEW: Callback when condition changes
  onRunVerification?: (index: number) => void;
  runDisabled?: boolean;
  runningVerificationIndex?: number | null;
  disabled?: boolean;
  // When provided, render a Shared checkbox next to "All must pass". Used in
  // the Verification Editor so newly-saved references are visible+editable by
  // every UI in the team whose models[] overlaps with this one's.
  shared?: boolean;
  onSharedChange?: (next: boolean) => void;
  // Locks Search Text + area X/Y/W/H. Reference assets are shared across
  // every node/edge that picks them, so editing them anywhere except
  // VerificationEditor (which has overwrite confirmation + a Save flow)
  // silently ripples into unrelated places. Node/Edge/Testcase dialogs
  // turn this on; VerificationEditor leaves it off.
  referenceReadOnly?: boolean;
  // Escape hatch for referenceReadOnly, scoped to TEXT references. When true
  // (Node Edit dialog) the Search Text + area of a text verification become
  // editable and the dialog's save propagates the edit to the reference row.
  allowReferenceEdit?: boolean;
  // When provided, each image verification row shows a "Recapture" camera
  // icon. Click overwrites the reference image in place using its current
  // area. The parent owns confirmation + execution (needs a controlled device).
  onRecaptureReference?: (index: number) => void;
  recapturingIndex?: number | null;
  // Optional per-field data-linking, forwarded to each VerificationItem.
  // Used by the TestCase builder inline editor (single verification); undefined
  // in the navigation Node/Edge dialogs.
  linkProps?: VerificationControlsLinkProps;
}

export const VerificationsList: React.FC<VerificationsListProps> = React.memo(
  ({
    verifications,
    availableVerifications,
    onVerificationsChange,
    loading,
    model,
    onTest: _onTest,
    testResults,
    onReferenceSelected,
    selectedHost: _selectedHost,
    modelReferences,
    referencesLoading,
    showCollapsible,
    title,
    passCondition: externalPassCondition, // NEW: Accept from props
    onPassConditionChange, // NEW: Callback for changes
    onRunVerification,
    runDisabled = false,
    runningVerificationIndex = null,
    disabled = false,
    shared,
    onSharedChange,
    referenceReadOnly = false,
    allowReferenceEdit = false,
    onRecaptureReference,
    recapturingIndex = null,
    linkProps,
  }) => {

    // Merge existing verifications with available ones to ensure existing verifications can always be selected
    const mergedAvailableVerifications = React.useMemo(() => {
      const merged = { ...availableVerifications };

      // For each existing verification, ensure it's available in the merged list
      verifications.forEach((verification) => {
        if (!verification.command) return;

        // Find if this command already exists in any category
        const exists = Object.values(merged).some((categoryVerifications: any) =>
          Array.isArray(categoryVerifications) &&
          categoryVerifications.some((v: any) => v.command === verification.command)
        );

        // If it doesn't exist, add it to a special "Existing" category
        if (!exists) {
          if (!merged['Existing']) {
            merged['Existing'] = [];
          }
          merged['Existing'].push({
            command: verification.command,
            verification_type: verification.verification_type,
            params: verification.params || {},
          } as Verification);
        }
      });

      return merged;
    }, [availableVerifications, verifications]);

    // Auto-resolve reference areas when verifications load (for node panel consistency)
    React.useEffect(() => {
      if (!modelReferences || Object.keys(modelReferences).length === 0) return;
      
      let hasChanges = false;
      const resolvedVerifications = verifications.map((verification) => {
        const params = verification.params || {};
        const referenceName = (params as any).reference_name || (params as any).image_path;
        
        // CRITICAL: Skip auto-resolve if area was manually modified by user
        if ((params as any).area_modified) {
          console.log(`[VerificationsList] Skipping auto-resolve for ${referenceName} - area was manually modified`);
          return verification;
        }
        
        // If verification has a reference name but potentially wrong area, auto-resolve it
        // Try with _text suffix first, then without (backward compatibility)
        let selectedRef = null;
        if (referenceName) {
          selectedRef = modelReferences[referenceName] || 
                       modelReferences[`${referenceName}_text`] || 
                       modelReferences[referenceName.replace('_text', '')];
        }
        
        if (selectedRef) {
          const currentArea = (params as any).area;
          const dbArea = selectedRef.area;
          
          // Check if areas are different (need resolution) - including fuzzy coordinates
          const needsResolution = !currentArea || 
            currentArea.x !== dbArea?.x || 
            currentArea.y !== dbArea?.y || 
            currentArea.width !== dbArea?.width || 
            currentArea.height !== dbArea?.height ||
            currentArea.fx !== dbArea?.fx ||
            currentArea.fy !== dbArea?.fy ||
            currentArea.fwidth !== dbArea?.fwidth ||
            currentArea.fheight !== dbArea?.fheight;
            
          if (needsResolution && dbArea) {
            console.log(`[VerificationsList] Auto-resolving area for ${referenceName}:`, dbArea);
            hasChanges = true;
            
            return {
              ...verification,
              params: {
                ...params,
                area: {
                  x: dbArea.x,
                  y: dbArea.y,
                  width: dbArea.width,
                  height: dbArea.height,
                  // Include fuzzy search coordinates if present
                  ...(dbArea.fx !== undefined && { fx: dbArea.fx }),
                  ...(dbArea.fy !== undefined && { fy: dbArea.fy }),
                  ...(dbArea.fwidth !== undefined && { fwidth: dbArea.fwidth }),
                  ...(dbArea.fheight !== undefined && { fheight: dbArea.fheight }),
                },
                // ✅ FIX: Add text field for text verifications
                ...(selectedRef.type === 'text' && selectedRef.text && { text: selectedRef.text }),
              },
            };
          }
        }
        
        return verification;
      });
      
      if (hasChanges) {
        onVerificationsChange(resolvedVerifications as Verification[]);
      }
    }, [verifications, modelReferences, onVerificationsChange]);
    
    // Use external passCondition if provided, otherwise use internal state (defaults to 'all')
    const [internalPassCondition, setInternalPassCondition] = useState<'all' | 'any'>('all');
    const passCondition = externalPassCondition !== undefined ? externalPassCondition : internalPassCondition;
    
    // Handler that updates both internal state and notifies parent
    const handlePassConditionChange = useCallback((newCondition: 'all' | 'any') => {
      setInternalPassCondition(newCondition);
      if (onPassConditionChange) {
        onPassConditionChange(newCondition);
      }
    }, [onPassConditionChange]);
    
    const [collapsed, setCollapsed] = useState<boolean>(false);
    const [imageComparisonDialog, setImageComparisonDialog] = useState<{
      open: boolean;
      sourceUrl: string;
      referenceUrl: string;
      overlayUrl?: string;
      userThreshold?: number;
      matchingResult?: number;
      focusScore?: number;
      focusThreshold?: number;
      resultType?: 'PASS' | 'FAIL' | 'ERROR';
      imageFilter?: 'none' | 'greyscale' | 'binary';
    }>({
      open: false,
      sourceUrl: '',
      referenceUrl: '',
      overlayUrl: undefined,
      userThreshold: undefined,
      matchingResult: undefined,
      focusScore: undefined,
      focusThreshold: undefined,
      resultType: undefined,
      imageFilter: undefined,
    });

    const [textComparisonDialog, setTextComparisonDialog] = useState<{
      open: boolean;
      searchedText: string;
      extractedText: string;
      sourceUrl?: string;
      resultType?: 'PASS' | 'FAIL' | 'ERROR';
      detectedLanguage?: string;
      languageConfidence?: number;
      imageFilter?: 'none' | 'greyscale' | 'binary';
      focusScore?: number;
      focusThreshold?: number;
    }>({
      open: false,
      searchedText: '',
      extractedText: '',
      sourceUrl: undefined,
      resultType: undefined,
      detectedLanguage: undefined,
      languageConfidence: undefined,
      imageFilter: undefined,
      focusScore: undefined,
      focusThreshold: undefined,
    });

    // Image processing functions
    const processImageUrl = useCallback((url: string): string => {
      if (!url) return '';

      console.log(`[@component:VerificationsList] Processing image URL: ${url}`);

      // Handle data URLs (base64) - return as is
      if (url.startsWith('data:')) {
        console.log('[@component:VerificationsList] Using data URL');
        return url;
      }

      // Handle HTTP URLs - use proxy to convert to HTTPS
      if (url.startsWith('http:')) {
        console.log('[@component:VerificationsList] HTTP URL detected, using proxy');
        // URL is already processed by backend
        const proxyUrl = url;
        console.log(`[@component:VerificationsList] Generated proxy URL: ${proxyUrl}`);
        return proxyUrl;
      }

      // Handle HTTPS URLs - return as is (no proxy needed)
      if (url.startsWith('https:')) {
        console.log('[@component:VerificationsList] Using HTTPS URL directly');
        return url;
      }

      // Handle local file paths from backend (e.g., /var/www/html/stream/capture4/captures/verification_results/source_image_0.png)
      if (url.startsWith('/var/www/html/')) {
        console.log('[@component:VerificationsList] Local file path detected, converting to URL');
        if (_selectedHost) {
          const hostUrl = buildVerificationResultUrl(_selectedHost, url);
          console.log(`[@component:VerificationsList] Converted to: ${hostUrl}`);
          return hostUrl;
        } else {
          console.warn('[@component:VerificationsList] No selected host, cannot convert local path to URL');
        }
      }

      // For relative paths or other formats, use directly
      console.log('[@component:VerificationsList] Using URL directly');
      return url;
    }, [_selectedHost]);

    const getCacheBustedUrl = useCallback((url: string): string => {
      if (!url) return '';
      const separator = url.includes('?') ? '&' : '?';
      return `${url}${separator}cache=${Date.now()}`;
    }, []);

    // Note: Debug logging removed to reduce console spam

    // Sentinel at the bottom of the list; scrolled into view whenever a row is
    // added or expands (command/reference selected) so the new content stays
    // visible without the user manually scrolling. Double rAF waits for the
    // appended/expanded row to render before scrolling.
    const bottomRef = useRef<HTMLDivElement>(null);
    const scrollToBottom = useCallback(() => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
        });
      });
    }, []);

    const addVerification = useCallback(() => {
      const newVerification: Verification = {
        command: '',
        params: { timeout: 0 } as any,
        verification_type: 'text',
      };
      onVerificationsChange([...verifications, newVerification]);
      scrollToBottom();
    }, [verifications, onVerificationsChange, scrollToBottom]);

    const removeVerification = useCallback(
      (index: number) => {
        const newVerifications = verifications.filter((_, i) => i !== index);
        onVerificationsChange(newVerifications);
      },
      [verifications, onVerificationsChange],
    );

    const updateVerification = useCallback(
      (index: number, updates: any) => {
        const newVerifications = verifications.map((verification, i) =>
          i === index ? { ...verification, ...updates } : verification,
        );
        onVerificationsChange(newVerifications as Verification[]);
      },
      [verifications, onVerificationsChange],
    );

    const moveVerificationUp = useCallback(
      (index: number) => {
        if (index === 0) return;
        const newVerifications = [...verifications];
        [newVerifications[index - 1], newVerifications[index]] = [
          newVerifications[index],
          newVerifications[index - 1],
        ];
        onVerificationsChange(newVerifications);
      },
      [verifications, onVerificationsChange],
    );

    const moveVerificationDown = useCallback(
      (index: number) => {
        if (index === verifications.length - 1) return;
        const newVerifications = [...verifications];
        [newVerifications[index], newVerifications[index + 1]] = [
          newVerifications[index + 1],
          newVerifications[index],
        ];
        onVerificationsChange(newVerifications);
      },
      [verifications, onVerificationsChange],
    );

    const handleVerificationSelect = useCallback(
      (index: number, command: string) => {
        // Find the selected verification from available verifications
        let selectedVerification: any = undefined;

        // Search through all controller types to find the verification
        for (const verifications of Object.values(availableVerifications)) {
          if (!Array.isArray(verifications)) continue;

          const verification = verifications.find((v) => v.command === command);
          if (verification) {
            selectedVerification = verification;
            break;
          }
        }

        if (selectedVerification) {
          // Extract default values from typed params (backend sends {type, required, default} structure)
          const cleanParams: any = {};
          if (selectedVerification.params) {
            Object.entries(selectedVerification.params).forEach(([key, value]: [string, any]) => {
              // Check if this is a typed param object (has 'default' field)
              if (value && typeof value === 'object' && 'default' in value) {
                cleanParams[key] = value.default;
              } else {
                // Already a simple value
                cleanParams[key] = value;
              }
            });
          }
          
          updateVerification(index, {
            command: selectedVerification.command,
            verification_type: selectedVerification.verification_type,
            params: cleanParams,
          });
          // Selecting a command expands the row (reference dropdown, params).
          scrollToBottom();
        }
      },
      [availableVerifications, updateVerification, scrollToBottom],
    );

    const handleReferenceSelect = useCallback(
      (index: number, internalKey: string) => {
        console.log('[@component:VerificationsList] Reference selected:', {
          index,
          internalKey,
          model,
        });

        const selectedRef = modelReferences[internalKey];

        if (selectedRef) {
          console.log('[@component:VerificationsList] Selected reference details:', {
            internalKey: internalKey,
            name: selectedRef.name,
            model: model,
            type: selectedRef.type,
            url: selectedRef.url,
            area: selectedRef.area,
          });

          const baseParams = {
            ...verifications[index].params,
            area: {
              x: selectedRef.area.x,
              y: selectedRef.area.y,
              width: selectedRef.area.width,
              height: selectedRef.area.height,
              // Include fuzzy search coordinates if present
              ...(selectedRef.area.fx !== undefined && { fx: selectedRef.area.fx }),
              ...(selectedRef.area.fy !== undefined && { fy: selectedRef.area.fy }),
              ...(selectedRef.area.fwidth !== undefined && { fwidth: selectedRef.area.fwidth }),
              ...(selectedRef.area.fheight !== undefined && { fheight: selectedRef.area.fheight }),
            },
          };

          console.log('[@component:VerificationsList] baseParams area with fuzzy:', baseParams.area);

          if (selectedRef.type === 'image') {
            // Image reference parameters - use original database name for backend
            updateVerification(index, {
              params: {
                ...baseParams,
                image_path: selectedRef.name || internalKey, // Use original name for backend lookup
                reference_name: internalKey, // Store internalKey for UI select component
              },
            });
            console.log(
              '[@component:VerificationsList] Updated verification with image reference:',
              {
                internal_key: internalKey,
                display_name: selectedRef.name,
                reference_url: selectedRef.url,
                backend_image_path: selectedRef.name || internalKey,
                updatedParams: {
                  ...baseParams,
                  image_path: selectedRef.name || internalKey,
                  reference_name: internalKey,
                },
              },
            );
          } else if (selectedRef.type === 'text') {
            // Text reference parameters - store text and use original name
            updateVerification(index, {
              params: {
                ...baseParams,
                text: selectedRef.text || '',
                reference_name: internalKey, // Store internalKey for UI select component
              },
            });
            console.log(
              '[@component:VerificationsList] Updated verification with text reference:',
              {
                internal_key: internalKey,
                display_name: selectedRef.name,
                reference_text: selectedRef.text,
                backend_reference_name: selectedRef.name || internalKey,
                updatedParams: {
                  ...baseParams,
                  text: selectedRef.text || '',
                  reference_name: internalKey,
                },
              },
            );
          }

          // Pass the display name to the callback, not the internal key
          onReferenceSelected(selectedRef.name || internalKey, selectedRef);
          // Selecting a reference expands the row (preview, params).
          scrollToBottom();
        }
      },
      [model, modelReferences, verifications, updateVerification, onReferenceSelected, scrollToBottom],
    );

    const handleImageFilterChange = useCallback(
      (index: number, filter: 'none' | 'greyscale' | 'binary') => {
        updateVerification(index, {
          params: {
            ...verifications[index].params,
            image_filter: filter,
          },
        });
        console.log('[@component:VerificationsList] Changed image filter to:', filter);
      },
      [verifications, updateVerification],
    );

    const handleTextFilterChange = useCallback(
      (index: number, filter: 'none' | 'greyscale' | 'binary') => {
        updateVerification(index, {
          params: {
            ...verifications[index].params,
            text_filter: filter,
          },
        });
        console.log('[@component:VerificationsList] Changed text filter to:', filter);
      },
      [verifications, updateVerification],
    );

    const handleTextChange = useCallback(
      (index: number, text: string) => {
        updateVerification(index, {
          params: {
            ...verifications[index].params,
            text: text,
            text_modified: true, // Mark that text has been manually edited
          },
        });
        console.log('[@component:VerificationsList] Updated search text:', text);
      },
      [verifications, updateVerification],
    );

    const handleImageClick = useCallback(
      (
        sourceUrl: string,
        referenceUrl: string,
        overlayUrl?: string,
        userThreshold?: number,
        matchingResult?: number,
        resultType?: 'PASS' | 'FAIL' | 'ERROR',
        imageFilter?: 'none' | 'greyscale' | 'binary',
        focusScore?: number,
        focusThreshold?: number,
      ) => {
        setImageComparisonDialog({
          open: true,
          sourceUrl,
          referenceUrl,
          overlayUrl,
          userThreshold,
          matchingResult,
          focusScore,
          focusThreshold,
          resultType,
          imageFilter,
        });
      },
      [],
    );

    const handleTextSourceImageClick = useCallback(
      (
        searchedText: string,
        extractedText: string,
        sourceUrl?: string,
        resultType?: 'PASS' | 'FAIL' | 'ERROR',
        detectedLanguage?: string,
        languageConfidence?: number,
        imageFilter?: 'none' | 'greyscale' | 'binary',
        focusScore?: number,
        focusThreshold?: number,
      ) => {
        setTextComparisonDialog({
          open: true,
          searchedText,
          extractedText,
          sourceUrl,
          resultType,
          detectedLanguage,
          languageConfidence,
          imageFilter,
          focusScore,
          focusThreshold,
        });
      },
      [],
    );

    const isInteractionDisabled = disabled || loading;

    const content = (
      <Box sx={{ overflow: 'visible', position: 'relative' }}>
        <Box sx={{ mb: 0.5, overflow: 'visible' }}>
          {verifications.map((verification, index) => (
            <VerificationItem
              key={index}
              verification={verification}
              index={index}
              availableVerifications={mergedAvailableVerifications}
              modelReferences={modelReferences}
              referencesLoading={referencesLoading}
              testResult={testResults[index]}
              onVerificationSelect={handleVerificationSelect}
              onReferenceSelect={handleReferenceSelect}
              onImageFilterChange={handleImageFilterChange}
              onTextFilterChange={handleTextFilterChange}
              onUpdateVerification={updateVerification}
              onRemoveVerification={removeVerification}
              onImageClick={handleImageClick}
              onSourceImageClick={handleTextSourceImageClick}
              processImageUrl={processImageUrl}
              getCacheBustedUrl={getCacheBustedUrl}
              onMoveUp={moveVerificationUp}
              onMoveDown={moveVerificationDown}
              canMoveUp={index > 0}
              canMoveDown={index < verifications.length - 1}
              onRun={onRunVerification}
              canRun={Boolean(verification.command) && !runDisabled && !loading}
              isRunning={runningVerificationIndex === index}
              disabled={isInteractionDisabled}
              onTextChange={handleTextChange}
              referenceReadOnly={referenceReadOnly}
              allowReferenceEdit={allowReferenceEdit}
              onRecaptureReference={onRecaptureReference}
              isRecapturing={recapturingIndex === index}
              recaptureDisabled={recapturingIndex !== null}
              linkProps={linkProps}
            />
          ))}
        </Box>

        <Box sx={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', mt: 0.5, gap: 1 }}>
          {onSharedChange && (
            <Tooltip
              title="Shared with all userinterfaces with compatible model"
              placement="top"
              arrow
            >
              <FormControlLabel
                control={
                  <Checkbox
                    size="small"
                    checked={Boolean(shared)}
                    onChange={(e) => onSharedChange(e.target.checked)}
                    disabled={isInteractionDisabled}
                    sx={{ p: 0.25 }}
                  />
                }
                label="Shared"
                sx={{
                  m: 0,
                  '& .MuiFormControlLabel-label': { fontSize: '0.75rem' },
                }}
              />
            </Tooltip>
          )}
          <FormControl size="small" sx={{ minWidth: 100 }}>
            <Select
              value={passCondition}
              onChange={(e) => handlePassConditionChange(e.target.value as 'all' | 'any')}
              size="small"
              disabled={isInteractionDisabled}
              sx={{
                fontSize: '0.75rem',
                height: '28px',
                '& .MuiSelect-select': {
                  padding: '4px 8px',
                },
              }}
            >
              <MenuItem value="all" sx={{ fontSize: '0.75rem' }}>
                All must pass
              </MenuItem>
              <MenuItem value="any" sx={{ fontSize: '0.75rem' }}>
                Any can pass
              </MenuItem>
            </Select>
          </FormControl>
          
          <Button
            size="small"
            variant="outlined"
            startIcon={<AddIcon />}
            onClick={addVerification}
            disabled={isInteractionDisabled}
            sx={{ minWidth: 'auto', fontSize: '0.75rem', py: 0.25 }}
          >
            Add
          </Button>

          {/* Test Button - only show if we have verifications and onTest is provided */}
          {verifications.length > 0 && _onTest && (
            <Button
              size="small"
              variant="contained"
              onClick={_onTest}
              disabled={loading || disabled}
              startIcon={
                loading ? (
                  <CircularProgress size={12} sx={{ color: 'inherit' }} />
                ) : undefined
              }
              sx={{
                minWidth: 'auto',
                fontSize: '0.75rem',
                py: 0.25,
                backgroundColor: '#2196f3',
                '&:hover': {
                  backgroundColor: '#1976d2',
                },
              }}
            >
              Test
            </Button>
          )}
        </Box>

        {/* Final Result indicator */}
        {testResults.length > 0 && (
          <Box
            sx={{
              display: 'flex',
              justifyContent: 'center',
              mt: 1,
              p: 0.5,
              borderRadius: 1,
              backgroundColor:
                passCondition === 'all'
                  ? testResults.every((result) => result.success)
                    ? 'rgba(76, 175, 80, 0.1)'
                    : 'rgba(244, 67, 54, 0.1)'
                  : testResults.some((result) => result.success)
                    ? 'rgba(76, 175, 80, 0.1)'
                    : 'rgba(244, 67, 54, 0.1)',
              border: `1px solid ${
                passCondition === 'all'
                  ? testResults.every((result) => result.success)
                    ? '#4caf50'
                    : '#f44336'
                  : testResults.some((result) => result.success)
                    ? '#4caf50'
                    : '#f44336'
              }`,
            }}
          >
            <Typography
              sx={{
                fontWeight: 'bold',
                fontSize: '0.8rem',
                color:
                  passCondition === 'all'
                    ? testResults.every((result) => result.success)
                      ? '#4caf50'
                      : '#f44336'
                    : testResults.some((result) => result.success)
                      ? '#4caf50'
                      : '#f44336',
              }}
            >
              Final Result:{' '}
              {passCondition === 'all'
                ? testResults.every((result) => result.success)
                  ? 'PASS'
                  : 'FAIL'
                : testResults.some((result) => result.success)
                  ? 'PASS'
                  : 'FAIL'}
            </Typography>
          </Box>
        )}

        {/* Image Comparison Dialog */}
        <VerificationImageComparisonDialog
          open={imageComparisonDialog.open}
          sourceUrl={imageComparisonDialog.sourceUrl}
          referenceUrl={imageComparisonDialog.referenceUrl}
          overlayUrl={imageComparisonDialog.overlayUrl}
          userThreshold={imageComparisonDialog.userThreshold}
          matchingResult={imageComparisonDialog.matchingResult}
          focusScore={imageComparisonDialog.focusScore}
          focusThreshold={imageComparisonDialog.focusThreshold}
          resultType={imageComparisonDialog.resultType}
          imageFilter={imageComparisonDialog.imageFilter}
          onClose={() => setImageComparisonDialog((prev) => ({ ...prev, open: false }))}
          processImageUrl={processImageUrl}
          getCacheBustedUrl={getCacheBustedUrl}
        />

        {/* Text Comparison Dialog */}
        <VerificationTextComparisonDialog
          open={textComparisonDialog.open}
          searchedText={textComparisonDialog.searchedText}
          extractedText={textComparisonDialog.extractedText}
          sourceUrl={textComparisonDialog.sourceUrl}
          resultType={textComparisonDialog.resultType}
          detectedLanguage={textComparisonDialog.detectedLanguage}
          languageConfidence={textComparisonDialog.languageConfidence}
          imageFilter={textComparisonDialog.imageFilter}
          focusScore={textComparisonDialog.focusScore}
          focusThreshold={textComparisonDialog.focusThreshold}
          onClose={() => setTextComparisonDialog((prev) => ({ ...prev, open: false }))}
        />

        {/* Scroll anchor: keeps the newest/expanding verification row in view */}
        <div ref={bottomRef} />
      </Box>
    );

    // If collapsible is requested, wrap in collapsible container
    if (showCollapsible) {
      return (
        <Box>
          {/* Collapsible toggle button and title */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.25 }}>
            <Button
              size="small"
              onClick={() => setCollapsed(!collapsed)}
              sx={{ p: 0.125, minWidth: 'auto' }}
            >
              {collapsed ? '▶' : '▼'}
            </Button>
            <Typography variant="subtitle2" sx={{ fontSize: '0.8rem', fontWeight: 600 }}>
              {title}
            </Typography>
          </Box>

          {/* Collapsible content */}
          {!collapsed && (
            <Box
              sx={{
                overflow: 'visible',
                position: 'relative',
                '& .MuiTypography-subtitle2': {
                  fontSize: '0.75rem',
                },
                '& .MuiButton-root': {
                  fontSize: '0.7rem',
                },
                '& .MuiTextField-root': {
                  '& .MuiInputLabel-root': {
                    fontSize: '0.75rem',
                  },
                  '& .MuiInputBase-input': {
                    fontSize: '0.75rem',
                  },
                },
                '& .MuiSelect-root': {
                  fontSize: '0.75rem',
                },
                '& .MuiFormControl-root': {
                  '& .MuiInputLabel-root': {
                    fontSize: '0.75rem',
                  },
                },
              }}
            >
              {content}
            </Box>
          )}
        </Box>
      );
    }

    // Otherwise return content directly
    return <Box sx={{ overflow: 'visible', position: 'relative' }}>{content}</Box>;
  },
  (prevProps, nextProps) => {
    // Shallow comparison helper function
    const shallowEqual = (obj1: any, obj2: any): boolean => {
      if (obj1 === obj2) return true;
      if (!obj1 || !obj2) return obj1 === obj2;

      const keys1 = Object.keys(obj1);
      const keys2 = Object.keys(obj2);

      if (keys1.length !== keys2.length) return false;

      for (const key of keys1) {
        if (obj1[key] !== obj2[key]) return false;
      }

      return true;
    };

    // Array comparison helper - improved for better performance
    const arraysEqual = (arr1: any[], arr2: any[]): boolean => {
      if (arr1 === arr2) return true;
      if (!arr1 || !arr2) return arr1 === arr2;
      if (arr1.length !== arr2.length) return false;

      // For verifications array, do a more thorough comparison
      // to avoid re-renders when only internal state changes
      for (let i = 0; i < arr1.length; i++) {
        const item1 = arr1[i];
        const item2 = arr2[i];

        // Compare essential fields that would affect rendering
        if (
          item1.command !== item2.command ||
          item1.verification_type !== item2.verification_type ||
          JSON.stringify(item1.params) !== JSON.stringify(item2.params) ||
          item1.success !== item2.success ||
          item1.error !== item2.error
        ) {
          return false;
        }
      }

      return true;
    };

    // Custom comparison function to prevent unnecessary re-renders
    const verificationsChanged = !arraysEqual(prevProps.verifications, nextProps.verifications);
    const availableVerificationsChanged = !shallowEqual(
      prevProps.availableVerifications,
      nextProps.availableVerifications,
    );
    const loadingChanged = prevProps.loading !== nextProps.loading;
    const modelChanged = prevProps.model !== nextProps.model;
    const testResultsChanged = !arraysEqual(prevProps.testResults, nextProps.testResults);

    const selectedHostChanged = !shallowEqual(prevProps.selectedHost, nextProps.selectedHost);
    const modelReferencesChanged = !shallowEqual(
      prevProps.modelReferences,
      nextProps.modelReferences,
    );
    const referencesLoadingChanged = prevProps.referencesLoading !== nextProps.referencesLoading;
    const showCollapsibleChanged = prevProps.showCollapsible !== nextProps.showCollapsible;
    const titleChanged = prevProps.title !== nextProps.title;
    const passConditionChanged = prevProps.passCondition !== nextProps.passCondition;
    const runDisabledChanged = prevProps.runDisabled !== nextProps.runDisabled;
    const runningVerificationIndexChanged =
      prevProps.runningVerificationIndex !== nextProps.runningVerificationIndex;
    const disabledChanged = prevProps.disabled !== nextProps.disabled;
    const referenceReadOnlyChanged =
      prevProps.referenceReadOnly !== nextProps.referenceReadOnly;
    const allowReferenceEditChanged =
      prevProps.allowReferenceEdit !== nextProps.allowReferenceEdit;
    const onRecaptureReferenceChanged =
      prevProps.onRecaptureReference !== nextProps.onRecaptureReference;
    const recapturingIndexChanged =
      prevProps.recapturingIndex !== nextProps.recapturingIndex;
    // Re-render when the link surface changes — notably draggedOutput toggling
    // during a drag (so the drop-target dashed outline appears/clears) and the
    // paramLinks map after a link/unlink.
    const linkPropsChanged =
      prevProps.linkProps?.draggedOutput !== nextProps.linkProps?.draggedOutput ||
      prevProps.linkProps?.paramLinks !== nextProps.linkProps?.paramLinks ||
      prevProps.linkProps?.onLinkDrop !== nextProps.linkProps?.onLinkDrop ||
      prevProps.linkProps?.onUnlink !== nextProps.linkProps?.onUnlink;

    // Function references - only check if they're different functions
    const onVerificationsChangeChanged =
      prevProps.onVerificationsChange !== nextProps.onVerificationsChange;
    const onTestChanged = prevProps.onTest !== nextProps.onTest;
    const onReferenceSelectedChanged =
      prevProps.onReferenceSelected !== nextProps.onReferenceSelected;
    const onPassConditionChangeChanged =
      prevProps.onPassConditionChange !== nextProps.onPassConditionChange;
    const onRunVerificationChanged =
      prevProps.onRunVerification !== nextProps.onRunVerification;

    // Only re-render if meaningful props have changed
    const shouldRerender =
      verificationsChanged ||
      availableVerificationsChanged ||
      loadingChanged ||
      modelChanged ||
      testResultsChanged ||
      selectedHostChanged ||
      modelReferencesChanged ||
      referencesLoadingChanged ||
      showCollapsibleChanged ||
      titleChanged ||
      passConditionChanged ||
      runDisabledChanged ||
      runningVerificationIndexChanged ||
      disabledChanged ||
      referenceReadOnlyChanged ||
      allowReferenceEditChanged ||
      onRecaptureReferenceChanged ||
      recapturingIndexChanged ||
      onVerificationsChangeChanged ||
      onTestChanged ||
      onReferenceSelectedChanged ||
      onPassConditionChangeChanged ||
      onRunVerificationChanged ||
      linkPropsChanged;

    // Reduce logging frequency to avoid console spam
    if (shouldRerender && verificationsChanged) {
      console.log('[@component:VerificationsList] Verifications changed, re-rendering');
    }

    return !shouldRerender; // Return true to skip re-render, false to re-render
  },
);
