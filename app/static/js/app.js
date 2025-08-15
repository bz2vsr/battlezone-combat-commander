// Minimal JS bridge for DaisyUI modal and profile/logout actions
// Main page logic (sessions grid, SSE/WS, Team Picker modal)
(()=>{
  const grid = document.getElementById('grid');
  const fState = document.getElementById('fState');
  const fMin = document.getElementById('fMin');
  const fQ = document.getElementById('fQ');
  const connDot = document.getElementById('connDot');
  const connText = document.getElementById('connText');
  const fMod = document.getElementById('fMod');
  const daisyModal = document.getElementById('appModal');
  const mTitle = document.getElementById('appModalTitle');
  const mBody = document.getElementById('appModalBody');
  let firstDataReceived = false;
  let isWarmup = true;
  setTimeout(()=>{ isWarmup = false; }, 8000);

  // no skeleton card; we will show loading state on button instead

  function compareByName(a, b){
    const an = ((a.name || a.id || '').toString()).toLowerCase();
    const bn = ((b.name || b.id || '').toString()).toLowerCase();
    if (an < bn) return -1; if (an > bn) return 1; return 0;
  }

  function sortSessions(list){
    const mode = (document.getElementById('fSort') && document.getElementById('fSort').value) || 'recent_desc';
    const arr = list.slice();
    const stateOrder = { 'InGame': 0, 'PreGame': 1, 'PostGame': 2 };
    if (mode === 'name_asc') {
      arr.sort((a,b)=> compareByName(a,b));
    } else if (mode === 'state_then_recent') {
      arr.sort((a,b)=>{
        const sa = stateOrder[a.state] ?? 3;
        const sb = stateOrder[b.state] ?? 3;
        if (sa !== sb) return sa - sb;
        const ta = new Date(a.created_at || a.started_at || 0).getTime();
        const tb = new Date(b.created_at || b.started_at || 0).getTime();
        if (ta !== tb) return tb - ta; // recent first within same state
        return compareByName(a,b);
      });
    } else if (mode === 'players_desc') {
      arr.sort((a,b)=>{
        const ca = (a.players||[]).length; const cb = (b.players||[]).length;
        if (ca !== cb) return cb - ca;
        return compareByName(a,b);
      });
    } else { // recent_desc default
      arr.sort((a,b)=>{
        const ta = new Date(a.created_at || a.started_at || 0).getTime();
        const tb = new Date(b.created_at || b.started_at || 0).getTime();
        if (ta !== tb) return tb - ta; // recent first
        const ca = (a.players||[]).length; const cb = (b.players||[]).length;
        if (ca !== cb) return cb - ca;
        return compareByName(a,b);
      });
    }
    return arr;
  }

  function render(data) {
    if (!grid) return;
    grid.innerHTML = '';
    const sessionsRaw = data.sessions || [];
    const sessions = sortSessions(sessionsRaw);
    // Simple per-session TP status cache { active:boolean, ts:number }
    const cache = (window.__TP_STATUS_CACHE__ ||= new Map());
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
      card.className = 'card bg-base-200 border border-base-300 p-3';
      const title = (((s.level && s.level.name) || '') + ' ' + ((s.name || ''))).toLowerCase();
      const isFFA = /(ffa|deathmatch|\bdm\b)/.test(title);
      const playersHtml = `
        <div class="mt-2 text-sm leading-6">
          ${(s.players||[]).map(p => {
            const nick = (p.steam && p.steam.nickname) ? p.steam.nickname : (p.name || 'Player');
            const isStar = (p.is_host || p.slot===1 || p.slot===6);
            const avatar = (p.steam && p.steam.avatar) ? `<img src="${p.steam.avatar}" alt="" class="w-4 h-4 rounded-full mr-2 flex-none"/>` : '';
            return `<div class="flex items-center truncate">${isStar?'<span class=\"mr-2\">★</span>':''}${avatar}<span class="truncate">${nick}</span></div>`;
          }).join('')}
        </div>`;
      const teamsHtml = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-2 items-stretch">
          <div class="card bg-base-100 border border-base-300 h-full"><div class="card-body p-3 h-full">
            <h4 class="text-sm opacity-70 mb-1">Team 1</h4>
                        ${(s.players||[]).filter(p=>!p.team_id || p.team_id===1).map(p => {
                          const nick = (p.steam && p.steam.nickname) ? p.steam.nickname : (p.name || 'Player');
                          const isStar = (p.is_host || p.slot===1 || p.slot===6);
                          const avatar = (p.steam && p.steam.avatar) ? `<img src=\"${p.steam.avatar}\" alt=\"\" class=\"w-4 h-4 rounded-full mr-2 flex-none\"/>` : '';
                          return `<div class=\"flex items-center truncate\">${isStar?'<span class=\\\"mr-2\\\">★</span>':''}${avatar}<span class=\"truncate\">${nick}</span></div>`;
                        }).join('') || '<span class="opacity-70 text-xs">Open</span>'}
            <div class="grow"></div>
          </div></div>
          <div class="card bg-base-100 border border-base-300 h-full"><div class="card-body p-3 h-full">
            <h4 class="text-sm opacity-70 mb-1">Team 2</h4>
                        ${(s.players||[]).filter(p=>p.team_id===2).map(p => {
                          const nick = (p.steam && p.steam.nickname) ? p.steam.nickname : (p.name || 'Player');
                          const isStar = (p.is_host || p.slot===1 || p.slot===6);
                          const avatar = (p.steam && p.steam.avatar) ? `<img src=\"${p.steam.avatar}\" alt=\"\" class=\"w-4 h-4 rounded-full mr-2 flex-none\"/>` : '';
                          return `<div class=\"flex items-center truncate\">${isStar?'<span class=\\\"mr-2\\\">★</span>':''}${avatar}<span class=\"truncate\">${nick}</span></div>`;
                        }).join('') || '<span class="opacity-70 text-xs">Open</span>'}
            <div class="grow"></div>
          </div></div>
        </div>`;
      const a = s.attributes || {};
      const sidKey = String(s.id||'').replace(/[^a-zA-Z0-9_-]/g, '_');
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
        ${s.level && s.level.image ? `<div class="mt-2 card bg-base-100 border border-base-300"><div class="card-body p-3"><img alt="map" class="map-thumb" src="${s.level.image}"/></div></div>` : ''}
        ${isFFA ? playersHtml : teamsHtml}
        <div class="mt-2 flex items-center justify-between">
          <div id="tpInd-${sidKey}" class="text-xs opacity-70">Checking Team Picker…</div>
          <button id="tpBtn-${sidKey}" class="btn btn-sm">Open</button>
        </div>
      `;

      // Decide label/visibility asynchronously with minimal caching
      const me = (window.__ME__||null);
      const commanderIds = new Set((s.players||[]).filter(p=>p.is_host && p.steam && p.steam.id).map(p=>String(p.steam.id)));
      const isCommander = !!(me && me.provider==='steam' && me.id && commanderIds.has(String(me.id)));
      const btn = card.querySelector(`#tpBtn-${sidKey}`);
      const ind = card.querySelector(`#tpInd-${sidKey}`);
      // Use cached status immediately if fresh (<10s)
      const now = Date.now();
      const cached = cache.get(s.id);
      const fresh = cached && (now - cached.ts < 10000);
      const applyUI = (active)=>{
        if (ind) ind.textContent = active ? 'Team Picker active' : 'No Team Picker';
        if (btn) {
          if (active) {
            btn.textContent = isCommander ? 'Open Team Picker' : 'View Team Picker';
            btn.disabled = false;
          } else {
            btn.textContent = isCommander ? 'Start Team Picker' : 'View Team Picker';
            btn.disabled = !isCommander;
          }
          btn.onclick = ()=> openTeamPickerModal(s);
        }
      };
      if (fresh) applyUI(!!cached.active);
      // Refresh in background if stale
      if (!fresh) {
        (async ()=>{
          try {
            const r = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`);
            const j = await r.json();
            const active = !!(j && j.session);
            cache.set(s.id, { active, ts: Date.now() });
            applyUI(active);
          } catch { /* ignore */ }
        })();
      }

      grid.appendChild(card);
    });
    // no-op: no skeleton placeholder behavior
  }

  async function openTeamPickerModal(s){
    try {
      const res = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`);
      const data = await res.json();
      mTitle.textContent = 'Team Picker';
      const sess = data && data.session;
      if (!sess) {
        const isPre = (s.state === 'PreGame');
        const needTwo = '<div class="text-xs opacity-70">Team Picker requires both commanders to be signed in.</div>';
        let isAuthed = false;
        try { const me = await fetch('/api/v1/me', {credentials:'same-origin'}); const mj = await me.json(); isAuthed = !!(mj && mj.user); } catch {}
        mBody.innerHTML = `<div class="space-y-4">
          <div class="text-sm opacity-80">No Team Picker has been started for this session yet.</div>
          ${!isPre?'<div class="alert bg-base-200 border border-base-300 text-xs">Team Picker is only available in PreGame.</div>':''}
          ${needTwo}
          ${isAuthed ? `<div><button id="tpStart" class="btn btn-sm btn-primary mt-2" ${!isPre?'disabled':''}>Start Team Picker</button></div>` : '<div class="text-xs opacity-70">Sign in as a commander to start the Team Picker.</div>'}
          <div id="tpStartErr" class="text-xs text-error"></div>
        </div>`;
        daisyModal.showModal();
        const startBtn = document.getElementById('tpStart');
        if (startBtn) startBtn.onclick = async ()=>{
          try {
            const resp = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/start`, {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin'});
            if (!resp.ok) {
              let msg = 'Unable to start Team Picker.';
              try { const j = await resp.json(); if (j && j.error === 'missing_commanders') msg = 'Could not detect two commanders. Team Picker requires two commanders with Steam IDs.'; if (j && j.error === 'not_pregame') msg = 'Team Picker is only available while the game is in PreGame.'; if (j && j.error==='both_commanders_required') msg='Both commanders must be signed in to start Team Picker.'; } catch {}
              const err = document.getElementById('tpStartErr'); if (err) { err.textContent = msg; }
              return;
            }
          } catch {}
          try {
            const r = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`);
            const j = await r.json();
            renderTP(j.session);
            daisyModal.showModal();
            window.__TP_OPEN__ = s.id;
            try { if (socket && window.__REALTIME__) { socket.emit('join', { room: `team_picker:${s.id}` }); } } catch {}
            try { await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/presence`, {method:'POST', credentials:'same-origin'}); } catch {}
          } catch {}
        };
        return;
      }
      renderTP(sess);
      daisyModal.showModal();
      window.__TP_OPEN__ = s.id;
      try { if (socket && window.__REALTIME__) { socket.emit('join', { room: `team_picker:${s.id}` }); } } catch {}
      try { await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/presence`, {method:'POST', credentials:'same-origin'}); } catch {}
    } catch {}
  }

  function url() {
    const p = new URLSearchParams();
    if (fState && fState.value) p.set('state', fState.value);
    if (fMin && fMin.value && +fMin.value>0) p.set('min_players', fMin.value);
    if (fQ && fQ.value) p.set('q', fQ.value);
    if (fMod) fMod.addEventListener('change', fetchOnce);
    return `/api/v1/sessions/current?${p.toString()}`;
  }

  async function fetchOnce() {
    try {
      const res = await fetch(url());
      const data = await res.json();
      if ((data.sessions||[]).length > 0) firstDataReceived = true;
      render(data);
      if (connDot) connDot.className = 'dot ok';
      if (connText) connText.textContent = 'Live';
    } catch {}
  }

  let sse;
  let sseLive = false;
  let socket;
  // Track last realtime update for Team Picker to avoid jittery polling
  let __TP_LAST_SOCKET_TS = 0;
  function startSSE(){
    if (!window.EventSource) return;
    if (sse) sse.close();
    sse = new EventSource('/api/v1/stream/sessions');
    sse.onopen = ()=>{ sseLive = true; if (connDot) connDot.className='dot ok'; if (connText) connText.textContent='Live'; };
    sse.onmessage = (ev) => {
      if (connDot) connDot.className = 'dot ok';
      if (connText) connText.textContent = 'Live';
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
    };
    sse.onerror = ()=>{ sseLive = false; if (connDot) connDot.className = 'dot err'; if (connText) connText.textContent = 'Reconnecting…'; sse && sse.close(); setTimeout(startSSE, 5000); };
  }

  function startWS(){
    try { if (!window.__REALTIME__ || window.__REALTIME__==='false') return; } catch {}
    try {
      // eslint-disable-next-line no-undef
      socket = io('/', { transports: ['websocket', 'polling'] });
      socket.on('connect', ()=>{ if (!sseLive) { if (connDot) connDot.className='dot ok'; if (connText) connText.textContent='Live'; } });
      socket.on('sessions:update', ()=>{ fetchOnce(); });
      socket.on('team_picker:update', (payload)=>{
        try {
          if (!window.__TP_OPEN__ || !payload || !payload.session_id) return;
          if (window.__TP_OPEN__ !== payload.session_id) return;
          __TP_LAST_SOCKET_TS = Date.now();
          const sess = payload.session;
          if (sess && typeof window.__RENDER_TP === 'function') { window.__RENDER_TP(sess); return; }
          fetch(`/api/v1/team_picker/${encodeURIComponent(window.__TP_OPEN__)}`, {cache:'no-store'}).then(r=>r.json()).then(j=>{ if (j && j.session) { if (typeof window.__RENDER_TP === 'function') { window.__RENDER_TP(j.session); } } });
        } catch {}
      });
      socket.on('connect_error', ()=>{ if (!sseLive) { if (connDot) connDot.className='dot err'; if (connText) connText.textContent='Reconnecting…'; } });
      socket.on('disconnect', ()=>{ if (!sseLive) { if (connDot) connDot.className='dot err'; if (connText) connText.textContent='Reconnecting…'; } });
    } catch {}
  }

  if (fState) fState.addEventListener('change', fetchOnce);
  if (fMin) fMin.addEventListener('change', fetchOnce);
  if (fQ) fQ.addEventListener('input', fetchOnce);
  if (fMod) fMod.addEventListener('change', fetchOnce);
  const fSort = document.getElementById('fSort');
  if (fSort) fSort.addEventListener('change', fetchOnce);
  fetchOnce();
  setTimeout(startWS, 200);
  startSSE();
})();

(function(){
  const modal = document.getElementById('appModal');
  const title = document.getElementById('appModalTitle');
  const body = document.getElementById('appModalBody');
  const btnProfile = document.getElementById('profileLink');
  const btnSignout = document.getElementById('signout');
  // const btnCreateMock = document.getElementById('createMockSession');
  // Sidebar user elements
  const sbSignedIn = document.getElementById('sbSignedIn');
  const sbSignedOut = document.getElementById('sbSignedOut');
  const sbAvatar = document.getElementById('sbAvatar');
  const sbName = document.getElementById('sbName');
  const sbProfile = document.getElementById('sbProfile');
  const sbOpenProfile = document.getElementById('sbOpenProfile');
  const sbSignOut = document.getElementById('sbSignOut');
  const onlineList = document.getElementById('onlineList');
  let presenceTimer = null;
  const modalCloseX = document.getElementById('appModalCloseX');
  // Track Team Picker invite prompts to avoid repeat spam
  const tpNotified = new Map(); // session_id -> expiresAt (ms)
  let tpPromptOpen = false;

  async function fetchMe(){ try { const r = await fetch('/api/v1/me'); return await r.json(); } catch { return {user:null}; } }

  if (btnProfile) btnProfile.addEventListener('click', async (e)=>{
    e.preventDefault();
    const { user } = await fetchMe(); if (!user) return;
    title.textContent = 'Your account';
    const avatar = user.avatar ? `<img src="${user.avatar}" class="w-16 h-16 rounded-full border border-base-300 mr-3"/>` : '';
    body.innerHTML = `<div class="flex items-center">${avatar}<div><div class="font-bold">${user.display_name||user.id}</div><div class="text-xs opacity-70">${user.provider||'steam'}</div><a class="link" href="${user.profile}" target="_blank" rel="noopener">Open Steam profile</a></div></div>`;
    modal.showModal();
  });
  if (modalCloseX) modalCloseX.addEventListener('click', ()=>{ document.getElementById('appModal')?.close(); });

  if (btnSignout) btnSignout.addEventListener('click', async (e)=>{
    e.preventDefault();
    title.textContent = 'Confirm';
    body.innerHTML = `<div class="mb-4">Sign out of your session?</div><div class="flex justify-end gap-2"><button id="no" class="btn btn-sm">Cancel</button><button id="yes" class="btn btn-sm btn-primary">Sign out</button></div>`;
    modal.showModal();
    document.getElementById('no').onclick = ()=> modal.close();
    document.getElementById('yes').onclick = async ()=>{ try { await fetch('/auth/logout', {method:'POST'}); } catch {} location.href='/'; };
  });

  // Initialize sidebar user section
  (async function initSidebarUser(){
    const { user } = await fetchMe();
    try { window.__ME__ = user || null; } catch {}
    if (user) {
      if (sbSignedOut) sbSignedOut.classList.add('hidden');
      if (sbSignedIn) sbSignedIn.classList.remove('hidden');
      if (sbAvatar && user.avatar) sbAvatar.src = user.avatar;
      if (sbName) sbName.textContent = user.display_name || user.id;
      if (sbProfile) sbProfile.href = user.profile;
      if (sbOpenProfile) sbOpenProfile.onclick = (e)=>{ e.preventDefault(); btnProfile?.click(); };
      // Start presence heartbeat for site-online API
      if (!presenceTimer) {
        const hb = async ()=>{ try { await fetch('/api/v1/presence/heartbeat', {method:'POST'}); } catch {} setTimeout(refreshOnline, 200); };
        presenceTimer = setInterval(hb, 5000);
        hb();
      }
      if (sbSignOut) sbSignOut.onclick = async (e)=>{ e.preventDefault(); try { await fetch('/auth/logout', {method:'POST'}); } catch {} location.href='/'; };
    } else {
      if (sbSignedOut) sbSignedOut.classList.remove('hidden');
      if (sbSignedIn) sbSignedIn.classList.add('hidden');
    }
  })();

  // Players online sidebar — refresh periodically
  async function refreshOnline(){
    try {
      const map = new Map();
      // signed-in site presence
      try {
        const r1 = await fetch('/api/v1/players/site-online');
        const j1 = await r1.json();
        const rows = (j1 && Array.isArray(j1.players)) ? j1.players : [];
        for (const p of rows) {
          const key = p.provider === 'steam' && p.id ? `steam:${p.id}` : `${p.provider}:${p.id}`;
          map.set(key, { name: p.display_name || p.id, avatar: p.avatar, profile: p.profile, signed: true });
        }
      } catch {}
      // in-game players
      try {
        const r2 = await fetch('/api/v1/players/online');
        const j2 = await r2.json();
        const rows2 = (j2 && Array.isArray(j2.players)) ? j2.players : [];
        for (const p of rows2) {
          const sid = p.steam && p.steam.id;
          const key = sid ? `steam:${sid}` : `name:${p.name||''}`;
          const name = (p.steam && p.steam.nickname) || p.name;
          const avatar = p.steam && p.steam.avatar;
          const profile = p.steam && p.steam.url;
          if (!map.has(key)) map.set(key, { name, avatar, profile, signed: false });
          else {
            const cur = map.get(key);
            map.set(key, { name: cur.name || name, avatar: cur.avatar || avatar, profile: cur.profile || profile, signed: cur.signed || false });
          }
        }
      } catch {}
      const players = Array.from(map.values()).sort((a,b)=>{
        if (!!a.signed !== !!b.signed) return a.signed ? -1 : 1;
        return (a.name||'').localeCompare(b.name||'');
      });
      if (onlineList) {
        const items = players.map(p=>{
          const av = p.avatar ? `<img src="${p.avatar}" class="tp-avatar-sm mr-2"/>` : '';
          const name = p.name || 'Player';
          const href = p.profile || '#';
          const dot = p.signed ? '<span class="dot sm ok ml-2 flex-none"></span>' : '';
          return `<a class="flex items-center text-sm mb-1" href="${href}" target="_blank" rel="noopener">${av}<span class="truncate flex-1">${name}</span>${dot}</a>`;
        }).join('');
        onlineList.innerHTML = items || '<span class="opacity-70 text-xs">No players online</span>';
      }
    } catch {
      if (onlineList) onlineList.innerHTML = '<span class="opacity-70 text-xs">No players online</span>';
    }
  }
  refreshOnline();
  setInterval(refreshOnline, 5000);

  // Team Picker: poll for sessions open for me and prompt join
  async function checkTeamPickerInvites(){
    try {
      const r = await fetch('/api/v1/team_picker/open_for_me');
      const j = await r.json();
      const items = (j && Array.isArray(j.items)) ? j.items : [];
      if (!items.length || tpPromptOpen || window.__TP_OPEN__) return;
      // Pick the first session we haven't prompted for recently
      let s = null;
      const now = Date.now();
      for (const it of items) {
        const exp = tpNotified.get(it.session_id) || 0;
        if (now > exp) { s = it; break; }
      }
      if (!s) return;
      const title = document.getElementById('appModalTitle');
      const body = document.getElementById('appModalBody');
      if (title && body) {
        title.textContent = 'Team Picker started';
        const parts = (s.participants||[]).map(p=>{
          const av = (p.steam && p.steam.avatar) ? `<img src="${p.steam.avatar}" class="tp-avatar-sm mr-2"/>` : '';
          const name = (p.steam && p.steam.nickname) || p.id;
          const dot = p.active ? '<span class="dot sm ok ml-2"></span>' : '';
          return `<div class="flex items-center text-sm">${av}<span class="truncate flex-1">${name}</span>${dot}</div>`;
        }).join('');
        body.innerHTML = `<div class="space-y-3">
          <div class="text-sm">A Team Picker was started for this session.</div>
          <div class="card bg-base-100 border border-base-300"><div class="card-body p-3">${parts}</div></div>
          <div class="flex gap-2"><button id="tpOpenFromPrompt" class="btn btn-sm btn-primary">Open</button><button id="tpDismiss" class="btn btn-sm">Dismiss</button></div>
        </div>`;
        const modalEl = document.getElementById('appModal');
        modalEl?.showModal();
        tpPromptOpen = true;
        const openBtn = document.getElementById('tpOpenFromPrompt');
        if (openBtn) openBtn.onclick = async ()=>{
          modalEl?.close(); tpPromptOpen = false;
          try {
            const resp = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.session_id)}`);
            const out = await resp.json();
            if (!out || !out.session) { return; }
            const t = out.session;
            // Reuse card click flow: renderTP and open fully
            try { window.__TP_OPEN__ = s.session_id; } catch {}
            const tTitle=document.getElementById('appModalTitle'); if (tTitle) tTitle.textContent='Team Picker';
            renderTP(t); modalEl?.showModal();
            // Ensure we join the realtime room and begin presence heartbeats when opened via invite
            try { if (socket && window.__REALTIME__) { socket.emit('join', { room: `team_picker:${s.session_id}` }); } } catch {}
            try { await fetch(`/api/v1/team_picker/${encodeURIComponent(s.session_id)}/presence`, {method:'POST', credentials:'same-origin'}); } catch {}
            let tpPresenceTimer = setInterval(async ()=>{ try { await fetch(`/api/v1/team_picker/${encodeURIComponent(s.session_id)}/presence`, {method:'POST', credentials:'same-origin'}); } catch {} }, 10000);
            const onClose = ()=>{ window.__TP_OPEN__ = null; try { if (socket && window.__REALTIME__) { socket.emit('leave', { room: `team_picker:${s.session_id}` }); } } catch {}; if (tpPresenceTimer) { clearInterval(tpPresenceTimer); tpPresenceTimer=null; } modalEl?.removeEventListener('close', onClose); };
            modalEl?.addEventListener('close', onClose);
          } catch {}
        };
        const dismissBtn = document.getElementById('tpDismiss'); if (dismissBtn) dismissBtn.onclick = ()=>{ modalEl?.close(); tpPromptOpen=false; };
        // Remember we showed this prompt for a short time window (2 min)
        tpNotified.set(s.session_id, now + 120000);
      }
    } catch {}
  }
  setInterval(checkTeamPickerInvites, 5000);
  setTimeout(checkTeamPickerInvites, 1000);

  // Mock session button removed
})();


