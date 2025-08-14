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

  function render(data) {
    if (!grid) return;
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
            mBody.innerHTML = `<div class="space-y-3">
              <div class="text-sm opacity-80">No Team Picker is active for this session.</div>
              <button id="tpStart" class="btn btn-sm btn-primary">Start Team Picker</button>
            </div>`;
            daisyModal.showModal();
            const btn = document.getElementById('tpStart');
            if (btn) btn.onclick = async ()=>{
              try { await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/start`, {method:'POST', headers:{'Content-Type':'application/json'}}); } catch {}
              try { const r = await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j = await r.json(); renderTP(j.session); } catch {}
            };
            return;
          }
          renderTP(sess);
          daisyModal.showModal();
        } catch {}
      };

      function renderTP(tp){
        const picks = (tp.picks||[]).map(p=>`<div class="flex items-center justify-between text-sm"><span class="opacity-70">#${p.order}</span><span>Team ${p.team_id}</span><span class="truncate">${(p.player&&p.player.steam&&p.player.steam.nickname)||p.player.steam_id}</span></div>`).join('');
        const commander1 = (tp.participants||[]).find(p=>p.role==='commander1');
        const commander2 = (tp.participants||[]).find(p=>p.role==='commander2');
        const c1 = commander1 ? `<div class="flex items-center gap-2">${(commander1.steam&&commander1.steam.avatar)?`<img src="${commander1.steam.avatar}" class="tp-avatar"/>`:''}<span class="text-sm">Commander 1: ${(commander1.steam&&commander1.steam.nickname)||commander1.id}</span></div>` : '';
        const c2 = commander2 ? `<div class="flex items-center gap-2">${(commander2.steam&&commander2.steam.avatar)?`<img src="${commander2.steam.avatar}" class="tp-avatar"/>`:''}<span class="text-sm">Commander 2: ${(commander2.steam&&commander2.steam.nickname)||commander2.id}</span></div>` : '';
        const isMyTurn = (tp.your_role==='commander1' && tp.next_team===1) || (tp.your_role==='commander2' && tp.next_team===2);
        const waitingText = !tp.coin_winner_team ? 'Run coin toss to begin' : (isMyTurn? 'Your turn' : `Waiting for ${(tp.next_team===1?(commander1&&((commander1.steam&&commander1.steam.nickname)||commander1.id)):(commander2&&((commander2.steam&&commander2.steam.nickname)||commander2.id))) || 'commander'} to pick`);
        const coin = tp.coin_winner_team? `<span class="badge-soft">Coin: Team ${tp.coin_winner_team}</span>` : '<button id="tpCoin" class="btn btn-xs">Coin toss</button>';
        const eligible = (tp.roster||[]).filter(r=>r.steam_id && !(tp.picks||[]).some(p=>p.player&&p.player.steam_id===String(r.steam_id)));
        const rosterHtml = eligible.map(r=>{ const nick = (r.steam&&r.steam.nickname) || r.name || r.steam_id; const av = (r.steam&&r.steam.avatar)?`<img src="${r.steam.avatar}" class="tp-avatar-sm mr-2"/>`:''; return `<button class="btn btn-xs" data-sid="${r.steam_id}" ${!tp.coin_winner_team?'disabled':''}>${av}<span class="truncate">${nick}</span></button>`; }).join(' ');
        mBody.innerHTML = `
          <div class="space-y-3">
            <div class="flex items-center justify-between">${c1}${c2}</div>
            <div class="flex gap-2 items-center text-sm"><span class="badge-soft">${tp.state}</span>${coin}<span class="text-xs opacity-70">${tp.next_team?`Team ${tp.next_team}'s turn`:(!tp.coin_winner_team?'Run coin toss to begin':'')}</span></div>
            <div class="alert bg-base-200 border border-base-300 text-xs">${waitingText}</div>
            <div class="card bg-base-100 border border-base-300"><div class="card-body p-3">${picks || '<span class="opacity-70 text-sm">No picks yet</span>'}</div></div>
            <div class="flex flex-wrap gap-2" id="tpRoster">${rosterHtml || '<span class="opacity-70 text-sm">No eligible players</span>'}</div>
            <div class="flex gap-2">
              <button id="tpFinalize" class="btn btn-sm">Finalize</button>
              ${location.hostname==='localhost'? '<button id="tpAuto" class="btn btn-sm">Auto-pick opponent</button>' : ''}
            </div>
          </div>`;
        const btnCoin = document.getElementById('tpCoin');
        if (btnCoin) btnCoin.onclick = async ()=>{ const b=btnCoin; b.disabled=true; b.textContent='Tossing…'; setTimeout(async ()=>{ try { await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/coin_toss`, {method:'POST'}); } catch {}; try { const r=await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j=await r.json(); renderTP(j.session);} catch {} }, 1200); };
        const roster = document.getElementById('tpRoster');
        if (roster) roster.querySelectorAll('button[data-sid]').forEach(btn=>{ btn.addEventListener('click', async ()=>{ const sid = btn.getAttribute('data-sid'); if(!sid) return; btn.disabled = true; try { await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/pick`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({player_steam_id: sid})}); } catch {}; try { const r=await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j=await r.json(); renderTP(j.session);} catch {} }); });
        const btnFin = document.getElementById('tpFinalize'); if (btnFin) btnFin.onclick = async ()=>{ try { await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}/finalize`, {method:'POST'}); } catch {}; try { const r=await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j=await r.json(); renderTP(j.session);} catch {} };
        const btnAuto = document.getElementById('tpAuto'); if (btnAuto) btnAuto.onclick = async ()=>{ try { await fetch(`/admin/dev/team_picker/${encodeURIComponent(s.id)}/auto_pick`, {method:'POST'}); } catch {}; try { const r=await fetch(`/api/v1/team_picker/${encodeURIComponent(s.id)}`); const j=await r.json(); renderTP(j.session);} catch {} };
      }
      grid.appendChild(card);
    });
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

  async function fetchMe(){ try { const r = await fetch('/api/v1/me'); return await r.json(); } catch { return {user:null}; } }

  if (btnProfile) btnProfile.addEventListener('click', async (e)=>{
    e.preventDefault();
    const { user } = await fetchMe(); if (!user) return;
    title.textContent = 'Your account';
    const avatar = user.avatar ? `<img src="${user.avatar}" class="w-16 h-16 rounded-full border border-base-300 mr-3"/>` : '';
    body.innerHTML = `<div class="flex items-center">${avatar}<div><div class="font-bold">${user.display_name||user.id}</div><div class="text-xs opacity-70">${user.provider||'steam'}</div><a class="link" href="${user.profile}" target="_blank" rel="noopener">Open Steam profile</a></div></div>`;
    modal.showModal();
  });

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
      if (sbSignOut) sbSignOut.onclick = async (e)=>{ e.preventDefault(); try { await fetch('/auth/logout', {method:'POST'}); } catch {} location.href='/'; };
    } else {
      if (sbSignedOut) sbSignedOut.classList.remove('hidden');
      if (sbSignedIn) sbSignedIn.classList.add('hidden');
    }
  })();

  if (btnCreateMock) btnCreateMock.addEventListener('click', async (e)=>{
    e.preventDefault();
    try {
      const r = await fetch('/admin/dev/mock/session', {method:'POST'});
      const j = await r.json();
      if (j && j.ok && j.session_id) {
        // refresh grid to include mock session
        try { await fetch('/api/v1/sessions/current'); } catch {}
      }
    } catch {}
  });
})();


