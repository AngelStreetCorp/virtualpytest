import { useModStore } from '../../../../../frontend/src/mods/core/hooks/useModStore';
import { onlineStore } from '../data/store';

export const useOnline = () => useModStore(onlineStore);
