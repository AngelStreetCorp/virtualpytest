import {
  AttachFile as AttachIcon,
  Close as CloseIcon,
  ExpandLess as LessIcon,
  ExpandMore as MoreIcon,
} from '@mui/icons-material';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  Collapse,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';

import { goldButtonSx } from '../../../frontend/src/components/common/PageChrome';
import { StyledDialog } from '../../../frontend/src/components/common/StyledDialog';
import { useAgentChatPalette } from '../../../frontend/src/constants/agentChatTheme';
import { APP_CONFIG } from '../../../frontend/src/config/constants';
import { useAuthContext } from '../../../frontend/src/contexts/auth/AuthContext';
import { useServerManager } from '../../../frontend/src/hooks/useServerManager';
import { useToast } from '../../../frontend/src/hooks/useToast';
import { useI18n } from '../../../frontend/src/i18n/useI18n';
import type { ReportIncidentOptions, SupportAttachment } from './reportIncident';
import {
  FAMILIES,
  FAMILY_KEYS,
  DEFAULT_PRIORITY,
  FREQUENCIES,
  PRIORITIES,
  SEVERITIES,
  SEVERITY_TYPES,
  TICKET_TYPES,
  type Category,
  type Family,
  type Frequency,
  type Priority,
  type Severity,
  type TicketTarget,
  type TicketType,
} from './ticketModel';
import { useSupportTickets } from './useSupportTickets';
import { useTicketLabels } from './useTicketLabels';
import { useTicketTargets } from './useTicketTargets';

const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_FILES = 5;
// Bumped from 13 in the "one step larger" mockup so the dialog reads at a glance.
const FONT = 15;

interface ReportIncidentDialogProps {
  open: boolean;
  options: ReportIncidentOptions;
  onClose: () => void;
}

const readAsBase64 = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

/** A small row of single-choice chips with its caption on the same line. */
function ChipChoice<T extends string>({
  caption,
  values,
  value,
  onChange,
  labels,
}: {
  caption: string;
  values: readonly T[];
  value: T | '';
  onChange: (v: T) => void;
  labels: Record<string, string>;
}) {
  const P = useAgentChatPalette();
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'nowrap', gap: 0.75 }}>
      <Typography sx={{ fontSize: 14, color: P.textMuted, mr: 0.25, flexShrink: 0 }}>{caption}</Typography>
      {values.map((v) => {
        const selected = v === value;
        return (
          <Chip
            key={v}
            size="small"
            clickable
            label={labels[v]}
            onClick={() => onChange(v)}
            variant="outlined"
            sx={{
              height: 28,
              fontSize: 14,
              borderColor: selected ? P.accent : P.borderColor,
              color: selected ? P.accentText : P.textSecondary,
              bgcolor: selected ? P.hoverBg : 'transparent',
              fontWeight: selected ? 600 : 400,
            }}
          />
        );
      })}
    </Box>
  );
}

export const ReportIncidentDialog: React.FC<ReportIncidentDialogProps> = ({ open, options, onClose }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const location = useLocation();
  const { user } = useAuthContext();
  const { serverHostsData, selectedServer } = useServerManager();
  const { showSuccess } = useToast();
  const { createTicket, isSubmitting, error, clearError } = useSupportTickets();
  const { label, template } = useTicketLabels();
  const fileInput = useRef<HTMLInputElement>(null);

  const [ticketType, setTicketType] = useState<TicketType>('incident');
  const [priority, setPriority] = useState<Priority>(DEFAULT_PRIORITY);
  const [severity, setSeverity] = useState<Severity | ''>('');
  const [family, setFamily] = useState<Family | ''>('');
  const [category, setCategory] = useState<Category | ''>('');
  const [target, setTarget] = useState<TicketTarget | null>(null);
  const [frequency, setFrequency] = useState<Frequency | ''>('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [descriptionEdited, setDescriptionEdited] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [since, setSince] = useState('');
  const [files, setFiles] = useState<SupportAttachment[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);

  const { targets, loading: targetsLoading } = useTicketTargets(category);

  // Reset on open only, from the options passed at that moment.
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const templateRef = useRef(template);
  templateRef.current = template;
  useEffect(() => {
    if (!open) return;
    const o = optionsRef.current;
    const type = o.ticketType ?? 'incident';
    setTicketType(type);
    setPriority(DEFAULT_PRIORITY);
    setSeverity(SEVERITY_TYPES.includes(type) ? (o.severity ?? '') : '');
    const fam = o.family ?? (o.category ? FAMILY_KEYS.find((f) => (FAMILIES[f] as readonly string[]).includes(o.category as string)) : undefined);
    setFamily(fam ?? '');
    setCategory(fam ? (o.category ?? '') : '');
    setTarget(o.targetId ? { id: o.targetId, label: o.targetLabel ?? o.targetId } : null);
    setFrequency('');
    setTitle(o.title ?? '');
    // Context text (log lines, report link...) is the user's text from the start: never replaced by a template.
    setDescription(o.details ? `${templateRef.current[type]}\n${o.details}` : templateRef.current[type]);
    setDescriptionEdited(Boolean(o.details));
    setShowMore(false);
    setSince('');
    setFiles(o.attachments ?? []);
    setFileError(null);
    clearError();
  }, [open]);

  const serverName = useMemo(() => {
    const match = serverHostsData.find((sd) => sd.server_info.server_url === selectedServer);
    return (match ?? serverHostsData[0])?.server_info.server_name ?? 'unknown';
  }, [serverHostsData, selectedServer]);

  const version = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'unknown';
  const hasSeverity = SEVERITY_TYPES.includes(ticketType);

  const pickType = (type: TicketType) => {
    setTicketType(type);
    if (!SEVERITY_TYPES.includes(type)) setSeverity('');
    if (!descriptionEdited) setDescription(template[type]);
  };

  const pickFamily = (next: Family | '') => {
    setFamily(next);
    setCategory('');
    setTarget(null);
  };

  const onPickFiles = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(event.target.files ?? []);
    event.target.value = '';
    setFileError(null);
    const next = [...files];
    for (const file of picked) {
      if (next.length >= MAX_FILES) {
        setFileError(t('At most {count} files', { count: MAX_FILES }));
        break;
      }
      if (file.size > MAX_FILE_BYTES) {
        setFileError(t('{name} is larger than 5 MB', { name: file.name }));
        continue;
      }
      next.push({
        filename: file.name,
        data_b64: await readAsBase64(file),
        mime_type: file.type || 'application/octet-stream',
      });
    }
    setFiles(next);
  };

  // The template alone is not a report: something has to be written, or the text came with the context.
  const written = description.trim().length > 0 && description.trim() !== template[ticketType].trim();
  const canSubmit =
    Boolean(family && category && frequency) &&
    (!hasSeverity || Boolean(severity)) &&
    title.trim().length > 0 &&
    written &&
    !isSubmitting;

  const submit = async () => {
    if (!family || !category || !frequency) return;
    // Context block: data for the support team, English on purpose (never translated).
    const context = [
      '---',
      since ? `Since: ${since}` : null,
      `Version: ${version}`,
      `Server: ${serverName}`,
      `Team: ${APP_CONFIG.DEFAULT_TEAM_ID}`,
      `User: ${user?.email ?? 'unknown'}`,
      `Page: ${window.location.origin}${location.pathname}${location.search}`,
      `Browser: ${navigator.userAgent}`,
    ].filter(Boolean).join('\n');
    const ticket = await createTicket({
      ticket_type: ticketType,
      family,
      category,
      frequency,
      priority,
      severity: hasSeverity && severity ? severity : undefined,
      target_id: target?.id,
      target_label: target?.label,
      title: title.trim(),
      description: `${description.trim()}\n\n${context}`,
      attachments: files,
    });
    if (ticket) {
      showSuccess(t('Ticket sent to support'));
      onClose();
    }
  };

  const fieldSx = {
    '& .MuiInputBase-root, & .MuiInputBase-input': { fontSize: FONT },
    '& .MuiInputLabel-root': { fontSize: FONT },
  };
  const categoryKeys: readonly Category[] = family ? FAMILIES[family] : [];

  return (
    <StyledDialog open={open} onClose={isSubmitting ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ pb: 1, fontSize: 18 }}>{t('Open a ticket')}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, pt: 0.5, ...fieldSx }}>
          <ChipChoice caption={t('Type')} values={TICKET_TYPES} value={ticketType} onChange={pickType} labels={label} />
          <ChipChoice caption={t('Priority')} values={PRIORITIES} value={priority} onChange={setPriority} labels={label} />
          {hasSeverity && (
            <ChipChoice
              caption={t('Severity')}
              values={SEVERITIES}
              value={severity}
              onChange={setSeverity}
              labels={label}
            />
          )}
          <ChipChoice
            caption={t('Frequency')}
            values={FREQUENCIES}
            value={frequency}
            onChange={setFrequency}
            labels={label}
          />

          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr 1.4fr' }, gap: 1 }}>
            <TextField
              select
              size="small"
              label={t('Family')}
              value={family}
              onChange={(e) => pickFamily(e.target.value as Family | '')}
            >
              {FAMILY_KEYS.map((f) => (
                <MenuItem key={f} value={f} sx={{ fontSize: FONT }}>{label[f]}</MenuItem>
              ))}
            </TextField>
            <TextField
              select
              size="small"
              label={t('Category')}
              value={category}
              disabled={!family}
              onChange={(e) => {
                setCategory(e.target.value as Category);
                setTarget(null);
              }}
            >
              {categoryKeys.map((c) => (
                <MenuItem key={c} value={c} sx={{ fontSize: FONT }}>{label[c]}</MenuItem>
              ))}
            </TextField>
            <Autocomplete
              size="small"
              disabled={!category}
              options={targets}
              value={target}
              loading={targetsLoading}
              onChange={(_, v) => setTarget(v)}
              getOptionLabel={(o) => o.label}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              noOptionsText={t('Nothing to pick')}
              ListboxProps={{ sx: { fontSize: FONT } }}
              renderInput={(params) => <TextField {...params} label={t('Target')} placeholder="—" />}
            />
          </Box>

          <TextField
            size="small"
            label={t('Title')}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            inputProps={{ maxLength: 200 }}
            autoFocus
          />
          <TextField
            size="small"
            label={t('Description')}
            value={description}
            onChange={(e) => {
              setDescription(e.target.value);
              setDescriptionEdited(true);
            }}
            multiline
            minRows={6}
            maxRows={12}
          />

          <Box>
            <Button
              size="small"
              onClick={() => setShowMore(!showMore)}
              endIcon={showMore ? <LessIcon fontSize="small" /> : <MoreIcon fontSize="small" />}
              sx={{ textTransform: 'none', fontSize: 14, color: P.textSecondary, px: 0.5 }}
            >
              {t('More details')}
            </Button>
            <Collapse in={showMore} unmountOnExit>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, pt: 0.75 }}>
                <TextField
                  size="small"
                  type="datetime-local"
                  label={t('Since when')}
                  value={since}
                  onChange={(e) => setSince(e.target.value)}
                  InputLabelProps={{ shrink: true }}
                  sx={{ maxWidth: 240 }}
                />
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap' }}>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<AttachIcon />}
                    onClick={() => fileInput.current?.click()}
                    sx={{ textTransform: 'none', fontSize: 14 }}
                  >
                    {t('Attach a file')}
                  </Button>
                  {files.map((f, i) => (
                    <Chip
                      key={`${f.filename}-${i}`}
                      size="small"
                      label={f.filename}
                      onDelete={() => setFiles(files.filter((_, j) => j !== i))}
                      deleteIcon={<CloseIcon />}
                      sx={{ fontSize: 14 }}
                    />
                  ))}
                  <input ref={fileInput} type="file" multiple hidden onChange={onPickFiles} />
                </Box>
                {fileError && (
                  <Typography variant="caption" sx={{ color: P.error }}>{fileError}</Typography>
                )}
              </Box>
            </Collapse>
          </Box>

          <Typography sx={{ fontSize: 13, color: P.textMuted }}>
            {t('Version, server, team, page and logs are added automatically.')}
          </Typography>
          {error && <Alert severity="error" sx={{ py: 0 }}>{error}</Alert>}
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
        <Button size="small" onClick={onClose} disabled={isSubmitting} sx={{ fontSize: FONT }}>
          {t('Cancel')}
        </Button>
        <Button size="small" variant="contained" sx={{ ...goldButtonSx(P), fontSize: FONT }} onClick={submit} disabled={!canSubmit}>
          {isSubmitting ? t('Sending…') : t('Send')}
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

export default ReportIncidentDialog;
