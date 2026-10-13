# YM-DL 0.4.0-beta.2 release build

Run **Build-Windows.cmd** in a fresh extraction on 64-bit Windows with official
Python 3.11 or newer (Python 3.12 recommended). The build needs internet for
the first dependency/source downloads. It installs the exact versions in
`requirements-release.txt`, verifies supplied runtime/source materials, and
uses Node.js **24.21.0 LTS** from its official SHA-256-verified Windows archive.
No npm packages or global Node installation are required.

The supplied `runtime_bin/ffmpeg.exe` is a Windows x86-64 music-focused build of
FFmpeg **9.0.2**, with **Opus 1.5.2** and **LAME 3.100**. It has no external
non-system DLL requirements. It supports original AAC/Opus stream copying and
the app's AAC, Opus, MP3, FLAC and WAV output profiles. It includes Windows
Schannel support for HTTP/HTTPS input. Full source archives, the build recipe,
configure record and build transcript are in `runtime_sources/`; versions and
checksums are recorded in `runtime_bin/ffmpeg-build.json`.

FFmpeg uses LGPLv3-or-later. No GPL video codec libraries or nonfree libraries
are enabled. The app continues to use GPLv3, with Mutagen's GPLv3-compatible
license route and Qt/PySide/Shiboken's GPLv3 option. Full texts and third-party
attribution records are preserved under `release_materials/licenses`.

Qt/PySide source archives and Mutagen/certifi sources are fetched from exact,
recorded upstream releases and checked against the supplied SHA-256 manifests.
They are cached locally after the first build. The builder packages those full
archives alongside the exact application source files into the Sources ZIP.
It also preserves Python's actual installed runtime LICENSE.txt, Python package
notices and a file/checksum inventory from PyInstaller's Analysis output.

The custom PySide hook omits optional ANGLE/Mesa OpenGL renderer binaries.
YM-DL uses raster Qt Widgets. Required imported DLLs are still collected by
PyInstaller; adding Qt Quick, WebEngine or other modules requires corresponding
source/notice coverage. Unexpected Qt modules and optional GL runtime additions
stop release packaging instead of silently producing an incomplete asset.

## Build outputs

The build verifies the frozen GUI, spawned worker, bundled Node and FFmpeg,
conversion to all five formats and audio stream copying before creating:

- `dist/YM-DL-0.4.0-beta.2-Windows-x64.zip`: executable, license notices, source
  directions, dependency/build records and the self-check result.
- `dist/YM-DL-0.4.0-beta.2-Sources.zip`: exact app files, source archives,
  notices, recipes and runtime provenance. It also includes the small prebuilt
  Windows FFmpeg so the GUI can be rebuilt on Windows without a cross-compiler.
- `dist/YM-DL-0.4.0-beta.2-SHA256SUMS.txt`: checksums for both ZIPs.

Upload all three to the same GitHub release. Users only need the Windows ZIP
to run the app; the source asset is provided for access and rebuilding.
Do not substitute GitHub's automatic source ZIP for this companion Sources
asset, because it may not contain the downloaded Qt and Python sources.

## Rebuilding FFmpeg from its source

On a Linux host, install GCC, make, pkg-config, tar, xz and MinGW-w64's x86-64
C compiler/binutils. Run `bash runtime_sources/build_ffmpeg.sh windows`.
The original compiler was Ubuntu's GCC/MinGW-w64 13.2.0 package with MinGW-w64
11.0.1 headers; exact package digests are in the runtime build record.
The original sources are unmodified; the script applies no patches.

`YM_DL_CROSS_PREFIX` can point to a different MinGW cross-compiler prefix, and
`YM_DL_RUNTIME_BUILD_DIR` selects an out-of-tree workspace. The script also
supports `linux` for the development conversion tests. If changing the runtime,
record the new binary/source/recipe digests and build transcript and regenerate
`release_materials/materials-manifest.json` before building a new release.

Qt/PySide archives contain their upstream build instructions. The normal
Windows GUI build uses pinned PyPI wheels; this package records versions and
source access and does not claim bit-identical reproduction of upstream wheels.

## Verification limits

Development checks run on Linux, including a frozen app with equivalent imports
and Node/FFmpeg bundling, codec conversions and release archive generation.
The supplied FFmpeg is a compiled Windows binary, checked for imported DLLs.
The complete Windows GUI executable must still be built and tested on Windows;
the build script performs its frozen self-check there automatically.
