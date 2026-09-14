# Frontend Technical Documentation

**React TypeScript web interface for VirtualPyTest.**

---

## 🎯 **Purpose**

Frontend provides:
- **Web Interface**: User-friendly dashboard for test management
- **Real-Time Updates**: Live test execution monitoring
- **Device Control**: Remote device interaction
- **Campaign Management**: Batch test configuration
- **Monitoring Dashboard**: System health visualization

---

## 🏗️ **Architecture**

```
Frontend (React TypeScript):
├── Components/
│   ├── Dashboard/          # Main dashboard views
│   ├── TestManagement/     # Test case CRUD
│   ├── DeviceControl/      # Device interaction
│   ├── Monitoring/         # Real-time status
│   └── Common/             # Shared components
├── Services/
│   ├── API Client          # Backend communication
│   ├── WebSocket Client    # Real-time updates
│   └── State Management    # React Query
├── Pages/
│   ├── Dashboard           # Main overview
│   ├── Tests               # Test management
│   ├── Campaigns           # Campaign management
│   └── Devices             # Device configuration
└── Utils/
    ├── Helpers             # Utility functions
    ├── Constants           # App constants
    └── Types               # TypeScript types
```

---

## 🔧 **Technology Stack**

### Core Technologies
- **React 18**: Modern React with hooks and concurrent features
- **TypeScript**: Type safety and better developer experience
- **Vite**: Fast build tool and dev server
- **Material-UI v5**: Component library for consistent UI

### State Management
- **React Query**: Server state management and caching
- **React Context**: Local UI state management
- **React Router**: Client-side routing

### Real-Time Communication
- **Socket.IO Client**: WebSocket communication
- **React Query**: Automatic data refetching

---

## 🌐 **API Integration**

### API Client Service
```typescript
class APIClient {
  private baseURL: string;
  private socket: SocketIOClient.Socket;

  constructor() {
    this.baseURL = import.meta.env.VITE_SERVER_URL || 'http://localhost:5109';
    this.socket = io(this.baseURL);
  }

  // Test Management
  async getTestCases(): Promise<TestCase[]> {
    const response = await fetch(`${this.baseURL}/api/testcases`);
    return response.json();
  }

  async createTestCase(testCase: CreateTestCaseRequest): Promise<TestCase> {
    const response = await fetch(`${this.baseURL}/api/testcases`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(testCase)
    });
    return response.json();
  }

  async executeTestCase(id: string, config: ExecutionConfig): Promise<TestExecution> {
    const response = await fetch(`${this.baseURL}/api/testcases/${id}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
    return response.json();
  }

  // Real-time subscriptions
  subscribeToTestUpdates(callback: (update: TestUpdate) => void) {
    this.socket.on('test_progress', callback);
    return () => this.socket.off('test_progress', callback);
  }

  subscribeToDeviceUpdates(callback: (update: DeviceUpdate) => void) {
    this.socket.on('device_status', callback);
    return () => this.socket.off('device_status', callback);
  }
}
```

### React Query Integration
```typescript
// Custom hooks for data fetching
export function useTestCases() {
  return useQuery({
    queryKey: ['testcases'],
    queryFn: () => apiClient.getTestCases(),
    refetchInterval: 30000 // Refetch every 30 seconds
  });
}

export function useExecuteTestCase() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ id, config }: { id: string; config: ExecutionConfig }) =>
      apiClient.executeTestCase(id, config),
    onSuccess: () => {
      // Invalidate and refetch test executions
      queryClient.invalidateQueries(['executions']);
    }
  });
}

export function useTestExecutions() {
  return useQuery({
    queryKey: ['executions'],
    queryFn: () => apiClient.getTestExecutions(),
    refetchInterval: 5000 // More frequent updates for executions
  });
}
```

---

## 🎨 **Component Architecture**

### Dashboard Component
```typescript
interface DashboardProps {
  // Props interface
}

export const Dashboard: React.FC<DashboardProps> = () => {
  const { data: testCases, isLoading } = useTestCases();
  const { data: devices } = useDevices();
  const { data: executions } = useRecentExecutions();

  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={6}>
        <SystemOverviewCard />
      </Grid>
      <Grid item xs={12} md={6}>
        <DeviceStatusCard devices={devices} />
      </Grid>
      <Grid item xs={12}>
        <RecentExecutionsTable executions={executions} />
      </Grid>
    </Grid>
  );
};
```

### Test Execution Component
```typescript
interface TestExecutionProps {
  testCase: TestCase;
  onExecute: (config: ExecutionConfig) => void;
}

export const TestExecution: React.FC<TestExecutionProps> = ({ 
  testCase, 
  onExecute 
}) => {
  const [config, setConfig] = useState<ExecutionConfig>({
    device_id: '',
    host_id: ''
  });
  
  const executeTest = useExecuteTestCase();

  const handleExecute = () => {
    executeTest.mutate(
      { id: testCase.id, config },
      {
        onSuccess: (execution) => {
          // Navigate to execution monitoring
          navigate(`/executions/${execution.id}`);
        }
      }
    );
  };

  return (
    <Card>
      <CardContent>
        <Typography variant="h6">{testCase.name}</Typography>
        <DeviceSelector 
          value={config.device_id}
          onChange={(device_id) => setConfig({ ...config, device_id })}
        />
        <Button 
          onClick={handleExecute}
          disabled={executeTest.isLoading}
          variant="contained"
        >
          {executeTest.isLoading ? 'Executing...' : 'Execute Test'}
        </Button>
      </CardContent>
    </Card>
  );
};
```

### Real-Time Monitoring Component
```typescript
export const ExecutionMonitor: React.FC<{ executionId: string }> = ({ 
  executionId 
}) => {
  const [execution, setExecution] = useState<TestExecution | null>(null);
  const [progress, setProgress] = useState<TestProgress[]>([]);

  useEffect(() => {
    // Subscribe to real-time updates
    const unsubscribe = apiClient.subscribeToTestUpdates((update) => {
      if (update.execution_id === executionId) {
        setProgress(prev => [...prev, update]);
      }
    });

    return unsubscribe;
  }, [executionId]);

  return (
    <Box>
      <LinearProgress 
        variant="determinate" 
        value={(progress.length / execution?.total_steps || 1) * 100} 
      />
      
      <Timeline>
        {progress.map((step, index) => (
          <TimelineItem key={index}>
            <TimelineOppositeContent>
              {formatTime(step.timestamp)}
            </TimelineOppositeContent>
            <TimelineSeparator>
              <TimelineDot color={step.status === 'success' ? 'primary' : 'error'} />
              <TimelineConnector />
            </TimelineSeparator>
            <TimelineContent>
              <Typography variant="h6">{step.action}</Typography>
              {step.screenshot_url && (
                <img 
                  src={step.screenshot_url} 
                  alt={`Step ${index + 1}`}
                  style={{ maxWidth: 200, height: 'auto' }}
                />
              )}
            </TimelineContent>
          </TimelineItem>
        ))}
      </Timeline>
    </Box>
  );
};
```

---

## 🔄 **State Management**

### Global State Context
```typescript
interface AppContextType {
  user: User | null;
  selectedDevice: Device | null;
  systemHealth: SystemHealth;
  setSelectedDevice: (device: Device | null) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ 
  children 
}) => {
  const [user, setUser] = useState<User | null>(null);
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const { data: systemHealth } = useSystemHealth();

  const value = {
    user,
    selectedDevice,
    systemHealth,
    setSelectedDevice
  };

  return (
    <AppContext.Provider value={value}>
      {children}
    </AppContext.Provider>
  );
};

export const useAppContext = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useAppContext must be used within AppProvider');
  }
  return context;
};
```

---

## 🎯 **TypeScript Types**

### Core Types
```typescript
// Test Management Types
export interface TestCase {
  id: string;
  name: string;
  description: string;
  steps: TestStep[];
  device_model: string;
  created_at: string;
  updated_at: string;
}

export interface TestStep {
  id: string;
  action: string;
  parameters: Record<string, any>;
  expected_result?: string;
  verification?: VerificationConfig;
}

export interface TestExecution {
  id: string;
  test_case_id: string;
  device_id: string;
  host_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at: string;
  completed_at?: string;
  results?: ExecutionResults;
  screenshots: Screenshot[];
}

// Device Types
export interface Device {
  id: string;
  name: string;
  model: string;
  status: 'online' | 'offline' | 'busy';
  capabilities: string[];
  last_seen: string;
  host_id: string;
}

export interface Host {
  id: string;
  name: string;
  url: string;
  status: 'available' | 'busy' | 'offline';
  capabilities: string[];
  devices: Device[];
}

// Real-time Update Types
export interface TestProgress {
  execution_id: string;
  step: number;
  total_steps: number;
  action: string;
  status: 'running' | 'success' | 'error';
  timestamp: string;
  screenshot_url?: string;
  message?: string;
}

export interface DeviceUpdate {
  device_id: string;
  status: 'online' | 'offline' | 'busy';
  last_seen: string;
  current_execution?: string;
}
```

---

## 🎨 **UI/UX Design**

### Theme Configuration
```typescript
import { createTheme } from '@mui/material/styles';

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#1976d2',
    },
    secondary: {
      main: '#dc004e',
    },
    background: {
      default: '#f5f5f5',
    },
  },
  typography: {
    fontFamily: 'Roboto, Arial, sans-serif',
    h4: {
      fontWeight: 600,
    },
  },
  components: {
    MuiCard: {
      styleOverrides: {
        root: {
          boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
          borderRadius: 8,
        },
      },
    },
  },
});
```

### Responsive Design
```typescript
import { useMediaQuery, useTheme } from '@mui/material';

export const ResponsiveDashboard: React.FC = () => {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  return (
    <Grid container spacing={isMobile ? 2 : 3}>
      <Grid item xs={12} md={isMobile ? 12 : 8}>
        <MainContent />
      </Grid>
      {!isMobile && (
        <Grid item md={4}>
          <Sidebar />
        </Grid>
      )}
    </Grid>
  );
};
```

---

## 🚀 **Build & Deployment**

### Vite Configuration
```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:5109',
        changeOrigin: true,
      },
      '/socket.io': {
        target: 'http://localhost:5109',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          mui: ['@mui/material', '@mui/icons-material'],
        },
      },
    },
  },
});
```

### Environment Configuration
```typescript
// Environment variables (Vite)
interface ImportMetaEnv {
  readonly VITE_SERVER_URL: string;
  readonly VITE_CLOUDFLARE_R2_PUBLIC_URL: string;
  readonly VITE_DEV_MODE: string;
}

// Usage in code
const config = {
  serverUrl: import.meta.env.VITE_SERVER_URL || 'http://localhost:5109',
  r2PublicUrl: import.meta.env.VITE_CLOUDFLARE_R2_PUBLIC_URL,
  isDevelopment: import.meta.env.VITE_DEV_MODE === 'true',
};
```

### Production Build
```bash
# Build for production
npm run build

# Preview production build
npm run preview

# Build output structure
dist/
├── index.html
├── assets/
│   ├── index-[hash].js
│   ├── index-[hash].css
│   └── vendor-[hash].js
└── images/
```

---

## 🔍 **Testing**

### Component Testing
```typescript
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TestExecution } from '../TestExecution';

describe('TestExecution Component', () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );

  it('should execute test when button is clicked', async () => {
    const mockTestCase = {
      id: 'test-1',
      name: 'Test Case 1',
      // ... other properties
    };

    const mockOnExecute = jest.fn();

    render(
      <TestExecution testCase={mockTestCase} onExecute={mockOnExecute} />,
      { wrapper }
    );

    const executeButton = screen.getByText('Execute Test');
    fireEvent.click(executeButton);

    expect(mockOnExecute).toHaveBeenCalled();
  });
});
```

---

## 📱 **Performance Optimization**

### Code Splitting
```typescript
import { lazy, Suspense } from 'react';
import { CircularProgress } from '@mui/material';

// Lazy load heavy components
const Dashboard = lazy(() => import('./pages/Dashboard'));
const TestManagement = lazy(() => import('./pages/TestManagement'));
const DeviceControl = lazy(() => import('./pages/DeviceControl'));

export const App: React.FC = () => {
  return (
    <Suspense fallback={<CircularProgress />}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/tests" element={<TestManagement />} />
        <Route path="/devices" element={<DeviceControl />} />
      </Routes>
    </Suspense>
  );
};
```

### React Query Optimization
```typescript
// Optimize queries with proper caching
export function useTestCasesOptimized() {
  return useQuery({
    queryKey: ['testcases'],
    queryFn: apiClient.getTestCases,
    staleTime: 5 * 60 * 1000, // 5 minutes
    cacheTime: 10 * 60 * 1000, // 10 minutes
    refetchOnWindowFocus: false,
  });
}

// Prefetch related data
export function usePrefetchTestData() {
  const queryClient = useQueryClient();
  
  const prefetchTestCases = () => {
    queryClient.prefetchQuery({
      queryKey: ['testcases'],
      queryFn: apiClient.getTestCases,
    });
  };

  return { prefetchTestCases };
}
```

---

**Want to understand API integration? Check API Reference Documentation!** 🌐
