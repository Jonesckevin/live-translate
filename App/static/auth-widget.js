
(function () {
  'use strict';

  var LOCAL_KEY = 'lt_auth_token';
  var SESSION_KEY = 'lt_auth_token_s';

  function token() {
    return localStorage.getItem(LOCAL_KEY) || sessionStorage.getItem(SESSION_KEY) || '';
  }
  function setToken(t, remember) {
    localStorage.removeItem(LOCAL_KEY);
    sessionStorage.removeItem(SESSION_KEY);
    if (t) {
      if (remember === false) sessionStorage.setItem(SESSION_KEY, t);
      else localStorage.setItem(LOCAL_KEY, t);
    }
  }

  
  
  
  var _requireAuth = document.documentElement.getAttribute('data-lt-require-auth') === 'true';
  var _gated = _requireAuth && !token();   

  
  var _fetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    try {
      var url = typeof input === 'string' ? input : (input && input.url) || '';

      
      
      if (_gated) {
        if (/^\/api\/sessions(\/public)?(\?|$)/.test(url)) {
          return Promise.resolve(new Response(
            JSON.stringify({ sessions: [] }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          ));
        }
      }

      
      if ((url.indexOf('/api/') === 0 || url.indexOf('/auth/') === 0) && token()) {
        init = init || {};
        var headers = new Headers((init && init.headers) ||
          (typeof input !== 'string' && input.headers) || {});
        if (!headers.has('Authorization')) headers.set('Authorization', 'Bearer ' + token());
        init.headers = headers;
      }
    } catch (e) {  }
    return _fetch(input, init);
  };

  
  var cfg = {};                    
  var modalEl = null;
  var headerEl = null;
  var gateEl = null;               
  var modalSetTab = null;

  
  function h(tag, attrs, kids) {
    var e = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      if (k === 'class') e.className = attrs[k];
      else if (k === 'text') e.textContent = attrs[k];
      else if (k.indexOf('on') === 0 && typeof attrs[k] === 'function') e.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) {
      if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return e;
  }

  function showError(msg) {
    var b = document.getElementById('authError');
    if (b) { b.textContent = msg || ''; b.style.display = msg ? 'block' : 'none'; }
  }

  function field(type, ac, placeholder) {
    return h('input', { type: type, class: 'auth-input', autocomplete: ac || 'off',
      placeholder: placeholder || '' });
  }
  function labeled(label, input) {
    return h('label', { class: 'auth-field' }, [h('span', { class: 'auth-label', text: label }), input]);
  }

  
  function openModal() {
    if (!modalEl) return;
    modalEl.classList.add('active');
    modalEl.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open');
  }

  function closeModal() {
    if (cfg.require_auth) return;   
    if (!modalEl) return;
    modalEl.classList.remove('active');
    modalEl.setAttribute('aria-hidden', 'true');
    if (!document.querySelector('.app-modal.active')) document.body.classList.remove('modal-open');
  }

  
  function onAuthenticated(tokenStr, remember) {
    setToken(tokenStr, remember);
    if (window.reconnectSocket) window.reconnectSocket();
    if (gateEl) {
      
      gateEl.classList.add('auth-gate-fading');
      setTimeout(function () {
        if (gateEl && gateEl.parentNode) gateEl.parentNode.removeChild(gateEl);
        gateEl = null;
        document.body.classList.remove('auth-gated');
        window.location.reload();
      }, 400);
    } else {
      window.location.reload();
    }
  }

  
  function submit(path, payload, remember) {
    showError('');
    var method = 'POST';
    var body = payload ? JSON.stringify(payload) : undefined;
    _fetch(path, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: body,
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) { showError(res.d.error || 'Request failed'); return; }
        onAuthenticated(res.d.token, remember);
      }).catch(function () { showError('Network error, please try again'); });
  }

  // --- WebAuthn / Passkey helpers -------------------------------------------

  function webauthnOK() {
    return !!(window.PublicKeyCredential && navigator.credentials);
  }

  var _bufToB64u = function (buf) {
    return btoa(String.fromCharCode.apply(null, new Uint8Array(buf)))
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  };
  var _b64uToBuf = function (s) {
    return Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')),
      function (c) { return c.charCodeAt(0); }).buffer;
  };

  function _credToJSON(cred) {
    var r = cred.response;
    var out = {
      id: cred.id,
      rawId: _bufToB64u(cred.rawId),
      type: cred.type,
      authenticatorAttachment: cred.authenticatorAttachment || null,
      clientExtensionResults: (cred.getClientExtensionResults ? cred.getClientExtensionResults() : {}),
      response: { clientDataJSON: _bufToB64u(r.clientDataJSON) }
    };
    if (r.attestationObject) {
      out.response.attestationObject = _bufToB64u(r.attestationObject);
      out.response.transports = r.getTransports ? r.getTransports() : ['internal'];
    }
    if (r.authenticatorData) {
      out.response.authenticatorData = _bufToB64u(r.authenticatorData);
      out.response.signature = _bufToB64u(r.signature);
      out.response.userHandle = r.userHandle ? _bufToB64u(r.userHandle) : null;
    }
    return out;
  }

  function _toCreationOpts(o) {
    o.challenge = _b64uToBuf(o.challenge);
    if (o.user && o.user.id) o.user.id = _b64uToBuf(o.user.id);
    (o.excludeCredentials || []).forEach(function (c) { c.id = _b64uToBuf(c.id); });
    return o;
  }

  function _toRequestOpts(o) {
    o.challenge = _b64uToBuf(o.challenge);
    (o.allowCredentials || []).forEach(function (c) { c.id = _b64uToBuf(c.id); });
    return o;
  }

  function passkeyRegister(username, email) {
    return _fetch('/auth/passkey/register/options', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username, email: email || '' })
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) { throw new Error(res.d.error || 'Options request failed'); }
        var cid = res.d.cid;
        return navigator.credentials.create({ publicKey: _toCreationOpts(res.d.options) })
          .then(function (cred) {
            return _fetch('/auth/passkey/register/verify', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ cid: cid, credential: _credToJSON(cred) })
            }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); });
          }).then(function (res) {
            if (!res.ok) { throw new Error(res.d.error || 'Verification failed'); }
            return res.d;
          });
      });
  }

  function passkeyLogin() {
    return _fetch('/auth/passkey/login/options', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}'
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) { throw new Error(res.d.error || 'Options request failed'); }
        var cid = res.d.cid;
        return navigator.credentials.get({ publicKey: _toRequestOpts(res.d.options) })
          .then(function (cred) {
            return _fetch('/auth/passkey/login/verify', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ cid: cid, credential: _credToJSON(cred) })
            }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); });
          }).then(function (res) {
            if (!res.ok) { throw new Error(res.d.error || 'Authentication failed'); }
            return res.d;
          });
      });
  }

  
  function buildModal() {
    var registrationEnabled = cfg.registration_enabled;
    var guestEnabled = cfg.guest_login_enabled;
    var required = cfg.require_auth;

    var errorBox = h('div', { class: 'auth-error', id: 'authError' });

    
    var siUser = field('text', 'username', 'Username');
    var siPass = field('password', 'current-password', 'Password');
    var siRemember = h('input', { type: 'checkbox' });
    siRemember.checked = true;
    var signInForm = h('form', {
      class: 'auth-form', onsubmit: function (e) {
        e.preventDefault();
        submit('/auth/login', { username: siUser.value.trim(), password: siPass.value }, siRemember.checked);
      }
    }, [
      labeled('Username', siUser),
      labeled('Password', siPass),
      h('label', { class: 'auth-remember' }, [siRemember, h('span', { text: ' Remember me' })]),
      h('button', { type: 'submit', class: 'btn-primary auth-submit' }, ['Sign In'])
    ]);

    
    var rUser = field('text', 'username', 'Username (3–32 chars)');
    var rEmail = field('email', 'email', 'Email (optional)');
    var rPass = field('password', 'new-password', 'Password (min 12 chars)');
    var rPass2 = field('password', 'new-password', 'Confirm password');
    var registerForm = h('form', {
      class: 'auth-form', onsubmit: function (e) {
        e.preventDefault();
        if (rPass.value !== rPass2.value) { showError('Passwords do not match'); return; }
        submit('/auth/register', { username: rUser.value.trim(), email: rEmail.value.trim(), password: rPass.value }, true);
      }
    }, [
      labeled('Username', rUser),
      labeled('Email (optional)', rEmail),
      labeled('Password (min 12 chars, mixed case + number)', rPass),
      labeled('Confirm password', rPass2),
      h('button', { type: 'submit', class: 'btn-primary auth-submit' }, ['Create account'])
    ]);
    registerForm.style.display = 'none';

    // Passkey sections (only rendered when browser supports WebAuthn)
    var passkeySignInSection = null;
    var passkeyRegSection = null;
    if (webauthnOK()) {
      var pkSignInBtn = h('button', {
        type: 'button', class: 'auth-guest-btn', onclick: function () {
          showError('');
          pkSignInBtn.disabled = true;
          pkSignInBtn.textContent = 'Waiting for passkey\u2026';
          passkeyLogin().then(function (res) {
            onAuthenticated(res.token, true);
          }).catch(function (err) {
            pkSignInBtn.disabled = false;
            pkSignInBtn.textContent = '\uD83D\uDD11 Sign in with Passkey';
            if (err.name !== 'NotAllowedError' && err.name !== 'AbortError') {
              showError(err.message || 'Passkey sign-in failed');
            }
          });
        }
      }, ['\uD83D\uDD11 Sign in with Passkey']);
      passkeySignInSection = h('div', { class: 'auth-passkey-section' }, [
        h('div', { class: 'auth-divider' }, ['or']),
        pkSignInBtn
      ]);
      if (registrationEnabled) {
        var pkRegBtn = h('button', {
          type: 'button', class: 'auth-guest-btn', onclick: function () {
            var uname = rUser.value.trim();
            if (!uname) { showError('Please enter a username first'); return; }
            showError('');
            pkRegBtn.disabled = true;
            pkRegBtn.textContent = 'Waiting for passkey\u2026';
            passkeyRegister(uname, rEmail.value.trim()).then(function (res) {
              onAuthenticated(res.token, true);
            }).catch(function (err) {
              pkRegBtn.disabled = false;
              pkRegBtn.textContent = '\uD83D\uDD11 Register with Passkey';
              if (err.name !== 'NotAllowedError' && err.name !== 'AbortError') {
                showError(err.message || 'Passkey registration failed');
              }
            });
          }
        }, ['\uD83D\uDD11 Register with Passkey']);
        passkeyRegSection = h('div', { class: 'auth-passkey-section' }, [
          h('div', { class: 'auth-divider' }, ['or, skip the password']),
          h('p', { class: 'auth-guest-note' }, ['Use the username (and optional email) above, then confirm with your device biometrics or PIN. No password needed.']),
          pkRegBtn
        ]);
        passkeyRegSection.style.display = 'none';
      }
    }

    var tabSignIn   = h('button', { class: 'auth-tab active', type: 'button', onclick: function () { modalSetTab('signin'); } }, ['Sign In']);
    var tabRegister = h('button', { class: 'auth-tab', type: 'button', onclick: function () { modalSetTab('register'); } }, ['Register']);
    if (!registrationEnabled) tabRegister.style.display = 'none';

    modalSetTab = function (name) {
      var reg = name === 'register';
      tabSignIn.classList.toggle('active', !reg);
      tabRegister.classList.toggle('active', reg);
      signInForm.style.display  = reg ? 'none' : '';
      registerForm.style.display = reg ? '' : 'none';
      if (passkeySignInSection) passkeySignInSection.style.display = reg ? 'none' : '';
      if (passkeyRegSection) passkeyRegSection.style.display = reg ? '' : 'none';
      showError('');
    };

    
    var guestSection = null;
    if (required && guestEnabled) {
      var guestBtn = h('button', {
        class: 'auth-guest-btn', type: 'button',
        onclick: function () {
          showError('');
          guestBtn.disabled = true;
          guestBtn.textContent = 'Creating guest session…';
          _fetch('/auth/guest', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
            .then(function (res) {
              if (!res.ok) {
                showError(res.d.error || 'Guest login failed');
                guestBtn.disabled = false;
                guestBtn.textContent = 'Continue as Guest';
                return;
              }
              onAuthenticated(res.d.token, false);   
            }).catch(function () {
              showError('Network error');
              guestBtn.disabled = false;
              guestBtn.textContent = 'Continue as Guest';
            });
        }
      }, ['Continue as Guest']);
      guestSection = h('div', { class: 'auth-guest-section' }, [
        h('p', { class: 'auth-guest-note' }, [
          'Guest sessions last up to ' + (24) + ' hours and are not saved permanently. ',
          'For persistent history, create an account.'
        ]),
        guestBtn
      ]);
    }

    var intro = required
      ? h('p', { class: 'auth-intro auth-intro-required', text: 'Sign in to use Live Translate.' })
      : h('p', { class: 'auth-intro', text: 'Sign in to save and own your sessions.' });

    var bodyParts = [intro];
    
    if (registrationEnabled) {
      bodyParts.push(h('div', { class: 'auth-tabs' }, [tabSignIn, tabRegister]));
    }
    bodyParts.push(errorBox, signInForm);
    if (passkeySignInSection) bodyParts.push(passkeySignInSection);
    bodyParts.push(registerForm);
    if (passkeyRegSection) bodyParts.push(passkeyRegSection);
    if (guestSection) bodyParts.push(guestSection);

    var body = h('div', { class: 'app-modal-body auth-body' }, bodyParts);
    var headerKids = [h('h2', { text: 'Live Translate — Account' })];
    
    if (!required) {
      headerKids.push(h('button', { class: 'icon-btn', title: 'Close', type: 'button', onclick: closeModal }, ['✕']));
    }
    var hdr = h('div', { class: 'app-modal-header' }, headerKids);
    var dialog = h('div', { class: 'app-modal-dialog auth-dialog' }, [hdr, body]);
    modalEl = h('div', { class: 'app-modal', id: 'authModal', 'aria-hidden': 'true',
      role: 'dialog', 'aria-labelledby': 'authModalHeading' }, [dialog]);
    
    modalEl.addEventListener('click', function (e) { if (!required && e.target === modalEl) closeModal(); });
    document.addEventListener('keydown', function (e) { if (!required && e.key === 'Escape') closeModal(); });
  }

  
  function renderHeader() {
    if (!headerEl) return;
    headerEl.textContent = '';
    if (!token()) {
      headerEl.appendChild(h('button', {
        class: 'btn-secondary auth-signin-btn', type: 'button',
        onclick: function () { if (modalSetTab) modalSetTab('signin'); openModal(); }
      }, ['Sign in']));
      return;
    }
    _fetch('/auth/me', { headers: { 'Authorization': 'Bearer ' + token() } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.user) { setToken(''); renderHeader(); return; }
        renderUserChip(data.user);
      }).catch(function () { });
  }

  function renderUserChip(user) {
    headerEl.textContent = '';
    var menu = h('div', { class: 'auth-menu' }, []);
    if (user.role === 'admin') menu.appendChild(h('a', { class: 'auth-menu-item', href: '/admin' }, ['Admin panel']));
    menu.appendChild(h('a', { class: 'auth-menu-item', href: '/docs' }, ['Docs & Legal']));
    menu.appendChild(h('button', { class: 'auth-menu-item auth-menu-danger', type: 'button', onclick: logout }, ['Log out']));

    var isGuest = user.role === 'guest' || user.is_guest;
    var label = '\uD83D\uDC64 ' + user.username
      + (isGuest ? ' (guest)' : (user.role === 'admin' ? ' (admin)' : ''))
      + ' \u25BE';
    var chip = h('button', {
      class: 'btn-secondary auth-chip' + (isGuest ? ' auth-chip-guest' : ''), type: 'button',
      onclick: function (e) { e.stopPropagation(); menu.classList.toggle('open'); }
    }, [label]);
    headerEl.appendChild(h('div', { class: 'auth-chip-wrap' }, [chip, menu]));
    document.addEventListener('click', function () { menu.classList.remove('open'); });
  }

  function logout() {
    _fetch('/auth/logout', { method: 'POST', headers: { 'Authorization': 'Bearer ' + token() } })
      .finally(function () { setToken(''); window.location.reload(); });
  }

  
  function buildGate(registrationEnabled) {
    var gateButtonText = registrationEnabled ? 'Sign In / Register' : 'Sign In';
    gateEl = h('div', { class: 'auth-gate', id: 'authGate', 'aria-live': 'polite' }, [
      h('div', { class: 'auth-gate-card' }, [
        h('div', { class: 'auth-gate-logo' }, [h('span', { class: 'auth-gate-lt', text: 'LT' })]),
        h('h1', { class: 'auth-gate-title', text: 'Live Translate' }),
        h('p',  { class: 'auth-gate-sub',   text: 'Sign in to get started' }),
        h('button', {
          class: 'btn-primary auth-gate-open', type: 'button', text: gateButtonText,
          onclick: openModal
        })
      ])
    ]);
    document.body.appendChild(gateEl);
    document.body.classList.add('auth-gated');
  }

  
  function init() {
    _fetch('/api/config').then(function (r) { return r.json(); }).then(function (config) {
      cfg = (config && config.features) || {};
      if (!cfg.auth_enabled) return;    

      headerEl = document.getElementById('authHeader');
      if (!headerEl) return;
      headerEl.style.display = 'flex';

      buildModal();
      document.body.appendChild(modalEl);

      if (cfg.require_auth && !token()) {
        
        buildGate(cfg.registration_enabled);
        openModal();
      } else {
        renderHeader();
      }
    }).catch(function () { });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
