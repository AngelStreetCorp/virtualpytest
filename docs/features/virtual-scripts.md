# ⚡ Virtual Scripts

**Write a test in your browser. Run it immediately. No deployment.**

Virtual Scripts let anyone author and edit test scripts straight from the web interface and run them right away on a real device — skipping the usual edit → commit → deploy → restart cycle entirely.

---

## The Problem

Changing a normal test script means going through a full deployment:
- ❌ Edit the file, commit it, push it, wait for it to roll out to every test machine
- ❌ Minutes of turnaround just to try one small idea
- ❌ Requires developer tooling (git, command line) that not every QA tester wants to touch
- ❌ Testing a quick "what if" means going through the same pipeline as a real release

---

## The VirtualPyTest Solution

✅ **Edit in the browser** — a full code editor, no local setup or git required
✅ **Run instantly** — hit Run and it executes on any connected device right away, no deployment step
✅ **Safe promotion path** — move a script through Dev → Test → Production stages, so experiments never put what's live at risk
✅ **Automatic version history** — every saved change is recorded; roll back to any earlier version whenever you need to
✅ **Shared building blocks** — common helper code can be reused across scripts instead of copy-pasted into each one
✅ **Behaves exactly like a normal test** — same reports, logs, run history, and scheduling; nothing extra to learn

---

## How It Works, In Plain Terms

1. **Write it.** Open the Virtual Scripts editor and write your test like any other — same tools, same building blocks.
2. **Run it.** Pick a device and hit Run. The script executes immediately — there's no separate deployment step to wait on.
3. **Promote it, when ready.** Keep experimenting freely in your personal Dev copy. Once it's solid, promote it to Test, and later to Production — each stage is a deliberate, separate step.
4. **Roll back if needed.** Every save is kept in history, so a bad edit is never permanent — restore any previous version in a click.

---

## How It Helps

- Try a test idea in seconds instead of waiting on a release cycle
- Let QA testers author and iterate on scripts without needing developer tooling
- Keep experimentation in Dev completely separate from what's actually scheduled in Production
- Turn an existing script into an instantly-editable Virtual Script (and back) without losing anything

---

## Where to Find It

- **Build → Virtual Scripts** in the navigation menu
- Runs alongside regular scripts everywhere else in the product — **Run Tests**, **Scheduling**, and **Campaigns** all treat a Virtual Script exactly like any other test

---

## Next Steps

- 🧪 [Test Automation](./test-automation.md) - The test-building concepts Virtual Scripts share
- 📊 [Real-time Analytics](./analytics.md) - See run results and history
- 🔁 [CI/CD](./cicd.md) - Automate scheduled runs

---

**Ready to write your first Virtual Script?**
➡️ [Get Started](../get-started/README.md)
