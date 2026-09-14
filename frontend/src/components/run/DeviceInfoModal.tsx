/**
 * DeviceInfoModal — set manual device info (metadata.info) per selected device.
 *
 * Device info is a property of the device, not the script, so it's edited once
 * here (at the Selected Items level) and applied to every script the run
 * executes on that device (merged into metadata.info by the executor). The user
 * fills plain Key/Value fields — no JSON/format to worry about; the backend
 * normalizes. `device_get_info` ignores it (it fetches its own).
 */
import {
  Add as AddIcon,
  Close as CloseIcon,
  DeleteOutline as DeleteIcon,
  ContentCopy as CopyIcon,
} from '@mui/icons-material';
import {
  Autocomplete,
  Box,
  Button,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useEffect, useState } from 'react';
import { StyledDialog } from '../common/StyledDialog';

export type DeviceInfoMap = Record<string, Record<string, string>>;

interface Pair {
  k: string;
  v: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  devices: { deviceKey: string; label: string }[];
  value: DeviceInfoMap;
  onChange: (next: DeviceInfoMap) => void;
}

const COMMON_KEYS = [
  'build_version',
  'software_version',
  'hardware_version',
  'serial_number_stb',
  'application_version',
];

const toPairs = (obj?: Record<string, string>): Pair[] =>
  obj ? Object.entries(obj).map(([k, v]) => ({ k, v })) : [];

const toObj = (pairs: Pair[]): Record<string, string> => {
  const o: Record<string, string> = {};
  pairs.forEach(({ k, v }) => {
    const key = k.trim();
    if (key) o[key] = v;
  });
  return o;
};

export const DeviceInfoModal: React.FC<Props> = ({ open, onClose, devices, value, onChange }) => {
  // Local editable pairs per device (keeps empty rows while typing); committed
  // to the parent map (dropping empty keys) on every edit.
  const [pairsByDevice, setPairsByDevice] = useState<Record<string, Pair[]>>({});

  useEffect(() => {
    if (!open) return;
    const init: Record<string, Pair[]> = {};
    devices.forEach((d) => {
      init[d.deviceKey] = toPairs(value[d.deviceKey]);
    });
    setPairsByDevice(init);
    // Re-seed only when the modal opens (intentionally ignoring devices/value).
  }, [open]);

  const commit = (next: Record<string, Pair[]>) => {
    setPairsByDevice(next);
    const map: DeviceInfoMap = {};
    Object.entries(next).forEach(([deviceKey, pairs]) => {
      const obj = toObj(pairs);
      if (Object.keys(obj).length > 0) map[deviceKey] = obj;
    });
    onChange(map);
  };

  const update = (deviceKey: string, pairs: Pair[]) =>
    commit({ ...pairsByDevice, [deviceKey]: pairs });

  const setPair = (deviceKey: string, idx: number, patch: Partial<Pair>) => {
    const pairs = [...(pairsByDevice[deviceKey] || [])];
    pairs[idx] = { ...pairs[idx], ...patch };
    update(deviceKey, pairs);
  };

  const addField = (deviceKey: string) =>
    update(deviceKey, [...(pairsByDevice[deviceKey] || []), { k: '', v: '' }]);

  const removeField = (deviceKey: string, idx: number) =>
    update(deviceKey, (pairsByDevice[deviceKey] || []).filter((_, i) => i !== idx));

  const copyToAll = (deviceKey: string) => {
    const source = (pairsByDevice[deviceKey] || []).map((p) => ({ ...p }));
    const next: Record<string, Pair[]> = {};
    devices.forEach((d) => {
      next[d.deviceKey] = source.map((p) => ({ ...p }));
    });
    commit(next);
  };

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', pr: 1 }}>
        <span>Device Info</span>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Recorded into <code>metadata.info</code> for every script run on each device
        </Typography>

        {devices.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            Select target devices first.
          </Typography>
        )}

        <Stack spacing={2} divider={<Divider flexItem />}>
          {devices.map((d) => {
            const pairs = pairsByDevice[d.deviceKey] || [];
            return (
              <Box key={d.deviceKey}>
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                  <Typography variant="subtitle2">{d.label}</Typography>
                  {devices.length > 1 && pairs.some((p) => p.k.trim()) && (
                    <Tooltip title="Copy these fields to all selected devices">
                      <Button size="small" startIcon={<CopyIcon fontSize="small" />} onClick={() => copyToAll(d.deviceKey)} sx={{ textTransform: 'none' }}>
                        Copy to all
                      </Button>
                    </Tooltip>
                  )}
                </Box>
                <Stack spacing={1}>
                  {pairs.map((pair, idx) => (
                    <Stack key={idx} direction="row" spacing={1} alignItems="center">
                      <Autocomplete
                        freeSolo
                        size="small"
                        options={COMMON_KEYS}
                        value={pair.k}
                        onInputChange={(_, v) => setPair(d.deviceKey, idx, { k: v })}
                        sx={{ flex: 1 }}
                        renderInput={(params) => <TextField {...params} label="Key" placeholder="build_version" />}
                      />
                      <TextField
                        size="small"
                        label="Value"
                        value={pair.v}
                        onChange={(e) => setPair(d.deviceKey, idx, { v: e.target.value })}
                        sx={{ flex: 1 }}
                      />
                      <IconButton size="small" onClick={() => removeField(d.deviceKey, idx)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Stack>
                  ))}
                  <Box>
                    <Button size="small" startIcon={<AddIcon fontSize="small" />} onClick={() => addField(d.deviceKey)} sx={{ textTransform: 'none' }}>
                      Add field
                    </Button>
                  </Box>
                </Stack>
              </Box>
            );
          })}
        </Stack>
      </DialogContent>
    </StyledDialog>
  );
};
