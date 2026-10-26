import { AppIcon } from '../../constants/icons';
import React from 'react';
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Checkbox, CircularProgress, FormControlLabel, MenuItem, Select, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import UploadFileIcon from '@mui/icons-material/UploadFile';

import { CodeDeploymentState, gitRepositoryName } from '../../hooks/platformUpdate/useCodeDeployment';
import { dangerButtonSx } from '../common/PageChrome';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

// The former Code deployment sections, unchanged apart from their titles. Rendered inside steps 1 and 2.

interface PanelProps {
  d: CodeDeploymentState;
}

export const SourcePanel: React.FC<PanelProps> = ({ d }) => {
  const P = useAgentChatPalette();
  const { gitRef, setGitRef, activeGitBranch, sourceMode, setSourceMode, detectedGit, pathExists, gitBranches, uploadId, uploadFilename, zipValidated, sourceVersionInfo, sourceDiffEntries, originUrl, remoteUrlDraft, setRemoteUrlDraft, needsGitReset, isSubmitting, fileInputRef, originOptions, reconfigureGitRemote, prepareGitSource, uploadZip, validateZip, applyZipToStorage, sectionAccordionSx } = d;
  return (
    <>
      <Accordion defaultExpanded sx={sectionAccordionSx}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Box sx={{ display: 'flex', alignItems: 'center', width: '100%', gap: 1 }}>
            <Typography sx={{ fontWeight: 600 }}>Source</Typography>
            {pathExists ? (
              <Box sx={{ ml: 'auto' }} onClick={(event) => event.stopPropagation()}>
                <ToggleButtonGroup
                  exclusive
                  size="small"
                  value={sourceMode}
                  onChange={(_, nextMode: 'git' | 'zip' | null) => nextMode && setSourceMode(nextMode)}
                  aria-label="Deployment source type"
                >
                  {detectedGit ? <ToggleButton value="git">Git</ToggleButton> : null}
                  <ToggleButton value="zip">ZIP</ToggleButton>
                </ToggleButtonGroup>
              </Box>
            ) : null}
          </Box>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0.25, pb: 0.75, px: 1.5 }}>
          {!pathExists && !isSubmitting ? (
            <Typography variant="body2" color="error.main" sx={{ mb: 0.75 }}>
              Source storage is not reachable from server.
            </Typography>
          ) : null}

          {pathExists && detectedGit && sourceMode === 'git' ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 0.5 }}>
              <Typography variant="caption" color="success.main" sx={{ whiteSpace: 'nowrap' }}>
                {`Current: ${gitRepositoryName(originUrl)} · ${activeGitBranch || 'unknown'} · ${sourceVersionInfo.current || 'unknown'}`}
              </Typography>
              <TextField
                select
                label="Origin"
                size="small"
                value={remoteUrlDraft}
                onChange={(event) => setRemoteUrlDraft(event.target.value)}
                sx={{ minWidth: 190 }}
                disabled={isSubmitting || originOptions.length === 0}
                SelectProps={{
                  renderValue: (value) => {
                    const repository = originOptions.find((entry) => entry.url === value);
                    return repository
                      ? `${repository.name}${repository.url === originUrl ? ' (origin)' : ''}`
                      : 'Select origin';
                  },
                }}
              >
                <MenuItem value="" disabled>
                  Select an approved repository
                </MenuItem>
                {originOptions.map((repository) => (
                  <MenuItem key={repository.url} value={repository.url}>
                    {repository.url === originUrl ? <AppIcon name="success" /> : ''}{repository.name}
                  </MenuItem>
                ))}
              </TextField>
              <Button
                variant="outlined"
                size="small"
                onClick={reconfigureGitRemote}
                disabled={isSubmitting || !remoteUrlDraft.trim() || remoteUrlDraft.trim() === originUrl}
              >
                {isSubmitting ? <CircularProgress size={16} color="inherit" /> : 'Reconfigure'}
              </Button>
                <TextField
                  select
                  label="Branch"
                  size="small"
                  value={gitRef}
                  onChange={(event) => setGitRef(event.target.value)}
                  sx={{ minWidth: 150 }}
                >
                  {(gitBranches.length > 0 ? gitBranches : [gitRef]).map((branch) => (
                    <MenuItem key={branch} value={branch}>
                      {branch}
                    </MenuItem>
                  ))}
                </TextField>
                <Button variant="contained" size="small" onClick={() => prepareGitSource()} disabled={isSubmitting || !gitRef.trim()}>
                  {isSubmitting ? <CircularProgress size={16} color="inherit" /> : 'Fetch & pull'}
                </Button>
                {activeGitBranch && gitRef !== activeGitBranch ? (
                  <Typography variant="caption" color="error.main" sx={{ whiteSpace: 'nowrap' }}>
                    {`Target: ${gitRef}`}
                  </Typography>
                ) : null}
              {needsGitReset ? (
                <Button size="small" onClick={() => prepareGitSource(true)} disabled={isSubmitting || !gitRef.trim()} sx={dangerButtonSx(P)}>
                  Force reset
                </Button>
              ) : null}
            </Box>
          ) : null}

          {pathExists && sourceMode === 'zip' ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                style={{ display: 'none' }}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) uploadZip(file);
                }}
              />
              <Button
                variant="outlined"
                size="small"
                startIcon={<UploadFileIcon />}
                onClick={() => fileInputRef.current?.click()}
                disabled={isSubmitting}
              >
                Upload ZIP
              </Button>
              {uploadFilename ? <Typography variant="caption">{uploadFilename}</Typography> : null}
              <Button variant="outlined" size="small" onClick={validateZip} disabled={isSubmitting || !uploadId}>
                Validate ZIP
              </Button>
              <Button
                variant="contained"
                size="small"
                onClick={applyZipToStorage}
                disabled={isSubmitting || !zipValidated}
              >
                Apply to Storage
              </Button>
            </Box>
          ) : null}

          {sourceDiffEntries.length > 0 ? (
            <Accordion disableGutters elevation={0} sx={{ mt: 0.75, '&:before': { display: 'none' } }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 30, px: 0 }}>
                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                  Changed files ({sourceDiffEntries.length})
                </Typography>
              </AccordionSummary>
              <AccordionDetails sx={{ pt: 0, px: 0 }}>
                <Box sx={{ display: 'grid', gap: 0.25 }}>
                  {sourceDiffEntries.map((entry) => (
                    <Typography
                      key={`${entry.status}-${entry.path}`}
                      variant="caption"
                      sx={{ fontFamily: 'monospace', display: 'block' }}
                    >
                      {entry.status} {entry.path} +{entry.added} -{entry.deleted}
                    </Typography>
                  ))}
                </Box>
              </AccordionDetails>
            </Accordion>
          ) : null}
        </AccordionDetails>
      </Accordion>
    </>
  );
};

export const TargetsPanel: React.FC<PanelProps> = ({ d }) => {
  const { P, selectedHosts, selectedLocalTargets, frontendVersion, allHosts, serverInfo, allHostsSelected, allTargetsSelected, someTargetsSelected, toggleSelectAllTargets, toggleLocalTarget, toggleHost, toggleSelectAllHosts, formatVersion, getVersionColor, sectionAccordionSx, targetTileSx } = d;
  return (
    <>
      <Accordion defaultExpanded sx={sectionAccordionSx}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography sx={{ fontWeight: 600 }}>Targets</Typography>
            <Typography variant="caption" color="text.secondary">|</Typography>
            <Typography
              variant="caption"
              color={allTargetsSelected ? 'text.disabled' : P.accentText}
              sx={{ cursor: allTargetsSelected ? 'default' : 'pointer' }}
              onClick={e => { e.stopPropagation(); if (!allTargetsSelected) toggleSelectAllTargets(true); }}
            >
              Select All
            </Typography>
            <Typography variant="caption" color="text.secondary">/</Typography>
            <Typography
              variant="caption"
              color={someTargetsSelected ? P.accentText : 'text.disabled'}
              sx={{ cursor: someTargetsSelected ? 'pointer' : 'default' }}
              onClick={e => { e.stopPropagation(); if (someTargetsSelected) toggleSelectAllTargets(false); }}
            >
              Unselect All
            </Typography>
          </Box>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0.125, pb: 0.75, px: 1.5 }}>
          <Box sx={{ display: 'grid', gap: 0.5 }}>
            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: {
                  xs: '1fr',
                  md: 'repeat(2, minmax(0, 1fr))',
                },
                gap: 0.75,
              }}
            >
              <FormControlLabel
                sx={targetTileSx}
                control={
                  <Checkbox
                    size="small"
                    checked={selectedLocalTargets.includes('server')}
                    onChange={() => toggleLocalTarget('server')}
                    sx={{ p: 0.375, pt: 0.5 }}
                  />
                }
                label={
                  <Box sx={{ py: 0.25 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.15 }}>
                      Server
                    </Typography>
                    {serverInfo?.deployed_version ? (
                      <Typography variant="caption" color={getVersionColor(serverInfo.deployed_version)}>
                        {formatVersion(serverInfo.deployed_version)}
                      </Typography>
                    ) : null}
                  </Box>
                }
              />
              <FormControlLabel
                sx={targetTileSx}
                control={
                  <Checkbox
                    size="small"
                    checked={selectedLocalTargets.includes('frontend')}
                    onChange={() => toggleLocalTarget('frontend')}
                    sx={{ p: 0.375, pt: 0.5 }}
                  />
                }
                label={
                  <Box sx={{ py: 0.25 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.15 }}>
                      Frontend
                    </Typography>
                    {frontendVersion && frontendVersion !== 'unknown' ? (
                      <Typography variant="caption" color={getVersionColor(frontendVersion)}>
                        {formatVersion(frontendVersion)}
                      </Typography>
                    ) : null}
                  </Box>
                }
              />
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.125, mb: 0 }}>
              <Checkbox
                size="small"
                checked={allHostsSelected}
                indeterminate={selectedHosts.length > 0 && !allHostsSelected}
                onChange={(_, checked) => toggleSelectAllHosts(checked)}
                sx={{ p: 0.25 }}
              />
              <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.2 }}>
                Hosts ({allHosts.length})
              </Typography>
            </Box>
            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: {
                  xs: '1fr',
                  md: 'repeat(2, minmax(0, 1fr))',
                  lg: 'repeat(3, minmax(0, 1fr))',
                },
                gap: 0.75,
              }}
            >
              {allHosts.map((host) => (
                <FormControlLabel
                  key={host.host_name}
                  sx={targetTileSx}
                  control={
                    <Checkbox
                      size="small"
                      checked={selectedHosts.includes(host.host_name)}
                      onChange={() => toggleHost(host.host_name)}
                      sx={{ p: 0.375 }}
                    />
                  }
                  label={
                    <Box sx={{ py: 0.25 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.15 }}>
                        {host.host_name}
                      </Typography>
                      {host.deployed_version ? (
                        <Typography variant="caption" color={getVersionColor(host.deployed_version)}>
                          {formatVersion(host.deployed_version)}
                        </Typography>
                      ) : null}
                    </Box>
                  }
                />
              ))}
            </Box>
          </Box>
        </AccordionDetails>
      </Accordion>
    </>
  );
};

export const ExecutePanel: React.FC<PanelProps> = ({ d }) => {
  const { sourceReady, isSubmitting, results, orderedTargets, executeDeploy, sectionAccordionSx } = d;
  return (
    <>
      <Accordion defaultExpanded sx={sectionAccordionSx}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography sx={{ fontWeight: 600 }}>Deploy</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0.125, pb: 0.75, px: 1.5 }}>
          <Box display="flex" alignItems="center" gap={0.5} mb={0.5} flexWrap="wrap">
            <Button
              variant="contained"
              size="small"
              onClick={executeDeploy}
              disabled={isSubmitting || orderedTargets.length === 0 || !sourceReady}
            >
              Deploy
            </Button>
            {isSubmitting ? <CircularProgress size={16} /> : null}
            <Typography variant="caption" color="text.secondary">
              Selected targets: {orderedTargets.length}
            </Typography>
          </Box>

          {results.length > 0 ? (
            <Box display="flex" flexDirection="column" gap={0.375}>
              {results.map((result, index) => (
                <Alert
                  key={`${result.action}-${result.target}-${index}`}
                  severity={result.success ? 'success' : 'error'}
                  variant="outlined"
                  sx={{ py: 0 }}
                >
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {result.target} - {result.action.toUpperCase()}
                  </Typography>
                  <Typography variant="caption" display="block">
                    {result.message || result.error || 'No message'}
                  </Typography>
                  <Typography variant="caption" display="block">
                    Version: {result.version_before || 'unknown'} -&gt; {result.version_after || 'unknown'}
                  </Typography>
                </Alert>
              ))}
            </Box>
          ) : null}
        </AccordionDetails>
      </Accordion>
    </>
  );
};

export const RollbackPanel: React.FC<PanelProps> = ({ d }) => {
  const P = useAgentChatPalette();
  const { rollbackCandidates, rollbackOptions, selectedRollbackId, setSelectedRollbackId, isLoadingRollbackOptions, isSubmitting, orderedTargets, executeRollbackSelected, executeRollbackRecovery, sectionAccordionSx, noStableRollbackOption } = d;
  return (
    <>
      <Accordion defaultExpanded={false} sx={sectionAccordionSx}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography sx={{ fontWeight: 600 }}>Rollback</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0.125, pb: 0.75, px: 1.5 }}>
          <Box display="flex" alignItems="center" gap={0.5} mb={0.5} flexWrap="wrap">
            <Button
              variant="outlined"
              size="small"
              onClick={executeRollbackSelected}
              disabled={
                isSubmitting ||
                orderedTargets.length === 0 ||
                selectedRollbackId === noStableRollbackOption.backup_id
              } sx={dangerButtonSx(P)}>
              Rollback
            </Button>
            <Select
              size="small"
              value={selectedRollbackId}
              onChange={(event) => setSelectedRollbackId(String(event.target.value))}
              disabled={isSubmitting || orderedTargets.length === 0 || isLoadingRollbackOptions}
              sx={{ minWidth: 260 }}
            >
              {rollbackOptions.map((option) => (
                <MenuItem key={option.backup_id} value={option.backup_id}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
            {isLoadingRollbackOptions ? <CircularProgress size={16} /> : null}
          </Box>

          {rollbackCandidates.length > 0 ? (
            <Box mb={0.75}>
              <Button
                variant="text"
                size="small"
                onClick={executeRollbackRecovery}
                disabled={isSubmitting}
                sx={dangerButtonSx(P)}
              >
                Rollback completed targets
              </Button>
            </Box>
          ) : null}
        </AccordionDetails>
      </Accordion>
    </>
  );
};
