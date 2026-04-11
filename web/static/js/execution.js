// ===================== DISCOVERY DRAWER =====================

const _entIconMap = {company:'🏢',sector:'📊',geography:'📍',country:'📍',city:'📍',person:'👤',regulation:'⚖️',concept:'💡',event:'📅',index:'📈'};

function _setDiscoveryMargin(open) {
    // Toggle floating mode when brainstorm overlay is visible
    const drawer = document.getElementById('discovery-drawer');
    const overlay = document.getElementById('brainstorm-overlay');
    if (drawer) {
        const brainstormOpen = overlay && overlay.classList.contains('visible');
        drawer.classList.toggle('floating', brainstormOpen && open);
    }
}

function _openDiscoveryDrawer(crumbNode) {
    _discoveryDrawerOpen = true;
    const drawer = document.getElementById('discovery-drawer');
    const wasHidden = drawer && drawer.style.display === 'none';
    if (drawer) { drawer.style.display = ''; if (wasHidden) drawer.style.animation = 'disc-slide-in 0.2s ease-out'; }
    _setDiscoveryMargin(true);

    if (crumbNode) {
        if (_discoveryBreadcrumb.length === 0) {
            _pendingCrumbNode = crumbNode;
            _discoveryBreadcrumb = [crumbNode];
        } else {
            _discoveryNavigateTo(crumbNode);
            return;
        }
        _renderDiscoveryBreadcrumb();
        _renderDiscoveryBody('<div style="text-align:center;padding:40px;color:var(--text-muted);font-size:13px">Searching...</div>');
        _updateDiscoverySaveBtn();
    } else if (_discoveryBreadcrumb.length > 0) {
        _renderDiscoveryBreadcrumb();
        if (_discoveryResults.length) _renderDiscoveryResults(_discoveryResults);
        _updateDiscoverySaveBtn();
    }
}

function _closeDiscoveryDrawer() {
    _discoveryDrawerOpen = false;
    const drawer = document.getElementById('discovery-drawer');
    if (drawer) drawer.style.display = 'none';
    _setDiscoveryMargin(false);
}

function _clearDiscoveryTrail() {
    _discoveryBreadcrumb = [];
    _discoveryResults = [];
    // Remove discovery-specific board highlights
    for (let i = _boardHighlights.length - 1; i >= 0; i--) {
        if (_boardHighlights[i].key && _boardHighlights[i].key.startsWith('discovery:')) _removeBoardHighlight(i);
    }
    _renderDiscoveryBreadcrumb();
    _renderDiscoveryBody('<div class="discovery-drawer-empty"><div style="font-size:28px;margin-bottom:10px">🔍</div><div style="font-size:14px">Click a concept, entity, or "Find similar" to start exploring</div></div>');
    _updateDiscoverySaveBtn();
}

function _renderDiscoveryBody(html) {
    const body = document.getElementById('discovery-drawer-body');
    if (body) body.innerHTML = html;
}

// Track pending crumb so we can remove it if results are empty
let _pendingCrumbNode = null;

function _discoveryNavigateTo(crumbNode) {
    const last = _discoveryBreadcrumb[_discoveryBreadcrumb.length - 1];
    if (last && last.type === crumbNode.type &&
        ((crumbNode.type === 'thread' && last.threadId === crumbNode.threadId) ||
         (crumbNode.type === 'entity' && last.entityValue === crumbNode.entityValue) ||
         (crumbNode.type === 'keyword' && last.query === crumbNode.query))) return;
    _pendingCrumbNode = crumbNode;
    _discoveryBreadcrumb.push(crumbNode);
    _renderDiscoveryBreadcrumb();
    _updateDiscoverySaveBtn();
    _fetchDiscoveryResults(crumbNode);
}

function _fetchDiscoveryResults(crumbNode) {
    _renderDiscoveryBody('<div style="text-align:center;padding:40px;color:var(--text-muted);font-size:13px">Searching...</div>');

    if (crumbNode.type === 'thread') {
        if (crumbNode.method === 'domain') {
            // Client-side domain match
            const thread = (_threadsCache || []).find(t => t.id === crumbNode.threadId);
            if (!thread) return;
            const domains = _parseDomains(thread.domain);
            const similar = (_threadsCache || []).filter(t => {
                if (t.id === crumbNode.threadId) return false;
                return _parseDomains(t.domain).some(d => domains.includes(d));
            }).slice(0, 20);
            _renderDiscoveryResults(similar.map(t => ({
                threadId: t.id, title: t.title, domain: t.domain,
                reason: `Same domain: ${_parseDomains(t.domain).filter(d => domains.includes(d)).join(', ')}`,
                matchScore: t.signal_count || 0,
            })));
        } else if (crumbNode.method === 'size') {
            const thread = (_threadsCache || []).find(t => t.id === crumbNode.threadId);
            if (!thread) return;
            const count = thread.signal_count || 0;
            const min = Math.max(1, Math.floor(count * 0.8));
            const max = Math.ceil(count * 1.2);
            const similar = (_threadsCache || []).filter(t => {
                const sc = t.signal_count || 0;
                return t.id !== crumbNode.threadId && sc >= min && sc <= max;
            }).sort((a, b) => Math.abs((a.signal_count || 0) - count) - Math.abs((b.signal_count || 0) - count)).slice(0, 20);
            _renderDiscoveryResults(similar.map(t => ({
                threadId: t.id, title: t.title, domain: t.domain,
                reason: `${t.signal_count || 0} signals (similar to ${count})`,
                matchScore: t.signal_count || 0,
            })));
        } else {
            // Default: entity overlap
            fetch(`/api/signals/threads/${crumbNode.threadId}/related`).then(r => r.json()).then(data => {
                _renderDiscoveryResults((data.related || []).map(r => ({
                    threadId: r.id, title: r.title, domain: r.domain,
                    reason: `${r.shared_count} shared: ${(r.shared_entities || []).map(e => e.name).join(', ')}`,
                    sharedEntities: r.shared_entities || [], matchScore: r.shared_count,
                })));
            });
        }
    } else if (crumbNode.type === 'entity') {
        fetch(`/api/signals/entity-threads?type=${encodeURIComponent(crumbNode.entityType)}&value=${encodeURIComponent(crumbNode.entityValue)}`)
            .then(r => r.json()).then(data => {
                const threadIds = data.thread_ids || [];
                const results = threadIds.map(tid => {
                    const t = (_threadsCache || []).find(th => th.id === tid);
                    return t ? { threadId: t.id, title: t.title, domain: t.domain,
                        reason: `Contains: ${crumbNode.entityValue}`, matchScore: t.signal_count || 0 } : null;
                }).filter(Boolean);
                _renderDiscoveryResults(results);
                if (_signalTab === 'graph' && threadIds.length) {
                    _addBoardHighlight({ kind: 'entity', label: crumbNode.entityValue, icon: '🔭',
                        threadIds: new Set(threadIds), key: 'discovery:' + crumbNode.entityValue });
                }
            });
    } else if (crumbNode.type === 'keyword') {
        fetch(`/api/signals/search?q=${encodeURIComponent(crumbNode.query)}`).then(r => r.json()).then(data => {
            const matches = data.thread_matches || [];
            const results = matches.map(m => {
                const t = (_threadsCache || []).find(th => th.id === m.thread_id);
                return { threadId: m.thread_id, title: t ? t.title : m.thread_title || `Thread #${m.thread_id}`,
                    domain: t ? t.domain : '', reason: `${m.match_count} signal matches`, matchScore: m.match_count };
            });
            _renderDiscoveryResults(results);
            if (_signalTab === 'graph' && results.length) {
                _addBoardHighlight({ kind: 'keyword', label: crumbNode.query, icon: '🔭',
                    threadIds: new Set(results.map(r => r.threadId)), key: 'discovery:' + crumbNode.query });
            }
        });
    }
}

function _renderDiscoveryResults(results) {
    _discoveryResults = results;
    const body = document.getElementById('discovery-drawer-body');
    if (!body) return;
    if (!results.length) {
        // Remove the pending crumb that produced no results
        if (_pendingCrumbNode && _discoveryBreadcrumb.length > 0) {
            const last = _discoveryBreadcrumb[_discoveryBreadcrumb.length - 1];
            if (last === _pendingCrumbNode) {
                _discoveryBreadcrumb.pop();
                _renderDiscoveryBreadcrumb();
                _updateDiscoverySaveBtn();
            }
        }
        _pendingCrumbNode = null;
        const label = _discoveryBreadcrumb.length > 0
            ? escHtml((_discoveryBreadcrumb[_discoveryBreadcrumb.length - 1].label || _discoveryBreadcrumb[_discoveryBreadcrumb.length - 1].title || '').substring(0, 30))
            : '';
        body.innerHTML = `<div class="discovery-drawer-empty"><div style="font-size:24px;margin-bottom:8px">🔍</div><div style="font-size:13px">No related threads found</div>${label ? `<div style="font-size:11px;color:var(--text-muted);margin-top:4px">for "${label}"</div>` : ''}</div>`;
        return;
    }
    _pendingCrumbNode = null;
    let html = `<div style="font-size:12px;color:var(--text-muted);margin-bottom:10px">${results.length} thread${results.length !== 1 ? 's' : ''} found</div>`;
    html += results.slice(0, 25).map(r => {
        const thread = (_threadsCache || []).find(t => t.id === r.threadId);
        const domColor = thread ? (_DOMAIN_COLORS[_parseDomains(thread.domain)[0]] || '#6b7280') : '#6b7280';
        const sigCount = thread ? (thread.signal_count || 0) : 0;
        const safeTitle = escHtml(r.title.replace(/'/g, "\\'"));

        let chipsHtml = '';
        if (r.sharedEntities && r.sharedEntities.length) {
            chipsHtml = `<div class="disc-result-chips">${r.sharedEntities.slice(0, 6).map(e => {
                const safeVal = escHtml(e.name.replace(/'/g, "\\'"));
                const safeType = escHtml(e.type);
                return `<span class="disc-entity-chip" onclick="event.stopPropagation();_discoveryClickEntity('${safeType}','${safeVal}')">${_entIconMap[e.type] || '🔹'} ${escHtml(e.name)}</span>`;
            }).join('')}</div>`;
        }

        return `<div class="disc-result-card" style="border-left:3px solid ${domColor}" data-disc-tid="${r.threadId}" data-disc-title="${escHtml(r.title)}" onclick="_discoveryClickThread(${r.threadId},'${safeTitle}')">
            <div class="disc-result-title">${escHtml(r.title)}</div>
            <div class="disc-result-reason">${escHtml(r.reason)}</div>
            <div class="disc-result-meta">${_renderDomainBadges(r.domain || '', '11px')} <span>${sigCount} signals</span></div>
            ${chipsHtml}
        </div>`;
    }).join('');
    body.innerHTML = html;
}

// ── Discovery Click Handlers ──

function _showDiscoveryCtxMenu(event, threadId, title, breadcrumbIndex) {
    document.querySelectorAll('.sv-ctx-menu').forEach(m => m.remove());
    const isBreadcrumb = breadcrumbIndex !== undefined;
    const menu = document.createElement('div');
    menu.className = 'sv-ctx-menu';
    menu.style.cssText = `position:fixed;left:${event.clientX}px;top:${event.clientY}px;z-index:10001;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,0.5);min-width:200px;padding:4px 0;font-size:12px`;

    const itemStyle = 'padding:6px 12px;cursor:pointer;color:var(--text-secondary);display:flex;align-items:center;gap:6px';
    const items = [
        { icon: '📄', label: 'View thread detail', action: () => openThreadDetail(threadId) },
        { icon: '🔭', label: 'Find related threads', action: () => _discoveryNavigateTo({type:'thread',threadId,title:title||'',method:'entities'}) },
        { icon: '🔮', label: 'Highlight on board', action: () => _highlightThreadById(threadId, title) },
        { icon: '⛓', label: 'Add to chain', action: () => _addThreadToChainFromDiscovery(threadId, title) },
        null, // separator
        { icon: '🔍', label: 'Search existing signals', action: () => { document.getElementById('signals-search').value = title || ''; renderActiveSignalTab(); } },
        { icon: '📡', label: 'Search for new signals', action: () => _searchSignalsFor(title || '') },
    ];
    if (isBreadcrumb) {
        items.push(null); // separator
        items.push({ icon: '✕', label: 'Remove from trail', action: () => _discoveryRemoveCrumb(breadcrumbIndex), color: '#ef4444' });
    }

    const headerEl = document.createElement('div');
    headerEl.style.cssText = 'padding:4px 12px;font-size:9px;color:var(--text-muted);font-weight:600;border-bottom:1px solid var(--border);margin-bottom:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
    headerEl.textContent = title || '';
    menu.appendChild(headerEl);

    items.forEach(item => {
        if (!item) {
            const sep = document.createElement('div');
            sep.style.cssText = 'border-top:1px solid var(--border);margin:2px 0';
            menu.appendChild(sep);
            return;
        }
        const el = document.createElement('div');
        el.style.cssText = itemStyle;
        if (item.color) el.style.color = item.color;
        el.innerHTML = `${item.icon} ${escHtml(item.label)}`;
        el.onmouseenter = () => el.style.background = 'var(--bg-tertiary)';
        el.onmouseleave = () => el.style.background = '';
        el.onclick = () => { menu.remove(); item.action(); };
        menu.appendChild(el);
    });
    document.body.appendChild(menu);
    // Clamp to viewport
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
    setTimeout(() => document.addEventListener('click', function h() { menu.remove(); document.removeEventListener('click', h); }), 0);
}

function _highlightThreadById(threadId, title) {
    const key = _hlKey('thread', String(threadId));
    const existing = _boardHighlights.findIndex(h => h.key === key);
    if (existing !== -1) { _removeBoardHighlight(existing); return; }
    _addBoardHighlight({ kind: 'keyword', label: (title || '').substring(0, 25), icon: '🔮',
        threadIds: new Set([threadId]), key });
    if (_signalTab !== 'graph') switchSignalTab('graph');
    _showToast(`"${(title || '').substring(0, 30)}" highlighted on board`, 'success', 3000);
}

function _addThreadToChainFromDiscovery(threadId, title) {
    if (!_activeCausalPathId) {
        _showToast('No chain selected — switch to Chains tab and select one', 'info');
        return;
    }
    fetch(`/api/causal-paths/${_activeCausalPathId}`, { method: 'GET' }).catch(() => null);
    // Add thread to the active chain
    const path = (_causalPathsCache || []).find(p => p.id === _activeCausalPathId);
    if (path) {
        const ids = [...(path.thread_ids || []), threadId];
        fetch(`/api/causal-paths/${_activeCausalPathId}`, {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ thread_ids: ids })
        }).then(r => r.json()).then(d => {
            if (d.ok) {
                path.thread_ids = ids;
                _showToast(`Added "${title}" to chain`, 'success');
                if (_signalTab === 'causal') loadCausalView();
            }
        });
    } else {
        _showToast('Select a chain first', 'info');
    }
}

function _discoveryClickThread(threadId, title) {
    _discoveryNavigateTo({ type: 'thread', threadId, title: title || `Thread #${threadId}`, method: 'entities' });
    // Always open thread detail for context alongside the drawer
    openThreadDetail(threadId);
    // Also add board highlight if on graph tab
    if (_signalTab === 'graph') {
        _addBoardHighlight({ kind: 'keyword', label: (title || '').substring(0, 25), icon: '🔭',
            threadIds: new Set([threadId]), key: 'discovery:thread:' + threadId });
    }
}

function _discoveryClickEntity(entityType, entityValue) {
    _discoveryNavigateTo({ type: 'entity', entityType, entityValue, label: entityValue });
}

function _discoveryClickKeyword(text) {
    _discoveryNavigateTo({ type: 'keyword', query: text, label: text });
}

// ── Discovery Breadcrumb ──

function _renderDiscoveryBreadcrumb() {
    const el = document.getElementById('discovery-breadcrumb');
    if (!el || !_discoveryBreadcrumb.length) { if (el) el.innerHTML = ''; return; }
    // Entities (lightbulbs) are not threads and cannot be added to chains,
    // so they are filtered out of the visible breadcrumb trail.
    const visibleCrumbs = _discoveryBreadcrumb
        .map((node, i) => ({ node, originalIndex: i }))
        .filter(({ node }) => node.type !== 'entity');
    if (!visibleCrumbs.length) { el.innerHTML = ''; return; }
    const crumbs = visibleCrumbs.map(({ node, originalIndex }, vi) => {
        const isCurrent = originalIndex === _discoveryBreadcrumb.length - 1;
        let icon = '', label = '';
        if (node.type === 'thread') { icon = '📄'; label = (node.title || '').substring(0, 20); }
        else if (node.type === 'keyword') { icon = '🔍'; label = (node.label || node.query || '').substring(0, 20); }
        const cls = isCurrent ? 'disc-crumb current' : 'disc-crumb';
        let onclick = '';
        if (isCurrent && node.type === 'thread') {
            onclick = `onclick="openThreadDetail(${node.threadId})"`;
        } else if (isCurrent && node.type === 'keyword') {
            onclick = `onclick="_discoveryJumpTo(${originalIndex})"`;
        } else if (!isCurrent) {
            onclick = `onclick="_discoveryJumpTo(${originalIndex})"`;
        }
        const ctxmenu = node.type === 'thread' ? `data-ctx-tid="${node.threadId}" data-ctx-idx="${originalIndex}" data-ctx-title="${escHtml(node.title || '')}"` : '';
        return `<span class="${cls}" ${onclick} ${ctxmenu} title="${escHtml(node.title || node.label || '')}" style="cursor:pointer"><span class="disc-crumb-icon">${icon}</span>${escHtml(label)}</span>`;
    });
    el.innerHTML = crumbs.join('<span class="disc-crumb-sep">›</span>');
}

// Discovery right-click via event delegation (avoids inline handler quoting issues)
document.addEventListener('contextmenu', function(e) {
    // Breadcrumb crumbs
    const crumb = e.target.closest('[data-ctx-tid]');
    if (crumb) {
        e.preventDefault();
        _showDiscoveryCtxMenu(e, parseInt(crumb.dataset.ctxTid), crumb.dataset.ctxTitle || '', parseInt(crumb.dataset.ctxIdx));
        return;
    }
    // Result cards
    const card = e.target.closest('[data-disc-tid]');
    if (card) {
        e.preventDefault();
        _showDiscoveryCtxMenu(e, parseInt(card.dataset.discTid), card.dataset.discTitle || '');
        return;
    }
});

function _discoveryRemoveCrumb(index) {
    if (_discoveryBreadcrumb.length <= 1) { _clearDiscoveryTrail(); return; }
    _discoveryBreadcrumb.splice(index, 1);
    _renderDiscoveryBreadcrumb();
    _updateDiscoverySaveBtn();
    // Re-fetch for the new last crumb
    if (_discoveryBreadcrumb.length > 0) {
        _fetchDiscoveryResults(_discoveryBreadcrumb[_discoveryBreadcrumb.length - 1]);
    }
}

function _discoveryJumpTo(index) {
    _discoveryBreadcrumb = _discoveryBreadcrumb.slice(0, index + 1);
    _renderDiscoveryBreadcrumb();
    _updateDiscoverySaveBtn();
    _fetchDiscoveryResults(_discoveryBreadcrumb[_discoveryBreadcrumb.length - 1]);
}

// ── Save as Chain ──

function _updateDiscoverySaveBtn() {
    const btn = document.getElementById('discovery-save-chain-btn');
    if (!btn) return;
    const threadNodes = _discoveryBreadcrumb.filter(n => n.type === 'thread');
    btn.style.display = threadNodes.length >= 2 ? '' : 'none';
}

function _discoverySaveChain() {
    const threadNodes = _discoveryBreadcrumb.filter(n => n.type === 'thread');
    const threadIds = threadNodes.map(n => n.threadId);
    if (threadIds.length < 2) { _showToast('Need at least 2 threads in the trail', 'warn'); return; }
    _createChainFromThreads(threadIds);
}

// ===================== EXECUTION =====================

var _execData = { domains: {}, scan: {}, synthesis: {}, entities: {}, phase: 'idle', narrativeSearch: null, customSearches: [] };  // var: directly accessed from signals.js (separate script scope)
var _execExpandedDomains = new Set(); // track which domain cards the user has expanded  // var: accessed from board.js (separate script scope)
let _narrativeSearchReader = null; // persisted SSE reader for narrative search
const _SIG_SOURCE_ICONS = { fred: '📈', google_news: '📰', reddit: '💬', hackernews: '🟧' };
const _SIG_SOURCE_LABELS = { fred: 'FRED API', google_news: 'Google News', reddit: 'Reddit', hackernews: 'Hacker News' };

function runSignalScan() {
    const btn = document.getElementById('signals-scan-btn');
    const statusEl = document.getElementById('signals-scan-status');
    const statusText = document.getElementById('scan-status-text');
    btn.classList.add('scanning');
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg> Scanning...';
    statusEl.style.display = 'block';
    statusText.textContent = 'Starting scan...';

    // Use active domains from unified domain chips
    const selectedDomains = [..._activeDomains];
    if (!selectedDomains.length) { _showToast('Select at least one domain', 'warn'); return; }

    // Reset execution data
    _execData = { domains: {}, scan: {}, synthesis: {}, entities: {}, phase: 'collecting', startedAt: new Date().toISOString(), narrativeSearch: null };
    _execExpandedDomains.clear();

    // Switch to execution tab and render (setTimeout ensures DOM has updated)
    switchSignalTab('execution');
    setTimeout(() => _renderExecutionDetail(), 0);

    fetch('/api/signals/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domains: selectedDomains })
    }).then(response => {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        function read() {
            reader.read().then(({ done, value }) => {
                if (done) {
                    _finishScan();
                    return;
                }
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const ev = JSON.parse(line.substring(6));
                        _handleScanEvent(ev);
                    } catch (e) {}
                }
                read();
            }).catch(() => _finishScan());
        }
        read();
    }).catch(() => _finishScan());
}

function _handleScanEvent(ev) {
    const statusText = document.getElementById('scan-status-text');

    // Accumulate structured data
    switch (ev.type) {
        case 'domain_start':
            _execData.domains[ev.domain] = { status: 'running', sources: {}, count: 0 };
            statusText.textContent = `Scanning ${_DOMAIN_LABELS[ev.domain] || ev.domain}...`;
            break;
        case 'source_start': {
            const dom = _execData.domains[ev.domain] || (_execData.domains[ev.domain] = { status: 'running', sources: {}, count: 0 });
            dom.sources[ev.source] = { status: 'running', count: 0, queries: ev.queries || [] };
            break;
        }
        case 'source_done': {
            const dom = _execData.domains[ev.domain];
            if (dom && dom.sources[ev.source]) {
                dom.sources[ev.source].status = 'done';
                dom.sources[ev.source].count = ev.count || 0;
                dom.sources[ev.source].queries = ev.queries || dom.sources[ev.source].queries;
            }
            break;
        }
        case 'domain_done': {
            const dom = _execData.domains[ev.domain];
            if (dom) { dom.status = 'done'; dom.count = ev.count || 0; }
            const done = Object.values(_execData.domains).filter(d => d.status === 'done').length;
            const total = Object.keys(_execData.domains).length;
            statusText.textContent = `Collected ${done}/${total} domains`;
            break;
        }
        case 'scan_complete':
            _execData.scan = { total_collected: ev.total_collected, new_inserted: ev.new_inserted };
            _execData.phase = 'synthesizing';
            statusText.textContent = `${ev.total_collected} signals (${ev.new_inserted} new)`;
            break;
        case 'status':
            statusText.textContent = ev.text;
            break;
        case 'synthesize_start':
            _execData.synthesis.status = 'running';
            _execData.synthesis.signal_count = ev.signal_count;
            _execData.synthesis.existing_threads = ev.existing_threads;
            statusText.textContent = 'Detecting threads...';
            break;
        case 'new_thread':
            if (!_execData.synthesis.new_threads) _execData.synthesis.new_threads = [];
            _execData.synthesis.new_threads.push({ title: ev.title, signal_count: ev.signal_count });
            break;
        case 'assignments_done':
            _execData.synthesis.assigned = ev.assigned;
            _execData.synthesis.threads_updated = ev.threads_updated;
            break;
        case 'synthesize_complete':
            _execData.synthesis.status = 'done';
            break;
        case 'enrich_start':
            if (!_execData.enrich) _execData.enrich = {};
            _execData.enrich.status = 'running';
            _execData.enrich.total = ev.count;
            _execData.enrich.enriched = 0;
            _execData.phase = 'enriching';
            statusText.textContent = `Fetching ${ev.count} articles...`;
            break;
        case 'enrich_progress':
            if (_execData.enrich) {
                _execData.enrich.enriched = ev.enriched;
                statusText.textContent = `Articles: ${ev.enriched}/${_execData.enrich.total}`;
            }
            break;
        case 'enrich_complete':
            if (!_execData.enrich) _execData.enrich = {};
            _execData.enrich.status = 'done';
            _execData.enrich.enriched = ev.enriched;
            _execData.enrich.total = ev.total;
            break;
        case 'enrich_skip':
            if (!_execData.enrich) _execData.enrich = {};
            _execData.enrich.status = 'skipped';
            break;
        case 'entities_start':
            _execData.entities.status = 'running';
            _execData.entities.signal_count = ev.signal_count;
            _execData.phase = 'entities';
            statusText.textContent = 'Extracting entities...';
            break;
        case 'entities_complete':
            _execData.entities.status = 'done';
            _execData.entities.count = ev.count;
            break;
        case 'threads_ready':
            _execData.phase = 'complete';
            statusText.textContent = 'Scan complete';
            break;
        case 'error':
        case 'synth_error':
            statusText.textContent = ev.text || 'Error';
            statusText.style.color = 'var(--red)';
            break;
    }

    // Live-update the execution tab
    _renderExecutionDetail();
}

function _renderExecutionDetail() {
    const container = document.getElementById('sig-tab-execution');
    if (!container) return;

    try { _renderExecutionDetailInner(container); }
    catch (e) {
        console.error('[exec] Render error:', e);
        container.innerHTML = '<div style="padding:20px;color:var(--red)">Execution render error: ' + e.message + '</div>';
    }
}

function _renderExecutionDetailInner(container) {
    const d = _execData;
    const phase = d.phase || 'idle';
    const phaseLabels = { collecting: 'Collecting Signals', synthesizing: 'Detecting Threads', enriching: 'Fetching Articles', entities: 'Extracting Entities', complete: 'Complete' };

    // Header with phase indicator
    let html = `<div style="margin-bottom:16px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
            <span style="font-size:18px;font-weight:800;color:var(--text-primary)">Execution Log</span>
            <span class="exec-step-badge ${phase === 'complete' ? 'done' : 'running'}">${phaseLabels[phase] || phase}</span>
        </div>
        <div style="font-size:10px;color:var(--text-muted)">${d.startedAt ? new Date(d.startedAt).toLocaleString() : ''}</div>
    </div>`;

    // Phase 1: Collection — one step per domain, expandable to show sources+queries
    html += `<div class="exec-step open">
        <div class="exec-step-header" onclick="this.parentElement.classList.toggle('open')">
            <div class="exec-step-icon" style="background:rgba(59,130,246,0.15)">📡</div>
            <div class="exec-step-info">
                <div class="exec-step-title">Signal Collection</div>
                <div class="exec-step-subtitle">${Object.keys(d.domains).length} domains · ${d.scan.total_collected || '...'} signals collected · ${d.scan.new_inserted ?? '...'} new</div>
            </div>
            <span class="exec-step-badge ${d.scan.total_collected !== undefined ? 'done' : 'running'}">${d.scan.total_collected !== undefined ? 'Done' : 'Running'}</span>
        </div>
        <div class="exec-step-body" style="padding-top:8px">`;

    for (const [dom, domData] of Object.entries(d.domains)) {
        const domLabel = _DOMAIN_LABELS[dom] || dom;
        const domColor = _DOMAIN_COLORS[dom] || '#6b7280';
        const domOpen = _execExpandedDomains.has(dom) ? ' open' : '';
        html += `<div class="exec-step${domOpen}" style="margin-bottom:6px" data-domain="${escHtml(dom)}">
            <div class="exec-step-header" onclick="event.stopPropagation();_toggleExecDomain('${escHtml(dom)}')" style="padding:8px 12px;cursor:pointer">
                <span class="sig-domain-dot" style="background:${domColor};width:10px;height:10px"></span>
                <div class="exec-step-info">
                    <div class="exec-step-title" style="font-size:11px">${escHtml(domLabel)}</div>
                </div>
                <span style="font-size:10px;color:var(--text-muted);font-weight:600">${domData.count} signals</span>
                <span class="exec-step-badge ${domData.status === 'done' ? 'done' : 'running'}" style="font-size:9px">${domData.status === 'done' ? '✓' : '...'}</span>
            </div>
            <div class="exec-step-body">`;

        for (const [src, srcData] of Object.entries(domData.sources || {})) {
            const srcIcon = _SIG_SOURCE_ICONS[src] || '🔗';
            const srcLabel = _SIG_SOURCE_LABELS[src] || src;
            html += `<div class="exec-source-row">
                <span class="exec-source-icon" style="background:var(--bg-tertiary)">${srcIcon}</span>
                <div style="flex:1;min-width:0">
                    <div style="font-size:11px;font-weight:600;color:var(--text-primary)">${escHtml(srcLabel)}</div>
                    <div style="margin-top:3px">${(srcData.queries || []).map(q => `<span class="exec-query-chip">${escHtml(q)}</span>`).join('')}</div>
                </div>
                <span style="font-size:11px;font-weight:700;color:${srcData.status === 'done' ? 'var(--green)' : 'var(--text-muted)'}">${srcData.count ?? '...'}</span>
            </div>`;
        }
        html += `</div></div>`;
    }
    html += `</div></div>`;

    // Arrow
    html += `<div class="exec-arrow">↓</div>`;

    // Phase 2: Dedup + Store
    html += `<div class="exec-step ${d.scan.new_inserted !== undefined ? 'open' : ''}">
        <div class="exec-step-header" onclick="this.parentElement.classList.toggle('open')">
            <div class="exec-step-icon" style="background:rgba(168,85,247,0.15)">🧹</div>
            <div class="exec-step-info">
                <div class="exec-step-title">Deduplication & Storage</div>
                <div class="exec-step-subtitle">${d.scan.total_collected ?? '...'} collected → ${d.scan.new_inserted ?? '...'} new (${d.scan.total_collected && d.scan.new_inserted !== undefined ? d.scan.total_collected - d.scan.new_inserted : '...'} duplicates skipped)</div>
            </div>
            <span class="exec-step-badge ${d.scan.new_inserted !== undefined ? 'done' : 'running'}">${d.scan.new_inserted !== undefined ? 'Done' : '...'}</span>
        </div>
        <div class="exec-step-body" style="padding-top:8px">
            <div style="font-size:11px;color:var(--text-secondary)">Signals are deduplicated via SHA-256 content hash (source + URL + title). Duplicates from previous scans are automatically skipped.</div>
        </div>
    </div>`;

    html += `<div class="exec-arrow">↓</div>`;

    // Phase 3: LLM Synthesis
    const synth = d.synthesis || {};
    html += `<div class="exec-step ${synth.status === 'done' ? 'open' : ''}">
        <div class="exec-step-header" onclick="this.parentElement.classList.toggle('open')">
            <div class="exec-step-icon" style="background:rgba(168,85,247,0.15)">🧠</div>
            <div class="exec-step-info">
                <div class="exec-step-title">LLM Thread Detection</div>
                <div class="exec-step-subtitle">${synth.signal_count || '...'} signals → ${(synth.new_threads || []).length} new threads, ${synth.assigned || 0} assigned to existing</div>
            </div>
            <span class="exec-step-badge ${synth.status === 'done' ? 'done' : synth.status === 'running' ? 'running' : ''}">${synth.status === 'done' ? 'Done' : synth.status === 'running' ? 'Running' : '...'}</span>
        </div>
        <div class="exec-step-body" style="padding-top:8px">
            <div style="font-size:11px;color:var(--text-secondary);margin-bottom:8px">FAST_CHAIN assigns each signal to an existing thread or groups unmatched signals into new threads (min 2 signals per thread).</div>`;

    if (synth.new_threads && synth.new_threads.length) {
        html += `<div style="font-size:10px;font-weight:700;color:var(--text-muted);margin-bottom:4px">NEW THREADS DETECTED</div>`;
        for (const t of synth.new_threads) {
            html += `<div style="padding:6px 0;border-bottom:1px solid var(--border);font-size:11px"><strong>${escHtml(t.title)}</strong> <span style="color:var(--text-muted)">(${t.signal_count} signals)</span></div>`;
        }
    }
    if (synth.assigned) {
        html += `<div style="margin-top:8px;font-size:11px;color:var(--text-secondary)">${synth.assigned} signals matched to ${synth.threads_updated || 0} existing threads (summaries updated via LLM)</div>`;
    }
    html += `</div></div>`;

    html += `<div class="exec-arrow">↓</div>`;

    // Phase 3.5: Article Enrichment
    const enr = d.enrich || {};
    html += `<div class="exec-step ${enr.status === 'done' ? 'open' : ''}">
        <div class="exec-step-header" onclick="this.parentElement.classList.toggle('open')">
            <div class="exec-step-icon" style="background:rgba(234,179,8,0.15)">📄</div>
            <div class="exec-step-info">
                <div class="exec-step-title">Article Text Enrichment</div>
                <div class="exec-step-subtitle">${enr.status === 'skipped' ? 'All signals already enriched' : `${enr.enriched ?? '...'} / ${enr.total ?? '...'} articles fetched via trafilatura`}</div>
            </div>
            <span class="exec-step-badge ${enr.status === 'done' ? 'done' : enr.status === 'skipped' ? 'done' : enr.status === 'running' ? 'running' : ''}">${enr.status === 'done' || enr.status === 'skipped' ? 'Done' : enr.status === 'running' ? 'Running' : '...'}</span>
        </div>
        <div class="exec-step-body" style="padding-top:8px">
            <div style="font-size:11px;color:var(--text-secondary)">Fetches full article text (up to 4,000 chars) for signals assigned to threads. Uses trafilatura for clean extraction (strips nav, ads, footers). Only fetches articles with missing or short body text.</div>
        </div>
    </div>`;

    html += `<div class="exec-arrow">↓</div>`;

    // Phase 4: Entity Extraction
    const ent = d.entities || {};
    html += `<div class="exec-step">
        <div class="exec-step-header" onclick="this.parentElement.classList.toggle('open')">
            <div class="exec-step-icon" style="background:rgba(34,197,94,0.15)">🏷️</div>
            <div class="exec-step-info">
                <div class="exec-step-title">Entity Extraction</div>
                <div class="exec-step-subtitle">${ent.count ?? '...'} entities extracted from enriched article text</div>
            </div>
            <span class="exec-step-badge ${ent.status === 'done' ? 'done' : ent.status === 'running' ? 'running' : ''}">${ent.status === 'done' ? 'Done' : ent.status === 'running' ? 'Running' : '...'}</span>
        </div>
        <div class="exec-step-body" style="padding-top:8px">
            <div style="font-size:11px;color:var(--text-secondary)">FAST_CHAIN extracts named entities (companies, sectors, geographies, people, regulations) from full article text. Company entities are fuzzy-matched against existing dossiers for cross-module linking.</div>
        </div>
    </div>`;

    // Re-detect execution (if running or completed)
    const rd = d.redetect;
    if (rd) {
        const rdPhase = rd.phase === 'complete' ? 'done' : 'running';
        html += `<div style="margin-top:24px;padding-top:16px;border-top:2px solid var(--accent)">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
                <span style="font-size:16px;font-weight:800;color:var(--text-primary)">🧠 Re-detect Threads</span>
                <span class="exec-step-badge ${rdPhase}">${rd.phase === 'complete' ? 'Complete' : 'Detecting...'}</span>
            </div>
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:12px">${rd.startedAt ? new Date(rd.startedAt).toLocaleString() : ''}</div>`;

        // Show batches
        for (const msg of (rd.batches || [])) {
            html += `<div style="padding:3px 0;font-size:10px;color:var(--text-muted)">${escHtml(msg)}</div>`;
        }

        // New threads found
        if (rd.newThreads && rd.newThreads.length) {
            html += `<div style="font-size:10px;font-weight:700;color:var(--green);margin-top:8px;margin-bottom:4px">NEW THREADS</div>`;
            for (const t of rd.newThreads) {
                html += `<div style="padding:4px 0;font-size:11px;border-bottom:1px solid var(--border)"><strong>${escHtml(t.title)}</strong> <span style="color:var(--text-muted)">(${t.signal_count} signals)</span></div>`;
            }
        }

        if (rd.phase === 'complete') {
            html += `<div style="padding:10px 12px;background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);border-radius:8px;font-size:11px;color:var(--green);font-weight:600;margin-top:8px">
                ✓ ${rd.newPatterns || 0} new threads · ${rd.assigned || 0} signals assigned
            </div>`;
        }
        html += `</div>`;
    }

    // Narrative search execution (if running or completed)
    const ns = d.narrativeSearch;
    if (ns) {
        const nsPhase = ns.phase === 'complete' ? 'done' : 'running';
        const stanceColors = { supporting: '#22c55e', contradicting: '#ef4444', neutral: '#6b7280' };
        html += `<div style="margin-top:24px;padding-top:16px;border-top:2px solid var(--purple)">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
                <span style="font-size:16px;font-weight:800;color:var(--text-primary)">📖 Narrative Search</span>
                <span class="exec-step-badge ${nsPhase}">${ns.phase === 'complete' ? 'Complete' : 'Searching...'}</span>
            </div>
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:12px">${ns.startedAt ? new Date(ns.startedAt).toLocaleString() : ''}</div>`;

        // Render each query as a collapsible step
        for (const q of (ns.queries || [])) {
            const qStatus = q.found > 0 ? 'done' : (ns.phase === 'complete' ? 'done' : 'running');
            html += `<div class="exec-step" style="margin-bottom:6px">
                <div class="exec-step-header" onclick="this.parentElement.classList.toggle('open')" style="padding:8px 12px;cursor:pointer">
                    <div class="exec-step-icon" style="background:rgba(168,85,247,0.15)">🔍</div>
                    <div class="exec-step-info">
                        <div class="exec-step-title" style="font-size:11px">${escHtml(q.query)}</div>
                    </div>
                    <span style="font-size:10px;color:var(--text-muted);font-weight:600">${q.found} results</span>
                    <span class="exec-step-badge ${qStatus}" style="font-size:9px">${qStatus === 'done' ? '✓' : '...'}</span>
                </div>
                <div class="exec-step-body" style="padding:6px 12px">
                    ${q.signals.map(s => {
                        const c = stanceColors[s.stance] || '#6b7280';
                        return `<div style="padding:2px 0;font-size:10px;color:var(--text-muted)"><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${c};margin-right:4px"></span>${escHtml(s.title)} <span style="color:${c};font-size:9px">${s.stance}</span></div>`;
                    }).join('')}
                </div>
            </div>`;
        }

        if (ns.phase === 'complete') {
            html += `<div style="padding:10px 12px;background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);border-radius:8px;font-size:11px;color:var(--green);font-weight:600;margin-top:8px">
                ✓ ${ns.totalFound} signals found · ${ns.totalClassified} classified
            </div>`;
        }
        html += `</div>`;
    }

    // Custom Searches section
    const cs = d.customSearches || [];
    if (cs.length) {
        html += `<div style="margin-top:24px;padding-top:16px;border-top:2px solid #06b6d4">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
                <span style="font-size:16px;font-weight:800;color:var(--text-primary)">📡 Custom Searches</span>
                <span style="font-size:10px;color:var(--text-muted)">${cs.length} quer${cs.length === 1 ? 'y' : 'ies'}</span>
            </div>`;
        for (const s of cs.slice().reverse()) {
            const isDone = s.status === 'done';
            const isErr = s.status === 'error';
            const badge = isDone ? 'done' : isErr ? '' : 'running';
            const badgeText = isDone ? `${s.total_found} found · ${s.new_inserted} new` : isErr ? 'Error' : 'Searching...';
            const badgeColor = isErr ? 'background:rgba(239,68,68,0.15);color:#ef4444' : '';
            html += `<div class="exec-step" style="margin-bottom:6px">
                <div class="exec-step-header" onclick="this.parentElement.classList.toggle('open')" style="padding:8px 12px;cursor:pointer">
                    <div class="exec-step-icon" style="background:rgba(6,182,212,0.15)">🔍</div>
                    <div class="exec-step-info">
                        <div class="exec-step-title" style="font-size:11px">${escHtml(s.query)}</div>
                        <div style="font-size:9px;color:var(--text-muted)">${_timeAgo(s.startedAt)}</div>
                    </div>
                    <span class="exec-step-badge ${badge}" style="${badgeColor}">${badgeText}</span>
                </div>
                <div class="exec-step-body" style="padding-top:6px">`;
            if (isDone && s.audit && s.audit.length) {
                for (const a of s.audit) {
                    const srcIcon = a.source.includes('Google') ? '📰' : a.source.includes('DDG') ? '📰' : a.source.includes('Hacker') ? '🟧' : a.source.includes('Reddit') ? '💬' : a.source.includes('Gov') ? '🏛️' : a.source.includes('FRED') ? '📈' : '🔍';
                    html += `<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:10px;color:var(--text-secondary)">
                        <span>${srcIcon} ${escHtml(a.source)}</span>
                        <span style="color:var(--text-muted)">${a.new || 0} new${a.error ? ' <span style="color:#ef4444">⚠</span>' : ''}</span>
                    </div>`;
                }
            }
            html += `</div></div>`;
        }
        html += `</div>`;
    }

    container.innerHTML = `<div style="padding:12px">${html}</div>`;
}

function _finishScan() {
    const btn = document.getElementById('signals-scan-btn');
    btn.classList.remove('scanning');
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg> Scan Now';
    _renderExecutionDetail();
    loadSignals();
    loadSignalFreshness();
    setTimeout(() => switchSignalTab('threads'), 1500);
}

function runResynthesize() {
    const btn = document.getElementById('signals-resynth-btn');
    const statusEl = document.getElementById('signals-scan-status');
    const statusText = document.getElementById('scan-status-text');
    btn.disabled = true;
    btn.textContent = '🧠 Detecting...';
    btn.style.color = 'var(--accent)';
    btn.style.borderColor = 'var(--accent)';
    statusEl.style.display = 'block';
    statusText.textContent = 'Re-detecting threads...';

    // Initialize redetect execution state
    _execData.redetect = { phase: 'running', startedAt: new Date().toISOString(), batches: [], newThreads: [], assigned: 0 };
    switchSignalTab('execution');
    _renderExecutionDetail();

    fetch('/api/signals/resynthesize', { method: 'POST' })
        .then(response => {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            function read() {
                reader.read().then(({ done, value }) => {
                    if (done) { _finishResynth(); return; }
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();
                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        try {
                            const ev = JSON.parse(line.substring(6));
                            const rd = _execData.redetect;
                            if (ev.type === 'status') { statusText.textContent = ev.text; rd.batches.push(ev.text); }
                            else if (ev.type === 'new_thread') { statusText.textContent = `New thread: ${ev.title}`; statusText.style.color = 'var(--green)'; rd.newThreads.push(ev); }
                            else if (ev.type === 'resynth_complete') { statusText.textContent = `✓ ${ev.new_patterns} new threads, ${ev.assigned} signals assigned`; statusText.style.color = 'var(--green)'; rd.phase = 'complete'; rd.assigned = ev.assigned; rd.newPatterns = ev.new_patterns; }
                            _renderExecutionDetail();
                        } catch (e) {}
                    }
                    read();
                }).catch(() => _finishResynth());
            }
            read();
        })
        .catch(() => _finishResynth());
}

function _finishResynth() {
    const btn = document.getElementById('signals-resynth-btn');
    btn.disabled = false;
    btn.textContent = '🧠 Re-detect Threads';
    btn.style.color = '';
    btn.style.borderColor = '';
    loadSignals();
    loadSignalFreshness();
    if (_signalTab === 'graph') loadBoard();
}

