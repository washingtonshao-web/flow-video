"""Shared paths and runtime auto-detection. Nothing is version-pinned: browsers, Codex and ffmpeg are located at runtime."""
import glob
import io
import os
import platform
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# Persistent per-user data (survives plugin updates): Claude Code sets CLAUDE_PLUGIN_DATA for plugin servers.
DATA = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or os.environ.get("FLOW_VIDEO_HOME")
            or Path.home() / ".flow-video")
DATA.mkdir(parents=True, exist_ok=True)
STATE = DATA


def browser_exe(kind: str = "auto") -> tuple[str, str] | None:
    """(kind, path) of Chrome or Edge, or None."""
    names = {"auto": ["chrome", "msedge"], "chrome": ["chrome"], "edge": ["msedge"]}[kind]
    for name in names:
        if IS_WIN:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}.exe") as k:
                        p = winreg.QueryValue(k, None)
                        if p and Path(p).exists():
                            return name, p
                except OSError:
                    pass
        elif IS_MAC:
            app = {"chrome": "/Applications/Google Chrome.app", "msedge": "/Applications/Microsoft Edge.app"}[name]
            if Path(app).exists():
                return name, app
        else:
            p = shutil.which("google-chrome") if name == "chrome" else shutil.which("microsoft-edge")
            if p:
                return name, p
    return None


def browser_prefs() -> list[Path]:
    """Default-profile Preferences files of Chrome and Edge (used to find the download folder)."""
    if IS_WIN:
        base = Path(os.environ.get("LOCALAPPDATA", ""))
        return [base / r"Google\Chrome\User Data\Default\Preferences", base / r"Microsoft\Edge\User Data\Default\Preferences"]
    if IS_MAC:
        base = Path.home() / "Library/Application Support"
        return [base / "Google/Chrome/Default/Preferences", base / "Microsoft Edge/Default/Preferences"]
    return [Path.home() / ".config/google-chrome/Default/Preferences"]


def codex_exe() -> str | None:
    """Newest Codex binary: the desktop app's bundled CLI first (the PATH one can be stale), then PATH."""
    pats = [os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe")] if IS_WIN else \
           ["/Applications/Codex.app/Contents/Resources/codex", str(Path.home() / ".codex/bin/*/codex")]
    found = [f for p in pats for f in glob.glob(p)]
    if found:
        return max(found, key=os.path.getmtime)
    return shutil.which("codex")


def font(bold: bool = False) -> str | None:
    """A CJK-capable font for title cards, escaped for ffmpeg drawtext."""
    cands = ([r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc"] if bold else
             [r"C:\Windows\Fonts\msyh.ttc"]) if IS_WIN else \
            ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"] if IS_MAC else \
            ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    for c in cands:
        if Path(c).exists():
            return c.replace("\\", "/").replace(":", "\\:")
    return None


# ---------- ffmpeg: use the system one, else a private copy downloaded on first use ----------

# GitHub's CDN is far faster in most regions (measured 6.4 MB/s vs 0.24 MB/s); gyan.dev as fallback
FFMPEG_WIN_URLS = ["https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                   "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"]


def _private_bin(name: str) -> Path | None:
    hits = glob.glob(str(DATA / "ffmpeg" / "**" / (name + (".exe" if IS_WIN else ""))), recursive=True)
    return Path(hits[0]) if hits else None


def ffmpeg_status() -> dict:
    sys_ff, sys_fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if sys_ff and sys_fp:
        return {"ok": True, "source": "system", "ffmpeg": sys_ff}
    pf = _private_bin("ffmpeg")
    if pf and _private_bin("ffprobe"):
        return {"ok": True, "source": "private", "ffmpeg": str(pf)}
    return {"ok": False}


def install_ffmpeg() -> dict:
    """Download a static ffmpeg build into the plugin data folder (Windows). macOS/Linux: use the package manager."""
    if ffmpeg_status()["ok"]:
        return ffmpeg_status()
    if not IS_WIN:
        return {"ok": False, "error": "ffmpeg not found; install it with: brew install ffmpeg (macOS) / apt install ffmpeg"}
    target, errors = DATA / "ffmpeg", []
    for url in FFMPEG_WIN_URLS:
        try:
            with urllib.request.urlopen(url, timeout=900) as r:
                data = r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                members = [m for m in z.namelist() if m.endswith(("/bin/ffmpeg.exe", "/bin/ffprobe.exe"))]
                z.extractall(target, members)
            if ffmpeg_status()["ok"]:
                return {**ffmpeg_status(), "downloaded_mb": round(len(data) / 1e6), "from": url.split("/")[2]}
        except Exception as e:
            errors.append(f"{url.split('/')[2]}: {e}")
    return {"ok": False, "error": "; ".join(errors) or "download failed"}


def ffmpeg() -> str:
    st = ffmpeg_status()
    if not st["ok"]:
        st = install_ffmpeg()
        if not st["ok"]:
            raise FileNotFoundError(st.get("error", "ffmpeg unavailable"))
    return st["ffmpeg"]


def ffprobe() -> str:
    ff = Path(ffmpeg())
    probe = ff.with_name("ffprobe" + (".exe" if IS_WIN else ""))
    return str(probe) if probe.exists() else (shutil.which("ffprobe") or "ffprobe")
