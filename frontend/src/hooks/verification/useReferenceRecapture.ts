import { useState, useCallback } from 'react';

import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useToastContext } from '../../contexts/ToastContext';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { invalidateSignedUrl } from '../../utils/infrastructure/cloudflareUtils';

/**
 * In-place reference recapture.
 *
 * "Recapture" takes a fresh screenshot from the controlled device, crops it
 * with the reference's CURRENT stored area (box + fuzzy box, untouched), and
 * overwrites the existing image reference in R2 + DB under the same name. It
 * is the one-click counterpart to VerificationEditor's drag → Capture → Save
 * flow for the common case "the screen changed, recapture the same region".
 *
 * Area is read from the reference asset (`modelReferences[key].area`), never
 * from the verification's possibly-edited params, so a recapture can never
 * silently move the area or drop the fuzzy-search coordinates.
 *
 * Host + device come from DeviceDataContext (the currently-controlled device);
 * a live frame is only obtainable while control is active. `userinterfaceName`
 * scopes the reference lookup + R2 folder.
 */
export const useReferenceRecapture = (userinterfaceName?: string) => {
  const { currentHost, currentDeviceId, getModelReferences, addReferenceToCache } = useDeviceData();
  const { showError, showSuccess } = useToastContext();

  // Index of the verification row currently recapturing (null = idle). Drives
  // the per-row spinner so two rows can't fire at once visually.
  const [recapturingIndex, setRecapturingIndex] = useState<number | null>(null);

  const recapture = useCallback(
    // checkFocus: when true the saved reference also learns the "selected" accent
    // (border / underline / fill) so the verification fails when the element is on
    // screen but NOT focused. When false, any previously-learned focus is cleared
    // (we strip it from the area before saving). See docs/agent/devices/image.md.
    async (index: number, internalKey: string, checkFocus: boolean = false) => {
      if (!currentHost || !currentDeviceId) {
        showError('Take control of a device before recapturing');
        return;
      }
      if (!userinterfaceName) {
        showError('No user interface context — cannot recapture');
        return;
      }

      const references = getModelReferences(userinterfaceName);
      const ref = references[internalKey];
      if (!ref || ref.type !== 'image' || !ref.area) {
        showError('Reference has no stored area to recapture');
        return;
      }

      // Original DB name (the select stores the internal key); area is the
      // canonical reference box including any fuzzy coordinates. Strip any stale
      // learned focus — the backend re-learns it from this fresh crop when
      // checkFocus is on, or leaves it cleared when off.
      const referenceName = ref.name || internalKey;
      const { focus: _staleFocus, ...area } = (ref.area as any) || {};

      setRecapturingIndex(index);
      try {
        // 1. Fresh frame from the live device → verification_source.jpg
        const shot = await api.post<{ success?: boolean; screenshot_url?: string; error?: string }>(
          buildServerUrl('/server/av/takeScreenshot'),
          { host_name: currentHost.host_name, device_id: currentDeviceId },
        );
        if (!shot.success || !shot.screenshot_url) {
          throw new Error(shot.error || 'Failed to take screenshot');
        }

        // 2. Crop the fresh frame with the reference's existing area.
        const crop = await api.post<{ success?: boolean; filename?: string; message?: string }>(
          buildServerUrl('/server/verification/image/cropImage'),
          {
            host_name: currentHost.host_name,
            device_id: currentDeviceId,
            area,
            image_source_url: shot.screenshot_url,
            reference_name: referenceName,
            userinterface_name: userinterfaceName,
          },
        );
        if (!crop.success || !crop.filename) {
          throw new Error(crop.message || 'Failed to crop screenshot');
        }

        // 3. Overwrite the reference in R2 + DB (same name, same area).
        const save = await api.post<{
          success?: boolean;
          r2_url?: string;
          message?: string;
          error?: string;
          area?: any;
          focus_warning?: string | null;
        }>(
          buildServerUrl('/server/verification/image/saveImage'),
          {
            host_name: currentHost.host_name,
            device_id: currentDeviceId,
            reference_name: referenceName,
            userinterface_name: userinterfaceName,
            area,
            image_source_url: crop.filename,
            reference_type: 'reference_image',
            check_focus: checkFocus, // learn / clear the focus accent
          },
        );
        if (!save.success) {
          throw new Error(save.error || save.message || 'Failed to save reference');
        }
        // Focus requested but no accent learnable — area likely excludes the indicator.
        if (checkFocus && save.focus_warning) {
          showError(save.focus_warning);
        }

        // Refresh ONLY this reference's preview — no global reloadReferences()
        // (that flips referencesLoading and reflows the whole panel). The R2
        // key was overwritten in place, so:
        //   1. Drop the cached signed URL for the path; otherwise getR2Url
        //      hands back the old signed URL (→ old bytes) for ~55 min.
        //   2. Re-seed the cache entry with a cache-busted url so the preview's
        //      useR2Url(path) sees a changed path, re-runs, and re-signs to the
        //      now-overwritten object.
        const savedUrl = save.r2_url || ref.url;
        invalidateSignedUrl(savedUrl);
        invalidateSignedUrl(ref.url);
        const bustedUrl = `${savedUrl}${savedUrl.includes('?') ? '&' : '?'}recap=${Date.now()}`;
        addReferenceToCache(userinterfaceName, {
          name: referenceName,
          type: 'image',
          // Prefer the area echoed back by the server — it carries the freshly
          // learned area.focus (or its absence) so the cached ref stays in sync.
          area: (save.area ?? area) as any,
          url: bustedUrl,
          shared: ref.shared,
        });
        showSuccess(`Recaptured reference "${referenceName}"`);
      } catch (err) {
        showError(`Recapture failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
      } finally {
        setRecapturingIndex(null);
      }
    },
    [currentHost, currentDeviceId, userinterfaceName, getModelReferences, addReferenceToCache, showError, showSuccess],
  );

  return { recapture, recapturingIndex };
};

export type UseReferenceRecaptureType = ReturnType<typeof useReferenceRecapture>;
