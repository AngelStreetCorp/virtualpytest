import { useState, useEffect, useRef, useCallback, useMemo } from 'react';

import { Host } from '../../types/common/Host_Types';
import { DragArea, HdmiStreamState, HdmiStreamActions, VideoFrame } from '../../types/controller/Hdmi_Types';
import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { useControllerApi } from './useControllerApi';

interface UseHdmiStreamProps {
  host: Host;
  deviceId?: string;
  deviceModel?: string;
  streamUrl?: string;
  isStreamActive?: boolean;
}

export function useHdmiStream({
  host,
  deviceId = 'device1',
  deviceModel = 'unknown',
  streamUrl: providedStreamUrl = '',
  isStreamActive: providedIsStreamActive = false,
}: UseHdmiStreamProps): HdmiStreamState & HdmiStreamActions {
  // Stream state - now controlled by component
  const [streamUrl, setStreamUrl] = useState<string>(providedStreamUrl);
  const [isStreamActive, setIsStreamActive] = useState(providedIsStreamActive);
  const [captureMode, setCaptureMode] = useState<'stream' | 'screenshot' | 'video'>('stream');

  // Capture state
  const [isCaptureActive, setIsCaptureActive] = useState(false);
  const [captureImageRef, setCaptureImageRef] = useState<React.RefObject<HTMLImageElement> | null>(
    null,
  );
  const [captureImageDimensions, setCaptureImageDimensions] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const [originalImageDimensions, setOriginalImageDimensions] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const [captureSourcePath, setCaptureSourcePath] = useState<string>(''); // TODO: Rename to imageSourceUrl
  const [selectedArea, setSelectedArea] = useState<DragArea | null>(null);

  // Screenshot state
  const [screenshotPath, setScreenshotPath] = useState<string>('');

  // Video state
  const [videoFramesPath, _setVideoFramesPath] = useState<string>('');
  const [videoFrames, setVideoFrames] = useState<VideoFrame[]>([]);
  const [totalFrames, setTotalFrames] = useState<number>(0);
  const [currentFrame, setCurrentFrame] = useState<number>(0);
  const [captureStartTime, setCaptureStartTime] = useState<Date | null>(null);
  const [recordingStartTime, setRecordingStartTime] = useState<Date | null>(null);

  // UI state
  const [referenceName, setReferenceName] = useState<string>('hdmi_capture');
  const [capturedReferenceImage, setCapturedReferenceImage] = useState<string | null>(null);
  const [hasCaptured, setHasCaptured] = useState<boolean>(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [captureCollapsed, setCaptureCollapsed] = useState<boolean>(false);
  const [referenceText, setReferenceText] = useState<string>('');
  const [referenceType, setReferenceType] = useState<'image' | 'text'>('image');
  const [detectedTextData, setDetectedTextData] = useState<{
    text: string;
    fontSize: number;
    confidence: number;
    detectedLanguage?: string;
    detectedLanguageName?: string;
    languageConfidence?: number;
  } | null>(null);
  const [imageProcessingOptions, setImageProcessingOptions] = useState({
    autocrop: false,
    removeBackground: false,
  });

  // Refs
  const captureContainerRef = useRef<HTMLDivElement>(null);
  const videoElementRef = useRef<HTMLVideoElement>(null);
  const { postToHost } = useControllerApi(host, deviceId);

  // Update stream state when props change
  useEffect(() => {
    setStreamUrl(providedStreamUrl);
    setIsStreamActive(providedIsStreamActive);
    console.log(`[@hook:useHdmiStream] Stream URL updated: ${providedStreamUrl}`);
    console.log(`[@hook:useHdmiStream] Stream active: ${providedIsStreamActive}`);
  }, [providedStreamUrl, providedIsStreamActive]);

  // Clear success message after 3 seconds
  useEffect(() => {
    if (successMessage) {
      const timer = setTimeout(() => {
        setSuccessMessage(null);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [successMessage]);

  // Handle area selection from drag overlay
  const handleAreaSelected = useCallback(
    (area: { x: number; y: number; width: number; height: number }) => {
      console.log('[@hook:useHdmiStream] === AREA SELECTION DEBUG ===');
      console.log('[@hook:useHdmiStream] New area selected:', {
        x: area.x,
        y: area.y,
        width: area.width,
        height: area.height,
        area: area,
      });
      console.log('[@hook:useHdmiStream] Previous selected area:', selectedArea);
      console.log('[@hook:useHdmiStream] Capture image dimensions:', captureImageDimensions);
      console.log('[@hook:useHdmiStream] Original image dimensions:', originalImageDimensions);
      console.log('[@hook:useHdmiStream] Capture source path:', captureSourcePath);

      setSelectedArea(area);
    },
    [selectedArea, captureImageDimensions, originalImageDimensions, captureSourcePath],
  );

  // Handle clearing selection
  const handleClearSelection = useCallback(() => {
    console.log('[@hook:useHdmiStream] === AREA CLEAR DEBUG ===');
    console.log('[@hook:useHdmiStream] Clearing area selection');
    console.log('[@hook:useHdmiStream] Previous selected area:', selectedArea);

    // Clear captured reference images when clearing selection
    setCapturedReferenceImage(null);
    setHasCaptured(false);
    setSelectedArea(null);
  }, [selectedArea]);

  // Handle image load from capture components
  const handleImageLoad = useCallback(
    (
      ref: React.RefObject<HTMLImageElement>,
      dimensions: { width: number; height: number },
      sourcePath: string,
    ) => {
      console.log('[@hook:useHdmiStream] Image loaded:', { dimensions, sourcePath });
      setCaptureImageRef(ref);
      setCaptureImageDimensions(dimensions);
      setOriginalImageDimensions(dimensions);
      setCaptureSourcePath(sourcePath);
    },
    [],
  );

  const handleCaptureReference = useCallback(async () => {
    if (!selectedArea) {
      console.error('[@hook:useHdmiStream] Missing area selection for capture');
      return;
    }

    if (!captureSourcePath) {
      console.error('[@hook:useHdmiStream] No capture source path available');
      return;
    }

    console.log('[@hook:useHdmiStream] === CAPTURE REFERENCE DEBUG ===');
    console.log('[@hook:useHdmiStream] Selected area (original coordinates):', {
      x: selectedArea.x,
      y: selectedArea.y,
      width: selectedArea.width,
      height: selectedArea.height,
      area: selectedArea,
    });
    console.log('[@hook:useHdmiStream] Capture source path:', captureSourcePath);
    console.log('[@hook:useHdmiStream] Capture image dimensions:', captureImageDimensions);
    console.log('[@hook:useHdmiStream] Original image dimensions:', originalImageDimensions);
    console.log('[@hook:useHdmiStream] Reference name:', referenceName);
    console.log('[@hook:useHdmiStream] Model:', deviceModel);
    console.log(
      '[@hook:useHdmiStream] Processing options:',
      referenceType === 'image' ? imageProcessingOptions : undefined,
    );

    try {
      const areaPayload: Record<string, unknown> = {
        x: selectedArea.x,
        y: selectedArea.y,
        width: selectedArea.width,
        height: selectedArea.height,
      };

      let result;
      if (
        referenceType === 'image' &&
        (imageProcessingOptions.autocrop || imageProcessingOptions.removeBackground)
      ) {
        console.log('[@hook:useHdmiStream] Using process-area endpoint with processing options');
        result = await postToHost('/server/av/capture-area-process', {
          area: areaPayload,
          image_source_url: captureSourcePath,
          reference_name: referenceName,
          device_model: deviceModel,
          autocrop: imageProcessingOptions.autocrop,
          remove_background: imageProcessingOptions.removeBackground,
        });
      } else {
        console.log('[@hook:useHdmiStream] Using standard capture endpoint');
        result = await postToHost('/server/av/capture-area', {
          area: areaPayload,
          image_source_url: captureSourcePath,
          reference_name: referenceName,
          device_model: deviceModel,
        });
      }
      console.log('[@hook:useHdmiStream] Capture response result:', result);

      if (result.success) {
        const timestamp = new Date().getTime();
        // Use new field names with fallback to old ones
        const imageUrl = result.image_cropped_url || result.image_filtered_url || result.image_url;
        const finalImageUrl = `${imageUrl}?t=${timestamp}`;
        console.log(
          '[@hook:useHdmiStream] Temporary capture created successfully, setting image URL:',
          finalImageUrl,
        );
        setCapturedReferenceImage(finalImageUrl);
        setHasCaptured(true);

        // If autocrop was applied and new area dimensions are provided, update the selected area
        if (imageProcessingOptions.autocrop && result.processed_area) {
          console.log('[@hook:useHdmiStream] === AUTOCROP AREA UPDATE ===');
          console.log('[@hook:useHdmiStream] Original area:', selectedArea);
          console.log('[@hook:useHdmiStream] Processed area from server:', result.processed_area);
          setSelectedArea({
            x: result.processed_area.x,
            y: result.processed_area.y,
            width: result.processed_area.width,
            height: result.processed_area.height,
          });
          console.log('[@hook:useHdmiStream] Area updated after autocrop');
        }
      } else {
        console.error('[@hook:useHdmiStream] Failed to capture reference:', result.error);
      }
    } catch (error) {
      console.error('[@hook:useHdmiStream] Error capturing reference:', error);
    }
  }, [
    selectedArea,
    captureSourcePath,
    referenceName,
    host,
    deviceModel,
    referenceType,
    imageProcessingOptions,
    captureImageDimensions,
    originalImageDimensions,
  ]);

  // Handle take screenshot
  const handleTakeScreenshot = useCallback(async () => {
    try {
      const result = await postToHost('/server/av/takeScreenshot', {}, { includeDeviceId: true });
      if (result.success && result.screenshot_url) {
        // Add cache-busting timestamp to force image reload
        const timestamp = new Date().getTime();
        const screenshotUrlWithTimestamp = `${result.screenshot_url}?t=${timestamp}`;
        
        setScreenshotPath(screenshotUrlWithTimestamp);
        setCaptureSourcePath(screenshotUrlWithTimestamp);
        setCaptureMode('screenshot');
        console.log('[@hook:useHdmiStream] Screenshot taken:', screenshotUrlWithTimestamp);
      }
    } catch (error) {
      console.error('[@hook:useHdmiStream] Screenshot failed:', error);
    }
  }, [host, deviceId]);

  // Persist + load the captured frames for playback. promoteCapturedFrames copies
  // the recording window's frames from HOT (RAM, rotating) to COLD (persistent)
  // storage — the same hot->cold promotion takeScreenshot does — so the player's
  // images don't vanish when the RAM dir rotates. The host selects by duration
  // from its newest frame (clock-skew safe) and returns them oldest-first.
  const fetchCapturedFrames = useCallback(
    async (startMs: number, endMs: number) => {
      try {
        const result = await postToHost(
          '/server/av/promoteCapturedFrames',
          { duration_ms: Math.max(0, endMs - startMs) },
          { includeDeviceId: true },
        );
        const captures: VideoFrame[] = (result?.captures || []).map((c: any) => ({
          url: c.url,
          timestamp: c.timestamp,
        }));
        setVideoFrames(captures);
        setTotalFrames(captures.length);
        setCurrentFrame(0);
        console.log(
          `[@hook:useHdmiStream] Loaded ${captures.length} captured frames for playback`,
        );
      } catch (error) {
        console.error('[@hook:useHdmiStream] Failed to fetch captured frames:', error);
        setVideoFrames([]);
        setTotalFrames(0);
      }
    },
    [postToHost],
  );

  const handleAutoDetectText = useCallback(async () => {
    if (!selectedArea) {
      console.log('[@hook:useHdmiStream] Cannot auto-detect: missing area');
      return;
    }

    if (!captureSourcePath) {
      console.log('[@hook:useHdmiStream] Cannot auto-detect: missing capture source path');
      return;
    }

    try {
      console.log('[@hook:useHdmiStream] Starting text auto-detection in area:', selectedArea);

      const response = await apiClient(buildServerUrl(`/server/av/text-detect`), {
        method: 'POST',
        body: JSON.stringify({
          host_name: host.host_name,
          device_model: deviceModel,
          area: selectedArea,
          image_source_url: captureSourcePath,
          image_filter: 'none',
        }),
      });
      const result = await response.json();

      if (response.ok) {
        console.log('[@hook:useHdmiStream] Text auto-detection successful:', result);

        setDetectedTextData({
          text: result.detected_text,
          fontSize: result.font_size,
          confidence: result.confidence,
          detectedLanguage: result.detected_language,
          detectedLanguageName: result.detected_language_name,
          languageConfidence: result.language_confidence,
        });

        // Pre-fill the text input with detected text
        setReferenceText(result.detected_text);

        // Use the preview URL returned from the backend
        if (result.preview_url) {
          console.log(
            '[@hook:useHdmiStream] Setting preview from backend response:',
            result.preview_url,
          );
          setCapturedReferenceImage(result.preview_url);
          setHasCaptured(true);
        }
      } else {
        console.error(
          '[@hook:useHdmiStream] Text auto-detection failed:',
          response.status,
          result,
        );

        // Still show preview even if OCR failed (but area was cropped)
        if (result.preview_url) {
          console.log(
            '[@hook:useHdmiStream] Setting preview from error response:',
            result.preview_url,
          );
          setCapturedReferenceImage(result.preview_url);
          setHasCaptured(true);
        }
      }
    } catch (error) {
      console.error('[@hook:useHdmiStream] Error during text auto-detection:', error);
    }
  }, [selectedArea, deviceModel, host.host_name, captureSourcePath]);

  const validateRegex = useCallback((text: string): boolean => {
    if (!text) return true; // Empty text is valid

    try {
      new RegExp(text);
      return true;
    } catch {
      return false;
    }
  }, []);

  // Computed values
  const canCapture = !!selectedArea;
  const canSave = useMemo(() => {
    if (!referenceName.trim() || !selectedArea || !deviceModel || deviceModel.trim() === '') {
      return false;
    }

    if (referenceType === 'image') {
      return hasCaptured; // Image type requires capture
    } else if (referenceType === 'text') {
      return referenceText.trim() !== '' && validateRegex(referenceText); // Text type requires valid text/regex
    }

    return false;
  }, [
    referenceName,
    selectedArea,
    deviceModel,
    referenceType,
    hasCaptured,
    referenceText,
    validateRegex,
  ]);

  const allowSelection = !isCaptureActive && !!captureSourcePath && !!captureImageRef;

  // Layout config based on device model
  const layoutConfig = useMemo(() => {
    const isMobileModel =
      deviceModel === 'android_mobile' ||
      deviceModel === 'ios_mobile' ||
      deviceModel === 'cloud_android_mobile' ||
      deviceModel === 'cloud_ios_mobile';
    return {
      width: 400,
      height: 800,
      captureHeight: isMobileModel ? 300 : 200,
      isMobileModel,
    };
  }, [deviceModel]);

  return {
    // State
    streamUrl,
    isStreamActive,
    captureMode,
    isCaptureActive,
    captureImageRef,
    captureImageDimensions,
    originalImageDimensions,
    captureSourcePath,
    selectedArea,
    screenshotPath,
    videoFramesPath,
    videoFrames,
    totalFrames,
    currentFrame,
    captureStartTime,
    recordingStartTime,
    referenceName,
    capturedReferenceImage,
    hasCaptured,
    successMessage,
    captureCollapsed,
    referenceText,
    referenceType,
    detectedTextData,
    imageProcessingOptions,
    captureContainerRef,
    videoElementRef,
    canCapture,
    canSave,
    allowSelection,
    layoutConfig,

    // Actions
    setCaptureMode,
    setIsCaptureActive,
    setCurrentFrame,
    setTotalFrames,
    setCaptureStartTime,
    setRecordingStartTime,
    setReferenceName,
    setCaptureCollapsed,
    setReferenceText,
    setReferenceType,
    setImageProcessingOptions,
    handleAreaSelected,
    handleClearSelection,
    handleImageLoad,
    handleCaptureReference,
    handleTakeScreenshot,
    handleAutoDetectText,
    validateRegex,
    fetchCapturedFrames,
  };
}
