-- Inverse of 20261026a_platform_servers.sql (drops the server list; the frontend picker then has no servers to show).
BEGIN;
DROP TABLE IF EXISTS public.platform_servers;
COMMIT;
