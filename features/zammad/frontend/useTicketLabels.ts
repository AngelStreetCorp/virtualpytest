/**
 * Every word the ticket form and the ticket list show for the model's keys. One place, literal t() calls,
 * so the i18n check sees them all and fr/de stay complete.
 */
import { useMemo } from 'react';

import { useI18n } from '../../../frontend/src/i18n/useI18n';
import type { ReporterStatus, TicketType } from './ticketModel';

export const useTicketLabels = () => {
  const { t } = useI18n();
  return useMemo(() => {
    const label: Record<string, string> = {
      incident: t('Incident'), bug: t('Bug'), request: t('Request'), question: t('Question'),
      blocker: t('Blocker'), major: t('Major'), minor: t('Minor'),
      P0: t('P0 High'), P1: t('P1 Medium'), P2: t('P2 Low'),
      always: t('Always'), frequent: t('Frequent'), random: t('Random'), once: t('Seen once'),
      platform: t('Platform'), scripting: t('Scripting'), monitoring: t('Monitoring'),
      dashboards: t('Dashboards'), ai: t('AI'),
      server: t('Server'), host: t('Host'), device: t('Device'), service: t('Service'),
      script: t('Script'), campaign: t('Campaign'), virtual_script: t('Virtual script'), testcase: t('Testcase'),
      heatmap: t('Heatmap'), timeline: t('Timeline'), grafana: t('Grafana'), report: t('Report'),
      agent: t('Agent'),
    };
    // 'incident' is also a monitoring category: the word is the same, one entry serves both.
    const status: Record<ReporterStatus, string> = {
      open: t('Open'), in_progress: t('In progress'), waiting: t('Waiting for you'),
      delivered: t('Delivered, please check'), closed: t('Closed'),
    };
    /** The description a ticket of this type starts from; the user fills it in. */
    const template: Record<TicketType, string> = {
      incident: `${t('What is broken')}:\n\n${t('Since when')}:\n\n${t('Who is blocked')}:\n`,
      bug: `${t('Steps')}:\n\n${t('Expected')}:\n\n${t('Actual')}:\n\n${t('Run or report link')}:\n`,
      request: `${t('What you want')}:\n\n${t('Why')}:\n`,
      question: `${t('Your question')}:\n\n${t('What you tried')}:\n`,
    };
    return { label, status, template };
  }, [t]);
};
