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

// Auto-reload on chunk loading failure (fixes deployment 404s)
window.addEventListener('error', (event) => {
  if (event.message?.includes('Failed to fetch dynamically imported module')) {
    const hasReloaded = sessionStorage.getItem('chunk-load-reload');
    if (!hasReloaded) {
      sessionStorage.setItem('chunk-load-reload', 'true');
      window.location.reload();
    }
  }
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}>
    <CustomThemeProvider>
      <App />
    </CustomThemeProvider>
  </QueryClientProvider>,
);
