/**
 * Cron Utilities
 * Functions for validating and working with cron expressions
 */

/**
 * Validate cron expression format (basic validation)
 */
export function validateCronExpression(cron: string): { valid: boolean; error?: string } {
  if (!cron || !cron.trim()) {
    return { valid: false, error: 'Cron expression is required' };
  }
  
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) {
    return { valid: false, error: 'Cron must have 5 parts: minute hour day month day_of_week' };
  }
  
  const [minute, hour, day, month, dayOfWeek] = parts;
  
  // Basic validation for each part
  const validations = [
    { part: minute, name: 'minute', min: 0, max: 59 },
    { part: hour, name: 'hour', min: 0, max: 23 },
    { part: day, name: 'day', min: 1, max: 31 },
    { part: month, name: 'month', min: 1, max: 12 },
    { part: dayOfWeek, name: 'day_of_week', min: 0, max: 6 },
  ];
  
  for (const { part, name, min, max } of validations) {
    if (!isValidCronPart(part, min, max)) {
      return { valid: false, error: `Invalid ${name}: ${part}` };
    }
  }
  
  return { valid: true };
}

/**
 * Check if a single cron part is valid
 */
function isValidCronPart(part: string, min: number, max: number): boolean {
  // Asterisk is always valid
  if (part === '*') return true;
  
  // Check for step values (*/5)
  if (part.startsWith('*/')) {
    const step = parseInt(part.substring(2));
    return !isNaN(step) && step > 0 && step <= max;
  }
  
  // Check for ranges (1-5)
  if (part.includes('-')) {
    const [start, end] = part.split('-').map(n => parseInt(n));
    return !isNaN(start) && !isNaN(end) && start >= min && end <= max && start <= end;
  }
  
  // Check for lists (1,2,3)
  if (part.includes(',')) {
    const numbers = part.split(',').map(n => parseInt(n));
    return numbers.every(n => !isNaN(n) && n >= min && n <= max);
  }
  
  // Check for specific number
  const num = parseInt(part);
  return !isNaN(num) && num >= min && num <= max;
}

/**
 * Convert cron expression to human-readable description
 */
export function cronToHuman(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return 'Invalid cron expression';
  
  const [minute, hour, , , dayOfWeek] = parts;
  
  // Common patterns
  const everyNMinutes = cron.match(/^\*\/(\d+) \* \* \* \*$/);
  if (everyNMinutes) {
    const mins = parseInt(everyNMinutes[1], 10);
    if (!Number.isFinite(mins) || mins <= 0) {
      return `Cron: ${cron}`;
    }

    // Cron steps on the minute field mean "matching minute values in each hour",
    // not rolling fixed intervals from the current time. For values that divide 60,
    // the wording "Every N minutes" is accurate. For others (e.g. */40), show the
    // exact minute positions to avoid implying :20 / :60 style intervals.
    if (60 % mins === 0) {
      return `Every ${mins} minutes`;
    }

    const minuteMarks: number[] = [];
    for (let mark = 0; mark < 60; mark += mins) {
      minuteMarks.push(mark);
    }
    const formattedMarks = minuteMarks.map((mark) => `:${String(mark).padStart(2, '0')}`).join(', ');
    return `At ${formattedMarks} each hour`;
  }
  
  if (cron === '0 * * * *') return 'Every hour';
  if (cron.match(/^\d+ \* \* \* \*$/)) {
    const mins = minute;
    return `Every hour at :${mins.padStart(2, '0')}`;
  }
  if (cron.match(/^0 \*\/\d+ \* \* \*$/)) {
    const hrs = hour.substring(2);
    return `Every ${hrs} hours`;
  }
  
  if (cron.match(/^\d+ \d+ \* \* \*$/)) {
    return `Daily at ${hour}:${minute.padStart(2, '0')}`;
  }
  
  if (cron.match(/^\d+ \d+ \* \* [0-6]$/)) {
    const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    return `Weekly on ${days[parseInt(dayOfWeek)]} at ${hour}:${minute.padStart(2, '0')}`;
  }
  
  if (cron.match(/^\d+ \d+-\d+ \* \* \d-\d$/)) {
    return `Business hours (Mon-Fri, ${hour})`;
  }
  
  return `Cron: ${cron}`;
}

/**
 * Compute the next execution time after a given date (defaults to now).
 * Handles the common cron patterns used in VirtualPyTest deployments.
 * Returns null for unrecognised patterns.
 */
export function getNextCronExecution(cron: string, after?: Date): Date | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;

  const now = after || new Date();
  // Work in whole minutes
  const base = new Date(now);
  base.setSeconds(0, 0);
  base.setTime(base.getTime() + 60_000); // at least 1 minute from now

  // Every N minutes: */N * * * *
  const everyNMin = cron.match(/^\*\/(\d+) \* \* \* \*$/);
  if (everyNMin) {
    const n = parseInt(everyNMin[1]);
    const cur = base.getMinutes();
    const next = Math.ceil(cur / n) * n;
    if (next < 60) {
      base.setMinutes(next);
    } else {
      base.setMinutes(0);
      base.setTime(base.getTime() + 3_600_000);
    }
    return base;
  }

  // Every hour at minute M: M * * * * (where M is a number)
  const everyHourAtMin = cron.match(/^(\d+) \* \* \* \*$/);
  if (everyHourAtMin) {
    const targetMin = parseInt(everyHourAtMin[1]);
    base.setMinutes(targetMin);
    base.setSeconds(0, 0);
    if (base <= now) base.setTime(base.getTime() + 3_600_000);
    return base;
  }

  // Every N hours: 0 */N * * *
  const everyNHr = cron.match(/^0 \*\/(\d+) \* \* \*$/);
  if (everyNHr) {
    const n = parseInt(everyNHr[1]);
    base.setMinutes(0);
    const cur = base.getHours();
    const next = Math.ceil(cur / n) * n;
    if (next < 24) {
      base.setHours(next);
    } else {
      base.setHours(0);
      base.setDate(base.getDate() + 1);
    }
    return base;
  }

  // Daily at H:M: M H * * *
  const daily = cron.match(/^(\d+) (\d+) \* \* \*$/);
  if (daily) {
    base.setHours(parseInt(daily[2]), parseInt(daily[1]), 0, 0);
    if (base <= now) base.setDate(base.getDate() + 1);
    return base;
  }

  // Weekly on day D at H:M: M H * * D
  const weekly = cron.match(/^(\d+) (\d+) \* \* (\d)$/);
  if (weekly) {
    const targetDay = parseInt(weekly[3]);
    base.setHours(parseInt(weekly[2]), parseInt(weekly[1]), 0, 0);
    const daysUntil = (targetDay - base.getDay() + 7) % 7 || (base <= now ? 7 : 0);
    base.setDate(base.getDate() + daysUntil);
    return base;
  }

  return null;
}

/**
 * Convert old schedule format to cron
 */
export function legacyToCron(
  scheduleType: string,
  scheduleConfig: { hour?: number; minute?: number; day?: number }
): string {
  const minute = scheduleConfig.minute || 0;
  const hour = scheduleConfig.hour || 0;
  const day = scheduleConfig.day || 0;
  
  switch (scheduleType) {
    case 'hourly':
      return `${minute} * * * *`;
    case 'daily':
      return `${minute} ${hour} * * *`;
    case 'weekly':
      return `${minute} ${hour} * * ${day}`;
    default:
      return '0 * * * *'; // default: every hour
  }
}
