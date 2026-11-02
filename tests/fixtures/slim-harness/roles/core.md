---
kind: role-core
role: generate
domain: task
version: 1
requires: {skills: []}
outputs: [what_was_done, done_block, durable_evidence_location]
boundaries: [durable-output-outside-repository, no-repository-changes, no-merge, no-post-merge-actions, no-review, no-evaluation]
---
Execute only the admitted task. Write durable output outside every repository
checkout. Do not create a branch, change a tracked file, merge, run post-merge
work, review, or evaluate. Report what was done and the durable evidence
location. The terminal alone executes every frozen done check and records exit
codes; a `done_block` in generator progress is optional and informational only.
A terminal nonzero check is a blocked task outcome, not authority to repair a
repository or to re-run through another role.
