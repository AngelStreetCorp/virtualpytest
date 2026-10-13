import type {
  AnalyticsArtifactSpec,
  AnalyticsCanvasSpec,
  AnalyticsVisualizationSpec,
} from './AnalyticsArtifactViewer';

/** What Agent Chat keeps for the Analytics tab; `turn` = index of the user message that started the turn. */
export interface MergeableAnalyticsContent {
  title?: string;
  data: { artifact_spec?: AnalyticsArtifactSpec };
  turn?: number;
}

const panelsOf = (spec: AnalyticsArtifactSpec): AnalyticsVisualizationSpec[] =>
  spec.kind === 'canvas' ? spec.panels : [spec];

const panelKey = (p: AnalyticsVisualizationSpec) => `${p.title}\u0000${p.data?.source_id ?? ''}`;

/**
 * Atlas sometimes renders each chart with its own call. Within one agent turn, fold the artifacts
 * into ONE canvas (same title+source replaces that panel); a new turn starts fresh.
 */
export function mergeAnalyticsArtifact<T extends MergeableAnalyticsContent>(
  prev: T | null,
  incoming: { title?: string; data: T['data'] },
  turn: number,
): T {
  const next = { title: incoming.title, data: incoming.data, turn } as T;
  const prevSpec = prev?.data?.artifact_spec;
  const newSpec = incoming.data?.artifact_spec;
  if (!prev || prev.turn !== turn || !prevSpec || !newSpec) return next;

  const panels = [...panelsOf(prevSpec)];
  for (const panel of panelsOf(newSpec)) {
    const idx = panels.findIndex((p) => panelKey(p) === panelKey(panel));
    if (idx >= 0) panels[idx] = panel;
    else panels.push(panel);
  }
  if (panels.length === 1 && newSpec.kind !== 'canvas' && prevSpec.kind !== 'canvas') return next;

  const base = prevSpec.kind === 'canvas' ? prevSpec : undefined;
  const title = base?.title || 'Analytics canvas';
  const canvas: AnalyticsCanvasSpec = {
    schema: 'vpt-artifact/v1',
    kind: 'canvas',
    title,
    layout: base?.layout ?? { columns: panels.length >= 3 ? 2 : (panels.length as 1 | 2) },
    panels,
    // The draft matches the newest call's panels only; once panels were merged it would be stale.
    ...(newSpec.kind === 'canvas' && newSpec.grafana && newSpec.panels.length === panels.length ? { grafana: newSpec.grafana } : {}),
  };
  return { title, data: { ...incoming.data, artifact_spec: canvas }, turn } as T;
}
