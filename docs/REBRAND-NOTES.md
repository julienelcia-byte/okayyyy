# NELTH BROWSER — Windows rebrand notes (Optix AI)

Branch `nelth-rebrand`, based on upstream `phibrowser/phibrowser-win` `dev`
(`5e115ec`, v0.6.0 line). This file documents every brand change and, just as
importantly, every place where the **Phi** name must stay because the
proprietary framework computes it.

## What was rebranded

| File | Change |
|---|---|
| `client/phi_client.rc` | `ProductName`/`FileDescription` "Nelth Browser", `CompanyName` "Optix AI", `InternalName` "Nelth", `ProductShortName` "Nelth", copyright "Optix AI. Based on Phi Browser (Apache 2.0)." |
| `client/phi_updater.cc` | Upstream updater **disabled**: empty appcast URL + empty EdDSA signing key → WinSparkle never initialises, the "check for updates" surface stays dark, and no update is ever pulled from `ota.phibrowser.com`. App details read "Optix AI" / "Nelth Browser". |
| `client/resources/phi.ico` | Regenerated with `tools/gen-app-icon.py` from the Nelth "N" master art (all 16 Windows shell sizes). Same file feeds the exe icon (`.rc` slot 101), the installer and uninstaller icons (NSIS `Icon`/`UninstallIcon`), and shortcuts. |
| `client/resources/strings.json`, `strings-source.json` | Every user-visible string value: "Phi Browser" → "Nelth Browser", "Phi" → "Nelth", "Phinomenon (Inc.)" → "Optix AI", in all languages. Catalog **keys** (e.g. `menuBar.aboutPhi`) untouched — they are code identifiers. |
| `installer/phi-installer.nsi` | Name/Captions "Nelth Browser", `OutFile NelthBrowserSetup-<version>.exe`, install dir `%PROGRAMFILES64%\Nelth Browser`, `REG_PRODUCT Software\Nelth`, uninstall key `...\Uninstall\NelthBrowser`, `BROWSER_NAME "Nelth"`, `BROWSER_COMPANY "Optix AI"`, VI version keys, `Publisher "Optix AI"`, and all user-visible messages. |
| `installer/make-installer.sh` | Setup output name `NelthBrowserSetup-<version>.<build>.exe`. |

## What deliberately keeps the Phi/Chromium names (and why)

- **`BROWSER_APP "Chromium"`, `ChromiumHTM`, `ChromiumPDF`, `chromium` scheme**
  (`phi-installer.nsi`). The comment in the file says it plainly: these must
  match what `chrome.dll` (the proprietary framework) computes through
  `install_static`, or default-browser registration and Settings' deep links
  miss the entry. Changing them breaks the browser, not just the name.
- **`Phi.exe`** — the framework's binary name. The framework is a prebuilt,
  closed-source Chromium distribution; its loader, child processes and
  relaunch logic refer to that name. Renaming it without the framework's
  build system would break the browser.
- **`%LOCALAPPDATA%\Phi\User Data`** (`$DataDirDefault` in the installer) —
  the profile location computed by `chrome.dll`. Keeping it is what makes
  existing user profiles survive install/update/uninstall/reinstall.
- **Profile data file names** (`PhiPrefs.json`, `PhiAuth.dat`, …) in the
  uninstall list — these are the real files the client writes; the list must
  match them so uninstall stays accurate.
- **Catalog keys and code identifiers** (`phi_*`, `phi-browser-skill`,
  `menuBar.aboutPhi`, …) — not user-visible; renaming them breaks lookups.
- **Apache 2.0 attribution** — LICENSE and the `// Copyright 2026 Phinomenon
  Inc.` headers are kept intact. Nelth is an Apache 2.0 fork of Phi; the
  licence requires the attribution and the project wants it.

## Known limitations of this build (honest list)

1. **Unsigned** — no Authenticode certificate is wired into CI
   (`--no-sign`). SmartScreen will warn on first run ("More info → Run
   anyway"). Signed builds need a certificate and `phibrowser-win-build`'s
   signing rig, which is upstream's private infra.
2. **No updater** — by design (see `phi_updater.cc`). Nelth ships installers;
   it never pulls updates from upstream Phi infrastructure.
3. **No Widevine VMP** — `--vmp` is not used, so DRM-verified streaming
   services may refuse a licence. Needs castLabs EVS credentials (upstream's
   private rig).
4. **Self-build boundaries** (upstream README applies verbatim): no Phi
   account sign-in, no Phi Cloud, no sync, no connectors/messaging relay.
   The browser itself, tabs, bookmarks, history, settings and the local AI
   agent surfaces are unchanged.
5. **Not the app Phi distributes** — do not present it as such (upstream
   README §"A build you make yourself").

## How the real installer is produced

`.github/workflows/build-nelth-installer.yml`:

1. **windows-latest**: `tools/fetch-framework.py` downloads the framework
   pinned in `framework.lock` and verifies its SHA-256 byte-for-byte;
   `build-client.py` compiles `phi_client.dll` with MSVC (this is the only
   step that genuinely requires Windows).
2. **ubuntu-latest**: `installer/make-installer.sh` stages the ship tree in
   the installed layout and packs `NelthBrowserSetup.exe` with the Debian
   NSIS package — the host upstream's script was written for ("The Windows
   box plays no part"). The job also emits `NelthBrowserSetup.exe.SHA256`.

Run it: push this branch to GitHub → Actions → "Build Nelth Browser
installer" → Run workflow → download the `NelthBrowserSetup` artifact.

## Framework-level rebrand (tools/nelthize-framework.py)

The prebuilt framework zip carries the upstream Phi branding inside its own
binary assets. `tools/nelthize-framework.py` rewrites it in place during CI,
right after `fetch-framework.py` verified the pinned download:

* every locale `.pak` (all languages): user-visible strings "Phi" → "Nelth",
  "Phinomenon" → "Optix AI" (word-boundary, text entries only — binary
  entries are never touched, so embedded fonts stay intact);
* `chrome_100/200_percent.pak` ids 40262/40263: the swirl+"Phi" product
  logos → NELTH lockups (light and dark variants, sizes preserved);
* `resources.pak` ids 14152/14154/14155/14156/14200 (app-icon tiles) and
  15163/15659/15687/15739 (profile tiles + letter): → NELTH tiles;
* `Phi.exe`: VERSIONINFO → Nelth Browser / Optix AI (Apache 2.0 attribution
  kept) and all 16 RT_ICON frames → the NELTH icon (dims matched 1:1);
* `chrome.dll` / `chrome_proxy.exe` / `chrome_elf.dll`: VERSIONINFO →
  Optix AI / Nelth.

The asset PNGs live in `tools/nelth-assets/` (committed; regenerate with
`tools/gen-nelth-assets.py`, which extracts the "N" silhouette from the
master art). Every patched file is parsed back and validated by the tool;
a failed patch fails the build.

Deliberately untouched: `PhiClient*` API names, catalog keys, class and
registry names, `phibrowser.com` URLs, the exe file name `Phi.exe` (the
framework's loader refers to it), and the Apache 2.0 attribution strings.
