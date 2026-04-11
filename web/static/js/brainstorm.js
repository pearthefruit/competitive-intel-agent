// ===================== BRAINSTORM MODE =====================

function openBrainstormMode() {
    if (_selectedThreadIds.size < 2) return;
    const overlay = document.getElementById('brainstorm-overlay');
    const content = document.getElementById('brainstorm-content');
    const subtitle = document.getElementById('brainstorm-subtitle');
    overlay.classList.add('visible');

    const ids = [..._selectedThreadIds];
    const _findThread = id => _graphData?.nodes.find(n => n.id === id) || (_threadsCache || []).find(t => t.id === id);
    const threadNames = ids.map(id => {
        const n = _findThread(id);
        return n ? n.title : '';
    }).filter(Boolean);
    subtitle.textContent = threadNames.join(' × ');

    // Show selected threads while loading
    content.innerHTML = `
        <div class="brainstorm-threads">
            ${ids.map(id => {
                const n = _findThread(id);
                if (!n) return '';
                const bDoms = _parseDomains(n.domain);
                const domColor = _DOMAIN_COLORS[bDoms[0]] || '#6b7280';
                return `<div class="brainstorm-thread-card" style="border-left:3px solid ${domColor}">
                    <h3>${escHtml(n.title)}</h3>
                    <p>${escHtml(n.synthesis || 'No summary')}</p>
                    <div style="margin-top:6px">${_renderDomainBadges(n.domain)} <span style="font-size:10px;color:var(--text-muted)">${n.signal_count} signals</span></div>
                </div>`;
            }).join('')}
        </div>
        <div style="text-align:center;padding:24px;color:var(--text-muted)">
            <div style="font-size:18px;margin-bottom:8px">🧠</div>
            Generating hypotheses...
        </div>
    `;

    // Fetch related hypotheses and brainstorm in parallel, render only when both complete
    const relatedPromise = fetch('/api/hypotheses/related', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_ids: ids })
    }).then(r => r.json()).then(data => {
        window._brainstormRelatedHyps = data.hypotheses || [];
    }).catch(() => { window._brainstormRelatedHyps = []; });

    const brainstormPromise = fetch('/api/signals/brainstorm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_ids: ids })
    }).then(r => r.json());

    Promise.all([relatedPromise, brainstormPromise]).then(([_, result]) => {
        console.log('[brainstorm] Promise.all resolved, relatedHyps:', window._brainstormRelatedHyps?.length);
        if (result.error) {
            content.querySelector('div:last-child').innerHTML = `<div style="color:var(--red)">${escHtml(result.error)}</div>`;
            return;
        }
        _renderBrainstormResults(content, result, ids);
    })
    .catch(e => {
        content.querySelector('div:last-child').innerHTML = `<div style="color:var(--red)">Failed to generate hypotheses</div>`;
    });
}

function _renderBrainstormResults(container, result, threadIds) {
    // Keep the thread cards at the top, replace the loading section
    const threadCards = container.querySelector('.brainstorm-threads').outerHTML;

    let html = threadCards;

    // Connection summary + link label badges
    if (result.connection_summary) {
        const linkLabels = result.link_labels || [];
        html += `<div class="brainstorm-section">
            <div class="brainstorm-section-title">🔗 Connection</div>
            <div style="font-size:13px;color:var(--text-secondary);line-height:1.6;padding:12px 16px;background:var(--bg-secondary);border-radius:10px;border:1px solid var(--border)">
                ${_renderBrainstormLinks(result.connection_summary)}
                ${linkLabels.length ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:10px">${linkLabels.map(ll =>
                    `<span style="padding:3px 10px;background:rgba(168,85,247,0.15);border:1px solid rgba(168,85,247,0.3);border-radius:12px;font-size:10px;font-weight:600;color:var(--purple)">${escHtml(ll.label)}</span>`
                ).join('')}</div>` : ''}
            </div>
        </div>`;
    }

    // Hypotheses
    if (result.hypotheses && result.hypotheses.length) {
        html += `<div class="brainstorm-section">
            <div class="brainstorm-section-title">💡 Hypotheses</div>
            ${result.hypotheses.map((h, hi) => `
                <div class="hypothesis-card" id="hyp-card-${hi}">
                    <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:6px">
                        <h4>${_renderBrainstormLinks(h.title)}</h4>
                        <span class="hypothesis-confidence ${h.confidence || 'medium'}">${(h.confidence || 'medium').toUpperCase()}</span>
                    </div>
                    <p>${_renderBrainstormLinks(h.reasoning)}</p>
                    <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
                        ${h.investigate ? `<button onclick="_investigateInline(this, '${escHtml(h.investigate.replace(/'/g, "\\'"))}')" style="padding:4px 10px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:5px;color:var(--accent);font-size:10px;font-weight:600;cursor:pointer">🔍 Search signals</button>` : ''}
                        <button onclick="_createNarrativeFromHypothesis('${escHtml(h.title.replace(/'/g, "\\'"))}', '${escHtml(h.reasoning.replace(/'/g, "\\'"))}')" style="padding:4px 10px;background:var(--bg-tertiary);border:1px solid var(--purple);border-radius:5px;color:var(--purple);font-size:10px;font-weight:600;cursor:pointer">📖 Create narrative</button>
                    </div>
                    <div class="hyp-search-results" style="display:none;margin-top:8px"></div>
                </div>
            `).join('')}
        </div>`;
    }

    // Second-order effects
    if (result.second_order_effects && result.second_order_effects.length) {
        html += `<div class="brainstorm-section">
            <div class="brainstorm-section-title">🌊 Second-Order Effects</div>
            ${result.second_order_effects.map(e => `
                <div class="second-order-card">
                    <p><strong>${_renderBrainstormLinks(e.effect)}</strong></p>
                    ${e.affected_sectors?.length ? `<div style="font-size:10px;color:var(--text-muted)">Sectors: ${e.affected_sectors.map(s => `<span class="bs-link" onclick="_brainstormConceptClick('${escHtml(s.replace(/'/g, "\\'"))}')" style="color:var(--accent);cursor:pointer;text-decoration:underline dotted;text-underline-offset:2px">${escHtml(s)}</span>`).join(', ')}</div>` : ''}
                    ${e.affected_companies?.length ? `<div style="font-size:10px;color:var(--text-muted)">Companies: ${e.affected_companies.map(c => `<span class="bs-link" onclick="_brainstormConceptClick('${escHtml(c.replace(/'/g, "\\'"))}')" style="color:var(--accent);cursor:pointer;text-decoration:underline dotted;text-underline-offset:2px">${escHtml(c)}</span>`).join(', ')}</div>` : ''}
                </div>
            `).join('')}
        </div>`;
    }

    // Questions to investigate
    if (result.questions_to_investigate && result.questions_to_investigate.length) {
        html += `<div class="brainstorm-section">
            <div class="brainstorm-section-title">❓ Questions to Investigate</div>
            ${result.questions_to_investigate.map((q, qi) => `
                <div id="investigate-q-${qi}" style="padding:8px 12px;margin-bottom:6px;background:var(--bg-secondary);border-radius:8px;border:1px solid var(--border);font-size:12px;color:var(--text-secondary);cursor:pointer;display:flex;align-items:center;gap:8px" onclick="_investigateWithFeedback(this, '${escHtml(q.replace(/'/g, "\\'"))}')">
                    <span style="flex:1">🔍 ${escHtml(q)}</span>
                    <span class="investigate-status" style="font-size:10px;color:var(--text-muted)"></span>
                </div>
            `).join('')}
        </div>`;
    }

    // Store link labels from brainstorm for use when linking
    window._brainstormLinkLabels = result.link_labels || [];

    // Related past hypotheses (serendipity engine)
    const relatedHyps = window._brainstormRelatedHyps || [];
    console.log('[brainstorm] relatedHyps:', relatedHyps.length, relatedHyps);
    
    html += `<div class="brainstorm-section">
        <div class="brainstorm-section-title">🔮 Related Past Hypotheses</div>
        <div style="font-size:10px;color:var(--text-muted);margin-bottom:8px">From previous brainstorm sessions — may reveal unexpected connections</div>
        ${relatedHyps.length ? relatedHyps.map(h => `
            <div style="padding:10px 12px;margin-bottom:6px;background:var(--bg-secondary);border-radius:8px;border:1px solid var(--border);border-left:3px solid ${h.relevance_score >= 3 ? 'var(--accent)' : 'var(--border)'}">
                <div style="display:flex;justify-content:space-between;align-items:start">
                    <div style="font-size:12px;font-weight:600;color:var(--text-primary)">${_renderBrainstormLinks(h.title)}</div>
                    <span style="font-size:9px;padding:2px 6px;border-radius:4px;background:rgba(6,182,212,0.15);color:var(--accent);white-space:nowrap">${h.relevance_score >= 3 ? 'strong' : 'weak'}</span>
                </div>
                <div style="font-size:11px;color:var(--text-muted);margin-top:4px">${_renderBrainstormLinks(h.reasoning || '')}</div>
                <div style="font-size:9px;color:var(--text-muted);margin-top:6px">Match: ${_renderBrainstormLinks(h.match_reason || '')}</div>
                <div style="display:flex;gap:6px;margin-top:6px">
                    <button onclick="_createNarrativeFromHypothesis('${escHtml(h.title.replace(/'/g, "\\'"))}', '${escHtml((h.reasoning || '').replace(/'/g, "\\'"))}')" style="padding:3px 8px;background:var(--bg-tertiary);border:1px solid var(--purple);border-radius:4px;color:var(--purple);font-size:9px;font-weight:600;cursor:pointer">📖 Narrative</button>
                </div>
            </div>
        `).join('') : '<div style="font-size:11px;color:var(--text-muted);padding:8px 0;font-style:italic">No related past hypotheses found for these threads.</div>'}
    </div>`;

    // Actions bar
    const tids = JSON.stringify(threadIds);
    html += `<div style="display:flex;gap:10px;margin-top:24px;padding-top:16px;border-top:1px solid var(--border)">
        <button onclick="_linkFromBrainstorm(${escHtml(tids)})" style="padding:10px 20px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:8px;color:var(--purple);font-size:12px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px">🔗 Link These Threads</button>
        <button onclick="closeBrainstorm()" style="padding:10px 20px;background:none;border:1px solid var(--border);border-radius:8px;color:var(--text-muted);font-size:12px;cursor:pointer">Close</button>
    </div>`;

    container.innerHTML = html;
}

function _linkFromBrainstorm(threadIds) {
    const btn = event.target.closest('button');
    if (btn) { btn.textContent = '🔗 Linking...'; btn.disabled = true; }

    // Use pre-generated labels from brainstorm (no extra LLM call)
    const brainstormLabels = window._brainstormLinkLabels || [];
    let labelIdx = 0;

    const promises = [];
    for (let i = 0; i < threadIds.length; i++) {
        for (let j = i + 1; j < threadIds.length; j++) {
            const label = brainstormLabels[labelIdx]?.label || '';
            labelIdx++;
            promises.push(
                fetch('/api/signals/thread-links', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ thread_a_id: threadIds[i], thread_b_id: threadIds[j], label })
                }).then(r => r.json()).then(() => label)
            );
        }
    }
    Promise.all(promises).then(labels => {
        const used = labels.filter(Boolean);
        if (btn) { btn.textContent = `✓ Linked${used.length ? ' (' + used.join(', ') + ')' : ''}`; btn.style.color = 'var(--green)'; }
        if (_signalTab === 'graph') loadBoard();
    });
}

/** Render brainstorm text with [[concept]] links clickable. Also auto-links known patterns. */
function _renderBrainstormLinks(text) {
    if (!text) return '';
    let html = escHtml(text);
    // Replace [[concept]] with clickable links
    html = html.replace(/\[\[([^\]]+)\]\]/g, (_, concept) =>
        `<span class="bs-link" onclick="_brainstormConceptClick('${concept.replace(/'/g, "\\'")}')" style="color:var(--accent);cursor:pointer;text-decoration:underline dotted;text-underline-offset:2px;font-weight:600">${concept}</span>`
    );
    return html;
}

function _brainstormConceptClick(concept) {
    // Open Discovery Drawer with keyword search — works from any view
    const crumbNode = { type: 'keyword', query: concept, label: concept };
    _openDiscoveryDrawer(crumbNode);
    _fetchDiscoveryResults(crumbNode);
}

function _investigateInline(btn, query) {
    const card = btn.closest('.hypothesis-card');
    const resultsDiv = card ? card.querySelector('.hyp-search-results') : null;

    btn.textContent = '🔍 Searching...';
    btn.disabled = true;
    btn.style.borderColor = 'var(--accent)';

    fetch('/api/signals/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
    })
    .then(r => r.json())
    .then(data => {
        btn.disabled = false;
        const found = data.total_found || 0;
        const newCount = data.new_inserted || 0;
        btn.textContent = `✓ ${found} found, ${newCount} new`;
        btn.style.color = 'var(--green)';
        btn.style.borderColor = 'var(--green)';

        // Show results inline under the hypothesis
        if (resultsDiv && found > 0) {
            resultsDiv.style.display = 'block';
            const auditHtml = (data.audit || []).map(a =>
                `<span style="color:var(--text-muted)">${escHtml(a.source)}: ${a.new || 0} new</span>`
            ).join(' · ');
            resultsDiv.innerHTML = `<div style="font-size:10px;color:var(--green);padding:4px 8px;background:rgba(34,197,94,0.08);border-radius:6px;border:1px solid rgba(34,197,94,0.2)">
                ${auditHtml}
            </div>`;
        }

        // Reload signals in background
        loadSignals();
        if (_signalTab === 'graph') loadBoard();
    })
    .catch(() => {
        btn.disabled = false;
        btn.textContent = '🔍 Search signals';
        btn.style.color = 'var(--red)';
    });
}

function investigateHypothesis(query) {
    closeBrainstorm();
    _runInvestigateSearch(null, query);
}

function _investigateWithFeedback(el, query) {
    _runInvestigateSearch(el, query);
}

function _runInvestigateSearch(el, query) {
    const status = el ? el.querySelector('.investigate-status') : null;
    if (el) { el.style.borderColor = 'var(--accent)'; if (status) status.textContent = 'searching...'; }

    fetch('/api/signals/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
    })
    .then(r => r.json())
    .then(data => {
        loadSignals();
        if (_signalTab === 'graph') loadBoard();
        if (el) {
            el.style.borderColor = 'var(--green)';
            if (status) status.innerHTML = `<span style="color:var(--green)">✓ ${data.total_found || 0} found, ${data.new_inserted || 0} new</span>`;
        } else {
            switchSignalTab('raw');
        }
    })
    .catch(() => {
        if (el && status) status.innerHTML = `<span style="color:var(--red)">failed</span>`;
    });
}

function openPastBrainstorm(brainstormId) {
    const overlay = document.getElementById('brainstorm-overlay');
    const content = document.getElementById('brainstorm-content');
    const subtitle = document.getElementById('brainstorm-subtitle');
    overlay.classList.add('visible');
    subtitle.textContent = 'Loading...';
    content.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)">Loading brainstorm...</div>';

    fetch(`/api/signals/brainstorms/${brainstormId}`)
        .then(r => r.json())
        .then(b => {
            if (b.error) { content.innerHTML = `<div style="color:var(--red)">${escHtml(b.error)}</div>`; return; }
            const threads = b.threads || [];
            subtitle.textContent = threads.map(t => t.title).join(' × ');
            // Re-use the render function
            const result = {
                connection_summary: b.connection_summary,
                hypotheses: b.hypotheses || [],
                second_order_effects: b.second_order_effects || [],
                questions_to_investigate: b.questions_to_investigate || [],
            };
            // Build thread cards HTML first
            content.innerHTML = `<div class="brainstorm-threads">
                ${threads.map(t => {
                    const bDoms2 = _parseDomains(t.domain);
                    const domColor = _DOMAIN_COLORS[bDoms2[0]] || '#6b7280';
                    return `<div class="brainstorm-thread-card" style="border-left:3px solid ${domColor}">
                        <h3>${escHtml(t.title)}</h3>
                        <p>${escHtml(t.synthesis || 'No summary')}</p>
                    </div>`;
                }).join('')}
            </div>
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:16px">Brainstormed ${b.created_at ? _timeAgo(b.created_at) : 'previously'}</div>`;

            // Fetch related hypotheses for this past brainstorm before rendering the rest
            const tids = b.thread_ids || [];
            fetch('/api/hypotheses/related', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ thread_ids: tids })
            })
            .then(r => r.json())
            .then(data => {
                window._brainstormRelatedHyps = (data.hypotheses || []).filter(h => h.brainstorm_id !== brainstormId);
                _renderBrainstormResults(content, result, tids);
            })
            .catch(() => {
                window._brainstormRelatedHyps = [];
                _renderBrainstormResults(content, result, tids);
            });
        })
        .catch(() => { content.innerHTML = '<div style="color:var(--red)">Failed to load</div>'; });
}

function closeBrainstorm() {
    document.getElementById('brainstorm-overlay').classList.remove('visible');
    // Reload graph to show any new links
    if (_signalTab === 'graph') loadBoard();
    // Refresh brainstorm list in sidebar
    fetch('/api/signals/brainstorms').then(r => r.json()).then(data => {
        _renderBrainstormList(data.brainstorms || []);
    }).catch(() => {});
}

function _prefillResearchChat(companyName) {
    // Create a new chat and pre-fill the input with a company research prompt
    if (typeof newChat === 'function') newChat();
    const input = document.getElementById('chat-input');
    if (input) {
        input.value = `Run a full profile on ${companyName}`;
        input.focus();
    }
}

function _toggleRawSelect(sigId) {
    if (_rawSelectedSignals.has(sigId)) _rawSelectedSignals.delete(sigId);
    else _rawSelectedSignals.add(sigId);
    const el = document.querySelector(`.sig-card-select[data-sig-id="${sigId}"]`);
    if (el) el.classList.toggle('checked');
    _updateSelectionBar();
}

function _clearRawSelection() {
    _rawSelectedSignals.clear();
    document.querySelectorAll('.sig-card-select.checked[data-sig-id]').forEach(el => el.classList.remove('checked'));
    _updateSelectionBar();
}

function _createPatternFromSelection() {
    if (_rawSelectedSignals.size < 2) return;
    const ids = [..._rawSelectedSignals];
    // Get titles for preview
    const titles = ids.map(id => {
        const s = _signalsCache.find(x => x.id == id);
        return s ? s.title : '';
    }).filter(Boolean);

    const defaultTitle = titles[0] ? titles[0].substring(0, 50) : 'New Thread';
    _showInlineInput(window.innerWidth / 2 - 100, window.innerHeight / 2, 'Thread title...', defaultTitle, (title) => {
        if (!title) return;
        fetch('/api/signals/patterns', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, signal_ids: ids })
        })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                _rawSelectedSignals.clear();
                loadSignals();
                setTimeout(() => switchSignalTab('threads'), 500);
            }
        });
    });
}

// ── Tabbed Right Pane (Review Queue / Thread Detail) ──

function _switchRightPaneTab(tab) {
    const queueTab = document.getElementById('sig-rq-tab-queue');
    const threadTab = document.getElementById('sig-rq-tab-thread');
    const queueBody = document.getElementById('sig-rq-body');
    const threadBody = document.getElementById('sig-rq-thread-body');
    if (tab === 'queue') {
        if (queueTab) queueTab.classList.add('active');
        if (threadTab) threadTab.classList.remove('active');
        if (queueBody) queueBody.style.display = '';
        if (threadBody) threadBody.style.display = 'none';
    } else {
        if (queueTab) queueTab.classList.remove('active');
        if (threadTab) { threadTab.classList.add('active'); threadTab.style.display = ''; }
        if (queueBody) queueBody.style.display = 'none';
        if (threadBody) threadBody.style.display = '';
    }
}

function _showThreadInRightPane(threadId) {
    const threadTab = document.getElementById('sig-rq-tab-thread');
    const threadBody = document.getElementById('sig-rq-thread-body');
    if (!threadBody) return;
    // Show the thread tab and switch to it
    if (threadTab) threadTab.style.display = '';
    _switchRightPaneTab('thread');
    threadBody.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted)">Loading thread...</div>';
    // Fetch and render thread detail
    fetch(`/api/signals/threads/${threadId}`)
        .then(r => r.json())
        .then(thread => {
            if (!thread || thread.error) { threadBody.innerHTML = '<div style="padding:20px;color:var(--red)">Thread not found</div>'; return; }
            const domains = _parseDomains(thread.domain);
            const domColor = _DOMAIN_COLORS[domains[0]] || '#6b7280';
            const signals = thread.signals || [];
            const m = thread.momentum || {};
            const mDir = m.direction || 'stable';
            const mLabel = {accelerating: '\u2191 Accelerating', stable: '\u2192 Stable', fading: '\u2193 Decelerating'}[mDir];
            threadBody.innerHTML = `
                <div style="border-left:4px solid ${domColor};padding:12px 16px;margin-bottom:12px">
                    <div style="font-size:16px;font-weight:700;color:var(--text-primary);margin-bottom:6px">${escHtml(thread.title)}</div>
                    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12px">
                        ${_renderDomainBadges(thread.domain, '12px')}
                        <span class="thread-momentum ${escHtml(mDir)}">${mLabel}</span>
                        <span style="color:var(--text-muted)">${signals.length} signals</span>
                    </div>
                </div>
                ${thread.synthesis ? `<div style="font-size:13px;color:var(--text-secondary);line-height:1.6;margin-bottom:12px;padding:0 4px">${escHtml(thread.synthesis)}</div>` : ''}
                <div style="font-size:12px;font-weight:700;color:var(--text-secondary);margin-bottom:8px;padding:0 4px">Signals (${signals.length})</div>
                ${signals.filter(s => s.signal_status !== 'noise').slice(0, 15).map(s => `
                    <div style="padding:8px 4px;border-bottom:1px solid var(--border)">
                        <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:2px">${escHtml(s.title)}</div>
                        <div style="font-size:11px;color:var(--text-muted);display:flex;gap:6px">
                            <span>${escHtml(s.source_name || s.source || '')}</span>
                            <span>${s.published_at ? s.published_at.substring(0, 10) : ''}</span>
                        </div>
                    </div>
                `).join('')}
            `;
        });
}

// ── Raw Signal Detail Pane (middle pane in 3-pane layout) ──

function _showRawDetailPane(title) {
    const detailBody = document.getElementById('sig-raw-detail-body');
    const detailEmpty = document.getElementById('sig-raw-detail-empty');
    const closeBtn = document.getElementById('sig-raw-detail-close');
    const titleEl = document.querySelector('.sig-raw-detail-title');
    if (detailEmpty) detailEmpty.style.display = 'none';
    if (closeBtn) closeBtn.style.display = 'block';
    if (titleEl && title) titleEl.textContent = title;
    return detailBody;
}

function _closeRawDetail() {
    _activeSignalId = null;
    document.querySelectorAll('.sig-card').forEach(c => c.classList.remove('active'));
    const detailBody = document.getElementById('sig-raw-detail-body');
    const closeBtn = document.getElementById('sig-raw-detail-close');
    if (detailBody) detailBody.innerHTML = `<div class="signals-empty" id="sig-raw-detail-empty" style="display:flex">
        <div style="font-size:32px;margin-bottom:12px">&#128270;</div>
        <div>Select a signal to view details</div>
        <div style="color:var(--text-muted);font-size:12px;margin-top:6px">Click any signal card in the feed.</div>
    </div>`;
    if (closeBtn) closeBtn.style.display = 'none';
}

// ── Inline Review Queue (right pane in 3-pane layout) ──

let _reviewGroupsCache = { groups: [], ungrouped: [], total_unassigned: 0 };
let _reviewQueueExpanded = true;

function _loadReviewGroups() {
    const body = document.getElementById('sig-rq-body');
    const countEl = document.getElementById('sig-rq-count');
    if (!body) return;
    // Ensure queue body is visible (not thread detail)
    _switchRightPaneTab('queue');
    // Pre-fetch threads cache if empty (needed for "Other thread..." dropdown)
    if (!_threadsCache || !_threadsCache.length) {
        fetch('/api/signals/threads').then(r => r.json()).then(td => { _threadsCache = td.threads || []; }).catch(() => {});
    }

    // If user is on list view, just render list
    // Use cache if already populated (preserves locally-injected suggestions from _injectRecentThread)
    if (_rqView === 'list') {
        _renderReviewList(_rqListCache && _rqListCache.length > 0);
        // Still update the count badge
        fetch('/api/signals/review-queue?limit=1').then(r => r.json()).then(d => {
            if (countEl) countEl.textContent = d.total || '';
            const badge = document.getElementById('review-queue-count');
            if (badge) badge.textContent = d.total || '';
        }).catch(() => {});
        return;
    }

    // Grouped view: load fast ungrouped first, then groups in background
    body.innerHTML = '<div style="padding:20px;color:var(--text-muted);font-size:12px;text-align:center">Loading...</div>';
    fetch('/api/signals/review-queue?limit=20').then(r => r.json()).then(fastData => {
        const total = fastData.total || 0;
        if (countEl) countEl.textContent = total;
        const badge = document.getElementById('review-queue-count');
        if (badge) badge.textContent = total;

        const signals = fastData.signals || [];
        if (!signals.length) {
            _reviewGroupsCache = { groups: [], ungrouped: [], total_unassigned: 0 };
            _renderReviewGroups();
            _updateReviewQueueVisibility();
            return;
        }
        _reviewGroupsCache = { groups: [], ungrouped: signals.map(s => ({
            id: s.id, title: s.title, source_name: s.source_name || '', published_at: s.published_at || '',
            domain: s.domain || '', confidence: s.confidence || 'low',
            suggestions: (s.suggestions || []).map(sg => ({ thread_id: sg.thread_id, thread_title: sg.thread_title, score: sg.score }))
        })), total_unassigned: total };
        if (_rqView === 'grouped') _renderReviewGroups();
        _updateReviewQueueVisibility();

        // Load grouped version in background
        fetch('/api/signals/review-queue/groups').then(r => r.json()).then(groupData => {
            _reviewGroupsCache = groupData;
            // Sync counts from the authoritative total
            if (countEl) countEl.textContent = total;
            if (_rqView === 'grouped') _renderReviewGroups();
        }).catch(() => {});
    }).catch(() => {
        body.innerHTML = '<div style="padding:20px;color:var(--red);font-size:12px;text-align:center">Failed to load</div>';
    });
}

function _renderReviewGroups() {
    _rqActiveSignalIdx = -1;
    _rqActivePillIdx = -1;

    const body = document.getElementById('sig-rq-body');
    if (!body) return;
    const { groups, ungrouped, total_unassigned } = _reviewGroupsCache;
    if (total_unassigned === 0) {
        body.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-muted)">
            <div style="font-size:28px;margin-bottom:10px">&#10003;</div>
            <div style="font-size:13px">All signals assigned</div>
        </div>`;
        return;
    }
    let html = '';

    // Groups
    groups.forEach((g, gi) => {
        if (!g) return; // skip assigned/dismissed groups
        const sigCount = g.signals.length;
        const suggPills = (g.all_suggestions || []).map((s, si) => {
            const pct = Math.round(s.score * 100);
            const isTop = si === 0 && pct > 15;
            return `<div onclick="_bulkAssignGroup(${gi},${s.thread_id})" data-rq-pill-tid="${s.thread_id}" data-rq-pill-title="${escHtml(s.thread_title)}" class="sig-rq-suggestion-pill ${isTop ? 'top' : ''}">
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(s.thread_title)}</span>
                <span style="font-size:11px;color:var(--text-muted);font-weight:600;flex-shrink:0">${pct}%</span>
            </div>`;
        }).join('');

        html += `<div class="sig-rq-group rq-nav-item" id="rq-group-${gi}" draggable="true"
            ondragstart="event.dataTransfer.setData('text/plain','rq-group:${gi}');event.dataTransfer.effectAllowed='move'">
            <div class="sig-rq-group-header" onclick="document.getElementById('rq-group-signals-${gi}').style.display=document.getElementById('rq-group-signals-${gi}').style.display==='none'?'':'none'">
                <div class="sig-rq-group-title">${escHtml(g.group_title)}</div>
                <div class="sig-rq-group-count">${sigCount}</div>
                <button onclick="event.stopPropagation();_dismissGroup(${gi})" style="margin-left:6px;padding:3px 8px;background:none;border:1px solid var(--border);border-radius:4px;color:var(--text-muted);font-size:10px;cursor:pointer;flex-shrink:0" title="Dismiss all as noise" onmouseenter="this.style.borderColor='#ef4444';this.style.color='#ef4444'" onmouseleave="this.style.borderColor='var(--border)';this.style.color='var(--text-muted)'">✕</button>
            </div>
            <div class="sig-rq-group-signals" id="rq-group-signals-${gi}">
                ${g.signals.map(s => `<div class="sig-rq-group-signal">
                    <span style="color:var(--text-muted);flex-shrink:0">&#8226;</span>
                    <span onclick="openSignalDetail(${s.id})" oncontextmenu="_showRqSignalCtxMenu(event, ${s.id}, ${JSON.stringify(s.title).replace(/"/g, '&quot;')}, ${JSON.stringify(s.url || '').replace(/"/g, '&quot;')})" style="cursor:pointer" onmouseenter="this.style.color='var(--accent)'" onmouseleave="this.style.color=''">${escHtml(s.title)}</span>
                </div>`).join('')}
            </div>
            <div class="sig-rq-group-actions">
                ${suggPills}
            </div>
            <div style="padding:0 10px 8px;position:relative">
                <input type="text" placeholder="Search or type thread name..." id="rq-gsearch-${gi}" class="sig-rq-dropdown-toggle"
                    onfocus="_renderRqGroupList(${gi},this.value);document.getElementById('rq-glist-${gi}').style.display=''"
                    oninput="_renderRqGroupList(${gi},this.value)"
                    onkeydown="_rqGroupSearchKeydown(event,${gi})"
                    style="width:100%;padding:8px 12px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);font-size:13px;outline:none;box-sizing:border-box" />
                <div id="rq-glist-${gi}" style="display:none;position:absolute;left:10px;right:10px;top:100%;z-index:20;background:var(--bg-secondary);border:1px solid var(--border);border-radius:0 0 6px 6px;box-shadow:0 4px 16px rgba(0,0,0,0.5);max-height:200px;overflow-y:auto"></div>
                <button onclick="_dismissGroup(${gi})" style="position:absolute;right:16px;top:6px;padding:4px 8px;background:none;border:1px solid var(--border);border-radius:4px;color:var(--text-muted);font-size:10px;cursor:pointer" title="Dismiss all as noise">&#10005;</button>
            </div>
        </div>`;
    });

    // If no groups remain, show empty state with nudge to list view
    const activeGroups = groups.filter(Boolean);
    if (!activeGroups.length && ungrouped.length) {
        html += `<div style="text-align:center;padding:30px;color:var(--text-muted)">
            <div style="font-size:13px;margin-bottom:6px">No similar signal groups found</div>
            <div style="font-size:12px">${ungrouped.length} ungrouped signal${ungrouped.length !== 1 ? 's' : ''} — <span onclick="_switchRqView('list')" style="color:var(--accent);cursor:pointer;text-decoration:underline">switch to List view</span></div>
        </div>`;
    }

    // Ungrouped (only show when groups also exist — otherwise list view is better)
    if (ungrouped.length && activeGroups.length) {
        html += `<div style="margin-top:12px;padding:0 4px"><div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Ungrouped (${ungrouped.length})</div></div>`;
        ungrouped.slice(0, 30).forEach(sig => {
            const suggPills = (sig.suggestions || []).map((s, si) => {
                const pct = Math.round(s.score * 100);
                const isTop = si === 0 && pct > 15;
                return `<div onclick="_assignFromQueue(${sig.id},${s.thread_id},this);_onRqItemAssigned()" data-rq-pill-tid="${s.thread_id}" data-rq-pill-title="${escHtml(s.thread_title)}" class="sig-rq-suggestion-pill ${isTop ? 'top' : ''}">
                    <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(s.thread_title)}</span>
                    <span style="font-size:11px;color:var(--text-muted);font-weight:600;flex-shrink:0">${pct}%</span>
                </div>`;
            }).join('');
            html += `<div id="rq-ungrouped-${sig.id}" class="rq-nav-item" style="padding:10px 12px;margin-bottom:6px;border:1px solid var(--border);border-radius:8px;background:var(--bg-secondary)">
                <div style="display:flex;justify-content:space-between;align-items:start;gap:8px;margin-bottom:6px">
                    <div onclick="openSignalDetail(${sig.id})" oncontextmenu="_showRqSignalCtxMenu(event, ${sig.id}, ${JSON.stringify(sig.title).replace(/"/g, '&quot;')}, ${JSON.stringify(sig.url || '').replace(/"/g, '&quot;')})" style="font-size:13px;font-weight:600;color:var(--text-primary);cursor:pointer;line-height:1.3">${escHtml(sig.title)}</div>
                    <button onclick="_dismissFromQueue(${sig.id},this);_onRqItemAssigned()" style="flex-shrink:0;width:22px;height:22px;display:flex;align-items:center;justify-content:center;background:none;border:1px solid var(--border);border-radius:4px;font-size:11px;color:var(--text-muted);cursor:pointer" title="Dismiss">&#10005;</button>
                </div>
                <div style="display:flex;flex-direction:column;gap:4px">
                    ${suggPills}
                    <div style="position:relative">
                        <div onclick="_toggleRqDropdown(${sig.id})" class="sig-rq-dropdown-toggle" style="padding:6px 10px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;transition:all 0.15s">
                            <span>Other thread…</span><span style="font-size:9px">▼</span>
                        </div>
                        <div id="rq-dd-${sig.id}" style="display:none;position:absolute;left:0;right:0;top:100%;z-index:20;background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px;margin-top:2px;box-shadow:0 4px 16px rgba(0,0,0,0.5);overflow:hidden">
                            <input type="text" placeholder="Search or create thread…" id="rq-search-${sig.id}" oninput="_filterRqDropdown(${sig.id},this.value)" onkeydown="_rqSearchKeydown(event,${sig.id})" style="width:100%;padding:7px 12px;background:var(--bg-tertiary);border:none;border-bottom:1px solid var(--border);color:var(--text-primary);font-size:12px;outline:none;box-sizing:border-box">
                            <div id="rq-list-${sig.id}" style="max-height:200px;overflow-y:auto"></div>
                        </div>
                    </div>
                </div>
            </div>`;
        });
    }

    body.innerHTML = html || '<div style="padding:20px;color:var(--text-muted);font-size:12px;text-align:center">No signals to review</div>';
    _renderNoiseFooter(body);
    _updateRqNavHighlight();
}

function _bulkAssignGroup(gi, threadId) {
    const group = _reviewGroupsCache.groups[gi];
    if (!group) return;
    const sigIds = group.signals.map(s => s.id);
    const groupEl = document.getElementById(`rq-group-${gi}`);
    if (groupEl) groupEl.style.opacity = '0.5';
    fetch('/api/signals/review-queue/bulk-assign', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_ids: sigIds, thread_id: threadId })
    }).then(r => r.json()).then(data => {
        if (data.ok && groupEl) {
            const threadTitle = (_threadsCache.find(t => t.id === threadId) || {}).title || `Thread #${threadId}`;
            groupEl.innerHTML = `<div style="padding:10px;display:flex;align-items:center;justify-content:space-between">
                <span style="font-size:12px;color:var(--green)">&#10003; ${sigIds.length} assigned to ${escHtml(threadTitle)}</span>
                <button onclick="_undoBulkAssign(${gi},${threadId})" style="padding:3px 8px;background:none;border:1px solid var(--border);border-radius:4px;font-size:10px;color:var(--text-muted);cursor:pointer">Undo</button>
            </div>`;
            groupEl.style.opacity = '1';
            _reviewGroupsCache.groups[gi] = null;
            _onRqItemAssigned();
            // Boost this thread in remaining signals' suggestions
            _injectRecentThread(threadId, threadTitle);
            // Refresh thread cache
            fetch('/api/signals/threads').then(r => r.json()).then(td => { _threadsCache = td.threads || []; _sortedThreadsCache = null; });
        }
    });
}

function _undoBulkAssign(gi, threadId) {
    const group = _reviewGroupsCache.groups[gi];
    if (!group) return;
    Promise.all(group.signals.map(s =>
        fetch('/api/signals/review-queue/unassign', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signal_id: s.id, thread_id: threadId })
        })
    )).then(() => _loadReviewGroups());
}

function _dismissGroup(gi) {
    const group = _reviewGroupsCache.groups[gi];
    if (!group) return;
    const groupEl = document.getElementById(`rq-group-${gi}`);
    if (groupEl) groupEl.style.opacity = '0.5';
    Promise.all(group.signals.map(s =>
        fetch('/api/signals/review-queue/dismiss', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signal_id: s.id })
        })
    )).then(() => {
        if (groupEl) {
            groupEl.innerHTML = `<div style="padding:10px;display:flex;align-items:center;justify-content:space-between">
                <span style="font-size:12px;color:var(--text-muted)">&#10005; ${group.signals.length} dismissed</span>
                <button onclick="_loadReviewGroups()" style="padding:3px 8px;background:none;border:1px solid var(--border);border-radius:4px;font-size:10px;color:var(--text-muted);cursor:pointer">Undo</button>
            </div>`;
            groupEl.style.opacity = '1';
        }
        _reviewGroupsCache.groups[gi] = null;
        _onRqItemAssigned();
    });
}

function _renderNoiseFooter(container) {
    fetch('/api/signals/noise-count').then(r => r.json()).then(d => {
        if (!d.count) return;
        const footer = document.createElement('div');
        footer.style.cssText = 'padding:10px 12px;border-top:1px solid var(--border);text-align:center';
        footer.innerHTML = `<button onclick="_showNoiseSignals(this.parentElement)" style="background:none;border:none;color:var(--text-muted);font-size:11px;cursor:pointer">${d.count} dismissed · <span style="color:var(--accent)">review</span></button>`;
        container.appendChild(footer);
    }).catch(() => {});
}

function _showNoiseSignals(footerEl) {
    footerEl.innerHTML = '<div style="padding:8px;color:var(--text-muted);font-size:11px;text-align:center">Loading…</div>';
    fetch('/api/signals/noise?limit=50').then(r => r.json()).then(d => {
        const signals = d.signals || [];
        if (!signals.length) { footerEl.innerHTML = '<div style="padding:8px;color:var(--text-muted);font-size:11px;text-align:center">No dismissed signals</div>'; return; }
        footerEl.innerHTML = `<div style="padding:8px 12px;font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;display:flex;align-items:center;justify-content:space-between">
            Dismissed (${signals.length})
            <button onclick="_clearAllNoise()" style="padding:3px 8px;background:none;border:1px solid #ef4444;border-radius:4px;color:#ef4444;font-size:10px;cursor:pointer">Delete all</button>
        </div>` + signals.map(s => `<div style="padding:6px 12px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:8px">
            <span style="font-size:12px;color:var(--text-muted);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(s.title)}</span>
            <button onclick="_restoreFromNoise(${s.id},this)" style="padding:2px 8px;background:none;border:1px solid var(--border);border-radius:4px;color:var(--accent);font-size:10px;cursor:pointer;flex-shrink:0">Restore</button>
        </div>`).join('');
    });
}

function _restoreFromNoise(signalId, btn) {
    fetch('/api/signals/review-queue/undismiss', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({signal_id: signalId})
    }).then(r => r.json()).then(d => {
        if (d.ok) {
            const row = btn.closest('div');
            if (row) row.remove();
            _showToast('Signal restored', 'success');
        }
    });
}

function _clearAllNoise() {
    _showConfirm('Permanently delete all dismissed signals?', () => {
        fetch('/api/signals/noise', { method: 'DELETE' }).then(r => r.json()).then(d => {
            if (d.ok) {
                _showToast(`${d.deleted || 0} signals deleted`, 'success');
                _loadReviewGroups();
            }
        });
    });
}

function _dismissAllReviewQueue() {
    _showConfirm('Dismiss all remaining unassigned signals as noise?', () => {
        const body = document.getElementById('sig-rq-body');
        if (body) body.style.opacity = '0.5';
        fetch('/api/signals/review-queue/dismiss-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        }).then(r => r.json()).then(d => {
            if (d.ok) {
                _showToast(`${d.count || 0} signals dismissed`, 'success');
                _loadReviewGroups();
            }
        });
    });
}

function _onRqItemAssigned() {
    const countEl = document.getElementById('sig-rq-count');
    if (countEl) {
        const cur = parseInt(countEl.textContent || '0');
        if (cur > 0) countEl.textContent = cur - 1;
    }
    const oldCount = document.getElementById('review-queue-count');
    if (oldCount) {
        const cur = parseInt(oldCount.textContent || '0');
        if (cur > 0) oldCount.textContent = cur - 1;
    }
}

let _rqView = 'grouped'; // 'grouped' or 'list'
let _rqListOffset = 0;
var _rqListCache = []; // signals for current List view page
var _activeRqIndex = -1; // index of highlighted item in dropdown

function _switchRqView(view) {
    _rqView = view;
    const gBtn = document.getElementById('rq-view-grouped');
    const lBtn = document.getElementById('rq-view-list');
    if (gBtn && lBtn) {
        if (view === 'grouped') {
            gBtn.style.background = 'rgba(168,85,247,0.1)';
            gBtn.style.borderColor = 'rgba(168,85,247,0.3)';
            gBtn.style.color = 'var(--purple)';
            lBtn.style.background = 'none';
            lBtn.style.borderColor = 'var(--border)';
            lBtn.style.color = 'var(--text-muted)';
        } else {
            lBtn.style.background = 'rgba(168,85,247,0.1)';
            lBtn.style.borderColor = 'rgba(168,85,247,0.3)';
            lBtn.style.color = 'var(--purple)';
            gBtn.style.background = 'none';
            gBtn.style.borderColor = 'var(--border)';
            gBtn.style.color = 'var(--text-muted)';
        }
    }
    if (view === 'grouped') {
        _loadReviewGroups(); // re-fetch fresh data, not stale cache
    } else {
        _rqListOffset = 0;
        _renderReviewList();
    }
}

function _renderReviewList(offsetOrFromCache) {
    let fromCache = (offsetOrFromCache === true);
    let offset = fromCache ? _rqListOffset : (offsetOrFromCache || 0);
    _rqListOffset = offset;

    const body = document.getElementById('sig-rq-body');
    if (!body) return;

    const render = (signals, total) => {
        _rqActiveSignalIdx = -1;
        _rqActivePillIdx = -1;

        if (!signals.length) {
            body.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted)"><div style="font-size:28px;margin-bottom:8px">✓</div><div style="font-size:13px">All signals assigned</div></div>';
            return;
        }
        let html = `<div style="padding:8px 12px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between">
            <span style="font-size:11px;color:var(--text-muted)">${offset + 1}–${Math.min(offset + signals.length, total)} of ${total}</span>
            <div style="display:flex;gap:4px">
                <button onclick="_enrichVisibleSignals()" style="padding:4px 8px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:4px;color:var(--accent);font-size:11px;cursor:pointer;margin-right:8px">Enrich Page</button>
                ${offset > 0 ? `<button onclick="_renderReviewList(${offset - 20})" style="padding:4px 8px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:4px;color:var(--text-muted);font-size:11px;cursor:pointer">← Prev</button>` : ''}
                ${offset + 20 < total ? `<button onclick="_renderReviewList(${offset + 20})" style="padding:4px 8px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:4px;color:var(--text-muted);font-size:11px;cursor:pointer">Next →</button>` : ''}
            </div>
        </div>
        <div id="rq-progress-bar" style="display:none;height:2px;background:var(--bg-tertiary);width:100%"><div id="rq-progress-fill" style="height:100%;width:0;background:var(--accent);transition:width 0.3s"></div></div>`;
        html += signals.map(sig => {
            if (sig._assigned) return ''; // local hide for immediate feedback
            const dateStr = sig.published_at ? sig.published_at.substring(0, 10) : '';
            const suggHtml = (sig.suggestions || []).map((s, si) => {
                const pct = Math.round(s.score * 100);
                const isTop = si === 0 && pct > 15;
                return `<div onclick="_assignFromQueue(${sig.id},${s.thread_id},this);_onRqItemAssigned()" data-rq-pill-tid="${s.thread_id}" data-rq-pill-title="${escHtml(s.thread_title)}" class="sig-rq-suggestion-pill ${isTop ? 'top' : ''}">
                    <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(s.thread_title)}</span>
                    <span style="font-size:11px;color:var(--text-muted);font-weight:600;flex-shrink:0">${pct}%</span>
                </div>`;
            }).join('');
            const bodyPreview = sig.body ? _formatBody(sig.body) : '';
            const urlLink = sig.url ? `<a href="${escHtml(sig.url)}" target="_blank" rel="noopener" style="font-size:10px;color:var(--accent);text-decoration:none;margin-top:4px;display:inline-block" onclick="event.stopPropagation()">Open source →</a>` : '';
            return `<div id="rq-item-${sig.id}" class="rq-nav-item" style="padding:10px 12px;border-bottom:1px solid var(--border)">
                <div style="display:flex;align-items:start;justify-content:space-between;gap:8px;margin-bottom:6px">
                    <div style="flex:1;min-width:0">
                        <div onclick="const el=document.getElementById('rq-body-${sig.id}');el.style.display=el.style.display==='none'?'block':'none'" oncontextmenu="_showRqSignalCtxMenu(event, ${sig.id}, ${JSON.stringify(sig.title).replace(/"/g, '&quot;')}, ${JSON.stringify(sig.url || '').replace(/"/g, '&quot;')})" style="font-size:13px;font-weight:600;color:var(--text-primary);line-height:1.3;cursor:pointer">${escHtml(sig.title)}</div>
                        <div style="font-size:11px;color:var(--text-muted);margin-top:3px">${escHtml(sig.source_name)} · ${escHtml(dateStr)}</div>
                        <div id="rq-body-${sig.id}" style="display:none;margin-top:6px;padding:8px;background:var(--bg-tertiary);border-radius:6px;font-size:12px;color:var(--text-secondary);line-height:1.5;max-height:200px;overflow-y:auto">${bodyPreview || '<span style="color:var(--text-muted);font-style:italic">No body text</span>'}${urlLink ? '<br>' + urlLink : ''}</div>
                    </div>
                    <button onclick="_dismissFromQueue(${sig.id},this);_onRqItemAssigned()" style="flex-shrink:0;width:22px;height:22px;display:flex;align-items:center;justify-content:center;background:none;border:1px solid var(--border);border-radius:4px;font-size:11px;color:var(--text-muted);cursor:pointer" title="Dismiss">✕</button>
                </div>
                <div style="display:flex;flex-direction:column;gap:4px">
                    ${suggHtml}
                    <div style="position:relative">
                        <div onclick="_toggleRqDropdown(${sig.id})" class="sig-rq-dropdown-toggle" style="padding:6px 10px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;transition:all 0.15s">
                            <span>Other thread…</span><span style="font-size:9px">▼</span>
                        </div>
                        <div id="rq-dd-${sig.id}" style="display:none;position:absolute;left:0;right:0;top:100%;z-index:20;background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px;margin-top:2px;box-shadow:0 4px 16px rgba(0,0,0,0.5);overflow:hidden">
                            <input type="text" placeholder="Search or create thread…" id="rq-search-${sig.id}" oninput="_filterRqDropdown(${sig.id},this.value)" onkeydown="_rqSearchKeydown(event,${sig.id})" style="width:100%;padding:7px 12px;background:var(--bg-tertiary);border:none;border-bottom:1px solid var(--border);color:var(--text-primary);font-size:12px;outline:none;box-sizing:border-box">
                            <div id="rq-list-${sig.id}" style="max-height:200px;overflow-y:auto"></div>
                        </div>
                    </div>
                </div>
            </div>`;
        }).join('');
        body.innerHTML = html;
        _renderNoiseFooter(body);
        _updateRqNavHighlight();
    };

    if (fromCache && _rqListCache.length) {
        // Find total from meta if available, otherwise just use cache length
        render(_rqListCache, _rqListCache.total || _rqListCache.length);
        return;
    }

    body.innerHTML = '<div style="padding:16px;color:var(--text-muted);font-size:12px;text-align:center">Loading…</div>';
    fetch(`/api/signals/review-queue?limit=20&offset=${offset}`)
        .then(r => r.json())
        .then(data => {
            _rqListCache = data.signals || [];
            _rqListCache.total = data.total || 0;
            render(_rqListCache, _rqListCache.total);
        });
}

function _toggleReviewQueue() {
    // Switch to Signals tab if not already there (RQ pane lives in raw tab)
    if (_signalTab !== 'raw') { switchSignalTab('raw'); }
    const queue = document.getElementById('sig-review-queue');
    const collapsed = document.getElementById('sig-rq-collapsed');
    if (queue && collapsed) {
        const isHidden = queue.classList.contains('hidden');
        queue.classList.toggle('hidden');
        collapsed.style.display = isHidden ? 'none' : 'flex';
        _reviewQueueExpanded = isHidden;
        if (isHidden) _loadReviewGroups();
    }
}

function _updateReviewQueueVisibility() {
    const total = _reviewGroupsCache.total_unassigned || 0;
    const queue = document.getElementById('sig-review-queue');
    const collapsed = document.getElementById('sig-rq-collapsed');
    if (total === 0 && !_reviewQueueExpanded) {
        if (queue) queue.classList.add('hidden');
        if (collapsed) collapsed.style.display = 'flex';
    } else {
        if (queue) queue.classList.remove('hidden');
        if (collapsed) collapsed.style.display = 'none';
    }
}

// ── Drag Review Queue Groups to Thread Detail ──

function _rqGroupDragOver(event) {
    const data = (event.dataTransfer.types || []).includes('text/plain');
    if (!data) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    const pane = document.getElementById('signals-detail');
    if (pane) pane.style.outline = '2px solid var(--accent)';
}

function _rqGroupDragLeave(event) {
    const pane = document.getElementById('signals-detail');
    if (pane) pane.style.outline = '';
}

function _rqGroupDrop(event) {
    event.preventDefault();
    const pane = document.getElementById('signals-detail');
    if (pane) pane.style.outline = '';
    const data = event.dataTransfer.getData('text/plain');
    if (!data.startsWith('rq-group:')) return;
    const gi = parseInt(data.split(':')[1]);
    // Get the thread currently shown in the detail pane
    if (!_activeThreadId) { _showToast('No thread open — open a thread first', 'warn'); return; }
    _bulkAssignGroup(gi, _activeThreadId);
}

// Right-click on suggestion pills to view thread
document.addEventListener('contextmenu', (e) => {
    const pill = e.target.closest('[data-rq-pill-tid]');
    if (!pill) return;
    e.preventDefault();
    e.stopPropagation();
    const tid = parseInt(pill.dataset.rqPillTid);
    const title = pill.dataset.rqPillTitle || '';
    openThreadDetail(tid);
    _showToast(`Viewing: ${title.substring(0, 40)}`, 'info', 2000);
});

function _showRqSignalCtxMenu(e, sigId, title, url) {
    e.preventDefault();
    e.stopPropagation();
    const safeTitle = title.replace(/'/g, "\\'");
    const safeUrl = url.replace(/'/g, "\\'");
    const items = [
        { label: 'Open Detail', icon: '🔍', action: `openSignalDetail(${sigId})` },
        { label: 'Open Source URL', icon: '🌐', action: `window.open('${safeUrl}', '_blank')` },
        { label: 'Fetch Full Text', icon: '📥', action: `_scrapeSignal(${sigId})` },
        { label: 'Copy link', icon: '🔗', action: `navigator.clipboard.writeText('${safeUrl}');_showToast('Copied link', 'info')` },
    ];
    _showContextMenu(items, e.clientX, e.clientY, title);
}

function _scrapeSignal(sigId) {
    _showToast('Fetching article text...', 'info', 2000);
    fetch(`/api/signals/${sigId}/scrape`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                _showToast('Article text fetched', 'success');
                const bodyEl = document.getElementById(`rq-body-${sigId}`);
                if (bodyEl) {
                    bodyEl.innerHTML = _formatBody(data.body);
                    bodyEl.style.display = 'block';
                }
            } else {
                _showToast(data.error || 'Failed to fetch text', 'error');
            }
        });
}

async function _enrichVisibleSignals() {
    const items = Array.from(document.querySelectorAll('[id^="rq-item-"]')).filter(el => {
        const bodyEl = el.querySelector('[id^="rq-body-"]');
        return bodyEl && (bodyEl.innerText.includes('No body text') || bodyEl.innerText.length < 500);
    });
    if (!items.length) { _showToast('No signals on this page need text', 'info'); return; }

    const bar = document.getElementById('rq-progress-bar');
    const fill = document.getElementById('rq-progress-fill');
    if (bar) bar.style.display = 'block';
    if (fill) fill.style.width = '0%';
    
    let count = 0;
    for (const item of items) {
        const sigId = parseInt(item.id.replace('rq-item-', ''));
        try {
            const r = await fetch(`/api/signals/${sigId}/scrape`, { method: 'POST' });
            const data = await r.json();
            if (data.ok) {
                const bodyEl = document.getElementById(`rq-body-${sigId}`);
                if (bodyEl) bodyEl.innerHTML = _formatBody(data.body);
            }
        } catch (e) {}
        count++;
        if (fill) fill.style.width = `${(count / items.length) * 100}%`;
    }
    
    _showToast('Page enrichment complete', 'success');
    setTimeout(() => { if (bar) bar.style.display = 'none'; }, 2000);
}

// Close group search dropdowns on click outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('[id^="rq-gsearch-"]') && !e.target.closest('[id^="rq-glist-"]')) {
        document.querySelectorAll('[id^="rq-glist-"]').forEach(l => l.style.display = 'none');
    }
});
let _sortedThreadsCache = null;
let _sortedThreadsCacheKey = 0;

function _getSortedThreads() {
    const key = (_threadsCache || []).length;
    if (_sortedThreadsCache && _sortedThreadsCacheKey === key) return _sortedThreadsCache;
    _sortedThreadsCache = [...(_threadsCache || [])].sort((a, b) => (a.title || '').localeCompare(b.title || ''));
    _sortedThreadsCacheKey = key;
    return _sortedThreadsCache;
}

function _renderRqGroupList(gi, query) {
    const list = document.getElementById(`rq-glist-${gi}`);
    if (!list) return;
    const q = (query || '').toLowerCase().trim();
    const threads = _getSortedThreads();
    const filtered = q ? threads.filter(t => (t.title || '').toLowerCase().includes(q)) : threads.slice(0, 20);

    // Show "+ Create thread" option if query doesn't match an existing thread exactly
    const exactMatch = q && threads.some(t => (t.title || '').toLowerCase() === q);
    const createBtn = q && !exactMatch
        ? `<div onclick="_createThreadForGroup(${gi},'${escHtml(q.replace(/'/g, "\\'"))}')" style="padding:8px 12px;font-size:13px;color:var(--accent);cursor:pointer;border-bottom:1px solid var(--border);font-weight:600;transition:background 0.1s" onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background=''">+ Create: "${escHtml(q)}"</div>`
        : '';

    list.style.display = '';
    list.innerHTML = createBtn + filtered.slice(0, 20).map(t =>
        `<div onclick="_bulkAssignGroup(${gi},${t.id});document.getElementById('rq-glist-${gi}').style.display='none';document.getElementById('rq-gsearch-${gi}').value=''" style="padding:8px 12px;font-size:13px;color:var(--text-secondary);cursor:pointer;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;transition:background 0.1s" onmouseenter="this.style.background='var(--bg-tertiary)'" onmouseleave="this.style.background=''">
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(t.title)}</span>
            <span style="flex-shrink:0;font-size:11px;color:var(--text-muted);margin-left:8px">${t.signal_count || 0}</span>
        </div>`
    ).join('') || '<div style="padding:8px 12px;font-size:12px;color:var(--text-muted)">No threads found</div>';
}

function _rqGroupSearchKeydown(event, gi) {
    if (event.key === 'Escape') {
        document.getElementById(`rq-glist-${gi}`).style.display = 'none';
        event.target.blur();
    } else if (event.key === 'Enter') {
        const v = event.target.value.trim();
        if (!v) return;
        const match = (_threadsCache || []).find(t => (t.title || '').toLowerCase() === v.toLowerCase());
        if (match) {
            _bulkAssignGroup(gi, match.id);
        } else {
            _createThreadForGroup(gi, v);
        }
    }
}

function _injectRecentThread(threadId, title) {
    // Add newly created thread as top suggestion to all remaining groups and ungrouped signals
    const newSugg = { thread_id: threadId, thread_title: title, score: 0.99 };

    // Update groups cache
    (_reviewGroupsCache.groups || []).forEach(g => {
        if (!g) return;
        if (!g.all_suggestions) g.all_suggestions = [];
        // Prepend if not already present
        if (!g.all_suggestions.some(s => s.thread_id === threadId)) {
            g.all_suggestions.unshift(newSugg);
        }
    });
    (_reviewGroupsCache.ungrouped || []).forEach(s => {
        if (!s.suggestions) s.suggestions = [];
        if (!s.suggestions.some(sg => sg.thread_id === threadId)) {
            s.suggestions.unshift(newSugg);
        }
    });

    // Update list view cache
    (_rqListCache || []).forEach(s => {
        if (s._assigned) return;
        if (!s.suggestions) s.suggestions = [];
        if (!s.suggestions.some(sg => sg.thread_id === threadId)) {
            s.suggestions.unshift(newSugg);
        }
    });

    // Re-render current view
    if (_rqView === 'grouped') {
        _renderReviewGroups();
    } else {
        _renderReviewList(true); // render from cache
    }
}

function _createThreadForGroup(gi, title) {
    const group = _reviewGroupsCache.groups[gi];
    if (!group) return;
    const sigIds = group.signals.map(s => s.id);
    fetch('/api/signals/patterns', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, signal_ids: sigIds })
    }).then(r => r.json()).then(data => {
        if (data.ok) {
            const groupEl = document.getElementById(`rq-group-${gi}`);
            if (groupEl) {
                groupEl.innerHTML = `<div style="padding:10px;display:flex;align-items:center;justify-content:space-between">
                    <span style="font-size:12px;color:var(--green)">&#10003; ${sigIds.length} signals → new thread "${escHtml(title)}"</span>
                </div>`;
            }
            _reviewGroupsCache.groups[gi] = null;
            _onRqItemAssigned();
            // Inject new thread as top suggestion into all remaining groups + ungrouped signals
            const newThreadId = data.id;
            _injectRecentThread(newThreadId, title);
            // Refresh thread cache
            fetch('/api/signals/threads').then(r => r.json()).then(td => { _threadsCache = td.threads || []; _sortedThreadsCache = null; });
            _showToast(`Created thread "${title}" with ${sigIds.length} signals`, 'success');
        }
    });
}

function _setSignalStatus(signalId, status, patternId) {
    fetch(`/api/signals/${signalId}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
    }).then(() => {
        // Refresh the pattern detail to reflect the change
        if (patternId) openThreadDetail(patternId);
    });
}

function _toggleSignalArticle(signalId, el) {
    const articleDiv = document.getElementById(`sig-article-${signalId}`);
    if (!articleDiv) return;
    if (articleDiv.style.display === 'block') {
        articleDiv.style.display = 'none';
        return;
    }
    // Show loading, then fetch
    articleDiv.style.display = 'block';
    articleDiv.innerHTML = '<div style="padding:8px;font-size:11px;color:var(--text-muted)">Loading article...</div>';

    fetch(`/api/signals/${signalId}/fetch-article`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            const bodyText = data.body || '';
            if (bodyText.length > 20) {
                let bodyHtml = escHtml(bodyText).substring(0, 2000);
                // Apply search highlights if active
                if (_threadSearchQuery) {
                    const terms = _threadSearchQuery.split(/\s+/).filter(t => t.length >= 2);
                    if (terms.length) {
                        const esc = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
                        bodyHtml = bodyHtml.replace(new RegExp(`(${esc})`, 'gi'), '<mark class="sig-search-hl" style="background:#a855f740;color:var(--text-primary);border-radius:2px;padding:0 1px">$1</mark>');
                    }
                }
                articleDiv.innerHTML = `<div style="padding:8px 0;font-size:11px;color:var(--text-secondary);line-height:1.5;border-left:2px solid var(--border);padding-left:10px;margin-top:6px">${bodyHtml}</div>`;
            } else {
                articleDiv.innerHTML = `<div style="padding:8px;font-size:11px;color:var(--text-muted)">Could not load article text</div>`;
            }
        })
        .catch(() => {
            articleDiv.innerHTML = `<div style="padding:8px;font-size:11px;color:var(--red)">Failed to fetch</div>`;
        });
}

function _closeSharedDetailPane() {
    // When on raw or causal tab, only hide the shared pane
    if (_signalTab === 'raw' || _signalTab === 'causal') {
        const detailPane = document.getElementById('signals-detail');
        if (detailPane) detailPane.style.display = 'none';
        _activeThreadId = null;
        _activeNarrativeId = null;
        // Clear chain board node highlights
        document.querySelectorAll('.cb-node circle:not(.cb-shared-ring)').forEach(c => c.setAttribute('stroke-width', '2'));
        return;
    }
    closeSignalDetail();
}

function closeSignalDetail() {
    _activeSignalId = null;
    _activeThreadId = null;
    _activeNarrativeId = null;
    ++_detailRequestId;
    document.querySelectorAll('.sig-card, .thread-card, .narrative-card').forEach(c => c.classList.remove('active'));
    const detailPane = document.getElementById('signals-detail');
    const detailBody = document.getElementById('signals-detail-body');
    const closeBtn = document.querySelector('.signals-detail-close');
    if (_signalTab === 'raw') {
        // Raw tab: close inline detail pane
        _closeRawDetail();
        return;
    } else if (_signalTab === 'graph' || _signalTab === 'causal') {
        // Board/Causal: collapse pane entirely (causal uses its own inspector)
        if (detailPane) detailPane.style.display = 'none';
    } else {
        // Feed views: reset to empty state (keep pane visible)
        if (detailBody) detailBody.innerHTML = `
            <div class="signals-empty" id="signals-detail-empty" style="display:flex">
                <div style="font-size:32px;margin-bottom:12px">&#128270;</div>
                <div>Select a thread to view details</div>
                <div style="color:var(--text-muted);font-size:12px;margin-top:6px">Click any thread in the feed or graph.</div>
            </div>`;
    }
    if (closeBtn) closeBtn.style.display = 'none';
}

// Structured execution data (persists for "View Last Execution" button)
