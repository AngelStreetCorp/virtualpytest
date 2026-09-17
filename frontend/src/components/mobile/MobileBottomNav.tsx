import {
  Dashboard as DashboardIcon,
  Devices as DevicesIcon,
  PlayArrow as PlayArrowIcon,
  GridView as GridViewIcon,
  MoreHoriz as MoreHorizIcon,
  PhoneAndroid as PhoneIcon,
} from '@mui/icons-material';
import {
  BottomNavigation,
  BottomNavigationAction,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Paper,
} from '@mui/material';
import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { isFeatureEnabled } from '../../config/features';
import { useIsNativeApp } from '../../hooks/useIsNativeApp';
import { useResponsiveMode } from '../../hooks/useResponsiveMode';
import { MOBILE_MORE_MENU_ITEMS, MORE_TAB_VALUE, type MobileMoreMenuItem } from './MobileMoreMenuItems';

// features/mobile-app entry point (docs/tasks/TASK-17): one More-menu entry whose label and
// destination depend on where the bundle runs — on the web it opens "Mobile app & phones"
// (get the app / pair a phone), inside the native app it opens "This phone" (pair and check
// the phone you are holding). Not folded into MOBILE_MORE_MENU_ITEMS itself — that list is a
// static mirror of the desktop dropdowns, feature-unaware; this one is feature-gated and its
// destination depends on `native`, so it's spliced in here instead.
//
// It lived briefly as a sixth bottom-nav tab in the native app (560c73a4ec, on the argument
// that a phone needs pairing/status in a hurry); six labels are too many across a phone's
// width, so it is back in More at the user's request.
const MOBILE_APP_PAGE = '/configuration/mobile-app';
const THIS_PHONE_PATH = '/mobile-app/this-phone';

// `native` comes from useIsNativeApp() and is threaded through rather than read here:
// this used to call isNativeApp() directly, which pinned the answer to whatever was true
// during the first render and left the app in its web layout inside the APK.
const moreMenuItems = (native: boolean): MobileMoreMenuItem[] => {
  if (!isFeatureEnabled('mobile-app')) return MOBILE_MORE_MENU_ITEMS;
  // Settings must stay the last item in this menu, so splice the phone entry in
  // just before it rather than appending it after everything.
  const withoutSettings = MOBILE_MORE_MENU_ITEMS.slice(0, -1);
  const settings = MOBILE_MORE_MENU_ITEMS[MOBILE_MORE_MENU_ITEMS.length - 1];
  const phoneEntry: MobileMoreMenuItem = native
    ? { label: 'This phone', path: THIS_PHONE_PATH, icon: <PhoneIcon fontSize="small" /> }
    : { label: 'Mobile App', path: MOBILE_APP_PAGE, icon: <PhoneIcon fontSize="small" /> };
  return [...withoutSettings, phoneEntry, settings];
};

const resolveTabValue = (pathname: string, native: boolean): string => {
  if (pathname.startsWith('/run/') || pathname.startsWith('/test-execution/')) return '/run/tests';
  if (pathname.startsWith('/monitoring/heatmap')) return '/monitoring/heatmap';
  if (pathname.startsWith('/device-control')) return '/device-control';
  if (pathname.startsWith('/mobile-app/') || pathname.startsWith(MOBILE_APP_PAGE)) return MORE_TAB_VALUE;
  if (moreMenuItems(native).some((item) => pathname.startsWith(item.path))) return MORE_TAB_VALUE;
  return '/';
};

const MobileBottomNav: React.FC = () => {
  const { isMobile } = useResponsiveMode();
  const isNative = useIsNativeApp();
  const location = useLocation();
  const navigate = useNavigate();
  const [moreMenuAnchorEl, setMoreMenuAnchorEl] = useState<HTMLElement | null>(null);

  const isAuthPage = location.pathname === '/login' || location.pathname === '/auth/callback';
  const isHiddenRoute = location.pathname.startsWith('/ai-agent');

  if (!isMobile || isAuthPage || isHiddenRoute) {
    return null;
  }

  const closeMoreMenu = () => setMoreMenuAnchorEl(null);

  const handleTabChange = (event: React.SyntheticEvent, value: string) => {
    if (value === MORE_TAB_VALUE) {
      setMoreMenuAnchorEl(event.currentTarget as HTMLElement);
      return;
    }
    navigate(value);
  };

  const handleMoreItemClick = (path: string) => {
    closeMoreMenu();
    navigate(path);
  };

  return (
    <Paper
      elevation={8}
      sx={{
        position: 'fixed',
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 1200,
        borderTop: '1px solid',
        borderColor: 'divider',
      }}
    >
      <BottomNavigation
        value={resolveTabValue(location.pathname, isNative)}
        onChange={handleTabChange}
        showLabels
        sx={{
          '& .MuiBottomNavigationAction-root': {
            minWidth: 0,
            padding: '0px 4px',
          },
        }}
      >
        <BottomNavigationAction label="Dashboard" value="/" icon={<DashboardIcon />} />
        <BottomNavigationAction label="Device" value="/device-control" icon={<DevicesIcon />} />
        <BottomNavigationAction label="Run" value="/run/tests" icon={<PlayArrowIcon />} />
        <BottomNavigationAction label="Heatmap" value="/monitoring/heatmap" icon={<GridViewIcon />} />
        <BottomNavigationAction label="More" value={MORE_TAB_VALUE} icon={<MoreHorizIcon />} />
      </BottomNavigation>
      <Menu anchorEl={moreMenuAnchorEl} open={Boolean(moreMenuAnchorEl)} onClose={closeMoreMenu}>
        {moreMenuItems(isNative).map((item) => (
          <MenuItem key={item.path} onClick={() => handleMoreItemClick(item.path)}>
            <ListItemIcon>{item.icon}</ListItemIcon>
            <ListItemText>{item.label}</ListItemText>
          </MenuItem>
        ))}
      </Menu>
    </Paper>
  );
};

export default MobileBottomNav;
