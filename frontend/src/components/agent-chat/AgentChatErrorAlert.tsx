import { Alert } from '@mui/material';
import React from 'react';

/**
 * The chat error / "Reconnecting to the server…" notice. Shared by the thread
 * view (ChatMessages) and the landing view (AgentChat empty state) so a send
 * from a brand-new chat shows the same feedback (BUG-0360).
 */
export const AgentChatErrorAlert: React.FC<{ error: string | null | undefined }> = ({ error }) =>
  error ? (
    <Alert severity="error" sx={{ mt: 1 }} onClose={() => {}} data-testid="agent-chat-error">
      {error}
    </Alert>
  ) : null;
