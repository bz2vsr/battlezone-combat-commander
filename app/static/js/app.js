// Minimal JS bridge for DaisyUI modal and profile/logout actions
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


