// Keyboard Navigation — extracted from base.html (Phase 1 refactor)
// State vars _rqActiveSignalIdx/_rqActivePillIdx declared here as var (window-level)
// so base.html reset calls (non-strict) can write them as globals.

var _rqActiveSignalIdx = -1; // currently focused row in review queue
var _rqActivePillIdx = -1;   // currently focused pill in active row

function _updateRqNavHighlight() {
    const rows = document.querySelectorAll('#sig-rq-body .rq-nav-item');
    rows.forEach((row, rIdx) => {
        if (rIdx === _rqActiveSignalIdx) {
            row.classList.add('active-row');
            // Ensure visible
            row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            
            // Highlight pills + other toggle within this row
            const pills = row.querySelectorAll('.sig-rq-suggestion-pill, .sig-rq-dropdown-toggle');
            pills.forEach((pill, pIdx) => {
                if (pIdx === _rqActivePillIdx) pill.classList.add('active-pill');
                else pill.classList.remove('active-pill');
            });
        } else {
            row.classList.remove('active-row');
            row.querySelectorAll('.sig-rq-suggestion-pill, .sig-rq-dropdown-toggle').forEach(p => p.classList.remove('active-pill'));
        }
    });
}

// Global keyboard listener for Review Queue navigation
// Two modes: row mode (_rqActivePillIdx === -1) and pill mode (_rqActivePillIdx >= 0)
// Row mode:  ↑/↓ navigate rows | Enter → enter pill mode | Space → expand row | x/Delete → dismiss | 1-9 → jump to pill | Ctrl+Z → undo
// Pill mode: ↑/↓ navigate pills | Enter → assign pill (auto-exits to row mode) | Escape → back to row mode
window.addEventListener('keydown', (e) => {
    // Ignore if typing in an input/textarea
    if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;

    const rqPane = document.getElementById('sig-review-queue');
    if (!rqPane || rqPane.classList.contains('hidden')) return;

    const rows = document.querySelectorAll('#sig-rq-body .rq-nav-item');
    if (!rows.length) return;

    const inPillMode = _rqActiveSignalIdx >= 0 && _rqActivePillIdx >= 0;
    let handled = true;

    switch (e.key) {
        case 'ArrowDown':
            if (inPillMode) {
                const pills = rows[_rqActiveSignalIdx].querySelectorAll('.sig-rq-suggestion-pill, .sig-rq-dropdown-toggle');
                if (pills.length) _rqActivePillIdx = Math.min(pills.length - 1, _rqActivePillIdx + 1);
            } else {
                _rqActiveSignalIdx = Math.min(rows.length - 1, _rqActiveSignalIdx + 1);
                _rqActivePillIdx = -1;
            }
            break;
        case 'ArrowUp':
            if (inPillMode) {
                _rqActivePillIdx = Math.max(0, _rqActivePillIdx - 1);
            } else {
                _rqActiveSignalIdx = Math.max(0, _rqActiveSignalIdx - 1);
                _rqActivePillIdx = -1;
            }
            break;
        case 'Enter':
            if (_rqActiveSignalIdx >= 0) {
                if (inPillMode) {
                    // Assign the focused pill, then exit pill mode
                    const pills = rows[_rqActiveSignalIdx].querySelectorAll('.sig-rq-suggestion-pill, .sig-rq-dropdown-toggle');
                    if (pills[_rqActivePillIdx]) {
                        const isDropdown = pills[_rqActivePillIdx].classList.contains('sig-rq-dropdown-toggle');
                        pills[_rqActivePillIdx].click();
                        if (isDropdown) {
                            // Dropdown opens an input — stay in pill mode and focus the search
                            setTimeout(() => {
                                const sigIdMatch = rows[_rqActiveSignalIdx].id.match(/rq-item-(\d+)|rq-ungrouped-(\d+)/);
                                const sigId = sigIdMatch ? (sigIdMatch[1] || sigIdMatch[2]) : null;
                                const giMatch = rows[_rqActiveSignalIdx].id.match(/rq-group-(\d+)/);
                                let input;
                                if (sigId) input = document.getElementById(`rq-search-${sigId}`);
                                else if (giMatch) input = document.getElementById(`rq-gsearch-${giMatch[1]}`);
                                if (input) input.focus();
                            }, 50);
                        } else {
                            // Assignment complete — exit pill mode so ↑/↓ navigates rows again
                            _rqActivePillIdx = -1;
                        }
                    }
                } else {
                    // Enter pill mode — focus first pill
                    const pills = rows[_rqActiveSignalIdx].querySelectorAll('.sig-rq-suggestion-pill, .sig-rq-dropdown-toggle');
                    if (pills.length) _rqActivePillIdx = 0;
                }
            }
            break;
        case 'Escape':
            if (inPillMode) {
                // Exit pill mode back to row level
                _rqActivePillIdx = -1;
            }
            break;
        case ' ':
            if (_rqActiveSignalIdx >= 0) {
                // Expand/collapse the row body
                const titleArea = rows[_rqActiveSignalIdx].querySelector('[onclick^="const el=document.getElementById(\'rq-body-"]');
                const groupHeader = rows[_rqActiveSignalIdx].querySelector('.sig-rq-group-header');
                if (titleArea) titleArea.click();
                else if (groupHeader) groupHeader.click();
            }
            break;
        case 'z':
            if (e.ctrlKey || e.metaKey) {
                // Undo last assignment on the focused row
                if (_rqActiveSignalIdx >= 0) {
                    const undoBtn = rows[_rqActiveSignalIdx].querySelector('button[onclick*="_undo"]');
                    if (undoBtn) undoBtn.click();
                }
            } else {
                handled = false;
            }
            break;
        case 'x':
        case 'Delete':
            if (_rqActiveSignalIdx >= 0) {
                const dismissBtn = rows[_rqActiveSignalIdx].querySelector('button[title="Dismiss"], button[title="Dismiss all as noise"]');
                if (dismissBtn) dismissBtn.click();
            }
            break;
        default:
            // 1-9: jump directly to that pill (enters pill mode)
            if (e.key >= '1' && e.key <= '9') {
                const num = parseInt(e.key) - 1;
                if (_rqActiveSignalIdx >= 0) {
                    const pills = rows[_rqActiveSignalIdx].querySelectorAll('.sig-rq-suggestion-pill');
                    if (pills[num]) _rqActivePillIdx = num;
                }
            } else {
                handled = false;
            }
    }

    if (handled) {
        e.preventDefault();
        _updateRqNavHighlight();
    }
});

// ─────────────────────────────────────────────────────────────────
// Signals module — global keyboard navigation
// Tabs: s/t/n/b/c  |  R: review queue  |  F2: rename  |  E: edit body
// F: tab filter  |  /: signal search  |  Q: quick capture
// Ctrl+N: new item  |  ?/F1: help  |  ↑↓+Enter: list nav  |  []: paginate
// ─────────────────────────────────────────────────────────────────
(function () {
    const s = document.createElement('style');
    s.textContent = '.kb-focused{outline:2px solid rgba(99,102,241,0.55)!important;outline-offset:-2px;border-radius:inherit}';
    document.head.appendChild(s);
})();

let _sigFocusedIdx = -1;
let _threadFocusedIdx = -1;

function _sigKbIsVisible() {
    const el = document.querySelector('.sig-feed-tab');
    return !!(el && el.offsetParent !== null);
}

function _sigKbActiveTab() {
    return document.querySelector('.sig-feed-tab.active')?.dataset?.tab || 'raw';
}

function _sigKbMoveFocus(items, idx) {
    items.forEach((el, i) => {
        el.classList.toggle('kb-focused', i === idx);
        if (i === idx) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
}

function _kbRename() {
    const tab = _sigKbActiveTab();
    if (tab === 'threads') {
        const focused = document.querySelector('.thread-card.kb-focused');
        if (focused) _renameThread(parseInt(focused.dataset.id));
    } else if (tab === 'raw') {
        const focused = document.querySelector('.sig-card.kb-focused');
        if (focused) {
            const titleEl = focused.querySelector('.sig-card-title');
            if (titleEl) { titleEl.contentEditable = 'true'; titleEl.focus(); }
        }
    }
}

function _kbEditBody() {
    const tab = _sigKbActiveTab();
    if (tab === 'raw') {
        const focused = document.querySelector('.sig-card.kb-focused');
        if (focused) openSignalDetail(parseInt(focused.dataset.id));
    } else if (tab === 'threads') {
        const focused = document.querySelector('.thread-card.kb-focused');
        if (focused) openThreadDetail(parseInt(focused.dataset.id));
    }
}

function _toggleKbHints() {
    const existing = document.getElementById('kb-hints-layer');
    if (existing) { existing.remove(); return; }

    const layer = document.createElement('div');
    layer.id = 'kb-hints-layer';
    layer.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:10000';
    document.body.appendChild(layer);

    // Place a badge anchored to an element.
    // anchor: 'tr'=inside top-right | 'tl'=inside top-left
    // stackIdx: stacks badges vertically (0=first, 1=second, etc.)
    function badge(el, key, anchor, stackIdx = 0) {
        if (!el) return;
        const rect = el.getBoundingClientRect();
        // Skip elements with no rendered size or off screen
        if ((rect.width === 0 && rect.height === 0) || rect.bottom < 0 || rect.top > window.innerHeight) return;
        const b = document.createElement('div');
        b.style.cssText = 'position:fixed;background:rgba(79,70,229,0.92);color:#fff;font-family:monospace;font-size:10px;font-weight:700;padding:1px 6px;border-radius:3px;line-height:17px;pointer-events:none;white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,.7)';
        b.textContent = key;
        const G = 3;
        const STACK = stackIdx * 21;
        if (anchor === 'tl') {
            b.style.top  = `${rect.top  + G + STACK}px`;
            b.style.left = `${rect.left + G}px`;
        } else { // 'tr' default
            b.style.top   = `${rect.top + G + STACK}px`;
            b.style.right = `${window.innerWidth - rect.right + G}px`;
        }
        layer.appendChild(b);
    }

    const rqOpen = !document.getElementById('sig-review-queue')?.classList.contains('hidden');
    const tab = _sigKbActiveTab();

    // ── Tab buttons — always shown regardless of context ──
    const tabMap = { raw: 'S', threads: 'T', narratives: 'N', graph: 'B', causal: 'C' };
    document.querySelectorAll('.sig-feed-tab[data-tab]').forEach(el => {
        const k = tabMap[el.dataset.tab];
        if (k) badge(el, k, 'tr');
    });

    if (rqOpen) {
        // ── Review Queue context ──
        const rows = [...document.querySelectorAll('#sig-rq-body .rq-nav-item')];
        if (rows.length) {
            badge(rows[0], '↑↓', 'tl');
            badge(rows[0], 'Space', 'tr', 0);
            badge(rows[0], 'X', 'tr', 1);
        }
        // Active row (if set and different from first)
        const ar = _rqActiveSignalIdx > 0 ? rows[_rqActiveSignalIdx] : null;
        if (ar) {
            badge(ar, 'Enter', 'tr', 0);
            badge(ar, '1–9', 'tr', 1);
            badge(ar, 'Esc', 'tr', 2);
        }
        const allBtns = [...document.querySelectorAll('#sig-review-queue button')];
        const nextBtn = allBtns.find(b => /next/i.test(b.textContent));
        const prevBtn = allBtns.find(b => /prev|←/i.test(b.textContent));
        if (nextBtn) badge(nextBtn, ']', 'tr');
        if (prevBtn) badge(prevBtn, '[', 'tr');
        badge(document.getElementById('sig-review-queue'), 'R', 'tr');

    } else if (tab === 'raw') {
        // ── Signals tab ──
        badge(document.getElementById('signals-search'), 'F', 'tr');
        badge(document.getElementById('custom-search-input'), '/', 'tr');
        badge(document.getElementById('quick-capture-toggle'), 'Q', 'tr');
        badge(document.getElementById('review-queue-badge'), 'R', 'tr');
        const firstCard = document.querySelector('#sig-tab-raw .sig-card');
        if (firstCard) badge(firstCard, '↑↓', 'tl');
        const focused = document.querySelector('#sig-tab-raw .sig-card.kb-focused');
        if (focused) {
            badge(focused, 'Enter', 'tr', 0);
            badge(focused, 'E', 'tr', 1);
            badge(focused, 'F2', 'tr', 2);
        }

    } else if (tab === 'threads') {
        // ── Threads tab ──
        badge(document.getElementById('signals-search'), 'F', 'tr');
        const firstCard = document.querySelector('#sig-tab-threads .thread-card');
        if (firstCard) badge(firstCard, '↑↓', 'tl');
        const focused = document.querySelector('#sig-tab-threads .thread-card.kb-focused');
        if (focused) {
            badge(focused, 'Enter', 'tr', 0);
            badge(focused, 'F2', 'tr', 1);
        }

    } else if (tab === 'graph') {
        badge(document.getElementById('board-keyword-search'), 'F', 'tr');

    } else if (tab === 'causal') {
        badge(document.getElementById('causal-thread-search'), 'F', 'tr');
    }
}

document.addEventListener('keydown', (e) => {
    // Escape from our own search inputs — blur so keyboard nav resumes
    if (e.key === 'Escape' && _sigKbIsVisible()) {
        const sigInputIds = ['signals-search', 'custom-search-input', 'board-keyword-search', 'causal-thread-search'];
        if (sigInputIds.includes(document.activeElement?.id)) {
            document.activeElement.blur();
            e.preventDefault();
            return;
        }
    }

    if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
    if (document.activeElement.contentEditable === 'true') return;
    if (!_sigKbIsVisible()) return;

    // ? or F1 — toggle contextual key hints (no modifier required)
    if (e.key === '?' || e.key === 'F1') { _toggleKbHints(); e.preventDefault(); return; }

    // Escape — dismiss hints layer if visible
    if (e.key === 'Escape' && document.getElementById('kb-hints-layer')) {
        document.getElementById('kb-hints-layer').remove(); e.preventDefault(); return;
    }

    // F2 — rename
    if (e.key === 'F2' && !e.ctrlKey && !e.metaKey && !e.altKey) { _kbRename(); e.preventDefault(); return; }

    // Ctrl+N — new item (context-sensitive)
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
        const tab = _sigKbActiveTab();
        if (tab === 'raw') _toggleQuickCapture();
        e.preventDefault(); e.stopPropagation(); return;
    }

    // Ignore other Ctrl / Meta / Alt combinations
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    const tab = _sigKbActiveTab();
    const rqOpen = !document.getElementById('sig-review-queue')?.classList.contains('hidden');
    const key = e.key;
    const kl = key.toLowerCase();

    // Tab switching (works whether RQ is open or not)
    if (kl === 's') { switchSignalTab('raw');       _sigFocusedIdx = -1;    e.preventDefault(); return; }
    if (kl === 't') { switchSignalTab('threads');   _threadFocusedIdx = -1; e.preventDefault(); return; }
    if (kl === 'n') { switchSignalTab('narratives');                         e.preventDefault(); return; }
    if (kl === 'b') { switchSignalTab('graph');                              e.preventDefault(); return; }
    if (kl === 'c') { switchSignalTab('causal');                             e.preventDefault(); return; }

    // R — toggle review queue
    if (kl === 'r') { _toggleReviewQueue(); e.preventDefault(); return; }

    // Q — quick capture
    if (kl === 'q') { _toggleQuickCapture(); e.preventDefault(); return; }

    // E — edit body (open detail pane for focused item)
    if (kl === 'e') { _kbEditBody(); e.preventDefault(); return; }

    // F — focus tab-local filter
    if (kl === 'f') {
        const map = { raw: 'signals-search', threads: 'signals-search', graph: 'board-keyword-search', causal: 'causal-thread-search' };
        const inp = document.getElementById(map[tab]);
        if (inp) { inp.focus(); inp.select(); }
        e.preventDefault(); return;
    }

    // / — global signal search (defer if thread-signal-search is currently visible)
    if (key === '/') {
        const tss = document.getElementById('thread-signal-search');
        if (tss && tss.offsetParent !== null) return;
        const inp = document.getElementById('custom-search-input');
        if (inp) { inp.focus(); inp.select(); e.preventDefault(); }
        return;
    }

    // [ / ] — review queue pagination
    if (key === ']') {
        const btn = [...document.querySelectorAll('#sig-review-queue button')].find(b => /next/i.test(b.textContent));
        if (btn) { btn.click(); e.preventDefault(); }
        return;
    }
    if (key === '[') {
        const btn = [...document.querySelectorAll('#sig-review-queue button')].find(b => /prev|←/i.test(b.textContent));
        if (btn) { btn.click(); e.preventDefault(); }
        return;
    }

    // List navigation — only when RQ is closed
    if (rqOpen) return;

    if (key === 'ArrowDown' || key === 'ArrowUp') {
        const dir = key === 'ArrowDown' ? 1 : -1;
        if (tab === 'raw') {
            const items = [...document.querySelectorAll('#sig-tab-raw .sig-card')];
            if (!items.length) return;
            _sigFocusedIdx = _sigFocusedIdx < 0
                ? (dir > 0 ? 0 : items.length - 1)
                : Math.max(0, Math.min(items.length - 1, _sigFocusedIdx + dir));
            _sigKbMoveFocus(items, _sigFocusedIdx);
            e.preventDefault();
        } else if (tab === 'threads') {
            const items = [...document.querySelectorAll('#sig-tab-threads .thread-card')];
            if (!items.length) return;
            _threadFocusedIdx = _threadFocusedIdx < 0
                ? (dir > 0 ? 0 : items.length - 1)
                : Math.max(0, Math.min(items.length - 1, _threadFocusedIdx + dir));
            _sigKbMoveFocus(items, _threadFocusedIdx);
            e.preventDefault();
        }
        return;
    }

    if (key === 'Enter') {
        if (tab === 'raw') {
            const focused = document.querySelector('#sig-tab-raw .sig-card.kb-focused');
            if (focused) { openSignalDetail(parseInt(focused.dataset.id)); e.preventDefault(); }
        } else if (tab === 'threads') {
            const focused = document.querySelector('#sig-tab-threads .thread-card.kb-focused');
            if (focused) { openThreadDetail(parseInt(focused.dataset.id)); e.preventDefault(); }
        }
        return;
    }
});

function _renderRqList(sigId, query) {
    const list = document.getElementById(`rq-list-${sigId}`);
    if (!list) return;
    const q = (query || '').toLowerCase();
    const threads = _getSortedThreads();
    const filtered = q ? threads.filter(t => (t.title || '').toLowerCase().includes(q)) : threads;

    _activeRqIndex = 0; // Default to first item (+ New thread)

    // "+ New thread" at top — uses search text as suggested title
    const newTitle = q || '';
    const newBtn = `<div onclick="_createThreadFromQueue(${sigId}, '${escHtml(newTitle.replace(/'/g, "\\'"))}')" class="rq-list-item" style="padding:8px 12px;font-size:12px;color:var(--accent);cursor:pointer;border-bottom:1px solid var(--border);font-weight:600;transition:background 0.1s" onmouseenter="_activeRqIndex=0;_updateRqHighlight(${sigId})" onmouseleave="this.style.background=''">+ New thread${newTitle ? `: "${escHtml(newTitle)}"` : ''}</div>`;

    list.innerHTML = newBtn + filtered.map((t, i) =>
        `<div onclick="_assignFromQueue(${sigId}, ${t.id}, this);document.getElementById('rq-dd-${sigId}').style.display='none'" class="rq-list-item" style="padding:7px 12px;font-size:12px;color:var(--text-secondary);cursor:pointer;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;transition:background 0.1s" onmouseenter="_activeRqIndex=${i + 1};_updateRqHighlight(${sigId})" onmouseleave="this.style.background=''">
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(t.title)}</span>
            <span style="flex-shrink:0;font-size:11px;color:var(--text-muted);margin-left:8px">${t.signal_count || 0}</span>
        </div>`
    ).join('') || '';

    // Initial highlight
    _updateRqHighlight(sigId);
}

function _createThreadFromQueue(sigId, title) {
    if (!title || !title.trim()) return;
    title = title.trim();

    // Close dropdown
    const dd = document.getElementById(`rq-dd-${sigId}`);
    if (dd) dd.style.display = 'none';

    const item = document.getElementById(`rq-item-${sigId}`);

    fetch('/api/signals/patterns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, signal_ids: [sigId] })
    }).then(r => r.json()).then(data => {
        if (data.ok || data.id) {
            const threadId = data.id;
            const cached = _rqListCache.find(s => s.id === sigId);
            if (cached) cached._assigned = true;

            const originalHtml = item ? item.innerHTML : '';
            if (item) {
                item.style.opacity = '0.5';
                item.innerHTML = `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0">
                    <span style="font-size:11px;color:var(--green)">✓ New thread: ${escHtml(title)}</span>
                    <button onclick="_undoAssign(${sigId}, ${threadId}, this)" style="padding:2px 8px;background:none;border:1px solid var(--border);border-radius:4px;font-size:10px;color:var(--text-muted);cursor:pointer">Undo</button>
                </div>`;
                item._originalHtml = originalHtml;
            }
            const countEl = document.getElementById('review-queue-count');
            if (countEl) countEl.textContent = Math.max(0, parseInt(countEl.textContent || '0') - 1);

            // Sync with all other signals in all views
            _injectRecentThread(threadId, title);

            // Refresh local threads list
            fetch('/api/signals/threads').then(r => r.json()).then(td => {
                _threadsCache = td.threads || td || [];
            });
            loadSignals();
        }
    });
}
