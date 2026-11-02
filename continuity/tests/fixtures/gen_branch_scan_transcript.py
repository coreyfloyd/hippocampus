#!/usr/bin/env python3
"""Build a synthetic pickup transcript for tests/test-pickup-branch-scan.sh.

#909 review: never hand-author a .jsonl with invented field
shapes. This clones real "user" and "assistant" rows from a REAL transcript
(isMeta/isSidechain/message-content structure preserved verbatim) and edits
only cwd/gitBranch/timestamp -- the two fields the #909 bug is about -- to
point at the fixture repo's synthetic branches.

Usage: gen_branch_scan_transcript.py <template.jsonl> <out.jsonl> <repo_path>
"""
import copy
import json
import sys

template_path, out_path, repo_path = sys.argv[1], sys.argv[2], sys.argv[3]

rows = []
with open(template_path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue

def text(r):
    c = r.get("message", {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c
                         if isinstance(p, dict) and p.get("type") == "text")
    return ""

def real(r):
    return not r.get("isMeta") and not r.get("isSidechain")

user_template = next(
    r for r in rows
    if r.get("type") == "user" and real(r) and text(r).strip()
    and not text(r).lstrip().startswith("<")
)
asst_template = next(
    r for r in rows
    if r.get("type") == "assistant" and real(r) and text(r).strip()
)

# (cwd, gitBranch) pairs the fixture repo builds — see
# tests/test-pickup-branch-scan.sh for what state each one is in.
pairs = [
    (repo_path, "main"),
    (repo_path + "/.worktrees/dirty-branch", "dirty-branch"),
    (repo_path + "/.worktrees/clean-unmerged-branch", "clean-unmerged-branch"),
    (repo_path + "/.worktrees/gone-unmerged-branch", "gone-unmerged-branch"),
    (repo_path + "/.worktrees/ghost-branch", "ghost-branch"),
    (repo_path + "/.worktrees/shared-scope", "shared-scope"),
    (repo_path, "main"),  # session ends back on main, like the real #909 case
]

out_rows = []
ts_minute = 0
for cwd, branch in pairs:
    for template in (user_template, asst_template):
        row = copy.deepcopy(template)
        row["cwd"] = cwd
        row["gitBranch"] = branch
        row["timestamp"] = "2026-09-02T00:%02d:00.000Z" % ts_minute
        ts_minute += 1
        out_rows.append(row)

with open(out_path, "w") as f:
    for row in out_rows:
        f.write(json.dumps(row) + "\n")
