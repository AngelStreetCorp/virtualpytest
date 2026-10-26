-- Inverse of 20261014d_executable_favorites.sql (drops every user's executable favorites).
BEGIN;
DROP TABLE IF EXISTS public.executable_favorites;
COMMIT;
