-- deployments.created_by must not block deleting a user.
--
-- The FK was created without an ON DELETE action, so it defaults to NO ACTION:
-- once a deployment row carries a created_by, deleting that user raises
-- foreign_key_violation and the account can never be removed. Offboarding then
-- fails on a person simply because they once deployed something.
--
-- SET NULL is the right semantic here: the deployment record is history that
-- belongs to the team (same rule as script_results and campaign runs — deleting
-- a user removes access, never the record of what was tested). Losing the author
-- reference is acceptable; losing the ability to remove someone's access is not.
--
-- Safe to run: created_by is NULL on every existing row (289/289 on the reference
-- deployment as of 2026-09-14) and nothing in the codebase writes it today, so
-- this rewrites no data. It closes the defect before anything starts populating it.
--
-- Related: BUG-0079.

ALTER TABLE public.deployments
    DROP CONSTRAINT IF EXISTS deployments_created_by_fkey;

ALTER TABLE public.deployments
    ADD CONSTRAINT deployments_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE SET NULL;
