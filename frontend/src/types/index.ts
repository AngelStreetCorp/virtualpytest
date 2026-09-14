// Export all types from organized structure

// Common types - Base types first, then specific types
export * from './common/Common_Base_Types'; // Only WizardStep and ServerResponse now

// Export device and host types
export type { Host } from './common/Host_Types';
export type { Device } from './common/Host_Types';

// Export all controller types
export type {
  AVControllerImplementation,
  ControllerConfigMap,
} from './controller/Controller_Types';

export * from './pages/Environment_Types';

// Page-specific types (Navigation_Types includes its own ActionExecutionResult)
export * from './pages/Navigation_Types';
export * from './pages/TestCase_Types';
export * from './pages/Campaign_Types';

// Export UserInterface types
export type {
  UserInterface,
  UserInterfaceCreatePayload,
  ScreenViewMode,
  StreamStatus,
  LayoutConfig,
  DeviceResolution,
  ResolutionInfo,
  SelectedArea,
  CaptureImageState,
  RecordingTimerProps,
  OverlayProps,
} from './pages/UserInterface_Types';

export * from './pages/Dashboard_Types';

// Feature-specific types - Remote types with explicit exports to avoid conflicts
export type {
  AndroidElement,
  AndroidApp,
  RemoteConfig,
  RemoteDeviceConfig,
  ConnectionForm,
  RemoteSession,
  AndroidTVSession,
  AndroidMobileSession,
  TestResult,
  RemoteType as RemoteControllerType,
  BaseConnectionConfig,
  AndroidConnectionConfig,
  IRConnectionConfig,
  BluetoothConnectionConfig,
  AnyConnectionConfig,
  ControllerItem,
  ControllerTypesResponse,
} from './controller/Remote_Types';

// Export the Remote ControllerTypes with alias to avoid conflict
export type {
  ControllerTypes as RemoteControllerTypes,
  ControllerType as RemoteControllerTypeAlias,
} from './controller/Remote_Types';

// Panel types for dynamic panel state management
export type {
  PanelInfo,
  PanelDimensions,
  PanelContentArea,
  PanelState,
  PanelLayoutConfig,
  PanelAwareProps,
  PanelManagerProps,
} from './controller/Panel_Types';

export * from './features/Validation_Types';

// Device Model types  
export type { Model as DeviceModel } from './pages/Models_Types';
