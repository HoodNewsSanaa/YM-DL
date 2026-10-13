# YM-DL — YouTube Music desktop downloader (beta)

A native desktop GUI for downloading YouTube Music albums and playlists as tagged audio files.

## Downloading music

1. In YouTube Music, use **Share** on an album or saved playlist and copy its link.
2. Paste it in YM-DL.
3. Review the tracks. Bitrate checks are optional: check the boxes beside the tracks you want to inspect, then click Check quality. Source information appears in **Source audio** and **Output audio** without downloading the audio file. Loading an album or clicking Download does not run a separate quality scan; source information fills in as each download begins. 
4. Choose a destination folder. Leave **Audio format** at **Original (best available)**, or choose Opus, AAC/M4A, MP3, FLAC or WAV. For Opus, AAC and MP3, choose a target bitrate from the **Bitrate** selector.
5. Click **Download selected**. Your format and bitrate preference is remembered for the next session.

Files are organized as `Album / 01 - Title.opus` or `.m4a`. There is no artist folder. Multi-disc releases stay in the same album folder and use names such as `02-01 - Title.opus` (disc 2, track 1). An album cover is embedded and also saved as `cover.jpg` when available. Filenames are sanitized for Windows. Existing files are preserved; naming collisions get an extra suffix. Older folders are not moved automatically.

## Download a queue

Choose your destination, audio format and optional cookies first. Click **Queue URLs…**, paste one public album or playlist URL per line, then click **Start queue**. The app processes them in the pasted order: load metadata, then download available tracks. Separate bitrate scans are off by default; enable **Check source quality before each album (slower)** in the queue dialog if wanted. The table and artwork panel follow the current album. Queue mode starts downloads automatically; use the normal **Load playlist** flow when you want to edit tags, choose individual tracks or review quality before starting.

**Queue order** lists every pasted URL immediately, with album/playlist names appearing as they load. Each entry shows progress and a colored box: green for Complete, yellow while Loading/Checking/Downloading, red for Failed/Skipped or Paused after an error, and gray for Waiting/Cancelled. The current URL is highlighted. You can open the dropdown and scroll the track list during downloads; metadata editing and track checkboxes remain locked until the job finishes.

## Audio and metadata behavior

- Selects yt-dlp's **best available audio-only stream**. Quality depends on the streams YouTube exposes to your session; the app does not promise Premium quality without suitable access.
- Source previews use the same cookie file as downloads. `~` marks a variable or estimated bitrate; missing bitrate data displays **Unknown**, and failed checks display **Check failed**. Source bitrate and conversion target are shown separately. Stream availability can change between checking and downloading; the actual selected stream is reported when downloading begins. A failed check does not prevent a later download attempt.
- **Original (best available)** is the initial default. It keeps the source codec: FFmpeg uses `-c:a copy` to put Opus into `.opus` or AAC into `.m4a`, without re-encoding the sound. Vorbis, MP3 and FLAC are supported if encountered. Unknown source codecs fail rather than being silently converted in Original mode.
- Converted formats are **Opus (64–256 kbps)**, **AAC/M4A (64–320 kbps)**, **MP3 (64–320 kbps)**, **FLAC** and **WAV**. The UI lists the supported bitrate steps; FLAC and WAV have no target-bitrate setting and store decoded audio as 16-bit PCM. Selecting a converted format re-encodes the downloaded source, including when its codec already matches your chosen output codec.
- Converted modes also fetch the best available source and then convert locally. Lower bitrate choices reduce saved file sizes; they do not necessarily reduce network download size. Conversion can lose fidelity, and higher bitrates or FLAC/WAV cannot improve the original source quality.
- Download completion records include your output format and bitrate. Changing either produces a separate file, preserving existing versions. Repeating the same format/bitrate skips completed files. Metadata and artwork are retained for every supported output format, including WAV.
- Embeds title, track artist, album, album artist, track number/total, disc number/total, available year/date, artwork and source URL.
- **Single-disc albums omit disc-number and disc-total tags.** Multi-disc albums retain both tags, including disc 1. Re-running the same album also removes unnecessary disc tags from recorded completed single-disc files without downloading the audio again.
- Automatically resolves public YouTube Music album metadata and canonical track order. A saved playlist can contain tracks from several albums; each track goes into its own album folder.
- Disc numbers default to one because YouTube Music often provides a flat track list. Disc, track and date fields can be edited manually in Extra tags.
- Genres, composer credits, label, catalogue number and lyrics are not fetched in this version. Missing dates are left empty rather than inferred from an upload date.
- Tracks that cannot be resolved to an album show a metadata review note and fall back to playlist numbering. Review these before downloading. Private playlist previews and endless radio mixes are not supported in this version.
- A failed track automatically retries **three times after the first attempt** (four total attempts). In **Settings → Downloads**, you can increase this to ten retries. This retries the complete track operation, including audio processing and tagging, in addition to yt-dlp's connection/fragment retries.
- Default waits before the three retries are **5, 15 and 45 seconds**. Rate-limit and bot-check errors wait at least **30, 60 and 120 seconds**. Downloads normally have randomized 5–10 second delays. In **Settings → Downloads**, enable **Start downloads ASAP (no random sleep)** to start tracks without those normal delays. This preference is remembered and also applies to queues; failure retry waits remain active. The interface shows a live retry countdown in the status line and track row, updating every second; cancellation also works during waits. The retry-count control has visible up/down arrow buttons. Outside URL queue mode, exhausted failures are logged and downloading continues.
- Cancellation stops the worker and its child processes. Completed files stay saved. Start again to skip recorded completed tracks and retry remaining downloads; partial audio may resume when the chosen source stream stays the same.
- A completed-file record is written only after audio validation and tagging. This allows safe retries. If you move files, or change their metadata, they may be downloaded again.
- Artwork failures are shown as **Complete — no artwork** and counted separately. Successful runs show a simple success message. Failed runs list each failed track or URL and its error reason; successful cleanup does not produce misleading end-of-job warnings.

## Optional account cookies

Open **Settings → Account access (optional)** and select an exported Netscape-format `cookies.txt` from your signed-in YouTube account. There are no browser-selection options. Album metadata lookup remains public; source-quality checks and downloads use the selected cookie file. Cookie contents are not saved in app settings: only the file path is retained. The app uses a private temporary copy and removes it after the job or cancellation, leaving your original file unchanged. Keep cookies outside the project folder and do not include them in shared logs, screenshots or uploads.

A red banner near the top appears when yt-dlp explicitly reports that your cookies are expired, invalid or rotated. A generic 403 does not trigger this diagnosis. Replace the exported file or choose a fresh one in Settings to clear the warning; the app does not expose cookie contents.

A YouTube Data API key authenticates official data requests; it does not authenticate this audio-download engine or exempt downloads from bot checks. Google OAuth is currently unsupported for yt-dlp downloads according to its own documentation. Cookies are the supported account-access option, and they do not guarantee that bot checks will disappear. The app has no API-key or Google-password fields.

Account-access reference: https://github.com/yt-dlp/yt-dlp/wiki/Extractors#logging-in-with-oauth

## Updates and troubleshooting

YouTube changes regularly. If downloads fail, check for a new YM-DL release with updated yt-dlp, or update the dependency pins and rebuild. Use a fresh cookies file if YouTube explicitly requires sign-in. The app does not bypass age restrictions, region restrictions or DRM. Release dependencies are pinned; update them deliberately in `requirements-release.txt` for a new release instead of silently changing the bundled versions.

If an album preview fails, make sure the album or playlist is public, the link contains `list=`, and the network can reach YouTube Music. There is no silent metadata guessing fallback.

## Run the source

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Source-mode downloads need Node.js LTS or Deno on PATH, or a runtime in `tools/`. Install FFmpeg on PATH for source mode. The optional development dependency imageio-ffmpeg can provide a fallback, and is excluded from the release executable. On Linux/macOS activate the virtual environment and run `python app.py`; Qt may need your system's desktop libraries. This is a local app: no hosted service or API keys.

## Tests

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

Tests use local generated audio and fake API responses, without downloading copyrighted songs or requiring an account. See `TEST-RESULTS.md` for the verification performed in the development environment.

## Project structure

- `app.py` / `gui.py`: desktop interface, background processes and cancellation
- `metadata.py`: YouTube Music album resolution
- `models.py`: track data, validation and safe filenames
- `engine.py` / `tagging.py`: downloads, audio stream copying, tags and artwork
- `quality.py` / `url_queue.py` / `queue_view.py`: source previews, ordered queues and colored progress overview
- `artwork.py`: asynchronous artwork panel and bounded image cache
- `queue_control.py`: paused queue decisions; `branding.py` / `assets/`: name, supplied logo and executable icon
- `worker.py`: worker process dispatch
- `build_windows.py` / `Build-Windows.cmd`: Windows executable packaging
- `tests/`: metadata, tagging, download, retry and interface checks

## Dependency documentation

- yt-dlp: https://github.com/yt-dlp/yt-dlp
- YouTube Music API: https://ytmusicapi.readthedocs.io/en/stable/reference/browsing.html
- Mutagen: https://mutagen.readthedocs.io/
- PyInstaller: https://pyinstaller.org/en/stable/
- Node.js LTS releases: https://nodejs.org/dist/
- FFmpeg source: https://ffmpeg.org/download.html
- Release packaging inputs and source provenance: `RELEASE-BUILD.md`

## Distribution

The supplied `assets/Logo.pixil` is retained unchanged; its active frame is exported as `logo.png` and a multi-size Windows `.ico` without changing the artwork. Previous Musicbox settings are imported once into YM-DL, preserving the selected destination, cookies path and audio preferences.

Queues reuse a bounded metadata cache and one metadata API session, share downloaded cover bytes, and refresh only the affected audio-quality row. Image requests stay asynchronous so cover loading cannot stall the queue.

YM-DL uses GNU GPLv3; see `LICENSE`. Dependencies retain their own licenses. The release build preserves the actual installed package notices, the official Node archive's full license, Qt attribution files, and the FFmpeg/LAME/Opus license texts. It also creates a source archive with the exact app files, FFmpeg/library source and recipe, Qt/PySide source archives, and Mutagen/certifi source archives. Publish both ZIPs and their checksum file together.

The `.exe` remains self-contained for running. The download ZIP keeps notices beside it for distribution. See **RELEASE-BUILD.md** for build details and **PUBLISHING.md** for the existing GitHub repository and beta-release steps.
