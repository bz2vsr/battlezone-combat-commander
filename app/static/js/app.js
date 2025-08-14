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
      `;
      card.onclick = async () => {
        try {
          const res = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`);
          const data = await res.json();
          mTitle.textContent = 'Team Picker';
          const sess = data && data.session;
          if (!sess) {
            // Gate: require PreGame and both commanders signed in
            const isPre = (s.state === 'PreGame');
            const needTwo = '<div class="text-xs opacity-70">Team Picker requires both commanders to be signed in.</div>';
            mBody.innerHTML = `<div class="space-y-4">
              <div class="text-sm opacity-80">No Team Picker has been started for this session yet.</div>
              ${!isPre?'<div class="alert bg-base-200 border border-base-300 text-xs">Team Picker is only available in PreGame.</div>':''}
              ${needTwo}
              <div><button id="tpStart" class="btn btn-sm btn-primary mt-2" ${!isPre?'disabled':''}>Start Team Picker</button></div>
              <div id="tpStartErr" class="text-xs text-error"></div>
            </div>`;
            daisyModal.showModal();
            const btn = document.getElementById('tpStart');
            if (btn) btn.onclick = async ()=>{
              try {
                const resp = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/start`, {method:'POST', headers:{'Content-Type':'application/json'}});
                if (!resp.ok) {
                  let msg = 'Unable to start Team Picker.';
                  try { const j = await resp.json(); if (j && j.error === 'missing_commanders') msg = 'Could not detect two commanders. Team Picker requires two commanders with Steam IDs.'; if (j && j.error === 'not_pregame') msg = 'Team Picker is only available while the game is in PreGame.'; } catch {}
                  const err = document.getElementById('tpStartErr'); if (err) { err.textContent = msg; }
                  return;
                }
              } catch {}
              try { const r = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j = await r.json(); renderTP(j.session); } catch {}
            };
            return;
          }
          renderTP(sess);
          daisyModal.showModal();
        } catch {}
      };

      function renderTP(tp){
        const commander1 = (tp.participants||[]).find(p=>p.role==='commander1');
        const commander2 = (tp.participants||[]).find(p=>p.role==='commander2');
        const c1 = commander1 ? `<div class="flex items-center gap-2">${(commander1.steam&&commander1.steam.avatar)?`<img src="${commander1.steam.avatar}" class="tp-avatar"/>`:''}<span class="text-sm font-medium">${(commander1.steam&&commander1.steam.nickname)||commander1.id}</span></div>` : '';
        const c2 = commander2 ? `<div class="flex items-center gap-2">${(commander2.steam&&commander2.steam.avatar)?`<img src="${commander2.steam.avatar}" class="tp-avatar"/>`:''}<span class="text-sm font-medium">${(commander2.steam&&commander2.steam.nickname)||commander2.id}</span></div>` : '';

        const team1Picks = (tp.picks||[]).filter(p=>p.team_id===1).map(p=>{
          const nick = (p.player&&p.player.steam&&p.player.steam.nickname) || p.player?.name || p.player?.steam_id || 'Player';
          const av = (p.player&&p.player.steam&&p.player.steam.avatar)?`<img src="${p.player.steam.avatar}" class="tp-avatar-sm mr-2"/>`:'';
          return `<div class="flex items-center text-sm">${av}<span class="truncate">${nick}</span></div>`;
        }).join('') || '<span class="opacity-70 text-xs">No picks yet</span>';
        const team2Picks = (tp.picks||[]).filter(p=>p.team_id===2).map(p=>{
          const nick = (p.player&&p.player.steam&&p.player.steam.nickname) || p.player?.name || p.player?.steam_id || 'Player';
          const av = (p.player&&p.player.steam&&p.player.steam.avatar)?`<img src="${p.player.steam.avatar}" class="tp-avatar-sm mr-2"/>`:'';
          return `<div class="flex items-center text-sm">${av}<span class="truncate">${nick}</span></div>`;
        }).join('') || '<span class="opacity-70 text-xs">No picks yet</span>';
        const isMyTurn = (tp.your_role==='commander1' && tp.next_team===1) || (tp.your_role==='commander2' && tp.next_team===2);
        const waitingText = !tp.coin_winner_team ? 'Run coin toss to begin' : (tp.picks_complete ? 'All players selected. Please finalize the roster.' : (isMyTurn? 'Your turn' : `Waiting for ${(tp.next_team===1?(commander1&&((commander1.steam&&commander1.steam.nickname)||commander1.id)):(commander2&&((commander2.steam&&commander2.steam.nickname)||commander2.id))) || 'commander'} to pick`));
        const coin = tp.coin_winner_team? `<span class="badge-soft">Coin: Team ${tp.coin_winner_team}</span>` : '<button id="tpCoin" class="btn btn-xs">Coin toss</button>';
        const commanderIds = new Set([
          commander1 && commander1.id ? String(commander1.id) : '',
          commander2 && commander2.id ? String(commander2.id) : ''
        ]);
        const eligible = (tp.roster||[]).filter(r=>{
          const sid = String(r.steam_id||'');
          if (!sid) return false;
          if (commanderIds.has(sid)) return false; // exclude commanders from pool
          return !(tp.picks||[]).some(p=>p.player && String(p.player.steam_id)===sid);
        });
        const rosterHtml = eligible.map(r=>{ const nick = (r.steam&&r.steam.nickname) || r.name || r.steam_id; const av = (r.steam&&r.steam.avatar)?`<img src="${r.steam.avatar}" class="tp-avatar-sm mr-2"/>`:''; return `<button class="btn btn-xs" data-sid="${r.steam_id}" ${!tp.coin_winner_team?'disabled':''}>${av}<span class="truncate">${nick}</span></button>`; }).join(' ');
        const commandersTop = `
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-0 mb-4 md:mb-6">
            <div class="card bg-base-100 border border-base-300"><div class="card-body p-3">${c1}</div></div>
            <div class="card bg-base-100 border border-base-300"><div class="card-body p-3 flex justify-end">${c2}</div></div>
          </div>`;
        mBody.innerHTML = `
          <div>
            ${commandersTop}
            <div class="flex gap-2 items-center text-sm mt-2 md:mt-3"><span class="badge-soft">${tp.state}</span>${coin}<span class="text-xs opacity-70">${tp.next_team?`Team ${tp.next_team}'s turn`:(!tp.coin_winner_team?'Run coin toss to begin':'')}</span></div>
            ${ (tp.accepted && (tp.accepted.commander1 || tp.accepted.commander2) && !(tp.accepted.commander1 && tp.accepted.commander2)) ? `<div class=\"alert bg-base-200 border border-base-300 text-xs mt-2\">Waiting for the other commander to finalize…</div>` : ''}
            <div class="alert bg-base-200 border border-base-300 text-xs mt-2 md:mt-3">${waitingText}</div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-5 mt-3 md:mt-4">
              <div class="card bg-base-100 border border-base-300"><div class="card-body p-3">
                <div class="flex items-center justify-between mb-2">
                  <div class="text-sm opacity-70">Team 1</div>
                </div>
                ${team1Picks}
              </div></div>
              <div class="card bg-base-100 border border-base-300"><div class="card-body p-3">
                <div class="flex items-center justify-between mb-2">
                  <div class="text-sm opacity-70">Team 2</div>
                </div>
                ${team2Picks}
              </div></div>
            </div>
            <div class="flex flex-wrap gap-2 mt-3 md:mt-4" id="tpRoster">${rosterHtml || '<span class="opacity-70 text-sm">No eligible players</span>'}</div>
            <div class="flex gap-2 mt-4 md:mt-5">
              <button id="tpPickRandom" class="btn btn-sm" ${eligible.length===0?'disabled':''}>Pick random</button>
              <button id="tpFinalize" class="btn btn-sm btn-primary" ${tp.picks_complete?'' : 'disabled'}>Finalize</button>
              <button id="tpRestart" class="btn btn-sm">Restart</button>
            </div>
            <div id="tpErr" class="text-xs text-error mt-2"></div>
          </div>`;
        const btnCoin = document.getElementById('tpCoin');
        if (btnCoin) btnCoin.onclick = async ()=>{ const b=btnCoin; b.disabled=true; b.textContent='Tossing…'; setTimeout(async ()=>{ try { await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/coin_toss`, {method:'POST'}); } catch {}; try { const r=await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j=await r.json(); renderTP(j.session);} catch {} }, 1200); };
        const roster = document.getElementById('tpRoster');
        if (roster) roster.querySelectorAll('button[data-sid]').forEach(btn=>{ btn.addEventListener('click', async ()=>{ const sid = btn.getAttribute('data-sid'); if(!sid) return; btn.disabled = true; try { await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/pick`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({player_steam_id: sid})}); } catch {}; try { const r=await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j=await r.json(); renderTP(j.session);} catch {} }); });
        const canAct = tp.your_role==='commander1' || tp.your_role==='commander2';
        const btnFin = document.getElementById('tpFinalize'); if (btnFin) { if (!canAct) btnFin.disabled = true; btnFin.onclick = async ()=>{ try { const resp = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/finalize`, {method:'POST'}); if(!resp.ok){ const err=document.getElementById('tpErr'); if(err){ err.textContent = resp.status===401?'Please sign in to finalize.': (resp.status===403?'Only commanders can finalize.':'Unable to finalize.'); } return;} } catch {}; try { const r=await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j=await r.json(); renderTP(j.session);} catch {} }; }
        const btnRestart = document.getElementById('tpRestart'); if (btnRestart) { if (!canAct) btnRestart.disabled = true; btnRestart.onclick = async ()=>{ btnRestart.disabled=true; try { const resp = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/restart`, {method:'POST'}); if(!resp.ok){ const err=document.getElementById('tpErr'); if(err){ err.textContent = resp.status===401?'Please sign in to restart Team Picker.': (resp.status===403?'Only commanders can restart Team Picker.':'Unable to restart.'); } btnRestart.disabled=false; return;} } catch {}; try { const r=await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j=await r.json(); renderTP(j.session);} catch {} }; }
        const btnRand = document.getElementById('tpPickRandom'); if (btnRand) { if (!canAct) btnRand.disabled = true; btnRand.onclick = async ()=>{ if (!eligible || eligible.length===0) return; btnRand.disabled = true; const pick = eligible[Math.floor(Math.random()*eligible.length)]; try { const resp = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/pick`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({player_steam_id: pick.steam_id})}); if(!resp.ok){ const err=document.getElementById('tpErr'); if(err){ err.textContent = resp.status===401?'Please sign in to pick.': (resp.status===403?'It is not your turn to pick.':'Unable to pick.'); } btnRand.disabled=false; return;} } catch {}; try { const r=await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j=await r.json(); renderTP(j.session);} catch {} }; }

        // If single-user testing and it's the other commander's turn, auto-pick after a short delay
        try {
          const yourRole = tp.your_role;
          const nextTeam = tp.next_team;
          if (tp.coin_winner_team && eligible.length > 0) {
            if ((yourRole==='commander1' && nextTeam===2) || (yourRole==='commander2' && nextTeam===1) || (!yourRole && nextTeam===2)) {
              setTimeout(async ()=>{
                try { await fetch(`/admin/dev/team_picker/${encodeURIComponent(s.id)}/auto_pick`, {method:'POST'}); } catch {}
                try { const r=await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j=await r.json(); renderTP(j.session);} catch {}
              }, 800);
            }
          }
        } catch {}
      }
      grid.appendChild(card);
    });
    // no-op: no skeleton placeholder behavior
  }

  function url() {
    const p = new URLSearchParams();
    if (fState && fState.value) p.set('state', fState.value);
    if (fMin && fMin.value && +fMin.value>0) p.set('min_players', fMin.value);
    if (fQ && fQ.value) p.set('q', fQ.value);
    if (fMod && fMod.value) p.set('mod', fMod.value);
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
    try { if (typeof window.__REALTIME__ === 'string' && window.__REALTIME__ !== 'true') return; } catch {}
    try {
      // eslint-disable-next-line no-undef
      socket = io('/', { transports: ['websocket', 'polling'] });
      socket.on('connect', ()=>{ if (!sseLive) { if (connDot) connDot.className='dot ok'; if (connText) connText.textContent='Live'; } });
      socket.on('sessions:update', ()=>{ fetchOnce(); });
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
  const btnCreateMock = document.getElementById('createMockSession');
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
      if (!items.length) return;
      // Show a minimal prompt for the first one
      const s = items[0];
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
        document.getElementById('appModal')?.showModal();
        const openBtn = document.getElementById('tpOpenFromPrompt'); if (openBtn) openBtn.onclick = ()=>{ document.getElementById('appModal')?.close(); try { fetch(`/api/v1/team_picker/${encodeURIComponent(s.session_id)}` ).then(r=>r.json()).then(j=>{ const t=j.session; if(!t) return; const tTitle=document.getElementById('appModalTitle'); const tBody=document.getElementById('appModalBody'); if(tTitle) tTitle.textContent='Team Picker'; if(tBody){ /* reuse existing renderer */ } }); } catch {} };
        const dismissBtn = document.getElementById('tpDismiss'); if (dismissBtn) dismissBtn.onclick = ()=>{ document.getElementById('appModal')?.close(); };
      }
    } catch {}
  }
  setInterval(checkTeamPickerInvites, 7000);

  if (btnCreateMock) btnCreateMock.addEventListener('click', async (e)=>{
    e.preventDefault();
    try {
      const original = btnCreateMock.textContent;
      btnCreateMock.textContent = 'Loading…';
      btnCreateMock.disabled = true;
      const r = await fetch('/admin/dev/mock/session', {method:'POST'});
      const j = await r.json();
      if (j && j.ok && j.session_id) {
        // refresh grid to include mock session
        try { await fetch('/api/v1/sessions/current'); } catch {}
      }
    } catch {}
    finally {
      btnCreateMock.textContent = 'Create mock session';
      btnCreateMock.disabled = false;
    }
  });
})();


