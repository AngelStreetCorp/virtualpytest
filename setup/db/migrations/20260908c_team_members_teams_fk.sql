-- 20260908c_team_members_teams_fk.sql
-- Forward migration: give team_members the foreign key to teams it never had.
--
-- public.team_members has team_members_user_id_fkey (user_id -> profiles.id) but nothing
-- on team_id, so:
--
--   1. There is no referential integrity on team_id at all — a membership row can point
--      at a team that does not exist, and deleting a team leaves its memberships behind.
--   2. PostgREST cannot embed the relationship, so any query of the form
--        team_members.select('team_id, teams(name, permissions)')
--      fails with PGRST200 "Could not find a relationship between 'team_members' and
--      'teams' in the schema cache". users_db.get_user() does exactly that, which is why
--      GET /server/users/<id> returned 404 for every user even after TASK-10 moved the
--      server onto the service_role key and RLS stopped being the obstacle (BUG-0062 was
--      two bugs wearing one coat: RLS, and this).
--
-- Verified 0 orphan rows before adding the constraint:
--   SELECT count(*) FROM team_members tm LEFT JOIN teams t ON t.id = tm.team_id
--    WHERE t.id IS NULL;  -- 0
--
-- ON DELETE CASCADE matches team_members_user_id_fkey: deleting a team removes its
-- memberships, as deleting a profile already does.
--
-- Apply with:
--   PGPASSWORD=$PGPASSWORD psql -h <db-vm> -p 54322 -U supabase_admin -d postgres \
--     -f setup/db/migrations/20260908c_team_members_teams_fk.sql
--   NOTIFY pgrst, 'reload schema';

DO $$ BEGIN
    ALTER TABLE public.team_members
        ADD CONSTRAINT team_members_team_id_fkey
        FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_team_members_team_id ON public.team_members(team_id);
