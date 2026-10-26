import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import { Autocomplete, Box, Button, CircularProgress, MenuItem, Select, TextField, Typography } from '@mui/material';
import React, { useEffect, useMemo, useState } from 'react';
import { ReactFlowProvider } from 'reactflow';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { NavigationConfigProvider } from '../../contexts/navigation/NavigationConfigContext';
import { NavigationEditorProvider } from '../../contexts/navigation/NavigationEditorProvider';
import { NavigationPreviewCacheProvider } from '../../contexts/navigation/NavigationPreviewCacheContext';
import { NavigationStackProvider } from '../../contexts/navigation/NavigationStackContext';
import { useMetrics } from '../../hooks/navigation/useMetrics';
import { useNavigationEditor } from '../../hooks/navigation/useNavigationEditor';
import { useUserInterface } from '../../hooks/pages/useUserInterface';
import { useUserInterfaceVariants } from '../../hooks/userinterface/useUserInterfaceVariants';
import { useI18n } from '../../i18n/useI18n';
import { Device, Host } from '../../types/common/Host_Types';
import type { UINavigationNode } from '../../types/pages/Navigation_Types';
import type { UserInterface } from '../../types/pages/UserInterface_Types';
import { primaryButtonSx } from '../common/PageChrome';
import { NodeGotoPanel } from '../navigation/Navigation_NodeGotoPanel';
import { RecOverlayPanel } from './RecOverlayPanel';
import { TYPOGRAPHY } from '../../constants/typography';

const BASE = '__base__';

interface RecGotoNodePanelProps {
  host: Host;
  device: Device;
  isControlActive: boolean;
  onClose: () => void;
  /** Render in the page flow (custom pages) instead of the absolute overlay of the stream modal. */
  inline?: boolean;
}

const nodeLabel = (n: UINavigationNode): string => n.data.display_name || n.data.label || n.id;

const Content: React.FC<RecGotoNodePanelProps> = ({ host, device, isControlActive, onClose, inline = false }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { getAllUserInterfaces } = useUserInterface();
  const { nodes, edges, loadTreeByUserInterface, setUserInterfaceFromProps } = useNavigationEditor();
  const { getDevicePosition, setControlState } = useDeviceData();

  // Same as NavigationTreeViewer: publish the device so positions and actions are stored/loaded.
  useEffect(() => {
    setControlState(host, device.device_id, isControlActive);
    return () => setControlState(null, null, false);
  }, [host, device.device_id, isControlActive, setControlState]);

  const [interfaces, setInterfaces] = useState<UserInterface[]>([]);
  const [uiId, setUiId] = useState<string>('');
  const [variant, setVariant] = useState<string>(BASE);
  const [treeId, setTreeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<UINavigationNode | null>(null);

  const { variants } = useUserInterfaceVariants(uiId || null);

  useEffect(() => {
    let cancelled = false;
    getAllUserInterfaces()
      .then((list) => {
        if (cancelled) return;
        const sorted = [...(list || [])].sort((a, b) => a.name.localeCompare(b.name));
        setInterfaces(sorted);
        const preferred = sorted.find((u) => u.name === device.preferred_userinterface);
        if (preferred) {
          setUiId(preferred.id);
          if (device.preferred_variant) setVariant(device.preferred_variant);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const ui = interfaces.find((u) => u.id === uiId);
    if (!ui) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelected(null);
    setTreeId(null);
    setUserInterfaceFromProps(ui as any);
    loadTreeByUserInterface(ui.id, { variant: variant === BASE ? null : variant })
      .then((res) => {
        if (!cancelled) {
          setTreeId(res?.tree?.id || null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [uiId, variant, interfaces]);

  // Same metrics source as the userinterface page (duration estimate in the path preview).
  const metricsHook = useMetrics({ treeId, nodes, edges, enabled: !!treeId });
  // Same source as the userinterface page: the per-device position kept in DeviceDataContext.
  const currentNodeId = treeId ? getDevicePosition(host, device.device_id, treeId)?.nodeId : undefined;

  const options = useMemo(() => nodes.filter((n) => n.data.type !== 'entry'), [nodes]);

  const nodePicker = (
      <Autocomplete
          size="small"
          options={options}
          value={selected}
          disabled={!treeId || loading}
          getOptionLabel={nodeLabel}
          isOptionEqualToValue={(a, b) => a.id === b.id}
          onChange={(_, v) => setSelected(v)}
          noOptionsText={t('No nodes')}
          renderInput={(params) => (
            <TextField {...params} placeholder={t('Search a node')} sx={{ '& .MuiInputBase-root': { fontSize: TYPOGRAPHY.caption.size } }} />
          )}
        />
  );

  const body = (
    <>
      {/* mb: 1 — RecOverlayPanel's body is a plain block, so the picker row below needs its own gap */}
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 1 }}>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Select
            size="small"
            displayEmpty
            value={uiId}
            onChange={(e) => {
              setUiId(e.target.value);
              setVariant(BASE);
            }}
            sx={{ flex: 1, minWidth: 0, fontSize: TYPOGRAPHY.caption.size }}
            renderValue={(v) => (v ? interfaces.find((u) => u.id === v)?.name : t('User interface'))}
          >
            {interfaces.map((u) => (
              <MenuItem key={u.id} value={u.id}>
                {u.name}
              </MenuItem>
            ))}
          </Select>
          <Select
            size="small"
            value={variant}
            disabled={!uiId}
            onChange={(e) => setVariant(e.target.value)}
            sx={{ width: 130, fontSize: TYPOGRAPHY.caption.size }}
            renderValue={(v) => (v === BASE ? t('Base') : v)}
          >
            <MenuItem value={BASE}>{t('Base')}</MenuItem>
            {variants.map((v) => (
              <MenuItem key={v.name} value={v.name}>
                {v.name}
              </MenuItem>
            ))}
          </Select>
        </Box>
        {loading && <CircularProgress size={18} sx={{ alignSelf: 'center', color: P.accent }} />}
        {error && (
          <Typography variant="caption" sx={{ color: P.error }}>
            {error}
          </Typography>
        )}
      </Box>
      {selected && treeId ? (
        <NodeGotoPanel
          key={`${treeId}:${selected.id}`}
          selectedNode={selected}
          nodes={nodes}
          treeId={treeId}
          currentNodeId={currentNodeId}
          edgeMetrics={metricsHook.edgeMetrics}
          nodeMetrics={metricsHook.nodeMetrics}
          onClose={onClose}
          selectedHost={host}
          selectedDeviceId={device.device_id}
          isControlActive={isControlActive}
          variant={variant === BASE ? null : variant}
          embedded
          leading={nodePicker}
        />
      ) : (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>{nodePicker}</Box>
          <Button
            variant="contained"
            size="small"
            startIcon={<PlayArrowIcon />}
            disabled
            sx={{ ...(primaryButtonSx(P) as object), alignSelf: 'stretch', fontSize: TYPOGRAPHY.caption.size, py: 0, minWidth: 0 }}
          >
            {t('Run')}
          </Button>
        </Box>
      )}

    </>
  );

  return inline ? <Box>{body}</Box> : <RecOverlayPanel title={t('Go to node')} onClose={onClose}>{body}</RecOverlayPanel>;
};

export const RecGotoNodePanel: React.FC<RecGotoNodePanelProps> = (props) => (
  <ReactFlowProvider>
    <NavigationConfigProvider>
      <NavigationPreviewCacheProvider>
        <NavigationEditorProvider>
          <NavigationStackProvider>
            <Content {...props} />
          </NavigationStackProvider>
        </NavigationEditorProvider>
      </NavigationPreviewCacheProvider>
    </NavigationConfigProvider>
  </ReactFlowProvider>
);

export default RecGotoNodePanel;
