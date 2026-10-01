"""JavaScript snippets the calling agent runs inside the user's signed-in Flow tab (Claude in Chrome javascript tool).

Each snippet is short, returns compact JSON, and avoids long waits (background tabs throttle timers; the
browser tool caps one call at ~45 s). Selectors rely on visible text / aria labels, not build-specific class names.
"""
import json

_H = r"""
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const vis=e=>!!(e&&e.offsetParent);
const btns=()=>[...document.querySelectorAll('button')].filter(vis);
const byAria=a=>btns().find(b=>(b.getAttribute('aria-label')||'')===a);
const byText=t=>btns().find(b=>b.innerText.replace(/\s+/g,' ').trim()===t);
const tiles=()=>[...document.querySelectorAll('flow-grid-tile-container')];
const tinfo=t=>{const s=t.innerText.replace(/\s+/g,' ').trim();const m=s.match(/(\d+)%/);
  return {label:t.getAttribute('aria-label')||'', progress:m?+m[1]:null, failed:/Failed|Unable to generate/i.test(s),
          text:s.replace(/^play_circle\s*/,'').replace(/^\d+%\s*/,'').slice(0,70)}};
"""


def _wrap(body: str) -> str:
    return "await (async()=>{" + _H + body + "})()"


def settings(duration: int = 8, aspect: str = "16:9", count: int = 1, model: str = "newest-omni") -> str:
    """Open settings, pick the newest Omni (or a named model), set duration / aspect / outputs."""
    body = f"""
const want={json.dumps(model)};
const trig=byAria('Settings trigger'); trig.click(); await sleep(700);
const vid=byText('Video')||btns().find(b=>/videocam.*Video|Video$/.test(b.innerText.trim())); if(vid) {{vid.click(); await sleep(300);}}
const frames=byText('Frames')||btns().find(b=>/Frames$/.test(b.innerText.trim())); if(frames) {{frames.click(); await sleep(300);}}
const dd=btns().find(b=>/Omni|Veo/.test(b.innerText) && b.innerText.length<40); dd.click(); await sleep(600);
const opts=[...document.querySelectorAll('[role=option],[role=menuitem],mat-option,li,button')].filter(e=>vis(e)&&/Omni|Veo/.test(e.innerText)&&e.innerText.length<40&&e!==dd);
const names=[...new Set(opts.map(o=>o.innerText.replace(/volume_up|\\s+/g,' ').trim()))];
const ver=n=>{{const m=n.match(/Omni\\s*([\\d.]+)/i);return m?m[1].split('.').map(Number):null}};
let pick;
if(want==='newest-omni'){{ pick=opts.filter(o=>ver(o.innerText)).sort((a,b)=>{{const x=ver(b.innerText),y=ver(a.innerText);for(let i=0;i<3;i++){{if((x[i]||0)!==(y[i]||0))return (x[i]||0)-(y[i]||0)}}return 0}})[0]; }}
else pick=opts.find(o=>o.innerText.includes(want));
if(pick) {{pick.click(); await sleep(500);}}
for (const t of [{json.dumps(aspect)}, '{duration}s', 'x{count}']) {{ const b=btns().find(b=>b!==trig&&b.innerText.replace(/\\s+/g,' ').trim().endsWith(t)); if(b) {{b.click(); await sleep(250);}} }}
const cost=(document.body.innerText.match(/Generating will use (\\d+) credits/)||[])[1];
document.dispatchEvent(new KeyboardEvent('keydown',{{key:'Escape',bubbles:true}})); await sleep(400);
if(btns().some(b=>b.innerText.trim()==='Frames')) {{ trig.click(); await sleep(300); }}
return JSON.stringify({{models:names, picked:pick&&pick.innerText.replace(/volume_up|\\s+/g,' ').trim(), cost_per_run:cost&&+cost, setting:byAria('Settings trigger').innerText.replace(/\\s+/g,' ')}});
"""
    return _wrap(body)


def submit(prompt: str) -> str:
    """Type the prompt into the ProseMirror box and start generation."""
    body = f"""
const pm=document.querySelector('.ProseMirror'); pm.focus(); document.execCommand('selectAll'); document.execCommand('delete');
document.execCommand('insertText', false, {json.dumps(prompt)}); await sleep(400);
const sb=byAria('Start generation'); if(!sb||sb.disabled) return JSON.stringify({{ok:false, reason:'submit disabled'}});
const n0=tiles().length; sb.click(); await sleep(2500);
return JSON.stringify({{ok:tiles().length>n0, tiles:tiles().length}});
"""
    return _wrap(body)


def status(limit: int = 12) -> str:
    """Newest tiles first: label, progress %, failed flag, prompt prefix."""
    return _wrap(f"return JSON.stringify(tiles().slice(0,{limit}).map(tinfo));")


def prep_upload() -> str:
    """Open the Start-frame picker and capture Flow's file input (no native dialog) so the agent can upload to it."""
    body = """
const start=byText('Start'); if(start){start.click(); await sleep(1200);}
const orig=HTMLInputElement.prototype.click;
HTMLInputElement.prototype.click=function(){ if(this.type==='file'){ this.style.display='block'; if(!this.isConnected) document.body.appendChild(this); window.__flowFile=this; return;} return orig.call(this); };
const up=btns().find(b=>/Upload media/.test(b.innerText)); if(up) up.click(); await sleep(700);
HTMLInputElement.prototype.click=orig;
return JSON.stringify({captured:!!window.__flowFile, next:'find the file input (type=file) and upload the keyframe to it'});
"""
    return _wrap(body)


def use_frame(filename: str, slot: str = "Start") -> str:
    """After upload finishes: pick the uploaded image in the picker and add it as the Start (or End) frame."""
    body = f"""
// newer Flow builds attach the uploaded image straight to the Start slot
const swap=byAria('Swap first and last frames'); const st=swap&&swap.previousElementSibling;
if({json.dumps(slot)}==='Start' && st && st.querySelector('img')) return JSON.stringify({{ok:true, attached:'auto'}});
const isOpen=()=>/Select a frame image/.test(document.body.innerText);
if(!isOpen()){{ const s=byText({json.dumps(slot)}); if(s){{s.click(); for(let i=0;i<10&&!isOpen();i++) await sleep(400);}} }}
const item=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&vis(e)&&e.innerText&&e.innerText.trim()==={json.dumps(filename)});
if(item){{item.click(); await sleep(600);}}
const add=byText('Add to prompt'); if(!add||add.disabled) return JSON.stringify({{ok:false, reason: item?'still uploading, retry':'file not in picker'}});
add.click(); await sleep(800);
return JSON.stringify({{ok:true}});
"""
    return _wrap(body)


def download(match: str, resolution: str = "720p") -> str:
    """Open the tile whose label or prompt contains `match`, download it, return to the grid."""
    body = f"""
const m={json.dumps(match)}.toLowerCase();
const t=tiles().find(t=>{{const i=tinfo(t);return (i.label+' '+i.text).toLowerCase().includes(m)}});
if(!t) return JSON.stringify({{ok:false, reason:'tile not found'}});
const info=tinfo(t); if(info.progress!==null||info.failed) return JSON.stringify({{ok:false, reason:'not ready', info}});
const back=location.href; t.querySelector('flow-video-tile, img').click(); await sleep(2500);
const dl=byAria('Download media')||btns().find(b=>/download/i.test(b.getAttribute('aria-label')||'')); dl.click(); await sleep(1000);
const opt=[...document.querySelectorAll('button,[role=menuitem],li,div')].filter(e=>vis(e)&&new RegExp('^\\\\s*'+{json.dumps(resolution)}).test(e.innerText||'')).sort((a,b)=>a.innerText.length-b.innerText.length)[0];
if(!opt) return JSON.stringify({{ok:false, reason:'resolution option missing'}});
opt.click(); await sleep(6000);   // leaving the editor too early cancels the download
return JSON.stringify({{ok:true, label:info.label, next:'collect, then navigate back to the project grid'}});
"""
    return _wrap(body)


_FINISH = """
const c=window.__flowSave; if(!c) return JSON.stringify({ok:false, reason:'no save in progress'});
if(!c.blob||!c.fname) return JSON.stringify({ok:false, pending:true, secs:Math.round((Date.now()-c.t0)/1000),
  next:'Flow is still preparing (1080p upscale ~1 min); call save_finish again in ~20 s'});
URL.createObjectURL=c.oc; HTMLAnchorElement.prototype.click=c.oa;
const ac=new AbortController(); setTimeout(()=>ac.abort(), 20000);
try {
  const r=await fetch('http://127.0.0.1:'+c.port+'/save?job='+encodeURIComponent(c.job)+'&name='+encodeURIComponent(c.shot+'.mp4'),
                      {method:'POST', body:c.blob, signal:ac.signal}).then(r=>r.json());
  window.__flowSave=null;
  return JSON.stringify({ok:r.ok, saved:c.shot+'.mp4', bytes:r.bytes, res:c.res, secs:Math.round((Date.now()-c.t0)/1000)});
} catch(e) {
  const a=document.createElement('a'); a.href=c.oc.call(URL,c.blob); a.download=c.fname; c.oa.call(a); window.__flowSave=null;
  return JSON.stringify({ok:false, fallback:'downloaded via browser; run collect', file:a.download});
}
"""


def save(match: str, job: str, shot_id: str, resolution: str = "1080p", port: int = 8765) -> str:
    """Open the finished tile, take Flow's own download (1080p upscale by default: free, ~1 min, sharper than a local
    upscale) and hand it to the local MCP receiver, which writes <job>/clips/<shot_id>.mp4. If the file is not ready
    within ~25 s it returns pending -> call save_finish. Falls back to 720p if 1080p is not offered, and to a normal
    browser download (then `collect`) if the local hand-off is refused. One upscale at a time (Flow's advice)."""
    body = f"""
const m={json.dumps(match)}.toLowerCase();
if(window.__flowSave) return JSON.stringify({{ok:false, reason:'another save in progress: call save_finish first'}});
if(location.pathname.includes('/edit/')){{ history.back(); await sleep(2500); }}
const t=tiles().find(t=>{{const i=tinfo(t);return (i.label+' '+i.text).toLowerCase().includes(m)}});
if(!t) return JSON.stringify({{ok:false, reason:'tile not found'}});
const info=tinfo(t); if(info.progress!==null||info.failed) return JSON.stringify({{ok:false, reason:'not ready', info}});
t.querySelector('flow-video-tile, img').click(); await sleep(2500);
const c=window.__flowSave={{blob:null, fname:null, t0:Date.now(), job:{json.dumps(job)}, shot:{json.dumps(shot_id)}, port:{port},
  oc:URL.createObjectURL, oa:HTMLAnchorElement.prototype.click}};
URL.createObjectURL=function(o){{ if(o instanceof Blob) c.blob=o; return c.oc.call(URL,o); }};
HTMLAnchorElement.prototype.click=function(){{ if(this.download){{c.fname=this.download; return;}} return c.oa.call(this); }};
const dl=byAria('Download media')||btns().find(b=>/download/i.test(b.getAttribute('aria-label')||'')); dl.click(); await sleep(900);
const pickRes=r=>[...document.querySelectorAll('button,[role=menuitem],li,div')].filter(e=>vis(e)&&new RegExp('^\\\\s*'+r).test(e.innerText||'')).sort((a,b)=>a.innerText.length-b.innerText.length)[0];
let opt=pickRes({json.dumps(resolution)}); c.res={json.dumps(resolution)};
if(!opt){{ opt=pickRes('720p'); c.res='720p'; }}
if(!opt){{ URL.createObjectURL=c.oc; HTMLAnchorElement.prototype.click=c.oa; window.__flowSave=null; return JSON.stringify({{ok:false, reason:'no download option'}}); }}
opt.click(); for(let i=0;i<36&&!c.fname;i++) await sleep(500);
""" + "return await (async()=>{" + _FINISH + "})();"
    return _wrap(body)


def save_finish() -> str:
    """Second half of `save` when it returned pending."""
    return _wrap(_FINISH)


def whoami() -> str:
    """Run on flow.google.com: is this browser signed in to Flow, and as whom (masked)."""
    return _wrap(r"""await sleep(1500);
const a=document.querySelector("[aria-label^='Google Account']"); const lab=a?a.getAttribute('aria-label'):'';
const mail=(lab.match(/\(([^)]+)\)/)||[])[1]||''; const masked=mail?mail.replace(/^(.).*(@.*)$/,'$1***$2'):'';
return JSON.stringify({signed_in:!!a && !location.pathname.startsWith('/about'), account:masked, plan:/membership|PRO|ULTRA/i.test(document.body.innerText)?'AI plan':null, url:location.pathname});""")


def credits() -> str:
    """Run on https://one.google.com/ai/activity : Flow credit balance."""
    return _wrap(r"""const s=document.body.innerText; const m=s.match(/Google Flow credits\s*([\d,]+)/);
return JSON.stringify({flow_credits:m?+m[1].replace(/,/g,''):null, daily:(s.match(/(\d+) daily Flow credits remaining/)||[])[1]||null});""")


ACTIONS = {"settings": settings, "submit": submit, "status": status, "prep_upload": prep_upload,
           "use_frame": use_frame, "download": download, "save": save, "save_finish": save_finish,
           "credits": credits, "whoami": whoami}
