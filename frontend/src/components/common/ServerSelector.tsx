import React from 'react';
import { FormControl, InputLabel, Select, MenuItem, Chip, Box, CircularProgress, Divider } from '@mui/material';
import { Lock as LockIcon, ArrowDropDown as ArrowDropDownIcon, Public as PublicIcon } from '@mui/icons-material';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useServerPicker } from '../../hooks/useServerPicker';
import { useI18n } from '../../i18n/useI18n';
import { ALL_SERVERS_SENTINEL, isAllServersSentinel } from '../../lib/allServer/scope';
import { TYPOGRAPHY } from '../../constants/typography';

// While switching, the spinner takes the arrow's slot so the name keeps its full width.
const SwitchingIcon: React.FC<{ className?: string }> = ({ className }) => (
  <CircularProgress size={16} className={className} />
);

interface ServerSelectorProps {
  size?: 'small' | 'medium';
  label?: string;
  variant?: 'outlined' | 'standard' | 'filled';
}

export const ServerSelector: React.FC<ServerSelectorProps> = ({
  size = 'small',
  label = 'Server',
  variant = 'outlined'
}) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const {
    selectedServer,
    availableServers,
    failedServers,
    isServerChanging,
    serverAuthStates,
    labelFor,
    handleChange,
    authDialog,
  } = useServerPicker();

  // The closed Select has a fixed width of 12 characters, so switching between a
  // short and a long server name does not resize it (that resize was the flash).
  // Names longer than 12 chars show their first 9 plus "...". The dropdown
  // MenuItems keep the full text.
  const MAX_DISPLAY_LENGTH = 12;
  const truncateForDisplay = (value: string): string => {
    if (value.length <= MAX_DISPLAY_LENGTH) return value;
    return `${value.slice(0, MAX_DISPLAY_LENGTH - 3)}...`;
  };

  const renderSelectedServer = (value: unknown): React.ReactNode => {
    const serverUrl = typeof value === 'string' ? value : '';
    if (isAllServersSentinel(serverUrl)) return t('All servers');
    return truncateForDisplay(labelFor(serverUrl));
  };

  return (
    <>
      <FormControl size={size} sx={{ width: 170, flexShrink: 0 }} variant={variant}>
        <InputLabel sx={{ fontSize: TYPOGRAPHY.body.size }}>{isServerChanging ? t('Switching...') : t(label)}</InputLabel>
        <Select
          value={selectedServer}
          label={isServerChanging ? t('Switching...') : t(label)}
          onChange={(e) => handleChange(e.target.value)}
          disabled={isServerChanging}
          renderValue={renderSelectedServer}
          IconComponent={isServerChanging ? SwitchingIcon : ArrowDropDownIcon}
          sx={{
            opacity: isServerChanging ? 0.7 : 1,
            '& .MuiSelect-select': {
              display: 'flex',
              alignItems: 'center',
              overflow: 'hidden',
              whiteSpace: 'nowrap',
              textOverflow: 'ellipsis',
              fontSize: TYPOGRAPHY.body.size,
              py: 0.5,
            }
          }}
        >
          {/* TASK-113 PR-C + BUG-0577: the "All servers" row. Sits at the top,
              visually distinct (globe + bold). Shown only when 2+ configured
              servers exist — a single-server deployment has no second
              server to federate with, so the row collapses to "the only
              thing there is" and would only waste a click. `=1` also covers
              the empty case (the loop below falls back to a 0-length list,
              so picking the sentinel would render nothing); `<=1` is the
              compact form. */}
          {availableServers.length > 1 && (
            <>
              <MenuItem
                key={ALL_SERVERS_SENTINEL}
                value={ALL_SERVERS_SENTINEL}
                sx={{ fontWeight: 600 }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                  <PublicIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, opacity: 0.85 }} />
                  {t('All servers')}
                </Box>
              </MenuItem>
              <Divider />
            </>
          )}
          {availableServers.map((serverUrl) => {
            const isFailed = failedServers.has(serverUrl);
            const needsAuth = serverAuthStates[serverUrl] === 'needs-auth';
            const displayName = labelFor(serverUrl);

            return (
              <MenuItem
                key={serverUrl}
                value={serverUrl}
                disabled={isFailed}
                sx={{
                  color: isFailed ? P.error : 'inherit',
                  '&.Mui-disabled': {
                    opacity: 1,
                    color: P.error
                  }
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                  {displayName}
                  {isFailed && (
                    <Chip
                      label={t('Offline')}
                      size="small"
                      color="error"
                      sx={{ height: 20, fontSize: TYPOGRAPHY.caption.size }}
                    />
                  )}
                  {!isFailed && needsAuth && (
                    <LockIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, opacity: 0.7 }} />
                  )}
                </Box>
              </MenuItem>
            );
          })}
        </Select>
      </FormControl>

      {authDialog}
    </>
  );
};
