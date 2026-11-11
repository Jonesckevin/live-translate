/* Read-only live caption viewer for Live Translate.
 * Loaded by live.html (external file so it passes the app's CSP script-src 'self'). */
(function () {
    'use strict';

    var body = document.body;
    var SESSION_ID = body ? body.getAttribute('data-session-id') : '';
    // The viewer is anonymous, so the signed share code must accompany both the
    // history fetch and the socket join or the server rejects the read.
    var SHARE_CODE = body ? (body.getAttribute('data-share-code') || '') : '';
    var ERROR = body ? body.getAttribute('data-error') === '1' : false;
    var container = document.getElementById('captions');
    var seen = {};
    // Display names stored on the session, so a rename shows up here too.
    var speakerNames = {};
    var renderedCount = 0;

    function showStatusMessage(message) {
        // Never replace real captions with a status line.
        if (renderedCount > 0) return;
        var existing = container.querySelector('.empty, .error');
        if (existing) {
            existing.textContent = message;
            return;
        }
        var el = document.createElement('div');
        el.className = 'error';
        el.textContent = message;
        container.appendChild(el);
    }

    function langName(code) { return (code || '?').toUpperCase(); }

    function humanizeSpeakerKey(key) {
        if (key === 'left' || key === 'right') return key.charAt(0).toUpperCase() + key.slice(1);
        if (key.indexOf('speaker_') === 0) {
            var suffix = key.slice('speaker_'.length);
            return /^\d+$/.test(suffix) ? 'Speaker ' + suffix : key;
        }
        return key.charAt(0).toUpperCase() + key.slice(1);
    }

    function speakerLabelFor(msg) {
        var key = (msg.speaker || msg.panel || '').trim();
        if (key && speakerNames[key]) return speakerNames[key];
        return key ? humanizeSpeakerKey(key) : 'Speaker';
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function appendMsg(msg) {
        if (!msg) return;
        var key = (msg.timestamp || '') + '|' + (msg.source_text || '') + '|' + (msg.translated_text || '');
        if (seen[key]) return;
        seen[key] = true;

        var empty = container.querySelector('.empty');
        if (empty) empty.remove();
        renderedCount += 1;

        var el = document.createElement('div');
        el.className = 'msg';
        var speakerLabel = speakerLabelFor(msg);
        var t = msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : '';
        el.innerHTML = [
            '<div class="speaker">' + escapeHtml(speakerLabel) + '</div>',
            '<div class="source">' + escapeHtml(msg.source_text || '') + '</div>',
            msg.translated_text ? '<div class="translated">' + escapeHtml(msg.translated_text) + '</div>' : '',
            '<div class="meta">' + langName(msg.source_language) + ' → ' + langName(msg.target_language) + ' · ' + t + '</div>'
        ].join('');
        container.appendChild(el);
        container.scrollTop = container.scrollHeight;
    }

    if (ERROR || !SESSION_ID) {
        return;
    }

    var socket = io({ transports: ['websocket', 'polling'] });
    socket.on('connect', function () {
        socket.emit('join_session_room', { session_id: SESSION_ID, share_code: SHARE_CODE });
    });
    socket.on('session_join_denied', function (payload) {
        showStatusMessage((payload && payload.error) || 'Not authorised to view this session.');
    });
    socket.on('session_new_message', function (msg) { if (msg) appendMsg(msg); });

    // Load existing history on open.
    var historyUrl = '/api/sessions/' + SESSION_ID +
        (SHARE_CODE ? '?share=' + encodeURIComponent(SHARE_CODE) : '');
    fetch(historyUrl)
        .then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(function (d) {
            speakerNames = (d && d.speaker_names) || {};
            (d.messages || []).forEach(appendMsg);
        })
        .catch(function () {
            showStatusMessage('Could not load this session. The link may have expired, or sharing may have been turned off.');
        });
})();
