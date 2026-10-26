import React, { useState } from 'react';
import { Badge, Box, Button, IconButton, Popover, Tooltip, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';

import { TYPOGRAPHY } from '../../constants/typography';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon } from '../../constants/icons';
import { isResolved, notificationStore, sortForBell, useNotifications, type NotificationItem } from '../../contexts/notificationStore';
import { useNotificationHistory } from '../../hooks/useNotificationHistory';
import { useNotificationPrefs } from '../../hooks/useNotificationPrefs';
import { useI18n } from '../../i18n/useI18n';
import { formatAgo } from '../dashboard/dashboardFormat';
import { neutralButtonSx } from '../common/PageChrome';

/** Top-bar bell: unread count and the account's last 200 platform notifications (cached per browser).
 *  TASK-100: live rows on top, resolved rows underneath (muted, ✓, "Fixed X ago"), dismissed items hidden. */
export const NotificationBell: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const navigate = useNavigate();
  const items = useNotifications();
  useNotificationHistory(); // merges the account's server history into the local cache
  useNotificationPrefs(); // loads the viewer's preferences once for the whole app
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const visible = sortForBell(items);
  // Unread = live and not read; resolved items auto-mark themselves read on resolve and would otherwise flood the badge.
  const unread = items.filter((n) => !isResolved(n) && !n.read).length;

  const open = (n: NotificationItem) => {
    notificationStore.markRead(n.id);
    if (n.to) {
      setAnchor(null);
      navigate(n.to);
    }
  };

  // A monitoring problem opens the Masterchief chat with the alert as the first message.
  const askMasterchief = (n: NotificationItem) => {
    notificationStore.markRead(n.id);
    setAnchor(null);
    navigate(`/ai-agent?agent=masterchief&prompt=${encodeURIComponent(n.message + '. Diagnose it read-only and propose the fix.')}`);
  };

  return (
    <>
      <Tooltip title={t('Notifications')}>
        <IconButton size="small" aria-label={t('Notifications')} onClick={(e) => setAnchor(e.currentTarget)} sx={{ color: 'inherit' }}>
          <Badge badgeContent={unread} max={9} color="error" invisible={unread === 0}>
            <AppIcon name="bell" size="md" color="inherit" />
          </Badge>
        </IconButton>
      </Tooltip>
      <Popover
        open={Boolean(anchor)}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { sx: { width: 380, maxWidth: '94vw', bgcolor: P.surfaceSolid, color: P.textPrimary, border: `1px solid ${P.borderColor}`, backgroundImage: 'none' } } }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1.5, borderBottom: `1px solid ${P.borderColor}` }}>
          <Typography sx={{ flex: 1, fontWeight: 600 }}>{t('Notifications')}</Typography>
          <Button size="small" variant="outlined" disabled={unread === 0} onClick={notificationStore.markAllRead} sx={neutralButtonSx(P)}>
            {t('Mark all read')}
          </Button>
          <Button size="small" variant="outlined" disabled={visible.length === 0} onClick={notificationStore.clear} sx={neutralButtonSx(P)}>
            {t('Clear')}
          </Button>
        </Box>
        {visible.length === 0 ? (
          <Typography sx={{ p: 3, textAlign: 'center', color: P.textMuted }}>{t('No notifications')}</Typography>
        ) : (
          <Box sx={{ maxHeight: 420, overflowY: 'auto' }}>
            {visible.map((n) => {
              const resolved = isResolved(n);
              const titleColor = resolved ? P.textMuted : P.textPrimary;
              return (
                <Box
                  key={n.id}
                  data-testid={resolved ? 'notif-fixed' : 'notif-live'}
                  sx={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 1,
                    px: 1.5,
                    py: 1,
                    borderBottom: `1px solid ${P.borderColor}`,
                    opacity: resolved ? 0.7 : 1,
                    '&:hover': { bgcolor: P.hoverBg },
                  }}
                >
                  <Box sx={{ pt: 0.25 }}>
                    <AppIcon name={resolved ? 'success' : n.severity} />
                  </Box>
                  <Box
                    role={n.to ? 'link' : undefined}
                    tabIndex={0}
                    onClick={() => open(n)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        open(n);
                      }
                    }}
                    sx={{ flex: 1, minWidth: 0, cursor: n.to ? 'pointer' : 'default', '&:focus-visible': { outline: `2px solid ${P.accentText}` } }}
                  >
                    <Typography sx={{ fontWeight: n.read ? 400 : 600, color: titleColor, wordBreak: 'break-word' }}>{n.message}</Typography>
                    <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>
                      {resolved
                        ? t('Fixed {ago} ago', { ago: formatAgo(new Date(n.resolved_at as number).toISOString(), Date.now(), t) })
                        : t('{ago} ago', { ago: formatAgo(new Date(n.ts).toISOString(), Date.now(), t) })}
                    </Typography>
                  </Box>
                  {!resolved && n.id.startsWith('dash-monitoring:') && (
                    <Button size="small" variant="outlined" onClick={() => askMasterchief(n)} sx={neutralButtonSx(P)}>
                      {t('Ask masterchief')}
                    </Button>
                  )}
                  <Tooltip title={t('Dismiss')}>
                    <IconButton size="small" aria-label={t('Dismiss')} onClick={() => notificationStore.dismiss(n.id)} sx={{ color: P.textMuted }}>
                      <AppIcon name="close" />
                    </IconButton>
                  </Tooltip>
                </Box>
              );
            })}
          </Box>
        )}
        <Box sx={{ p: 1, borderTop: `1px solid ${P.borderColor}`, textAlign: 'center' }}>
          <Button
            size="small"
            variant="outlined"
            onClick={() => {
              setAnchor(null);
              navigate('/notifications');
            }}
            sx={neutralButtonSx(P)}
          >
            {t('View all')}
          </Button>
        </Box>
      </Popover>
    </>
  );
};

export default NotificationBell;
