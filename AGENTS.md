# AGENTS.md — AutoDJ working agreement

These rules persist across all milestones. Read them before touching this repository.

The architectural roadmap lives in the AutoDJ V1 Technical Plan (16 milestones, M0-M15). The
roadmap is not permission to implement more than one milestone.

## Milestone workflow

1. Implement exactly one approved milestone per run. Never start the next milestone without
   explicit approval.
2. Create the milestone's feature branch (`cursor/mNN-<slug>-<suffix>`) before writing code. One
   branch per milestone; never reuse a milestone branch.
3. Keep every change inside that milestone's scope: no future-milestone code, no speculative
   abstractions, no unrelated refactors, no drive-by fixes.
4. When the milestone is complete, run the relevant checks (`ruff`, `mypy`, `lint-imports`,
   `pytest`) and then stop.
5. Report before committing: a concise diff summary (each file with a one-line purpose), test and
   lint results, architectural or implementation decisions and any deviation from the plan, and a
   proposed set of logical atomic commits with Conventional Commit messages.
6. Do not commit, push, open a pull request, or merge until the proposal is explicitly approved.
7. After approval, create exactly the approved commits, then stop again. Beginning the next
   milestone is a separate, separately approved step.
8. Do not parallelize work across milestones unless explicitly requested.

## Commits

- Conventional Commit messages (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`).
- Atomic commits grouped by logical change. A milestone may contain several commits when that
  reflects the work better; one commit per milestone is not a goal.
- Run `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, and `pytest` before committing.
- Summarize the diff before committing.
- Never force-push, rewrite history, or run destructive git or database operations without explicit
  permission.

## Architecture rules

- Layering is enforced by `lint-imports` (import-linter), configured in `pyproject.toml`:

  ```text
  autodj.api  ->  autodj.services  ->  autodj.persistence
                                   ->  autodj.render  ->  autodj.audio
                                   ->  autodj.dj
                                   ->  autodj.metrics
  ```

- `autodj.audio` and `autodj.dj` are pure. They take numpy arrays and plain dataclasses and return
  values. They must not import SQLAlchemy, FastAPI, `autodj.persistence`, or touch the filesystem.
- Only `autodj.services` composes repositories, pure logic, and rendering.
- Expensive analysis belongs on the offline path, never on the runtime path.

## Configuration and experiments

- Every tunable lives in `backend/autodj/config/default.yaml` with a default and a reason, and is
  documented in `docs/parameters.md`. No inline magic numbers in code.
- Thresholds and weights are starting hypotheses, not truths. Record how a value was chosen, and
  log experiments in `docs/experiments.md` with the config snapshot that produced them.
- Any change to feature extraction bumps `analysis.version` and states the reprocessing
  implication for already-analyzed tracks.

## Dependencies and licensing

- New dependencies require a written justification and a license note.
- This project links Rubber Band via `pedalboard` and is therefore distributed under GPLv3. See
  `docs/licensing.md` before adding or swapping DSP dependencies.

## Data hygiene

- Never commit audio. `audio/`, `render_cache/`, and `analysis_cache/` are gitignored and must stay
  that way.
- Never commit secrets or `.env`. Update `.env.example` instead.
- Source audio files are read-only inputs; nothing in this repository may modify them.

## Testing

- Automated tests must run without the private MP3 library. Use synthetic audio generated in code.
- Prefer the simplest implementation that satisfies the current milestone's acceptance criteria.
