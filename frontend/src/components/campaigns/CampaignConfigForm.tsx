/**
 * Campaign Configuration Form Component
 * 
 * Form for configuring campaign-level settings like name, description,
 * execution configuration, and device selection.
 */

import React from 'react';
import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormControlLabel,
  Switch,
  Typography,
} from '@mui/material';
import { CampaignConfig, CampaignExecutionConfig } from '../../types/pages/Campaign_Types';
import { UserinterfaceSelector } from '../common/UserinterfaceSelector';

interface CampaignConfigFormProps {
  config: Partial<CampaignConfig>;
  hosts: any[];
  getDevicesFromHost: (hostName: string) => any[];
  onConfigChange: (updates: Partial<CampaignConfig>) => void;
  errors: string[];
  deviceModel?: string; // For UserinterfaceSelector
}

export const CampaignConfigForm: React.FC<CampaignConfigFormProps> = ({
  config,
  hosts,
  getDevicesFromHost,
  onConfigChange,
  deviceModel,
}) => {
  const handleBasicInfoChange = (field: keyof CampaignConfig, value: string) => {
    onConfigChange({ [field]: value });
  };

  const handleExecutionConfigChange = (field: keyof CampaignExecutionConfig, value: any) => {
    onConfigChange({
      execution_config: {
        ...config.execution_config,
        timeout_minutes: 120, // Fixed to 2 hours
        [field]: value,
      } as CampaignExecutionConfig,
    });
  };

  const handleHostChange = (hostName: string) => {
    onConfigChange({
      host: hostName,
      device: '', // Reset device when host changes
    });
  };

  const selectedHostDevices = config.host ? getDevicesFromHost(config.host) : [];

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      {/* Compact form - all fields in minimal space */}
      <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
        <FormControl fullWidth size="small">
          <InputLabel>Campaign *</InputLabel>
          <Select
            value={config.name || ''}
            label="Campaign *"
            onChange={(e) => {
              const campaignName = e.target.value;
              const campaignId = `${campaignName.replace(/\s+/g, '_').toLowerCase()}_${Date.now()}`;
              handleBasicInfoChange('name', campaignName);
              handleBasicInfoChange('campaign_id', campaignId);
            }}
            error={!config.name}
          >
            <MenuItem value="fullzap_double">Fullzap Double</MenuItem>
            <MenuItem value="validation_suite">Validation Suite</MenuItem>
            <MenuItem value="goto_live_test">Goto Live Test</MenuItem>
            <MenuItem value="custom_campaign">Custom Campaign</MenuItem>
          </Select>
        </FormControl>
      </Box>

      <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
        <FormControl fullWidth size="small">
          <InputLabel>Host *</InputLabel>
          <Select
            value={config.host || ''}
            label="Host *"
            onChange={(e) => handleHostChange(e.target.value)}
            error={!config.host}
          >
            {hosts.map((host) => (
              <MenuItem key={host.host_name} value={host.host_name}>
                {host.host_name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <FormControl fullWidth size="small">
          <InputLabel>Device *</InputLabel>
          <Select
            value={config.device || ''}
            label="Device *"
            onChange={(e) => handleBasicInfoChange('device', e.target.value)}
            disabled={!config.host || selectedHostDevices.length === 0}
            error={!config.device}
          >
            {selectedHostDevices.map((device) => (
              <MenuItem key={device.device_id} value={device.device_id}>
                {device.device_id} ({device.device_model})
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <UserinterfaceSelector
          deviceModel={deviceModel}
          value={config.userinterface_name || ''}
          onChange={(userinterface) => handleBasicInfoChange('userinterface_name', userinterface)}
          label="User Interface *"
          size="small"
          fullWidth
        />
      </Box>

      {/* Simple execution settings */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Timeout: 2h
        </Typography>
        <FormControlLabel
          control={
            <Switch
              checked={config.execution_config?.continue_on_failure ?? true}
              onChange={(e) => handleExecutionConfigChange('continue_on_failure', e.target.checked)}
              size="small"
            />
          }
          label="Continue on Failure"
        />
      </Box>
    </Box>
  );
};
