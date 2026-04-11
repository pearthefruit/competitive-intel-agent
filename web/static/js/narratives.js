// Narratives — extracted from base.html (Phase 2 refactor)
// Shared state (var = window-level, written by signals/board/brainstorm code):
//   _activeNarrativeId, _selectedThreadsForNarrative
// Dependencies (function declarations on window):
//   switchSignalTab, _showToast, _showConfirm, _showInlineInput, escHtml
//   loadThreads, closeSignalDetail, _threadsCache

// ===================== NARRATIVES =====================

let _narrativesCache = [];
var _activeNarrativeId = null;           // var: read/written from board and brainstorm code
var _selectedThreadsForNarrative = new Set(); // var: read/written from signals/threads/board code

function _toggleThreadForNarrative(threadId) {
    if (_selectedThreadsForNarrative.has(threadId)) _selectedThreadsForNarrative.delete(threadId);
    else _selectedThreadsForNarrative.add(threadId);
    // Update checkbox visuals without full re-render
    document.querySelectorAll(`.thread-card[data-id="${threadId}"] .sig-card-select`).forEach(el => {
        el.classList.toggle('checked', _selectedThreadsForNarrative.has(threadId));
    });
    _updateSelectionBar();
}

function _createNarrativeFromThreads() {
    const ids = [..._selectedThreadsForNarrative];
    const threads = ids.map(id => _threadsCache.find(t => t.id === id)).filter(Boolean);
    const titles = threads.map(t => t.title).join('; ');

    // Pre-fill the modal with a thesis derived from the selected threads
    document.getElementById('narrative-modal').style.display = 'flex';
    document.getElementById('narrative-thesis').value = '';
    document.getElementById('narrative-reasoning').value = 'Based on these threads: ' + titles;
    document.getElementById('narrative-thesis').focus();

    // Store thread IDs so we can link them after creation
    window._pendingNarrativeThreadIds = ids;
}


let _hypothesesCache = [];
let _expandedHypothesisId = null;
let _hypRelatedCache = {}; // hypId -> related hypotheses array

function loadNarratives() {
    Promise.all([
        fetch('/api/narratives').then(r => r.json()),
        fetch('/api/hypotheses?status=captured').then(r => r.json()),
    ]).then(([narrData, hypData]) => {
        _narrativesCache = narrData.narratives || [];
        _hypothesesCache = hypData.hypotheses || [];
        renderNarrativesList();
    });
}

function renderNarrativesList() {
    const container = document.getElementById('narratives-list');
    if (!container) return;
    let narrativesHtml = '';
    if (!_narrativesCache.length && !_hypothesesCache.length) {
        container.innerHTML = `<div class="signals-empty" style="display:flex">
            <div style="font-size:32px;margin-bottom:12px">📖</div>
            <div>No narratives yet</div>
            <div style="color:var(--text-muted);font-size:12px;margin-top:6px">Create a narrative to test a hypothesis with targeted evidence gathering.</div>
        </div>`;
        return;
    }
    const nFilter = (document.getElementById('signals-search')?.value || '').toLowerCase();
    const filteredNarratives = nFilter
        ? _narrativesCache.filter(n => (n.title || '').toLowerCase().includes(nFilter) || (n.thesis || '').toLowerCase().includes(nFilter))
        : _narrativesCache;
    narrativesHtml = filteredNarratives.map(n => {
        const ev = n.evidence || {};
        const sup = ev.supporting || 0;
        const con = ev.contradicting || 0;
        const neu = ev.neutral || 0;
        const total = sup + con + neu;
        const badge = n.status === 'validated' ? 'validated' : n.status === 'disproven' ? 'disproven' : 'active';
        return `<div class="narrative-card ${n.id === _activeNarrativeId ? 'active' : ''}" onclick="openNarrativeDetail(${n.id})">
            <div class="narrative-card-title">${escHtml(n.title)}</div>
            <div class="narrative-card-thesis">${escHtml(n.thesis)}</div>
            <div class="narrative-card-meta">
                <span class="narrative-badge narrative-badge-${badge}">${badge}</span>
                <span>${n.thread_count || 0} threads</span>
                <span>${n.signal_count || 0} signals</span>
                ${total > 0 ? `<div class="narrative-evidence-bar">
                    ${sup > 0 ? `<div class="supporting" style="width:${sup/total*100}%"></div>` : ''}
                    ${neu > 0 ? `<div class="neutral" style="width:${neu/total*100}%"></div>` : ''}
                    ${con > 0 ? `<div class="contradicting" style="width:${con/total*100}%"></div>` : ''}
                </div>` : ''}
                ${n.confidence_score != null ? `<span>${n.confidence_score}%</span>` : ''}
            </div>
        </div>`;
    }).join('');

    // Concept overlap visualization (between narratives and hypothesis bank)
    if (_hypothesesCache.length >= 2) {
        narrativesHtml += `<div style="padding:12px;border-top:1px solid var(--border)">
            <div onclick="const b=document.getElementById('concept-overlap-body');b.style.display=b.style.display==='none'?'':'none'" style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;user-select:none">
                <div style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px">Concept Overlap</div>
                <span style="font-size:8px;color:var(--text-muted)">▾</span>
            </div>
            <div id="concept-overlap-body" style="margin-top:8px"></div>
        </div>`;
    }

    // Hypothesis bank section
    if (_hypothesesCache.length) {
        narrativesHtml += `<div style="padding:12px;border-top:1px solid var(--border)">
            <div style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Hypothesis Bank (${_hypothesesCache.length})</div>
            <div id="hypothesis-bank-list">${_renderHypothesisBank()}</div>
        </div>`;
    }

    container.innerHTML = narrativesHtml;

    // Load concept overlap visualization
    if (_hypothesesCache.length >= 2) {
        _loadConceptOverlap();
    }
}

function _promoteHypothesis(hypId, title, reasoning) {
    document.getElementById('narrative-modal').style.display = 'flex';
    document.getElementById('narrative-thesis').value = title;
    document.getElementById('narrative-reasoning').value = reasoning;
    document.getElementById('narrative-thesis').focus();
    window._pendingPromoteHypId = hypId;
}

function _dismissHypothesis(hypId) {
    fetch(`/api/hypotheses/${hypId}`, { method: 'DELETE' })
        .then(() => loadNarratives());
}

function _renderHypothesisBank() {
    const confColors = { high: 'var(--green)', medium: 'var(--accent)', low: 'var(--text-muted)' };
    return _hypothesesCache.map(h => {
        const isExpanded = _expandedHypothesisId === h.id;
        const threadCount = (h.source_thread_ids || []).length;
        const entityCount = (h.source_entities || []).length;
        const borderColor = confColors[h.confidence] || 'var(--border)';

        let expandedHtml = '';
        if (isExpanded) {
            // Full reasoning
            expandedHtml += `<div style="font-size:11px;color:var(--text-secondary);margin-top:8px;line-height:1.5;padding:8px 0;border-top:1px solid var(--border)">${_renderBrainstormLinks(h.reasoning || '')}</div>`;

            // Source threads
            const srcThreads = (h.source_thread_ids || []).map(tid => (_threadsCache || []).find(t => t.id === tid)).filter(Boolean);
            if (srcThreads.length) {
                expandedHtml += `<div style="margin-top:8px"><div style="font-size:9px;font-weight:700;color:var(--text-muted);margin-bottom:4px">SOURCE THREADS</div>`;
                expandedHtml += srcThreads.map(t => {
                    const dc = _DOMAIN_COLORS[t.domain] || '#6b7280';
                    return `<div onclick="switchSignalTab('graph');openThreadDetail(${t.id})" style="padding:4px 8px;margin-bottom:3px;background:var(--bg-secondary);border-radius:4px;border-left:2px solid ${dc};cursor:pointer;font-size:10px;color:var(--text-secondary);display:flex;justify-content:space-between;align-items:center">
                        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(t.title)}</span>
                        <span style="font-size:9px;color:var(--text-muted);flex-shrink:0;margin-left:6px">${t.signal_count || 0} sig</span>
                    </div>`;
                }).join('') + '</div>';
            }

            // Source entities
            const entities = h.source_entities || [];
            if (entities.length) {
                expandedHtml += `<div style="margin-top:8px"><div style="font-size:9px;font-weight:700;color:var(--text-muted);margin-bottom:4px">ENTITIES</div><div style="display:flex;flex-wrap:wrap;gap:3px">`;
                expandedHtml += entities.slice(0, 15).map(e => {
                    const name = e.name || e.entity_value || e;
                    const type = e.type || e.entity_type || 'concept';
                    const icon = _entIcon[type] || '🔹';
                    return `<span onclick="_brainstormConceptClick('${escHtml(String(name).replace(/'/g, "\\'"))}')" style="padding:2px 6px;border-radius:4px;font-size:9px;background:var(--bg-secondary);border:1px solid var(--border);color:var(--text-secondary);cursor:pointer;transition:border-color 0.15s" onmouseenter="this.style.borderColor='var(--accent)'" onmouseleave="this.style.borderColor='var(--border)'">${icon} ${escHtml(String(name))}</span>`;
                }).join('') + (entities.length > 15 ? `<span style="font-size:9px;color:var(--text-muted)">+${entities.length - 15} more</span>` : '') + '</div></div>';
            }

            // Related hypotheses (lazy-loaded)
            expandedHtml += `<div id="hyp-related-${h.id}" style="margin-top:8px"></div>`;

            // Action buttons
            expandedHtml += `<div style="display:flex;gap:4px;margin-top:10px;padding-top:8px;border-top:1px solid var(--border)">
                <button onclick="event.stopPropagation();_promoteHypothesis(${h.id}, '${escHtml(h.title.replace(/'/g, "\\'"))}', '${escHtml((h.reasoning || '').replace(/'/g, "\\'"))}')" style="padding:3px 10px;background:none;border:1px solid var(--purple);border-radius:4px;color:var(--purple);font-size:9px;font-weight:600;cursor:pointer">📖 Promote</button>
                <button onclick="event.stopPropagation();_showHypAssignDropdown(${h.id}, this)" style="padding:3px 10px;background:none;border:1px solid var(--accent);border-radius:4px;color:var(--accent);font-size:9px;font-weight:600;cursor:pointer">📎 Assign to...</button>
                <button onclick="event.stopPropagation();_dismissHypothesis(${h.id})" style="padding:3px 10px;background:none;border:1px solid var(--border);border-radius:4px;color:var(--text-muted);font-size:9px;cursor:pointer">Dismiss</button>
            </div>`;
        }

        return `<div onclick="_toggleHypothesisExpand(${h.id})" style="padding:8px 12px;margin-bottom:4px;background:var(--bg-tertiary);border-radius:6px;border-left:2px solid ${borderColor};cursor:pointer;transition:background 0.15s" onmouseenter="this.style.background='var(--bg-secondary)'" onmouseleave="this.style.background='var(--bg-tertiary)'">
            <div style="display:flex;justify-content:space-between;align-items:start;gap:8px">
                <div style="font-size:11px;font-weight:600;color:var(--text-primary);flex:1">${_renderBrainstormLinks(h.title)}</div>
                <span style="font-size:8px;padding:1px 5px;border-radius:3px;background:var(--bg-secondary);color:var(--text-muted);white-space:nowrap">${threadCount} threads · ${entityCount} entities</span>
            </div>
            ${isExpanded ? '' : `<div style="font-size:10px;color:var(--text-muted);margin-top:3px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${_renderBrainstormLinks(h.reasoning || '')}</div>`}
            ${isExpanded ? '' : `<div style="display:flex;gap:4px;margin-top:6px">
                <button onclick="event.stopPropagation();_promoteHypothesis(${h.id}, '${escHtml(h.title.replace(/'/g, "\\'"))}', '${escHtml((h.reasoning || '').replace(/'/g, "\\'"))}')" style="padding:2px 8px;background:none;border:1px solid var(--purple);border-radius:4px;color:var(--purple);font-size:9px;font-weight:600;cursor:pointer">📖 Promote</button>
                <button onclick="event.stopPropagation();_dismissHypothesis(${h.id})" style="padding:2px 8px;background:none;border:1px solid var(--border);border-radius:4px;color:var(--text-muted);font-size:9px;cursor:pointer">Dismiss</button>
            </div>`}
            ${expandedHtml}
        </div>`;
    }).join('');
}

function _toggleHypothesisExpand(hypId) {
    _expandedHypothesisId = _expandedHypothesisId === hypId ? null : hypId;
    const container = document.getElementById('hypothesis-bank-list');
    if (container) container.innerHTML = _renderHypothesisBank();
    // Lazy-load related hypotheses when expanding
    if (_expandedHypothesisId) {
        const h = _hypothesesCache.find(h => h.id === _expandedHypothesisId);
        if (h && !_hypRelatedCache[h.id]) {
            const relEl = document.getElementById(`hyp-related-${h.id}`);
            if (relEl) relEl.innerHTML = '<div style="font-size:9px;color:var(--text-muted)">Finding related hypotheses...</div>';
            fetch('/api/hypotheses/related', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ thread_ids: h.source_thread_ids || [] })
            }).then(r => r.json()).then(data => {
                const related = (data.hypotheses || []).filter(rh => rh.id !== h.id);
                _hypRelatedCache[h.id] = related;
                _renderHypRelated(h.id, related);
            });
        } else if (h && _hypRelatedCache[h.id]) {
            _renderHypRelated(h.id, _hypRelatedCache[h.id]);
        }
    }
}

function _renderHypRelated(hypId, related) {
    const el = document.getElementById(`hyp-related-${hypId}`);
    if (!el) return;
    if (!related.length) { el.innerHTML = ''; return; }
    el.innerHTML = `<div style="font-size:9px;font-weight:700;color:var(--text-muted);margin-bottom:4px">RELATED HYPOTHESES</div>`
        + related.slice(0, 5).map(rh => {
            const score = rh.relevance_score >= 3 ? 'strong' : 'weak';
            const color = score === 'strong' ? 'var(--accent)' : 'var(--text-muted)';
            return `<div style="padding:4px 8px;margin-bottom:3px;background:var(--bg-secondary);border-radius:4px;border-left:2px solid ${color};font-size:10px">
                <div style="display:flex;justify-content:space-between;align-items:start;gap:6px">
                    <span style="color:var(--text-secondary);font-weight:600">${escHtml(rh.title)}</span>
                    <span style="font-size:8px;color:${color};flex-shrink:0">${score}</span>
                </div>
                ${rh.match_reason ? `<div style="font-size:9px;color:var(--text-muted);margin-top:2px">${escHtml(rh.match_reason)}</div>` : ''}
            </div>`;
        }).join('');
}

let _conceptOverlapData = null;
let _conceptHighlightedHypIds = new Set();

function _loadConceptOverlap() {
    const body = document.getElementById('concept-overlap-body');
    if (!body) return;
    body.innerHTML = '<div style="font-size:9px;color:var(--text-muted)">Loading concept graph...</div>';
    fetch('/api/hypotheses/concepts')
        .then(r => r.json())
        .then(data => {
            _conceptOverlapData = data;
            _renderConceptOverlap(body, data);
        })
        .catch(() => { body.innerHTML = ''; });
}

function _renderConceptOverlap(container, data) {
    const concepts = data.concepts || [];
    const hypotheses = data.hypotheses || [];
    if (!concepts.length) { container.innerHTML = '<div style="font-size:9px;color:var(--text-muted)">No shared concepts found across hypotheses</div>'; return; }

    // Limit to top 20 concepts
    const topConcepts = concepts.slice(0, 20);
    const conceptNames = new Set(topConcepts.map(c => c.name));

    // Build HTML: concept pills at top, then hypothesis cards grouped by shared concepts
    let html = '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px">';
    topConcepts.forEach(c => {
        const count = c.hypothesis_ids.length;
        const isActive = _conceptHighlightedHypIds.size > 0 && c.hypothesis_ids.some(id => _conceptHighlightedHypIds.has(id));
        html += `<span onclick="_toggleConceptHighlight('${escHtml(c.name.replace(/'/g, "\\'"))}')" style="padding:3px 8px;border-radius:12px;font-size:9px;font-weight:600;cursor:pointer;transition:all 0.15s;${isActive ? 'background:rgba(168,85,247,0.2);border:1px solid rgba(168,85,247,0.4);color:var(--purple)' : 'background:var(--bg-secondary);border:1px solid var(--border);color:var(--text-secondary)'}" title="${count} hypotheses share this concept">${escHtml(c.name)} <span style="color:var(--text-muted);font-weight:400">${count}</span></span>`;
    });
    html += '</div>';

    // Hypothesis connection pairs — show hypotheses that share 2+ concepts
    const pairMap = {};
    topConcepts.forEach(c => {
        for (let i = 0; i < c.hypothesis_ids.length; i++) {
            for (let j = i + 1; j < c.hypothesis_ids.length; j++) {
                const key = [c.hypothesis_ids[i], c.hypothesis_ids[j]].sort().join('-');
                if (!pairMap[key]) pairMap[key] = { a: c.hypothesis_ids[i], b: c.hypothesis_ids[j], concepts: [] };
                pairMap[key].concepts.push(c.name);
            }
        }
    });
    const strongPairs = Object.values(pairMap).filter(p => p.concepts.length >= 2).sort((a, b) => b.concepts.length - a.concepts.length);

    if (strongPairs.length) {
        html += '<div style="font-size:9px;font-weight:700;color:var(--text-muted);margin:8px 0 4px">STRONG CONNECTIONS</div>';
        strongPairs.slice(0, 10).forEach(pair => {
            const hA = hypotheses.find(h => h.id === pair.a);
            const hB = hypotheses.find(h => h.id === pair.b);
            if (!hA || !hB) return;
            html += `<div style="padding:6px 8px;margin-bottom:4px;background:var(--bg-secondary);border-radius:6px;border-left:2px solid var(--purple)">
                <div style="display:flex;align-items:center;gap:6px;font-size:10px">
                    <span onclick="_toggleHypothesisExpand(${hA.id})" style="color:var(--text-primary);font-weight:600;cursor:pointer;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(hA.title)}</span>
                    <span style="color:var(--purple);font-size:9px;flex-shrink:0">⟷</span>
                    <span onclick="_toggleHypothesisExpand(${hB.id})" style="color:var(--text-primary);font-weight:600;cursor:pointer;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right">${escHtml(hB.title)}</span>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:3px;margin-top:4px;justify-content:center">
                    ${pair.concepts.map(c => `<span style="padding:1px 5px;border-radius:3px;font-size:8px;background:rgba(168,85,247,0.1);color:var(--purple)">${escHtml(c)}</span>`).join('')}
                </div>
                <div style="text-align:center;margin-top:4px">
                    <button onclick="event.stopPropagation();_mergeHypotheses([${hA.id}, ${hB.id}])" style="padding:2px 8px;background:none;border:1px solid var(--purple);border-radius:4px;color:var(--purple);font-size:8px;font-weight:600;cursor:pointer">Merge these</button>
                </div>
            </div>`;
        });
    }

    container.innerHTML = html;
}

function _toggleConceptHighlight(conceptName) {
    if (!_conceptOverlapData) return;
    const concept = _conceptOverlapData.concepts.find(c => c.name === conceptName);
    if (!concept) return;

    // Toggle: if all of this concept's hyps are already highlighted, clear; otherwise set
    const allHighlighted = concept.hypothesis_ids.every(id => _conceptHighlightedHypIds.has(id));
    if (allHighlighted) {
        concept.hypothesis_ids.forEach(id => _conceptHighlightedHypIds.delete(id));
    } else {
        concept.hypothesis_ids.forEach(id => _conceptHighlightedHypIds.add(id));
    }

    // Re-render concept overlap section
    const body = document.getElementById('concept-overlap-body');
    if (body) _renderConceptOverlap(body, _conceptOverlapData);

    // Highlight matching hypothesis cards in bank
    document.querySelectorAll('#hypothesis-bank-list > div').forEach((card, i) => {
        const h = _hypothesesCache[i];
        if (!h) return;
        if (_conceptHighlightedHypIds.size === 0) {
            card.style.opacity = '';
        } else {
            card.style.opacity = _conceptHighlightedHypIds.has(h.id) ? '' : '0.3';
        }
    });
}

function _showHypAssignDropdown(hypId, btnEl) {
    // Remove any existing dropdown
    document.querySelectorAll('.hyp-assign-dd').forEach(d => d.remove());
    if (!_narrativesCache.length) { _showToast('No narratives to assign to', 'warn'); return; }
    const dd = document.createElement('div');
    dd.className = 'hyp-assign-dd';
    dd.style.cssText = 'position:absolute;z-index:50;background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.4);max-height:200px;overflow-y:auto;min-width:200px';
    dd.innerHTML = _narrativesCache.map(n =>
        `<div onclick="event.stopPropagation();_assignHypToNarrative(${hypId}, ${n.id})" style="padding:6px 10px;font-size:10px;color:var(--text-secondary);cursor:pointer;border-bottom:1px solid var(--border);transition:background 0.1s" onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background=''">
            ${escHtml(n.title)}
        </div>`
    ).join('');
    btnEl.style.position = 'relative';
    btnEl.parentElement.style.position = 'relative';
    btnEl.parentElement.appendChild(dd);
    dd.style.bottom = '100%';
    dd.style.left = '0';
    dd.style.marginBottom = '4px';
    // Close on outside click
    setTimeout(() => {
        const close = (e) => { if (!dd.contains(e.target)) { dd.remove(); document.removeEventListener('click', close); } };
        document.addEventListener('click', close);
    }, 0);
}

function _assignHypToNarrative(hypId, narrativeId) {
    const h = _hypothesesCache.find(h => h.id === hypId);
    if (!h) return;
    document.querySelectorAll('.hyp-assign-dd').forEach(d => d.remove());
    fetch(`/api/narratives/${narrativeId}/add-subclaim`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ claim: h.title, hypothesis_id: hypId })
    }).then(r => r.json()).then(data => {
        if (data.ok) {
            _showToast('Hypothesis assigned as sub-claim', 'success');
            loadNarratives();
        } else {
            _showToast(data.error || 'Failed to assign', 'error');
        }
    });
}

function _mergeHypotheses(hypIds) {
    if (hypIds.length < 2) return;
    const hyps = hypIds.map(id => _hypothesesCache.find(h => h.id === id)).filter(Boolean);
    if (hyps.length < 2) return;

    // Show merge overlay
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.7);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    const modal = document.createElement('div');
    modal.style.cssText = 'background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:600px;width:90%;max-height:80vh;overflow-y:auto';

    modal.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
            <h3 style="font-size:14px;font-weight:700;color:var(--text-primary);margin:0">Merge ${hyps.length} Hypotheses</h3>
            <span onclick="this.closest('[style*=fixed]').remove()" style="cursor:pointer;color:var(--text-muted);font-size:16px">&times;</span>
        </div>
        <div style="font-size:10px;font-weight:700;color:var(--text-muted);margin-bottom:6px">SOURCE HYPOTHESES</div>
        ${hyps.map(h => `<div style="padding:6px 8px;margin-bottom:4px;background:var(--bg-tertiary);border-radius:4px;font-size:10px">
            <div style="font-weight:600;color:var(--text-primary)">${escHtml(h.title)}</div>
            <div style="color:var(--text-muted);margin-top:2px">${escHtml((h.reasoning || '').substring(0, 120))}${(h.reasoning || '').length > 120 ? '...' : ''}</div>
        </div>`).join('')}
        <div style="margin-top:12px;text-align:center;padding:12px;color:var(--text-muted);font-size:10px" id="merge-status">Generating merged hypothesis...</div>
        <div id="merge-result" style="display:none">
            <div style="font-size:10px;font-weight:700;color:var(--text-muted);margin-bottom:4px;margin-top:12px">MERGED RESULT</div>
            <input type="text" id="merge-title" style="width:100%;padding:8px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);font-size:12px;font-weight:600;box-sizing:border-box;margin-bottom:6px">
            <textarea id="merge-reasoning" rows="4" style="width:100%;padding:8px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-secondary);font-size:11px;box-sizing:border-box;resize:vertical"></textarea>
            <div style="display:flex;gap:8px;margin-top:12px;justify-content:flex-end">
                <button onclick="this.closest('[style*=fixed]').remove()" style="padding:6px 16px;background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;cursor:pointer">Cancel</button>
                <button id="merge-confirm-btn" style="padding:6px 16px;background:linear-gradient(135deg,var(--accent),var(--purple));border:none;border-radius:6px;color:#fff;font-size:11px;font-weight:600;cursor:pointer">Confirm Merge</button>
            </div>
        </div>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Call LLM to generate merged hypothesis
    fetch('/api/hypotheses/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hypothesis_ids: hypIds })
    }).then(r => r.json()).then(data => {
        if (data.error) {
            document.getElementById('merge-status').innerHTML = `<span style="color:var(--red)">${escHtml(data.error)}</span>`;
            return;
        }
        document.getElementById('merge-status').style.display = 'none';
        document.getElementById('merge-result').style.display = '';
        document.getElementById('merge-title').value = data.merged_hypothesis.title;
        document.getElementById('merge-reasoning').value = data.merged_hypothesis.reasoning;

        // Confirm button just refreshes — the merge already happened server-side
        document.getElementById('merge-confirm-btn').onclick = () => {
            overlay.remove();
            _showToast('Hypotheses merged', 'success');
            _hypRelatedCache = {}; // clear cache
            loadNarratives();
        };
    }).catch(() => {
        document.getElementById('merge-status').innerHTML = '<span style="color:var(--red)">Merge failed — check server</span>';
    });
}

function openNarrativeDetail(narrativeId) {
    _activeNarrativeId = narrativeId;
    renderNarrativesList();
    const detailBody = _showDetailPane('Narrative Detail');
    detailBody.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)">Loading narrative...</div>';

    fetch(`/api/narratives/${narrativeId}`)
        .then(r => r.json())
        .then(n => {
            if (n.error) { detailBody.innerHTML = `<div style="color:var(--red);padding:20px">${n.error}</div>`; return; }
            const ev = n.evidence || {};
            const sup = ev.supporting || 0;
            const con = ev.contradicting || 0;
            const neu = ev.neutral || 0;
            const total = sup + con + neu;
            const subClaims = n.sub_claims || [];
            const threads = n.threads || [];
            const queries = n.search_queries || [];

            detailBody.innerHTML = `
                <div style="padding:20px">
                    ${_editableTitle(n.title, '/api/narratives/' + n.id, 'title', 'loadNarratives()', '16px')}
                    <div style="font-size:12px;color:var(--text-secondary);line-height:1.5;margin-bottom:12px;padding:10px;background:var(--bg-tertiary);border-radius:8px;border-left:3px solid var(--accent)">${escHtml(n.thesis)}</div>
                    ${n.reasoning ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:12px"><strong>Reasoning:</strong> ${escHtml(n.reasoning)}</div>` : ''}

                    <!-- Evidence bar -->
                    ${total > 0 ? `<div style="margin-bottom:16px">
                        <div style="font-size:10px;font-weight:700;color:var(--text-muted);margin-bottom:4px">EVIDENCE</div>
                        <div style="display:flex;height:8px;border-radius:4px;overflow:hidden;background:var(--bg-tertiary);margin-bottom:4px">
                            ${sup > 0 ? `<div style="width:${sup/total*100}%;background:#22c55e"></div>` : ''}
                            ${neu > 0 ? `<div style="width:${neu/total*100}%;background:#6b7280"></div>` : ''}
                            ${con > 0 ? `<div style="width:${con/total*100}%;background:#ef4444"></div>` : ''}
                        </div>
                        <div style="display:flex;gap:12px;font-size:10px">
                            <span style="color:#22c55e">${sup} supporting</span>
                            <span style="color:#6b7280">${neu} neutral</span>
                            <span style="color:#ef4444">${con} contradicting</span>
                        </div>
                    </div>` : ''}

                    <!-- Sub-claims / Threads -->
                    <div style="font-size:10px;font-weight:700;color:var(--text-muted);margin-bottom:6px">SUB-CLAIMS (${subClaims.length})</div>
                    <div id="narrative-subclaims-${n.id}">
                    ${subClaims.map((sc, i) => {
                        const thread = threads[i];
                        const sigCount = thread ? thread.signal_count || 0 : 0;
                        const isGap = sigCount < 3;
                        const gapColor = sigCount === 0 ? '#ef4444' : sigCount < 3 ? '#eab308' : '#22c55e';
                        const gapLabel = sigCount === 0 ? 'No evidence' : sigCount < 3 ? 'Weak evidence' : `${sigCount} signals`;
                        const scQueries = (sc.queries || []).slice(0, 3);
                        return `<div id="subclaim-${n.id}-${i}" style="padding:10px 12px;background:var(--bg-tertiary);border-radius:8px;margin-bottom:6px;border-left:3px solid ${gapColor}">
                            <div style="display:flex;justify-content:space-between;align-items:start;gap:8px">
                                <div style="flex:1;min-width:0">
                                    <div style="font-size:11px;font-weight:600;color:var(--text-primary);line-height:1.3">${escHtml(sc.claim)}</div>
                                    <div style="font-size:10px;color:${gapColor};margin-top:3px;font-weight:600">${gapLabel} ${thread ? `· <span style="color:var(--accent);cursor:pointer;font-weight:400" onclick="openThreadDetail(${thread.id})">view thread →</span>` : ''}</div>
                                </div>
                                ${isGap ? `<button onclick="_searchSubClaim(${n.id}, ${i}, this)" style="flex-shrink:0;padding:3px 8px;background:none;border:1px solid var(--accent);border-radius:5px;color:var(--accent);font-size:9px;font-weight:600;cursor:pointer;white-space:nowrap">📡 Find evidence</button>` : ''}
                            </div>
                            <div id="subclaim-results-${n.id}-${i}" style="display:none;margin-top:6px"></div>
                        </div>`;
                    }).join('')}
                    </div>

                    <!-- Actions -->
                    <div style="display:flex;gap:8px;align-items:center;margin-top:12px">
                        <button onclick="_scanNarrativeInternal(${n.id})" id="narrative-scan-btn-${n.id}" style="padding:6px 14px;background:var(--bg-tertiary);border:1px solid var(--purple);border-radius:6px;color:var(--purple);font-size:11px;font-weight:600;cursor:pointer">🔍 Scan existing signals</button>
                        <button onclick="runNarrativeSearch(${n.id})" id="narrative-search-btn" style="padding:6px 14px;background:var(--bg-tertiary);border:1px solid var(--accent);border-radius:6px;color:var(--accent);font-size:11px;font-weight:600;cursor:pointer">📡 Search all external</button>
                        <button onclick="deleteNarrative(${n.id})" style="padding:6px 10px;background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:10px;cursor:pointer;margin-left:auto">Delete</button>
                    </div>
                    <div id="narrative-search-log" style="display:none;margin-top:12px;max-height:200px;overflow-y:auto;font-size:10px;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:8px"></div>
                </div>`;
        });
}

function _scanNarrativeInternal(narrativeId) {
    const btn = document.getElementById(`narrative-scan-btn-${narrativeId}`);
    if (btn) { btn.textContent = '🔍 Scanning...'; btn.disabled = true; }

    fetch(`/api/narratives/${narrativeId}/scan-internal`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (btn) { btn.disabled = false; btn.textContent = '🔍 Scan existing signals'; }
            if (!data.ok) {
                _showToast(data.error || 'Scan failed', 'error');
                return;
            }

            _showToast(`Found ${data.total_linked} new evidence links across ${data.sub_claims.length} sub-claims`, 'success');

            // Update sub-claim cards with results
            (data.sub_claims || []).forEach((sc, i) => {
                const el = document.getElementById(`subclaim-${narrativeId}-${i}`);
                const resultsEl = document.getElementById(`subclaim-results-${narrativeId}-${i}`);
                if (!resultsEl) return;

                if (sc.matches && sc.matches.length) {
                    const supCount = sc.matches.filter(m => m.stance === 'supporting').length;
                    const conCount = sc.matches.filter(m => m.stance === 'contradicting').length;
                    const stanceSummary = [
                        supCount ? `<span style="color:#22c55e">${supCount} supporting</span>` : '',
                        conCount ? `<span style="color:#ef4444">${conCount} contradicting</span>` : '',
                    ].filter(Boolean).join(' · ');
                    resultsEl.style.display = 'block';
                    resultsEl.innerHTML = `<div style="font-size:9px;font-weight:600;color:var(--text-muted);margin-bottom:4px">${sc.total} signals found${sc.linked > 0 ? ` · ${sc.linked} linked` : ''}${stanceSummary ? ` · ${stanceSummary}` : ''}</div>`
                        + sc.matches.slice(0, 5).map(m => {
                            const stanceColor = m.stance === 'supporting' ? '#22c55e' : m.stance === 'contradicting' ? '#ef4444' : '#6b7280';
                            const stanceIcon = m.stance === 'supporting' ? '▲' : m.stance === 'contradicting' ? '▼' : '●';
                            return `<div style="font-size:10px;color:var(--text-secondary);padding:2px 0;display:flex;gap:4px;align-items:start">
                                <span style="color:${stanceColor};flex-shrink:0;font-size:8px;margin-top:2px">${stanceIcon}</span>
                                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(m.title.substring(0, 60))}</span>
                            </div>`;
                        }).join('') + (sc.total > 5 ? `<div style="font-size:9px;color:var(--text-muted);padding-top:2px">+ ${sc.total - 5} more</div>` : '');

                    // Update the gap indicator color based on evidence balance
                    if (el) {
                        if (supCount > 0 && conCount === 0) el.style.borderLeftColor = '#22c55e';
                        else if (conCount > 0 && supCount === 0) el.style.borderLeftColor = '#ef4444';
                        else if (supCount > 0 && conCount > 0) el.style.borderLeftColor = '#eab308';
                        else if (sc.total > 0) el.style.borderLeftColor = '#6b7280';
                    }
                } else {
                    resultsEl.style.display = 'block';
                    resultsEl.innerHTML = `<div style="font-size:9px;color:var(--text-muted)">No existing signals match this sub-claim</div>`;
                }
            });

            // Refresh the narrative detail to update evidence bar + signal counts
            setTimeout(() => {
                openNarrativeDetail(narrativeId);
                loadSignals();
            }, 500);
        })
        .catch(() => {
            if (btn) { btn.disabled = false; btn.textContent = '🔍 Scan existing signals'; }
            _showToast('Internal scan failed — restart server', 'error');
        });
}

function _searchSubClaim(narrativeId, subClaimIndex, btn) {
    btn.textContent = '📡 Searching...';
    btn.disabled = true;

    // Get the narrative to find this sub-claim's queries
    fetch(`/api/narratives/${narrativeId}`)
        .then(r => r.json())
        .then(n => {
            const sc = (n.sub_claims || [])[subClaimIndex];
            if (!sc || !sc.queries || !sc.queries.length) {
                btn.textContent = '📡 Find evidence';
                btn.disabled = false;
                _showToast('No search queries for this sub-claim', 'warn');
                return;
            }

            // Run targeted search for this sub-claim's queries only
            return fetch(`/api/narratives/${narrativeId}/search`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ queries: sc.queries })
            });
        })
        .then(r => {
            if (!r) return;
            // SSE stream — read it
            const reader = r.body.getReader();
            const decoder = new TextDecoder();
            const resultsEl = document.getElementById(`subclaim-results-${narrativeId}-${subClaimIndex}`);
            if (resultsEl) { resultsEl.style.display = 'block'; resultsEl.innerHTML = '<div style="font-size:9px;color:var(--accent)">Searching external sources...</div>'; }

            let signals = [];
            function readChunk() {
                reader.read().then(({ done, value }) => {
                    if (done) {
                        btn.textContent = `✓ ${signals.length} found`;
                        btn.style.color = 'var(--green)';
                        btn.style.borderColor = 'var(--green)';
                        if (resultsEl && signals.length) {
                            resultsEl.innerHTML = signals.map(s =>
                                `<div style="font-size:10px;color:var(--text-secondary);padding:2px 0;display:flex;gap:4px;align-items:start">
                                    <span style="color:var(--accent);flex-shrink:0">●</span>
                                    <span>${escHtml(s.title)}</span>
                                    <span style="font-size:9px;color:var(--text-muted);flex-shrink:0">${s.stance}</span>
                                </div>`
                            ).join('');
                        } else if (resultsEl) {
                            resultsEl.innerHTML = '<div style="font-size:9px;color:var(--text-muted)">No new signals found</div>';
                        }
                        return;
                    }
                    const text = decoder.decode(value, { stream: true });
                    text.split('\n').forEach(line => {
                        if (!line.startsWith('data: ')) return;
                        try {
                            const ev = JSON.parse(line.substring(6));
                            if (ev.type === 'signal') signals.push(ev);
                        } catch {}
                    });
                    readChunk();
                });
            }
            readChunk();
        })
        .catch(() => {
            btn.textContent = '📡 Find evidence';
            btn.disabled = false;
            _showToast('Search failed', 'error');
        });
}

function openNarrativeModal() {
    document.getElementById('narrative-modal').style.display = 'flex';
    document.getElementById('narrative-thesis').focus();
}

function closeNarrativeModal() {
    document.getElementById('narrative-modal').style.display = 'none';
    document.getElementById('narrative-thesis').value = '';
    document.getElementById('narrative-reasoning').value = '';
    document.getElementById('narrative-create-status').style.display = 'none';
}

function createNarrative() {
    const thesis = document.getElementById('narrative-thesis').value.trim();
    const reasoning = document.getElementById('narrative-reasoning').value.trim();
    if (!thesis) return;

    const btn = document.getElementById('narrative-create-btn');
    const status = document.getElementById('narrative-create-status');
    btn.disabled = true;
    btn.textContent = 'Decomposing...';
    status.style.display = 'block';
    status.textContent = 'AI is breaking your hypothesis into testable sub-claims and generating search queries...';

    fetch('/api/narratives', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thesis, reasoning })
    })
    .then(r => r.json())
    .then(data => {
        btn.disabled = false;
        btn.textContent = 'Create & Decompose';
        if (data.ok) {
            // Link pre-selected threads to the new narrative
            const pendingIds = window._pendingNarrativeThreadIds || [];
            if (pendingIds.length) {
                Promise.all(pendingIds.map(tid =>
                    fetch(`/api/narratives/${data.narrative_id}/link-thread`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ thread_id: tid })
                    })
                )).then(() => {
                    _selectedThreadsForNarrative.clear();
                    window._pendingNarrativeThreadIds = null;
                    loadNarratives();
                    setTimeout(() => {
                        switchSignalTab('narratives');
                        openNarrativeDetail(data.narrative_id);
                        // Phase 1: auto-scan existing signals
                        setTimeout(() => _scanNarrativeInternal(data.narrative_id), 500);
                    }, 300);
                });
            } else {
                // Mark hypothesis as promoted if this came from the bank
                const promoteId = window._pendingPromoteHypId;
                if (promoteId) {
                    fetch(`/api/hypotheses/${promoteId}/promote`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ narrative_id: data.narrative_id })
                    });
                    window._pendingPromoteHypId = null;
                }
                loadNarratives();
                setTimeout(() => {
                    openNarrativeDetail(data.narrative_id);
                    // Phase 1: auto-scan existing signals
                    setTimeout(() => _scanNarrativeInternal(data.narrative_id), 500);
                }, 300);
            }
            closeNarrativeModal();
        } else {
            status.textContent = data.error || 'Failed to create narrative';
            status.style.color = 'var(--red)';
        }
    })
    .catch(() => {
        btn.disabled = false;
        btn.textContent = 'Create & Decompose';
        status.textContent = 'Network error';
        status.style.color = 'var(--red)';
    });
}

function runNarrativeSearch(narrativeId) {
    const btn = document.getElementById('narrative-search-btn');
    const log = document.getElementById('narrative-search-log');
    btn.disabled = true;
    btn.textContent = '🔍 Searching...';
    if (log) { log.style.display = 'block'; log.innerHTML = '<div style="color:var(--text-muted)">Starting targeted search...</div>'; }

    const stanceColors = { supporting: '#22c55e', contradicting: '#ef4444', neutral: '#6b7280' };

    // Initialize execution state for the Execution tab
    _execData.narrativeSearch = {
        narrativeId,
        phase: 'searching',
        startedAt: new Date().toISOString(),
        queries: [],
        signals: [],
        totalFound: 0,
        totalClassified: 0,
    };
    _renderExecutionDetail();

    fetch(`/api/narratives/${narrativeId}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    })
    .then(response => {
        _narrativeSearchReader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        function read() {
            _narrativeSearchReader.read().then(({ done, value }) => {
                if (done) { _narrativeSearchReader = null; _finishNarrativeSearch(narrativeId, btn); return; }
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const ev = JSON.parse(line.substring(6));
                        const ns = _execData.narrativeSearch;

                        if (ev.type === 'query_start') {
                            ns.queries.push({ query: ev.query, index: ev.index, total: ev.total, signals: [], found: 0 });
                            if (log) log.innerHTML += `<div style="margin-top:6px;font-weight:600;color:var(--text-secondary)">Query ${ev.index}/${ev.total}: <span style="color:var(--accent)">${escHtml(ev.query)}</span></div>`;
                            btn.textContent = `🔍 Query ${ev.index}/${ev.total}...`;
                        } else if (ev.type === 'signal') {
                            const c = stanceColors[ev.stance] || '#6b7280';
                            ns.signals.push(ev);
                            if (ns.queries.length) ns.queries[ns.queries.length - 1].signals.push(ev);
                            if (log) { log.innerHTML += `<div style="padding:2px 0;color:var(--text-muted)"><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${c};margin-right:4px"></span>${escHtml(ev.title)}</div>`; log.scrollTop = log.scrollHeight; }
                        } else if (ev.type === 'query_done') {
                            if (ns.queries.length) ns.queries[ns.queries.length - 1].found = ev.found;
                            if (log) log.innerHTML += `<div style="color:var(--text-muted);font-size:9px;padding-left:10px">${ev.found} results</div>`;
                        } else if (ev.type === 'complete') {
                            ns.phase = 'complete';
                            ns.totalFound = ev.total_found;
                            ns.totalClassified = ev.total_classified;
                            if (log) log.innerHTML += `<div style="margin-top:8px;font-weight:600;color:var(--green)">Done — ${ev.total_found} signals found, ${ev.total_classified} classified</div>`;
                        }
                        _renderExecutionDetail();
                    } catch (e) {}
                }
                read();
            }).catch(() => { _narrativeSearchReader = null; _finishNarrativeSearch(narrativeId, btn); });
        }
        read();
    })
    .catch(() => {
        btn.disabled = false;
        btn.textContent = '🔍 Run Search';
        if (log) log.innerHTML += '<div style="color:var(--red)">Network error</div>';
    });
}

function _finishNarrativeSearch(narrativeId, btn) {
    if (btn) { btn.disabled = false; btn.textContent = '🔍 Run Search'; }
    loadNarratives();
    // Only refresh detail if we're still on that narrative
    if (_activeNarrativeId === narrativeId) setTimeout(() => openNarrativeDetail(narrativeId), 500);
}

function deleteNarrative(narrativeId) {
    _showConfirm('Delete this narrative? Threads will be unlinked but not deleted.', () => {
        fetch(`/api/narratives/${narrativeId}`, { method: 'DELETE' })
            .then(r => r.json())
            .then(() => {
                _activeNarrativeId = null;
                loadNarratives();
                closeSignalDetail();
            });
    }, { danger: true, confirmText: 'Delete' });
}

