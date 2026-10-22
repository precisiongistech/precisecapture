# Useful prompts during development

- **Resume after a break:** "Read `CLAUDE.md`, then `git log --oneline -20` and `git status`. Tell me where we are in the current milestone and what's next."
- **Explain before changing:** "Before changing anything, explain how `<module>` works today and what you'd change, in 10 lines or fewer."
- **Contract update for Selorm:** "Run `make contract`. Summarise what changed in `contract/openapi.json` since tag `<tag>` as a short message to Selorm, the mobile developer. Mark anything breaking."
- **Seed and demo:** "Reset the dev database, run `seed_pilot`, and give me the URLs and logins to click through the pilot project."
- **Bug report:** "Here's the error: `<paste>`. Write a failing test that reproduces it first, then fix it."
- **Decision record:** "Add a `DECISIONS.md` entry for `<decision>` with the reason, and update any affected docs."
- **Keep the context small:** run `/compact` when a long session gets slow, and start a fresh session for each milestone.
