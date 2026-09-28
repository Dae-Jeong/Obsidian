import argparse
import json
from pathlib import Path
import sys

from harness.check import check
from harness.context import context
from harness.search import build, search
from harness.checkpoint import checkpoint
from harness.preserve import snapshot, verify
from harness.catalog import export as export_catalog


def main():
    parser = argparse.ArgumentParser(description="Local document rules and scoped retrieval")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    structural = sub.add_parser("structure", help="Validate template contracts without editing documents")
    structural.add_argument("file", nargs="?", type=Path)
    catalog = sub.add_parser("catalog", help="Register document roles and declared dates without certifying freshness")
    catalog.add_argument("--output", type=Path, required=True, help="New directory under wiki/log")
    snap = sub.add_parser("snapshot")
    snap.add_argument("files", nargs="+")
    snap.add_argument("--reason", required=True)
    verification = sub.add_parser("verify")
    verification.add_argument("record")
    commit = sub.add_parser("checkpoint")
    commit.add_argument("--initialize", action="store_true")
    lookup = sub.add_parser("context")
    lookup.add_argument("workspace", type=Path)
    lookup.add_argument("--task")
    lookup.add_argument("--query", help="Find bounded current knowledge candidates for the work topic; does not verify application")
    work = sub.add_parser('work', help='Bind code observations to a central Task and execution evidence')
    actions = work.add_subparsers(dest='work_command', required=True)
    binding = actions.add_parser('bind')
    binding.add_argument('workspace', type=Path)
    binding.add_argument('--task', required=True)
    recording = actions.add_parser('record')
    recording.add_argument('--evidence', required=True)
    recording.add_argument('--reconciliation')
    inspection = actions.add_parser('status')
    inspection.add_argument('--workspace', type=Path)
    recovery = actions.add_parser('reconcile')
    recovery.add_argument('--tool', required=True)
    recovery.add_argument('--reason', required=True)
    for action in (binding, recording, inspection, recovery):
        action.add_argument('--agent', choices=('codex', 'claude'), required=action is not inspection)
        action.add_argument('--session', required=action is not inspection)
    index = sub.add_parser("index")
    query = sub.add_parser("search")
    query.add_argument("query")
    query.add_argument("--limit", type=int, default=5)
    for command in (index, query):
        command.add_argument("--scope", choices=("current", "sources", "history"), default="current")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == 'work':
            from harness import work
            if bool(args.agent) != bool(args.session):
                raise ValueError('Specify both --agent and --session, or neither for workspace status')
            key = f'{args.agent}:{args.session}' if args.agent else None
            if args.work_command == 'bind':
                result = work.bind(root, key, args.workspace, args.task)
            elif args.work_command == 'record':
                result = work.record(root, key, args.evidence, args.reconciliation)
            elif args.work_command == 'reconcile':
                result = work.reconcile(root, key, args.tool, args.reason)
            else:
                result = work.status(root, key, args.workspace)
            status = 1 if args.work_command == 'status' and result['issues'] else 0
        elif args.command == "structure":
            from harness.structure import check_structure, check_file
            if args.file:
                path = (root / args.file).resolve()
                issues = check_file(root, path)
            else:
                issues = check_structure(root)
            result = {"ok": not issues, "issues": issues, "verification": "structure-only"}
            status = 0 if result['ok'] else 1
        elif args.command == "catalog":
            result = export_catalog(root, args.output)
            status = 0
        elif args.command == "snapshot":
            record = snapshot(root, args.files, args.reason)
            result = {"record": str(record.relative_to(root)), "verified_files": verify(root, record)}
            status = 0
        elif args.command == "verify":
            result = {"verified_files": verify(root, args.record)}
            status = 0
        elif args.command == "check":
            result = check(root)
            status = 0 if result["ok"] else 1
        elif args.command == "checkpoint":
            result = checkpoint(root, args.initialize)
            status = 0
        elif args.command == "context":
            result = context(root, args.workspace, args.task, query=args.query)
            status = 0
        else:
            database = root / ".local/harness" / f"{args.scope}.sqlite"
            if args.command == "index":
                result = {"revision": build(root, database, args.scope), "scope": args.scope}
            else:
                result = search(root, database, args.query, args.scope, args.limit)
            status = 0
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return status
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
