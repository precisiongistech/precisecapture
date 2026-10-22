# Prompt 02: review before merging a milestone

---

Before I merge this milestone, review your own work as a strict senior reviewer would.

1. Run `git diff main...HEAD --stat`, then read the full diff.
2. Check specifically:
   - **Tenant isolation:** every new tenant table has RLS plus an isolation test, and every query runs inside `tenant_context`.
   - **Idempotency and versioning:** in any sync or feature write path.
   - **Contract compatibility:** a diff of `contract/openapi.json` and `packages/schema` against `main`.
   - **Hard-coded values:** any hosts, buckets, secrets or magic numbers that belong in settings.
   - **Error handling:** problem JSON shape, with no stack traces leaking.
   - **Missing tests:** for the edge cases listed in the milestone.
   - **Performance:** N+1 queries (use `django-assert-num-queries` where sensible), missing indexes (especially GIST on geometry), and unbounded queries.
3. List each problem found with its file and line, then fix it. Re-run lint and tests.
4. Give me the final acceptance-criteria table and a merge recommendation.
