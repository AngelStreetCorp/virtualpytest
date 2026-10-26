-- Inverse of 20261014b_device_favorites.sql (drops every user's favorites).
BEGIN;
DROP TABLE IF EXISTS public.device_favorites;
COMMIT;
