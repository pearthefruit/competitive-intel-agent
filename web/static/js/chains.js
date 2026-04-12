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
    // Restore view mode on tab load
    _switchCausalViewMode(_causalViewMode);

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
        // Render chain board if in board mode
        if (_causalViewMode === 'board') _renderChainBoard();
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

// ===================== CHAIN BOARD =====================

let _causalViewMode = localStorage.getItem('causal_view_mode') || 'editor';
let _chainBoardSim = null;
let _chainBoardZoomTransform = null;

// Swimlane board state
let _cbPhysicsEnabled = false;
let _cbSwimLayout = null;
let _cbNodeData = null;
let _cbThreadToNodeMap = null;
let _cbEdgePathFn = null;
let _cbPillarsG = null;
let _cbNodeSel = null;
let _cbLinkSel = null;

function _switchCausalViewMode(mode) {
    _causalViewMode = mode;
    localStorage.setItem('causal_view_mode', mode);
    const layout = document.querySelector('.causal-layout');
    const board = document.getElementById('causal-board-container');
    document.querySelectorAll('.causal-view-btn').forEach(b => b.classList.remove('active'));
    const activeBtn = document.querySelector(`.causal-view-btn[data-mode="${mode}"]`);
    if (activeBtn) activeBtn.classList.add('active');
    if (mode === 'editor') {
        if (layout) layout.style.display = '';
        if (board) board.classList.remove('active');
        if (_chainBoardSim) { _chainBoardSim.stop(); _chainBoardSim = null; }
    } else {
        if (layout) layout.style.display = 'none';
        if (board) board.classList.add('active');
        setTimeout(() => _renderChainBoard(), 50); // slight delay for container to get dimensions
    }
}

function _renderChainBoard() {
    const container = document.getElementById('causal-board-container');
    const svg = d3.select('#causal-board-svg');
    if (!container || !svg.node()) return;

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;
    svg.selectAll('*').remove();
    svg.attr('viewBox', null).attr('height', null);
    if (_chainBoardSim) { _chainBoardSim.stop(); _chainBoardSim = null; }

    if (!_causalPathsCache.length) {
        svg.append('text').attr('x', width / 2).attr('y', height / 2)
            .attr('text-anchor', 'middle').attr('fill', 'var(--text-muted)').attr('font-size', 14)
            .text('No chains yet \u2014 create chains in the Editor view');
        return;
    }

    // ── Swimlane layout ──
    const layout = _computeSwimlaneLayout(_causalPathsCache, width, height);
    _cbSwimLayout = layout;
    if (layout.totalH > height) svg.attr('height', layout.totalH);

    // ── Build nodes ──
    const nodes = [];
    const threadToNodes = {};
    const sharedColors = ['#f59e0b', '#06b6d4', '#a855f7', '#22c55e', '#ef4444', '#ec4899', '#8b5cf6', '#14b8a6'];

    _causalPathsCache.forEach(path => {
        (path.thread_ids || []).forEach((tid, i) => {
            const t = (_threadsCache || []).find(t => t.id === tid);
            const pos = layout.positions[`p${path.id}_t${tid}`] || { x: width / 2, y: height / 2 };
            const node = {
                id: `p${path.id}_t${tid}`,
                threadId: tid, pathId: path.id, pathIndex: i,
                pathLength: (path.thread_ids || []).length,
                pathName: path.name || 'Untitled',
                title: t?.title || `Thread #${tid}`,
                domain: t?.domain || '', signal_count: t?.signal_count || 0,
                shared: false, sharedColor: null,
                x: pos.x, y: pos.y,
            };
            nodes.push(node);
            if (!threadToNodes[tid]) threadToNodes[tid] = [];
            threadToNodes[tid].push(node);
        });
    });
    _cbNodeData = nodes;
    _cbThreadToNodeMap = threadToNodes;

    // ── Deterministic copy colors (hash threadId so same thread always gets same color) ──
    Object.entries(threadToNodes).forEach(([tidStr, copies]) => {
        if (copies.length > 1) {
            const color = sharedColors[parseInt(tidStr) % sharedColors.length];
            copies.forEach(n => { n.shared = true; n.sharedColor = color; });
        }
    });

    // ── Build chain edges (object refs, not string IDs) ──
    const nodeR = d => Math.sqrt(d.signal_count || 1) * 5 + 12;
    const chainEdges = [];
    _causalPathsCache.forEach(path => {
        const tids = path.thread_ids || [];
        for (let i = 0; i < tids.length - 1; i++) {
            const lnk = _causalLinksCache.find(l =>
                l.cause_thread_id === tids[i] && l.effect_thread_id === tids[i + 1]);
            const src = nodes.find(n => n.id === `p${path.id}_t${tids[i]}`);
            const tgt = nodes.find(n => n.id === `p${path.id}_t${tids[i + 1]}`);
            if (src && tgt) chainEdges.push({
                source: src, target: tgt,
                status: lnk?.status || 'captured', label: lnk?.label || '',
                pathId: path.id,
            });
        }
    });

    // ── D3 zoom setup ──
    const zoomGroup = svg.append('g').attr('class', 'cb-zoom-group');
    const zoomBehavior = d3.zoom().scaleExtent([0.15, 4]).on('zoom', (event) => {
        _chainBoardZoomTransform = event.transform;
        zoomGroup.attr('transform', event.transform);
    });
    svg.call(zoomBehavior);
    svg.on('dblclick.zoom', null);
    if (_chainBoardZoomTransform) {
        zoomGroup.attr('transform', _chainBoardZoomTransform);
        svg.call(zoomBehavior.transform, _chainBoardZoomTransform);
    }
    svg.node().__cbZoom = zoomBehavior;

    // ── Arrow markers per status ──
    const defs = svg.append('defs');
    Object.entries(_causalStatusColors).forEach(([status, color]) => {
        defs.append('marker')
            .attr('id', `cb-arrow-${status}`).attr('viewBox', '0 0 10 6')
            .attr('refX', 9).attr('refY', 3)
            .attr('markerWidth', 7).attr('markerHeight', 5).attr('orient', 'auto')
            .append('path').attr('d', 'M0,0 L10,3 L0,6 Z').attr('fill', color);
    });

    // ── Lane backgrounds (alternating tint) ──
    const lanesBg = zoomGroup.append('g').attr('class', 'cb-lanes').attr('pointer-events', 'none');
    layout.sorted.forEach((_, row) => {
        if (row % 2 === 0) return;
        const y = layout.MARGIN_V + row * layout.LANE_HEIGHT;
        lanesBg.append('rect')
            .attr('x', -9999).attr('y', y - layout.LANE_HEIGHT / 2)
            .attr('width', 19998).attr('height', layout.LANE_HEIGHT)
            .attr('fill', 'rgba(255,255,255,0.018)');
    });

    // ── Lane labels (left margin) ──
    const labelsG = zoomGroup.append('g').attr('class', 'cb-lane-labels').attr('pointer-events', 'none');
    layout.sorted.forEach((path, row) => {
        const y = layout.MARGIN_V + row * layout.LANE_HEIGHT;
        const name = path.name || 'Untitled';
        labelsG.append('text')
            .attr('x', 8).attr('y', y + 4)
            .attr('fill', 'var(--accent)').attr('font-size', 10).attr('font-weight', 700).attr('opacity', 0.7)
            .text(name.length > 26 ? name.substring(0, 24) + '\u2026' : name);
    });

    // ── Copy pillars (vertical dashed connectors between shared-thread copies) ──
    const pillarsG = zoomGroup.append('g').attr('class', 'cb-pillars').attr('pointer-events', 'none');
    _cbPillarsG = pillarsG;
    _cbUpdatePillars();

    // ── Edge path function (quadratic bezier, arcs above the lane) ──
    const edgePath = (d) => {
        const src = d.source, tgt = d.target;
        const dx = tgt.x - src.x, dy = tgt.y - src.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const rSrc = nodeR(src), rTgt = nodeR(tgt);
        const sx = src.x + (dx / dist) * rSrc;
        const sy = src.y + (dy / dist) * rSrc;
        const ex = tgt.x - (dx / dist) * (rTgt + 4);
        const ey = tgt.y - (dy / dist) * (rTgt + 4);
        const mx = (sx + ex) / 2;
        const my = (sy + ey) / 2 - Math.max(18, Math.abs(dx) * 0.1);
        return `M${sx},${sy} Q${mx},${my} ${ex},${ey}`;
    };
    _cbEdgePathFn = edgePath;

    // ── Render edges ──
    const linkG = zoomGroup.append('g').attr('class', 'cb-edges');
    const link = linkG.selectAll('path').data(chainEdges).join('path')
        .attr('fill', 'none')
        .attr('stroke', d => _causalStatusColors[d.status] || '#6b7280')
        .attr('stroke-width', 2)
        .attr('stroke-opacity', 0.85)
        .attr('marker-end', d => `url(#cb-arrow-${d.status || 'captured'})`)
        .attr('d', edgePath);
    _cbLinkSel = link;

    const linkLabel = zoomGroup.append('g').selectAll('text')
        .data(chainEdges.filter(e => e.label)).join('text')
        .attr('text-anchor', 'middle').attr('fill', 'var(--text-muted)').attr('font-size', 9)
        .attr('pointer-events', 'none')
        .attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2 - Math.max(18, Math.abs(d.target.x - d.source.x) * 0.1) - 5)
        .text(d => d.label.length > 20 ? d.label.substring(0, 18) + '\u2026' : d.label);

    // ── Drag behavior ──
    const drag = d3.drag()
        .on('start', (event, d) => {
            if (_cbPhysicsEnabled && _chainBoardSim) {
                _chainBoardSim.alphaTarget(0.1).restart();
                d.fx = d.x; d.fy = d.y;
            }
        })
        .on('drag', (event, d) => {
            d.x = event.x; d.y = event.y;
            if (_cbPhysicsEnabled && _chainBoardSim) {
                d.fx = event.x; d.fy = event.y;
            } else {
                _cbNodeSel?.filter(n => n.id === d.id).attr('transform', `translate(${d.x},${d.y})`);
                link.attr('d', edgePath);
                linkLabel
                    .attr('x', e => (e.source.x + e.target.x) / 2)
                    .attr('y', e => (e.source.y + e.target.y) / 2 - Math.max(18, Math.abs(e.target.x - e.source.x) * 0.1) - 5);
                _cbUpdatePillars();
            }
        })
        .on('end', (event, d) => {
            if (_cbPhysicsEnabled && _chainBoardSim) {
                _chainBoardSim.alphaTarget(0);
                d.fx = null; d.fy = null;
            }
        });

    // ── Render nodes ──
    const node = zoomGroup.append('g').selectAll('g').data(nodes).join('g')
        .attr('class', 'cb-node')
        .attr('data-thread-id', d => d.threadId)
        .attr('transform', d => `translate(${d.x},${d.y})`)
        .attr('cursor', 'grab')
        .call(drag)
        .on('click', (event, d) => {
            event.stopPropagation();
            const detailPane = document.getElementById('signals-detail');
            if (detailPane) detailPane.style.display = '';
            _activeThreadId = d.threadId;
            const savedTab = _signalTab;
            _signalTab = 'causal_board';
            openThreadDetail(d.threadId);
            _signalTab = savedTab;
            // Pulse shared copies on click
            if (d.shared) {
                const copies = threadToNodes[d.threadId] || [];
                node.select('.cb-shared-ring').attr('opacity', dd =>
                    copies.some(c => c.id === dd.id) ? 1 : (dd.shared ? 0.15 : 0));
                setTimeout(() => node.select('.cb-shared-ring').attr('opacity', dd => dd.shared ? 0.6 : 0), 2500);
            }
            node.each(function(dd) {
                d3.select(this).select('circle:not(.cb-shared-ring)')
                    .attr('stroke-width', dd.id === d.id ? 3.5 : 2);
            });
        })
        .on('contextmenu', (event, d) => {
            event.preventDefault();
            event.stopPropagation();
            const items = [
                { label: 'Inspect thread', icon: '🔍', action: `_cbClickNode(${d.threadId})` },
                { label: 'Open chain in editor', icon: '✏️', action: `_selectCausalChain(${d.pathId});_switchCausalViewMode('editor')` },
            ];
            if (d.shared) items.push({ label: 'Align copies vertically', icon: '⬡', action: `_cbAlignCopies(${d.threadId})` });
            _showContextMenu(items, event.clientX, event.clientY, d.title.substring(0, 40));
        });
    _cbNodeSel = node;

    node.each(function(d) {
        const g = d3.select(this);
        const r = nodeR(d);
        const domColor = _DOMAIN_COLORS[_parseDomains(d.domain)[0]] || '#6b7280';
        if (d.shared) {
            g.append('circle').attr('class', 'cb-shared-ring')
                .attr('r', r + 5).attr('fill', 'none')
                .attr('stroke', d.sharedColor).attr('stroke-width', 2)
                .attr('stroke-dasharray', '3 2').attr('opacity', 0.6);
        }
        g.append('circle').attr('r', r)
            .attr('fill', domColor + '33').attr('stroke', domColor).attr('stroke-width', 2);
        g.append('text').attr('text-anchor', 'middle').attr('dy', '0.35em')
            .attr('fill', '#fff').attr('font-size', Math.min(13, r * 0.7)).attr('font-weight', 700)
            .attr('pointer-events', 'none').text(d.signal_count);
        g.append('text').attr('text-anchor', 'middle').attr('y', r + 14)
            .attr('fill', 'var(--text-secondary)').attr('font-size', 10).attr('font-weight', 600)
            .attr('pointer-events', 'none')
            .text(d.title.length > 25 ? d.title.substring(0, 23) + '\u2026' : d.title);
    });

    // ── Optional physics (weak forces that attract back to swimlane positions) ──
    if (_cbPhysicsEnabled) {
        _chainBoardSim = d3.forceSimulation(nodes)
            .force('swimX', d3.forceX(d => (layout.positions[d.id] || { x: width / 2 }).x).strength(0.07))
            .force('swimY', d3.forceY(d => (layout.positions[d.id] || { y: height / 2 }).y).strength(0.1))
            .force('collide', d3.forceCollide().radius(d => nodeR(d) + 12))
            .on('tick', () => {
                node.attr('transform', d => `translate(${d.x},${d.y})`);
                link.attr('d', edgePath);
                linkLabel
                    .attr('x', d => (d.source.x + d.target.x) / 2)
                    .attr('y', d => (d.source.y + d.target.y) / 2 - 14);
                _cbUpdatePillars();
            });
        _chainBoardSim.alpha(0.3).restart();
    }
}

// ── Swimlane Layout Engine ──
function _computeSwimlaneLayout(paths, svgWidth, svgHeight) {
    if (!paths.length) return { positions: {}, sorted: [], LANE_HEIGHT: 150, MARGIN_H: 110, MARGIN_V: 70, totalH: svgHeight };

    const sorted = [...paths].sort((a, b) => (b.thread_ids || []).length - (a.thread_ids || []).length);
    const threadX = {}; // threadId → fractional x [0..1]

    // Anchor path (longest): evenly spaced
    const anchor = sorted[0];
    const anchorLen = (anchor.thread_ids || []).length;
    (anchor.thread_ids || []).forEach((tid, i) => {
        threadX[tid] = anchorLen > 1 ? i / (anchorLen - 1) : 0.5;
    });

    // Remaining paths: pin shared threads to their canonical x, interpolate non-shared
    for (const path of sorted.slice(1)) {
        const tids = path.thread_ids || [];
        const n = tids.length;
        if (!n) continue;
        const slots = tids.map((tid, i) => ({ tid, i, x: threadX[tid] ?? null }));

        for (let i = 0; i < n; i++) {
            if (slots[i].x !== null) continue;
            let prev = null, next = null;
            for (let j = i - 1; j >= 0; j--) if (slots[j].x !== null) { prev = slots[j]; break; }
            for (let j = i + 1; j < n; j++) if (slots[j].x !== null) { next = slots[j]; break; }

            if (prev && next) {
                // Interpolate between two anchors
                slots[i].x = prev.x + ((i - prev.i) / (next.i - prev.i)) * (next.x - prev.x);
            } else if (prev) {
                // Extend right from last anchor
                const step = (1 - prev.x) / Math.max(n - prev.i, 1);
                slots[i].x = Math.min(1, prev.x + (i - prev.i) * step);
            } else if (next) {
                // Extend left from next anchor
                const step = next.x / Math.max(next.i + 1, 1);
                slots[i].x = Math.max(0, next.x - (next.i - i) * step);
            } else {
                slots[i].x = n > 1 ? i / (n - 1) : 0.5;
            }
            // Write back so later paths can use this as a shared anchor if needed
            threadX[tids[i]] = slots[i].x;
        }
    }

    // Pixel geometry
    const MARGIN_H = 110, MARGIN_V = 70;
    const usableW = Math.max(svgWidth - 2 * MARGIN_H, 300);

    // Lane height: scale with max node radius so labels don't overlap
    const allCounts = sorted.flatMap(p =>
        (p.thread_ids || []).map(tid => (_threadsCache || []).find(t => t.id === tid)?.signal_count || 0)
    );
    const maxR = Math.sqrt(Math.max(...allCounts, 1)) * 5 + 12;
    const LANE_HEIGHT = Math.max(maxR * 2 + 80, 150);

    const positions = {};
    sorted.forEach((path, row) => {
        (path.thread_ids || []).forEach(tid => {
            positions[`p${path.id}_t${tid}`] = {
                x: MARGIN_H + (threadX[tid] ?? 0.5) * usableW,
                y: MARGIN_V + row * LANE_HEIGHT,
                row,
            };
        });
    });

    const totalH = MARGIN_V + Math.max(0, sorted.length - 1) * LANE_HEIGHT + maxR + MARGIN_V + 20;
    return { positions, sorted, LANE_HEIGHT, MARGIN_H, MARGIN_V, totalH };
}

// Re-render vertical pillar connectors between shared thread copies
function _cbUpdatePillars() {
    if (!_cbPillarsG || !_cbThreadToNodeMap) return;
    const sharedColors = ['#f59e0b', '#06b6d4', '#a855f7', '#22c55e', '#ef4444', '#ec4899', '#8b5cf6', '#14b8a6'];
    _cbPillarsG.selectAll('*').remove();
    Object.entries(_cbThreadToNodeMap).forEach(([tidStr, copies]) => {
        if (copies.length < 2) return;
        const color = sharedColors[parseInt(tidStr) % sharedColors.length];
        const avgX = copies.reduce((s, c) => s + c.x, 0) / copies.length;
        const yMin = Math.min(...copies.map(c => c.y));
        const yMax = Math.max(...copies.map(c => c.y));
        _cbPillarsG.append('line')
            .attr('x1', avgX).attr('y1', yMin)
            .attr('x2', avgX).attr('y2', yMax)
            .attr('stroke', color).attr('stroke-width', 1.5)
            .attr('stroke-dasharray', '5 3').attr('opacity', 0.4);
    });
}

// Right-click → align all copies of a thread to same x position
function _cbAlignCopies(threadId) {
    if (!_cbNodeData || !_cbEdgePathFn || !_cbNodeSel || !_cbLinkSel) return;
    const copies = _cbNodeData.filter(n => n.threadId === threadId);
    if (copies.length < 2) return;
    // Use the swimlane canonical x (average of computed positions) as the target
    const targetX = copies.reduce((s, c) => s + c.x, 0) / copies.length;
    copies.forEach(n => { n.x = targetX; });
    _cbNodeSel.attr('transform', d => `translate(${d.x},${d.y})`);
    _cbLinkSel.attr('d', _cbEdgePathFn);
    _cbUpdatePillars();
    _showToast(`Aligned ${copies.length} copies`, 'info');
}

// Reset all nodes to their computed swimlane positions
function _cbResetLayout() {
    _renderChainBoard();
}

// Toggle physics mode (weak forces that respect swimlane structure)
function _cbTogglePhysics() {
    _cbPhysicsEnabled = !_cbPhysicsEnabled;
    const btn = document.getElementById('cb-physics-btn');
    if (btn) {
        btn.classList.toggle('active', _cbPhysicsEnabled);
        btn.title = _cbPhysicsEnabled ? 'Physics ON — click to disable' : 'Toggle physics';
    }
    _renderChainBoard();
}

// ── Chain Board Controls ──
function _cbZoom(factor) {
    const svg = d3.select('#causal-board-svg');
    const zoom = svg.node()?.__cbZoom;
    if (zoom) svg.transition().duration(200).call(zoom.scaleBy, factor);
}
function _cbResetZoom() {
    const svg = d3.select('#causal-board-svg');
    const zoom = svg.node()?.__cbZoom;
    if (zoom) { svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity); _chainBoardZoomTransform = null; }
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

let _cbHighlights = []; // [{label, query, matchedThreadIds: Set}]

function _cbHighlightSearch(query) {
    if (!query || query.length < 2) return;
    const q = query.toLowerCase();
    // Check if already highlighted
    if (_cbHighlights.some(h => h.query === q)) return;
    const matchedIds = new Set();
    (_threadsCache || []).forEach(t => {
        const title = (t.title || '').toLowerCase();
        const synthesis = (t.synthesis || '').toLowerCase();
        if (title.includes(q) || synthesis.includes(q)) matchedIds.add(t.id);
    });
    if (!matchedIds.size) { _showToast('No matches', 'info'); return; }
    _cbHighlights.push({ label: query.substring(0, 20), query: q, matchedThreadIds: matchedIds });
    _applyCbHighlights();
    _renderCbPills();
    _showToast(`${matchedIds.size} threads match "${query}"`, 'info');
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
        cbNodes.forEach(n => { n.style.filter = ''; n.style.pointerEvents = ''; n.classList.remove('cb-dimmed'); });
        return;
    }
    const unionIds = new Set();
    _cbHighlights.forEach(h => h.matchedThreadIds.forEach(id => unionIds.add(id)));
    cbNodes.forEach(n => {
        const tid = parseInt(n.dataset.threadId);
        if (unionIds.has(tid)) {
            const matchCount = _cbHighlights.filter(h => h.matchedThreadIds.has(tid)).length;
            const glow = matchCount >= _cbHighlights.length ? '1.5' : '1.2';
            const color = matchCount >= 2 ? 'rgba(6,182,212,0.7)' : 'rgba(168,85,247,0.5)';
            n.style.filter = `brightness(${glow}) drop-shadow(0 0 12px ${color})`;
            n.style.pointerEvents = '';
            n.classList.remove('cb-dimmed');
            // Pulse new highlights
            const circle = n.querySelector('circle:not(.cb-shared-ring)');
            if (circle) {
                const origR = circle.getAttribute('r');
                if (origR) d3.select(circle).transition().duration(150).attr('r', parseFloat(origR) * 1.15).transition().duration(200).attr('r', origR);
            }
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
    tray.innerHTML = _cbHighlights.map((h, i) =>
        `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 8px;background:rgba(168,85,247,0.1);border:1px solid rgba(168,85,247,0.3);border-radius:12px;font-size:10px;color:#a855f7;font-weight:600;white-space:nowrap">
            🔍 ${escHtml(h.label)} <span style="font-weight:400;color:var(--text-muted)">${h.matchedThreadIds.size}</span>
            <span onclick="_removeCbHighlight(${i})" style="cursor:pointer;margin-left:2px;font-size:12px;color:var(--text-muted);line-height:1" title="Remove">&times;</span>
        </span>`
    ).join('') +
    `<span onclick="_cbClearHighlight()" style="display:inline-flex;align-items:center;padding:3px 8px;border-radius:12px;font-size:10px;color:var(--text-muted);cursor:pointer;border:1px solid var(--border);white-space:nowrap">Clear all</span>`;
}

