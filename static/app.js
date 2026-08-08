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

    // Every box between the conversation and the document that could be the one
    // scrolling, innermost first.
    //
    // This used to force `overflow: auto` onto stAppViewContainer, stMain and body,
    // manufacturing three nested scrollports where Streamlit has one — and then
    // scroll all of them (plus documentElement) to the bottom. The scroll amounts
    // compounded, pushing the newest message clean above the top of the viewport
    // and slicing it in half. Forcing overflow also risked trapping content that
    // overflowed the welcome screen on a short window, so it is gone entirely:
    // Streamlit's own scrolling is left alone.
    //
    // What replaced it was a three-item list — `[data-testid="stMain"]`, the
    // scrolling element, documentElement — and both halves of that were wrong.
    //
    // The first entry is an unversioned Streamlit test id, which is the one kind of
    // rule this repo has written down not to write: Streamlit has put the app's
    // scrollbar on `.appview-container`, on `section.main` and on
    // `[data-testid="stMain"]` across the versions requirements.txt allows. This
    // app's own stylesheet sharpens it — app.css sets `overflow-x: hidden` on html,
    // body, stAppViewContainer and stMain, and CSS computes a `visible` axis to
    // `auto` beside a non-visible one, so all four are scroll containers here and
    // two of them were not on the list. On a page whose vertical overflow settles on
    // one of those two the list matched nothing, `scroller()` returned null, and
    // `autoScroll` returned on its first line: no per-turn pin, no settle, no
    // landing reset, on every turn at every window size. That is "the page stays
    // where it is after I send a prompt" — and it was invisible from the harness,
    // which defines the scrollport to be stMain or the document.
    //
    // The second half was `scrollHeight > clientHeight`, which is equally true of a
    // box that merely OVERFLOWS. `overflow: visible` reports the overflow and then
    // ignores every assignment to scrollTop, so a list that only asks about overflow
    // can pick a box that is never going to move and write into it all turn.
    //
    // So the chain is walked and the browser is asked which of them is a scroll
    // container, the same way `overlays()` asks it about fixed versus sticky.
    function ports() {
        var out = [];
        function add(el) { if (el && out.indexOf(el) === -1) out.push(el); }
        // Whatever Streamlit calls the box, the scrollport is an ancestor of the
        // conversation — so start at the conversation and walk out. The fallbacks are
        // the landing screen (no conversation yet) and a page mid-rebuild.
        var anchor = doc.querySelector('.chat-container')
            || doc.querySelector('.stChatMessage')
            || doc.querySelector('.welcome')
            || doc.querySelector('[data-testid="stMainBlockContainer"]')
            || doc.querySelector('.block-container')
            || doc.querySelector('[data-testid="stMain"]')
            || doc.body;
        for (var node = anchor; node; node = node.parentElement) add(node);
        add(doc.scrollingElement);
        add(doc.documentElement);
        return out;
    }

    // Does writing to this element's scrollTop move anything a reader can see? The
    // document always scrolls; anything else has to say so in its computed overflow.
    // `hidden` is deliberately not on the list: it takes a scrollTop, but it shows no
    // scrollbar, so it is a clipping wrapper rather than the page — and scrolling one
    // of those hides content with no way to bring it back.
    function scrollable(el) {
        if (el === doc.scrollingElement || el === doc.documentElement) return true;
        var overflow = view.getComputedStyle(el).overflowY;
        return overflow === 'auto' || overflow === 'scroll' || overflow === 'overlay';
    }

    // Move the view, now, whatever the stylesheet thinks about animation.
    //
    // `el.scrollTop = x` obeys `scroll-behavior`, and a `smooth` anywhere in the chain
    // — Streamlit's own stylesheet is not visible from this repo, and one line of it
    // would do — turns every scroll in this file into an animation that has not
    // started when the next line reads the position back. The reader sees the page
    // crawl, and this script reads its own unfinished scroll as a reader who has taken
    // the page over. `behavior: 'instant'` overrides the declaration; the assignment
    // stays as the fallback for anything without `scrollTo`.
    function scrollView(el, top) {
        if (el.scrollTo) {
            try {
                el.scrollTo({top: top, behavior: 'instant'});
                return;
            } catch (err) { /* older signature: fall through */ }
        }
        el.scrollTop = top;
    }

    // The single element that actually scrolls.
    function scroller() {
        var candidates = ports();
        var overflowing = null;
        for (var i = 0; i < candidates.length; i++) {
            var el = candidates[i];
            if (el.scrollHeight <= el.clientHeight + 1) continue;
            if (scrollable(el)) return el;
            // Remembered rather than returned. If nothing in the chain admits to
            // being a scroll container, writing into the box that at least overflows
            // is a guess — but the alternative is what shipped, which was to return
            // null and do nothing at all, and doing nothing is the bug.
            if (!overflowing) overflowing = el;
        }
        return overflowing;
    }

    // Streamlit's header strip is 3.75rem — 60px, full width, and on top of the
    // page — plus 16px so the question does not sit flush against it. Pinning
    // tighter puts the question underneath the header. (It was 112px while a
    // sticky bar of controls parked below that header; those have moved under the
    // input, and took their 36px of clearance with them.)
    var TOP_GAP = 76;
    // What should be left between the end of an answer and the input bar. Same
    // value as `--tail-gap` in app.css, which is how much room the page reserves
    // past its last message; this is the scroll that lands on it.
    var TAIL_GAP = 28;
    // Between the attachment chips and the top of the input bar. Matches the 0.35rem
    // the stylesheet offsets them by, so the room reserved is the room they occupy.
    var CHIP_GAP = 6;

    // The top edge of everything pinned at the bottom of the window.
    //
    // Not the bar's own top: the attachment chips are pinned above it and are `fixed`
    // too, so a gap measured to the bar is a gap measured underneath them. Every
    // spacing decision in this file is about how much room is left before the reader
    // runs into the composer, and the composer starts where the chips do.
    //
    // This was worth 5px of overlap with one row of chips and 38px with two, which is
    // the last message disappearing behind a chip — found by the `attached` screens in
    // tools/render_check.py the moment they were added.
    function composerTop(bar) {
        var top = bar.getBoundingClientRect().top;
        var chips = doc.querySelector('.st-key-attachments');
        if (chips) {
            var rect = chips.getBoundingClientRect();
            if (rect.height > 0 && rect.top < top) top = rect.top;
        }
        return top;
    }

    // Which question the chase is currently on ('' = none yet).
    var chasing = '';
    // Where the last scroll this script made left the view, so the next pass can tell
    // its own work from a reader who has scrolled somewhere else (-1 = nothing yet).
    var pinnedAt = -1;

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
        return Math.max(0, Math.min(rawBand(element),
                                    Math.round(view.innerHeight * 0.4)));
    }

    // The same measurement without the cap, for the things that are POSITIONS rather
    // than reservations. Capping a position does not make it safer, it moves it: the
    // attachment chips are pinned from `--bar-band`, so every pixel the cap clipped
    // slid them down into the input box. At 966x626 — a width CI renders — the cap
    // was already clipping 16-24px off a bar that tall, and with a paragraph typed
    // the chips ended up on top of the textarea.
    function rawBand(element) {
        return Math.max(0, Math.ceil(
            view.innerHeight - element.getBoundingClientRect().top));
    }

    // Does the input bar sit ON the page, or IN it?
    //
    // This is the question the whole bottom of the layout turns on, and it was
    // answered wrong for as long as this file has existed. If the bar is `fixed`
    // it is painted over the conversation, and the page has to leave a bar's worth
    // of room at the end or the newest answer hides underneath it. If it is
    // `sticky` it is *in the flow* at the end of the scrolling area — it already
    // occupies its own space, and reserving that much again is dead space at the
    // end of every conversation. Streamlit has done both across versions.
    //
    // tools/render_check.py modelled it as fixed, which is where the famous "the
    // newest answer is 131px underneath the input" measurement came from: a replica
    // asserting a layout the app may not have. Three rounds of trying to close a
    // gap by tuning padding, alignment and scrolling never touched the padding that
    // was the gap. So this asks the browser instead of guessing.
    //
    // A `sticky` anywhere in the chain wins, and this is the one part of the file
    // decided by the running app rather than by reasoning about CSS.
    //
    // In the abstract the opposite is true: `fixed` takes a subtree out of the flow
    // whatever is inside it, so a bar that is sticky inside something fixed is
    // painted over the page and needs room reserved. That version shipped, and the
    // gap at the end of the conversation came straight back — because Streamlit's own
    // stylesheet already leaves room for its own bar. Reserving it again is additive,
    // and additive is what a reader sees as 200px of nothing above the box they type
    // in. The reservation here is for the case where nothing in the chain is sticky
    // at all: then Streamlit is not pinning the bar and this has to.
    //
    // So the walk still goes to the top — it is how a fixed-only chain is told apart
    // from a sticky one — but sticky is the answer when both are present.
    function overlays(bar) {
        var streamlitPins = false;
        var overlaid = false;
        for (var node = bar; node && node !== doc.body; node = node.parentElement) {
            var position = view.getComputedStyle(node).position;
            if (position === 'sticky') streamlitPins = true;
            if (position === 'fixed' || position === 'absolute') overlaid = true;
        }
        return overlaid && !streamlitPins;
    }

    function measureChrome() {
        var strip = doc.querySelector('.st-key-composer-strip');
        var bar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        var chips = doc.querySelector('.st-key-attachments');
        // Strip first: the bar reserves room for it, so publishing it is what
        // gives the bar its final height. Reading the bar's rect afterwards
        // flushes that change, so both values come from the same layout.
        if (strip) publish('--strip-h', band(strip));
        if (bar) {
            // Two numbers, and the difference between them matters.
            //
            // `--bar-band` is the bar alone, measured from the bottom of the window.
            // The attachment chips are pinned to it, so it must not include them.
            // `--bar-h` is what the page reserves at its end, which must include
            // them, because they are `fixed` and would otherwise sit on top of the
            // newest answer.
            //
            // Kept apart on purpose. One variable used for both would mean the chips'
            // position depended on a number their own height changed — a feedback
            // loop, and the last one of those in this file grew by 42px a frame until
            // it was the height of the window.
            // The band is published UNCONDITIONALLY, because it is a position: it is
            // where the bar's top edge is, and that is true whether Streamlit pinned
            // the bar with `fixed` or `sticky`. Gating it on `overlays()` — as the
            // reservation below is correctly gated — published 0 in the sticky shape,
            // which pinned the attachment chips 5.6px off the bottom of the window:
            // below the box they belong above, on top of the controls strip, and
            // taking no clicks at all. The reservation is the only thing `overlays()`
            // has an opinion about.
            publish('--bar-band', rawBand(bar));
            // Height first, then decide: a container that is present at zero height
            // (or display:none) needs no gap reserved, and `composerTop` already
            // takes that view of the same node.
            var chipHeight = chips ? chips.getBoundingClientRect().height : 0;
            var chipRoom = chipHeight > 0 ? chipHeight + CHIP_GAP : 0;
            publish('--bar-h', (overlays(bar) ? band(bar) : 0) + chipRoom);
        }
        watch(strip, bar, chips);
    }

    // Re-measure whenever either one changes size, rather than only when the
    // MutationObserver below happens to fire. Both are sized by their text, so
    // they resize with no DOM change at all — a rewrapped disclaimer, a font
    // arriving late — and a published height that has gone stale is a stale
    // reservation: too small, and the newest answer sits under the input.
    var watcher = null;
    function watch(strip, bar, chips) {
        if (typeof ResizeObserver === 'undefined') return;
        try {
            if (!watcher) watcher = new ResizeObserver(measureChrome);
            // observe() on an element already observed is a no-op, so this can
            // run every sync and pick up the elements Streamlit just rebuilt.
            if (strip) watcher.observe(strip);
            if (bar) watcher.observe(bar);
            // The chips too: one more attached file adds a row, and the room the
            // page reserves has to follow it without waiting for the next rerun.
            if (chips) watcher.observe(chips);
        } catch (err) { /* the sync pass still measures */ }
    }

    // The bottom edge of the conversation, whatever ended it. Measuring only the
    // last answer left the space under a trailing failover notice or error card
    // exactly as dead as before — and a failover notice is precisely when the
    // reader is looking at the bottom of the page.
    function tail() {
        var edge = null;
        // `.stChatMessage` covers what is in flight as well as what has landed —
        // the status row and the streaming answer both render inside one. Without
        // it the slack above a short conversation is measured to the bottom of the
        // *question*, which pushes the answer being streamed under the input bar.
        var nodes = doc.querySelectorAll('[class*="st-key-answer-"], .user-message,' +
            '.stChatMessage, .notice, .error-card, [class*="st-key-error-actions"]');
        nodes.forEach(function (node) {
            var bottom = node.getBoundingClientRect().bottom;
            if (edge === null || bottom > edge) edge = bottom;
        });
        return edge;
    }

    // Sit a conversation shorter than the window just above the composer, by
    // padding the space above it, so the reader is not left looking at a screenful
    // of nothing between the answer and the box they type in.
    //
    // The stylesheet used to do this with `min-height: 100dvh` and
    // `justify-content: flex-end`. That shipped, and on the landing screen the
    // hero ended up above the top of the window: where flex puts the free space
    // depends on how Streamlit lays out the page around the block, and when the
    // guess is wrong the overflow goes out of the end of a scrollport that cannot
    // be scrolled back. Padding at the top can only push content down.
    //
    // It measures from the layout with no fill at all — set to zero, read, decide —
    // rather than subtracting its own last value from what it sees. Those are the
    // same number only while the padding is actually moving the conversation, and
    // the first version assumed that: a `padding-top` override in a media query
    // quietly won on every window under 720px, so the content never moved, "what is
    // left after the padding I applied" grew by the same 42px every frame, and the
    // fill ran away to the height of the window. Measuring the real thing costs one
    // extra reflow and cannot diverge, because nothing it reads depends on its own
    // previous output. If something is ignoring the padding, this now does nothing
    // instead of doing damage.
    function fill(port) {
        var bar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        // Not while an answer is coming. A question and a "Reading…" row are short,
        // so this would sit them just above the composer and stream the answer into
        // the bottom of the window with most of the page empty above it — which is
        // where a question goes to be read, not where it goes to be answered. The
        // pin puts it at the top for the duration; this takes over once the answer
        // has landed and its real height is known.
        if (!bar || isProcessing() || !doc.querySelector('.chat-container')) {
            publish('--fill', 0);
            return;
        }
        publish('--fill', 0);
        // Reads below force the reflow that makes that zero real.
        if (port.scrollHeight > port.clientHeight + 1) {
            return;   // long enough to scroll on its own; there is no slack
        }
        var end = tail();
        if (end === null) return;
        var slack = composerTop(bar) - end - TAIL_GAP;
        publish('--fill', Math.max(0, Math.min(Math.round(slack), port.clientHeight)));
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
    // A backstop now rather than the mechanism: with the page reserving exactly the
    // bar plus one gap, and `--fill` closing the slack on a short conversation, max
    // scroll already lands the tail one gap above the bar and this finds nothing to
    // do. It stays for the cases neither of those covers — no ResizeObserver, a
    // stylesheet whose padding something else is overriding — so it must still be
    // correct if it ever does fire.
    function settle(el) {
        var messages = doc.querySelectorAll('.user-message');
        var latest = messages[messages.length - 1];
        var end = tail();
        var bar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        // Measure before spending the once-per-turn stamp. Spending it up front
        // looked equivalent and was not: this runs on a page Streamlit is still
        // rebuilding, so a pass with no messages in the DOM yet burned the stamp and
        // returned, and the real layout — arriving a moment later with the same
        // count — was never settled. That is the dead space that survived two rounds.
        if (!latest || end === null || !bar) return;

        // Counted on questions, not on answers. An errored turn appends no assistant
        // message, so an answer count carries over from the previous turn and this
        // reads as already done; every turn has exactly one question.
        var stamp = String(messages.length);
        if (doc.body.dataset.sageSettled === stamp) return;

        var excess = composerTop(bar) - end - TAIL_GAP;
        if (excess <= 4) return;

        // Never buy that space by pushing a still-visible question off the top.
        // Once it has scrolled away on its own there is nothing left to protect.
        var top = latest.getBoundingClientRect().top;
        var move = Math.min(excess, top >= TOP_GAP ? top - TOP_GAP : excess);
        if (move <= 4) return;
        // Stamped here, where it has actually scrolled. Stamped before the two
        // returns above, a pass that found nothing to do would spend the turn's one
        // chance and a later pass with a real gap could not take it.
        doc.body.dataset.sageSettled = stamp;
        scrollView(el, el.scrollTop + move);
    }

    // A landing screen starts at the top. Streamlit keeps the scroll position
    // across a rerun, so arriving at this screen by clearing a conversation left
    // the page parked where that conversation had been: hero off the top of the
    // window, starter cards against the top edge, and nothing on screen to
    // suggest the page had simply not scrolled back. Once per visit to the
    // screen, so it never fights a reader scrolling it themselves.
    function landing(el) {
        if (doc.querySelector('.chat-container')) {
            delete doc.body.dataset.sageAtTop;
            return false;
        }
        if (doc.body.dataset.sageAtTop !== 'done') {
            doc.body.dataset.sageAtTop = 'done';
            if (el.scrollTop > 0) scrollView(el, 0);
        }
        return true;
    }

    // Has the reader taken this turn's page over? Recorded on the parent document
    // rather than in this realm, because Streamlit rebuilds this script's iframe and a
    // flag that died with it would yank them back the moment it did.
    function heldByReader(stamp) {
        return doc.body.dataset.sageHeld === stamp;
    }

    function autoScroll() {
        var el = scroller();
        if (!el) return;
        if (landing(el)) return;
        if (!isProcessing()) {
            chasing = '';
            pinnedAt = -1;
            delete doc.body.dataset.sageHeld;
            settle(el);
            return;
        }

        // Bring the question to the TOP of the viewport and let the answer stream in
        // beneath it, the way every chat UI behaves.
        //
        // This used to pin to the document's absolute bottom on every frame. On
        // anything but a tall window that scrolls the question clean off the top —
        // and because the container reserves the measured bar height plus
        // `--tail-gap` below the last message to clear the fixed input, the bottom
        // of the document is mostly empty padding, so pinning there wasted a
        // third of the viewport on blank space.
        var messages = doc.querySelectorAll('.user-message');
        var latest = messages[messages.length - 1];
        if (!latest) return;

        // A new question starts a new chase, so nothing below reads a position — or a
        // hand-off — left over from the previous turn.
        var stamp = String(messages.length);
        if (chasing !== stamp) {
            chasing = stamp;
            pinnedAt = -1;
            delete doc.body.dataset.sageHeld;
        }

        var limit = Math.max(0, el.scrollHeight - el.clientHeight);
        // Has the reader scrolled away from where this script left the view? Then the
        // page is theirs for the rest of the turn.
        //
        // Compared against the position CLAMPED to what the page can still offer, not
        // against the raw one. A page that shrinks takes the scroll down with it — the
        // tool round that wipes what streamed and starts the answer again does exactly
        // that — and reading the browser's clamp as a reader would hand the turn over
        // on a move nobody made, leaving the real answer to arrive below the fold.
        //
        // Either direction counts. While the chase is running there is no downward move
        // to make — it leaves the view at the bottom of the page every pass — so a
        // reader who has gone down is one who has gone down from the pinned question,
        // to read the tail, and scrolling them back up to it is the same rudeness as
        // dragging them forward.
        if (pinnedAt >= 0
                && Math.abs(el.scrollTop - Math.min(pinnedAt, limit)) > 4) {
            doc.body.dataset.sageHeld = stamp;
        }
        if (heldByReader(stamp)) return;

        // Keep the newest text on screen for as long as the answer is arriving, and
        // scroll DOWN only. One rule for the whole turn, deliberately.
        //
        // It used to be two: follow the page while it was too short to lift the question
        // to the top of the window, then stop there for the rest of the turn. That read
        // as the page freezing — the view arrived on send and every token after the first
        // screenful streamed in below the fold with nothing moving. Reinstating the
        // follow *alongside* the pin is worse than either: the follow scrolls down to the
        // tail, the pin pulls back up to the question, and they fight every pass.
        //
        // The target is the tail rather than the document's end, because the container
        // reserves the measured bar height plus `--tail-gap` below the last message to
        // clear the fixed composer — the bottom of the document is mostly padding, and
        // scrolling there wastes a third of the window on nothing. Where the reply
        // actually ends, one gap above the composer, is the same edge `settle()` closes
        // to once the turn is over.
        //
        // Down only, so a reply that already fits is never yanked, and the question ends
        // up on screen without being pinned there: at the start of a turn the tail IS
        // just below the question. A reply longer than the window stays the reader's to
        // scroll — the moment they move it, the hand-off above sees that and this stops
        // for the rest of the turn.
        var bar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        var end = tail();
        if (!bar || end === null) return;
        var hidden = end - (composerTop(bar) - TAIL_GAP);
        if (hidden <= 2) return;
        scrollView(el, Math.min(limit, el.scrollTop + hidden));
        // Read back rather than assumed. The scroller refuses while Streamlit is
        // mid-rebuild, and `scroll-behavior: smooth` anywhere in the chain turns the
        // assignment into an animation that has not started yet — in both cases the
        // view is still where it was, and recording the intended position instead
        // would read as the reader having moved it on the very next pass.
        pinnedAt = el.scrollTop;
    }

    /* --- injected controls ---------------------------------------------- */

    function addPaperclip() {
        var input = doc.querySelector('[data-testid="stChatInput"]');
        if (!input || doc.getElementById('paperclip-btn')) return;

        var btn = doc.createElement('button');
        btn.id = 'paperclip-btn';
        btn.type = 'button';
        btn.innerHTML = CLIP_SVG;
        // Deliberately not a list of extensions. It was one — "PDF, TXT, MD, PY,
        // JSON, CSV, YAML" — and it went stale the moment uploads stopped being
        // gated on a list at all: anything that reads as text is accepted now, and a
        // tooltip enumerating seven of them reads as a refusal of the rest.
        btn.title = 'Attach a PDF or text file — script, log, config, source';
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

    // Paste a screenshot into the box and have it attach.
    //
    // Before this, nothing happened at all: the clipboard's image never reached
    // Streamlit's uploader, because the only thing wired to that uploader was the
    // paperclip's `click()`. A paste is the same file arriving by a different door,
    // so it is handed to the same input.
    //
    // The transfer has to go through `DataTransfer`, because `input.files` is not
    // otherwise assignable, and the `change` has to be dispatched by hand: React
    // listens for the native event at the document root, so a bubbling one reaches
    // its handler, but nothing dispatches it when the list is set programmatically.
    // Distinguishes one paste from the next. Two screenshots of the same size would
    // otherwise be the same (name, size) pair and count as one attachment.
    var pasteCount = 1;

    // Re-registered every pass, with the previous registration torn down first.
    //
    // The guard used to be a `data-` marker on the parent's own node, and that was
    // wrong in a way with no visible symptom: the marker lives in the parent document
    // and survives, while the listener lives in THIS iframe's realm and dies whenever
    // Streamlit rebuilds the component. The next copy of the script saw the marker,
    // skipped registration, and no listener existed anywhere — so pasting a screenshot
    // worked once per page load and silently never again. A remover parked on the
    // parent window is the one handle that outlives the realm it came from.
    function addPasteHandler() {
        var input = doc.querySelector('[data-testid="stChatInput"]');
        if (!input) return;
        if (view.__sagePasteOff) {
            try { view.__sagePasteOff(); } catch (err) { /* node already gone */ }
        }
        var onPaste = function (event) {
            var data = event.clipboardData;
            if (!data) return;
            // Text wins. A clipboard from Word, Excel, Sheets or Preview carries
            // text/plain AND an image, and taking the file branch on those pasted a
            // screenshot of the selection while throwing the text away.
            var types = data.types ? [].slice.call(data.types) : [];
            if (types.indexOf('text/plain') !== -1) return;
            var files = [];
            // `items` rather than `files`: a screenshot on the clipboard is an item
            // of kind 'file' and shows up in both, but some browsers only populate
            // `items` for synthesised image data.
            for (var i = 0; i < (data.items || []).length; i++) {
                var item = data.items[i];
                if (item.kind === 'file') {
                    var file = item.getAsFile();
                    if (file) files.push(file);
                }
            }
            if (!files.length) return;
            // The uploader is looked up BEFORE the paste is cancelled. The other order
            // meant that when the input was missing — mid-rebuild, or the widget key
            // being swapped — the paste was swallowed and nothing happened at all.
            var target = doc.querySelector(
                '[data-testid="stFileUploader"] input[type="file"]');
            if (!target) return;
            event.preventDefault();
            var transfer = new view.DataTransfer();
            // Seeded with what the widget already holds, because assigning
            // `input.files` REPLACES the list. Without this, pasting a screenshot
            // silently dropped every file picked before it from the widget's own
            // record — the chips stayed, so nothing looked wrong.
            for (var f = 0; f < (target.files || []).length; f++) {
                transfer.items.add(target.files[f]);
            }
            files.forEach(function (file, index) {
                // A clipboard image arrives as "image.png" or with no name at all, so
                // several pastes would collide on the (name, size) pair app.py
                // identifies a file by — two screenshots of the same size would be one
                // attachment. The index makes them distinct, which the comment here
                // claimed before the code did it.
                var stamp = pasteCount + (index ? '-' + index : '');
                var name = file.name
                    ? file.name.replace(/(\.[^.]*)?$/, '-' + stamp + '$1')
                    : 'pasted-image-' + stamp + '.png';
                transfer.items.add(new view.File([file], name, {type: file.type}));
            });
            pasteCount += 1;
            target.files = transfer.files;
            target.dispatchEvent(new view.Event('change', {bubbles: true}));
        };
        input.addEventListener('paste', onPaste);
        view.__sagePasteOff = function () {
            input.removeEventListener('paste', onPaste);
        };
    }

    // Up-arrow recalls what you asked before, the way a shell does.
    //
    // The questions are read out of the page rather than passed in from Python: they
    // are already in the DOM as `.user-bubble`, one per turn, in order, so there is
    // nothing to keep in sync and nothing to serialise. `history` is rebuilt on every
    // keypress for the same reason — a rerun replaces those nodes, and a list captured
    // once would recall a conversation that has since been cleared.
    //
    // Hijacked ONLY when the caret is at the very start of the box and there is no
    // selection. Anywhere else, Up means "move up a line", and a multi-line question
    // being retyped is exactly when stealing that would be most annoying.
    // Puts a value into a React-controlled field so React believes it.
    //
    // Assigning `.value` directly does not work: React caches the last value it wrote
    // on the node and compares against it, so a plain assignment plus an `input` event
    // is discarded as "no change". The field then LOOKS updated — the text is on
    // screen — while Streamlit still holds the old value, which is why a recalled
    // prompt could not be sent until something was typed after it: the send button
    // stayed disabled because, as far as Streamlit knew, the box was still empty.
    //
    // Going through the prototype's own setter is what React's value tracker hooks,
    // so the change is seen and the widget updates.
    function setFieldValue(field, text) {
        var proto = view.HTMLTextAreaElement && view.HTMLTextAreaElement.prototype;
        var descriptor = proto
            ? Object.getOwnPropertyDescriptor(proto, 'value')
            : null;
        if (descriptor && descriptor.set) {
            descriptor.set.call(field, text);
        } else {
            field.value = text;   // no prototype setter: better than nothing
        }
        field.dispatchEvent(new view.Event('input', {bubbles: true}));
    }

    // What the reader has already asked, most recent first.
    //
    // Read from the page rather than passed in from Python: the questions are already
    // in the DOM, one `.user-bubble` per turn. Attachment badges are nested INSIDE
    // that bubble, and `textContent` concatenates without a separator, so the raw
    // reading of a turn with a file on it came out as
    // "🖼️ pasted-image-1.pngHow do I read this log?" — the filename recalled into the
    // box as if it had been typed. The badges are removed from a clone instead.
    function askedBefore() {
        var out = [];
        doc.querySelectorAll('.user-bubble').forEach(function (node) {
            var copy = node.cloneNode(true);
            copy.querySelectorAll('.attachment-badge').forEach(function (badge) {
                badge.remove();
            });
            var text = copy.textContent.replace(/^\s+|\s+$/g, '');
            if (text) out.push(text);
        });
        return out.reverse();
    }

    // Up recalls what you asked before; Down comes back toward the present and, one
    // step past the newest question, leaves the box as it found it.
    //
    // The browse position lives on the PARENT window, not in this closure. sync()
    // rebuilds these handlers on every mutation frame, so a closure variable was reset
    // by any DOM change between two keypresses — which made repeated Up stick on the
    // most recent question instead of walking back through the conversation.
    function addPromptHistory() {
        var box = doc.querySelector('.stChatInput textarea');
        if (!box) return;
        if (view.__sageHistoryOff) {
            try { view.__sageHistoryOff(); } catch (err) { /* node gone */ }
        }
        if (typeof view.__sageHistoryAt !== 'number') view.__sageHistoryAt = -1;

        var onKey = function (event) {
            if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
            // Never mid-composition: the arrow keys belong to the IME while a Chinese,
            // Japanese or Korean candidate is being chosen.
            if (event.isComposing) return;
            var at = view.__sageHistoryAt;
            // Up only from the very start of the box, so it still moves the caret in a
            // multi-line question. Once browsing, both keys are ours.
            var atStart = box.selectionStart === 0 && box.selectionEnd === 0;
            if (event.key === 'ArrowUp' && at === -1 && !atStart) return;
            if (event.key === 'ArrowDown' && at === -1) return;

            var asked = askedBefore();
            if (!asked.length) return;

            if (event.key === 'ArrowUp') {
                if (at === -1) view.__sageHistoryDraft = box.value;
                if (at + 1 >= asked.length) { event.preventDefault(); return; }
                view.__sageHistoryAt = at + 1;
            } else {
                // Down always advances toward the present, even after the recalled
                // question has been edited. Editing used to end the browse, which left
                // Down doing nothing at all — the reader was stuck on a prompt they had
                // changed with no way forward.
                view.__sageHistoryAt = at - 1;
            }
            event.preventDefault();
            var next = view.__sageHistoryAt;
            // Past the newest question: back to whatever was in the box before the
            // first Up, which is empty in the ordinary case.
            var text = next === -1 ? (view.__sageHistoryDraft || '') : asked[next];
            setFieldValue(box, text);
            box.selectionStart = box.selectionEnd = text.length;
            box.style.height = 'auto';
        };

        // Sending resets the browse: the next Up starts from the newest question
        // rather than from wherever the last walk stopped.
        var onSubmit = function (event) {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
                view.__sageHistoryAt = -1;
                view.__sageHistoryDraft = '';
            }
        };

        box.addEventListener('keydown', onKey);
        box.addEventListener('keydown', onSubmit);
        view.__sageHistoryOff = function () {
            box.removeEventListener('keydown', onKey);
            box.removeEventListener('keydown', onSubmit);
        };
    }

    // Empty the composer when the conversation is cleared.
    //
    // Clearing wipes the transcript from Python, but the text in Streamlit's chat input
    // is client-side state that Python only ever reads on submit — so the last question
    // stayed in the box, sitting over the starter cards on a freshly emptied landing
    // screen as though it were still about to be sent.
    //
    // Driven by a token app.py renders rather than by "the conversation looks empty":
    // the token says a clear HAPPENED, which is different from the transcript being
    // empty, and only the first tells us the box should be emptied. Compared against
    // the last token acted on, so a reader who starts typing straight after clearing
    // does not have it taken away again on the next mutation frame.
    function resetComposerOnClear() {
        var marker = doc.getElementById('composer-reset');
        if (!marker) return;
        var token = marker.getAttribute('data-token') || '';
        if (view.__sageClearToken === undefined) {
            // First sight of the page: adopt the token without clearing, or a reload
            // would wipe a question the reader had already typed.
            view.__sageClearToken = token;
            return;
        }
        if (view.__sageClearToken === token) return;
        view.__sageClearToken = token;
        var box = doc.querySelector('.stChatInput textarea');
        if (box && box.value) {
            setFieldValue(box, '');
            box.style.height = 'auto';
        }
        view.__sageHistoryAt = -1;
        view.__sageHistoryDraft = '';
    }

    // Close the model picker once a model has been picked.
    //
    // Streamlit leaves the popover open across the rerun, so the panel stayed up over
    // the conversation and had to be dismissed by clicking somewhere else — after
    // choosing, which is the one moment there is nothing left to choose. Base Web
    // closes its popover on Escape, so that is what this sends.
    //
    // Delegated from the document, because the panel is rendered in a portal that
    // Streamlit rebuilds on every rerun: a listener bound to the panel itself would
    // be attached to a node that no longer exists by the time it is needed.
    //
    // Two selectors, because Streamlit moved the panel. Up to 1.58 it was a Base Web
    // popover; 1.59 removed Base Web and renders the body into a floating-ui portal
    // on `document.body` instead. This shipped matching only `[data-baseweb=popover]`,
    // which on a current Streamlit matches nothing at all — so the Escape was never
    // sent and the picker went on staying open, the exact bug it was added to fix.
    // requirements.txt allows >=1.42, so both shapes are live and both are named.
    var PANEL = '[data-testid="stPopoverBody"], [data-baseweb="popover"]';

    function closePickerOnPick() {
        if (view.__sagePickerOff) {
            try { view.__sagePickerOff(); } catch (err) { /* realm gone */ }
        }
        var onClick = function (event) {
            var button = event.target && event.target.closest
                ? event.target.closest('button')
                : null;
            // Scoped to the model list, not to "any button in any popover". The wider
            // rule was harmless only because the picker is currently the one popover
            // in the app with buttons in it; a date picker or a multiselect added later
            // would have inherited an Escape nobody asked for.
            if (!button || !button.closest('.st-key-model-list')) return;
            if (!button.closest(PANEL)) return;
            // After the click has been delivered, not instead of it.
            view.setTimeout(function () {
                // Both events, with the same init. Base Web's popover has bound its
                // dismissal to `keyup` in some versions and `keydown` in others, and
                // which one is installed is not visible from this repo — sending one
                // and hoping is how a feature becomes a silent no-op.
                ['keydown', 'keyup'].forEach(function (kind) {
                    doc.dispatchEvent(new view.KeyboardEvent(kind, {
                        key: 'Escape', code: 'Escape', keyCode: 27, which: 27,
                        bubbles: true, cancelable: true
                    }));
                });
            }, 0);
        };
        doc.addEventListener('click', onClick, true);
        view.__sagePickerOff = function () {
            doc.removeEventListener('click', onClick, true);
        };
    }

    function copyText(text) {
        // The PARENT's clipboard. This iframe is never focused — the click that gets
        // here happened in the page around it — so Chromium rejects the iframe's own
        // `writeText` with NotAllowedError, which the caller's empty `.catch` then
        // swallowed: a copy button that looked fine and copied nothing.
        var nav = view.navigator || navigator;
        if (nav.clipboard && nav.clipboard.writeText) {
            return nav.clipboard.writeText(text);
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
        // Measurement FIRST. It used to run after the injectors, all of them inside
        // one try/catch, so a single throw anywhere above cost the whole pass its
        // layout: `--bar-h` went unpublished and the frame rendered on the
        // stylesheet's fallback. `addPaperclip` could not even recover, because it
        // guards on the element it had failed to create, so it threw at the same
        // place forever and the bar was never measured again.
        //
        // Order among the three below still matters: the bar's height is what the
        // page reserves for it, the slack above a short conversation is measured
        // against that reservation, and autoScroll measures the gap they leave.
        measureChrome();
        addPaperclip();
        addPasteHandler();
        addPromptHistory();
        resetComposerOnClear();
        closePickerOnPick();
        addCodeCopyButtons();
        addAnswerCopyButtons();
        blockSendWhileProcessing();
        // `scroller()` first, because it is the one that asks which element actually
        // scrolls instead of assuming. This line named stMain outright while
        // `autoScroll()` two lines down asked `scroller()` — two functions in one file
        // disagreeing about which element is the scrollport. On a page where the
        // document scrolls and stMain does not, stMain reports
        // scrollHeight == clientHeight however long the conversation is, so `fill()`
        // read the page as short and padded slack above one that already scrolled:
        // the reader's gap at the *top* of the page. The fallbacks are for when
        // nothing scrolls, which is exactly when `fill()` has work to do and needs a
        // viewport height to measure the slack against.
        var port = scroller() || doc.querySelector('[data-testid="stMain"]')
            || doc.scrollingElement;
        if (port) fill(port);
        autoScroll();
    }

    function safeSync() {
        try { sync(); } catch (err) { /* never break the page */ }
    }

    // Streaming mutates the DOM once per token. Running the full sync on every
    // mutation meant a document-wide querySelectorAll sweep per token; coalescing
    // keeps it O(frames) instead of O(tokens).
    //
    // A frame callback *and* a timer, whichever arrives first. Coalescing on rAF
    // alone assumes the page is painting: in a browser that is producing no
    // frames — headless Chrome under a virtual clock, a backgrounded tab — the
    // callback never ran, `queued` stayed true for ever, and every later mutation
    // was dropped on the floor. CI found that as a page still sized by the
    // stylesheet's fallbacks, several renders deep.
    var queued = false;
    function flush() {
        if (!queued) return;
        queued = false;
        safeSync();
    }

    function schedule() {
        if (queued) return;
        queued = true;
        window.requestAnimationFrame(flush);
        window.setTimeout(flush, 32);
    }

    // Straight away rather than a frame from now: until this has run, the page is
    // laid out around the stylesheet's guess at the input bar rather than its
    // measured height, and that is a frame the reader sees.
    safeSync();
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
