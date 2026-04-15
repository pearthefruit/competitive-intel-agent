// Chains / Causal View — extracted from base.html (Phase 2 refactor)
// Shared state (var = window-level, written by signals/discovery code):
//   _activeCausalPathId, _causalPathsCache
// Dependencies (function declarations on window):
//   switchSignalTab, _showToast, _showConfirm, escHtml, loadNarratives

// ===================== CAUSAL/TEMPORAL VIEW — UNIFIED CHAIN CANVAS =====================

// ===================== CAUSAL VIEW (Redesigned) =====================
let _causalLinksCache = [];
var _causalPathsCache = [];        // var: read from discovery drawer outside this module
let _causalSuggestionsCache = [];
let _causalAuditCache = {};        // pathId → temporal audit result
let _causalDismissedPairs = JSON.parse(localStorage.getItem('causal_dismissed') || '[]');
var _activeCausalPathId = null;    // var: written from signals/discovery code outside this module
let _causalInspectedThreadId = null;
let _causalSuggestionsCollapsed = false;
const _causalStatusColors = { captured: '#6b7280', investigating: '#06b6d4', validated: '#22c55e', disproven: '#ef4444' };

function loadCausalView() {
    Promise.all([
        fetch('/api/causal-links').then(r => r.json()),
        fetch('/api/causal-paths').then(r => r.json()),
        fetch('/api/signals/threads').then(r => r.json()),
        fetch('/api/signals/threads/names').then(r => r.json()),
    ]).then(([linkData, pathData, threadData, namesData]) => {
        let activeThreads = threadData.threads || _threadsCache || [];
        // Merge missing lightweight threads so we have titles for older/inactive threads
        if (namesData && namesData.threads) {
            const activeIds = new Set(activeThreads.map(t => t.id));
            namesData.threads.forEach(nt => {
                if (!activeIds.has(nt.id)) {
                    activeThreads.push(nt);
                }
            });
        }
        _threadsCache = activeThreads;

        _causalLinksCache = linkData.links || [];
        _causalPathsCache = pathData.paths || [];
        _renderCausalThreadPicker();
        _renderCausalChainsList();
        // Re-render editor if a chain is active
        if (_activeCausalPathId) {
            const still = _causalPathsCache.find(p => p.id === _activeCausalPathId);
            if (still) _renderCausalEditor();
            else { _activeCausalPathId = null; _renderCausalEditor(); }
        }
        // Chain board lives in Board tab > Chains subtab now — no render here
    });
    fetch('/api/causal-suggestions?limit=20').then(r => r.json())
        .then(data => { _causalSuggestionsCache = data.suggestions || []; _renderCausalSuggestions(); })
        .catch(e => console.warn('[causal] Suggestions failed:', e));
}

// ── Causal Pane Resize Handles ──
(function() {
    let resizingPane = null;
    function initCausalResize() {
        const leftHandle = document.getElementById('causal-resize-left');
        const rightHandle = document.getElementById('causal-resize-right');
        const leftPane = document.getElementById('causal-thread-picker');
        const rightPane = document.getElementById('causal-right-panel');

        // Restore saved widths
        const savedLeft = localStorage.getItem('causal_left_width');
        const savedRight = localStorage.getItem('causal_right_width');
        if (savedLeft && leftPane) leftPane.style.width = savedLeft + 'px';
        if (savedRight && rightPane) rightPane.style.width = savedRight + 'px';

        if (leftHandle) leftHandle.addEventListener('mousedown', e => {
            e.preventDefault(); resizingPane = 'left';
            leftHandle.classList.add('active');
            document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
        });
        if (rightHandle) rightHandle.addEventListener('mousedown', e => {
            e.preventDefault(); resizingPane = 'right';
            rightHandle.classList.add('active');
            document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
        });
        document.addEventListener('mousemove', e => {
            if (!resizingPane) return;
            if (resizingPane === 'left' && leftPane) {
                const parentLeft = leftPane.parentElement.getBoundingClientRect().left;
                const newW = Math.min(450, Math.max(180, e.clientX - parentLeft));
                leftPane.style.width = newW + 'px';
            } else if (resizingPane === 'right' && rightPane) {
                const parentRight = rightPane.parentElement.getBoundingClientRect().right;
                const newW = Math.min(500, Math.max(200, parentRight - e.clientX));
                rightPane.style.width = newW + 'px';
            }
        });
        document.addEventListener('mouseup', () => {
            if (!resizingPane) return;
            const handle = resizingPane === 'left' ? leftHandle : rightHandle;
            if (handle) handle.classList.remove('active');
            if (resizingPane === 'left' && leftPane) localStorage.setItem('causal_left_width', parseInt(leftPane.style.width));
            if (resizingPane === 'right' && rightPane) localStorage.setItem('causal_right_width', parseInt(rightPane.style.width));
            resizingPane = null;
            document.body.style.cursor = ''; document.body.style.userSelect = '';
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initCausalResize);
    else initCausalResize();
})();

// ── Right Panel: Chains List ──

function _renderCausalChainsList() {
    const list = document.getElementById('causal-chains-list');
    const empty = document.getElementById('causal-chains-empty');
    if (!list) return;
    if (!_causalPathsCache.length) {
        list.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
    }
    if (empty) empty.style.display = 'none';
    list.innerHTML = _causalPathsCache.map(path => {
        const tids = path.thread_ids || [];
        const isActive = path.id === _activeCausalPathId;
        const titles = tids.map(tid => {
            const t = (_threadsCache || []).find(t => t.id === tid);
            return t ? t.title.substring(0, 15) : '#' + tid;
        });
        const audit = _causalAuditCache[path.id];
        const auditBadge = audit && audit.total_links
            ? `<span id="chain-temporal-${path.id}" class="causal-chain-temporal ${audit.overall}" title="${audit.coherent_count}/${audit.total_links} links coherent">${{coherent:'✓',warning:'✗',caution:'⚠',mixed:'~'}[audit.overall]||''} ${audit.coherent_count}/${audit.total_links}</span>`
            : `<span id="chain-temporal-${path.id}" class="causal-chain-temporal"></span>`;
        return `<div class="causal-chain-item ${isActive ? 'active' : ''}" onclick="_selectCausalChain(${path.id})" oncontextmenu="event.preventDefault();_showChainItemMenu(event,${path.id})">
            <div style="display:flex;align-items:center;justify-content:space-between;min-width:0">
                <div class="causal-chain-item-title" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(path.name)}</div>
                ${auditBadge}
            </div>
            <div class="causal-chain-item-meta">${tids.length} thread${tids.length !== 1 ? 's' : ''} · ${titles.join(' → ')}</div>
        </div>`;
    }).join('');
}

function _selectCausalChain(pathId) {
    _activeCausalPathId = pathId;
    _renderCausalChainsList();
    _renderCausalEditor();
    _renderCausalSuggestions(); // refresh for new tail node
}

// ── Right Panel: Next Link Suggestions (contextual to active chain's tail) ──

function _renderCausalSuggestions() {
    const list = document.getElementById('causal-suggestions-list');
    const countEl = document.getElementById('causal-suggestions-count');
    if (!list) return;
    const dismissed = new Set(_causalDismissedPairs.map(p => `${p[0]}-${p[1]}`));

    // Get the tail thread of the active chain
    let tailThreadId = null;
    if (_activeCausalPathId) {
        const path = _causalPathsCache.find(p => p.id === _activeCausalPathId);
        if (path && path.thread_ids.length) tailThreadId = path.thread_ids[path.thread_ids.length - 1];
    }

    // Filter suggestions: only those where the tail thread is the cause
    let filtered;
    if (tailThreadId) {
        filtered = _causalSuggestionsCache.filter(s =>
            s.cause_thread_id === tailThreadId && !dismissed.has(`${s.cause_thread_id}-${s.effect_thread_id}`)
        );
    } else {
        // No active chain — show top global suggestions
        filtered = _causalSuggestionsCache.filter(s => !dismissed.has(`${s.cause_thread_id}-${s.effect_thread_id}`)).slice(0, 8);
    }

    if (countEl) countEl.textContent = filtered.length ? `(${filtered.length})` : '';

    if (!filtered.length) {
        const msg = tailThreadId ? 'No next-step suggestions for this chain' : 'Select a chain to see suggestions';
        list.innerHTML = `<div style="color:var(--text-muted);font-size:11px;padding:10px;text-align:center">${msg}</div>`;
        return;
    }
    if (_causalSuggestionsCollapsed) { list.innerHTML = ''; return; }

    list.innerHTML = filtered.map(s => {
        const icon = s.reasons?.[0]?.type === 'temporal' ? '&#9203;' : s.reasons?.[0]?.type === 'entity' ? '&#128279;' : '&#129504;';
        const effectThread = (_threadsCache || []).find(t => t.id === s.effect_thread_id);
        const effectTitle = effectThread ? effectThread.title : s.effect_title;
        return `<div class="causal-sugg-compact" onclick="_openCausalComparison(${s.cause_thread_id},${s.effect_thread_id})">
            <div class="causal-sugg-compact-title">${icon} ${escHtml(effectTitle.substring(0, 30))}</div>
            <div class="causal-sugg-compact-reason">${s.reasons?.map(r => escHtml(r.detail)).join(', ') || ''}</div>
            <button onclick="event.stopPropagation();_acceptNextLink(${s.cause_thread_id},${s.effect_thread_id})" style="margin-top:4px;padding:3px 8px;background:none;border:1px solid #22c55e;border-radius:4px;color:#22c55e;font-size:10px;font-weight:600;cursor:pointer;width:100%">+ Add to chain</button>
        </div>`;
    }).join('');
}

function _acceptNextLink(causeId, effectId) {
    // Add the effect thread to the active chain's tail
    if (!_activeCausalPathId) {
        // No active chain — create one
        _acceptSuggestion(causeId, effectId, '');
        return;
    }
    const path = _causalPathsCache.find(p => p.id === _activeCausalPathId);
    if (!path) return;
    if (path.thread_ids.includes(effectId)) { _showToast('Thread already in chain', 'warn'); return; }
    // Create the causal link
    fetch('/api/causal-links', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cause_thread_id: causeId, effect_thread_id: effectId })
    }).then(r => r.json()).then(() => {
        path.thread_ids.push(effectId);
        _autosaveChain(_activeCausalPathId);
        _renderCausalEditor();
        _renderCausalSuggestions(); // refresh — new tail means new suggestions
        _showToast('Link added', 'success');
    });
}

function _toggleSuggestionsCollapse() {
    _causalSuggestionsCollapsed = !_causalSuggestionsCollapsed;
    const chevron = document.getElementById('causal-suggestions-chevron');
    if (chevron) chevron.innerHTML = _causalSuggestionsCollapsed ? '&#9656;' : '&#9662;';
    _renderCausalSuggestions();
}

// ── Top: Chain Editor ──

// ── Temporal Audit ──

function _fetchAndRenderTemporalAudit(pathId) {
    const forPath = pathId;
    fetch(`/api/causal-paths/${pathId}/temporal-audit`)
        .then(r => r.json())
        .then(audit => {
            _causalAuditCache[pathId] = audit;
            if (_activeCausalPathId !== forPath) return; // user switched chains
            _injectTemporalBadges(audit);
            _updateChainListBadge(pathId, audit);
        })
        .catch(() => {}); // non-critical — fail silently
}

function _injectTemporalBadges(audit) {
    const arrows = document.querySelectorAll('#causal-editor-content .causal-arrow');
    const ICONS = { coherent: '✓', reversed: '✗', simultaneous: '⚠', large_gap: '↔', insufficient_data: '—' };
    (audit.links || []).forEach((link, i) => {
        const arrow = arrows[i];
        if (!arrow) return;
        arrow.querySelector('.causal-arrow-temporal')?.remove();
        const badge = document.createElement('div');
        badge.className = `causal-arrow-temporal ${link.verdict}`;
        badge.title = link.message || '';
        const dayStr = link.days_diff != null
            ? ` ${link.days_diff > 0 ? '+' : ''}${link.days_diff}d`
            : '';
        badge.textContent = (ICONS[link.verdict] || '?') + dayStr;
        arrow.appendChild(badge);
    });
}

function _updateChainListBadge(pathId, audit) {
    const el = document.getElementById(`chain-temporal-${pathId}`);
    if (!el || !audit.total_links) return;
    const ICONS = { coherent: '✓', warning: '✗', caution: '⚠', mixed: '~' };
    el.className = `causal-chain-temporal ${audit.overall}`;
    el.title = `${audit.coherent_count}/${audit.total_links} links temporally coherent`;
    el.textContent = `${ICONS[audit.overall] || ''} ${audit.coherent_count}/${audit.total_links}`;
}

function _renderCausalEditor() {
    const content = document.getElementById('causal-editor-content');
    const titleEl = document.getElementById('causal-editor-title');
    const actions = document.getElementById('causal-editor-actions');
    const emptyEl = document.getElementById('causal-editor-empty');
    if (!content) return;

    if (!_activeCausalPathId) {
        if (titleEl) titleEl.textContent = 'No chain selected';
        if (actions) actions.innerHTML = '';
        content.innerHTML = '';
        if (emptyEl) { emptyEl.style.display = 'flex'; content.appendChild(emptyEl); }
        return;
    }
    const path = _causalPathsCache.find(p => p.id === _activeCausalPathId);
    if (!path) { _activeCausalPathId = null; _renderCausalEditor(); return; }
    if (emptyEl) emptyEl.style.display = 'none';

    // Header
    if (titleEl) titleEl.innerHTML = _editableTitle(path.name, '/api/causal-paths/' + path.id, 'name', '_reloadAfterChainRename()', '13px');
    if (actions) {
        const canPromote = (path.thread_ids || []).length >= 2;
        actions.innerHTML = `
            ${canPromote ? `<button onclick="_promoteChainToNarrative(${path.id})" style="padding:4px 10px;background:none;border:1px solid var(--purple);border-radius:4px;color:var(--purple);font-size:11px;cursor:pointer" title="Creates a narrative from this chain and links all threads as evidence">&#10132; Move to Narratives</button>` : ''}
            <button onclick="_deleteChain(${path.id})" style="padding:4px 8px;background:none;border:1px solid var(--border);border-radius:4px;color:var(--text-muted);font-size:11px;cursor:pointer" title="Delete chain">&times;</button>`;
    }

    // Card nodes
    const tids = path.thread_ids || [];
    let nodesHtml = '';
    tids.forEach((tid, i) => {
        const t = (_threadsCache || []).find(t => t.id === tid);
        const domColor = t ? _DOMAIN_COLORS[_parseDomains(t.domain)[0]] || '#6b7280' : '#6b7280';
        const title = t ? t.title : `Thread #${tid}`;
        const sigCount = t ? t.signal_count || 0 : 0;
        const synthesis = t?.synthesis || '';
        const desc = synthesis.substring(0, 80) || _parseDomains(t?.domain)?.[0] || '';
        const isInspected = tid === _causalInspectedThreadId;
        const nextTid = tids[i + 1];
        const link = nextTid ? _causalLinksCache.find(l => l.cause_thread_id === tid && l.effect_thread_id === nextTid) : null;
        const linkColor = link ? _causalStatusColors[link.status] || '#6b7280' : '#555';

        // Drop zone before node
        nodesHtml += `<div class="causal-drop-zone" ondragover="event.preventDefault();this.classList.add('active')" ondragleave="this.classList.remove('active')" ondrop="this.classList.remove('active');_chainDropOnZone(event,${path.id},${i})"></div>`;

        // Card node
        nodesHtml += `<div class="causal-card ${isInspected ? 'inspected' : ''}" draggable="true"
            ondragstart="event.dataTransfer.setData('text/plain','chain:${path.id}:${i}')"
            onclick="_causalClickThread(${tid})"
            oncontextmenu="event.preventDefault();event.stopPropagation();_showCausalCardMenu(event,${path.id},${i},${tid})">
            <div class="causal-card-count" style="background:${domColor}22;border:2px solid ${domColor}">${sigCount}</div>
            <div class="causal-card-info">
                <div class="causal-card-title">${escHtml(title)}</div>
                <div class="causal-card-desc">${escHtml(desc)}</div>
            </div>
            <button class="causal-card-remove" onclick="event.stopPropagation();_chainRemoveNode(${path.id},${i})">&times;</button>
        </div>`;

        // Arrow to next
        if (nextTid) {
            const label = link ? (link.label || '') : '';
            const escapedLabel = label.replace(/'/g, "\\'").replace(/"/g, '&quot;');
            nodesHtml += `<div class="causal-arrow" oncontextmenu="event.preventDefault();event.stopPropagation();${link ? `_showCausalArrowMenu(event,${link.id})` : ''}">
                ${label ? `<div class="causal-arrow-label" onclick="event.stopPropagation();_editArrowLabelWithHypothesis(${link ? link.id : 0},'${escapedLabel}',${tid},${nextTid})" title="${escHtml(label)}">${escHtml(label)}</div>` : ''}
                <svg width="56" height="14" style="cursor:pointer" onclick="event.stopPropagation();_editArrowLabelWithHypothesis(${link ? link.id : 0},'${escapedLabel}',${tid},${nextTid})"><line x1="0" y1="7" x2="44" y2="7" stroke="${linkColor}" stroke-width="2.5"/><polygon points="42,2 54,7 42,12" fill="${linkColor}"/></svg>
                ${link ? `<div class="causal-arrow-status" style="color:${linkColor};background:${linkColor}15" onclick="event.stopPropagation();_showLinkActions(${link.id})" title="Click to manage this link">${link.status}</div>` : ''}
            </div>`;
        }
    });

    // Extend zone at end
    nodesHtml += `<div class="causal-extend-zone" ondragover="event.preventDefault();this.classList.add('active')" ondragleave="this.classList.remove('active')" ondrop="this.classList.remove('active');_chainDropOnZone(event,${path.id},${tids.length})">+</div>`;

    content.innerHTML = nodesHtml;

    // Fetch temporal audit and inject badges (async, non-blocking)
    if (tids.length >= 2) _fetchAndRenderTemporalAudit(path.id);
}

function _reloadAfterChainRename() { loadCausalView(); }

// ── Middle: Thread Inspector ──

function _causalClickThread(threadId) {
    _causalInspectedThreadId = threadId;
    _renderCausalEditor(); // update card highlight
    // Highlight in picker
    document.querySelectorAll('#causal-thread-list > div').forEach(d => d.style.background = 'var(--bg-secondary)');
    const inspector = document.getElementById('causal-inspector-content');
    if (!inspector) return;
    inspector.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-muted)">Loading thread...</div>`;

    fetch(`/api/signals/threads/${threadId}`)
        .then(r => r.json())
        .then(thread => {
            if (!thread || thread.error) { inspector.innerHTML = '<div style="padding:20px;color:var(--red)">Thread not found</div>'; return; }
            _renderCausalInspector(thread);
        });
}

function _renderCausalInspector(thread) {
    const inspector = document.getElementById('causal-inspector-content');
    if (!inspector) return;
    const domains = _parseDomains(thread.domain);
    const domColor = _DOMAIN_COLORS[domains[0]] || '#6b7280';
    const signals = thread.signals || [];
    const m = thread.momentum || {};
    const mDir = m.direction || 'stable';
    const mLabel = {accelerating: '\u2191 Accelerating', stable: '\u2192 Stable', fading: '\u2193 Decelerating'}[mDir];

    let html = `<div class="causal-thread-detail">
        <div class="causal-thread-hero" style="border-left:4px solid ${domColor}">
            <div class="causal-thread-hero-title">${escHtml(thread.title)}</div>
            <div class="causal-thread-hero-meta">
                ${_renderDomainBadges(thread.domain, '13px')}
                <span class="thread-momentum ${escHtml(mDir)}">${mLabel}</span>
                <span style="color:var(--text-muted)">${signals.length} signals</span>
                ${_activeCausalPathId ? `<button onclick="_addThreadToActiveChain(${thread.id})" style="padding:5px 12px;background:none;border:1px solid var(--accent);border-radius:4px;color:var(--accent);font-size:12px;cursor:pointer;margin-left:auto">+ Add to chain</button>` : ''}
            </div>
        </div>
        ${thread.synthesis ? `<div style="padding:16px 20px;font-size:14px;color:var(--text-secondary);line-height:1.6;border-bottom:1px solid var(--border)">${escHtml(thread.synthesis)}</div>` : ''}
        <div class="causal-thread-signals">
            <div style="font-size:14px;font-weight:700;color:var(--text-secondary);margin-bottom:12px">Signals (${signals.length})</div>
            ${signals.filter(s => s.signal_status !== 'noise').slice(0, 20).map(s => `<div class="causal-thread-signal">
                <div class="causal-thread-signal-title">${escHtml(s.title)}</div>
                <div class="causal-thread-signal-meta">
                    <span>${escHtml(s.source_name || s.source || '')}</span>
                    <span>${s.published_at ? s.published_at.substring(0, 10) : ''}</span>
                    ${s.url ? `<a href="${escHtml(s.url)}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none">source \u2192</a>` : ''}
                </div>
            </div>`).join('')}
        </div>
    </div>`;
    inspector.innerHTML = html;
}

function _addThreadToActiveChain(threadId) {
    if (!_activeCausalPathId) return;
    const path = _causalPathsCache.find(p => p.id === _activeCausalPathId);
    if (!path) return;
    if (path.thread_ids.includes(threadId)) { _showToast('Thread already in chain', 'warn'); return; }
    path.thread_ids.push(threadId);
    _autosaveChain(_activeCausalPathId);
    _renderCausalEditor();
}

// ── Middle: Comparison View (for suggestion evaluation) ──

function _openCausalComparison(causeId, effectId) {
    const inspector = document.getElementById('causal-inspector-content');
    if (!inspector) return;
    inspector.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)">Loading comparison...</div>';

    Promise.all([
        fetch(`/api/signals/threads/${causeId}`).then(r => r.json()),
        fetch(`/api/signals/threads/${effectId}`).then(r => r.json()),
    ]).then(([cause, effect]) => {
        if (!cause || !effect) { inspector.innerHTML = '<div style="padding:20px;color:var(--red)">Thread not found</div>'; return; }
        const sugg = _causalSuggestionsCache.find(s => s.cause_thread_id === causeId && s.effect_thread_id === effectId);
        const causeColor = _DOMAIN_COLORS[_parseDomains(cause.domain)[0]] || '#6b7280';
        const effectColor = _DOMAIN_COLORS[_parseDomains(effect.domain)[0]] || '#6b7280';

        inspector.innerHTML = `<div class="causal-comparison">
            <div style="font-size:16px;font-weight:700;color:var(--text-primary);margin-bottom:16px">Evaluate Suggested Connection</div>
            <div class="causal-comparison-thread" style="border-left:3px solid ${causeColor}">
                <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;margin-bottom:5px">Cause</div>
                <div style="font-size:16px;font-weight:600;color:var(--text-primary)">${escHtml(cause.title)}</div>
                <div style="font-size:13px;color:var(--text-secondary);margin-top:8px">${escHtml((cause.synthesis || '').substring(0, 150))}${(cause.synthesis || '').length > 150 ? '...' : ''}</div>
                <div style="font-size:12px;color:var(--text-muted);margin-top:6px">${(cause.signals || []).length} signals · ${_renderDomainBadges(cause.domain, '12px')}</div>
            </div>
            <div class="causal-comparison-arrow">&#8595;</div>
            <div class="causal-comparison-thread" style="border-left:3px solid ${effectColor}">
                <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;margin-bottom:5px">Effect</div>
                <div style="font-size:16px;font-weight:600;color:var(--text-primary)">${escHtml(effect.title)}</div>
                <div style="font-size:13px;color:var(--text-secondary);margin-top:8px">${escHtml((effect.synthesis || '').substring(0, 150))}${(effect.synthesis || '').length > 150 ? '...' : ''}</div>
                <div style="font-size:12px;color:var(--text-muted);margin-top:6px">${(effect.signals || []).length} signals · ${_renderDomainBadges(effect.domain, '12px')}</div>
            </div>
            ${sugg ? `<div class="causal-comparison-reason">
                <div style="font-weight:600;color:var(--purple);margin-bottom:4px">Why suggested</div>
                ${sugg.reasons?.map(r => {
                    const icon = r.type === 'temporal' ? '&#9203;' : r.type === 'entity' ? '&#128279;' : '&#129504;';
                    return `<div>${icon} ${escHtml(r.detail)}</div>`;
                }).join('') || ''}
            </div>` : ''}
            <div style="display:flex;gap:6px;margin-top:12px">
                <button onclick="_acceptSuggestion(${causeId},${effectId},'${escHtml(cause.title.substring(0,20))} \u2192 ${escHtml(effect.title.substring(0,20))}')" style="padding:8px 16px;background:none;border:1px solid #22c55e;border-radius:5px;color:#22c55e;font-size:13px;font-weight:600;cursor:pointer;flex:1">Accept &amp; Create Chain</button>
                <button onclick="_dismissSuggestion(${causeId},${effectId});_clearCausalInspector()" style="padding:8px 16px;background:none;border:1px solid var(--border);border-radius:5px;color:var(--text-muted);font-size:13px;cursor:pointer;flex:1">Dismiss</button>
            </div>
        </div>`;
    });
}

function _clearCausalInspector() {
    _causalInspectedThreadId = null;
    const inspector = document.getElementById('causal-inspector-content');
    if (inspector) inspector.innerHTML = `<div class="causal-inspector-empty" id="causal-inspector-empty">
        <div style="font-size:32px;margin-bottom:10px">&#128270;</div>
        <div style="font-size:14px">Select a thread to inspect</div>
        <div style="color:var(--text-muted);font-size:12px;margin-top:6px">Click a thread from the left or a node in the chain above</div>
    </div>`;
    _renderCausalEditor();
}

// ── Left: Thread Picker ──

function _renderCausalThreadPicker() {
    const container = document.getElementById('causal-thread-list');
    if (!container) return;
    const search = (document.getElementById('causal-thread-search')?.value || '').toLowerCase();
    const filtered = (_threadsCache || [])
        .filter(t => _activeDomains.size === _ALL_DOMAINS.length || _parseDomains(t.domain).some(d => _activeDomains.has(d)))
        .filter(t => !search || t.title.toLowerCase().includes(search))
        .slice(0, 50);
    container.innerHTML = filtered.map(t => {
        const domColor = _DOMAIN_COLORS[_parseDomains(t.domain)[0]] || '#6b7280';
        const isInspected = t.id === _causalInspectedThreadId;
        return `<div draggable="true" ondragstart="event.dataTransfer.setData('text/plain','${t.id}')"
            onclick="_causalClickThread(${t.id})"
            oncontextmenu="event.preventDefault();_showCausalPickerMenu(event,${t.id})"
            style="padding:8px 12px;margin-bottom:4px;background:${isInspected ? 'var(--bg-tertiary)' : 'var(--bg-secondary)'};border-radius:5px;border-left:3px solid ${domColor};cursor:grab;font-size:13px;color:var(--text-secondary);display:flex;justify-content:space-between;align-items:center;transition:background 0.1s"
            onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background='${isInspected ? 'var(--bg-tertiary)' : 'var(--bg-secondary)'}'" >
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(t.title)}</span>
            <span style="font-size:11px;color:var(--text-muted);flex-shrink:0;margin-left:4px">${t.signal_count || 0}</span>
        </div>`;
    }).join('') || '<div style="color:var(--text-muted);font-size:13px;padding:10px">No threads available</div>';
}
function _filterCausalThreadPicker() { _renderCausalThreadPicker(); }

// ── Suggestions: Accept / Dismiss ──

function _acceptSuggestion(causeId, effectId, name) {
    fetch('/api/causal-links', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cause_thread_id: causeId, effect_thread_id: effectId })
    }).then(r => r.json()).then(linkResult => {
        if (!linkResult.ok && linkResult.error !== 'Link already exists') return;
        fetch('/api/causal-paths', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name || 'Untitled chain', thread_ids: [causeId, effectId] })
        }).then(r => r.json()).then(result => {
            _showToast('Chain created', 'success');
            if (result.ok) _activeCausalPathId = result.id;
            loadCausalView();
        });
    });
}

function _dismissSuggestion(causeId, effectId) {
    _causalDismissedPairs.push([causeId, effectId]);
    localStorage.setItem('causal_dismissed', JSON.stringify(_causalDismissedPairs));
    _causalSuggestionsCache = _causalSuggestionsCache.filter(s => !(s.cause_thread_id === causeId && s.effect_thread_id === effectId));
    _renderCausalSuggestions();
    // Re-render inspector if it's showing this comparison
    if (_causalInspectedThreadId) _causalClickThread(_causalInspectedThreadId);
}

// ── Drag & Drop ──

function _chainDropOnZone(event, pathId, insertIndex) {
    event.preventDefault();
    const data = event.dataTransfer.getData('text/plain');
    if (data.startsWith('chain:')) {
        const [, srcPathId, srcIndex] = data.split(':');
        if (parseInt(srcPathId) === pathId) { _chainReorderNode(pathId, parseInt(srcIndex), insertIndex); return; }
    }
    const threadId = parseInt(data);
    if (!threadId || isNaN(threadId)) return;
    const path = _causalPathsCache.find(p => p.id === pathId);
    if (!path) return;
    if (path.thread_ids.includes(threadId)) { _showToast('Thread already in this chain', 'warn'); return; }
    path.thread_ids.splice(insertIndex, 0, threadId);
    _autosaveChain(pathId);
    _renderCausalEditor();
    _renderCausalThreadPicker();
}

function _editorDragOver(event) {
    event.preventDefault();
    const emptyEl = document.getElementById('causal-editor-empty');
    if (emptyEl) emptyEl.style.borderColor = 'var(--accent)';
}
function _editorDragLeave(event) {
    const emptyEl = document.getElementById('causal-editor-empty');
    if (emptyEl) emptyEl.style.borderColor = '';
}
function _editorDrop(event) {
    event.preventDefault();
    const emptyEl = document.getElementById('causal-editor-empty');
    if (emptyEl) emptyEl.style.borderColor = '';
    if (event.target.closest('.causal-card') || event.target.closest('.causal-drop-zone') || event.target.closest('.causal-extend-zone')) return;
    const data = event.dataTransfer.getData('text/plain');
    if (data.startsWith('chain:')) return;
    const threadId = parseInt(data);
    if (!threadId || isNaN(threadId)) return;
    if (_activeCausalPathId) {
        // Add to active chain
        _addThreadToActiveChain(threadId);
    } else {
        // Start new chain
        _startNewChain(threadId);
    }
}

function _chainDropOnPicker(event) {
    event.preventDefault();
    const data = event.dataTransfer.getData('text/plain');
    if (!data.startsWith('chain:')) return;
    const [, pathId, nodeIndex] = data.split(':');
    _chainRemoveNode(parseInt(pathId), parseInt(nodeIndex));
}

function _startNewChain(threadId) {
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    const name = thread ? thread.title.substring(0, 30) : 'New chain';
    fetch('/api/causal-paths', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, thread_ids: [threadId] })
    }).then(r => r.json()).then(result => {
        if (result.ok) {
            _activeCausalPathId = result.id;
            _showToast('Chain started', 'success');
            loadCausalView();
        }
    });
}

function _startNewChainEmpty() {
    _showInlineInput(window.innerWidth / 2, 200, 'Chain name...', '', (name) => {
        if (!name.trim()) return;
        // Create a placeholder path — user will drag threads to it
        // We need at least one thread, so show a toast
        _showToast('Drag a thread to the editor to start', 'info');
    });
}

// ── Chain Mutations ──

function _chainRemoveNode(pathId, nodeIndex) {
    const path = _causalPathsCache.find(p => p.id === pathId);
    if (!path) return;
    const tids = path.thread_ids;
    if (tids.length <= 1) { _deleteChain(pathId); return; }
    const prevId = nodeIndex > 0 ? tids[nodeIndex - 1] : null;
    const nextId = nodeIndex < tids.length - 1 ? tids[nodeIndex + 1] : null;
    tids.splice(nodeIndex, 1);
    if (prevId && nextId) {
        fetch('/api/causal-links', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cause_thread_id: prevId, effect_thread_id: nextId }) });
    }
    _autosaveChain(pathId);
    _renderCausalEditor();
    _renderCausalThreadPicker();
}

function _chainReorderNode(pathId, fromIndex, toIndex) {
    const path = _causalPathsCache.find(p => p.id === pathId);
    if (!path) return;
    const tids = path.thread_ids;
    const [moved] = tids.splice(fromIndex, 1);
    const adjustedTo = toIndex > fromIndex ? toIndex - 1 : toIndex;
    tids.splice(adjustedTo, 0, moved);
    _autosaveChain(pathId);
    _renderCausalEditor();
}

function _autosaveChain(pathId) {
    const path = _causalPathsCache.find(p => p.id === pathId);
    if (!path) return;
    fetch(`/api/causal-paths/${pathId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_ids: path.thread_ids }) });
    const tids = path.thread_ids;
    for (let i = 0; i < tids.length - 1; i++) {
        const exists = _causalLinksCache.find(l => l.cause_thread_id === tids[i] && l.effect_thread_id === tids[i + 1]);
        if (!exists) {
            fetch('/api/causal-links', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cause_thread_id: tids[i], effect_thread_id: tids[i + 1] })
            }).then(r => r.json()).then(data => {
                if (data.ok) _causalLinksCache.push({ id: data.id, cause_thread_id: tids[i], effect_thread_id: tids[i + 1], status: 'captured' });
            });
        }
    }
}

function _deleteChain(pathId) {
    _showConfirm('Delete this chain?', () => {
        fetch(`/api/causal-paths/${pathId}`, { method: 'DELETE' }).then(() => {
            _causalPathsCache = _causalPathsCache.filter(p => p.id !== pathId);
            if (_activeCausalPathId === pathId) _activeCausalPathId = null;
            _renderCausalChainsList();
            _renderCausalEditor();
            _showToast('Chain deleted', 'success');
        });
    });
}

// ── Arrow Labels with Hypothesis Autocomplete ──

function _editArrowLabelWithHypothesis(linkId, currentLabel, causeThreadId, effectThreadId) {
    if (!linkId) return;
    // Build inline input with autocomplete
    const x = window.innerWidth / 2;
    const y = window.innerHeight / 3;
    _showInlineInput(x, y, 'Causal mechanism... (type to search hypotheses)', currentLabel, (label) => {
        // Save label on the link
        fetch(`/api/causal-links/${linkId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label }) })
        .then(() => {
            const link = _causalLinksCache.find(l => l.id === linkId);
            if (link) link.label = label;
            _renderCausalEditor();
        });
    });
    // After inline input is shown, add autocomplete below it
    setTimeout(() => {
        const input = document.querySelector('.sig-inline-input');
        if (!input) return;
        fetch('/api/hypotheses?status=captured').then(r => r.json()).then(data => {
            const hyps = data.hypotheses || [];
            if (!hyps.length) return;
            let dropdown = document.createElement('div');
            dropdown.className = 'causal-hyp-autocomplete';
            dropdown.style.left = input.style.left;
            dropdown.style.top = (parseInt(input.style.top) + 36) + 'px';
            dropdown.style.position = 'fixed';
            const render = (filter) => {
                const filtered = filter ? hyps.filter(h => h.title.toLowerCase().includes(filter.toLowerCase())) : hyps.slice(0, 8);
                dropdown.innerHTML = filtered.length ?
                    `<div style="padding:6px 10px;font-size:10px;color:var(--text-muted);border-bottom:1px solid var(--border)">Hypotheses from bank</div>` +
                    filtered.map(h => `<div class="causal-hyp-item" data-title="${escHtml(h.title)}">${escHtml(h.title.substring(0, 50))}</div>`).join('') :
                    '<div style="padding:8px 12px;font-size:11px;color:var(--text-muted)">No matches</div>';
            };
            render('');
            document.body.appendChild(dropdown);
            input.addEventListener('input', () => render(input.value));
            dropdown.addEventListener('click', (e) => {
                const item = e.target.closest('.causal-hyp-item');
                if (item) { input.value = item.dataset.title; input.dispatchEvent(new Event('change')); }
            });
            // Clean up when input is removed
            const observer = new MutationObserver(() => {
                if (!document.body.contains(input)) { dropdown.remove(); observer.disconnect(); }
            });
            observer.observe(document.body, { childList: true, subtree: true });
        });
    }, 100);
}

// ── Link Actions (status + validation) ──

function _showLinkActions(linkId) {
    const link = _causalLinksCache.find(l => l.id === linkId);
    if (!link) return;
    const inspector = document.getElementById('causal-inspector-content');
    if (!inspector) return;
    const causeTitle = (_threadsCache.find(t => t.id === link.cause_thread_id) || {}).title || `Thread #${link.cause_thread_id}`;
    const effectTitle = (_threadsCache.find(t => t.id === link.effect_thread_id) || {}).title || `Thread #${link.effect_thread_id}`;
    const color = _causalStatusColors[link.status] || '#6b7280';
    const alts = link.alternatives_json ? JSON.parse(link.alternatives_json) : null;

    let html = `<div style="padding:20px">
        <div style="font-size:17px;font-weight:700;color:var(--text-primary);margin-bottom:12px">${escHtml(link.label || 'Unnamed causal link')}</div>
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:16px">
            <span style="font-size:13px;padding:4px 12px;border-radius:4px;background:${color}22;color:${color};font-weight:600">${link.status}</span>
        </div>
        <div style="margin-bottom:12px">
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:5px">CAUSE</div>
            <div style="padding:10px 12px;background:var(--bg-secondary);border-radius:6px;font-size:14px;color:var(--text-primary);cursor:pointer;border-left:3px solid var(--accent)" onclick="_causalClickThread(${link.cause_thread_id})">${escHtml(causeTitle)}</div>
        </div>
        <div style="text-align:center;font-size:18px;color:var(--text-muted);margin:6px 0">&#8595;</div>
        <div style="margin-bottom:16px">
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:5px">EFFECT</div>
            <div style="padding:10px 12px;background:var(--bg-secondary);border-radius:6px;font-size:14px;color:var(--text-primary);cursor:pointer;border-left:3px solid var(--purple)" onclick="_causalClickThread(${link.effect_thread_id})">${escHtml(effectTitle)}</div>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px">
            <button onclick="_updateCausalStatus(${link.id},'investigating')" style="padding:6px 12px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:5px;color:var(--accent);font-size:12px;cursor:pointer">Investigate</button>
            <button onclick="_challengeCausalLink(${link.id})" style="padding:6px 12px;background:var(--bg-tertiary);border:1px solid #f59e0b;border-radius:5px;color:#f59e0b;font-size:12px;cursor:pointer" title="Devil's advocate: find alternative explanations">&#9888; Challenge</button>
            <button onclick="_validateCausalLink(${link.id})" style="padding:6px 12px;background:var(--bg-tertiary);border:1px solid #22c55e;border-radius:5px;color:#22c55e;font-size:12px;cursor:pointer">Validate</button>
            <button onclick="_updateCausalStatus(${link.id},'disproven')" style="padding:6px 12px;background:var(--bg-tertiary);border:1px solid #ef4444;border-radius:5px;color:#ef4444;font-size:12px;cursor:pointer">Disprove</button>
            <button onclick="_deleteCausalLink(${link.id})" style="padding:6px 12px;background:none;border:1px solid var(--border);border-radius:5px;color:var(--text-muted);font-size:12px;cursor:pointer;margin-left:auto">Delete</button>
        </div>`;

    // Show existing alternatives if any
    if (alts && alts.length) {
        html += `<div style="margin-top:12px">
            <div style="font-size:14px;font-weight:700;color:#f59e0b;margin-bottom:10px">&#9888; Alternative Explanations</div>
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:12px">These must be dismissed before validating</div>
            ${alts.map((alt, i) => {
                const plColor = alt.plausibility === 'high' ? '#ef4444' : alt.plausibility === 'medium' ? '#f59e0b' : '#22c55e';
                return `<div class="causal-alt-item" id="causal-alt-${linkId}-${i}">
                    <div class="causal-alt-explain">${escHtml(alt.explanation)}</div>
                    <div class="causal-alt-evidence">Evidence to check: ${escHtml(alt.distinguishing_evidence || '')}</div>
                    <span class="causal-alt-plausibility" style="background:${plColor}22;color:${plColor}">${alt.plausibility} plausibility</span>
                    <button onclick="_dismissAlternative(${linkId},${i})" style="float:right;padding:5px 12px;background:none;border:1px solid var(--border);border-radius:4px;color:var(--text-muted);font-size:11px;cursor:pointer;margin-top:4px">Dismiss with reasoning</button>
                </div>`;
            }).join('')}
        </div>`;
    }

    html += '</div>';
    inspector.innerHTML = html;
}

function _challengeCausalLink(linkId) {
    const inspector = document.getElementById('causal-inspector-content');
    const statusDiv = document.createElement('div');
    statusDiv.style.cssText = 'padding:12px 16px;color:var(--accent);font-size:12px;display:flex;align-items:center;gap:6px';
    statusDiv.innerHTML = '<span class="animate-spin" style="display:inline-block">&#9881;</span> Finding alternative explanations...';
    inspector.prepend(statusDiv);

    fetch(`/api/causal-links/${linkId}/validate`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            statusDiv.remove();
            if (data.ok && data.assessment) {
                // Update local cache
                const link = _causalLinksCache.find(l => l.id === linkId);
                if (link && data.assessment.alternatives) {
                    link.alternatives_json = JSON.stringify(data.assessment.alternatives);
                }
                _showLinkActions(linkId);
                _showToast('Alternatives generated', 'success');
            } else {
                _showToast(data.error || 'Challenge failed', 'error');
            }
        })
        .catch(() => { statusDiv.remove(); _showToast('Challenge failed', 'error'); });
}

function _validateCausalLink(linkId) {
    const link = _causalLinksCache.find(l => l.id === linkId);
    if (link) {
        const alts = link.alternatives_json ? JSON.parse(link.alternatives_json) : [];
        if (alts.length > 0) {
            _showToast('Dismiss all alternatives before validating', 'warn');
            return;
        }
    }
    _updateCausalStatus(linkId, 'validated');
}

function _dismissAlternative(linkId, altIndex) {
    _showInlineInput(window.innerWidth / 2, window.innerHeight / 3, 'Why is this alternative not the cause?', '', (reasoning) => {
        if (!reasoning.trim()) return;
        const link = _causalLinksCache.find(l => l.id === linkId);
        if (!link) return;
        const alts = link.alternatives_json ? JSON.parse(link.alternatives_json) : [];
        alts.splice(altIndex, 1);
        const newAltsJson = JSON.stringify(alts);
        link.alternatives_json = newAltsJson;
        fetch(`/api/causal-links/${linkId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ alternatives_json: newAltsJson }) })
        .then(() => { _showLinkActions(linkId); });
    });
}

function _updateCausalStatus(linkId, status) {
    fetch(`/api/causal-links/${linkId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }) })
    .then(() => { _showToast(`Status \u2192 ${status}`, 'success'); loadCausalView(); });
}

function _deleteCausalLink(linkId) {
    _showConfirm('Delete this causal link?', () => {
        fetch(`/api/causal-links/${linkId}`, { method: 'DELETE' })
            .then(() => { _clearCausalInspector(); loadCausalView(); });
    });
}

// ── Promote to Narrative ──

function _promoteChainToNarrative(pathId) {
    _showConfirm('Move this chain to Narratives? This creates a narrative from your chain with all threads linked as evidence.', () => {
        fetch(`/api/causal-paths/${pathId}/promote`, { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    _showToast('Chain moved to Narratives', 'success');
                    loadNarratives();
                    setTimeout(() => {
                        switchSignalTab('narratives');
                        openNarrativeDetail(data.narrative_id);
                    }, 300);
                } else {
                    _showToast(data.error || 'Promotion failed', 'error');
                }
            });
    });
}

// ── Brainstorm Integration ──

function _seedCausalFromBrainstorm(brainstormId, threadIds) {
    const labels = window._brainstormLinkLabels || [];
    const links = labels.map(l => {
        const source = (_threadsCache || []).find(t => t.title === l.source_thread);
        const target = (_threadsCache || []).find(t => t.title === l.target_thread);
        if (!source || !target) return null;
        return { cause_thread_id: source.id, effect_thread_id: target.id, label: l.label };
    }).filter(Boolean);
    if (!links.length) { _showToast('No thread matches found', 'warn'); return; }
    fetch('/api/causal-links/from-brainstorm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ brainstorm_id: brainstormId, links })
    }).then(r => r.json()).then(result => {
        _showToast(`Seeded ${result.created_count} causal link${result.created_count !== 1 ? 's' : ''}`, 'success');
    });
}

// ── Causal Context Menus ──

function _showCausalPickerMenu(event, threadId) {
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    if (!thread) return;
    const sigCount = thread.signal_count || 0;
    const items = [
        { label: 'Inspect', icon: '🔍', action: `_causalClickThread(${threadId})` },
        { label: 'Add to chain', icon: '⛓️', action: `_addThreadToChainFromMenu(${threadId})` },
        { label: 'Rename', icon: '✏️', action: `_renameThread(${threadId})` },
    ];
    if (sigCount >= 6) {
        items.push({ label: 'Split thread', icon: '✂️', action: `_splitThreadFromMenu(${threadId})` });
    }
    items.push(
        'separator',
        { label: 'Highlight on board', icon: '🔮', action: `_highlightThreadOnBoard(${threadId})` },
        { label: 'Find similar', icon: '🔎', submenu: [
            { label: 'By shared entities', icon: '🏢', action: `_findSimilarByEntities(${threadId})` },
            { label: 'By domain', icon: '🎯', action: `_findSimilarByDomain(${threadId})` },
            { label: 'By signal count', icon: '📊', action: `_findSimilarBySize(${threadId})` },
        ]},
        'separator',
        { label: 'Delete', icon: '🗑️', action: `_deleteThread(${threadId})`, color: '#ef4444' },
    );
    _showContextMenu(items, event.clientX, event.clientY, thread.title.substring(0, 40));
}

function _showCausalCardMenu(event, pathId, nodeIndex, threadId) {
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    const sigCount = thread?.signal_count || 0;
    const items = [
        { label: 'Inspect thread', icon: '🔍', action: `_causalClickThread(${threadId})` },
        { label: 'Rename', icon: '✏️', action: `_renameThread(${threadId})` },
    ];
    if (sigCount >= 6) {
        items.push({ label: 'Split thread', icon: '✂️', action: `_splitThreadFromMenu(${threadId})` });
    }
    items.push(
        'separator',
        { label: 'Remove from chain', icon: '↩️', action: `_chainRemoveNode(${pathId},${nodeIndex})` },
        { label: 'Delete thread', icon: '🗑️', action: `_deleteThread(${threadId})`, color: '#ef4444' },
    );
    _showContextMenu(items, event.clientX, event.clientY, thread?.title?.substring(0, 40) || `Thread #${threadId}`);
}

function _showCausalArrowMenu(event, linkId) {
    const link = _causalLinksCache.find(l => l.id === linkId);
    if (!link) return;
    const label = link.label || 'Unnamed link';
    _showContextMenu([
        { label: 'Edit label', icon: '✏️', action: `_editArrowLabelWithHypothesis(${linkId},'${escHtml((link.label || '').replace(/'/g, "\\\\'"))}',${link.cause_thread_id},${link.effect_thread_id})` },
        { label: 'Challenge (devil\'s advocate)', icon: '⚠️', action: `_showLinkActions(${linkId});setTimeout(()=>_challengeCausalLink(${linkId}),100)` },
        'separator',
        { label: 'Set: Investigating', icon: '🔎', action: `_updateCausalStatus(${linkId},'investigating')` },
        { label: 'Set: Validated', icon: '✅', action: `_validateCausalLink(${linkId})` },
        { label: 'Set: Disproven', icon: '❌', action: `_updateCausalStatus(${linkId},'disproven')` },
        'separator',
        { label: 'Delete link', icon: '🗑️', action: `_deleteCausalLink(${linkId})`, color: '#ef4444' },
    ], event.clientX, event.clientY, label.substring(0, 40));
}

function _showChainItemMenu(event, pathId) {
    const path = _causalPathsCache.find(p => p.id === pathId);
    if (!path) return;
    const canPromote = (path.thread_ids || []).length >= 2;
    const items = [
        { label: 'Rename chain', icon: '✏️', action: `_selectCausalChain(${pathId});setTimeout(()=>{const t=document.querySelector('.causal-editor-header .editable-title');if(t)_startTitleEdit(t)},200)` },
    ];
    if (canPromote) {
        items.push({ label: 'Move to Narratives', icon: '➜', action: `_promoteChainToNarrative(${pathId})` });
    }
    items.push(
        'separator',
        { label: 'Delete chain', icon: '🗑️', action: `_deleteChain(${pathId})`, color: '#ef4444' },
    );
    _showContextMenu(items, event.clientX, event.clientY, path.name?.substring(0, 40) || 'Chain');
}

function _setCausalMode() {}  // no-op stub for compatibility

// ===================== CHAIN BOARD (Subway Map) =====================
// Single node per thread, chains as colored directed paths, force layout.

let _chainBoardSim = null;
let _chainBoardZoomTransform = null;

const _CB_CHAIN_COLORS = [
    '#3b82f6', '#a855f7', '#f59e0b', '#22c55e',
    '#ef4444', '#ec4899', '#06b6d4', '#8b5cf6',
];

// Persists node positions across re-renders (legend toggles, subtab switches, etc.)
// Keyed by threadId. Cleared only by _cbResetLayout().
let _cbNodePositions = new Map();
// Closure set after each render — recomputes bezier paths for a moved node live
let _cbPathUpdateFn  = null;

// Which chains are currently dimmed (toggled via legend)
let _cbDimmedChains = new Set();

// ── Entry point called from Board tab > Chains subtab ─────────────────────
function _renderChainBoard() {
    const container = document.getElementById('causal-board-container');
    const svgEl = document.getElementById('causal-board-svg');
    if (!container || !svgEl) return;

    const svg = d3.select(svgEl);
    svg.selectAll('*').remove();
    if (_chainBoardSim) { _chainBoardSim.stop(); _chainBoardSim = null; }

    // Chain cache empty — fetch regardless of whether threads are cached.
    // (_threadsCache may be populated from the Threads tab without chain data.)
    if (!_causalPathsCache || !_causalPathsCache.length) {
        Promise.all([
            fetch('/api/causal-links').then(r => r.json()),
            fetch('/api/causal-paths').then(r => r.json()),
            fetch('/api/signal-threads').then(r => r.json()),
        ]).then(function(results) {
            _causalLinksCache = results[0].links || [];
            _causalPathsCache = results[1].paths || [];
            _threadsCache     = results[2].threads || [];
            _renderChainBoard();
        }).catch(function() {});
        return;
    }

    // Chains fetched but genuinely empty
    if (!_causalPathsCache.length) {
        svg.append('text')
            .attr('x', container.clientWidth / 2).attr('y', container.clientHeight / 2)
            .attr('text-anchor', 'middle').attr('fill', 'var(--text-muted)').attr('font-size', 14)
            .text('No chains yet \u2014 build chains in the Chains editor');
        return;
    }

    const width  = container.clientWidth  || 900;
    const height = container.clientHeight || 600;

    // ── 1. Build unique node set (one per thread across all chains) ────────
    const nodeMap = new Map();
    _causalPathsCache.forEach((path, pi) => {
        const color = _CB_CHAIN_COLORS[pi % _CB_CHAIN_COLORS.length];
        (path.thread_ids || []).forEach(tid => {
            if (!nodeMap.has(tid)) {
                const t = (_threadsCache || []).find(t => t.id === tid);
                nodeMap.set(tid, {
                    id: tid,
                    title: t ? t.title || ('Thread #' + tid) : ('Thread #' + tid),
                    domain: t ? t.domain || '' : '',
                    signal_count: t ? t.signal_count || 0 : 0,
                    chainMembership: [],
                    x: 0, y: 0, vx: 0, vy: 0,
                });
            }
            const node = nodeMap.get(tid);
            if (!node.chainMembership.find(function(m) { return m.pathId === path.id; })) {
                node.chainMembership.push({ pathId: path.id, color: color });
            }
        });
    });
    const nodes = Array.from(nodeMap.values());

    // ── 2. Build unique edges ──────────────────────────────────────────────
    const edgeMap = new Map();
    _causalPathsCache.forEach((path, pi) => {
        const color = _CB_CHAIN_COLORS[pi % _CB_CHAIN_COLORS.length];
        const tids = path.thread_ids || [];
        for (var i = 0; i < tids.length - 1; i++) {
            const key = tids[i] + '-' + tids[i + 1];
            if (!edgeMap.has(key)) {
                const lnk = _causalLinksCache.find(function(l) {
                    return l.cause_thread_id === tids[i] && l.effect_thread_id === tids[i + 1];
                });
                edgeMap.set(key, {
                    source: nodeMap.get(tids[i]),
                    target: nodeMap.get(tids[i + 1]),
                    status: lnk ? lnk.status || 'captured' : 'captured',
                    label:  lnk ? lnk.label  || '' : '',
                    chains: [],
                });
            }
            const edge = edgeMap.get(key);
            if (!edge.chains.find(function(c) { return c.pathId === path.id; })) {
                edge.chains.push({ pathId: path.id, color: color });
            }
        }
    });
    const edges = Array.from(edgeMap.values()).filter(function(e) { return e.source && e.target; });

    // ── 3. Estimate causal depth via BFS ──────────────────────────────────
    const inDeg = new Map(nodes.map(function(n) { return [n.id, 0]; }));
    edges.forEach(function(e) { inDeg.set(e.target.id, (inDeg.get(e.target.id) || 0) + 1); });
    const depthMap = new Map();
    const bfsQ = nodes.filter(function(n) { return !inDeg.get(n.id); });
    bfsQ.forEach(function(n) { depthMap.set(n.id, 0); });
    var qi = 0;
    while (qi < bfsQ.length) {
        const cur = bfsQ[qi++];
        const curDepth = depthMap.get(cur.id) || 0;
        edges.filter(function(e) { return e.source.id === cur.id; }).forEach(function(e) {
            const nd = curDepth + 1;
            if (!depthMap.has(e.target.id) || depthMap.get(e.target.id) < nd) {
                depthMap.set(e.target.id, nd);
                bfsQ.push(e.target);
            }
        });
    }
    const maxDepth = Math.max.apply(null, Array.from(depthMap.values()).concat([1]));
    nodes.forEach(function(n) {
        if (!depthMap.has(n.id)) depthMap.set(n.id, Math.floor(maxDepth / 2));
    });

    // ── 4. Positions: restore saved or compute via force sim ──────────────
    const MARGIN = 90;
    const usableW = width - MARGIN * 2;
    const nodeR = function(n) { return Math.sqrt(n.signal_count || 1) * 4.5 + 10; };

    // Nodes with saved positions get restored; new nodes need the sim.
    const needsSim = nodes.filter(function(n) { return !_cbNodePositions.has(n.id); });

    if (needsSim.length > 0) {
        // Set random start for unsaved nodes
        nodes.forEach(function(n) {
            const saved = _cbNodePositions.get(n.id);
            if (saved) {
                n.x = saved.x; n.y = saved.y;
                n.fx = saved.x; n.fy = saved.y; // pin during sim
            } else {
                const depth = depthMap.get(n.id) || 0;
                n.x = MARGIN + (depth / maxDepth) * usableW;
                n.y = height * 0.2 + Math.random() * height * 0.6;
            }
        });
        _chainBoardSim = d3.forceSimulation(nodes)
            .force('depth', d3.forceX(function(n) {
                return MARGIN + ((depthMap.get(n.id) || 0) / maxDepth) * usableW;
            }).strength(0.45))
            .force('centerY', d3.forceY(height / 2).strength(0.08))
            .force('collide', d3.forceCollide(function(n) { return nodeR(n) + 22; }).strength(0.85))
            .force('charge', d3.forceManyBody().strength(-220))
            .stop();
        for (var tick = 0; tick < 150; tick++) _chainBoardSim.tick();
        // Unpin all nodes after sim
        nodes.forEach(function(n) { n.fx = null; n.fy = null; });
    } else {
        // All positions known — restore directly, skip sim
        nodes.forEach(function(n) {
            var saved = _cbNodePositions.get(n.id);
            n.x = saved.x; n.y = saved.y;
        });
    }

    // Persist all positions for next render
    nodes.forEach(function(n) { _cbNodePositions.set(n.id, { x: n.x, y: n.y }); });

    // ── 6. D3 zoom ────────────────────────────────────────────────────────
    const zoomG = svg.append('g').attr('class', 'cb-zoom-group');
    const zoomBehavior = d3.zoom().scaleExtent([0.1, 5]).on('zoom', function(ev) {
        _chainBoardZoomTransform = ev.transform;
        zoomG.attr('transform', ev.transform);
    });
    svg.call(zoomBehavior).on('dblclick.zoom', null);
    if (_chainBoardZoomTransform) {
        zoomG.attr('transform', _chainBoardZoomTransform);
        svg.call(zoomBehavior.transform, _chainBoardZoomTransform);
    }
    svgEl.__cbZoom = zoomBehavior;

    // ── 7. Arrow marker defs per chain color ──────────────────────────────
    const defs = svg.append('defs');
    _causalPathsCache.forEach(function(_, pi) {
        const color = _CB_CHAIN_COLORS[pi % _CB_CHAIN_COLORS.length];
        defs.append('marker')
            .attr('id', 'cbarrow-' + pi).attr('viewBox', '0 0 8 6')
            .attr('refX', 7).attr('refY', 3)
            .attr('markerWidth', 6).attr('markerHeight', 5).attr('orient', 'auto')
            .append('path').attr('d', 'M0,0 L8,3 L0,6 Z').attr('fill', color);
    });

    // ── 8. Pre-compute per-edge offsets for shared edges ──────────────────
    const edgeChainCount = new Map();
    const edgeChainIdx   = new Map();
    _causalPathsCache.forEach(function(path) {
        const tids = path.thread_ids || [];
        for (var i = 0; i < tids.length - 1; i++) {
            const key = tids[i] + '-' + tids[i + 1];
            if (!edgeChainCount.has(key)) edgeChainCount.set(key, 0);
            const idx = edgeChainCount.get(key);
            edgeChainIdx.set(key + '-' + path.id, idx);
            edgeChainCount.set(key, idx + 1);
        }
    });

    // ── 9. Draw chain routes (segment by segment) ─────────────────────────
    const chainPathsG = zoomG.append('g').attr('class', 'cb-chain-paths');

    // Helper: compute the bezier path string for one segment
    function _segPathD(src, tgt, offset) {
        var rSrc = nodeR(src) + 2, rTgt = nodeR(tgt) + 5;
        var dx = tgt.x - src.x, dy = tgt.y - src.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        var sx = src.x + (dx / dist) * rSrc, sy = src.y + (dy / dist) * rSrc;
        var ex = tgt.x - (dx / dist) * rTgt, ey = tgt.y - (dy / dist) * rTgt;
        var ox = -dy / dist * offset, oy = dx / dist * offset;
        var mx = (sx + ex) / 2 + ox;
        var my = (sy + ey) / 2 + oy - Math.max(12, Math.abs(dx) * 0.08);
        return 'M' + (sx+ox) + ',' + (sy+oy) + ' Q' + mx + ',' + my + ' ' + (ex+ox) + ',' + (ey+oy);
    }

    _causalPathsCache.forEach(function(path, pi) {
        var color = _CB_CHAIN_COLORS[pi % _CB_CHAIN_COLORS.length];
        var tids  = path.thread_ids || [];
        var chainNodes = tids.map(function(tid) { return nodeMap.get(tid); }).filter(Boolean);
        if (chainNodes.length < 2) return;

        for (var i = 0; i < chainNodes.length - 1; i++) {
            var src = chainNodes[i], tgt = chainNodes[i + 1];
            var edgeKey = src.id + '-' + tgt.id;
            var total   = edgeChainCount.get(edgeKey) || 1;
            var idx     = edgeChainIdx.get(edgeKey + '-' + path.id) !== undefined
                          ? edgeChainIdx.get(edgeKey + '-' + path.id) : 0;
            var offset  = total > 1 ? (idx - (total - 1) / 2) * 9 : 0;
            var dimmed  = _cbDimmedChains.has(path.id);

            chainPathsG.append('path')
                .attr('data-chain', path.id)
                .attr('data-src', src.id)
                .attr('data-tgt', tgt.id)
                .attr('data-offset', offset)
                .attr('fill', 'none')
                .attr('stroke', color)
                .attr('stroke-width', 2.5)
                .attr('stroke-opacity', dimmed ? 0.07 : 0.82)
                .attr('marker-end', 'url(#cbarrow-' + pi + ')')
                .attr('d', _segPathD(src, tgt, offset))
                .style('cursor', 'pointer')
                .on('mouseenter', (function(pid) { return function() {
                    if (_cbDimmedChains.has(pid)) return;
                    d3.select(this).attr('stroke-width', 4.5).attr('stroke-opacity', 1);
                }; })(path.id))
                .on('mouseleave', function() {
                    d3.select(this).attr('stroke-width', 2.5).attr('stroke-opacity', 0.82);
                })
                .on('click', (function(pid) { return function(event) {
                    event.stopPropagation();
                    _selectCausalChain(pid);
                    switchSignalTab('causal');
                }; })(path.id));
        }
    });

    // ── 10. Edge labels ───────────────────────────────────────────────────
    var labelG = zoomG.append('g').attr('pointer-events', 'none');
    edges.forEach(function(e) {
        if (!e.label) return;
        labelG.append('text')
            .attr('data-src', e.source.id).attr('data-tgt', e.target.id)
            .attr('x', (e.source.x + e.target.x) / 2)
            .attr('y', (e.source.y + e.target.y) / 2 - 16)
            .attr('text-anchor', 'middle').attr('fill', 'var(--text-muted)')
            .attr('font-size', 9)
            .text(e.label.length > 22 ? e.label.slice(0, 20) + '\u2026' : e.label);
    });

    // ── 11. Path-update closure (used by drag — avoids full re-render) ────
    _cbPathUpdateFn = function(movedId) {
        // Recompute bezier for every path segment touching the moved node
        chainPathsG.selectAll('path').each(function() {
            var el  = d3.select(this);
            var sid = +el.attr('data-src'), tid = +el.attr('data-tgt');
            if (sid !== movedId && tid !== movedId) return;
            var src = nodeMap.get(sid), tgt = nodeMap.get(tid);
            if (!src || !tgt) return;
            el.attr('d', _segPathD(src, tgt, +el.attr('data-offset') || 0));
        });
        // Move edge labels
        labelG.selectAll('text').each(function() {
            var el  = d3.select(this);
            var sid = +el.attr('data-src'), tid = +el.attr('data-tgt');
            if (sid !== movedId && tid !== movedId) return;
            var src = nodeMap.get(sid), tgt = nodeMap.get(tid);
            if (!src || !tgt) return;
            el.attr('x', (src.x + tgt.x) / 2).attr('y', (src.y + tgt.y) / 2 - 16);
        });
    };

    // ── 12. Node drag — live path update, no re-render on end ────────────
    var drag = d3.drag()
        .on('start', function(ev, d) {
            d3.select(this).attr('cursor', 'grabbing');
        })
        .on('drag', function(ev, d) {
            d.x = ev.x; d.y = ev.y;
            _cbNodePositions.set(d.id, { x: d.x, y: d.y });
            d3.select(this).attr('transform', 'translate(' + d.x + ',' + d.y + ')');
            if (_cbPathUpdateFn) _cbPathUpdateFn(d.id);
        })
        .on('end', function(ev, d) {
            // Save final position — no re-render (positions persist in _cbNodePositions)
            _cbNodePositions.set(d.id, { x: d.x, y: d.y });
            d3.select(this).attr('cursor', 'grab');
        });

    // ── 12. Render nodes ──────────────────────────────────────────────────
    var nodeG = zoomG.append('g').selectAll('g').data(nodes).join('g')
        .attr('class', 'cb-node')
        .attr('data-thread-id', function(d) { return d.id; })
        .attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; })
        .attr('cursor', 'grab')
        .call(drag)
        .on('click', function(ev, d) {
            ev.stopPropagation();
            _cbClickNode(d.id);
        })
        .on('contextmenu', function(ev, d) {
            ev.preventDefault();
            _showContextMenu([
                { label: 'Inspect thread', icon: '\uD83D\uDD0D', action: '_cbClickNode(' + d.id + ')' },
                { label: 'Edit in Chains tab', icon: '\u270F\uFE0F', action: "switchSignalTab('causal')" },
            ], ev.clientX, ev.clientY, d.title.substring(0, 40));
        })
        .on('mouseenter', function(ev, d) {
            const tt = document.getElementById('chain-node-tooltip');
            if (!tt) return;
            const chains = d.chainMembership.map(function(m) {
                const p = _causalPathsCache.find(function(p) { return p.id === m.pathId; });
                return '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + m.color + ';margin-right:4px"></span>' + escHtml(p ? p.name || 'Chain' : 'Chain');
            }).join('<br>');
            tt.innerHTML = '<div style="font-weight:700;margin-bottom:4px">' + escHtml(d.title) + '</div>' +
                '<div style="font-size:10px;color:var(--text-muted)">' + d.signal_count + ' signals</div>' +
                (chains ? '<div style="margin-top:6px;font-size:10px">' + chains + '</div>' : '');
            tt.style.display = 'block';
            const rect = container.getBoundingClientRect();
            tt.style.left = (ev.clientX - rect.left + 14) + 'px';
            tt.style.top  = (ev.clientY - rect.top  - 10) + 'px';
        })
        .on('mousemove', function(ev) {
            const tt = document.getElementById('chain-node-tooltip');
            if (!tt || tt.style.display === 'none') return;
            const rect = container.getBoundingClientRect();
            tt.style.left = (ev.clientX - rect.left + 14) + 'px';
            tt.style.top  = (ev.clientY - rect.top  - 10) + 'px';
        })
        .on('mouseleave', function() {
            const tt = document.getElementById('chain-node-tooltip');
            if (tt) tt.style.display = 'none';
        });

    nodeG.each(function(d) {
        const g = d3.select(this);
        const r = nodeR(d);
        const domColor = _DOMAIN_COLORS[_parseDomains(d.domain)[0]] || '#6b7280';

        // Chain membership rings (outermost first so smaller rings on top)
        d.chainMembership.slice().reverse().forEach(function(m, ri) {
            g.append('circle')
                .attr('r', r + 4 + ri * 5)
                .attr('fill', 'none')
                .attr('stroke', m.color)
                .attr('stroke-width', 1.5)
                .attr('stroke-dasharray', '3 2')
                .attr('opacity', _cbDimmedChains.has(m.pathId) ? 0.08 : 0.45);
        });

        g.append('circle').attr('r', r)
            .attr('fill', domColor + '33').attr('stroke', domColor).attr('stroke-width', 2);

        g.append('text').attr('text-anchor', 'middle').attr('dy', '0.35em')
            .attr('fill', '#fff').attr('font-size', Math.min(12, r * 0.75)).attr('font-weight', 700)
            .attr('pointer-events', 'none')
            .text(d.signal_count);

        var label = d.title.length > 30 ? d.title.slice(0, 28) + '\u2026' : d.title;
        g.append('text').attr('text-anchor', 'middle').attr('y', r + 13)
            .attr('fill', 'var(--text-secondary)').attr('font-size', 10).attr('font-weight', 600)
            .attr('pointer-events', 'none')
            .text(label);
    });

    // ── 13. Legend ────────────────────────────────────────────────────────
    _cbRenderLegend();
}

function _cbRenderLegend() {
    const el = document.getElementById('causal-board-legend');
    if (!el) return;
    if (!_causalPathsCache || !_causalPathsCache.length) { el.innerHTML = ''; return; }
    el.innerHTML = _causalPathsCache.map(function(path, pi) {
        const color  = _CB_CHAIN_COLORS[pi % _CB_CHAIN_COLORS.length];
        const dimmed = _cbDimmedChains.has(path.id);
        const name   = (path.name || 'Untitled').length > 28
            ? (path.name || 'Untitled').slice(0, 26) + '\u2026'
            : (path.name || 'Untitled');
        return '<div class="cb-legend-item' + (dimmed ? ' cb-legend-dimmed' : '') +
            '" onclick="_cbToggleChainDim(' + path.id + ')" title="' + (dimmed ? 'Show' : 'Hide') + ' this chain">' +
            '<span class="cb-legend-dot" style="background:' + color + '"></span>' +
            '<span class="cb-legend-name">' + escHtml(name) + '</span>' +
            '</div>';
    }).join('');
}

function _cbToggleChainDim(pathId) {
    if (_cbDimmedChains.has(pathId)) _cbDimmedChains.delete(pathId);
    else _cbDimmedChains.add(pathId);
    _renderChainBoard();
}

// ── Board subtab switch ───────────────────────────────────────────────────
function _switchBoardSubtab(tab) {
    const graphDiv  = document.getElementById('board-subtab-graph');
    const chainsDiv = document.getElementById('board-subtab-chains');
    document.querySelectorAll('.board-subtab-btn').forEach(function(b) { b.classList.remove('active'); });
    const btn = document.querySelector('.board-subtab-btn[data-subtab="' + tab + '"]');
    if (btn) btn.classList.add('active');
    localStorage.setItem('board_subtab', tab);

    if (tab === 'graph') {
        if (graphDiv)  graphDiv.style.display  = 'flex';
        if (chainsDiv) chainsDiv.style.display = 'none';
    } else {
        if (graphDiv)  graphDiv.style.display  = 'none';
        if (chainsDiv) chainsDiv.style.display = 'flex';
        setTimeout(function() { _renderChainBoard(); }, 30);
    }
}

function _restoreBoardSubtab() {
    _switchBoardSubtab(localStorage.getItem('board_subtab') || 'graph');
}

// ── Chain board controls ──────────────────────────────────────────────────
function _cbZoom(factor) {
    const svg  = d3.select('#causal-board-svg');
    const zoom = document.getElementById('causal-board-svg') ? document.getElementById('causal-board-svg').__cbZoom : null;
    if (zoom) svg.transition().duration(200).call(zoom.scaleBy, factor);
}

function _cbResetZoom() {
    const svg  = d3.select('#causal-board-svg');
    const zoom = document.getElementById('causal-board-svg') ? document.getElementById('causal-board-svg').__cbZoom : null;
    if (zoom) {
        svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity);
        _chainBoardZoomTransform = null;
    }
}

function _cbResetLayout() {
    _chainBoardZoomTransform = null;
    _cbNodePositions.clear();  // force fresh layout
    _cbPathUpdateFn = null;
    _renderChainBoard();
}

function _cbClickNode(threadId) {
    const detailPane = document.getElementById('signals-detail');
    if (detailPane) detailPane.style.display = '';
    _activeThreadId = threadId;
    const savedTab = _signalTab;
    _signalTab = 'causal_board';
    openThreadDetail(threadId);
    _signalTab = savedTab;
}

// ── Highlight search ──────────────────────────────────────────────────────
let _cbHighlights = [];

function _cbHighlightSearch(query) {
    if (!query || query.length < 2) return;
    const q = query.toLowerCase();
    if (_cbHighlights.some(function(h) { return h.query === q; })) return;
    const matchedIds = new Set();
    (_threadsCache || []).forEach(function(t) {
        const title = (t.title || '').toLowerCase();
        const synth = (t.synthesis || '').toLowerCase();
        if (title.includes(q) || synth.includes(q)) matchedIds.add(t.id);
    });
    if (!matchedIds.size) { _showToast('No matches', 'info'); return; }
    _cbHighlights.push({ label: query.substring(0, 20), query: q, matchedThreadIds: matchedIds });
    _applyCbHighlights();
    _renderCbPills();
    _showToast(matchedIds.size + ' threads match "' + query + '"', 'info');
}

function _removeCbHighlight(idx) {
    _cbHighlights.splice(idx, 1);
    _applyCbHighlights();
    _renderCbPills();
}

function _cbClearHighlight() {
    _cbHighlights = [];
    _applyCbHighlights();
    _renderCbPills();
}

function _applyCbHighlights() {
    const cbNodes = document.querySelectorAll('.cb-node');
    if (!_cbHighlights.length) {
        cbNodes.forEach(function(n) { n.style.filter = ''; n.style.pointerEvents = ''; n.classList.remove('cb-dimmed'); });
        return;
    }
    const unionIds = new Set();
    _cbHighlights.forEach(function(h) { h.matchedThreadIds.forEach(function(id) { unionIds.add(id); }); });
    cbNodes.forEach(function(n) {
        const tid = parseInt(n.dataset.threadId);
        if (unionIds.has(tid)) {
            const matchCount = _cbHighlights.filter(function(h) { return h.matchedThreadIds.has(tid); }).length;
            const glow  = matchCount >= _cbHighlights.length ? '1.5' : '1.2';
            const color = matchCount >= 2 ? 'rgba(6,182,212,0.7)' : 'rgba(168,85,247,0.5)';
            n.style.filter = 'brightness(' + glow + ') drop-shadow(0 0 12px ' + color + ')';
            n.style.pointerEvents = '';
            n.classList.remove('cb-dimmed');
        } else {
            n.style.filter = 'brightness(0.25) saturate(0.3)';
            n.style.pointerEvents = 'none';
            n.classList.add('cb-dimmed');
        }
    });
}

function _renderCbPills() {
    const tray = document.getElementById('cb-highlight-pills');
    if (!tray) return;
    if (!_cbHighlights.length) { tray.innerHTML = ''; tray.style.display = 'none'; return; }
    tray.style.display = 'flex';
    tray.innerHTML = _cbHighlights.map(function(h, i) {
        return '<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 8px;background:rgba(168,85,247,0.1);border:1px solid rgba(168,85,247,0.3);border-radius:12px;font-size:10px;color:#a855f7;font-weight:600;white-space:nowrap">' +
            '\uD83D\uDD0D ' + escHtml(h.label) + ' <span style="font-weight:400;color:var(--text-muted)">' + h.matchedThreadIds.size + '</span>' +
            '<span onclick="_removeCbHighlight(' + i + ')" style="cursor:pointer;margin-left:2px;font-size:12px;color:var(--text-muted);line-height:1">&times;</span>' +
            '</span>';
    }).join('') +
    '<span onclick="_cbClearHighlight()" style="display:inline-flex;align-items:center;padding:3px 8px;border-radius:12px;font-size:10px;color:var(--text-muted);cursor:pointer;border:1px solid var(--border)">Clear all</span>';
}

// Stubs for removed swimlane functions (compatibility)
function _setCausalMode() {}
function _cbTogglePhysics() {}
function _switchCausalViewMode() {}
