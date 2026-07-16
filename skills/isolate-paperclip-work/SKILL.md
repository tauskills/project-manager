---
name: isolate-paperclip-work
description: Keep Paperclip task, agent, prompt, run, and assignment context separate from durable project assets while enforcing Git change scope, project-owned naming, verification, delivery evidence, and local process cleanup. Use whenever an agent works on a software project from inside Paperclip, declares files it may change, creates intermediate TODOs or screenshots, names files or code from a task, hands work to another agent, scans changed or staged files, closes a run, or audits a repository for Paperclip-to-project coupling.
---

# Isolate Paperclip Work

Treat Paperclip as an execution environment, not as part of the project's domain. Preserve durable product and engineering knowledge; isolate how Paperclip assigned and executed the work.

## Establish The Boundary

Read [paperclip-project-boundary-standard.md](references/paperclip-project-boundary-standard.md) before creating files or identifiers.

Classify every artifact before writing it:

| Class | Location | Allowed content |
| --- | --- | --- |
| Durable project asset | Repository-owned canonical path | Stable product facts, domain concepts, engineering decisions, implementation, and verification |
| Paperclip process artifact | `.run/paperclip/sessions/<session-key>/` | Opaque task and agent references, execution TODOs, handoffs, screenshots, logs, notes, and scratch output |
| Intentional Paperclip integration | Explicit product-owned path | Code or documentation whose actual product domain integrates with Paperclip, excluding the current run's metadata |

Do not put Paperclip task titles, task IDs, task URLs, agent names or IDs, prompts, assignment state, retry history, or run status in project documentation, source code, tests, configuration, migrations, assets, release notes, branches, or code identifiers. Do not name any durable file, directory, symbol, module, test, or migration after a task title or task reference.

Rewrite requirements received through a task as tool-neutral domain statements. Name artifacts after the capability, behavior, or decision they own. A matching phrase is not automatically acceptable merely because it appeared in the task.

## Prepare Local Process Space

Create a process session only when intermediate artifacts are needed:

```bash
python3 scripts/paperclip_session.py create \
  --workspace /path/to/repo \
  --slug payment-timeout \
  --allow-path 'src/payment/**' \
  --allow-path 'docs/development/payment-timeout/**' \
  --forbid-path 'src/payment/secrets/**' \
  --expect-output 'src/payment/timeout.py' \
  --verify-command 'python3 -m pytest tests/payment' \
  --task-ref '<opaque-paperclip-ref>' \
  --agent-ref '<opaque-agent-ref>'
```

Choose `--slug` from a stable domain concept, never from a task title, task number, agent identity, or status. Start from a Git repository with at least one commit. Declare the smallest permitted paths, any explicit exclusions, concrete outputs, and repeatable verification commands. Commands are stored as argument arrays and run without a shell.

The command creates a timestamped session under `.run/paperclip/sessions/`, adds a narrow ignore rule when needed, and snapshots HEAD plus all pre-existing dirty paths. Treat unchanged baseline dirt as user-owned; never overwrite, revert, stage, or commit it outside the declared scope.

Keep all execution-only material inside the current session:

- Track only the current run's actions in `todo.md`; move durable backlog items into the project's canonical backlog after rewriting them.
- Record cross-agent state in `handoff.md`; include the current state, evidence paths, next action, and risks, but no credentials or copied prompt.
- Put screenshots in `screens/`, use the required sequence/type/surface name, index them in `evidence.md`, and redact secrets and personal data.
- Put exploratory notes, logs, and disposable output in `notes/`, `logs/`, and `scratch/`. Never import, link, or depend on these paths from project assets.

During work, attribute the Git diff to the current session and pass task identity only at runtime:

```bash
PAPERCLIP_TASK_TITLE='<runtime title>' \
python3 scripts/paperclip_hygiene_checker.py \
  --workspace /path/to/repo \
  --session 20260715T103000Z-payment-timeout \
  --scan changed \
  --fail-on revise
```

Use `--scan staged` before a commit to inspect index content rather than the working copy. The checker also accepts `PAPERCLIP_TASK_REF` and `PAPERCLIP_AGENT_REF`; never persist the task title merely to enable detection.

When an aggregate commit has already charged another owner's path to an older session, do not edit the older session's `allowed_paths`, `forbidden_paths`, baseline, or digest. Add a commit-bound ownership attestation instead:

```bash
python3 scripts/paperclip_session.py attest-commit \
  --workspace /path/to/repo \
  --session 20260715T103000Z-payment-timeout \
  --commit <commit> \
  --path 'docs/checkout-policy.md' \
  --owner-session 20260715T103001Z-checkout-policy
```

Use repeatable `--path`. If a verified legacy owner has no surviving session evidence, first create a new session whose contract names only the exact legacy paths and a real verification command; use that session as `--owner-session`. The attestation command requires each path to be changed by the named commit, rejects uncommitted path changes, and binds commit/HEAD/path-history fingerprints plus owner scope into `committed-path-ownership.json`. Source `forbidden_paths` can be migrated only when the other owner proves the path; an owner session's own forbidden paths remain ineligible. A later commit touching an attested path or any manifest tampering invalidates the claim, so close fails closed.

## Promote Outcomes, Not Process

Do not treat a Paperclip task or prompt as the project's source of truth. Link the outcome to the canonical PRD, issue, architecture decision, test evidence, or other repository-approved system. When an intermediate result becomes durable:

1. Extract the verified product fact, decision, code change, or test evidence.
2. Rewrite it without Paperclip provenance or execution narration.
3. Place it in the repository's canonical domain path and apply project-native naming.
4. Cite project-owned evidence, not `.run/paperclip/` paths.
5. Keep the original process artifact local until cleanup; do not move it into `docs/` or source directories.

If the product intentionally integrates with Paperclip, state that boundary explicitly and keep current task/run metadata isolated. An integration exception permits product behavior such as a Paperclip client or API contract; it does not permit leaking the agent's current assignment into those assets.

## Close And Audit

Before reporting completion, complete or explicitly cancel every TODO, then close through the session manager:

```bash
PAPERCLIP_TASK_TITLE='<runtime title>' \
python3 scripts/paperclip_session.py close \
  --workspace /path/to/repo \
  --session 20260715T103000Z-payment-timeout
```

The close command verifies expected outputs, runs every declared command, generates `delivery.json`, enforces scope and leakage gates, and marks the session closed. It automatically deletes `retention: discard` sessions. For `external-archive`, pass `--archive-ref` during close and delete the closed local session with `paperclip_session.py purge` after confirming the external record.

Use close's repeatable `--integration-path`, or the checker's `--allow-path`, only for verified product-owned Paperclip integrations. Never allow an entire repository or a generic parent such as `src`, `docs`, or `tests`.

Do not bypass a failed close. Resolve scope, naming, output, verification, evidence, or secret findings and rerun it. Use `purge --force` only to remove explicitly abandoned local work, never to represent successful delivery.

Return `allow`, `revise`, or `block`. Include exact paths, leaked context type, scope violation, and repair action. Treat task-title similarity as `revise`, not proof; manually confirm that names remain natural project concepts after deleting the Paperclip task.
