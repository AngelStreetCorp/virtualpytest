/**
 * Shared helpers for testcase builder hooks/components.
 */

export const getErrorMessage = (error: unknown, fallback = 'Unknown error'): string => {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
};

export const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
