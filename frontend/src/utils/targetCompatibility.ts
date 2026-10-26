import { getCompatibleModels } from '../config/deviceModelFamilies';
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

/**
 * The rules for an executable that declares none.
 *
 * 'all', not 'device': an executable with no declared rules fits every target,
 * and the Run page must say so in ONE place. It used to say 'device' when it
 * filtered the executable list and 'all' when it pruned the selected targets,
 * so picking a rule-less script could silently delete the operator's target
 * (QA-OPS-19) — the list showed the script, and taking it removed the target
 * and greyed out the Run button without a word.
 *
 * The two call sites that answer "does this executable fit this target" must
 * use this constant, so the list and the pruning can never disagree again.
 */
export const NO_DECLARED_RULES: Required<TargetRules> = {
  target_type: 'all',
  host_os: 'all',
  device_model: 'all',
};

/**
 * True when the host really has a device with that id.
 *
 * The device id 'host' is the host_vnc pseudo-device — the browser device the
 * target list offers like any other device — and not "the host". Deciding
 * from the id string alone is what made the Run page drop a browser target
 * when a script was picked (QA-OPS-19).
 */
export const hostHasDeviceWithId = (host: Host | undefined, deviceId: string): boolean =>
  (host?.devices || []).some((device) => device.device_id === deviceId);

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

/**
 * The rules an executable imposes on the target it is run on.
 *
 * ONE answer for every call site: the executable list and the target pruning
 * must never disagree, or a script shows up in the list and then deletes the
 * operator's target when it is picked (QA-OPS-19 / BUG-0789).
 *
 * An executable that declares **no** target rules can run on any target: the
 * server only checks the rules a script actually declares
 * (`server_script_routes.py`), and the other direction on the Run page —
 * "which scripts can I run here?" — already treats a rule-less script as
 * compatible with everything. Defaulting to 'device' instead made the page
 * prune a target the server would have run, without a word to the user.
 *
 * "No rules" means what the server means by it: no rules object at all, or an
 * empty one — `extract_script_target_rules()` returns None for an empty dict,
 * so the server checks nothing at all for it.
 *
 * Rules that ARE declared are normalised, so a partial one reads exactly like
 * the backend reads it (`normalize_target_rules`): a missing target_type means
 * 'device', a missing model means 'all'.
 */
export const effectiveTargetRules = (rules?: TargetRules | null): Required<TargetRules> => {
  if (!rules || Object.keys(rules).length === 0) {
    return NO_DECLARED_RULES;
  }
  return normalizeTargetRules(rules);
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

  // Model families: a runner stands in for its physical equivalent, and an Android
  // phone is one whether it is reached by adb, by the paired app or through a cloud
  // farm. One table, shared with userinterface matching — a script declaring
  // `device_model: android_mobile` must therefore be offered for a farm phone too.
  const familyModels = getCompatibleModels(deviceModel);
  if (ruleModels.some((m) => familyModels.includes(m))) {
    return true;
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
