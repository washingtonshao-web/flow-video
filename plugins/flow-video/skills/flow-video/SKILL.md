---
name: flow-video
description: Make a video from one sentence with Google Flow (Omni) on the user's own Google AI subscription — storyboard, keyframes, generation in the user's signed-in Chrome, QC, 1080p assembly. Use when the user asks to make/generate/produce a video, clip, short film, ad or animation, or mentions Flow, Omni or 做视频/出片.
---

# Flow Video

Tools come from the `flow-video` MCP server; Flow is driven in the user's existing signed-in Chrome through the Claude in Chrome browser tools (javascript tool + file upload). Subscription credits only — the paid API channel is used only after the user approves a quote in chat.

## First use on a machine
1. `doctor()` — fixes ffmpeg automatically; relay any `next_steps` to the user in plain words.
2. Open `https://flow.google.com/` in the browser tool, run `flow_js('whoami')`. Not signed in → ask the user to sign in to Flow in Chrome once.
3. The first `save` makes Chrome ask “allow access to local network” → tell the user to click **Allow** once.

## Workflow
1. **Storyboard (you):** style bible (look, palette, lens, light; recurring subjects as one fixed sentence repeated verbatim) + shots that each fit 8 s with one main action, explicit camera, subject position/scale and light.
   End every prompt with “one continuous single take, no cuts”. Keep signage/text wide or out of focus. No on-screen text.
2. `job_create(title, shots)` — the folder is created in the current working folder.
3. **Keyframes:** `keyframe(job, shot_id, prompt)` per shot (ChatGPT via Codex; ~1 min each). Review them together; redo only weak ones. No Codex → skip keyframes.
4. **Credits:** open the Flow credits page and run `flow_js('credits')`; 8 s Omni = 12 credits. Not enough → stop and tell the user.
5. **Generate** in a Flow project tab: `flow_js('settings')` once (newest Omni, 8 s, 16:9). Per shot: with keyframe → `flow_js('prep_upload')`, upload the PNG to the captured `type=file` input, `flow_js('use_frame', filename=…)`; then `flow_js('submit', prompt=…)`.
   Poll `flow_js('status')` every ~20 s (every browser JS call must finish in < 40 s). Progress frozen > 60 s → reload the tab. Failed tile → its refresh button once. Content refusals → report; never try to slip past them.
6. **Save:** `flow_js('save', match=<label or prompt prefix>, job=…, shot_id=…)` — Flow's free 1080p upscale goes straight into `job/clips`. `pending` → `flow_js('save_finish')` every ~20 s. One save at a time. `fallback` → `collect(job, items)`.
7. **Review:** `review(job)` → look at `review/sheet.jpg` + flags. Score each shot 1–5: prompt match, deformation/clipping through scenery, garbled text, subject identity vs keyframe/neighbours, motion. ≤ 2 → retry with a sharper prompt (max 2 retries, keep the best). `in_shot_cuts` → use `suggest_trim` or retry.
8. **Continuity:** `seams(job, order)`; set trims to drop weak heads/tails.
9. **Assemble:** `assemble(job, order, trims)` → check `review/final_sheet.jpg`; one revision round if needed. Report the file path and credits used.

Defaults: newest Omni, 8 s, 16:9 (9:16 on request), Flow 1080p, no title card or watermark, fully automatic.
