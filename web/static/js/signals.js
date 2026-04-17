// ===================== SIGNALS MODULE =====================

var _DOMAIN_LABELS = {  // var: accessed from board.js (separate script scope)
    economics: 'Economics', finance: 'Finance', geopolitics: 'Geopolitics',
    tech_ai: 'Tech / AI', labor: 'Labor', regulatory: 'Regulatory'
};
var _DOMAIN_COLORS = {  // var: accessed from board.js (separate script scope)
    economics: '#3b82f6', finance: '#22c55e', geopolitics: '#ef4444',
    tech_ai: '#a855f7', labor: '#eab308', regulatory: '#f97316'
};
const _DOMAIN_ALIASES = {
    software_development: 'tech_ai', technology: 'tech_ai', artificial_intelligence: 'tech_ai',
    tech: 'tech_ai', ai: 'tech_ai', software: 'tech_ai', automation: 'tech_ai',
    hiring: 'labor', employment: 'labor', workforce: 'labor', jobs: 'labor',
    financial: 'finance', markets: 'finance', banking: 'finance',
    political: 'geopolitics', trade: 'geopolitics', policy: 'geopolitics',
    regulation: 'regulatory', compliance: 'regulatory', legal: 'regulatory',
    economic: 'economics', macro: 'economics',
};
/** Parse a raw domain string (possibly pipe-separated, possibly invalid) into array of valid domains. */
function _parseDomains(raw) {
    if (!raw) return ['economics'];
    const parts = raw.split('|').map(d => d.trim().toLowerCase());
    const valid = [];
    for (const p of parts) {
        if (_DOMAIN_COLORS[p]) { if (!valid.includes(p)) valid.push(p); }
        else if (_DOMAIN_ALIASES[p]) { const mapped = _DOMAIN_ALIASES[p]; if (!valid.includes(mapped)) valid.push(mapped); }
    }
    return valid.length ? valid : ['economics'];
}
/** Render one or more colored domain badges from a raw domain string. */
function _renderDomainBadges(raw, fontSize) {
    const sz = fontSize || '9px';
    return _parseDomains(raw).map(d => {
        const c = _DOMAIN_COLORS[d]; const l = _DOMAIN_LABELS[d] || d;
        return `<span class="sig-card-domain" style="background:${c}22;color:${c};padding:2px 6px;border-radius:4px;font-size:${sz};font-weight:700">${escHtml(l)}</span>`;
    }).join(' ');
}

// ── Detail pane resize + persistence ──
(function() {
    const saved = localStorage.getItem('sig_detail_width');
    if (saved) document.documentElement.style.setProperty('--sig-detail-width', saved + 'px');

    let resizing = false;
    const handle = document.getElementById('signals-detail-resize');
    const pane = document.getElementById('signals-detail');
    if (!handle || !pane) return;

    handle.addEventListener('mousedown', e => {
        e.preventDefault();
        resizing = true;
        handle.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });
    document.addEventListener('mousemove', e => {
        if (!resizing) return;
        const parentRight = pane.parentElement.getBoundingClientRect().right;
        const newWidth = Math.min(700, Math.max(280, parentRight - e.clientX));
        pane.style.width = newWidth + 'px';
    });
    document.addEventListener('mouseup', () => {
        if (!resizing) return;
        resizing = false;
        handle.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        const w = parseInt(pane.style.width);
        if (w) localStorage.setItem('sig_detail_width', w);
    });
})();

// Raw signals 3-pane resize
(function() {
    let resizingPane = null;
    function initRawResize() {
        const feedHandle = document.getElementById('sig-raw-detail-resize');
        const rqHandle = document.getElementById('sig-rq-resize');
        const feedPane = document.getElementById('sig-raw-feed');
        const rqPane = document.getElementById('sig-review-queue');
        const savedRq = localStorage.getItem('sig_rq_width');
        if (savedRq && rqPane) rqPane.style.width = savedRq + 'px';
        if (feedHandle) feedHandle.addEventListener('mousedown', e => {
            e.preventDefault(); resizingPane = 'feed';
            feedHandle.classList.add('active');
            document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
        });
        if (rqHandle) rqHandle.addEventListener('mousedown', e => {
            e.preventDefault(); resizingPane = 'rq';
            rqHandle.classList.add('active');
            document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
        });
        document.addEventListener('mousemove', e => {
            if (!resizingPane) return;
            if (resizingPane === 'feed' && feedPane) {
                const parentLeft = feedPane.parentElement.getBoundingClientRect().left;
                const newW = Math.min(500, Math.max(250, e.clientX - parentLeft));
                feedPane.style.width = newW + 'px';
            } else if (resizingPane === 'rq' && rqPane) {
                const parentRight = rqPane.parentElement.getBoundingClientRect().right;
                const newW = Math.min(480, Math.max(240, parentRight - e.clientX));
                rqPane.style.width = newW + 'px';
            }
        });
        document.addEventListener('mouseup', () => {
            if (!resizingPane) return;
            const handle = resizingPane === 'feed' ? feedHandle : rqHandle;
            if (handle) handle.classList.remove('active');
            if (resizingPane === 'feed' && feedPane) localStorage.setItem('sig_raw_feed_width', parseInt(feedPane.style.width));
            if (resizingPane === 'rq' && rqPane) localStorage.setItem('sig_rq_width', parseInt(rqPane.style.width));
            resizingPane = null;
            document.body.style.cursor = ''; document.body.style.userSelect = '';
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initRawResize);
    else initRawResize();
})();

// Discovery drawer resize
(function() {
    let resizing = false;
    function initDiscoveryResize() {
        const handle = document.getElementById('discovery-drawer-resize');
        const pane = document.getElementById('discovery-drawer');
        if (!handle || !pane) return;
        const saved = localStorage.getItem('discovery_drawer_width');
        if (saved) pane.style.width = saved + 'px';
        handle.addEventListener('mousedown', e => {
            e.preventDefault(); resizing = true;
            handle.classList.add('active');
            document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
        });
        document.addEventListener('mousemove', e => {
            if (!resizing) return;
            const parentRight = pane.parentElement.getBoundingClientRect().right;
            const newW = Math.min(500, Math.max(260, parentRight - e.clientX));
            pane.style.width = newW + 'px';
        });
        document.addEventListener('mouseup', () => {
            if (!resizing) return;
            resizing = false; handle.classList.remove('active');
            document.body.style.cursor = ''; document.body.style.userSelect = '';
            const w = parseInt(pane.style.width);
            if (w) localStorage.setItem('discovery_drawer_width', w);
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initDiscoveryResize);
    else initDiscoveryResize();
})();

// ── Collapsible Sidebar (module + signals/research sidebar) ──
function _toggleSidebarCollapse() {
    const app = document.querySelector('.app');
    if (!app) return;
    const collapsed = app.classList.toggle('sidebar-collapsed');
    localStorage.setItem('sidebar_collapsed', collapsed ? '1' : '0');
}
(function() {
    if (localStorage.getItem('sidebar_collapsed') === '1') {
        const app = document.querySelector('.app');
        if (app) app.classList.add('sidebar-collapsed');
    }
})();

var _signalsCache = [];  // var: read/written from base.html (detail pane, search) outside this module
var _threadsCache = [];  // var: accessed from board.js (separate script scope)
let _signalsDomainFilter = 'all'; // kept for backward compat — derived from _activeDomains
let _signalsSourceTypeFilter = 'all';

// ── Feed filters ────────────────────────────────────────────────────────────
let _sigAssignmentFilter = 'all';   // 'all' | 'assigned' | 'unassigned'
let _threadMomentumFilter = 'all';  // 'all' | 'accelerating' | 'fading' | 'dormant'
let _threadSizeMin = 0;             // minimum signal count

// Unified domain toggle — all domains active by default
var _ALL_DOMAINS = ['economics', 'finance', 'geopolitics', 'tech_ai', 'labor', 'regulatory'];  // var: accessed from board.js (separate script scope)
var _activeDomains = new Set(_ALL_DOMAINS);  // var: accessed from board.js (separate script scope)

function _toggleDomain(domain) {
    if (_activeDomains.has(domain)) {
        if (_activeDomains.size === 1) return; // can't deactivate last one
        _activeDomains.delete(domain);
    } else {
        _activeDomains.add(domain);
    }
    // Sync legacy filter
    _signalsDomainFilter = _activeDomains.size === _ALL_DOMAINS.length ? 'all' : [..._activeDomains][0];
    _renderDomainChips();
    _applyGlobalDomainFilter();
}

function _setAllDomains() {
    _ALL_DOMAINS.forEach(d => _activeDomains.add(d));
    _signalsDomainFilter = 'all';
    _renderDomainChips();
    _applyGlobalDomainFilter();
}

function _applyGlobalDomainFilter() {
    renderActiveSignalTab();
    if (_signalTab === 'graph') loadBoard();
    if (_signalTab === 'narratives') loadNarratives();
    if (_signalTab === 'causal') { _renderCausalThreadPicker(); _renderCausalEditor(); }
}

function _renderDomainChips() {
    const container = document.getElementById('sig-domain-chips');
    if (!container) return;
    const allActive = _activeDomains.size === _ALL_DOMAINS.length;
    let html = `<span onclick="_setAllDomains()" style="padding:3px 8px;border-radius:6px;font-size:9px;font-weight:600;cursor:pointer;transition:all 0.15s;${allActive ? 'background:var(--bg-tertiary);color:var(--text-primary)' : 'background:transparent;color:var(--text-muted)'}">All</span>`;
    _ALL_DOMAINS.forEach(dom => {
        const color = _DOMAIN_COLORS[dom] || '#6b7280';
        const label = _DOMAIN_LABELS[dom] || dom;
        const count = _domainCounts[dom] || 0;
        const active = _activeDomains.has(dom);
        html += `<span onclick="_toggleDomain('${dom}')" style="padding:3px 8px;border-radius:6px;font-size:9px;font-weight:600;cursor:pointer;transition:all 0.15s;${active ? `background:${color}22;color:${color};border:1px solid ${color}44` : `background:transparent;color:var(--text-muted);border:1px solid var(--border);opacity:0.4`}">${count} ${label}</span>`;
    });
    container.innerHTML = html;
}

let _domainCounts = {};

function _filterSourceType(srcType) {
    _signalsSourceTypeFilter = srcType;
    renderActiveSignalTab();
}

function _renderFeedFilters(tab) {
    var row = document.getElementById('feed-filters-row');
    if (!row) return;
    // Use a stable sub-element for pills so we don't clobber organize/review buttons
    var container = document.getElementById('feed-filter-pills');
    if (!container) {
        container = document.createElement('div');
        container.id = 'feed-filter-pills';
        container.style.cssText = 'display:flex;align-items:center;gap:6px';
        row.insertBefore(container, row.firstChild);
    }

    if (tab === 'raw') {
        container.innerHTML =
            '<div class="feed-filter-group">' +
                _feedFilterPill('all', 'All', _sigAssignmentFilter, '_setSigAssignment') +
                _feedFilterPill('assigned', 'Assigned', _sigAssignmentFilter, '_setSigAssignment') +
                _feedFilterPill('unassigned', 'Unassigned', _sigAssignmentFilter, '_setSigAssignment') +
            '</div>';
    } else if (tab === 'threads') {
        container.innerHTML =
            '<div class="feed-filter-group">' +
                _feedFilterPill('all', 'All', _threadMomentumFilter, '_setThreadMomentum') +
                _feedFilterPill('accelerating', '↑ Accel', _threadMomentumFilter, '_setThreadMomentum') +
                _feedFilterPill('fading', '↓ Fading', _threadMomentumFilter, '_setThreadMomentum') +
                _feedFilterPill('dormant', '💤 Dormant', _threadMomentumFilter, '_setThreadMomentum') +
            '</div>' +
            '<select onchange="_setThreadSizeMin(+this.value)" class="feed-filter-select">' +
                '<option value="0"' + (_threadSizeMin === 0 ? ' selected' : '') + '>Any size</option>' +
                '<option value="2"' + (_threadSizeMin === 2 ? ' selected' : '') + '>2+ signals</option>' +
                '<option value="5"' + (_threadSizeMin === 5 ? ' selected' : '') + '>5+ signals</option>' +
                '<option value="10"' + (_threadSizeMin === 10 ? ' selected' : '') + '>10+ signals</option>' +
            '</select>';
    } else {
        container.innerHTML = '';
    }
}

function _feedFilterPill(value, label, activeValue, fnName) {
    var active = value === activeValue;
    return '<button class="feed-filter-pill' + (active ? ' active' : '') + '" onclick="' + fnName + '(\'' + value + '\')">' + label + '</button>';
}

function _setSigAssignment(value) {
    _sigAssignmentFilter = value;
    _renderFeedFilters('raw');
    renderSignalFeed();
}

function _setThreadMomentum(value) {
    _threadMomentumFilter = value;
    _renderFeedFilters('threads');
    renderThreadFeed();
}

function _setThreadSizeMin(value) {
    _threadSizeMin = value;
    _renderFeedFilters('threads');
    renderThreadFeed();
}
var _activeSignalId = null;  // var: accessed from board.js (separate script scope)
var _activeThreadId = null;  // var: accessed from board.js (separate script scope)
var _signalTab = 'raw';  // var: accessed from board.js (separate script scope)
var _detailRequestId = 0; // monotonic counter to cancel stale fetches  // var: accessed from board.js (separate script scope)
var _discoveryDrawerOpen = false;  // var: read from base.html outside this module
var _discoveryBreadcrumb = [];  // var: accessed from board.js (separate script scope)
var _discoveryResults = [];  // var: read/written from base.html outside this module
var _rawSelectedSignals = new Set(); // selected signal IDs in Raw tab for pattern creation

const _TAB_TITLES = { raw: 'Signals', threads: 'Threads', narratives: 'Narratives', graph: 'Board', causal: 'Chains', execution: 'Execution' };
const _TAB_HAS_ADD = { raw: true, threads: true, narratives: true, causal: true };

function switchSignalTab(tab) {
    _signalTab = tab;
    document.querySelectorAll('.sig-feed-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.sig-feed-tab[data-tab="${tab}"]`).classList.add('active');
    document.querySelectorAll('.sig-tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`sig-tab-${tab}`).classList.add('active');
    if (tab === 'graph') loadBoard();
    if (tab === 'narratives') loadNarratives();
    if (tab === 'causal') loadCausalView();
    // Update sidebar title + add button
    const titleEl = document.querySelector('.signals-sidebar-title');
    if (titleEl) titleEl.textContent = _TAB_TITLES[tab] || 'Signals';
    const addBtn = document.getElementById('quick-capture-toggle');
    if (addBtn) addBtn.style.display = _TAB_HAS_ADD[tab] ? '' : 'none';
    // Close any open add panel when switching tabs
    _closeAllAddPanels();
    // Show/hide filter bar
    const filterBar = document.getElementById('signals-filter-bar');
    if (filterBar) {
        filterBar.style.display = (tab === 'threads' || tab === 'raw' || tab === 'narratives') ? '' : 'none';
        const searchInput = document.getElementById('signals-search');
        if (searchInput) searchInput.placeholder = `Filter ${(_TAB_TITLES[tab] || 'signals').toLowerCase()}…`;
    }
    _renderFeedFilters(tab);
    // Toggle shared detail pane — raw tab has its own inline detail, causal has inspector
    const sharedDetail = document.getElementById('signals-detail');
    if (tab === 'raw' || tab === 'graph' || tab === 'causal') {
        if (sharedDetail) sharedDetail.style.display = 'none';
    } else {
        if (sharedDetail) sharedDetail.style.display = '';
    }
    // Load review groups when switching to raw tab
    if (tab === 'raw') _loadReviewGroups();
    // Clear detail pane on tab switch (except graph)
    if (tab !== 'graph' && tab !== 'raw') closeSignalDetail();
    // Update selection bar for current tab
    _updateSelectionBar();
}

function renderActiveSignalTab() {
    if (_signalTab === 'threads') renderThreadFeed();
    else if (_signalTab === 'narratives') renderNarrativesList();
    else renderSignalFeed();
}

function filterSignalDomain(domain) {
    if (domain === 'all') {
        _setAllDomains();
    } else {
        // Solo-select: only this domain active
        _activeDomains.clear();
        _activeDomains.add(domain);
        _signalsDomainFilter = domain;
        _renderDomainChips();
        _applyGlobalDomainFilter();
    }
}

function loadSignals() {
    const params = new URLSearchParams({ days_back: 7, limit: 300 });
    // Load raw signals, threads, and brainstorms in parallel
    Promise.all([
        fetch('/api/signals?' + params).then(r => r.json()),
        fetch('/api/signals/threads').then(r => r.json()),
        fetch('/api/signals/brainstorms').then(r => r.json()),
    ]).then(([sigData, threadData, brainstormData]) => {
        _signalsCache = sigData.signals || [];
        _threadsCache = threadData.threads || [];
        _renderFeedFilters(_signalTab);
        renderSignalFeed();
        renderThreadFeed();
        _renderBrainstormList(brainstormData.brainstorms || []);
        _loadReviewQueueCount();
        if (_signalTab === 'raw') {
            _loadReviewGroups();
            // Hide shared detail pane — raw tab uses its own inline detail
            const sharedDetail = document.getElementById('signals-detail');
            if (sharedDetail) sharedDetail.style.display = 'none';
        }
    }).catch(e => console.error('[signals] load error:', e));
}

function _renderBrainstormList(brainstorms) {
    const container = document.getElementById('signals-brainstorm-list');
    const items = document.getElementById('brainstorm-list-items');
    if (!brainstorms.length) { container.style.display = 'none'; return; }
    container.style.display = 'block';
    items.innerHTML = brainstorms.slice(0, 8).map(b => {
        const titles = (b.thread_titles || []).join(' × ');
        const date = b.created_at ? _timeAgo(b.created_at) : '';
        return `<div onclick="openPastBrainstorm(${b.id})" style="padding:6px 0;border-bottom:1px solid var(--border);cursor:pointer;transition:color 0.15s" onmouseenter="this.style.color='var(--accent)'" onmouseleave="this.style.color=''">
            <div style="font-size:12px;font-weight:600;color:var(--text-primary);line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${escHtml(titles)}</div>
            <div style="font-size:10px;color:var(--text-muted);margin-top:2px">${escHtml(date)} · ${(b.hypotheses || []).length} hypotheses</div>
        </div>`;
    }).join('');
}

function loadSignalFreshness() {
    fetch('/api/signals/freshness')
        .then(r => r.json())
        .then(data => {
            const fresh = data.freshness || {};
            const counts = data.counts || {};
            for (const [dom, cnt] of Object.entries(counts)) {
                const el = document.getElementById(`sig-count-${dom}`);
                if (el) el.textContent = cnt;
            }
            const el = document.getElementById('signals-freshness');
            const times = Object.values(fresh);
            if (times.length) {
                const latest = times.sort().reverse()[0];
                el.textContent = 'Last scan: ' + _timeAgo(latest);
            }
        })
        .catch(() => {});

    // Also load scan history
    fetch('/api/signals/scan-history')
        .then(r => r.json())
        .then(data => {
            const scans = data.scans || [];
            const container = document.getElementById('signals-scan-history');
            const items = document.getElementById('scan-history-items');
            if (!scans.length) { container.style.display = 'none'; return; }
            container.style.display = 'block';
            items.innerHTML = scans.map(s => {
                const age = _timeAgo(s.created_at);
                return `<div style="padding:4px 0;border-bottom:1px solid var(--border);font-size:10px;cursor:pointer" onclick="switchSignalTab('execution')">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span style="color:var(--text-secondary);font-weight:600">${s.total_collected} signals · ${s.new_inserted} new</span>
                        <span style="color:var(--text-muted)">${escHtml(age)}</span>
                    </div>
                    <div style="color:var(--text-muted);margin-top:2px">${s.threads_created} threads · ${s.threads_assigned} assigned</div>
                </div>`;
            }).join('');
        })
        .catch(() => {});
}

function _timeAgo(isoStr) {
    if (!isoStr) return 'never';
    const d = new Date(isoStr + (isoStr.includes('Z') || isoStr.includes('+') ? '' : 'Z'));
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

function _updateDomainCounts() {
    _domainCounts = {};
    _signalsCache.forEach(s => { _domainCounts[s.domain] = (_domainCounts[s.domain] || 0) + 1; });
    const total = _signalsCache.length || 1;
    // Render proportional domain bar
    const bar = document.getElementById('sig-domain-bar');
    if (bar) {
        bar.innerHTML = _ALL_DOMAINS.map(dom => {
            const count = _domainCounts[dom] || 0;
            const pct = (count / total * 100).toFixed(1);
            const color = _DOMAIN_COLORS[dom];
            const opacity = _activeDomains.has(dom) ? 1 : 0.2;
            return count > 0 ? `<div onclick="_toggleDomain('${dom}')" style="width:${pct}%;background:${color};opacity:${opacity};transition:all 0.3s" title="${_DOMAIN_LABELS[dom]}: ${count}"></div>` : '';
        }).join('');
    }
    _renderDomainChips();
}

function renderSignalFeed() {
    const container = document.getElementById('sig-raw-feed') || document.getElementById('sig-tab-raw');
    const search = (document.getElementById('signals-search').value || '').toLowerCase();

    let filtered = _signalsCache;
    if (_activeDomains.size < _ALL_DOMAINS.length) {
        filtered = filtered.filter(s => _parseDomains(s.domain).some(d => _activeDomains.has(d)));
    }
    if (_signalsSourceTypeFilter !== 'all') {
        filtered = filtered.filter(s => (s.source_type || 'news') === _signalsSourceTypeFilter);
    }
    if (_sigAssignmentFilter === 'assigned') {
        filtered = filtered.filter(s => !!s.thread_info);
    } else if (_sigAssignmentFilter === 'unassigned') {
        filtered = filtered.filter(s => !s.thread_info);
    }
    if (search) {
        filtered = filtered.filter(s =>
            (s.title || '').toLowerCase().includes(search) ||
            (s.body || '').toLowerCase().includes(search) ||
            (s.source_name || '').toLowerCase().includes(search)
        );
    }

    _updateDomainCounts();

    if (!filtered.length) {
        container.innerHTML = `<div class="signals-empty">
            <div style="font-size:32px;margin-bottom:12px">&#128225;</div>
            <div>No signals match this filter</div>
        </div>`;
        return;
    }

    const html = filtered.map(s => {
        const sPrimaryDom = _parseDomains(s.domain)[0];
        const dateStr = s.published_at ? s.published_at.substring(0, 10) : '';
        const checked = _rawSelectedSignals.has(s.id) ? ' checked' : '';
        const threads = typeof _parseThreadInfo === 'function' ? _parseThreadInfo(s) : [];
        const threadBadges = threads.length
            ? threads.map(t => `<span class="sig-thread-badge" onclick="event.stopPropagation();openThreadDetail(${t.id})" title="${escHtml(t.title)}">${escHtml(t.title)}</span>`).join('')
            : '';
        return `<div class="sig-card sig-domain-${escHtml(sPrimaryDom)} ${s.id === _activeSignalId ? 'active' : ''}"
                     data-id="${s.id}">
            <div style="display:flex;gap:8px;align-items:start">
                <div class="sig-card-select${checked}" data-sig-id="${s.id}" onclick="event.stopPropagation();_toggleRawSelect(${s.id})">✓</div>
                <div style="flex:1;min-width:0">
                    <div class="sig-card-header">
                        ${_renderDomainBadges(s.domain)}
                        <span class="sig-card-source">${escHtml(s.source_name || s.source)}</span>
                        <span class="sig-card-date">${escHtml(dateStr)}</span>
                    </div>
                    <div class="sig-card-title">${escHtml(s.title)}</div>
                    ${threadBadges ? `<div class="sig-thread-badges">${threadBadges}</div>` : ''}
                    ${s.body ? `<div class="sig-card-body">${escHtml(s.body.substring(0, 200))}</div>` : ''}
                </div>
            </div>
        </div>`;
    }).join('');

    container.innerHTML = html;
    _updateSelectionBar();
}

// Single event delegation on the feed body — handles both tabs
document.addEventListener('DOMContentLoaded', () => {
    const feedBody = document.getElementById('signals-feed-body');
    if (feedBody) {
        feedBody.addEventListener('click', function(e) {
            const sigCard = e.target.closest('.sig-card');
            if (sigCard) { openSignalDetail(parseInt(sigCard.dataset.id)); return; }
            const threadCard = e.target.closest('.thread-card');
            if (threadCard) { openThreadDetail(parseInt(threadCard.dataset.id)); return; }
        });
        feedBody.addEventListener('contextmenu', function(e) {
            const threadCard = e.target.closest('.thread-card');
            if (threadCard) {
                e.preventDefault();
                _showThreadContextMenu(parseInt(threadCard.dataset.id), e.clientX, e.clientY);
                return;
            }
            const sigCard = e.target.closest('.sig-card');
            if (sigCard) {
                e.preventDefault();
                _showSignalContextMenu(parseInt(sigCard.dataset.id), e.clientX, e.clientY);
            }
        });
    }
});

// ── Shared Context Menu Component ──

function _showContextMenu(items, x, y, header) {
    document.querySelectorAll('.sv-ctx-menu').forEach(m => m.remove());
    const menu = document.createElement('div');
    menu.className = 'sv-ctx-menu';
    menu.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:9999;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.5);min-width:200px;padding:4px 0;font-size:13px`;

    let html = '';
    if (header) html += `<div style="padding:6px 14px;font-size:11px;color:var(--text-muted);font-weight:600;border-bottom:1px solid var(--border);margin-bottom:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px">${escHtml(header)}</div>`;

    for (const item of items) {
        if (item === 'separator') {
            html += '<div style="border-top:1px solid var(--border);margin:3px 0"></div>';
            continue;
        }
        const color = item.color || 'var(--text-secondary)';
        if (item.submenu) {
            html += `<div class="sv-ctx-item sv-ctx-submenu" style="padding:7px 14px;cursor:pointer;color:${color};display:flex;align-items:center;justify-content:space-between;gap:8px;transition:background 0.1s" onmouseenter="this.style.background='var(--bg-tertiary)';_showCtxSubmenu(this,${JSON.stringify(item.submenu).replace(/"/g, '&quot;')})" onmouseleave="this.style.background=''">
                <span>${item.icon || ''} ${item.label}</span><span style="font-size:10px;color:var(--text-muted)">&#9656;</span>
            </div>`;
        } else {
            html += `<div class="sv-ctx-item" onclick="${item.action};document.querySelectorAll('.sv-ctx-menu').forEach(m=>m.remove())" style="padding:7px 14px;cursor:pointer;color:${color};display:flex;align-items:center;gap:8px;transition:background 0.1s" onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background=''">${item.icon || ''} ${item.label}</div>`;
        }
    }
    menu.innerHTML = html;
    document.body.appendChild(menu);

    // Clamp to viewport
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';

    setTimeout(() => {
        const close = (e) => { if (!e.target.closest('.sv-ctx-menu')) { document.querySelectorAll('.sv-ctx-menu').forEach(m => m.remove()); document.removeEventListener('click', close); } };
        document.addEventListener('click', close);
    }, 0);
}

function _showCtxSubmenu(parentEl, items) {
    document.querySelectorAll('.sv-ctx-submenu-popup').forEach(m => m.remove());
    const parentRect = parentEl.getBoundingClientRect();
    const sub = document.createElement('div');
    sub.className = 'sv-ctx-menu sv-ctx-submenu-popup';
    sub.style.cssText = `position:fixed;left:${parentRect.right + 2}px;top:${parentRect.top}px;z-index:10000;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.5);min-width:180px;padding:4px 0;font-size:13px`;
    sub.innerHTML = items.map(item =>
        `<div class="sv-ctx-item" onclick="${item.action};document.querySelectorAll('.sv-ctx-menu').forEach(m=>m.remove())" style="padding:7px 14px;cursor:pointer;color:${item.color || 'var(--text-secondary)'};display:flex;align-items:center;gap:8px;transition:background 0.1s" onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background=''">${item.icon || ''} ${item.label}</div>`
    ).join('');
    document.body.appendChild(sub);
    // Clamp
    const rect = sub.getBoundingClientRect();
    if (rect.right > window.innerWidth) sub.style.left = (parentRect.left - rect.width - 2) + 'px';
    if (rect.bottom > window.innerHeight) sub.style.top = (window.innerHeight - rect.height - 8) + 'px';
    // Close when mouse leaves both parent and submenu
    parentEl.addEventListener('mouseleave', (e) => {
        setTimeout(() => { if (!sub.matches(':hover')) sub.remove(); }, 200);
    }, { once: true });
}

// ── Thread Context Menu (Threads tab) ──

function _showThreadContextMenu(threadId, x, y) {
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    if (!thread) return;

    // Check if multiple threads selected
    const multiSelected = _selectedThreadsForNarrative.size > 1 && _selectedThreadsForNarrative.has(threadId);

    if (multiSelected) {
        const ids = [..._selectedThreadsForNarrative];
        const count = ids.length;
        _showContextMenu([
            { label: `Merge ${count} threads`, icon: '🔗', action: `_mergeThreads()` },
            { label: `AI rename ${count} threads`, icon: '🤖', action: `_bulkAIRename([${ids}])` },
            { label: 'Create chain from selection', icon: '⛓️', action: `_createChainFromThreads([${ids}])` },
            { label: 'Brainstorm connections', icon: '🧠', action: `openBrainstormMode()` },
            { label: 'Create narrative', icon: '📖', action: `_createNarrativeFromThreads()` },
            'separator',
            { label: `Delete ${count} threads`, icon: '🗑️', action: `_bulkDeleteThreads([${ids}])`, color: '#ef4444' },
        ], x, y, `${count} threads selected`);
    } else {
        const sigCount = thread.signal_count || 0;
        const items = [
            { label: 'Rename', icon: '✏️', action: `_renameThread(${threadId})` },
        ];
        if (sigCount >= 20) {
            items.push({ label: 'Thread Lab', icon: '🧪', action: `_openThreadLab(${threadId})` });
        } else if (sigCount >= 6) {
            items.push({ label: 'Split thread', icon: '✂️', action: `_splitThreadFromMenu(${threadId})` });
        }
        items.push(
            { label: 'Add to chain', icon: '⛓️', action: `_addThreadToChainFromMenu(${threadId})` },
            'separator',
            { label: 'Find related internally', icon: '🔍', action: `_findRelatedInternally(${threadId})` },
            { label: 'Search externally for more', icon: '📡', action: `_searchExternallyForThread(${threadId})` },
            { label: 'Highlight on board', icon: '🔮', action: `_highlightThreadOnBoard(${threadId})` },
            { label: 'Find similar', icon: '🔎', submenu: [
                { label: 'By shared entities', icon: '🏢', action: `_findSimilarByEntities(${threadId})` },
                { label: 'By domain', icon: '🎯', action: `_findSimilarByDomain(${threadId})` },
                { label: 'By signal count', icon: '📊', action: `_findSimilarBySize(${threadId})` },
            ]},
            'separator',
            { label: 'Delete', icon: '🗑️', action: `_deleteThread(${threadId})`, color: '#ef4444' },
        );
        _showContextMenu(items, x, y, thread.title.substring(0, 40));
    }
}

// ── Signal Context Menu (Signals tab) ──

function _showSignalContextMenu(signalId, x, y) {
    const signal = (_signalsCache || []).find(s => s.id == signalId);
    if (!signal) return;

    const multiSelected = _rawSelectedSignals.size > 1 && _rawSelectedSignals.has(signalId);

    if (multiSelected) {
        const ids = [..._rawSelectedSignals];
        const count = ids.length;
        _showContextMenu([
            { label: `Create thread from ${count}`, icon: '⛓️', action: `_createPatternFromSelection()` },
            { label: `Assign all ${count} to thread`, icon: '📌', action: `_bulkAssignSignalsPrompt([${ids}])` },
            'separator',
            { label: `Mark all ${count} as noise`, icon: '🔇', action: `_bulkDismissSignals([${ids}])` },
        ], x, y, `${count} signals selected`);
    } else {
        const items = [
            { label: 'Assign to thread', icon: '📌', action: `_assignSignalPrompt(${signalId})` },
            { label: 'Find similar signals', icon: '🔍', action: `_findSimilarSignals(${signalId})` },
            { label: 'Mark as noise', icon: '🔇', action: `_dismissSignalFromMenu(${signalId})` },
        ];
        if (signal.url) {
            items.push({ label: 'Open source', icon: '🔗', action: `window.open('${escHtml(signal.url)}','_blank')` });
        }
        _showContextMenu(items, x, y, signal.title.substring(0, 45));
    }
}

function _assignSignalPrompt(signalId) {
    _showAssignDropdown([signalId], false);
}

function _bulkAssignSignalsPrompt(signalIds) {
    _showAssignDropdown(signalIds, true);
}

function _showAssignDropdown(signalIds, isBulk) {
    // Remove any existing assign dropdown
    document.querySelectorAll('.sig-assign-dropdown').forEach(d => d.remove());
    const dd = document.createElement('div');
    dd.className = 'sig-assign-dropdown';
    dd.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999;background:var(--bg-secondary);border:1px solid var(--border);border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,0.6);width:360px;max-height:400px;overflow:hidden;display:flex;flex-direction:column';
    dd.innerHTML = `
        <div style="padding:12px 16px;border-bottom:1px solid var(--border);font-size:13px;font-weight:600;color:var(--text-primary);display:flex;justify-content:space-between;align-items:center">
            <span>Assign ${isBulk ? signalIds.length + ' signals' : 'signal'} to thread</span>
            <button onclick="this.closest('.sig-assign-dropdown').remove()" style="background:none;border:none;color:var(--text-muted);font-size:16px;cursor:pointer">&times;</button>
        </div>
        <input type="text" placeholder="Search or type new thread name..." id="sig-assign-search" style="margin:8px 12px;padding:8px 12px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);font-size:13px;outline:none;box-sizing:border-box" autofocus />
        <div id="sig-assign-list" style="flex:1;overflow-y:auto;max-height:280px"></div>
    `;
    document.body.appendChild(dd);
    const input = dd.querySelector('#sig-assign-search');
    const list = dd.querySelector('#sig-assign-list');
    const render = (q) => {
        q = (q || '').toLowerCase().trim();
        const threads = [...(_threadsCache || [])].sort((a, b) => (b.signal_count || 0) - (a.signal_count || 0));
        const filtered = q ? threads.filter(t => (t.title || '').toLowerCase().includes(q)) : threads.slice(0, 20);
        const exactMatch = q && threads.some(t => (t.title || '').toLowerCase() === q);
        const createBtn = q && !exactMatch
            ? `<div onclick="_doAssignSignals([${signalIds}],null,'${escHtml(q.replace(/'/g, "\\'"))}',${isBulk})" style="padding:10px 16px;font-size:13px;color:var(--accent);cursor:pointer;border-bottom:1px solid var(--border);font-weight:600;transition:background 0.1s" onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background=''">+ Create: "${escHtml(q)}"</div>`
            : '';
        list.innerHTML = createBtn + filtered.map(t =>
            `<div onclick="_doAssignSignals([${signalIds}],${t.id},null,${isBulk})" style="padding:10px 16px;font-size:13px;color:var(--text-secondary);cursor:pointer;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;transition:background 0.1s" onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background=''">
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(t.title)}</span>
                <span style="flex-shrink:0;font-size:11px;color:var(--text-muted);margin-left:8px">${t.signal_count || 0}</span>
            </div>`
        ).join('') || '<div style="padding:12px 16px;color:var(--text-muted);font-size:12px">No threads found</div>';
    };
    render('');
    input.addEventListener('input', () => render(input.value));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') dd.remove();
        if (e.key === 'Enter') {
            const v = input.value.trim();
            if (!v) return;
            const match = (_threadsCache || []).find(t => (t.title || '').toLowerCase() === v.toLowerCase());
            _doAssignSignals(signalIds, match ? match.id : null, match ? null : v, isBulk);
        }
    });
    // Close on click outside
    setTimeout(() => {
        const close = (e) => { if (!dd.contains(e.target)) { dd.remove(); document.removeEventListener('click', close); } };
        document.addEventListener('click', close);
    }, 100);
    setTimeout(() => input.focus(), 50);
}

function _doAssignSignals(signalIds, threadId, newTitle, isBulk) {
    document.querySelectorAll('.sig-assign-dropdown').forEach(d => d.remove());
    if (threadId) {
        const endpoint = signalIds.length > 1 ? '/api/signals/review-queue/bulk-assign' : '/api/signals/review-queue/assign';
        const body = signalIds.length > 1
            ? { signal_ids: signalIds, thread_id: threadId }
            : { signal_id: signalIds[0], thread_id: threadId };
        fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
            .then(() => {
                const t = (_threadsCache || []).find(th => th.id === threadId);
                _showToast(`${signalIds.length > 1 ? signalIds.length + ' signals' : 'Signal'} assigned to "${t ? t.title : 'thread'}"`, 'success');
                if (isBulk) _rawSelectedSignals.clear();
                loadSignals();
                if (_signalTab === 'raw') _loadReviewGroups();
            });
    } else if (newTitle) {
        fetch('/api/signals/patterns', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle, signal_ids: signalIds }) })
            .then(() => {
                _showToast(`Created thread "${newTitle}" with ${signalIds.length} signal${signalIds.length > 1 ? 's' : ''}`, 'success');
                if (isBulk) _rawSelectedSignals.clear();
                loadSignals();
                if (_signalTab === 'raw') _loadReviewGroups();
            });
    }
}

function _dismissSignalFromMenu(signalId) {
    fetch('/api/signals/review-queue/dismiss', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_id: signalId })
    }).then(() => { _showToast('Signal dismissed', 'success'); loadSignals(); });
}

function _bulkDismissSignals(signalIds) {
    Promise.all(signalIds.map(sid =>
        fetch('/api/signals/review-queue/dismiss', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signal_id: sid })
        })
    )).then(() => { _showToast(`${signalIds.length} signals dismissed`, 'success'); _rawSelectedSignals.clear(); loadSignals(); });
}

function _findSimilarSignals(signalId) {
    const signal = (_signalsCache || []).find(s => s.id == signalId);
    if (!signal) return;
    // Find similar signals by title keyword matching in the local cache
    const words = signal.title.toLowerCase().split(/\s+/).filter(w => w.length > 3);
    const similar = (_signalsCache || []).filter(s => {
        if (s.id === signalId) return false;
        const t = (s.title || '').toLowerCase();
        const matchedWords = words.filter(w => t.includes(w));
        return matchedWords.length >= 2;
    }).slice(0, 20);

    if (!similar.length) {
        _showToast('No similar signals found', 'info');
        return;
    }

    _showToast(`Found ${similar.length} similar signals`, 'info');

    // Visually highlight matching cards with a glow + scroll to first
    setTimeout(() => {
        similar.forEach(s => {
            const card = document.querySelector(`.sig-card[data-id="${s.id}"]`);
            if (card) {
                card.style.transition = 'box-shadow 0.3s, border-color 0.3s';
                card.style.boxShadow = '0 0 12px rgba(168,85,247,0.5)';
                card.style.borderColor = 'var(--purple)';
                setTimeout(() => { card.style.boxShadow = ''; card.style.borderColor = ''; }, 5000);
            }
        });
        const firstCard = document.querySelector(`.sig-card[data-id="${similar[0].id}"]`);
        if (firstCard) firstCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 50);
}

function _splitThreadFromMenu(threadId) {
    openThreadDetail(threadId);
    setTimeout(() => _proposeThreadSplit(threadId), 400);
}

function _addThreadToChainFromMenu(threadId) {
    if (_activeCausalPathId) {
        _addThreadToActiveChain(threadId);
        if (_signalTab !== 'causal') { switchSignalTab('causal'); }
    } else {
        // Start a new chain with this thread
        _startNewChain(threadId);
        if (_signalTab !== 'causal') { switchSignalTab('causal'); }
    }
}

function _createChainFromThreads(threadIds) {
    if (threadIds.length < 1) return;
    const firstThread = (_threadsCache || []).find(t => t.id === threadIds[0]);
    const name = firstThread ? firstThread.title.substring(0, 25) + '...' : 'New chain';
    fetch('/api/causal-paths', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, thread_ids: threadIds })
    }).then(r => r.json()).then(result => {
        if (result.ok) {
            // Create links between adjacent threads
            for (let i = 0; i < threadIds.length - 1; i++) {
                fetch('/api/causal-links', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cause_thread_id: threadIds[i], effect_thread_id: threadIds[i + 1] }) });
            }
            _activeCausalPathId = result.id;
            _showToast('Chain created', 'success');
            switchSignalTab('causal');
        }
    });
}

function _bulkAIRename(threadIds) {
    _showConfirm(`AI rename ${threadIds.length} threads? Each will get a new directional title based on its signals.`, () => {
        let completed = 0;
        threadIds.forEach(tid => {
            fetch(`/api/signals/threads/${tid}/ai-rename`, { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    completed++;
                    if (completed === threadIds.length) {
                        _showToast(`${completed} threads renamed`, 'success');
                        loadSignals();
                    }
                });
        });
    });
}

function _renameThread(threadId) {
    document.querySelectorAll('.sv-ctx-menu').forEach(m => m.remove());
    // Open thread detail then focus the editable title
    openThreadDetail(threadId);
    setTimeout(() => {
        const title = document.querySelector('.editable-title');
        if (title) _startTitleEdit(title);
    }, 300);
}

function _deleteThread(threadId) {
    document.querySelectorAll('.sv-ctx-menu').forEach(m => m.remove());
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    _showConfirm(`Delete "${thread ? thread.title.substring(0, 40) : 'thread'}"? Signals will become unassigned.`, () => {
        fetch(`/api/signals/threads/${threadId}`, { method: 'DELETE' })
            .then(r => r.json()).then(data => {
                if (data.ok) {
                    _showToast('Thread deleted', 'success');
                    loadSignals();
                    if (_signalTab === 'graph') loadBoard();
                }
            });
    });
}

function _bulkDeleteThreads(threadIds) {
    _showConfirm(`Delete ${threadIds.length} threads? Signals will become unassigned.`, () => {
        fetch('/api/signals/threads/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ thread_ids: threadIds })
        }).then(r => r.json()).then(data => {
            if (data.ok) {
                _showToast(`${data.deleted} threads deleted`, 'success');
                _selectedThreadsForNarrative.clear();
                loadSignals();
                if (_signalTab === 'graph') loadBoard();
            }
        });
    });
}

// ── Text selection right-click → context menu with search options ──
document.addEventListener('contextmenu', (e) => {
    const sel = window.getSelection();
    const text = (sel.toString() || '').trim();
    if (!text || text.length < 3 || text.length > 80) return;
    // Only trigger inside relevant areas
    const target = e.target.closest('#signals-detail, #brainstorm-overlay, .sig-tab-content, .signals-feed-body');
    if (!target) return;
    if (e.target.closest('input, textarea')) return;
    // Don't intercept if right-clicking a thread card (that has its own context menu)
    if (e.target.closest('.thread-card')) return;

    e.preventDefault();
    _showTextContextMenu(text, e.clientX, e.clientY);
});

function _showTextContextMenu(text, x, y) {
    document.querySelectorAll('.text-ctx-menu').forEach(m => m.remove());
    const safeText = text.replace(/'/g, "\\'").replace(/"/g, '\\"');
    const displayText = text.length > 25 ? text.substring(0, 23) + '...' : text;

    const menu = document.createElement('div');
    menu.className = 'text-ctx-menu';
    menu.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:9999;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,0.5);min-width:180px;padding:4px 0;font-size:11px`;

    menu.innerHTML = `
        <div style="padding:4px 12px;font-size:9px;color:var(--text-muted);font-weight:600;border-bottom:1px solid var(--border);margin-bottom:2px">"${escHtml(displayText)}"</div>
        <div onclick="_findThreadsInDetail('${safeText}')" style="padding:6px 12px;cursor:pointer;color:var(--text-secondary);transition:background 0.1s;display:flex;align-items:center;gap:6px" onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background=''">
            <span style="font-size:12px">&#128269;</span> Find related threads
        </div>
        <div onclick="_highlightOnBoard('${safeText}')" style="padding:6px 12px;cursor:pointer;color:var(--text-secondary);transition:background 0.1s;display:flex;align-items:center;gap:6px" onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background=''">
            <span style="font-size:12px">&#128302;</span> Highlight on board
        </div>
        <div onclick="_searchSignalsFor('${safeText}')" style="padding:6px 12px;cursor:pointer;color:var(--text-secondary);transition:background 0.1s;display:flex;align-items:center;gap:6px" onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background=''">
            <span style="font-size:12px">&#128225;</span> Search for new signals
        </div>
    `;

    document.body.appendChild(menu);

    // Clamp to viewport
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';

    setTimeout(() => {
        const close = (e) => { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('mousedown', close); } };
        document.addEventListener('mousedown', close);
    }, 0);
}

function _findThreadsInDetail(text) {
    document.querySelectorAll('.text-ctx-menu').forEach(m => m.remove());

    // Always use Discovery Drawer for related thread exploration
    _brainstormConceptClick(text);
    return;

    // Legacy: detail pane fallback (kept for reference)
    const detailBody = _showDetailPane('Search: ' + text);
    detailBody.innerHTML = '<div style="padding:20px;color:var(--text-muted);font-size:11px">Searching threads...</div>';

    fetch(`/api/signals/search?q=${encodeURIComponent(text)}`)
        .then(r => r.json())
        .then(data => {
            const matches = data.thread_matches || [];
            if (!matches.length) {
                const q = text.toLowerCase();
                const titleMatches = (_threadsCache || []).filter(t =>
                    t.title.toLowerCase().includes(q) || (t.synthesis || '').toLowerCase().includes(q)
                );
                if (titleMatches.length) {
                    _renderThreadSearchResults(detailBody, text, titleMatches.map(t => ({
                        thread_id: t.id, thread_title: t.title, match_count: t.signal_count, domain: t.domain
                    })));
                } else {
                    detailBody.innerHTML = `<div style="padding:20px;text-align:center">
                        <div style="font-size:24px;margin-bottom:8px">&#128269;</div>
                        <div style="color:var(--text-muted);font-size:11px">No threads found for "${escHtml(text)}"</div>
                        <button onclick="_searchSignalsFor('${text.replace(/'/g, "\\'")}')" style="margin-top:12px;padding:6px 14px;background:linear-gradient(135deg,var(--accent),var(--purple));border:none;border-radius:6px;color:#fff;font-size:10px;font-weight:600;cursor:pointer">&#128225; Search for new signals</button>
                    </div>`;
                }
                return;
            }
            _renderThreadSearchResults(detailBody, text, matches);
        });
}

function _renderThreadSearchResults(container, query, matches) {
    // Deduplicate by thread_id
    const seen = new Set();
    const unique = matches.filter(m => {
        if (seen.has(m.thread_id)) return false;
        seen.add(m.thread_id);
        return true;
    });

    container.innerHTML = `
        <div style="padding:16px">
            <div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:4px">Threads matching "${escHtml(query)}"</div>
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:12px">${unique.length} thread${unique.length !== 1 ? 's' : ''} found</div>
            ${unique.map(m => {
                const thread = (_threadsCache || []).find(t => t.id === m.thread_id);
                const domColor = thread ? _DOMAIN_COLORS[_parseDomains(thread.domain)[0]] || '#6b7280' : '#6b7280';
                const title = m.thread_title || (thread ? thread.title : `Thread #${m.thread_id}`);
                const sigCount = thread ? thread.signal_count : (m.match_count || 0);
                return `<div onclick="openThreadDetail(${m.thread_id})" style="padding:8px 10px;margin-bottom:4px;background:var(--bg-tertiary);border-radius:6px;border-left:3px solid ${domColor};cursor:pointer;transition:background 0.15s" onmouseenter="this.style.background='var(--bg-secondary)'" onmouseleave="this.style.background='var(--bg-tertiary)'">
                    <div style="font-size:11px;font-weight:600;color:var(--text-primary)">${escHtml(title)}</div>
                    <div style="font-size:9px;color:var(--text-muted);margin-top:2px">${sigCount} signals${m.match_count ? ` · ${m.match_count} matches` : ''}</div>
                </div>`;
            }).join('')}
            <div style="margin-top:12px;display:flex;gap:6px">
                <button onclick="_highlightOnBoard('${escHtml(query.replace(/'/g, "\\'"))}')" style="padding:5px 10px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:5px;color:var(--text-secondary);font-size:10px;cursor:pointer">&#128302; Highlight on board</button>
                <button onclick="_searchSignalsFor('${escHtml(query.replace(/'/g, "\\'"))}')" style="padding:5px 10px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:5px;color:var(--text-secondary);font-size:10px;cursor:pointer">&#128225; Search for more signals</button>
            </div>
        </div>`;
}

function _highlightOnBoard(text) {
    document.querySelectorAll('.text-ctx-menu').forEach(m => m.remove());
    fetch(`/api/signals/search?q=${encodeURIComponent(text)}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (!data || data.error) return;
            const key = _hlKey('keyword', text);
            if (_boardHighlights.findIndex(h => h.key === key) === -1) {
                const threadIds = new Set((data.thread_matches || []).map(m => m.thread_id));
                _boardHighlights.push({ kind: 'keyword', label: text, icon: '🔍', threadIds, key });
                _applyBoardHighlights();
                _renderHighlightPills();
            }
            const matchCount = (data.thread_matches || []).length;
            _showToast(`"${text}" highlighted — ${matchCount} thread${matchCount !== 1 ? 's' : ''}`, 'success', 3000);
        });
}

function _searchSignalsFor(text) {
    document.querySelectorAll('.text-ctx-menu').forEach(m => m.remove());
    // Use the custom search flow
    const input = document.getElementById('custom-search-input');
    if (input) input.value = text;
    _runCustomSearch();
}

function _findRelatedInternally(threadId) {
    document.querySelectorAll('.sv-ctx-menu').forEach(m => m.remove());
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    if (!thread) return;
    // Show results in the detail pane (existing function)
    _findThreadsInDetail(thread.title);
    // Flash-highlight matching thread cards in the feed
    const q = thread.title.toLowerCase().split(/\s+/).filter(w => w.length > 3);
    document.querySelectorAll('.thread-card').forEach(card => {
        if (parseInt(card.dataset.id) === threadId) return;
        const titleEl = card.querySelector('.thread-card-title');
        if (!titleEl) return;
        const title = titleEl.textContent.toLowerCase();
        if (q.some(w => title.includes(w))) {
            card.style.transition = 'box-shadow 0.3s';
            card.style.boxShadow = '0 0 12px rgba(168,85,247,0.5)';
            setTimeout(() => { card.style.boxShadow = ''; }, 3000);
        }
    });
}

function _searchExternallyForThread(threadId) {
    document.querySelectorAll('.sv-ctx-menu').forEach(m => m.remove());
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    if (!thread) return;
    const query = thread.title.substring(0, 60);
    _showToast(`Searching: "${query.substring(0, 35)}..."`, 'info', 6000);
    const entry = { query, status: 'running', startedAt: new Date().toISOString() };
    if (!_execData.customSearches) _execData.customSearches = [];
    _execData.customSearches.push(entry);
    _renderExecutionDetail();
    fetch('/api/signals/search', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
    }).then(r => r.json()).then(data => {
        entry.status = 'done';
        entry.total_found = data.total_found || 0;
        entry.new_inserted = data.new_inserted || 0;
        _renderExecutionDetail();
        _showToast(`Found ${data.total_found || 0} signals, ${data.new_inserted || 0} new`, 'success');
        loadSignals();
        if (_signalTab === 'graph') loadBoard();
    }).catch(() => {
        entry.status = 'error';
        _renderExecutionDetail();
        _showToast('External search failed', 'error');
    });
}

function _highlightThreadOnBoard(threadId) {
    document.querySelectorAll('.sv-ctx-menu').forEach(m => m.remove());
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    if (!thread) return;
    const key = _hlKey('thread', String(threadId));
    _addBoardHighlight({ kind: 'keyword', label: thread.title.substring(0, 25), icon: '🔮', threadIds: new Set([threadId]), key });
    if (_signalTab !== 'graph') switchSignalTab('graph');
}

function renderThreadFeed() {
    const container = document.getElementById('sig-tab-threads');
    const search = (document.getElementById('signals-search').value || '').toLowerCase();

    let filtered = _threadsCache;
    if (_activeDomains.size < _ALL_DOMAINS.length) {
        filtered = filtered.filter(t => _parseDomains(t.domain).some(d => _activeDomains.has(d)));
    }
    if (_threadMomentumFilter !== 'all') {
        filtered = filtered.filter(t => {
            var m = t.momentum || {};
            if (_threadMomentumFilter === 'dormant') return m.lifecycle === 'dormant';
            return m.direction === _threadMomentumFilter;
        });
    }
    if (_threadSizeMin > 0) {
        filtered = filtered.filter(t => (t.signal_count || 0) >= _threadSizeMin);
    }
    if (search) {
        filtered = filtered.filter(t =>
            (t.title || '').toLowerCase().includes(search) ||
            (t.synthesis || '').toLowerCase().includes(search)
        );
    }

    _updateDomainCounts();

    if (!filtered.length) {
        container.innerHTML = `<div class="signals-empty">
            <div style="font-size:32px;margin-bottom:12px">&#128202;</div>
            <div>${_signalsCache.length ? 'No threads yet — run a scan to detect them' : 'No threads yet'}</div>
            <div style="color:var(--text-muted);font-size:12px;margin-top:6px">Threads are detected automatically when you scan for signals.</div>
        </div>`;
        return;
    }

    const html = filtered.map(t => {
        const m = t.momentum || {};
        const mDir = m.direction || 'stable';
        const mLabel = {accelerating: '↑ Accelerating', stable: '→ Stable', fading: '↓ Decelerating'}[mDir] || '→ Stable';
        const lifecycle = m.lifecycle || 'active';
        const domains = _parseDomains(t.domain);
        const domColor = _DOMAIN_COLORS[domains[0]] || '#6b7280';
        const age = t.last_signal_at ? _timeAgo(t.last_signal_at) : _timeAgo(t.created_at);
        const dormantStyle = lifecycle === 'dormant' ? 'opacity:0.45;' : lifecycle === 'cooling' ? 'opacity:0.7;' : '';
        const lifecycleLabel = lifecycle === 'dormant' ? `<span style="font-size:9px;color:var(--text-muted);background:var(--bg-tertiary);padding:1px 5px;border-radius:3px">dormant · ${m.days_since_last || 0}d</span>` :
                               lifecycle === 'cooling' ? `<span style="font-size:9px;color:var(--text-muted);background:var(--bg-tertiary);padding:1px 5px;border-radius:3px">cooling</span>` : '';

        const checked = _selectedThreadsForNarrative.has(t.id) ? ' checked' : '';
        return `<div class="thread-card ${t.id === _activeThreadId ? 'active' : ''}" data-id="${t.id}" style="${dormantStyle}">
            <div style="display:flex;align-items:start;gap:8px">
                <div class="sig-card-select${checked}" onclick="event.stopPropagation();_toggleThreadForNarrative(${t.id})">✓</div>
                <div style="flex:1;min-width:0">
                    <div class="thread-card-title">${escHtml(t.title)}</div>
                    ${t.synthesis ? `<div class="thread-card-summary">${escHtml(t.synthesis)}</div>` : ''}
                    <div class="thread-card-meta">
                        ${_renderDomainBadges(t.domain)}
                        <span class="thread-card-stat">${t.signal_count || 0} signals</span>
                        <span class="thread-card-stat">${escHtml(age)}</span>
                        <span class="thread-momentum ${escHtml(mDir)}">${mLabel}</span>
                        ${lifecycleLabel}
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');
    container.innerHTML = html;
    _updateSelectionBar();
}

function openSignalDetail(signalId) {
    // Match by loose equality to handle string/int mismatch from dataset
    const s = _signalsCache.find(x => x.id == signalId);
    if (!s) { console.warn('[signals] Signal not found in cache:', signalId); return; }
    _activeSignalId = s.id;
    ++_detailRequestId; // cancel any pending thread detail fetches

    // Highlight active card and scroll to it
    document.querySelectorAll('.sig-card').forEach(c => c.classList.remove('active'));
    const card = document.querySelector(`.sig-card[data-id="${s.id}"]`);
    if (card) {
        card.classList.add('active');
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    // Use raw-specific detail pane when on raw tab, shared pane otherwise
    const detailBody = _signalTab === 'raw' ? _showRawDetailPane('Signal Detail') : _showDetailPane('Signal Detail');

    const sDoms = _parseDomains(s.domain);
    const domColor = _DOMAIN_COLORS[sDoms[0]] || '#6b7280';
    const dateStr = s.published_at ? s.published_at.substring(0, 10) : 'Unknown date';

    detailBody.innerHTML = `
        <div class="sig-detail-card">
            <div class="sig-detail-hero" style="border-left: 4px solid ${domColor}">
                <h2 class="sig-editable-title" onclick="_editSignalTitle(${s.id},this)" title="Click to edit" style="cursor:text">${escHtml(s.title)}</h2>
                <div class="sig-detail-meta">
                    ${_renderDomainBadges(s.domain, '10px')}
                    <span style="font-size:11px;color:var(--text-muted)">${escHtml(s.source_name || s.source)}</span>
                    <span style="font-size:11px;color:var(--text-muted)">${escHtml(dateStr)}</span>
                </div>
            </div>
            <div class="sig-detail-body-text" id="sig-detail-text-${s.id}">${s.body ? _formatBody(s.body) : '<span style="color:var(--text-muted);font-style:italic">No article text yet</span>'}</div>
            <div style="padding:12px 20px;border-top:1px solid var(--border);display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                ${s.url && (!s.body || s.body.length < 500) ? `<button id="sig-fetch-btn-${s.id}" onclick="fetchArticleText(${s.id})" style="padding:6px 14px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--accent);font-size:11px;font-weight:600;cursor:pointer">Load full article</button>` : ''}
                ${s.url ? `<a href="${escHtml(s.url)}" target="_blank" rel="noopener" style="color:var(--text-muted);font-size:11px;text-decoration:none">Open source &rarr;</a>` : ''}
            </div>
        </div>
    `;
}

function _editSignalTitle(signalId, h2El) {
    const current = h2El.textContent;
    const input = document.createElement('input');
    input.type = 'text';
    input.value = current;
    input.style.cssText = 'width:100%;font-size:inherit;font-weight:inherit;font-family:inherit;line-height:inherit;color:var(--text-primary);background:var(--bg-tertiary);border:1px solid var(--accent);border-radius:4px;padding:2px 6px;outline:none;box-sizing:border-box';
    h2El.replaceWith(input);
    input.focus();
    input.select();

    function save() {
        const newTitle = input.value.trim();
        const h2 = document.createElement('h2');
        h2.className = 'sig-editable-title';
        h2.style.cursor = 'text';
        h2.title = 'Click to edit';
        h2.onclick = () => _editSignalTitle(signalId, h2);
        h2.textContent = newTitle || current;
        input.replaceWith(h2);

        if (newTitle && newTitle !== current) {
            fetch(`/api/signals/${signalId}`, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({title: newTitle}),
            }).then(r => r.json()).then(d => {
                if (d.ok) {
                    // Update cache + card in list
                    const cached = _signalsCache.find(x => x.id == signalId);
                    if (cached) cached.title = newTitle;
                    const card = document.querySelector(`.sig-card[data-id="${signalId}"] .sig-card-title`);
                    if (card) card.textContent = newTitle;
                    _showToast('Title updated', 'success');
                }
            });
        }
    }

    input.addEventListener('blur', save);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { input.value = current; input.blur(); }
    });
}

function fetchArticleText(signalId, attempt) {
    attempt = attempt || 1;
    const maxAttempts = 3;
    const btn = document.getElementById('sig-fetch-btn-' + signalId);
    const textEl = document.getElementById('sig-detail-text-' + signalId);
    if (btn) { btn.textContent = attempt > 1 ? `Retry ${attempt}/${maxAttempts}...` : 'Fetching...'; btn.disabled = true; }

    fetch('/api/signals/' + signalId + '/fetch-article', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.ok && data.body) {
                textEl.innerHTML = _formatBody(data.body);
                const cached = _signalsCache.find(x => x.id == signalId);
                if (cached) cached.body = data.body;
                if (btn) btn.remove();
            } else if (attempt < maxAttempts) {
                if (btn) btn.textContent = `Retry ${attempt + 1}/${maxAttempts}...`;
                setTimeout(() => fetchArticleText(signalId, attempt + 1), 1500);
            } else {
                if (btn) { btn.textContent = 'Retry'; btn.style.color = 'var(--red)'; btn.disabled = false; btn.onclick = () => fetchArticleText(signalId, 1); }
            }
        })
        .catch(() => {
            if (attempt < maxAttempts) {
                setTimeout(() => fetchArticleText(signalId, attempt + 1), 1500);
            } else {
                if (btn) { btn.textContent = 'Retry'; btn.style.color = 'var(--red)'; btn.disabled = false; btn.onclick = () => fetchArticleText(signalId, 1); }
            }
        });
}

function _showDetailPane(title) {
    const detailPane = document.getElementById('signals-detail');
    const detailBody = document.getElementById('signals-detail-body');
    const detailEmpty = document.getElementById('signals-detail-empty');
    const closeBtn = document.querySelector('.signals-detail-close');
    const titleEl = document.querySelector('.signals-detail-title');
    if (detailPane) detailPane.style.display = '';
    if (detailEmpty) detailEmpty.style.display = 'none';
    if (closeBtn) closeBtn.style.display = 'block';
    if (titleEl && title) titleEl.textContent = title;
    return detailBody;
}

/**
 * Render an inline-editable title. Click to edit, Enter/blur to save.
 * @param {string} text - current title
 * @param {string} endpoint - API endpoint (PATCH) e.g. '/api/signals/threads/5'
 * @param {string} field - JSON field name, default 'title'
 * @param {string} onSaveAction - JS code to run after save (e.g. 'loadSignals()')
 * @param {string} fontSize - optional, default '14px'
 */
function _editableTitle(text, endpoint, field, onSaveAction, fontSize) {
    const fs = fontSize || '14px';
    return `<h2 class="editable-title" data-endpoint="${escHtml(endpoint)}" data-field="${field}" data-onsave="${escHtml(onSaveAction || 'loadSignals()')}"
        style="font-size:${fs};font-weight:700;margin:0;cursor:text;padding:2px 4px;margin:-2px -4px;border-radius:4px;border:1px solid transparent;transition:border-color 0.15s"
        onclick="_startTitleEdit(this)"
        onmouseenter="this.style.borderColor='var(--border)'" onmouseleave="if(!this.querySelector('input'))this.style.borderColor='transparent'"
        title="Click to rename">${escHtml(text)}</h2>`;
}

function _startTitleEdit(el) {
    if (el.querySelector('input')) return;
    const current = el.textContent;
    const endpoint = el.dataset.endpoint;
    const field = el.dataset.field || 'title';
    const onSaveAction = el.dataset.onsave || 'loadSignals()';
    const fontSize = getComputedStyle(el).fontSize;
    el.style.borderColor = 'var(--accent)';
    el.onmouseenter = null;
    el.onmouseleave = null;
    el.innerHTML = `<input type="text" value="${current.replace(/"/g, '&quot;')}" style="width:100%;font-size:${fontSize};font-weight:700;background:var(--bg-tertiary);border:none;color:var(--text-primary);outline:none;padding:0;margin:0;font-family:inherit" />`;
    const input = el.querySelector('input');
    input.focus();
    input.select();

    let saved = false;
    const save = () => {
        if (saved) return;
        saved = true;
        const newTitle = input.value.trim();
        if (!newTitle || newTitle === current) {
            el.textContent = current;
            el.style.borderColor = 'transparent';
            return;
        }
        el.textContent = newTitle;
        el.style.borderColor = 'transparent';
        fetch(endpoint, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: newTitle })
        }).then(r => r.json()).then(data => {
            if (data.ok) {
                _showToast('Renamed', 'success', 2000);
                try { eval(onSaveAction); } catch(e) {}
            } else {
                el.textContent = current;
            }
        });
    };

    input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
        if (e.key === 'Escape') { saved = true; el.textContent = current; el.style.borderColor = 'transparent'; }
    });
    input.addEventListener('blur', save);
}

function openThreadDetail(threadId) {
    _activeThreadId = threadId;
    const myRequest = ++_detailRequestId; // capture this request's ID

    // Ensure shared detail pane is visible (may be hidden on board/chains/execution tabs)
    const sharedDetail = document.getElementById('signals-detail');
    if (sharedDetail && _signalTab !== 'raw') sharedDetail.style.display = '';

    // Highlight active thread card + graph node
    document.querySelectorAll('.thread-card').forEach(c => c.classList.remove('active'));
    const card = document.querySelector(`.thread-card[data-id="${threadId}"]`);
    if (card) card.classList.add('active');

    const detailBody = _signalTab === 'raw' ? _showRawDetailPane('Thread Detail') : _showDetailPane('Thread Detail');
    detailBody.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-muted)">Loading thread...</div>`;

    fetch(`/api/signals/threads/${threadId}`)
        .then(r => r.json())
        .then(thread => {
            // Stale guard: if another request was made after this one, discard
            if (myRequest !== _detailRequestId) return;
            if (!thread || thread.error) {
                detailBody.innerHTML = `<div style="text-align:center;padding:40px;color:var(--red)">Thread not found</div>`;
                return;
            }
            const domains = _parseDomains(thread.domain);
            const domColor = _DOMAIN_COLORS[domains[0]] || '#6b7280';
            const m = thread.momentum || {};
            const mDir = m.direction || 'stable';
            const mLabel = {accelerating: '↑ Accelerating', stable: '→ Stable', fading: '↓ Decelerating'}[mDir];
            const signals = thread.signals || [];
            const entities = thread.entities || [];

            // Group entities by type, dedup
            const entsByType = {};
            entities.forEach(e => {
                const type = e.entity_type;
                if (!entsByType[type]) entsByType[type] = [];
                const val = e.normalized_value || e.entity_value;
                if (!entsByType[type].find(x => x.toLowerCase() === val.toLowerCase())) entsByType[type].push(val);
            });

            const _entIcon = {company:'🏢',sector:'📊',geography:'📍',country:'📍',city:'📍',person:'👤',regulation:'⚖️',concept:'💡','economic concept':'💡',event:'📅',index:'📈',exchange:'📈',university:'🎓'};
            const typeOrder = ['concept', 'economic concept', 'event', 'company', 'sector', 'geography', 'country', 'city', 'person', 'regulation', 'index', 'exchange'];
            const _entClickable = typeOrder; // ALL types are clickable
            const sortedEntTypes = Object.entries(entsByType).sort((a, b) => (typeOrder.indexOf(a[0]) === -1 ? 99 : typeOrder.indexOf(a[0])) - (typeOrder.indexOf(b[0]) === -1 ? 99 : typeOrder.indexOf(b[0])));
            const entHtml = sortedEntTypes.map(([type, vals]) => {
                const icon = _entIcon[type] || '🔹';
                const clickable = _entClickable.includes(type);
                return `<div style="margin-bottom:8px">
                    <span style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px">${escHtml(type)}</span><br>
                    ${vals.map(v => {
                        const cls = clickable ? 'ent-chip ent-chip-clickable' : 'ent-chip';
                        const onclick = clickable ? `onclick="_highlightEntityOnBoard('${escHtml(type)}', '${escHtml(v.replace(/'/g, "\\'"))}')"` : '';
                        return `<span class="${cls}" data-type="${escHtml(type)}" ${onclick}>${icon} ${escHtml(v)}</span>`;
                    }).join('')}
                </div>`;
            }).join('');

            const sigSignals = signals.filter(s => s.signal_status !== 'noise');
            const sigNoise = signals.filter(s => s.signal_status === 'noise');

            const _renderSignalItem = (s, isNoise) => {
                const dateStr = s.published_at ? s.published_at.substring(0, 10) : '';
                const opacity = isNoise ? 'opacity:0.4;' : '';
                const toggleLabel = isNoise ? 'Promote' : 'Noise';
                const toggleStatus = isNoise ? 'signal' : 'noise';
                return `<div id="sig-item-${s.id}" class="sig-draggable" draggable="true" data-sig-id="${s.id}" data-from-thread="${thread.id}" style="padding:8px 0;border-bottom:1px solid var(--border);${opacity}">
                    <div style="display:flex;align-items:start;gap:6px">
                        <div class="sig-card-select" data-drag-select="${s.id}" onclick="event.stopPropagation();_toggleDragSelect(${s.id})" style="margin-top:3px">✓</div>
                        <div style="flex:1;min-width:0;cursor:pointer" onclick="_toggleSignalArticle(${s.id}, this)">
                            <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:3px">${escHtml(s.title)}</div>
                            <div style="font-size:10px;color:var(--text-muted);display:flex;gap:8px;flex-wrap:wrap">
                                <span>${escHtml(s.source_name || s.source)}</span>
                                <span>${escHtml(dateStr)}</span>
                                ${s.url ? `<a href="${escHtml(s.url)}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none" onclick="event.stopPropagation()">source →</a>` : ''}
                            </div>
                        </div>
                        <button onclick="_setSignalStatus(${s.id}, '${toggleStatus}', ${thread.id})" style="flex-shrink:0;padding:2px 6px;background:none;border:1px solid var(--border);border-radius:4px;font-size:9px;color:var(--text-muted);cursor:pointer" title="${toggleLabel}">${isNoise ? '↑' : '↓'}</button>
                    </div>
                    <div id="sig-article-${s.id}" style="display:none"></div>
                </div>`;
            };

            const signalListHtml = sigSignals.map(s => _renderSignalItem(s, false)).join('');
            const noiseListHtml = sigNoise.length ? `
                <div style="margin-top:12px;padding-top:8px;border-top:1px dashed var(--border)">
                    <div style="font-size:10px;color:var(--text-muted);margin-bottom:6px;cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
                        ↓ ${sigNoise.length} noise signal(s) — click to toggle
                    </div>
                    <div style="display:none">${sigNoise.map(s => _renderSignalItem(s, true)).join('')}</div>
                </div>
            ` : '';

            const narr = thread.narrative;
            const narrativeBreadcrumb = narr
                ? `<div style="padding:8px 16px;border-bottom:1px solid var(--border);font-size:11px;display:flex;align-items:center;gap:4px">
                    <span style="color:var(--accent);cursor:pointer" onclick="_showNarrativeInBoardPane(${narr.id})">📖 ${escHtml(narr.title)}</span>
                    <span style="color:var(--text-muted)">→</span>
                    <span style="color:var(--text-secondary)">${escHtml(thread.title).substring(0, 50)}</span>
                </div>`
                : '';

            detailBody.innerHTML = `
                <div class="sig-detail-card">
                    ${narrativeBreadcrumb}
                    <div class="sig-detail-hero" style="border-left: 4px solid ${domColor}">
                        ${_editableTitle(thread.title, '/api/signals/threads/' + thread.id, 'title', 'loadSignals()')}
                        <div class="sig-detail-meta">
                            ${_renderDomainBadges(thread.domain, '10px')}
                            <span class="thread-momentum ${escHtml(mDir)}">${mLabel}</span>
                            <span style="font-size:11px;color:var(--text-muted)">${signals.length} signals</span>
                            <span style="font-size:11px;color:var(--text-muted)">${m.this_period || 0} this week / ${m.last_period || 0} last week</span>
                        </div>
                    </div>
                    ${thread.synthesis ? `<div class="sig-detail-body-text">${escHtml(thread.synthesis)}</div>` : ''}
                    ${entHtml ? `<div style="padding:12px 20px;border-top:1px solid var(--border)">
                        <div style="font-size:11px;font-weight:700;color:var(--text-secondary);margin-bottom:8px">Entities <span style="font-weight:400;color:var(--text-muted)">(click to find connections)</span></div>
                        ${entHtml}
                    </div>` : ''}
                    <div id="related-threads-${thread.id}" style="padding:12px 20px;border-top:1px solid var(--border);display:none">
                        <div style="font-size:11px;font-weight:700;color:var(--text-secondary);margin-bottom:8px">🔗 Related Threads</div>
                        <div id="related-threads-list-${thread.id}" style="color:var(--text-muted);font-size:11px">Loading...</div>
                    </div>
                    <div style="padding:12px 20px;border-top:1px solid var(--border)">
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                            <div style="font-size:11px;font-weight:700;color:var(--text-secondary)">Signals (${sigSignals.length})${sigNoise.length ? ` · <span style="color:var(--text-muted)">${sigNoise.length} noise</span>` : ''}</div>
                        </div>
                        <div style="margin-bottom:10px;display:flex;gap:6px;align-items:center">
                            <input id="thread-signal-search" type="text" placeholder="Search signals...  (/ to focus)" oninput="_filterThreadSignals(this.value)" onkeydown="if(event.key==='Escape'){this.value='';_filterThreadSignals('');this.blur()}" onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'" style="flex:1;padding:5px 10px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);font-size:11px;outline:none;transition:border-color 0.15s" />
                            <span id="thread-search-count" style="font-size:10px;color:var(--text-muted);white-space:nowrap"></span>
                        </div>
                        <div id="thread-search-actions" style="margin-bottom:8px;gap:6px;display:none">
                            <button onclick="_selectMatchedSignals()" style="padding:4px 10px;background:var(--bg-tertiary);border:1px solid var(--accent);border-radius:5px;color:var(--accent);font-size:10px;font-weight:600;cursor:pointer" id="thread-select-matched-btn">Select matched</button>
                        </div>
                        <div id="thread-signals-list" style="display:flex;flex-direction:column">
                        ${signalListHtml || '<div style="color:var(--text-muted);font-size:12px">No signals</div>'}
                        ${noiseListHtml}
                        </div>
                    </div>
                    <div style="padding:12px 20px;border-top:1px solid var(--border);display:flex;flex-direction:column;gap:6px">
                        <div style="font-size:11px;font-weight:700;color:var(--text-secondary);margin-bottom:2px">Actions</div>
                        ${_buildThreadActions(thread, entities)}
                    </div>
                </div>
            `;
            // Store signals for search/filter
            window._threadDetailSignals = signals;
            window._threadDetailId = thread.id;
            // Load related threads asynchronously
            setTimeout(() => _loadRelatedThreads(thread.id), 100);

            // Auto-apply highlight keywords to signal search if highlights are active
            if (_boardHighlights.length) {
                const hlQuery = _boardHighlights.map(h => h.label).join(' ');
                const searchInput = document.getElementById('thread-signal-search');
                if (searchInput) {
                    searchInput.value = hlQuery;
                    setTimeout(() => _filterThreadSignals(hlQuery), 50);
                }
            }
        })
        .catch(e => {
            if (myRequest !== _detailRequestId) return;
            console.error('[signals] thread detail error:', e);
            detailBody.innerHTML = `<div style="text-align:center;padding:40px;color:var(--red)">Failed to load thread</div>`;
        });
}

var _threadSearchQuery = '';  // var: read/written from base.html outside this module
let _threadSearchMatchIds = new Set();

// / key focuses the thread signal search input
document.addEventListener('keydown', function(e) {
    if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        // Don't capture if user is typing in an input/textarea/select
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        const searchInput = document.getElementById('thread-signal-search');
        if (searchInput && searchInput.offsetParent !== null) {
            e.preventDefault();
            searchInput.focus();
        }
    }
});

function _filterThreadSignals(query) {
    _threadSearchQuery = (query || '').trim().toLowerCase();
    const container = document.getElementById('thread-signals-list');
    const countEl = document.getElementById('thread-search-count');
    const actionsEl = document.getElementById('thread-search-actions');
    const selectBtn = document.getElementById('thread-select-matched-btn');
    if (!container) return;

    const items = container.querySelectorAll('.sig-draggable');
    _threadSearchMatchIds.clear();

    if (!_threadSearchQuery) {
        // Reset: show all, remove highlights
        items.forEach(el => {
            el.style.opacity = '';
            el.style.order = '';
            _removeHighlights(el);
            const hint = el.querySelector('.body-match-hint');
            if (hint) hint.remove();
        });
        if (countEl) countEl.textContent = '';
        if (actionsEl) actionsEl.style.display = 'none';
        return;
    }

    const signals = window._threadDetailSignals || [];
    const sigMap = {};
    signals.forEach(s => { sigMap[s.id] = s; });

    let matchCount = 0;
    items.forEach(el => {
        const sigId = parseInt(el.dataset.sigId);
        const sig = sigMap[sigId];
        if (!sig) { el.style.opacity = '0.2'; return; }

        // Support multi-keyword search (space-separated terms match ANY)
        const _searchTerms = _threadSearchQuery.split(/\s+/).filter(t => t.length >= 2);
        const titleLower = (sig.title || '').toLowerCase();
        const bodyLower = (sig.body || '').toLowerCase();
        const sourceLower = (sig.source_name || sig.source || '').toLowerCase();
        const titleMatch = _searchTerms.some(t => titleLower.includes(t));
        const bodyMatch = _searchTerms.some(t => bodyLower.includes(t));
        const sourceMatch = _searchTerms.some(t => sourceLower.includes(t));

        if (titleMatch || bodyMatch || sourceMatch) {
            el.style.opacity = '';
            el.style.order = '-1';
            _threadSearchMatchIds.add(sigId);
            matchCount++;
            _applyHighlights(el, _threadSearchQuery);
            // Show "match in body" hint if only body matched (not title)
            let hint = el.querySelector('.body-match-hint');
            if (!titleMatch && bodyMatch) {
                if (!hint) {
                    hint = document.createElement('div');
                    hint.className = 'body-match-hint';
                    hint.style.cssText = 'font-size:9px;color:var(--purple);margin-top:2px;cursor:pointer';
                    hint.textContent = '↳ match in article body — click to expand';
                    hint.onclick = (e) => { e.stopPropagation(); _toggleSignalArticle(sigId, el); };
                    el.querySelector('[style*="min-width:0"]')?.appendChild(hint);
                }
            } else if (hint) { hint.remove(); }
        } else {
            el.style.opacity = '0.2';
            el.style.order = '';
            _removeHighlights(el);
        }
    });

    if (countEl) countEl.textContent = `${matchCount}/${items.length}`;
    if (actionsEl && selectBtn) {
        if (matchCount > 0 && matchCount < items.length) {
            actionsEl.style.display = 'flex';
            selectBtn.style.display = '';
            selectBtn.textContent = `Select ${matchCount} matched`;
        } else {
            actionsEl.style.display = 'none';
        }
    }
}

function _applyHighlights(el, query) {
    _removeHighlights(el);
    const titleEl = el.querySelector('[style*="font-weight:600"]');
    if (titleEl) titleEl.innerHTML = _highlightText(titleEl.textContent, query);
}

function _removeHighlights(el) {
    el.querySelectorAll('mark.sig-search-hl').forEach(m => {
        m.replaceWith(document.createTextNode(m.textContent));
    });
    // Normalize merged text nodes
    const titleEl = el.querySelector('[style*="font-weight:600"]');
    if (titleEl) titleEl.normalize();
}

function _highlightText(text, query) {
    if (!query) return escHtml(text);
    // Support multi-keyword: split by spaces, highlight each term
    const terms = query.split(/\s+/).filter(t => t.length >= 2);
    if (!terms.length) return escHtml(text);
    const escaped = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
    const re = new RegExp(`(${escaped})`, 'gi');
    return escHtml(text).replace(re, '<mark class="sig-search-hl" style="background:#a855f740;color:var(--text-primary);border-radius:2px;padding:0 1px">$1</mark>');
}

function _selectMatchedSignals() {
    _threadSearchMatchIds.forEach(id => {
        const selectEl = document.querySelector(`[data-drag-select="${id}"]`);
        if (selectEl && !selectEl.classList.contains('checked')) {
            _toggleDragSelect(id);
        }
    });
}

function _buildThreadActions(thread, entities) {
    const actions = [];
    const companies = (entities || []).filter(e => e.entity_type === 'company');
    const sectors = (entities || []).filter(e => e.entity_type === 'sector');
    const companyNames = [...new Set(companies.map(e => e.normalized_value || e.entity_value))];
    const sectorNames = [...new Set(sectors.map(e => e.entity_value))];

    const btnStyle = 'padding:8px 12px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;text-align:left;display:flex;align-items:center;gap:6px;transition:all 0.15s;';

    // If thread has companies, offer to research them
    if (companyNames.length) {
        const top = companyNames.slice(0, 3);
        actions.push(`<button onclick="_threadActionResearch('${escHtml(top[0].replace(/'/g, "\\'"))}')" style="${btnStyle}background:var(--bg-tertiary);border:1px solid var(--border);color:var(--accent)">🔬 Research ${escHtml(top[0])}</button>`);
        if (top.length > 1) {
            actions.push(`<button onclick="_threadActionDiscover('${escHtml(top.join(', ').replace(/'/g, "\\'"))}')" style="${btnStyle}background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text-secondary)">🔍 Discover companies like ${escHtml(top.slice(0, 2).join(', '))}</button>`);
        }
    }

    // If thread has sectors, offer to discover in that niche
    if (sectorNames.length) {
        const niche = sectorNames[0] + (thread.synthesis ? ' — ' + thread.title : '');
        actions.push(`<button onclick="_threadActionDiscover('${escHtml(niche.replace(/'/g, "\\'"))}')" style="${btnStyle}background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text-secondary)">📊 Discover companies in ${escHtml(sectorNames[0])}</button>`);
    }

    // Internal search (existing signals) + external search (new sources)
    actions.push(`<button onclick="_threadActionSearchInternal(${thread.id}, '${escHtml(thread.title.replace(/'/g, "\\'"))}')" style="${btnStyle}background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text-secondary)">🔍 Find in existing signals</button>`);
    actions.push(`<button onclick="_threadActionSearchMore('${escHtml(thread.title.replace(/'/g, "\\'"))}', ${thread.id})" style="${btnStyle}background:var(--bg-tertiary);border:1px solid var(--border);color:var(--text-muted)">📡 Search for more signals</button>`);

    // Split / Thread Lab (6+ signals → split, 20+ signals → Thread Lab)
    const sigCount = (thread.signals || []).length;
    if (sigCount >= 20) {
        actions.push(`<button onclick="_openThreadLab(${thread.id})" style="${btnStyle}background:var(--bg-tertiary);border:1px solid var(--purple);color:var(--purple)">🧪 Thread Lab</button>`);
    } else if (sigCount >= 6) {
        actions.push(`<button onclick="_proposeThreadSplit(${thread.id})" id="split-thread-btn" style="${btnStyle}background:var(--bg-tertiary);border:1px solid var(--purple);color:var(--purple)">✂️ Split thread</button>`);
    }

    // Delete thread
    actions.push(`<button onclick="_deleteThread(${thread.id})" style="${btnStyle}background:none;border:1px solid var(--border);color:var(--text-muted);font-size:10px">🗑 Delete thread</button>`);

    return actions.join('');
}

// ── Review Queue ──
let _reviewQueueData = [];

function _loadReviewQueueCount() {
    fetch('/api/signals/review-queue?limit=1')
        .then(r => r.json())
        .then(data => {
            const total = data.total || 0;
            // Inline badge in filter bar (threads + signals tabs)
            const badge = document.getElementById('review-queue-badge');
            const count = document.getElementById('review-queue-count');
            if (badge) badge.style.display = total > 0 ? '' : 'none';
            if (count) count.textContent = total;
            // Organize lab badge
            const orgBtn = document.getElementById('organize-lab-btn');
            const orgCount = document.getElementById('organize-count');
            if (orgBtn) orgBtn.style.display = total > 0 ? '' : 'none';
            if (orgCount) orgCount.textContent = total;
            // Right-pane count (signals raw tab)
            const rqCount = document.getElementById('sig-rq-count');
            if (rqCount) rqCount.textContent = total || '';
        })
        .catch(() => {});
}

function _openReviewQueue(offset) {
    offset = offset || 0;
    const detailBody = _showDetailPane('Review Queue');
    detailBody.innerHTML = '<div style="padding:20px;color:var(--text-muted);font-size:12px">Loading review queue...</div>';

    fetch(`/api/signals/review-queue?limit=20&offset=${offset}`)
        .then(r => r.json())
        .then(data => {
            _reviewQueueData = data.signals || [];
            const total = data.total || 0;

            if (!_reviewQueueData.length) {
                detailBody.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-muted)">
                    <div style="font-size:32px;margin-bottom:12px">✓</div>
                    <div>No signals to review</div>
                </div>`;
                return;
            }

            // Get thread list for the "assign to" dropdowns
            const threads = _threadsCache || [];

            let html = `<div style="padding:12px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between">
                <div style="font-size:11px;color:var(--text-muted)">${offset + 1}–${Math.min(offset + _reviewQueueData.length, total)} of ${total} unassigned</div>
                <div style="display:flex;gap:4px">
                    ${offset > 0 ? `<button onclick="_openReviewQueue(${offset - 20})" style="padding:4px 8px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:4px;color:var(--text-muted);font-size:10px;cursor:pointer">← Prev</button>` : ''}
                    ${offset + 20 < total ? `<button onclick="_openReviewQueue(${offset + 20})" style="padding:4px 8px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:4px;color:var(--text-muted);font-size:10px;cursor:pointer">Next →</button>` : ''}
                </div>
            </div>`;

            html += _reviewQueueData.map((sig, i) => {
                const dateStr = sig.published_at ? sig.published_at.substring(0, 10) : '';
                const confColor = sig.confidence === 'high' ? '#22c55e' : sig.confidence === 'medium' ? '#eab308' : '#6b7280';
                const confDot = `<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${confColor};margin-right:2px"></span>`;

                // Thread suggestion pills — styled like entity chips
                const suggHtml = (sig.suggestions || []).map((s, si) => {
                    const pct = Math.round(s.score * 100);
                    const barWidth = Math.max(pct, 8);
                    const isTop = si === 0 && pct > 15;
                    const isOutlier = s.temporal_outlier;
                    const borderColor = isOutlier ? 'rgba(245,158,11,0.5)' : isTop ? 'var(--accent)' : 'var(--border)';
                    const textColor = isOutlier ? '#f59e0b' : isTop ? 'var(--accent)' : 'var(--text-secondary)';
                    const outlierBadge = isOutlier
                        ? `<span title="Signal date outside thread range ${s.thread_range || ''}" style="font-size:9px;color:#f59e0b;flex-shrink:0;margin-left:4px">⏱ ${s.thread_range || ''}</span>`
                        : '';
                    return `<div onclick="_assignFromQueue(${sig.id}, ${s.thread_id}, this)" style="position:relative;padding:6px 10px;background:var(--bg-tertiary);border:1px solid ${borderColor};border-radius:6px;cursor:pointer;overflow:hidden;transition:all 0.15s" onmouseenter="this.style.borderColor='var(--accent)';this.style.background='rgba(59,130,246,0.08)'" onmouseleave="this.style.borderColor='${borderColor}';this.style.background='var(--bg-tertiary)'">
                        <div style="position:absolute;left:0;top:0;bottom:0;width:${barWidth}%;background:rgba(59,130,246,0.06);pointer-events:none"></div>
                        <div style="position:relative;display:flex;justify-content:space-between;align-items:center;gap:8px">
                            <span style="font-size:11px;color:${textColor};font-weight:${isTop ? '600' : '400'};overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(s.thread_title)}</span>
                            <div style="display:flex;align-items:center;flex-shrink:0;gap:2px">
                                ${outlierBadge}
                                <span style="font-size:10px;color:var(--text-muted);font-weight:600">${pct}%</span>
                            </div>
                        </div>
                    </div>`;
                }).join('');

                return `<div id="rq-item-${sig.id}" style="padding:12px 16px;border-bottom:1px solid var(--border)">
                    <div style="display:flex;align-items:start;justify-content:space-between;gap:8px;margin-bottom:8px">
                        <div style="flex:1;min-width:0">
                            <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:4px;line-height:1.3">${escHtml(sig.title)}</div>
                            <div style="font-size:10px;color:var(--text-muted);display:flex;gap:8px;align-items:center">
                                ${confDot}
                                <span>${escHtml(sig.source_name)}</span>
                                <span>${escHtml(dateStr)}</span>
                            </div>
                        </div>
                        <button onclick="_dismissFromQueue(${sig.id}, this)" style="flex-shrink:0;width:24px;height:24px;display:flex;align-items:center;justify-content:center;background:none;border:1px solid var(--border);border-radius:6px;font-size:11px;color:var(--text-muted);cursor:pointer;transition:all 0.15s" onmouseenter="this.style.borderColor='#ef4444';this.style.color='#ef4444'" onmouseleave="this.style.borderColor='var(--border)';this.style.color='var(--text-muted)'" title="Dismiss as noise">✕</button>
                    </div>
                    <div style="display:flex;flex-direction:column;gap:4px">
                        ${suggHtml || '<div style="font-size:10px;color:var(--text-muted);padding:4px 0">No thread suggestions</div>'}
                        <div style="position:relative">
                            <div onclick="_toggleRqDropdown(${sig.id})" style="padding:5px 10px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:10px;cursor:pointer;display:flex;justify-content:space-between;align-items:center">
                                <span>Other thread...</span><span style="font-size:8px">▼</span>
                            </div>
                            <div id="rq-dd-${sig.id}" style="display:none;position:absolute;left:0;right:0;top:100%;z-index:20;background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px;margin-top:2px;box-shadow:0 4px 16px rgba(0,0,0,0.5);overflow:hidden">
                                <div style="padding:6px 12px;font-size:12px;color:var(--text-primary);font-weight:600;border-bottom:1px solid var(--border);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml(sig.title)}</div>
                                <input type="text" placeholder="Search or create thread..." id="rq-search-${sig.id}" oninput="_filterRqDropdown(${sig.id}, this.value)" onkeydown="_rqSearchKeydown(event,${sig.id})" style="width:100%;padding:7px 12px;background:var(--bg-tertiary);border:none;border-bottom:1px solid var(--border);color:var(--text-primary);font-size:12px;outline:none;box-sizing:border-box" />
                                <div id="rq-list-${sig.id}" style="max-height:200px;overflow-y:auto"></div>
                            </div>
                        </div>
                    </div>
                </div>`;
            }).join('');

            detailBody.innerHTML = html;
        });
}

function _assignFromQueue(signalId, threadId, el) {
    const item = document.getElementById(`rq-item-${signalId}`);
    const originalHtml = item ? item.innerHTML : '';

    fetch('/api/signals/review-queue/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_id: signalId, thread_id: threadId })
    }).then(r => r.json()).then(data => {
        if (data.ok && item) {
            const cached = _rqListCache.find(s => s.id === signalId);
            if (cached) cached._assigned = true;

            item.style.opacity = '0.5';
            item.innerHTML = `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0">
                <span style="font-size:11px;color:var(--green)">✓ Assigned</span>
                <button onclick="_undoAssign(${signalId}, ${threadId}, this)" style="padding:2px 8px;background:none;border:1px solid var(--border);border-radius:4px;font-size:10px;color:var(--text-muted);cursor:pointer">Undo</button>
            </div>`;
            item._originalHtml = originalHtml;
            const countEl = document.getElementById('review-queue-count');
            if (countEl) countEl.textContent = Math.max(0, parseInt(countEl.textContent || '0') - 1);
        }
    });
}

function _undoAssign(signalId, threadId, btn) {
    fetch('/api/signals/review-queue/unassign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_id: signalId, thread_id: threadId })
    }).then(r => r.json()).then(data => {
        if (data.ok) {
            const cached = _rqListCache.find(s => s.id === signalId);
            if (cached) delete cached._assigned;

            const item = document.getElementById(`rq-item-${signalId}`);
            if (item && item._originalHtml) {
                item.innerHTML = item._originalHtml;
                item.style.opacity = '';
                delete item._originalHtml;
            }
            const countEl = document.getElementById('review-queue-count');
            if (countEl) countEl.textContent = parseInt(countEl.textContent || '0') + 1;
        }
    });
}

function _dismissFromQueue(signalId, el) {
    const item = document.getElementById(`rq-item-${signalId}`);
    const originalHtml = item ? item.innerHTML : '';

    fetch('/api/signals/review-queue/dismiss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_id: signalId })
    }).then(r => r.json()).then(data => {
        if (data.ok && item) {
            const cached = _rqListCache.find(s => s.id === signalId);
            if (cached) cached._assigned = true;

            item.style.opacity = '0.5';
            item.innerHTML = `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0">
                <span style="font-size:11px;color:var(--text-muted)">✕ Dismissed</span>
                <button onclick="_undoDismiss(${signalId}, this)" style="padding:2px 8px;background:none;border:1px solid var(--border);border-radius:4px;font-size:10px;color:var(--text-muted);cursor:pointer">Undo</button>
            </div>`;
            item._originalHtml = originalHtml;
            const countEl = document.getElementById('review-queue-count');
            if (countEl) countEl.textContent = Math.max(0, parseInt(countEl.textContent || '0') - 1);
        }
    });
}

function _undoDismiss(signalId, btn) {
    fetch('/api/signals/review-queue/undismiss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_id: signalId })
    }).then(r => r.json()).then(data => {
        if (data.ok) {
            const cached = _rqListCache.find(s => s.id === signalId);
            if (cached) delete cached._assigned;

            const item = document.getElementById(`rq-item-${signalId}`);
            if (item && item._originalHtml) {
                item.innerHTML = item._originalHtml;
                item.style.opacity = '';
                delete item._originalHtml;
            }
            const countEl = document.getElementById('review-queue-count');
            if (countEl) countEl.textContent = parseInt(countEl.textContent || '0') + 1;
        }
    });
}

function _toggleRqDropdown(sigId) {
    // Close any other open dropdowns
    document.querySelectorAll('[id^="rq-dd-"]').forEach(dd => {
        if (dd.id !== `rq-dd-${sigId}`) dd.style.display = 'none';
    });
    const dd = document.getElementById(`rq-dd-${sigId}`);
    if (!dd) return;
    const isOpen = dd.style.display !== 'none';
    dd.style.display = isOpen ? 'none' : '';
    if (!isOpen) {
        _renderRqList(sigId, '');
        const input = document.getElementById(`rq-search-${sigId}`);
        if (input) { input.value = ''; setTimeout(() => input.focus(), 50); }
    }
}

function _filterRqDropdown(sigId, query) {
    _renderRqList(sigId, query);
}

function _rqSearchKeydown(event, sigId) {
    if (event.key === 'Escape') {
        const dd = document.getElementById(`rq-dd-${sigId}`);
        if (dd) dd.style.display = 'none';
        return;
    }

    const items = document.querySelectorAll(`#rq-list-${sigId} .rq-list-item`);
    if (!items.length) return;

    if (event.key === 'ArrowDown') {
        event.preventDefault();
        _activeRqIndex = (_activeRqIndex + 1) % items.length;
        _updateRqHighlight(sigId);
    } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        _activeRqIndex = (_activeRqIndex - 1 + items.length) % items.length;
        _updateRqHighlight(sigId);
    } else if (event.key === 'Enter') {
        event.preventDefault();
        if (_activeRqIndex >= 0 && _activeRqIndex < items.length) {
            items[_activeRqIndex].click();
        }
    }
}

function _updateRqHighlight(sigId) {
    const items = document.querySelectorAll(`#rq-list-${sigId} .rq-list-item`);
    items.forEach((it, idx) => {
        if (idx === _activeRqIndex) {
            it.classList.add('active');
            it.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        } else {
            it.classList.remove('active');
        }
    });
}


// Close dropdown when clicking outside or pressing Escape
document.addEventListener('click', (e) => {
    if (!e.target.closest('[id^="rq-dd-"]') && !e.target.closest('[onclick*="_toggleRqDropdown"]')) {
        document.querySelectorAll('[id^="rq-dd-"]').forEach(dd => dd.style.display = 'none');
    }
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('[id^="rq-dd-"]').forEach(dd => dd.style.display = 'none');
    }
});

function _pruneSignals() {
    const btn = document.getElementById('signals-prune-btn');
    if (btn) { btn.textContent = '✂️ Pruning...'; btn.disabled = true; }

    fetch('/api/signals/prune', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (btn) { btn.disabled = false; btn.textContent = '✂️ Prune Duplicates'; }
            if (data.ok) {
                _showToast(`Pruned ${data.pruned} duplicates across ${data.groups} groups`, 'success', 5000);
                loadSignals();
                if (_signalTab === 'graph') loadBoard();
                _loadReviewQueueCount();
            } else {
                _showToast(data.error || 'Prune failed', 'error');
            }
        })
        .catch(() => {
            if (btn) { btn.disabled = false; btn.textContent = '✂️ Prune Duplicates'; }
            _showToast('Prune failed — restart server', 'error');
        });
}

function _mergeThreads() {
    _showConfirm('Merge duplicate threads? This will consolidate threads with similar titles, keeping the one with the most signals.', () => {
        _showToast('Merging threads...', 'info', 10000);
        fetch('/api/signals/merge-threads', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    _showToast(`Merged ${data.groups_merged} groups: ${data.threads_removed} duplicates removed, ${data.signals_reassigned} signals reassigned`, 'success', 8000);
                    loadSignals();
                    if (_signalTab === 'graph') loadBoard();
                    if (_signalTab === 'causal') loadCausalView();
                } else {
                    _showToast(data.error || 'Merge failed', 'error');
                }
            })
            .catch(() => _showToast('Merge failed — restart server', 'error'));
    });
}

// ── Selection Action Bar (inline in filter bar) ──────────────────
function _updateSelectionBar() {
    const bar = document.getElementById('selection-action-bar');
    if (!bar) return;

    if (_signalTab === 'raw') {
        const count = _rawSelectedSignals.size;
        if (count === 0) {
            bar.style.display = 'none';
            return;
        }
        bar.style.display = 'flex';
        bar.innerHTML = `<span style="font-size:11px;color:var(--text-secondary);font-weight:600;white-space:nowrap">${count} selected</span>` +
            (count >= 2
                ? `<button onclick="_createPatternFromSelection()" style="padding:4px 10px;background:linear-gradient(135deg,var(--accent),var(--purple));border:none;border-radius:6px;color:#fff;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap">Create Thread</button>`
                : `<span style="font-size:10px;color:var(--text-muted);white-space:nowrap">+1 more</span>`) +
            `<button onclick="_clearRawSelection()" style="padding:4px 8px;background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:10px;cursor:pointer">✕</button>`;
    } else if (_signalTab === 'threads') {
        const count = _selectedThreadsForNarrative.size;
        if (count === 0) {
            bar.style.display = 'none';
            return;
        }
        bar.style.display = 'flex';
        bar.innerHTML = `<span style="font-size:11px;color:var(--text-secondary);font-weight:600;white-space:nowrap">${count} selected</span>` +
            (count >= 2
                ? `<button onclick="_createNarrativeFromThreads()" style="padding:4px 10px;background:linear-gradient(135deg,var(--accent),var(--purple));border:none;border-radius:6px;color:#fff;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap">Create Narrative</button>`
                : `<span style="font-size:10px;color:var(--text-muted);white-space:nowrap">+1 more</span>`) +
            `<button onclick="_bulkDeleteThreads([..._selectedThreadsForNarrative])" style="padding:4px 8px;background:none;border:1px solid #ef4444;border-radius:6px;color:#ef4444;font-size:10px;cursor:pointer" title="Delete selected">🗑</button>` +
            `<button onclick="_selectedThreadsForNarrative.clear();renderThreadFeed()" style="padding:4px 8px;background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:10px;cursor:pointer">✕</button>`;
    } else {
        bar.style.display = 'none';
    }
}

// ── Signal Tools Menu ─────────────────────────────────────────────
function _toggleSignalTools() {
    const menu = document.getElementById('signal-tools-menu');
    if (menu) menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}
// Close on click outside
document.addEventListener('click', (e) => {
    const menu = document.getElementById('signal-tools-menu');
    if (menu && menu.style.display !== 'none' && !e.target.closest('#signal-tools-btn') && !e.target.closest('#signal-tools-menu')) {
        menu.style.display = 'none';
    }
});

// ── Quick Capture ─────────────────────────────────────────────────

let _qcSource = 'linkedin';
let _qcCapturing = false;
let _qcSessionItems = [];

function _closeAllAddPanels() {
    const btn = document.getElementById('quick-capture-toggle');
    ['quick-capture-panel', 'thread-create-panel', 'chain-create-panel'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    if (btn) { btn.style.background = 'rgba(168,85,247,0.08)'; btn.textContent = '+'; }
}

function _toggleQuickCapture() {
    const btn = document.getElementById('quick-capture-toggle');
    const isOpen = btn && btn.textContent === '×';
    if (isOpen) { _closeAllAddPanels(); return; }

    _closeAllAddPanels();
    btn.style.background = 'rgba(168,85,247,0.2)';
    btn.textContent = '×';

    if (_signalTab === 'raw') {
        const panel = document.getElementById('quick-capture-panel');
        panel.style.display = 'block';
        document.getElementById('qc-paste').focus();
    } else if (_signalTab === 'threads') {
        const panel = document.getElementById('thread-create-panel');
        panel.style.display = 'block';
        document.getElementById('tc-title').focus();
    } else if (_signalTab === 'narratives') {
        _closeAllAddPanels();
        openNarrativeModal();
    } else if (_signalTab === 'causal') {
        const panel = document.getElementById('chain-create-panel');
        panel.style.display = 'block';
        document.getElementById('cc-name').focus();
    }
}

function _qcSelectSource(el) {
    document.querySelectorAll('.qc-source').forEach(c => {
        c.style.background = 'none';
        c.style.borderColor = 'var(--border)';
        c.style.color = 'var(--text-muted)';
        c.classList.remove('active');
    });
    el.classList.add('active');
    el.style.background = 'rgba(168,85,247,0.1)';
    el.style.borderColor = 'rgba(168,85,247,0.3)';
    el.style.color = 'var(--purple)';
    _qcSource = el.dataset.source;
}

// Live preview parse on input
(function() {
    const ta = document.getElementById('qc-paste');
    if (!ta) return;
    ta.addEventListener('input', () => {
        const btn = document.getElementById('qc-submit');
        btn.disabled = !ta.value.trim();
        btn.style.opacity = ta.value.trim() ? '1' : '0.4';
        _qcPreviewParse(ta.value);
    });
    ta.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            if (!document.getElementById('qc-submit').disabled) _qcCapture();
        }
    });
})();

function _qcPreviewParse(text) {
    const parsed = document.getElementById('qc-parsed');
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) { parsed.style.display = 'none'; return; }

    const timeRe = /^(\d+[dhwmo]|just now|yesterday|\d+\s*(day|hour|week|month|min)s?\s*ago)/i;
    let headerEnd = -1;
    for (let i = 1; i < Math.min(5, lines.length); i++) {
        const clean = lines[i].replace(/[•·🌐🔒]/g, '').replace(/Edited\s*/i, '').trim();
        if (timeRe.test(clean) && clean.length < 40) { headerEnd = i; break; }
    }

    const authorEl = document.getElementById('qc-author-badge');
    const domainEl = document.getElementById('qc-domain-badge');
    const dateEl = document.getElementById('qc-date-badge');

    if (headerEnd > 0) {
        authorEl.textContent = lines[0];
        const body = lines.slice(headerEnd + 1).join(' ').toLowerCase();
        domainEl.textContent = _qcGuessDomain(body);
        // Parse date
        const timeLine = lines[headerEnd].replace(/[•·🌐🔒]/g, '').replace(/Edited\s*/i, '').trim();
        const m = timeLine.match(/^(\d+)\s*([dhwmo])/);
        if (m) {
            const n = parseInt(m[1]), u = m[2];
            const d = new Date();
            d.setDate(d.getDate() - n * ({d:1,h:1/24,w:7,m:30,o:30}[u]||1));
            dateEl.textContent = d.toISOString().slice(0,10);
        } else if (/yesterday/i.test(timeLine)) {
            const d = new Date(); d.setDate(d.getDate()-1);
            dateEl.textContent = d.toISOString().slice(0,10);
        } else {
            dateEl.textContent = new Date().toISOString().slice(0,10);
        }
    } else {
        authorEl.textContent = '';
        domainEl.textContent = _qcGuessDomain(text.toLowerCase());
        dateEl.textContent = '';
    }
    parsed.style.display = 'block';
}

function _qcGuessDomain(text) {
    const kw = {
        tech_ai: ['ai ','artificial intelligence','llm','machine learning','software','cloud','startup','saas','semiconductor'],
        finance: ['earnings','ipo','merger','acquisition','investor','market cap','valuation','hedge fund'],
        economics: ['gdp','recession','inflation','economic','fed ','interest rate','monetary'],
        labor: ['layoff','hiring','workforce','employment','job market','remote work','salary'],
        geopolitics: ['tariff','sanction','trade war','china','nato','conflict'],
        regulatory: ['regulation','compliance','fda','antitrust','privacy','gdpr'],
    };
    let best = 'economics', bs = 0;
    for (const [d, ws] of Object.entries(kw)) {
        let s = 0; for (const w of ws) if (text.includes(w)) s++;
        if (s > bs) { bs = s; best = d; }
    }
    return best;
}

async function _qcCapture() {
    if (_qcCapturing) return;
    _qcCapturing = true;
    const btn = document.getElementById('qc-submit');
    btn.disabled = true;
    btn.textContent = 'Capturing…';

    const ta = document.getElementById('qc-paste');
    try {
        const res = await fetch('/api/signals/manual', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                content: ta.value,
                source: _qcSource,
                url: document.getElementById('qc-url').value.trim(),
                title: (document.getElementById('qc-title').value || '').trim(),
            }),
        });
        const data = await res.json();
        if (data.ok) {
            _qcSessionItems.unshift(data);
            _qcRenderSession();
            _showToast('Captured' + (data.thread_assignment ? ' → ' + data.thread_assignment.thread_title : ''), 'success');
            ta.value = '';
            document.getElementById('qc-title').value = '';
            document.getElementById('qc-url').value = '';
            document.getElementById('qc-parsed').style.display = 'none';
            btn.style.opacity = '0.4';
            ta.focus();
            // Refresh signals list if on Signals tab
            if (typeof loadSignals === 'function') loadSignals();
        } else {
            _showToast(data.error || 'Capture failed', 'error');
        }
    } catch (e) {
        _showToast('Network error', 'error');
    }
    _qcCapturing = false;
    btn.disabled = !ta.value.trim();
    btn.textContent = 'Capture';
}

function _qcRenderSession() {
    const wrap = document.getElementById('qc-session');
    wrap.style.display = 'block';
    wrap.innerHTML = _qcSessionItems.map(s => {
        const thread = s.thread_assignment ? `<span style="color:var(--purple)">→ ${escHtml(s.thread_assignment.thread_title)}</span>` : '';
        return `<div style="display:flex;align-items:center;gap:4px;padding:3px 0;font-size:9px;border-bottom:1px solid var(--border)">
            <span style="color:var(--green)">✓</span>
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-primary)">${escHtml(s.title)}</span>
            ${thread}
        </div>`;
    }).join('');
}

// ── Thread Creation ───────────────────────────────────────────────
async function _tcCreate() {
    const title = document.getElementById('tc-title').value.trim();
    if (!title) { _showToast('Thread title required', 'error'); return; }
    const btn = document.getElementById('tc-submit');
    btn.disabled = true; btn.textContent = 'Creating…';
    try {
        const res = await fetch('/api/signals/threads/create', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ title, content: document.getElementById('tc-paste').value }),
        });
        const d = await res.json();
        if (d.ok) {
            const msg = d.signals_created > 0 ? `Thread created with ${d.signals_created} signals` : 'Empty thread created';
            _showToast(msg, 'success');
            document.getElementById('tc-title').value = '';
            document.getElementById('tc-paste').value = '';
            _closeAllAddPanels();
            loadSignals();
        } else {
            _showToast(d.error || 'Failed', 'error');
        }
    } catch (e) { _showToast('Error: ' + e.message, 'error'); }
    btn.disabled = false; btn.textContent = 'Create Thread';
}

// ── Chain Creation ────────────────────────────────────────────────
async function _ccCreate() {
    const name = document.getElementById('cc-name').value.trim();
    if (!name) { _showToast('Chain name required', 'error'); return; }
    const btn = document.getElementById('cc-submit');
    btn.disabled = true; btn.textContent = 'Creating…';
    try {
        const res = await fetch('/api/causal-paths', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name, thread_ids: [] }),
        });
        const d = await res.json();
        if (d.ok) {
            _showToast('Chain created', 'success');
            document.getElementById('cc-name').value = '';
            _closeAllAddPanels();
            _activeCausalPathId = d.id;
            loadCausalView();
        } else {
            _showToast(d.error || 'Failed', 'error');
        }
    } catch (e) { _showToast('Error: ' + e.message, 'error'); }
    btn.disabled = false; btn.textContent = 'Create Chain';
}

function _runCustomSearch() {
    const input = document.getElementById('custom-search-input');
    const status = document.getElementById('custom-search-status');
    const query = input.value.trim();
    if (!query) return;

    status.style.display = 'block';
    status.innerHTML = `<span style="color:var(--accent)">Searching "${escHtml(query.substring(0,30))}"...</span>`;

    // Log to execution data
    const entry = { query, status: 'running', startedAt: new Date().toISOString() };
    if (!_execData.customSearches) _execData.customSearches = [];
    _execData.customSearches.push(entry);
    _renderExecutionDetail();

    fetch('/api/signals/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
    })
    .then(r => r.json())
    .then(data => {
        status.innerHTML = `<span style="color:var(--green)">✓ ${data.total_found || 0} found, ${data.new_inserted || 0} new</span>`;
        entry.status = 'done';
        entry.total_found = data.total_found || 0;
        entry.new_inserted = data.new_inserted || 0;
        entry.audit = data.audit || [];
        _renderExecutionDetail();
        loadSignals();
        if (_signalTab === 'graph') loadBoard();
        setTimeout(() => { status.style.display = 'none'; }, 5000);
    })
    .catch(() => {
        status.innerHTML = '<span style="color:var(--red)">Search failed</span>';
        entry.status = 'error';
        _renderExecutionDetail();
    });
}

function _loadRelatedThreads(threadId) {
    fetch(`/api/signals/threads/${threadId}/related`)
        .then(r => r.json())
        .then(data => {
            const container = document.getElementById(`related-threads-${threadId}`);
            const list = document.getElementById(`related-threads-list-${threadId}`);
            if (!container || !list) return;
            const related = data.related || [];
            if (!related.length) { container.style.display = 'none'; return; }
            container.style.display = 'block';
            list.innerHTML = related.map(r => {
                const color = _DOMAIN_COLORS[r.domain] || '#6b7280';
                const sharedText = r.shared_entities.map(e => `${_entIcon[e.type] || '🔹'} ${e.name}`).join(', ');
                return `<div style="padding:6px 0;border-bottom:1px solid var(--border);cursor:pointer" onclick="openThreadDetail(${r.id})">
                    <div style="font-size:11px;font-weight:600;color:var(--text-primary)">${escHtml(r.title)}</div>
                    <div style="font-size:9px;color:var(--text-muted);margin-top:2px">${r.shared_count} shared: ${escHtml(sharedText)}</div>
                </div>`;
            }).join('');
        });
}
const _entIcon = {company: '🏢', sector: '📊', geography: '📍', person: '👤', regulation: '⚖️', concept: '💡', event: '📅'};

