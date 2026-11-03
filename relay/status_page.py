"""Human-readable status page served at GET / (reads /status every 3 s). No external assets."""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TAK relay</title>
<style>
:root{--bg:#f6f7f9;--fg:#1c2128;--muted:#5d6672;--card:#fff;--line:#dfe3e8;--ok:#1a7f37;--bad:#c62828;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--fg:#e6e8eb;--muted:#99a2ad;--card:#1a1f25;--line:#2c333b;--ok:#3fb950;--bad:#f85149;--warn:#d29922}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
#state{display:flex;align-items:center;gap:12px;font-size:22px;font-weight:600}
#dot{width:18px;height:18px;border-radius:50%;background:var(--muted)}
.ok #dot{background:var(--ok)}.bad #dot{background:var(--bad)}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 8px}
table{width:100%;border-collapse:collapse}td{padding:4px 0;border-top:1px solid var(--line);vertical-align:top}
td:first-child{color:var(--muted);width:45%}tr:first-child td{border-top:0}
ul{margin:6px 0 0;padding-left:20px;color:var(--bad)}.muted{color:var(--muted)}a{color:inherit}
.y{color:var(--ok)}.n{color:var(--bad)}
</style></head><body><main>
<div class="card" id="head"><div id="state"><span id="dot"></span><span id="title">Loading…</span></div><ul id="reasons"></ul></div>
<div class="card"><h2>Relay</h2><table id="info"></table></div>
<div class="card"><h2>TAK outputs</h2><table id="outputs"></table></div>
<div class="card"><h2>Traffic since start</h2><table id="traffic"></table></div>
<div class="card"><h2>Dropped</h2><table id="dropped"></table></div>
<p class="muted"><a href="/streams">Streams</a> · <a href="/status">/status JSON</a> · <a href="/metrics">/metrics</a></p>
</main><script>
function rows(id, list){const t=document.getElementById(id);t.replaceChildren();
 if(!list.length){list=[["—",""]]}
 for(const [k,v,cls] of list){const tr=t.insertRow();tr.insertCell().textContent=k;const c=tr.insertCell();c.textContent=v;if(cls)c.className=cls}}
function sum(c,prefix){let n=0;for(const k in c){if(k.startsWith(prefix))n+=c[k]}return n}
function by(c,prefix,label){const out={};for(const k in c){if(!k.startsWith(prefix))continue;
 const m=k.match(new RegExp(label+'="([^"]*)"'));const key=m?m[1]:"other";out[key]=(out[key]||0)+c[k]}return out}
async function tick(){
 let s;try{s=await (await fetch("/status",{cache:"no-store"})).json()}catch(e){
  document.getElementById("head").className="card bad";document.getElementById("title").textContent="Relay not answering";return}
 const ok=s.healthy;document.getElementById("head").className="card "+(ok?"ok":"bad");
 document.getElementById("title").textContent=ok?"Healthy":"Needs attention";
 const r=document.getElementById("reasons");r.replaceChildren();
 for(const x of s.reasons||[]){const li=document.createElement("li");li.textContent=x;r.append(li)}
 const g=s.gauges||{},c=s.counters||{};
 const age=g.gateway_last_sample_age_seconds;
 rows("info",[["Version",s.version||""],["TAK mode",s.mode||""],["Org slot",s.org||""],["System (heartbeat)",s.system||""],
  ["Fabric",g.gateway_fabric_up?"connected":"down",g.gateway_fabric_up?"y":"n"],
  ["Last backbone data",age<0?"none yet":age+" s ago"],
  ["PLI to backbone",s.ingest?("on, from "+(s.ingest_from||[]).join(", ")+(s.ingest_uids&&s.ingest_uids.length?", devices "+s.ingest_uids.join(", "):", any local device")):"off"],
  ["Uptime",Math.round((g.gateway_uptime_seconds||0)/60)+" min"]]);
 rows("outputs",(s.outputs||[]).map(o=>[o.name,(o.connected?"connected":"not connected")+(o.clients!==undefined?" · "+o.clients+" client(s)":"")+(o.queued?" · "+o.queued+" queued":""),o.connected?"y":"n"]));
 rows("traffic",[["Messages in",String(sum(c,"gateway_cot_in_total"))],["Sent to TAK",String(sum(c,"gateway_output_sent_total"))],
  ["Published to backbone (PLI)",String(c.gateway_ingest_published_total||0)]]);
 const d=Object.entries(by(c,"gateway_cot_dropped_total","reason")).map(([k,v])=>["backbone → TAK: "+k,String(v)])
  .concat(Object.entries(by(c,"gateway_ingest_dropped_total","reason")).map(([k,v])=>["TAK → backbone: "+k,String(v)]));
 rows("dropped",d)}
tick();setInterval(tick,3000);
</script></body></html>
"""
