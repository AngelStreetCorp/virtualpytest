-- =====================================================
-- Fix: Profiles RLS infinite recursion
-- The "Admins can view/update all profiles" policies
-- queried public.profiles inside a profiles policy,
-- causing infinite recursion (Supabase error 42P17).
-- Fix: use a SECURITY DEFINER function that bypasses
-- RLS when checking the admin role.
-- =====================================================

-- is_admin() runs as the function owner (bypasses RLS), breaking the recursion
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin');
END;
$$;

DROP POLICY IF EXISTS "Admins can view all profiles" ON public.profiles;
DROP POLICY IF EXISTS "Admins can update all profiles" ON public.profiles;

CREATE POLICY "Admins can view all profiles"
  ON public.profiles FOR SELECT
  USING (auth.uid() = id OR public.is_admin());

CREATE POLICY "Admins can update all profiles"
  ON public.profiles FOR UPDATE
  USING (public.is_admin());
