#!/usr/bin/env python3
"""Check explicit named paths and command executables without executing commands."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys


def check(paths,commands,base):
    def existing_path(value):
        path=Path(os.path.expandvars(value)).expanduser()
        return (path if path.is_absolute() else Path(base)/path).exists()
    def existing_command(value):
        if '/' in value:
            path=Path(os.path.expandvars(value)).expanduser()
            path=path if path.is_absolute() else Path(base)/path
            return path.is_file() and os.access(path,os.X_OK)
        return shutil.which(value) is not None
    return dict(missing_paths=[p for p in paths if not existing_path(p)],
                missing_commands=[c for c in commands if not existing_command(c)])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',default='.')
    parser.add_argument('--path',action='append',default=[])
    parser.add_argument('--command',action='append',default=[])
    args=parser.parse_args();result=check(args.path,args.command,args.base)
    print(json.dumps(result))
    return 1 if any(result.values()) else 0

if __name__=='__main__':sys.exit(main())
