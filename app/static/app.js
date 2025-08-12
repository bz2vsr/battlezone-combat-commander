(() => {
  const grid = document.getElementById('grid');
  const fState = document.getElementById('fState');
  const fMin = document.getElementById('fMin');
  const fQ = document.getElementById('fQ');
  const connDot = document.getElementById('connDot');
  const connText = document.getElementById('connText');
  const fVsr = document.getElementById('fVsr');
  const fMod = document.getElementById('fMod');
  const modal = document.getElementById('modal');
  const mTitle = document.getElementById('mTitle');
  const mBody = document.getElementById('mBody');
  document.getElementById('mClose').onclick = () => { modal.style.display = 'none'; modal.setAttribute('aria-hidden','true'); };
  modal.addEventListener('click', (e)=>{ if(e.target===modal){ modal.style.display='none'; modal.setAttribute('aria-hidden','true'); }});

  function drawHistory(points){
    const c = document.getElementById('histCanvas');
    if(!c) return;
    const ctx = c.getContext('2d');
    const W = c.width = c.clientWidth;
    const H = c.height;
    ctx.clearRect(0,0,W,H);
    if(!points || points.length===0){ return; }
    const sessions = points.map(p=>p.sessions||0);
    const players = points.map(p=>p.players||0);
    const maxY = Math.max(1, Math.max(...players), Math.max(...sessions));
    const step = W / Math.max(1, points.length-1);
    function plot(series, color){
      ctx.beginPath();
      series.forEach((v,i)=>{
        const x = i*step;
        const y = H - (v/maxY)*(H-16) - 8;
        if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
      });
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    }
    ctx.strokeStyle = '#1b2535'; ctx.lineWidth = 1;
    for(let i=0;i<=4;i++){ const y=i*(H/4); ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke(); }
    plot(players, '#22c55e');
    plot(sessions, '#3b82f6');
    const last = points[points.length-1] || {sessions:0, players:0};
    const lbl = document.getElementById('histSummary');
    if(lbl) lbl.textContent = `${last.sessions||0} sessions • ${last.players||0} players`;
  }

  async function loadHistory(){
    try {
      const res = await fetch('/api/v1/history/summary?minutes=120');
      const data = await res.json();
      drawHistory(data.points||[]);
    } catch {}
  }

  function timeAgo(iso){
    if(!iso) return '';
    const s = Math.max(0, Math.floor((Date.now()-Date.parse(iso))/1000));
    if(s<60) return `${s}s ago`;
    const m=Math.floor(s/60); if(m<60) return `${m}m ago`;
    const h=Math.floor(m/60); return `${h}h ago`;
  }

  function render(data) {
    grid.innerHTML = '';
    const sessions = data.sessions || [];
    if (sessions.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.setAttribute('aria-live', 'polite');
      empty.innerHTML = `No sessions online right now.<br/><span class="muted">Waiting for live updates…</span>`;
      grid.appendChild(empty);
      return;
    }
    sessions.forEach(s => {
      const card = document.createElement('div');
      card.className = 'card';

      const title = (((s.level && s.level.name) || '') + ' ' + ((s.name || ''))).toLowerCase();
      const isFFA = /(ffa|deathmatch|\bdm\b)/.test(title);
      const playersHtml = `
        <div class="players">
          ${(s.players||[]).map(p => {
            const nick = (p.steam && p.steam.nickname) ? p.steam.nickname : (p.name || 'Player');
            const star = (p.is_host || p.slot===1 || p.slot===6)? '★ ' : '';
            const avatar = (p.steam && p.steam.avatar) ? `<img src="${p.steam.avatar}" alt="" style="width:16px;height:16px;border-radius:50%;vertical-align:-3px;margin-right:6px;"/>` : '';
            const score = (p.score!=null? ' (score '+p.score+')' : '');
            return `${star}${avatar}${nick}${score}`;
          }).join('<br/>')}
        </div>`;
      const teamsHtml = `
        <div class="teams">
          <div class="team">
            <h4>Team 1</h4>
            ${(s.players||[]).filter(p=>!p.team_id || p.team_id===1).map(p => {
              const nick = (p.steam && p.steam.nickname) ? p.steam.nickname : (p.name || 'Player');
              const star = (p.is_host || p.slot===1 || p.slot===6)? '★ ' : '';
              const avatar = (p.steam && p.steam.avatar) ? `<img src="${p.steam.avatar}" alt="" style="width:16px;height:16px;border-radius:50%;vertical-align:-3px;margin-right:6px;"/>` : '';
              const score = (p.score!=null? ' (score '+p.score+')' : '');
              return `${star}${avatar}${nick}${score}`;
            }).join('<br/>') || '<span class="muted">Open</span>'}
          </div>
          <div class="team">
            <h4>Team 2</h4>
            ${(s.players||[]).filter(p=>p.team_id===2).map(p => {
              const nick = (p.steam && p.steam.nickname) ? p.steam.nickname : (p.name || 'Player');
              const star = (p.is_host || p.slot===1 || p.slot===6)? '★ ' : '';
              const avatar = (p.steam && p.steam.avatar) ? `<img src="${p.steam.avatar}" alt="" style="width:16px;height:16px;border-radius:50%;vertical-align:-3px;margin-right:6px;"/>` : '';
              const score = (p.score!=null? ' (score '+p.score+')' : '');
              return `${star}${avatar}${nick}${score}`;
            }).join('<br/>') || '<span class="muted">Open</span>'}
          </div>
        </div>`;

      const a = s.attributes || {};
      card.innerHTML = `
        <div class="row">
          <span class="badge">${s.state || 'Unknown'}</span>
          <span class="badge">${s.nat_type || ''}</span>
          ${a.worst_ping!=null ? `<span class="badge" title="Worst ping seen">Worst ${a.worst_ping}ms</span>` : ''}
          ${a.game_mode ? `<span class=\"badge\" title=\"Game mode\">${a.game_mode}</span>` : ''}
          <span class="muted">${s.version || ''}</span>
          ${a.time_limit!=null ? `<span class="badge" title="Time limit">TL ${a.time_limit}m</span>` : ''}
          ${a.kill_limit!=null ? `<span class="badge" title="Kill limit">KL ${a.kill_limit}</span>` : ''}
          
          <span class="muted" style="margin-left:auto">${(s.players||[]).length}${(s.attributes && s.attributes.max_players)? '/'+s.attributes.max_players : ''} players • ${timeAgo(s.last_seen_at)}</span>
        </div>
        <h3>${(s.name || s.id)}</h3>
        <div class="muted">${s.id}</div>
        <div class="muted">${s.level && s.level.name ? ('Map: ' + s.level.name) : (s.map_file? ('Map: ' + s.map_file) : '')}
          ${s.mod_details && (s.mod_details.name || s.mod) ? (' • Mod: ' + (s.mod_details.url ? (`<a href="${s.mod_details.url}" target="_blank" rel="noopener">${s.mod_details.name || s.mod}</a>`) : (s.mod_details.name || s.mod))) : ''}
        </div>
        ${s.level && s.level.image ? `<img alt="map" class="map-thumb" src="${s.level.image}" onclick="event.stopPropagation(); (function(src){const m=document.createElement('div');m.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;z-index:9999';m.onclick=()=>document.body.removeChild(m);const i=document.createElement('img');i.src=src;i.style.cssText='max-width:92vw;max-height:92vh;border-radius:10px;border:1px solid #1b2535';m.appendChild(i);document.body.appendChild(m);})('${s.level.image}')"/>` : ''}
        ${isFFA ? playersHtml : teamsHtml}
      `;
      card.onclick = async () => {
        try {
          const res = await fetch(`/api/v1/sessions/${encodeURIComponent(s.id)}`);
          const detail = await res.json();
          mTitle.textContent = s.name || s.id;
          mBody.textContent = JSON.stringify(detail, null, 2);
          modal.style.display = 'flex';
          modal.setAttribute('aria-hidden','false');
        } catch (e) {}
      };
      grid.appendChild(card);
    });
  }

  function url() {
    const p = new URLSearchParams();
    if (fState.value) p.set('state', fState.value);
    if (fMin.value && +fMin.value>0) p.set('min_players', fMin.value);
    if (fQ.value) p.set('q', fQ.value);
    if (fMod.value) {
      p.set('mod', fMod.value);
    } else if (fVsr.checked) {
      p.set('mod', '1325933293');
    }
    return `/api/v1/sessions/current?${p.toString()}`;
  }

  async function fetchOnce() {
    const res = await fetch(url());
    render(await res.json());
  }

  let sse;
  function startSSE(){
    if (sse) sse.close();
    sse = new EventSource('/api/v1/stream/sessions');
    sse.onmessage = (ev) => {
      connDot.className = 'dot ok';
      connText.textContent = 'Live';
      const payload = JSON.parse(ev.data);
      const req = new URL(url(), window.location);
      const state = req.searchParams.get('state');
      const min = +(req.searchParams.get('min_players')||0);
      const q = (req.searchParams.get('q')||'').toLowerCase();
      let sessions = payload.sessions || [];
      if (state) sessions = sessions.filter(s => (s.state||'').toLowerCase()===state.toLowerCase());
      if (min>0) sessions = sessions.filter(s => (s.players||[]).length>=min);
      if (q) sessions = sessions.filter(s => {
        if ((s.name||'').toLowerCase().includes(q)) return true;
        return (s.players||[]).some(p => (p.name||'').toLowerCase().includes(q));
      });
      render({sessions});
    };
    sse.onerror = ()=>{ connDot.className = 'dot err'; connText.textContent = 'Reconnecting…'; sse && sse.close(); setTimeout(startSSE, 5000); };
  }

  fState.addEventListener('change', fetchOnce);
  fMin.addEventListener('change', fetchOnce);
  fQ.addEventListener('input', fetchOnce);
  fVsr.addEventListener('change', fetchOnce);
  fMod.addEventListener('change', fetchOnce);
  fetchOnce();
  startSSE();
  loadHistory();

  (async function loadMods(){
    try {
      const res = await fetch('/api/v1/mods');
      const data = await res.json();
      const mods = data.mods || {};
      const entries = Object.entries(mods)
        .map(([id, m]) => ({ id, name: (m && m.name) || id }))
        .filter(x => x.id && x.id !== '0')
        .sort((a,b)=> (a.name||'').localeCompare(b.name||''));
      entries.forEach(({id, name})=>{
        const opt = document.createElement('option');
        opt.value = id; opt.textContent = name;
        fMod.appendChild(opt);
      });
    } catch {}
  })();
})();
