/** Plain-language text for the monitoring profiles: one line for tooltips, one line per service for the info card. */
const PROFILE_ONE_LINERS: Record<string, string> = {
  tv_app: 'Black screen, freeze, zap, audio loss, subtitles',
  tv_lite: 'Stream and control only, no monitoring',
  pc: 'Like TV lite, for PC and desktop captures',
  caption_playback: 'Watch 2.5 min behind live with captions of its own audio',
  counting_cars: 'Counts cars, trucks and buses in the picture',
  egg_quality: 'Grades eggs on a belt as good or bad',
  ad_meter: 'Share of a live channel that is ad breaks',
  drone: 'Drone battery, heat, altitude and GPS next to its picture',
  fixnet: 'Voice line: no picture monitoring, keeps the KPI scan and A/V quality score',
};

const PROFILE_TITLES: Record<string, string> = {
  tv_app: 'TV app testing',
  tv_lite: 'TV lite',
  pc: 'PC',
  caption_playback: 'Caption playback',
  counting_cars: 'Counting cars',
  egg_quality: 'Egg quality',
  ad_meter: 'Ad meter',
  drone: 'Drone',
  fixnet: 'Voice line',
};

export const profileTitle = (profile: string): string => PROFILE_TITLES[profile] ?? profile.replace(/_/g, ' ');

export const profileOneLiner = (profile: string): string =>
  PROFILE_ONE_LINERS[profile] ?? `Monitoring profile ${profile}`;

/** Services a profile can switch on, in display order, with what each one does. */
export const PROFILE_SERVICES: Array<{ key: string; label: string; unit: string; does: string }> = [
  { key: 'img', unit: 'vpt-monitor-img', label: 'Image', does: 'Black screen, freeze, zap' },
  { key: 'audio', unit: 'vpt-monitor-audio', label: 'Audio', does: 'Loss and levels' },
  { key: 'subtitle', unit: 'vpt-monitor-subtitle', label: 'Subtitles', does: 'Text and language' },
  { key: 'archiver', unit: 'vpt-archiver', label: 'Archive', does: '24 h replay' },
  { key: 'kpi', unit: 'vpt-kpi', label: 'KPI scan', does: 'Zap timings' },
  { key: 'avq', unit: 'vpt-avq', label: 'A/V quality', does: 'Per-minute score' },
];

const ALL_OFF = { img: false, audio: false, subtitle: false, archiver: false, kpi: false, avq: false };
const IMG_ONLY = { img: true, audio: false, subtitle: false, archiver: true, kpi: true, avq: true };
const ALL_ON = { img: true, audio: true, subtitle: true, archiver: true, kpi: true, avq: true };
/** fixnet: nothing that looks at a screen, only the two services that score a call. */
const QUALITY_ONLY = { img: false, audio: false, subtitle: false, archiver: false, kpi: true, avq: true };

/**
 * Services of the stock profiles (mirrors backend_host/config/monitor/profiles/*.yaml; a service a manifest
 * does not name is on for img/archiver/kpi/avq, off for audio/subtitle). Used when the host's status does not
 * carry `monitor_profile_services`, as on the Device Control page.
 */
const PROFILE_SERVICE_DEFAULTS: Record<string, Record<string, boolean>> = {
  tv_app: ALL_ON,
  caption_playback: ALL_ON,
  tv_lite: ALL_OFF,
  pc: ALL_OFF,
  counting_cars: IMG_ONLY,
  egg_quality: IMG_ONLY,
  ad_meter: IMG_ONLY,
  drone: IMG_ONLY,
  fixnet: QUALITY_ONLY,
};

export const profileServicesFallback = (profile: string): Record<string, boolean> | undefined =>
  PROFILE_SERVICE_DEFAULTS[profile];
