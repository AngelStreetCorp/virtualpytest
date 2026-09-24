import { Box, Typography, Paper, Link } from '@mui/material';
import GitHubIcon from '@mui/icons-material/GitHub';
import PhoneAndroidIcon from '@mui/icons-material/PhoneAndroid';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { isFeatureEnabled } from '../../config/features';
import { useBranding } from '../../contexts/BrandingContext';
import { useIsNativeApp } from '../../hooks/useIsNativeApp';

const GITHUB_REPO_URL = 'https://github.com/AngelStreetCorp/virtualpytest';
// features/mobile-app: the "Get the app" card (APK link + config QR) lives on this page.
// The link is pointless inside the app itself, hence the native check.
const MOBILE_APP_PAGE = '/configuration/mobile-app';

const Footer: React.FC = () => {
  const { branding } = useBranding();
  const isNative = useIsNativeApp();
  const year = new Date().getFullYear();
  const embeddedVersion = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'unknown';
  const [appVersion, setAppVersion] = React.useState(embeddedVersion);

  React.useEffect(() => {
    if (embeddedVersion && embeddedVersion !== 'unknown') {
      setAppVersion(embeddedVersion);
      return;
    }

    let cancelled = false;

    const loadVersion = async () => {
      try {
        const response = await fetch('/version.txt', {
          cache: 'no-store',
          headers: { 'Cache-Control': 'no-cache' },
        });
        if (!response.ok) {
          return;
        }

        const text = await response.text();
        const lines = text.split(/\r?\n/).map((line) => line.trim());
        const currentLine = lines.find((line) => /^current\s*:/i.test(line));
        const nextVersion = currentLine
          ? currentLine.split(':').slice(1).join(':').trim()
          : lines.find((line) => line.length > 0);

        if (!cancelled && nextVersion) {
          setAppVersion(nextVersion);
        }
      } catch {
        // Keep the embedded fallback.
      }
    };

    void loadVersion();

    return () => {
      cancelled = true;
    };
  }, [embeddedVersion]);

  if (!branding.showFooter) {
    return null;
  }

  return (
    <Paper
      component="footer"
      elevation={1}
      sx={{
        mt: 'auto',
        py: 0,
        px: 4,
        backgroundColor: 'background.paper',
        borderTop: 1,
        borderColor: 'divider',
      }}
    >
      <Box display="flex" justifyContent="space-between" alignItems="center" minHeight={16}>
        <Box display="flex" alignItems="center" gap={1}>
          {/* TASK-23 footer-logo follow-up: tenant-specific logo wins over
              the deployment-level logo. The alt text follows the same
              precedence: tenant alt > `${name} logo`. */}
          {(() => {
            const logoUrl = branding.tenantFooterLogoUrl || branding.logoUrl;
            if (!logoUrl) return null;
            const altText = branding.tenantFooterLogoAlt || `${branding.name} logo`;
            return (
              <Box
                component="img"
                src={logoUrl}
                alt={altText}
                sx={{ height: 18, width: 'auto', maxWidth: 120, objectFit: 'contain' }}
              />
            );
          })()}
          <Typography
            variant="body2"
            color="text.secondary"
            sx={branding.tenantFooterTextColor ? { color: branding.tenantFooterTextColor } : undefined}
          >
            © {year} {[branding.showProjectName ? branding.name : '', branding.tagline]
              .filter(Boolean)
              .join(' - ')}
          </Typography>
        </Box>

        <Box display="flex" alignItems="center" gap={2}>
          {isFeatureEnabled('mobile-app') && !isNative && (
            <Link
              component={RouterLink}
              to={MOBILE_APP_PAGE}
              underline="hover"
              color="text.secondary"
              variant="caption"
              sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
            >
              Get the mobile app
              <PhoneAndroidIcon sx={{ fontSize: 14 }} />
            </Link>
          )}
          <Link
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            underline="hover"
            color="text.secondary"
            variant="caption"
            sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
          >
            View on GitHub
            <GitHubIcon sx={{ fontSize: 14 }} />
          </Link>
          {appVersion && (
            <Typography variant="caption" color="text.secondary">
              {appVersion}
            </Typography>
          )}
        </Box>
      </Box>
    </Paper>
  );
};

export default Footer;
