/**
 * App icon palette (TASK-102 G15). ONE MUI icon per meaning, all from the Outlined family
 * (`@mui/icons-material/*Outlined`). Use `<AppIcon name="success" />` instead of an emoji or a
 * one-off icon import; `<StatusText ok>` for "icon + word" status lines (UI_STYLE "status = coloured icon + word").
 * Status icons (success / error / warning / info / running / pending) take the fixed status colours of
 * `useAgentChatPalette()`; every other icon inherits `currentColor`.
 * Strings (toasts, alerts, labels, i18n, logs) cannot hold React icons: no emoji there at all (UI_STYLE "Icons").
 */
import React from 'react';
import { Box } from '@mui/material';
import type { SvgIconComponent } from '@mui/icons-material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import WarningAmberOutlinedIcon from '@mui/icons-material/WarningAmberOutlined';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import AutorenewOutlinedIcon from '@mui/icons-material/AutorenewOutlined';
import ScheduleOutlinedIcon from '@mui/icons-material/ScheduleOutlined';
import SearchOutlinedIcon from '@mui/icons-material/SearchOutlined';
import AutoAwesomeOutlinedIcon from '@mui/icons-material/AutoAwesomeOutlined';
import BarChartOutlinedIcon from '@mui/icons-material/BarChartOutlined';
import EditNoteOutlinedIcon from '@mui/icons-material/EditNoteOutlined';
import LinkOutlinedIcon from '@mui/icons-material/LinkOutlined';
import GpsFixedOutlinedIcon from '@mui/icons-material/GpsFixedOutlined';
import MicNoneOutlinedIcon from '@mui/icons-material/MicNoneOutlined';
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined';
import BoltOutlinedIcon from '@mui/icons-material/BoltOutlined';
import CloseOutlinedIcon from '@mui/icons-material/CloseOutlined';
import AddOutlinedIcon from '@mui/icons-material/AddOutlined';
import DeleteOutlineOutlinedIcon from '@mui/icons-material/DeleteOutlineOutlined';
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import DevicesOutlinedIcon from '@mui/icons-material/DevicesOutlined';
import PlayArrowOutlinedIcon from '@mui/icons-material/PlayArrowOutlined';
import StopOutlinedIcon from '@mui/icons-material/StopOutlined';
import ContentCopyOutlinedIcon from '@mui/icons-material/ContentCopyOutlined';
import FileDownloadOutlinedIcon from '@mui/icons-material/FileDownloadOutlined';
import FileUploadOutlinedIcon from '@mui/icons-material/FileUploadOutlined';
import AccessTimeOutlinedIcon from '@mui/icons-material/AccessTimeOutlined';
import ExploreOutlinedIcon from '@mui/icons-material/ExploreOutlined';
import TokenOutlinedIcon from '@mui/icons-material/TokenOutlined';
import PsychologyOutlinedIcon from '@mui/icons-material/PsychologyOutlined';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import FolderOutlinedIcon from '@mui/icons-material/FolderOutlined';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import StarOutlineOutlinedIcon from '@mui/icons-material/StarOutlineOutlined';
import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined';
import PublicOutlinedIcon from '@mui/icons-material/PublicOutlined';
import RocketLaunchOutlinedIcon from '@mui/icons-material/RocketLaunchOutlined';
import LayersOutlinedIcon from '@mui/icons-material/LayersOutlined';
import ExtensionOutlinedIcon from '@mui/icons-material/ExtensionOutlined';
import StorageOutlinedIcon from '@mui/icons-material/StorageOutlined';
import CropSquareOutlinedIcon from '@mui/icons-material/CropSquareOutlined';
import CallSplitOutlinedIcon from '@mui/icons-material/CallSplitOutlined';
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined';
import TextFieldsOutlinedIcon from '@mui/icons-material/TextFieldsOutlined';
import ExpandMoreOutlinedIcon from '@mui/icons-material/ExpandMoreOutlined';
import NotificationsNoneOutlinedIcon from '@mui/icons-material/NotificationsNoneOutlined';
import ChevronRightOutlinedIcon from '@mui/icons-material/ChevronRightOutlined';
import AutoStoriesOutlinedIcon from '@mui/icons-material/AutoStoriesOutlined';
import { useAgentChatPalette } from './agentChatTheme';

export const APP_ICONS = {
  success: CheckCircleOutlineIcon,
  error: ErrorOutlineIcon,
  warning: WarningAmberOutlinedIcon,
  info: InfoOutlinedIcon,
  running: AutorenewOutlinedIcon,
  pending: ScheduleOutlinedIcon,
  search: SearchOutlinedIcon,
  ai: AutoAwesomeOutlinedIcon,
  report: BarChartOutlinedIcon,
  edit: EditNoteOutlinedIcon,
  link: LinkOutlinedIcon,
  target: GpsFixedOutlinedIcon,
  mic: MicNoneOutlinedIcon,
  image: ImageOutlinedIcon,
  fast: BoltOutlinedIcon,
  close: CloseOutlinedIcon,
  add: AddOutlinedIcon,
  delete: DeleteOutlineOutlinedIcon,
  refresh: RefreshOutlinedIcon,
  settings: SettingsOutlinedIcon,
  device: DevicesOutlinedIcon,
  play: PlayArrowOutlinedIcon,
  stop: StopOutlinedIcon,
  copy: ContentCopyOutlinedIcon,
  download: FileDownloadOutlinedIcon,
  upload: FileUploadOutlinedIcon,
  time: AccessTimeOutlinedIcon,
  navigation: ExploreOutlinedIcon,
  tokens: TokenOutlinedIcon,
  thinking: PsychologyOutlinedIcon,
  lock: LockOutlinedIcon,
  folder: FolderOutlinedIcon,
  docs: DescriptionOutlinedIcon,
  star: StarOutlineOutlinedIcon,
  tree: AccountTreeOutlinedIcon,
  globe: PublicOutlinedIcon,
  launch: RocketLaunchOutlinedIcon,
  layers: LayersOutlinedIcon,
  extension: ExtensionOutlinedIcon,
  storage: StorageOutlinedIcon,
  area: CropSquareOutlinedIcon,
  branch: CallSplitOutlinedIcon,
  agent: SmartToyOutlinedIcon,
  text: TextFieldsOutlinedIcon,
  expand: ExpandMoreOutlinedIcon,
  chevron: ChevronRightOutlinedIcon,
  bell: NotificationsNoneOutlinedIcon,
  memory: AutoStoriesOutlinedIcon,
} as const satisfies Record<string, SvgIconComponent>;

export type AppIconName = keyof typeof APP_ICONS;

const SIZES = { sm: 16, md: 20 } as const;

interface AppIconProps {
  name: AppIconName;
  size?: keyof typeof SIZES;
  /** Override the colour (default: status colour for status icons, else currentColor). */
  color?: string;
}

export const AppIcon: React.FC<AppIconProps> = ({ name, size = 'sm', color }) => {
  const P = useAgentChatPalette();
  const statusColour: Partial<Record<AppIconName, string>> = {
    success: P.success,
    error: P.error,
    warning: P.warning,
    info: P.textSecondary,
    running: P.accentText,
    pending: P.textMuted,
  };
  const Icon = APP_ICONS[name];
  return (
    <Icon
      sx={{ fontSize: SIZES[size], color: color ?? statusColour[name] ?? 'inherit', verticalAlign: 'middle', flexShrink: 0 }}
    />
  );
};

interface StatusTextProps {
  /** true = success, false = error; pass `level` for a warning / info line. */
  ok?: boolean;
  level?: 'success' | 'error' | 'warning' | 'info';
  size?: keyof typeof SIZES;
  children: React.ReactNode;
}

/** Coloured status icon + word (UI_STYLE: status = coloured icon + word). */
export const StatusText: React.FC<StatusTextProps> = ({ ok, level, size = 'sm', children }) => {
  const P = useAgentChatPalette();
  const lvl = level ?? (ok === false ? 'error' : 'success');
  const colour = { success: P.success, error: P.error, warning: P.warning, info: P.textSecondary }[lvl];
  return (
    <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, color: colour }}>
      <AppIcon name={lvl} size={size} />
      <span>{children}</span>
    </Box>
  );
};
