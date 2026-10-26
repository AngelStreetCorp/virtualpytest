/**
 * Device ceiling editor (TASK-31 phase C), shared by the Teams, Roles and Users editors.
 *
 * `value` is a list of `host_name:device_id` keys, or null for "no limit". `limit` is what the
 * level above allows (team ∩ role for a user); devices outside it cannot be picked. A device
 * limit filters what people see in the app — it is not an authorization boundary.
 */
import SettingRow from '../common/SettingRow';
import React from 'react';
import { Alert, Box, Typography } from '@mui/material';
import { useServerManager } from '../../hooks/useServerManager';
import { TargetPanel } from '../common/TargetPanel';

interface DeviceScopePickerProps {
  value: string[] | null;
  onChange: (next: string[] | null) => void;
  /** What the parent level allows; null/undefined = every device. */
  limit?: string[] | null;
  /** Names the parent level in the "outside the limit" reason, e.g. "team and role". */
  limitLabel?: string;
  disabled?: boolean;
}

export const DeviceScopePicker: React.FC<DeviceScopePickerProps> = ({
  value,
  onChange,
  limit = null,
  limitLabel = 'parent',
  disabled = false,
}) => {
  const { serverHostsData } = useServerManager();

  // Every registered server's hosts: a device limit applies across the whole platform.
  const allHosts = React.useMemo(() => {
    const byHostName = new Map<string, { host_name: string; devices: any[] }>();
    serverHostsData.forEach((server) => {
      server.hosts.forEach((host) => {
        const existing = byHostName.get(host.host_name);
        if (existing) {
          const seen = new Set(existing.devices.map((d: any) => d.device_id));
          (host.devices || []).forEach((d: any) => {
            if (!seen.has(d.device_id)) existing.devices.push(d);
          });
        } else {
          byHostName.set(host.host_name, { host_name: host.host_name, devices: [...(host.devices || [])] });
        }
      });
    });
    return Array.from(byHostName.values()).sort((a, b) =>
      a.host_name.localeCompare(b.host_name, undefined, { numeric: true }),
    );
  }, [serverHostsData]);

  const getDevicesFromHost = React.useCallback(
    (hostName: string) => allHosts.find((h) => h.host_name === hostName)?.devices ?? [],
    [allHosts],
  );

  const selected = React.useMemo(() => new Map((value ?? []).map((key) => [key, ''])), [value]);
  const outsideLimit = (key: string) => limit !== null && !limit.includes(key);

  const toggle = (key: string) => {
    const current = value ?? [];
    onChange(current.includes(key) ? current.filter((k) => k !== key) : [...current, key]);
  };

  return (
    <Box>
      <SettingRow
        title="No limit"
        description={
          value === null
            ? limit === null
              ? 'Every device'
              : `No limit of its own: the ${limitLabel} limit applies (${limit.length} devices)`
            : `${value.length} device${value.length !== 1 ? 's' : ''} allowed`
        }
        checked={value === null}
        disabled={disabled}
        // Turning the limit on starts from what the parent allows (or nothing).
        onChange={(on) => onChange(on ? null : [...(limit ?? [])])}
      />
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Filters which devices appear in the app. It does not block device control or runs started
        through the API.
      </Typography>
      {value !== null &&
        (allHosts.length === 0 ? (
          <Alert severity="info">No hosts registered.</Alert>
        ) : (
          <TargetPanel
            selectedDevices={selected}
            onToggle={disabled ? () => undefined : toggle}
            onUpdateUserinterface={() => undefined}
            allHosts={allHosts}
            getDevicesFromHost={getDevicesFromHost}
            isTargetDisabled={(key) => disabled || (outsideLimit(key) && !selected.has(key))}
            getDisabledReason={(key) => (outsideLimit(key) ? `outside the ${limitLabel} limit` : undefined)}
            selectionCountLabel={`${value.length} device${value.length !== 1 ? 's' : ''} selected`}
          />
        ))}
    </Box>
  );
};
