/* Read-only live caption viewer for Live Translate.
 * Loaded by live.html (external file so it passes the app's CSP script-src 'self'). */
(function () {
    'use strict';

    var body = document.body;
    var SESSION_ID = body ? body.getAttribute('data-session-id') : '';
    var ERROR = body ? body.getAttribute('data-error') === '1' : false;
    var container = document.getElementById('captions');
    var seen = {};

    function langName(code) { return (code || '?').toUpperCase(); }

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

        var el = document.createElement('div');
        el.className = 'msg';
        var speaker = msg.speaker || msg.panel || 'Speaker';
        var speakerLabel = speaker.charAt(0).toUpperCase() + speaker.slice(1);
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
        socket.emit('join_session_room', { session_id: SESSION_ID });
    });
    socket.on('session_new_message', function (msg) { if (msg) appendMsg(msg); });

    // Load existing history on open.
    fetch('/api/sessions/' + SESSION_ID)
        .then(function (r) { return r.json(); })
        .then(function (d) { (d.messages || []).forEach(appendMsg); })
        .catch(function () {});
})();
