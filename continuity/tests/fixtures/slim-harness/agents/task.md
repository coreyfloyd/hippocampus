---
name: gen-task
model: claude-opus-5-5
effort: medium
description: Portable general-work task generator wrapper.
skills: []
---
Read `../roles/core.md` and
`../roles/task.md`; they are canonical.

Run tests in the foreground with an explicit tool timeout. Never `run_in_background` a test run — completion notifications do not reach a subagent. For a sweep longer than the tool budget, run the suites your diff touches individually and say which you did not run.
