import React from 'react';
import { Box, Chip, Typography } from '@mui/material';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

/** Why Jev decided a Sherlock verdict (script_results.metadata.jev, written with the verdict). */
export interface JevReasons {
  decision_id?: string | null;
  choice: string;
  confidence?: number | null;
  probabilities?: Record<string, number>;
  runner_up?: string | null;
  evidence?: string[];
}

const CLASSES = ['VALID_PASS', 'VALID_FAIL', 'BUG', 'SCRIPT_ISSUE', 'SYSTEM_ISSUE', 'EXTERNAL_BLOCK'];

/** The jev block of a result or queue row, when it is a usable one. */
// Human label for script_results.check_type (who produced the verdict). Shared by the AI queue and Test Reports.
export const analysisTypeLabel = (checkType?: string | null): string => {
  switch (checkType) {
    case 'ai_auto_jev': return 'Jev (automatic)';
    case 'ai_auto_openrouter': return 'AI model (automatic)';
    case 'ai_strategy_skip': return 'Skipped by sampling policy';
    case 'ai_error': return 'AI analysis failed';
    case 'ai':
    case 'ai_agent': return 'AI Agent Analysis';
    case 'ai_and_human': return 'AI & Human Review';
    default: return 'Manual Review';
  }
};

export const getJev = (source?: { metadata?: any; jev?: any } | null): JevReasons | null => {
  const jev = source?.jev ?? source?.metadata?.jev;
  return jev && typeof jev === 'object' && typeof jev.choice === 'string' ? (jev as JevReasons) : null;
};

const pct = (p?: number | null) => `${Math.round((p || 0) * 100)} %`;

const JevWhy: React.FC<{ jev: JevReasons }> = ({ jev }) => {
  const P = useAgentChatPalette();
  const probs = jev.probabilities || {};
  const rows = [...new Set([...CLASSES, ...Object.keys(probs)])]
    .map((c) => [c, probs[c] || 0] as [string, number])
    .sort((a, b) => b[1] - a[1]);
  const verdictColor = (c: string) =>
    c === 'VALID_PASS' ? P.success : c === 'VALID_FAIL' || c === 'BUG' ? P.error : P.warning;
  const chosen = verdictColor(jev.choice);

  return (
    <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 1.5, bgcolor: P.surface, p: 1.5, mb: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.25, flexWrap: 'wrap' }}>
        <Chip
          size="small"
          label={jev.choice}
          sx={{ height: 22, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color: chosen,
                bgcolor: `${chosen}1f`, border: `1px solid ${chosen}66` }}
        />
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textSecondary }}>
          Jev, {pct(jev.confidence)} sure. No LLM call.
        </Typography>
      </Box>

      <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(96px, 120px) 1fr 40px', rowGap: 0.5, columnGap: 1,
                 alignItems: 'center', mb: jev.evidence?.length ? 1.5 : 0 }}>
        {rows.map(([c, p]) => {
          const isChosen = c === jev.choice;
          return (
            <React.Fragment key={c}>
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', fontWeight: isChosen ? 600 : 400,
                                color: isChosen ? P.textPrimary : P.textMuted }}>
                {c}
              </Typography>
              <Box sx={{ height: 6, borderRadius: 3, bgcolor: P.hoverBg, overflow: 'hidden' }}>
                <Box sx={{ height: '100%', width: `${Math.max(p * 100, p > 0 ? 1 : 0)}%`, borderRadius: 3,
                           bgcolor: isChosen ? chosen : P.textMuted, opacity: isChosen ? 1 : 0.6 }} />
              </Box>
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, textAlign: 'right', color: isChosen ? P.textPrimary : P.textMuted }}>
                {pct(p)}
              </Typography>
            </React.Fragment>
          );
        })}
      </Box>

      {!!jev.evidence?.length && (
        <Box>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 0.25 }}>Evidence</Typography>
          <Box component="ul" sx={{ m: 0, pl: 2.25, fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, wordBreak: 'break-word' }}>
            {jev.evidence.map((line, i) => (<li key={i}>{line}</li>))}
          </Box>
        </Box>
      )}

      {jev.decision_id && (
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', color: P.textMuted, mt: 1.25 }}>
          decision {jev.decision_id}
        </Typography>
      )}
    </Box>
  );
};

export default JevWhy;
