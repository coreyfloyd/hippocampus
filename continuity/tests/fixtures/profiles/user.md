# User profile: example

A user profile for the checklist tests. It binds the four slots and adds four
steps after the persist step. The shared checklist owns their ordering.

```checklist-profile
{
  "name": "example-user",
  "bindings": {
    "record": {
      "command": "/record-step",
      "consumes": ["progress", "commitment", "decision", "artifact"],
      "section": "Reconcile the record"
    },
    "knowledge": {
      "command": "/knowledge-step",
      "consumes": ["knowledge"],
      "section": "Capture knowledge"
    },
    "lessons": {
      "command": "/improve-harness",
      "consumes": ["lesson"],
      "section": "Fold in lessons"
    },
    "persist": {
      "command": "/persist-step",
      "consumes": [],
      "section": "Persist"
    }
  },
  "steps": [
    {"id": "cleanup", "after": "persist", "section": "Clean up"},
    {"id": "context-health", "after": "persist", "section": "Context health"},
    {"id": "session-metadata", "after": "persist", "section": "Session metadata"},
    {"id": "whats-next", "after": "persist", "section": "What's next"}
  ]
}
```

## Reconcile the record

Write this session's progress, commitments, decisions, and artifact locations to the record.

## Capture knowledge

Save the knowledge this session produced, asking before anything is written.

## Fold in lessons

Place each lesson in the rules, skills, or memory it belongs to.

## Persist

Commit and push every repository this session touched.

## Clean up

Remove worktrees and stop background agents this session started.

## Context health

Recommend clearing only when context use is high or compaction has happened more than once.

## Session metadata

Record usage metadata for this session, if the tool provides it.

## What's next

Suggest what to pick up next.
