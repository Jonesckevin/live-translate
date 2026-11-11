/**
 * Live Translate - inline SVG icon set
 * ====================================
 * Replaces the emoji that used to stand in for control affordances (the
 * hamburger, mic, TTS speaker, send arrow, gear, trash, refresh, warning...).
 * Emoji render differently on every platform, are full-colour glyphs in a
 * matte monochrome UI, and cannot inherit the accent colour -- which is a
 * large part of why the app read as "cartoon" rather than as a tool.
 *
 * Icons are stroked paths on a 24x24 grid that inherit `currentColor`, so a
 * button's existing colour rules keep working unchanged (including hover and
 * the `[data-state]`/`.active` variants).
 *
 * Usage
 * -----
 *   Static markup:  <button><span data-icon="mic"></span> Start</button>
 *                   (hydrated automatically on DOMContentLoaded)
 *   Dynamic markup: ` <button>\${Icons.svg('trash')} Delete</button> `
 *   After inject:   container.innerHTML = html; Icons.hydrate(container);
 *
 * Only prose keeps literal emoji; anything that behaves like a control gets
 * an icon here.
 */
(function () {
    'use strict';

    /* Stroked because the UI is monochrome line-work; `filled` marks the few
       glyphs whose shape only reads correctly as a solid form (stop, record
       dot). Every path assumes a 24x24 viewBox. */
    const PATHS = {
        menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
        close: '<path d="M6 6l12 12M18 6L6 18"/>',
        back: '<path d="M15 5l-7 7 7 7"/>',
        chevronDown: '<path d="M6 9l6 6 6-6"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
        check: '<path d="M4 12.5l5 5L20 6.5"/>',
        mic: '<path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3z"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
        micOff: '<path d="M9 9v3a3 3 0 0 0 4.6 2.5"/><path d="M15 12V6a3 3 0 0 0-5.6-1.5"/><path d="M5 11a7 7 0 0 0 10.7 6"/><path d="M19 11a7 7 0 0 1-.7 3"/><path d="M12 18v3"/><path d="M4 3l16 18"/>',
        volume: '<path d="M11 5L6 9H3v6h3l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/>',
        mute: '<path d="M11 5L6 9H3v6h3l5 4V5z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
        send: '<path d="M21 3L10.5 13.5"/><path d="M21 3l-6.6 18-3.9-7.5L3 9.6 21 3z"/>',
        present: '<path d="M3 4h18v12H3z"/><path d="M8 20h8"/><path d="M12 16v4"/>',
        book: '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
        settings: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><path d="M1 14h6M9 8h6M17 16h6"/>',
        sparkles: '<path d="M11 3l1.5 4.1L16.6 8.6 12.5 10.1 11 14.2 9.5 10.1 5.4 8.6l4.1-1.5L11 3z"/><path d="M18.5 14l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z"/>',
        record: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/>',
        stop: '<rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" stroke="none"/>',
        trash: '<path d="M4 7h16"/><path d="M9.5 7V5.2a1.2 1.2 0 0 1 1.2-1.2h2.6a1.2 1.2 0 0 1 1.2 1.2V7"/><path d="M6.5 7l.9 12.1A1.8 1.8 0 0 0 9.2 21h5.6a1.8 1.8 0 0 0 1.8-1.9L17.5 7"/>',
        refresh: '<path d="M21 12a9 9 0 1 1-2.9-6.6"/><path d="M21 3.5V10h-6.5"/>',
        lock: '<rect x="5" y="10.5" width="14" height="9.5" rx="1.5"/><path d="M8.5 10.5V7.8a3.5 3.5 0 0 1 7 0v2.7"/>',
        globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.5 2.4 3.8 5.5 3.8 9S14.5 18.6 12 21c-2.5-2.4-3.8-5.5-3.8-9S9.5 5.4 12 3z"/>',
        link: '<path d="M10.5 13.5a4.5 4.5 0 0 0 6.4 0l2.1-2.1a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M13.5 10.5a4.5 4.5 0 0 0-6.4 0l-2.1 2.1a4.5 4.5 0 0 0 6.4 6.4l1-1"/>',
        clipboard: '<path d="M9 4.5h6v2.6H9z"/><path d="M8.5 5H6.4A1.4 1.4 0 0 0 5 6.4v13.2A1.4 1.4 0 0 0 6.4 21h11.2a1.4 1.4 0 0 0 1.4-1.4V6.4A1.4 1.4 0 0 0 17.6 5h-2.1"/>',
        warning: '<path d="M12 4L2.6 20h18.8L12 4z"/><path d="M12 10v4.5"/><path d="M12 17.6h.01"/>',
        signal: '<path d="M12 20h.01"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/><path d="M5 13a10 10 0 0 1 14 0"/><path d="M1.5 9.5a15 15 0 0 1 21 0"/>',
        users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 5.2a3.5 3.5 0 0 1 0 6.6"/><path d="M17.5 14.4A6.5 6.5 0 0 1 21.5 20"/>',
        shield: '<path d="M12 3l7.5 3v6c0 4.2-3 7.8-7.5 9.2C7.5 19.8 4.5 16.2 4.5 12V6L12 3z"/><path d="M9.2 12.2l2 2 3.6-3.9"/>'
    };

    const DEFAULT_SIZE = 16;

    /**
     * Build an inline SVG string for `name`.
     *
     * @param {string} name            Key from PATHS; unknown names render nothing.
     * @param {object} [opts]
     * @param {number} [opts.size]     Square size in px (default 16).
     * @param {string} [opts.cls]      Extra class attribute value.
     * @param {string} [opts.title]    Adds a <title> for screen readers. Omit
     *                                 when adjacent visible text already names
     *                                 the control.
     * @returns {string} SVG markup (empty string for an unknown name).
     */
    function svg(name, opts) {
        const body = PATHS[name];
        if (!body) return '';

        const options = opts || {};
        const size = options.size || DEFAULT_SIZE;
        const cls = options.cls ? ` class="${options.cls}"` : '';
        const title = options.title ? `<title>${options.title}</title>` : '';

        return `<svg${cls} width="${size}" height="${size}" viewBox="0 0 24 24" ` +
            'fill="none" stroke="currentColor" stroke-width="1.7" ' +
            'stroke-linecap="round" stroke-linejoin="round" ' +
            `aria-hidden="${options.title ? 'false' : 'true'}" focusable="false">` +
            `${title}${body}</svg>`;
    }

    /**
     * Replace `[data-icon]` placeholders inside `root` with their SVG.
     * Placeholders are marked `data-icon-done` so re-hydration is a no-op and
     * freshly injected markup can be hydrated cheaply.
     *
     * @param {ParentNode} [root] Defaults to `document`.
     */
    function hydrate(root) {
        const scope = root || document;
        const nodes = scope.querySelectorAll('[data-icon]:not([data-icon-done])');

        nodes.forEach((node) => {
            const markup = svg(
                node.getAttribute('data-icon'),
                { size: Number(node.getAttribute('data-icon-size')) || DEFAULT_SIZE }
            );
            if (!markup) return;

            node.innerHTML = markup;
            node.setAttribute('data-icon-done', '');
            if (!node.getAttribute('role') && !node.getAttribute('aria-hidden')) {
                node.setAttribute('aria-hidden', 'true');
            }
        });
    }

    /** Fill `el` with the named icon (replacing whatever it held). */
    function set(el, name, opts) {
        if (!el) return;
        el.innerHTML = svg(name, opts);
    }

    /** Icon markup for a `<button>` that shows only an icon. */
    function button(name, opts) {
        return svg(name, opts);
    }

    window.Icons = { svg, set, hydrate, button, names: Object.keys(PATHS) };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => hydrate(document));
    } else {
        hydrate(document);
    }
})();
