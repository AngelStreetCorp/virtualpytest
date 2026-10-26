import { Box, ButtonBase, CircularProgress } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

import {
  CorrectionNode,
  LocalizeCorrectionBanner,
  LocalizeCorrectionQuestion,
  useLocalizeCorrection,
} from './LocalizeCorrectionDialog';

export interface RunForCorrection {
  userinterface_name: string;
  tree_id: string | null;
  live_fingerprint?: unknown;
  matched_node_id: string | null;
  frame_url: string | null;
  host_name: string;
  device_id: string | null;
}

/** "Wrong screen?" on a stored match run: the Localize picker, fed with the run's own fingerprint. */
export const RunWrongScreen: React.FC<{ run: RunForCorrection; teamId: string }> = ({ run, teamId }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [nodes, setNodes] = useState<CorrectionNode[]>([]);
  const [asking, setAsking] = useState(false);
  const [loading, setLoading] = useState(false);
  const labelOf = (id: string) => nodes.find((n) => n.node_id === id)?.label ?? id;
  const { answered, save, undo } = useLocalizeCorrection({
    userinterfaceName: run.userinterface_name,
    liveFingerprint: run.live_fingerprint ?? null,
    claimedNodeId: run.matched_node_id,
    frameUrl: run.frame_url,
    hostName: run.host_name,
    deviceId: run.device_id,
    labelOf,
  });

  const open = async () => {
    setAsking(true);
    if (!run.tree_id || nodes.length > 0) return;
    setLoading(true);
    try {
      const res = (await api.get(
        buildServerUrl(`/server/navigationTrees/${run.tree_id}/nodes?team_id=${encodeURIComponent(teamId)}&limit=500`),
      )) as { nodes?: { node_id: string; label?: string }[] };
      setNodes(
        (res.nodes ?? [])
          .filter((n) => n.node_id && n.label)
          .map((n) => ({ node_id: n.node_id, label: String(n.label) }))
          .sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase())),
      );
    } catch {
      setNodes([]);
    } finally {
      setLoading(false);
    }
  };

  if (answered) return <LocalizeCorrectionBanner answered={answered} onUndo={() => void undo()} bordered={false} />;
  if (asking) {
    return loading ? (
      <CircularProgress size={16} sx={{ color: P.accent }} />
    ) : (
      <Box sx={{ minWidth: 220 }}>
        <LocalizeCorrectionQuestion
          primary={[]}
          others={nodes.filter((n) => n.node_id !== run.matched_node_id)}
          bordered={false}
          onSave={(pick) => {
            setAsking(false);
            void save(pick);
          }}
          onCancel={() => setAsking(false)}
        />
      </Box>
    );
  }
  return (
    <ButtonBase
      onClick={() => void open()}
      sx={{ fontSize: TYPOGRAPHY.caption.size, textDecoration: 'underline', color: P.textSecondary }}
    >
      {t('Wrong screen?')}
    </ButtonBase>
  );
};
