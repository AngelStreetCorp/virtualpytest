-- Rollback of 20261022c_image_telemetry.sql (TASK-157). Nothing else depends on the table.
BEGIN;
DROP TABLE IF EXISTS public.image_telemetry_buckets;
COMMIT;
