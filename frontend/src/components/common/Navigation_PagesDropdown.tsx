import { Add, KeyboardArrowDown } from '@mui/icons-material';
import { Box, Button, Divider, Menu, MenuItem, Typography } from '@mui/material';
import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { usePermissions } from '../../hooks/auth/usePermissions';
import { useCustomPages } from '../../hooks/customPages/useCustomPages';
import { useI18n } from '../../i18n/useI18n';
import { navItemSx, NavLabel } from './Navigation_ItemStyle';

/**
 * The "Pages" menu of the top bar (TASK-139): the user's saved custom pages, the pages shared with them,
 * and a way to make a new one. Hidden when the user holds no page and may not create one.
 */
const NavigationPagesDropdown: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();
  const { data } = useCustomPages();
  const [anchor, setAnchor] = useState<null | HTMLElement>(null);
  const canCreate = hasPermission('pages.custom:edit');
  const saved = (data ?? []).filter((p) => p.status === 'saved');
  const mine = saved.filter((p) => p.access === 'owner');
  const shared = saved.filter((p) => p.access !== 'owner');
  if (!hasPermission('pages.custom:view') || (saved.length === 0 && !canCreate)) return null;

  const close = () => setAnchor(null);
  const label = (text: string) => (
    <Typography sx={{ px: 2, pt: 1, pb: 0.25, color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
      {text}
    </Typography>
  );
  const item = (p: { id: string; title: string }) => (
    <MenuItem key={p.id} component={Link} to={`/pages/${p.id}`} onClick={close} selected={location.pathname === `/pages/${p.id}`} sx={{ py: 1, px: 2 }}>
      <Typography variant="body2" noWrap>
        {p.title}
      </Typography>
    </MenuItem>
  );

  return (
    <>
      <Button onClick={(e) => setAnchor(e.currentTarget)} endIcon={<KeyboardArrowDown />} sx={navItemSx(location.pathname.startsWith('/pages'))}>
        <NavLabel text={t('Pages')} />
      </Button>
      <Menu
        anchorEl={anchor}
        open={Boolean(anchor)}
        onClose={close}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        PaperProps={{ sx: { mt: 1, minWidth: 240, maxHeight: '70vh' } }}
      >
        {mine.length > 0 && label(t('My pages'))}
        {mine.map(item)}
        {shared.length > 0 && label(t('Shared with me'))}
        {shared.map(item)}
        {saved.length > 0 && <Divider sx={{ my: 0.5 }} />}
        <MenuItem component={Link} to="/pages" onClick={close} sx={{ py: 1, px: 2 }}>
          <Typography variant="body2">{t('All pages')}</Typography>
        </MenuItem>
        {canCreate && (
          <MenuItem
            onClick={() => {
              close();
              navigate('/pages');
            }}
            sx={{ py: 1, px: 2, color: P.accentText }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Add fontSize="small" />
              <Typography variant="body2">{t('New page')}</Typography>
            </Box>
          </MenuItem>
        )}
      </Menu>
    </>
  );
};

export default NavigationPagesDropdown;
