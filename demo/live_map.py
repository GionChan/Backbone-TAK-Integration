#!/usr/bin/env python3
"""Demo viewer: live tactical map (Leaflet.js) of exercise and sensor tracks.

Subscribes <org>/exercise/** and <org>/sensor/v1/**. The /control panel injects tracks by
hand or from a CSV (e.g. demo/scenarios/mass_raid.csv) through demo/sender.py,
so injected tracks are exercise-labelled and reach TAK through the relay.

Env:   GOAT_MAP_PORT  HTTP port (default 8080); identity/router: see relay/goat_connect.py
Run:   python demo/live_map.py      Open: http://localhost:8080  (control: /control)
"""

import json
import os
import queue
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sender  # noqa: E402
from sender import gc as _gc  # noqa: E402

_PORT = int(os.environ.get("GOAT_MAP_PORT", "8080"))

_clients: list[queue.Queue] = []
_lock = threading.Lock()
_zen_session = None
_sender = None


def _netbird_ip():
    try:
        import subprocess
        out = subprocess.check_output(["ifconfig"], text=True, stderr=subprocess.DEVNULL)
        for line in out.split("\n"):
            if "inet 100.64." in line:
                return line.strip().split()[1]
    except Exception:
        pass
    return None


_SHARE_URL = f"http://{_netbird_ip() or 'localhost'}:{_PORT}"

_HTML_SRC = """<!DOCTYPE html>
<html lang="fi"><head>
  <meta charset="utf-8">
  <title>EFDI Tactical Display</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Segoe UI',monospace;background:#0d1117;color:#e6edf3;display:flex;flex-direction:column;height:100vh;overflow:hidden}

    /* TOP BAR */
    #topbar{
      height:48px;display:flex;align-items:center;padding:0 16px;gap:12px;
      background:#161b22;border-bottom:1px solid #30363d;flex-shrink:0;
    }
    #topbar .logo{font-weight:800;font-size:15px;letter-spacing:2px;color:#f85149}
    #topbar .badge{
      background:#21262d;border:1px solid #30363d;border-radius:4px;
      padding:2px 10px;font-size:12px;color:#8b949e
    }
    #topbar .badge span{color:#e6edf3;font-weight:700}
    #conn-dot{width:8px;height:8px;border-radius:50%;background:#3fb950;margin-left:auto;flex-shrink:0}
    #conn-dot.dead{background:#f85149;animation:none}
    #conn-label{font-size:11px;color:#8b949e}
    .pulse{animation:pulse 1.4s infinite}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

    /* MAIN LAYOUT */
    #main{display:flex;flex:1;overflow:hidden}

    /* SIDEBAR */
    #sidebar{
      width:260px;flex-shrink:0;background:#161b22;border-right:1px solid #30363d;
      display:flex;flex-direction:column;overflow:hidden
    }
    #sidebar-header{
      padding:10px 12px;font-size:11px;font-weight:700;letter-spacing:1px;
      color:#8b949e;border-bottom:1px solid #30363d;display:flex;justify-content:space-between;align-items:center
    }
    #threat-list{flex:1;overflow-y:auto;padding:8px}
    .threat-card{
      background:#21262d;border:1px solid #30363d;border-radius:6px;
      padding:10px 12px;margin-bottom:8px;cursor:pointer;transition:border-color .15s,background .15s
    }
    .threat-card:hover{background:#2d333b;border-color:#58a6ff}
    .threat-card.selected{border-color:#f0883e;background:#2d1f12}
    .threat-card.ingress{border-left:3px solid #f85149}
    .threat-card.orbit{border-left:3px solid #e3b341}
    .tc-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
    .tc-id{font-weight:700;font-size:13px}
    .tc-phase{font-size:10px;font-weight:700;letter-spacing:1px;padding:2px 6px;border-radius:3px}
    .phase-ingress{background:#3d1515;color:#f85149}
    .phase-orbit{background:#2d2208;color:#e3b341}
    .tc-row{font-size:11px;color:#8b949e;line-height:1.7}
    .tc-row span{color:#e6edf3}

    /* EVENT LOG */
    #log-section{border-top:1px solid #30363d;height:180px;display:flex;flex-direction:column}
    #log-header{padding:8px 12px;font-size:11px;font-weight:700;letter-spacing:1px;color:#8b949e}
    #event-log{flex:1;overflow-y:auto;padding:0 12px 8px;font-size:11px;line-height:1.8}
    .ev{color:#8b949e}
    .ev time{color:#484f58;margin-right:6px}
    .ev.ev-spawn{color:#58a6ff}
    .ev.ev-orbit{color:#e3b341}
    .ev.ev-ingress{color:#f85149}
    .ev.ev-reset{color:#7c8d99}
    .ev.ev-lost{color:#6e7681}

    /* MAP */
    #map-wrap{position:relative;flex:1;display:flex;flex-direction:column}
    #map{flex:1}

    /* CONTROLS */
    #controls{
      position:absolute;bottom:20px;right:20px;z-index:1000;display:flex;flex-direction:column;gap:8px
    }
    .ctrl-btn{
      background:#161b22cc;border:1px solid #30363d;color:#e6edf3;
      padding:8px 14px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:700;
      backdrop-filter:blur(4px);transition:background .15s,border-color .15s
    }
    .ctrl-btn:hover{background:#21262d;border-color:#58a6ff}

    /* POPUP */
    .drone-popup .leaflet-popup-content-wrapper{
      background:#161b22ee;color:#e6edf3;
      border:1px solid #30363d;border-radius:8px;
      font-size:12px;line-height:1.8;font-family:monospace;
      backdrop-filter:blur(8px)
    }
    .drone-popup .leaflet-popup-tip{background:#30363d}
    .drone-popup b{color:#f85149;font-size:13px}
    .drone-popup .phase-tag{font-size:10px;font-weight:700;letter-spacing:1px;padding:1px 5px;border-radius:3px;vertical-align:middle}

    /* SCROLLBARS */
    ::-webkit-scrollbar{width:4px}
    ::-webkit-scrollbar-track{background:#0d1117}
    ::-webkit-scrollbar-thumb{background:#30363d;border-radius:2px}

    /* TILE DARK */
    .map-tiles{filter:invert(1) hue-rotate(180deg) brightness(0.85) saturate(0.6)}
  </style>
</head><body>

<div id="topbar">
  <span class="logo">&#9888; HOSTILE SWARM</span>
  <div class="badge">Tracks: <span id="cnt">0</span></div>
  <div class="badge">INGRESS: <span id="cnt-ingress" style="color:#f85149">0</span></div>
  <div class="badge">ORBIT: <span id="cnt-orbit" style="color:#e3b341">0</span></div>
  <div class="badge">Fabric: <span id="fabric-label" style="color:#3fb950">EFDI GOAT</span></div>
  <div class="badge" id="share-badge" onclick="copyShare()" title="Click to copy share URL" style="cursor:pointer;color:#3fb950">&#128279; __SHARE_URL__</div>
  <div id="conn-dot" class="pulse"></div>
  <span id="conn-label">connecting…</span>
</div>

<div id="main">
  <div id="sidebar">
    <div id="sidebar-header">
      <span>THREAT TRACKS</span>
      <span id="last-update" style="font-weight:400"></span>
    </div>
    <div id="threat-list"></div>
    <div id="log-section">
      <div id="log-header">EVENT LOG</div>
      <div id="event-log"></div>
    </div>
  </div>

  <div id="map-wrap">
    <div id="map"></div>
    <div id="controls">
      <button class="ctrl-btn" onclick="fitAll()">&#8982; FIT ALL</button>
      <button class="ctrl-btn" id="tail-btn" onclick="toggleTails()">&#9760; TAILS ON</button>
      <button class="ctrl-btn" onclick="window.open('https://portal.example','_blank')">&#128268; PORTAL</button>
    </div>
  </div>
</div>

<script>
const map = L.map('map',{zoomControl:false}).setView([60.28,25.3],9);
L.control.zoom({position:'topleft'}).addTo(map);
window.addEventListener('load',()=>map.invalidateSize());
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
  attribution:'© OpenStreetMap',className:'map-tiles'
}).addTo(map);

const SHARE_URL='__SHARE_URL__';
L.circle([60.1699,24.9384],{radius:3000,color:'#f85149',weight:1,dashArray:'6,3',fillOpacity:0.06,interactive:false}).addTo(map);
L.marker([60.1699,24.9384],{icon:L.divIcon({className:'',html:'<div style="color:#f85149;font-size:10px;font-weight:700;white-space:nowrap;letter-spacing:1px">&#9678; TARGET A</div>',iconSize:[80,14],iconAnchor:[40,7]})}).addTo(map);

const drones={};
let showTails=true;
let selectedId=null;

// ---- ICONS — NATO hostile air track (diamond + heading vector) ----
function mkIcon(heading,phase){
  // NATO APP-6 hostile fixed-wing air track: red diamond (static) + aircraft silhouette + heading vector (both rotate)
  const fill=phase==='orbit'?'#FCA5A5':'#F87171';
  const rot=heading||0;
  const svg=`<svg width="56" height="56" viewBox="-28 -28 56 56"
      xmlns="http://www.w3.org/2000/svg"
      style="overflow:visible;cursor:pointer;filter:drop-shadow(0 0 3px rgba(0,0,0,0.85))">
    <polygon points="0,-18 18,0 0,18 -18,0"
      fill="${fill}" stroke="#111" stroke-width="2.5"/>
    <g transform="rotate(${rot})">
      <polygon points="0,-5 11,-1 7,2 0,7 -7,2 -11,-1" fill="#111"/>
      <line x1="0" y1="-19" x2="0" y2="-26" stroke="#111" stroke-width="2"/>
      <polygon points="0,-29 3,-24 -3,-24" fill="#111"/>
    </g>
  </svg>`;
  return L.divIcon({className:'',html:svg,iconSize:[56,56],iconAnchor:[28,28]});
}

// ---- POPUP ----
function popupHtml(d){
  const uid=d.source.replace('hostile-uav-','UAV-').toUpperCase();
  const phaseColor=d.phase==='orbit'?'#e3b341':'#f85149';
  const phaseBg=d.phase==='orbit'?'#2d2208':'#3d1515';
  return `<b>${uid}</b>
    <span class="phase-tag" style="background:${phaseBg};color:${phaseColor}">${(d.phase||'').toUpperCase()}</span><br>
    &#128205; ${d.lat.toFixed(5)}, ${d.lon.toFixed(5)}<br>
    Alt: <b>${d.alt} m</b> &nbsp; Hdg: <b>${(d.heading||0).toFixed(0)}°</b><br>
    Speed: <b>${(d.speed_kmh||0).toFixed(0)} km/h</b><br>
    Seq: ${d.seq||0}`;
}

// ---- EVENT LOG ----
const MAX_LOG=40;
function addEvent(cls,msg){
  const log=document.getElementById('event-log');
  const now=new Date();
  const ts=now.toTimeString().slice(0,8);
  const el=document.createElement('div');
  el.className=`ev ${cls}`;
  el.innerHTML=`<time>${ts}</time>${msg}`;
  log.prepend(el);
  while(log.children.length>MAX_LOG) log.removeChild(log.lastChild);
}

// ---- SIDEBAR CARD ----
function upsertCard(d){
  const uid=d.source;
  const label=uid.replace('hostile-uav-','UAV-').toUpperCase();
  const phaseClass=d.phase==='orbit'?'orbit':'ingress';
  const phaseLabel=d.phase==='orbit'?'ORBIT':'INGRESS';
  const phaseTagCls=d.phase==='orbit'?'phase-orbit':'phase-ingress';
  let card=document.getElementById('card-'+uid);
  if(!card){
    card=document.createElement('div');
    card.id='card-'+uid;
    card.className=`threat-card ${phaseClass}`;
    card.onclick=()=>focusDrone(uid);
    document.getElementById('threat-list').appendChild(card);
  }
  card.className=`threat-card ${phaseClass}${selectedId===uid?' selected':''}`;
  const eta=etaMin(d);
  card.innerHTML=`
    <div class="tc-head">
      <span class="tc-id">${label}</span>
      <span class="tc-phase ${phaseTagCls}">${phaseLabel}</span>
    </div>
    <div class="tc-row">Lat/Lon: <span>${d.lat.toFixed(4)}, ${d.lon.toFixed(4)}</span></div>
    <div class="tc-row">Alt: <span>${d.alt} m</span> &nbsp; Hdg: <span>${(d.heading||0).toFixed(0)}&deg;</span></div>
    <div class="tc-row">Speed: <span>${(d.speed_kmh||0).toFixed(0)} km/h</span>${eta!==null?' &nbsp; ETA: <span style="color:#f85149;font-weight:700">'+eta+' min</span>':''}</div>`;
}

// ---- FOCUS ----
function focusDrone(uid){
  selectedId=uid;
  document.querySelectorAll('.threat-card').forEach(c=>{
    c.classList.toggle('selected',c.id==='card-'+uid);
  });
  const st=drones[uid];
  if(st) map.setView(st.marker.getLatLng(),12,{animate:true});
}

// ---- FIT ALL ----
function fitAll(){
  const pts=Object.values(drones).map(s=>s.marker.getLatLng());
  if(pts.length) map.fitBounds(L.latLngBounds(pts),{padding:[60,60]});
}

// ---- SHARE ----
function copyShare(){
  navigator.clipboard.writeText(SHARE_URL).then(()=>{
    const b=document.getElementById('share-badge');
    const t=b.textContent;
    b.textContent='&#10003; Copied!';
    setTimeout(()=>b.textContent=t,1800);
  });
}

// ---- ETA ----
function etaMin(d){
  if(d.phase!=='ingress') return null;
  const dlat=60.1699-d.lat, dlon=24.9384-d.lon;
  const dist=Math.hypot(dlat*111.0, dlon*111.0*Math.cos(d.lat*Math.PI/180));
  return Math.max(0,(dist/(d.speed_kmh||1)*60)).toFixed(0);
}

// ---- TAILS TOGGLE ----
function toggleTails(){
  showTails=!showTails;
  document.getElementById('tail-btn').textContent=showTails?'☠ TAILS ON':'☠ TAILS OFF';
  Object.values(drones).forEach(s=>{
    s.tail.setStyle({opacity:showTails?0.55:0});
  });
}

// ---- COUNTERS ----
function updateCounters(){
  const all=Object.values(drones);
  document.getElementById('cnt').textContent=all.length;
  document.getElementById('cnt-ingress').textContent=all.filter(s=>s.phase==='ingress').length;
  document.getElementById('cnt-orbit').textContent=all.filter(s=>s.phase==='orbit').length;
  document.getElementById('last-update').textContent=new Date().toTimeString().slice(0,8);
}

// ---- SSE ----
const es=new EventSource('/events');
es.onopen=()=>{
  document.getElementById('conn-dot').className='pulse';
  document.getElementById('conn-label').textContent='GOAT FABRIC LIVE';
};
es.onerror=()=>{
  document.getElementById('conn-dot').className='dead';
  document.getElementById('conn-label').textContent='reconnecting…';
};

// Backbone data is untrusted: safe characters in ids and numbers in numeric fields before any of it
// reaches innerHTML.
function clean(d){
  const num=v=>{const n=Number(v);return Number.isFinite(n)?n:0;};
  d.source=String(d.source||'').replace(/[^A-Za-z0-9._:-]/g,'_');
  d.phase=String(d.phase||'').replace(/[^A-Za-z-]/g,'');
  for(const k of ['lat','lon','alt','heading','speed_kmh','seq','delay_s']) if(k in d) d[k]=num(d[k]);
  return d;
}

es.onmessage=e=>{
  const d=clean(JSON.parse(e.data));
  const uid=d.source;
  if(!uid) return;

  if(d.lost){
    const st=drones[uid];
    if(st){
      st.marker.remove(); st.tail.remove(); st.popup.remove();
      delete drones[uid];
      document.getElementById('card-'+uid)?.remove();
    }
    addEvent('ev-lost',`<b>${uid.replace('hostile-uav-','UAV-').toUpperCase()}</b> &mdash; CONTACT LOST`);
    updateCounters();
    return;
  }

  const isNew=!drones[uid];
  const prevPhase=drones[uid]?.phase;

  if(isNew){
    const popup=L.popup({className:'drone-popup',maxWidth:240,autoClose:false,closeOnClick:false});
    let popupOpen=false;
    const marker=L.marker([d.lat,d.lon],{icon:mkIcon(d.heading,d.phase)}).addTo(map);
    const tail=L.polyline([[d.lat,d.lon]],{
      color:d.phase==='orbit'?'#e3b341':'#f85149',
      weight:2,opacity:showTails?0.55:0,dashArray:'6,4'
    }).addTo(map);

    marker.on('click',function(ev){
      L.DomEvent.stopPropagation(ev);
      if(popupOpen){popup.remove();popupOpen=false;}
      else{popup.setLatLng(marker.getLatLng()).setContent(popupHtml(d)).addTo(map);popupOpen=true;}
      focusDrone(uid);
    });

    drones[uid]={marker,tail,popup,isPopupOpen:()=>popupOpen,setPopupOpen:v=>{popupOpen=v;},history:[[d.lat,d.lon]],phase:d.phase};
    addEvent('ev-spawn',`<b>${uid.replace('hostile-uav-','UAV-').toUpperCase()}</b> appeared &mdash; INGRESS ${d.speed_kmh?.toFixed(0)} km/h`);

  } else {
    const st=drones[uid];
    st.marker.setLatLng([d.lat,d.lon]);
    st.marker.setIcon(mkIcon(d.heading,d.phase));
    if(st.isPopupOpen()) st.popup.setLatLng([d.lat,d.lon]).setContent(popupHtml(d));

    if(d.reset){
      st.history=[[d.lat,d.lon]];
      st.tail.setStyle({color:d.phase==='orbit'?'#e3b341':'#f85149'});
      addEvent('ev-reset',`<b>${uid.replace('hostile-uav-','UAV-').toUpperCase()}</b> cycle reset &mdash; new ingress`);
    } else {
      st.history.push([d.lat,d.lon]);
      if(st.history.length>120) st.history.shift();
    }
    st.tail.setLatLngs(st.history);

    if(d.phase!==prevPhase){
      st.phase=d.phase;
      const evCls=d.phase==='orbit'?'ev-orbit':'ev-ingress';
      addEvent(evCls,`<b>${uid.replace('hostile-uav-','UAV-').toUpperCase()}</b> entered <b>${d.phase.toUpperCase()}</b>`);
      st.tail.setStyle({color:d.phase==='orbit'?'#e3b341':'#f85149'});
    } else {
      st.phase=d.phase;
    }
  }

  upsertCard(d);
  updateCounters();
};
</script>
</body></html>"""

_HTML = _HTML_SRC.replace("__SHARE_URL__", _SHARE_URL).encode()
_HTML_LEN = len(_HTML)

_CTRL_HTML = """<!DOCTYPE html>
<html lang="fi"><head>
<meta charset="utf-8">
<title>GOAT Control</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',monospace;background:#0d1117;color:#e6edf3;padding:24px;min-height:100vh}
a{color:#58a6ff;text-decoration:none}
#topbar{display:flex;align-items:center;justify-content:space-between;
  background:#161b22;border:1px solid #30363d;border-radius:8px;
  padding:12px 20px;margin-bottom:20px}
#topbar .logo{font-size:14px;font-weight:800;letter-spacing:2px;color:#f85149}
.section{background:#161b22;border:1px solid #30363d;border-radius:8px;
  margin-bottom:16px;overflow:hidden}
.sec-head{padding:10px 16px;font-size:11px;font-weight:700;letter-spacing:1px;
  color:#8b949e;background:#0d1117;border-bottom:1px solid #30363d}
.sec-body{padding:16px}
.btn-row{display:flex;gap:10px;flex-wrap:wrap}
.scn-btn{flex:1;min-width:160px;padding:14px 16px;border-radius:8px;
  border:2px solid;cursor:pointer;font-size:11px;font-weight:700;
  letter-spacing:1px;background:#21262d;transition:background .15s;text-align:left}
.scn-btn:hover{background:#2d333b}
.scn-btn .title{font-size:13px;margin-bottom:4px}
.scn-btn .desc{font-weight:400;color:#8b949e;font-size:10px}
.green{border-color:#3fb950;color:#3fb950}
.amber{border-color:#e3b341;color:#e3b341}
.red{border-color:#f85149;color:#f85149}
.purple{border-color:#bc8cff;color:#bc8cff}
.form-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.field label{display:block;font-size:10px;color:#8b949e;font-weight:700;
  letter-spacing:1px;margin-bottom:4px}
.field input,.field select{width:100%;background:#0d1117;border:1px solid #30363d;
  border-radius:6px;padding:8px 10px;color:#e6edf3;font-size:12px;font-family:monospace}
.field input:focus,.field select:focus{outline:none;border-color:#58a6ff}
.send-btn{margin-top:14px;width:100%;padding:12px;background:#21262d;
  border:2px solid #58a6ff;border-radius:8px;color:#58a6ff;font-weight:700;
  font-size:13px;letter-spacing:1px;cursor:pointer;transition:background .15s}
.send-btn:hover{background:#2d333b}
#auto-demo-btn{width:100%;padding:16px;background:#12001a;border:2px solid #bc8cff;
  border-radius:8px;color:#bc8cff;font-weight:800;font-size:14px;letter-spacing:2px;
  cursor:pointer;transition:all .2s;margin-bottom:16px}
#auto-demo-btn:hover:not(:disabled){background:#1e0a2a;border-color:#e0b0ff;color:#e0b0ff}
#auto-demo-btn:disabled{opacity:0.5;cursor:not-allowed}
#demo-status{text-align:center;font-size:11px;color:#8b949e;min-height:18px;margin-bottom:4px}
#demo-bar-wrap{height:4px;background:#21262d;border-radius:2px;margin-bottom:16px;overflow:hidden}
#demo-bar{height:4px;background:#bc8cff;border-radius:2px;width:0%;transition:width .1s linear}
#tx-log{max-height:220px;overflow-y:auto;font-size:11px;padding:0}
.tx{padding:8px 16px;border-bottom:1px solid #21262d;line-height:1.7}
.tx time{color:#484f58;margin-right:8px}
.tx.ok{color:#3fb950}.tx.err{color:#f85149}
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-thumb{background:#30363d;border-radius:2px}
.drop-zone{border:2px dashed #30363d;border-radius:8px;padding:28px;text-align:center;
  color:#8b949e;cursor:pointer;transition:all .2s;font-size:13px;user-select:none}
.drop-zone:hover,.drop-zone.drag-over{border-color:#58a6ff;background:#0d1f3c;color:#58a6ff}
.drop-zone.loaded{border-color:#3fb950;color:#3fb950}
.mission-table{width:100%;font-size:11px;border-collapse:collapse;margin-top:12px;font-family:monospace}
.mission-table th{color:#8b949e;text-align:left;padding:4px 8px;
  border-bottom:1px solid #30363d;font-size:10px;letter-spacing:1px}
.mission-table td{padding:4px 8px;border-bottom:1px solid #21262d}
.play-btn{margin-top:12px;width:100%;padding:12px;background:#0a2010;
  border:2px solid #3fb950;border-radius:8px;color:#3fb950;font-weight:700;
  font-size:13px;letter-spacing:1px;cursor:pointer;transition:all .15s}
.play-btn:hover:not(:disabled){background:#0d3018}
.play-btn:disabled{opacity:.5;cursor:not-allowed}
</style>
</head><body>
<div id="topbar">
  <span class="logo">&#9888; EFDI GOAT &mdash; SCENARIO CONTROL</span>
  <a href="/" target="_blank">&#128506; Open map &rarr;</a>
</div>

<div class="section">
  <div class="sec-head">AUTO DEMO</div>
  <div class="sec-body">
    <div id="demo-status">Press button to start &mdash; scenario plays automatically</div>
    <div id="demo-bar-wrap"><div id="demo-bar"></div></div>
    <button id="auto-demo-btn" onclick="autoDemo()">START DEMO</button>
  </div>
</div>

<div class="section">
  <div class="sec-head">QUICK SCENARIO &mdash; one click</div>
  <div class="sec-body">
    <div class="btn-row">
      <button class="scn-btn green" onclick="runScenario('spawn')">
        <div class="title">+ NEW CONTACT</div>
        <div class="desc">Detected beyond the border &mdash; INGRESS 280 km/h</div>
      </button>
      <button class="scn-btn amber" onclick="runScenario('orbit')">
        <div class="title">&#8635; ENTERING ORBIT</div>
        <div class="desc">Target reached objective area &mdash; loiter phase</div>
      </button>
      <button class="scn-btn red" onclick="runScenario('lost')">
        <div class="title">&#10005; CONTACT LOST</div>
        <div class="desc">Left surveillance zone</div>
      </button>
      <button class="scn-btn purple" onclick="runScenario('fast')">
        <div class="title">&#9889; ACCELERATING</div>
        <div class="desc">Speed increasing &mdash; 400 km/h</div>
      </button>
    </div>
  </div>
</div>

<div class="section">
  <div class="sec-head">MANUAL INPUT</div>
  <div class="sec-body">
    <div class="form-grid">
      <div class="field"><label>TARGET ID</label>
        <input id="f-uid" value="hostile-uav-04"></div>
      <div class="field"><label>PHASE</label>
        <select id="f-phase">
          <option value="ingress">INGRESS &mdash; approaching</option>
          <option value="orbit">ORBIT &mdash; loitering</option>
        </select></div>
      <div class="field"><label>LAT</label>
        <input id="f-lat" type="number" step="0.0001" value="60.80"></div>
      <div class="field"><label>LON</label>
        <input id="f-lon" type="number" step="0.0001" value="26.80"></div>
      <div class="field"><label>ALTITUDE (m)</label>
        <input id="f-alt" type="number" value="150"></div>
      <div class="field"><label>SPEED (km/h)</label>
        <input id="f-speed" type="number" value="250"></div>
      <div class="field"><label>HEADING (&deg;)</label>
        <input id="f-heading" type="number" value="220"></div>
      <div class="field"><label>RESET</label>
        <select id="f-reset">
          <option value="false">No</option>
          <option value="true">Yes (new cycle)</option>
        </select></div>
    </div>
    <button class="send-btn" onclick="sendManual()">&#8680; SEND TO FABRIC</button>
  </div>
</div>

<div class="section">
  <div class="sec-head">MISSION FILE &mdash; drag &amp; drop CSV or JSON</div>
  <div class="sec-body">
    <div id="drop-zone" class="drop-zone"
         ondragover="dropOver(event)" ondragleave="dropLeave(event)" ondrop="dropFile(event)"
         onclick="document.getElementById('file-input').click()">
      &#128196; Drop mission file here or click to browse<br>
      <small style="color:#484f58;font-size:10px;margin-top:6px;display:block">
        CSV or JSON &nbsp;&bull;&nbsp;
        <a href="/example.csv" download onclick="event.stopPropagation()">download example.csv</a>
      </small>
    </div>
    <input type="file" id="file-input" accept=".csv,.json" style="display:none"
           onchange="loadFile(this.files[0])">
    <div id="mission-preview" style="display:none">
      <table class="mission-table">
        <thead><tr>
          <th>#</th><th>SOURCE</th><th>PHASE</th><th>LAT</th><th>LON</th>
          <th>ALT</th><th>SPD km/h</th><th>HDG&deg;</th><th>DELAY s</th>
        </tr></thead>
        <tbody id="mission-rows"></tbody>
      </table>
      <button class="play-btn" id="play-btn" onclick="playMission()">&#9654; PLAY MISSION</button>
    </div>
  </div>
</div>

<div class="section">
  <div class="sec-head">TRANSMISSION LOG</div>
  <div id="tx-log"></div>
</div>

<script>
const SCENARIOS = {
  // INGRESS — spawning just across the border line (~29.3–29.8°E)
  spawn_04: {source:'hostile-uav-04',phase:'ingress',lat:60.55,lon:29.40,alt:250,speed_kmh:280,heading:263,reset:true},  // border S → target A
  spawn_05: {source:'hostile-uav-05',phase:'ingress',lat:61.85,lon:29.50,alt:200,speed_kmh:260,heading:248,reset:true},  // border C → target B
  spawn_06: {source:'hostile-uav-06',phase:'ingress',lat:62.55,lon:29.80,alt:180,speed_kmh:245,heading:233,reset:true},  // border N → target C
  spawn_07: {source:'hostile-uav-07',phase:'ingress',lat:60.35,lon:29.30,alt:150,speed_kmh:420,heading:268,reset:true},  // fast, low — border S → target D
  spawn_08: {source:'hostile-uav-08',phase:'ingress',lat:61.50,lon:29.45,alt:220,speed_kmh:265,heading:253,reset:true},  // border C → target E
  // ORBIT — loitering over the targets
  orbit_04: {source:'hostile-uav-04',phase:'orbit',lat:60.17,lon:24.94,alt:150,speed_kmh:145,heading:60,reset:false},   // target A
  orbit_05: {source:'hostile-uav-05',phase:'orbit',lat:61.50,lon:23.77,alt:120,speed_kmh:135,heading:90,reset:false},   // target B
  orbit_06: {source:'hostile-uav-06',phase:'orbit',lat:60.45,lon:22.27,alt:165,speed_kmh:140,heading:270,reset:false},  // target C
  orbit_07: {source:'hostile-uav-07',phase:'orbit',lat:60.29,lon:25.04,alt:90, speed_kmh:160,heading:45,reset:false},   // target D (low)
  orbit_08: {source:'hostile-uav-08',phase:'orbit',lat:60.22,lon:24.66,alt:175,speed_kmh:130,heading:120,reset:false},  // target E
  // CONTACT LOST
  lost_04: {source:'hostile-uav-04',lost:true,lat:0,lon:0,alt:0,speed_kmh:0,heading:0,phase:'ingress',reset:false},
  lost_05: {source:'hostile-uav-05',lost:true,lat:0,lon:0,alt:0,speed_kmh:0,heading:0,phase:'ingress',reset:false},
  lost_06: {source:'hostile-uav-06',lost:true,lat:0,lon:0,alt:0,speed_kmh:0,heading:0,phase:'ingress',reset:false},
  lost_07: {source:'hostile-uav-07',lost:true,lat:0,lon:0,alt:0,speed_kmh:0,heading:0,phase:'ingress',reset:false},
  lost_08: {source:'hostile-uav-08',lost:true,lat:0,lon:0,alt:0,speed_kmh:0,heading:0,phase:'ingress',reset:false},
  // quick scenario buttons
  spawn: {source:'hostile-uav-04',phase:'ingress',lat:60.55,lon:29.40,alt:250,speed_kmh:280,heading:263,reset:true},
  orbit: {source:'hostile-uav-04',phase:'orbit',lat:60.17,lon:24.94,alt:150,speed_kmh:145,heading:60,reset:false},
  lost:  {source:'hostile-uav-04',lost:true,lat:0,lon:0,alt:0,speed_kmh:0,heading:0,phase:'ingress',reset:false},
  fast:  {source:'hostile-uav-04',phase:'ingress',lat:60.55,lon:29.0,alt:100,speed_kmh:420,heading:278,reset:false},
};

const DEMO_STEPS = [
  // PHASE 1 — contacts detected beyond the border line
  {key:'spawn_04', label:'UAV-04 detected beyond the border — INGRESS toward target A, 280 km/h, alt 250m', delay:6000},
  {key:'spawn_07', label:'UAV-07 detected — fast low contact 420 km/h, alt 150m toward target D', delay:5000},
  {key:'spawn_05', label:'UAV-05 detected beyond the border — INGRESS toward target B, 260 km/h', delay:6000},
  {key:'spawn_08', label:'UAV-08 detected beyond the border — INGRESS toward target E, 265 km/h, alt 220m', delay:5000},
  {key:'spawn_06', label:'UAV-06 detected far beyond the border — INGRESS toward target C, 245 km/h, alt 180m', delay:7000},
  // PHASE 2 — contacts reach their targets
  {key:'orbit_07', label:'UAV-07 reached target D — entering ORBIT, alt 90m (low-observable)', delay:7000},
  {key:'orbit_04', label:'UAV-04 reached target A — ORBIT phase commenced, alt 150m', delay:8000},
  {key:'orbit_05', label:'UAV-05 reached target B — ORBIT phase commenced, alt 120m', delay:8000},
  {key:'orbit_08', label:'UAV-08 reached target E — ORBIT phase commenced, alt 175m', delay:7000},
  {key:'orbit_06', label:'UAV-06 reached target C — ORBIT phase commenced, alt 165m', delay:9000},
  // PHASE 3 — contacts lost
  {key:'lost_07', label:'UAV-07 — CONTACT LOST over target D', delay:4000},
  {key:'lost_04', label:'UAV-04 — CONTACT LOST over target A', delay:4000},
  {key:'lost_08', label:'UAV-08 — CONTACT LOST over target E', delay:4000},
  {key:'lost_05', label:'UAV-05 — CONTACT LOST over target B', delay:4000},
  {key:'lost_06', label:'UAV-06 — CONTACT LOST over target C', delay:0},
];

function autoDemo(){
  const btn = document.getElementById('auto-demo-btn');
  const status = document.getElementById('demo-status');
  const bar = document.getElementById('demo-bar');
  btn.disabled = true;
  let stepIdx = 0;
  let barInterval = null;

  function runStep(){
    if(stepIdx >= DEMO_STEPS.length){
      status.textContent = 'Demo complete';
      bar.style.width = '100%';
      setTimeout(()=>{
        btn.disabled = false;
        bar.style.width = '0%';
        status.textContent = 'Press button — scenario plays automatically';
      }, 2000);
      return;
    }
    const step = DEMO_STEPS[stepIdx];
    status.innerHTML = `Vaihe ${stepIdx+1}/${DEMO_STEPS.length}: ${step.label}`;
    runScenario(step.key);

    if(step.delay > 0){
      bar.style.width = '0%';
      const start = Date.now();
      clearInterval(barInterval);
      barInterval = setInterval(()=>{
        const pct = Math.min(100, (Date.now()-start)/step.delay*100);
        bar.style.width = pct + '%';
        if(pct >= 100){ clearInterval(barInterval); stepIdx++; runStep(); }
      }, 80);
    } else {
      stepIdx++;
      runStep();
    }
  }
  runStep();
}

function logTx(msg, ok){
  const log = document.getElementById('tx-log');
  const el = document.createElement('div');
  el.className = 'tx ' + (ok ? 'ok' : 'err');
  const ts = new Date().toTimeString().slice(0,8);
  el.innerHTML = `<time>${ts}</time>${msg}`;
  log.prepend(el);
  while(log.children.length > 40) log.removeChild(log.lastChild);
}

function send(payload){
  return fetch('/inject',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  }).then(r=>r.json()).then(r=>{
    const uid = (payload.source||'?').replace('hostile-uav-','UAV-').toUpperCase();
    const phase = payload.lost ? 'CONTACT LOST' : (payload.phase||'').toUpperCase();
    const spd = payload.speed_kmh ? ` ${payload.speed_kmh} km/h` : '';
    logTx(`<b>${uid}</b> &mdash; ${phase}${spd}`, true);
  }).catch(e=>logTx('Error: '+e, false));
}

function runScenario(key){
  const p = SCENARIOS[key];
  if(!p) return;
  // fill form with scenario values
  if(document.getElementById('f-uid')) document.getElementById('f-uid').value = p.source;
  send({...p, seq:0, ts_ms: Date.now(), type:'hostile-uav'});
}

function sendManual(){
  const payload = {
    source:   document.getElementById('f-uid').value.trim(),
    phase:    document.getElementById('f-phase').value,
    lat:      parseFloat(document.getElementById('f-lat').value),
    lon:      parseFloat(document.getElementById('f-lon').value),
    alt:      parseFloat(document.getElementById('f-alt').value),
    speed_kmh:parseFloat(document.getElementById('f-speed').value),
    heading:  parseFloat(document.getElementById('f-heading').value),
    reset:    document.getElementById('f-reset').value === 'true',
    seq: 0, ts_ms: Date.now(), type: 'hostile-uav',
  };
  send(payload);
}

// ---- MISSION FILE DROP ----
let _mission = [];
let _playTimer = null;

function dropOver(e){ e.preventDefault(); document.getElementById('drop-zone').classList.add('drag-over'); }
function dropLeave(){ document.getElementById('drop-zone').classList.remove('drag-over'); }
function dropFile(e){
  e.preventDefault(); dropLeave();
  const f = e.dataTransfer.files[0];
  if(f) loadFile(f);
}

function loadFile(f){
  if(!f) return;
  const reader = new FileReader();
  reader.onload = ev => {
    try {
      const text = ev.target.result;
      _mission = f.name.toLowerCase().endsWith('.json') ? parseMissionJSON(text) : parseMissionCSV(text);
      showMissionPreview(_mission.length + ' events loaded from ' + f.name);
    } catch(err){ logTx('Parse error: ' + err.message, false); }
  };
  reader.readAsText(f);
}

function parseMissionCSV(text){
  const lines = text.trim().split('\\n').filter(l => l.trim() && !l.startsWith('#'));
  const header = lines[0].split(',').map(h => h.trim().toLowerCase());
  return lines.slice(1).map(line => rowToPayload(
    Object.fromEntries(header.map((h,i) => [h, line.split(',')[i]?.trim()||'']))
  ));
}

function parseMissionJSON(text){
  return JSON.parse(text).map(row => rowToPayload(row));
}

function rowToPayload(row){
  const phase = (row.phase||'ingress').toLowerCase().trim();
  const lost = phase === 'lost';
  return {
    source: (row.source||'hostile-uav-04').trim(),
    phase: lost ? 'ingress' : phase,
    lost: lost,
    lat: parseFloat(row.lat)||0,
    lon: parseFloat(row.lon)||0,
    alt: parseFloat(row.alt)||0,
    speed_kmh: parseFloat(row.speed_kmh)||0,
    heading: parseFloat(row.heading)||0,
    reset: row.reset === 'true' || row.reset === true,
    delay_s: parseFloat(row.delay_s)||3,
    seq: 0, ts_ms: 0, type: 'hostile-uav',
  };
}

function showMissionPreview(msg){
  const zone = document.getElementById('drop-zone');
  zone.classList.remove('drag-over');
  zone.classList.add('loaded');
  zone.innerHTML = '&#10003; ' + msg;
  const tbody = document.getElementById('mission-rows');
  tbody.innerHTML = '';
  _mission.forEach((m,i) => {
    m = clean(m);
    const phase = m.lost ? 'LOST' : m.phase.toUpperCase();
    const color = m.lost ? '#f85149' : m.phase==='orbit' ? '#e3b341' : '#3fb950';
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + (i+1) + '</td><td>' + m.source + '</td>'
      + '<td style="color:' + color + '">' + phase + '</td>'
      + '<td>' + (m.lat||'-') + '</td><td>' + (m.lon||'-') + '</td>'
      + '<td>' + (m.alt||'-') + '</td><td>' + (m.speed_kmh||'-') + '</td>'
      + '<td>' + (m.heading||'-') + '</td><td>' + m.delay_s + '</td>';
    tbody.appendChild(tr);
  });
  document.getElementById('mission-preview').style.display = 'block';
}

function playMission(){
  if(!_mission.length) return;
  const btn = document.getElementById('play-btn');
  if(_playTimer !== null){
    clearTimeout(_playTimer); _playTimer = null;
    btn.textContent = '\\u25b6 PLAY MISSION';
    btn.style.cssText = 'border-color:#3fb950;color:#3fb950';
    return;
  }
  btn.textContent = '\\u23f9 STOP';
  btn.style.cssText = 'border-color:#f85149;color:#f85149';
  let i = 0;
  function next(){
    if(i >= _mission.length){
      btn.textContent = '\\u25b6 PLAY MISSION';
      btn.style.cssText = 'border-color:#3fb950;color:#3fb950';
      _playTimer = null;
      logTx('Mission complete &mdash; ' + _mission.length + ' events transmitted', true);
      return;
    }
    const ev = Object.assign({}, _mission[i], {ts_ms: Date.now(), seq: i});
    send(ev);
    _playTimer = setTimeout(next, (_mission[i].delay_s||3) * 1000);
    i++;
  }
  next();
}
</script>
</body></html>""".encode()

_CTRL_LEN = len(_CTRL_HTML)

_EXAMPLE_CSV = (
    "source,lat,lon,alt,speed_kmh,heading,phase,delay_s\n"
    "# PHASE 1 — contacts detected just beyond the border line\n"
    "hostile-uav-04,60.55,29.40,250,280,263,ingress,6\n"
    "hostile-uav-07,60.35,29.30,150,420,268,ingress,5\n"
    "hostile-uav-05,61.85,29.50,200,260,248,ingress,6\n"
    "hostile-uav-08,61.50,29.45,220,265,253,ingress,5\n"
    "hostile-uav-06,62.55,29.80,180,245,233,ingress,7\n"
    "# PHASE 2 — contacts enter orbit over their targets\n"
    "hostile-uav-07,60.29,25.04,90,160,45,orbit,7\n"
    "hostile-uav-04,60.17,24.94,150,145,60,orbit,8\n"
    "hostile-uav-05,61.50,23.77,120,135,90,orbit,8\n"
    "hostile-uav-08,60.22,24.66,175,130,120,orbit,7\n"
    "hostile-uav-06,60.45,22.27,165,140,270,orbit,9\n"
    "# PHASE 3 — contacts lost\n"
    "hostile-uav-07,0,0,0,0,0,lost,4\n"
    "hostile-uav-04,0,0,0,0,0,lost,4\n"
    "hostile-uav-08,0,0,0,0,0,lost,4\n"
    "hostile-uav-05,0,0,0,0,0,lost,4\n"
    "hostile-uav-06,0,0,0,0,0,lost,0\n"
).encode()
_EXAMPLE_CSV_LEN = len(_EXAMPLE_CSV)


def _broadcast(msg: str) -> None:
    with _lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


def _subscribe() -> None:
    global _zen_session, _sender
    keys = (f"{sender.EXERCISE_ROOT}/**", f"{_gc.KEY_PREFIX}/**")
    with sender.open_session("live-map") as s:
        _zen_session = s
        _sender = sender.Sender(s, "manual")

        def on_sample(sample) -> None:
            try:
                _broadcast(sample.payload.to_bytes().decode())
            except Exception:
                pass
        subs = [s.declare_subscriber(k, on_sample) for k in keys]  # noqa: F841
        print(f"[live-map] subscribed {', '.join(keys)}")
        print(f"[live-map] subscribed — open http://localhost:{_PORT}")
        print(f"[live-map] control panel — open http://localhost:{_PORT}/control")
        while True:
            time.sleep(1)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/events":
            self._sse()
        elif self.path == "/control":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(_CTRL_LEN))
            self.end_headers()
            self.wfile.write(_CTRL_HTML)
        elif self.path == "/example.csv":
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="mission_example.csv"')
            self.send_header("Content-Length", str(_EXAMPLE_CSV_LEN))
            self.end_headers()
            self.wfile.write(_EXAMPLE_CSV)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(_HTML_LEN))
            self.end_headers()
            self.wfile.write(_HTML)

    def do_POST(self):
        if self.path == "/inject":
            self._inject()

    def _inject(self):
        # JSON only: a web page can send text/plain to this port without a CORS preflight, but not
        # application/json (and no Access-Control-Allow-Origin is sent back).
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self.send_response(415)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            d = json.loads(self.rfile.read(length))
            uid = str(d.pop("source", "hostile-uav-04"))
            lat, lon = float(d.pop("lat")), float(d.pop("lon"))
            fields = {k: float(d.pop(k)) for k in ("alt", "heading", "speed_kmh") if k in d}
            if "phase" in d:
                fields["phase"] = re.sub(r"[^A-Za-z-]", "", str(d.pop("phase")))
            if "lost" in d:
                fields["lost"] = bool(d.pop("lost"))
            # Only known extras go on to the fabric; the sender sets the exercise labels itself.
            d = {"reset": bool(d.get("reset", False))}
            if _sender is not None:
                _sender.track(uid, lat, lon, **fields, **d)
            else:
                _broadcast(json.dumps(dict(d, source=uid, lat=lat, lon=lon, **fields)))
            print(f"[inject] {uid}  phase={fields.get('phase','?')}  lost={fields.get('lost', False)}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception as exc:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())

    def _sse(self):
        q: queue.Queue = queue.Queue(maxsize=100)
        with _lock:
            _clients.append(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                try:
                    msg = q.get(timeout=20)
                    self.wfile.write(f"data: {msg}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _lock:
                if q in _clients:
                    _clients.remove(q)


def main() -> None:
    threading.Thread(target=_subscribe, daemon=True).start()
    time.sleep(0.5)
    print(f"[live-map] HTTP server on http://localhost:{_PORT}  (Ctrl-C to stop)")
    ThreadingHTTPServer(("", _PORT), _Handler).serve_forever()


if __name__ == "__main__":
    main()
