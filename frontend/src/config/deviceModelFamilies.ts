/**
 * Device model families — which model names describe the same kind of device.
 *
 * Several model names describe the same *thing* reached a different way. An Android
 * phone is an Android phone whether adb is plugged into it (`android_mobile`), the
 * VirtualPyTest app is paired with it (`phone_agent`, features/mobile-app), it lives
 * in a cloud farm (`cloud_android_mobile`, features/device-farm) or a CI runner is
 * standing in for it (`runner_android_mobile`). They run the same navigation trees,
 * the same action blocks and the same scripts.
 *
 * Without this table every matcher compared model strings exactly, so a userinterface
 * built for `android_mobile` was invisible to a paired phone and to a farm phone —
 * which is why near-duplicate userinterfaces (`phone_home`, `cloud_farm_demo`) had to
 * be created per transport.
 *
 * This is the mirror of `MODEL_FAMILIES` in
 * `shared/src/lib/config/device_capabilities.py`. The two must stay in step — the
 * backend filters `getCompatibleInterfaces` with the Python copy and the frontend
 * filters hosts, campaigns and script targets with this one.
 *
 * A model that is not listed here is its own family — adding a model is only needed
 * when it is genuinely interchangeable with another one.
 */
export const MODEL_FAMILIES: Record<string, string[]> = {
  android_phone: ['android_mobile', 'phone_agent', 'cloud_android_mobile', 'runner_android_mobile'],
  android_tablet: ['android_tablet', 'runner_android_tablet'],
  android_tv: ['android_tv', 'fire_tv', 'runner_android_tv'],
  ios_phone: ['ios_mobile', 'cloud_ios_mobile'],
  desktop_host: ['host_vnc', 'runner_host'],
};

/**
 * One-directional extras, for pairs that are *not* twins.
 *
 * A `host_vnc` device can run a web or desktop userinterface, because it has a browser
 * and a desktop on it — this rule pre-dates the family table and lives on. The reverse
 * is not true: a `web` device is Playwright only, so offering it a `host_vnc`
 * userinterface would offer a tree full of desktop actions it cannot execute. That
 * asymmetry is why these are not a family.
 */
export const MODEL_EXTRA_MATCHES: Record<string, string[]> = {
  host_vnc: ['web', 'desktop'],
  runner_host: ['web', 'desktop'],
};

// model name → family name, built once. A model may only belong to one family.
const MODEL_TO_FAMILY: Record<string, string> = Object.entries(MODEL_FAMILIES).reduce(
  (acc, [family, models]) => {
    models.forEach((model) => {
      acc[model] = family;
    });
    return acc;
  },
  {} as Record<string, string>,
);

/** Family name for a model, or the model itself when it is in no family. */
export function getModelFamily(deviceModel: string): string {
  return MODEL_TO_FAMILY[deviceModel] || deviceModel;
}

/**
 * Every model name a device of `deviceModel` should be matched against.
 *
 * Always contains `deviceModel` itself, so an unknown or feature-specific model
 * degrades to exact matching.
 */
export function getCompatibleModels(deviceModel: string): string[] {
  if (!deviceModel) return [];
  const family = MODEL_TO_FAMILY[deviceModel];
  const models = family ? [...MODEL_FAMILIES[family]] : [deviceModel];
  (MODEL_EXTRA_MATCHES[deviceModel] || []).forEach((extra) => {
    if (!models.includes(extra)) models.push(extra);
  });
  return models;
}

/** True when two model names describe the same kind of device. */
export function modelsAreCompatible(modelA: string, modelB: string): boolean {
  if (!modelA || !modelB) return false;
  return getModelFamily(modelA) === getModelFamily(modelB);
}

/**
 * True when `deviceModel` is compatible with any entry of `models` — typically a
 * userinterface's `models[]` column.
 */
export function modelMatchesAny(deviceModel: string, models?: string[] | null): boolean {
  if (!deviceModel || !models || models.length === 0) return false;
  const compatible = getCompatibleModels(deviceModel);
  return models.some((model) => compatible.includes(model));
}

/**
 * Expand a userinterface's `models[]` into every model name that should be accepted
 * for it — the reverse direction of `modelMatchesAny`, for filtering a device list by
 * an already-chosen userinterface.
 */
export function expandModels(models?: string[] | null): string[] {
  if (!models || models.length === 0) return [];
  const expanded = new Set(models.flatMap((model) => getCompatibleModels(model)));
  // Reverse of MODEL_EXTRA_MATCHES: a `web` userinterface is runnable by a `host_vnc`
  // device, even though a `web` device cannot run a `host_vnc` one.
  Object.entries(MODEL_EXTRA_MATCHES).forEach(([deviceModel, extras]) => {
    if (models.some((model) => extras.includes(model))) expanded.add(deviceModel);
  });
  return Array.from(expanded);
}
