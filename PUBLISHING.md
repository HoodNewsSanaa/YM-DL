# Publish YM-DL 0.4.0-beta.2

Existing repository: https://github.com/HoodNewsSanaa/YM-DL
Project license: GNU GPLv3, supplied as `LICENSE`.

1. Extract the updated Windows project into a fresh folder and run
   **Build-Windows.cmd**. Read `RELEASE-BUILD.md` for its verified inputs and
   companion source packaging. Do not mix it with the older Deno/Gyan build.
2. Test `dist/YM-DL.exe` on Windows: load a public album, download Original
   audio and a converted format, and check a two-album queue. Keep cookies and
   downloaded music private. The build already runs offline GUI/worker/runtime
   and all-codec self-checks, but real YouTube downloads require your Windows PC.
3. Update the source repository with the new application/build files,
   requirements, hooks, release material manifests/notices, `runtime_bin` and
   `runtime_sources`. Keep `assets/` and `tests/` as folders. Use GitHub Desktop
   for folder-preserving updates. The full Qt/Python source download caches,
   virtual environment, tools cache and `dist` belong outside the source commit.
4. Edit the saved release draft to use tag **v0.4.0-beta.2**, target **main**,
   and title **YM-DL 0.4 Beta 2**. Keep **Set as a pre-release** checked.
5. Attach all three automatically generated files:
   - `YM-DL-0.4.0-beta.2-Windows-x64.zip`
   - `YM-DL-0.4.0-beta.2-Sources.zip`
   - `YM-DL-0.4.0-beta.2-SHA256SUMS.txt`
6. Publish after testing the Windows build. Leave all three assets together.
   The companion Sources asset contains downloaded Qt/dependency sources that
   GitHub's automatically generated repository source ZIP may omit.

The executable is portable and unsigned. Users extract the Windows ZIP and
open YM-DL.exe; they do not install Python, Node or FFmpeg. Keep the notices
with distributed copies. The source asset also records upstream source URLs,
versions, build recipes, package notices and file digests.

Suggested release description:

> YM-DL 0.4 Beta 2 retains ordered music queues, source quality previews,
> album artwork, editable YouTube Music tags, album-only folders, automatic
> retries, retry countdowns, paused queue error decisions and per-album cleanup.
> This build replaces Deno with verified Node.js LTS and uses an audio-focused
> FFmpeg build from included source. Download the Windows ZIP to run the app.
> The Sources ZIP and checksums accompany it. Stream quality depends on the
> formats YouTube exposes to your session. This executable is unsigned.

GitHub release instructions:
https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository
