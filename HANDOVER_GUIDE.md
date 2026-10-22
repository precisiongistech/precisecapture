# Handing PreciseCapture over to Claude Code: guide for Ben

This pack contains everything Claude Code needs to start building the PreciseCapture backend (Django) and web app (React) on your machine. You stay the product owner and reviewer: Claude Code proposes, builds and tests, and you approve each milestone.

## What's in the pack

| File / folder | Purpose |
| --- | --- |
| `CLAUDE.md` | Claude Code reads this automatically every session: product, stack, repo layout, rules, conventions |
| `docs/SPEC.md` | The full product and technical spec (exported from our shared doc) |
| `docs/BUILD_PLAN.md` | 13 milestones (M0–M12) with tasks and acceptance criteria |
| `docs/ENGINEERING_NOTES.md` | How to build the hard parts: tenant isolation (RLS), sync ordering, conflicts, geometry, attachments, auth |
| `docs/DECISIONS.md` | Every decision made so far, so Claude Code doesn't reopen them |
| `packages/schema/` | The shared contract with Selorm: JSON Schemas for layer attributes and capture profiles, pilot examples (Farmers, Farms), expression language spec and test vectors |
| `infra/docker/` | Local dev services (PostGIS, Redis, MinIO, Martin, Mailpit) and the database role setup |
| `.env.example`, `.gitignore` | Every environment variable; `.env` is excluded from git |
| `.claude/settings.json` | Claude Code permissions: allows dev commands; blocks edits to the mobile app and production infra |
| `prompts/` | Copy-paste prompts: kickoff, start a milestone, review, and useful one-liners |
| `README.md` | The repo's README |

## Step 1: Install prerequisites (once)

On your MacBook:

1. **Claude Code:** install it and sign in. See [docs.claude.com](https://docs.claude.com/en/docs/claude-code/overview) for the current install command.
2. **Docker Desktop:** runs the local database, Redis, MinIO and tile server.
3. **Python tooling:** `uv` (it installs Python 3.12 for the project).
4. **Node 22 + pnpm:** `corepack enable` turns on pnpm.
5. **GDAL/GEOS/PROJ:** needed by GeoDjango; on macOS, `brew install gdal geos proj`.
6. **Git + a GitHub repository:** create a private repo, e.g. `precisegis/precisecapture`, and add Selorm and Desmond.

## Step 2: Create the repo from this pack

```bash
mkdir precisecapture && cd precisecapture
git init -b main
# copy everything from this pack into the folder, including the hidden .claude folder, .gitignore and .env.example
git status            # check that .env is NOT listed (the pack's .gitignore excludes it)
git add . && git commit -m "chore: project handover pack (spec, plan, schemas, dev infra)"
git remote add origin git@github.com:<org>/precisecapture.git && git push -u origin main
cp .env.example .env  # local secrets, never committed
```

The pack's `.gitignore` already excludes `.env`, so it can't be committed by accident.

**About `.claude/settings.json`:** it pre-approves routine dev commands and blocks edits to `apps/mobile` and `infra/deploy`, reading `.env`, and destructive git and shell commands. It's a guardrail, not a sandbox, so still read any unusual command before approving it.

## Step 3: Kick off Claude Code

```bash
cd precisecapture
claude
```

1. Switch to **plan mode** (Shift+Tab) and paste `prompts/00-kickoff.md`.
2. Read its summary, its list of gaps and contradictions, and its M0 plan. Answer its questions, then say **"go"**.
3. When M0 is done, check the acceptance criteria yourself. Run `make dev-up`, `make api-run`, then open `http://localhost:8000/api/v1/docs`.

## Step 4: The milestone loop (repeat for M1 to M12)

1. Start a fresh Claude Code session. In plan mode, paste `prompts/01-start-milestone.md` with the milestone number.
2. Review the plan, adjust it if needed, then say **"go"**.
3. Let it work. It commits task by task with tests.
4. Paste `prompts/02-review-and-fix.md` for a self-review.
5. Check the acceptance criteria yourself (click through, or run the tests), then merge the PR.
6. If the milestone has a 📱 marker, send Selorm the contract summary Claude Code wrote.

**Rough pacing:** M0–M4 are foundation work and go fastest. M6 (sync) and M8–M9 (web UI) need the most review from you. Don't skip the review step on M2 (tenancy) and M6 (sync). Those are the parts where a subtle bug is costly.

## Step 5: Keep Selorm and Desmond in sync

**Selorm (mobile)**

- After M1, he can build forms and capture rules from `packages/schema`.
- After M3 and M4, he can build against the mock server (`make mock`) and the generated TS client.
- After M6 and M7, he can switch to real sync and photo uploads.
- Selorm should get his own `CLAUDE.md` inside `apps/mobile/` if he uses Claude Code too. I can draft one for him.

**Desmond (DevOps)**

- Involve him at M0 (CI) and M12 (DigitalOcean deploy, backups, staging).
- Give him `docs/ENGINEERING_NOTES.md §1`: the database roles and RLS setup have to be replicated on DigitalOcean Managed Postgres.

## Tips for working with Claude Code

- **One milestone per session.** Use `/compact` or start a new session when a session gets long.
- **Plan mode first, every time.** Reviewing a plan is cheaper than reviewing code you didn't want.
- **Ask for evidence:** "show me the test that proves org A can't read org B".
- **It may ask to install packages or run commands.** `.claude/settings.json` pre-approves the routine ones. Read anything else before approving.
- **If it drifts from the spec,** say "check `docs/DECISIONS.md`". If the spec itself was wrong, have it update the spec and add a decision entry.
- **Keep the shared spec doc as the human-readable version.** When something big changes, ask me to update it as well, so `docs/SPEC.md` and the doc don't drift.

## Open items still to decide (they don't block M0–M6)

- Domain name and app store listings
- Pilot partner and region
- Pricing model
- QA owner
- SMS provider for OTP (needed before the pilot; dev uses a console backend)
- Basemap source and licence for offline packs (M11)
