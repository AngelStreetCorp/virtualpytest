/** Short grouping label for a free-text triage discard comment. */
const RULES: Array<[RegExp, string]> = [
  [/test (pattern|stream)|looping|timecode|colou?r bars?/i, 'Test stream'],
  [/vnc|desktop/i, 'Idle desktop'],
  [/menu|home screen|login|settings|guide|interface|logo|poster|update screen|progress bar|setup/i, 'Menu screen'],
  [/silen|-\d+\s?db|low (audio|volume)/i, 'Silent content'],
  [/idle|standby|static|still/i, 'Idle screen'],
];

export const discardReason = (comment?: string | null): string | null => {
  if (!comment || !comment.trim()) return null;
  for (const [re, label] of RULES) if (re.test(comment)) return label;
  return 'Other';
};
