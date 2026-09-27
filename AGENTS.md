# Agent Entry

1. Read `/Users/marin/.agents/AGENTS.md`, [global entry](wiki/notes/agents/index.md), and the [shared work policy](wiki/notes/agents/work-management-policy.md).
2. Read [README.md](README.md), including File Naming and Document Lifecycle, then [wiki/index.md](wiki/index.md) and the relevant project index/Task.
3. Current owners are `wiki/profile.md`, `wiki/notes/`, `wiki/projects/` and the explicitly selected `current_domains` owners in the local registry. Selection can include active product registries under `wiki/sources/`; other source files remain original evidence. Process and before-state belong in `wiki/log/`. Product repositories own code, executable contracts and raw evidence.
4. Before editing, preserve full bytes with `uv run python -m harness snapshot ... --reason '...'`. Verify the record and update links with the owner change. Do not leave duplicate editable bodies or removed-content notices.
5. Run `uv run python -m harness check` before reporting document changes complete. Fix errors; record actual evidence and remaining limits. Script success does not establish factual truth.
6. Use `uv run python -m harness context /absolute/project/path` for registered project discovery and `--task ID` for the full Task. Reconcile actual workspace and unfinished calls before continuing. With `work_contract: 1`, bind the raw session ID to the Task before code changes, update its result and next action after changes, and run `harness work record` with actual Log evidence. Keep stable Task IDs and paths.
7. Use `uv run python -m harness search 'query'` for current retrieval. Select `--scope history` or `--scope sources` only when needed. Read the resulting owner and assess applicability.
8. Keep personal content, logs, configuration, indexes and credentials out of public Git. Never force-add private paths.
9. Preserve unrelated dirty work. The independent `orchestration/` submodule has its own AGENTS.md and README.md; do not fold its changes into the parent.
