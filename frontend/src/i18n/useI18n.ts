import { useSyncExternalStore } from 'react';

import {
  formatDate,
  formatNumber,
  getLanguage,
  setLanguage,
  subscribe,
  translate,
  translatePlural,
} from './index';

/** Components that render text call this so they re-render on a language switch. */
export const useI18n = () => {
  const lang = useSyncExternalStore(subscribe, getLanguage, getLanguage);
  return { t: translate, tn: translatePlural, lang, setLanguage, formatDate, formatNumber };
};

export default useI18n;
