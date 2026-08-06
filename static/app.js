/* Sage — DOM touch-ups Streamlit cannot express declaratively.
 *
 * Two whole functions were deleted rather than fixed: example-card animation and
 * attachment-chip styling are now pure CSS keyed off `st.container(key=...)`
 * hooks. They used to find elements by matching visible English text and then
 * wrote hardcoded dark-mode colours as inline styles, which beat the light-mode
 * stylesheet — so on a light theme every hovered card stayed broken until rerun.
 *
 * What is left injects elements and lets app.css style them.
 */
(function () {
    'use strict';

    var doc = window.parent.document;

    var COPY_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
    var CHECK_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
    var CLIP_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>';

    function isProcessing() {
        return !!doc.getElementById('processing-signal');
    }

    /* --- scrolling ------------------------------------------------------- */

    var NEAR_BOTTOM_PX = 140;

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

    // Clearance for the host toolbar and our own fixed controls.
    var TOP_GAP = 58;
    var pinnedTurn = false;

    function autoScroll() {
        if (!isProcessing()) { pinnedTurn = false; return; }
        var el = scroller();
        if (!el) return;

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

    function addDisclaimer() {
        var bottom = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        if (!bottom || doc.getElementById('ai-disclaimer')) return;
        var note = doc.createElement('p');
        note.id = 'ai-disclaimer';
        note.className = 'ai-disclaimer';
        note.textContent = 'Sage can make mistakes and cannot see your account or jobs. Verify commands against the linked docs.';
        bottom.appendChild(note);
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
        addDisclaimer();
        addCodeCopyButtons();
        addAnswerCopyButtons();
        blockSendWhileProcessing();
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
})();
