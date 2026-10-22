# Prompt 01: start a milestone (reuse for M1, M2, …)

Replace `<N>` with the milestone number. Use plan mode for this message.

---

Let's start milestone M<N> from `docs/BUILD_PLAN.md`.

1. Re-read the M<N> section, plus any parts of `docs/SPEC.md` and `docs/ENGINEERING_NOTES.md` it references.
2. Create the branch `m<N>-<short-slug>` from `main`.
3. Propose a plan covering:
   - the models, migrations, services, endpoints and UI screens you'll add
   - the tests you'll write, mapped to each acceptance criterion
   - any change to `packages/schema` or `contract/openapi.json`, and whether it's backward compatible
   - risks, or anything you need from me
4. Wait for my "go". Then implement task by task, committing after each one with lint and tests passing.
5. When finished:
   - run the full test suite
   - run `make contract` if the API changed
   - report each acceptance criterion as ✅ or ❌ with evidence (test names, command output)
   - write a short summary I can forward to Selorm (mobile) or Desmond (DevOps) if it affects them
   - open a PR description in `docs/prs/M<N>.md`
