# transcribe

Standalone macOS 26+ command-line transcription using on-device Apple Speech.

It accepts an audio file or a video file containing an audio track and writes a timestamped Markdown or JSON transcript. It has no dependency on remote machines, APIs, queues, or persistent state.

## Build

```bash
swift build -c release
```

## Use

```bash
.build/release/transcribe recording.m4a --output recording.md --format markdown --language en-US
.build/release/transcribe interview.mp4 --output interview.json --format json --language en-GB
```

The first transcription for a locale may download Apple's model asset. Markdown preserves source, locale, engine, and timestamped segments. JSON adds segment end times and mean confidence when the speech framework supplies it.
