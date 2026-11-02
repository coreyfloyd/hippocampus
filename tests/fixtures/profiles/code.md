# Profile: code

```checklist-profile
{
  "name": "code",
  "steps": [
    {"id": "code-tests", "after": "before-spine", "section": "Tests"},
    {"id": "code-review", "after": "persist", "section": "Review pending"}
  ]
}
```

Applies when a repository's code changed this session.

## Tests

Run the project's test suite before the persist step.

## Review pending

If the change still awaits review, say so in the report.
