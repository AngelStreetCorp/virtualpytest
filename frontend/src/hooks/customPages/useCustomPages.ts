import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { usePermissions } from '../auth/usePermissions';
import * as api from './customPagesApi';

const ROOT = 'custom-pages';

/** Pages the user may open. Off (no request) for a user without `pages.custom:view`. */
export const useCustomPages = () => {
  const { hasPermission } = usePermissions();
  const canView = hasPermission('pages.custom:view');
  return useQuery({ queryKey: [ROOT, 'list'], queryFn: api.fetchPages, enabled: canView, staleTime: 15_000 });
};

export const useCatalogue = () => useQuery({ queryKey: [ROOT, 'catalogue'], queryFn: api.fetchCatalogue });

export const useCustomPage = (id: string | undefined) =>
  useQuery({ queryKey: [ROOT, 'page', id], queryFn: () => api.fetchPage(id as string), enabled: Boolean(id) });

export const useSharing = (id: string | undefined, enabled: boolean) =>
  useQuery({ queryKey: [ROOT, 'sharing', id], queryFn: () => api.fetchSharing(id as string), enabled: Boolean(id) && enabled });

export const useCustomPageMutations = () => {
  const client = useQueryClient();
  const invalidate = () => client.invalidateQueries({ queryKey: [ROOT] });
  return {
    create: useMutation({ mutationFn: api.createPage, onSuccess: invalidate }),
    update: useMutation({
      mutationFn: ({ id, ...input }: { id: string } & Parameters<typeof api.updatePage>[1]) => api.updatePage(id, input),
      onSuccess: (page) => {
        client.setQueryData([ROOT, 'page', page.id], page);
        invalidate();
      },
    }),
    remove: useMutation({ mutationFn: api.deletePage, onSuccess: invalidate }),
    saveSharing: useMutation({
      mutationFn: ({ id, ...input }: { id: string } & Parameters<typeof api.saveSharing>[1]) => api.saveSharing(id, input),
      onSuccess: invalidate,
    }),
  };
};
