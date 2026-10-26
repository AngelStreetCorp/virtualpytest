import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { Socket } from 'socket.io-client';
import { createServerSocket } from '../utils/serverSocket';
import { ServerManagerContext } from './ServerManagerContext';
import { ServerHostData } from '../types/common/Server_Types';
import { Host } from '../types/common/Host_Types';
import { getAllServerUrls, buildServerUrlForServer } from '../utils/buildUrlUtils';
import { CACHE_CONFIG, STORAGE_KEYS } from '../config/constants';
import { apiClient } from '../utils/apiClient';
import { isAuthEnabled } from '../lib/supabase';
import { ALL_SERVERS_SENTINEL, isAllServersSentinel } from '../lib/allServer/scope';
import {
  discoverServerIdentity,
  getServerAuthInfo,
  getServerAuthState,
  ServerAuthState,
} from '../lib/serverIdentity';
import { useAuthContext } from './auth/AuthContext';

const log = (..._args: unknown[]): void => {};

interface ServerManagerProviderProps {
  children: React.ReactNode;
}

interface CachedData {
  data: ServerHostData[];
  timestamp: number;
}

/**
 * Keep the richer stats a lightweight refresh doesn't ask for.
 *
 * `include_system_stats=false` rounds return hosts without system_stats/service_health,
 * so overwriting the Dashboard's fuller entry with one of those would blank its gauges
 * between polls.
 */
const preserveRicherStats = (
  entry: ServerHostData,
  previous: ServerHostData | undefined,
): ServerHostData => {
  if (!previous) return entry;

  const previousHostByName = new Map(previous.hosts.map((h: Host) => [h.host_name, h]));
  return {
    ...entry,
    server_info: {
      ...entry.server_info,
      system_stats: previous.server_info.system_stats ?? entry.server_info.system_stats,
      service_health: previous.server_info.service_health ?? entry.server_info.service_health,
    },
    frontend_info: entry.frontend_info ?? previous.frontend_info ?? null,
    hosts: entry.hosts.map((host: Host) => {
      const prevHost = previousHostByName.get(host.host_name);
      if (!prevHost?.system_stats) {
        return host;
      }
      return { ...host, system_stats: prevHost.system_stats };
    }),
  };
};

/**
 * Server Manager Provider
 * 
 * Manages backend server selection and server data fetching.
 * Handles multi-server architecture where frontend can connect to multiple backend servers.
 * 
 * Features:
 * - Server selection with localStorage persistence
 * - Fetches server info and hosts from all configured servers
 * - Provides centralized server state management
 * - Caches server data for 30 seconds to show fresh host status after reboot
 */
export const ServerManagerProvider: React.FC<ServerManagerProviderProps> = ({ children }) => {
  // ========================================
  // STATE
  // ========================================

  // Auth-awareness: skip API calls when auth is enabled but user hasn't logged in yet
  const { isAuthenticated } = useAuthContext();
  const canFetch = !isAuthEnabled || isAuthenticated;

  // Get all configured server URLs from environment
  const availableServers = useMemo(() => getAllServerUrls(), []);

  // Selected server state with localStorage persistence. The sentinel
  // ALL_SERVERS_SENTINEL is also a valid value (it is the "All servers"
  // row in the picker) — availableServers does NOT list it, so the
  // membership check has to special-case the sentinel. Without this,
  // reloading the page while ALL is selected would silently flip the
  // picker back to the first configured server.
  const [selectedServer, setSelectedServerState] = useState<string>(() => {
    try {
      const saved = localStorage.getItem('selectedServer');
      if (saved === ALL_SERVERS_SENTINEL) return ALL_SERVERS_SENTINEL;
      return saved && availableServers.includes(saved) ? saved : availableServers[0] || '';
    } catch {
      return availableServers[0] || '';
    }
  });

  // Server data state - Initialize from cache if available (even if stale, for immediate display)
  const [serverHostsData, setServerHostsData] = useState<ServerHostData[]>(() => {
    try {
      const cached = localStorage.getItem(STORAGE_KEYS.SERVER_HOSTS_CACHE);
      if (cached) {
        const { data, timestamp }: CachedData = JSON.parse(cached);
        const age = Date.now() - timestamp;
        // Use cached data even if stale (better than showing empty combobox)
        // Background refresh will update it if stale
        log(`[@ServerManager] Using cached data (age: ${Math.round(age / 1000)}s, ${age < CACHE_CONFIG.VERY_SHORT_TTL ? 'FRESH' : 'STALE - will refresh'})`);
        return data;
      }
    } catch (error) {
      console.warn('[@ServerManager] Failed to load cached data:', error);
    }
    return [];
  });

  // Check if we have FRESH (not stale) cached data on initial load
  const hasFreshCache = useMemo(() => {
    try {
      const cached = localStorage.getItem(STORAGE_KEYS.SERVER_HOSTS_CACHE);
      if (cached) {
        const { timestamp }: CachedData = JSON.parse(cached);
        const age = Date.now() - timestamp;
        return age < CACHE_CONFIG.VERY_SHORT_TTL;
      }
    } catch {
      return false;
    }
    return false;
  }, []);

  const [isLoading, setIsLoading] = useState(!hasFreshCache);
  const hasLoadedOnceRef = useRef<boolean>(serverHostsData.length > 0 || hasFreshCache);
  const lastDataSignatureRef = useRef<string>(JSON.stringify(serverHostsData));
  const [error, setError] = useState<string | null>(null);
  const [pendingServers, setPendingServers] = useState<Set<string>>(new Set());
  const [failedServers, setFailedServers] = useState<Set<string>>(new Set());

  // Per-server auth state (TASK-18). Distinct from failedServers: a server we simply
  // have no session for is reachable and selectable-after-login, not broken, and
  // collapsing the two into "Offline" is what made a different-Supabase server look
  // like a dead one.
  const [serverAuthStates, setServerAuthStates] = useState<Record<string, ServerAuthState>>({});

  // Read inside fetchServerData without adding a dependency that would rebuild the
  // callback (and re-trigger every fetch effect) on each discovery round.
  const serverAuthStatesRef = useRef<Record<string, ServerAuthState>>(serverAuthStates);
  serverAuthStatesRef.current = serverAuthStates;
  
  // Server change transition state - blocks re-selection while streams initialize
  const [isServerChanging, setIsServerChanging] = useState(false);
  const serverChangeTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Ref to prevent duplicate API calls
  // Keep serverHostsData in a stable ref so fetchServerData doesn't recreate on every fetch.
  const serverHostsDataRef = useRef<ServerHostData[]>(serverHostsData);
  const selectedServerRef = useRef<string>(selectedServer);
  selectedServerRef.current = selectedServer;
  serverHostsDataRef.current = serverHostsData;

  const isRequestInProgress = useRef(false);
  const inFlightFetchRef = useRef<Promise<void> | null>(null);
  const systemSocketRef = useRef<Socket | null>(null);
  const systemSocketConnectedRef = useRef(false);
  const hasHandledFirstConnectRef = useRef(false);
  const refreshDebounceRef = useRef<NodeJS.Timeout | null>(null);
  const lastForceRefreshTimeRef = useRef(0);

  // ========================================
  // SERVER SELECTION
  // ========================================

  // Wrapper to persist server selection to localStorage
  // Sets transition state to block re-selection while streams initialize
  const setSelectedServer = useCallback((serverUrl: string) => {
    // Skip if already changing or same server
    if (isServerChanging || serverUrl === selectedServer) {
      log('[@ServerManager] Server change blocked:', { isServerChanging, sameServer: serverUrl === selectedServer });
      return;
    }
    
    // Set transition state
    setIsServerChanging(true);
    log('[@ServerManager] Server change started - UI blocked for stream initialization');
    
    // Clear any existing timeout
    if (serverChangeTimeoutRef.current) {
      clearTimeout(serverChangeTimeoutRef.current);
    }
    
    // Update server selection
    setSelectedServerState(serverUrl);
    try {
      localStorage.setItem('selectedServer', serverUrl);
      log('[@ServerManager] Server selection saved:', serverUrl);
    } catch (error) {
      console.warn('[@ServerManager] Failed to save selected server to localStorage:', error);
    }
    // Notify listeners that need to rebind to the new server (e.g. the shared
    // agent socket, which otherwise keeps talking to the previous server while
    // the UI shows the new one).
    window.dispatchEvent(new CustomEvent('vpt:server-changed', { detail: serverUrl }));
    
    // Clear transition state after streams have time to initialize (2 seconds)
    serverChangeTimeoutRef.current = setTimeout(() => {
      setIsServerChanging(false);
      log('[@ServerManager] Server change completed - UI unblocked');
    }, 2000);
  }, [isServerChanging, selectedServer]);

  // ========================================
  // SERVER AUTH DISCOVERY (TASK-18)
  // ========================================

  /**
   * Ask every configured server which Supabase it authenticates against, then work out
   * whether we already hold a session for it.
   *
   * Runs regardless of whether the user is signed in: the probe is unauthenticated, and
   * knowing the identity BEFORE login is what lets the very first API call of the session
   * attach the right token instead of the primary one.
   */
  const refreshServerAuth = useCallback(async () => {
    await Promise.all(
      availableServers.map(async (serverUrl) => {
        await discoverServerIdentity(serverUrl);
        const state = await getServerAuthState(serverUrl);
        // Published per server instead of as one map after Promise.all: this map gates
        // which servers the host fetch may call, so making it wait for the slowest (or
        // unreachable) server held up the fetch for every healthy one too.
        setServerAuthStates((previous) =>
          previous[serverUrl] === state ? previous : { ...previous, [serverUrl]: state },
        );
      }),
    );
  }, [availableServers]);

  useEffect(() => {
    void refreshServerAuth();
  }, [refreshServerAuth, isAuthenticated]);

  // ========================================
  // SERVER DATA FETCHING
  // ========================================

  /**
   * Fetch server information and hosts from all configured servers
   * Non-blocking: Shows partial data if some servers fail
   */
  const fetchServerData = useCallback(async (forceRefresh = false, includeSystemStats = false) => {
    if (!canFetch) {
      log('[@ServerManager] Skipping fetch until authentication completes');
      return;
    }

    const shouldShowLoader = !hasLoadedOnceRef.current;

    // Check cache first (unless force refresh)
    if (!forceRefresh) {
      try {
        const cached = localStorage.getItem(STORAGE_KEYS.SERVER_HOSTS_CACHE);
        if (cached) {
          const { data, timestamp }: CachedData = JSON.parse(cached);
          const age = Date.now() - timestamp;
          if (age < CACHE_CONFIG.VERY_SHORT_TTL) {
            log(`[@ServerManager] Using cached data (age: ${Math.round(age / 1000)}s)`);
            setServerHostsData(data);
            setIsLoading(false);
            isRequestInProgress.current = false;
            hasLoadedOnceRef.current = true;
            return;
          }
        }
      } catch (error) {
        console.warn('[@ServerManager] Failed to load cached data:', error);
      }
    }

    // Coalesce concurrent callers onto the same in-flight network request.
    // The initial useEffect, the socket `connect` handler, and the host_ping /
    // topology refreshes all converge on this function within milliseconds; without
    // this, the page fires multiple identical /getAllHosts on first load.
    if (inFlightFetchRef.current) {
      log('[@ServerManager] Awaiting in-flight fetch instead of starting a new one');
      return inFlightFetchRef.current;
    }

    // Legacy guard kept for callers that bypass the in-flight ref (defensive).
    if (isRequestInProgress.current) {
      log('[@ServerManager] Request already in progress, skipping duplicate call');
      return;
    }

    if (shouldShowLoader) {
      setIsLoading(true);
    }

    isRequestInProgress.current = true;
    setError(null);

    // TASK-18: skip servers we hold no session for. Calling them would 401 on every
    // refresh and then show up as "Offline", which reads as a broken server rather than
    // one that is simply waiting for a login.
    //
    // This map is only a fast path: on the first paint of a page load it is still empty,
    // because filling it takes a /server/auth/check round trip per server. Every server
    // therefore passed this filter on the very load where the skip mattered most, and a
    // server behind a different Supabase got its 401 anyway. The per-server check inside
    // the fetch below is the one that actually decides.
    const fetchableServers = availableServers.filter(
      (serverUrl) => serverAuthStatesRef.current[serverUrl] !== 'needs-auth',
    );

    // Don't reset serverHostsData to empty - keep old data while fetching
    // This prevents triggering hostCount=0 conditions during refresh
    setPendingServers(new Set(fetchableServers));
    setFailedServers(new Set()); // Reset failed servers

    const fetchPromise = (async () => {
    // Display order = the configured order, so results landing out of order can't
    // reshuffle the list under the user.
    const displayOrder = availableServers.map((url) => url || window.location.origin);
    const orderOf = (entry: ServerHostData): number => {
      const index = displayOrder.indexOf(entry.server_info.server_url);
      return index === -1 ? displayOrder.length : index;
    };

    // What this round actually published, keyed by server_url, for the cache write below.
    const published = new Map<string, ServerHostData>();

    /**
     * Publish one server's data the moment it lands.
     *
     * Every server's result used to wait on the Promise.all below before ANY of it
     * reached state, so a single slow or unreachable server left the Dashboard and
     * Devices pages empty until that one gave up — even though the others had already
     * answered. Now each server renders on its own, and a failing one only removes
     * itself, at the end of the round.
     */
    const publishServerEntry = (entry: ServerHostData) => {
      const url = entry.server_info.server_url;
      const previous = serverHostsDataRef.current.find((e) => e.server_info.server_url === url);
      const merged = includeSystemStats ? entry : preserveRicherStats(entry, previous);
      published.set(url, merged);

      setServerHostsData((prev) => {
        const existing = prev.find((e) => e.server_info.server_url === url);
        // Skip the state churn when a poll returns exactly what is already displayed.
        if (existing && JSON.stringify(existing) === JSON.stringify(merged)) return prev;
        return [...prev.filter((e) => e.server_info.server_url !== url), merged].sort(
          (a, b) => orderOf(a) - orderOf(b),
        );
      });

      // The first server to answer ends the page-level spinner; the rest stream in behind it.
      setIsLoading(false);
      hasLoadedOnceRef.current = true;
    };

    // Fetch from all servers in parallel
    const promises = fetchableServers.map(async (serverUrl) => {
      try {
        // Does this server want a login we do not have? Answering needs the server's
        // identity, so probe it first when we have never seen it — one cheap
        // unauthenticated GET, in parallel with the other servers' work, in exchange for
        // not sending a doomed request (and, on a shared Supabase, not showing the server
        // as "Offline" when it is merely logged out).
        if (!getServerAuthInfo(serverUrl)) {
          await discoverServerIdentity(serverUrl);
        }
        const authState = await getServerAuthState(serverUrl);
        setServerAuthStates((previous) =>
          previous[serverUrl] === authState ? previous : { ...previous, [serverUrl]: authState },
        );

        if (authState === 'needs-auth') {
          // Not a failure: the server is reachable and selectable after a login, so it
          // must stay out of failedServers or the picker reports it as broken.
          return { success: false, serverUrl, data: null };
        }

        // Lightweight by default; full stats only when explicitly requested (e.g. Dashboard).
        const response = await apiClient(
          buildServerUrlForServer(
            serverUrl,
            `/server/system/getAllHosts?include_actions=false&include_system_stats=${includeSystemStats ? 'true' : 'false'}&force_refresh=${forceRefresh ? 'true' : 'false'}`
          ),
          {
          // Every caller of this function awaits the same shared round, so the round lasts
          // as long as its slowest server. Only the selected server gets the long budget;
          // a slow side server (e.g. a Pi on a weak link) must not hold the others for 10 s.
          signal: AbortSignal.timeout(
            isAllServersSentinel(selectedServerRef.current) || serverUrl === selectedServerRef.current
              ? 10000
              : 4000,
          )
          }
        );
        
        if (response.ok) {
          const data = await response.json();
          
          // Handle empty serverUrl (relative URLs behind nginx proxy)
          let cleanUrl = serverUrl;
          let serverPort = '80';
          if (serverUrl === '') {
            // Using relative URLs - extract info from window.location
            cleanUrl = window.location.host;
            serverPort = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
          } else {
            const urlParts = new URL(serverUrl);
            cleanUrl = serverUrl.replace(/^https?:\/\//, '').replace(/:\d+$/, '');
            serverPort = urlParts.port || (urlParts.protocol === 'https:' ? '443' : '80');
          }
          
          const serverData = {
            server_info: {
              server_name: data.server_info?.server_name || 'Unknown Server',
              server_url: serverUrl || window.location.origin,
              server_url_display: cleanUrl,
              server_port: serverPort,
              deployed_version: data.server_info?.deployed_version || null,
              last_deploy_at: data.server_info?.last_deploy_at || null,
              deploy_state: data.server_info?.deploy_state || null,
              system_stats: data.server_info?.system_stats || null,
              service_health: data.server_info?.service_health || null,
            },
            frontend_info: data.frontend_info || null,
            // Stamp each host with the server it came from. A host registers a RELATIVE
            // host_url (/host/<name>) that only resolves correctly against its own proxy;
            // without this, selecting another server here builds stream/VNC URLs against
            // THIS origin and they 502 on a proxy that knows nothing about those hosts.
            hosts: (data.hosts || []).map((host: Host) => ({
              ...host,
              server_url: serverUrl || window.location.origin,
            }))
          };

          // Straight to the screen, without waiting for the other servers.
          publishServerEntry(serverData);

          return { success: true, serverUrl, data: serverData };
        } else {
          console.warn(`[@ServerManager] Failed response from ${serverUrl}: ${response.status}`);
          setFailedServers(prev => new Set(prev).add(serverUrl));
          return { success: false, serverUrl, data: null };
        }
      } catch (error: any) {
        console.warn(`[@ServerManager] Error from ${serverUrl}: ${error.message}`);
        setFailedServers(prev => new Set(prev).add(serverUrl));
        return { success: false, serverUrl, data: null };
      } finally {
        // Remove from pending
        setPendingServers(prev => {
          const newSet = new Set(prev);
          newSet.delete(serverUrl);
          return newSet;
        });
      }
    });

    // Wait for all requests to complete. Only to settle the round — every successful
    // server's data is already on screen.
    const results = await Promise.all(promises);

    const answered = new Set(
      results
        .filter((result) => result.success)
        .map((result) => result.serverUrl || window.location.origin),
    );

    // Drop the servers that did not answer this round: leaving their last-known hosts on
    // screen would present an unreachable server's devices as if they were live.
    setServerHostsData((prev) => {
      const next = prev.filter((entry) => answered.has(entry.server_info.server_url));
      return next.length === prev.length ? prev : next;
    });

    const finalData = displayOrder
      .filter((url) => answered.has(url))
      .map((url) => published.get(url))
      .filter((entry): entry is ServerHostData => Boolean(entry));

    lastDataSignatureRef.current = JSON.stringify(finalData);

    // Cache what answered. A partial round is still worth caching: the next load then
    // paints the servers that were reachable instead of nothing at all.
    if (finalData.length > 0) {
      try {
        const cacheData: CachedData = {
          data: finalData,
          timestamp: Date.now(),
        };
        localStorage.setItem(STORAGE_KEYS.SERVER_HOSTS_CACHE, JSON.stringify(cacheData));
      } catch (error) {
        console.warn('[@ServerManager] Failed to cache data:', error);
      }
    }

    setIsLoading(false);
    isRequestInProgress.current = false;
    hasLoadedOnceRef.current = true;
    })();
    inFlightFetchRef.current = fetchPromise.finally(() => {
      inFlightFetchRef.current = null;
    });
    return inFlightFetchRef.current;
  }, [availableServers, canFetch]);

  /**
   * Manual refresh function - forces a fresh fetch bypassing cache
   */
  const refreshServerData = useCallback(async (includeSystemStats = false) => {
    log('[@ServerManager] Manual refresh requested - bypassing cache');
    await fetchServerData(true, includeSystemStats);
  }, [fetchServerData]);

  // ========================================
  // EFFECTS
  // ========================================

  // Initial data fetch — deferred until auth resolves when auth is enabled.
  // Use the cached path (force_refresh=false) to avoid pinning the single Gunicorn
  // worker on a synchronous fan-out of /health checks across every host. The /system
  // socket subscription (below) pushes host_registered / host_unregistered events,
  // so any stale state is corrected within seconds without blocking the page load.
  useEffect(() => {
    if (availableServers.length > 0 && canFetch) {
      log('[@ServerManager] Initial data fetch');
      fetchServerData(false);
    }
  }, [canFetch]); // Re-run when auth state settles

  // Push updates for host/lock state via /system socket namespace.
  useEffect(() => {
    if (!canFetch) {
      if (refreshDebounceRef.current) {
        clearTimeout(refreshDebounceRef.current);
        refreshDebounceRef.current = null;
      }
      if (systemSocketRef.current) {
        systemSocketConnectedRef.current = false;
        systemSocketRef.current.disconnect();
        systemSocketRef.current = null;
      }
      return;
    }

    // TASK-113 PR-C: when the user picks "All servers", the picker's
    // value is the `ALL_SERVERS_SENTINEL` literal, not a real URL. The
    // system socket is a per-server stream — there is no `wss://__all__`
    // origin to connect to. Earlier this fell through to
    // `createServerSocket('__all__', '/system', ...)` and the browser
    // spammed `WebSocket connection to 'wss://__all__/...' failed`
    // on every reconnect cycle while the page was visibly slow and
    // devices showed empty (BUG-0571-edge). Skip the effect entirely
    // in ALL mode; the cached `serverHostsData` (refreshed every
    // 30 s, force-refreshed by manual `refreshServerData()`) is the
    // source of truth while there. Per-server sockets in ALL mode is
    // PR-E's job.
    if (isAllServersSentinel(selectedServer) || selectedServer === '') {
      return;
    }

    const serverBaseUrl = selectedServer || window.location.origin;
    const socket = createServerSocket(serverBaseUrl, '/system', {
      transports: ['websocket'],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
    });
    systemSocketRef.current = socket;

    // Minimum 10s between force refreshes to avoid hammering the API.
    const FORCE_REFRESH_COOLDOWN_MS = 10_000;

    const scheduleRefresh = (forceRefresh = true, includeSystemStats = false) => {
      // Enforce cooldown on force refreshes
      if (forceRefresh) {
        const now = Date.now();
        if (now - lastForceRefreshTimeRef.current < FORCE_REFRESH_COOLDOWN_MS) {
          return;
        }
        lastForceRefreshTimeRef.current = now;
      }

      if (refreshDebounceRef.current) {
        clearTimeout(refreshDebounceRef.current);
      }
      refreshDebounceRef.current = setTimeout(() => {
        fetchServerData(forceRefresh, includeSystemStats);
      }, 300);
    };

    // Only these events affect host/device topology and warrant a force refresh.
    const TOPOLOGY_EVENTS = new Set(['host_registered', 'host_unregistered', 'host_status_changed']);

    socket.on('system_update', (event: any) => {
      const eventType = event?.type || '';
      // host_ping is a heartbeat — it only nudges last_seen on the server, which is
      // already reflected in the next natural refresh. Subscribing to it here meant
      // every host's heartbeat scheduled its own /getAllHosts; that was the
      // dominant source of background traffic. Ignore it.
      // Lock changes are handled by HostManagerProvider's own socket subscription.
      if (eventType === 'host_ping' || eventType === 'lock_changed') {
        return;
      }
      // Topology changes (host register/unregister/status) need a force refresh.
      if (TOPOLOGY_EVENTS.has(eventType)) {
        scheduleRefresh(true, false);
        return;
      }
      // All other events (execution_update, deployment_changed, agent_*_changed, etc.)
      // don't affect host/device data — ignore them here.
    });

    socket.on('connect', () => {
      systemSocketConnectedRef.current = true;
      // Skip the redundant fetch on the FIRST connect — the initial useEffect above
      // already issued one. Only refresh on actual reconnects, where data may be stale.
      if (!hasHandledFirstConnectRef.current) {
        hasHandledFirstConnectRef.current = true;
        return;
      }
      scheduleRefresh(false);
    });

    socket.on('disconnect', () => {
      systemSocketConnectedRef.current = false;
    });

    return () => {
      if (refreshDebounceRef.current) {
        clearTimeout(refreshDebounceRef.current);
        refreshDebounceRef.current = null;
      }
      systemSocketConnectedRef.current = false;
      socket.disconnect();
      systemSocketRef.current = null;
    };
  }, [selectedServer, fetchServerData, canFetch]);

  // Note: No auto-switch from failed servers. The user explicitly chose a server
  // and the system should not silently override that choice due to transient failures.

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (serverChangeTimeoutRef.current) {
        clearTimeout(serverChangeTimeoutRef.current);
      }
      if (refreshDebounceRef.current) {
        clearTimeout(refreshDebounceRef.current);
        refreshDebounceRef.current = null;
      }
      if (systemSocketRef.current) {
        systemSocketConnectedRef.current = false;
        systemSocketRef.current.disconnect();
        systemSocketRef.current = null;
      }
    };
  }, []);

  // ========================================
  // CONTEXT VALUE
  // ========================================

  const contextValue = useMemo(
    () => ({
      // Server selection
      selectedServer,
      availableServers,
      setSelectedServer,

      // Server data
      serverHostsData,
      isLoading,
      error,
      pendingServers,
      failedServers,

      // Per-server auth state (TASK-18)
      serverAuthStates,

      // Server change transition state
      isServerChanging,

      // Actions
      refreshServerData,
      refreshServerAuth,
    }),
    [selectedServer, availableServers, setSelectedServer, serverHostsData, isLoading, error, refreshServerData, pendingServers, failedServers, isServerChanging, serverAuthStates, refreshServerAuth]
  );

  return (
    <ServerManagerContext.Provider value={contextValue}>
      {children}
    </ServerManagerContext.Provider>
  );
};

ServerManagerProvider.displayName = 'ServerManagerProvider';
