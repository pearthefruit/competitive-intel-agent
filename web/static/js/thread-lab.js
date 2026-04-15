// ─── Thread Lab ──────────────────────────────────────────────────────────────
// Two modes:
//   split    — opened from a thread, clusters its signals for splitting into sub-threads
//   organize — opened from signals tab, clusters ALL unassigned signals for assignment to threads
// Shared kanban UI: drag-and-drop, shift+click multi-select, heatmap search, approve, cohesion.

let _labSortablesMounted = false;
let _labSelected = new Set();  // signal IDs currently selected for mass-move

// ─── Keyword groups ───────────────────────────────────────────────────────────
// Each group: { label, color, key, signalIds: Set }
let _labKeywordGroups = [];
const _LAB_KG_COLORS = ['#06b6d4','#a855f7','#f59e0b','#10b981','#ec4899','#f97316','#8b5cf6','#14b8a6'];

// ─── Entry points ────────────────────────────────────────────────────────────

function _openThreadLab(threadId) {
    _labOpenModal('split', `/api/signals/threads/${threadId}/lab`, threadId);
}

function _openOrganizeLab() {
    _labOpenModal('organize', '/api/signals/organize-lab', null);
}

function _labOpenModal(mode, url, threadId) {
    document.getElementById('thread-lab-modal')?.remove();
    _labKeywordGroups = [];
    const isOrganize = mode === 'organize';
    const modal = document.createElement('div');
    modal.id = 'thread-lab-modal';
    modal.className = 'thread-lab-modal';
    modal.innerHTML = `
        <div class="thread-lab-inner${isOrganize ? ' lab-organize-mode' : ''}">
            <div class="thread-lab-header">
                <div style="display:flex;flex-direction:column;gap:2px;min-width:0;flex-shrink:0">
                    <span class="thread-lab-title">${isOrganize ? 'Organize Signals' : 'Thread Lab'}</span>
                    <span id="thread-lab-subtitle" style="font-size:11px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
                </div>
                <div class="lab-search-wrap">
                    <input id="lab-global-search" class="lab-search-bar" placeholder="Search to highlight… Enter to pin as group"
                        oninput="_labSearch(this.value)"
                        onkeydown="if(event.key==='Enter'&&this.value.trim())_labAddKeywordGroup(this.value.trim())"
                        autocomplete="off" />
                    <button id="lab-select-all-btn" class="lab-select-all-btn" style="display:none"
                        onclick="_labSelectAllMatches()">Grab all</button>
                </div>
                <div id="lab-kg-tray" class="lab-kg-tray" style="display:none"></div>
                <button class="thread-lab-close" onclick="document.getElementById('thread-lab-modal').remove()">×</button>
            </div>
            <div id="thread-lab-body" class="thread-lab-body">
                <div style="padding:80px;text-align:center;color:var(--text-muted);font-size:12px">${isOrganize ? 'Clustering unassigned signals…' : 'Clustering signals…'}</div>
            </div>
        </div>`;
    document.body.appendChild(modal);

    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                document.getElementById('thread-lab-body').innerHTML =
                    `<div style="padding:80px;text-align:center;color:#ef4444;font-size:12px">${escHtml(data.error)}</div>`;
                return;
            }
            const sub = document.getElementById('thread-lab-subtitle');
            if (sub) sub.textContent = isOrganize
                ? `${data.total_unassigned || data.health?.signal_count || 0} unassigned signals`
                : data.title;
            _labBuildState(data, threadId, mode);
            _labRenderKanban();
        })
        .catch(() => {
            document.getElementById('thread-lab-body').innerHTML =
                `<div style="padding:80px;text-align:center;color:#ef4444;font-size:12px">Failed to load</div>`;
        });
}

// ─── State ───────────────────────────────────────────────────────────────────

function _labBuildState(data, threadId, mode) {
    const simIdxMap = {};
    (data.sim_order || []).forEach((id, i) => simIdxMap[id] = i);
    const isOrganize = mode === 'organize';

    window._threadLabState = {
        mode: mode || 'split',
        threadId,
        originalData: data,
        simMatrix: data.sim_matrix || [],
        simIdxMap,
        groups: data.sub_groups.map(g => ({
            cluster_idx: g.cluster_idx,
            label: g.label,
            key_terms: g.key_terms,
            cohesion: g.cohesion ?? null,
            suggested_thread: g.suggested_thread || null,
            group_type: g.group_type || null,       // 'thread_match' | 'event_burst' | null
            date_range: g.date_range || null,        // e.g. 'Apr 9–13'
            // In organize mode, pre-accept suggestions (inverse of split mode)
            _accepted_thread_id: isOrganize && g.suggested_thread ? g.suggested_thread.id : null,
            _accepted_thread_title: isOrganize && g.suggested_thread ? g.suggested_thread.title : null,
            active: true,
            signals: g.signals.map(s => ({ ...s, from_pool: false, original_thread_id: null })),
        })),
        overflowSignals: data.overflow_signals || [],
    };
}

function _labColCohesion(signalIds) {
    const state = window._threadLabState;
    if (!state?.simMatrix?.length) return null;
    const idxs = signalIds.map(id => state.simIdxMap[id]).filter(i => i !== undefined);
    if (idxs.length < 2) return null;
    let sum = 0, count = 0;
    for (let i = 0; i < idxs.length; i++) {
        for (let j = i + 1; j < idxs.length; j++) {
            sum += state.simMatrix[idxs[i]][idxs[j]];
            count++;
        }
    }
    return count > 0 ? Math.round((sum / count) * 1000) / 1000 : null;
}

// ─── Kanban rendering ────────────────────────────────────────────────────────

function _labRenderKanban() {
    const body = document.getElementById('thread-lab-body');
    if (!body) return;
    const state = window._threadLabState;
    const data = state.originalData;
    const health = data.health;
    const isOrganize = state.mode === 'organize';

    const cs = health.coherence_score;
    // In organize mode, coherence = avg best-thread match (0.2–0.6 is healthy)
    const cColor = isOrganize
        ? (cs < 0.15 ? '#ef4444' : cs < 0.30 ? '#f59e0b' : '#22c55e')
        : (cs < 0.15 ? '#ef4444' : cs < 0.30 ? '#f59e0b' : '#22c55e');
    const cLabel = isOrganize
        ? (cs < 0.15 ? 'low match' : cs < 0.30 ? 'ok match' : 'good match')
        : (cs < 0.15 ? 'low cohesion' : cs < 0.30 ? 'medium cohesion' : 'high cohesion');

    // Build each group column
    const groupCols = state.groups.map((g, gi) => {
        const cards = g.signals.map(s => _labSigCard(s, isOrganize)).join('');
        const isAccepted = !!g._accepted_thread_id;

        // group_type determines left-border color and cohesion label
        const gtype = g.group_type;  // 'thread_match' | 'event_burst' | null
        const colTypeClass = gtype === 'thread_match' ? ' lab-col-thread-match'
                           : gtype === 'event_burst'  ? ' lab-col-event-burst'
                           : '';

        // Suggestion badge — in thread_match mode the suggestion IS the column, show it differently
        const suggBadge = (g.suggested_thread && gtype !== 'thread_match') ? `
            <div class="lab-col-sugg-row">
                <span class="lab-suggestion-badge${isAccepted ? ' lab-suggestion-accepted' : ''}" data-suggest-gi="${gi}"
                    data-suggest-tid="${g.suggested_thread.id}"
                    data-suggest-title="${escHtml(g.suggested_thread.title)}">
                    → "${escHtml(g.suggested_thread.title.slice(0, 28))}" (${Math.round(g.suggested_thread.similarity * 100)}%)
                </span>
            </div>` : '';

        // Cohesion badge — label differs by group type
        const cohVal = g.cohesion ?? _labColCohesion(g.signals.map(s => s.id));
        const cohLabel = gtype === 'thread_match' ? 'match' : 'cohesion';
        const cohHtml = cohVal !== null
            ? `<span class="lab-col-cohesion" id="lab-coh-${g.cluster_idx}"
                title="${cohLabel} score"
                style="color:${cohVal < 0.15 ? '#ef4444' : cohVal < 0.30 ? '#f59e0b' : '#22c55e'}">${cohVal.toFixed(2)}</span>`
            : `<span class="lab-col-cohesion" id="lab-coh-${g.cluster_idx}"></span>`;

        // Date range badge
        const dateBadge = g.date_range
            ? `<span class="lab-col-date-range">${escHtml(g.date_range)}</span>`
            : '';

        return `
            <div class="lab-kanban-col${colTypeClass}" data-lab-col-gi="${gi}">
                <div class="lab-col-header">
                    <input class="lab-col-name" value="${escHtml(isAccepted ? g._accepted_thread_title : g.label)}"
                        ${isAccepted ? 'readonly' : ''}
                        oninput="window._threadLabState.groups[${gi}].label=this.value" />
                    <span class="lab-col-count" id="lab-cnt-${g.cluster_idx}">${g.signals.length}</span>
                    ${cohHtml}
                    <button class="lab-col-approve" title="${isOrganize ? 'Assign to thread' : 'Approve & split off'}" onclick="_labApproveCol(${gi})">✓</button>
                    ${isOrganize
                        ? `<button class="lab-col-dismiss-all" title="Dismiss all as noise" onclick="_labDismissCol(${gi})">🗑</button>`
                        : `<button class="lab-col-toggle" title="Keep in original thread" onclick="_labToggleCol(${gi})">×</button>`}
                </div>
                ${suggBadge}
                <div class="lab-col-terms">${escHtml(g.key_terms.slice(0,4).join(' · '))}${dateBadge}</div>
                <div class="lab-col-body" id="lab-col-${g.cluster_idx}">${cards}</div>
            </div>`;
    }).join('');

    // Pool / overflow column
    let poolCol = '';
    if (isOrganize) {
        const overflowCards = (state.overflowSignals || []).map(s =>
            _labSigCard({ ...s, from_pool: true, original_thread_id: null, _thread_label: '', _sim: 0 }, isOrganize)
        ).join('') || '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:11px">No unsorted signals</div>';
        poolCol = `
            <div class="lab-kanban-col lab-overflow-col">
                <div class="lab-col-header">
                    <span class="lab-col-name-text">Unsorted</span>
                    <span class="lab-col-count">${(state.overflowSignals || []).length}</span>
                </div>
                <div class="lab-col-terms">Drag into any group →</div>
                <div class="lab-col-body" id="lab-pool-signals">${overflowCards}</div>
            </div>`;
    } else {
        const poolCards = (data.related_from_other_threads || []).map(r =>
            _labSigCard({
                id: r.signal_id, title: r.title, published_at: r.published_at,
                body: r.body || '', source_name: r.source_name || '',
                from_pool: true, original_thread_id: r.current_thread_id,
                _thread_label: r.current_thread_title.slice(0, 30),
                _sim: Math.round(r.similarity * 100),
            }, false)
        ).join('') || '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:11px">No related signals found</div>';
        poolCol = `
            <div class="lab-kanban-col lab-pool-col">
                <div class="lab-col-header">
                    <span class="lab-col-name-text">From other threads</span>
                    <span class="lab-col-count">${(data.related_from_other_threads || []).length}</span>
                </div>
                <div class="lab-col-terms">Drag into any group →</div>
                <div class="lab-col-body" id="lab-pool-signals">${poolCards}</div>
            </div>`;
    }

    // "+" drop zone — drag cards here to create a new column
    const newColZone = `
        <div class="lab-kanban-col lab-new-col">
            <div class="lab-col-header">
                <span class="lab-col-name-text">+ New thread</span>
            </div>
            <div class="lab-col-body" id="lab-col-new"></div>
        </div>`;

    const activeCount = state.groups.filter(g => g.active && g.signals.length >= 2).length;
    const actionLabel = isOrganize
        ? `📥 Assign all ${activeCount} group${activeCount !== 1 ? 's' : ''}`
        : `✂️ Split off ${activeCount} thread${activeCount !== 1 ? 's' : ''}`;

    body.innerHTML = `
        <div class="thread-lab-health">
            <span class="lab-health-stat">${health.signal_count} signals</span>
            ${health.date_span_days != null ? `<span class="lab-health-stat">${health.date_span_days}d span</span>` : ''}
            ${health.date_min ? `<span class="lab-health-stat">${health.date_min.slice(0,7)} → ${health.date_max.slice(0,7)}</span>` : ''}
            <span class="lab-health-stat" style="color:${cColor}" title="${isOrganize ? 'avg similarity to best matching thread' : 'overall signal coherence'}">${cLabel} (${cs})</span>
        </div>
        <div class="thread-lab-kanban-wrap">
            <div class="thread-lab-kanban">${groupCols}${poolCol}${newColZone}</div>
            <div id="lab-sig-detail" class="lab-sig-detail-panel"></div>
        </div>
        <div class="thread-lab-footer">
            <button id="lab-split-btn" onclick="_labExecuteAction()"
                style="padding:8px 18px;background:var(--purple);border:none;border-radius:7px;color:#fff;font-size:12px;font-weight:600;cursor:pointer">
                ${actionLabel}
            </button>
            ${isOrganize && state.groups.length > 0 ? `
                <button id="lab-recluster-btn" class="lab-recluster-btn" onclick="_labRecluster()" style="display:none">
                    Re-cluster remainder
                </button>` : ''}
            <span class="lab-hint">Shift+click select · Ctrl+A grab matches · Ctrl+⌫ clear · drag to move · Esc close</span>
            <button onclick="document.getElementById('thread-lab-modal').remove()"
                style="margin-left:auto;padding:8px 14px;background:none;border:1px solid var(--border);border-radius:7px;color:var(--text-muted);font-size:12px;cursor:pointer">
                Cancel
            </button>
        </div>`;

    requestAnimationFrame(() => {
        _labInitSortables();
        if (_labKeywordGroups.length) _labUpdateAllCardDots();
    });
}

function _labSigCard(s, isOrganize) {
    const dateStr = (s.published_at || '').slice(0, 7);
    const meta = s.from_pool && !isOrganize
        ? `<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">→ ${escHtml(s._thread_label || '')}</span><span style="color:var(--accent);flex-shrink:0">${s._sim || ''}%</span>`
        : `<span>${escHtml(dateStr)}</span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-muted)">${escHtml(s.source_name||'')}</span>`;
    const dismissBtn = isOrganize
        ? `<button class="lab-sig-dismiss" onclick="event.stopPropagation();_labDismissSignal(${s.id},this)" title="Dismiss as noise">✕</button>`
        : '';
    return `<div class="lab-sig-card${s.from_pool ? ' lab-sig-pool' : ''}"
        data-signal-id="${s.id}"
        data-signal-title="${escHtml(s.title)}"
        data-signal-date="${escHtml(dateStr)}"
        data-signal-source="${escHtml(s.source_name||'')}"
        data-signal-body="${escHtml((s.body||'').slice(0,300))}"
        data-from-pool="${s.from_pool ? 'true' : 'false'}"
        ${s.original_thread_id ? `data-original-thread-id="${s.original_thread_id}"` : ''}>
        <div class="lab-kg-dots"></div>
        <div class="lab-sig-title">${escHtml(s.title)}</div>
        <div class="lab-sig-meta">${meta}${dismissBtn}</div>
    </div>`;
}

// ─── SortableJS + click delegation ───────────────────────────────────────────

function _labInitSortables() {
    if (typeof Sortable === 'undefined') return;

    const state = window._threadLabState;
    if (!state) return;
    _labSelected.clear();

    const sharedCfg = {
        group: 'lab-signals',
        animation: 120,
        ghostClass: 'lab-sig-ghost',
        onStart: _labOnDragStart,
        onEnd: _labOnDragEnd,
    };

    state.groups.forEach(g => {
        const el = document.getElementById(`lab-col-${g.cluster_idx}`);
        if (el) new Sortable(el, sharedCfg);
    });

    const poolEl = document.getElementById('lab-pool-signals');
    if (poolEl) {
        new Sortable(poolEl, {
            ...sharedCfg,
            group: { name: 'lab-signals', pull: true, put: true },
            sort: false,
        });
    }

    // "+" new column drop zone
    const newColEl = document.getElementById('lab-col-new');
    if (newColEl) {
        new Sortable(newColEl, {
            ...sharedCfg,
            group: { name: 'lab-signals', put: true },
        });
    }

    // Keyboard shortcuts (scoped to modal lifetime)
    document.addEventListener('keydown', function _labKeyHandler(e) {
        if (!document.getElementById('thread-lab-modal')) {
            document.removeEventListener('keydown', _labKeyHandler);
            return;
        }
        const inInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
        const isLabSearch = e.target.id === 'lab-global-search';

        // Ctrl+A — grab all heatmap matches (works even when focused in the search bar)
        if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
            const matches = document.querySelectorAll('.lab-sig-card.lab-heatmap-match');
            if (matches.length > 0) {
                e.preventDefault();
                _labSelectAllMatches();
                return;
            }
            // If no heatmap matches, don't block default Ctrl+A in inputs
            if (inInput) return;
        }

        // Ctrl+Backspace — clear heatmap search + selection
        if ((e.ctrlKey || e.metaKey) && e.key === 'Backspace') {
            e.preventDefault();
            const searchInput = document.getElementById('lab-global-search');
            if (searchInput) { searchInput.value = ''; _labSearch(''); }
            _labClearSelection();
            return;
        }

        // Escape — close detail panel, or clear selection, or close modal
        if (e.key === 'Escape' && !inInput) {
            const detail = document.getElementById('lab-sig-detail');
            if (detail?.classList.contains('lab-detail-open')) { _labHideDetail(); return; }
            if (_labSelected.size > 0) { _labClearSelection(); return; }
            document.getElementById('thread-lab-modal')?.remove();
            return;
        }

        // Block other shortcuts when in inputs (except lab search)
        if (inInput && !isLabSearch) return;
    });

    // Prevent SortableJS from intercepting shift+click
    const kanban = document.querySelector('.thread-lab-kanban');
    if (kanban) {
        kanban.addEventListener('mousedown', (e) => {
            if (e.shiftKey && e.target.closest('.lab-sig-card')) {
                e.stopPropagation();
            }
        }, true);

        kanban.addEventListener('click', (e) => {
            const badge = e.target.closest('.lab-suggestion-badge');
            if (badge) {
                const gi    = parseInt(badge.dataset.suggestGi);
                const tid   = parseInt(badge.dataset.suggestTid);
                const title = badge.dataset.suggestTitle || '';
                _labAcceptSuggestion(gi, tid, title);
                return;
            }
            const card = e.target.closest('.lab-sig-card');
            if (!card) { _labHideDetail(); return; }

            if (e.shiftKey) {
                const sid = parseInt(card.dataset.signalId);
                if (_labSelected.has(sid)) {
                    _labSelected.delete(sid);
                    card.classList.remove('lab-sig-selected');
                } else {
                    _labSelected.add(sid);
                    card.classList.add('lab-sig-selected');
                }
                _labUpdateSelectionBar();
                return;
            }
            _labShowSignalDetail(card);
        });
    }
}

// ─── Drag handlers ───────────────────────────────────────────────────────────

function _labOnDragStart(evt) {
    const draggedId = parseInt(evt.item?.dataset?.signalId);
    if (!draggedId || !_labSelected.has(draggedId) || _labSelected.size < 2) return;
    _labSelected.forEach(sid => {
        if (sid === draggedId) return;
        const card = document.querySelector(`.lab-sig-card[data-signal-id="${sid}"]`);
        if (card) card.classList.add('lab-sig-lifting');
    });
    requestAnimationFrame(() => {
        const ghost = document.querySelector('.lab-sig-ghost');
        if (ghost && !ghost.querySelector('.lab-drag-badge')) {
            const badge = document.createElement('span');
            badge.className = 'lab-drag-badge';
            badge.textContent = _labSelected.size;
            ghost.appendChild(badge);
        }
    });
}

function _labOnDragEnd(evt) {
    document.querySelectorAll('.lab-sig-lifting').forEach(c => c.classList.remove('lab-sig-lifting'));
    const draggedId = parseInt(evt.item?.dataset?.signalId);
    const targetCol = evt.item?.parentElement;

    // Dropped into "+" new column zone — create a real column
    if (targetCol?.id === 'lab-col-new') {
        _labCreateColFromDrop(evt);
        return;
    }

    if (draggedId && _labSelected.has(draggedId) && _labSelected.size > 1 && targetCol) {
        const movedCards = [evt.item];
        _labSelected.forEach(sid => {
            if (sid === draggedId) return;
            const card = document.querySelector(`.lab-sig-card[data-signal-id="${sid}"]`);
            if (card) {
                targetCol.appendChild(card);
                movedCards.push(card);
            }
        });
        movedCards.forEach(c => {
            c.classList.remove('lab-sig-selected', 'lab-sig-lifting');
            c.classList.add('lab-sig-landed');
            c.addEventListener('animationend', () => c.classList.remove('lab-sig-landed'), { once: true });
        });
        _labSelected.clear();
        _labUpdateSelectionBar();
    }
    const badge = evt.item?.querySelector('.lab-drag-badge');
    if (badge) badge.remove();
    _labSyncAndRefreshCounts();
    if (_labKeywordGroups.length) _labUpdateAllCardDots();
}

function _labCreateColFromDrop(evt) {
    const state = window._threadLabState;
    if (!state) return;
    const newColEl = document.getElementById('lab-col-new');
    if (!newColEl) return;

    // Move any other selected cards into the new zone too
    const draggedId = parseInt(evt.item?.dataset?.signalId);
    if (draggedId && _labSelected.has(draggedId) && _labSelected.size > 1) {
        _labSelected.forEach(sid => {
            if (sid === draggedId) return;
            const card = document.querySelector(`.lab-sig-card[data-signal-id="${sid}"]`);
            if (card && card.parentElement !== newColEl) newColEl.appendChild(card);
        });
        _labSelected.clear();
    }

    // Read all cards now in the new zone
    const signals = Array.from(newColEl.querySelectorAll('[data-signal-id]')).map(el => ({
        id: parseInt(el.dataset.signalId),
        title: el.dataset.signalTitle || '',
        published_at: el.dataset.signalDate || '',
        source_name: el.dataset.signalSource || '',
        body: el.dataset.signalBody || '',
        from_pool: el.dataset.fromPool === 'true',
        original_thread_id: el.dataset.originalThreadId ? parseInt(el.dataset.originalThreadId) : null,
    }));
    if (signals.length === 0) return;

    // Sync existing columns first (so moved-out cards are removed from their groups)
    _labSyncAndRefreshCounts();

    // Create new group
    const newIdx = state.groups.length > 0
        ? Math.max(...state.groups.map(g => g.cluster_idx)) + 1
        : 100;
    state.groups.push({
        cluster_idx: newIdx,
        label: 'New thread',
        key_terms: [],
        cohesion: null,
        suggested_thread: null,
        _accepted_thread_id: null,
        _accepted_thread_title: null,
        active: true,
        signals,
    });

    // Re-render and focus the new column's name input
    _labRenderKanban();
    _labUpdateSelectionBar();
    requestAnimationFrame(() => {
        const gi = state.groups.length - 1;
        const nameInput = document.querySelector(`[data-lab-col-gi="${gi}"] .lab-col-name`);
        if (nameInput) { nameInput.focus(); nameInput.select(); }
    });
}

// ─── Signal detail panel ─────────────────────────────────────────────────────

function _labShowSignalDetail(card) {
    const panel = document.getElementById('lab-sig-detail');
    if (!panel) return;
    // Single-select: clear previous selection, select only this card
    document.querySelectorAll('.lab-sig-card.lab-sig-selected').forEach(c => {
        if (c !== card) { c.classList.remove('lab-sig-selected'); }
    });
    _labSelected.clear();
    const sid = parseInt(card.dataset.signalId);
    _labSelected.add(sid);
    card.classList.add('lab-sig-selected');
    _labUpdateSelectionBar();
    const title  = card.dataset.signalTitle  || '';
    const date   = card.dataset.signalDate   || '';
    const source = card.dataset.signalSource || '';
    const body   = card.dataset.signalBody   || '';
    const sigId  = card.dataset.signalId     || '';
    const meta   = [source, date].filter(Boolean).join(' · ');
    const fetchBtn = `<button class="lab-detail-fetch" onclick="_labFetchArticle(${sigId}, this)">📄 Fetch article text</button>`;
    panel.innerHTML = `
        <button class="lab-detail-close" onclick="_labHideDetail()">×</button>
        <div class="lab-detail-title">${escHtml(title)}</div>
        ${meta ? `<div class="lab-detail-meta">${escHtml(meta)}</div>` : ''}
        ${body ? `<div class="lab-detail-body" id="lab-detail-body-text">${escHtml(body)}</div>` : '<div class="lab-detail-body" id="lab-detail-body-text" style="color:var(--text-muted);font-style:italic">No body text</div>'}
        ${fetchBtn}`;
    panel.classList.add('lab-detail-open');
    document.querySelector('.thread-lab-inner')?.classList.add('lab-detail-expanded');
}

function _labFetchArticle(sigId, btn) {
    if (btn) { btn.textContent = '⏳ Fetching…'; btn.disabled = true; }
    fetch(`/api/signals/${sigId}/scrape`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                if (btn) { btn.textContent = '❌ ' + data.error; btn.style.color = '#ef4444'; }
                return;
            }
            const newBody = data.body || data.text || '';
            // Update the detail panel body
            const bodyEl = document.getElementById('lab-detail-body-text');
            if (bodyEl) {
                bodyEl.textContent = newBody;
                bodyEl.style.color = '';
                bodyEl.style.fontStyle = '';
            }
            // Update the card's data attribute so it persists across interactions
            const card = document.querySelector(`.lab-sig-card[data-signal-id="${sigId}"]`);
            if (card) card.dataset.signalBody = newBody.slice(0, 300);
            if (btn) { btn.textContent = '✓ Fetched'; btn.style.color = 'var(--green)'; }
        })
        .catch(() => {
            if (btn) { btn.textContent = '❌ Failed'; btn.style.color = '#ef4444'; }
        });
}

function _labHideDetail() {
    const panel = document.getElementById('lab-sig-detail');
    if (panel) panel.classList.remove('lab-detail-open');
    document.querySelector('.thread-lab-inner')?.classList.remove('lab-detail-expanded');
    // If only one card is "selected" (from single-click-to-view), deselect it on close
    if (_labSelected.size === 1) {
        _labClearSelection();
    }
}

// ─── Heatmap search + selection ──────────────────────────────────────────────

function _labSearch(query) {
    const q = (query || '').toLowerCase().trim();
    const cards = document.querySelectorAll('.lab-sig-card');
    if (!q) {
        cards.forEach(c => c.classList.remove('lab-heatmap-match', 'lab-heatmap-dim'));
        const btn = document.getElementById('lab-select-all-btn');
        if (btn) btn.style.display = 'none';
        return;
    }
    const words = q.split(/\s+/).filter(Boolean);
    let matchCount = 0;
    cards.forEach(c => {
        const text = ((c.dataset.signalTitle || '') + ' ' + (c.dataset.signalSource || '') + ' ' + (c.dataset.signalBody || '')).toLowerCase();
        const allMatch = words.every(w => text.includes(w));
        c.classList.toggle('lab-heatmap-match', allMatch);
        c.classList.toggle('lab-heatmap-dim',  !allMatch);
        if (allMatch) matchCount++;
    });
    const btn = document.getElementById('lab-select-all-btn');
    if (btn) {
        btn.textContent = `Grab all (${matchCount})`;
        btn.style.display = matchCount > 0 ? 'inline-block' : 'none';
    }
}

// ─── Keyword groups ───────────────────────────────────────────────────────────

function _labAddKeywordGroup(label) {
    const key = label.toLowerCase().trim();
    // Toggle off if already exists
    const existing = _labKeywordGroups.findIndex(g => g.key === key);
    if (existing !== -1) {
        _labRemoveKeywordGroup(existing);
        return;
    }
    const color = _LAB_KG_COLORS[_labKeywordGroups.length % _LAB_KG_COLORS.length];
    const words = key.split(/\s+/).filter(Boolean);

    // Collect matching signal IDs
    const signalIds = new Set();
    document.querySelectorAll('.lab-sig-card').forEach(c => {
        const text = ((c.dataset.signalTitle || '') + ' ' + (c.dataset.signalSource || '') + ' ' + (c.dataset.signalBody || '')).toLowerCase();
        if (words.every(w => text.includes(w))) signalIds.add(parseInt(c.dataset.signalId));
    });

    _labKeywordGroups.push({ label, key, color, signalIds });

    // Clear search bar + heatmap
    const inp = document.getElementById('lab-global-search');
    if (inp) { inp.value = ''; _labSearch(''); }

    _labRenderKgTray();
    _labUpdateAllCardDots();
}

function _labRemoveKeywordGroup(idx) {
    _labKeywordGroups.splice(idx, 1);
    _labRenderKgTray();
    _labUpdateAllCardDots();
}

function _labGrabKeywordGroup(idx) {
    const grp = _labKeywordGroups[idx];
    if (!grp) return;
    grp.signalIds.forEach(sid => {
        _labSelected.add(sid);
        const card = document.querySelector(`.lab-sig-card[data-signal-id="${sid}"]`);
        if (card) card.classList.add('lab-sig-selected');
    });
    _labUpdateSelectionBar();
}

function _labRenderKgTray() {
    const tray = document.getElementById('lab-kg-tray');
    if (!tray) return;
    if (!_labKeywordGroups.length) {
        tray.style.display = 'none';
        tray.innerHTML = '';
        return;
    }
    tray.style.display = 'flex';
    tray.innerHTML = _labKeywordGroups.map((g, i) =>
        `<span class="lab-kg-pill" style="--kg-color:${g.color}">
            <span class="lab-kg-swatch" style="background:${g.color}"></span>
            ${escHtml(g.label)}
            <span class="lab-kg-count">${g.signalIds.size}</span>
            <button class="lab-kg-grab" onclick="_labGrabKeywordGroup(${i})" title="Select all matching signals">↗ Grab</button>
            <button class="lab-kg-x" onclick="_labRemoveKeywordGroup(${i})" title="Remove group">×</button>
        </span>`
    ).join('') +
    `<button class="lab-kg-clear-all" onclick="_labKeywordGroups=[];_labRenderKgTray();_labUpdateAllCardDots()">Clear all</button>`;
}

function _labUpdateAllCardDots() {
    document.querySelectorAll('.lab-sig-card').forEach(card => {
        const sid = parseInt(card.dataset.signalId);
        const dots = card.querySelector('.lab-kg-dots');
        if (!dots) return;
        if (!_labKeywordGroups.length) { dots.innerHTML = ''; return; }
        dots.innerHTML = _labKeywordGroups
            .filter(g => g.signalIds.has(sid))
            .map(g => `<span class="lab-kg-dot" style="background:${g.color}" title="${escHtml(g.label)}"></span>`)
            .join('');
    });
}

function _labSelectAllMatches() {
    document.querySelectorAll('.lab-sig-card.lab-heatmap-match').forEach(c => {
        const sid = parseInt(c.dataset.signalId);
        _labSelected.add(sid);
        c.classList.add('lab-sig-selected');
    });
    _labUpdateSelectionBar();
}

function _labClearSelection() {
    _labSelected.forEach(sid => {
        const card = document.querySelector(`.lab-sig-card[data-signal-id="${sid}"]`);
        if (card) card.classList.remove('lab-sig-selected');
    });
    _labSelected.clear();
    _labUpdateSelectionBar();
}

function _labUpdateSelectionBar() {
    let bar = document.getElementById('lab-selection-bar');
    if (_labSelected.size === 0) {
        if (bar) bar.remove();
        return;
    }
    const health = document.querySelector('.thread-lab-health');
    if (!health) return;
    if (!bar) {
        bar = document.createElement('span');
        bar.id = 'lab-selection-bar';
        bar.className = 'lab-selection-inline';
        health.appendChild(bar);
    }
    const state = window._threadLabState;
    if (!state) return;
    const colBtns = state.groups.map((g, gi) =>
        `<button class="lab-moveto-btn" onclick="_labMoveSelectedTo(${gi})">${escHtml(g.label.slice(0, 18))}</button>`
    ).join('');
    const dismissBtn = state.mode === 'organize'
        ? `<button class="lab-moveto-btn" onclick="_labDismissSelected()" style="color:#ef4444">Dismiss</button>` : '';
    bar.innerHTML = `
        <span class="lab-sel-count">${_labSelected.size} selected</span>
        <span style="font-size:9px;color:var(--text-muted)">→</span>
        ${colBtns}
        <span class="lab-thread-search-wrap">
            <input id="lab-thread-search" class="lab-thread-search" type="text"
                placeholder="Find thread…" autocomplete="off"
                oninput="_labThreadSearchFilter(this.value)"
                onkeydown="_labThreadSearchKey(event)"
                onfocus="_labThreadSearchFilter(this.value)" />
            <div id="lab-thread-dropdown" class="lab-thread-dropdown"></div>
        </span>
        ${dismissBtn}
        <button class="lab-moveto-btn lab-moveto-clear" onclick="_labClearSelection()">✕</button>`;
}

// ─── Thread search in selection bar ──────────────────────────────────────────

let _labThreadSearchIdx = 0;

function _labThreadSearchFilter(query) {
    const dd = document.getElementById('lab-thread-dropdown');
    if (!dd) return;
    const q = (query || '').toLowerCase().trim();
    const threads = typeof _getSortedThreads === 'function' ? _getSortedThreads() : (_threadsCache || []);
    const filtered = q
        ? threads.filter(t => (t.title || '').toLowerCase().includes(q)).slice(0, 15)
        : threads.slice(0, 15);
    _labThreadSearchIdx = 0;

    if (filtered.length === 0 && !q) { dd.innerHTML = ''; dd.style.display = 'none'; return; }

    // "+ New thread" option at top when there's a query
    const newOpt = q ? `<div class="lab-tsd-item lab-tsd-new" data-action="new" data-title="${escHtml(q)}">
        <span style="color:var(--accent)">+ New thread:</span> ${escHtml(q)}
    </div>` : '';

    const items = filtered.map((t, i) => `
        <div class="lab-tsd-item${i === 0 && !q ? ' lab-tsd-active' : ''}" data-thread-id="${t.id}" data-thread-title="${escHtml(t.title)}">
            <span class="lab-tsd-title">${escHtml(t.title)}</span>
            <span class="lab-tsd-count">${t.signal_count || ''}</span>
        </div>`).join('');

    dd.innerHTML = newOpt + items;
    dd.style.display = 'block';

    // Click delegation
    dd.onclick = (e) => {
        const item = e.target.closest('.lab-tsd-item');
        if (!item) return;
        if (item.dataset.action === 'new') {
            _labCreateThreadFromSelected(item.dataset.title);
        } else {
            const tid = parseInt(item.dataset.threadId);
            const title = item.dataset.threadTitle;
            _labAssignSelectedToThread(tid, title);
        }
    };

    _labThreadSearchHighlight();
}

function _labThreadSearchKey(e) {
    const dd = document.getElementById('lab-thread-dropdown');
    if (!dd || dd.style.display === 'none') return;
    const items = dd.querySelectorAll('.lab-tsd-item');
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        _labThreadSearchIdx = Math.min(_labThreadSearchIdx + 1, items.length - 1);
        _labThreadSearchHighlight();
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        _labThreadSearchIdx = Math.max(_labThreadSearchIdx - 1, 0);
        _labThreadSearchHighlight();
    } else if (e.key === 'Enter') {
        e.preventDefault();
        const active = items[_labThreadSearchIdx];
        if (active) active.click();
    } else if (e.key === 'Escape') {
        dd.style.display = 'none';
    }
}

function _labThreadSearchHighlight() {
    const dd = document.getElementById('lab-thread-dropdown');
    if (!dd) return;
    dd.querySelectorAll('.lab-tsd-item').forEach((el, i) => {
        el.classList.toggle('lab-tsd-active', i === _labThreadSearchIdx);
        if (i === _labThreadSearchIdx) el.scrollIntoView({ block: 'nearest' });
    });
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.lab-thread-search-wrap')) {
        const dd = document.getElementById('lab-thread-dropdown');
        if (dd) dd.style.display = 'none';
    }
});

function _labAssignSelectedToThread(threadId, threadTitle) {
    if (_labSelected.size < 1) return;
    const sigIds = Array.from(_labSelected);
    const dd = document.getElementById('lab-thread-dropdown');
    if (dd) dd.style.display = 'none';

    fetch('/api/signals/review-queue/bulk-assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_ids: sigIds, thread_id: threadId }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok) {
            _showToast(`Assigned ${sigIds.length} → ${threadTitle}`, 'success');
            sigIds.forEach(sid => {
                document.querySelector(`.lab-sig-card[data-signal-id="${sid}"]`)?.remove();
            });
            _labSelected.clear();
            _labSyncAndRefreshCounts();
            _labUpdateSelectionBar();
            _labShowReclusterBtn();
        } else {
            _showToast(data.error || 'Assign failed', 'error');
        }
    });
}

function _labShowNewThreadInput() {
    const bar = document.getElementById('lab-selection-bar');
    if (!bar) return;
    // Replace bar contents with an inline input
    bar.innerHTML = `
        <span class="lab-sel-count">${_labSelected.size} selected → new thread:</span>
        <input id="lab-new-thread-input" class="lab-new-thread-input" type="text"
            placeholder="Thread name…" autofocus
            onkeydown="if(event.key==='Enter')_labCreateThreadFromSelected(this.value);if(event.key==='Escape')_labUpdateSelectionBar()" />
        <button class="lab-moveto-btn" onclick="_labCreateThreadFromSelected(document.getElementById('lab-new-thread-input')?.value)">Create</button>
        <button class="lab-moveto-btn lab-moveto-clear" onclick="_labUpdateSelectionBar()">✕</button>`;
    document.getElementById('lab-new-thread-input')?.focus();
}

function _labCreateThreadFromSelected(title) {
    title = (title || '').trim();
    if (!title) { _showToast('Enter a thread name', 'error'); return; }
    if (_labSelected.size < 1) { _showToast('No signals selected', 'error'); return; }

    const sigIds = Array.from(_labSelected);
    const bar = document.getElementById('lab-selection-bar');
    if (bar) bar.innerHTML = '<span class="lab-sel-count">Creating…</span>';

    fetch('/api/signals/patterns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, signal_ids: sigIds }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok || data.thread_id || data.id) {
            _showToast(`Created: ${title} (${sigIds.length} signals)`, 'success');
            // Remove cards from DOM
            sigIds.forEach(sid => {
                document.querySelector(`.lab-sig-card[data-signal-id="${sid}"]`)?.remove();
            });
            _labSelected.clear();
            _labSyncAndRefreshCounts();
            _labUpdateSelectionBar();
            _labShowReclusterBtn();
        } else {
            _showToast(data.error || 'Failed to create thread', 'error');
            _labUpdateSelectionBar();
        }
    });
}

function _labMoveSelectedTo(gi) {
    const state = window._threadLabState;
    if (!state) return;
    const targetCol = document.getElementById(`lab-col-${state.groups[gi].cluster_idx}`);
    if (!targetCol) return;
    _labSelected.forEach(sid => {
        const card = document.querySelector(`.lab-sig-card[data-signal-id="${sid}"]`);
        if (card) {
            targetCol.appendChild(card);
            card.classList.remove('lab-sig-selected');
        }
    });
    _labSelected.clear();
    _labSyncAndRefreshCounts();
    _labUpdateSelectionBar();
}

// ─── Column actions ──────────────────────────────────────────────────────────

function _labToggleCol(gi) {
    const state = window._threadLabState;
    if (!state) return;
    state.groups[gi].active = !state.groups[gi].active;
    const col = document.querySelector(`[data-lab-col-gi="${gi}"]`);
    if (col) col.classList.toggle('lab-kanban-col-inactive', !state.groups[gi].active);
    _labSyncAndRefreshCounts();
}

function _labAcceptSuggestion(gi, threadId, title) {
    const state = window._threadLabState;
    if (!state) return;
    const g = state.groups[gi];
    const toggling_off = g._accepted_thread_id === threadId;
    if (toggling_off) {
        g._accepted_thread_id = null;
        g._accepted_thread_title = null;
        g.label = state.originalData.sub_groups.find(sg => sg.cluster_idx === g.cluster_idx)?.label || g.label;
    } else {
        g._accepted_thread_id = threadId;
        g._accepted_thread_title = title;
        g.label = title;
    }
    const badge = document.querySelector(`[data-suggest-gi="${gi}"]`);
    if (badge) badge.classList.toggle('lab-suggestion-accepted', !toggling_off);
    const nameInput = document.querySelector(`[data-lab-col-gi="${gi}"] .lab-col-name`);
    if (nameInput) {
        nameInput.value = g.label;
        if (!toggling_off) nameInput.setAttribute('readonly', 'true');
        else nameInput.removeAttribute('readonly');
    }
}

// ─── Approve (mode-dispatched) ───────────────────────────────────────────────

function _labApproveCol(gi) {
    const state = window._threadLabState;
    if (!state) return;
    if (state.mode === 'organize') return _labApproveColOrganize(gi);
    return _labApproveColSplit(gi);
}

function _labApproveColSplit(gi) {
    const state = window._threadLabState;
    _labSyncAndRefreshCounts();
    const g = state.groups[gi];
    if (!g) return;

    const selectedInCol = g.signals.filter(s => _labSelected.has(s.id));
    const isPartial = selectedInCol.length > 0 && selectedInCol.length < g.signals.length;
    const signalsToApprove = isPartial ? selectedInCol : g.signals;
    if (signalsToApprove.length < 2) { _showToast('Need at least 2 signals to approve', 'error'); return; }

    const split = {
        title: g._accepted_thread_title || g.label,
        target_thread_id: g._accepted_thread_id || null,
        signal_ids: signalsToApprove.filter(s => !s.from_pool).map(s => s.id),
        external_signals: signalsToApprove
            .filter(s => s.from_pool && s.original_thread_id)
            .map(s => ({ signal_id: s.id, from_thread_id: s.original_thread_id })),
    };

    const col = document.querySelector(`[data-lab-col-gi="${gi}"]`);
    if (col) col.classList.add('lab-kanban-col-approving');

    fetch(`/api/signals/threads/${state.threadId}/execute-split`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ splits: [split] }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok) {
            const action = data.created?.[0]?.merged ? 'Merged' : 'Split off';
            _showToast(`${action}: ${split.title} (${signalsToApprove.length})`, 'success');
            if (isPartial) {
                const colBody = document.getElementById(`lab-col-${g.cluster_idx}`);
                signalsToApprove.forEach(s => {
                    colBody?.querySelector(`[data-signal-id="${s.id}"]`)?.remove();
                    _labSelected.delete(s.id);
                });
                _labSyncAndRefreshCounts();
                _labUpdateSelectionBar();
                if (col) col.classList.remove('lab-kanban-col-approving');
            } else {
                state.groups.splice(gi, 1);
                _labClearSelection();
                if (state.groups.length === 0) {
                    document.getElementById('thread-lab-modal')?.remove();
                    loadSignals();
                    if (_signalTab === 'graph') loadBoard();
                } else {
                    _labRenderKanban();
                }
            }
        } else {
            _showToast(data.error || 'Approve failed', 'error');
            if (col) col.classList.remove('lab-kanban-col-approving');
        }
    });
}

function _labApproveColOrganize(gi) {
    const state = window._threadLabState;
    _labSyncAndRefreshCounts();
    const g = state.groups[gi];
    if (!g) return;

    const selectedInCol = g.signals.filter(s => _labSelected.has(s.id));
    const isPartial = selectedInCol.length > 0 && selectedInCol.length < g.signals.length;
    const signalsToApprove = isPartial ? selectedInCol : g.signals;
    if (signalsToApprove.length < 1) { _showToast('No signals to assign', 'error'); return; }

    const sigIds = signalsToApprove.map(s => s.id);
    const threadId = g._accepted_thread_id;
    const threadTitle = g._accepted_thread_title || g.label;

    const col = document.querySelector(`[data-lab-col-gi="${gi}"]`);
    if (col) col.classList.add('lab-kanban-col-approving');

    if (threadId) {
        // Merge into existing thread via bulk-assign
        fetch('/api/signals/review-queue/bulk-assign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signal_ids: sigIds, thread_id: threadId }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                _showToast(`Assigned ${sigIds.length} → ${threadTitle}`, 'success');
                _labPostApproveOrganize(gi, sigIds, isPartial, col, g);
            } else {
                _showToast(data.error || 'Assign failed', 'error');
                if (col) col.classList.remove('lab-kanban-col-approving');
            }
        });
    } else {
        // Create new thread via patterns endpoint
        fetch('/api/signals/patterns', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: threadTitle, signal_ids: sigIds }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.ok || data.thread_id || data.id) {
                _showToast(`Created: ${threadTitle} (${sigIds.length})`, 'success');
                _labPostApproveOrganize(gi, sigIds, isPartial, col, g);
            } else {
                _showToast(data.error || 'Create failed', 'error');
                if (col) col.classList.remove('lab-kanban-col-approving');
            }
        });
    }
}

function _labPostApproveOrganize(gi, sigIds, isPartial, col, g) {
    const state = window._threadLabState;
    if (isPartial) {
        const colBody = document.getElementById(`lab-col-${g.cluster_idx}`);
        sigIds.forEach(sid => {
            colBody?.querySelector(`[data-signal-id="${sid}"]`)?.remove();
            _labSelected.delete(sid);
        });
        _labSyncAndRefreshCounts();
        _labUpdateSelectionBar();
        if (col) col.classList.remove('lab-kanban-col-approving');
    } else {
        state.groups.splice(gi, 1);
        _labClearSelection();
        _labShowReclusterBtn();
        if (state.groups.length === 0) {
            document.getElementById('thread-lab-modal')?.remove();
            _showToast('All signals organized', 'success');
            loadSignals();
            if (_signalTab === 'graph') loadBoard();
        } else {
            _labRenderKanban();
        }
    }
}

// ─── Dismiss (organize mode only) ────────────────────────────────────────────

function _labDismissSignal(signalId, btnEl) {
    const card = btnEl?.closest('.lab-sig-card');
    if (card) card.classList.add('lab-kanban-col-approving');
    fetch('/api/signals/review-queue/dismiss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_id: signalId }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok) {
            if (card) card.remove();
            _labSelected.delete(signalId);
            _labSyncAndRefreshCounts();
            _labUpdateSelectionBar();
        } else {
            if (card) card.classList.remove('lab-kanban-col-approving');
        }
    });
}

function _labDismissCol(gi) {
    const state = window._threadLabState;
    if (!state) return;
    _labSyncAndRefreshCounts();
    const g = state.groups[gi];
    if (!g || g.signals.length === 0) return;

    const col = document.querySelector(`[data-lab-col-gi="${gi}"]`);
    if (col) col.classList.add('lab-kanban-col-approving');

    const sigIds = g.signals.map(s => s.id);
    Promise.all(sigIds.map(sid =>
        fetch('/api/signals/review-queue/dismiss', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signal_id: sid }),
        })
    )).then(() => {
        _showToast(`Dismissed ${sigIds.length} signals`, 'success');
        sigIds.forEach(sid => _labSelected.delete(sid));
        state.groups.splice(gi, 1);
        _labClearSelection();
        _labShowReclusterBtn();
        if (state.groups.length === 0) {
            document.getElementById('thread-lab-modal')?.remove();
            loadSignals();
        } else {
            _labRenderKanban();
        }
    });
}

function _labDismissSelected() {
    if (_labSelected.size === 0) return;
    const ids = Array.from(_labSelected);
    Promise.all(ids.map(sid =>
        fetch('/api/signals/review-queue/dismiss', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signal_id: sid }),
        })
    )).then(() => {
        _showToast(`Dismissed ${ids.length} signals`, 'success');
        ids.forEach(sid => {
            document.querySelector(`.lab-sig-card[data-signal-id="${sid}"]`)?.remove();
        });
        _labSelected.clear();
        _labSyncAndRefreshCounts();
        _labUpdateSelectionBar();
    });
}

// ─── Re-cluster ──────────────────────────────────────────────────────────────

function _labShowReclusterBtn() {
    const btn = document.getElementById('lab-recluster-btn');
    if (btn) btn.style.display = 'inline-block';
}

function _labRecluster() {
    _openOrganizeLab();  // re-open, which re-fetches unassigned signals
}

// ─── Sync & refresh ──────────────────────────────────────────────────────────

function _labSyncAndRefreshCounts() {
    const state = window._threadLabState;
    if (!state) return;

    state.groups.forEach(g => {
        const col = document.getElementById(`lab-col-${g.cluster_idx}`);
        if (!col) return;
        g.signals = Array.from(col.querySelectorAll('[data-signal-id]')).map(el => ({
            id: parseInt(el.dataset.signalId),
            title: el.dataset.signalTitle || '',
            published_at: el.dataset.signalDate || '',
            source_name: el.dataset.signalSource || '',
            body: el.dataset.signalBody || '',
            from_pool: el.dataset.fromPool === 'true',
            original_thread_id: el.dataset.originalThreadId ? parseInt(el.dataset.originalThreadId) : null,
        }));
        const cnt = document.getElementById(`lab-cnt-${g.cluster_idx}`);
        if (cnt) cnt.textContent = g.signals.length;

        // Live per-column cohesion (client-side if sim_matrix available, else use server value)
        const cohEl = document.getElementById(`lab-coh-${g.cluster_idx}`);
        if (cohEl) {
            const coh = _labColCohesion(g.signals.map(s => s.id)) ?? g.cohesion;
            if (coh !== null && coh !== undefined) {
                const color = coh < 0.15 ? '#ef4444' : coh < 0.30 ? '#f59e0b' : '#22c55e';
                cohEl.textContent = coh.toFixed(2);
                cohEl.style.color = color;
            } else {
                cohEl.textContent = '';
            }
        }
    });

    // Auto-remove empty user-created columns (cluster_idx >= 100 = created via "+ New" drop)
    const origIdxs = new Set((state.originalData?.sub_groups || []).map(g => g.cluster_idx));
    let removed = false;
    for (let i = state.groups.length - 1; i >= 0; i--) {
        const g = state.groups[i];
        if (g.signals.length === 0 && !origIdxs.has(g.cluster_idx)) {
            const col = document.querySelector(`[data-lab-col-gi="${i}"]`);
            if (col) col.remove();
            state.groups.splice(i, 1);
            removed = true;
        }
    }
    if (removed) { _labRenderKanban(); return; }  // re-render to fix indices

    const isOrganize = state.mode === 'organize';
    const activeCount = state.groups.filter(g => g.active && g.signals.length >= (isOrganize ? 1 : 2)).length;
    const btn = document.getElementById('lab-split-btn');
    if (btn) {
        btn.textContent = isOrganize
            ? `📥 Assign all ${activeCount} group${activeCount !== 1 ? 's' : ''}`
            : `✂️ Split off ${activeCount} thread${activeCount !== 1 ? 's' : ''}`;
    }
}

// ─── Execute all (mode-dispatched) ───────────────────────────────────────────

function _labExecuteAction() {
    const state = window._threadLabState;
    if (!state) return;
    if (state.mode === 'organize') return _labExecuteOrganize();
    return _labExecuteSplit();
}

function _labExecuteSplit() {
    const state = window._threadLabState;
    _labSyncAndRefreshCounts();

    const splits = state.groups
        .filter(g => g.active && g.signals.length >= 2)
        .map(g => ({
            title: g._accepted_thread_title || g.label,
            target_thread_id: g._accepted_thread_id || null,
            signal_ids: g.signals.filter(s => !s.from_pool).map(s => s.id),
            external_signals: g.signals
                .filter(s => s.from_pool && s.original_thread_id)
                .map(s => ({ signal_id: s.id, from_thread_id: s.original_thread_id })),
        }));

    if (splits.length < 1) { _showToast('Activate at least 1 group with 2+ signals to split', 'error'); return; }

    const footer = document.querySelector('.thread-lab-footer');
    if (footer) footer.innerHTML = '<div style="font-size:12px;color:var(--text-muted);padding:8px 0">Splitting…</div>';

    fetch(`/api/signals/threads/${state.threadId}/execute-split`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ splits }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok) {
            document.getElementById('thread-lab-modal')?.remove();
            const mergedCount = data.created?.filter(c => c.merged)?.length || 0;
            const createdCount = (data.created?.length || splits.length) - mergedCount;
            const parts = [];
            if (createdCount > 0) parts.push(`${createdCount} new thread${createdCount !== 1 ? 's' : ''} created`);
            if (mergedCount  > 0) parts.push(`${mergedCount} merged into existing`);
            _showToast(parts.join(', ') || 'Done', 'success');
            loadSignals();
            if (_signalTab === 'graph') loadBoard();
        } else {
            _showToast(data.error || 'Split failed', 'error');
        }
    });
}

function _labExecuteOrganize() {
    const state = window._threadLabState;
    _labSyncAndRefreshCounts();

    const activeGroups = state.groups.filter(g => g.active && g.signals.length >= 1);
    if (activeGroups.length < 1) { _showToast('No groups to assign', 'error'); return; }

    const footer = document.querySelector('.thread-lab-footer');
    if (footer) footer.innerHTML = '<div style="font-size:12px;color:var(--text-muted);padding:8px 0">Assigning…</div>';

    // Process each group sequentially
    let idx = 0;
    function processNext() {
        if (idx >= activeGroups.length) {
            document.getElementById('thread-lab-modal')?.remove();
            _showToast(`Assigned ${activeGroups.length} groups`, 'success');
            loadSignals();
            if (_signalTab === 'graph') loadBoard();
            return;
        }
        const g = activeGroups[idx++];
        const sigIds = g.signals.map(s => s.id);
        const threadId = g._accepted_thread_id;
        const title = g._accepted_thread_title || g.label;

        const endpoint = threadId
            ? '/api/signals/review-queue/bulk-assign'
            : '/api/signals/patterns';
        const payload = threadId
            ? { signal_ids: sigIds, thread_id: threadId }
            : { title, signal_ids: sigIds };

        fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
        .then(r => r.json())
        .then(() => processNext())
        .catch(() => processNext());  // continue even if one fails
    }
    processNext();
}
