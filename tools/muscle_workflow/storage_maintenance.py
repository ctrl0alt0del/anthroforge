"""Explicit, receipt-producing maintenance. Never invoked by reconstruction automatically."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from storage_support import inventory, safe
from storage_actions import baseline, compression, assets, verify_protected
from storage_retention import backup_plan, remove_backups
from storage_archive import create_archives, retire_archives, restore_archive


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('protect', 'compress', 'assets', 'verify', 'backup-plan', 'backup-apply',
                                         'archive-create', 'archive-retire', 'archive-restore'))
    parser.add_argument('--root', required=True)
    parser.add_argument('--run')
    parser.add_argument('--manifest')
    args = parser.parse_args()
    if args.phase == 'archive-restore' and not args.manifest: parser.error('--manifest is required for restoration')
    if args.phase != 'archive-restore' and not args.run: parser.error('--run is required for maintenance')
    return args


def main():
    args = arguments(); root = Path(args.root).resolve(strict=True)
    if args.phase == 'archive-restore':
        print(json.dumps(restore_archive(root, args.manifest))); return
    run = safe(root, Path(args.run).resolve(strict=True).relative_to(root))
    actions = {'verify': verify_protected, 'backup-apply': remove_backups,
               'archive-create': create_archives, 'archive-retire': retire_archives}
    if args.phase in actions:
        result = actions[args.phase](root, run)
    else:
        action = {'protect': baseline, 'compress': compression, 'assets': assets, 'backup-plan': backup_plan}[args.phase]
        result = action(root, run, inventory(root, run))
    print(json.dumps(result, default=str), flush=True)


if __name__ == '__main__':
    main()
