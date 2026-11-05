"""Live picture of what flows on the backbone: who publishes what, how fast, in which format.

StreamStats is fed one call per sample (record) and produces a snapshot for the /streams page.
Pure Python, no I/O; bounded memory (groups are capped and idle groups are dropped).
"""
import collections
import threading
import time

MAX_GROUPS = 600
IDLE_DROP_S = 900
RATE_WINDOW_S = 10.0


def group_of(key: str) -> str:
    """Group keys per publisher and topic: org/system/topic (4 segments for release/ and ops/ namespaces)."""
    parts = key.split("/")
    n = 4 if parts[0] in ("release", "ops") else 3
    return "/".join(parts[:n]) if len(parts) > n else key


def kind_of(head: bytes, hint: str = "") -> str:
    if hint:
        return hint
    if not head:
        return "?"
    b0 = head[:1]
    if head[:3] == bytes([0xFF, 0xD8, 0xFF]):
        return "jpeg"
    if head[:4] == bytes([0x89, 0x50, 0x4E, 0x47]):
        return "png"
    if b0 == b"<":
        return "xml"
    if b0 in (b"{", b"["):
        return "json"
    if head[:5] == b"EFDIS":
        return "encrypted"
    if b0 == bytes([0x47]):
        return "video-ts"
    if b0 == bytes([0x0A]):
        return "protobuf?"
    return "binary"


class StreamStats:
    def __init__(self, own_org: str):
        self.own_org = own_org
        self.lock = threading.Lock()
        self.g = {}
        self.started = time.time()

    def record(self, key: str, size: int, head: bytes = b"", tak_sources=(), hint: str = "", now=None, payload=None):
        now = time.time() if now is None else now
        name = group_of(key)
        with self.lock:
            d = self.g.get(name)
            if d is None:
                if len(self.g) >= MAX_GROUPS:
                    return
                d = self.g[name] = {"n": 0, "bytes": 0, "first": now, "recent": collections.deque(maxlen=2000),
                                    "kind": "?", "tak": collections.Counter(), "sample": "", "last_key": key}
            d["n"] += 1
            d["bytes"] += size
            d["last"] = now
            d["last_key"] = key
            d["recent"].append((now, size))
            if payload is not None and size <= 200_000:
                d["payload"] = payload
                if hint == "video/binary" or head[:1] == bytes([0x47]):
                    d.setdefault("ring", collections.deque(maxlen=4000)).append(payload)
            if head:
                d["kind"] = kind_of(head, hint)
                if d["kind"] in ("json", "xml") and (not d["sample"] or d["n"] % 50 == 1):
                    d["sample"] = head[:240].decode("utf-8", "replace")
            elif hint:
                d["kind"] = hint
            for s in tak_sources:
                d["tak"][s] += 1

    def sample(self, group: str):
        """(last payload bytes, kind) for a group, or (None, None)."""
        with self.lock:
            d = self.g.get(group)
            return (d.get("payload"), d["kind"]) if d else (None, None)

    def video(self, group: str):
        """Concatenated recent packets of a video group (MPEG-TS), or None."""
        with self.lock:
            d = self.g.get(group)
            return b"".join(d["ring"]) if d and d.get("ring") else None

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        rows = []
        with self.lock:
            for name in [k for k, d in self.g.items() if now - d["last"] > IDLE_DROP_S]:
                del self.g[name]
            for name, d in self.g.items():
                recent = [(t, s) for t, s in d["recent"] if now - t <= RATE_WINDOW_S]
                span = max(1.0, min(RATE_WINDOW_S, now - d["first"]))
                parts = name.split("/")
                org = parts[0] if parts[0] not in ("release", "ops") else "/".join(parts[:2])
                rows.append({
                    "group": name, "org": org, "own": name.startswith(self.own_org),
                    "topic": "/".join(parts[1:]) if len(parts) > 1 else name,
                    "kind": d["kind"], "total": d["n"],
                    "msg_per_s": round(len(recent) / span, 2),
                    "kb_per_s": round(sum(s for _, s in recent) / span / 1024, 1),
                    "age_s": round(now - d["last"], 1),
                    "last_bytes": recent[-1][1] if recent else 0,
                    "tak": dict(d["tak"]), "sample": d["sample"], "last_key": d["last_key"],
                })
        rows.sort(key=lambda r: (-r["msg_per_s"], r["group"]))
        return {"uptime_s": int(now - self.started), "groups": len(rows), "streams": rows}


def extract_image(payload: bytes):
    """A displayable JPEG/PNG from a sample: the payload itself, or a base64 image inside a JSON message."""
    import base64
    import json
    if payload[:3] == bytes([0xFF, 0xD8, 0xFF]) or payload[:4] == bytes([0x89, 0x50, 0x4E, 0x47]):
        return payload
    if payload[:1] == b"{":
        try:
            j = json.loads(payload)
        except ValueError:
            return None
        stack = [j]
        while stack:  # look for a large base64 string that decodes to an image (keyframe, jpeg_b64, image_b64, ...)
            cur = stack.pop()
            for v in (cur.values() if isinstance(cur, dict) else cur if isinstance(cur, list) else []):
                if isinstance(v, str) and len(v) > 500:
                    try:
                        raw = base64.b64decode(v, validate=False)
                    except Exception:  # noqa: BLE001
                        continue
                    if raw[:3] == bytes([0xFF, 0xD8, 0xFF]) or raw[:4] == bytes([0x89, 0x50, 0x4E, 0x47]):
                        return raw
                elif isinstance(v, (dict, list)):
                    stack.append(v)
    return None


def video_frame_jpeg(ts_bytes: bytes):
    """Last decodable frame of an MPEG-TS buffer as JPEG (needs PyAV), or None. May show damage on lossy streams."""
    try:
        import io
        import av
        c = av.open(io.BytesIO(ts_bytes), format="mpegts")
        last = None
        for pkt in c.demux(c.streams.video[0]):
            if pkt.size == 0:
                continue
            try:
                for f in pkt.decode():
                    last = f
            except av.error.FFmpegError:
                continue
        if last is None:
            return None
        out = io.BytesIO()
        last.to_image().save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Backbone streams</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1419;--fg:#e6edf3;--mut:#8b98a5;--line:#232d38;--own:#2ea043;--tak:#d29922;--old:#6e7681}
@media (prefers-color-scheme: light){:root{--bg:#fff;--fg:#1f2328;--mut:#59636e;--line:#d1d9e0;--own:#1a7f37;--tak:#9a6700;--old:#8c959f}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;gap:16px;flex-wrap:wrap;align-items:center}
h1{font-size:16px;margin:0}.mut{color:var(--mut)}input,select{background:transparent;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px 8px}
table{width:100%;border-collapse:collapse}th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{position:sticky;top:0;background:var(--bg);font-size:12px;color:var(--mut);cursor:pointer;white-space:nowrap}
td.num{text-align:right;font-variant-numeric:tabular-nums}.own{color:var(--own);font-weight:600}.tak{color:var(--tak)}.stale{color:var(--old)}
code{font-size:12px;word-break:break-all}.sample{color:var(--mut);font-size:12px;max-width:520px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#pv{position:fixed;inset:0;background:rgba(0,0,0,.8);display:none;align-items:center;justify-content:center;z-index:9;flex-direction:column;gap:8px}
#pv img{max-width:92vw;max-height:84vh;border:1px solid var(--line)}#pv span{color:#fff;font-size:13px}
tr.row{cursor:pointer}tr.row:hover{background:rgba(127,127,127,.12)}
.badge{border:1px solid var(--line);border-radius:10px;padding:0 7px;font-size:12px}
@media (max-width:700px){.hide-s{display:none}}
</style></head><body>
<header><h1>Backbone streams</h1><span class="mut" id="sum">loading…</span>
<input id="q" placeholder="filter (org, topic, format)…" size="28">
<label class="mut"><input type="checkbox" id="own"> ours only</label>
<label class="mut"><input type="checkbox" id="tak"> reaching TAK only</label>
<label class="mut"><input type="checkbox" id="live" checked> active (last 60 s) only</label></header>
<div id="pv" onclick="this.style.display='none'"><span id="pvt"></span><img id="pvi" alt="preview"></div>
<table><thead><tr>
<th data-k="org">Source</th><th data-k="topic">Topic</th><th data-k="kind">Format</th>
<th data-k="msg_per_s">msg/s</th><th data-k="kb_per_s">KB/s</th><th data-k="age_s">age s</th>
<th data-k="tak">→ TAK</th><th class="hide-s">Sample</th></tr></thead><tbody id="rows"></tbody></table>
<script>
let data=[],sortK="msg_per_s",desc=true;
const $=id=>document.getElementById(id);
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function render(){
  const q=$("q").value.toLowerCase();
  let r=data.filter(x=>(!$("own").checked||x.own)&&(!$("tak").checked||Object.keys(x.tak).length)&&(!$("live").checked||x.age_s<=60)
    &&(!q||(x.org+" "+x.topic+" "+x.kind).toLowerCase().includes(q)));
  r.sort((a,b)=>{let A=a[sortK],B=b[sortK];if(sortK==="tak"){A=Object.values(a.tak).reduce((s,v)=>s+v,0);B=Object.values(b.tak).reduce((s,v)=>s+v,0)}
    return (A<B?-1:A>B?1:0)*(desc?-1:1)});
  $("rows").innerHTML=r.map(x=>{const t=Object.entries(x.tak).map(([k,v])=>k+" "+v).join(", ");
    return `<tr class="row ${x.age_s>60?'stale':''}" data-g="${esc(x.group)}" data-k="${esc(x.kind)}"><td><code class="${x.own?'own':''}">${esc(x.org.slice(0,12))}${x.own?' (us)':''}</code></td>
    <td><code>${esc(x.topic)}</code></td><td><span class="badge">${esc(x.kind)}</span></td>
    <td class="num">${x.msg_per_s}</td><td class="num">${x.kb_per_s}</td><td class="num">${x.age_s}</td>
    <td class="tak">${esc(t)}</td><td class="hide-s"><div class="sample">${esc(x.sample)}</div></td></tr>`}).join("");
}
async function tick(){
  try{const j=await (await fetch("/api/streams")).json();data=j.streams;
    $("sum").textContent=j.groups+" streams · up "+j.uptime_s+" s · updated "+new Date().toLocaleTimeString();render()}
  catch(e){$("sum").textContent="gateway unreachable"}
}
$("rows").addEventListener("click",e=>{const tr=e.target.closest("tr.row");if(!tr)return;
  const g=tr.dataset.g,k=tr.dataset.k;if(!["jpeg","png","json","video/binary","video-ts"].includes(k))return;
  const img=$("pvi");$("pvt").textContent=g+" ("+k+") - click to close";
  img.onerror=()=>{$("pvt").textContent=g+": no image in this stream"};img.src="/api/preview?g="+encodeURIComponent(g)+"&t="+Date.now();$("pv").style.display="flex"});
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{const k=th.dataset.k;desc=(k===sortK)?!desc:true;sortK=k;render()});
["q","own","tak","live"].forEach(i=>$(i).addEventListener("input",render));
tick();setInterval(tick,2000);
</script></body></html>
"""
