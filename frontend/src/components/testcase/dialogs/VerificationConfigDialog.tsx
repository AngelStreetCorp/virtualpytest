import CloseIcon from '@mui/icons-material/Close';
import React, { useState, useMemo, useEffect } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  IconButton,
} from '@mui/material';
import { VerificationBlockData } from '../../../types/testcase/TestCase_Types';
import { VerificationsList } from '../../verification/VerificationsList';
import { getZIndex } from '../../../utils/zIndexUtils';
import { useTestCaseBuilder } from '../../../contexts/testcase/TestCaseBuilderContext';
import { useDeviceData } from '../../../contexts/device/DeviceDataContext';
import { StyledDialog } from '../../common/StyledDialog';
import { cleanVerification } from './verificationParamUtils';

interface VerificationConfigDialogProps {
  open: boolean;
  initialData?: VerificationBlockData;
  onSave: (data: VerificationBlockData) => void;
  onCancel: () => void;
  // For showing output values
  mode?: 'configure' | 'viewValue';
  outputName?: string;
  outputValue?: any;
}

export const VerificationConfigDialog: React.FC<VerificationConfigDialogProps> = ({
  open,
  initialData,
  onSave,
  onCancel,
  mode = 'configure',
  outputName,
  outputValue
}) => {
  // Try to get available verifications from context (if available)
  // This allows the component to work both within and outside TestCaseBuilderProvider
  let contextData: any = null;
  try {
    contextData = useTestCaseBuilder();
  } catch (error) {
    // Context not available
    // Continue with empty array
  }
  
  // Existing references for the selected userinterface, so the user can pick a
  // saved reference from the dropdown instead of authoring params by hand —
  // mirrors the Navigation Node/Edge edit dialogs (which read the same
  // DeviceDataContext via useNodeEdit / getModelReferences).
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

  const userinterfaceName: string | undefined = contextData?.userinterfaceName;

  const modelReferences = useMemo(() => {
    if (!userinterfaceName) return {};
    return getModelReferences(userinterfaceName);
    // `references` keeps this fresh as the cache fills/updates.
  }, [getModelReferences, userinterfaceName, references]);

  // Device model for the reference dropdown context (mirrors NodeEditDialog).
  const deviceModel = useMemo(() => {
    const device = currentHost?.devices?.find((d: any) => d.device_id === currentDeviceId);
    return device?.device_model || 'android_mobile';
  }, [currentHost, currentDeviceId]);

  // Re-fetch references whenever the dialog opens so references created
  // elsewhere (e.g. the stream panel's Verification Editor) show up without a
  // page reload. Honours the server cache (refreshReferences, not reload).
  useEffect(() => {
    if (open && mode === 'configure') {
      void refreshReferences();
    }
  }, [open, mode, refreshReferences]);

  // Store single verification in an array for VerificationsList component
  const [verifications, setVerifications] = useState<any[]>([
    cleanVerification(initialData) || { command: '', params: {} }
  ]);

  // The block seeds params as PARAM SCHEMAS (e.g. text: {type:'string'}) rather
  // than values, so without cleaning the editor renders "[object Object]" in
  // Search Text. Re-seed (cleaned) every time the dialog opens to configure so
  // the fields show real defaults and a reference pick can fill them.
  useEffect(() => {
    if (open && mode === 'configure' && initialData) {
      setVerifications([cleanVerification(initialData)]);
    }
    // Intentionally keyed on open only — initialData is a fresh literal each
    // render and would otherwise reset the form on every keystroke.
  }, [open]);

  // Available verifications come from the DEVICE (loaded on take-control), the
  // same Record<type, Verification[]> shape VerificationsList expects — and the
  // same source InlineVerificationConfig uses.
  const availableVerificationsFormatted = useMemo(
    () => getAvailableVerificationTypes() || {},
    [getAvailableVerificationTypes, availableVerificationTypes],
  );

  const handleSave = () => {
    // Save the first (and only) verification
    if (verifications.length > 0 && verifications[0].command) {
      onSave(verifications[0]);
    }
  };

  const isValid = verifications.length > 0 && Boolean(verifications[0].command);

  // Format value for display
  const formatValue = (value: any): string => {
    if (value === null) return 'null';
    if (value === undefined) return 'undefined';
    if (typeof value === 'object') {
      return JSON.stringify(value, null, 2);
    }
    return String(value);
  };

  const hasExecutionValue = outputValue !== undefined;

  return (
    <StyledDialog 
      open={open} 
      onClose={onCancel} 
      maxWidth={mode === 'viewValue' ? 'sm' : 'md'} 
      fullWidth
      sx={{ zIndex: getZIndex('NAVIGATION_DIALOGS') }}
    >
      <DialogTitle sx={{ borderBottom: 1, borderColor: 'divider', pb: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="h6">
            {mode === 'viewValue' ? (outputName || 'Output Value') : 'Configure Verification'}
          </Typography>
          <IconButton onClick={onCancel} size="small">
            <CloseIcon />
          </IconButton>
        </Box>
      </DialogTitle>

      <DialogContent sx={{ py: mode === 'viewValue' ? 3 : 0.5 }}>
        {mode === 'viewValue' ? (
          // Show output value
          <>
            {hasExecutionValue ? (
              <Box>
                <Typography variant="caption" sx={{ color: 'text.secondary', mb: 1, display: 'block' }}>
                  VALUE
                </Typography>
                <Box
                  sx={{
                    bgcolor: 'rgba(16, 185, 129, 0.1)',
                    border: '1px solid rgba(16, 185, 129, 0.3)',
                    borderRadius: 1,
                    p: 2,
                    fontFamily: 'monospace',
                    fontSize: '0.9rem',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                    maxHeight: '400px',
                    overflowY: 'auto'
                  }}
                >
                  {formatValue(outputValue)}
                </Box>
              </Box>
            ) : (
              <Box
                sx={{
                  bgcolor: 'rgba(239, 68, 68, 0.1)',
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  borderRadius: 1,
                  p: 2,
                  textAlign: 'center'
                }}
              >
                <Typography variant="body2" color="text.secondary">
                  No value yet. Run the test case to see the output value.
                </Typography>
              </Box>
            )}
          </>
        ) : (
          // Show verification config
          <>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Edit the verification parameters
            </Typography>

            <Box
              sx={{
                border: '1px solid',
                borderColor: 'divider',
                borderRadius: 1,
                p: 1,
              }}
            >
              <VerificationsList
                verifications={verifications}
                availableVerifications={availableVerificationsFormatted}
                onVerificationsChange={setVerifications}
                loading={false}
                model={deviceModel}
                selectedHost={currentHost || undefined}
                testResults={[]}
                onReferenceSelected={() => {}}
                // Existing references for the selected UI — selecting one fills
                // the block's params (text/area) from the saved reference.
                modelReferences={modelReferences}
                referencesLoading={referencesLoading}
                showCollapsible={false}
                title=""
                onTest={undefined}
                // Reference content (the stored crop/text) is authored in
                // VerificationEditor; this dialog only picks which existing
                // reference to use, so its area/text stay read-only here.
                referenceReadOnly={true}
              />
            </Box>
          </>
        )}
      </DialogContent>

      <DialogActions sx={{ borderTop: 1, borderColor: 'divider', pt: 2, pb: 2, px: 3 }}>
        {mode === 'viewValue' ? (
          <Button onClick={onCancel} variant="contained">
            Close
          </Button>
        ) : (
          <>
            <Button onClick={onCancel} variant="outlined">
              Cancel
            </Button>
            <Button onClick={handleSave} variant="contained" disabled={!isValid}>
              Save
            </Button>
          </>
        )}
      </DialogActions>
    </StyledDialog>
  );
};
