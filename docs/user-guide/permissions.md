# Who can do what

Three things decide what a person sees and can change: their **role**, their **team**, and their
**workspace**. They answer different questions, and mixing them up is the usual source of
confusion.

| | answers | set by |
|---|---|---|
| **Role** | *what may I do?* | an admin, on the Users page |
| **Team** | *whose data am I looking at?* — and, optionally, *what extra may I do?* | an admin, on the Users and Teams pages |
| **Workspace** | *which slice of it is on screen?* | anyone, from the top bar |

The team does two jobs. It is the data wall, and it can also carry permissions of its own that
every member gets on top of their role — see [Giving a whole team an extra permission](#giving-a-whole-team-an-extra-permission).

---

## The picture

```
        ┌──────────────┐
        │   ACCOUNT    │   email + password, confirmed by email
        └──────┬───────┘
               │ one account = one profile
        ┌──────▼───────┐
        │   PROFILE    │   ROLE: admin · tester · viewer   ← what you may do
        │              │   + per-person extra / denied permissions
        └──────┬───────┘
               │ belongs to
        ┌──────▼───────┐
        │     TEAM     │   ← the wall. All data lives inside one team:
        │              │      devices, tests, campaigns, results, reports.
        │              │      Two teams never see each other's anything.
        └──────┬───────┘      + optional team permissions, given to every member
               │ sees
        ┌──────▼───────┐
        │  WORKSPACE   │   ← a saved view, NOT a wall.
        │              │      Filters devices/scripts, hides pages.
        └──────────────┘      Changes what's on screen, never what you may do.
```

**The team is the wall. The workspace is a window.** Narrowing your workspace hides things; it
never grants or removes permission. If you want someone to *not be able* to do something, that is
the role — not the workspace.

---

## The three roles

| | Viewer | Tester | Admin |
|---|:---:|:---:|:---:|
| See dashboard, reports, monitoring | ✅ | ✅ | ✅ |
| Watch device streams | ✅ | ✅ | ✅ |
| Run tests and campaigns | — | ✅ | ✅ |
| Create / edit test cases | — | ✅ | ✅ |
| Take control of a device | — | ✅ | ✅ |
| Use the AI agent | — | ✅ | ✅ |
| Manage users, roles, teams | — | — | ✅ |
| Server / deployment actions | — | — | ✅ |

**Viewer is read-only, enforced in the backend.** Not merely hidden buttons: any request that
would change something is refused, whatever page or API it came from. A new account is always a
viewer — nobody gets more by signing up.

**Only an admin can change a role or a permission.** Users cannot edit their own, and an account
that claims a different role for itself is ignored — the server reads only the value an admin set.

---

## Fine-tuning one person

Roles cover almost every case. When they don't, an admin can adjust one person on the Users page
without inventing a new role:

- **Grant** an extra permission — a tester who may also reboot devices.
- **Deny** a permission the role normally includes — a tester who must never delete a test case.

A denial always wins over a grant. Neither applies to admins, who can do everything.

**A grant cannot make a viewer act.** Viewer read-only is a floor, not a list of permissions: the
backend refuses *any* request from a viewer that would change something, before it looks at what
they have been granted. So granting a viewer "run tests" widens nothing — they are refused at the
door. Grants on a viewer can only open up more *reading*; to let someone do anything at all, make
them a tester.

### Reading the Permissions tab — blank is normal

**Edit User → Permissions shows the exceptions, not what the person can do.** Every box starts
unticked, and for almost everyone it stays that way: an empty tab means *this person gets exactly
what their role gives them*, which is the healthy default. It is not a sign that they have no
access.

So the tab answers "what has an admin changed for this one person?" — never "what may they do?".
For that, read the role, and the [role table above](#the-three-roles).

Two consequences worth knowing:

- **On a viewer, grants that would change something do nothing.** See the note above — the
  read-only floor refuses the request whatever the tab says.
- **On an admin the tab does nothing at all.** Admins hold every permission and denials never
  apply to them, so ticking a box on an admin's row changes nothing. To actually restrict
  someone, lower their role first.
- **Team permissions do not appear here.** A permission a person gets from their team is real
  and in force, but it is stored on the team, so it shows on the Teams page instead.

### Giving a whole team an extra permission

When the same exception applies to several people, put it on the team rather than on each person.
**Settings → Teams** carries the same permission list, and everything ticked there is granted to
every member of that team, on top of whatever their role already gives them.

Teams stack: someone in two teams gets both teams' permissions. A personal denial still overrides
a team grant — and admins still keep everything.

Use a team grant for "the whole on-call group may reboot devices", and a personal grant for
"only Sam may".

### All together

What someone may do is the sum of four things:

```
  what their role gives them
+ what any of their teams gives them
+ what an admin granted them personally
− what an admin denied them personally      ← always wins
```

…except for admins, who get everything regardless.

---

## Worked examples

**"A customer wants to watch, not touch."**
Role **viewer**, their team. They see dashboards, reports, monitoring and live device streams, and
cannot change one thing. Safe to hand out.

**"A new colleague should run tests but not manage anyone."**
Role **tester**, your team. They run and edit tests and drive devices; they cannot see the Users
page or change anyone's access.

**"A contractor on one project only."**
Role **tester**, their **own team** — not yours. The team is the wall, so they see only their own
devices and results. A workspace would *not* have done this: it would only hide your devices from
their screen, not stop them reaching the data.

**"Our tester keeps deleting test cases by accident."**
Keep them a tester, and **deny** `testcases:delete`. They keep everything else.

**"The dashboard is cluttered — too many devices."**
That is a **workspace**, not a role. Make one that filters to the devices that matter and switch
to it in the top bar. Everyone's permissions stay exactly as they were.

---

## Rules of thumb

1. **Signing up gives you nothing but read access.** Every new account is a viewer.
2. **To stop someone doing something, change the role** — never rely on hiding the page.
3. **To separate two groups' data, use teams.** One team per customer or project.
4. **To tidy a screen, use workspaces.** They are cosmetic by design.
5. **Only admins hand out access.** Nobody can promote themselves.
6. **An empty Permissions tab means "role defaults apply."** It is the normal state, not a
   problem to fix.

---

## Where to change things

**Settings → Users** (admins only): a person's role, their team, and their individual granted or
denied permissions. **Settings → Teams**: create teams, manage membership, and set the
permissions every member of that team inherits. **Top bar → Workspace**: switch your own view at
any time.

A role change takes effect when the person's session next refreshes — within about an hour, or
immediately if they sign out and back in.
