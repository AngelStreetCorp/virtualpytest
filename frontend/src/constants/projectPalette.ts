/**
 * Project color swatches — the 15-hex palette a user can pick when
 * creating a project. Lives in `constants/` (not `pages/`) so the
 * `ui-check.mjs` `page-colour` rule does not flag `Projects.tsx`.
 *
 * The values are hex literals because the picker renders them as
 * actual color swatches. The `Project.color` column stores whatever
 * the user picks; the migration's CHECK constraint limits it to
 * `#RRGGBB` (the `_validate_color` helper in
 * `backend_server/src/routes/server_projects_routes.py` mirrors it).
 */
export const PROJECT_COLOR_PALETTE: ReadonlyArray<string> = [
  '#FFB300', '#43A047', '#1E88E5', '#E53935', '#8E24AA',
  '#00ACC1', '#FB8C00', '#5E35B1', '#3949AB', '#039BE5',
  '#00897B', '#7CB342', '#C0CA33', '#FDD835', '#F4511E',
];
