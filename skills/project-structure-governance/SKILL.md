---
name: project-structure-governance
description: Define, initialize, locate, and audit the canonical structure of a software repository, including source code, tests, scripts, configuration, documentation, assets, automation, generated output, and runtime files. Use when Codex needs to scaffold a project, decide where a new file belongs, name a repository-owned artifact, inspect or reorganize a repository, add a new project directory, or give another agent an authoritative directory index.
---

# Project Structure Governance

Treat repository structure as an interface shared by people, tools, and agents. Govern file placement and naming; leave product, architecture, and content-quality decisions to their owning workflows.

## Resolve A Path

Read [project-layout.json](references/project-layout.json) before creating or moving a file. Use its zones and artifact patterns as the global index.

Read the target repository's `.project-structure.json` next. It selects one or more technology profiles and records project-specific zones or root files. Apply rules in this order:

1. Determine whether the file belongs to one registered application, a shared package, or the repository as a whole.
2. For application-owned code, resolve the registered `apps/<name>` path before applying that application's profiles.
3. Preserve paths required by the selected framework or build tool inside that ownership boundary.
4. Apply the repository manifest's explicit additions, then the global baseline and artifact index.
5. Stop and extend the index when no rule owns the file; do not invent an arbitrary directory.

Read [project-structure-standard.md](references/project-structure-standard.md) when classifying an unfamiliar file, choosing a name, or changing the index.
Read [document-bundle-standard.md](references/document-bundle-standard.md) before creating or reorganizing PRD, design, development, testing, release, or retrospective artifacts. Require the total-part directory structure and three-digit chapter numbering defined there.

## Initialize A Repository

Run from this skill directory:

```bash
python3 scripts/project_structure_bootstrap.py --workspace /path/to/repo
```

Use repeatable `--profile` options for a single root application. The initializer automatically discovers existing direct children of `apps/` and their profile markers. For a new multi-application repository, use `--application web=node --application api=go`; this selects the root `monorepo` profile and creates each profile's structure under `apps/<name>`. Record custom Owner and Purpose values in the generated manifest, then rerun the initializer to synchronize the application table in `docs/project/project-overview.md`. Keep shared libraries in `packages/<name>` rather than registering them as applications.

Supported profiles are `generic`, `node`, `python`, `go`, `rust`, `java`, `dotnet`, `ruby`, `php`, `flutter`, and `monorepo`; `generic` cannot be combined. The command creates baseline/profile directories, `.project-structure.json`, `docs/project/project-overview.md`, and a managed `.gitignore` baseline while preserving existing content. Use `--dry-run` to inspect the plan, `--no-gitignore` to leave ignore rules unmanaged, and `--keep-empty` when initialized empty directories must be committed.

Existing version 1 or 2 manifests and profile/application changes require `--migrate`; never migrate them implicitly.

## Audit A Repository

Run:

```bash
python3 scripts/project_structure_checker.py --workspace /path/to/repo
```

Use `--format json` for machine consumption. Use `--fail-on revise` or `--fail-on block` in CI. Treat automated language detection as a baseline and inspect substantial project documentation manually.

Before changing an existing repository, inspect current framework conventions and references. In a multi-application repository, audit every direct child of `apps/` against `applications` and verify that every application appears in the project overview table. Do not move framework-required paths merely to match the generic profile; record legitimate exceptions in `.project-structure.json`.

## Extend The Structure

Register a new independently deployable unit in `applications`; do not model it as an `additional_zones` entry. Put a genuinely shared library in `packages/<name>`. For any other project-only path, add a narrowly scoped `additional_zones` or `allowed_root_files` entry to `.project-structure.json`. For a reusable path, update `references/project-layout.json`, the standard when policy changes, and checker tests in the same change. Every application and zone must state one owner and one purpose.

## Return Results

Return `allow`, `revise`, or `block`. Include exact offending paths, their classification, and concrete target zones. State when a target requires owner confirmation instead of guessing.
