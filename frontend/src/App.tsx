import {
  Science,
} from '@mui/icons-material';
import {
  Container,
  AppBar,
  Toolbar,
  Typography,
  Box,
  CircularProgress,
} from '@mui/material';
import React, { Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';

// Import navigation components (keep these as regular imports since they're always needed)
import Footer from './components/common/Footer';
import NavigationBar from './components/common/Navigation_Bar';
import { ServerSelector } from './components/common/ServerSelector';
import ThemeToggle from './components/common/ThemeToggle';

import { HostManagerProvider } from './contexts/HostManagerProvider';
import { RunExecutionsProvider } from './contexts/RunExecutionsContext';
import { ServerManagerProvider } from './contexts/ServerManagerProvider';
import { ToastProvider } from './contexts/ToastContext';
import { BuilderProvider } from './contexts/builder/BuilderContext';

// Auth components and providers
import { AuthProvider } from './contexts/auth/AuthContext';
import { PermissionProvider } from './contexts/auth/PermissionContext';
import { LoginPage, ProtectedRoute, AuthCallback } from './components/auth';
import { UserMenu } from './components/auth/UserMenu';
import { useAuth } from './hooks/auth/useAuth';
import { useResponsiveMode } from './hooks/useResponsiveMode';
import { isAuthEnabled } from './lib/supabase';
import { BrandingProvider, useBranding } from './contexts/BrandingContext';
import MobileRunNavTabs from './components/mobile/MobileTopBar';
import MobileBottomNav from './components/mobile/MobileBottomNav';
import { RouteErrorBoundary } from './components/common/RouteErrorBoundary';
import { featureRoutes, matchesFeatureRoute } from './config/features';

// Lazy load all pages for better performance and to avoid loading everything at once
const Dashboard = React.lazy(() => import('./pages/Dashboard'));
const Rec = React.lazy(() => import('./pages/Rec'));
const Documentation = React.lazy(() => import('./pages/Documentation'));
const CampaignEditor = React.lazy(() => import('./pages/CampaignEditor'));
const Requirements = React.lazy(() => import('./pages/Requirements'));
const Coverage = React.lazy(() => import('./pages/Coverage'));
const Models = React.lazy(() => import('./pages/Models'));
const GrafanaDashboard = React.lazy(() => import('./pages/GrafanaDashboard'));
const LangfuseDashboard = React.lazy(() => import('./pages/LangfuseDashboard'));
import RunTests from './pages/RunTests';
const MonitorTests = React.lazy(() => import('./pages/MonitorTests'));
const BuildCampaigns = React.lazy(() => import('./pages/BuildCampaigns'));
const CampaignBuilder = React.lazy(() => import('./pages/CampaignBuilder'));
const TestReports = React.lazy(() => import('./pages/TestReports'));
const ModelReports = React.lazy(() => import('./pages/ModelReports'));
const DependencyReport = React.lazy(() => import('./pages/DependencyReport'));
const MonitoringIncidents = React.lazy(() => import('./pages/MonitoringIncidents'));
const Heatmap = React.lazy(() => import('./pages/Heatmap'));
const UserInterface = React.lazy(() => import('./pages/UserInterface'));
const UserInterfaceReferences = React.lazy(() => import('./pages/UserInterfaceReferences'));
const TestCaseEditor = React.lazy(() => import('./pages/TestCaseEditor'));
const TestCaseBuilder = React.lazy(() => import('./pages/TestCaseBuilder'));
const NavigationEditor = React.lazy(() => import('./pages/NavigationEditor'));
const RemoteTestPage = React.lazy(() => import('./pages/RemoteTestPage'));
const AIQueueMonitor = React.lazy(() => import('./pages/AIQueueMonitor'));
const HLSDebugPage = React.lazy(() => import('./pages/HLSDebugPage'));
const OpenRouterDebug = React.lazy(() => import('./pages/OpenRouterDebug'));
const FullscreenPlayer = React.lazy(() => import('./pages/FullscreenPlayer'));
const Settings = React.lazy(() => import('./pages/Settings'));
const CodeDeployment = React.lazy(() => import('./pages/CodeDeployment'));
const RunCommand = React.lazy(() => import('./pages/RunCommand'));

const GrafanaRedirect = React.lazy(() => import('./pages/GrafanaRedirect'));
const ApiDocumentation = React.lazy(() => import('./pages/ApiDocumentation'));
const SecurityReports = React.lazy(() => import('./pages/SecurityReports'));
const UserApiWorkspaces = React.lazy(() => import('./pages/UserApiWorkspaces'));
const UserApiWorkspaceDetail = React.lazy(() => import('./pages/UserApiWorkspaceDetail'));
const JiraIntegration = React.lazy(() => import('./pages/JiraIntegration'));
const Teams = React.lazy(() => import('./pages/Teams'));
const Users = React.lazy(() => import('./pages/Users'));
const Workspaces = React.lazy(() => import('./pages/Workspaces'));
const DeviceInfoOverrides = React.lazy(() => import('./pages/DeviceInfoOverrides'));
const AgentChat = React.lazy(() => import('./pages/AgentChat'));
const AgentDashboard = React.lazy(() => import('./pages/AgentDashboard'));
const Status = React.lazy(() => import('./pages/Status'));

const isRunTestsPath = (pathname: string) =>
  pathname.startsWith('/run/tests') ||
  pathname.startsWith('/test-execution/run-tests');

const isBuildCampaignPath = (pathname: string) =>
  pathname.startsWith('/run/build') ||
  pathname.startsWith('/test-execution/build-campaign');

const isMonitorTestsPath = (pathname: string) =>
  pathname.startsWith('/run/monitor') ||
  pathname.startsWith('/run/schedule-run') ||
  pathname.startsWith('/run/deployments') ||
  pathname.startsWith('/test-execution/monitor-tests') ||
  pathname.startsWith('/test-execution/schedule-run') ||
  pathname.startsWith('/test-execution/deployments');

const runViewSx = (visible: boolean) => ({
  display: visible ? 'block' : 'none',
  width: '100%',
});

const RunExecutionShell: React.FC = () => {
  const { pathname } = useLocation();
  const { isMobile } = useResponsiveMode();

  const showRunTests = isRunTestsPath(pathname);
  const showBuildCampaigns = isBuildCampaignPath(pathname);
  const showMonitorTests = isMonitorTestsPath(pathname);

  return (
    <RunExecutionsProvider>
      <Box sx={{ width: '100%' }}>
        {isMobile ? <MobileRunNavTabs /> : null}
        <Box sx={runViewSx(showRunTests)} hidden={!showRunTests}>
          {/* One Run Tests page at every width. The simplified mobile page was built on the
              assumption that this one could not work on a phone; it can — the only thing that
              actually broke below ~600px was the Selected Items parameter row, which laid its
              fixed-width controls out with `nowrap` and overlapped the target chip. That row
              wraps now, and a narrow viewport keeps the full page: targets, campaigns, Start/
              Repeat scheduling, Last Executions with Report/Logs/rerun — none of which the
              simplified page had. */}
          <RunTests />
        </Box>
        <Box sx={runViewSx(showBuildCampaigns)} hidden={!showBuildCampaigns}>
          <BuildCampaigns />
        </Box>
        <Box sx={runViewSx(showMonitorTests)} hidden={!showMonitorTests}>
          <MonitorTests />
        </Box>
      </Box>
    </RunExecutionsProvider>
  );
};

// 404 Not Found component
const NotFound: React.FC = () => {
  const { branding } = useBranding();

  // Set document title for 404 pages
  React.useEffect(() => {
    document.title = `404 - Page Not Found | ${branding.name}`;

    // Set HTTP status to 404 if running on server
    if (typeof window !== 'undefined' && window.history) {
      // This helps with SEO and proper status codes
      const meta = document.createElement('meta');
      meta.name = 'robots';
      meta.content = 'noindex';
      document.head.appendChild(meta);

      return () => {
        document.head.removeChild(meta);
      };
    }
  }, [branding.name]);

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '60vh',
        textAlign: 'center',
        gap: 3,
      }}
    >
      <Typography
        variant="h1"
        component="h1"
        sx={{ fontSize: '6rem', fontWeight: 'bold', color: 'error.main' }}
      >
        404
      </Typography>
      <Typography variant="h4" component="h2" gutterBottom>
        Page Not Found
      </Typography>
      <Typography variant="body1" color="textSecondary" sx={{ maxWidth: '500px', mb: 3 }}>
        The page you are looking for doesn't exist or has been moved.
      </Typography>
      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', justifyContent: 'center' }}>
        <Typography
          component="a"
          href="/"
          sx={{
            textDecoration: 'none',
            color: 'primary.main',
            '&:hover': { textDecoration: 'underline' },
          }}
        >
          ← Back to Dashboard
        </Typography>
      </Box>
    </Box>
  );
};

// Loading component for Suspense fallback
const LoadingSpinner: React.FC = () => (
  <Box
    sx={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '200px',
      flexDirection: 'column',
      gap: 2,
    }}
  >
    <CircularProgress />
    <Typography variant="body2" color="textSecondary">
      Loading...
    </Typography>
  </Box>
);

// Conditional Container wrapper based on route
const ConditionalContainer: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  const { isMobile, isTablet } = useResponsiveMode();
  const isFullWidth =
    FULL_WIDTH_ROUTES.includes(location.pathname) || matchesFeatureRoute(location.pathname, 'fullWidth');

  if (isFullWidth) {
    // Full width layout for chat-like pages
    return (
      <Box
        sx={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {children}
      </Box>
    );
  }

  if (isMobile) {
    return (
      <Box
        sx={{
          mt: 1,
          mb: 1,
          px: 1,
          // MobileBottomNav is a fixed-position sibling (not part of this scroll flow), so its
          // real footprint has to be reserved here explicitly: MUI's BottomNavigation is a fixed
          // 56px (see @mui/material/BottomNavigation) plus the Paper's 1px top border, rounded up
          // to 64px for a little breathing room, plus the iOS home-indicator safe area on notched
          // phones — a flat spacing unit (previously `pb: 9` / 72px) doesn't account for that inset
          // and let the last card clip behind the nav bar on notched devices.
          pb: 'calc(64px + env(safe-area-inset-bottom, 0px))',
          // `flex: 1` + `minHeight: 0` capped this box at the viewport height, and a page
          // taller than that simply overflowed it (overflow is visible): the 64px reserved
          // above was then *inside* the capped box, above the escaping content instead of
          // below it, so the reservation vanished exactly when it was needed and the last
          // ~56px of every long mobile page sat under the fixed nav — measured on an S21:
          // container 763px tall holding 819px of content, scroll ending 88px past the
          // viewport with the nav covering the last 56. `1 0 auto` keeps the fill-the-screen
          // behaviour for short pages (grow) while letting a long one size to its content
          // (basis auto, no shrink), so the scroll container scrolls past the padding.
          flex: '1 0 auto',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'stretch',
        }}
      >
        {children}
      </Box>
    );
  }

  // Standard container layout for other pages
  return (
    <Container
      maxWidth={isTablet ? 'xl' : 'lg'}
      sx={{
        mt: 2,
        mb: 2,
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'stretch',
      }}
    >
      {children}
    </Container>
  );
};

// Routes that should use full width without Container constraints
const FULL_WIDTH_ROUTES = ['/ai-agent', '/docs/api', '/fullscreen-player'];

// AGENTS: When adding or removing a route, also update:
//   1. tests/e2e/playwright/specs/ui.pages.spec.js  — PAGES array (screenshot + error test per route)
//   2. docs/agent/validation/TESTING.md                        — Route inventory table (name, path, description)

// Header component that checks auth state
const AppHeader: React.FC = () => {
  const location = useLocation();
  const { isAuthenticated, isLoading } = useAuth();
  const { branding } = useBranding();
  const { isMobile } = useResponsiveMode();

  // Fully bare pages render their own chrome (e.g. dedicated fullscreen player tab) —
  // no AppHeader at all, so the fixed full-viewport video isn't shoved below the AppBar.
  if (location.pathname === '/fullscreen-player') {
    return null;
  }

  // Hide header on login and callback pages
  const isAuthPage = location.pathname === '/login' || location.pathname === '/auth/callback';

  // Show header if: auth disabled OR user authenticated OR not on auth pages
  const shouldShowHeader = !isAuthEnabled || (isAuthenticated && !isAuthPage);

  if (isAuthPage || isLoading) {
    // Minimal header for login page
    return (
      <AppBar position="static" elevation={1} sx={{ overflow: 'hidden' }}>
        <Toolbar>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexGrow: 1 }}>
            {branding.logoUrl ? (
              <Box
                component="img"
                src={branding.logoUrl}
                alt={`${branding.name} logo`}
                sx={{ height: 24, width: 'auto', maxWidth: 140, objectFit: 'contain' }}
              />
            ) : null}
            <Typography variant="h6" component="div">
              {branding.name}
            </Typography>
          </Box>
          <ThemeToggle />
        </Toolbar>
      </AppBar>
    );
  }

  if (!shouldShowHeader) {
    return null;
  }

  // Mobile: no top app bar — the bottom nav already provides navigation
  // context, so the fixed header (logo + theme toggle) added no value and
  // its overlay was clipping the top of in-page headings.
  if (isMobile) {
    return null;
  }

  // Full header with navigation
  return (
    <AppBar position="static" elevation={1} sx={{ overflow: 'hidden' }}>
      <Toolbar sx={{ overflow: 'hidden' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
          {branding.logoUrl ? (
            <Box
              component="img"
              src={branding.logoUrl}
              alt={`${branding.name} logo`}
              sx={{ height: 28, width: 'auto', maxWidth: 140, objectFit: 'contain', mr: 1 }}
            />
          ) : (
            <Science sx={{ mr: 1 }} />
          )}
          <Typography variant="h6" component="div" sx={{ mr: 1 }}>
            {branding.name}
          </Typography>
          <ServerSelector size="small" minWidth={140} />
          <Box sx={{ ml: 1 }}>
            <WorkspaceSwitcher size="small" minWidth={140} />
          </Box>
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', minWidth: 0, flex: 1, ml: 2, mr: 2 }}>
          <NavigationBar />
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
          <UserMenu />
        </Box>
      </Toolbar>
    </AppBar>
  );
};

const BrandingTitle: React.FC = () => {
  const { branding } = useBranding();

  React.useEffect(() => {
    if (document.title === 'Web Interface' || document.title === 'VirtualPyTest Web Interface') {
      document.title = branding.title;
    }
  }, [branding.title]);

  return null;
};

const ResponsiveFooter: React.FC = () => {
  const location = useLocation();
  const { isMobile } = useResponsiveMode();
  const isAuthPage = location.pathname === '/login' || location.pathname === '/auth/callback';
  const isApiDocsPage = location.pathname === '/docs/api';

  if (isMobile || isAuthPage || isApiDocsPage) {
    return null;
  }

  return <Footer />;
};

import { WorkspaceProvider } from './contexts/workspace/WorkspaceContext';
import WorkspaceSwitcher from './components/common/WorkspaceSwitcher';
import { AIProvider } from './contexts/AIContext';
import { AgentChatProvider } from './contexts/AgentChatContext';
import { AgentActivityProvider } from './contexts/AgentActivityContext';
import { SocketProvider } from './contexts/SocketContext';
import { AIOmniOverlay } from './components/ai/AIOmniOverlay';
import { GlobalAgentBadges } from './components/agent/GlobalAgentBadges';
import { AgentActivityBridge } from './components/agent/AgentActivityBridge';
import { useAIOrchestrator } from './hooks/ai/useAIOrchestrator';

// Orchestrator Wrapper Component
const AIOrchestratorWrapper: React.FC = () => {
  useAIOrchestrator();
  return null;
};

const App: React.FC = () => {
  // Mobile hides its scrollbar entirely (index.css) — no gutter needed to reserve
  // space for it, so 'stable' (which leaves a blank strip even with the thumb/track
  // hidden) is only worth it on desktop, where the scrollbar is still visible.
  const { isMobile } = useResponsiveMode();

  // Detect if app is running under a proxy path (e.g., /pi4/)
  // Check if current path starts with /piX/ pattern
  const getBasename = () => {
    const path = window.location.pathname;
    const proxyMatch = path.match(/^\/(pi\d+|mac)\//);
    return proxyMatch ? proxyMatch[0].slice(0, -1) : '';  // Return /pi4 (without trailing slash)
  };
  
  // react-router v7 made v7_startTransition and v7_relativeSplatPath the default behaviour
  // and removed the `future` prop, so passing it is now a type error. Nothing in CI caught
  // this on the v6 -> v7 bump (#26): `build` is `vite build`, which strips types without
  // checking them; `lint` is eslint; the component tests mock the router; and the E2E jobs
  // run against the deployed app rather than the built PR. Found by running tsc by hand.
  return (
        <Router basename={getBasename()}>
      <BrandingProvider>
        <AuthProvider>
          <PermissionProvider>
            <WorkspaceProvider>
            <ToastProvider>
              <BuilderProvider>
                <ServerManagerProvider>
                  <HostManagerProvider>
                    <SocketProvider>
                      <AgentChatProvider>
                      <AIProvider>
                        <AgentActivityProvider>
                    <AIOrchestratorWrapper />
                    <BrandingTitle />
                    <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                      <AppHeader />

                      <AIOmniOverlay />
                      <GlobalAgentBadges />
                      <AgentActivityBridge />

                      <Box sx={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', scrollbarGutter: isMobile ? 'auto' : 'stable', display: 'flex', flexDirection: 'column' }}>
                      <ConditionalContainer>
                        <RouteErrorBoundary>
                        <Suspense fallback={<LoadingSpinner />}>
                <Routes>
                  {/* Public Routes - Only login and OAuth callback */}
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/auth/callback" element={<AuthCallback />} />

                  {/* Dedicated fullscreen "watch in best quality" player (opens in its own tab).
                      Public + bare (no app chrome) — see AppHeader bare-page hide below. */}
                  <Route path="/fullscreen-player" element={<FullscreenPlayer />} />

                  {/* All other routes require authentication */}
                  <Route element={<ProtectedRoute />}>
                    <Route path="/" element={<Dashboard />} />

                  {/* Device Control Page */}
                  <Route path="/device-control" element={<Rec />} />
                  <Route path="/device-info" element={<DeviceInfoOverrides />} />

                  {/* AI Agent - Chat-based QA automation */}
                  <Route path="/ai-agent" element={<AgentChat />} />
                  
                  {/* Agent Dashboard - Multi-agent control panel */}
                  <Route path="/agent-dashboard" element={<AgentDashboard />} />

                  {/* Builder Routes */}
                  <Route path="/builder/test-builder" element={<TestCaseBuilder />} />
                  <Route path="/builder/campaign-builder" element={<CampaignBuilder />} />

                  {/* Test Plan Routes */}
                  <Route path="/test-plan/test-cases" element={<TestCaseEditor />} />
                  <Route path="/test-plan/testcase-builder" element={<TestCaseBuilder />} /> {/* Legacy redirect */}
                  <Route path="/test-plan/campaigns" element={<CampaignEditor />} />
                  <Route path="/test-plan/requirements" element={<Requirements />} />
                  <Route path="/test-plan/coverage" element={<Coverage />} />

                  {/* Test Execution Routes */}
                  <Route path="/run" element={<Navigate to="/run/tests" replace />} />
                  <Route path="/run/tests" element={<RunExecutionShell />} />
                  <Route path="/run/build" element={<RunExecutionShell />} />
                  <Route path="/run/monitor" element={<RunExecutionShell />} />
                  <Route path="/run/schedule-run" element={<RunExecutionShell />} />
                  <Route path="/run/deployments" element={<RunExecutionShell />} />
                  <Route path="/test-execution/run-tests" element={<RunExecutionShell />} />
                  <Route path="/test-execution/build-campaign" element={<RunExecutionShell />} />
                  <Route path="/campaign-builder" element={<CampaignBuilder />} /> {/* Legacy redirect */}
                  <Route path="/test-execution/monitor-tests" element={<RunExecutionShell />} />
                  <Route path="/test-execution/schedule-run" element={<RunExecutionShell />} />
                  <Route path="/test-execution/deployments" element={<RunExecutionShell />} />

                  {/* Monitoring Routes */}
                  <Route path="/monitoring/system" element={<GrafanaDashboard />} />
                  <Route path="/monitoring/incidents" element={<MonitoringIncidents />} />
                  <Route path="/monitoring/heatmap" element={<Heatmap />} />
                  <Route path="/monitoring/ai-queue" element={<AIQueueMonitor />} />

                  {/* Test Results Routes */}
                  <Route path="/test-results/reports" element={<TestReports />} />
                  <Route path="/test-results/model-reports" element={<ModelReports />} />
                  <Route path="/test-results/dependency-report" element={<DependencyReport />} />

                  {/* System Status Page */}
                  <Route path="/status" element={<Status />} />

                  {/* Grafana Dashboard Route */}
                  <Route path="/grafana-dashboard" element={<GrafanaDashboard />} />
                  
                  {/* Langfuse LLM Observability Dashboard */}
                  <Route path="/langfuse-dashboard" element={<LangfuseDashboard />} />
                  
                  {/* Grafana Direct Access - Redirects to VITE_GRAFANA_URL */}
                  <Route path="/grafana/*" element={<GrafanaRedirect />} />

                  {/* User API Testing Routes - Protected by permission */}
                  <Route element={<ProtectedRoute requiredPermission="plugins.postman:view" />}>
                    <Route path="/api/workspaces" element={<UserApiWorkspaces />} />
                    <Route path="/api/workspace/:workspaceId" element={<UserApiWorkspaceDetail />} />
                  </Route>
                  
                  {/* Documentation Routes */}
                  <Route path="/docs/api" element={<ApiDocumentation />} />
                  <Route path="/docs/security" element={<SecurityReports />} />
                  <Route path="/docs/:section/:subsection/:category/:page" element={<Documentation />} />
                  <Route path="/docs/:section/:subsection/:page" element={<Documentation />} />
                  <Route path="/docs/:section/:page" element={<Documentation />} />
                  <Route path="/docs/:section" element={<Documentation />} />

                  {/* Integrations Routes - Protected by permission */}
                  <Route element={<ProtectedRoute requiredPermission="plugins.jira:view" />}>
                    <Route path="/integrations/jira" element={<JiraIntegration />} />
                  </Route>

                  {/* Teams, Users & Workspaces Management - Admin only */}
                  <Route element={<ProtectedRoute requiredRole="admin" />}>
                    <Route path="/teams" element={<Teams />} />
                    <Route path="/users" element={<Users />} />
                    <Route path="/workspaces" element={<Workspaces />} />
                  </Route>

                  {/* Configuration Routes */}
                  <Route
                    path="/configuration"
                    element={<Navigate to="/configuration/models" replace />}
                  />
                  <Route
                    path="/configuration/"
                    element={<Navigate to="/configuration/models" replace />}
                  />
                  
                  {/* Admin-only configuration routes */}
                  <Route element={<ProtectedRoute requiredRole="admin" />}>
                    <Route path="/configuration/models" element={<Models />} />
                    <Route path="/configuration/settings" element={<Settings />} />
                    <Route path="/configuration/code-deployment" element={<CodeDeployment />} />
                    <Route path="/configuration/run-command" element={<RunCommand />} />
                  </Route>

                  {/* Regular configuration routes */}
                  <Route path="/configuration/interface" element={<UserInterface />} />
                  <Route
                    path="/configuration/interface/:name/references"
                    element={<UserInterfaceReferences />}
                  />
                  <Route path="/configuration/openrouter" element={<OpenRouterDebug />} />
                  {/* CI/CD Reports moved into the optional `cicd` feature
                      (Test -> Report). Keep the old Settings path working for
                      bookmarks; with the feature disabled the target 404s like any
                      other absent page. */}
                  <Route
                    path="/configuration/cicd-reports"
                    element={<Navigate to="/test-results/cicd-reports" replace />}
                  />

                  {/* Navigation Editor Route */}
                  <Route
                    path="/navigation-editor/:treeName/:treeId"
                    element={<NavigationEditor />}
                  />
                  <Route path="/navigation-editor/:treeName" element={<NavigationEditor />} />

                  {/* Remote Testing Route */}
                  <Route path="/remote-test" element={<RemoteTestPage />} />

                  {/* Debug Routes */}
                  <Route path="/debug/hls" element={<HLSDebugPage />} />

                  {/* Optional features (features/<name>/frontend/routes.tsx, docs/technical/FEATURES.md) */}
                  {featureRoutes().map((r) => (
                    <Route key={r.path} path={r.path} element={r.element} />
                  ))}

                    {/* Catch-all route for 404 */}
                    <Route path="*" element={<NotFound />} />
                  </Route>
                </Routes>
              </Suspense>
                        </RouteErrorBoundary>
            </ConditionalContainer>

            <ResponsiveFooter />
            </Box>
            <MobileBottomNav />
            </Box>
                      </AgentActivityProvider>
                    </AIProvider>
                      </AgentChatProvider>
                  </SocketProvider>
                </HostManagerProvider>
              </ServerManagerProvider>
            </BuilderProvider>
          </ToastProvider>
            </WorkspaceProvider>
        </PermissionProvider>
      </AuthProvider>
      </BrandingProvider>
    </Router>
  );
};

export default App;
