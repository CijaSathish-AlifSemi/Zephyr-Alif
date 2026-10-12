# alif-zephyr-setup

This tool sets up a complete host environment for building Zephyr applications
for Alif Ensemble devices with a single command. Python, git, CMake, Ninja and
the Arm GNU compiler are installed as pinned, self-contained copies; nothing
needs to be installed on the system beforehand.

After installation, open a project in VS Code, select a board and select **Build**.

Linux:

```bash
./alif-setup install      # install or repair (safe to repeat)
./alif-setup verify       # health check, changes nothing
./alif-setup uninstall    # remove the install, restore VS Code settings
```

Windows (`cmd.exe`; in PowerShell type `.\alif-setup` instead of `alif-setup`):

```bat
alif-setup install
alif-setup verify
alif-setup uninstall
```

---

## 1. What you need

| Need | Notes |
|---|---|
| Linux PC, 64-bit Intel/AMD (x86_64) | Ubuntu 22.04 or newer (Alif's requirement). Other Linux versions get a warning but the install continues. |
| or Windows 10 (1803 or newer) / Windows 11, 64-bit | Uses the `tar.exe` and PowerShell that ship with Windows. macOS is not supported in this version. |
| About 8 GB free disk space | Most of it is the Zephyr source code. |
| Internet connection | Downloads come from GitHub and developer.arm.com. A proxy works if `https_proxy` is set. |
| Linux: `curl` (or `wget`) and `tar` | Included in most Linux installations. Otherwise: `sudo apt install curl tar` |
| VS Code | Not required for the install; required to build from the IDE. |

You do **not** need admin rights (`sudo`). On Linux everything goes into your
home folder; on Windows into `C:\alif-zephyr`, a short path on purpose.

> **Windows status.** The Windows installer has not yet been verified on a
> physical machine. If a step fails, `install.log` in the install folder holds
> every command and its output.

**Windows long paths.** Zephyr has deeply nested folders, and Windows limits
paths to 260 characters unless long paths are enabled. The installer checks
this and prints the one-time command if it is off. Run it from an
administrator PowerShell:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
```

---

## 2. Install

Linux:

```bash
cd ~/alif-zephyr-setup
./alif-setup install
```

Windows (`cmd.exe`):

```bat
cd C:\path\to\alif-zephyr-setup
alif-setup install
```

The first run takes **15–30 minutes**, depending on network speed. The install
runs in 7 steps:

| Step | What happens |
|---|---|
| 1. Check this machine | Disk space, internet, operating system version (and Windows long paths) |
| 2. Install tools | Downloads Python, git, CMake, Ninja and the Arm GNU compiler, checks each checksum, unpacks into `tools/` |
| 3. Python environment | Creates a private Python environment (`.venv`) with `west`, Zephyr's command-line tool |
| 4. Download sdk-alif | `west` downloads the Alif SDK, Zephyr and its modules (the slowest step) |
| 5. Zephyr requirements | Python packages Zephyr needs to build |
| 6. Configure VS Code | Tells the Keil Studio extension where Zephyr and the tools are, and installs the extension if needed |
| 7. Smoke test | Builds the `hello_world` sample for the DevKit-E8 to prove everything works |

The install is complete when **Done.** is shown.

**If a step fails**, the message states what failed, why, and the next action.
Most failures are caused by network interruptions. Run `install` again;
completed steps are skipped and the install resumes.

---

## 3. Where things are

Everything for one release lives in one folder:

On Windows the folder is `C:\alif-zephyr\v2.4.0\`, with `env.bat` instead
of `env.sh`.

```
~/alif-zephyr/v2.4.0/
├── tools/
│   ├── python/        Python 3.12
│   ├── git/           git
│   ├── cmake/         CMake
│   ├── ninja/         Ninja
│   └── gcc/           Arm GNU Toolchain 14.3.rel1 (arm-none-eabi-gcc)
├── .venv/             Python environment with west
├── sdk/               the Alif SDK
│   ├── alif/          sdk-alif (the release manifest)
│   ├── zephyr/        Zephyr (this is ZEPHYR_BASE)
│   └── modules/       HALs and libraries
├── build/             smoke-test build output
├── env.sh             for terminal use (see section 5)
├── alif-zephyr.json   product and version
├── install-state.json what was installed (used by verify / uninstall)
└── install.log        every command the installer ran
```

**System tools.** The installer never relies on a system Python, git, CMake or
compiler. Two optional extras are used only if your PC already has them: the
`code` command (to install the VS Code extension) and `dtc`, the devicetree
compiler. Zephyr runs `dtc` only for extra devicetree checks; without it, builds
work the same.

Downloads are cached in `~/.cache/alif-zephyr-setup/downloads/` (Windows:
`%LOCALAPPDATA%\alif-zephyr-setup\downloads\`), so a reinstall does not
download them again.

A new release (for example v2.5.0) installs **next to** this one in
`~/alif-zephyr/v2.5.0/`. Installed releases are independent of each other.

---

## 4. Build in VS Code

1. Restart VS Code if it was open during the install.
2. Open your project folder, for example `~/Zephyr-Alif`.
3. In the **CMSIS** view, select the solution, the target (for example
   `DevKit-E8`) and the build type.
4. Press **Build**.

The installer has already filled in this VS Code user setting, so there is
nothing to type:

```json
"cmsis-csolution.environmentVariables": {
    "ZEPHYR_BASE": "~/alif-zephyr/v2.4.0/sdk/zephyr",
    "VIRTUAL_ENV": "~/alif-zephyr/v2.4.0/.venv",
    "PATH": "<.venv/bin>:<tools/gcc/bin>:<tools/cmake/bin>:<tools/ninja>:<tools/git/bin>",   (Windows: Scripts, cmd, and ";" as separator)
    "GCC_TOOLCHAIN_14_3_1": "~/alif-zephyr/v2.4.0/tools/gcc/bin"
}
```
(In the real file these are full paths. The file is `~/.config/Code/User/settings.json`
on Linux and `%APPDATA%\Code\User\settings.json` on Windows.)

> **Watch out for project settings.** If a project has its own
> `.vscode/settings.json` with `cmsis-csolution.environmentVariables`, those
> values **win** over the installer's. Delete them from the project file, or
> run `verify --check-workspace <project>` to see which ones clash.

---

## 5. Build in a terminal

```bash
source ~/alif-zephyr/v2.4.0/env.sh
cd ~/alif-zephyr/v2.4.0/sdk
west build -p always -b alif_e8_dk/ae822fa0e5597xx0/rtss_he zephyr/samples/hello_world
```

On Windows (`cmd.exe`):

```bat
call C:\alif-zephyr\v2.4.0\env.bat
cd C:\alif-zephyr\v2.4.0\sdk
west build -p always -b alif_e8_dk/ae822fa0e5597xx0/rtss_he zephyr/samples/hello_world
```

`env.sh` / `env.bat` only affect the terminal you run them in. On Windows,
`env.bat` also sets `core.autocrlf=false` and `core.longpaths=true` for git in
that terminal (through `GIT_CONFIG_*` variables), because the default
`autocrlf=true` converts line endings in Zephyr's files.

---

## 6. Check the install: `verify`

```bash
./alif-setup verify          # Windows: alif-setup verify
```

`verify` is a **health check**. It changes nothing. It checks each part and
prints a list:

```
  [OK  ] tool gcc 14.3.rel1  - arm-none-eabi-gcc (Arm GNU Toolchain 14.3.Rel1 ...) 14.3.1
  [OK  ] sdk-alif at v2.4.0
  [OK  ] VS Code settings point here (settings.json)
  [WARN] workspace /home/me/old-project does not override settings - ... sets PATH to other values
```

Use it when a build suddenly fails, after changing VS Code settings, or on a
colleague's machine. Add `--build` to also rebuild `hello_world`.

`OK` = fine · `WARN` = worth a look, builds may still work · `FAIL` = broken; run `install` again.

---

## 7. Remove: `uninstall`

```bash
./alif-setup uninstall       # Windows: alif-setup uninstall
```

This deletes `~/alif-zephyr/v2.4.0/` (Windows: `C:\alif-zephyr\v2.4.0\`) and puts your VS Code setting back the way
it was. It asks before deleting.

- Your own projects are **never** touched.
- VS Code extensions stay installed, because other projects may use them.
- Downloaded archives stay in the cache. Add `--purge-cache` to delete them too.
- Before every change to `settings.json`, a backup is saved next to it as
  `settings.json.alif-backup-<date>`.

---

## 8. Options

| Option | Use |
|---|---|
| `--prefix DIR` | Install somewhere other than `~/alif-zephyr/<release>` (Windows: `C:\alif-zephyr\<release>`) |
| `--manifest FILE` | Use a specific release file from `manifests/` (default: the newest) |
| `--revision REV` | Try another sdk-alif tag or branch with the same tools |
| `--board BOARD` | Use a different board for the smoke test, for example `alif_e7_dk/ae722f80f55d5xx/rtss_he` |
| `--workspace DIR` | Write the VS Code settings into one project instead of your user settings |
| `--no-vscode` | Do not modify VS Code settings or extensions |
| `--skip-smoke-test` | Skip the `hello_world` build at the end (install only) |

Use the same `--prefix` / `--revision` for `verify` and `uninstall` as you did for `install`.

---

## 9. Troubleshooting

| Message | What to do |
|---|---|
| `no connection to github.com` | Check the network connection or proxy (`export https_proxy=http://proxy:port`), then run `install` again. |
| `west update failed 3 times` | Network interruption. Run `install` again; it resumes where it stopped. |
| `checksum mismatch` | The download is corrupted. Run `install` again. If the error persists, the manifest pin may be outdated; contact the maintainer. |
| `cannot read settings.json` | The VS Code settings file has a syntax error. Fix it in VS Code, or use `--no-vscode`. |
| Build in VS Code can't find Zephyr | Run `verify --check-workspace <your project>`. |
| Windows: PowerShell shows a "Security warning" and asks to run a script | You started `alif-setup-windows.ps1` directly. Start `alif-setup` (the `.bat`) instead, or run `Unblock-File .\*` once in the folder. |
| Windows: `CERTIFICATE_VERIFY_FAILED` | Python could not verify a server certificate. The installer then retries with Windows' own downloader (`curl.exe`, then PowerShell), so this normally resolves itself; the sha256 pin still checks every file. If it still fails, a company proxy or firewall is blocking the download. |
| Windows: `tar.exe not found` | Windows 10 before version 1803 has no `tar.exe`. Update Windows. |
| Windows: `Filename too long` / paths longer than 260 characters | Enable long paths (see section 1) and install under a short folder such as the default `C:\alif-zephyr`. |
| Windows: the install is very slow while unpacking | Antivirus scanning of the many small files. Exclude the install folder from real-time scanning if your policy allows it. |

Every command and its full output are in `~/alif-zephyr/<release>/install.log`.

---

## 10. Files in this folder

| File | Purpose |
|---|---|
| `alif-setup` | Linux launcher. Downloads a portable Python, then runs `alif_setup.py` |
| `alif-setup.bat`, `alif-setup-windows.ps1` | Windows launcher: the same job, started from `cmd.exe` or PowerShell |
| `alif_setup.py` | The installer (Python standard library only; Linux and Windows) |
| `manifests/<release>.json` | Every version pin and checksum for one release, with a block per platform |

`hook_setools()` in `alif_setup.py` is a placeholder for Alif SETools (flashing), which is not part of this version.

---

## 11. For maintainers: a new release

1. Copy `manifests/v2.4.0.json` to `manifests/v2.5.0.json`.
2. Change `release`, `sdk_alif.revision` and the tool pins (`url` + `sha256`) in **each** platform block
   (`linux-x86_64`, `windows-x86_64`). Check each archive's layout: `strip` is 1 when it has one top-level
   folder and 0 when it has none (the Arm compiler zip for Windows has none).
3. Run `install` on a clean account on each platform, then `verify --build`.

The installer code does not change between releases; all versions are defined in the manifest.
