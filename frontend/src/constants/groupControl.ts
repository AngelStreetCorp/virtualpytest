/** Group remote control limits (TASK-76). */
export const GROUP_MIN_SIZE = 2;
export const GROUP_MAX_SIZE = 6;

/** Status queries go to the first member only; their answer drives the remote's dot. */
export const GROUP_PRIMARY_ONLY_COMMANDS = new Set(['get_pairing_status', 'get_status']);

/** How many sent commands the remote footer keeps. */
export const GROUP_LOG_SIZE = 5;
