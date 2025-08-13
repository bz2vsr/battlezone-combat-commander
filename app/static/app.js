(() => {
  const grid = document.getElementById('grid');
  const fState = document.getElementById('fState');
  const fMin = document.getElementById('fMin');
  const fQ = document.getElementById('fQ');
  const connDot = document.getElementById('connDot');
  const connText = document.getElementById('connText');
  const fMod = document.getElementById('fMod');
  // legacy modal shim removed in favor of DaisyUI modal in layout
  const daisyModal = document.getElementById('appModal');
  const mTitle = document.getElementById('appModalTitle');
  const mBody = document.getElementById('appModalBody');
  let firstDataReceived = false;
  let isWarmup = true;
  setTimeout(()=>{ isWarmup = false; }, 8000);
  // DaisyUI modal buttons are handled in app/static/js/app.js

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
      empty.className = 'col-span-full';
      empty.setAttribute('aria-live', 'polite');
      const msg = isWarmup ? 'Loading sessions…' : 'No sessions online right now.';
      empty.innerHTML = `<div class="alert alert-info bg-base-200 border border-base-300"><span>${msg}</span></div>`;
      grid.appendChild(empty);
      return;
    }
    sessions.forEach(s => {
      const card = document.createElement('div');
      card.className = 'card bg-base-200 border border-base-300 cursor-pointer p-3';

      const title = (((s.level && s.level.name) || '') + ' ' + ((s.name || ''))).toLowerCase();
      const isFFA = /(ffa|deathmatch|\bdm\b)/.test(title);
      const playersHtml = `
        <div class="mt-2 text-sm leading-6">
          ${(s.players||[]).map(p => {
            const nick = (p.steam && p.steam.nickname) ? p.steam.nickname : (p.name || 'Player');
            const isStar = (p.is_host || p.slot===1 || p.slot===6);
            const avatar = (p.steam && p.steam.avatar) ? `<img src="${p.steam.avatar}" alt="" class="w-4 h-4 rounded-full shrink-0"/>` : '';
            const score = (p.score!=null? ` <span class=\"opacity-70 text-xs\">(score ${p.score})</span>` : '');
            return `<div class=\"flex items-center gap-1 truncate\">${isStar?'<span>★</span>':''}${avatar}<span class=\"truncate\">${nick}</span>${score}</div>`;
          }).join('')}
        </div>`;
      const teamsHtml = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-2 items-stretch">
          <div class="card bg-base-100 border border-base-300 h-full"><div class="card-body p-3 h-full">
            <h4 class="text-sm opacity-70 mb-1">Team 1</h4>
            ${(s.players||[]).filter(p=>!p.team_id || p.team_id===1).map(p => {
              const nick = (p.steam && p.steam.nickname) ? p.steam.nickname : (p.name || 'Player');
              const isStar = (p.is_host || p.slot===1 || p.slot===6);
              const avatar = (p.steam && p.steam.avatar) ? `<img src=\"${p.steam.avatar}\" alt=\"\" class=\"w-4 h-4 rounded-full shrink-0\"/>` : '';
              const score = (p.score!=null? ` <span class=\\"opacity-70 text-xs\\">(score ${p.score})</span>` : '');
              return `<div class=\"flex items-center gap-1 truncate\">${isStar?'<span>★</span>':''}${avatar}<span class=\"truncate\">${nick}</span>${score}</div>`;
            }).join('') || '<span class="opacity-70 text-xs">Open</span>'}
            <div class="grow"></div>
          </div></div>
          <div class="card bg-base-100 border border-base-300 h-full"><div class="card-body p-3 h-full">
            <h4 class="text-sm opacity-70 mb-1">Team 2</h4>
            ${(s.players||[]).filter(p=>p.team_id===2).map(p => {
              const nick = (p.steam && p.steam.nickname) ? p.steam.nickname : (p.name || 'Player');
              const isStar = (p.is_host || p.slot===1 || p.slot===6);
              const avatar = (p.steam && p.steam.avatar) ? `<img src=\"${p.steam.avatar}\" alt=\"\" class=\"w-4 h-4 rounded-full shrink-0\"/>` : '';
              const score = (p.score!=null? ` <span class=\\"opacity-70 text-xs\\">(score ${p.score})</span>` : '');
              return `<div class=\"flex items-center gap-1 truncate\">${isStar?'<span>★</span>':''}${avatar}<span class=\"truncate\">${nick}</span>${score}</div>`;
            }).join('') || '<span class="opacity-70 text-xs">Open</span>'}
            <div class="grow"></div>
          </div></div>
        </div>`;

      const a = s.attributes || {};
      card.innerHTML = `
        <div class="flex flex-wrap gap-2 items-center">
          <span class="${((s.state||'')==='InGame') ? 'badge-accent-soft' : 'badge-soft'}">${s.state || 'Unknown'}</span>
          ${s.nat_type ? `<span class=\"badge-soft\">${s.nat_type}</span>` : ''}
          ${a.worst_ping!=null ? `<span class=\"badge-soft\" title=\"Worst ping seen\">Worst ${a.worst_ping}ms</span>` : ''}
          ${a.game_mode ? `<span class=\"badge-soft\" title=\"Game mode\">${a.game_mode}</span>` : ''}
          ${a.time_limit!=null ? `<span class=\"badge-soft\" title=\"Time limit\">TL ${a.time_limit}m</span>` : ''}
          ${a.kill_limit!=null ? `<span class=\"badge-soft\" title=\"Kill limit\">KL ${a.kill_limit}</span>` : ''}
          <span class="ml-auto text-xs opacity-70">${(s.players||[]).length}${(s.attributes && s.attributes.max_players)? '/'+s.attributes.max_players : ''} players</span>
        </div>
        <div class="mt-1 card bg-base-100 border border-base-300">
          <div class="card-body p-3">
            <h3 class="text-lg">${(s.name || s.id)}</h3>
            <div class="text-xs opacity-70">${s.id}</div>
            <div class="text-xs opacity-70">${s.level && s.level.name ? ('Map: ' + s.level.name) : (s.map_file? ('Map: ' + s.map_file) : '')}
              ${s.mod_details && (s.mod_details.name || s.mod) ? (' • Mod: ' + (s.mod_details.url ? (`<a class=\"link\" href=\"${s.mod_details.url}\" target=\"_blank\" rel=\"noopener\">${s.mod_details.name || s.mod}</a>`) : (s.mod_details.name || s.mod))) : ''}
            </div>
          </div>
        </div>
        ${s.level && s.level.image ? `<div class="mt-2 card bg-base-100 border border-base-300"><div class="card-body p-3"><img alt="map" class="map-thumb" src="${s.level.image}" onclick="event.stopPropagation(); (function(src){const m=document.createElement('div');m.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;z-index:9999';m.onclick=()=>document.body.removeChild(m);const i=document.createElement('img');i.src=src;i.style.cssText='max-width:92vw;max-height:92vh;border-radius:10px;border:1px solid #1b2535';m.appendChild(i);document.body.appendChild(m);})('${s.level.image}')"/></div></div>` : ''}
        ${isFFA ? playersHtml : teamsHtml}
      `;
      card.onclick = async () => {
        try {
          const res = await fetch(`/api/v1/sessions/${encodeURIComponent(s.id)}`);
          const detail = await res.json();
          mTitle.textContent = s.name || s.id;
          mBody.textContent = JSON.stringify(detail, null, 2);
          daisyModal.showModal();
        } catch (e) {}
      };
      grid.appendChild(card);
    });
  }

  async function renderOnlineSidebar() {
    const box = document.getElementById('onlineList');
    if (!box) return;
    try {
      const [ingRes, siteRes] = await Promise.all([
        fetch('/api/v1/players/online'),
        fetch('/api/v1/players/site-online').catch(()=>null)
      ]);
      const ing = ingRes ? await ingRes.json() : {players: []};
      const site = siteRes ? await siteRes.json() : {players: []};
      const players = ing.players || [];
      const siteMap = new Map((site.players||[]).map(p => [String(p.id), p]));
      if (players.length === 0) {
        box.innerHTML = '<span class="muted">No players detected</span>';
        return;
      }
      box.innerHTML = players.map(p => {
        const avatar = (p.steam && p.steam.avatar) ? `<img src="${p.steam.avatar}" alt="" class="w-4 h-4 rounded-full mr-2 inline-block align-[-3px]"/>` : '';
        const name = p.steam && p.steam.nickname ? p.steam.nickname : (p.name || 'Player');
        const sid = p.steam && p.steam.id ? String(p.steam.id) : (p.steam_id ? String(p.steam_id) : null);
        const active = sid && siteMap.has(sid);
        const dot = active ? '<span class="dot ok mr-2"></span>' : '<span class="dot mr-2"></span>';
        return `<div class="flex items-center">${dot}${avatar}<span class="truncate">${name}</span></div>`;
      }).join('');
    } catch {
      box.innerHTML = '<span class="muted">Unavailable</span>';
    }
  }

  function url() {
    const p = new URLSearchParams();
    if (fState.value) p.set('state', fState.value);
    if (fMin.value && +fMin.value>0) p.set('min_players', fMin.value);
    if (fQ.value) p.set('q', fQ.value);
    if (fMod.value) {
      p.set('mod', fMod.value);
    }
    return `/api/v1/sessions/current?${p.toString()}`;
  }

  async function fetchOnce() {
    const res = await fetch(url());
    const data = await res.json();
    if ((data.sessions||[]).length > 0) firstDataReceived = true;
    render(data);
    // mark connection healthy when REST responds
    connDot.className = 'dot ok';
    connText.textContent = 'Live';
  }

  let sse;
  let sseLive = false;
  let socket;
  function startSSE(){
    if (sse) sse.close();
    sse = new EventSource('/api/v1/stream/sessions');
    sse.onopen = ()=>{ sseLive = true; connDot.className='dot ok'; connText.textContent='Live'; };
    sse.onmessage = (ev) => {
      connDot.className = 'dot ok';
      connText.textContent = 'Live';
      const payload = JSON.parse(ev.data);
      if ((payload.sessions||[]).length > 0) firstDataReceived = true;
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
      renderOnlineSidebar();
    };
    sse.onerror = ()=>{ sseLive = false; connDot.className = 'dot err'; connText.textContent = 'Reconnecting…'; sse && sse.close(); setTimeout(startSSE, 5000); };
  }

  function startWS(){
    try {
      // eslint-disable-next-line no-undef
      socket = io('/', { transports: ['websocket', 'polling'] });
      socket.on('connect', ()=>{ if (!sseLive) { connDot.className='dot ok'; connText.textContent='Live'; } });
      socket.on('sessions:update', ()=>{ fetchOnce(); renderOnlineSidebar(); });
      socket.on('connect_error', ()=>{ if (!sseLive) { connDot.className='dot err'; connText.textContent='Reconnecting…'; } });
      socket.on('presence:update', ()=>{ renderOnlineSidebar(); });
      socket.on('disconnect', ()=>{ if (!sseLive) { connDot.className='dot err'; connText.textContent='Reconnecting…'; } });
    } catch {}
  }

  fState.addEventListener('change', fetchOnce);
  fMin.addEventListener('change', fetchOnce);
  fQ.addEventListener('input', fetchOnce);
  fMod.addEventListener('change', fetchOnce);
  fetchOnce();
  // Defer WS init slightly to ensure client script is present
  setTimeout(startWS, 200);
  startSSE();
  // history chart removed from main page for now
  renderOnlineSidebar();

  // Heartbeat every 8s for logged-in users for faster presence
  setInterval(()=>{
    fetch('/api/v1/presence/heartbeat', {method:'POST'}).catch(()=>{});
  }, 8000);

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

  // Load current user and toggle sign-in UI
  (async function loadMe(){
    try {
      const res = await fetch('/api/v1/me');
      const data = await res.json();
      const user = data && data.user;
      const me = document.getElementById('me');
      const btn = document.getElementById('signin');
      const out = document.getElementById('signout');
      const prof = document.getElementById('profileLink');
      if (user) {
        if (btn) btn.style.display = 'none';
        if (me) {
          me.style.display = '';
          const name = (user.display_name && String(user.display_name).trim()) || user.id;
          me.innerHTML = `You: <a href="${user.profile}" target="_blank" rel="noopener">${name}</a>`;
        }
        if (out) out.style.display = '';
        if (prof) {
          prof.style.display = '';
          prof.onclick = async (e) => {
            e.preventDefault();
            await showProfileModal();
          };
        }
        // immediate heartbeat when detected
        fetch('/api/v1/presence/heartbeat', {method:'POST'}).catch(()=>{});
      } else {
        if (btn) btn.style.display = '';
        if (me) me.style.display = 'none';
        if (out) out.style.display = 'none';
        if (prof) { prof.style.display = 'none'; prof.onclick = null; }
      }
    } catch {}
  })();

  const outBtn = document.getElementById('signout');
  if (outBtn) {
    outBtn.addEventListener('click', async () => {
      const ok = await showConfirm('Are you sure you want to sign out?');
      if (!ok) return;
      try { await fetch('/auth/logout', {method:'POST'}); } catch {}
      location.href = '/';
    });
  }

  function showConfirm(message){
    return new Promise(resolve => {
      const oldClose = document.getElementById('mClose');
      const onCancel = () => { cleanup(false); };
      const cleanup = (result) => {
        modal.style.display = 'none';
        modal.setAttribute('aria-hidden','true');
        oldClose.removeEventListener('click', onCancel);
        modal.removeEventListener('click', onBackdrop);
        resolve(result);
      };
      const onBackdrop = (e)=>{ if(e.target===modal) cleanup(false); };
      oldClose.addEventListener('click', onCancel, { once: true });
      modal.addEventListener('click', onBackdrop, { once: true });
      mTitle.textContent = 'Confirm';
      mBody.innerHTML = `
        <div>${message}</div>
        <div class="row" style="justify-content:flex-end;margin-top:12px">
          <button id="confirmNo" style="background:#0f1622;color:#e6e9ef;border:1px solid #243149;padding:6px 10px;border-radius:6px;margin-right:8px">Cancel</button>
          <button id="confirmYes" style="background:#18263a;color:#e6e9ef;border:1px solid #2a3953;padding:6px 10px;border-radius:6px">Sign out</button>
        </div>`;
      modal.style.display = 'flex';
      modal.setAttribute('aria-hidden','false');
      document.getElementById('confirmNo').onclick = () => cleanup(false);
      document.getElementById('confirmYes').onclick = () => cleanup(true);
    });
  }

  async function showProfileModal(){
    try {
      const res = await fetch('/api/v1/me');
      const data = await res.json();
      const user = data && data.user;
      if (!user) return;
      const avatar = user.avatar ? `<img src="${user.avatar}" alt="" style="width:64px;height:64px;border-radius:50%;border:1px solid #243149;margin-right:12px"/>` : '';
      mTitle.textContent = 'Your account';
      mBody.innerHTML = `
        <div class="row" style="align-items:center">
          ${avatar}
          <div>
            <div><strong>${(user.display_name && String(user.display_name).trim()) || user.id}</strong></div>
            <div class="muted">Provider: ${user.provider || 'steam'}</div>
            <div class="muted">ID: ${user.id}</div>
            <div><a href="${user.profile}" target="_blank" rel="noopener">Open Steam profile</a></div>
          </div>
        </div>
      `;
      modal.style.display = 'flex';
      modal.setAttribute('aria-hidden','false');
    } catch {}
  }
})();
