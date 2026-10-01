"""Keyframes via ChatGPT image generation (Codex desktop CLI, ChatGPT subscription — no API spend).

No model is pinned: Codex uses its own configured default (the newest it ships with).
Set VIDEO_MCP_GPT_MODEL to force one.
"""
import os
import re
import subprocess
from pathlib import Path

from common import codex_exe


def generate(job: Path, shot_id: str, prompt: str, aspect: str = "16:9", ref_image: str | None = None) -> dict:
    exe = codex_exe()
    if not exe:
        return {"ok": False, "error": "Codex CLI not found"}
    kdir = job / "keyframes"
    kdir.mkdir(exist_ok=True)
    target = kdir / f"{shot_id}.png"
    n = 2
    while target.exists():                       # never overwrite
        target = kdir / f"{shot_id}_v{n}.png"
        n += 1
    orient = "16:9 landscape" if aspect == "16:9" else "9:16 portrait"
    ask = (f"Use built-in image_gen at the largest size and highest quality available: {prompt} "
           f"Aspect ratio {orient}. Cinematic film still, no text, no watermark. "
           f"Copy the PNG to {target.as_posix()}; reply only with the path and pixel size.")
    cmd = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "workspace-write",
           "-C", str(job), "--add-dir", str(kdir)]
    if os.environ.get("VIDEO_MCP_GPT_MODEL"):
        cmd += ["-m", os.environ["VIDEO_MCP_GPT_MODEL"]]
    if ref_image:
        cmd += ["-i", ref_image]
    cmd.append(ask)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL, timeout=900)
    tokens = re.search(r"tokens used\s*\n?\s*([\d,]+)", p.stdout + p.stderr)
    if not target.exists():
        return {"ok": False, "error": (p.stdout + p.stderr)[-800:]}
    return {"ok": True, "file": str(target), "gpt_tokens": int(tokens.group(1).replace(",", "")) if tokens else None}
