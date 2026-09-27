# Document Workflow

This document explains the executable workflow for current Markdown, historical
Log records and local retrieval. The [shared work policy](../../wiki/notes/agents/work-management-policy.md)
owns mandatory gates W01–W06, failure handling and acceptance requirements.
Markdown is canonical; search indexes are disposable. Hook execution state is not a search cache.

The [central hook adapter](agent-hooks-design.md) connects Codex and Claude to
one entry point, with preservation gates and bounded stop validation.
Installation, runtime trust and execution evidence are separate checks.

## Layout

- `wiki/profile.md`: confirmed working preferences.
- `wiki/notes/`: reusable current knowledge and shared rules.
- `wiki/projects/<project>/`: project entry, Tasks and relevant reviews.
- `wiki/sources/`: original evidence and attachments; explicitly selected active domain owners follow current-document rules.
- `wiki/log/` and `wiki/log/index.md`: before-state, reasons, attempts and validation evidence.
- `harness/`: executable preservation, validation, context and retrieval workflow.
- `tests/`: synthetic regression tests.
- `docs/`: installation, usage and implementation documentation.
- `.local/harness/`: machine registry, preservation checkpoint, hook execution state and derived search indexes.

Project code and executable product contracts stay in their repositories.
Product task IDs remain stable. Current documents contain applicable content;
prior wording and change narratives belong in Log.

## Commands

Run from the vault root after `uv sync --locked`:

```sh
uv run python -m harness check
uv run python -m harness structure wiki/notes/example.md
uv run python -m harness snapshot wiki/notes/example.md --reason 'Explain the change'
uv run python -m harness verify wiki/log/<record>
uv run python -m harness checkpoint
uv run python -m harness search 'query'
uv run python -m harness search 'historical question' --scope history
uv run python -m harness search 'original evidence' --scope sources
uv run python -m harness catalog --output wiki/log/<new-register-record>
uv run python -m unittest discover -s tests -v
```

`check` returns nonzero when the document contract fails. Fix diagnostics before
reporting the document change complete. Format/link checks do not verify factual
claims or replace applicable product tests and reviews.

After the initial corpus setup, initialize its local baseline once with
`uv run python -m harness checkpoint --initialize`. Subsequent work uses
`snapshot → edit → check → checkpoint`. Check rejects edits or deletions without
the exact checkpoint before-state in a hash-verified Log snapshot, interrupted
migration journals, and invalid names for newly added current documents.
Checkpoint advances the baseline only after validation and a corpus-drift check.
Existing stable Task paths retain their names. The local baseline is part of the
machine setup; it is not a tamper-proof security boundary.

Normal checks reject a missing or malformed checkpoint. Only explicit first-time
`checkpoint --initialize` permits an absent baseline, while still validating
documents and publication state. It is not a recovery command for a lost baseline.
Current search, index building and context reject prepared or malformed publication
journals, and recheck publication state before returning results. Context requires
an existing workspace and a registered document directory with index.md inside the
vault. History and source retrieval remain available for evidence investigation.

The project registry, checkpoint and hook-state.sqlite are required machine state. Only the three
SQLite indexes are disposable. Reports and before-state belong in wiki/log;
original evidence belongs in wiki/sources. Root layout checks include hidden entries and empty directories. Current retrieval
covers base current owners plus explicitly selected current_domains. Task validation covers wiki/projects; unselected sources and historical Log are separate scopes. The independent orchestration submodule is a runtime boundary.

Recognizable process headings such as Previous Version, Changelog and 작업 로그
are rejected in current documents. This catches explicit historical sections;
semantic obsolescence still requires reading the source and current owner.

Search returns bounded sections and discloses truncation. Read the complete Task
before resuming work. Whole-corpus hashes detect additions, edits, moves and
deletions; stale indexes rebuild locally. Current queries exclude Log and unselected source archives; selected current domain owners remain searchable.

## Preservation and Template Scope

Preservation covers full bytes of current Markdown and non-Markdown companions
under notes, projects and docs. Companion edits also invalidate the current
revision seen by hooks and retrieval. Markdown receives metadata/link checks; selected domain YAML/JSON receives syntax and duplicate-key checks plus section search. Preservation does not test HTML behavior or validate a product YAML schema.

The optional `protected_roots` list in projects.json registers explicit domain
paths under wiki/sources for preservation. On this machine it includes
`wiki/sources/Dae-Jeong/wiki`, which contains live domain registries as well as
original evidence. This does not promote all domain files into current search or
make frozen submissions editable. The product's domain workflow owns mutability
and schema validation; source/log hook protections still apply. Missing registered
domains or removing a checkpointed registration causes validation failure.

Local Markdown/Obsidian fragments are checked against target headings or explicit
IDs, including fragments into preserved evidence and HTML IDs. External URL
fragments and runtime rendering are not verified by this check.

### Explicit Current-Domain Selection

`current_domains` in projects.json selects current owners within an existing
`protected_roots` registration. This is opt-in; the live domain classification,
cleanup and product validation must establish the selected scope. This machine selects active Dae-Jeong owners; frozen submissions and original evidence remain excluded. Registration alone does
not select every preserved file. A generic configuration has this shape:

```json
{
  "root": "wiki/sources/example/wiki",
  "include": ["profile/**", "registry.yaml"],
  "exclude": ["**/originals/**", "**/submissions/**"],
  "collections": [{
    "registry": "registry.yaml",
    "items": "attempts",
    "path_field": "current_source_path",
    "fallback_path_field": "source_path",
    "strip_prefix": "wiki/",
    "where": {"status": ["active"], "artifact_state": ["mutable"]},
    "include": ["*.md"],
    "exclude": []
  }]
}
```

Each domain requires root/include/exclude; collections is optional. A collection
requires registry/items/path_field/where/include/exclude; fallback_path_field and
strip_prefix are optional. Unknown keys and malformed field types are errors,
including when no record currently matches. Paths are normalized relative paths;
selection cannot escape its domain or follow symlinks. The domain must exist.

Domain include/exclude patterns are relative to its root. Every collection
condition must match; the named registry field then identifies an existing owner
file. Only a missing current path uses the optional fallback. Collection patterns
are relative to that owner's parent; `*.md` does not recursively select revision
or submission subdirectories. Domain exclusions apply after the union of explicit
and collection selections, so a registry entry cannot override an excluded area.
Allowed record states come from the product's lifecycle contract, not a shared
assumption that all projects use the same states.

Selected Markdown receives current link/history checks and section retrieval.
Selected JSON/YAML must be a mapping or list and is indexed by top-level groups
and mapping records. That syntax check does not validate the product schema or
facts. Selected owners use current-document snapshot gates in the shared adapter;
unselected source material retains evidence protection. Registry and selector
changes invalidate the current index. The product validator remains responsible
for lifecycle transitions, frozen payload integrity and the correctness of owner
pointers. Current-scope selection does not certify freshness or replace review.

`structure [file]` checks the [role templates](document-templates.md) and returns
nonzero for missing required sections, unresolved template variables, invalid
role metadata and invalid review dates. Optional template sections can be omitted.
Without a file it covers current Notes and Projects; an individual Log may be
checked explicitly. Unknown Note purposes require classification rather than a
silent fallback. Global enforcement requires `document_contract: 1` in the registry;
this machine enables it after current Notes and Projects passed reviewed role adoption
and the complete structure check. The ordinary check now includes role validation.
This setting does not certify factual freshness or include original Sources and Log
in current-document template enforcement.

## Checkpoint Coordination

Checkpoint commands use a POSIX advisory lock at `.local/harness/checkpoint.lock`;
a concurrent checkpoint fails explicitly and can be retried after the first finishes.
Before advancing an existing baseline, the command snapshots and verifies the full
bytes of new or changed current files included in that baseline. A preservation
failure or detected corpus drift leaves the old checkpoint in place. An unchanged
checkpoint creates no additional snapshot. Initialization remains a distinct first
setup operation. This protects intermediate baseline bytes when another session
continues editing; it does not freeze arbitrary filesystem writers, identify which
session caused every change, or implement atomic multi-file publication.

## Document Register

`catalog` creates a new Log record containing a full JSON inventory and a
searchable HTML view of current documents, companions and source-domain owner
candidates. It includes hidden files and attachments, keeps original/history
material separate, and never follows symlinks or changes source metadata.

The register separates declared content-update dates, explicit review records,
source capture dates, generation dates and filesystem mtime. An unspecified
timestamp stays unspecified. Missing dates remain unknown; mtime is never used
to certify semantic freshness. Review records are declarations, not fresh source
verification. Only an explicit stale_after date triggers a due-date finding.

Metadata-key corruption, malformed dates, ambiguous domain boundaries and
missing embedded graph file references are review flags. Flags do not authorize
automatic deletion or bulk date updates. Existing Log exports are immutable;
rerun into a new directory and update the current register entry after preserving
its before-state.

## Migration

Prepare a manifest of exact source/target paths and expected hashes before moving
documents. The migration command rejects changed inputs and colliding targets,
preserves full originals in Log, prepares candidates, writes all targets and only
then removes original owners. Its journal supports explicit resume after an
interruption. Readers must wait for the batch's applied state and validation.
Multi-file loose-file refresh is not an atomic filesystem transaction.

Sources and historical snapshots retain exact bytes. Their relative links retain
the original source-path context recorded in the manifest. Current documents have
their link targets updated. Required project integrations must resolve to the
same central owner; never copy an editable task body into a second repository.

## Rule Enforcement

This is CI-style validation used by agents and local commands. No administrator
service is required. The rules require clients to preserve history and pass
checks; they do not prevent arbitrary filesystem edits by the same user.
Natural-language correctness and latest-only meaning require a content review.
