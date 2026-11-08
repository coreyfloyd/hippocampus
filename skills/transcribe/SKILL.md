---
name: transcribe
description: Convert supplied local audio or video into a timestamped transcript. Use as an input adapter for research, archival, or analysis; it does not perform research or decide where findings belong.
---

# Transcribe

Use this skill only to obtain a transcript. The calling workflow retains ownership of research scope, synthesis, artifact placement, and disposition.

## Choose the lightest source route

- **YouTube research source:** add the URL directly to NotebookLM when its native indexing is sufficient. Do not download merely to create a duplicate transcript.
- **Video archival:** when frames plus a vault raw artifact are required and a `video-ingest` skill is installed, use it; it prefers native captions and has its own transcription fallback. That skill is not part of this package.
- **Local audio/video, or media without usable captions:** use the standalone CLI below.

## Local CLI

The CLI is a runtime-detected optional integration bundled at `tools/apple-speech`. It requires macOS 26+ and uses on-device Apple Speech; when that route is unsupported or unavailable, report the limitation and select another input route. It has no network-host, API-key, queue, or persistent-state dependency.

From the installed skill directory (the directory containing this `SKILL.md`), run its launcher. The launcher resolves the bundled package, builds the release executable when needed, and forwards all arguments:

```bash
tools/apple-speech/run-transcribe.sh <media-file> --output <transcript.md> --format markdown --language en-US
```

Use `--format json` when a downstream tool needs structured segments. Both formats retain source path, locale, engine identifier, and timestamps; JSON also retains per-segment mean confidence when Apple Speech supplies it.

Do not create a research output, raw vault record, or wiki article merely because transcription succeeded. Return the transcript path and provenance to the calling workflow.
