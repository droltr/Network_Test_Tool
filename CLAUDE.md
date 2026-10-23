# Network Test Tool: agent working model

These rules are permanent for this repository. They apply to the main Claude session (the orchestrator) and to every subagent it starts.

## Language
- Talk to the user in Turkish.
- Code, comments, UI text, commit messages, docs and `.maestro/changes.jsonl` entries are English.

## Running the app
- Windows: `python` is the Microsoft Store stub. Use the project venv: `venv\Scripts\python.exe main.py` (create it with `py -m venv venv` and `pip install -r requirements.txt` if missing).
- Tests: `venv\Scripts\python.exe -m unittest discover tests` and `venv\Scripts\python.exe test_suite.py`.

## Work is done in rounds
1. **Plan.** The orchestrator splits the work into tasks and gives each subagent an explicit **file ownership** list. No two agents running in parallel may edit the same file. Read-only agents may read anything.
2. **Implement.** Claude subagents run in the background. Rules for each one:
   - Verify a finding against the code or real output before changing code. Report "not reproduced" when it does not hold.
   - Never commit, push or change git state.
   - Put scratch scripts, screenshots and outputs in the session scratchpad, not in the repo.
   - Take screenshots with `widget.grab()` only, never full-screen grabs, because the user is using the screen.
   - Report back what was fixed, what was left and why, the files changed, and the verification output.
3. **Integrate.** The orchestrator checks the combined result: every module imports, all three themes (`bauhaus-light`, `bauhaus-dark`, `onedark`) build, and the unit tests and `test_suite.py` pass.
4. **External review.** Codex (`codex exec -s read-only`) and Antigravity (`agy`) review the uncommitted diff. Rules for the reviews:
   - Each reviewer runs read-only in its own visible Windows Terminal window (`wt -w new ... pwsh -NoExit -File <script>`), so the user can watch.
   - Output is tee'd to report files in the scratchpad.
   - Split the diff between the reviewers (for example codex: `network/` and `utils/`; agy: `gui/`).
   - Do not run agy in `--mode plan` for reviews: it stops and waits for approval instead of writing the report.
5. **Fix review findings** with a new round of owned-file subagents. Treat reviewer claims as leads; they did not run the code.
6. **Commit** only after integration checks pass and serious review findings are fixed. Commit as one commit per round with a descriptive English message. Push only when the user asks.

## Change log (`.maestro/changes.jsonl`)
- Only the orchestrator writes it, never subagents, so parallel agents cannot conflict on the file.
- Append one JSON line per completed unit of work: after each subagent report, external review, merge, commit or push.
- Fields: `agent`, `subagent` (name or `null`), `time` (ISO 8601 with offset), `basis` (the user request or approval it rests on, with its date), `files`, `what`, `verify`.
- In `verify`, prefix checked facts with `V:` and unverified items with `U:`. Mark uncommitted work as `UNCOMMITTED`.
- Keep the file valid JSONL: write the lines with `json.dumps(..., ensure_ascii=False)`.

## Reporting to the user
- After each round, give a short Turkish summary covering what changed, what was verified, what is still open, and the next step.
- When a step was skipped or something was not verified, say so plainly.
