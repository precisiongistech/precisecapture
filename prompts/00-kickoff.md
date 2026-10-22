# Prompt 00: kickoff (paste this into Claude Code first)

Use plan mode for this first message (Shift+Tab until "plan mode" shows), so Claude Code reads and plans before writing any files.

---

You're joining the PreciseCapture project as the lead developer for the backend (Django) and web app (React). I'm Ben, the product owner and reviewer.

Before doing anything else:

1. Read `CLAUDE.md` fully.
2. Read `docs/SPEC.md`, `docs/BUILD_PLAN.md`, `docs/DECISIONS.md` and `docs/ENGINEERING_NOTES.md`.
3. Look at everything in `packages/schema/` (schemas, examples, expressions.md, test vectors) and `infra/docker/`.

Then reply with:

- **A five-bullet summary** of the product and architecture in your own words, so I can check you've understood it.
- **Any contradictions or gaps** you found between the spec, the build plan, the engineering notes and the schemas. List each with your recommended fix.
- **A concrete plan for milestone M0:** the files you'll create, the tools and versions you'll pin, the Makefile targets, the CI workflow, and the order of commits.
- **Questions** you need me to answer before starting. Keep these to the ones that actually block you, each with a recommended default.

Do not write code yet. Wait for my "go".

Ground rules for the whole project:

- Work one milestone at a time, on a branch named `m<N>-<slug>`.
- Commit after each task using Conventional Commits. Run lint and tests before every commit.
- Never edit `apps/mobile/`, and never touch production infrastructure.
- Any change to `packages/schema` or `contract/openapi.json` must be backward compatible, or flagged as **BREAKING CHANGE**.
- If you disagree with a decision in `docs/DECISIONS.md`, say so and explain why, but don't change it without my OK.
- At the end of each milestone, report every acceptance criterion as pass or fail, with evidence.
