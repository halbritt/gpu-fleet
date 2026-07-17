# AGENTS.md

Repository-level instructions for AI coding agents.

## Striatum Registration

This repository is a registered Striatum target repository (`.striatum/graph.json`; `repo_id 019f3d37-d495-7876-b06d-3e21233f8b42`, registry alias `gpu-fleet`, genesis bound to root commit `ddff975`). The Graph Store lives at `$XDG_DATA_HOME/striatum/graphs/<repo_id>/`; `.striatum/graph.json` is committed identity only, and `.striatum/scratch/` and `.striatum/worktrees/` are gitignored and never state.

Driving compilations here uses the striatum-next binary with its contracts: `~/git/striatum-next/bin/striatum --catalog ~/git/striatum-next/catalog --backends ~/git/striatum-next/backends <verb>`. Escalation resolutions are read and adjudicated individually by whoever holds authority — never pre-scripted, blanket-applied, or pattern-matched (Principal rule, 2026-07-06).

The bootstrap-Striatum history in this repo's log (`striatum:`-prefixed commits, `striatum/` campaign dir) predates this registration and belongs to the old daemon (`striatumd`), not the striatum-next graph.

<!-- BEGIN PROXIMAL PLANE TRACKING -->
## Plane Tracking

This repository is represented in the local/private Plane workspace `Proximal`.

- Plane project: `Gpu Fleet` (`GPUFLE`)
- Issue tracker: Plane (`Proximal` workspace), project `Gpu Fleet` (`GPUFLE`).
- Plane URL: `https://proximal.tail0ecc2e.ts.net:10000/`
- GitHub repo: `https://github.com/halbritt/gpu-fleet`
- GitHub Issues: deprecated; use Plane work items for new issue tracking, claims, reviews, and issue-state changes.
- Use Plane work items for multi-agent planning, claims, submitted artifacts, reviews, and acceptance decisions.
- When updating Plane, include the repo, branch/worktree, `run_id`, `base_sha`, artifact links, verification evidence, and authority scope in the work item description or comments.
- Do not commit Plane API tokens. Local tokens and MCP env files live outside git under `~/.config/plane/`.
<!-- END PROXIMAL PLANE TRACKING -->


## Branch hygiene

Do not leave unmerged code lying around. If a task uses a branch, merge its authorized work into the intended target branch before reporting completion. If merge authority is absent, report that as a blocker instead of treating the branch as finished. Clean up branches and associated worktrees after merge.
