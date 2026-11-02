# Sweep handoff fixture

Captured on 2026-10-24 from a real local schema-version-2 checkpoint handoff.
Only the handoff contract fields used by the sweep are retained. All free text,
paths, session identities, timestamps, ticket references and commit identifiers
were replaced with neutral stand-ins; item types and the carried array structure
were preserved. Distinct item texts receive distinct numbered placeholders so
redaction does not collapse their identities. Spawned process details and uncommitted paths were removed.
No original session content is shipped.

The sweep command tests copy this captured structure into isolated stores and
vary individual contract fields, including deriving schema-version-1 and
untyped legacy cases. Dates, paths, and sessions in those variations are test
controls, not claims about the captured session.
