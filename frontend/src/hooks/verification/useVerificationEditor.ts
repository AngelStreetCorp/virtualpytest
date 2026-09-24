import { useState, useCallback, useMemo, useEffect, useRef } from 'react';

import { Host } from '../../types/common/Host_Types';
import { DragArea } from '../../types/controller/Hdmi_Types';
import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useToastContext } from '../../contexts/ToastContext';

import { useVerification } from './useVerification';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api, apiClient } from '../../utils/apiClient';

// Helper to round area coordinates to 2 decimal places
const roundArea = (area: any) => {
  if (!area) return area;
  const rounded: any = {};
  for (const key in area) {
    rounded[key] = typeof area[key] === 'number' ? parseFloat(area[key].toFixed(2)) : area[key];
  }
  return rounded;
};

// Geometry-only equality for the editor's area-sync loop guard. Compares the
// box + optional fuzzy box at integer precision (the verification X/Y/W/H
// inputs are Math.round-ed, the drag box is float) so a drag and the
// equivalent typed value compare equal and the bidirectional mirror settles
// after one hop instead of ping-ponging.
const areasEqual = (a: any, b: any): boolean => {
  if (!a || !b) return a === b;
  const keys = ['x', 'y', 'width', 'height', 'fx', 'fy', 'fwidth', 'fheight'];
  for (const k of keys) {
    const av = typeof a[k] === 'number' ? Math.round(a[k]) : a[k];
    const bv = typeof b[k] === 'number' ? Math.round(b[k]) : b[k];
    if ((av ?? null) !== (bv ?? null)) return false;
  }
  return true;
};

// The reference area in the editor lives in two places: the drag rectangle
// on the screenshot (`selectedArea`, owned by the stream hook) and the
// X/Y/W/H of the first image/text verification (`params.area`). Save uses
// `selectedArea`; Test uses `params.area`. This finds the verification that
// should mirror `selectedArea` so the two stay in lockstep.
const firstAreaVerifIndex = (verifs: any[]): number =>
  (verifs || []).findIndex(
    (v) =>
      (v?.verification_type === 'image' || v?.verification_type === 'text') &&
      v?.params?.area,
  );

// Define interfaces for editor-specific data structures
interface DetectedTextData {
  text: string;
  fontSize: number;
  confidence: number;
  detectedLanguage?: string;
  detectedLanguageName?: string;
  languageConfidence?: number;
  image_textdetected_path?: string;
}

interface ImageProcessingOptions {
  autocrop: boolean;
  removeBackground: boolean;
}

interface SelectedReferenceInfo {
  name: string;
  type: 'image' | 'text';
}

interface UseVerificationEditorProps {
  isVisible: boolean;
  selectedHost: Host;
  selectedDeviceId: string;
  captureSourcePath?: string; // TODO: Rename to image_source_url
  selectedArea?: DragArea | null;
  onAreaSelected?: (area: DragArea) => void;
  onClearSelection?: () => void;
  isCaptureActive?: boolean;
  isControlActive?: boolean; // Add control state to trigger reference fetching
  userinterfaceName?: string; // Required for saving references - defines the app/UI context
}

export const useVerificationEditor = ({
  isVisible: _isVisible,
  selectedHost,
  selectedDeviceId,
  captureSourcePath,
  selectedArea,
  onAreaSelected: _onAreaSelected,
  onClearSelection: _onClearSelection,
  isCaptureActive,
  isControlActive: _isControlActive = false, // Default to false if not provided
  userinterfaceName, // Required for saving references
}: UseVerificationEditorProps) => {
  // Get references from centralized context
  const {
    references: availableReferences,
    referencesLoading,
    getModelReferences,
    addReferenceToCache,
    reloadReferences,
  } = useDeviceData();

  const { showError, showSuccess } = useToastContext();

  // In-stream reference-capture editor: the user is testing a candidate
  // reference against the live frame, not visiting a node. The recordAs
  // discriminator on useVerification skips emitting tree_id/node_id, so
  // the host dispatcher runs the primitive only (no DB write). That's the
  // correct behavior here.
  const verification = useVerification({
    captureSourcePath,
    recordAs: { kind: 'reference-test' },
    userinterfaceName,
  });

  // State for reference capture
  const [referenceName, setReferenceName] = useState<string>('default_capture');
  const [capturedReferenceImage, setCapturedReferenceImage] = useState<string | null>(null);
  const [hasCaptured, setHasCaptured] = useState<boolean>(false);
  const [pendingSave, setPendingSave] = useState<boolean>(false);
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false);
  const [showConfirmDialog, setShowConfirmDialog] = useState<boolean>(false);
  const [referenceSaveCounter, setReferenceSaveCounter] = useState<number>(0);
  // When true, the next saved reference is marked shared and becomes
  // visible+editable by every UI in the team whose models[] intersects with
  // the current userinterfaceName's models[].
  const [shared, setShared] = useState<boolean>(false);

  // Get model references using userinterface_name (not device_model)
  const modelReferences = useMemo(() => {
    if (!userinterfaceName) {
      console.warn('[@hook:useVerificationEditor] No userinterfaceName provided, returning empty references');
      return {};
    }
    console.log('[@hook:useVerificationEditor] Getting references for userinterface:', userinterfaceName);
    const refs = getModelReferences(userinterfaceName);
    console.log('[@hook:useVerificationEditor] Retrieved references:', Object.keys(refs).length, 'items');
    return refs;
  }, [getModelReferences, userinterfaceName]);

  // State for reference type and details
  const [referenceText, setReferenceText] = useState<string>('');
  const [referenceType, setReferenceType] = useState<'image' | 'text'>('image');
  const [detectedTextData, setDetectedTextData] = useState<DetectedTextData | null>(null);
  const [textImageFilter, setTextImageFilter] = useState<'none' | 'greyscale' | 'binary'>('none');
  // Text "Focus" tick: also learn the selected/focused colour accent (coloured
  // underline / border / pill / glyphs) from this capture, so verification can
  // gate on "is this the SELECTED label", not just "is the text present".
  const [checkFocus, setCheckFocus] = useState<boolean>(false);

  // State for selected reference image preview
  const [selectedReferenceImage, setSelectedReferenceImage] = useState<string | null>(null);
  const [selectedReferenceInfo, setSelectedReferenceInfo] = useState<SelectedReferenceInfo | null>(
    null,
  );

  // Image processing options for capture only
  const [imageProcessingOptions, setImageProcessingOptions] = useState<ImageProcessingOptions>({
    autocrop: false,
    removeBackground: false,
  });

  // Collapsible sections state
  const [verificationsCollapsed, setVerificationsCollapsed] = useState<boolean>(false);
  const [captureCollapsed, setCaptureCollapsed] = useState<boolean>(false);

  // Handle reference selection
  const handleReferenceSelected = useCallback(async (referenceName: string, referenceData: any) => {
    console.log('[@hook:useVerificationEditor] Reference selected:', referenceName, referenceData);

    // If it's an image reference, display it in the preview area
    if (referenceData && referenceData.type === 'image') {
      // Use the complete URL directly from reference data
      const referenceUrl = referenceData.url;

      console.log('[@hook:useVerificationEditor] Setting reference image preview:', {
        referenceName,
        referenceUrl,
        referenceData,
      });

      setSelectedReferenceImage(referenceUrl);
      setSelectedReferenceInfo({
        name: referenceName,
        type: 'image',
      });

      // Keep the capture radio/toggle in sync with the selected reference type
      setReferenceType('image');

      // Auto-populate capture area and reference name for image references
      if (referenceData.area && _onAreaSelected) {
        const { x, y, width, height, fx, fy, fwidth, fheight } = referenceData.area;
        console.log('[@hook:useVerificationEditor] Auto-populating capture area from image reference:', {
          referenceName,
          area: { x, y, width, height, fx, fy, fwidth, fheight }
        });
        
        // Set the capture area coordinates including fuzzy search area if present
        _onAreaSelected({ 
          x, 
          y, 
          width, 
          height,
          ...(fx !== undefined && { fx }),
          ...(fy !== undefined && { fy }),
          ...(fwidth !== undefined && { fwidth }),
          ...(fheight !== undefined && { fheight }),
        });
      }

      // Auto-populate the reference name in the capture field
      if (referenceData.name) {
        console.log('[@hook:useVerificationEditor] Auto-populating reference name:', referenceData.name);
        setReferenceName(referenceData.name);
      }
    } else if (referenceData && referenceData.type === 'text') {
      // For text references, clear the image preview
      console.log('[@hook:useVerificationEditor] Text reference selected, clearing image preview');
      setSelectedReferenceImage(null);
      setSelectedReferenceInfo({
        name: referenceName,
        type: 'text',
      });

      // Switch the capture radio/toggle to "text" so the Text/Regex field shows.
      // Use the setter directly (not handleReferenceTypeChange) since that resets
      // referenceText, which we want to prefill from the reference below.
      setReferenceType('text');

      // Prefill the Text / Regex Pattern field from the reference's stored text
      console.log('[@hook:useVerificationEditor] Auto-populating reference text:', referenceData.text);
      setReferenceText(referenceData.text || '');

      // Reflect whether this reference already has a learned focus accent.
      setCheckFocus(Boolean((referenceData.area as any)?.focus));

      // Auto-populate capture area for text references (mirror image behavior)
      if (referenceData.area && _onAreaSelected) {
        const { x, y, width, height, fx, fy, fwidth, fheight } = referenceData.area;
        console.log('[@hook:useVerificationEditor] Auto-populating capture area from text reference:', {
          referenceName,
          area: { x, y, width, height, fx, fy, fwidth, fheight }
        });

        _onAreaSelected({
          x,
          y,
          width,
          height,
          ...(fx !== undefined && { fx }),
          ...(fy !== undefined && { fy }),
          ...(fwidth !== undefined && { fwidth }),
          ...(fheight !== undefined && { fheight }),
        });
      }

      // Auto-populate the reference name in the capture field so the user can
      // edit it and save to overwrite the existing text reference (mirror image)
      if (referenceData.name) {
        console.log('[@hook:useVerificationEditor] Auto-populating reference name:', referenceData.name);
        setReferenceName(referenceData.name);
      }
    } else {
      // Clear preview for unknown or null references
      setSelectedReferenceImage(null);
      setSelectedReferenceInfo(null);
    }

    // Clear captured reference when selecting a new reference
    setCapturedReferenceImage(null);
    setHasCaptured(false);
  }, [_onAreaSelected]);

  // Handle capture reference
  const handleCaptureReference = useCallback(async () => {
    if (!selectedArea || !captureSourcePath) {
      console.error('[@hook:useVerificationEditor] Please select an area on the screenshot first');
      showError('Select an area on the screenshot before capturing');
      return;
    }

    const roundedArea = roundArea(selectedArea);

    console.log('[@hook:useVerificationEditor] Capture reference requested:', {
      selectedArea,
      roundedArea,
      captureSourcePath,
      referenceName,
      referenceType,
      imageProcessingOptions,
      userinterfaceName,
    });

    try {
      let captureResponse;

      if (
        referenceType === 'image' &&
        (imageProcessingOptions.autocrop || imageProcessingOptions.removeBackground)
      ) {
        console.log(
          '[@hook:useVerificationEditor] Using processImage endpoint with processing options',
        );
        captureResponse = await apiClient(buildServerUrl(`/server/verification/image/processImage`), {
          method: 'POST',
          body: JSON.stringify({
            host_name: selectedHost.host_name, // Send full host object
            device_id: selectedDeviceId, // Send device ID
            area: roundedArea,
            image_source_url: captureSourcePath,
            reference_name: referenceName || 'temp_capture',
            userinterface_name: userinterfaceName,
            autocrop: imageProcessingOptions.autocrop,
            remove_background: imageProcessingOptions.removeBackground,
          }),
        });
      } else {
        console.log('[@hook:useVerificationEditor] Using standard cropImage endpoint');
        captureResponse = await apiClient(buildServerUrl(`/server/verification/image/cropImage`), {
          method: 'POST',
          body: JSON.stringify({
            host_name: selectedHost.host_name, // Send full host object
            device_id: selectedDeviceId, // Send device ID
            area: roundedArea,
            image_source_url: captureSourcePath,
            reference_name: referenceName || 'temp_capture',
            userinterface_name: userinterfaceName,
          }),
        });
      }

      const result = await captureResponse.json();
      console.log('[@hook:useVerificationEditor] Capture response result:', result);

      if (result.success) {
        const timestamp = new Date().getTime();
        // Use new field names with fallback to old ones
        const imageUrl = result.image_cropped_url || result.image_filtered_url || result.image_url;
        const finalImageUrl = `${imageUrl}?t=${timestamp}`;
        console.log(
          '[@hook:useVerificationEditor] Temporary capture created successfully, setting image URL:',
          finalImageUrl,
        );

        setCapturedReferenceImage(finalImageUrl);
        setHasCaptured(true);

        // If autocrop was applied and new area dimensions are provided, update the selected area
        if (imageProcessingOptions.autocrop && result.processed_area) {
          console.log('[@hook:useVerificationEditor] === AUTOCROP AREA UPDATE ===');
          console.log('[@hook:useVerificationEditor] Original area:', selectedArea);
          console.log(
            '[@hook:useVerificationEditor] Processed area from server:',
            result.processed_area,
          );

          // Update selected area if onAreaSelected callback is available
          if (_onAreaSelected) {
            _onAreaSelected({
              x: result.processed_area.x,
              y: result.processed_area.y,
              width: result.processed_area.width,
              height: result.processed_area.height,
            });
          }
          console.log('[@hook:useVerificationEditor] Area updated after autocrop');
        }
      } else {
        const message = result.error || result.message || 'Failed to capture reference';
        console.error('[@hook:useVerificationEditor] Failed to capture reference:', message);
        showError(`Capture failed: ${message}`);
      }
    } catch (error) {
      console.error('[@hook:useVerificationEditor] Error capturing reference:', error);
      showError(
        `Capture error: ${error instanceof Error ? error.message : 'Unknown error'}`,
      );
    }
  }, [
    selectedArea,
    captureSourcePath,
    referenceName,
    selectedHost,
    selectedDeviceId,
    referenceType,
    imageProcessingOptions,
    _onAreaSelected,
    userinterfaceName,
    showError,
  ]);

  // Handle save reference
  const handleSaveReference = useCallback(async () => {
    if (!selectedArea || !captureSourcePath) {
      console.error('[@hook:useVerificationEditor] Please select an area on the screenshot first');
      showError('Select an area on the screenshot before saving');
      return;
    }

    if (!referenceName.trim()) {
      console.error('[@hook:useVerificationEditor] Please enter a reference name');
      showError('Enter a reference name before saving');
      return;
    }

    if (referenceName.includes('.')) {
      showError('Reference names cannot contain dots. Use underscores instead.');
      return;
    }

    const roundedArea = roundArea(selectedArea);
    setPendingSave(true);

    try {
      console.log('[@hook:useVerificationEditor] Saving reference with data:', {
        name: referenceName,
        userinterface_name: userinterfaceName,
        area: selectedArea,
        roundedArea,
        captureSourcePath: captureSourcePath,
        referenceType: referenceType,
        imageProcessingOptions: imageProcessingOptions,
      });

      // Handle saving based on reference type
      if (referenceType === 'text') {
        // Text references should use processed image from detectText (no cropping needed)
        console.log(
          '[@hook:useVerificationEditor] Saving text reference using processed image from detectText',
        );
        const result = await api.post(buildServerUrl('/server/verification/text/saveText'), {
          host_name: selectedHost.host_name,
          device_id: selectedDeviceId,
          reference_name: referenceName,
          userinterface_name: userinterfaceName, // Required for R2 folder structure - defines app/UI context
          area: roundedArea,
          text: referenceText,
          image_textdetected_path: detectedTextData?.image_textdetected_path || '', // Use processed image from detectText
          // Focus: learn the selected-state colour accent from the FULL source
          // frame (the backend pads the area by 30px to catch an underline/border
          // just outside the tight text box). captureSourcePath is the full frame.
          check_focus: checkFocus,
          image_source_url: captureSourcePath,
          shared,
        });
        if (result.success) {
          console.log(
            '[@hook:useVerificationEditor] Text reference saved successfully:',
            referenceName,
            result,
          );
          showSuccess(`Saved text reference "${referenceName}"`);
          // Focus was requested but no colour accent could be learned — tell the
          // user so they don't assume the focus gate is active.
          if (checkFocus && result.focus_warning) {
            showError(result.focus_warning);
          }
          setReferenceSaveCounter((prev) => prev + 1);
          setSaveSuccess(true);

          // Add text reference to cache immediately for instant availability in verification dropdown
          if (addReferenceToCache && userinterfaceName) {
            addReferenceToCache(userinterfaceName, {
              name: referenceName,
              type: 'text',
              url: '', // Text references don't have URLs
              area: result.area || roundedArea, // result.area carries area['focus'] when learned
              text: referenceText,
              font_size: detectedTextData?.fontSize,
              confidence: detectedTextData?.confidence,
              shared,
            });
            console.log('[@hook:useVerificationEditor] Added text reference to cache for immediate use');
          }

          // Reload references from server to ensure complete sync
          if (reloadReferences) {
            try {
              await reloadReferences();
              console.log('[@hook:useVerificationEditor] Successfully reloaded references after text save');
            } catch (reloadError) {
              console.warn('[@hook:useVerificationEditor] Failed to reload references after text save:', reloadError);
            }
          }

          // Clear success state after 3 seconds (increased from 2)
          setTimeout(() => {
            setSaveSuccess(false);
          }, 3000);
        } else {
          const message = result.error || result.message || 'Unknown error';
          console.error(
            '[@hook:useVerificationEditor] Failed to save text reference:',
            message,
          );
          showError(`Save failed: ${message}`);
        }
      } else {
        // Image references: First capture, then save
        let captureResponse;

        if (imageProcessingOptions.autocrop || imageProcessingOptions.removeBackground) {
          console.log('[@hook:useVerificationEditor] Capturing with processing options for save');
          captureResponse = await apiClient(buildServerUrl(`/server/verification/image/processImage`), {
            method: 'POST',
            body: JSON.stringify({
              host_name: selectedHost.host_name,
              device_id: selectedDeviceId,
              area: roundedArea,
              image_source_url: captureSourcePath,
              reference_name: referenceName,
              userinterface_name: userinterfaceName,
              autocrop: imageProcessingOptions.autocrop,
              remove_background: imageProcessingOptions.removeBackground,
            }),
          });
        } else {
          console.log('[@hook:useVerificationEditor] Capturing without processing for save');
          captureResponse = await apiClient(buildServerUrl(`/server/verification/image/cropImage`), {
            method: 'POST',
            body: JSON.stringify({
              host_name: selectedHost.host_name,
              device_id: selectedDeviceId,
              area: roundedArea,
              image_source_url: captureSourcePath,
              reference_name: referenceName,
              userinterface_name: userinterfaceName,
            }),
          });
        }

        const captureResult = await captureResponse.json();

        if (!captureResult.success) {
          throw new Error(
            captureResult.error || captureResult.message || 'Failed to capture area',
          );
        }

        // Image references: Single call uploads to R2 and saves to database
        const result = await api.post(buildServerUrl('/server/verification/image/saveImage'), {
          host_name: selectedHost.host_name,
          device_id: selectedDeviceId, // MUST include device_id to find file in correct captures folder
          reference_name: referenceName,
          userinterface_name: userinterfaceName, // Required for R2 folder structure - defines app/UI context
          area:
            imageProcessingOptions.autocrop && captureResult.processed_area
              ? roundArea(captureResult.processed_area)
              : roundedArea,
          image_source_url: captureResult.filename, // Use cropped filename as source
          reference_type: referenceType === 'image' ? 'reference_image' : 'screenshot',
          shared,
        });

        if (result.success) {
          console.log(
            '[@hook:useVerificationEditor] Image reference saved successfully:',
            referenceName,
            result,
          );
          showSuccess(`Saved image reference "${referenceName}"`);
          setReferenceSaveCounter((prev) => prev + 1);
          setSaveSuccess(true);

          // Add reference to cache immediately for instant availability in verification dropdown
          if (addReferenceToCache && userinterfaceName && result.r2_url) {
            const savedArea = imageProcessingOptions.autocrop && captureResult.processed_area
              ? roundArea(captureResult.processed_area)
              : roundedArea;

            addReferenceToCache(userinterfaceName, {
              name: referenceName,
              type: 'image',
              url: result.r2_url,
              area: savedArea,
              shared,
            });
            console.log('[@hook:useVerificationEditor] Added reference to cache for immediate use');
          }

          // Reload references from server to ensure complete sync
          if (reloadReferences) {
            try {
              await reloadReferences();
              console.log('[@hook:useVerificationEditor] Successfully reloaded references after image save');
            } catch (reloadError) {
              console.warn('[@hook:useVerificationEditor] Failed to reload references after image save:', reloadError);
            }
          }

          // Clear success state after 3 seconds (increased from 2)
          setTimeout(() => {
            setSaveSuccess(false);
          }, 3000);
        } else {
          const message = result.error || result.message || 'Unknown error';
          console.error(
            '[@hook:useVerificationEditor] Failed to save reference to database:',
            message,
          );
          showError(`Save failed: ${message}`);
        }
      }
    } catch (err: any) {
      console.error('[@hook:useVerificationEditor] Error saving reference:', err);
      showError(`Save error: ${err?.message || 'Unknown error'}`);
    } finally {
      setPendingSave(false);
    }
  }, [
    selectedArea,
    captureSourcePath,
    referenceName,
    selectedHost,
    selectedDeviceId,
    referenceType,
    referenceText,
    checkFocus,
    imageProcessingOptions,
    userinterfaceName,
    detectedTextData,
    addReferenceToCache,
    reloadReferences,
    showError,
    showSuccess,
    shared,
  ]);

  // Handle auto-detect text
  const handleAutoDetectText = useCallback(async () => {
    if (!selectedArea) {
      console.log('[@hook:useVerificationEditor] Cannot auto-detect: missing area');
      return;
    }

    if (!captureSourcePath) {
      console.log('[@hook:useVerificationEditor] Cannot auto-detect: missing capture source path');
      return;
    }

    const roundedArea = roundArea(selectedArea);

    try {
      console.log(
        '[@hook:useVerificationEditor] Starting text auto-detection in area:',
        selectedArea,
      );

      // Extract filename from captureSourcePath for the backend
      const sourceFilename = captureSourcePath.split('/').pop() || '';
      console.log('[@hook:useVerificationEditor] Extracted source filename:', sourceFilename);

      const result = await api.post(buildServerUrl(`/server/verification/text/detectText`), {
        host_name: selectedHost.host_name, // Send full host object
        device_id: selectedDeviceId, // Add missing device_id parameter
        userinterface_name: userinterfaceName,
        area: roundedArea,
        image_source_url: sourceFilename,
        image_filter: textImageFilter,
      });

      if (result.success) {
        console.log('[@hook:useVerificationEditor] Text auto-detection successful:', result);

        setDetectedTextData({
          text: result.extracted_text || '',
          fontSize: result.font_size || 0,
          confidence: result.confidence || 0,
          detectedLanguage: result.language || result.detected_language,
          detectedLanguageName: result.detected_language_name,
          languageConfidence: result.language_confidence,
          image_textdetected_path: result.image_textdetected_path || result.processed_image_path,
        });

        // Pre-fill the text input with detected text
        setReferenceText(result.extracted_text || '');

        // Display the cropped area image in the drag area (like image cropping does)
        const imageUrl = result.image_textdetected_url || result.image_url;
        if (imageUrl) {
          const timestamp = new Date().getTime();
          const finalImageUrl = `${imageUrl}?t=${timestamp}`;
          console.log(
            '[@hook:useVerificationEditor] Text detection using text detected image URL:',
            finalImageUrl,
          );
          setCapturedReferenceImage(finalImageUrl);
        }

        // Mark as captured
        setHasCaptured(true);
      } else {
        console.log('[@hook:useVerificationEditor] No text detected, but processing image result:', result);

        // Even when no text is detected, we should still show the processed image and set helpful state
        setDetectedTextData({
          text: '',
          fontSize: result.font_size || 0,
          confidence: result.confidence || 0,
          detectedLanguage: result.language || result.detected_language || 'en',
          detectedLanguageName: result.detected_language_name,
          languageConfidence: result.language_confidence || 0,
          image_textdetected_path: result.image_textdetected_path || result.processed_image_path,
        });

        // Set helpful message when no text is detected
        setReferenceText('No text detected in image');

        // Still display the processed image even when no text is found
        const imageUrl = result.image_textdetected_url || result.image_url;
        if (imageUrl) {
          const timestamp = new Date().getTime();
          const finalImageUrl = `${imageUrl}?t=${timestamp}`;
          console.log(
            '[@hook:useVerificationEditor] No text detected, but showing processed image:',
            finalImageUrl,
          );
          setCapturedReferenceImage(finalImageUrl);
        }

        // Mark as captured so user can see the result
        setHasCaptured(true);
        
        console.log('[@hook:useVerificationEditor] Text auto-detection completed with no text found, but image processed successfully');
      }
    } catch (error) {
      console.error('[@hook:useVerificationEditor] Error during text auto-detection:', error);
      showError(
        `Text detection error: ${error instanceof Error ? error.message : 'Unknown error'}`,
      );
    }
  }, [
    selectedArea,
    selectedHost,
    captureSourcePath,
    textImageFilter,
    userinterfaceName,
    selectedDeviceId,
    showError,
  ]);

  // Validate regex
  const validateRegex = useCallback((text: string): boolean => {
    if (!text) return true; // Empty text is valid

    try {
      new RegExp(text);
      return true;
    } catch {
      return false;
    }
  }, []);

  // Handle confirm overwrite
  const handleConfirmOverwrite = useCallback(async () => {
    setShowConfirmDialog(false);
    await handleSaveReference();
  }, [handleSaveReference]);

  // Handle cancel overwrite
  const handleCancelOverwrite = useCallback(() => {
    setShowConfirmDialog(false);
  }, []);

  // Calculate if capture is possible
  const canCapture = selectedArea;

  // Calculate if save is possible
  const canSave = (() => {
    if (!referenceName.trim() || !selectedArea) {
      return false;
    }

    if (referenceType === 'image') {
      // Save no longer requires a manual Capture click. handleSaveReference
      // crops from captureSourcePath + selectedArea and uploads in one shot
      // (see the cropImage/processImage → saveImage path), so the only hard
      // requirement is a live source frame. Capture stays as preview-only.
      return Boolean(captureSourcePath);
    } else if (referenceType === 'text') {
      return referenceText.trim() !== '' && validateRegex(referenceText); // Text type requires valid text/regex
    }

    return false;
  })();

  // Calculate if selection is allowed
  const allowSelection = !isCaptureActive && captureSourcePath;

  // Handle type change
  const handleReferenceTypeChange = useCallback((newType: 'image' | 'text') => {
    setReferenceType(newType);
    // Reset related states when switching types
    if (newType === 'text') {
      setReferenceText('');
      setDetectedTextData(null);
      // Reset image processing options when switching to text
      setImageProcessingOptions({ autocrop: false, removeBackground: false });
    }
  }, []);

  // ─── Bidirectional area sync (editor only) ──────────────────────────
  // The reference area exists in two UI surfaces: the drag rectangle on the
  // screenshot (`selectedArea`, what Save crops/uploads) and the first
  // image/text verification's X/Y/W/H (`params.area`, what Test runs). Users
  // expect editing either to update the other. areasEqual at integer
  // precision is the loop guard — each direction settles after one hop.

  // Verification row X/Y/W/H → drag box. Wraps the base change handler and
  // mirrors the first image/text verification's area into selectedArea.
  const handleVerificationsChange = useCallback(
    (next: any[]) => {
      verification.handleVerificationsChange(next);
      const idx = firstAreaVerifIndex(next);
      if (idx === -1) return;
      const verifArea = next[idx]?.params?.area;
      if (verifArea && _onAreaSelected && !areasEqual(verifArea, selectedArea)) {
        _onAreaSelected(roundArea(verifArea));
      }
    },
    [verification, selectedArea, _onAreaSelected],
  );

  // Drag box → verification row. Mirrors selectedArea into the first
  // image/text verification. area_modified:true stops VerificationsList's
  // auto-resolve from pulling the stale reference area back over the edit.
  useEffect(() => {
    if (!selectedArea) return;
    const verifs = verification.verifications as any[];
    const idx = firstAreaVerifIndex(verifs);
    if (idx === -1) return;
    if (areasEqual(verifs[idx]?.params?.area, selectedArea)) return;
    const nextVerifs = verifs.map((v: any, i: number) =>
      i === idx
        ? {
            ...v,
            params: { ...v.params, area: roundArea(selectedArea), area_modified: true },
          }
        : v,
    );
    verification.handleVerificationsChange(nextVerifs);
  }, [selectedArea, verification.verifications]);

  // ─── Refresh verification rows after Save ───────────────────────────
  // Each verification row holds an inline SNAPSHOT of the reference's text
  // (params.text) and area (params.area); Test runs from those row params,
  // not from the live reference. Editing the capture "Text / Regex Pattern"
  // field and clicking Save updates the reference cache but leaves the
  // already-attached row's snapshot stale, so Test keeps using the OLD text
  // until the user manually reselects the reference. Keyed on
  // referenceSaveCounter, this re-resolves the matching row(s) from the
  // freshly-saved values right after every save.
  const lastSyncedSaveCounter = useRef(0);
  useEffect(() => {
    if (referenceSaveCounter === lastSyncedSaveCounter.current) return;
    lastSyncedSaveCounter.current = referenceSaveCounter;
    if (referenceSaveCounter === 0) return;

    const internalKey = `${referenceName}_${referenceType}`;
    const savedRef = (modelReferences as any)[internalKey];
    const verifs = verification.verifications as any[];

    let changed = false;
    const next = verifs.map((v) => {
      const params = v?.params || {};
      // Match rows that point at the just-saved reference (text rows store
      // the suffixed internalKey in reference_name; image rows additionally
      // store the display name in image_path).
      const matches =
        params.reference_name === internalKey ||
        params.reference_name === referenceName ||
        params.image_path === referenceName;
      if (!matches) return v;

      const newParams: any = { ...params };
      const newArea = savedRef?.area ? roundArea(savedRef.area) : roundArea(selectedArea);
      if (newArea) {
        newParams.area = newArea;
        newParams.area_modified = true; // keep auto-resolve from clobbering it
      }
      if (referenceType === 'text') {
        newParams.text = savedRef?.text ?? referenceText;
        newParams.text_modified = false; // value now matches the saved reference
      }
      changed = true;
      return { ...v, params: newParams };
    });

    if (changed) verification.handleVerificationsChange(next);
  }, [
    referenceSaveCounter,
    referenceName,
    referenceType,
    referenceText,
    selectedArea,
    modelReferences,
    verification,
  ]);

  return {
    // Include all verification functionality
    ...verification,

    // Editor area-sync wrapper — overrides the base handler from
    // ...verification above so the VerificationsList X/Y/W/H stay in
    // lockstep with the drag rectangle / Save.
    handleVerificationsChange,

    // References functionality
    availableReferences,
    referencesLoading,
    getModelReferences,
    modelReferences,

    // Editor-specific state
    referenceName,
    capturedReferenceImage,
    hasCaptured,
    pendingSave,
    saveSuccess,
    showConfirmDialog,
    referenceSaveCounter,
    referenceText,
    referenceType,
    detectedTextData,
    textImageFilter,
    checkFocus,
    selectedReferenceImage,
    selectedReferenceInfo,
    imageProcessingOptions,
    canCapture,
    canSave,
    allowSelection,
    verificationsCollapsed,
    captureCollapsed,
    shared,

    // Editor-specific setters
    setReferenceName,
    setCapturedReferenceImage,
    setHasCaptured,
    setShowConfirmDialog,
    setPendingSave,
    setReferenceText,
    setTextImageFilter,
    setCheckFocus,
    setImageProcessingOptions,
    setVerificationsCollapsed,
    setCaptureCollapsed,
    setShared,

    // Editor-specific handlers
    handleReferenceSelected,
    handleCaptureReference,
    handleSaveReference,
    handleAutoDetectText,
    validateRegex,
    handleConfirmOverwrite,
    handleCancelOverwrite,
    handleReferenceTypeChange,
  };
};

export type UseVerificationEditorType = ReturnType<typeof useVerificationEditor>;
