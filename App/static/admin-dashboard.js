
(function () {
  'use strict';

  var LOCAL_KEY = 'lt_auth_token';
  var SESSION_KEY = 'lt_auth_token_s';
  var msg = document.getElementById('msg');
  var loginEl = document.getElementById('login');
  var panelEl = document.getElementById('panel');
  var topbar = document.getElementById('topbarRight');

  function token() { return localStorage.getItem(LOCAL_KEY) || sessionStorage.getItem(SESSION_KEY) || ''; }
  function setToken(t) {
    localStorage.removeItem(LOCAL_KEY); sessionStorage.removeItem(SESSION_KEY);
    if (t) localStorage.setItem(LOCAL_KEY, t);
  }
  function note(text, isError) { msg.textContent = text || ''; msg.style.color = isError ? '#fca5a5' : '#86efac'; }

  function api(path, options) {
    options = options || {};
    options.headers = Object.assign({ 'Authorization': 'Bearer ' + token() }, options.headers || {});
    if (options.body && typeof options.body !== 'string' && !(options.body instanceof FormData)) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }
    return fetch(path, options).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        return { ok: r.ok, status: r.status, data: data };
      });
    });
  }

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function cell(text) { var td = document.createElement('td'); td.textContent = (text == null ? '' : String(text)); return td; }
  function mkBtn(label, fn, cls) { var b = el('button', cls || 'btn-secondary', label); b.type = 'button'; b.addEventListener('click', fn); return b; }

  function show(authed) {
    loginEl.classList.toggle('hidden', authed);
    panelEl.classList.toggle('hidden', !authed);
    if (topbar) topbar.style.display = authed ? 'flex' : 'none';
  }

  function login() {
    var u = document.getElementById('username').value.trim();
    var p = document.getElementById('password').value;
    fetch('/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p })
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) { note(res.d.error || 'Login failed', true); return; }
        if (res.d.user && res.d.user.role !== 'admin') { note('That account is not an administrator', true); return; }
        setToken(res.d.token); note(''); boot();
      }).catch(function () { note('Network error', true); });
  }

  function logout() { api('/auth/logout', { method: 'POST' }).finally(function () { setToken(''); show(false); }); }

  

  function loadStats() {
    return api('/api/admin/stats').then(function (r) {
      if (!r.ok) return;
      var s = r.data, host = document.getElementById('stats'); host.innerHTML = '';
      [['Users', s.users], ['Sessions', s.sessions], ['Public', s.public_sessions]].forEach(function (pair) {
        var d = el('div', 'admin-stat');
        d.appendChild(el('b', null, pair[1] != null ? pair[1] : '-'));
        d.appendChild(el('span', null, pair[0]));
        host.appendChild(d);
      });
    });
  }

  

  function loadSettings() {
    return api('/api/admin/settings').then(function (r) {
      if (!r.ok) return;
      var s = r.data, host = document.getElementById('settings'); host.innerHTML = '';
      Object.keys(s).forEach(function (key) {
        var val = s[key];
        var wrap = el('label', 'admin-toggle');
        var input;
        if (typeof val === 'boolean') {
          input = document.createElement('input'); input.type = 'checkbox'; input.checked = val;
        } else {
          input = document.createElement('input'); input.type = 'number'; input.value = val; input.min = '0';
          input.className = 'auth-input admin-num';
        }
        input.dataset.key = key;
        wrap.appendChild(input);
        wrap.appendChild(el('span', null, ' ' + key));
        host.appendChild(wrap);
      });
    });
  }

  function saveSettings() {
    var payload = {};
    document.querySelectorAll('#settings [data-key]').forEach(function (input) {
      payload[input.dataset.key] = input.type === 'checkbox' ? input.checked : (parseInt(input.value, 10) || 0);
    });
    api('/api/admin/settings', { method: 'POST', body: payload }).then(function (r) {
      note(r.ok ? 'Settings saved' : (r.data.error || 'Save failed'), !r.ok);
    });
  }

  

  var _users = [];   

  function loadUsers() {
    return api('/api/admin/users').then(function (r) {
      if (!r.ok) return;
      _users = r.data.users || [];
      var tb = document.getElementById('users'); tb.innerHTML = '';
      _users.forEach(function (u) {
        var tr = document.createElement('tr');
        tr.appendChild(cell(u.username));
        tr.appendChild(cell(u.role));
        tr.appendChild(cell(u.status));
        var actions = el('td', 'admin-actions');
        var roleOther = u.role === 'admin' ? 'user' : 'admin';
        var statusOther = u.status === 'active' ? 'banned' : 'active';
        actions.appendChild(mkBtn('Make ' + roleOther, function () {
          api('/api/admin/users/' + u.user_id + '/role', { method: 'POST', body: { role: roleOther } }).then(refresh);
        }));
        actions.appendChild(mkBtn(statusOther === 'banned' ? 'Ban' : 'Unban', function () {
          api('/api/admin/users/' + u.user_id + '/status', { method: 'POST', body: { status: statusOther } }).then(refresh);
        }));
        actions.appendChild(mkBtn('Delete', function () {
          if (!confirm('Delete user "' + u.username + '"? This cannot be undone.')) return;
          api('/api/admin/users/' + u.user_id, { method: 'DELETE' }).then(function (res) {
            if (!res.ok) note(res.data.error || 'Delete failed', true); else refresh();
          });
        }, 'btn-danger'));
        tr.appendChild(actions);
        tb.appendChild(tr);
      });
    });
  }

  

  var _openSessionId = null;
  var _sessions = [];

  function loadSessions() {
    return api('/api/admin/sessions').then(function (r) {
      if (!r.ok) return;
      _sessions = r.data.sessions || [];
      var tb = document.getElementById('sessions'); tb.innerHTML = '';
      _sessions.forEach(function (s) {
        var tr = document.createElement('tr');
        tr.style.cursor = 'pointer';

        
        var iconTd = document.createElement('td');
        if (s.icon_url) {
          var img = document.createElement('img');
          img.src = s.icon_url; img.className = 'sd-row-icon'; img.alt = '';
          iconTd.appendChild(img);
        }
        tr.appendChild(iconTd);
        tr.appendChild(cell(s.title));
        tr.appendChild(cell(s.owner_username || '-'));
        tr.appendChild(cell(s.visibility));
        tr.appendChild(cell(s.message_count || 0));

        var actions = el('td', 'admin-actions');
        var editBtn = mkBtn('Manage', function (e) { e.stopPropagation(); openDetail(s.id); });
        actions.appendChild(editBtn);
        actions.appendChild(mkBtn('Delete', function (e) {
          e.stopPropagation();
          if (!confirm('Delete session "' + s.title + '"? This cannot be undone.')) return;
          if (_openSessionId === s.id) closeDetail();
          api('/api/admin/sessions/' + s.id, { method: 'DELETE' }).then(function (res) {
            if (!res.ok) note(res.data.error || 'Delete failed', true);
            else { note('Session deleted'); refresh(); }
          });
        }, 'btn-danger'));
        tr.appendChild(actions);
        tr.addEventListener('click', function () { openDetail(s.id); });
        tb.appendChild(tr);
      });

      
      if (_openSessionId) {
        var still = _sessions.find(function (s) { return s.id === _openSessionId; });
        if (still) openDetail(_openSessionId); else closeDetail();
      }
    });
  }

  function fmt(iso) {
    if (!iso) return '-';
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
  }

  function openDetail(sessionId) {
    _openSessionId = sessionId;
    api('/api/admin/sessions/' + sessionId).then(function (r) {
      if (!r.ok) { note(r.data.error || 'Failed to load session', true); return; }
      var s = r.data;
      var detail = document.getElementById('sessionDetail');
      detail.classList.remove('hidden');

      
      document.getElementById('sdTitle').textContent = s.title || '';

      
      var preview = document.getElementById('sdIconPreview');
      preview.src = s.icon_url ? s.icon_url + '&_t=' + Date.now() : '';
      preview.style.display = s.icon_url ? 'block' : 'none';

      
      document.getElementById('sdTitleInput').value = s.title || '';

      
      document.getElementById('sdVisibility').value = s.visibility || 'public';

      
      document.getElementById('sdOwnerDisplay').textContent =
        s.owner_username ? (s.owner_username + ' (' + (s.owner_id || '') + ')') : '— anonymous';

      
      var sel = document.getElementById('sdOwnerSelect');
      sel.innerHTML = '<option value="">(no owner — anonymous)</option>';
      _users.forEach(function (u) {
        var opt = document.createElement('option');
        opt.value = u.user_id;
        opt.textContent = u.username;
        if (u.user_id === s.owner_id) opt.selected = true;
        sel.appendChild(opt);
      });

      
      document.getElementById('sdId').textContent = s.id || sessionId;
      document.getElementById('sdMsgCount').textContent = (s.messages || []).length;
      document.getElementById('sdCreated').textContent = fmt(s.created_at);
      document.getElementById('sdUpdated').textContent = fmt(s.updated_at);
    });
  }

  function closeDetail() {
    _openSessionId = null;
    document.getElementById('sessionDetail').classList.add('hidden');
  }

  function patchSession(payload) {
    if (!_openSessionId) return;
    api('/api/admin/sessions/' + _openSessionId, { method: 'PATCH', body: payload })
      .then(function (r) {
        if (!r.ok) { note(r.data.error || 'Update failed', true); return; }
        note('Session updated');
        loadSessions();
      });
  }

  function uploadIcon() {
    var file = document.getElementById('sdIconFile').files[0];
    if (!file || !_openSessionId) return;
    var fd = new FormData();
    fd.append('file', file);
    api('/api/admin/sessions/' + _openSessionId + '/icon', { method: 'POST', body: fd })
      .then(function (r) {
        if (!r.ok) { note(r.data.error || 'Icon upload failed', true); return; }
        note('Icon updated');
        document.getElementById('sdIconFile').value = '';
        loadSessions();
      });
  }

  

  function refresh() { return Promise.all([loadStats(), loadUsers(), loadSessions()]); }

  function boot() {
    api('/auth/me').then(function (r) {
      if (!r.ok || !r.data.user || r.data.user.role !== 'admin') { show(false); return; }
      document.getElementById('whoami').textContent = r.data.user.username;
      show(true);
      loadSettings(); refresh();
    });
  }

  document.getElementById('loginBtn').addEventListener('click', login);
  document.getElementById('logoutBtn').addEventListener('click', logout);
  document.getElementById('saveSettings').addEventListener('click', saveSettings);
  document.getElementById('password').addEventListener('keydown', function (e) { if (e.key === 'Enter') login(); });
  document.getElementById('closeDetail').addEventListener('click', closeDetail);

  document.getElementById('sdSaveTitle').addEventListener('click', function () {
    var v = document.getElementById('sdTitleInput').value.trim();
    if (!v) { note('Title cannot be empty', true); return; }
    patchSession({ title: v });
  });
  document.getElementById('sdSaveVisibility').addEventListener('click', function () {
    patchSession({ visibility: document.getElementById('sdVisibility').value });
  });
  document.getElementById('sdSaveOwner').addEventListener('click', function () {
    var v = document.getElementById('sdOwnerSelect').value;
    patchSession({ owner_id: v || null });
  });
  document.getElementById('sdIconFile').addEventListener('change', uploadIcon);
  document.getElementById('sdIconDelete').addEventListener('click', function () {
    if (!_openSessionId) return;
    if (!confirm('Remove the icon from this session?')) return;
    api('/api/admin/sessions/' + _openSessionId + '/icon', { method: 'DELETE' })
      .then(function (r) {
        if (!r.ok) { note(r.data.error || 'Delete failed', true); return; }
        note('Icon removed');
        loadSessions();
      });
  });

  if (token()) boot(); else show(false);
})();
