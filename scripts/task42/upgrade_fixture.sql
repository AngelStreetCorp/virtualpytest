-- Existing-data fixture for the TASK-42 upgrade gate (scripts/task42_gate.py).
-- Applied to a DISPOSABLE database that holds the schema as of the base revision,
-- BEFORE the TASK-42 migrations, so the migrations are proven against populated tables.
INSERT INTO public.tenants (id, name, slug)
VALUES ('4a420000-0000-0000-0000-000000000001', 'gate tenant', 'gate-tenant-t42')
ON CONFLICT DO NOTHING;
INSERT INTO public.teams (id, name, tenant_id) VALUES
    ('4a420000-0000-0000-0000-0000000000a1', 'gate team a', '4a420000-0000-0000-0000-000000000001'),
    ('4a420000-0000-0000-0000-0000000000b1', 'gate team b', '4a420000-0000-0000-0000-000000000001')
ON CONFLICT DO NOTHING;
INSERT INTO public.script_results
    (id, team_id, script_name, script_type, userinterface_name, host_name, device_name, success,
     execution_time_ms, started_at, completed_at, discard, metadata, environment)
SELECT ('4a42' || lpad(to_hex(g), 4, '0') || '-0000-0000-0000-000000000000')::uuid,
       CASE WHEN g % 2 = 0 THEN '4a420000-0000-0000-0000-0000000000a1'::uuid
            ELSE '4a420000-0000-0000-0000-0000000000b1'::uuid END,
       'goto_live', 'script', 'gate_ui', 'gate-host', 'device1', g % 3 <> 0,
       1000 + g, now() - make_interval(hours => g), now() - make_interval(hours => g) + interval '1 minute',
       false, '{}'::jsonb, 'prod'
FROM generate_series(1, 40) AS g
ON CONFLICT DO NOTHING;
INSERT INTO public.campaign_executions
    (team_id, campaign_name, campaign_execution_id, host_name, device_name, started_at)
VALUES ('4a420000-0000-0000-0000-0000000000a1', 'gate campaign', 'gate-campaign-exec-1',
        'gate-host', 'device1', now() - interval '2 days')
ON CONFLICT DO NOTHING;
INSERT INTO public.testcase_definitions (team_id, testcase_name, graph_json)
VALUES ('4a420000-0000-0000-0000-0000000000a1', 'gate testcase', '{"nodes":[],"edges":[]}'::jsonb)
ON CONFLICT DO NOTHING;
