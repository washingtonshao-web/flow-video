"""Flow Video MCP server (stdio, Python standard library only). Started on demand by the MCP client; exits with it.

Division of labour:
  - the calling model writes the storyboard, judges review sheets and decides retries;
  - keyframes come from ChatGPT image generation (Codex CLI);
  - video is generated in Google Flow inside the user's signed-in Chrome (Claude in Chrome tab) with the
    snippets returned by `flow_js` — subscription credits only;
  - this server handles job folders, downloads, automatic QC, review sheets and assembly.
"""
import json
import re
import secrets
import sys
import time
import traceback
from pathlib import Path

import flow_js
import keyframe
import media
import common
from common import STATE

PLAYBOOK = """Flow Video — one sentence to a finished video, using Google Flow subscription credits (never paid API unless the user approves).

Workflow (you are the director; keep images small, never take full-page screenshots):
0. First use on a machine: run doctor(); follow its next_steps. In the Flow tab run flow_js('whoami').
1. Write the storyboard yourself: style bible (look, palette, lens, light, character/location descriptions repeated verbatim)
   + 6-8 shots, each one main action that fits 8 s, explicit camera/subject/light, no on-screen text. Check total length.
   Prompt rules learned from real runs:
   - end every prompt with "one continuous single take, no cuts" (Omni otherwise often cuts at ~3 s and ~6 s);
   - real places with signage/banners: frame wide or keep signs soft/out of focus — legible text comes out garbled;
   - recurring subjects (aircraft, characters, vehicles): one fixed descriptor sentence, plus a keyframe per shot —
     text-only shots drift (same prompt gave a different boat; jets changed shape between shots);
   - state scale/position ("two jets high above the towers") — otherwise objects clip through buildings.
2. job_create(title, shots) — the job folder goes into the current conversation's working folder.
3. Optional keyframes: keyframe(job, shot_id, prompt) per shot -> look at them together; regenerate only the weak ones.
4. In the user's Flow tab (Claude in Chrome, existing signed-in Chrome): run flow_js('settings') once (picks the newest Omni,
   duration/aspect/outputs). For credits: open
   https://one.google.com/ai/activity?utm_source=flow&utm_medium=web&utm_campaign=flow_ai_credits_page&g1_landing_page=0
   and run flow_js('credits'); stop if not enough (8 s Omni = 12 credits; failed generations are refunded).
   For each shot: if keyframe -> flow_js('prep_upload'), upload the PNG to the captured file input, flow_js('use_frame', filename);
   then flow_js('submit', prompt). Submit all shots, then poll flow_js('status') every ~20 s with short calls
   (each browser JS call must finish in <40 s). If progress stops moving for >60 s, reload the tab (hidden tabs stall).
   Failed tiles: click its refresh once; content refusals: report, do not try to sneak past.
5. flow_js('save', match=<label or prompt prefix>, job, shot_id) per finished tile -> Flow upscales to 1080p (free, ~1 min,
   sharper than a local upscale) and the clip lands in job/clips directly. If it returns pending, call
   flow_js('save_finish') every ~20 s. One save at a time. If it returns a fallback, run collect(job, [{shot_id,label}]).
6. review(job) -> look at review/sheet.jpg (one 4-frame strip per shot, top to bottom) + metrics flags. Score each shot 1-5 on:
   prompt match, deformation / objects clipping through scenery, garbled text or signage, subject identity vs keyframe and
   neighbours, natural motion. Any score <=2 -> retry with a sharper prompt (max 2 retries, keep the best take).
   Flags: in_shot_cuts -> use metrics.suggest_trim (longest clean segment) or retry if that leaves <4 s;
   audio_clipped / level differences are fixed automatically in assemble; black_frames / frozen -> retry.
7. seams(job, order) -> check last/first frame pairs for direction, light, time of day. Set trims to drop weak heads/tails.
8. assemble(job, order, trims) -> look at review/final_sheet.jpg; one revision round if needed. Report file path.
Defaults: Omni (newest), 720p, 8 s, 16:9, 1080p output, no title card or watermark, fully automatic.
Paid API channel: api_quote then api_generate only with the user's explicit approval in chat."""


def _job(p: str) -> Path:
    j = Path(p)
    if not (j / "job.json").exists():
        raise ValueError(f"not a job folder: {p}")
    return j


def job_create(title: str, shots: list, output_dir: str | None = None, aspect: str = "16:9", style: str = "") -> dict:
    """output_dir defaults to the client's working folder (the current conversation's project folder)."""
    import os
    safe = re.sub(r'[\\/:*?"<>|]+', "_", title).strip()[:60] or "video"
    job = Path(output_dir or os.getcwd()) / f"{time.strftime('%y%m%d_%H%M')}_{safe}"
    for d in ("clips", "keyframes", "review"):
        (job / d).mkdir(parents=True, exist_ok=True)
    meta = {"title": title, "aspect": aspect, "style": style, "created": time.strftime("%Y-%m-%d %H:%M"), "shots": shots}
    (job / "job.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (job / "shots.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"job": str(job), "shots": len(shots)}


def doctor(fix: bool = True) -> dict:
    """Self-check with plain-language next steps (Chinese + English)."""
    import platform
    import shutil
    import socket
    checks, steps = {}, []
    checks["python"] = platform.python_version()
    if sys.version_info < (3, 10):
        steps.append("Python 版本太旧，请安装 Python 3.10 以上 / install Python 3.10+")
    st = common.ffmpeg_status()
    if not st["ok"] and fix:
        try:
            st = common.install_ffmpeg()
        except Exception as e:
            st = {"ok": False, "error": str(e)}
    checks["ffmpeg"] = st
    if not st["ok"]:
        steps.append("ffmpeg 没装好：" + st.get("error", "自动下载失败，请检查网络后再运行 doctor"))
    b = common.browser_exe("auto")
    checks["browser"] = b[0] if b else None
    if not b:
        steps.append("没找到 Chrome 或 Edge，请先安装 Chrome / install Google Chrome")
    cx = common.codex_exe()
    checks["chatgpt_keyframes"] = bool(cx)
    if not cx:
        steps.append("（可选）关键帧要用 ChatGPT 出图：安装 Codex 桌面版并用 ChatGPT 账号登录；不装也能出片，只是没有关键帧")
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=1):
            checks["receiver"] = "listening"
    except OSError:
        checks["receiver"] = "not listening (restart Claude so the plugin server starts)"
        steps.append("本机接收端没启动：重启 Claude 后再试")
    checks["data_dir"] = str(common.DATA)
    steps += ["在 Chrome 里装好 Claude 扩展并登录；打开 flow.google.com 确认已登录有 AI 套餐的 Google 账号",
              "第一次保存视频时 Chrome 会问“访问本地网络”，点“允许”（只需一次）"]
    return {"ok": all(x for x in [st["ok"], b]), "checks": checks, "next_steps": steps}


def api_quote(job: str, seconds: float, model: str = "newest-omni") -> dict:
    rate = 0.10                                   # USD/s, Omni 720p list price at time of writing; verify before use
    code = secrets.token_hex(3)
    q = {"code": code, "job": job, "seconds": seconds, "model": model, "usd_estimate": round(seconds * rate * 1.3, 2),
         "created": time.time()}
    f = STATE / "quotes.json"
    allq = json.loads(f.read_text()) if f.exists() else {}
    allq[code] = q
    f.write_text(json.dumps(allq, indent=1))
    return {**q, "note": "Ask the user in chat; call api_generate with this code only after they approve."}


def api_generate(code: str, user_approved: bool) -> dict:
    import os
    f = STATE / "quotes.json"
    q = (json.loads(f.read_text()) if f.exists() else {}).get(code)
    if not q or not user_approved:
        return {"ok": False, "error": "needs a valid quote code and the user's explicit approval"}
    if not os.environ.get("GEMINI_API_KEY"):
        return {"ok": False, "error": "API channel not configured (no GEMINI_API_KEY); use the Flow subscription channel"}
    return {"ok": False, "error": "API channel not implemented yet"}


TOOLS = {
    "doctor": (doctor, "Self-check (Python, ffmpeg auto-install, browser, ChatGPT/Codex, local receiver) with next steps.",
               {"fix": "boolean?"}),
    "job_create": (job_create, "Create a job folder in the current conversation's working folder (or output_dir).",
                   {"title": "string", "shots": "array", "output_dir": "string?", "aspect": "string?", "style": "string?"}),
    "flow_js": (lambda action, **kw: {"js": flow_js.ACTIONS[action](**kw)},
                "Return a JavaScript snippet to run in the user's Flow tab with the browser javascript tool. "
                "action: settings(duration,aspect,count,model) | submit(prompt) | status(limit) | prep_upload() | "
                "use_frame(filename,slot) | save(match,job,shot_id,resolution='1080p') [Flow's free 1080p upscale straight "
                "into job/clips; may return pending] | save_finish() | "
                "download(match,resolution) [browser download + collect] | credits() [on one.google.com/ai/activity].",
                {"action": "string", "duration": "integer?", "aspect": "string?", "count": "integer?", "model": "string?",
                 "prompt": "string?", "limit": "integer?", "filename": "string?", "slot": "string?",
                 "match": "string?", "resolution": "string?", "job": "string?", "shot_id": "string?"}),
    "keyframe": (lambda job, shot_id, prompt, aspect="16:9", ref_image=None:
                 keyframe.generate(_job(job), shot_id, prompt, aspect, ref_image),
                 "Generate a keyframe PNG with ChatGPT image generation (Codex). ~1 min each.",
                 {"job": "string", "shot_id": "string", "prompt": "string", "aspect": "string?", "ref_image": "string?"}),
    "collect": (lambda job, items, wait_s=30: {"clips": media.collect(_job(job), items, wait_s)},
                "Move downloaded Flow clips from the browser download folder into job/clips/<shot_id>.mp4.",
                {"job": "string", "items": "array", "wait_s": "integer?"}),
    "review": (lambda job, shot_ids=None, frames=4: media.review(_job(job), shot_ids, frames),
               "Automatic QC metrics + one review sheet (a frame strip per shot). Look at the sheet, then score.",
               {"job": "string", "shot_ids": "array?", "frames": "integer?"}),
    "seams": (lambda job, order: {"sheet": media.seams(_job(job), order)},
              "Continuity sheet: last frame of each shot beside the first frame of the next.",
              {"job": "string", "order": "array"}),
    "assemble": (lambda job, order, trims=None, transition="fade", title=None, subtitle=None, out_name="final.mp4":
                 media.assemble(_job(job), order, trims, transition, 0.25, title, subtitle,
                                json.loads((_job(job) / "job.json").read_text(encoding="utf-8")).get("aspect", "16:9"),
                                out_name),
                 "Trim, upscale to 1080p, join (transition: fade|fadewhite|fadeblack|dissolve), loudness -14 LUFS, final sheet.",
                 {"job": "string", "order": "array", "trims": "object?", "transition": "string?", "title": "string?",
                  "subtitle": "string?", "out_name": "string?"}),
    "api_quote": (api_quote, "Paid Gemini API channel, step 1: cost estimate + approval code. Requires user approval.",
                  {"job": "string", "seconds": "number", "model": "string?"}),
    "api_generate": (api_generate, "Paid Gemini API channel, step 2: only with a quote code the user approved in chat.",
                     {"code": "string", "user_approved": "boolean"}),
}

_T = {"string": "string", "integer": "integer", "number": "number", "array": "array", "object": "object", "boolean": "boolean"}


def _schema(params: dict) -> dict:
    props, req = {}, []
    for k, t in params.items():
        opt = t.endswith("?")
        props[k] = {"type": _T[t.rstrip("?")]}
        if not opt:
            req.append(k)
    return {"type": "object", "properties": props, "required": req}


def _version() -> str:
    try:
        return json.loads((Path(__file__).parent.parent / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    except Exception:
        return "dev"


def handle(msg: dict):
    m, mid = msg.get("method"), msg.get("id")
    if m == "initialize":
        return {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "flow-video", "version": _version()},
                "instructions": PLAYBOOK}
    if m == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": _schema(p)} for n, (_, d, p) in TOOLS.items()]}
    if m == "tools/call":
        name, args = msg["params"]["name"], msg["params"].get("arguments", {}) or {}
        try:
            out = TOOLS[name][0](**args)
            return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}"}],
                    "isError": True}
    if m == "ping":
        return {}
    if mid is not None:
        raise KeyError(m)
    return None


def main():
    # MCP is UTF-8 JSON; Windows would otherwise decode stdin with the ANSI code page and garble Chinese
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    import receiver
    receiver.ensure_running()
    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        try:
            res = handle(msg)
            if msg.get("id") is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}), flush=True)
        except Exception as e:
            if msg.get("id") is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                  "error": {"code": -32601, "message": str(e)}}), flush=True)


if __name__ == "__main__":
    main()
