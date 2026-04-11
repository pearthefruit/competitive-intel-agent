// Prospecting / Discover Module — extracted from base.html (Phase 2 refactor)
// Dependencies (all function declarations on window):
//   switchModule, refreshSidebar, switchLeftTab, newChat, autoResize, openReport
//   _prefillResearchChat, escHtml, _showToast, _showConfirm, _showInlineInput
//   renderPipelineTree (pipeline-tree.js)

// ===================== PROSPECTING =====================
let allCampaigns = [];
let activeCampaignId = null;
let activeProspectName = null;
let _prospectPipelineRunning = false;
let _currentRunCampaignId = null; // tracks which campaign owns the live pipeline DOM in Pane 2
let _savedLivePipelineDOM = null; // stashed live pipeline DOM when user views another campaign
let _activeTreeRootId = null;    // root campaign id of the currently displayed discovery tree
let _activeTreeNodeId = null;    // which tree node is selected (shows its companies in Pane 3)

// Flat prospect lookup — built from campaigns for detail view
let _prospectsByName = {};

function _getScore(p) {
    // Unified score accessor — prefers lens score over UA fit
    return p?.lens_score || p?.ua_fit || null;
}

function _hasScore(p) {
    return !!_getScore(p);
}

function _prospectTierClass(score) {
    if (score >= 80) return 'prime';
    if (score >= 60) return 'strong';
    if (score >= 40) return 'possible';
    if (score >= 20) return 'weak';
    return 'none';
}

function _dimColor(score) {
    if (score >= 80) return 'var(--green)';
    if (score >= 60) return 'var(--accent)';
    if (score >= 40) return 'var(--yellow)';
    return 'var(--red)';
}

async function loadCampaigns() {
    try {
        const resp = await fetch('/api/campaigns');
        if (!resp.ok) { allCampaigns = []; }
        else { allCampaigns = await resp.json(); }
    } catch (e) { console.error('loadCampaigns failed:', e); allCampaigns = []; }
    renderCampaignSidebar();
}

function renderCampaignSidebar() {
    const list = document.getElementById('prospect-search-list');
    if (!list) return;
    _prospectsByName = {};

    // Index all prospects from all campaigns (including children) for detail lookup
    allCampaigns.forEach(c => {
        (c.prospects || []).forEach(p => {
            if (p.company_name) _prospectsByName[p.company_name] = p;
        });
        (c.children || []).forEach(ch => {
            (ch.prospects || []).forEach(p => {
                if (p.company_name) _prospectsByName[p.company_name] = p;
            });
        });
    });

    if (!allCampaigns.length) {
        list.innerHTML = `<div class="pane-empty">
            <div class="icon">&#128269;</div>
            <div>No campaigns yet.</div>
            <div class="subtitle">Enter a niche above to discover and score companies.</div>
        </div>`;
        return;
    }

    list.innerHTML = allCampaigns.map(c => {
        const isActive = activeCampaignId === c.id ? ' active' : '';
        const statusBadge = c.status === 'running'
            ? '<span class="pane-status-badge running">Running</span>'
            : c.status === 'error'
            ? '<span class="pane-status-badge error">Error</span>'
            : c.status === 'empty'
            ? '<span class="pane-status-badge" style="background:rgba(107,114,128,0.15);color:#9ca3af">No results</span>'
            : '';

        return `<div class="search-query-item${isActive}" data-campaign-id="${c.id}" onclick="selectCampaign(${c.id})">
            <div class="search-query-info">
                <div class="search-query-name">${escHtml(c.name || c.niche)}</div>
                <div class="search-query-meta">
                    ${c.prospect_count || 0} prospects ${statusBadge}
                </div>
            </div>
            <div class="search-query-actions">
                <button class="campaign-group-action" onclick="event.stopPropagation();renameCampaign(${c.id})" title="Rename">&#9998;</button>
                <button class="campaign-group-action" onclick="event.stopPropagation();deleteCampaign(${c.id})" title="Delete">&times;</button>
            </div>
        </div>`;
    }).join('');
}

function selectCampaign(campaignId) {
    const wasActive = activeCampaignId === campaignId;
    if (wasActive) {
        // Re-trigger insight generation if missing on re-click
        const c = allCampaigns.find(x => x.id === campaignId);
        if (c && !c.insight && c.status === 'complete') {
            _autoGenerateInsight(campaignId);
        }
        return;
    }

    const mapEl = document.getElementById('pipeline-map');

    // If pipeline is running and we're leaving the live campaign, stash its DOM
    if (_prospectPipelineRunning && _currentRunCampaignId && activeCampaignId === _currentRunCampaignId && mapEl) {
        _savedLivePipelineDOM = mapEl.innerHTML;
    }

    activeCampaignId = campaignId;
    // Highlight sidebar item
    document.querySelectorAll('.search-query-item').forEach(el => {
        const id = parseInt(el.dataset.campaignId, 10);
        el.classList.toggle('active', id === campaignId);
    });

    // If switching back to the running campaign, restore its live DOM
    if (_prospectPipelineRunning && _currentRunCampaignId === campaignId && _savedLivePipelineDOM && mapEl) {
        mapEl.innerHTML = _savedLivePipelineDOM;
        mapEl.style.display = 'block';
        const emptyEl = document.getElementById('pane-execution-empty');
        if (emptyEl) emptyEl.style.display = 'none';
        const badge = document.getElementById('pane-execution-status');
        if (badge) { badge.textContent = 'Running'; badge.className = 'pane-status-badge running'; }
        _savedLivePipelineDOM = null;
    } else {
        // Check if campaign has child expansions → render discovery tree
        const c = allCampaigns.find(x => x.id === campaignId);
        const hasChildren = c && c.children && c.children.length > 0;
        if (hasChildren) {
            _activeTreeRootId = campaignId;
            _activeTreeNodeId = campaignId;
            renderDiscoveryTree(campaignId);
        } else {
            _activeTreeRootId = null;
            _activeTreeNodeId = null;
            renderExecutionPane(campaignId);
        }
    }

    renderSummaryPane(_activeTreeNodeId || campaignId);
    clearDetailPane();
    focusPane('pane-execution');
}

function renameCampaign(campaignId, event) {
    const c = allCampaigns.find(x => x.id === campaignId);
    const el = event?.target || document.body;
    const rect = el.getBoundingClientRect();
    _showInlineInput(rect.left, rect.bottom + 4, 'Campaign name', c?.name || c?.niche || '', async (newName) => {
        if (!newName || !newName.trim()) return;
        try {
            await fetch(`/api/campaigns/${campaignId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName.trim() }),
            });
            await loadCampaigns();
        } catch (e) { console.error('Rename failed:', e); }
    });
}

async function deleteCampaign(campaignId) {
    _showConfirm('Delete this campaign? Prospect data will be kept.', async () => {
        try {
            await fetch(`/api/campaigns/${campaignId}`, { method: 'DELETE' });
            if (activeCampaignId === campaignId) {
                activeCampaignId = null;
                _resetAllPanes();
            }
            await loadCampaigns();
        } catch (e) { console.error('Delete failed:', e); }
    }, { danger: true, confirmText: 'Delete' });
}

// --- Pane helpers ---

function _resetAllPanes() {
    // Reset Pane 2
    const mapEl = document.getElementById('pipeline-map');
    const execEmpty = document.getElementById('pane-execution-empty');
    const execStatus = document.getElementById('pane-execution-status');
    if (mapEl) { mapEl.style.display = 'none'; mapEl.innerHTML = ''; }
    if (execEmpty) execEmpty.style.display = 'block';
    if (execStatus) { execStatus.textContent = ''; execStatus.className = 'pane-status-badge'; }
    // Reset Pane 3
    const sumContent = document.getElementById('pane-summary-content');
    const sumEmpty = document.getElementById('pane-summary-empty');
    if (sumContent) { sumContent.style.display = 'none'; sumContent.innerHTML = ''; }
    if (sumEmpty) sumEmpty.style.display = 'block';
    // Reset Pane 4
    clearDetailPane();
}

function clearDetailPane() {
    activeProspectName = null;
    _savedDetailHTML = null;
    const detContent = document.getElementById('pane-detail-content');
    const detEmpty = document.getElementById('pane-detail-empty');
    if (detContent) { detContent.style.display = 'none'; detContent.innerHTML = ''; }
    if (detEmpty) detEmpty.style.display = 'block';
    // Exit fullscreen if active
    const pane = document.getElementById('pane-detail');
    if (pane) pane.classList.remove('fullscreen');
    const btn = document.getElementById('detail-expand-btn');
    if (btn) { btn.innerHTML = '&#x26F6;'; btn.title = 'Expand to fullscreen'; }
    // Remove highlights from Pane 2 cards and Pane 3 rows
    document.querySelectorAll('.company-card.active').forEach(c => c.classList.remove('active'));
    document.querySelectorAll('.cv-result-row.active').forEach(r => r.classList.remove('active'));
}

// --- Pane 2: Execution Engine ---

function renderExecutionPane(campaignId) {
    // If this campaign is the one currently running live, don't touch DOM — just update badge
    if (_prospectPipelineRunning && _currentRunCampaignId === campaignId) {
        const badge = document.getElementById('pane-execution-status');
        if (badge) { badge.textContent = 'Running'; badge.className = 'pane-status-badge running'; }
        return;
    }

    const c = allCampaigns.find(x => x.id === campaignId);
    if (!c) return;

    const emptyEl = document.getElementById('pane-execution-empty');
    const mapEl = document.getElementById('pipeline-map');
    const badge = document.getElementById('pane-execution-status');

    // Use flowchart renderer if execution_log exists (new campaigns)
    if (c.execution_log && c.execution_log.length && c.status !== 'empty') {
        if (emptyEl) emptyEl.style.display = 'none';
        if (mapEl) mapEl.style.display = 'block';
        if (badge) { badge.textContent = 'Complete'; badge.className = 'pane-status-badge complete'; }
        const label = c.seed_company ? `Similar to ${c.seed_company}` : (c.name || c.niche || 'Discovery');
        const treeNodes = _discoverLogToTree(c.execution_log, c.prospects, label);
        renderPipelineTree(treeNodes, mapEl);
        return;
    }

    // Set status badge
    if (badge) {
        if (c.status === 'complete') { badge.textContent = 'Complete'; badge.className = 'pane-status-badge complete'; }
        else if (c.status === 'error') { badge.textContent = 'Error'; badge.className = 'pane-status-badge error'; }
        else if (c.status === 'empty') { badge.textContent = 'No Results'; badge.className = 'pane-status-badge'; badge.style.cssText = 'background:rgba(107,114,128,0.15);color:#9ca3af'; }
        else { badge.textContent = ''; badge.className = 'pane-status-badge'; }
    }

    const prospects = (c.prospects || []).sort((a, b) =>
        (_getScore(b)?.overall_score || 0) - (_getScore(a)?.overall_score || 0));

    // Handle empty campaigns (no companies found)
    if (c.status === 'empty' || (!prospects.length && c.status !== 'running')) {
        emptyEl.style.display = 'none';
        mapEl.style.display = 'block';
        mapEl.innerHTML = `
            <div class="pipeline-node done" style="padding:10px 14px">
                <div class="pipeline-node-header">
                    <div class="pipeline-node-icon">&#128269;</div>
                    <div class="pipeline-node-label">Discovery</div>
                </div>
                <div class="pipeline-node-meta">Niche: <strong style="color:var(--text-primary)">${escHtml(c.niche || c.name)}</strong></div>
            </div>
            <div class="pipeline-connector"></div>
            <div class="pipeline-node" style="border-color:rgba(107,114,128,0.3);padding:12px">
                <div class="pipeline-node-header">
                    <div class="pipeline-node-icon" style="background:rgba(107,114,128,0.15)">&#128269;</div>
                    <div class="pipeline-node-label" style="color:#9ca3af">No Results</div>
                </div>
                <div class="pipeline-node-meta" style="margin-top:4px;color:var(--text-muted)">No companies matched this niche. Try broadening the search terms.</div>
            </div>
        `;
        return;
    }

    const scored = prospects.filter(p => _hasScore(p));
    const _limitedStatuses = ['limited', 'http_403', 'connection_failed'];
    const valid = prospects.filter(p => p.validation_status === 'valid').length;
    const limited = prospects.filter(p => _limitedStatuses.includes(p.validation_status)).length;
    const skipped = prospects.filter(p => p.validation_status && p.validation_status !== 'valid' && !_limitedStatuses.includes(p.validation_status)).length;

    // Build static pipeline reconstruction — pipeline steps + search log
    emptyEl.style.display = 'none';
    mapEl.style.display = 'block';

    const companyNames = prospects.map(p => p.company_name).join(', ');
    const searchLogHtml = _buildSearchLogHtml(c.execution_log);

    mapEl.innerHTML = `
        <div class="pipeline-node done" style="padding:10px 14px">
            <div class="pipeline-node-header">
                <div class="pipeline-node-icon">&#128269;</div>
                <div class="pipeline-node-label">Discovery</div>
            </div>
            <div class="pipeline-node-meta">Niche: <strong style="color:var(--text-primary)">${escHtml(c.niche || c.name)}</strong></div>
            ${searchLogHtml}
        </div>
        <div class="pipeline-connector done"></div>
        <div class="pipeline-node done" style="border-color:rgba(168,85,247,0.2);padding:12px">
            <div class="pipeline-node-header">
                <div class="pipeline-node-icon" style="background:rgba(168,85,247,0.15)">&#127919;</div>
                <div class="pipeline-node-label" style="color:var(--purple)">Found ${prospects.length} companies</div>
            </div>
            <div class="pipeline-node-meta" style="margin-top:4px;font-size:11px;color:var(--text-muted)">${escHtml(companyNames)}</div>
        </div>
        <div class="pipeline-connector done"></div>
        <div class="pipeline-node done" style="padding:10px 14px">
            <div class="pipeline-node-header">
                <div class="pipeline-node-icon" style="font-size:14px">&#10003;</div>
                <div class="pipeline-node-label">Validation</div>
            </div>
            <div class="pipeline-node-meta">${valid} valid${limited > 0 ? ` (${limited} limited)` : ''}${skipped > 0 ? ` &mdash; ${skipped} skipped` : ''}</div>
        </div>
        <div class="pipeline-connector done"></div>
        <div class="pipeline-complete-node">
            <span class="check">&#10003;</span>
            Pipeline complete &mdash; ${scored.length > 0 ? `${scored.length} companies scored` : `${prospects.length} companies discovered`}
        </div>
    `;
}

// --- Niche Evaluation Chart Renderers ---

function renderNicheEvaluation(ne, prospects, campaignNode) {
    if (!ne) return '';
    const cov = ne.data_coverage || {};
    const agg = ne.aggregate || {};

    // KPI stat cards
    const stats = [];
    if (agg.total_revenue_formatted) stats.push({v: agg.total_revenue_formatted, l: 'Combined Revenue'});
    if (agg.median_revenue_formatted) stats.push({v: agg.median_revenue_formatted, l: 'Median Revenue'});
    if (ne.company_count) stats.push({v: ne.company_count, l: 'Companies Scanned'});
    if (agg.avg_revenue_growth != null) {
        const allEstimated = (ne.per_company || []).filter(c => c.growth != null).every(c => c.growth_estimated);
        stats.push({v: (agg.avg_revenue_growth > 0 ? '+' : '') + agg.avg_revenue_growth.toFixed(1) + '%', l: allEstimated ? 'Avg Growth YoY (est.)' : 'Avg Growth YoY'});
    }
    if (agg.total_market_cap_formatted) stats.push({v: agg.total_market_cap_formatted, l: 'Combined Mkt Cap'});
    if (agg.total_employees) stats.push({v: agg.total_employees.toLocaleString(), l: 'Total Employees'});

    const statHtml = stats.length ? `<div class="ne-stat-grid">${stats.map(s =>
        `<div class="ne-stat-card"><div class="ne-stat-value">${s.v}</div><div class="ne-stat-label">${s.l}</div></div>`
    ).join('')}</div>` : '';

    // Public vs Private
    const pp = ne.public_vs_private || {};
    const ppHtml = (pp.public || pp.private) ? `<div style="display:flex;gap:12px;font-size:11px;color:var(--text-muted);margin-top:6px">
        ${pp.public ? `<span><span style="color:var(--accent);font-weight:600">${pp.public}</span> Public</span>` : ''}
        ${pp.private ? `<span><span style="color:var(--purple);font-weight:600">${pp.private}</span> Private</span>` : ''}
    </div>` : '';

    // Build prospect lookup for descriptions and metadata
    const prospectMap = {};
    (prospects || []).forEach(p => {
        if (p.company_name) prospectMap[p.company_name.toLowerCase()] = p;
    });

    // Clear selection state when rebuilding with checkboxes
    if (prospects && prospects.length) _selectedForResearch.clear();

    // Unified company cards with expandable detail + research checkboxes
    const companies = (ne.per_company || []).sort((a, b) => (b.revenue || 0) - (a.revenue || 0));
    const maxRev = companies.length ? Math.max(...companies.map(c => c.revenue || 0)) : 0;
    const companyCardsHtml = companies.map(c => {
        const hasRev = c.revenue != null;
        const barPct = hasRev && maxRev ? Math.max((c.revenue / maxRev) * 100, 2) : 0;
        const growthVal = c.growth != null ? c.growth : null;
        const barColor = growthVal != null ? (growthVal > 0 ? 'var(--green)' : growthVal < 0 ? 'var(--red)' : 'var(--text-muted)') : 'var(--text-muted)';
        const growthColor = growthVal != null ? (growthVal > 10 ? 'var(--green)' : growthVal >= 0 ? 'var(--text-secondary)' : 'var(--red)') : '';
        let growthText = '';
        let growthEst = c.growth_estimated ? ' est.' : '';
        if (growthVal != null) {
            const pctStr = `${growthVal > 0 ? '+' : ''}${growthVal.toFixed(0)}%`;
            if (hasRev) {
                const priorRev = c.revenue / (1 + growthVal / 100);
                const absChange = c.revenue - priorRev;
                const sign = absChange >= 0 ? '+' : '';
                const absFmt = Math.abs(absChange) >= 1e9 ? `${sign}$${(absChange/1e9).toFixed(1)}B`
                    : Math.abs(absChange) >= 1e6 ? `${sign}$${(absChange/1e6).toFixed(0)}M`
                    : `${sign}$${(absChange/1e3).toFixed(0)}K`;
                growthText = `${pctStr} (${absFmt})`;
            } else {
                growthText = pctStr;
            }
        }
        const quality = c.data_quality === 'high' ? '' : c.data_quality === 'medium' ? '' : ' (est.)';

        const badges = [];
        if (c.hq_country && c.hq_country !== 'Unknown') badges.push(c.hq_country);
        if (c.sector && c.sector !== 'Unknown' && c.sector !== 'None') badges.push(c.sector);
        const ppBadge = c.is_public
            ? `<span class="ne-badge" style="font-size:9px;padding:1px 6px;border-color:rgba(59,130,246,0.3);color:var(--accent)">Public</span>`
            : `<span class="ne-badge" style="font-size:9px;padding:1px 6px;border-color:rgba(168,85,247,0.3);color:var(--purple)">Private</span>`;

        // Merge prospect data (description, validation, discovery evidence)
        const prospect = prospectMap[(c.name || '').toLowerCase()];
        const desc = prospect?.company_description || '';
        const disc = prospect?.discovery || {};
        const vstatus = prospect?.validation_status || 'valid';
        const isSkipped = vstatus !== 'valid' && vstatus !== 'limited' && vstatus !== 'http_403' && vstatus !== 'connection_failed';
        const safeName = (c.name || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        const hasProspects = prospects && prospects.length > 0;

        return `<div class="ne-company-card${isSkipped ? ' skipped' : ''}" onclick="if(!event.target.closest('.ne-card-cb-wrap')){openProspectDetail('${safeName}')}" style="cursor:pointer${isSkipped ? ';opacity:0.5' : ''}">
            ${hasProspects && !isSkipped ? `<div class="ne-card-cb-wrap" onclick="event.stopPropagation();const cb=this.querySelector('input');cb.checked=!cb.checked;this.classList.toggle('checked',cb.checked);_toggleResearchSelection('${safeName}',cb)">
                <input type="checkbox" class="discovery-select-cb">
                <div class="ne-card-cb-dot"></div>
            </div>` : ''}
            <div class="ne-company-row">
                <span class="ne-company-name" title="${escHtml(c.name)}">${escHtml(c.name)}</span>
                <span class="ne-company-rev">${hasRev ? c.revenue_formatted + quality : '—'}</span>
                ${growthText ? `<span class="ne-company-growth" style="color:${growthColor}">${growthText}${growthEst}</span>` : '<span class="ne-company-growth" style="color:var(--text-muted)">—</span>'}
            </div>
            ${hasRev ? `<div class="ne-bar-track" style="height:6px;margin:4px 0 0">
                <div class="ne-bar-fill" style="width:${barPct}%;background:${barColor};height:100%"></div>
            </div>` : ''}
            ${desc ? `<div style="font-size:11px;color:var(--text-muted);line-height:1.4;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${escHtml(desc)}</div>` : ''}
            <div class="ne-company-badges">
                ${ppBadge}
                ${badges.map(b => `<span class="ne-badge" style="font-size:9px;padding:1px 6px">${escHtml(b)}</span>`).join('')}
            </div>
        </div>`;
    }).join('');

    // Send to Research bar (only when prospects exist)
    const researchBarHtml = (prospects && prospects.length) ? `
        <div class="send-to-research-bar" id="summary-research-bar" style="display:none">
            <span class="str-count">0/3 selected</span>
            <span class="str-label" style="font-size:11px;color:var(--text-muted)">Score with:</span>
            ${_buildLensSelectHtml('summary-lens-select')}
            <button class="str-btn" onclick="_sendToResearch('summary-lens-select')" disabled>Send to Research</button>
        </div>` : '';

    // Coverage footer
    const coverageHtml = `<div class="ne-coverage">
        Data coverage: ${cov.revenue_known || 0}/${ne.company_count} with revenue &bull;
        ${cov.market_cap_known || 0} publicly traded &bull;
        ${cov.growth_known || 0} with growth data
    </div>`;

    return `
        <div class="ne-section">
            <div class="cv-section-title" style="margin-bottom:12px">Niche Evaluation</div>
            ${statHtml}
            ${ppHtml}
        </div>
        ${companies.length ? `<div class="ne-section" style="padding-right:36px">
            <div class="ne-section-title">Company Breakdown</div>
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:8px">Click a company for details. Select companies to send to Research.</div>
            ${companyCardsHtml}
        </div>` : ''}
        ${coverageHtml}
        ${researchBarHtml}
    `;
}

function _neRevenueChart(ne) {
    const companies = (ne.per_company || []).filter(c => c.revenue).sort((a,b) => b.revenue - a.revenue);
    if (!companies.length) return '<div class="ne-no-data">No revenue data available</div>';
    const maxRev = companies[0].revenue;
    return companies.map(c => {
        const pct = Math.max((c.revenue / maxRev) * 100, 2);
        const color = c.is_public ? 'var(--accent)' : 'var(--purple)';
        const quality = c.data_quality === 'low' ? ' (est.)' : '';
        return `<div class="ne-bar-row">
            <span class="ne-bar-label" title="${escHtml(c.name)}">${escHtml(c.name)}</span>
            <div class="ne-bar-track">
                <div class="ne-bar-fill" style="width:${pct}%;background:${color}"></div>
            </div>
            <span class="ne-bar-value">${c.revenue_formatted || '?'}${quality}</span>
        </div>`;
    }).join('');
}

function _neStackedBar(buckets, config) {
    if (!buckets || !buckets.length) return '';
    const total = buckets.reduce((s, b) => s + b.count, 0);
    if (!total) return '<div class="ne-no-data">No data available</div>';

    const segments = buckets.map((b, i) => {
        const pct = (b.count / total) * 100;
        const cfg = config[i] || {color: 'var(--text-muted)'};
        return pct > 0 ? `<div class="ne-stacked-segment" style="width:${pct}%;background:${cfg.color}" title="${b.label}: ${b.count}"></div>` : '';
    }).join('');

    const legend = buckets.map((b, i) => {
        const cfg = config[i] || {color: 'var(--text-muted)', label: b.label};
        return b.count > 0 ? `<span class="ne-legend-item"><span class="ne-legend-dot" style="background:${cfg.color}"></span>${cfg.label} (${b.count})</span>` : '';
    }).join('');

    return `<div class="ne-stacked-bar">${segments}</div><div class="ne-legend">${legend}</div>`;
}

// --- Pane 3: Market Summary ---

function renderSummaryPane(campaignId) {
    const c = _findCampaignById(campaignId);
    if (!c) return;

    const sumContent = document.getElementById('pane-summary-content');
    const sumEmpty = document.getElementById('pane-summary-empty');
    if (!sumContent) return;

    const prospects = (c.prospects || []).sort((a, b) =>
        (_getScore(b)?.overall_score || 0) - (_getScore(a)?.overall_score || 0));
    const scored = prospects.filter(p => _hasScore(p));

    // Handle empty campaigns
    if (c.status === 'empty' || (!prospects.length && c.status !== 'running')) {
        if (sumEmpty) sumEmpty.style.display = 'none';
        sumContent.style.display = 'block';
        sumContent.innerHTML = `<div class="pane-empty">
            <div class="icon">&#128269;</div>
            <div>No companies found</div>
            <div class="subtitle">Try different search terms or broaden the niche.</div>
        </div>`;
        return;
    }

    const statusText = c.status === 'complete' ? 'Complete' : c.status === 'running' ? 'Running...' : c.status === 'error' ? 'Error' : c.status;
    let createdDate = '';
    if (c.created_at) {
        const d = new Date(c.created_at.replace(' ', 'T') + (c.created_at.includes('Z') || c.created_at.includes('+') ? '' : 'Z'));
        createdDate = isNaN(d.getTime()) ? '' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    // Score tier distribution
    const tiers = { prime: 0, strong: 0, possible: 0, weak: 0 };
    scored.forEach(p => { tiers[_prospectTierClass(_getScore(p)?.overall_score || 0)]++; });

    // Tier distribution bar
    const tierTotal = scored.length || 1;
    const tierBarHtml = scored.length > 0 ? `
        <div style="display:flex;height:8px;border-radius:4px;overflow:hidden;margin-bottom:6px">
            ${tiers.prime > 0 ? `<div style="width:${(tiers.prime/tierTotal)*100}%;background:var(--green)" title="${tiers.prime} Prime"></div>` : ''}
            ${tiers.strong > 0 ? `<div style="width:${(tiers.strong/tierTotal)*100}%;background:var(--accent)" title="${tiers.strong} Strong"></div>` : ''}
            ${tiers.possible > 0 ? `<div style="width:${(tiers.possible/tierTotal)*100}%;background:var(--yellow)" title="${tiers.possible} Possible"></div>` : ''}
            ${tiers.weak > 0 ? `<div style="width:${(tiers.weak/tierTotal)*100}%;background:var(--red)" title="${tiers.weak} Weak"></div>` : ''}
        </div>
        <div style="display:flex;gap:12px;font-size:10px;color:var(--text-muted)">
            ${tiers.prime > 0 ? `<span><span style="color:var(--green);font-weight:600">${tiers.prime}</span> Prime</span>` : ''}
            ${tiers.strong > 0 ? `<span><span style="color:var(--accent);font-weight:600">${tiers.strong}</span> Strong</span>` : ''}
            ${tiers.possible > 0 ? `<span><span style="color:var(--yellow);font-weight:600">${tiers.possible}</span> Possible</span>` : ''}
            ${tiers.weak > 0 ? `<span><span style="color:var(--red);font-weight:600">${tiers.weak}</span> Weak</span>` : ''}
        </div>` : '';

    // Fit levels legend
    const fitLegendHtml = `
        <div class="fit-legend">
            <span class="fit-legend-item"><span class="fit-dot" style="background:var(--green)"></span>80+ Prime</span>
            <span class="fit-legend-item"><span class="fit-dot" style="background:var(--accent)"></span>60-79 Strong</span>
            <span class="fit-legend-item"><span class="fit-dot" style="background:var(--yellow)"></span>40-59 Possible</span>
            <span class="fit-legend-item"><span class="fit-dot" style="background:var(--red)"></span>20-39 Weak</span>
            <span class="fit-legend-item"><span class="fit-dot" style="background:var(--text-muted)"></span>0-19 Not a Fit</span>
        </div>`;

    // Ranked results
    const rankedHtml = _buildRankedListHtml(scored);

    // Agent Insights
    const insight = c.insight;
    let insightHtml = '';
    const _priorityIcons = [
        { icon: '&#8593;', bg: 'rgba(22,163,74,0.12)', color: 'var(--green)' },   // trending up
        { icon: '&#36;', bg: 'rgba(59,130,246,0.12)', color: 'var(--accent)' },    // dollar
        { icon: '&#9678;', bg: 'rgba(168,85,247,0.12)', color: 'var(--purple)' },  // target
    ];
    if (insight) {
        const summaryP = insight.vertical_summary ? `<div class="agent-insights-summary">${escHtml(insight.vertical_summary)}</div>` : '';
        const prioritiesHtml = (insight.top_3_priorities || []).map((p, i) => {
            const ic = _priorityIcons[i] || _priorityIcons[2];
            return `<li><span class="priority-icon" style="background:${ic.bg};color:${ic.color}">${ic.icon}</span><div class="priority-title">${escHtml(p.title)}</div><div class="priority-desc">${escHtml(p.description)}</div></li>`;
        }).join('');

        // Market Signal Diagnostics — dynamically derived from lens dimensions
        const _diagIcons = [
            { icon: '&#128737;', bg: 'rgba(239,68,68,0.1)', color: 'var(--red)' },
            { icon: '&#128200;', bg: 'rgba(22,163,74,0.1)', color: 'var(--green)' },
            { icon: '&#127916;', bg: 'rgba(168,85,247,0.1)', color: 'var(--purple)' },
            { icon: '&#128176;', bg: 'rgba(59,130,246,0.1)', color: 'var(--accent)' },
        ];
        // Build diagnostics from whatever dimensions the score has
        const sampleScore = _getScore(scored[0]);
        const dims = sampleScore?._dimensions || Object.keys(sampleScore?.sub_scores || {}).map(k => ({
            key: k, label: k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()), weight: 0.2,
        }));
        const signalBadges = dims.slice(0, 4).map((dim, i) => {
            const ic = _diagIcons[i % _diagIcons.length];
            const aboveThreshold = scored.filter(p => {
                const sc = _getScore(p);
                return (sc?.sub_scores?.[dim.key]?.score || 0) >= 50;
            }).length;
            return { ...ic, title: dim.label, sub: `${aboveThreshold}/${scored.length} score 50+ on ${dim.label}` };
        });
        const signalHtml = signalBadges.map(b =>
            `<div class="signal-badge"><div class="signal-badge-icon" style="background:${b.bg};color:${b.color}">${b.icon}</div><div><div class="signal-badge-title">${b.title}</div><div class="signal-badge-sub">${b.sub}</div></div></div>`
        ).join('');

        insightHtml = `
            <div class="cv-section">
                <div class="cv-section-title">Agent Insights</div>
                <div class="agent-insights">
                    ${summaryP}
                    ${prioritiesHtml ? `<ul class="agent-insights-priorities">${prioritiesHtml}</ul>` : ''}
                </div>
            </div>
            <div class="cv-section">
                <div class="cv-section-title">Market Signal Diagnostics</div>
                <div class="signal-diagnostics">${signalHtml}</div>
            </div>`;
    } else if (scored.length > 0) {
        const willGenerate = c.status === 'complete';
        insightHtml = `
            <div class="cv-section">
                <div class="cv-section-title">Agent Insights</div>
                <div id="agent-insights-placeholder" class="agent-insights-loading">
                    ${willGenerate
                        ? '<div class="spinner"></div> Generating insights...'
                        : '<span style="color:var(--text-muted);font-size:12px">Insights will generate once pipeline completes</span>'}
                </div>
            </div>`;
    }

    sumEmpty.style.display = 'none';
    sumContent.style.display = 'block';
    const breadcrumbHtml = _buildBreadcrumb(campaignId);
    sumContent.innerHTML = `
        <div class="campaign-view">
            ${breadcrumbHtml}
            <div class="campaign-view-header">
                <div>
                    <h2 class="campaign-view-title">${escHtml(c.seed_company ? `Similar to ${c.seed_company}` : (c.name || c.niche))}</h2>
                    <div class="campaign-view-meta">
                        ${createdDate} &bull; ${statusText} &bull; ${prospects.length} companies
                    </div>
                </div>
            </div>

            ${c.niche_eval ? renderNicheEvaluation(c.niche_eval, prospects, c) : ''}

            ${!c.niche_eval ? (scored.length > 0 ? `
            <div class="cv-section">
                <div class="cv-section-title">Score Distribution</div>
                ${tierBarHtml}
                ${fitLegendHtml}
            </div>

            ${insightHtml}

            <div class="cv-section">
                <div class="cv-section-title">Results</div>
                <div style="font-size:10px;color:var(--text-muted);margin-bottom:8px">Click a company for detailed analysis</div>
                <div id="pane-summary-ranked-list">${rankedHtml}</div>
            </div>
            ${(() => {
                const unscoredProspects = prospects.filter(p => !_hasScore(p));
                return unscoredProspects.length > 0 ? `<div class="ne-divider"></div>${_buildDiscoveryListHtml(unscoredProspects, c)}` : '';
            })()}
            ` : _buildDiscoveryListHtml(prospects, c)) : ''}

            ${c.niche_eval && scored.length > 0 ? `
            <div class="ne-divider"></div>
            <div class="cv-section">
                <div class="cv-section-title">Score Distribution</div>
                ${tierBarHtml}
                ${fitLegendHtml}
            </div>
            ${insightHtml}
            <div class="cv-section">
                <div class="cv-section-title">Scored Results</div>
                <div style="font-size:10px;color:var(--text-muted);margin-bottom:8px">Click a company for detailed analysis</div>
                <div id="pane-summary-ranked-list">${rankedHtml}</div>
            </div>
            ` : ''}

            ${_buildChildCampaignsHtml(c)}
        </div>
    `;

    // Auto-trigger insight generation if missing
    if (!insight && scored.length > 0 && c.status === 'complete') {
        _autoGenerateInsight(campaignId);
    }
}

function _buildDiscoveryListHtml(prospects, campaignNode) {
    if (!prospects || prospects.length === 0) {
        return '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px">No prospects discovered yet.</div>';
    }
    // Clear selection state when rebuilding
    _selectedForResearch.clear();
    const seedCompany = campaignNode && campaignNode.seed_company;

    const items = prospects.map(p => {
        const name = p.company_name || '?';
        const desc = p.company_description || '';
        const disc = p.discovery || {};
        const size = disc.estimated_size || '';
        const evidence = disc.evidence || [];
        const vstatus = p.validation_status || 'valid';
        const vreason = p.validation_reason || '';
        const isLimited = vstatus === 'limited' || vstatus === 'http_403' || vstatus === 'connection_failed';
        const isSkipped = vstatus !== 'valid' && !isLimited;
        const vIcon = vstatus === 'valid' ? '&#10003;' : isLimited ? '&#9888;' : '';
        const vColor = vstatus === 'valid' ? 'var(--green)' : isLimited ? 'var(--yellow)' : '';
        const limitedMsg = isLimited ? (vstatus === 'http_403' ? 'Website blocked (403)' : vstatus === 'connection_failed' ? 'Website unreachable' : vreason || 'Limited data') : '';
        const ancestryBadge = seedCompany ? `<span class="ancestry-badge">Similar to ${escHtml(seedCompany)}</span>` : '';
        const dataPayload = JSON.stringify({name, description: desc, evidence}).replace(/'/g, '&#39;');
        return `<div class="discovery-list-item${isSkipped ? ' skipped' : ''}" data-company-name="${escHtml(name)}" data-company-payload='${dataPayload}' style="cursor:pointer;padding:10px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px;position:relative${isSkipped ? ';opacity:0.5' : ''}">
            ${!isSkipped ? `<input type="checkbox" class="discovery-select-cb" onclick="event.stopPropagation();_toggleResearchSelection('${escHtml(name).replace(/'/g, "\\'")}', this)" style="position:absolute;top:10px;right:10px;width:16px;height:16px;accent-color:var(--purple);cursor:pointer">` : ''}
            ${ancestryBadge}
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:${desc ? '4px' : '0'};padding-right:${isSkipped ? '0' : '28px'}">
                ${vIcon ? `<span style="color:${vColor};font-size:12px">${vIcon}</span>` : ''}
                <span style="font-weight:600;font-size:13px;color:var(--text-primary)">${escHtml(name)}</span>
                ${size ? `<span class="company-card-size" style="margin:0">${escHtml(size)}</span>` : ''}
            </div>
            ${desc ? `<div style="font-size:11px;color:var(--text-muted);line-height:1.4;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;${!isSkipped ? 'padding-right:28px' : ''}">${escHtml(desc)}</div>` : ''}
            ${isLimited ? `<div style="font-size:10px;color:var(--yellow);margin-top:2px">&#9888; ${escHtml(limitedMsg)} &mdash; financial &amp; sentiment analysis still available</div>` : ''}
            ${isSkipped ? `<div style="font-size:10px;color:var(--text-muted);margin-top:2px">No valid website found</div>` : ''}
        </div>`;
    }).join('');
    return `
        <div class="cv-section">
            <div class="cv-section-title">Discovered Companies (${prospects.length})</div>
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:8px">Select companies to send to Research for scoring.</div>
            ${items}
        </div>
        <div class="send-to-research-bar" id="summary-research-bar" style="display:none">
            <span class="str-count">0/3 selected</span>
            <span class="str-label" style="font-size:11px;color:var(--text-muted)">Score with:</span>
            ${_buildLensSelectHtml('summary-lens-select')}
            <button class="str-btn" onclick="_sendToResearch('summary-lens-select')" disabled>Send to Research</button>
        </div>`;
}

function _buildRankedListHtml(scored) {
    return scored.map(p => {
        const _sc = _getScore(p);
        const s = _sc?.overall_score || 0;
        const label = _sc?.overall_label || '';
        const isLimited = p.validation_status && p.validation_status !== 'valid';
        const isActive = activeProspectName === p.company_name ? ' active' : '';
        return `<div class="cv-result-row${isActive}" data-company="${escHtml(p.company_name)}">
            <span class="cv-result-score" style="color:${_dimColor(s)}">${s}</span>
            <span class="cv-result-name">${escHtml(p.company_name)}${isLimited ? ' <span class="limited-badge">Limited</span>' : ''}</span>
            <span class="cv-result-label" style="color:${_dimColor(s)}">${escHtml(label)}</span>
        </div>`;
    }).join('');
}

let _insightGenerating = {};
async function _autoGenerateInsight(campaignId) {
    if (_insightGenerating[campaignId]) return; // prevent duplicate concurrent calls
    _insightGenerating[campaignId] = true;
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 min client timeout
        const resp = await fetch(`/api/campaigns/${campaignId}/insight`, {
            method: 'POST',
            signal: controller.signal,
        });
        clearTimeout(timeoutId);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        // Update local cache
        const c = allCampaigns.find(x => x.id === campaignId);
        if (c) c.insight = data.insight || data;
        // Re-render insight section if this campaign is still active
        if (activeCampaignId === campaignId) {
            renderSummaryPane(campaignId);
        }
    } catch (err) {
        console.error('Failed to generate insight:', err);
        const ph = document.getElementById('agent-insights-placeholder');
        if (ph) {
            const msg = err.name === 'AbortError'
                ? 'Insight generation timed out. Click campaign again to retry.'
                : 'Insights unavailable. Click campaign again to retry.';
            ph.innerHTML = `<span style="color:var(--text-muted);font-size:12px">${msg}</span>`;
        }
    } finally {
        delete _insightGenerating[campaignId];
    }
}

// ===================== DISCOVERY TREE HELPERS =====================

/** Find a campaign by id — searches roots AND their children arrays. */
function _findCampaignById(campaignId) {
    for (const c of allCampaigns) {
        if (c.id === campaignId) return c;
        for (const ch of (c.children || [])) {
            if (ch.id === campaignId) return ch;
        }
    }
    return null;
}

/** Get depth of a campaign in its tree (root = 0). */
function _getNodeDepth(campaignId) {
    const c = _findCampaignById(campaignId);
    if (!c || !c.parent_campaign_id) return 0;
    return 1 + _getNodeDepth(c.parent_campaign_id);
}

/** Build clickable breadcrumb for child campaign nodes. */
function _buildBreadcrumb(campaignId) {
    const nodes = [];
    let cur = _findCampaignById(campaignId);
    while (cur) {
        nodes.unshift(cur);
        if (!cur.parent_campaign_id) break;
        cur = _findCampaignById(cur.parent_campaign_id);
    }
    if (nodes.length <= 1) return '';
    return `<div class="tree-breadcrumb">${nodes.map((n, i) => {
        const label = n.seed_company ? `Similar to ${escHtml(n.seed_company)}` : escHtml(n.name || n.niche);
        const isCurrent = i === nodes.length - 1;
        return `<span class="breadcrumb-seg${isCurrent ? ' current' : ''}" ${isCurrent ? '' : `onclick="_selectTreeNode(${n.id})"`}>${label}</span>`;
    }).join('<span class="breadcrumb-sep">/</span>')}</div>`;
}

function _buildChildCampaignsHtml(campaign) {
    // Find child campaigns (Find Similar explorations) for this campaign
    const children = (campaign.children || []).filter(ch => ch.parent_campaign_id === campaign.id);
    if (!children.length) return '';

    const items = children.map(ch => {
        const label = ch.seed_company ? `Similar to ${escHtml(ch.seed_company)}` : escHtml(ch.name || ch.niche);
        const count = ch.prospect_count || (ch.prospects || []).length || 0;
        const statusBadge = ch.status === 'running'
            ? '<span class="pane-status-badge running" style="font-size:9px;padding:1px 5px">Running</span>'
            : ch.status === 'empty'
            ? '<span class="pane-status-badge" style="font-size:9px;padding:1px 5px;background:rgba(107,114,128,0.15);color:#9ca3af">Empty</span>'
            : '';
        return `<div class="discovery-list-item" style="cursor:pointer;padding:10px 12px;border:1px solid rgba(168,85,247,0.2);border-radius:8px;margin-bottom:6px;background:rgba(168,85,247,0.03)"
            onclick="_selectTreeNode(${ch.id})">
            <div style="display:flex;align-items:center;gap:8px">
                <span style="color:var(--purple);font-size:13px">&#128279;</span>
                <span style="font-weight:600;font-size:13px;color:var(--text-primary)">${label}</span>
                <span style="font-size:11px;color:var(--purple)">${count} companies</span>
                ${statusBadge}
            </div>
        </div>`;
    }).join('');

    return `<div class="ne-divider"></div>
        <div class="cv-section">
            <div class="cv-section-title">Related Explorations</div>
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:8px">Click to view "Find Similar" results</div>
            ${items}
        </div>`;
}


// ---- Execution log rendering (summary + expandable detail) ----

/** Toggle expanded detail on an execution step block (double-click handler). */
function _toggleExecDetail(el) {
    const detail = el.querySelector('.exec-detail');
    if (detail) detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
}

/** Build full execution log HTML — summary by default, double-click expands detail. */
function _buildExecutionLogHtml(executionLog, prospects) {
    if (!executionLog || !executionLog.length) return '';
    const log = executionLog;

    const sections = [];

    // --- Seed Profile (for "Find Similar" mode) ---
    const seedProfile = log.find(e => e.type === 'seed_profile');
    if (seedProfile) {
        const p = seedProfile.profile;
        const company = seedProfile.company || '?';
        const summaryText = p
            ? `${p.industry || '?'} · ${p.scale || '?'} · ${p.client_type || '?'}`
            : 'Profile lookup failed';
        const detailHtml = p ? `
            <div class="exec-detail" style="display:none;margin-top:6px;font-size:10px;color:var(--text-muted);line-height:1.6">
                <div><strong>Industry:</strong> ${escHtml(p.industry || 'Unknown')}</div>
                <div><strong>Scale:</strong> ${escHtml(p.scale || 'Unknown')}</div>
                <div><strong>Client type:</strong> ${escHtml(p.client_type || 'Unknown')}</div>
                <div><strong>Services:</strong> ${escHtml(Array.isArray(p.services) ? p.services.join(', ') : (p.services || 'Unknown'))}</div>
            </div>
        ` : '';
        sections.push(`<div class="exec-step" ondblclick="_toggleExecDetail(this)" title="Double-click for detail" style="cursor:pointer">
            <div style="display:flex;align-items:center;gap:6px">
                <span style="color:var(--purple);font-size:10px">&#128100;</span>
                <span class="exec-step-title">Seed Profile: ${escHtml(company)}</span>
            </div>
            <div class="exec-step-summary">${escHtml(summaryText)}</div>
            ${detailHtml}
        </div>`);
    }

    // --- Search Queries ---
    const plan = log.find(e => e.type === 'discovery_plan' && e.total_queries > 0);
    const searches = log.filter(e => e.type === 'search_done');
    const summary = log.find(e => e.type === 'search_complete');
    if (searches.length) {
        const totalResults = summary ? summary.total_results : searches.reduce((s, e) => s + (e.results_count || 0), 0);
        const uniqueResults = summary ? summary.unique_results : totalResults;
        const srcCounts = {};
        searches.forEach(s => { srcCounts[s.source] = (srcCounts[s.source] || 0) + 1; });
        const srcSummary = Object.entries(srcCounts).map(([k, v]) => `${v} ${_srcLabels[k] || k}`).join(', ');
        const summaryText = `${searches.length} queries (${srcSummary}) → ${uniqueResults} unique results`;

        const detailRows = searches.map(s => {
            const color = _srcColors[s.source] || '#6b7280';
            const label = _srcLabels[s.source] || s.source_label || s.source;
            return `<div style="display:flex;align-items:center;gap:6px;font-size:10px;line-height:1.8">
                <span style="color:var(--green);font-size:9px">&#10003;</span>
                <span style="color:${color};font-weight:600;min-width:70px">${escHtml(label)}</span>
                <span style="color:var(--text-muted);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(s.query || '')}</span>
                <span style="color:var(--text-muted);font-size:9px;white-space:nowrap">${s.results_count || 0}</span>
            </div>`;
        }).join('');

        sections.push(`<div class="exec-step" ondblclick="_toggleExecDetail(this)" title="Double-click for detail" style="cursor:pointer">
            <div style="display:flex;align-items:center;gap:6px">
                <span style="color:var(--accent);font-size:10px">&#128269;</span>
                <span class="exec-step-title">Search</span>
            </div>
            <div class="exec-step-summary">${escHtml(summaryText)}</div>
            <div class="exec-detail" style="display:none;margin-top:6px">
                ${detailRows}
                ${summary ? `<div style="font-size:10px;color:var(--text-muted);margin-top:4px;padding-top:4px;border-top:1px solid var(--border)">Deduplicated: ${summary.total_results} total → ${summary.unique_results} unique</div>` : ''}
            </div>
        </div>`);
    }

    // --- LLM Extraction ---
    const extracted = log.find(e => e.type === 'extracted');
    if (extracted) {
        const names = extracted.companies || [];
        sections.push(`<div class="exec-step" ondblclick="_toggleExecDetail(this)" title="Double-click for detail" style="cursor:pointer">
            <div style="display:flex;align-items:center;gap:6px">
                <span style="color:var(--purple);font-size:10px">&#127919;</span>
                <span class="exec-step-title">AI Extraction</span>
            </div>
            <div class="exec-step-summary">Extracted ${names.length} companies from search results</div>
            <div class="exec-detail" style="display:none;margin-top:6px;font-size:10px;color:var(--text-muted);line-height:1.6">${escHtml(names.join(', '))}</div>
        </div>`);
    }

    // --- Validation ---
    const validations = log.filter(e => e.type === 'validated');
    if (validations.length) {
        const vValid = validations.filter(v => !v.limited && v.valid).length;
        const vLimited = validations.filter(v => v.limited).length;
        const vSkipped = validations.filter(v => !v.valid && !v.limited).length;
        const summaryText = `${vValid} valid${vLimited ? `, ${vLimited} limited` : ''}${vSkipped ? `, ${vSkipped} skipped` : ''}`;

        const detailRows = validations.map(v => {
            const icon = v.limited ? '<span style="color:var(--yellow)">&#9888;</span>'
                       : v.valid ? '<span style="color:var(--green)">&#10003;</span>'
                       : '<span style="color:var(--red)">&times;</span>';
            const reason = v.reason && v.reason !== 'OK' ? ` — ${escHtml(v.reason)}` : '';
            return `<div style="font-size:10px;line-height:1.8;display:flex;align-items:center;gap:6px">
                ${icon}
                <span style="color:var(--text-secondary)">${escHtml(v.company || '?')}</span>
                <span style="color:var(--text-muted)">${reason}</span>
            </div>`;
        }).join('');

        sections.push(`<div class="exec-step" ondblclick="_toggleExecDetail(this)" title="Double-click for detail" style="cursor:pointer">
            <div style="display:flex;align-items:center;gap:6px">
                <span style="color:var(--green);font-size:10px">&#10003;</span>
                <span class="exec-step-title">Validation</span>
            </div>
            <div class="exec-step-summary">${escHtml(summaryText)}</div>
            <div class="exec-detail" style="display:none;margin-top:6px">${detailRows}</div>
        </div>`);
    } else if (prospects && prospects.length) {
        // Fallback: reconstruct from prospect data if no validation events in log
        const _ls = ['limited', 'http_403', 'connection_failed'];
        const v = prospects.filter(p => p.validation_status === 'valid').length;
        const l = prospects.filter(p => _ls.includes(p.validation_status)).length;
        const sk = prospects.filter(p => p.validation_status && p.validation_status !== 'valid' && !_ls.includes(p.validation_status)).length;
        sections.push(`<div class="exec-step">
            <div style="display:flex;align-items:center;gap:6px">
                <span style="color:var(--green);font-size:10px">&#10003;</span>
                <span class="exec-step-title">Validation</span>
            </div>
            <div class="exec-step-summary">${v} valid${l ? `, ${l} limited` : ''}${sk ? `, ${sk} skipped` : ''}</div>
        </div>`);
    }

    return `<div style="margin-top:8px;display:flex;flex-direction:column;gap:3px">${sections.join('')}</div>`;
}

/** Build inline execution details using the PipelineTree renderer. */
function _buildNodeExecutionHtml(node) {
    const prospects = node.prospects || [];
    if (!prospects.length && node.status !== 'empty') return '';

    if (node.status === 'empty') {
        return `<div style="margin-top:8px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary)">
            <div style="font-size:11px;color:var(--text-muted)">No companies matched this search.</div>
        </div>`;
    }

    // Use new tree renderer if execution_log exists
    if (node.execution_log && node.execution_log.length) {
        const label = node.seed_company ? `Similar to ${node.seed_company}` : (node.name || node.niche || 'Discovery');
        const treeNodes = _discoverLogToTree(node.execution_log, prospects, label);
        // Render to string: create temp container, render, extract innerHTML
        const tmp = document.createElement('div');
        renderPipelineTree(treeNodes, tmp);
        return `<div style="margin-top:8px">${tmp.innerHTML}</div>`;
    }

    // Fallback to legacy exec-step rendering
    return _buildExecutionLogHtml(node.execution_log, prospects);
}

/** Build search log HTML using PipelineTree for standalone campaigns (renderExecutionPane). */
function _buildSearchLogHtml(executionLog) {
    if (!executionLog || !executionLog.length) return '';
    const treeNodes = _discoverLogToTree(executionLog, null, 'Search Activity');
    // Render just the children (skip the root wrapper for inline use)
    if (treeNodes.length && treeNodes[0].children && treeNodes[0].children.length) {
        const tmp = document.createElement('div');
        // Render the children directly without the root wrapper
        const childNodes = treeNodes[0].children;
        tmp.innerHTML = `<div class="ptree">${childNodes.map(n => _renderPTreeNode(n, 0)).join('')}</div>`;
        return tmp.innerHTML;
    }
    return _buildExecutionLogHtml(executionLog, null);
}

/** Render the discovery tree in Pane 2 for a campaign with children. */
function renderDiscoveryTree(rootCampaignId) {
    const mapEl = document.getElementById('pipeline-map');
    const emptyEl = document.getElementById('pane-execution-empty');
    if (!mapEl) return;
    if (emptyEl) emptyEl.style.display = 'none';
    mapEl.style.display = 'block';

    const root = allCampaigns.find(x => x.id === rootCampaignId);
    if (!root) return;

    // Flatten tree: root + children
    const allNodes = [root, ...(root.children || [])];
    const activeId = _activeTreeNodeId || rootCampaignId;

    // Build a children map for tree-line rendering
    const childrenOf = {};
    allNodes.forEach(n => {
        const pid = n.parent_campaign_id || null;
        if (!childrenOf[pid]) childrenOf[pid] = [];
        childrenOf[pid].push(n);
    });

    // Recursive render
    function _renderNode(node, depth) {
        const isActive = node.id === activeId;
        const indent = depth * 24;
        const icon = node.seed_company ? '&#128279;' : '&#128269;';
        const label = node.seed_company ? `Similar to ${escHtml(node.seed_company)}` : escHtml(node.name || node.niche);
        const count = node.prospect_count || (node.prospects || []).length || 0;
        const statusCls = node.status === 'complete' ? 'done' : node.status === 'running' ? 'running' : '';
        const statusBadge = node.status === 'running'
            ? '<span class="pane-status-badge running" style="font-size:9px;padding:1px 6px">Running</span>'
            : node.status === 'error'
            ? '<span class="pane-status-badge error" style="font-size:9px;padding:1px 6px">Error</span>'
            : node.status === 'empty'
            ? '<span class="pane-status-badge" style="font-size:9px;padding:1px 6px;background:rgba(107,114,128,0.15);color:#9ca3af">Empty</span>'
            : '';

        // Active node shows expanded execution details; inactive nodes stay compact
        const executionHtml = isActive ? _buildNodeExecutionHtml(node) : '';

        let html = `<div class="tree-node${isActive ? ' active' : ''}" data-campaign-id="${node.id}" onclick="_selectTreeNode(${node.id})" style="margin-left:${indent}px">
            ${depth > 0 ? '<div class="tree-connector-horiz"></div>' : ''}
            <div class="pipeline-node ${statusCls}" style="margin:4px 0;padding:10px 12px;cursor:pointer">
                <div class="pipeline-node-header">
                    <div class="pipeline-node-icon" style="font-size:14px">${icon}</div>
                    <div class="pipeline-node-label" style="font-size:12px">${label}</div>
                </div>
                <div class="pipeline-node-meta" style="font-size:10px;margin-top:3px;display:flex;gap:8px;align-items:center">
                    <span style="color:var(--purple)">${count} companies</span>
                    ${statusBadge}
                </div>
                ${executionHtml}
            </div>
        </div>`;

        // Render children recursively
        const kids = childrenOf[node.id] || [];
        for (const kid of kids) {
            html += _renderNode(kid, depth + 1);
        }
        return html;
    }

    mapEl.innerHTML = _renderNode(root, 0);

    // Update status badge
    const badge = document.getElementById('pane-execution-status');
    if (badge) {
        badge.textContent = 'Tree';
        badge.className = 'pane-status-badge';
        badge.style.cssText = 'background:rgba(168,85,247,0.15);color:var(--purple)';
    }
}

/** Handle click on a tree node — update Pane 3 to show that node's companies. */
function _selectTreeNode(campaignId) {
    _activeTreeNodeId = campaignId;
    if (_activeTreeRootId) renderDiscoveryTree(_activeTreeRootId);
    renderSummaryPane(campaignId);
    clearDetailPane();
}

// Real-time summary update during live pipeline (called on each 'scored' SSE event)
function _updateLiveSummary(ev) {
    const sumContent = document.getElementById('pane-summary-content');
    const sumEmpty = document.getElementById('pane-summary-empty');
    if (!sumContent) return;

    // Show pane on first scored event
    if (sumEmpty && sumEmpty.style.display !== 'none') {
        sumEmpty.style.display = 'none';
        sumContent.style.display = 'block';
        sumContent.innerHTML = `<div class="campaign-view">
            <div class="cv-section">
                <div class="cv-section-title">Results (Live)</div>
                <div style="font-size:10px;color:var(--text-muted);margin-bottom:8px">Companies are ranked as they score</div>
                <div id="pane-summary-ranked-list"></div>
            </div>
        </div>`;
    }

    // Insert into ranked list in sorted position (descending score)
    const listEl = document.getElementById('pane-summary-ranked-list');
    if (!listEl) return;

    const score = ev.overall_score || 0;
    const label = ev.label || '';
    const name = ev.company || '';
    const color = _dimColor(score);
    const rowHtml = `<div class="cv-result-row" data-company="${escHtml(name)}" data-score="${score}">
        <span class="cv-result-score" style="color:${color}">${score}</span>
        <span class="cv-result-name">${escHtml(name)}</span>
        <span class="cv-result-label" style="color:${color}">${escHtml(label)}</span>
    </div>`;

    // Find insertion point (sorted descending)
    const existing = listEl.querySelectorAll('.cv-result-row');
    let inserted = false;
    for (const row of existing) {
        const rowScore = parseInt(row.dataset.score || '0', 10);
        if (score > rowScore) {
            row.insertAdjacentHTML('beforebegin', rowHtml);
            inserted = true;
            break;
        }
    }
    if (!inserted) listEl.insertAdjacentHTML('beforeend', rowHtml);
}

function closeProspectDetail() {
    clearDetailPane();
}

async function openProspectDetail(companyName) {
    activeProspectName = companyName;
    // Highlight matching card in Pane 2 pipeline map
    document.querySelectorAll('.company-card').forEach(c => {
        c.classList.toggle('active', c.dataset.companyName === companyName);
    });
    // Highlight matching row in Pane 3 ranked list
    document.querySelectorAll('.cv-result-row').forEach(r => {
        r.classList.toggle('active', r.dataset.company === companyName);
    });

    // Show loading state in Pane 4 immediately
    const detContent = document.getElementById('pane-detail-content');
    const detEmpty = document.getElementById('pane-detail-empty');
    if (detContent && detEmpty) {
        detEmpty.style.display = 'none';
        detContent.style.display = 'block';
        detContent.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;padding:40px;gap:10px;color:var(--text-muted)">
            <div style="width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--purple);border-radius:50%;animation:spin 0.8s linear infinite"></div>
            Loading ${escHtml(companyName)}...
        </div>`;
    }

    // Find the prospect data from campaign lookup or fetch fresh
    let p = _prospectsByName[companyName];
    if (!p || !_hasScore(p)) {
        try {
            const resp = await fetch('/api/ua-targets');
            if (resp.ok) {
                const targets = await resp.json();
                p = targets.find(x => x.company_name === companyName);
                if (p) _prospectsByName[companyName] = p;
            }
        } catch (e) { /* ignore */ }
    }
    if (!p || !_hasScore(p)) {
        // Show discovery blurb — try live pipeline state first, then campaign prospect data
        const discoveryCompany = (_pipelineState.companies || []).find(c => c.name === companyName);
        // Also check campaign data (for sidebar-loaded campaigns + child tree nodes)
        const lookupCampaignId = _activeTreeNodeId || activeCampaignId;
        const lookupCampaign = lookupCampaignId ? _findCampaignById(lookupCampaignId) : null;
        const campaignProspect = !discoveryCompany && lookupCampaign
            ? (lookupCampaign.prospects || []).find(x => x.company_name === companyName)
            : null;

        const disc = campaignProspect?.discovery || null;
        const dc = discoveryCompany || (campaignProspect ? {
            name: campaignProspect.company_name,
            description: disc?.description || campaignProspect.company_description,
            website: campaignProspect.website_url || disc?.website,
            estimated_size: disc?.estimated_size || null,
            why_included: disc?.why_included || null,
            evidence: disc?.evidence || [],
        } : null);

        if (dc && detContent) {
            const website = dc.website || '';
            const evidence = dc.evidence || [];

            // Why included (prominent, separate from sources)
            let whyHtml = '';
            if (dc.why_included) {
                whyHtml = `<div class="why-included-box"><strong>Why this company?</strong>${escHtml(dc.why_included)}</div>`;
            }

            // Evidence sources with type badges
            let evidenceHtml = '';
            if (evidence.length > 0) {
                evidenceHtml = `<div style="margin-top:14px">
                    <div style="font-size:11px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px">Sources</div>
                    ${evidence.map(e => {
                        const srcType = _inferSourceType(e.source_url);
                        return `<div class="evidence-item">
                            <div class="evidence-header">
                                <span class="evidence-source-badge ${srcType}">${srcType}</span>
                                ${e.source_url ? `<a href="${escHtml(e.source_url)}" target="_blank" rel="noopener">${escHtml(e.source_title || (() => { try { return new URL(e.source_url).hostname; } catch { return e.source_url; } })())}</a>` : `<span style="color:var(--text-secondary);font-size:12px">${escHtml(e.source_title || 'Unknown source')}</span>`}
                            </div>
                            ${e.snippet ? `<div class="evidence-snippet">${escHtml(e.snippet)}</div>` : ''}
                        </div>`;
                    }).join('')}
                </div>`;
            }

            // "Find Similar" button — show if depth < 3 and pipeline not running
            const treeDepth = _getNodeDepth(_activeTreeNodeId || activeCampaignId);
            const canExpand = treeDepth < 3 && !_prospectPipelineRunning;
            const safeName = companyName.replace(/'/g, "\\'").replace(/"/g, '&quot;');
            const findSimilarHtml = canExpand
                ? `<div style="margin-top:20px;padding-top:16px;border-top:1px solid var(--border)">
                    <button class="find-similar-btn" onclick="runFindSimilar('${safeName}')">
                        &#128279; Find Similar Companies
                    </button>
                    <div style="font-size:10px;color:var(--text-muted);margin-top:4px">
                        Discover companies similar to ${escHtml(companyName)}
                    </div>
                </div>`
                : (treeDepth >= 3
                    ? `<div style="margin-top:16px;font-size:11px;color:var(--text-muted)">Max expansion depth reached (3 levels)</div>`
                    : '');

            detContent.innerHTML = `<div style="padding:24px">
                <h2 style="margin-bottom:8px;font-size:18px">${escHtml(companyName)}</h2>
                ${dc.description ? `<p style="color:var(--text-secondary);font-size:13px;margin-bottom:10px;line-height:1.5">${escHtml(dc.description)}</p>` : ''}
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
                    ${dc.estimated_size ? `<span class="company-card-size">${escHtml(dc.estimated_size)}</span>` : ''}
                    ${website ? `<a href="${escHtml(website.startsWith('http') ? website : 'https://' + website)}" target="_blank" style="color:var(--accent);font-size:12px">${escHtml(website)}</a>` : ''}
                </div>
                ${whyHtml}
                ${evidenceHtml}
                ${findSimilarHtml}
            </div>`;
            detEmpty.style.display = 'none';
            detContent.style.display = 'block';
            return;
        }
        if (detContent) detContent.innerHTML = `<div style="padding:40px;text-align:center;color:var(--text-muted)">
            <div style="font-size:24px;margin-bottom:8px">&#8987;</div>
            No discovery data for ${escHtml(companyName)}.
        </div>`;
        return;
    }

    const fit = _getScore(p);
    const score = fit.overall_score || 0;
    const tier = _prospectTierClass(score);
    const sub = fit.sub_scores || {};
    const snap = fit.company_snapshot || {};

    const analysesUsed = fit._analyses_used || {};

    const dims = (fit._dimensions || [
        { key: 'financial_capacity',      label: 'Financial Capacity',      weight: 0.25 },
        { key: 'advertising_maturity',    label: 'Paid Media Footprint',    weight: 0.20 },
        { key: 'growth_trajectory',       label: 'Growth Trajectory',       weight: 0.20 },
        { key: 'creative_readiness',      label: 'Video Asset Readiness',   weight: 0.20 },
        { key: 'channel_expansion_intent',label: 'Channel Expansion Intent',weight: 0.15 },
    ]);

    const _dimDisplayLabel = {
        'advertising_maturity': 'Paid Media Footprint',
        'creative_readiness': 'Video Asset Readiness',
    };
    // Tooltips from lens config rubric descriptions (if present), else generic
    const _dimTooltips = {};
    dims.forEach(d => {
        if (d.rubric_description) _dimTooltips[d.key] = d.rubric_description;
    });

    // Collect all sources across dimensions for the Analysis Sources section
    const allSources = [];

    function _renderSignal(sig) {
        // Handle both old (string) and new ({text, url}) formats
        if (typeof sig === 'string') {
            // Auto-detect URLs in plain string signals
            const urlMatch = sig.match(/https?:\/\/[^\s)]+/);
            if (urlMatch) {
                const url = urlMatch[0];
                const text = sig.replace(url, '').trim() || url;
                allSources.push({ text, url });
                return `<a class="icp-signal-tag" href="${escHtml(url)}" target="_blank" rel="noopener">${escHtml(text)}</a>`;
            }
            return `<span class="icp-signal-tag">${escHtml(sig)}</span>`;
        }
        const text = sig.text || sig;
        const url = sig.url;
        if (url) {
            allSources.push({ text, url });
            return `<a class="icp-signal-tag" href="${escHtml(url)}" target="_blank" rel="noopener">${escHtml(text)}</a>`;
        }
        return `<span class="icp-signal-tag">${escHtml(text)}</span>`;
    }

    let dimCardsHtml = dims.map(d => {
        const ds = sub[d.key] || {};
        const s = ds.score || 0;
        const color = _dimColor(s);
        const wPct = Math.round((d.weight || 0) * 100) + '%';
        const displayLabel = _dimDisplayLabel[d.key] || d.label;
        const tooltip = _dimTooltips[d.key] || '';
        const rationale = ds.rationale || 'No data available';
        const signals = (ds.signals || []).map(sig => _renderSignal(sig)).join('');

        return `<div class="icp-dim-card" onclick="if(!event.target.closest('a')){this.classList.toggle('expanded')}">
            <div class="icp-dim-card-header">
                <span class="dim-chevron">&#9654;</span>
                <span class="icp-dim-name">
                    ${escHtml(displayLabel)}
                    <span class="dim-weight">(${wPct})</span>
                    ${tooltip ? `<span class="icp-dim-tooltip-icon" onclick="event.stopPropagation()">i<span class="dim-tooltip">${escHtml(tooltip)}</span></span>` : ''}
                </span>
                <span class="icp-dim-score-pill" style="color:${color}">${s}</span>
            </div>
            <div class="icp-dim-bar"><div class="icp-dim-fill" style="width:${s}%;background:${color}"></div></div>
            <div class="icp-dim-card-body">
                <div class="icp-dim-rationale">${_renderCitedText(rationale)}</div>
                ${signals ? `<div class="icp-dim-signals">${signals}</div>` : ''}
            </div>
        </div>`;
    }).join('');

    let snapHtml = '';
    const _pillColors = [
        { bg: 'rgba(59,130,246,0.12)', color: '#60a5fa' },
        { bg: 'rgba(168,85,247,0.12)', color: '#c084fc' },
        { bg: 'rgba(22,163,74,0.12)', color: '#4ade80' },
        { bg: 'rgba(234,179,8,0.12)', color: '#facc15' },
        { bg: 'rgba(239,68,68,0.12)', color: '#f87171' },
        { bg: 'rgba(20,184,166,0.12)', color: '#2dd4bf' },
    ];
    function _toPills(arr) {
        return `<div class="snap-pills">${arr.map((v, i) => {
            const c = _pillColors[i % _pillColors.length];
            return `<span class="snap-pill" style="background:${c.bg};color:${c.color}">${escHtml(v)}</span>`;
        }).join('')}</div>`;
    }

    const snapPlain = [
        ['Website', snap.website],
        ['Revenue', snap.estimated_revenue],
        ['Employees', snap.estimated_employees],
        ['Recent Funding', snap.recent_funding],
    ];
    const snapPillFields = [
        ['E-com Platform', snap.ecom_platform ? [snap.ecom_platform] : null],
        ['Ad Channels', snap.primary_ad_channels],
        ['Ad Pixels', snap.ad_pixels_detected],
    ];
    snapHtml = snapPlain.filter(f => f[1]).map(f =>
        `<div class="icp-snap-item">${f[0]}<span>${escHtml(String(f[1]))}</span></div>`
    ).join('');
    const pillRows = snapPillFields.filter(f => f[1] && f[1].length).map(f =>
        `<div class="icp-snap-item" style="grid-column:1/-1">${f[0]}${_toPills(f[1])}</div>`
    ).join('');
    snapHtml += pillRows;

    let risksHtml = (fit.key_risks || []).map(r => `<li>${_renderCitedText(r)}</li>`).join('');

    const cov = fit.signal_coverage || {};
    const confLabel = cov.confidence || '?';
    const confColor = confLabel === 'high' ? 'var(--green)' : confLabel === 'moderate' ? 'var(--yellow)' : 'var(--red)';

    const analysisLabels = { techstack: 'Tech Stack', financial: 'Financial', brand_ad: 'Brand & Ad Intel', sentiment: 'Brand & Ad Intel' };
    let methHtml = '';

    // Deduplicate allSources by URL
    const seenUrls = new Set();
    const uniqueSources = allSources.filter(s => {
        if (seenUrls.has(s.url)) return false;
        seenUrls.add(s.url);
        return true;
    });

    const sourceListHtml = uniqueSources.map(s => `<div style="font-size:12px;padding:4px 0;display:flex;gap:6px;align-items:baseline">
        <span style="color:var(--text-muted);flex-shrink:0">&#8226;</span>
        <a href="${escHtml(s.url)}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;word-break:break-all;font-size:11px">${escHtml(s.text)}</a>
    </div>`).join('');

    // Internal analysis report badges — clickable to open report in Research module
    const reportBadgesHtml = Object.entries(analysesUsed).map(([atype, path]) => {
        const label = analysisLabels[atype] || atype;
        const filename = path ? path.replace(/^reports[\\/\\\\]/, '') : '';
        if (!filename) return '';
        return `<span class="source-badge source-${atype}" style="cursor:pointer;font-size:12px;padding:3px 10px;margin:2px" onclick="event.stopPropagation();switchModule('research');openReport('${escHtml(filename)}')" title="View ${escHtml(label)} report">${escHtml(label)}</span>`;
    }).join('');

    if (uniqueSources.length > 0 || Object.keys(analysesUsed).length > 0) {
        methHtml = `<div class="icp-section">
            <div class="icp-section-title">Analysis Sources</div>
            <div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">
                Confidence: <span style="color:${confColor}">${confLabel}</span>
                &bull; ${Object.keys(analysesUsed).length}/3 analyses completed
            </div>
            ${reportBadgesHtml ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px">${reportBadgesHtml}</div>` : ''}
            ${uniqueSources.length > 0 ? `<div style="margin-top:4px;padding-top:8px;border-top:1px solid var(--border)">
                <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted);margin-bottom:6px;font-weight:600">External Sources (${uniqueSources.length})</div>
                ${sourceListHtml}
            </div>` : ''}
        </div>`;
    } else {
        methHtml = `<div class="icp-section">
            <div class="icp-section-title">Analysis Sources</div>
            <div style="font-size:12px;color:var(--text-muted);padding:12px;background:var(--bg-tertiary);border-radius:8px;border:1px solid var(--border)">
                No analysis data available. Re-score to run fresh analyses.
            </div>
        </div>`;
    }

    // Render into Pane 4
    if (!detContent) return;

    detContent.innerHTML = `<div class="icp-detail">
        <div class="icp-detail-header">
            <div style="text-align:center">
                <div class="icp-big-score ${tier}">
                    <span class="num">${score}</span>
                    <span class="lbl">/100</span>
                </div>
                <div class="icp-score-label-row">
                    <span class="icp-score-type-label">${escHtml(fit._lens_name || 'Prospect Score')}</span>
                    <span class="icp-info-icon">i
                        <span class="icp-info-tooltip">Scored using ${escHtml(fit._lens_name || 'the configured lens')} with weighted dimension analysis.</span>
                    </span>
                </div>
            </div>
            <div class="icp-detail-meta">
                <h2>${escHtml(companyName)}</h2>
                <span class="icp-label-badge" style="color:${_dimColor(score)}">${escHtml(fit.overall_label || '?')}</span>
                <span style="font-size:11px;color:var(--text-muted);margin-left:8px">Confidence: <span style="color:${confColor}">${confLabel}</span> &bull; ${cov.categories_with_data || 0}/${cov.categories_total || 3} analyses</span>
            </div>
            <div class="icp-actions-row">
                <button class="icp-rescore-btn" id="icp-rescore-btn" onclick="rescoreProspect('${encodeURIComponent(companyName)}')">&#8635; Re-score</button>
            </div>
        </div>

        ${fit.recommended_angle ? `<div class="icp-playbook">
            <div class="icp-playbook-header">
                <span class="icp-playbook-icon">&#128218;</span>
                <span class="icp-playbook-label">Outbound Strategy Playbook</span>
            </div>
            <div class="icp-playbook-text">${_renderCitedText(fit.recommended_angle)}</div>
        </div>` : ''}

        <div class="icp-section">
            <div class="icp-section-title">Score Dimensions</div>
            ${dimCardsHtml}
        </div>

        ${snapHtml ? `<div class="icp-section">
            <div class="icp-section-title">Company Snapshot</div>
            <div class="icp-snapshot">${snapHtml}</div>
        </div>` : ''}

        ${risksHtml ? `<div class="icp-section">
            <div class="icp-section-title">Key Risks</div>
            <ul class="icp-risks">${risksHtml}</ul>
        </div>` : ''}

        ${methHtml}
    </div>`;

    const pane = document.getElementById('pane-detail-body');
    if (pane) pane.scrollTop = 0;
    focusPane('pane-detail');
}

let _savedDetailHTML = null;

function toggleDetailFullscreen() {
    const pane = document.getElementById('pane-detail');
    const btn = document.getElementById('detail-expand-btn');
    const detContent = document.getElementById('pane-detail-content');
    if (!pane || !detContent) return;

    const isFs = pane.classList.contains('fullscreen');
    if (isFs) {
        // Exit fullscreen — restore original narrow layout
        pane.classList.remove('fullscreen');
        btn.innerHTML = '&#x26F6;';
        btn.title = 'Expand to fullscreen';
        if (_savedDetailHTML) {
            detContent.innerHTML = _savedDetailHTML;
            _savedDetailHTML = null;
        }
    } else {
        // Enter fullscreen — save original, rebuild as dashboard
        _savedDetailHTML = detContent.innerHTML;
        pane.classList.add('fullscreen');
        btn.innerHTML = '&#x2716;';
        btn.title = 'Exit fullscreen (Esc)';
        _buildProspectDashboard(detContent);
    }
}

function _buildProspectDashboard(container) {
    if (!activeProspectName) return;
    const p = _prospectsByName[activeProspectName];
    if (!p || !_hasScore(p)) return;

    const fit = _getScore(p);
    const score = fit.overall_score || 0;
    const tier = _prospectTierClass(score);
    const sub = fit.sub_scores || {};
    const snap = fit.company_snapshot || {};
    const cov = fit.signal_coverage || {};
    const confLabel = cov.confidence || '?';
    const confColor = confLabel === 'high' ? 'var(--green)' : confLabel === 'moderate' ? 'var(--yellow)' : 'var(--red)';
    const analysesUsed = fit._analyses_used || {};
    const analysisLabels = { techstack: 'Tech Stack', financial: 'Financial', brand_ad: 'Brand & Ad Intel', sentiment: 'Brand & Ad Intel' };

    const _dimDisplayLabel = {
        'advertising_maturity': 'Paid Media Footprint',
        'creative_readiness': 'Video Asset Readiness',
    };
    const dims = (fit._dimensions || [
        { key: 'financial_capacity',      label: 'Financial Capacity',      weight: 0.25 },
        { key: 'advertising_maturity',    label: 'Paid Media Footprint',    weight: 0.20 },
        { key: 'growth_trajectory',       label: 'Growth Trajectory',       weight: 0.20 },
        { key: 'creative_readiness',      label: 'Video Asset Readiness',   weight: 0.20 },
        { key: 'channel_expansion_intent',label: 'Channel Expansion Intent',weight: 0.15 },
    ]);

    // Tooltips from lens config (if present), else empty
    const _dimTooltips = {};
    dims.forEach(d => {
        if (d.rubric_description) _dimTooltips[d.key] = d.rubric_description;
    });

    // Collect all sources for the sources card
    const allSrc = [];
    dims.forEach(d => {
        const ds = sub[d.key] || {};
        (ds.signals || []).forEach(sig => {
            if (typeof sig === 'object' && sig.url) {
                if (!allSrc.some(s => s.url === sig.url)) allSrc.push(sig);
            }
        });
    });

    // Hero row: score donut + company meta | dimension bars
    let barsHtml = dims.map(d => {
        const ds = sub[d.key] || {};
        const s = ds.score || 0;
        const color = _dimColor(s);
        const displayLabel = _dimDisplayLabel[d.key] || d.label;
        const wPct = Math.round((d.weight || 0) * 100);
        const tooltip = _dimTooltips[d.key] || '';
        const tipHtml = tooltip ? ` <span class="icp-dim-tooltip-icon" onclick="event.stopPropagation()">i<span class="dim-tooltip">${escHtml(tooltip)}</span></span>` : '';
        return `<div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:12px;color:var(--text-secondary);min-width:180px">${escHtml(displayLabel)} <span style="color:var(--text-muted);font-size:10px">(${wPct}%)</span>${tipHtml}</span>
            <div style="flex:1;height:8px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden">
                <div style="height:100%;width:${s}%;background:${color};border-radius:4px;transition:width 0.8s"></div>
            </div>
            <span style="font-size:13px;font-weight:700;color:${color};min-width:28px;text-align:right">${s}</span>
        </div>`;
    }).join('');

    // Report badges
    const reportBadgesHtml = Object.entries(analysesUsed).map(([atype, path]) => {
        const label = analysisLabels[atype] || atype;
        const filename = path ? path.replace(/^reports[\\/\\\\]/, '') : '';
        if (!filename) return '';
        return `<span class="source-badge source-${atype}" style="cursor:pointer;font-size:12px;padding:3px 10px;margin:2px" onclick="event.stopPropagation();switchModule('research');openReport('${escHtml(filename)}')" title="View ${escHtml(label)} report">${escHtml(label)}</span>`;
    }).join('');

    // Playbook card
    const playbookCard = fit.recommended_angle ? _dashCard('Outbound Strategy Playbook',
        `<div style="font-size:13px;color:var(--text-secondary);line-height:1.5">${_renderCitedText(fit.recommended_angle)}</div>`, true) : '';

    // Dimension detail cards — each dimension gets its own card
    const dimCards = dims.map(d => {
        const ds = sub[d.key] || {};
        const s = ds.score || 0;
        const color = _dimColor(s);
        const displayLabel = _dimDisplayLabel[d.key] || d.label;
        const rationale = ds.rationale || 'No data available';
        const signals = (ds.signals || []).map(sig => {
            if (typeof sig === 'string') return `<span class="icp-signal-tag">${escHtml(sig)}</span>`;
            const text = sig.text || sig;
            const url = sig.url;
            return url
                ? `<a class="icp-signal-tag" href="${escHtml(url)}" target="_blank" rel="noopener">${escHtml(text)}</a>`
                : `<span class="icp-signal-tag">${escHtml(text)}</span>`;
        }).join('');

        const tooltip = _dimTooltips[d.key] || '';
        const tipHtml = tooltip ? ` <span class="icp-dim-tooltip-icon" onclick="event.stopPropagation()">i<span class="dim-tooltip">${escHtml(tooltip)}</span></span>` : '';

        return `<div class="dash-card">
            <div class="dash-card-title">${escHtml(displayLabel)}${tipHtml} <span style="color:${color};float:right;font-size:16px">${s}</span></div>
            <div style="height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden;margin-bottom:10px">
                <div style="height:100%;width:${s}%;background:${color};border-radius:3px"></div>
            </div>
            <div style="font-size:12px;color:var(--text-secondary);line-height:1.5;margin-bottom:8px">${_renderCitedText(rationale)}</div>
            ${signals ? `<div class="icp-dim-signals">${signals}</div>` : ''}
        </div>`;
    }).join('');

    // Company snapshot card
    const snapFields = [
        ['Website', snap.website], ['Revenue', snap.estimated_revenue],
        ['Employees', snap.estimated_employees], ['Recent Funding', snap.recent_funding],
    ].filter(f => f[1]);
    const snapCard = snapFields.length ? _dashCard('Company Snapshot',
        `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            ${snapFields.map(f => `<div style="font-size:12px;color:var(--text-muted)">${f[0]}<div style="font-size:13px;color:var(--text-primary);font-weight:500">${escHtml(String(f[1]))}</div></div>`).join('')}
        </div>
        ${(snap.primary_ad_channels || []).length ? `<div style="margin-top:8px;font-size:12px;color:var(--text-muted)">Ad Channels<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px">${snap.primary_ad_channels.map((v, i) => {
            const c2 = [{bg:'rgba(59,130,246,0.12)',color:'#60a5fa'},{bg:'rgba(168,85,247,0.12)',color:'#c084fc'},{bg:'rgba(22,163,74,0.12)',color:'#4ade80'},{bg:'rgba(234,179,8,0.12)',color:'#facc15'},{bg:'rgba(239,68,68,0.12)',color:'#f87171'}][i%5];
            return `<span style="display:inline-block;font-size:11px;padding:2px 8px;border-radius:4px;background:${c2.bg};color:${c2.color}">${escHtml(v)}</span>`;
        }).join('')}</div></div>` : ''}`, false) : '';

    // Risks card
    const risksCard = (fit.key_risks || []).length ? _dashCard('Key Risks',
        `<ul class="icp-risks">${(fit.key_risks || []).map(r => `<li>${_renderCitedText(r)}</li>`).join('')}</ul>`, false) : '';

    // Sources card
    const sourcesCard = _dashCard('Analysis Sources',
        `${reportBadgesHtml ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px">${reportBadgesHtml}</div>` : ''}
        ${allSrc.length > 0 ? `<div style="padding-top:8px;border-top:1px solid var(--border)">
            <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted);margin-bottom:6px;font-weight:600">External Sources (${allSrc.length})</div>
            ${allSrc.map(s => `<div style="font-size:11px;padding:3px 0"><a href="${escHtml(s.url)}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none">${escHtml(s.text)}</a></div>`).join('')}
        </div>` : '<div style="font-size:12px;color:var(--text-muted)">Re-score to generate source citations.</div>'}`, false);

    container.innerHTML = `<div class="icp-detail" style="padding:24px 32px">
        <div class="dash-hero-row">
            <div class="dash-hero-left">
                <div class="dash-hero-identity" style="border-right:none;padding-right:0">
                    <div class="dash-hero-company">${escHtml(activeProspectName)}</div>
                    <div style="margin-top:4px">
                        <span class="icp-label-badge" style="color:${_dimColor(score)};font-size:12px">${escHtml(fit.overall_label || '?')}</span>
                    </div>
                    <div class="dash-hero-detail">Confidence: <span style="color:${confColor}">${confLabel}</span> &bull; ${cov.categories_with_data || 0}/${cov.categories_total || 3} analyses</div>
                    <div class="icp-actions-row" style="margin-top:8px">
                        <button class="icp-rescore-btn" id="icp-rescore-btn" onclick="rescoreProspect('${encodeURIComponent(activeProspectName)}')" style="font-size:11px;padding:4px 10px">&#8635; Re-score</button>
                    </div>
                </div>
                <div class="dash-hero-score">
                    <div class="icp-big-score ${tier}" style="width:90px;height:90px;font-size:28px">
                        <span class="num">${score}</span>
                        <span class="lbl">/100</span>
                    </div>
                    <div style="font-size:10px;color:var(--text-muted);margin-top:4px">${escHtml(fit._lens_name || 'Prospect Score')} <span class="icp-info-icon" style="font-size:10px">i<span class="icp-info-tooltip">Scored using ${escHtml(fit._lens_name || 'the configured lens')} with weighted dimension analysis.</span></span></div>
                </div>
            </div>
            <div class="dash-hero-right">
                <div class="dash-hero-right-title">Dimension Scores</div>
                <div style="display:flex;flex-direction:column;gap:10px">${barsHtml}</div>
            </div>
        </div>

        ${playbookCard}

        <div class="dash-grid">
            ${dimCards}
            ${snapCard}
            ${risksCard}
            ${sourcesCard}
        </div>
    </div>`;
}

async function rescoreProspect(encodedName) {
    const companyName = decodeURIComponent(encodedName);
    const btn = document.getElementById('icp-rescore-btn');
    if (!btn) return;
    btn.disabled = true;
    btn.innerHTML = '&#8635; Scoring...';
    btn.style.opacity = '0.6';

    // Get website from existing data
    const p = _prospectsByName[companyName];
    const website = _getScore(p)?.company_snapshot?.website || '';

    try {
        const resp = await fetch(`/api/dossiers/${encodeURIComponent(companyName)}/ua-fit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ website_url: website }),
        });
        if (!resp.ok) throw new Error('Re-score failed');
        // Reload campaigns and re-open this company
        await loadCampaigns();
        openProspectDetail(companyName);
    } catch (e) {
        console.error('Re-score failed:', e);
        btn.innerHTML = '&#8635; Failed — retry';
        btn.disabled = false;
        btn.style.opacity = '1';
    }
}

// ===================== PIPELINE MAP =====================
let _pipelineState = {
    niche: '', companies: [],
    companyStatus: {}, companyScores: {}, companyAnalysisProgress: {},
    phase: 'idle',
};

function _safeName(name) {
    return name.replace(/[^a-zA-Z0-9]/g, '_');
}

// Responsive: focus a single pane on narrow screens
// Pane order for adjacency logic (the pane you click + its predecessor are shown)
const _paneOrder = ['pane-execution', 'pane-summary', 'pane-detail'];

// === Discover → Research selection state ===
let _selectedForResearch = new Map(); // name → {name, website, description}
let _availableLenses = []; // [{id, name, slug}, ...]

async function _loadLenses() {
    try {
        const resp = await fetch('/api/lenses');
        if (resp.ok) {
            _availableLenses = await resp.json();
        }
    } catch (e) { console.error('Failed to load lenses:', e); }
}

function _buildLensSelectHtml(selectId) {
    if (_availableLenses.length === 0) return `<select class="lens-select" id="${selectId}"><option>Loading...</option></select>`;
    const lastUsed = localStorage.getItem('sv_last_lens') || '';
    const opts = _availableLenses.map((l, i) => {
        const val = l.slug || l.name;
        const sel = lastUsed ? (val === lastUsed ? 'selected' : '') : (i === 0 ? 'selected' : '');
        return `<option value="${escHtml(val)}" ${sel}>${escHtml(l.name)}</option>`;
    }).join('');
    return `<select class="lens-select" id="${selectId}">${opts}</select>`;
}

function _getSelectedLensName(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel) return _availableLenses[0]?.name || 'CTV Ad Sales';
    const opt = sel.options[sel.selectedIndex];
    return opt ? opt.textContent : _availableLenses[0]?.name || 'CTV Ad Sales';
}

function _inferSourceType(url) {
    if (!url) return 'web';
    const u = url.toLowerCase();
    if (u.includes('reddit.com')) return 'reddit';
    if (u.includes('news.ycombinator.com')) return 'news';
    if (u.includes('techcrunch.com') || u.includes('bloomberg.com') || u.includes('reuters.com') ||
        u.includes('cnbc.com') || u.includes('forbes.com') || u.includes('wsj.com') ||
        u.includes('venturebeat.com') || u.includes('theverge.com') || u.includes('wired.com') ||
        u.includes('businessinsider.com') || u.includes('axios.com') || u.includes('theinformation.com') ||
        u.includes('semafor.com') || u.includes('news.') || u.includes('/news/')) return 'news';
    return 'web';
}

function _toggleResearchSelection(name, checkboxEl) {
    // Parse data from the parent list item (supports both discovery list and niche eval cards)
    const item = checkboxEl.closest('.discovery-list-item') || checkboxEl.closest('.ne-company-card');
    let data;
    try { data = JSON.parse(item?.dataset?.companyPayload || '{}'); } catch { data = {}; }
    if (!data.name) data.name = name;

    if (checkboxEl.checked) {
        // If at max, prevent checking
        if (_selectedForResearch.size >= 3) {
            checkboxEl.checked = false;
            return;
        }
        _selectedForResearch.set(name, data);
        if (item) item.classList.add('selected');
    } else {
        _selectedForResearch.delete(name);
        if (item) item.classList.remove('selected');
    }
    _updateSummaryResearchBar();
    _updateCheckboxStates();
}

function _updateCheckboxStates() {
    const atMax = _selectedForResearch.size >= 3;
    document.querySelectorAll('.discovery-select-cb').forEach(cb => {
        if (!cb.checked) {
            cb.disabled = atMax;
            cb.style.opacity = atMax ? '0.3' : '1';
            cb.style.cursor = atMax ? 'not-allowed' : 'pointer';
        }
    });
}

function _updateSummaryResearchBar() {
    const bar = document.getElementById('summary-research-bar');
    if (!bar) return;
    const count = _selectedForResearch.size;
    bar.style.display = count > 0 ? 'flex' : 'none';
    const countEl = bar.querySelector('.str-count');
    if (countEl) countEl.textContent = count >= 3 ? '3/3 selected (max)' : `${count}/3 selected`;
    const btn = bar.querySelector('.str-btn');
    if (btn) btn.disabled = count === 0;
}

function focusPane(paneId) {
    if (window.innerWidth >= 1440) return; // no-op on wide screens
    document.querySelectorAll('.prospect-pane').forEach(p => p.classList.remove('pane-focused'));

    const idx = _paneOrder.indexOf(paneId);
    if (idx < 0) return;

    // Show the target pane + the one before it (2 panes visible)
    const target = document.getElementById(paneId);
    if (target) target.classList.add('pane-focused');

    if (idx > 0) {
        const prev = document.getElementById(_paneOrder[idx - 1]);
        if (prev) prev.classList.add('pane-focused');
    }
}

// Pane header clicks for responsive expand
document.addEventListener('click', function(e) {
    const header = e.target.closest('.prospect-pane .pane-header');
    if (!header) return;
    const pane = header.closest('.prospect-pane');
    if (pane && window.innerWidth < 1440) {
        focusPane(pane.id);
    }
});

// Remove pane-focused on resize above breakpoint
window.addEventListener('resize', function() {
    if (window.innerWidth >= 1440) {
        document.querySelectorAll('.prospect-pane.pane-focused').forEach(p => p.classList.remove('pane-focused'));
    }
});

// Pane resize handles — drag to resize adjacent panes
(function initPaneResizers() {
    document.querySelectorAll('.pane-resize-handle').forEach(handle => {
        handle.addEventListener('mousedown', function(e) {
            e.preventDefault();
            const leftPane = document.getElementById(handle.dataset.left);
            const rightPane = document.getElementById(handle.dataset.right);
            if (!leftPane || !rightPane) return;

            handle.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';

            // Account for CSS zoom on ancestor — offsetWidth gives CSS px, clientX is visual px
            const zoomEl = leftPane.closest('[style*="zoom"], #workspace-prospecting');
            const zoom = zoomEl ? parseFloat(getComputedStyle(zoomEl).zoom) || 1 : 1;
            const startX = e.clientX;
            const startLeftW = leftPane.offsetWidth;
            const startRightW = rightPane.offsetWidth;

            function onMove(e2) {
                const dx = (e2.clientX - startX) / zoom;
                const totalW = startLeftW + startRightW;
                // Clamp so neither goes below 200 AND total is preserved
                const newLeft = Math.max(200, Math.min(startLeftW + dx, totalW - 200));
                const newRight = totalW - newLeft;
                if (newLeft >= 200 && newRight >= 200) {
                    leftPane.style.width = newLeft + 'px';
                    leftPane.style.flex = '0 0 ' + newLeft + 'px';
                    leftPane.style.minWidth = '0';
                    rightPane.style.width = newRight + 'px';
                    rightPane.style.flex = '0 0 ' + newRight + 'px';
                    rightPane.style.minWidth = '0';
                }
            }

            function onUp() {
                handle.classList.remove('dragging');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    });
})();

function _scrollPipelineBottom() {
    const pane = document.getElementById('pane-execution-body');
    if (pane) pane.scrollTo({ top: pane.scrollHeight, behavior: 'smooth' });
}

function initPipelineMap(niche) {
    const emptyEl = document.getElementById('pane-execution-empty');
    const mapEl = document.getElementById('pipeline-map');
    if (emptyEl) emptyEl.style.display = 'none';
    if (mapEl) mapEl.style.display = 'block';

    _pipelineState = {
        niche, companies: [],
        companyStatus: {}, companyScores: {}, companyAnalysisProgress: {},
        nicheEval: null,
        phase: 'discovering',
    };

    mapEl.innerHTML = `
        <div class="pipeline-node running" id="pm-input">
            <div class="pipeline-node-header">
                <div class="pipeline-node-icon">&#128269;</div>
                <div class="pipeline-node-label">Discovery</div>
            </div>
            <div class="pipeline-node-meta">
                Niche: <strong style="color:var(--text-primary)">${escHtml(niche)}</strong>
            </div>
        </div>
        <div class="pipeline-connector" id="pm-conn-discovery"></div>
        <div class="pipeline-node running" id="pm-discovery">
            <div class="pipeline-node-header">
                <div class="pipeline-node-icon"><div class="company-card-spinner"></div></div>
                <div class="pipeline-node-label">Searching...</div>
            </div>
            <div class="pipeline-node-meta" id="pm-discovery-meta">Querying web, news, Reddit...</div>
        </div>
    `;
}

function handlePipelineSSE(ev) {
    const mapEl = document.getElementById('pipeline-map');
    if (!mapEl) return;

    if (ev.type === 'status') {
        const metaEl = document.getElementById('pm-discovery-meta');
        if (metaEl) metaEl.textContent = ev.text;

    } else if (ev.type === 'discovery_plan') {
        // Show query plan breakdown
        const metaEl = document.getElementById('pm-discovery-meta');
        if (metaEl) metaEl.innerHTML = `<span style="color:var(--text-secondary)">Running ${ev.total_queries} targeted queries</span>
            <span style="color:var(--text-muted);font-size:10px;margin-left:6px">(${ev.web} web, ${ev.news} news, ${ev.reddit} reddit)</span>`;
        // Add search activity log container
        const discNode = document.getElementById('pm-discovery');
        if (discNode && !document.getElementById('pm-search-log')) {
            discNode.insertAdjacentHTML('beforeend', `<div id="pm-search-log" style="margin-top:8px;max-height:180px;overflow-y:auto;font-size:11px;line-height:1.6"></div>`);
        }

    } else if (ev.type === 'search_start') {
        const logEl = document.getElementById('pm-search-log');
        if (logEl) {
            const sourceColors = {web: 'var(--accent)', news: 'var(--green)', reddit: 'var(--yellow)'};
            const color = sourceColors[ev.source] || 'var(--text-muted)';
            logEl.insertAdjacentHTML('beforeend',
                `<div id="pm-search-${ev.index}" style="display:flex;align-items:center;gap:6px;padding:2px 0;opacity:0.7">
                    <div class="company-card-spinner" style="width:10px;height:10px;border-width:1.5px"></div>
                    <span style="color:${color};font-weight:600;min-width:56px">${escHtml(ev.source_label)}</span>
                    <span style="color:var(--text-muted);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(ev.query)}</span>
                </div>`);
            logEl.scrollTop = logEl.scrollHeight;
        }
        // Update counter
        const metaEl = document.getElementById('pm-discovery-meta');
        if (metaEl) {
            const counterSpan = metaEl.querySelector('.search-counter') || (() => {
                const s = document.createElement('span');
                s.className = 'search-counter';
                s.style.cssText = 'display:block;margin-top:3px;font-size:11px;color:var(--text-muted)';
                metaEl.appendChild(s);
                return s;
            })();
            counterSpan.textContent = `Search ${ev.index}/${ev.total}...`;
        }

    } else if (ev.type === 'search_done') {
        const rowEl = document.getElementById(`pm-search-${ev.index}`);
        if (rowEl) {
            rowEl.style.opacity = '1';
            const spinner = rowEl.querySelector('.company-card-spinner');
            if (spinner) spinner.outerHTML = `<span style="color:var(--green);font-size:10px">&#10003;</span>`;
            // Append result count
            rowEl.insertAdjacentHTML('beforeend',
                `<span style="color:var(--text-muted);font-size:10px;white-space:nowrap">${ev.results_count} results</span>`);
        }

    } else if (ev.type === 'search_complete') {
        const metaEl = document.getElementById('pm-discovery-meta');
        if (metaEl) {
            const counterSpan = metaEl.querySelector('.search-counter');
            if (counterSpan) counterSpan.textContent = `${ev.unique_results} unique results from ${ev.total_results} total`;
        }

    } else if (ev.type === 'extracting') {
        const metaEl = document.getElementById('pm-discovery-meta');
        if (metaEl) {
            const counterSpan = metaEl.querySelector('.search-counter');
            if (counterSpan) counterSpan.innerHTML = `<span style="color:var(--purple)">${escHtml(ev.text)}</span>`;
        }

    } else if (ev.type === 'extracted') {
        const metaEl = document.getElementById('pm-discovery-meta');
        if (metaEl) {
            const counterSpan = metaEl.querySelector('.search-counter');
            if (counterSpan) counterSpan.innerHTML = `<span style="color:var(--green)">Extracted ${ev.count} companies</span>`;
        }

    } else if (ev.type === 'discovered') {
        const companies = ev.companies || [];
        _pipelineState.companies = companies;
        _pipelineState.phase = 'discovered';
        if (ev.campaign_id) {
            _pipelineState.campaignId = ev.campaign_id;
            _currentRunCampaignId = ev.campaign_id;
            // For child campaigns (Find Similar), don't change activeCampaignId —
            // the root stays active in sidebar, the child becomes the active tree node
            if (_activeTreeRootId) {
                _activeTreeNodeId = ev.campaign_id;
            } else {
                activeCampaignId = ev.campaign_id;
            }
            // Refresh sidebar (root campaigns only) — child shows up in tree after pipeline completes
            loadCampaigns();
        }

        // Mark discovery as done
        const discNode = document.getElementById('pm-discovery');
        if (discNode) {
            discNode.classList.remove('running');
            discNode.classList.add('done');
            discNode.querySelector('.pipeline-node-icon').innerHTML = '&#10003;';
            discNode.querySelector('.pipeline-node-label').textContent = `Found ${companies.length} companies`;
        }
        const discConn = document.getElementById('pm-conn-discovery');
        if (discConn) discConn.classList.add('done');

        // Mark input node as done
        const inputNode = document.getElementById('pm-input');
        if (inputNode) { inputNode.classList.remove('running'); inputNode.classList.add('done'); }

        // Add "companies found" summary node (no company cards — those are in Pane 3)
        mapEl.insertAdjacentHTML('beforeend', `
            <div class="pipeline-connector done"></div>
            <div class="pipeline-node done" style="border-color:rgba(168,85,247,0.2);padding:12px">
                <div class="pipeline-node-header">
                    <div class="pipeline-node-icon" style="background:rgba(168,85,247,0.15)">&#127919;</div>
                    <div class="pipeline-node-label" style="color:var(--purple)">${companies.length} companies found</div>
                </div>
                <div class="pipeline-node-meta" style="margin-top:4px;font-size:11px;color:var(--text-muted)">${companies.map(c => c.name).join(', ')}</div>
            </div>
        `);
        companies.forEach(c => { _pipelineState.companyStatus[c.name || '?'] = 'discovered'; });
        setTimeout(_scrollPipelineBottom, 100);

    } else if (ev.type === 'validating') {
        const metaEl = document.getElementById('pm-discovery-meta');
        if (metaEl) metaEl.textContent = `Validating ${ev.total} company websites...`;

    } else if (ev.type === 'validated') {
        // No card DOM updates — company cards are in Pane 3 only
        // Just track validation state for later use
        _pipelineState.companyStatus[ev.company] = ev.valid ? (ev.limited ? 'limited' : 'valid') : 'skipped';

    } else if (ev.type === 'validation_complete') {
        // Insert validation summary node
        const conn = document.getElementById('pm-conn-discovery');
        if (conn) {
            conn.insertAdjacentHTML('afterend', `
                <div class="pipeline-node done" id="pm-validation" style="padding:10px 14px">
                    <div class="pipeline-node-header">
                        <div class="pipeline-node-icon" style="font-size:14px">&#10003;</div>
                        <div class="pipeline-node-label">Validation</div>
                    </div>
                    <div class="pipeline-node-meta">${ev.valid_count} valid${ev.limited_count ? ` (${ev.limited_count} limited)` : ''}${ev.rejected_count ? ` &mdash; ${ev.rejected_count} skipped` : ''}</div>
                </div>
                <div class="pipeline-connector done"></div>
            `);
        }

    } else if (ev.type === 'niche_scan_start') {
        // Show niche scan progress in Pane 3
        const sumContent = document.getElementById('pane-summary-content');
        const sumEmpty = document.getElementById('pane-summary-empty');
        if (sumEmpty) sumEmpty.style.display = 'none';
        if (sumContent) {
            sumContent.style.display = 'block';
            sumContent.innerHTML = `<div class="campaign-view" style="padding:16px">
                <div class="ne-section">
                    <div class="ne-section-title">Niche Evaluation</div>
                    <div id="niche-scan-progress" style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text-secondary)">
                        <div class="company-card-spinner" style="width:14px;height:14px;border-width:2px"></div>
                        <span>Scanning financial data: 0/${ev.total} companies...</span>
                    </div>
                </div>
            </div>`;
        }
        // Add scan node to Pane 2 pipeline
        const valNode = document.getElementById('pm-validation');
        if (valNode) {
            valNode.insertAdjacentHTML('afterend', `
                <div class="pipeline-connector" id="pm-conn-scan"></div>
                <div class="pipeline-node running" id="pm-niche-scan" style="padding:10px 14px">
                    <div class="pipeline-node-header">
                        <div class="company-card-spinner" style="width:14px;height:14px;border-width:2px"></div>
                        <div class="pipeline-node-label">Financial Scan</div>
                    </div>
                    <div class="pipeline-node-meta" id="pm-scan-meta">Scanning 0/${ev.total}...</div>
                </div>
            `);
        }

    } else if (ev.type === 'niche_scan_progress') {
        // Update scan counter in Pane 3 and Pane 2
        const progEl = document.getElementById('niche-scan-progress');
        if (progEl) {
            const icon = ev.status === 'done' ? '&#10003;' : ev.status === 'error' ? '&#10007;' : '';
            const snap = ev.snapshot || {};
            const detail = snap.revenue_formatted ? ` &mdash; ${snap.revenue_formatted}${snap.is_public ? ' (public)' : ''}` : '';
            progEl.innerHTML = `<div class="company-card-spinner" style="width:14px;height:14px;border-width:2px"></div>
                <span>Scanning: ${ev.index}/${ev.total} &mdash; ${escHtml(ev.company)}${detail}</span>`;
        }
        const scanMeta = document.getElementById('pm-scan-meta');
        if (scanMeta) scanMeta.textContent = `Scanning ${ev.index}/${ev.total}...`;

    } else if (ev.type === 'niche_eval_complete') {
        // Store niche eval and render charts in Pane 3
        _pipelineState.nicheEval = ev.niche_eval;
        const sumContent2 = document.getElementById('pane-summary-content');
        if (sumContent2) {
            // Build company list from discovery data
            const discoveredCompanies = (_pipelineState.companies || []);
            const discoveryListHtml = discoveredCompanies.map(c => {
                const name = c.name || '?';
                const desc = c.description || '';
                const size = c.estimated_size || '';
                return `<div class="discovery-list-item" data-company-name="${escHtml(name)}" style="cursor:pointer;padding:10px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px"
                    onclick="openProspectDetail('${escHtml(name).replace(/'/g, "\\'")}')">
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:${desc ? '4px' : '0'}">
                        <span style="font-weight:600;font-size:13px;color:var(--text-primary)">${escHtml(name)}</span>
                        ${size ? `<span class="company-card-size" style="margin:0">${escHtml(size)}</span>` : ''}
                    </div>
                    ${desc ? `<div style="font-size:11px;color:var(--text-muted);line-height:1.4;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden">${escHtml(desc)}</div>` : ''}
                </div>`;
            }).join('');

            // Build pseudo-prospects from discovered companies for consolidated cards
            const pseudoProspects = discoveredCompanies.map(c => ({
                company_name: c.name,
                company_description: c.description || '',
                validation_status: 'valid',
                discovery: { estimated_size: c.estimated_size, why_included: c.why_included, evidence: c.evidence },
            }));

            sumContent2.innerHTML = `<div class="campaign-view" style="padding:16px">
                ${renderNicheEvaluation(ev.niche_eval, pseudoProspects, null)}
            </div>`;
        }
        // Update Pane 2 scan node to done
        const scanNode = document.getElementById('pm-niche-scan');
        if (scanNode) {
            scanNode.className = 'pipeline-node done';
            scanNode.style.padding = '10px 14px';
            const cov = ev.niche_eval?.data_coverage || {};
            scanNode.innerHTML = `
                <div class="pipeline-node-header">
                    <div class="pipeline-node-icon" style="font-size:14px">&#10003;</div>
                    <div class="pipeline-node-label">Financial Scan</div>
                </div>
                <div class="pipeline-node-meta">${ev.niche_eval?.company_count || 0} scanned &mdash; ${cov.revenue_known || 0} with revenue data</div>
            `;
        }

    } else if (ev.type === 'analyzing') {
        // Fires at start of score_ua_fit() — BEFORE analyses run — so card + rows exist
        const name = ev.company;
        _pipelineState.companyStatus[name] = 'scoring';
        _pipelineState.companyAnalysisProgress[name] = {};
        const card = document.getElementById('pm-card-' + _safeName(name));
        if (card) {
            card.className = 'company-card scoring';
            const ring = card.querySelector('.company-card-ring');
            if (ring) ring.innerHTML = '<div class="company-card-spinner"></div>';
            // Build full-name analysis rows
            const analyses = ev.has_website
                ? [['techstack','Tech Stack'],['financial','Financial'],['brand_ad','Brand & Ad Intel']]
                : [['financial','Financial'],['brand_ad','Brand & Ad Intel']];
            const rowsHtml = analyses.map(([atype, label]) =>
                `<div class="analysis-row">
                    <div class="analysis-row-icon" id="pm-icon-${_safeName(name)}-${atype}"></div>
                    <span class="analysis-row-name">${label}</span>
                    <span class="analysis-row-status" id="pm-status-${_safeName(name)}-${atype}">Queued</span>
                </div>`
            ).join('');
            card.insertAdjacentHTML('beforeend',
                `<div class="analysis-list" id="pm-list-${_safeName(name)}">${rowsHtml}</div>`);
            card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }

    } else if (ev.type === 'scoring') {
        // LLM scoring starting — analyses are done
        const name = ev.company;
        const card = document.getElementById('pm-card-' + _safeName(name));
        if (card) {
            const ring = card.querySelector('.company-card-ring');
            if (ring) ring.title = 'AI scoring in progress...';
        }

    } else if (ev.type === 'analysis_start') {
        const name = ev.company;
        const atype = ev.analysis_type;
        if (!_pipelineState.companyAnalysisProgress[name]) {
            _pipelineState.companyAnalysisProgress[name] = {};
        }
        _pipelineState.companyAnalysisProgress[name][atype] = 'running';
        const icon = document.getElementById(`pm-icon-${_safeName(name)}-${atype}`);
        const status = document.getElementById(`pm-status-${_safeName(name)}-${atype}`);
        if (icon) icon.className = 'analysis-row-icon running';
        if (status) { status.className = 'analysis-row-status running'; status.textContent = 'Running...'; }

    } else if (ev.type === 'analysis_done') {
        const name = ev.company;
        const atype = ev.analysis_type;
        const state = ev.reused ? 'cached' : (ev.report_path ? 'done' : 'error');
        const symbol = state === 'done' ? '✓' : (state === 'cached' ? '↩' : '!');
        const statusText = ev.reused ? '↩ Cached' : (ev.report_path ? 'Done' : 'Failed');
        if (_pipelineState.companyAnalysisProgress[name]) {
            _pipelineState.companyAnalysisProgress[name][atype] = state;
        }
        const icon = document.getElementById(`pm-icon-${_safeName(name)}-${atype}`);
        const status = document.getElementById(`pm-status-${_safeName(name)}-${atype}`);
        if (icon) { icon.className = `analysis-row-icon ${state}`; icon.textContent = symbol; }
        if (status) { status.className = `analysis-row-status ${state}`; status.textContent = statusText; }

    } else if (ev.type === 'scored') {
        const name = ev.company;
        _pipelineState.companyStatus[name] = 'scored';
        _pipelineState.companyScores[name] = { score: ev.overall_score, label: ev.label };
        // Pre-fetch full prospect data so Pane 4 clicks work immediately
        fetch('/api/ua-targets').then(r => r.ok ? r.json() : []).then(targets => {
            const t = targets.find(x => x.company_name === name);
            if (t) _prospectsByName[name] = t;
        }).catch(() => {});
        const card = document.getElementById('pm-card-' + _safeName(name));
        if (card) {
            const color = _dimColor(ev.overall_score);
            card.className = 'company-card scored';
            card.style.borderColor = color;
            const ring = card.querySelector('.company-card-ring');
            if (ring) {
                ring.style.borderColor = color;
                ring.style.color = color;
                ring.textContent = ev.overall_score;
            }
            const meta = card.querySelector('.company-card-meta');
            if (meta) meta.innerHTML = `<span style="color:${color}">${escHtml(ev.label)}</span>`;
            // Ensure analysis rows exist — rebuild from scored event if analyzing event was missed
            const existingList = card.querySelector('.analysis-list');
            if (!existingList && ev.analyses_used && ev.analyses_used.length > 0) {
                const aLabels = { techstack: 'Tech Stack', financial: 'Financial', brand_ad: 'Brand & Ad Intel' };
                const rowsHtml = ev.analyses_used.map(k =>
                    `<div class="analysis-row">
                        <div class="analysis-row-icon done">&#10003;</div>
                        <span class="analysis-row-name">${escHtml(aLabels[k] || k)}</span>
                        <span class="analysis-row-status done">Done</span>
                    </div>`
                ).join('');
                card.insertAdjacentHTML('beforeend',
                    `<div class="analysis-list">${rowsHtml}</div>`);
            }
        }
        // Real-time Pane 3 update
        _updateLiveSummary(ev);

    } else if (ev.type === 'score_error') {
        const name = ev.company;
        _pipelineState.companyStatus[name] = 'error';
        const card = document.getElementById('pm-card-' + _safeName(name));
        if (card) {
            card.className = 'company-card error';
            const ring = card.querySelector('.company-card-ring');
            if (ring) { ring.textContent = '!'; ring.style.borderColor = 'var(--red)'; ring.style.color = 'var(--red)'; }
            const meta = card.querySelector('.company-card-meta');
            if (meta) meta.innerHTML = `<span style="color:var(--red)">Error</span>`;
        }

    } else if (ev.type === 'complete') {
        _pipelineState.phase = 'complete';
        // Pipeline is logically done — clear running state so renderExecutionPane won't bail
        _prospectPipelineRunning = false;
        _currentRunCampaignId = null;
        const mapEl2 = document.getElementById('pipeline-map');
        if (mapEl2) {
            mapEl2.insertAdjacentHTML('beforeend', `
                <div class="pipeline-connector done"></div>
                <div class="pipeline-complete-node">
                    <span class="check">&#10003;</span>
                    Discovery complete &mdash; ${ev.total_discovered || ev.total_scored || 0} companies found
                </div>
            `);
            setTimeout(_scrollPipelineBottom, 100);
        }
        // Set Pane 2 badge to Complete
        const badge = document.getElementById('pane-execution-status');
        if (badge) { badge.textContent = 'Complete'; badge.className = 'pane-status-badge complete'; }

        // Reload campaigns sidebar and populate Pane 3
        const cid = ev.campaign_id || _pipelineState.campaignId;
        if (cid) {
            loadCampaigns().then(() => {
                // Check if this is a child campaign (Find Similar completed)
                const completedCampaign = _findCampaignById(cid);
                if (completedCampaign && completedCampaign.parent_campaign_id) {
                    // Child campaign — rebuild tree, show child's results in Pane 3
                    const rootId = _activeTreeRootId || activeCampaignId;
                    _activeTreeRootId = rootId;
                    _activeTreeNodeId = cid;
                    renderDiscoveryTree(rootId);
                    renderSummaryPane(cid);
                    renderExecutionPane(cid);
                } else {
                    activeCampaignId = cid;
                    renderCampaignSidebar();
                    renderSummaryPane(cid);
                    renderExecutionPane(cid);
                    // Highlight active sidebar item
                    document.querySelectorAll('.search-query-item').forEach(el => {
                        const id = parseInt(el.dataset.campaignId, 10);
                        el.classList.toggle('active', id === cid);
                    });
                }
            });
        }

    } else if (ev.type === 'insight_ready') {
        // Server generated insight — reload campaign data and re-render summary
        const insightCid = ev.campaign_id || _pipelineState.campaignId;
        if (insightCid) {
            loadCampaigns().then(() => {
                if (activeCampaignId === insightCid) {
                    renderSummaryPane(insightCid);
                }
            });
        }

    } else if (ev.type === 'error') {
        const isEmptyResult = !!ev.campaign_id;
        const mapEl2 = document.getElementById('pipeline-map');
        if (mapEl2) {
            const color = isEmptyResult ? 'var(--text-secondary)' : 'var(--red)';
            const icon = isEmptyResult ? '&#128269;' : '&#9888;';
            const label = isEmptyResult ? 'No Results' : 'Error';
            const bgColor = isEmptyResult ? 'rgba(107,114,128,0.15)' : 'rgba(239,68,68,0.15)';
            mapEl2.insertAdjacentHTML('beforeend', `
                <div class="pipeline-connector"></div>
                <div class="pipeline-node" style="border-color:${color};color:${color}">
                    <div class="pipeline-node-header">
                        <div class="pipeline-node-icon" style="background:${bgColor}">${icon}</div>
                        <div class="pipeline-node-label" style="color:${color}">${label}</div>
                    </div>
                    <div class="pipeline-node-meta" style="color:${color}">${escHtml(ev.text)}</div>
                </div>
            `);
        }
        const badge = document.getElementById('pane-execution-status');
        if (badge) {
            if (isEmptyResult) {
                badge.textContent = 'No Results';
                badge.className = 'pane-status-badge';
                badge.style.cssText = 'background:rgba(107,114,128,0.15);color:#9ca3af';
            } else {
                badge.textContent = 'Error';
                badge.className = 'pane-status-badge error';
            }
        }
        if (ev.campaign_id) _currentRunCampaignId = ev.campaign_id;
    }
}

// Poll for vertical insight after pipeline completes (insight generates in background thread)
function _pollForInsight(campaignId, attempts = 0) {
    if (attempts >= 12) return; // stop after ~60s
    setTimeout(() => {
        fetch(`/api/campaigns/${campaignId}`).then(r => r.ok ? r.json() : null).then(data => {
            if (data && data.insight_json) {
                // Insight ready — update cache and re-render
                loadCampaigns().then(() => {
                    if (activeCampaignId === campaignId) {
                        renderSummaryPane(campaignId);
                    }
                });
            } else {
                _pollForInsight(campaignId, attempts + 1);
            }
        }).catch(() => _pollForInsight(campaignId, attempts + 1));
    }, 5000);
}

// Pipeline map company card clicks
document.getElementById('pipeline-map').addEventListener('click', function(e) {
    const card = e.target.closest('.company-card.scored');
    if (!card) return;
    const name = card.dataset.companyName;
    if (name) openProspectDetail(name);
});

// Result row clicks in summary pane (delegated to handle apostrophes/special chars in names)
document.getElementById('pane-summary-content').addEventListener('click', function(e) {
    // Don't handle clicks on links
    if (e.target.closest('a')) return;

    // Scored result row → open detail
    const row = e.target.closest('.cv-result-row');
    if (row) {
        const name = row.dataset.company;
        if (name) openProspectDetail(name);
        return;
    }

    // Discovery list item → open detail only (checkbox handles selection separately)
    const item = e.target.closest('.discovery-list-item');
    if (item && !e.target.closest('.discovery-select-cb')) {
        const name = item.dataset.companyName;
        if (name) openProspectDetail(name);
    }
});

async function _sendToResearch(lensSelectId) {
    // Gather companies from selection map
    const companies = Array.from(_selectedForResearch.values());
    if (!companies.length) return;

    const selId = lensSelectId || 'summary-lens-select';
    const lensName = _getSelectedLensName(selId);
    const selEl = document.getElementById(selId);
    if (selEl) localStorage.setItem('sv_last_lens', selEl.value);

    const btns = document.querySelectorAll('.str-btn');
    btns.forEach(b => { b.disabled = true; b.textContent = 'Sending...'; });

    try {
        const resp = await fetch('/api/send-to-research', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ companies }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            _showToast(err.error || 'Failed to send', 'error');
            return;
        }
        switchModule('research');
        refreshSidebar();
        switchLeftTab('chats');
        newChat();

        const names = companies.map(c => c.name);
        let query = '';
        if (names.length === 1) {
            query = `Score ${names[0]} using the ${lensName} lens.`;
        } else {
            query = `Score ${names.slice(0, -1).join(', ')} and ${names[names.length - 1]} using the ${lensName} lens.`;
        }

        // Collect all evidence source URLs across companies
        const allSources = [];
        companies.forEach(c => {
            (c.evidence || []).forEach(e => {
                if (e.source_url && !allSources.includes(e.source_url)) allSources.push(e.source_url);
            });
        });
        if (allSources.length > 0) {
            query += '\n\nSources:\n' + allSources.map(u => `- ${u}`).join('\n');
        }

        setTimeout(() => {
            const chatInput = document.getElementById('chat-input');
            if (chatInput) {
                chatInput.value = query;
                autoResize(chatInput);
                chatInput.focus();
                chatInput.setSelectionRange(chatInput.value.length, chatInput.value.length);
            }
        }, 200);

        // Clear selection state
        _selectedForResearch.clear();
    } catch (e) {
        console.error('Send to research failed:', e);
        _showToast('Failed: ' + e.message, 'error');
    } finally {
        btns.forEach(b => { b.disabled = false; b.textContent = 'Send to Research'; });
    }
}

function runProspectPipeline() {
    if (_prospectPipelineRunning) return;
    const nicheInput = document.getElementById('prospect-niche-input');
    const niche = (nicheInput.value || '').trim();
    if (!niche) {
        nicheInput.classList.add('shake');
        nicheInput.placeholder = 'Type a niche first, e.g. "DTC beauty brands"';
        setTimeout(() => nicheInput.classList.remove('shake'), 600);
        nicheInput.focus();
        return;
    }
    const topN = parseInt(document.getElementById('prospect-topn').value) || 10;

    _prospectPipelineRunning = true;
    _currentRunCampaignId = null; // will be set on 'discovered' event
    const btn = document.getElementById('prospect-run-btn');
    btn.disabled = true;
    btn.textContent = 'Running...';

    // Set Pane 2 badge to Running
    const badge = document.getElementById('pane-execution-status');
    if (badge) { badge.textContent = 'Running'; badge.className = 'pane-status-badge running'; }

    // Clear Panes 3 & 4
    clearDetailPane();
    const sumContent = document.getElementById('pane-summary-content');
    const sumEmpty = document.getElementById('pane-summary-empty');
    if (sumContent) { sumContent.style.display = 'none'; sumContent.innerHTML = ''; }
    if (sumEmpty) sumEmpty.style.display = 'block';

    // Init pipeline map in Pane 2
    initPipelineMap(niche);
    focusPane('pane-execution');

    // Add temporary sidebar entry so user can navigate back to this running pipeline
    const list = document.getElementById('prospect-search-list');
    if (list) {
        // Deactivate other items
        document.querySelectorAll('.search-query-item').forEach(el => el.classList.remove('active'));
        // Insert at top
        const tempItem = document.createElement('div');
        tempItem.className = 'search-query-item active';
        tempItem.id = 'prospect-running-temp';
        tempItem.setAttribute('data-campaign-id', 'running');
        tempItem.onclick = () => {
            // Switch back to the running pipeline
            document.querySelectorAll('.search-query-item').forEach(el => el.classList.remove('active'));
            tempItem.classList.add('active');
            if (_currentRunCampaignId) activeCampaignId = _currentRunCampaignId;
            if (_savedLivePipelineDOM) {
                const mapEl = document.getElementById('pipeline-map');
                if (mapEl) { mapEl.innerHTML = _savedLivePipelineDOM; mapEl.style.display = 'block'; }
                const emptyEl = document.getElementById('pane-execution-empty');
                if (emptyEl) emptyEl.style.display = 'none';
                _savedLivePipelineDOM = null;
            }
            const execBadge = document.getElementById('pane-execution-status');
            if (execBadge) { execBadge.textContent = 'Running'; execBadge.className = 'pane-status-badge running'; }
            focusPane('pane-execution');
        };
        tempItem.innerHTML = `<div class="search-query-info">
            <div class="search-query-name">${escHtml(niche)}</div>
            <div class="search-query-meta">
                <span class="pane-status-badge running">Running</span>
            </div>
        </div>`;
        list.insertBefore(tempItem, list.firstChild);
    }

    // Collect structured niche fields if Niche Builder was used
    const nicheCtx = {};
    const _nbSize = document.querySelector('#nb-company-size .icp-chip.selected');
    if (_nbSize) nicheCtx.company_size = _nbSize.dataset.value;
    const _nbModel = document.querySelector('#nb-business-model .icp-chip.selected');
    if (_nbModel) nicheCtx.business_model = _nbModel.dataset.value === 'Both' ? 'B2B/B2C' : _nbModel.dataset.value;
    const _nbVert = (document.getElementById('nb-vertical')?.value || '').trim();
    if (_nbVert) nicheCtx.vertical = _nbVert;
    const _nbGeoC = (document.getElementById('nb-geography-custom')?.value || '').trim();
    const _nbGeo = document.querySelector('#nb-geography .icp-chip.selected');
    if (_nbGeoC) nicheCtx.geography = _nbGeoC;
    else if (_nbGeo) nicheCtx.geography = _nbGeo.dataset.value;
    const _nbQual = (document.getElementById('nb-qualifiers')?.value || '').trim();
    if (_nbQual) nicheCtx.qualifiers = _nbQual;

    fetch('/api/ua-pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ niche, top_n: topN, context: nicheCtx }),
    }).then(async resp => {
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const ev = JSON.parse(line.slice(6));
                    handlePipelineSSE(ev);
                } catch {}
            }
        }
    }).catch(e => {
        console.error('Pipeline error:', e);
        handlePipelineSSE({ type: 'error', text: 'Connection error: ' + e.message });
    }).finally(() => {
        _prospectPipelineRunning = false;
        const finishedCampaignId = _currentRunCampaignId;
        _currentRunCampaignId = null;
        _savedLivePipelineDOM = null;
        btn.disabled = false;
        btn.textContent = 'Search';
        loadCampaigns().then(() => {
            // Re-render execution pane with the final pipeline tree
            if (finishedCampaignId) {
                activeCampaignId = finishedCampaignId;
                renderExecutionPane(finishedCampaignId);
            }
        });
    });
}

// ===================== FIND SIMILAR =====================

function initPipelineMapSimilar(seedCompany) {
    const emptyEl = document.getElementById('pane-execution-empty');
    const mapEl = document.getElementById('pipeline-map');
    if (emptyEl) emptyEl.style.display = 'none';
    if (mapEl) mapEl.style.display = 'block';

    _pipelineState = {
        niche: `Similar to ${seedCompany}`, companies: [],
        companyStatus: {}, companyScores: {}, companyAnalysisProgress: {},
        phase: 'discovering',
    };

    if (mapEl) mapEl.innerHTML = `
        <div class="pipeline-node running" id="pm-input">
            <div class="pipeline-node-header">
                <div class="pipeline-node-icon">&#128279;</div>
                <div class="pipeline-node-label">Find Similar</div>
            </div>
            <div class="pipeline-node-meta">
                Anchored on: <strong style="color:var(--purple)">${escHtml(seedCompany)}</strong>
            </div>
        </div>
        <div class="pipeline-connector" id="pm-conn-discovery"></div>
        <div class="pipeline-node running" id="pm-discovery">
            <div class="pipeline-node-header">
                <div class="pipeline-node-icon"><div class="company-card-spinner"></div></div>
                <div class="pipeline-node-label">Searching for Similar...</div>
            </div>
            <div class="pipeline-node-meta" id="pm-discovery-meta">Building competitor profile...</div>
        </div>
    `;
}

function runFindSimilar(companyName) {
    if (_prospectPipelineRunning) return;

    const parentCampaignId = _activeTreeNodeId || activeCampaignId;
    if (!parentCampaignId) return;

    const niche = `Similar to ${companyName}`;
    const topN = parseInt(document.getElementById('prospect-topn')?.value) || 10;

    _prospectPipelineRunning = true;
    _currentRunCampaignId = null;

    // Set Pane 2 badge to Running
    const badge = document.getElementById('pane-execution-status');
    if (badge) { badge.textContent = 'Running'; badge.className = 'pane-status-badge running'; }

    // Clear Panes 3 & 4
    clearDetailPane();
    const sumContent = document.getElementById('pane-summary-content');
    const sumEmpty = document.getElementById('pane-summary-empty');
    if (sumContent) { sumContent.style.display = 'none'; sumContent.innerHTML = ''; }
    if (sumEmpty) sumEmpty.style.display = 'block';

    // Init pipeline map for find-similar mode
    initPipelineMapSimilar(companyName);
    focusPane('pane-execution');

    fetch('/api/ua-pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            niche,
            top_n: topN,
            seed_company: companyName,
            parent_campaign_id: parentCampaignId,
        }),
    }).then(async resp => {
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const ev = JSON.parse(line.slice(6));
                    handlePipelineSSE(ev);
                } catch {}
            }
        }
    }).catch(e => {
        console.error('Find Similar error:', e);
        handlePipelineSSE({ type: 'error', text: 'Connection error: ' + e.message });
    }).finally(() => {
        _prospectPipelineRunning = false;
        const finishedCampaignId = _currentRunCampaignId;
        _currentRunCampaignId = null;
        _savedLivePipelineDOM = null;
        const btn = document.getElementById('prospect-run-btn');
        if (btn) { btn.disabled = false; btn.textContent = 'Search'; }
        loadCampaigns().then(() => {
            // After loading, if the parent now has children, render the tree
            if (_activeTreeRootId || activeCampaignId) {
                const rootId = _activeTreeRootId || activeCampaignId;
                const root = allCampaigns.find(x => x.id === rootId);
                if (root && root.children && root.children.length > 0) {
                    _activeTreeRootId = rootId;
                    renderDiscoveryTree(rootId);
                } else if (finishedCampaignId) {
                    renderExecutionPane(finishedCampaignId);
                }
            } else if (finishedCampaignId) {
                renderExecutionPane(finishedCampaignId);
            }
        });
    });
}

// ===================== ICP PROFILES =====================
let allIcpProfiles = [];
let activeIcpProfileId = null;
let _icpWizardStep = 0;
let _icpWizardMode = 'create'; // 'create' or 'edit'
let _icpEditData = null; // populated in edit mode
let _icpGeneratedConfig = null; // config from LLM generation
let _icpCustomerType = ''; // 'B2B', 'B2C', 'Both'

const _INDUSTRY_TREE = {
    B2B: {
        'Technology':              ['SaaS', 'Cybersecurity', 'AI / ML', 'DevTools', 'Cloud / Infra', 'E-commerce Platform', 'Other'],
        'Finance & Banking':       ['Banking / Sell Side', 'Asset Mgmt / Buy Side', 'Insurance', 'Payments / Fintech', 'Other'],
        'Professional Services':   ['Strategy Consulting', 'IT Consulting / SI', 'Legal', 'Accounting', 'Staffing / Recruiting', 'Other'],
        'Marketing & Advertising': ['Agency', 'Brand / In-house', 'AdTech', 'MarTech', 'PR / Communications', 'Other'],
        'Healthcare':              ['Pharma / Biotech', 'MedTech', 'Health IT', 'Providers', 'Payers', 'Other'],
        'Manufacturing':           ['Automotive', 'Aerospace', 'Electronics', 'Industrial', 'Other'],
        'Real Estate':             ['Commercial', 'Residential', 'PropTech', 'Other'],
        'Education':               ['EdTech', 'Higher Ed', 'K-12', 'Corporate Training', 'Other'],
    },
    B2C: {
        'Retail & E-commerce':     ['Fashion / Apparel', 'Beauty / Personal Care', 'Home Goods', 'Electronics', 'Other'],
        'Food & Beverage':         ['Restaurants / QSR', 'CPG Food', 'Beverage', 'D2C Food', 'Other'],
        'Health & Wellness':       ['Fitness', 'Supplements', 'Mental Health', 'Telehealth', 'Other'],
        'Entertainment & Media':   ['Streaming', 'Gaming', 'Publishing', 'Events', 'Other'],
        'Travel & Hospitality':    ['Hotels', 'Airlines', 'Tourism', 'Other'],
        'Financial Services':      ['Banking', 'Insurance', 'Investing / Wealth', 'Lending', 'Other'],
    },
};
// "Both" merges both trees
_INDUSTRY_TREE.Both = { ..._INDUSTRY_TREE.B2B, ..._INDUSTRY_TREE.B2C };

// Niche-detail placeholders based on sub-industry
const _NICHE_HINTS = {
    'SaaS': 'e.g. HR Tech, payroll automation, CRM',
    'Cybersecurity': 'e.g. endpoint security, identity management',
    'AI / ML': 'e.g. computer vision, NLP, MLOps',
    'DevTools': 'e.g. CI/CD, observability, testing',
    'Banking / Sell Side': 'e.g. investment banking, commercial lending',
    'Asset Mgmt / Buy Side': 'e.g. hedge funds, PE, wealth management',
    'Payments / Fintech': 'e.g. payment processing, neobanks, BNPL',
    'Strategy Consulting': 'e.g. MBB, boutique strategy firms',
    'IT Consulting / SI': 'e.g. Big 4, systems integrators',
    'Agency': 'e.g. creative agency, media buying, performance marketing',
    'Brand / In-house': 'e.g. demand gen, growth marketing teams',
    'AdTech': 'e.g. DSP, SSP, CTV advertising',
    'MarTech': 'e.g. email platforms, CDPs, analytics',
    'Fashion / Apparel': 'e.g. DTC fashion, streetwear, luxury',
    'Beauty / Personal Care': 'e.g. skincare, cosmetics, clean beauty',
    'Restaurants / QSR': 'e.g. fast-casual chains, ghost kitchens',
    'CPG Food': 'e.g. snack brands, organic food, frozen meals',
    'Fitness': 'e.g. gym chains, at-home fitness, wearables',
};

function _renderIndustryChips(containerId, items, savedVal, singleSelect) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const onclick = singleSelect
        ? `this.parentElement.querySelectorAll('.icp-chip').forEach(c=>c.classList.remove('selected'));this.classList.add('selected');_onIndustrySelect('${containerId}',this.textContent)`
        : `this.classList.toggle('selected')`;
    el.innerHTML = items.map(s => {
        const sel = s === savedVal ? ' selected' : '';
        return `<div class="icp-chip${sel}" onclick="${onclick}">${s}</div>`;
    }).join('');
}

function _onIndustrySelect(containerId, value) {
    if (containerId === 'icp-q-customer-type') {
        _icpCustomerType = value;
        // Re-render industry chips
        const industries = Object.keys(_INDUSTRY_TREE[value] || {});
        industries.push('Other');
        _renderIndustryChips('icp-q-industry', industries, '', true);
        document.getElementById('icp-q-sub-industry').innerHTML = '';
        document.getElementById('icp-q-niche-detail').placeholder = 'e.g. anything more specific about your area';
        _updateAdaptiveSteps();
    } else if (containerId === 'icp-q-industry') {
        // Re-render sub-industry chips
        const tree = _INDUSTRY_TREE[_icpCustomerType] || _INDUSTRY_TREE.B2B;
        const subs = tree[value] || ['Other'];
        _renderIndustryChips('icp-q-sub-industry', subs, '', true);
        document.getElementById('icp-q-niche-detail').placeholder = 'e.g. anything more specific about your area';
    } else if (containerId === 'icp-q-sub-industry') {
        const hint = _NICHE_HINTS[value] || 'e.g. anything more specific about your area';
        document.getElementById('icp-q-niche-detail').placeholder = hint;
    }
}

function _updateAdaptiveSteps() {
    // Show/hide B2B vs B2C content in steps 2 and 3
    const isB2C = _icpCustomerType === 'B2C';
    document.querySelectorAll('.icp-b2b-content').forEach(el => el.style.display = isB2C ? 'none' : '');
    document.querySelectorAll('.icp-b2c-content').forEach(el => el.style.display = isB2C ? '' : 'none');
}

async function loadIcpProfiles() {
    try {
        const resp = await fetch('/api/icp-profiles');
        if (resp.ok) allIcpProfiles = await resp.json();
        else allIcpProfiles = [];
    } catch (e) { console.error('loadIcpProfiles failed:', e); allIcpProfiles = []; }

    const active = allIcpProfiles.find(p => p.is_active);
    activeIcpProfileId = active ? active.id : null;

    // Update indicator name
    const nameEl = document.getElementById('icp-indicator-name');
    nameEl.textContent = active ? active.name : 'No profile';
    nameEl.dataset.profileId = active ? active.id : '';

    // Build popover list
    const listEl = document.getElementById('icp-popover-list');
    if (allIcpProfiles.length) {
        listEl.innerHTML = allIcpProfiles.map(p =>
            `<div class="icp-popover-item${p.is_active ? ' active' : ''}" onclick="closeIcpPopover(); switchIcpProfile(${p.id});">` +
            `<span class="icp-popover-dot"></span>` +
            `<span class="icp-popover-item-name">${escHtml(p.name)}${p.is_default ? ' (default)' : ''}</span></div>`
        ).join('');
    } else {
        listEl.innerHTML = '<div style="padding:10px;font-size:12px;color:var(--text-muted);text-align:center;">No ICP profiles yet</div>';
    }

    // Render niche suggestions from active profile config
    _renderNicheSuggestions(active);
}

function _renderNicheSuggestions(profile) {
    const container = document.getElementById('niche-suggestions');
    if (!container) return;
    const niches = profile?.config?.suggested_niches || [];
    if (!niches.length) { container.style.display = 'none'; return; }
    container.style.display = '';
    container.innerHTML = '<span class="niche-suggestion-label">Try:</span> ' +
        niches.map(n => `<span class="niche-chip" onclick="document.getElementById('prospect-niche-input').value='${escHtml(n)}';this.parentElement.style.display='none'">${escHtml(n)}</span>`).join('');
}

async function switchIcpProfile(id) {
    if (!id) return;
    id = parseInt(id);
    if (id === activeIcpProfileId) return;
    try {
        await fetch(`/api/icp-profiles/${id}/activate`, { method: 'POST' });
        activeIcpProfileId = id;
        await loadIcpProfiles();
        await loadCampaigns();
        // Clear all panes
        _resetAllPanes();
    } catch (e) { console.error('switchIcpProfile failed:', e); }
}

function toggleIcpPopover() {
    document.getElementById('icp-indicator-wrap').classList.toggle('open');
}
function closeIcpPopover() {
    document.getElementById('icp-indicator-wrap').classList.remove('open');
}
// Close popover on outside click
document.addEventListener('click', function(e) {
    const wrap = document.getElementById('icp-indicator-wrap');
    if (wrap && !wrap.contains(e.target)) closeIcpPopover();
});

function togglePreRevenue() {
    const wrap = document.getElementById('icp-best-customers-wrap');
    const label = document.getElementById('icp-best-customers-label');
    const check = document.getElementById('icp-pre-revenue-check');
    const isOn = wrap.dataset.preRevenue === 'true';
    wrap.dataset.preRevenue = isOn ? 'false' : 'true';
    label.textContent = isOn ? "Describe 2-3 of your best customers, or the type of company you'd love to sell to" : 'Describe your dream customers';
    check.innerHTML = isOn ? '' : '&#10003; ';
}

function openIcpWizard() {
    _icpWizardMode = 'create';
    _icpWizardStep = 0;
    _icpEditData = null;
    _icpGeneratedConfig = null;
    _renderIcpWizard();
}

function openIcpEditor() {
    const active = allIcpProfiles.find(p => p.id === activeIcpProfileId);
    if (!active) return;
    _icpWizardMode = 'edit';
    _icpWizardStep = 0;
    _icpEditData = active;
    _icpGeneratedConfig = active.config || null;
    _renderIcpWizard();
}

function _renderIcpWizard() {
    // Remove existing wizard if any
    const existing = document.querySelector('.icp-wizard-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'icp-wizard-overlay';
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeIcpWizard(); });

    const isEdit = _icpWizardMode === 'edit';
    const sa = isEdit && _icpEditData?.survey_answers ? _icpEditData.survey_answers : {};
    const title = isEdit ? 'Edit ICP Profile' : 'New ICP Profile';

    overlay.innerHTML = `<div class="icp-wizard">
        <div class="icp-wizard-header">
            <h2>${title}</h2>
            <button class="icp-wizard-close" onclick="closeIcpWizard()">&times;</button>
        </div>
        <div class="icp-wizard-steps">
            <div class="icp-step-dot active"></div>
            <div class="icp-step-dot"></div>
            <div class="icp-step-dot"></div>
            <div class="icp-step-dot"></div>
            <div class="icp-step-dot"></div>
        </div>
        <div class="icp-wizard-body">
            <!-- Step 0: Your Business (THE FUNNEL) -->
            <div class="icp-wizard-step active" data-step="0">
                <h3>Your Business</h3>
                <div class="step-desc">Let's narrow things down — a few clicks and we'll know your world.</div>
                <div class="icp-field">
                    <label>Who do you sell to?</label>
                    <div class="icp-chips" id="icp-q-customer-type">
                        ${['B2B', 'B2C', 'Both'].map(s => {
                            const sel = sa.customer_type === s ? ' selected' : '';
                            const desc = s === 'B2B' ? 'Businesses' : s === 'B2C' ? 'Consumers' : 'Both';
                            return `<div class="icp-chip${sel}" onclick="this.parentElement.querySelectorAll('.icp-chip').forEach(c=>c.classList.remove('selected'));this.classList.add('selected');_onIndustrySelect('icp-q-customer-type','${s}')">${s} <span style="opacity:.5;font-size:10px">(${desc})</span></div>`;
                        }).join('')}
                    </div>
                </div>
                <div class="icp-field">
                    <label>What industry are you in?</label>
                    <div class="icp-chips" id="icp-q-industry"></div>
                </div>
                <div class="icp-field">
                    <label>What's your specific area?</label>
                    <div class="icp-chips" id="icp-q-sub-industry"></div>
                </div>
                <div class="icp-field">
                    <label>Anything more specific?</label>
                    <div class="field-hint">Optional — helps the AI generate a more precise profile.</div>
                    <input type="text" id="icp-q-niche-detail" placeholder="e.g. anything more specific about your area" value="${escHtml(sa.niche_detail || '')}">
                </div>
            </div>

            <!-- Step 1: Your Offer -->
            <div class="icp-wizard-step" data-step="1">
                <h3>Your Offer</h3>
                <div class="step-desc">No jargon needed — just tell us what you do.</div>
                <div class="icp-field">
                    <label>What does your company do?</label>
                    <div class="field-hint">Describe it like you would to a friend.</div>
                    <textarea id="icp-q-product" placeholder="e.g. We help restaurants manage their online orders and delivery from one dashboard...">${escHtml(sa.product || '')}</textarea>
                </div>
                <div class="icp-field">
                    <label>What problem does it solve?</label>
                    <div class="field-hint">What was happening before they used you? What changes after?</div>
                    <textarea id="icp-q-problem" placeholder="e.g. They were juggling 5 different tablets for UberEats, DoorDash, etc. and losing orders...">${escHtml(sa.problem || '')}</textarea>
                </div>
            </div>

            <!-- Step 2: Your Customers (B2B + B2C adaptive) -->
            <div class="icp-wizard-step" data-step="2">
                <h3>Your Customers</h3>
                <div class="step-desc">Help us understand who you sell to — or want to sell to.</div>

                <!-- B2B content -->
                <div class="icp-b2b-content">
                    <div class="icp-field" id="icp-best-customers-wrap" data-pre-revenue="${sa.pre_revenue ? 'true' : 'false'}">
                        <label id="icp-best-customers-label">${sa.pre_revenue ? 'Describe your dream customers' : 'Describe 2-3 of your best customers or dream customers'}</label>
                        <textarea id="icp-q-best-customers" placeholder="e.g. Glossier, Warby Parker — DTC brands doing $5-50M that are scaling their ad spend">${escHtml(sa.best_customers || '')}</textarea>
                        <div class="icp-escape-hatch" onclick="togglePreRevenue()">
                            <span id="icp-pre-revenue-check">${sa.pre_revenue ? '&#10003; ' : ''}</span>I haven't sold yet / I'm pre-revenue
                        </div>
                    </div>
                    <div class="icp-field">
                        <label>How big are they typically?</label>
                        <div class="icp-chips" id="icp-q-sizes">
                            ${['Startup (<$1M)', 'Small biz ($1M-$10M)', 'Mid-market ($10M-$200M)', 'Enterprise ($200M+)', 'Not sure'].map(s => {
                                const sel = (sa.sizes || []).includes(s) ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.classList.toggle('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                    </div>
                    <div class="icp-field">
                        <label>What do they have in common?</label>
                        <div class="icp-chips" id="icp-q-commonalities">
                            ${['Growing fast', 'VC-backed', 'Hiring aggressively', 'Modernizing tech stack', 'Heavy ad spend', 'Compliance-driven', 'Digital-native'].map(s => {
                                const sel = (sa.commonalities || []).includes(s) ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.classList.toggle('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                        <textarea id="icp-q-commonalities-other" placeholder="Anything else they have in common?" style="margin-top:8px;min-height:40px">${escHtml(sa.commonalities_other || '')}</textarea>
                    </div>
                </div>

                <!-- B2C content (hidden by default) -->
                <div class="icp-b2c-content" style="display:none">
                    <div class="icp-field">
                        <label>Describe your ideal customer</label>
                        <textarea id="icp-q-ideal-consumer" placeholder="e.g. Health-conscious millennials who shop online and care about ingredients...">${escHtml(sa.ideal_consumer || '')}</textarea>
                    </div>
                    <div class="icp-field">
                        <label>What's your typical price point?</label>
                        <div class="icp-chips" id="icp-q-price-point">
                            ${['Under $25', '$25 - $100', '$100 - $500', '$500+', 'Varies'].map(s => {
                                const sel = sa.price_point === s ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.parentElement.querySelectorAll('.icp-chip').forEach(c=>c.classList.remove('selected'));this.classList.add('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                    </div>
                    <div class="icp-field">
                        <label>Where do they buy?</label>
                        <div class="icp-chips" id="icp-q-where-they-buy">
                            ${['Your website', 'Amazon / marketplace', 'Retail stores', 'Subscription', 'App', 'Other'].map(s => {
                                const sel = (sa.where_they_buy || []).includes(s) ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.classList.toggle('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                    </div>
                    <div class="icp-field">
                        <label>What do they have in common?</label>
                        <div class="icp-chips" id="icp-q-consumer-traits">
                            ${['Health-conscious', 'Premium buyers', 'Budget-conscious', 'Trend followers', 'Eco-conscious', 'Tech-savvy', 'Young adults (18-35)', 'Parents'].map(s => {
                                const sel = (sa.consumer_traits || []).includes(s) ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.classList.toggle('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Step 3: How You Sell (B2B + B2C adaptive) -->
            <div class="icp-wizard-step" data-step="3">
                <h3>How You Sell</h3>
                <div class="step-desc">Last step — tell us about your sales process.</div>

                <!-- B2B content -->
                <div class="icp-b2b-content">
                    <div class="icp-field">
                        <label>How do customers buy from you?</label>
                        <div class="icp-chips" id="icp-q-how-they-buy">
                            ${['Self-serve', 'Demos / sales calls', 'Enterprise sales', 'Partners / referrals', 'Mix', 'Haven\'t sold yet'].map(s => {
                                const sel = sa.how_they_buy === s ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.parentElement.querySelectorAll('.icp-chip').forEach(c=>c.classList.remove('selected'));this.classList.add('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                    </div>
                    <div class="icp-field">
                        <label>Typical deal size?</label>
                        <div class="icp-chips" id="icp-q-deal-size">
                            ${['Under $5K', '$5K - $25K', '$25K - $100K', '$100K - $500K', '$500K+', 'Not sure'].map(s => {
                                const sel = sa.deal_size === s ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.parentElement.querySelectorAll('.icp-chip').forEach(c=>c.classList.remove('selected'));this.classList.add('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                    </div>
                    <div class="icp-field">
                        <label>How long to close a deal?</label>
                        <div class="icp-chips" id="icp-q-sales-cycle">
                            ${['Days', 'Weeks', 'Months', '6+ months', 'Not sure'].map(s => {
                                const sel = sa.sales_cycle === s ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.parentElement.querySelectorAll('.icp-chip').forEach(c=>c.classList.remove('selected'));this.classList.add('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                    </div>
                </div>

                <!-- B2C content (hidden by default) -->
                <div class="icp-b2c-content" style="display:none">
                    <div class="icp-field">
                        <label>How do customers find you?</label>
                        <div class="icp-chips" id="icp-q-acquisition-channels">
                            ${['Social media', 'Search / SEO', 'Word of mouth', 'Paid ads', 'Retail / in-store', 'Influencers', 'Other'].map(s => {
                                const sel = (sa.acquisition_channels || []).includes(s) ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.classList.toggle('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                    </div>
                    <div class="icp-field">
                        <label>How often do they buy?</label>
                        <div class="icp-chips" id="icp-q-purchase-frequency">
                            ${['One-time', 'Monthly', 'Quarterly', 'Yearly', 'Varies'].map(s => {
                                const sel = sa.purchase_frequency === s ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.parentElement.querySelectorAll('.icp-chip').forEach(c=>c.classList.remove('selected'));this.classList.add('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                    </div>
                    <div class="icp-field">
                        <label>Average order value?</label>
                        <div class="icp-chips" id="icp-q-avg-order-value">
                            ${['Under $25', '$25 - $100', '$100 - $500', '$500+', 'Not sure'].map(s => {
                                const sel = sa.avg_order_value === s ? ' selected' : '';
                                return `<div class="icp-chip${sel}" onclick="this.parentElement.querySelectorAll('.icp-chip').forEach(c=>c.classList.remove('selected'));this.classList.add('selected')">${s}</div>`;
                            }).join('')}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Step 4: Review -->
            <div class="icp-wizard-step" data-step="4">
                <div id="icp-review-content">
                    ${_icpGeneratedConfig ? _renderReviewStep(_icpGeneratedConfig, isEdit ? _icpEditData.name : '') : `
                    <h3>Generate ICP Config</h3>
                    <div class="step-desc">We'll use AI to generate your scoring dimensions, weights, and rubrics from your answers.</div>
                    <div style="text-align:center;padding:20px 0">
                        <button class="icp-wizard-btn-next" onclick="icpWizardGenerate()" id="icp-generate-btn">Generate ICP Config</button>
                    </div>`}
                </div>
            </div>
        </div>
        <div class="icp-wizard-nav">
            <button class="icp-wizard-btn-back" onclick="icpWizardBack()" id="icp-back-btn" style="visibility:hidden">Back</button>
            <div id="icp-nav-right">
                <button class="icp-wizard-btn-next" onclick="icpWizardNext()" id="icp-next-btn">Next</button>
            </div>
        </div>
    </div>`;

    document.body.appendChild(overlay);
    _updateWizardStepUI();

    // Initialize funnel chips from saved state (edit mode) or default
    if (sa.customer_type) {
        _icpCustomerType = sa.customer_type;
        const industries = Object.keys(_INDUSTRY_TREE[sa.customer_type] || {});
        industries.push('Other');
        _renderIndustryChips('icp-q-industry', industries, sa.industry || '', true);
        if (sa.industry) {
            const tree = _INDUSTRY_TREE[sa.customer_type] || {};
            const subs = tree[sa.industry] || ['Other'];
            _renderIndustryChips('icp-q-sub-industry', subs, sa.sub_industry || '', true);
            if (sa.sub_industry) {
                const hint = _NICHE_HINTS[sa.sub_industry] || 'e.g. anything more specific about your area';
                document.getElementById('icp-q-niche-detail').placeholder = hint;
            }
        }
        _updateAdaptiveSteps();
    } else {
        _icpCustomerType = '';
    }

    // Escape key to close
    overlay._escHandler = (e) => { if (e.key === 'Escape') closeIcpWizard(); };
    document.addEventListener('keydown', overlay._escHandler);
}

function _renderReviewStep(config, profileName) {
    const dims = config.dimensions || [];
    let dimSliders = dims.map((d, i) => `<div class="icp-dim-edit">
        <span class="dim-name" title="${escHtml(d.label)}">${escHtml(d.label)}</span>
        <input type="range" min="5" max="50" value="${Math.round(d.weight * 100)}" oninput="this.nextElementSibling.textContent=this.value+'%'" data-dim-idx="${i}">
        <span class="dim-weight">${Math.round(d.weight * 100)}%</span>
    </div>`).join('');

    const filters = config.discovery_filters || {};
    return `
        <h3>Review & Customize</h3>
        <div class="step-desc">Fine-tune your ICP before saving. Adjust weights, edit the definition, and tweak filters.</div>
        <div class="icp-field">
            <label>Profile Name</label>
            <input type="text" id="icp-review-name" value="${escHtml(profileName || '')}" placeholder="e.g. DTC Beauty Brands">
        </div>
        <div class="icp-field">
            <label>ICP Definition (editable)</label>
            <textarea id="icp-review-definition" style="min-height:90px">${escHtml(config.icp_definition || '')}</textarea>
        </div>
        <div class="icp-field">
            <label>Scoring Dimensions & Weights</label>
            <div id="icp-review-dims">${dimSliders}</div>
        </div>
        <div class="icp-field">
            <label>Discovery Include Filter</label>
            <textarea id="icp-review-include" style="min-height:50px">${escHtml(filters.include_description || '')}</textarea>
        </div>
        <div class="icp-field">
            <label>Discovery Exclude Filter</label>
            <textarea id="icp-review-exclude" style="min-height:50px">${escHtml(filters.exclude_description || '')}</textarea>
        </div>`;
}

function closeIcpWizard() {
    const overlay = document.querySelector('.icp-wizard-overlay');
    if (overlay) {
        if (overlay._escHandler) document.removeEventListener('keydown', overlay._escHandler);
        overlay.remove();
    }
}

// ===================== NICHE BUILDER MODAL =====================

function _nbSingleSelect(chipEl) {
    const wasSelected = chipEl.classList.contains('selected');
    chipEl.parentElement.querySelectorAll('.icp-chip').forEach(c => c.classList.remove('selected'));
    if (!wasSelected) chipEl.classList.add('selected');
}

function buildNicheString() {
    const parts = [];
    const sizeChip = document.querySelector('#nb-company-size .icp-chip.selected');
    if (sizeChip) parts.push(sizeChip.dataset.value);
    const modelChip = document.querySelector('#nb-business-model .icp-chip.selected');
    if (modelChip) {
        const val = modelChip.dataset.value;
        parts.push(val === 'Both' ? 'B2B/B2C' : val);
    }
    const vertical = (document.getElementById('nb-vertical')?.value || '').trim();
    if (vertical) parts.push(vertical);
    const geoCustom = (document.getElementById('nb-geography-custom')?.value || '').trim();
    const geoChip = document.querySelector('#nb-geography .icp-chip.selected');
    if (geoCustom) parts.push(geoCustom);
    else if (geoChip) parts.push(geoChip.dataset.value);
    const qualifiers = (document.getElementById('nb-qualifiers')?.value || '').trim();
    if (qualifiers) parts.push(qualifiers);
    return parts.join(' ');
}

function applyNicheBuilder() {
    const niche = buildNicheString();
    if (niche) document.getElementById('prospect-niche-input').value = niche;
    closeNicheBuilder();
    document.getElementById('prospect-niche-input').focus();
}

function closeNicheBuilder() {
    const overlay = document.querySelector('.niche-builder-overlay');
    if (overlay) {
        if (overlay._escHandler) document.removeEventListener('keydown', overlay._escHandler);
        overlay.remove();
    }
}

function openNicheBuilder() {
    const existing = document.querySelector('.niche-builder-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'niche-builder-overlay';
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeNicheBuilder(); });

    const chipRow = (items) => items.map(s =>
        `<div class="icp-chip" data-value="${s}">${s}</div>`
    ).join('');

    overlay.innerHTML = `<div class="niche-builder-modal">
        <div class="niche-builder-header">
            <h2>Niche Builder</h2>
            <button class="icp-wizard-close" onclick="closeNicheBuilder()">&times;</button>
        </div>
        <div class="niche-builder-body">
            <div class="icp-field">
                <label>Business Model</label>
                <div class="icp-chips" id="nb-business-model">${chipRow(['B2B', 'B2C', 'Both'])}</div>
            </div>
            <div class="icp-field">
                <label>Company Size</label>
                <div class="icp-chips" id="nb-company-size">${chipRow(['Startup', 'SMB', 'Midmarket', 'Enterprise'])}</div>
            </div>
            <div class="icp-field">
                <label>Vertical / Industry</label>
                <input type="text" id="nb-vertical" placeholder="e.g. pet health, fintech, beauty, SaaS">
            </div>
            <div class="icp-field">
                <label>Geography</label>
                <div class="icp-chips" id="nb-geography">${chipRow(['US', 'North America', 'Europe', 'Global'])}</div>
                <input type="text" id="nb-geography-custom" placeholder="Or type a specific region..." style="margin-top:6px">
            </div>
            <div class="icp-field">
                <label>Additional Qualifiers</label>
                <input type="text" id="nb-qualifiers" placeholder="e.g. DTC only, VC-backed, subscription model">
            </div>
            <div class="niche-builder-preview-label">Preview</div>
            <div class="niche-builder-preview" id="nb-preview">Select options above to build a niche query...</div>
        </div>
        <div class="niche-builder-footer">
            <button class="icp-wizard-btn-back" onclick="closeNicheBuilder()">Cancel</button>
            <button class="icp-wizard-btn-next" onclick="applyNicheBuilder()">Build Niche</button>
        </div>
    </div>`;

    document.body.appendChild(overlay);

    // Live preview: update on chip clicks and text input
    const updatePreview = () => {
        const el = document.getElementById('nb-preview');
        if (el) el.textContent = buildNicheString() || 'Select options above to build a niche query...';
    };
    overlay.querySelectorAll('.icp-chip').forEach(chip => {
        chip.addEventListener('click', function() { _nbSingleSelect(this); updatePreview(); });
    });
    ['nb-vertical', 'nb-geography-custom', 'nb-qualifiers'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', updatePreview);
    });

    // Focus the vertical input for quick typing
    const vertInput = document.getElementById('nb-vertical');
    if (vertInput) setTimeout(() => vertInput.focus(), 50);

    // Escape to close
    overlay._escHandler = (e) => { if (e.key === 'Escape') closeNicheBuilder(); };
    document.addEventListener('keydown', overlay._escHandler);
}

function icpWizardNext() {
    if (_icpWizardStep >= 4) return;
    _icpWizardStep++;
    _updateWizardStepUI();
}

function icpWizardBack() {
    if (_icpWizardStep <= 0) return;
    _icpWizardStep--;
    _updateWizardStepUI();
}

function _updateWizardStepUI() {
    const overlay = document.querySelector('.icp-wizard-overlay');
    if (!overlay) return;

    // Update step dots
    overlay.querySelectorAll('.icp-step-dot').forEach((dot, i) => {
        dot.className = 'icp-step-dot';
        if (i < _icpWizardStep) dot.classList.add('done');
        if (i === _icpWizardStep) dot.classList.add('active');
    });

    // Show/hide steps
    overlay.querySelectorAll('.icp-wizard-step').forEach(s => {
        s.classList.toggle('active', parseInt(s.dataset.step) === _icpWizardStep);
    });

    // Back button
    const backBtn = document.getElementById('icp-back-btn');
    if (backBtn) backBtn.style.visibility = _icpWizardStep === 0 ? 'hidden' : 'visible';

    // Nav right: show Next for steps 0-3, Save for step 4
    const navRight = document.getElementById('icp-nav-right');
    if (navRight) {
        if (_icpWizardStep < 4) {
            navRight.innerHTML = '<button class="icp-wizard-btn-next" onclick="icpWizardNext()" id="icp-next-btn">Next</button>';
        } else if (_icpGeneratedConfig) {
            navRight.innerHTML = '<button class="icp-wizard-btn-save" onclick="icpWizardSave()" id="icp-save-btn">Save & Activate</button>';
        } else {
            navRight.innerHTML = '';
        }
    }
}

function _gatherSurveyAnswers() {
    const overlay = document.querySelector('.icp-wizard-overlay');
    if (!overlay) return {};
    const _chips = (id) => { const arr = []; overlay.querySelectorAll(`#${id} .icp-chip.selected`).forEach(c => { let t = c.textContent.trim(); if (c.querySelector('span')) t = c.childNodes[0].textContent.trim(); arr.push(t); }); return arr; };
    const _chip1 = (id) => { const el = overlay.querySelector(`#${id} .icp-chip.selected`); if (!el) return ''; let t = el.textContent.trim(); if (el.querySelector('span')) t = el.childNodes[0].textContent.trim(); return t; };
    const _val = (id) => (document.getElementById(id)?.value || '').trim();
    const preRev = document.getElementById('icp-best-customers-wrap')?.dataset.preRevenue === 'true';
    const isB2C = _icpCustomerType === 'B2C';
    return {
        // Step 0 — funnel
        customer_type: _icpCustomerType,
        industry: _chip1('icp-q-industry'),
        sub_industry: _chip1('icp-q-sub-industry'),
        niche_detail: _val('icp-q-niche-detail'),
        // Step 1 — offer
        product: _val('icp-q-product'),
        problem: _val('icp-q-problem'),
        // Step 2 — B2B customers
        best_customers: _val('icp-q-best-customers'),
        pre_revenue: preRev,
        sizes: _chips('icp-q-sizes'),
        commonalities: _chips('icp-q-commonalities'),
        commonalities_other: _val('icp-q-commonalities-other'),
        // Step 2 — B2C customers
        ideal_consumer: _val('icp-q-ideal-consumer'),
        price_point: _chip1('icp-q-price-point'),
        where_they_buy: _chips('icp-q-where-they-buy'),
        consumer_traits: _chips('icp-q-consumer-traits'),
        // Step 3 — B2B sales
        how_they_buy: _chip1('icp-q-how-they-buy'),
        deal_size: _chip1('icp-q-deal-size'),
        sales_cycle: _chip1('icp-q-sales-cycle'),
        // Step 3 — B2C sales
        acquisition_channels: _chips('icp-q-acquisition-channels'),
        purchase_frequency: _chip1('icp-q-purchase-frequency'),
        avg_order_value: _chip1('icp-q-avg-order-value'),
    };
}

async function icpWizardGenerate() {
    const answers = _gatherSurveyAnswers();
    if (!answers.customer_type) { _showToast('Please select who you sell to (B2B, B2C, or Both)', 'warn'); _icpWizardStep = 0; _updateWizardStepUI(); return; }
    if (!answers.product) { _showToast('Please describe what your company does', 'warn'); _icpWizardStep = 1; _updateWizardStepUI(); return; }

    const genBtn = document.getElementById('icp-generate-btn');
    const reviewContent = document.getElementById('icp-review-content');
    reviewContent.innerHTML = `<div class="icp-generate-spinner">
        <div class="spinner"></div>
        Generating your ICP scoring config...
    </div>`;

    try {
        const resp = await fetch('/api/icp-profiles/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ survey_answers: answers }),
        });
        if (!resp.ok) throw new Error('Generation failed');
        const data = await resp.json();
        _icpGeneratedConfig = data.config;

        // Auto-generate a name suggestion from product
        const autoName = answers.product.substring(0, 40).split(/[.,;]/)[0].trim();

        reviewContent.innerHTML = _renderReviewStep(_icpGeneratedConfig, autoName);
        _updateWizardStepUI();
    } catch (e) {
        console.error('ICP generation failed:', e);
        reviewContent.innerHTML = `<h3>Generation Failed</h3>
            <div class="step-desc" style="color:var(--red)">Could not generate ICP config. Please try again.</div>
            <div style="text-align:center;padding:20px 0">
                <button class="icp-wizard-btn-next" onclick="icpWizardGenerate()" id="icp-generate-btn">Retry</button>
            </div>`;
    }
}

async function icpWizardSave() {
    if (!_icpGeneratedConfig) return;

    // Read user edits from the review step
    const name = (document.getElementById('icp-review-name')?.value || '').trim();
    if (!name) { _showToast('Please enter a profile name', 'warn'); return; }

    const config = JSON.parse(JSON.stringify(_icpGeneratedConfig)); // deep copy
    config.icp_definition = document.getElementById('icp-review-definition')?.value || config.icp_definition;

    // Read dimension weight adjustments
    const sliders = document.querySelectorAll('#icp-review-dims input[type="range"]');
    let totalWeight = 0;
    sliders.forEach(s => { totalWeight += parseInt(s.value); });
    if (totalWeight > 0) {
        sliders.forEach(s => {
            const idx = parseInt(s.dataset.dimIdx);
            if (config.dimensions[idx]) {
                config.dimensions[idx].weight = Math.round((parseInt(s.value) / totalWeight) * 100) / 100;
            }
        });
    }

    // Read discovery filter edits
    if (!config.discovery_filters) config.discovery_filters = {};
    config.discovery_filters.include_description = document.getElementById('icp-review-include')?.value || '';
    config.discovery_filters.exclude_description = document.getElementById('icp-review-exclude')?.value || '';

    const survey_answers = _gatherSurveyAnswers();
    const saveBtn = document.getElementById('icp-save-btn');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving...'; }

    try {
        let resp;
        if (_icpWizardMode === 'edit' && _icpEditData) {
            resp = await fetch(`/api/icp-profiles/${_icpEditData.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, config, survey_answers }),
            });
        } else {
            resp = await fetch('/api/icp-profiles', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, config, survey_answers }),
            });
        }
        if (!resp.ok) throw new Error('Save failed');
        const data = await resp.json();

        // Activate the new/edited profile
        if (data.id) {
            await fetch(`/api/icp-profiles/${data.id}/activate`, { method: 'POST' });
        }

        closeIcpWizard();
        await loadIcpProfiles();
        await loadCampaigns();
    } catch (e) {
        console.error('ICP save failed:', e);
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save & Activate'; }
        _showToast('Failed to save ICP profile. Please try again.', 'error');
    }
}

