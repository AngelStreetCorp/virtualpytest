import type { Host, Device } from '../types/common/Host_Types';

export interface TargetRules {
  target_type?: 'all' | 'host' | 'device';
  host_os?: 'all' | 'linux' | 'windows' | 'mac';
  device_model?: string;
}

const DEFAULT_RULES: Required<TargetRules> = {
  target_type: 'device',
  host_os: 'all',
  device_model: 'all',
};

export const normalizeTargetRules = (rules?: TargetRules | null): Required<TargetRules> => {
  const targetType = rules?.target_type;
  const hostOs = rules?.host_os;
  const deviceModel = rules?.device_model;

  return {
    target_type: targetType === 'all' || targetType === 'host' || targetType === 'device'
      ? targetType
      : DEFAULT_RULES.target_type,
    host_os: hostOs === 'all' || hostOs === 'linux' || hostOs === 'windows' || hostOs === 'mac'
      ? hostOs
      : DEFAULT_RULES.host_os,
    device_model: typeof deviceModel === 'string' && deviceModel.trim()
      ? deviceModel.trim()
      : DEFAULT_RULES.device_model,
  };
};

const normalizePlatform = (platform?: string): 'linux' | 'windows' | 'mac' | 'unknown' => {
  const value = (platform || '').trim().toLowerCase();
  if (!value) return 'unknown';
  if (value.includes('win')) return 'windows';
  if (value.includes('darwin') || value.includes('mac')) return 'mac';
  if (value.includes('linux')) return 'linux';
  return 'unknown';
};

const hostMatchesRules = (host: Host, rules: Required<TargetRules>) => {
  if (rules.host_os === 'all') {
    return true;
  }
  return normalizePlatform(host.system_stats?.platform) === rules.host_os;
};

// Runner models are compatible with their physical-device equivalents (bidirectional)
const COMPATIBLE_MODEL_GROUPS: string[][] = [
  ['runner_host', 'host_vnc'],
  ['runner_android_mobile', 'android_mobile'],
  ['runner_android_tablet', 'android_tablet'],
  ['runner_android_tv', 'android_tv'],
];

const deviceMatchesRules = (device: Device, rules: Required<TargetRules>) => {
  if (rules.device_model === 'all') {
    return true;
  }
  const deviceModel = (device.device_model || '').trim().toLowerCase();
  // Support pipe-separated model list (e.g. "runner_android_mobile|runner_android_tablet")
  const ruleModels = rules.device_model.toLowerCase().split('|').map((m) => m.trim());

  if (ruleModels.some((m) => m === 'all' || m === deviceModel)) {
    return true;
  }

  // Runner ↔ physical-device compatibility groups
  for (const group of COMPATIBLE_MODEL_GROUPS) {
    if (group.includes(deviceModel) && ruleModels.some((m) => group.includes(m))) {
      return true;
    }
  }

  return false;
};

export const isHostCompatibleWithRules = (host: Host, rulesInput?: TargetRules | null) => {
  const rules = normalizeTargetRules(rulesInput);
  if (!hostMatchesRules(host, rules)) {
    return false;
  }

  if (rules.target_type === 'all') {
    return true;
  }

  // target_type === 'host' runs against the special `host` device (the
  // host_vnc browser device, device_id 'host'), which only exists on hosts
  // configured with VNC + capture. Pure-STB hosts have no such device, so
  // running a host-only script there crashes with "Host created with 0
  // devices" — don't offer them as host targets.
  if (rules.target_type === 'host') {
    return (host.devices || []).some(
      (device) =>
        device.device_id === 'host' ||
        (device.device_model || '').trim().toLowerCase() === 'host_vnc',
    );
  }

  return (host.devices || []).some((device) => deviceMatchesRules(device, rules));
};

export const isDeviceCompatibleWithRules = (
  host: Host,
  device: Device,
  rulesInput?: TargetRules | null,
) => {
  const rules = normalizeTargetRules(rulesInput);
  if (!hostMatchesRules(host, rules)) {
    return false;
  }

  if (rules.target_type === 'host') {
    return false;
  }

  return deviceMatchesRules(device, rules);
};

export const isTargetKeyCompatibleWithRules = (
  key: string,
  allHosts: Host[],
  rulesInput?: TargetRules | null,
) => {
  const [hostName, deviceId] = key.split(':');
  const host = allHosts.find((entry) => entry.host_name === hostName);
  if (!host) {
    return false;
  }

  if (!deviceId || deviceId === 'host') {
    const rules = normalizeTargetRules(rulesInput);
    if (rules.target_type === 'device') {
      return false;
    }
    return isHostCompatibleWithRules(host, rulesInput);
  }

  const device = (host.devices || []).find((entry) => entry.device_id === deviceId);
  if (!device) {
    return false;
  }

  return isDeviceCompatibleWithRules(host, device, rulesInput);
};
