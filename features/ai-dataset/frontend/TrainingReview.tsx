/**
 * AI Dataset (TASK-27 step 4, feature `ai-dataset`) — admin page where a human checks
 * each training screenshot against one plain question. The answers become the reference (eval) set.
 *
 * Keys: y yes/correct, n no/fix it, j skip (next), k back, Esc close the fix form,
 * Ctrl+Enter save the fix form. Built to clear 200 samples in under an hour.
 *
 * Show: "Not checked yet" drops a sample from the list the moment it is labelled and
 * ends on "All done"; "Already checked" asks "You said X. Still correct?"; "All" puts
 * a status chip on each sample. Frozen (eval_version) samples are read-only.
 * Navigation never wraps around; skipping never removes a sample.
 *
 * Step 4d: a failed-verification screen-id sample (the check failed on this frame, so
 * the true screen is unknown) asks "Which screen is this? (the test expected: X)" with
 * the screen dropdown already open and no Yes button. "Confusable pairs" shows only
 * label_conflict samples; Details names the other sample of the pair.
 *
 * Step 4f: the counter reads `x/K`: K = samples matching the filters when the page was
 * (re)loaded, x = answers saved since (Skip does not count); Reload recomputes K and
 * resets x. A screen-id frame showing a screen not in the tree gets a free-text answer
 * ("Screen not in the tree", saved as {node_id: null, label}). av-fault has no audio
 * answer: audio loss cannot be seen in a frame.
 *
 * Step 4g: a freeze alert is one "strip" sample (model_answer.evidence === 'strip'): 2-3
 * frames of the alert side by side with their times. A chip per frame under the strip says
 * "+0.0 s · during freeze" / "after freeze" / "before freeze" (reviewText.ts `stripFrames`).
 * It asks "The picture didn't change for 52.7 s (frames marked 'during freeze'). Was that a
 * problem?" with four buttons: Yes, the video got stuck ({incident_type: 'freeze'}); No, it
 * was a still screen ({incident_type: null, static_screen: true}); No, the picture was
 * actually moving ({incident_type: null, static_screen: false}); Can't tell (skip). Each
 * saves and advances. "Open alert" links to the alert.
 *
 * Step 4i: an AI teacher labels in place of the human (scripts/triage_batch.py). Show
 * "Needs you" lists what it sent to a human (disagrees with the test run, confusable pair,
 * low confidence, then the random spot-checks last). A chip names the triage on every row:
 * "Checked by AI" (agreed with the run label), the reason a human must look, or "Labelled by
 * AI, not checked". Answering such a row makes it human and the triage resolved. The eval
 * panel counts human-verified and AI-verified rows apart, and freezes either eval-vN (human
 * only, 200) or eval-vN-ai (human + AI-verified pilot, minimum set on the panel).
 *
 * Step 4k: a screen-id answer is a screen GROUP (Home with any tab focused is "home"). The
 * question is "Is this the home screen?" and, when the label names a focused item, a line
 * "Focused: apps" with where the guess comes from (the tree node name, or the AI when the triage
 * has `focus_teacher`). One answer per sample (owner, 2026-10-03): the main Yes ("✓ Save: home ·
 * focused apps", what `y` saves) saves screen and focus together; "No, fix it" changes both in
 * one form (screen list of the app's groups, focused item, "Nothing focused"). focus samples get
 * a "Nothing focused" answer ({focused: null}). The Coverage panel lists each app's groups
 * (group -> member nodes, focus states covered).
 *
 * Review flow (2026-10-03): an answer is saved in the background and the next sample shows at
 * once (a failed save brings that sample back with the error); the next two images are
 * preloaded, and a sample's question waits for its image so both appear together.
 *
 * Review UX (2026-09-30): the Set follows the Show view ("Needs you" starts on All, the others
 * on Eval) until the user picks a Set; an empty "Needs you" in one Set counts the other Sets
 * and offers "Show all sets". The triage note says the labels in words (reviewText.ts), never
 * JSON. The image sits at the top of its box, full width, at most 70vh tall.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Autocomplete, Box, Button, Checkbox, Chip,
  CircularProgress, FormControlLabel, IconButton, LinearProgress, MenuItem, Paper, Radio, RadioGroup,
  Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography,
} from '@mui/material';
import { useAgentChatPalette } from '../../../frontend/src/constants/agentChatTheme';
import { pageSurfaceSx } from '../../../frontend/src/components/common/PageChrome';
import { Add, Delete, ExpandMore, Refresh } from '@mui/icons-material';

import { ConfirmDialog } from '../../../frontend/src/components/common/ConfirmDialog';
import { useConfirmDialog } from '../../../frontend/src/hooks/useConfirmDialog';
import { buildIncidentFocusUrl } from '../../../frontend/src/utils/incidentFocus';
import {
  CoverageApp, CoverageReport, PAGE_SIZE, ReviewShow, SHOW_REMOVES_ON_LABEL, ScreenGroup, TRAINING_FAMILIES,
  TrainingFamily, TrainingFilters, TrainingSample, TriageReason, isAiVersion, useScreenGroups, useTrainingSamples,
} from './hooks/useTrainingSamples';
import {
  AV_FAULTS, Label, SPLIT_OPTIONS, STRIP_ANSWERS, STRIP_HINT, UUID_RE, acceptButtonText, asRecord, asText,
  focusGuessSource, frameChipText, isNoBanner, isOffTree, labelWords, screenName, splitName,
  stripAnswerWords, stripDurationText, stripFrames, toGroupLabel, triageNoteText, withShow,
} from './reviewText';

const SHOW_OPTIONS: [ReviewShow, string][] = [
  ['needs_you', 'Needs you'],
  ['unchecked', 'Not checked yet'],
  ['checked', 'Already checked'],
  ['all', 'All'],
];

const NO_BANNER = { channel_number: null, channel_name: null };

/** A select whose '' option ("All") shows its text instead of a blank field. */
const SHOW_EMPTY_OPTION = { SelectProps: { displayEmpty: true }, InputLabelProps: { shrink: true } };

const DEFAULT_FILTERS: TrainingFilters = {
  family: '',
  split: 'eval',
  show: 'unchecked',
  isFailure: '',
  deviceModel: '',
  balance: true,
  confusable: false,
};

const pretty = (value: unknown) => (value === null || value === undefined ? '—' : JSON.stringify(value, null, 2));

const isTyping = (target: EventTarget | null) => {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
};

const isChecked = (sample: TrainingSample) => sample.label_source === 'human';
/** A screen-id frame on which a node verification failed (step 4d): no guess, only the expected screen. */
const isFailedVerification = (sample: TrainingSample) =>
  sample.family === 'screen-id' && asRecord(sample.model_answer).verified === false;
const isFrozen = (sample: TrainingSample) => Boolean(sample.eval_version);
/** A freeze alert stored as one multi-frame strip (step 4g). */
const isFreezeStrip = (sample: TrainingSample) =>
  sample.family === 'av-fault' && asRecord(sample.model_answer).evidence === 'strip';

/** One chip per strip frame, in strip order: "+0.0 s · during freeze" (none without frames). */
const StripFrameChips: React.FC<{ sample: TrainingSample }> = ({ sample }) => {
  const P = useAgentChatPalette();
  const frames = stripFrames(sample.model_answer);
  if (!frames.length) return null;
  return (
    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', justifyContent: 'space-around', mt: 1 }}>
      {frames.map((f, i) => (
        <Chip key={i} size="small" label={frameChipText(f)}
          color={f.phase === 'during' ? 'warning' : 'default'} variant={f.phase === 'during' ? 'filled' : 'outlined'}
          sx={f.phase === 'during' ? undefined : { color: P.textSecondary, borderColor: P.borderColor }} />
      ))}
    </Box>
  );
};

/** Link to the alert on the Alerts page, when the sample carries host/device/time. */
const alertLink = (sample: TrainingSample): string | null => {
  const ref = asRecord(sample.source_ref);
  const [host, device, at] = [asText(ref.host), asText(ref.device), asText(ref.at)];
  if (!host || !device || !at) return null;
  return buildIncidentFocusUrl({ host, device, type: 'freeze', at });
};

// ─── Step 4k: screen groups (toGroupLabel, screenName: reviewText.ts) ─────────

/**
 * A grouped label with its focus set by a human. The node becomes the group member whose
 * focus (or label) matches; "Nothing focused" (null) matches the group's own node. No match:
 * the node stays the one the label named.
 */
const withFocus = (label: Label, focus: string | null, groups: ScreenGroup[]): Label => {
  const group = groups.find((g) => g.node_id === asText(label.node_id));
  const want = focus === null ? null : focus.trim().toLowerCase();
  const member = group?.members.find((m) => (want === null
    ? m.focus === null
    : asText(m.focus).toLowerCase() === want || m.label.toLowerCase() === want));
  return { ...label, focus, ...(member ? { node: member.node_id, node_label: member.label } : {}) };
};

/** Step 4i: why the AI triage sent a sample to a human, in words. */
const TRIAGE_REASON_TEXT: Record<TriageReason, string> = {
  disagrees_with_run: 'AI disagrees with the test run',
  conflict: 'Confusable pair',
  low_confidence: 'AI was not sure',
  spot_check: 'Spot-check of the AI',
  no_independent_label: 'Labelled by AI only',
  focus_low_confidence: 'AI was not sure of the focused item',
};

/** The triage chip of a sample, or null when the AI never looked at it. */
const triageChip = (s: TrainingSample): React.ReactNode => {
  const t = s.triage;
  if (!t) return null;
  const model = t.teacher_model ? ` (${t.teacher_model})` : '';
  switch (t.status) {
    case 'agreed':
      // A confusable pair flagged after the triage no longer counts as AI-verified.
      if (s.label_conflict) {
        return <Tooltip title="The AI agreed with the test run, but a near-identical screenshot has a different answer"><Chip size="small" color="warning" label="Needs you · Confusable pair" /></Tooltip>;
      }
      return <Tooltip title={`The AI teacher${model} gave the same answer as the test run`}><Chip size="small" color="secondary" label="Checked by AI" /></Tooltip>;
    case 'needs_human':
      return <Tooltip title={`Sent to a human by the AI triage${model}`}><Chip size="small" color="warning" label={`Needs you · ${t.reason ? TRIAGE_REASON_TEXT[t.reason] : 'AI triage'}`} /></Tooltip>;
    case 'teacher_only':
      return <Tooltip title={`Answer from the AI teacher${model}; nothing independent confirms it`}><Chip size="small" variant="outlined" color="secondary" label="Labelled by AI, not checked" /></Tooltip>;
    case 'excluded':
      // Second AI pass: still unsettled, so it never trains and is not sent to the human.
      return <Tooltip title={`A second AI look${model} could not settle this sample, so it is left out of training. Answering it here puts it back.`}><Chip size="small" variant="outlined" label="Left out of training (AI unsure)" /></Tooltip>;
    case 'resolved':
      return <Chip size="small" variant="outlined" label="AI triage resolved by a human" />;
    default:
      return null;
  }
};

/**
 * One line under the question when the AI triage sent this sample to a human, in words
 * (never the label JSON: the raw answers are in Details).
 */
const TriageNote: React.FC<{ sample: TrainingSample; groups: ScreenGroup[] }> = ({ sample, groups }) => {
  const note = triageNoteText(sample, groups);
  if (!note) return null;
  return (
    <Alert severity="warning" variant="outlined" sx={{ py: 0 }}>
      {note.kind === 'conflict' && note.partner
        ? <>{note.why} <strong>{note.partner}</strong>; check this one carefully.</>
        : note.why}
      {note.aiSaid && <> AI said: <strong>{note.aiSaid}</strong>.</>}
    </Alert>
  );
};

const guessSourceText = (sample: TrainingSample): string => {
  switch (sample.guess_source) {
    case 'run':
      if (sample.family === 'screen-id') return 'the test run (verified navigation)';
      if (sample.family === 'banner') return 'the test run (the channel it tuned to)';
      return 'the test run';
    case 'human': return 'an earlier human check';
    case 'teacher': return 'the teacher AI model';
    case 'model': return 'the AI model';
    default: return 'not set';
  }
};

// ─── The question ─────────────────────────────────────────────────────────────

const B: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const P = useAgentChatPalette();
  return <Box component="strong" sx={{ color: P.accentText }}>{children}</Box>;
};

/**
 * One plain yes/no question built from the proposed label. A human-checked sample
 * asks instead "You said: X. Still correct?".
 */
const Question: React.FC<{ sample: TrainingSample; groups: ScreenGroup[] }> = ({ sample, groups }) => {
  const p = sample.proposed_label;
  const r = asRecord(p);
  const none = p === null || p === undefined;
  const checked = isChecked(sample) && !none;
  let said: React.ReactNode = null;
  let text: React.ReactNode;
  let extra: React.ReactNode = null;

  switch (sample.family) {
    case 'screen-id': {
      // Step 4k: name the screen GROUP, never a node uuid.
      const raw = asText(r.label);
      const name = screenName(p, groups);
      const grouped = toGroupLabel(p, groups);
      const focus = grouped ? asText(grouped.focus) : '';
      const expected = isFailedVerification(sample) ? asRecord(sample.model_answer) : null;
      let expectedName = expected ? asText(expected.expected_group) : '';
      if (expected && !expectedName) {
        const group = groups.find((g) => g.members.some((m) => m.node_id === asText(expected.expected_node_id)));
        const expectedRaw = asText(expected.expected_label);
        expectedName = group ? group.label : UUID_RE.test(expectedRaw) ? '' : expectedRaw;
      }
      const offTree = isOffTree(p);
      text = none && expected ? <>Which screen is this? (the test expected: <B>{expectedName || 'unnamed screen'}</B>)</>
        : none ? 'Which screen is this?'
        : offTree ? <>Is this a screen not in the tree: <B>{raw}</B>?</>
        : !name ? <>Is this the screen the test run reached (<B>unnamed screen</B>)?</>
        : <>Is this the <B>{name}</B> screen?</>;
      said = offTree ? <>a screen not in the tree (<B>{raw}</B>)</>
        : <><B>{name || 'unnamed screen'}</B>{focus ? <>, with <B>{focus}</B> focused</> : null}</>;
      break;
    }
    case 'focus': {
      // Step 4k: focused null = nothing is focused (fullscreen video, splash).
      const nothing = !none && r.focused === null;
      text = none ? 'Which item is highlighted?'
        : nothing ? <>Is <B>nothing</B> highlighted on this screen?</>
        : <>Is <B>{asText(r.focused)}</B> the highlighted item?</>;
      said = nothing ? <><B>nothing</B> is highlighted</> : <><B>{asText(r.focused)}</B> is highlighted</>;
      break;
    }
    case 'banner': {
      const num = asText(r.channel_number);
      const name = asText(r.channel_name);
      if (none) text = 'What does the channel banner show?';
      else if (isNoBanner(p)) text = <>Is there really <B>no channel banner</B> on this screen?</>;
      else if (num && name) text = <>Does the banner show channel <B>{num}</B> ({name})?</>;
      else if (num) text = <>Does the banner show channel <B>{num}</B>?</>;
      else text = <>Does the banner show <B>{name}</B>?</>;
      said = isNoBanner(p) ? <B>no channel banner</B>
        : num ? <>channel <B>{num}</B>{name ? ` (${name})` : ''}</> : <B>{name}</B>;
      break;
    }
    case 'av-fault': {
      if (isFreezeStrip(sample)) {
        const duration = stripDurationText(sample.model_answer);
        text = <>The picture didn&apos;t change{duration ? <> for <B>{duration}</B></> : null} (frames marked &apos;during freeze&apos;). Was that a problem?</>;
        said = <B>{stripAnswerWords(p) || 'no fault'}</B>;
        const link = alertLink(sample);
        const alertId = asText(asRecord(sample.source_ref).alert_id);
        extra = (
          <Box sx={{ mt: 0.5 }}>
            <Typography variant="body1">{STRIP_HINT}</Typography>
            {link ? (
              <Button size="small" href={link} target="_blank" rel="noopener" sx={{ px: 0 }}>Open alert</Button>
            ) : alertId ? (
              <Typography variant="caption" color="text.secondary">Alert {alertId}</Typography>
            ) : null}
          </Box>
        );
        break;
      }
      const fault = AV_FAULTS.find(([v]) => v === r.incident_type);
      // A type that is no longer an answer (the old audio_loss rows) is named as stored.
      const legacy = !fault && r.incident_type !== null && r.incident_type !== undefined ? asText(r.incident_type) : '';
      if (none) text = 'Is there a picture fault on this frame?';
      else if (fault) text = <>Does this frame show <B>{fault[2]}</B>?</>;
      else if (legacy) text = <>Does this frame show <B>{legacy}</B>? (no longer an answer: press n and pick a picture fault or no fault)</>;
      else text = <>Is this frame <B>fine, with no fault</B> (a false alarm)?</>;
      said = fault ? <B>{fault[2]}</B> : legacy ? <B>{legacy}</B> : <B>no fault (false alarm)</B>;
      break;
    }
    case 'menu': {
      const items = Array.isArray(r.items) ? r.items.map(asText) : [];
      const selected = asText(r.selected);
      text = none ? 'What are the menu items, and which one is selected?'
        : selected ? <>Are these the menu items, with <B>{selected}</B> selected?</>
        : <>Are these the menu items, with <B>nothing</B> selected?</>;
      said = <>these menu items, with <B>{selected || 'nothing'}</B> selected</>;
      if (items.length) {
        extra = (
          <Box component="ol" sx={{ m: 0, mt: 0.5, pl: 3 }}>
            {items.map((item, i) => (
              <li key={`${item}-${i}`}><Typography fontWeight={item === selected ? 700 : 400}>{item}{item === selected ? '  ← selected' : ''}</Typography></li>
            ))}
          </Box>
        );
      }
      break;
    }
    default: {
      text = none ? 'What is the correct answer?' : 'Is this answer correct?';
      said = 'the answer below';
      if (!none) {
        const content = typeof r.content === 'string' && Object.keys(r).length === 1 ? r.content : pretty(p);
        extra = (
          <Paper variant="outlined" sx={{ p: 1, mt: 0.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 220, overflow: 'auto', fontSize: '0.85rem' }}>
            {content}
          </Paper>
        );
      }
    }
  }

  if (checked) text = <>You said: {said}. Still correct?</>;

  return (
    <Box>
      <Typography variant="h5" component="p" sx={{ fontWeight: 500, lineHeight: 1.3 }}>{text}</Typography>
      {extra}
      {/* A freeze strip already carries its own hint ("Look only at the 'during freeze' frames"). */}
      {(checked || !isFreezeStrip(sample)) && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
          {checked ? 'Answer given by a human reviewer'
            : none && isFailedVerification(sample) ? 'The screen check failed on this frame: pick the screen it really shows.'
            : `Guess from: ${guessSourceText(sample)}`}
        </Typography>
      )}
    </Box>
  );
};

/**
 * Step 4k: the focused item of a grouped screen-id label, shown under the screen question
 * ("Focused: apps"). Read-only: the main Yes saves the screen and this focus together, and
 * "No, fix it" changes both in one form (one Yes, one Fix per sample; owner, 2026-10-03).
 */
const FocusLine: React.FC<{ focus: string; source: string }> = ({ focus, source }) => (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
    <Typography variant="h6" component="p" sx={{ fontWeight: 500 }}>Focused: <B>{focus}</B></Typography>
    <Typography variant="caption" color="text.secondary">focus guess from: {source}</Typography>
  </Box>
);

// ─── "No, fix it" forms (one per family) ──────────────────────────────────────

interface FixFormProps {
  sample: TrainingSample;
  onSubmit: (groundTruth: unknown) => void;
  onCancel: () => void;
  saving: boolean;
  /** screen-id: suggestions for "Screen not in the tree" (starters + labels already saved). */
  offTreeOptions?: string[];
  /** Open the screen dropdown on mount (failed-verification samples). */
  openScreenList?: boolean;
  /** Hide the form title (the question above already asks it). */
  hideTitle?: boolean;
  cancelText?: string;
  /** screen-id (step 4k): the app's screen groups, the screen answers. */
  groups?: ScreenGroup[];
  groupsLoading?: boolean;
}

const FixForm: React.FC<FixFormProps> = ({
  sample, onSubmit, onCancel, saving, offTreeOptions = [], openScreenList = false, hideTitle = false, cancelText = 'Cancel (Esc)',
  groups = [], groupsLoading = false,
}) => {
  const initial = asRecord(sample.proposed_label);
  const initialOffTree = isOffTree(sample.proposed_label);
  // Step 4k: the screen answer is a group; the proposal (grouped or not) seeds group + focus.
  const initialGroup = sample.family === 'screen-id' ? toGroupLabel(sample.proposed_label, groups) : null;
  const [nodeId, setNodeId] = useState(initialOffTree ? '' : asText(initialGroup?.node_id ?? initial.node_id ?? sample.node_id));
  const [nodeLabel, setNodeLabel] = useState(initialOffTree ? '' : asText(initialGroup?.label ?? initial.label));
  const [screenFocus, setScreenFocus] = useState(asText(initialGroup?.focus));
  const [nothingFocused, setNothingFocused] = useState(false);
  // The groups arrive after the first render: seed the answer from them once.
  const seeded = useRef(Boolean(initialGroup));
  useEffect(() => {
    if (seeded.current || sample.family !== 'screen-id' || initialOffTree || !groups.length) return;
    const g = toGroupLabel(sample.proposed_label, groups);
    seeded.current = true;
    if (g) {
      setNodeId(asText(g.node_id));
      setNodeLabel(asText(g.label));
      setScreenFocus(asText(g.focus));
    }
  }, [groups, sample.family, sample.proposed_label, initialOffTree]);
  // Screen not in the tree (step 4f): free text; when filled in it is the answer.
  const [offTree, setOffTree] = useState(initialOffTree ? asText(initial.label) : '');
  const [focused, setFocused] = useState(asText(initial.focused));
  const [focusNothing, setFocusNothing] = useState(sample.family === 'focus' && 'focused' in initial && initial.focused === null);
  const [noBanner, setNoBanner] = useState(isNoBanner(sample.proposed_label));
  const [channelNumber, setChannelNumber] = useState(asText(initial.channel_number));
  const [channelName, setChannelName] = useState(asText(initial.channel_name));
  const [items, setItems] = useState<string[]>(Array.isArray(initial.items) ? initial.items.map(asText) : ['']);
  const [selectedIndex, setSelectedIndex] = useState(() =>
    Array.isArray(initial.items) ? initial.items.map(asText).indexOf(asText(initial.selected)) : -1);
  const [incidentType, setIncidentType] = useState(() => {
    if (sample.proposed_label === null || sample.proposed_label === undefined) return '';
    const kind = asText(initial.incident_type);
    if (!kind) return 'none';
    // A type that is no longer an answer (audio_loss) preselects nothing.
    return AV_FAULTS.some(([v]) => v === kind) ? kind : '';
  });
  const [jsonText, setJsonText] = useState(
    sample.proposed_label === null || sample.proposed_label === undefined ? '{}' : JSON.stringify(sample.proposed_label, null, 2),
  );
  const [formError, setFormError] = useState('');
  const [screenListOpen, setScreenListOpen] = useState(openScreenList);

  const build = (): unknown => {
    switch (sample.family) {
      case 'screen-id': {
        if (offTree.trim()) return { node_id: null, label: offTree.trim().toLowerCase() };
        if (!nodeId.trim() || !nodeLabel.trim()) throw new Error('Pick the screen, or type it under "Screen not in the tree".');
        const group = groups.find((g) => g.node_id === nodeId.trim());
        if (!group) return { node_id: nodeId.trim(), label: nodeLabel.trim() };  // no groups for this app
        const focusValue = nothingFocused ? null : screenFocus.trim() || null;
        // Same group as proposed: keep the node the label named unless the focus picks another.
        const base: Label = initialGroup && asText(initialGroup.node_id) === group.node_id
          ? initialGroup
          : { node_id: group.node_id, label: group.label, node: group.node_id, node_label: group.label, focus: null };
        return withFocus({ ...base, node_id: group.node_id, label: group.label }, focusValue, groups);
      }
      case 'focus':
        if (focusNothing) return { focused: null };
        if (!focused.trim()) throw new Error('Type the highlighted item, or tick "Nothing focused".');
        return { focused: focused.trim() };
      case 'banner': {
        if (noBanner) return NO_BANNER;
        const out: Record<string, string> = {};
        if (channelNumber.trim()) out.channel_number = channelNumber.trim();
        if (channelName.trim()) out.channel_name = channelName.trim();
        if (!Object.keys(out).length) throw new Error('Type the channel number or name, or tick "No banner visible".');
        return out;
      }
      case 'menu': {
        const clean = items.map((s) => s.trim());
        const kept = clean.filter(Boolean);
        if (!kept.length) throw new Error('Add at least one menu item.');
        const sel = selectedIndex >= 0 ? clean[selectedIndex] : '';
        return { items: kept, selected: sel || null };
      }
      case 'av-fault':
        if (!incidentType) throw new Error('Pick one answer.');
        return { incident_type: incidentType === 'none' ? null : incidentType };
      default:
        try {
          return JSON.parse(jsonText);
        } catch {
          throw new Error('The answer is not valid JSON.');
        }
    }
  };

  const submit = () => {
    try {
      setFormError('');
      onSubmit(build());
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Invalid answer');
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      submit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onCancel();
    }
  };

  const title: Record<TrainingFamily, string> = {
    'screen-id': 'Which screen is it?',
    focus: 'Which item is highlighted?',
    banner: 'What does the channel banner show?',
    menu: 'What are the menu items?',
    'av-fault': 'What does this frame show?',
    'content-type': 'What kind of screen is this (and what is playing)?',
    other: 'What is the correct answer?',
  };

  return (
    <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexDirection: 'column', gap: 1.25 }} onKeyDown={onKeyDown}>
      {!hideTitle && <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{title[sample.family]}</Typography>}

      {sample.family === 'screen-id' && (groups.length > 0 || groupsLoading ? (
        <TextField
          select size="small" label="Screen" value={nodeId} autoFocus disabled={groupsLoading}
          helperText={groupsLoading ? 'Loading screens…' : 'A screen stays the same screen whichever tab or tile is focused'}
          SelectProps={{
            open: screenListOpen && !groupsLoading,
            onOpen: () => setScreenListOpen(true),
            onClose: () => setScreenListOpen(false),
          }}
          onChange={(e) => {
            const group = groups.find((g) => g.node_id === e.target.value);
            setNodeId(e.target.value);
            setNodeLabel(group?.label || '');
            setOffTree('');
          }}
        >
          {nodeId && !groups.some((g) => g.node_id === nodeId) && (
            <MenuItem value={nodeId}>{nodeLabel || 'Current guess'} (not a screen of this interface)</MenuItem>
          )}
          {groups.map((g) => (
            <MenuItem key={g.node_id} value={g.node_id}>
              {g.label}
              {g.members.length > 1 && (
                <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                  {g.members.length} focus states
                </Typography>
              )}
            </MenuItem>
          ))}
        </TextField>
      ) : (
        <>
          <Typography variant="caption" color="text.secondary">No screen list for this interface: type the screen name.</Typography>
          <TextField size="small" label="Screen name" value={nodeLabel}
            onChange={(e) => { setNodeLabel(e.target.value); setNodeId(e.target.value.trim()); setOffTree(''); }} autoFocus />
        </>
      ))}

      {sample.family === 'screen-id' && (
        <Autocomplete
          freeSolo size="small" options={offTreeOptions}
          // Driven by the typed text, so Ctrl+Enter saves what is typed without Enter/blur first.
          inputValue={offTree}
          onInputChange={(_e, value) => {
            setOffTree(value);
            if (value.trim()) { setNodeId(''); setNodeLabel(''); }
          }}
          renderInput={(params) => (
            <Tooltip title="A screen that is not in the navigation tree, e.g. popup, error, dialog, tip" placement="top">
              <TextField {...params} label="Screen not in the tree" placeholder="e.g. popup, error, dialog, tip" />
            </Tooltip>
          )}
        />
      )}

      {sample.family === 'screen-id' && !offTree.trim() && groups.some((g) => g.node_id === nodeId) && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
          <Autocomplete
            freeSolo size="small" sx={{ flex: 1, minWidth: 200 }} disabled={nothingFocused}
            options={(groups.find((g) => g.node_id === nodeId)?.members || [])
              .map((m) => m.focus).filter((f): f is string => Boolean(f))}
            inputValue={screenFocus}
            onInputChange={(_e, value) => setScreenFocus(value)}
            renderInput={(params) => <TextField {...params} label="Focused item" placeholder="e.g. Apps, Settings" />}
          />
          <FormControlLabel control={<Checkbox size="small" checked={nothingFocused}
            onChange={(e) => setNothingFocused(e.target.checked)} />} label="Nothing focused" />
        </Box>
      )}

      {sample.family === 'focus' && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
          <TextField size="small" label="Highlighted item" value={focused} disabled={focusNothing}
            onChange={(e) => setFocused(e.target.value)} autoFocus sx={{ flex: 1, minWidth: 200 }} />
          <FormControlLabel control={<Checkbox size="small" checked={focusNothing}
            onChange={(e) => setFocusNothing(e.target.checked)} />} label="Nothing focused" />
        </Box>
      )}

      {sample.family === 'banner' && <>
        <FormControlLabel control={<Checkbox checked={noBanner} onChange={(e) => setNoBanner(e.target.checked)} />} label="No banner visible" />
        <Box sx={{ display: 'flex', gap: 1 }}>
          <TextField size="small" label="Channel number" value={channelNumber} onChange={(e) => setChannelNumber(e.target.value)} disabled={noBanner} autoFocus sx={{ width: 140 }} />
          <TextField size="small" label="Channel name" value={channelName} onChange={(e) => setChannelName(e.target.value)} disabled={noBanner} sx={{ flex: 1 }} />
        </Box>
      </>}

      {sample.family === 'menu' && (
        <RadioGroup value={String(selectedIndex)} onChange={(e) => setSelectedIndex(Number(e.target.value))}>
          <Typography variant="caption" color="text.secondary">One item per line; tick the selected one.</Typography>
          {items.map((item, i) => (
            <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Radio size="small" value={String(i)} inputProps={{ 'aria-label': `Item ${i + 1} is selected` }} />
              <TextField size="small" value={item} placeholder={`Item ${i + 1}`} autoFocus={i === 0} sx={{ flex: 1 }}
                onChange={(e) => setItems((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))} />
              <IconButton size="small" aria-label={`Remove item ${i + 1}`} onClick={() => {
                setItems((prev) => prev.filter((_, j) => j !== i));
                setSelectedIndex((s) => (s === i ? -1 : s > i ? s - 1 : s));
              }}><Delete fontSize="small" /></IconButton>
            </Box>
          ))}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <FormControlLabel value="-1" control={<Radio size="small" />} label="Nothing selected" />
            <Button size="small" startIcon={<Add />} onClick={() => setItems((prev) => [...prev, ''])}>Add item</Button>
          </Box>
        </RadioGroup>
      )}

      {sample.family === 'av-fault' && (
        <RadioGroup value={incidentType} onChange={(e) => setIncidentType(e.target.value)}>
          <FormControlLabel value="none" control={<Radio size="small" />} label="No fault (false alarm)" />
          {AV_FAULTS.map(([v, l]) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={l} />)}
        </RadioGroup>
      )}

      {(sample.family === 'other' || sample.family === 'content-type') && (
        <TextField size="small" label="Correct answer (JSON)" value={jsonText} onChange={(e) => setJsonText(e.target.value)}
          multiline minRows={4} autoFocus inputProps={{ style: { fontFamily: 'monospace', fontSize: '0.8rem' } }} />
      )}

      {formError && <Alert severity="error">{formError}</Alert>}
      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
        <Button size="small" onClick={onCancel} disabled={saving}>{cancelText}</Button>
        <Button size="small" variant="contained" onClick={submit} disabled={saving}>Save answer (Ctrl+Enter)</Button>
      </Box>
    </Paper>
  );
};

// ─── Coverage panel (step 4h) ─────────────────────────────────────────────────

const CoverageBar: React.FC<{ pct: number }> = ({ pct }) => (
  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 120 }}>
    <LinearProgress variant="determinate" value={Math.min(100, pct)} sx={{ flex: 1, height: 6, borderRadius: 3 }} />
    <Typography variant="caption" sx={{ width: 42, textAlign: 'right' }}>{pct.toFixed(1)}%</Typography>
  </Box>
);

const CoverageAppScreens: React.FC<{ app: CoverageApp; k: number }> = ({ app, k }) => (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, py: 0.5 }}>
    <Typography variant="caption" color="text.secondary">
      No sample yet ({app.missing_screens.length}): {app.missing_screens.map((m) => m.label).join(', ') || 'none'}
    </Typography>
    {app.thin_screens.length > 0 && (
      <Typography variant="caption" color="text.secondary">
        Fewer than {k} ({app.thin_screens.length}): {app.thin_screens.map((m) => `${m.label} (${m.samples})`).join(', ')}
      </Typography>
    )}
    {app.offtree_labels.length > 0 && (
      <Typography variant="caption" color="text.secondary">Screens not in the tree: {app.offtree_labels.join(', ')}</Typography>
    )}
    {(app.groups || []).some((g) => (g.states_total ?? 1) > 1) && (
      <Box sx={{ mt: 0.5 }}>
        <Typography variant="caption" sx={{ fontWeight: 600 }}>
          Screen groups (the same screen with a different item focused; {app.node_screens ?? '?'} nodes in {app.screens} screens)
        </Typography>
        {(app.groups || []).filter((g) => (g.states_total ?? 1) > 1).map((g) => (
          <Typography key={g.node_id} variant="caption" component="div" color="text.secondary">
            <Box component="span" sx={{ fontWeight: 600, color: 'text.primary' }}>{g.label}</Box>
            {` · ${g.samples} sample${g.samples === 1 ? '' : 's'} · ${g.states_covered ?? 0}/${g.states_total ?? 0} focus states have one: `}
            {(g.states || []).map((st) => `${st.label}${st.focus ? ` [${st.focus}]` : ''} (${st.samples})`).join(', ')}
          </Typography>
        ))}
      </Box>
    )}
  </Box>
);

const CoveragePanel: React.FC<{ report: CoverageReport | null }> = ({ report }) => {
  const [openApp, setOpenApp] = useState<string | null>(null);
  if (!report) return null;
  const { k } = report;
  return (
    <Accordion disableGutters variant="outlined" sx={{ mb: 1.5 }}>
      <AccordionSummary expandIcon={<ExpandMore />}>
        <Typography variant="body2">
          Coverage · {report.global.exhaustiveness_pct.toFixed(1)}% of {report.global.screens} screens have {k}+ samples
        </Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <Typography variant="caption" color="text.secondary">
          A screen counts once it has {k} labelled screen-id samples. Click an app to see the screens it still needs.
        </Typography>
        {report.platforms.map((p) => (
          <Box key={p.platform} sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Typography variant="body2" sx={{ width: 90, fontWeight: 600 }}>{p.platform}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
              {p.screens_gek} of {p.screens} screens · {p.eval_verified} verified eval · {p.banner?.labelled ?? 0} labelled banners
            </Typography>
            <CoverageBar pct={p.pct_gek} />
          </Box>
        ))}
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>App</TableCell>
              <TableCell align="right">Screens</TableCell>
              <TableCell align="right">1+</TableCell>
              <TableCell align="right">{k}+</TableCell>
              <TableCell align="right">Eval verified</TableCell>
              <TableCell sx={{ width: 180 }} />
            </TableRow>
          </TableHead>
          <TableBody>
            {report.apps.map((a) => (
              <React.Fragment key={a.name}>
                <TableRow hover sx={{ cursor: 'pointer' }} onClick={() => setOpenApp(openApp === a.name ? null : a.name)}>
                  <TableCell>{a.name} <Typography component="span" variant="caption" color="text.secondary">{a.platform}</Typography></TableCell>
                  <TableCell align="right">{a.screens}</TableCell>
                  <TableCell align="right">{a.screens_ge1}</TableCell>
                  <TableCell align="right">{a.screens_gek}</TableCell>
                  <TableCell align="right">{a.eval_verified}</TableCell>
                  <TableCell><CoverageBar pct={a.pct_gek} /></TableCell>
                </TableRow>
                {openApp === a.name && (
                  <TableRow>
                    <TableCell colSpan={6}><CoverageAppScreens app={a} k={k} /></TableCell>
                  </TableRow>
                )}
              </React.Fragment>
            ))}
          </TableBody>
        </Table>
        {report.canonical_missing.length > 0 && (
          <Typography variant="caption" color="warning.main">Not found in this team: {report.canonical_missing.join(', ')}</Typography>
        )}
        <Accordion disableGutters variant="outlined">
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Typography variant="caption">Not in scope ({report.not_in_scope.length}): copies, fixtures and apps not covered yet</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
            {report.not_in_scope.map((o) => (
              <Typography key={o.name} variant="caption" color="text.secondary">
                {o.name} · {o.platform} · {o.screens} screens · {o.reason}
              </Typography>
            ))}
          </AccordionDetails>
        </Accordion>
      </AccordionDetails>
    </Accordion>
  );
};

// ─── Eval set panel ───────────────────────────────────────────────────────────

interface EvalPanelProps {
  counts: Partial<Record<TrainingFamily, number>>;
  agreedCounts: Partial<Record<TrainingFamily, number>>;
  threshold: number;
  aiThreshold: number;
  onFreeze: (family: TrainingFamily, version: string, minRows?: number) => void;
}

/** Step 4i: the two freeze options. eval-vN = human only; eval-vN-ai = human + AI-verified pilot. */
const FREEZE_PRESETS: [string, string][] = [
  ['eval-v1', 'eval-v1 · human-verified only'],
  ['eval-v0-ai', 'eval-v0-ai · human + AI-verified (pilot)'],
];

const EvalPanel: React.FC<EvalPanelProps> = ({ counts, agreedCounts, threshold, aiThreshold, onFreeze }) => {
  const [version, setVersion] = useState('eval-v1');
  const [minRows, setMinRows] = useState(String(aiThreshold));
  useEffect(() => setMinRows(String(aiThreshold)), [aiThreshold]);
  const withAi = isAiVersion(version);
  const aiMin = Number.parseInt(minRows, 10);
  const aiMinValid = Number.isFinite(aiMin) && aiMin >= 1;
  const needed = withAi ? (aiMinValid ? aiMin : Infinity) : threshold;
  const available = (f: TrainingFamily) => (counts[f] ?? 0) + (withAi ? agreedCounts[f] ?? 0 : 0);
  const ready = TRAINING_FAMILIES.filter((f) => available(f) >= needed).length;
  return (
    <Accordion disableGutters variant="outlined" sx={{ mb: 1.5 }}>
      <AccordionSummary expandIcon={<ExpandMore />}>
        <Typography variant="body2">
          Eval set · {ready ? `${ready} famil${ready === 1 ? 'y' : 'ies'} ready to freeze as ${version}` : `each family needs ${threshold} human-verified eval samples`}
        </Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
        <Typography variant="caption" color="text.secondary">
          Freezing locks a family&apos;s eval samples as a fixed test set. Their answers can never change afterwards.
          Human-verified: a person answered. AI-verified: the AI teacher gave the same answer as the test run.
          {' '}eval-v1 takes human-verified samples only ({threshold} needed). eval-v0-ai is a pilot that also takes
          AI-verified ones; its results are marked as mixed human + AI labels.
        </Typography>
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', my: 0.5 }}>
          <TextField select size="small" label="Freeze as" value={FREEZE_PRESETS.some(([v]) => v === version) ? version : ''}
            onChange={(e) => setVersion(e.target.value)} sx={{ minWidth: 290 }}>
            {FREEZE_PRESETS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Version" value={version} onChange={(e) => setVersion(e.target.value)} sx={{ width: 140 }}
            helperText={withAi ? 'ends in -ai: human + AI' : 'human only'} />
          {withAi && (
            <TextField size="small" label="Minimum samples" type="number" value={minRows} onChange={(e) => setMinRows(e.target.value)}
              error={!aiMinValid} sx={{ width: 150 }} inputProps={{ min: 1 }} />
          )}
        </Box>
        {TRAINING_FAMILIES.map((f) => {
          const human = counts[f] ?? 0;
          const agreed = agreedCounts[f] ?? 0;
          const enough = available(f) >= needed;
          return (
            <Box key={f} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="body2" sx={{ width: 90 }}>{f}</Typography>
              <Typography variant="body2" sx={{ flex: 1 }} color={enough ? 'success.main' : 'text.secondary'}>
                {human} human-verified · {agreed} AI-verified
                {withAi ? ` · ${available(f)} of ${aiMinValid ? aiMin : '?'} for ${version}` : ` · ${human} of ${threshold} for ${version}`}
              </Typography>
              <Button size="small" variant="outlined" color="warning" disabled={!enough || !version.trim()}
                onClick={() => onFreeze(f, version.trim(), withAi && aiMinValid ? aiMin : undefined)}>
                Freeze
              </Button>
            </Box>
          );
        })}
      </AccordionDetails>
    </Accordion>
  );
};

// ─── Page ─────────────────────────────────────────────────────────────────────

const TrainingReview: React.FC = () => {
  const P = useAgentChatPalette();
  const {
    samples, total, isLoading, error, evalCounts, evalThreshold, agreedCounts, aiThreshold,
    load, countSamples, loadEvalCounts, loadOfftreeLabels, loadCoverage, label, freeze, clearError,
  } = useTrainingSamples();
  const [coverage, setCoverage] = useState<CoverageReport | null>(null);
  const [filters, setFilters] = useState<TrainingFilters>(DEFAULT_FILTERS);
  // The Set follows the Show view ("Needs you": All, else Eval) until the user picks one.
  const [splitPinned, setSplitPinned] = useState(false);
  // "Needs you" with a Set picked and nothing in it: how many wait in the other sets.
  const [inOtherSets, setInOtherSets] = useState<number | null>(null);
  // index === samples.length is the end state (everything after it was checked).
  const [index, setIndex] = useState(0);
  const [editing, setEditing] = useState(false);
  // The image URL whose load finished (or failed): the question waits for it, so the text and
  // the image of a sample always appear together.
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  // x of the x/K counter: answers saved since the last (re)load. Skip does not count.
  const [answered, setAnswered] = useState(0);
  const [offTreeOptions, setOffTreeOptions] = useState<string[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();
  const pagingRef = useRef(false);

  const sample = samples[index] as TrainingSample | undefined;
  const frozen = sample ? isFrozen(sample) : false;
  const hasGuess = sample ? sample.proposed_label !== null && sample.proposed_label !== undefined : false;
  // Failed verification with no answer yet: straight to the screen list, no Yes button.
  const askScreenDirectly = sample ? isFailedVerification(sample) && !hasGuess && !frozen : false;
  const strip = sample ? isFreezeStrip(sample) : false;
  const removesOnLabel = SHOW_REMOVES_ON_LABEL[filters.show];
  // Step 4k: the screen groups of the sample's app (screen-id answers), and the focus line.
  const { groups, loading: groupsLoading } = useScreenGroups(
    sample && sample.family === 'screen-id' ? sample.userinterface : null);
  const grouped = sample && sample.family === 'screen-id' ? toGroupLabel(sample.proposed_label, groups) : null;
  const imageReady = !sample?.image_url || loadedUrl === sample.image_url;
  // Preload the next two images: answering then shows the next sample at once.
  useEffect(() => {
    for (const next of samples.slice(index + 1, index + 3)) {
      if (next.image_url) new Image().src = next.image_url;
    }
  }, [samples, index]);
  // The focused item the screen answer names ('' = none): shown, and saved by the main Yes.
  const shownFocus = grouped ? asText(grouped.focus) : '';

  const reload = useCallback(async (next: TrainingFilters) => {
    setIndex(0);
    setEditing(false);
    setActionError('');
    setAnswered(0);
    const { returned } = await load(next, 0, false);
    setHasMore(returned === PAGE_SIZE);
  }, [load]);

  useEffect(() => {
    void reload(filters);
    // Reload only when the filters change.
  }, [filters, reload]);

  useEffect(() => {
    void loadEvalCounts();
  }, [loadEvalCounts]);

  useEffect(() => {
    void loadCoverage().then(setCoverage);
  }, [loadCoverage]);

  useEffect(() => {
    void loadOfftreeLabels().then(setOffTreeOptions);
  }, [loadOfftreeLabels]);

  /**
   * Append the next page, starting at `offset` (the rows still in the list). Rows
   * already loaded are skipped; returns how many new rows arrived.
   */
  const fetchMore = useCallback(async (offset: number) => {
    if (pagingRef.current) return 0;
    pagingRef.current = true;
    try {
      let at = offset;
      for (let attempt = 0; attempt < 5; attempt += 1) {
        const { returned, added } = await load(filters, at, true);
        setHasMore(returned === PAGE_SIZE);
        if (added > 0 || returned < PAGE_SIZE) return added;
        at += PAGE_SIZE;
      }
      return 0;
    } finally {
      pagingRef.current = false;
    }
  }, [load, filters]);

  /** Skip (j): next sample, fetching the next page at the end. Never wraps around. */
  const goNext = useCallback(async () => {
    setEditing(false);
    setActionError('');
    if (index < samples.length - 1) {
      setIndex(index + 1);
      return;
    }
    if (index >= samples.length || !hasMore) return;
    const added = await fetchMore(samples.length);
    if (added > 0) setIndex(index + 1);
  }, [index, samples.length, hasMore, fetchMore]);

  /** Back (k): previous sample. Never wraps around. */
  const goPrev = useCallback(() => {
    setEditing(false);
    setActionError('');
    setIndex((i) => Math.max(0, Math.min(i, samples.length) - 1));
  }, [samples.length]);

  /**
   * Save the answer and show the next sample at once: the save runs in the background (it can
   * take about a second through a remote server). A failed save brings that sample back with
   * the error, so no answer is lost silently.
   */
  const save = useCallback((groundTruth: unknown) => {
    if (!sample || isFrozen(sample)) return;
    const at = index;
    setActionError('');
    setEditing(false);
    // A new "screen not in the tree" answer becomes a suggestion for the next ones.
    const offTreeLabel = isOffTree(groundTruth) ? asText(asRecord(groundTruth).label) : '';
    if (offTreeLabel) setOffTreeOptions((prev) => (prev.includes(offTreeLabel) ? prev : [...prev, offTreeLabel]));
    // Remove views: the row leaves the list now and the next one slides into this index.
    const pending = label(sample, groundTruth, removesOnLabel);
    if (removesOnLabel) {
      const remaining = samples.length - 1;
      if (at >= remaining && hasMore) void fetchMore(remaining);
    } else {
      void goNext();
    }
    pending
      .then(() => setAnswered((n) => n + 1))
      .catch((e) => {
        setIndex(at);
        setActionError(`Your answer for screenshot ${at + 1} was not saved: `
          + (e instanceof Error ? e.message : 'saving the answer failed'));
      });
  }, [sample, label, removesOnLabel, samples.length, index, hasMore, fetchMore, goNext]);

  const accept = useCallback(() => {
    if (!sample || isFrozen(sample)) return;
    if (!hasGuess) {
      // Nothing to confirm: ask for the answer instead.
      setEditing(true);
      return;
    }
    if (isChecked(sample)) {
      // "You said X. Still correct?" Yes: nothing to change.
      void goNext();
      return;
    }
    // Step 4k: a screen-id answer is saved in the group form, with the focus it names.
    if (grouped) {
      void save(grouped);
      return;
    }
    void save(sample.proposed_label);
  }, [sample, hasGuess, save, goNext, grouped]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (editing || !imageReady || dialogState.open || isTyping(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'y') { e.preventDefault(); accept(); }
      else if (e.key === 'n') {
        e.preventDefault();
        // A freeze strip has its own answer buttons, no fix form.
        if (sample && !isFrozen(sample) && !isFreezeStrip(sample)) setEditing(true);
      }
      else if (e.key === 'j') { e.preventDefault(); void goNext(); }
      else if (e.key === 'k') { e.preventDefault(); goPrev(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [editing, imageReady, dialogState.open, accept, goNext, goPrev, sample]);

  const setFilter = <K extends keyof TrainingFilters>(key: K, value: TrainingFilters[K]) =>
    setFilters((prev) => ({ ...prev, [key]: value }));
  const setShow = (show: ReviewShow) => setFilters((prev) => withShow(prev, show, splitPinned));
  const setSplit = (split: TrainingFilters['split']) => {
    setSplitPinned(true);
    setFilter('split', split);
  };

  const askFreeze = (family: TrainingFamily, version: string, minRows?: number) => {
    const withAi = isAiVersion(version);
    confirm({
      title: `Freeze ${version} for ${family}`,
      message: withAi
        ? `Every human-verified and AI-verified eval sample of ${family} becomes part of ${version}, a pilot with mixed human + AI labels. `
          + 'Their answers can never change afterwards, and a sample can be in one frozen set only: the human-verified samples '
          + `frozen here can no longer go into a human-only set such as eval-v1.`
        : `Every human-verified eval sample of ${family} becomes part of ${version}. Their answers can never change afterwards.`,
      confirmText: 'Freeze',
      confirmColor: 'warning',
      onConfirm: () => {
        setNotice('');
        setActionError('');
        freeze(family, version, minRows)
          .then((res) => { setNotice(`${version} frozen for ${family}: ${res.frozen} samples.`); void loadEvalCounts(); })
          .catch((e) => setActionError(e instanceof Error ? e.message : 'Freeze failed'));
      },
    });
  };

  const statusChip = (s: TrainingSample) => {
    if (isFrozen(s)) return (
      <Chip
        size="small"
        variant="outlined"
        label="Frozen"
        sx={{ color: P.series[1], bgcolor: `${P.series[1]}1f`, borderColor: `${P.series[1]}66`, border: '1px solid' }}
      />
    );
    if (isChecked(s)) return <Chip size="small" color="success" label="Checked by you" />;
    if (s.triage?.status === 'agreed') return null;  // the triage chip already says "Checked by AI"
    return <Chip size="small" variant="outlined" label="Not checked" />;
  };

  const meta: [string, React.ReactNode][] = sample ? [
    ['id', sample.id],
    ['family', sample.family],
    ['device model', sample.device_model],
    ['userinterface', sample.userinterface || '—'],
    ['node / focus', `${sample.node_id || '—'} / ${sample.focus_label || '—'}`],
    ['split', sample.split],
    ['label source', sample.label_source],
    ['model failure', sample.is_failure ? 'yes' : 'no'],
    ['label conflict', sample.label_conflict ? 'yes' : 'no'],
    ...(sample.label_conflict ? [['conflicts with', sample.conflict_partner
      ? `${sample.conflict_partner.id} · ${labelWords(sample.family, sample.conflict_partner.ground_truth, groups) || 'a different answer'}`
      : 'not found (relabelled or out of range)'] as [string, React.ReactNode]] : []),
    ['eval version', sample.eval_version || '—'],
    ...(sample.triage ? [['AI triage', [
      sample.triage.status,
      sample.triage.reason,
      sample.triage.teacher_model,
      sample.triage.teacher_confidence ? `confidence ${sample.triage.teacher_confidence}` : null,
      sample.triage.batch_id,
    ].filter(Boolean).join(' · ')] as [string, React.ReactNode]] : []),
    ['source', sample.source_ref ? JSON.stringify(sample.source_ref) : '—'],
    ['created', new Date(sample.created_at).toLocaleString('en-GB')],
  ] : [];
  const rawValues: [string, unknown][] = sample ? ([
    ['Proposed answer', sample.proposed_label],
    ['Model answer', sample.model_answer],
    ['Reference answer', sample.ground_truth],
    ['AI teacher answer', sample.triage?.teacher_label],
  ] as [string, unknown][]).filter(([, v]) => v !== null && v !== undefined) : [];

  const atEnd = !isLoading && !error && index >= samples.length;
  const needsYouEmptyInSet = atEnd && samples.length === 0 && filters.show === 'needs_you' && filters.split !== '';

  useEffect(() => {
    setInOtherSets(null);
    if (!needsYouEmptyInSet) return undefined;
    let alive = true;
    void countSamples({ ...filters, split: '' }).then((n) => { if (alive) setInOtherSets(n); });
    return () => { alive = false; };
  }, [needsYouEmptyInSet, filters, countSamples]);
  const skippedLeft = samples.length;
  const lastOne = index === samples.length - 1 && !hasMore;

  return (
    <Box
      sx={{
        p: 3,
        ...(pageSurfaceSx(P) as object),
        '& .MuiAccordion-root': { borderRadius: 2, borderColor: P.borderColor, '&:before': { display: 'none' } },
        '& .MuiCheckbox-root.Mui-checked': { color: P.accent },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
        <Typography sx={{ flex: 1, fontSize: '1.5rem', fontWeight: 600 }}>AI Dataset</Typography>
        <Tooltip title={`${answered} answered since the last reload, out of ${total} that matched the filters then`}>
          <Box component="span" sx={{ fontSize: '0.8rem', fontWeight: 600, px: 1.25, py: 0.4, borderRadius: 999, color: P.accentText, bgcolor: `${P.accent}26`, fontVariantNumeric: 'tabular-nums' }}>
            {answered}/{total}
          </Box>
        </Tooltip>
        <Tooltip title="Reload">
          <span><IconButton aria-label="Reload samples" onClick={() => void reload(filters)} disabled={isLoading}><Refresh /></IconButton></span>
        </Tooltip>
      </Box>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 1.5 }}>
        Check each screenshot against the question. Your answers become the reference answers the AI is tested on.
      </Typography>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
        <TextField select size="small" label="Show" value={filters.show} onChange={(e) => setShow(e.target.value as ReviewShow)} sx={{ minWidth: 170 }}>
          {SHOW_OPTIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Family" value={filters.family} {...SHOW_EMPTY_OPTION} onChange={(e) => setFilter('family', e.target.value as TrainingFilters['family'])} sx={{ minWidth: 140 }}>
          <MenuItem value="">All</MenuItem>
          {TRAINING_FAMILIES.map((f) => <MenuItem key={f} value={f}>{f}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Set" value={filters.split} {...SHOW_EMPTY_OPTION} onChange={(e) => setSplit(e.target.value as TrainingFilters['split'])} sx={{ minWidth: 120 }}>
          {SPLIT_OPTIONS.map(([v, l]) => <MenuItem key={v || 'all'} value={v}>{l}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="AI got it" value={filters.isFailure} {...SHOW_EMPTY_OPTION} onChange={(e) => setFilter('isFailure', e.target.value as TrainingFilters['isFailure'])} sx={{ minWidth: 130 }}>
          {[['', 'All'], ['true', 'Wrong'], ['false', 'Right']].map(([v, l]) => <MenuItem key={v || 'all'} value={v}>{l}</MenuItem>)}
        </TextField>
        <TextField size="small" label="Device model" value={filters.deviceModel} onChange={(e) => setFilter('deviceModel', e.target.value)} sx={{ width: 150 }} />
        <FormControlLabel control={<Checkbox size="small" checked={filters.balance} onChange={(e) => setFilter('balance', e.target.checked)} />} label="Mix device models" />
        <Tooltip title="Only near-identical screenshots that were given different answers (look-alike screens such as Home vs TV Guide)">
          <FormControlLabel control={<Checkbox size="small" checked={filters.confusable} onChange={(e) => setFilter('confusable', e.target.checked)} />} label="Confusable pairs" />
        </Tooltip>
      </Box>

      <CoveragePanel report={coverage} />
      <EvalPanel counts={evalCounts} agreedCounts={agreedCounts} threshold={evalThreshold} aiThreshold={aiThreshold} onFreeze={askFreeze} />

      {error && <Alert severity="error" onClose={clearError} sx={{ mb: 1.5 }}>{error}</Alert>}
      {actionError && <Alert severity="error" onClose={() => setActionError('')} sx={{ mb: 1.5 }}>{actionError}</Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}

      {sample && lastOne && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>This is the last one.</Typography>
      )}

      {isLoading && !sample && <Box sx={{ p: 4, textAlign: 'center' }}><CircularProgress /></Box>}

      {atEnd && removesOnLabel && answered > 0 && (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1.5 }}>
          <Typography variant="h5">All done: {answered} checked</Typography>
          {skippedLeft > 0 && (
            <Typography color="text.secondary">
              {skippedLeft} skipped screenshot{skippedLeft === 1 ? ' is' : 's are'} still not checked. Press Back (k) to return to {skippedLeft === 1 ? 'it' : 'them'}.
            </Typography>
          )}
          <Button variant="outlined" onClick={() => setShow('checked')}>Show already checked</Button>
        </Paper>
      )}
      {atEnd && !(removesOnLabel && answered > 0) && samples.length === 0 && (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1.5 }}>
          <Typography color="text.secondary">
            {needsYouEmptyInSet ? `Nothing the AI triage sent to you in the ${splitName(filters.split)} set.`
              : filters.show === 'needs_you' ? 'Nothing the AI triage sent to you for these filters.'
              : removesOnLabel ? 'Nothing left to check for these filters.' : 'No screenshots match these filters.'}
          </Typography>
          {needsYouEmptyInSet && inOtherSets !== null && inOtherSets > 0 && (
            <>
              <Typography>
                {inOtherSets} screenshot{inOtherSets === 1 ? ' is' : 's are'} waiting for you in the other sets.
              </Typography>
              <Button variant="contained" onClick={() => setSplit('')}>Show all sets</Button>
            </>
          )}
          {removesOnLabel && <Button variant="outlined" onClick={() => setShow('checked')}>Show already checked</Button>}
        </Paper>
      )}

      {sample && (
        // alignItems start: the image box hugs the image instead of stretching to the height of
        // the question column (the image used to float in a tall empty box).
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 3fr) minmax(340px, 2fr)' }, gap: 2, alignItems: 'start' }}>
          <Paper variant="outlined" sx={{ p: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', bgcolor: P.surface }}>
            {sample.image_url
              // Fit the width, at most 70vh tall (a tall freeze strip shrinks, centred at the top).
              ? <>
                  {!imageReady && <Box sx={{ p: 4 }}><CircularProgress /></Box>}
                  <Box component="img" key={sample.image_url} src={sample.image_url} alt={`Screenshot ${index + 1}`}
                    ref={(img: HTMLImageElement | null) => { if (img?.complete && img.naturalWidth) setLoadedUrl(img.currentSrc || img.src); }}
                    onLoad={() => setLoadedUrl(sample.image_url)} onError={() => setLoadedUrl(sample.image_url)}
                    sx={{ display: imageReady ? 'block' : 'none', width: '100%', height: 'auto', maxHeight: '70vh', objectFit: 'contain', objectPosition: 'center top' }} />
                </>
              : <Typography sx={{ color: P.textMuted, p: 4 }}>No image (training storage is not configured on this server)</Typography>}
            {strip && <StripFrameChips sample={sample} />}
          </Paper>

          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, minWidth: 0, visibility: imageReady ? 'visible' : 'hidden' }}>
            {(filters.show === 'all' || frozen || sample.triage) && (
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                {filters.show === 'all' && statusChip(sample)}
                {triageChip(sample)}
                {frozen && (
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`Frozen in ${sample.eval_version}, read-only`}
                    sx={{ color: P.series[1], bgcolor: `${P.series[1]}1f`, borderColor: `${P.series[1]}66`, border: '1px solid' }}
                  />
                )}
              </Box>
            )}

            {askScreenDirectly ? (
              <>
                <Question sample={sample} groups={groups} />
                <TriageNote sample={sample} groups={groups} />
                <FixForm key={sample.id} sample={sample} onSubmit={(gt) => void save(gt)} onCancel={() => void goNext()}
                  saving={!imageReady} offTreeOptions={offTreeOptions} groups={groups} groupsLoading={groupsLoading}
                  openScreenList hideTitle cancelText="Skip (Esc)" />
              </>
            ) : strip ? (
              <>
                <Question sample={sample} groups={groups} />
                <TriageNote sample={sample} groups={groups} />
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, alignItems: 'stretch' }}>
                  {STRIP_ANSWERS.map(([bold, rest, answer, color]) => (
                    // One text block: as two flex items the bold part and the hint sat side by side
                    // in two ragged columns.
                    <Button key={bold} variant="contained" color={color} size="large"
                      onClick={() => save(answer)} disabled={frozen}>
                      <Box component="span"><strong>{bold}</strong> <Box component="span" sx={{ fontWeight: 400 }}>{rest}</Box></Box>
                    </Button>
                  ))}
                  <Button variant="outlined" size="large" onClick={() => void goNext()} disabled={lastOne}>Can&apos;t tell</Button>
                </Box>
              </>
            ) : editing && !frozen ? (
              <FixForm key={sample.id} sample={sample} onSubmit={(gt) => void save(gt)} onCancel={() => setEditing(false)}
                saving={!imageReady} offTreeOptions={offTreeOptions} groups={groups} groupsLoading={groupsLoading} />
            ) : (
              <>
                <Question sample={sample} groups={groups} />
                {shownFocus && <FocusLine focus={shownFocus} source={focusGuessSource(sample)} />}
                <TriageNote sample={sample} groups={groups} />
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                  <Button variant="contained" color="success" size="large" disableElevation onClick={accept} disabled={!imageReady || frozen || !hasGuess} sx={{ textTransform: 'none', fontWeight: 600, borderRadius: 2 }}>
                    {/* A checked sample with an unchanged focus: y only moves on, nothing is saved. */}
                    {acceptButtonText(grouped ? asText(grouped.label) : '',
                      isChecked(sample) || !shownFocus ? undefined : shownFocus)}
                  </Button>
                  <Button variant="outlined" color="error" size="large" onClick={() => setEditing(true)} disabled={!imageReady || frozen} sx={{ textTransform: 'none', fontWeight: 600, borderRadius: 2 }}>✗ No, fix it (n)</Button>
                  {sample.family === 'focus' && (
                    // Step 4k: fullscreen video, splash: no element has the focus.
                    <Button variant="outlined" size="large" onClick={() => void save({ focused: null })} disabled={!imageReady || frozen}>Nothing focused</Button>
                  )}
                </Box>
                {!hasGuess && !frozen && <Typography variant="body2" color="text.secondary">No guess to confirm: press n to give the answer.</Typography>}
              </>
            )}
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button onClick={goPrev} disabled={index === 0} sx={{ textTransform: 'none', color: P.textSecondary }}>Back (k)</Button>
              <Button onClick={() => void goNext()} disabled={lastOne} sx={{ textTransform: 'none', color: P.accentText }}>Skip (j)</Button>
            </Box>

            <Accordion disableGutters variant="outlined">
              <AccordionSummary expandIcon={<ExpandMore />}><Typography variant="body2">Details</Typography></AccordionSummary>
              <AccordionDetails sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {rawValues.map(([title, value]) => (
                  <Box key={title}>
                    <Typography variant="caption" color="text.secondary">{title}</Typography>
                    <Paper variant="outlined" sx={{ p: 1, fontFamily: 'monospace', fontSize: '0.8rem', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 200, overflow: 'auto' }}>
                      {pretty(value)}
                    </Paper>
                  </Box>
                ))}
                <Box>
                  {meta.map(([k, v]) => (
                    <Box key={k} sx={{ display: 'flex', gap: 1 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ width: 100, flexShrink: 0 }}>{k}</Typography>
                      <Typography variant="caption" sx={{ overflowWrap: 'anywhere' }}>{v}</Typography>
                    </Box>
                  ))}
                </Box>
              </AccordionDetails>
            </Accordion>
          </Box>
        </Box>
      )}

      {sample && index === samples.length - 1 && isLoading && (
        <Box sx={{ p: 2, textAlign: 'center' }}><CircularProgress size={20} /></Box>
      )}

      <ConfirmDialog
        open={dialogState.open}
        title={dialogState.title}
        message={dialogState.message}
        confirmText={dialogState.confirmText}
        cancelText={dialogState.cancelText}
        confirmColor={dialogState.confirmColor}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </Box>
  );
};

export default TrainingReview;
