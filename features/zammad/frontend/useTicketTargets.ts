/**
 * The real list behind the form's Target dropdown, per category, from sources the app already has:
 *   server                      the servers the app knows (ServerManager: getAllHosts)
 *   host                        their hosts
 *   device, heatmap, timeline,  the devices of those hosts (heatmaps, timelines and incidents are per device)
 *   incident
 *   service                     the vpt-* units on the Status page (service_health of each server and host)
 *   script, virtual_script,     GET /server/executable/list, the library the executable pickers use
 *   testcase
 *   campaign                    GET /server/campaigns/listExecutables, the campaign picker's list
 *   grafana                     utils/grafanaDashboards.ts, the Grafana page's list
 *   report                      the latest script results (their report is the thing to point at)
 *   agent                       GET /server/agents/overview, the agent dashboard's list
 * A source that fails or is empty gives an empty list: Target is optional, the form keeps working.
 */
import { useEffect, useMemo, useState } from 'react';

import { api } from '../../../frontend/src/utils/apiClient';
import { buildServerUrl } from '../../../frontend/src/utils/buildUrlUtils';
import { getCachedCampaignExecutableList, getCachedExecutableList } from '../../../frontend/src/utils/executionListCache';
import { GRAFANA_DASHBOARDS } from '../../../frontend/src/utils/grafanaDashboards';
import { buildServerPickerLabels } from '../../../frontend/src/utils/serverLabels';
import { useServerManager } from '../../../frontend/src/hooks/useServerManager';
import type { Category, TicketTarget } from './ticketModel';

const RECENT_REPORTS = 30;

const byLabel = (a: TicketTarget, b: TicketTarget) => a.label.localeCompare(b.label);

/** Items of the executable library as targets: scripts (disk), virtual scripts (DB), testcases. */
async function executableTargets(category: Category): Promise<TicketTarget[]> {
  const data = await getCachedExecutableList(buildServerUrl('/server/executable/list'));
  const items: any[] = (data?.folders ?? []).flatMap((folder: any) => folder.items ?? []);
  return items
    .filter((item) =>
      category === 'testcase'
        ? item.type === 'testcase'
        : item.type === 'script' && Boolean(item.is_virtual) === (category === 'virtual_script'),
    )
    .map((item) => ({ id: String(item.id), label: String(item.name || item.id) }));
}

async function campaignTargets(): Promise<TicketTarget[]> {
  const data = await getCachedCampaignExecutableList(
    buildServerUrl('/server/campaigns/listExecutables?include_hidden=true'),
  );
  return (data?.campaigns ?? []).map((c: any) => {
    const id = String(c.id || c.campaign_id);
    return { id, label: String(c.name || c.campaign_name || id) };
  });
}

async function reportTargets(): Promise<TicketTarget[]> {
  const rows = await api.get(`${buildServerUrl('/server/script-results/getAllScriptResults')}&limit=${RECENT_REPORTS}`);
  return (Array.isArray(rows) ? rows : []).map((r: any) => ({
    id: String(r.id),
    label: `${r.script_name}${r.started_at ? ` · ${String(r.started_at).slice(0, 16).replace('T', ' ')}` : ''}`,
  }));
}

async function agentTargets(): Promise<TicketTarget[]> {
  const data = await api.get(buildServerUrl('/server/agents/overview?hours=24'));
  return (data?.agents ?? []).map((a: any) => ({ id: String(a.id), label: String(a.name || a.id) }));
}

export const useTicketTargets = (category: Category | ''): { targets: TicketTarget[]; loading: boolean } => {
  const { serverHostsData } = useServerManager();
  const [remote, setRemote] = useState<{ category: string; targets: TicketTarget[] } | null>(null);
  const [loading, setLoading] = useState(false);

  // Lists that are already in the app's host data: no request.
  const local = useMemo<TicketTarget[] | null>(() => {
    // Host names collide across servers (node1 and node3 both have host-clone-1): with more than one
    // server every host-derived target carries the server's picker name, and its id the server URL.
    const urls = serverHostsData.map((sd) => sd.server_info.server_url);
    const names = buildServerPickerLabels(urls, (url) => {
      const info = serverHostsData.find((sd) => sd.server_info.server_url === url)?.server_info;
      return info?.server_name || url.replace(/^https?:\/\//, '');
    });
    const multi = serverHostsData.length > 1;
    const entries = serverHostsData.map((sd) => {
      const url = sd.server_info.server_url;
      return { sd, url, name: names[url] ?? sd.server_info.server_name };
    });
    const suffix = (label: string, name: string) =>
      multi && !label.endsWith(` · ${name}`) ? `${label} · ${name}` : label;
    const idOf = (id: string, url: string) => (multi ? `${url}|${id}` : id);
    switch (category) {
      case 'server':
        return entries.map((e) => ({ id: e.url, label: e.name }));
      case 'host':
        return entries.flatMap((e) =>
          e.sd.hosts.map((h) => ({ id: idOf(h.host_name, e.url), label: suffix(h.host_name, e.name) })),
        );
      case 'device':
      case 'heatmap':
      case 'timeline':
      case 'incident':
        return entries.flatMap((e) =>
          e.sd.hosts.flatMap((h) =>
            (h.devices ?? []).map((d) => ({
              id: idOf(`${h.host_name}:${d.device_id}`, e.url),
              label: suffix(`${d.device_name || d.device_id} · ${h.host_name}`, e.name),
            })),
          ),
        );
      case 'service':
        return entries.flatMap((e) => [
          ...(e.sd.server_info.service_health?.services ?? []).map((s) => ({
            id: idOf(`${e.sd.server_info.server_name}/${s.name}`, e.url),
            label: suffix(`${s.label || s.name} · ${e.name}`, e.name),
          })),
          ...e.sd.hosts.flatMap((h) =>
            (h.system_stats?.service_health?.services ?? []).map((s) => ({
              id: idOf(`${h.host_name}/${s.name}`, e.url),
              label: suffix(`${s.label || s.name} · ${h.host_name}`, e.name),
            })),
          ),
        ]);
      case 'grafana':
        return GRAFANA_DASHBOARDS.map((d) => ({ id: d.uid, label: d.title }));
      default:
        return null;
    }
  }, [category, serverHostsData]);

  useEffect(() => {
    if (!category || local) {
      setLoading(false);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    const load =
      category === 'campaign' ? campaignTargets()
        : category === 'report' ? reportTargets()
          : category === 'agent' ? agentTargets()
            : executableTargets(category);
    load
      .then((targets) => !cancelled && setRemote({ category, targets }))
      .catch(() => !cancelled && setRemote({ category, targets: [] }))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [category, local]);

  const targets = useMemo(() => {
    const list = local ?? (remote && remote.category === category ? remote.targets : []);
    return [...list].sort(byLabel);
  }, [local, remote, category]);
  return { targets, loading };
};
