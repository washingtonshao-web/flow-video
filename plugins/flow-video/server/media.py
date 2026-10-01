"""Local media work: collect downloads, automatic QC metrics, review strips, assembly. ffmpeg only."""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from common import browser_prefs, ffmpeg, ffprobe, font



def _run(args, check=True):
    if args and args[0] in ("ffmpeg", "ffprobe"):
        args = [ffmpeg() if args[0] == "ffmpeg" else ffprobe(), *args[1:]]
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)


def probe(path: Path) -> dict:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                "-of", "json", str(path)]).stdout
    j = json.loads(out)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    return {"duration": round(float(j["format"]["duration"]), 2), "width": v.get("width"), "height": v.get("height"),
            "audio": any(s["codec_type"] == "audio" for s in j["streams"])}


# ---------- downloads ----------

def download_dir() -> Path:
    """The browser's configured download folder (falls back to ~/Downloads)."""
    for prefs in browser_prefs():
        try:
            d = json.loads(prefs.read_text(encoding="utf-8")).get("download", {}).get("default_directory")
            if d and Path(d).exists():
                return Path(d)
        except Exception:
            pass
    return Path.home() / "Downloads"


def _slug(label: str) -> str:
    return re.sub(r"[\s]+", "_", label.replace("…", "").strip())


def collect(job: Path, items: list[dict], wait_s: int = 30) -> list[dict]:
    """items: [{shot_id, label}] -> move newest matching mp4 from the download folder to job/clips/<shot_id>.mp4."""
    src, out = download_dir(), []
    (job / "clips").mkdir(exist_ok=True)
    for it in items:
        key, dest, found = _slug(it["label"]).lower(), job / "clips" / f"{it['shot_id']}.mp4", None
        deadline = time.time() + wait_s
        while time.time() < deadline and not found:
            cands = sorted((p for p in src.glob("*.mp4") if p.name.lower().startswith(key[:40])),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            if cands and not list(src.glob("*.crdownload")):
                found = cands[0]
            else:
                time.sleep(1)
        if found:
            shutil.move(str(found), dest)
            out.append({"shot_id": it["shot_id"], "file": str(dest), **probe(dest)})
        else:
            out.append({"shot_id": it["shot_id"], "error": f"no download matching '{it['label']}' in {src}"})
    return out


# ---------- QC ----------

def metrics(clip: Path) -> dict:
    """Automatic checks, no model tokens: black frames, freezes, in-shot cuts, silence, peak level."""
    info = probe(clip)
    # scdet 10: Omni's in-clip jump cuts score ~13-27; smooth camera moves stay well below 10
    vf = "blackdetect=d=0.3:pix_th=0.10,freezedetect=n=0.003:d=1.2,scdet=threshold=10:sc_pass=0"
    log = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(clip), "-vf", vf,
                "-af", "silencedetect=n=-50dB:d=2,volumedetect", "-f", "null", "-"], check=False).stderr
    black = [float(x) for x in re.findall(r"black_duration:([\d.]+)", log)]
    freezes = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", log)]
    cuts = [round(float(x), 2) for x in re.findall(r"lavfi\.scd\.time: ([\d.]+)", log)]
    silences = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", log)]
    peak = re.search(r"max_volume: (-?[\d.]+) dB", log)
    flags = []
    if info["height"] and info["height"] < 700: flags.append("low_res")
    if not info["audio"]: flags.append("no_audio")
    if sum(black) > 0.5: flags.append("black_frames")
    if sum(freezes) > 1.5: flags.append("frozen")
    if cuts: flags.append("in_shot_cuts")
    if sum(silences) > info["duration"] * 0.6: flags.append("mostly_silent")
    if peak and float(peak.group(1)) > -0.1: flags.append("audio_clipped")
    # longest uncut segment, minus 0.15 s at each edge: a ready-made trim if the shot contains jump cuts
    bounds = [0.0, *[c for c in cuts if 0.3 < c < info["duration"] - 0.3], info["duration"]]
    a, b = max(zip(bounds, bounds[1:]), key=lambda s: s[1] - s[0])
    trim = [round(a + (0.15 if a > 0 else 0), 2), round(b - (0.15 if b < info["duration"] else 0), 2)]
    return {**info, "black_s": round(sum(black), 2), "freeze_s": round(sum(freezes), 2), "cuts_at": cuts,
            "silence_s": round(sum(silences), 2), "peak_db": float(peak.group(1)) if peak else None,
            "suggest_trim": trim if cuts else None, "flags": flags}


def strip(clip: Path, out: Path, frames: int = 4, width: int = 384) -> Path:
    d = probe(clip)["duration"]
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf",
          f"fps={frames}/{d},scale={width}:-2,tile={frames}x1", "-frames:v", "1", str(out)])
    return out


def review(job: Path, shot_ids: list[str] | None = None, frames: int = 4) -> dict:
    """Per-shot metrics + one stacked review sheet (one 4-frame strip per shot) for the agent to look at."""
    clips = sorted((job / "clips").glob("*.mp4"))
    if shot_ids:
        clips = [c for c in clips if c.stem in shot_ids]
    rdir = job / "review"
    rdir.mkdir(exist_ok=True)
    res, strips = {}, []
    for c in clips:
        res[c.stem] = metrics(c)
        strips.append(strip(c, rdir / f"{c.stem}.jpg", frames))
    sheet = rdir / "sheet.jpg"
    if strips:
        args = ["ffmpeg", "-v", "error", "-y"]
        for s in strips:
            args += ["-i", str(s)]
        args += ["-filter_complex", f"vstack=inputs={len(strips)}" if len(strips) > 1 else "null", str(sheet)]
        _run(args)
    (rdir / "metrics.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return {"sheet": str(sheet), "rows_top_to_bottom": [c.stem for c in clips], "metrics": res}


def seams(job: Path, order: list[str]) -> str:
    """Last frame of shot N beside first frame of shot N+1, one row per cut — continuity check."""
    rdir = job / "review"
    rows = []
    for a, b in zip(order, order[1:]):
        ca, cb = job / "clips" / f"{a}.mp4", job / "clips" / f"{b}.mp4"
        row = rdir / f"seam_{a}_{b}.jpg"
        _run(["ffmpeg", "-v", "error", "-y", "-sseof", "-0.1", "-i", str(ca), "-i", str(cb), "-filter_complex",
              "[0:v]scale=384:-2,trim=end_frame=1[a];[1:v]scale=384:-2,trim=end_frame=1[b];[a][b]hstack",
              "-frames:v", "1", str(row)])
        rows.append(row)
    out = rdir / "seams.jpg"
    if rows:
        args = ["ffmpeg", "-v", "error", "-y"]
        for r in rows:
            args += ["-i", str(r)]
        args += ["-filter_complex", f"vstack=inputs={len(rows)}" if len(rows) > 1 else "null", str(out)]
        _run(args)
    return str(out)


# ---------- assembly ----------

def _card(lines, dur):
    draws = ",".join(f"drawtext=" + (f"fontfile='{f}':" if f else "") + f"text='{t}':fontsize={s}:fontcolor={c}:x=(w-text_w)/2:y={y}"
                     for t, f, s, y, c in lines)
    return (f"color=c=black:s=1920x1080:r=24:d={dur},{draws},fade=t=in:st=0:d=0.5,"
            f"fade=t=out:st={dur - 0.5}:d=0.5,format=yuv420p,setsar=1")


def assemble(job: Path, order: list[str], trims: dict | None = None, transition: str = "fade",
             t_len: float = 0.25, title: str | None = None, subtitle: str | None = None,
             aspect: str = "16:9", out_name: str = "final.mp4") -> dict:
    """Trim, upscale to 1080p, join with xfade, normalise loudness (-14 LUFS, -1 dBTP), make a final sheet."""
    trims = trims or {}
    W, H = (1920, 1080) if aspect == "16:9" else (1080, 1920)
    inputs, f, durs = [], [], []
    k = 0
    if title:
        lines = [(title, font(True), 88, "(h/2)-90", "white")]
        if subtitle:
            lines.append((subtitle, font(), 36, "(h/2)+30", "0xCCCCCC"))
        f.append(_card(lines, 3.0).replace("1920x1080", f"{W}x{H}") + f"[v{k}]")
        f.append(f"anullsrc=r=48000:cl=stereo,atrim=0:3[a{k}]")
        durs.append(3.0)
        k += 1
    for i, sid in enumerate(order):
        clip = job / "clips" / f"{sid}.mp4"
        inputs += ["-i", str(clip)]
        d = probe(clip)["duration"]
        a, b = trims.get(sid, [0, d])
        b = min(b, d)
        f.append(f"[{i}:v]trim={a}:{b},setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
                 f"crop={W}:{H},unsharp=5:5:0.5,fps=24,format=yuv420p,setsar=1[v{k}]")
        # level each clip first (Omni clips differ by >10 dB and often peak at 0 dBFS), then soft-limit
        f.append(f"[{i}:a]atrim={a}:{b},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,"
                 f"loudnorm=I=-16:TP=-2:LRA=11,aresample=48000,alimiter=limit=0.8:level=false[a{k}]")
        durs.append(b - a)
        k += 1
    pv, pa, acc = "v0", "a0", durs[0]
    for j in range(1, k):
        tr = "fade" if (title and j == 1) else transition
        f.append(f"[{pv}][v{j}]xfade=transition={tr}:duration={t_len}:offset={acc - t_len:.3f}[xv{j}]")
        f.append(f"[{pa}][a{j}]acrossfade=d={t_len}[xa{j}]")
        pv, pa, acc = f"xv{j}", f"xa{j}", acc + durs[j] - t_len
    f.append(f"[{pa}]loudnorm=I=-14:TP=-1.0:LRA=11,aresample=48000[aout]")
    script = job / "review" / "filter.txt"
    script.parent.mkdir(exist_ok=True)
    script.write_text(";\n".join(f), encoding="utf-8")
    out = job / out_name
    _run(["ffmpeg", "-v", "error", "-y", *inputs, "-/filter_complex", str(script), "-map", f"[{pv}]",
          "-map", "[aout]", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    sheet = job / "review" / "final_sheet.jpg"
    n = max(4, min(24, int(acc // 3)))
    cols = 6 if n > 6 else n
    rows = -(-n // cols)
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(out), "-vf",
          f"fps={n}/{acc:.2f},scale=320:-2,tile={cols}x{rows}", "-frames:v", "1", str(sheet)])
    return {"file": str(out), "duration": round(acc, 1), "size_mb": round(out.stat().st_size / 1e6, 1),
            "sheet": str(sheet), "metrics": metrics(out)}
