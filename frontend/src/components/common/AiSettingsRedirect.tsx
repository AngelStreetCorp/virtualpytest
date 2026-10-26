import React from 'react';
import { Navigate } from 'react-router-dom';

/**
 * The OpenRouter debug page was retired with the AI unification (the backend
 * route it called, `POST /server/ai-tools/debug/openrouter`, was removed in
 * `8b4dce04b`). The tool itself lives on in Settings → AI, where an endpoint
 * can be tested against a model and the raw answer is shown.
 *
 * The old address redirects there, so a bookmark still lands on the working
 * tool instead of on a page that answers 400 for every click (BUG-0797).
 */
export const AiSettingsRedirect: React.FC = () => (
  <Navigate to="/configuration/settings?tab=ai" replace />
);

export default AiSettingsRedirect;
