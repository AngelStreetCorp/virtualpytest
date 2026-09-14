import {
  Add as AddIcon,
  CloudUpload as CloudUploadIcon,
  Visibility as VisibilityIcon,
  VisibilityOff as VisibilityOffIcon,
} from '@mui/icons-material';
import {
  Box,
  Paper,
  Typography,
  Button,
  IconButton,
} from '@mui/material';
import React, { useRef, useState } from 'react';

// Reuse TestCaseSelector component
import { TestCaseSelector } from '../components/testcase/TestCaseSelector';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { useToast } from '../hooks/useToast';

import { buildServerUrl } from '../utils/buildUrlUtils';
import { invalidateTestCaseListCache } from '../utils/testcaseCache';

const TestCaseEditor: React.FC = () => {
  // Ref to access TestCaseSelector's refresh method
  const selectorRef = useRef<{ refresh: () => void }>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [showHidden, setShowHidden] = useState(false);
  const [uploading, setUploading] = useState(false);

  const { showSuccess, showError } = useToast();

  // Confirmation dialog
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  // Handle testcase load - store in sessionStorage and navigate to builder
  const handleLoad = (testcaseId: string) => {
    console.log('[@TestCaseEditor] Loading testcase:', testcaseId);
    
    // Store testcase ID to load in sessionStorage
    sessionStorage.setItem('testcase_to_load', testcaseId);
    
    // Navigate to TestCase Builder (it will check sessionStorage on mount)
    window.location.href = '/builder/test-builder';
  };

  // Handle testcase delete
  const handleDelete = async (testcaseId: string, testcaseName: string) => {
    confirm({
      title: 'Confirm Delete',
      message: `Are you sure you want to delete "${testcaseName}"?`,
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          const response = await fetch(buildServerUrl(`/server/testcase/${testcaseId}`), {
            method: 'DELETE',
          });

          if (!response.ok) {
            throw new Error('Failed to delete test case');
          }
          
          // Invalidate cache after successful deletion
          invalidateTestCaseListCache();
          
          // After successful deletion, refresh the list
          if (selectorRef.current) {
            selectorRef.current.refresh();
          }
        } catch (err) {
          console.error('Error deleting test case:', err);
          throw err;
        }
      },
    });
  };

  // Navigate to TestCase Builder for new test case
  const handleCreateNew = () => {
    // Clear any stored testcase to load
    sessionStorage.removeItem('testcase_to_load');
    window.location.href = '/builder/test-builder';
  };

  // POST the script to the server, which saves it and fans it out to all hosts.
  // Returns the parsed JSON plus the HTTP status so the caller can detect a 409 conflict.
  const postScript = async (file: File, overwrite: boolean) => {
    const formData = new FormData();
    formData.append('file', file);
    if (overwrite) formData.append('overwrite', 'true');
    // Note: don't set Content-Type — the browser sets the multipart boundary.
    const response = await fetch(buildServerUrl('/server/script/upload'), {
      method: 'POST',
      body: formData,
    });
    const data = await response.json().catch(() => ({}));
    return { status: response.status, data };
  };

  const finishUpload = (filename: string, hosts?: { host_name: string; ok: boolean }[]) => {
    invalidateTestCaseListCache();
    selectorRef.current?.refresh();
    const okHosts = (hosts || []).filter((h) => h.ok).length;
    const totalHosts = (hosts || []).length;
    showSuccess(
      totalHosts > 0
        ? `Uploaded "${filename}" (${okHosts}/${totalHosts} hosts)`
        : `Uploaded "${filename}"`,
    );
  };

  // Handle Python script upload from the header button
  const handleScriptFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // Reset the input so the same file can be re-selected later
    e.target.value = '';
    if (!file) return;

    if (!file.name.endsWith('.py')) {
      showError('Please select a Python (.py) script');
      return;
    }

    setUploading(true);
    try {
      const { status, data } = await postScript(file, false);

      if (status === 409 && data?.exists) {
        // Script already exists — confirm before overwriting on server + all hosts
        confirm({
          title: 'Script already exists',
          message: `A script named "${data.filename}" already exists. Overwrite it on the server and all hosts?`,
          confirmText: 'Overwrite',
          confirmColor: 'warning',
          onConfirm: async () => {
            const retry = await postScript(file, true);
            if (retry.data?.success) {
              finishUpload(retry.data.filename, retry.data.hosts);
            } else {
              showError(retry.data?.error || 'Upload failed');
            }
          },
        });
        return;
      }

      if (data?.success) {
        finishUpload(data.filename, data.hosts);
      } else {
        showError(data?.error || 'Upload failed');
      }
    } catch (err) {
      console.error('[@TestCaseEditor] Script upload failed:', err);
      showError('Upload failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box display="flex" alignItems="center" gap={1}>
          <Typography variant="h4" component="h1">
            Test Case
          </Typography>
          <IconButton
            size="small"
            onClick={() => setShowHidden((current) => !current)}
            color={showHidden ? 'primary' : 'default'}
          >
            {showHidden ? <VisibilityIcon /> : <VisibilityOffIcon />}
          </IconButton>
        </Box>
        <Box display="flex" gap={1}>
          <Button
            variant="outlined"
            startIcon={<CloudUploadIcon />}
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            Upload Python Script
          </Button>
          <Button variant="contained" startIcon={<AddIcon />} onClick={handleCreateNew}>
            Create Test Case
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".py"
            hidden
            onChange={handleScriptFile}
          />
        </Box>
      </Box>

      {/* Reuse TestCaseSelector component - same as dialog */}
      <Paper sx={{ p: 2, flex: 1, display: 'flex', flexDirection: 'column' }}>
        <TestCaseSelector
          ref={selectorRef}
          onLoad={handleLoad}
          onDelete={handleDelete}
          selectedTestCaseId={null}
          showHidden={showHidden}
        />
      </Paper>

      {/* Confirmation Dialog */}
      <ConfirmDialog
        open={dialogState.open}
        title={dialogState.title}
        message={dialogState.message}
        confirmText={dialogState.confirmText}
        cancelText={dialogState.cancelText}
        confirmColor={dialogState.confirmColor}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </Box>
  );
};

export default TestCaseEditor;
