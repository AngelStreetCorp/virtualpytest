import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import App from './App.tsx';
import { CustomThemeProvider } from './contexts/ThemeContext';
import { installFetchAuth } from './utils/installFetchAuth';
import './index.css';

// Attach the Supabase JWT (and auto-sign token) to all /server/* fetch calls,
// covering both apiClient and raw fetch(). Must run before any request fires.
installFetchAuth();

// Create a QueryClient instance for React Query
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5 * 60 * 1000, // 5 minutes
    },
  },
});

// A deploy renames every lazy chunk and swaps dist, so a tab that was open across it
// asks for a file that no longer exists on its next navigation. Vite's preload helper
// wraps every dynamic import and raises this event before the failure reaches React —
// so it fires whether or not an error boundary sits above the route. Reload onto the
// current bundle. The 30s guard stops a chunk that is missing for good (a broken
// deploy) from looping, while a tab left open across several deploys recovers each time.
window.addEventListener('vite:preloadError', (event) => {
  const lastReloadAt = Number(sessionStorage.getItem('vpt:chunk-reload-at')) || 0;
  if (Date.now() - lastReloadAt < 30_000) return; // let the error surface
  event.preventDefault();
  sessionStorage.setItem('vpt:chunk-reload-at', String(Date.now()));
  window.location.reload();
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}>
    <CustomThemeProvider>
      <App />
    </CustomThemeProvider>
  </QueryClientProvider>,
);
