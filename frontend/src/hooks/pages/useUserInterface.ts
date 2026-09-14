/**
 * User Interface Hook
 *
 * This hook handles all user interface management functionality.
 */

import { useMemo } from 'react';

import { UserInterface, UserInterfaceCreatePayload } from '../../types/pages/UserInterface_Types';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api, apiClient } from '../../utils/apiClient';
import { APP_CONFIG } from '../../config/constants';

// 5-minute cache for user interfaces (now that we only cache valid non-empty results)
const USER_INTERFACE_TTL = 300 * 1000; // 5 minutes

const userInterfaceCache = new Map<string, {data: Promise<UserInterface>, timestamp: number}>();
const allInterfacesCache: {data: UserInterface[] | null, timestamp: number} = {data: null, timestamp: 0};
const compatibleInterfacesCache = new Map<string, {data: UserInterface[], timestamp: number}>();

function getCachedInterface(name: string) {
  const cached = userInterfaceCache.get(name);
  if (cached && (Date.now() - cached.timestamp) < USER_INTERFACE_TTL) {
    return cached.data;
  }
  if (cached) {
    userInterfaceCache.delete(name); // Remove expired
  }
  return null;
}

function setCachedInterface(name: string, data: Promise<UserInterface>) {
  userInterfaceCache.set(name, {data, timestamp: Date.now()});
}

function getCachedCompatibleInterfaces(deviceModel: string, teamId: string) {
  // Include team_id in cache key to prevent cross-team cache pollution
  const cacheKey = `${teamId}:${deviceModel}`;
  const cached = compatibleInterfacesCache.get(cacheKey);
  if (cached && (Date.now() - cached.timestamp) < USER_INTERFACE_TTL) {
    return cached.data;
  }
  if (cached) {
    compatibleInterfacesCache.delete(cacheKey); // Remove expired
  }
  return null;
}

function setCachedCompatibleInterfaces(deviceModel: string, teamId: string, data: UserInterface[]) {
  // Include team_id in cache key to prevent cross-team cache pollution
  const cacheKey = `${teamId}:${deviceModel}`;
  compatibleInterfacesCache.set(cacheKey, {data, timestamp: Date.now()});
}

/**
 * Clear all user interface caches
 * Call this when taking control to ensure fresh data
 */
export function clearUserInterfaceCaches() {
  userInterfaceCache.clear();
  allInterfacesCache.data = null;
  allInterfacesCache.timestamp = 0;
  compatibleInterfacesCache.clear();
  console.log('[@hook:useUserInterface] 🧹 All UI caches cleared (take-control)');
}

export const useUserInterface = () => {
  /**
   * Get all user interfaces
   */
  const getAllUserInterfaces = useMemo(
    () => async (): Promise<UserInterface[]> => {
      // Check 1-hour cache first
      if (allInterfacesCache.data && (Date.now() - allInterfacesCache.timestamp) < USER_INTERFACE_TTL) {
        console.log(
          `[@hook:useUserInterface:getAllUserInterfaces] Using 5m cached data (age: ${((Date.now() - allInterfacesCache.timestamp) / (1000 * 60)).toFixed(1)}m)`,
        );
        return allInterfacesCache.data;
      }
      
      try {
        console.log(
          '[@hook:useUserInterface:getAllUserInterfaces] Fetching all user interfaces from server',
        );

        const response = await apiClient(buildServerUrl('/server/userinterface/getAllUserInterfaces'));

        console.log(
          '[@hook:useUserInterface:getAllUserInterfaces] Response status:',
          response.status,
        );
        console.log(
          '[@hook:useUserInterface:getAllUserInterfaces] Response headers:',
          response.headers.get('content-type'),
        );

        if (!response.ok) {
          // Try to get error message from response
          let errorMessage = `Failed to fetch user interfaces: ${response.status} ${response.statusText}`;
          try {
            const errorData = await response.text();
            console.log(
              '[@hook:useUserInterface:getAllUserInterfaces] Error response body:',
              errorData,
            );

            // Check if it's JSON
            if (response.headers.get('content-type')?.includes('application/json')) {
              const jsonError = JSON.parse(errorData);
              errorMessage = jsonError.error || errorMessage;
            } else {
              // It's HTML or other content, likely a proxy/server issue
              if (errorData.includes('<!doctype') || errorData.includes('<html')) {
                errorMessage =
                  'Server endpoint not available. Make sure the Flask server is running on the correct port and the proxy is configured properly.';
              }
            }
          } catch {
            console.log(
              '[@hook:useUserInterface:getAllUserInterfaces] Could not parse error response',
            );
          }

          throw new Error(errorMessage);
        }

        // Check if response is JSON
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          throw new Error(
            `Expected JSON response but got ${contentType}. This usually means the Flask server is not running or the proxy is misconfigured.`,
          );
        }

        const userInterfaces = await response.json();
        console.log(
          `[@hook:useUserInterface:getAllUserInterfaces] Successfully loaded ${userInterfaces?.length || 0} user interfaces`,
        );

        // Only cache non-empty results to avoid caching temporary empty states during backend restarts
        if (userInterfaces && userInterfaces.length > 0) {
          allInterfacesCache.data = userInterfaces;
          allInterfacesCache.timestamp = Date.now();
          console.log('[@hook:useUserInterface:getAllUserInterfaces] Cached data for 5m');
        } else {
          console.log('[@hook:useUserInterface:getAllUserInterfaces] Not caching empty result');
        }

        return userInterfaces || [];
      } catch (error) {
        console.error(
          '[@hook:useUserInterface:getAllUserInterfaces] Error fetching user interfaces:',
          error,
        );
        throw error;
      }
    },
    [],
  );

  /**
   * Get a specific user interface by ID
   */
  const getUserInterface = useMemo(
    () =>
      async (id: string): Promise<UserInterface> => {
        try {
          console.log(
            `[@hook:useUserInterface:getUserInterface] Fetching user interface ${id} from server`,
          );

          const response = await apiClient(buildServerUrl(`/server/userinterface/getUserInterface/${id}`));
          if (!response.ok) {
            if (response.status === 404) {
              throw new Error('User interface not found');
            }
            throw new Error(
              `Failed to fetch user interface: ${response.status} ${response.statusText}`,
            );
          }

          const userInterface = await response.json();
          console.log(
            `[@hook:useUserInterface:getUserInterface] Successfully loaded user interface: ${userInterface.name}`,
          );
          return userInterface;
        } catch (error) {
          console.error(
            `[@hook:useUserInterface:getUserInterface] Error fetching user interface ${id}:`,
            error,
          );
          throw error;
        }
      },
    [],
  );

  /**
   * Get a specific user interface by name
   */
  const getUserInterfaceByName = useMemo(
    () =>
      async (name: string, mode: 'dev' | 'prod' = 'dev'): Promise<UserInterface> => {
        // Dev and prod rows share one name — cache + lookup are mode-scoped.
        const cacheKey = mode === 'prod' ? `${name}::prod` : name;
        // Check 1-hour cache first
        const cached = getCachedInterface(cacheKey);
        if (cached) {
          console.log(
            `[@hook:useUserInterface:getUserInterfaceByName] Using 1h cached user interface for name: ${name} (${mode})`,
          );
          return cached;
        }

        // Create and cache the promise
        const fetchPromise = (async () => {
          try {
            console.log(
              `[@hook:useUserInterface:getUserInterfaceByName] Fetching user interface by name: ${name} (${mode})`,
            );

            const response = await apiClient(buildServerUrl(`/server/userinterface/getUserInterfaceByName/${name}?mode=${mode}`));
            if (!response.ok) {
              if (response.status === 404) {
                throw new Error('User interface not found');
              }
              throw new Error(
                `Failed to fetch user interface: ${response.status} ${response.statusText}`,
              );
            }

            const userInterface = await response.json();
            console.log(
              `[@hook:useUserInterface:getUserInterfaceByName] Successfully loaded user interface: ${userInterface.name} (ID: ${userInterface.id})`,
            );
            return userInterface;
          } catch (error) {
            console.error(
              `[@hook:useUserInterface:getUserInterfaceByName] Error fetching user interface by name ${name}:`,
              error,
            );
            throw error;
          }
        })();

        // Cache for 1 hour
        setCachedInterface(cacheKey, fetchPromise);
        return fetchPromise;
      },
    [],
  );

  /**
   * Create a new user interface
   */
  const createUserInterface = useMemo(
    () =>
      async (payload: UserInterfaceCreatePayload): Promise<UserInterface> => {
        try {
          console.log(
            '[@hook:useUserInterface:createUserInterface] Creating user interface:',
            payload,
          );

          const result = await api.post(buildServerUrl('/server/userinterface/createUserInterface'), payload);

          if (result.status === 'success' && result.userinterface) {
            console.log(
              `[@hook:useUserInterface:createUserInterface] Successfully created user interface: ${result.userinterface.name}`,
            );
            return result.userinterface;
          } else {
            throw new Error(result.error || 'Failed to create user interface');
          }
        } catch (error) {
          console.error(
            '[@hook:useUserInterface:createUserInterface] Error creating user interface:',
            error,
          );
          throw error;
        }
      },
    [],
  );

  /**
   * Update an existing user interface
   */
  const updateUserInterface = useMemo(
    () =>
      async (id: string, payload: UserInterfaceCreatePayload): Promise<UserInterface> => {
        try {
          console.log(
            `[@hook:useUserInterface:updateUserInterface] Updating user interface ${id}:`,
            payload,
          );

          const result = await api.put(buildServerUrl(`/server/userinterface/updateUserInterface/${id}`), payload);

          if (result.status === 'success' && result.userinterface) {
            console.log(
              `[@hook:useUserInterface:updateUserInterface] Successfully updated user interface: ${result.userinterface.name}`,
            );
            return result.userinterface;
          } else {
            throw new Error(result.error || 'Failed to update user interface');
          }
        } catch (error) {
          console.error(
            `[@hook:useUserInterface:updateUserInterface] Error updating user interface ${id}:`,
            error,
          );
          throw error;
        }
      },
    [],
  );

  /**
   * Delete a user interface
   */
  const deleteUserInterface = useMemo(
    () =>
      async (id: string): Promise<void> => {
        try {
          console.log(`[@hook:useUserInterface:deleteUserInterface] Deleting user interface ${id}`);

          const result = await api.delete(buildServerUrl(`/server/userinterface/deleteUserInterface/${id}`));

          if (result.status === 'success') {
            console.log(
              `[@hook:useUserInterface:deleteUserInterface] Successfully deleted user interface ${id}`,
            );
          } else {
            throw new Error(result.error || 'Failed to delete user interface');
          }
        } catch (error) {
          console.error(
            `[@hook:useUserInterface:deleteUserInterface] Error deleting user interface ${id}:`,
            error,
          );
          throw error;
        }
      },
    [],
  );

  /**
   * Create empty navigation config for a user interface
   */
  const createEmptyNavigationConfig = useMemo(
    () =>
      async (userInterface: UserInterface): Promise<void> => {
        try {
          console.log(
            `[@hook:useUserInterface:createEmptyNavigationConfig] Creating empty navigation config for: ${userInterface.name}`,
          );

          const result = await api.post(
            buildServerUrl(`/server/navigation/config/createEmpty/${encodeURIComponent(userInterface.name)}`),
            {
              userinterface_data: {
                id: userInterface.id,
                name: userInterface.name,
                models: userInterface.models,
                min_version: userInterface.min_version,
                max_version: userInterface.max_version,
              },
              commit_message: `Create empty navigation config: ${userInterface.name}`,
            },
          );

          if (result.success) {
            console.log(
              `[@hook:useUserInterface:createEmptyNavigationConfig] Successfully created navigation config for: ${userInterface.name}`,
            );
          } else {
            throw new Error(result.error || 'Failed to create navigation config');
          }
        } catch (error) {
          console.error(
            `[@hook:useUserInterface:createEmptyNavigationConfig] Error creating navigation config for ${userInterface.name}:`,
            error,
          );
          throw error;
        }
      },
    [],
  );

  /**
   * Create a new user interface with validation
   */
  const createUserInterfaceWithValidation = useMemo(
    () =>
      async (
        payload: UserInterfaceCreatePayload,
        existingInterfaces: UserInterface[],
        options?: { createNavigationConfig?: boolean },
      ): Promise<UserInterface> => {
        try {
          // Validation: Name is required
          if (!payload.name.trim()) {
            throw new Error('Name is required');
          }

          // Validation: At least one model must be specified
          if (payload.models.length === 0) {
            throw new Error('At least one model must be specified');
          }

          // Validation: Check for duplicate names
          const isDuplicate = existingInterfaces.some(
            (ui) => ui.name.toLowerCase() === payload.name.toLowerCase().trim(),
          );

          if (isDuplicate) {
            throw new Error('A user interface with this name already exists');
          }

          console.log(
            '[@hook:useUserInterface:createUserInterfaceWithValidation] Creating user interface:',
            payload,
          );

          // Normalize payload
          const normalizedPayload: UserInterfaceCreatePayload = {
            name: payload.name.trim(),
            models: payload.models,
            min_version: payload.min_version?.trim() || '',
            max_version: payload.max_version?.trim() || '',
          };

          const createdInterface = await createUserInterface(normalizedPayload);

          // Create navigation config if requested (default: true)
          if (options?.createNavigationConfig !== false) {
            try {
              await createEmptyNavigationConfig(createdInterface);
              console.log(
                `[@hook:useUserInterface:createUserInterfaceWithValidation] Successfully created navigation config for: ${createdInterface.name}`,
              );
            } catch (configError) {
              console.error(
                '[@hook:useUserInterface:createUserInterfaceWithValidation] Error creating navigation config:',
                configError,
              );
              throw new Error(
                'User interface created successfully, but failed to create navigation config. You can still use the navigation editor.',
              );
            }
          }

          return createdInterface;
        } catch (error) {
          console.error(
            '[@hook:useUserInterface:createUserInterfaceWithValidation] Error creating user interface:',
            error,
          );
          throw error;
        }
      },
    [createUserInterface, createEmptyNavigationConfig],
  );

  /**
   * Update an existing user interface with validation
   */
  const updateUserInterfaceWithValidation = useMemo(
    () =>
      async (
        id: string,
        payload: UserInterfaceCreatePayload,
        existingInterfaces: UserInterface[],
      ): Promise<UserInterface> => {
        try {
          // Validation: Name is required
          if (!payload.name.trim()) {
            throw new Error('Name is required');
          }

          // Validation: At least one model must be specified
          if (payload.models.length === 0) {
            throw new Error('At least one model must be specified');
          }

          // Validation: Check for duplicate names (excluding current item)
          const isDuplicate = existingInterfaces.some(
            (ui) => ui.id !== id && ui.name.toLowerCase() === payload.name.toLowerCase().trim(),
          );

          if (isDuplicate) {
            throw new Error('A user interface with this name already exists');
          }

          console.log(
            `[@hook:useUserInterface:updateUserInterfaceWithValidation] Updating user interface ${id}:`,
            payload,
          );

          // Normalize payload
          const normalizedPayload: UserInterfaceCreatePayload = {
            name: payload.name.trim(),
            models: payload.models,
            min_version: payload.min_version?.trim() || '',
            max_version: payload.max_version?.trim() || '',
          };

          return await updateUserInterface(id, normalizedPayload);
        } catch (error) {
          console.error(
            `[@hook:useUserInterface:updateUserInterfaceWithValidation] Error updating user interface ${id}:`,
            error,
          );
          throw error;
        }
      },
    [updateUserInterface],
  );

  /**
   * Duplicate an existing user interface with _copy suffix
   */
  const duplicateUserInterface = useMemo(
    () =>
      async (userInterface: UserInterface, existingInterfaces: UserInterface[]): Promise<UserInterface> => {
        try {
          // Generate unique name with _copy suffix
          let newName = `${userInterface.name}_copy`;
          let counter = 1;
          
          // Check if name exists, if so add _1, _2, etc.
          while (existingInterfaces.some((ui) => ui.name.toLowerCase() === newName.toLowerCase())) {
            newName = `${userInterface.name}_copy_${counter}`;
            counter++;
          }

          console.log(
            `[@hook:useUserInterface:duplicateUserInterface] Duplicating user interface: ${userInterface.name} -> ${newName}`,
          );

          // Call the new backend endpoint that duplicates UI + tree
          const result = await api.post(
            buildServerUrl(`/server/userinterface/duplicateUserInterface/${userInterface.id}`),
            { name: newName },
          );

          if (result.status === 'success' && result.userinterface) {
            const duplicatedInterface = result.userinterface;
            const stats = duplicatedInterface.duplication_stats;

            if (stats?.tree_duplicated) {
              const treesText = stats.trees_count > 1 ? `${stats.trees_count} trees` : '1 tree';
              console.log(
                `[@hook:useUserInterface:duplicateUserInterface] Successfully duplicated user interface with navigation tree hierarchy: ${duplicatedInterface.name} (${treesText}, ${stats.nodes_count} nodes, ${stats.edges_count} edges, ${stats.references_count ?? 0} references)`,
              );
            } else {
              console.log(
                `[@hook:useUserInterface:duplicateUserInterface] Duplicated user interface without navigation tree: ${duplicatedInterface.name} - ${stats?.error || 'Unknown reason'}`,
              );
            }
            
            return duplicatedInterface;
          } else {
            throw new Error(result.error || 'Failed to duplicate user interface');
          }
        } catch (error) {
          console.error(
            `[@hook:useUserInterface:duplicateUserInterface] Error duplicating user interface ${userInterface.name}:`,
            error,
          );
          throw error;
        }
      },
    [],
  );

  /**
   * Publish a dev user interface to prod (create or in-place-update its prod
   * snapshot). Clears the module caches so the prod row appears immediately.
   */
  const publishUserInterface = useMemo(
    () =>
      async (userInterface: UserInterface): Promise<{
        prod_userinterface_id: string;
        version: number;
        first_publish: boolean;
        counts?: Record<string, number>;
      }> => {
        try {
          console.log(
            `[@hook:useUserInterface:publishUserInterface] Publishing: ${userInterface.name}`,
          );
          const result = await api.post(
            buildServerUrl(`/server/userinterface/publish/${userInterface.id}`),
            {},
          );
          if (result.success) {
            clearUserInterfaceCaches();
            console.log(
              `[@hook:useUserInterface:publishUserInterface] ${userInterface.name} -> prod v${result.version}`,
            );
            return result;
          }
          throw new Error(result.error || 'Failed to publish user interface');
        } catch (error) {
          console.error(
            `[@hook:useUserInterface:publishUserInterface] Error publishing ${userInterface.name}:`,
            error,
          );
          throw error;
        }
      },
    [],
  );

  /**
   * Get compatible user interfaces for a device model
   */
  const getCompatibleInterfaces = useMemo(
    () =>
      async (deviceModel: string): Promise<UserInterface[]> => {
        if (!deviceModel) {
          console.warn('[@hook:useUserInterface:getCompatibleInterfaces] No device model provided');
          return [];
        }

        const teamId = APP_CONFIG.DEFAULT_TEAM_ID;

        // Check cache first (with team_id to prevent cross-team pollution)
        const cachedData = getCachedCompatibleInterfaces(deviceModel, teamId);
        if (cachedData) {
          console.log(
            `[@hook:useUserInterface:getCompatibleInterfaces] Cache HIT for ${deviceModel}:${teamId} (${cachedData.length} interfaces)`,
          );
          return cachedData;
        }

        try {
          console.log(
            `[@hook:useUserInterface:getCompatibleInterfaces] Fetching compatible interfaces for device model: ${deviceModel}, team: ${teamId}`,
          );

          const data = await api.get(
            buildServerUrl(`/server/userinterface/getCompatibleInterfaces?device_model=${deviceModel}`)
          );

          if (data.success && Array.isArray(data.interfaces)) {
            console.log(
              `[@hook:useUserInterface:getCompatibleInterfaces] Found ${data.interfaces.length} compatible interfaces`,
            );
            // Only cache non-empty results to avoid caching temporary empty states during backend restarts
            if (data.interfaces.length > 0) {
              setCachedCompatibleInterfaces(deviceModel, teamId, data.interfaces);
            }
            return data.interfaces;
          } else {
            console.log(
              `[@hook:useUserInterface:getCompatibleInterfaces] No compatible interfaces found for ${deviceModel}`,
            );
            return [];
          }
        } catch (error) {
          console.error(
            `[@hook:useUserInterface:getCompatibleInterfaces] Error fetching compatible interfaces for ${deviceModel}:`,
            error,
          );
          return [];
        }
      },
    [],
  );

  /**
   * Export a user interface + its full navigation tree as a downloadable .vptree bundle.
   */
  const exportUserInterface = useMemo(
    () =>
      async (userInterface: UserInterface): Promise<void> => {
        console.log(
          `[@hook:useUserInterface:exportUserInterface] Exporting ${userInterface.name}`,
        );
        const response = await apiClient(
          buildServerUrl(`/server/userinterface/${userInterface.id}/export`),
          { method: 'GET' },
        );
        if (!response.ok) {
          const err = await response.json().catch(() => ({ error: response.statusText }));
          throw new Error(err.error || `HTTP ${response.status}`);
        }
        // Stream the zip to a browser download.
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${userInterface.name}.vptree`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      },
    [],
  );

  /**
   * Import a .vptree bundle as a new user interface.
   */
  const importUserInterface = useMemo(
    () =>
      async (file: File, name: string): Promise<UserInterface> => {
        console.log(
          `[@hook:useUserInterface:importUserInterface] Importing ${file.name} -> ${name}`,
        );
        const form = new FormData();
        form.append('file', file);
        form.append('name', name);
        const response = await apiClient(buildServerUrl('/server/userinterface/import'), {
          method: 'POST',
          body: form,
        });
        const result = await response
          .json()
          .catch(() => ({ error: response.statusText }));
        if (!response.ok || result.status !== 'success' || !result.userinterface) {
          throw new Error(result.error || `HTTP ${response.status}`);
        }
        const stats = result.stats || {};
        console.log(
          `[@hook:useUserInterface:importUserInterface] Imported ${result.userinterface.name} ` +
            `(${stats.trees ?? 0} trees, ${stats.nodes ?? 0} nodes, ${stats.edges ?? 0} edges, ` +
            `${stats.variants ?? 0} variants, ${stats.references ?? 0} references)`,
        );
        return result.userinterface;
      },
    [],
  );

  return {
    getAllUserInterfaces,
    getUserInterface,
    getUserInterfaceByName,
    createUserInterface,
    createUserInterfaceWithValidation,
    updateUserInterface,
    updateUserInterfaceWithValidation,
    deleteUserInterface,
    duplicateUserInterface,
    publishUserInterface,
    exportUserInterface,
    importUserInterface,
    createEmptyNavigationConfig,
    getCompatibleInterfaces,
  };
};
