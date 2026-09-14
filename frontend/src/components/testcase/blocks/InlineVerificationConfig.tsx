/**
 * InlineVerificationConfig
 *
 * Renders a Verification block's config directly INSIDE the block — no modal.
 * A verification block is a CONTAINER: it holds a SET of verifications combined
 * with a pass condition (All / Any), exactly like a navigation node's
 * verifications panel. Add / pick reference / set threshold all happen inline,
 * and every change writes straight back to the node via `onUpdate`.
 *
 * Reuses VerificationsList/VerificationItem (the same components Edit-Node uses)
 * so there is one reference-picker implementation, and the shared
 * `cleanVerification` helper so schema params never render as "[object Object]".
 */

import React, { useEffect, useMemo, useRef } from 'react';
import { Box } from '@mui/material';

import { VerificationsList } from '../../verification/VerificationsList';
import { VerificationControlsLinkProps } from '../../verification/VerificationControls';
import { useTestCaseBuilder } from '../../../contexts/testcase/TestCaseBuilderContext';
import { useDeviceData } from '../../../contexts/device/DeviceDataContext';
import { useVerification } from '../../../hooks/verification/useVerification';
import { VerificationBlockData } from '../../../types/testcase/TestCase_Types';
import { cleanVerification } from '../dialogs/verificationParamUtils';

interface InlineVerificationConfigProps {
  data: VerificationBlockData;
  // Write the edited verification set back onto the node's data.
  onUpdate: (partial: Partial<VerificationBlockData>) => void;
  // Optional per-field data-linking (drag an upstream output onto Timeout/Threshold).
  linkProps?: VerificationControlsLinkProps;
  // Active userinterface name, used to look up the reference set. The
  // TestCaseBuilder reads this from its context provider; callers that render
  // this block OUTSIDE TestCaseBuilderProvider (e.g. QuickTestBuilder) must
  // pass it explicitly, otherwise the reference dropdown stays empty.
  userinterfaceName?: string;
}

export const InlineVerificationConfig: React.FC<InlineVerificationConfigProps> = ({
  data,
  onUpdate,
  linkProps,
  userinterfaceName: userinterfaceNameProp,
}) => {
  let contextData: any = null;
  try {
    contextData = useTestCaseBuilder();
  } catch {
    // Outside provider (shouldn't happen in the builder) — render with no refs.
  }

  // Prefer the explicit prop (QuickTestBuilder has no TestCaseBuilderProvider);
  // fall back to the builder context for the TestCaseBuilder embedding.
  const userinterfaceName: string | undefined =
    userinterfaceNameProp || contextData?.userinterfaceName;

  const {
    getModelReferences,
    getAvailableVerificationTypes,
    availableVerificationTypes,
    references,
    referencesLoading,
    refreshReferences,
    currentHost,
    currentDeviceId,
  } = useDeviceData();

  // The SET of verifications, derived (cleaned) straight from the block data.
  // No local copy — deriving from data means an undo/redo that rewrites
  // data.verifications is reflected immediately (a useState seed went stale).
  const verifications = useMemo(
    () => (data.verifications || []).map(cleanVerification),
    [data.verifications],
  );
  const passCondition: 'all' | 'any' = data.verification_pass_condition || 'all';

  // Per-item Run uses a reference-test verification run (no DB write). Keep the
  // hook's verification list in lockstep with the block's, then run by index.
  const verificationHook = useVerification({
    recordAs: { kind: 'reference-test' },
    userinterfaceName,
    verificationPassCondition: passCondition,
  });
  const { handleVerificationsChange, handleTestSingle, runningVerificationIndex } =
    verificationHook;
  useEffect(() => {
    handleVerificationsChange(verifications as any);
  }, [verifications, handleVerificationsChange]);

  // Existing references for the selected UI (same lookup as VerificationConfigDialog).
  const modelReferences = useMemo(() => {
    if (!userinterfaceName) return {};
    return getModelReferences(userinterfaceName);
    // `references` keeps this fresh as the cache fills/updates.
  }, [getModelReferences, userinterfaceName, references]);

  const deviceModel = useMemo(() => {
    const device = currentHost?.devices?.find((d: any) => d.device_id === currentDeviceId);
    return device?.device_model || 'android_mobile';
  }, [currentHost, currentDeviceId]);

  // Available verifications come from the DEVICE (loaded on take-control), same
  // source the toolbox used — already a Record<type, Verification[]>. Reading
  // the TestCaseBuilder context's global list instead left this empty.
  const availableVerificationsFormatted = useMemo(
    () => getAvailableVerificationTypes() || {},
    [getAvailableVerificationTypes, availableVerificationTypes],
  );

  // One-time guard: if the block still stores raw SCHEMA-shaped params, persist
  // the cleaned copy back so the node never holds "[object Object]" params. The
  // JSON compare both detects the need AND prevents looping (once stored ===
  // cleaned, the effect is a no-op forever).
  const persistedRef = useRef(false);
  useEffect(() => {
    if (persistedRef.current) return;
    const stored = data.verifications || [];
    if (stored.length && JSON.stringify(verifications) !== JSON.stringify(stored)) {
      persistedRef.current = true;
      onUpdate({ verifications });
    }
  }, [verifications, data.verifications, onUpdate]);

  // Refresh references when control is active so the dropdown fills without a reload.
  useEffect(() => {
    void refreshReferences();
  }, [refreshReferences]);

  // Every edit (add, remove, reference pick, threshold change, auto-resolve)
  // writes the whole set through. A verification block must keep at least one
  // verification — ignore an edit that would empty the list (so the user never
  // sees an empty block / can't delete the last row).
  const handleChange = (next: any[]) => {
    if (next.length === 0) return;
    onUpdate({ verifications: next });
  };

  const handlePassConditionChange = (condition: 'all' | 'any') => {
    onUpdate({ verification_pass_condition: condition });
  };

  return (
    // nodrag: lets you click/drag inside the editor (text fields, dropdowns)
    // without ReactFlow starting a node drag from the mousedown.
    <Box className="nodrag">
      <VerificationsList
        verifications={verifications}
        availableVerifications={availableVerificationsFormatted}
        onVerificationsChange={handleChange}
        loading={false}
        model={deviceModel}
        selectedHost={currentHost || undefined}
        testResults={[]}
        onReferenceSelected={() => {}}
        modelReferences={modelReferences}
        referencesLoading={referencesLoading}
        showCollapsible={false}
        title=""
        onTest={undefined}
        // Per-item Run — only when a device is controlled (else undefined hides
        // the run affordance). reference-test run = no DB write.
        onRunVerification={currentHost ? (index: number) => void handleTestSingle(index) : undefined}
        runningVerificationIndex={runningVerificationIndex}
        // Pass condition across the set (All must pass / Any can pass).
        passCondition={passCondition}
        onPassConditionChange={handlePassConditionChange}
        // Reference content (crop/text) is authored in VerificationEditor; the
        // block only picks which existing reference to use.
        referenceReadOnly={true}
        // Per-field data-linking (Timeout / Threshold).
        linkProps={linkProps}
      />
    </Box>
  );
};
