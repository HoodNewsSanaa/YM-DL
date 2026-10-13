# Verification results

Development environment: Linux x86-64, Python 3.12.14, Qt/PySide6 6.12.0, yt-dlp 2026.08.19, ytmusicapi 1.12.3, Mutagen 1.48.1.

## Automated checks

`python -m pytest -q`: **131 passed**, exit status 0.

The tests cover:

- Album metadata, original track numbering and unavailable-track positions.
- Shuffled playlist tracks matched to their canonical album positions; cached album queries.
- YouTube link validation and Windows-safe filenames.
- Embedded title, artist, album, track, disc, date and cover tags in Opus, AAC/M4A, Vorbis, MP3 and FLAC.
- Identical decoded PCM hashes before and after stream copying and tagging for every tested audio format.
- Completed-file retry skipping, retry after tagging failure, missing-file redownload, preservation of existing unrelated files and artwork failure reporting.
- History paths restricted to their album folder.
- Interface selection, metadata edits, unavailable tracks, worker process startup/error reporting and cancellation of a worker plus its child process.
- Temporary cookie copy cleanup on cancellation.
- Three complete-track retries recovering on the fourth attempt; minimum retry enforcement and continuing after one track exhausts its attempts.
- Correct retry accounting, recoverable tagging and completion-record failures without duplicate completed audio, progressive rate-limit waits and music-focused diagnostics.
- Download settings and the optional account-access tab, including saved retry counts.
- Single-disc tag omission in Opus, AAC/M4A, Vorbis, MP3 and FLAC; automatic removal of older cached single-disc tags without a new download or changed decoded audio.
- Real FFmpeg conversions to Opus, AAC/M4A, MP3, FLAC and WAV, including lower and higher bitrate selections, with retained metadata and embedded cover art.
- Original-mode protection against re-encoding, separate completion records for different output formats/bitrates, invalid quality-setting rejection, and remembered format/bitrate selections in the interface.
- Source codec/bitrate previews, estimated and unknown bitrates, format fallback reporting and account-quality upgrades without skipping older Original files.
- Album-only folders and flat multi-disc filenames; completion signatures embedded in all supported audio containers; removal of work/history items while preserving unrelated files.
- Cookies-file-only interface, removal of saved browser selections and private cookie copies for quality checks and downloads.
- Ordered multiline URL queues, invalid-line validation, unavailable-track event mapping and cleanup before the next album/URL starts.
- Manual quality checks for selected available tracks; direct downloads and queues without a compulsory quality scan; optional queue quality checks.
- Clipboard paste detection loading once; artwork changes with the current track's album; artwork embedded on the right of the main window, asynchronous local image requests, caching, missing covers and stale-request cancellation.
- Saved sleep preference, zero normal sleep passed to yt-dlp, and failure retries retaining their backoff.
- Actual yt-dlp downloading a locally generated audio file from a local HTTP server using already-resolved source information; one extraction per track and reuse of a previously checked completed Original file without another audio download.
- Track alerts only after all four automatic attempts, Try again/Skip/Cancel behavior, paused worker decisions with stale responses rejected, and URL retries not advancing the queue before a decision.
- Non-blocking GUI error alerts, ASAP preference, supplied logo pixels retained in the 32px icon, and retry-arrow assets. The rendered Settings panel was inspected to confirm visible arrow graphics.
- Per-album cleanup for interleaved playlists; legacy completion markers/work folders; shared album metadata and artwork caches; duplicate URL results protected from later edits; quality updates refreshing only one row.

- Live retry countdown updates, zero-time retry start, wheel scrolling with checkboxes/tags locked, and removal of release-matching UI/API.
- Explicit invalid/rotated cookie warnings and rejection of generic 403/bot errors; banner reset after a fresh cookie export.
- Every URL visible in the queue overview; current-album progress; green/yellow/red status boxes; detailed track/URL failure aggregation and success-only final messages.

Audio tests use locally generated sine tones. Download tests inject a fake yt-dlp downloader while exercising actual FFmpeg, actual Mutagen tagging, filesystem publication and completed-file records.

## Interface and packaging

The simple light interface, embedded artwork panel, retry arrows, ASAP setting and queue error alert were rendered and inspected with Qt's offscreen platform. Source-mode checks passed for the interface, spawned worker, FFmpeg and Node runtime. A fresh YM-DL Linux packaged build also passed, including the supplied logo/icon, arrow assets and bundled SVG plugins.

A Linux PyInstaller directory build using the same application imports, package collection and FFmpeg bundling approach also passed its packaged self-check:

```json
{
  "ok": true,
  "yt_dlp": "2026.08.19",
  "qt": "6.12.0",
  "runtime": "node",
  "ffmpeg": "available",
  "worker_spawn": "ok",
  "app": "YM-DL",
  "version": "0.4.0-beta.1",
  "assets": "ok"
}
```

The Windows build script produces a one-file executable and runs this self-check automatically with its bundled Deno runtime. **The Windows executable has not been built or run in this Linux development environment.**

## Earlier live service checks

- Public YouTube Music album search, album lookup and share-playlist resolution succeeded on **Bach: Les Variations Goldberg - Gould**, a 32-track result with a 2016 release year. The preview preserved the original album order and numbering.
- yt-dlp inspected a public music stream without downloading it and selected **Opus in WebM**, approximately 143 kb/s.
- The stream inspection needed the development environment's system certificate trust (`no-certifi` compatibility option) because its default Certifi trust failed for the network certificate chain. Certificate verification remained enabled. This diagnostic option is not hardcoded into the app.

No live song was downloaded in these checks. Real Windows downloads, exported-cookie authentication, authenticated/Premium streams and region/age-restricted content still need testing on the target PC. Album previews do not support private playlists in this version.
