/* Sage — DOM touch-ups Streamlit cannot express declaratively.
 *
 * Two whole functions were deleted rather than fixed: example-card animation and
 * attachment-chip styling are now pure CSS keyed off `st.container(key=...)`
 * hooks. They used to find elements by matching visible English text and then
 * wrote hardcoded dark-mode colours as inline styles, which beat the light-mode
 * stylesheet — so on a light theme every hovered card stayed broken until rerun.
 * A third, the AI disclaimer, is now rendered by app.py: static text belongs in
 * the document rather than being appended into a container React owns.
 *
 * What is left injects the two controls Streamlit has no element for, scrolls the
 * page the way a chat is read, and measures the pinned bottom bar so app.css can
 * reserve exactly as much room for it as it actually takes.
 */
(function () {
    'use strict';

    // This script is served inside a components.html iframe, so `window` is the
    // iframe (0×0) and every measurement has to come from the page around it.
    var view = window.parent;
    var doc = view.document;

    var COPY_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
    var CHECK_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
    var CLIP_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>';

    function isProcessing() {
        return !!doc.getElementById('processing-signal');
    }

    /* --- scrolling ------------------------------------------------------- */

    // The single element that actually scrolls.
    //
    // This used to force `overflow: auto` onto stAppViewContainer, stMain and body,
    // manufacturing three nested scrollports where Streamlit has one — and then
    // scroll all of them (plus documentElement) to the bottom. The scroll amounts
    // compounded, pushing the newest message clean above the top of the viewport
    // and slicing it in half. Forcing overflow also risked trapping content that
    // overflowed the welcome screen on a short window, so it is gone entirely:
    // Streamlit's own scrolling is left alone.
    function scroller() {
        var candidates = [
            doc.querySelector('[data-testid="stMain"]'),
            doc.scrollingElement,
            doc.documentElement
        ];
        for (var i = 0; i < candidates.length; i++) {
            var el = candidates[i];
            if (el && el.scrollHeight > el.clientHeight + 1) return el;
        }
        return null;
    }

    // Clearance for Streamlit's header strip: 3.75rem, full width, and on top of
    // the page. Pinning tighter than this puts the question underneath it. (It
    // used to be 112px, for the header plus a sticky bar of controls that has
    // since moved under the input, taking 36px of it with it.)
    var TOP_GAP = 76;
    // What should be left between the end of an answer and the input bar. Same
    // value as `--tail-gap` in app.css, which is how much room the page reserves
    // past its last message; this is the scroll that lands on it.
    var TAIL_GAP = 28;
    var pinnedTurn = false;

    /* --- chrome measurement ---------------------------------------------- */

    // The page has to leave room for the fixed input bar, and the bar has to
    // leave room for the strip of controls under it. Neither height is a
    // constant — the disclaimer wraps to two or three lines on a narrow window —
    // so app.css takes both from here. A guess in the stylesheet is what left
    // either 50px of dead space under the newest answer or the answer 131px
    // underneath the input, depending on the viewport.
    function publish(name, px) {
        var root = doc.documentElement;
        var current = parseFloat(root.style.getPropertyValue(name));
        if (Math.abs(current - px) < 1) return;   // NaN on the first pass, so it sets
        root.style.setProperty(name, px + 'px');
    }

    // Both measured from the bottom of the window rather than as heights: what
    // has to be cleared is the band each one covers, and both are pinned to that
    // edge. Measuring the strip as a plain height would miss the gap it is lifted
    // off the edge by, and the bar would reserve too little by exactly that much.
    // Capped at a share of the window: a measurement that comes back as most of
    // the page means something upstream is wrong — an element that is not pinned
    // where the stylesheet thinks it is, or a rect read mid-rebuild — and
    // reserving that much space would push the conversation off screen. The cap
    // turns that into slightly-wrong spacing rather than an empty page.
    function band(element) {
        var raw = Math.ceil(view.innerHeight - element.getBoundingClientRect().top);
        return Math.max(0, Math.min(raw, Math.round(view.innerHeight * 0.4)));
    }

    function measureChrome() {
        var strip = doc.querySelector('.st-key-composer-strip');
        var bar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        if (strip) publish('--strip-h', band(strip));
        if (bar) publish('--bar-h', band(bar));
    }

    // The bottom edge of the conversation, whatever ended it. Measuring only the
    // last answer left the space under a trailing failover notice or error card
    // exactly as dead as before — and a failover notice is precisely when the
    // reader is looking at the bottom of the page.
    function tail() {
        var edge = null;
        var nodes = doc.querySelectorAll('[class*="st-key-answer-"], .user-message,' +
            '.notice, .error-card, [class*="st-key-error-actions"]');
        nodes.forEach(function (node) {
            var bottom = node.getBoundingClientRect().bottom;
            if (edge === null || bottom > edge) edge = bottom;
        });
        return edge;
    }

    // Close the dead space the pin leaves behind once an answer has landed.
    //
    // The pin scrolls so the question sits at the top; if the answer then turns
    // out to be short, the view is left with the reply floating high above the
    // input bar and a screenful of nothing under it.
    //
    // Runs exactly once per answer, keyed off a marker on the parent document so
    // it survives Streamlit rebuilding this script's iframe on every rerun. That
    // matters more than it looks: a version that ran every frame would yank the
    // page back down each time the reader scrolled up to re-read something.
    function settle(el, answers) {
        var stamp = String(answers.length);
        if (doc.body.dataset.sageSettled === stamp) return;
        doc.body.dataset.sageSettled = stamp;

        var messages = doc.querySelectorAll('.user-message');
        var latest = messages[messages.length - 1];
        var end = tail();
        var bar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        if (!latest || end === null || !bar) return;

        var excess = bar.getBoundingClientRect().top - end - TAIL_GAP;
        if (excess <= 4) return;

        // Never buy that space by pushing a still-visible question off the top.
        // Once it has scrolled away on its own there is nothing left to protect.
        var top = latest.getBoundingClientRect().top;
        var move = Math.min(excess, top >= TOP_GAP ? top - TOP_GAP : excess);
        if (move > 4) el.scrollTop += move;
    }

    function autoScroll() {
        var el = scroller();
        if (!el) return;
        if (!isProcessing()) {
            pinnedTurn = false;
            settle(el, doc.querySelectorAll('[class*="st-key-answer-"]'));
            return;
        }

        // Put the question at the TOP of the viewport once per turn and let the
        // answer stream in beneath it, the way every chat UI behaves.
        //
        // This used to pin to the document's absolute bottom on every frame. On
        // anything but a tall window that scrolls the question clean off the top —
        // and because the container reserves ~11rem below the last message to clear
        // the fixed input, the bottom of the document is mostly empty padding, so
        // pinning there wasted a third of the viewport on blank space.
        var messages = doc.querySelectorAll('.user-message');
        var latest = messages[messages.length - 1];
        if (!latest) return;

        if (!pinnedTurn) {
            pinnedTurn = true;
            var target = latest.getBoundingClientRect().top + el.scrollTop - TOP_GAP;
            el.scrollTop = Math.max(0, Math.min(target, el.scrollHeight - el.clientHeight));
            return;
        }

        // Then leave the view alone for the rest of the turn. Chasing the tail as
        // tokens arrive re-scrolls the question straight back off the top on any
        // window where the reply plus the input bar exceeds the viewport — and
        // "am I near the bottom?" is always true on a short document, so the pin
        // above would be undone on the very next frame. A reply longer than the
        // screen is the reader's to scroll; nothing here should grab the viewport
        // out from under them.
    }

    /* --- injected controls ---------------------------------------------- */

    function addPaperclip() {
        var input = doc.querySelector('[data-testid="stChatInput"]');
        if (!input || doc.getElementById('paperclip-btn')) return;

        var btn = doc.createElement('button');
        btn.id = 'paperclip-btn';
        btn.type = 'button';
        btn.innerHTML = CLIP_SVG;
        btn.title = 'Attach a file (PDF, TXT, MD, PY, JSON, CSV, YAML)';
        btn.setAttribute('aria-label', btn.title);
        btn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            var file = doc.querySelector('[data-testid="stFileUploader"] input[type="file"]');
            if (file) file.click();
        });

        input.style.position = 'relative';
        input.insertBefore(btn, input.firstChild);
    }

    function copyText(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
        }
        // Fallback for insecure (http) origins without the async clipboard API.
        return new Promise(function (resolve, reject) {
            try {
                var area = doc.createElement('textarea');
                area.value = text;
                area.style.position = 'fixed';
                area.style.opacity = '0';
                doc.body.appendChild(area);
                area.focus();
                area.select();
                var ok = doc.execCommand('copy');
                doc.body.removeChild(area);
                if (ok) { resolve(); } else { reject(); }
            } catch (err) { reject(err); }
        });
    }

    function makeCopyButton(getText, label) {
        var btn = doc.createElement('button');
        btn.type = 'button';
        btn.className = 'rcc-copy-btn';
        btn.innerHTML = COPY_SVG;
        btn.title = label;
        btn.setAttribute('aria-label', label);
        btn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            copyText(getText()).then(function () {
                btn.innerHTML = CHECK_SVG;
                btn.dataset.copied = 'true';
                btn.setAttribute('aria-label', 'Copied');
                setTimeout(function () {
                    btn.innerHTML = COPY_SVG;
                    delete btn.dataset.copied;
                    btn.setAttribute('aria-label', label);
                }, 2000);
            }).catch(function () {});
        });
        return btn;
    }

    function addCodeCopyButtons() {
        var blocks = doc.querySelectorAll('.stChatMessage div[data-testid="stCodeBlock"]');
        blocks.forEach(function (block) {
            if (block.dataset.sageCopy === 'true') return;
            var pre = block.querySelector('pre');
            var code = block.querySelector('code');
            if (!pre || !code) return;
            block.dataset.sageCopy = 'true';
            pre.style.setProperty('position', 'relative', 'important');
            pre.appendChild(makeCopyButton(function () {
                return code.innerText || code.textContent || '';
            }, 'Copy code to clipboard'));
        });
    }

    function addAnswerCopyButtons() {
        // Keyed answer containers only, so the streaming status row never gets one.
        var answers = doc.querySelectorAll('[class*="st-key-answer-"] .stChatMessage');
        answers.forEach(function (message) {
            if (message.dataset.sageCopy === 'true') return;
            message.dataset.sageCopy = 'true';
            message.style.setProperty('position', 'relative');
            var btn = makeCopyButton(function () {
                var body = message.querySelector('[data-testid="stChatMessageContent"]') || message;
                return body.innerText || body.textContent || '';
            }, 'Copy this answer');
            btn.style.top = '0';
            btn.style.right = '0';
            btn.style.opacity = '0.65';
            message.appendChild(btn);
        });
    }

    /* --- send blocking during generation -------------------------------- */

    var BLOCK_STYLE_ID = 'sage-send-block';

    function blockSendWhileProcessing() {
        var container = doc.querySelector('[data-testid="stChatInput"]');
        if (!container) return;
        var existing = doc.getElementById(BLOCK_STYLE_ID);
        var send = container.querySelector('button');

        if (isProcessing()) {
            if (!existing) {
                var style = doc.createElement('style');
                style.id = BLOCK_STYLE_ID;
                style.textContent = '[data-testid="stChatInput"] button {' +
                    'background: var(--control-bg) !important; opacity: 0.5 !important;' +
                    'pointer-events: none !important; cursor: not-allowed !important; }';
                doc.head.appendChild(style);
            }
            if (send) send.setAttribute('aria-disabled', 'true');
        } else {
            if (existing) existing.remove();
            if (send) send.removeAttribute('aria-disabled');
        }

        var area = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (area && !area.dataset.sageBlocked) {
            area.dataset.sageBlocked = 'true';
            area.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' && !event.shiftKey && isProcessing()) {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                }
            }, true);
        }
    }

    /* --- type to focus --------------------------------------------------- */

    doc.addEventListener('keydown', function (event) {
        if (event.ctrlKey || event.altKey || event.metaKey) return;
        // A single printable character only: never swallow Tab, Escape, arrows,
        // function keys, or Space/Enter aimed at a control.
        if (!event.key || event.key.length !== 1) return;
        var target = event.target;
        if (!target) return;
        if (target.isContentEditable) return;
        var tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (target.closest && target.closest('button, a, [role="button"], [role="dialog"]')) return;

        var input = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (input) input.focus();
    });

    /* --- scheduling ------------------------------------------------------ */

    function sync() {
        addPaperclip();
        addCodeCopyButtons();
        addAnswerCopyButtons();
        blockSendWhileProcessing();
        // Before autoScroll: it measures the gap to the input bar, and the bar's
        // own height is what this settles.
        measureChrome();
        autoScroll();
    }

    // Streaming mutates the DOM once per token. Running the full sync on every
    // mutation meant a document-wide querySelectorAll sweep per token; coalescing
    // into one animation frame keeps it O(frames) instead of O(tokens).
    var queued = false;
    function schedule() {
        if (queued) return;
        queued = true;
        window.requestAnimationFrame(function () {
            queued = false;
            try { sync(); } catch (err) { /* never break the page */ }
        });
    }

    schedule();
    new MutationObserver(schedule).observe(doc.body, { childList: true, subtree: true });
    // Streaming appends text nodes that sometimes do not trigger the observer.
    setInterval(function () { if (isProcessing()) schedule(); }, 250);

    // A resize changes what the page has to reserve for the input bar — the
    // disclaimer under it rewraps — and mutates nothing, so the observer above
    // never sees it. One listener on the page, retargeted to whichever copy of
    // this script is current: Streamlit rebuilds the iframe on every rerun, so
    // registering one per copy would pile up hundreds over a long session.
    view.__sageSync = schedule;
    if (!doc.body.dataset.sageResizeHook) {
        doc.body.dataset.sageResizeHook = 'true';
        view.addEventListener('resize', function () {
            if (view.__sageSync) view.__sageSync();
        });
    }
})();
