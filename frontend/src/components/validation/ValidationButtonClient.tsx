'use client';

import AccountTreeIcon from '@mui/icons-material/AccountTree';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  Button,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  CircularProgress,
} from '@mui/material';
import React, { useState } from 'react';

import { useNavigationStack } from '../../contexts/navigation/NavigationStackContext';
import { useValidation } from '../../hooks/validation';
import ValidationPreviewClient from './ValidationPreviewClient';
import { ValidationProgressClient } from './ValidationProgressClient';
import ValidationResultsClient from './ValidationResultsClient';


interface ValidationButtonClientProps {
  treeId: string;
  disabled?: boolean;
  selectedHost?: any;
  selectedDeviceId?: string | null;
}

export default function ValidationButtonClient({ treeId, disabled, selectedHost, selectedDeviceId }: ValidationButtonClientProps) {
  const validation = useValidation(treeId, selectedHost, selectedDeviceId);
  const { isNested, currentLevel } = useNavigationStack();
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [showPreview, setShowPreview] = useState(false);

  const subtreeRootNodeId = isNested ? currentLevel?.parentNodeId : undefined;
  const subtreeName = currentLevel?.treeName;

  const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    if (validation.isValidating) return;
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleRunValidation = () => {
    handleClose();
    setShowPreview(true);
    // ValidationPreviewClient will handle loading preview data automatically
  };

  const handleRunValidationFromHere = () => {
    handleClose();
    if (subtreeRootNodeId) {
      validation.runValidation(undefined, subtreeRootNodeId);
    }
  };

  return (
    <>
      <Button
        variant="outlined"
        color="primary"
        onClick={handleClick}
        disabled={disabled || validation.isValidating || !validation.canRunValidation}
        endIcon={validation.isValidating ? <CircularProgress size={16} /> : <ExpandMoreIcon />}
        size="small"
        sx={{
          minWidth: 'auto',
          height: 32,
          whiteSpace: 'nowrap',
          fontSize: '0.75rem',
          textTransform: 'none',
        }}
      >
        {validation.isValidating ? 'Validating...' : 'Validate'}
      </Button>

      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleClose}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'left',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: 'left',
        }}
      >
        <MenuItem onClick={handleRunValidation}>
          <ListItemIcon>
            <CheckCircleIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Run Validation</ListItemText>
        </MenuItem>

        {subtreeRootNodeId && (
          <MenuItem onClick={handleRunValidationFromHere}>
            <ListItemIcon>
              <AccountTreeIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>
              {subtreeName ? `Run Validation from here (${subtreeName})` : 'Run Validation from here'}
            </ListItemText>
          </MenuItem>
        )}

        {validation.hasLastResults && (
          <MenuItem
            onClick={() => {
              handleClose();
              validation.viewLastValidationResults();
            }}
          >
            <ListItemIcon>
              <CheckCircleIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>View Last Results</ListItemText>
          </MenuItem>
        )}
      </Menu>

      {/* Validation Preview Dialog - only show when triggered */}
      {showPreview && (
        <ValidationPreviewClient 
          treeId={treeId} 
          onClose={() => setShowPreview(false)}
          selectedHost={selectedHost}
          selectedDeviceId={selectedDeviceId}
        />
      )}

      {/* Progress dialog - shows during validation */}
      {validation.isValidating && (
        <ValidationProgressClient
          treeId={treeId}
          selectedHost={selectedHost}
          selectedDeviceId={selectedDeviceId}
        />
      )}

      {/* Results dialog - shows completion status */}
      {validation.validationResult && (
        <ValidationResultsClient
          open={true}
          onClose={validation.clearValidationResult}
          success={validation.validationResult.success}
          duration={validation.validationResult.duration}
          reportUrl={validation.validationResult.reportUrl}
        />
      )}
    </>
  );
}
