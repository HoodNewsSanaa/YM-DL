# Publish YM-DL on GitHub

Suggested repository name: **YM-DL**

Suggested description:

> Simple Windows desktop app for YouTube Music albums and playlists, with ordered URL queues, optional codec/bitrate previews, album artwork, tagged audio and album-only folders.

## 1. Create a source repository

Use a fresh extraction of this source ZIP. Do not upload a folder that contains your cookies, downloaded music, virtual environment or built executable.

The simplest first upload uses the GitHub website:

1. Sign in at https://github.com and choose **New repository** from the **+** menu.
2. Name it `YM-DL`, enter the description above, and choose **Public** if you want anyone to see it. A private repository is useful while testing.
3. Do not generate a README or .gitignore; this package already contains both. Click **Create repository**.
4. Choose **uploading an existing file** on the empty repository page. Upload the contents of the extracted `YM-DL` folder, including `assets/`, `tests/`, README.md, PUBLISHING.md and `.gitignore`. Upload the files rather than the ZIP itself; keep `app.py` and README.md at the repository root.
5. Review the file list, enter `Initial YM-DL beta` as the commit message, and click **Commit changes**.

Website uploads do not apply `.gitignore`; use the fresh source package and review the upload list yourself. If Windows hides `.gitignore`, enable hidden items or add it using GitHub's **Add file → Create new file**.

For frequent updates, install https://desktop.github.com, sign in, and clone this repository using **File → Clone repository**. Copy revised source files into the clone, review the changes, write a commit message, **Commit to main**, then **Push origin**. Build output and cookies are excluded by the provided `.gitignore` when using Git.

## 2. Select the project license

This package has no project LICENSE yet. Choose a license before calling the project open source and add the corresponding LICENSE file using GitHub's license template chooser. GitHub's guidance: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository

The app depends on Mutagen, PySide6, yt-dlp, FFmpeg and other components with their own licenses. A project license does not replace their terms. Before publishing a bundled executable, include the applicable third-party notices and source information for the exact bundled versions. The build generates version/hash information in `dist` to help identify them.

## 3. Test the Windows build

Run **Build-Windows.cmd** on Windows, then test `dist\YM-DL.exe`:

- Paste a public album link and verify it loads automatically with artwork on the right. Use Check quality on selected tracks to verify source/output audio columns.
- Download Original audio and one converted format.
- Queue two album URLs and confirm they run in order into album-only folders.
- Confirm completed jobs remove the work folder and history JSON.
- Test cancellation and repeat downloads.
- Turn off normal delays in Settings and confirm retry waits still apply when a track fails.
- Verify an exhausted queue failure pauses with Try again, Skip and Cancel, and that retry arrows appear correctly in Settings.
- If available, test your exported Premium cookies privately; do not upload them.

Automated tests and the Linux packaged self-check have passed. The Windows executable and Premium authentication have not been verified in the development environment. Keep that limitation in your release notes until you test them.

## 4. Make a downloadable beta release

After Windows testing and preparing dependency notices:

1. Open your repository's **Releases**, then **Draft a new release**.
2. Create tag `v0.4.0-beta.1` and title `YM-DL 0.4 beta`.
3. Describe the changes, known limitations, supported Windows version you tested and unsigned-executable status.
4. Attach a ZIP containing the tested `YM-DL.exe`, a short README, dependency notices and relevant build information. A checksum is helpful. Put compiled files in Release assets rather than the source tree.
5. Check **This is a pre-release** and click **Publish release**.

Suggested release notes:

> YM-DL 0.4 beta adds live retry countdowns, a queue overview with per-album progress and colored status boxes, a red warning for explicitly invalid or rotated cookies, scrolling during downloads and detailed failure summaries. Release matching has been removed; metadata comes from YouTube Music with manual editing. It retains the supplied logo, artwork panel, paused queue decisions, per-album cleanup and ASAP setting. Queues reuse metadata and artwork caches and update quality rows efficiently. Optional quality checks, exported cookies, original audio and converted formats remain available. Stream quality depends on the formats YouTube exposes to your session. This release is unsigned; please report reproducible bugs without cookies or account data.

GitHub upload instructions: https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository

GitHub release instructions: https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository
