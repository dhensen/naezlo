# Ralph Agent Instructions

You are an autonomous coding agent building todolist, a multi-tenant todolist app
that humans and AI agents share. You run from the repo root. Each iteration starts
with no memory of previous ones; the files below are your memory.

## Read first

1. `README.md`: the v1 feature list and technical requirements
2. `DECISIONS.md`: stack, domain model and rules decided so far. It wins over your own preferences.
3. `ralph/prd.json`: the user stories; `passes` marks the finished ones
4. `ralph/progress.txt`: start with the `## Codebase Patterns` section at the top
5. Root `CLAUDE.md` (exists after US-001): commands and lasting conventions

## Your task

1. Make sure you're on `main` and the working tree is clean apart from files a
   previous iteration left uncommitted. If there are such leftovers, read
   `ralph/progress.txt` to see whether they belong to an unfinished story before you continue.
2. Pick the **highest-priority** story with `passes: false` (lowest `priority` number).
3. Implement only that story. Every acceptance criterion must hold.
4. Run the quality checks that exist at this point:
   - `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, `uv run pytest`
   - once `frontend/` exists: `npm --prefix frontend run lint`, `npm --prefix frontend run typecheck`, `npm --prefix frontend run test`
   - once the e2e harness exists (US-029): `npm --prefix frontend run e2e`

   Never commit failing code.
5. If you made a decision that `README.md` and `DECISIONS.md` don't cover, append it to `DECISIONS.md`.
6. Set `passes: true` for the story in `ralph/prd.json`.
7. Append your progress to `ralph/progress.txt` (format below).
8. Commit all changes, including the two ralph files, as `feat: [Story ID] - [Story Title]`.
   Then `git push origin main` if a remote named `origin` exists. If it doesn't, skip
   the push and say so in your progress entry. Never add a remote.

## Hard rules

- Tests need Postgres. If it isn't running, start it with `docker compose up -d` and wait for the healthcheck.
- Never commit secret values. Configuration comes from environment variables; `.env`
  is git-ignored and `.env.example` holds placeholders only.
- Never call Google or any other external service in tests. Mock them.
- The dev-login endpoint must stay disabled unless `DEV_LOGIN=true`.
- Every permission check goes through the permission service with a `Principal`.
  Don't write ad-hoc role checks in route handlers or MCP tools.
- Schema changes go through an Alembic migration. Don't edit a migration that is already committed; add a new one.
- When a story depends on a library or protocol you can't verify from the code (the
  `mcp` SDK, the MCP authorization spec, Claude Code or Codex configuration syntax),
  read the current documentation instead of relying on memory.
- Billing is out of scope. Don't add features that aren't in a story.
- Don't mark a story as passing when a criterion isn't met. If a criterion turns out
  to be wrong or impossible, explain why in the story's `notes` and in
  `ralph/progress.txt`, and reply `<promise>BLOCKED</promise>`.
- If something external blocks you (Docker isn't available, a package can't be
  installed, a browser can't be downloaded), write down what you need in
  `ralph/progress.txt` and reply `<promise>BLOCKED</promise>`. Don't fake a pass.

## Progress report format

APPEND to `ralph/progress.txt` (never replace it):
```
## [Date/Time] - [Story ID]
- What was implemented
- Files changed
- Pushed: yes/no (reason)
- **Learnings for future iterations:**
  - Patterns, gotchas, useful context
---
```

Put reusable, general patterns in the `## Codebase Patterns` section at the top of
`ralph/progress.txt`. Put lasting conventions in the root `CLAUDE.md`.

## Browser testing

UI stories are verified by a Playwright spec (harness from US-029), which is part of
the quality checks. If you also have browser tools, open the page and check it
visually. If you don't, say in your progress entry that a manual visual check is
still needed.

## Stop condition

After finishing a story: if every story has `passes: true`, reply
`<promise>COMPLETE</promise>`. Otherwise end your response normally.
One story per iteration.
