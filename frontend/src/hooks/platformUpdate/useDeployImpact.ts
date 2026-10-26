import { useCallback, useEffect, useState } from 'react';

import { fetchDeployImpact, type DeployImpact } from './platformUpdateActions';
import type { RunStep, UpdateRun } from './usePlatformUpdateRun';

/**
 * TASK-128 G12: what the deploy changed (per machine, migrations) once it failed, was aborted, or waits for the server
 * restart. Reloaded whenever the roll back moves (the run is polled by the page; this follows its signature).
 */
export const useDeployImpact = (run: UpdateRun | null, deploy: RunStep, migrations: RunStep) => {
  const [impact, setImpact] = useState<DeployImpact | null>(null);
  const job = deploy.data.job as { state?: string } | undefined;
  const rollback = deploy.data.rollback as { state?: string; actions?: { state: string }[] } | undefined;
  const wanted =
    Boolean(run) && !run?.legacy && (deploy.state === 'failed' || (deploy.state === 'running' && job?.state === 'awaiting_confirmation'));
  const signature = [
    run?.id, deploy.state, job?.state, rollback?.state, (rollback?.actions ?? []).map((a) => a.state).join(','),
    ((migrations.data.rolled_back as string[] | undefined) ?? []).length, Boolean(deploy.data.partial),
  ].join('|');

  const reload = useCallback(async () => {
    if (!run) return;
    try {
      setImpact(await fetchDeployImpact(run.id));
    } catch {
      setImpact(null);
    }
  }, [run?.id]);  

  useEffect(() => {
    if (wanted) void reload();
    else setImpact(null);
  }, [wanted, signature, reload]);

  return { impact: wanted ? impact : null, reloadImpact: reload };
};
