#!/usr/bin/env python3
"""Alif Zephyr installer engine (standard library only).

Sets up a complete, self-contained Alif Zephyr host environment in one
versioned folder:

    ~/alif-zephyr/<release>/
        tools/      python, git, cmake, ninja, gcc   (pinned in the manifest)
        .venv/      Python environment with west + Zephyr requirements
        sdk/        west workspace (sdk-alif, zephyr, modules)
        env.sh      "source" this to use the tools in a terminal
        install-state.json, alif-zephyr.json, install.log

Nothing is taken from the system (no system Python, git, cmake...).
Normally started through the ./alif-setup launcher, which provides Python.

Commands: install, verify, uninstall.  Run with --help for options.
"""

import argparse
import collections
import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "alif-zephyr-setup"
DEFAULT_BASE = Path.home() / "alif-zephyr"
STATE_FILE = "install-state.json"
PRODUCT_FILE = "alif-zephyr.json"
TOOL_MARKER = ".alif-tool.json"
VSCODE_KEY = "cmsis-csolution.environmentVariables"
MIN_FREE_GB = 8


# --------------------------------------------------------------------------
# Errors and logging
# --------------------------------------------------------------------------

class Fail(Exception):
    """A problem the user can act on: what happened, why, what to do next."""

    def __init__(self, what, why="", next_step=""):
        super().__init__(what)
        self.what, self.why, self.next_step = what, why, next_step


class Log:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "a", encoding="utf-8")
        self.write(f"\n===== {datetime.datetime.now().isoformat(timespec='seconds')} "
                   f"{' '.join(sys.argv[1:])}")

    def write(self, text):
        self.f.write(text.rstrip("\n") + "\n")
        self.f.flush()

    def say(self, text=""):
        print(text, flush=True)
        self.write(text)

    def step(self, n, total, title):
        self.say(f"\n==> [{n}/{total}] {title}")


# --------------------------------------------------------------------------
# OS layer (Linux only for now; add Windows/macOS classes here later)
# --------------------------------------------------------------------------

class LinuxOS:
    name = "linux-x86_64"
    venv_bin = "bin"
    path_sep = ":"

    @staticmethod
    def vscode_user_settings():
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Code/User/settings.json"

    @staticmethod
    def check_platform():
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise Fail(f"unsupported platform {platform.system()} {platform.machine()}",
                       "this version only supports Linux x86_64.")

    @staticmethod
    def distro_warning():
        """(name, warning or None). Alif's guide asks for Ubuntu 22.04 or newer."""
        try:
            info = platform.freedesktop_os_release()
        except OSError:
            return "unknown Linux", "could not read /etc/os-release; Alif tests on Ubuntu 22.04 or newer."
        name = info.get("PRETTY_NAME", "unknown Linux")
        if info.get("ID") != "ubuntu":
            return name, "Alif tests on Ubuntu 22.04 or newer; other distributions may work but are untested."
        try:
            version = tuple(int(x) for x in info.get("VERSION_ID", "").split("."))
        except ValueError:
            version = ()
        if version < (22, 4):
            return name, "Alif tests on Ubuntu 22.04 or newer; this version is older and may not work."
        return name, None


OS = LinuxOS


# --------------------------------------------------------------------------
# Context: paths and environment for one install
# --------------------------------------------------------------------------

class Ctx:
    def __init__(self, args):
        self.args = args
        self.manifest_path = Path(args.manifest) if args.manifest else latest_manifest()
        self.m = json.loads(self.manifest_path.read_text())
        if self.m.get("platform") != OS.name:
            raise Fail(f"manifest is for {self.m.get('platform')}, this machine is {OS.name}")
        self.revision = args.revision or self.m["sdk_alif"]["revision"]
        self.board = args.board or self.m["smoke_test"]["board"]
        self.root = Path(args.prefix).expanduser().resolve() if args.prefix \
            else DEFAULT_BASE / self.revision
        self.tools = self.root / "tools"
        self.venv = self.root / ".venv"
        self.sdk = self.root / "sdk"
        self.zephyr = self.sdk / "zephyr"
        self.state_path = self.root / STATE_FILE
        self.log = None

    # Paths --------------------------------------------------------------
    def tool_dir(self, name):
        return self.tools / name

    def tool_bins(self):
        bins = []
        for name, t in self.m["tools"].items():
            for b in t["bin"]:
                bins.append((self.tool_dir(name) / b).resolve())
        return bins

    def venv_python(self):
        return self.venv / OS.venv_bin / "python"

    def gcc_bin(self):
        return self.tool_dir("gcc") / "bin"

    # Environment used for every command we run ---------------------------
    def env(self):
        env = dict(os.environ)
        for k in ("PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX"):
            env.pop(k, None)
        ours = [str(self.venv / OS.venv_bin)] + [str(b) for b in self.tool_bins()]
        env["PATH"] = OS.path_sep.join(ours + [env.get("PATH", "/usr/bin:/bin")])
        env["VIRTUAL_ENV"] = str(self.venv)
        env["PYTHONNOUSERSITE"] = "1"
        env.update(self.git_env())
        env["ZEPHYR_BASE"] = str(self.zephyr)
        env["ZEPHYR_TOOLCHAIN_VARIANT"] = "gnuarmemb"
        env["GNUARMEMB_TOOLCHAIN_PATH"] = str(self.tool_dir("gcc"))
        return env

    def git_env(self):
        # The portable git (dugite-native) needs to be told where its parts are.
        g = self.tool_dir("git")
        return {
            "GIT_EXEC_PATH": str(g / "libexec/git-core"),
            "GIT_TEMPLATE_DIR": str(g / "share/git-core/templates"),
            "GIT_SSL_CAINFO": str(g / "ssl/cacert.pem"),
        }

    # Running commands ----------------------------------------------------
    def run(self, cmd, *, cwd=None, check=True, env=None, show=False, next_step=""):
        """Run a command, log all output; on failure show the last lines."""
        cmd = [str(c) for c in cmd]
        self.log.write(f"$ {' '.join(cmd)}" + (f"   (in {cwd})" if cwd else ""))
        tail = collections.deque(maxlen=30)
        start = last_beat = time.monotonic()
        try:
            p = subprocess.Popen(cmd, cwd=cwd, env=env or self.env(), text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 errors="replace")
        except FileNotFoundError as e:
            raise Fail(f"could not start {cmd[0]}", str(e), next_step)
        out = []
        for line in p.stdout:
            self.log.write(line)
            tail.append(line.rstrip())
            out.append(line)
            if show:
                print("    " + line.rstrip(), flush=True)
            elif time.monotonic() - last_beat > 30:
                last_beat = time.monotonic()
                mins, secs = divmod(int(last_beat - start), 60)
                print(f"    ... still working ({mins}m {secs:02d}s)", flush=True)
        rc = p.wait()
        self.log.write(f"[exit {rc}]")
        if check and rc != 0:
            raise Fail(f"command failed: {' '.join(cmd[:4])}{' ...' if len(cmd) > 4 else ''}",
                       "last output:\n      " + "\n      ".join(tail), next_step)
        return rc, "".join(out)


def latest_manifest():
    found = sorted((HERE / "manifests").glob("v*.json"),
                   key=lambda p: [int(x) if x.isdigit() else x
                                  for x in p.stem.lstrip("v").replace("-", ".").split(".")])
    if not found:
        raise Fail("no manifest found", f"expected files like {HERE}/manifests/v2.4.0.json")
    return found[-1]


# --------------------------------------------------------------------------
# Download / extract
# --------------------------------------------------------------------------

def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(ctx, url, sha256):
    """Download into the shared cache (reused by later installs) and verify."""
    dl = CACHE / "downloads"
    dl.mkdir(parents=True, exist_ok=True)
    dest = dl / urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    if dest.exists() and sha256_of(dest) == sha256:
        ctx.log.say(f"    using cached {dest.name}")
        return dest
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, 4):
        try:
            ctx.log.write(f"GET {url} (attempt {attempt})")
            req = urllib.request.Request(url, headers={"User-Agent": "alif-zephyr-setup"})
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done, shown = 0, -10
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        if pct >= shown + 10:
                            shown = pct - pct % 10
                            print(f"    downloading {dest.name}: {pct}% of {total >> 20} MB", flush=True)
            break
        except OSError as e:
            ctx.log.say(f"    download problem: {e}")
            if attempt == 3:
                raise Fail(f"could not download {url}", str(e),
                           "check your internet connection or proxy (https_proxy), then run install again.")
            time.sleep(5 * attempt)
    got = sha256_of(part)
    if got != sha256:
        part.unlink()
        raise Fail(f"checksum mismatch for {dest.name}",
                   f"expected {sha256}\n      got      {got}",
                   "run install again; if it repeats, the manifest pin or the download server changed.")
    part.replace(dest)
    return dest


def extract(archive, dest, strip):
    """Extract archive into dest, removing `strip` leading folders (0 or 1)."""
    tmp = dest.with_name(f".tmp-{dest.name}")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                z.extract(info, tmp)
                mode = info.external_attr >> 16  # zipfile drops permissions
                if mode:
                    os.chmod(tmp / info.filename, mode & 0o777)
    else:
        with tarfile.open(archive) as t:
            t.extractall(tmp, filter="data")
    src = tmp
    if strip:
        children = list(tmp.iterdir())
        if len(children) != 1 or not children[0].is_dir():
            raise Fail(f"unexpected layout in {archive.name}",
                       "expected one top-level folder (manifest 'strip': 1).")
        src = children[0]
    shutil.rmtree(dest, ignore_errors=True)
    src.replace(dest)
    shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# Install steps
# --------------------------------------------------------------------------

def step_preflight(ctx):
    OS.check_platform()
    ctx.root.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(ctx.root).free / 1e9
    os_name, os_warning = OS.distro_warning()
    ctx.log.say(f"    system         : {os_name}")
    if os_warning:
        ctx.log.say(f"    WARNING        : {os_warning} Continuing anyway.")
    ctx.log.say(f"    install folder : {ctx.root}")
    ctx.log.say(f"    manifest       : {ctx.manifest_path.name} (sdk-alif {ctx.revision})")
    ctx.log.say(f"    free disk      : {free_gb:.0f} GB")
    if free_gb < MIN_FREE_GB:
        raise Fail(f"not enough disk space ({free_gb:.1f} GB free)",
                   f"the full install needs about {MIN_FREE_GB} GB.",
                   "free some space or choose another folder with --prefix.")
    try:
        urllib.request.urlopen("https://github.com", timeout=20).close()
    except OSError as e:
        raise Fail("no connection to github.com", str(e),
                   "check your internet connection or proxy (https_proxy), then run install again.")


def tool_ok(ctx, name, t):
    d = ctx.tool_dir(name)
    try:
        marker = json.loads((d / TOOL_MARKER).read_text())
    except (OSError, ValueError):
        return False
    if marker.get("sha256") != t["sha256"]:
        return False
    rc, _ = ctx.run([d / t["check"][0], *t["check"][1:]], check=False)
    return rc == 0


def step_tools(ctx):
    ctx.tools.mkdir(parents=True, exist_ok=True)
    for name, t in ctx.m["tools"].items():
        if tool_ok(ctx, name, t):
            ctx.log.say(f"    {name:7} {t['version']:10} already installed")
            continue
        ctx.log.say(f"    {name:7} {t['version']:10} installing...")
        archive = download(ctx, t["url"], t["sha256"])
        extract(archive, ctx.tool_dir(name), t["strip"])
        (ctx.tool_dir(name) / TOOL_MARKER).write_text(json.dumps(
            {"version": t["version"], "sha256": t["sha256"], "url": t["url"]}, indent=2))
        if not tool_ok(ctx, name, t):
            raise Fail(f"{name} was installed but does not run", f"see {ctx.log.path}")


def step_venv(ctx):
    py = ctx.venv_python()
    if not py.exists():
        ctx.run([ctx.tool_dir("python") / "bin/python3", "-m", "venv", ctx.venv])
    pins = [f"{k}=={v}" for k, v in ctx.m["python_packages"].items()]
    ctx.log.say(f"    pip install {' '.join(pins)}")
    ctx.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", *pins])


def manifest_repo(ctx):
    return ctx.sdk / "alif"


def step_sdk(ctx):
    url = ctx.m["sdk_alif"]["url"]
    py = ctx.venv_python()
    if not (ctx.sdk / ".west").exists():
        ctx.log.say(f"    west init {url} @ {ctx.revision}")
        shutil.rmtree(ctx.sdk, ignore_errors=True)
        ctx.run([py, "-m", "west", "init", "-m", url, "--mr", ctx.revision, ctx.sdk])
    else:
        _, head = ctx.run(["git", "-C", manifest_repo(ctx), "rev-parse", "HEAD"])
        rc, want = ctx.run(["git", "-C", manifest_repo(ctx), "rev-parse", f"{ctx.revision}^{{commit}}"],
                           check=False)
        if rc != 0 or head.strip() != want.strip():
            raise Fail(f"{ctx.sdk} already holds a different sdk-alif revision",
                       f"wanted {ctx.revision}.",
                       "use another --prefix, or run uninstall first.")
        ctx.log.say("    west workspace already initialised")
    ctx.log.say("    west update (downloads Zephyr and modules; 5-20 minutes the first time)")
    tries = [["--narrow", "--fetch-opt=--depth=1"], [], []]
    for i, extra in enumerate(tries, 1):
        rc, _ = ctx.run([py, "-m", "west", "update", *extra], cwd=ctx.sdk, check=False)
        if rc == 0:
            return
        ctx.log.say(f"    west update failed (try {i}/{len(tries)}), retrying...")
        time.sleep(5)
    raise Fail("west update failed 3 times", f"see {ctx.log.path}",
               "usually a network hiccup: run install again (it continues where it stopped).")


def step_requirements(ctx):
    req = ctx.zephyr / "scripts/requirements.txt"
    ctx.log.say(f"    pip install -r {req.relative_to(ctx.root)} (a few minutes)")
    ctx.run([ctx.venv_python(), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", req])


def hook_setools(ctx):
    """HOOK: Alif SETools (flashing). Intentionally empty - out of scope for v1."""
    return None


def write_env_files(ctx):
    env = ctx.env()
    keys = ["PATH", "VIRTUAL_ENV", "ZEPHYR_BASE", "ZEPHYR_TOOLCHAIN_VARIANT",
            "GNUARMEMB_TOOLCHAIN_PATH", *ctx.git_env()]
    ours = OS.path_sep.join([str(ctx.venv / OS.venv_bin)] + [str(b) for b in ctx.tool_bins()])
    lines = ["# Generated by alif-setup. Use:  source " + str(ctx.root / "env.sh"),
             f'export PATH="{ours}:$PATH"']
    lines += [f'export {k}="{env[k]}"' for k in keys if k != "PATH"]
    lines.append('echo "Alif Zephyr ' + ctx.revision + ' environment active (west, cmake, arm-none-eabi-gcc)."')
    (ctx.root / "env.sh").write_text("\n".join(lines) + "\n")


def vscode_values(ctx):
    path = OS.path_sep.join([str(ctx.venv / OS.venv_bin), str(ctx.gcc_bin()),
                             str(ctx.tool_dir("cmake") / "bin"), str(ctx.tool_dir("ninja")),
                             str(ctx.tool_dir("git") / "bin")])
    return {
        "ZEPHYR_BASE": str(ctx.zephyr),
        "VIRTUAL_ENV": str(ctx.venv),
        "PATH": path,
        ctx.m["vscode"]["gcc_env_var"]: str(ctx.gcc_bin()),
    }


def strip_jsonc(text):
    """Remove // and /* */ comments and trailing commas (VS Code allows them)."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        elif c in "}]":
            j = len(out) - 1
            while j >= 0 and out[j].isspace():
                j -= 1
            if j >= 0 and out[j] == ",":
                del out[j]
            out.append(c)
        else:
            out.append(c)
        i += 1
    return "".join(out)


def load_settings(path):
    if not path.exists() or not path.read_text().strip():
        return {}, False
    text = path.read_text()
    try:
        return json.loads(text), False
    except ValueError:
        pass
    try:
        return json.loads(strip_jsonc(text)), True
    except ValueError as e:
        raise Fail(f"cannot read {path}", f"not valid JSON: {e}",
                   "fix the file in VS Code, or rerun with --no-vscode and add the settings by hand.")


def save_settings(ctx, path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.alif-backup-{stamp}")
        shutil.copy2(path, backup)
        ctx.log.say(f"    backup: {backup}")
    path.write_text(json.dumps(data, indent=4) + "\n")


def settings_target(ctx):
    if ctx.args.workspace:
        return Path(ctx.args.workspace).expanduser().resolve() / ".vscode/settings.json"
    return OS.vscode_user_settings()


def step_vscode(ctx, state):
    if ctx.args.no_vscode:
        ctx.log.say("    skipped (--no-vscode)")
        return
    path = settings_target(ctx)
    data, had_comments = load_settings(path)
    current = data.get(VSCODE_KEY) or {}
    wanted = vscode_values(ctx)
    prev = state.get("vscode", {})
    # Keep the values from before our *first* install, so uninstall restores them.
    if prev.get("settings_file") == str(path):
        previous_values = prev.get("previous_values", {})
        key_existed = prev.get("key_existed", bool(current))
    else:
        previous_values = {k: current.get(k) for k in wanted}
        key_existed = VSCODE_KEY in data
    if all(current.get(k) == v for k, v in wanted.items()):
        ctx.log.say(f"    {path} already up to date")
    else:
        if had_comments:
            ctx.log.say("    note: comments in settings.json are removed when it is rewritten (backup kept)")
        data[VSCODE_KEY] = {**current, **wanted}
        save_settings(ctx, path, data)
        ctx.log.say(f"    wrote '{VSCODE_KEY}' to {path}")
    state["vscode"] = {"settings_file": str(path), "values": wanted,
                       "previous_values": previous_values, "key_existed": key_existed}

    code = shutil.which("code")
    if not code:
        ctx.log.say("    VS Code ('code' command) not found - install VS Code, then the"
                    f" extension(s): {', '.join(ctx.m['vscode']['extensions'])}")
        return
    _, have = ctx.run([code, "--list-extensions"], check=False)
    have = {x.strip().lower() for x in have.splitlines()}
    for ext in ctx.m["vscode"]["extensions"]:
        if ext.lower() in have:
            ctx.log.say(f"    extension {ext}: already installed")
        else:
            rc, _ = ctx.run([code, "--install-extension", ext], check=False)
            ctx.log.say(f"    extension {ext}: {'installed' if rc == 0 else 'FAILED (install it from the Extensions view)'}")


def smoke_build(ctx):
    build = ctx.root / "build" / "smoke-hello_world"
    app = ctx.sdk / ctx.m["smoke_test"]["app"]
    ctx.run([ctx.venv_python(), "-m", "west", "build", "-p", "always", "-b", ctx.board,
             "-d", build, app], cwd=ctx.sdk,
            next_step="see install.log; run './alif-setup verify' to check each part.")
    elf = build / "zephyr" / "zephyr.elf"
    if not elf.exists():
        raise Fail("smoke test built but zephyr.elf is missing", f"looked in {elf}")
    return elf


def step_smoke(ctx):
    if ctx.args.skip_smoke_test:
        ctx.log.say("    skipped (--skip-smoke-test)")
        return "skipped"
    ctx.log.say(f"    west build hello_world for {ctx.board}")
    elf = smoke_build(ctx)
    ctx.log.say(f"    OK: {elf.relative_to(ctx.root)} ({elf.stat().st_size // 1024} KB)")
    return "passed"


def load_state(ctx):
    try:
        return json.loads(ctx.state_path.read_text())
    except (OSError, ValueError):
        return {}


def save_state(ctx, state):
    ctx.state_path.write_text(json.dumps(state, indent=2) + "\n")


def cmd_install(ctx):
    ctx.log = Log(ctx.root / "install.log")
    state = load_state(ctx)
    state.update({"product": "alif-zephyr", "release": ctx.revision,
                  "manifest": ctx.m, "manifest_file": str(ctx.manifest_path), "root": str(ctx.root),
                  "started": datetime.datetime.now().isoformat(timespec="seconds"),
                  "complete": False})
    steps = [
        ("Check this machine", lambda: step_preflight(ctx)),
        ("Install tools (python, git, cmake, ninja, arm-none-eabi-gcc)", lambda: step_tools(ctx)),
        ("Create Python environment with west", lambda: step_venv(ctx)),
        (f"Download sdk-alif {ctx.revision} with west", lambda: step_sdk(ctx)),
        ("Install Zephyr Python requirements", lambda: step_requirements(ctx)),
        ("Configure VS Code", lambda: step_vscode(ctx, state)),
        ("Smoke test: build hello_world", lambda: state.__setitem__("smoke_test", step_smoke(ctx))),
    ]
    ctx.root.mkdir(parents=True, exist_ok=True)
    save_state(ctx, state)  # marks the folder as ours (uninstall relies on it)
    try:
        for i, (title, fn) in enumerate(steps, 1):
            ctx.log.step(i, len(steps), title)
            fn()
            if i == 4:
                write_env_files(ctx)
            save_state(ctx, state)
        hook_setools(ctx)
    finally:
        save_state(ctx, state)
    state["components"] = {n: t["version"] for n, t in ctx.m["tools"].items()}
    state["components"]["sdk-alif"] = ctx.revision
    state["complete"] = True
    state["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    save_state(ctx, state)
    (ctx.root / PRODUCT_FILE).write_text(json.dumps(
        {"product": "AlifZephyr", "version": ctx.revision,
         "installer_manifest": ctx.manifest_path.name}, indent=4) + "\n")
    ctx.log.say(f"""
Done. Alif Zephyr {ctx.revision} is installed in {ctx.root}

Next:
  * VS Code: open your project folder (e.g. ~/Zephyr-Alif), pick the board in
    the CMSIS view and press Build. Restart VS Code first if it was open.
  * Terminal:  source {ctx.root / 'env.sh'}   then use west as usual.
  * Health check any time:  ./alif-setup verify
""")


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def cmd_verify(ctx):
    ctx.log = Log(CACHE / "verify.log")
    results = []

    def check(label, ok, detail="", level="FAIL"):
        tag = "OK" if ok else level
        results.append(tag)
        print(f"  [{tag:4}] {label}" + (f"  - {detail}" if detail else ""))

    print(f"Checking {ctx.root}\n")
    os_name, os_warning = OS.distro_warning()
    check(f"system {os_name}", not os_warning, os_warning or "", "WARN")
    state = load_state(ctx)
    check("install folder exists", ctx.root.is_dir(), str(ctx.root))
    check("install finished completely", state.get("complete") is True,
          "" if state.get("complete") else "run ./alif-setup install again")
    if not ctx.root.is_dir():
        return summary(results)

    for name, t in ctx.m["tools"].items():
        d = ctx.tool_dir(name)
        ok = tool_ok(ctx, name, t)
        ver = ""
        if ok:
            _, out = ctx.run([d / t["check"][0], *t["check"][1:]], check=False)
            ver = (out.strip().splitlines() or [""])[0][:70]
        check(f"tool {name} {t['version']}", ok, ver or "missing or wrong version")

    py = ctx.venv_python()
    rc, out = ctx.run([py, "-m", "west", "--version"], check=False) if py.exists() else (1, "")
    check("Python environment + west", rc == 0, out.strip())

    rc, head = ctx.run(["git", "-C", manifest_repo(ctx), "rev-parse", "HEAD"], check=False)
    rc2, want = ctx.run(["git", "-C", manifest_repo(ctx), "rev-parse", f"{ctx.revision}^{{commit}}"],
                        check=False)
    check(f"sdk-alif at {ctx.revision}", rc == 0 and rc2 == 0 and head.strip() == want.strip(),
          head.strip()[:12])
    check("zephyr downloaded", (ctx.zephyr / "VERSION").exists(), str(ctx.zephyr))

    rc, out = ctx.run([py, "-c", REQ_CHECK, ctx.zephyr / "scripts/requirements.txt"], check=False) \
        if py.exists() else (1, "")
    check("Zephyr Python requirements", rc == 0, out.strip()[:120])

    if ctx.args.no_vscode:
        print("  [SKIP] VS Code checks (--no-vscode)")
    else:
        path = settings_target(ctx)
        wanted = vscode_values(ctx)
        try:
            data, _ = load_settings(path)
        except Fail as e:
            data = {}
            check(f"VS Code settings readable ({path})", False, e.why)
        cur = data.get(VSCODE_KEY) or {}
        bad = [k for k, v in wanted.items() if cur.get(k) != v]
        check(f"VS Code settings point here ({path.name})", not bad,
              f"wrong/missing: {', '.join(bad)}" if bad else "")
        # Workspace settings override user settings - warn if one points elsewhere.
        for ws in {Path.cwd(), *[Path(w).expanduser() for w in ctx.args.check_workspace or []]}:
            f = ws / ".vscode/settings.json"
            if f.exists() and f != path:
                try:
                    wcur = load_settings(f)[0].get(VSCODE_KEY)
                except Fail:
                    continue
                if wcur:
                    diff = [k for k in wanted if k in wcur and wcur[k] != wanted[k]]
                    check(f"workspace {ws} does not override settings", not diff,
                          f"{f} sets {', '.join(diff)} to other values", "WARN")
        code = shutil.which("code")
        if code:
            _, have = ctx.run([code, "--list-extensions"], check=False)
            have = {x.strip().lower() for x in have.splitlines()}
            for ext in ctx.m["vscode"]["extensions"]:
                check(f"VS Code extension {ext}", ext.lower() in have, level="WARN")
        else:
            check("VS Code installed ('code' command)", False, level="WARN")

    if ctx.args.build:
        try:
            smoke_build(ctx)
            check(f"test build hello_world ({ctx.board})", True)
        except Fail as e:
            check(f"test build hello_world ({ctx.board})", False, e.what)
    return summary(results)


# Runs inside the venv: every package named in requirements.txt (and the files
# it includes with -r) must be installed. Markers like "; sys_platform=='win32'"
# are honoured.
REQ_CHECK = r"""
import sys, re, importlib.metadata as md
from pathlib import Path
try:
    from packaging.markers import Marker
except ImportError:
    Marker = None
missing = []
def walk(f):
    for line in Path(f).read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        if line.startswith("-r"):
            walk(Path(f).parent / line[2:].strip())
            continue
        req, _, marker = line.partition(";")
        if marker.strip() and Marker and not Marker(marker.strip()).evaluate():
            continue
        name = re.split(r"[<>=!~\[ ]", req.strip(), 1)[0]
        try:
            md.version(name)
        except md.PackageNotFoundError:
            missing.append(name)
walk(sys.argv[1])
print("missing: " + ", ".join(missing) if missing else "all installed")
sys.exit(1 if missing else 0)
"""


def summary(results):
    fails, warns = results.count("FAIL"), results.count("WARN")
    print(f"\n{len(results) - fails - warns} OK, {warns} warnings, {fails} failures")
    return 1 if fails else 0


# --------------------------------------------------------------------------
# uninstall
# --------------------------------------------------------------------------

def cmd_uninstall(ctx):
    ctx.log = Log(CACHE / "uninstall.log")
    if not ctx.state_path.exists():
        raise Fail(f"{ctx.root} is not an alif-setup install",
                   f"{STATE_FILE} not found there, so nothing is deleted.",
                   "check the --prefix / --revision you passed.")
    state = load_state(ctx)
    vs = state.get("vscode")
    print(f"This will delete {ctx.root}")
    if vs:
        print(f"and remove its entries from {vs['settings_file']}")
    print("Your projects and the download cache are not touched.")
    if not ctx.args.yes and input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Cancelled.")
        return 1

    if vs:
        path = Path(vs["settings_file"])
        try:
            data, _ = load_settings(path)
            cur = dict(data.get(VSCODE_KEY) or {})
            changed = False
            for k, v in vs["values"].items():
                if cur.get(k) == v:  # only undo values that are still ours
                    old = vs["previous_values"].get(k)
                    if old is None:
                        cur.pop(k, None)
                    else:
                        cur[k] = old
                    changed = True
            if changed:
                if cur or vs.get("key_existed"):
                    data[VSCODE_KEY] = cur
                else:
                    data.pop(VSCODE_KEY, None)
                save_settings(ctx, path, data)
                ctx.log.say(f"restored {VSCODE_KEY} in {path}")
        except Fail as e:
            ctx.log.say(f"WARNING: could not update {path}: {e.why} - edit it by hand.")

    shutil.rmtree(ctx.root)
    ctx.log.say(f"deleted {ctx.root}")
    if ctx.args.purge_cache:
        shutil.rmtree(CACHE / "downloads", ignore_errors=True)
        ctx.log.say(f"deleted download cache {CACHE / 'downloads'}")
    print("VS Code extensions were left installed (other projects may use them).")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--manifest", help="manifest file (default: newest in manifests/)")
    common.add_argument("--prefix", help="install folder (default: ~/alif-zephyr/<release>)")
    common.add_argument("--revision", help="override the sdk-alif revision from the manifest")
    common.add_argument("--board", help="override the smoke-test board")
    common.add_argument("--workspace", help="write VS Code settings into this folder's .vscode/ "
                                            "instead of your user settings")
    common.add_argument("--no-vscode", action="store_true", help="do not touch VS Code")

    ap = argparse.ArgumentParser(prog="alif-setup", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("install", parents=[common], help="install or repair (safe to run again)")
    p.add_argument("--skip-smoke-test", action="store_true", help="do not build hello_world at the end")
    p = sub.add_parser("verify", parents=[common], help="health check; changes nothing")
    p.add_argument("--build", action="store_true", help="also rebuild hello_world")
    p.add_argument("--check-workspace", action="append", metavar="DIR",
                   help="also warn if DIR/.vscode/settings.json overrides the settings")
    p = sub.add_parser("uninstall", parents=[common], help="remove this install")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--purge-cache", action="store_true", help="also delete downloaded archives")
    args = ap.parse_args()

    ctx = None
    try:
        ctx = Ctx(args)
        rc = {"install": cmd_install, "verify": cmd_verify, "uninstall": cmd_uninstall}[args.command](ctx)
        return rc or 0
    except Fail as e:
        print(f"\nERROR: {e.what}", file=sys.stderr)
        if e.why:
            print(f"  Why : {e.why}", file=sys.stderr)
        if e.next_step:
            print(f"  Next: {e.next_step}", file=sys.stderr)
        if ctx and ctx.log:
            ctx.log.write(f"ERROR: {e.what} | {e.why} | {e.next_step}")
            print(f"  Log : {ctx.log.path}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. Run the same command again to continue.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
