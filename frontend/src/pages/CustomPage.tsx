import { Add, Delete, Edit, Share } from '@mui/icons-material';
import { Alert, Box, Button, TextField, Typography } from '@mui/material';
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { AddBlockDialog } from '../components/customPages/AddBlockDialog';
import { BlockSettingsDialog } from '../components/customPages/BlockSettingsDialog';
import { CustomPageBody } from '../components/customPages/CustomPageBody';
import { PageRuntimeProvider } from '../components/customPages/PageRuntime';
import { ShareDialog } from '../components/customPages/ShareDialog';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { PageTitle, dangerButtonSx, neutralButtonSx, pageSurfaceSx, primaryButtonSx, toggleSx } from '../components/common/PageChrome';
import { EmptyState, QueryState } from '../components/reports/PageState';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { useCustomPage, useCustomPageMutations } from '../hooks/customPages/useCustomPages';
import { usePermissions } from '../hooks/auth/usePermissions';
import { describeError } from '../hooks/reports/runManagementApi';
import { useToast } from '../hooks/useToast';
import { useI18n } from '../i18n/useI18n';
import type { BlockType, PageBlock, PageOp } from '../types/customPages';

const GRID = 6;

/** Re-place blocks left to right, wrapping to a new row: the same rule the server uses when x is missing. */
const reflow = (blocks: PageBlock[]): PageBlock[] => {
  let cursor = 0;
  return blocks.map((b) => {
    const x = cursor + b.w <= GRID ? cursor : 0;
    cursor = x + b.w < GRID ? x + b.w : 0;
    return { ...b, x };
  });
};

const CustomPage: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { showError, showSuccess } = useToast();
  const { hasPermission } = usePermissions();
  const { data: page, isLoading, error } = useCustomPage(id);
  const { update, remove } = useCustomPageMutations();

  const [editing, setEditing] = useState(params.get('edit') === '1');
  const [adding, setAdding] = useState(false);
  const [settingsId, setSettingsId] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [title, setTitle] = useState('');

  useEffect(() => {
    if (page) setTitle(page.title);
  }, [page?.id, page?.title]);

  const canEdit = Boolean(page) && page!.access !== 'view' && hasPermission('pages.custom:edit');
  const isOwner = page?.access === 'owner';
  const blocks = page?.definition.blocks ?? [];

  const run = async (input: Parameters<typeof update.mutateAsync>[0]) => {
    try {
      await update.mutateAsync(input);
    } catch (e) {
      showError(describeError(e));
    }
  };
  const applyOps = (ops: PageOp[]) => run({ id: id!, ops });
  const applyBlocks = (next: PageBlock[]) => run({ id: id!, definition: { schema_version: page!.definition.schema_version, blocks: reflow(next) } });

  const addBlock = async (type: BlockType) => {
    setAdding(false);
    await run({ id: id!, ops: [{ op: 'add_block', type }] });
  };
  const moveBlock = (blockId: string, toIndex: number) => {
    const next = [...blocks];
    const from = next.findIndex((b) => b.id === blockId);
    const [item] = next.splice(from, 1);
    next.splice(toIndex, 0, item);
    applyBlocks(next);
  };
  const setWidth = (blockId: string, w: number) => applyBlocks(blocks.map((b) => (b.id === blockId ? { ...b, w } : b)));
  const saveSettings = async (blockId: string, changes: Record<string, string | number | boolean>) => {
    setSettingsId(null);
    const current = blocks.find((b) => b.id === blockId)?.settings ?? {};
    const ops: PageOp[] = Object.entries(changes)
      .filter(([key, value]) => current[key] !== value)
      .map(([key, value]) => ({ op: 'set_setting', id: blockId, key, value }));
    if (ops.length) await applyOps(ops);
  };
  const renameIfChanged = () => {
    if (page && title.trim() && title.trim() !== page.title) run({ id: id!, title: title.trim() });
  };
  const leaveEdit = () => {
    renameIfChanged();
    setEditing(false);
    if (params.get('edit')) {
      params.delete('edit');
      setParams(params, { replace: true });
    }
  };
  const savePage = async () => {
    await run({ id: id!, status: 'saved' });
    showSuccess(t('Page saved'));
  };
  const deleteIt = async () => {
    setConfirmDelete(false);
    try {
      await remove.mutateAsync(id!);
      navigate('/pages');
    } catch (e) {
      showError(describeError(e));
    }
  };

  return (
    <Box sx={[{ width: '100%', minWidth: 0, py: 2 }, ...([pageSurfaceSx(P)] as never[])]}>
      <QueryState loading={isLoading} error={error}>
        {page && (
          <PageRuntimeProvider pageId={page.id}>
            <PageTitle
              title={
                editing && canEdit ? (
                  <TextField
                    size="small"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    onBlur={renameIfChanged}
                    inputProps={{ 'aria-label': t('Page title'), maxLength: 120 }}
                    sx={{ minWidth: 280 }}
                  />
                ) : (
                  page.title
                )
              }
              subtitle={page.status === 'draft' ? t('Draft, only you can see it') : page.access === 'owner' ? (page.visibility === 'team' ? t('Shared with the team') : t('Private')) : t('Shared with you')}
              right={
                <>
                  {canEdit && (
                    <Button size="small" startIcon={<Edit />} onClick={() => (editing ? leaveEdit() : setEditing(true))} sx={toggleSx(P, editing)}>
                      {editing ? t('Done') : t('Edit page')}
                    </Button>
                  )}
                  {isOwner && page.status === 'saved' && (
                    <Button size="small" startIcon={<Share />} onClick={() => setSharing(true)} sx={neutralButtonSx(P)}>
                      {t('Share')}
                    </Button>
                  )}
                  {isOwner && (
                    <Button size="small" startIcon={<Delete />} onClick={() => setConfirmDelete(true)} sx={dangerButtonSx(P)}>
                      {t('Delete')}
                    </Button>
                  )}
                </>
              }
            />
            {page.status === 'draft' && isOwner && (
              <Alert
                severity="info"
                sx={{ mb: 1.5 }}
                action={
                  <Button size="small" variant="contained" onClick={savePage} sx={primaryButtonSx(P)}>
                    {t('Save page')}
                  </Button>
                }
              >
                {t('This is a draft. Check it, then save it to keep it and share it. Delete it to discard it.')}
              </Alert>
            )}
            {editing && canEdit && (
              <Box sx={{ mb: 1.5 }}>
                <Button size="small" variant="contained" startIcon={<Add />} onClick={() => setAdding(true)} sx={primaryButtonSx(P)}>
                  {t('Add block')}
                </Button>
              </Box>
            )}
            {blocks.length === 0 ? (
              <EmptyState message={canEdit ? t('This page is empty. Add a block, or ask Atlas to build the page for you.') : t('This page is empty.')} />
            ) : (
              <CustomPageBody
                blocks={blocks}
                states={page.block_states}
                editing={editing && canEdit}
                onMove={moveBlock}
                onWidth={setWidth}
                onRemove={(blockId) => applyOps([{ op: 'remove_block', id: blockId }])}
                onSettings={setSettingsId}
              />
            )}
            <AddBlockDialog open={adding} onClose={() => setAdding(false)} onAdd={addBlock} />
            <BlockSettingsDialog block={blocks.find((b) => b.id === settingsId) ?? null} blocks={blocks} onClose={() => setSettingsId(null)} onSave={saveSettings} />
            {isOwner && <ShareDialog pageId={page.id} title={page.title} open={sharing} onClose={() => setSharing(false)} />}
            <ConfirmDialog
              open={confirmDelete}
              title={t('Delete page')}
              message={t('Delete "{title}"? This cannot be undone.', { title: page.title })}
              confirmText={t('Delete')}
              confirmColor="error"
              onConfirm={deleteIt}
              onCancel={() => setConfirmDelete(false)}
            />
          </PageRuntimeProvider>
        )}
      </QueryState>
      {!page && !isLoading && !error && <Typography>{t('Page not found.')}</Typography>}
    </Box>
  );
};

export default CustomPage;
