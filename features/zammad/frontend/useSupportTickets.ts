import { useCallback, useState } from 'react';

import { api } from '../../../frontend/src/utils/apiClient';
import { buildServerUrl } from '../../../frontend/src/utils/buildUrlUtils';
import type { SupportAttachment } from './reportIncident';
import type { Category, Family, Frequency, Priority, ReporterStatus, Severity, TicketType } from './ticketModel';

export interface SupportTicket {
  id: string;
  team_id: string;
  ticket_type: TicketType;
  family: Family;
  category: Category;
  target_id: string | null;
  target_label: string | null;
  severity: Severity | null;
  priority: Priority;
  frequency: Frequency;
  title: string;
  /** Workflow status (lib/model.py STATUSES). */
  status: string;
  /** What the reporter sees: Open / In progress / Waiting for you / Delivered / Closed. */
  reporter_status: ReporterStatus;
  external_number: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  created_by_email: string | null;
  /** Agent-side link in Zammad, or null when no URL is configured. */
  zammad_url?: string | null;
}

export interface CreateTicketInput {
  ticket_type: TicketType;
  family: Family;
  category: Category;
  frequency: Frequency;
  priority: Priority;
  /** Only for incident and bug. */
  severity?: Severity;
  target_id?: string;
  target_label?: string;
  title: string;
  description: string;
  attachments?: SupportAttachment[];
}

export const useSupportTickets = () => {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createTicket = useCallback(async (input: CreateTicketInput): Promise<SupportTicket | null> => {
    setIsSubmitting(true);
    setError(null);
    try {
      const data = await api.post(buildServerUrl('/server/zammad/tickets'), input);
      if (!data?.success) {
        setError(data?.error || 'Request failed');
        return null;
      }
      return data.ticket as SupportTicket;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed');
      return null;
    } finally {
      setIsSubmitting(false);
    }
  }, []);

  return { createTicket, isSubmitting, error, clearError: () => setError(null) };
};
