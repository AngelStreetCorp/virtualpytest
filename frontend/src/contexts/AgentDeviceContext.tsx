import React, { createContext, useContext, useEffect, useState, useMemo, ReactNode } from 'react';
import { useHostData } from '../hooks/useHostManager';
import { useUserInterface } from '../hooks/pages/useUserInterface';
import { filterCompatibleInterfaces } from '../utils/userinterface/deviceCompatibilityUtils';
import { Host, Device } from '../types/common/Host_Types';

interface AgentDeviceContextType {
  // Available items (cached)
  availableDevices: Device[];
  availableUserInterfaces: string[];
  availableHosts: Host[];

  // Auto-selected items
  selectedDevice: Device | null;
  selectedHost: Host | null;
  selectedUserInterface: string | null;

  // Loading states
  isLoadingDevices: boolean;
  isLoadingInterfaces: boolean;

  // Errors
  deviceError: string | null;
  interfaceError: string | null;

  // Utility functions
  getDeviceById: (deviceId: string) => Device | null;
  getHostByDeviceId: (deviceId: string) => Host | null;
  getCompatibleInterfacesForDevice: (deviceId: string) => string[];
}

const AgentDeviceContext = createContext<AgentDeviceContextType | undefined>(undefined);

interface AgentDeviceProviderProps {
  children: ReactNode;
}

export const AgentDeviceProvider: React.FC<AgentDeviceProviderProps> = ({ children }) => {
  const { getAllHosts, getAllDevices } = useHostData();
  const { getAllUserInterfaces } = useUserInterface();

  // State for available items
  const [availableHosts, setAvailableHosts] = useState<Host[]>([]);
  const [availableDevices, setAvailableDevices] = useState<Device[]>([]);
  const [availableUserInterfaces, setAvailableUserInterfaces] = useState<string[]>([]);

  // Auto-selected items
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [selectedHost, setSelectedHost] = useState<Host | null>(null);
  const [selectedUserInterface, setSelectedUserInterface] = useState<string | null>(null);

  // Loading states
  const [isLoadingDevices, setIsLoadingDevices] = useState(true);
  const [isLoadingInterfaces, setIsLoadingInterfaces] = useState(true);

  // Errors
  const [deviceError, setDeviceError] = useState<string | null>(null);
  const [interfaceError, setInterfaceError] = useState<string | null>(null);

  // Load available hosts and devices
  useEffect(() => {
    try {
      setIsLoadingDevices(true);
      setDeviceError(null);

      const hosts = getAllHosts();
      const devices = getAllDevices();

      setAvailableHosts(hosts);
      setAvailableDevices(devices);

      console.log('[AgentDeviceContext] Loaded devices:', {
        hostsCount: hosts.length,
        devicesCount: devices.length,
        devices: devices.map(d => `${d.device_name} (${d.device_id})`)
      });

      setIsLoadingDevices(false);
    } catch (error) {
      console.error('[AgentDeviceContext] Error loading devices:', error);
      setDeviceError(error instanceof Error ? error.message : 'Failed to load devices');
      setIsLoadingDevices(false);
    }
  }, [getAllHosts, getAllDevices]);

  // Load available user interfaces
  useEffect(() => {
    const loadInterfaces = async () => {
      try {
        setIsLoadingInterfaces(true);
        setInterfaceError(null);

        const interfaces = await getAllUserInterfaces();
        const interfaceNames = interfaces.map(iface => iface.name);

        setAvailableUserInterfaces(interfaceNames);

        console.log('[AgentDeviceContext] Loaded user interfaces:', interfaceNames);

        setIsLoadingInterfaces(false);
      } catch (error) {
        console.error('[AgentDeviceContext] Error loading user interfaces:', error);
        setInterfaceError(error instanceof Error ? error.message : 'Failed to load user interfaces');
        setIsLoadingInterfaces(false);
      }
    };

    loadInterfaces();
  }, [getAllUserInterfaces]);

  // Auto-select device when devices are loaded
  useEffect(() => {
    if (availableDevices.length === 0 || isLoadingDevices) return;

    // Auto-select first available online device
    const onlineDevices = availableDevices.filter(device => {
      const host = availableHosts.find(h => h.devices?.some(d => d.device_id === device.device_id));
      return host?.status === 'online';
    });

    if (onlineDevices.length > 0) {
      const autoSelectedDevice = onlineDevices[0];
      const autoSelectedHost = availableHosts.find(h =>
        h.devices?.some(d => d.device_id === autoSelectedDevice.device_id)
      );

      setSelectedDevice(autoSelectedDevice);
      setSelectedHost(autoSelectedHost || null);

      console.log('[AgentDeviceContext] Auto-selected device:', {
        device: `${autoSelectedDevice.device_name} (${autoSelectedDevice.device_id})`,
        host: autoSelectedHost?.host_name
      });
    } else {
      console.warn('[AgentDeviceContext] No online devices available for auto-selection');
    }
  }, [availableDevices, availableHosts, isLoadingDevices]);

  // Auto-select user interface when device is selected
  useEffect(() => {
    if (!selectedDevice || !selectedHost || availableUserInterfaces.length === 0 || isLoadingInterfaces) return;

    const loadCompatibleInterfaces = async () => {
      try {
        const allInterfaces = await getAllUserInterfaces();
        const compatibleInterfaces = filterCompatibleInterfaces(allInterfaces, selectedDevice);
        const compatibleNames = compatibleInterfaces.map(iface => iface.name);

        if (compatibleNames.length > 0) {
          const autoSelectedInterface = compatibleNames[0];
          setSelectedUserInterface(autoSelectedInterface);

          console.log('[AgentDeviceContext] Auto-selected user interface:', {
            device: selectedDevice.device_name,
            interface: autoSelectedInterface,
            available: compatibleNames
          });
        } else {
          console.warn('[AgentDeviceContext] No compatible interfaces found for device:', selectedDevice.device_name);
          setSelectedUserInterface(null);
        }
      } catch (error) {
        console.error('[AgentDeviceContext] Error loading compatible interfaces:', error);
      }
    };

    loadCompatibleInterfaces();
  }, [selectedDevice, selectedHost, availableUserInterfaces.length, isLoadingInterfaces, getAllUserInterfaces]);

  // Utility functions
  const getDeviceById = (deviceId: string): Device | null => {
    return availableDevices.find(device => device.device_id === deviceId) || null;
  };

  const getHostByDeviceId = (deviceId: string): Host | null => {
    return availableHosts.find(host =>
      host.devices?.some(device => device.device_id === deviceId)
    ) || null;
  };

  const getCompatibleInterfacesForDevice = (deviceId: string): string[] => {
    const device = getDeviceById(deviceId);
    if (!device) return [];

    // We need to get the full interface objects to filter them
    // This is a simplified version - in practice you'd want to cache this
    return availableUserInterfaces; // For now, return all - filtering would need async call
  };

  const contextValue: AgentDeviceContextType = useMemo(() => ({
    availableDevices,
    availableUserInterfaces,
    availableHosts,
    selectedDevice,
    selectedHost,
    selectedUserInterface,
    isLoadingDevices,
    isLoadingInterfaces,
    deviceError,
    interfaceError,
    getDeviceById,
    getHostByDeviceId,
    getCompatibleInterfacesForDevice,
  }), [
    availableDevices,
    availableUserInterfaces,
    availableHosts,
    selectedDevice,
    selectedHost,
    selectedUserInterface,
    isLoadingDevices,
    isLoadingInterfaces,
    deviceError,
    interfaceError,
  ]);

  return (
    <AgentDeviceContext.Provider value={contextValue}>
      {children}
    </AgentDeviceContext.Provider>
  );
};

export const useAgentDevice = (): AgentDeviceContextType => {
  const context = useContext(AgentDeviceContext);
  if (context === undefined) {
    throw new Error('useAgentDevice must be used within an AgentDeviceProvider');
  }
  return context;
};
