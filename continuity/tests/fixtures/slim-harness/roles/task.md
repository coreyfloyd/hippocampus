---
kind: role-profile
role: generate
domain: task
profile: task
version: 1
requires: {inputs: [ticket_body, ticket_labels, done_block]}
---
Treat the frozen done block as the only completion criterion. The terminal runs
its commands after the requested work and preserves every observed exit code in
the final run record; do not execute them yourself. A generator-reported
`done_block`, if any, is informational only.
If the requested work would change a tracked file in any checkout on the node,
stop before the change and report: "retype as chore or enhancement".
