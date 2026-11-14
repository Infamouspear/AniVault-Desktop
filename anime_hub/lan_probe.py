"""Small same-origin LAN test page, not a mobile client or credential store."""
HTML = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AniVault LAN diagnostics</title>
<style>body{font:16px system-ui;max-width:780px;margin:24px auto;padding:16px;background:#111c2a;color:#eee}input,button,select{font:inherit;padding:9px;margin:5px 0;max-width:100%;box-sizing:border-box}select{width:100%}button{cursor:pointer}video{width:100%;background:#000}fieldset{border:1px solid #526073;border-radius:8px;margin:20px 0;padding:14px}label{display:block}pre{white-space:pre-wrap;overflow-wrap:anywhere}#status{padding:12px;background:#243448;border-radius:6px}</style>
<h1>AniVault LAN diagnostics</h1><p>Pair, choose local media and test direct playback and progress. Restricted titles are never included here.</p>
<p id="status" role="status" aria-live="polite">Checking saved session…</p>
<fieldset><legend>Device pairing</legend><label>Pairing code (from desktop Settings)<input id="code" inputmode="numeric" autocomplete="off" maxlength="8"></label>
<label>Device name<input id="device" maxlength="64" placeholder="My phone"></label><button id="pair">Pair device</button><p id="session"></p></fieldset>
<fieldset><legend>Library and playback</legend><button id="library">Refresh library</button>
<label>Title<select id="title"><option value="">Choose a title</option></select></label>
<label>Episode<select id="episode"><option value="">Choose an episode</option></select></label>
<button id="play" disabled>Play selected episode</button><video id="video" controls playsinline preload="metadata"></video>
<p id="playback" role="status">No episode selected.</p></fieldset>
<fieldset><legend>Progress Testing</legend><p>These controls use the desktop progress API. Playback does not save automatically on this test page.</p>
<label>Position in seconds<input id="position" type="number" min="0" step="0.001" value="0"></label>
<button id="read-progress" disabled>Read progress</button><button id="save-progress" disabled>Save position</button>
<button id="watched" disabled>Mark watched</button><button id="unwatched" disabled>Mark unwatched</button>
<pre id="progress">Select an episode to inspect its state.</pre></fieldset><pre id="result"></pre>
<script src="/probe.js"></script></html>'''

JS = ''''use strict';
const el=id=>document.getElementById(id), status=el('status'), video=el('video');
let selected='', authorized=false, generation=0;
function controls(){for(const id of ['play','read-progress','save-progress','watched','unwatched'])el(id).disabled=!authorized||!selected;}
function options(id,rows,prompt,label){const select=el(id);select.replaceChildren(new Option(prompt,''));for(const row of rows)select.add(new Option(label(row),String(row.id)));}
function failed(error){status.textContent=error.message;}
async function api(path,body){
  status.textContent='Requesting '+path+'…';
  let response;try{response=await fetch(path,{credentials:'same-origin',cache:'no-store',...(body?{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});}
  catch(e){throw new Error('Cannot reach AniVault. Check the desktop server, address and private network.');}
  const data=await response.json();
  if(!response.ok){
    if(response.status===401){authorized=false;el('pair').disabled=false;controls();video.pause();video.removeAttribute('src');el('session').textContent='Session missing, expired or revoked. Pair again with a new desktop code.';}
    throw new Error('HTTP '+response.status+': '+String(data.error||'request failed').replaceAll('_',' '));
  }
  status.textContent='Request succeeded (HTTP '+response.status+').';return data;
}
function titleText(row){return typeof row.title==='string'?row.title:row.title.english||row.title.romaji||row.title.native||('Title '+row.id);}
async function library(){const rows=await api('/api/v1/anime');options('title',rows,'Choose a title',titleText);options('episode',[],'Choose an episode',String);selected='';controls();el('result').textContent=rows.length+' normal local titles available.';}
async function session(){const data=await api('/api/v1/session');authorized=true;el('pair').disabled=true;el('device').value=data.name;el('session').textContent='Paired as '+data.name+'. Session expires '+new Date(data.expires_at*1000).toLocaleDateString()+'.';controls();return data;}
async function progress(){if(!selected)return;const data=await api('/api/v1/media/'+selected+'/progress');el('progress').textContent=JSON.stringify(data,null,2);el('position').value=(data.resume_position_ms||0)/1000;return data;}
async function update(body){if(!selected)return;await api('/api/v1/media/'+selected+'/progress',body);await progress();}
el('pair').onclick=async()=>{try{
  status.textContent='Pairing…';const response=await fetch('/pair',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:el('code').value.trim(),name:el('device').value.trim()})});
  const data=await response.json();if(!response.ok)throw new Error('Pairing failed (HTTP '+response.status+'): '+String(data.error).replaceAll('_',' '));
  el('code').value='';await session();await library();
}catch(e){failed(e);}};
el('library').onclick=()=>library().catch(failed);
el('title').onchange=async()=>{const version=++generation;selected='';controls();options('episode',[],'Loading episodes…',String);try{
  if(!el('title').value){options('episode',[],'Choose an episode',String);return;}
  const detail=await api('/api/v1/anime/'+el('title').value);if(version!==generation)return;
  const rows=detail.items.filter(row=>row.kind==='episode'&&row.present);
  options('episode',rows,'Choose an episode',row=>'Season '+(row.season??'—')+' · Episode '+(row.episode??'—')+' · Media ID '+row.id);
  el('result').textContent=rows.length+' available episodes for '+titleText(detail)+'.';
}catch(e){options('episode',[],'Could not load episodes',String);failed(e);}};
el('episode').onchange=()=>{selected=el('episode').value;controls();progress().catch(failed);};
el('play').onclick=async()=>{try{if(!selected)return;await session();video.src='/api/v1/media/'+selected;await video.play();}catch(e){failed(e);}};
el('read-progress').onclick=()=>progress().catch(failed);
el('save-progress').onclick=()=>{const value=Number(el('position').value);if(!Number.isFinite(value)||value<0){failed(new Error('Enter a nonnegative position in seconds.'));return;}update({position_ms:Math.round(value*1000),automatic:false}).catch(failed);};
el('watched').onclick=()=>update({watched:true,automatic:false}).catch(failed);
el('unwatched').onclick=()=>update({watched:false,automatic:false}).catch(failed);
for(const event of ['loadstart','loadedmetadata','playing','waiting','seeking','seeked','pause','ended'])video.addEventListener(event,()=>{el('playback').textContent='Playback: '+event+' · '+video.currentTime.toFixed(1)+' seconds';});
video.addEventListener('error',()=>{el('playback').textContent='Media failed. Check authorization/file availability or use a player supporting this container and codec.';});
session().then(library).catch(e=>{status.textContent='Pair this device using the desktop code. '+e.message;});
controls();'''
