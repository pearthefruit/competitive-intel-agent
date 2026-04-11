// Pipeline Tree Renderer — extracted from base.html (Phase 1 refactor)
// Dependencies: escHtml() must be defined before this file loads

// ===================== SHARED PIPELINE TREE RENDERER (Flowchart Cards) =====================
//
// Renders pipeline stages as visual card nodes connected by arrows.
// Stage children are shown as inline chips (source badges) inside the card.
// Click a mini-card to expand its detail panel below the grid.
//

/** Toggle a single mini-card detail panel. Only one open at a time per card. */
function _toggleMiniDetail(cardId, idx) {
    const area = document.getElementById('ptree-details-' + cardId);
    if (!area) return;
    const panels = area.querySelectorAll('.ptree-mini-detail-panel');
    const target = document.getElementById('ptree-detail-' + cardId + '-' + idx);
    // Find the mini-card to toggle its selected state
    const fanout = area.closest('.ptree-fanout');
    const minis = fanout ? fanout.querySelectorAll('.ptree-mini') : [];

    const isOpen = target && target.style.display !== 'none';
    // Close all panels first
    panels.forEach(p => p.style.display = 'none');
    minis.forEach(m => m.classList.remove('selected'));
    // Toggle target
    if (!isOpen && target) {
        target.style.display = 'block';
        if (minis[idx]) minis[idx].classList.add('selected');
    }
}

function _ptreeStatusBg(status) {
    const m = { done: 'rgba(22,163,74,0.15)', running: 'rgba(168,85,247,0.15)', cached: 'rgba(59,130,246,0.15)', error: 'rgba(239,68,68,0.15)', skipped: 'rgba(107,114,128,0.15)' };
    return m[status] || 'rgba(255,255,255,0.06)';
}

/**
 * Render a tree of pipeline nodes as a flowchart into a container element.
 * Each top-level node is a card. Children become chips inside the card.
 */
function renderPipelineTree(nodes, container) {
    if (!container || !nodes || !nodes.length) return;
    const tree = nodes[0].children ? nodes : _assembleTreePT(nodes);
    let html = '<div class="ptree">';
    tree.forEach((node, i) => {
        if (i > 0) html += '<div class="ptree-arrow"></div>';
        html += _renderCard(node);
    });
    html += '</div>';
    container.innerHTML = html;
}

function _assembleTreePT(nodes) {
    const map = {};
    nodes.forEach(n => { map[n.id] = { ...n, children: [] }; });
    const roots = [];
    nodes.forEach(n => {
        if (n.parent_id && map[n.parent_id]) {
            map[n.parent_id].children.push(map[n.id]);
        } else {
            roots.push(map[n.id]);
        }
    });
    return roots;
}

/** Render a single card node with horizontal fan-out for children. */
function _renderCard(node) {
    const status = node.status || 'done';
    const iconBg = node.iconBg || _ptreeStatusBg(status);
    const iconHtml = node.icon
        ? `<div class="ptree-card-icon" style="background:${iconBg}">${node.icon}</div>`
        : '';
    const statusHtml = status !== 'done'
        ? `<span class="ptree-status ${status}">${status}</span>`
        : '';
    const summaryHtml = node.summary
        ? `<div class="ptree-card-summary">${escHtml(node.summary)}</div>`
        : '';

    const children = node.children || [];

    // Build horizontal fan-out — mini-cards branching from this stage
    let fanoutHtml = '';
    if (children.length > 0) {
        const cardId = (node.id || Math.random().toString(36).slice(2)).replace(/[^a-zA-Z0-9_-]/g, '_');
        const minis = children.map((child, idx) => {
            const cStatus = child.status || 'done';
            const cLabel = child.label || '?';
            const cSummary = child.summary || '';
            const cDetail = child.detail || '';
            const subCount = (child.children || []).length;
            const valueText = cSummary || (subCount > 0 ? `${subCount} steps` : '');
            const hasDetail = !!(cDetail && cDetail !== cSummary);
            const clickAttr = hasDetail
                ? `onclick="event.stopPropagation();_toggleMiniDetail('${cardId}',${idx})"`
                : '';
            return `<div class="ptree-mini ${cStatus}${hasDetail ? ' has-detail' : ''}" ${clickAttr} data-idx="${idx}" title="${escHtml(cLabel)}${valueText ? ': ' + escHtml(valueText) : ''}">
                <div class="ptree-mini-label">${escHtml(cLabel)}</div>
                ${valueText ? `<div class="ptree-mini-value">${escHtml(valueText)}</div>` : ''}
            </div>`;
        }).join('');

        // Per-child detail panels (only one visible at a time, below the grid)
        const detailPanels = children.map((child, idx) => {
            const cDetail = child.detail || '';
            if (!cDetail || cDetail === (child.summary || '')) return '';
            // _richDetail flag means the detail already contains safe HTML (links)
            const detailRendered = child._richDetail
                ? cDetail.replace(/\n/g, '<br>')
                : escHtml(cDetail).replace(/\n/g, '<br>');
            return `<div class="ptree-mini-detail-panel" id="ptree-detail-${cardId}-${idx}" style="display:none">
                <strong>${escHtml(child.label || '')}</strong><br>${detailRendered}
            </div>`;
        }).join('');

        fanoutHtml = `<div class="ptree-fanout">
            <div class="ptree-fanout-rail"></div>
            <div class="ptree-fanout-items">${minis}</div>
            ${detailPanels ? `<div class="ptree-detail-area" id="ptree-details-${cardId}">${detailPanels}</div>` : ''}
        </div>`;
    }

    const detailHtml = '';
    const chevronHtml = '';

    return `<div class="ptree-card status-${status}">
        <div class="ptree-card-header">
            ${iconHtml}
            <span class="ptree-card-label">${escHtml(node.label || '')}</span>
            ${statusHtml}
        </div>
        ${summaryHtml}
        ${fanoutHtml}
    </div>`;
}

// ===================== DISCOVER EXECUTION LOG → TREE NODES =====================

const _srcColors = { web: '#3b82f6', news: '#a855f7', gnews: '#a855f7', reddit: '#f97316' };
const _srcLabels = { web: 'Web', news: 'News', gnews: 'Google News', reddit: 'Reddit' };

/** Convert a Discover execution_log array into pipeline tree nodes. */
function _discoverLogToTree(executionLog, prospects, campaignLabel) {
    if (!executionLog || !executionLog.length) return [];
    const log = executionLog;

    // Build as flat array of top-level cards (each renders as its own ptree-card
    // with arrows between them). Children of each card become clickable mini-cards.
    const cards = [];

    // Root / label card
    const rootCard = {
        id: 'root', label: campaignLabel || 'Discovery', status: 'done',
        kind: 'root', icon: '&#128269;', iconBg: 'rgba(168,85,247,0.15)', children: [],
    };

    // Seed Profile — shown as mini-card inside root
    const seedProfile = log.find(e => e.type === 'seed_profile');
    if (seedProfile && seedProfile.profile) {
        const p = seedProfile.profile;
        const svc = Array.isArray(p.services) ? p.services.join(', ') : (p.services || '');
        rootCard.summary = `${p.industry || '?'} · ${p.scale || '?'} · ${p.client_type || '?'}`;
        rootCard.children.push({
            id: 'profile', label: `Profile: ${escHtml(seedProfile.company || '?')}`,
            status: 'done', kind: 'stage', icon: '&#128100;', iconBg: 'rgba(168,85,247,0.15)',
            summary: `${p.industry || '?'} · ${p.scale || '?'}`,
            detail: `Industry: ${escHtml(p.industry || '?')}\nScale: ${escHtml(p.scale || '?')}\nClient type: ${escHtml(p.client_type || '?')}\nServices: ${escHtml(svc)}`,
            children: [],
        });
    }
    cards.push(rootCard);

    // Search — own top-level card, source groups as mini-cards
    const searches = log.filter(e => e.type === 'search_done');
    const summary = log.find(e => e.type === 'search_complete');
    if (searches.length) {
        const unique = summary ? summary.unique_results : searches.reduce((s, e) => s + (e.results_count || 0), 0);
        const srcCounts = {};
        searches.forEach(s => { srcCounts[s.source] = (srcCounts[s.source] || 0) + 1; });
        const srcText = Object.entries(srcCounts).map(([k, v]) => `${v} ${_srcLabels[k] || k}`).join(', ');

        const searchCard = {
            id: 'search', label: 'Search', status: 'done', kind: 'stage',
            icon: '&#128269;', iconBg: 'rgba(59,130,246,0.15)',
            summary: `${searches.length} queries (${srcText}) → ${unique} unique`,
            children: [],
        };

        // Group searches by source — each source becomes a clickable mini-card
        const bySource = {};
        searches.forEach(s => {
            const src = s.source || 'web';
            if (!bySource[src]) bySource[src] = [];
            bySource[src].push(s);
        });

        Object.entries(bySource).forEach(([src, items]) => {
            const color = _srcColors[src] || '#6b7280';
            const label = _srcLabels[src] || src;
            const totalResults = items.reduce((s, e) => s + (e.results_count || 0), 0);
            // Build rich detail with results under each query
            const srcDetailParts = [];
            items.forEach(s => {
                srcDetailParts.push(`⟐ ${escHtml(s.query || '?')} → ${s.results_count || 0} results`);
                if (s.results && s.results.length) {
                    s.results.forEach(r => {
                        const title = r.title || 'Untitled';
                        const url = r.url || '';
                        const meta = [r.source, r.date].filter(Boolean).join(' · ');
                        if (url) {
                            srcDetailParts.push(`  ↳ <a href="${escHtml(url)}" target="_blank" rel="noopener" class="ptree-result-link">${escHtml(title)}</a>${meta ? ' <span class="ptree-result-meta">(' + escHtml(meta) + ')</span>' : ''}`);
                        } else {
                            srcDetailParts.push(`  ↳ ${escHtml(title)}${meta ? ' (' + escHtml(meta) + ')' : ''}`);
                        }
                    });
                }
            });
            const srcDetail = srcDetailParts.join('\n');
            searchCard.children.push({
                id: `search.${src}`, label: label, status: 'done', kind: 'stage',
                icon: '&#127760;', iconBg: `${color}22`,
                summary: `${items.length} queries → ${totalResults} results`,
                detail: srcDetail,
                _richDetail: true,
                children: [],
            });
        });

        if (summary) {
            searchCard.children.push({
                id: 'search.dedup', label: 'Deduplicate', status: 'done', kind: 'result',
                icon: '&#128200;', iconBg: 'rgba(22,163,74,0.15)',
                summary: `${summary.total_results} → ${summary.unique_results} unique`,
                children: [],
            });
        }
        cards.push(searchCard);
    }

    // AI Extraction — own top-level card, each company as a mini-card
    const extracted = log.find(e => e.type === 'extracted');
    if (extracted) {
        const details = extracted.company_details || [];
        const names = extracted.companies || [];
        const extractionCard = {
            id: 'extraction', label: 'AI Extraction', status: 'done', kind: 'stage',
            icon: '&#127919;', iconBg: 'rgba(168,85,247,0.15)',
            summary: `${names.length} companies`,
            children: [],
        };
        if (details.length) {
            extractionCard.children = details.map((c, i) => {
                const name = c.name || names[i] || '?';
                const lines = [];
                if (c.description) lines.push(escHtml(c.description));
                if (c.estimated_size) lines.push(`Size: ${escHtml(c.estimated_size)}`);
                if (c.website) lines.push(`<a href="${escHtml(c.website)}" target="_blank" rel="noopener" class="ptree-result-link">${escHtml(c.website)}</a>`);
                if (c.why_included) lines.push(`Why: ${escHtml(c.why_included)}`);
                return {
                    id: `extraction.${i}`, label: name, status: 'done', kind: 'result',
                    summary: c.estimated_size || '',
                    detail: lines.join('\n'),
                    _richDetail: true,
                    children: [],
                };
            });
        } else {
            // Fallback for old campaigns without company_details
            extractionCard.detail = escHtml(names.join(', '));
        }
        cards.push(extractionCard);
    }

    // Validation — own top-level card, per-company results as mini-cards
    const validations = log.filter(e => e.type === 'validated');
    if (validations.length) {
        const vValid = validations.filter(v => !v.limited && v.valid).length;
        const vLimited = validations.filter(v => v.limited).length;
        cards.push({
            id: 'validation', label: 'Validation', status: 'done', kind: 'stage',
            icon: '&#10003;', iconBg: 'rgba(22,163,74,0.15)',
            summary: `${vValid} valid${vLimited ? `, ${vLimited} limited` : ''}`,
            children: validations.map((v, i) => ({
                id: `validation.${i}`, label: v.company || '?',
                status: v.limited ? 'error' : v.valid ? 'done' : 'skipped',
                kind: 'result',
                summary: v.limited ? (v.reason || 'limited') : v.valid ? 'OK' : (v.reason || 'skipped'),
                detail: `Company: ${v.company || '?'}\nStatus: ${v.limited ? 'Limited' : v.valid ? 'Valid' : 'Skipped'}${v.reason ? '\nReason: ' + v.reason : ''}`,
                children: [],
            })),
        });
    } else if (prospects && prospects.length) {
        // Fallback from prospect data
        const _ls = ['limited', 'http_403', 'connection_failed'];
        const v = prospects.filter(p => p.validation_status === 'valid').length;
        const l = prospects.filter(p => _ls.includes(p.validation_status)).length;
        cards.push({
            id: 'validation', label: 'Validation', status: 'done', kind: 'stage',
            icon: '&#10003;', iconBg: 'rgba(22,163,74,0.15)',
            summary: `${v} valid${l ? `, ${l} limited` : ''}`,
            children: [],
        });
    }

    return cards;
}

// ===================== RESEARCH TOOL STEPS → TREE (BRIDGE) =====================

const _agentMeta = {
    financial:      { icon: '&#128200;', label: 'Financial Analysis',  bg: 'rgba(22,163,74,0.15)' },
    sentiment:      { icon: '&#128172;', label: 'Sentiment Analysis',  bg: 'rgba(234,179,8,0.15)' },
    techstack:      { icon: '&#9881;',   label: 'Techstack Analysis',  bg: 'rgba(59,130,246,0.15)' },
    lens:           { icon: '&#127919;', label: 'Lens Scoring',        bg: 'rgba(168,85,247,0.15)' },
    landscape:      { icon: '&#127758;', label: 'Landscape',           bg: 'rgba(107,114,128,0.15)' },
    competitors:    { icon: '&#9876;',   label: 'Competitors',         bg: 'rgba(239,68,68,0.15)' },
    patents:        { icon: '&#128218;', label: 'Patents',             bg: 'rgba(168,85,247,0.15)' },
    discover:       { icon: '&#128269;', label: 'Discovery',           bg: 'rgba(168,85,247,0.15)' },
    // Phase types (used by structured progress within individual agents)
    lookup:         { icon: '&#128270;', label: 'Industry Lookup',     bg: 'rgba(59,130,246,0.15)' },
    search:         { icon: '&#128269;', label: 'Patent Search',       bg: 'rgba(168,85,247,0.15)' },
    web_search:     { icon: '&#127760;', label: 'Web Search',          bg: 'rgba(59,130,246,0.15)' },
    deep_sources:   { icon: '&#128225;', label: 'Deep Sources',        bg: 'rgba(234,179,8,0.15)' },
    crawl:          { icon: '&#128424;', label: 'Site Crawl',          bg: 'rgba(107,114,128,0.15)' },
    analysis:       { icon: '&#128202;', label: 'SEO/AEO Analysis',   bg: 'rgba(59,130,246,0.15)' },
    pricing_detect: { icon: '&#128176;', label: 'Pricing Detection',  bg: 'rgba(22,163,74,0.15)' },
    report:         { icon: '&#128196;', label: 'Report Generation',   bg: 'rgba(22,163,74,0.15)' },
    dossier:        { icon: '&#128451;', label: 'Dossier Update',      bg: 'rgba(168,85,247,0.15)' },
};

/**
 * Convert structuredSteps (from progress_cb events) into PipelineTree nodes.
 * This produces a proper flowchart because the data carries real tree structure.
 */
function _structuredStepsToTree(structuredSteps, toolName, args) {
    if (!structuredSteps || !structuredSteps.length) return null;

    const root = {
        id: 'root', label: toolName ? toolLabel(toolName) : 'Execution',
        status: 'done', kind: 'root', icon: toolIcon(toolName),
        iconBg: 'rgba(168,85,247,0.15)',
        summary: args ? formatArgs(args) : '', children: [],
    };

    // Group events by analysis_type to build stage nodes
    // Flow: analyzing → (analysis_start → source_start/source_done... → analysis_done)* → scoring
    const stages = {};
    const stageOrder = [];
    let currentStage = null;

    structuredSteps.forEach(ev => {
        if (ev.event === 'analyzing') {
            // Root-level info — which analyses are planned
            root.summary = `${(ev.analyses || []).length} analyses for ${ev.company || ''}`;
        } else if (ev.event === 'analysis_start') {
            const at = ev.analysis_type || 'unknown';
            const meta = _agentMeta[at] || { icon: '&#9654;', label: ev.label || at, bg: 'rgba(255,255,255,0.06)' };
            currentStage = {
                id: at, label: meta.label, status: 'running', kind: 'stage',
                icon: meta.icon, iconBg: meta.bg,
                summary: '', children: [], _sources: [],
            };
            stages[at] = currentStage;
            stageOrder.push(at);
        } else if (ev.event === 'analysis_done') {
            const at = ev.analysis_type || currentStage?.id;
            if (at && stages[at]) {
                stages[at].status = ev.error ? 'error' : (ev.reused ? 'cached' : 'done');
                if (ev.reused) stages[at].summary = 'Cached (< 7 days old)';
                else if (ev.error) stages[at].summary = ev.error;
                else if (ev.report_path) stages[at].summary = 'Report saved';
                // else: leave summary from source_done events
            }
        } else if (ev.event === 'source_start') {
            // Create implicit stage if source events arrive without analysis_start
            // (financial, sentiment, techstack emit source events directly)
            if (!currentStage) {
                const implicitKey = (toolName || '').replace('_analysis', '').replace('_audit', '');
                const meta = _agentMeta[implicitKey] || { icon: '&#9654;', label: toolLabel(toolName) || 'Analysis', bg: 'rgba(255,255,255,0.06)' };
                currentStage = {
                    id: implicitKey || '_implicit', label: meta.label, status: 'running', kind: 'stage',
                    icon: meta.icon, iconBg: meta.bg,
                    summary: '', children: [], _sources: [],
                };
                stages[currentStage.id] = currentStage;
                stageOrder.push(currentStage.id);
            }
            // Track that a source is being queried
            currentStage._sources.push({
                source: ev.source, label: ev.label || ev.source,
                status: 'running', summary: ev.detail || '', detail: ev.detail || '',
            });
        } else if (ev.event === 'source_done') {
            // Create implicit stage if needed (same as source_start)
            if (!currentStage) {
                const implicitKey = (toolName || '').replace('_analysis', '').replace('_audit', '');
                const meta = _agentMeta[implicitKey] || { icon: '&#9654;', label: toolLabel(toolName) || 'Analysis', bg: 'rgba(255,255,255,0.06)' };
                currentStage = {
                    id: implicitKey || '_implicit', label: meta.label, status: 'running', kind: 'stage',
                    icon: meta.icon, iconBg: meta.bg,
                    summary: '', children: [], _sources: [],
                };
                stages[currentStage.id] = currentStage;
                stageOrder.push(currentStage.id);
            }
            // Update the source with result — preserve detail from source_start
            const src = currentStage._sources.find(s => s.source === ev.source);
            if (src) {
                src.status = ev.status || 'done';
                src.summary = ev.summary || '';
                if (ev.detail) src.detail = ev.detail;
            } else {
                currentStage._sources.push({
                    source: ev.source, label: ev.label || ev.source,
                    status: ev.status || 'done', summary: ev.summary || '',
                    detail: ev.detail || '',
                });
            }
        } else if (ev.event === 'generating') {
            if (currentStage) {
                currentStage._sources.push({
                    source: 'llm', label: 'LLM Synthesis',
                    status: 'done', summary: ev.detail || 'Generating report',
                });
            }
        } else if (ev.event === 'report_saved') {
            if (currentStage) {
                currentStage._sources.push({
                    source: 'report', label: 'Report Saved',
                    status: 'done', summary: ev.path || 'Saved',
                });
            }
        } else if (ev.event === 'scoring') {
            const scoringNode = {
                id: 'scoring', label: 'Lens Scoring', status: 'done', kind: 'stage',
                icon: '&#127919;', iconBg: 'rgba(168,85,247,0.15)',
                summary: `${ev.lens || 'Lens'} evaluation`, children: [],
            };
            stages['scoring'] = scoringNode;
            stageOrder.push('scoring');
        }
    });

    // Convert source arrays into children nodes, collect phases as top-level cards
    const topLevel = [];
    stageOrder.forEach(at => {
        const stage = stages[at];
        if (stage._sources) {
            stage.children = stage._sources.map((src, i) => ({
                id: `${at}.${src.source || i}`, label: src.label,
                status: src.status, kind: 'operation',
                summary: src.summary, detail: src.detail || '', children: [],
            }));
            delete stage._sources;
        }
        // Implicit stages (no analysis_done) — infer status from children
        if (stage.status === 'running' && stage.children && stage.children.length > 0) {
            const hasError = stage.children.some(c => c.status === 'error');
            stage.status = hasError ? 'error' : 'done';
        }
        topLevel.push(stage);
    });

    // Return phases as top-level nodes — each becomes a full card with source fan-out.
    // The overlay header already shows the tool name + args, so no root wrapper needed.
    return topLevel.length > 0 ? topLevel : null;
}

/**
 * Parse flat tool_progress step strings into a PipelineTree structure (bridge/fallback).
 * Groups steps by [agent_prefix] into stage branches with operations as children.
 */
function _buildToolStepsTree(steps, toolName) {
    if (!steps || !steps.length) return '';

    // Parse each step to identify its agent prefix
    const parsed = steps.map(s => {
        const match = s.match(/^\[(\w+)\]\s*(.+)$/);
        if (match) return { agent: match[1].toLowerCase(), text: match[2].trim(), raw: s };
        // Direct progress strings (no prefix) — group under tool name
        return { agent: '_direct', text: s, raw: s };
    });

    // Group by agent
    const groups = {};
    const groupOrder = [];
    parsed.forEach(p => {
        if (!groups[p.agent]) {
            groups[p.agent] = [];
            groupOrder.push(p.agent);
        }
        groups[p.agent].push(p);
    });

    // Build tree nodes
    const rootChildren = [];
    groupOrder.forEach(agent => {
        const items = groups[agent];
        const meta = _agentMeta[agent] || { icon: '&#9654;', label: agent, bg: 'rgba(255,255,255,0.06)' };

        if (agent === '_direct') {
            // Direct progress — render as flat operations under root
            items.forEach((item, i) => {
                rootChildren.push({
                    id: `direct.${i}`, label: item.text, status: 'done', kind: 'operation', children: [],
                });
            });
            return;
        }

        // Classify steps within each agent
        const stageNode = {
            id: agent, label: meta.label, status: 'done', kind: 'stage',
            icon: meta.icon, iconBg: meta.bg,
            summary: `${items.length} steps`,
            children: [],
        };

        items.forEach((item, i) => {
            // Detect key patterns for richer display
            const text = item.text;
            let childLabel = text;
            let childSummary = '';
            let childStatus = 'done';

            // Extract results/counts from common patterns
            const resultMatch = text.match(/returned (\d+) results?/i);
            const savedMatch = text.match(/Report saved to (.+)/i);
            const notFoundMatch = text.match(/not found|no .* results|could not/i);
            const reusedMatch = text.match(/reusing cached/i);
            const fetchingMatch = text.match(/^(Fetching|Searching|Scraping|Generating)/i);

            if (resultMatch) childSummary = `${resultMatch[1]} results`;
            else if (savedMatch) { childLabel = 'Report saved'; childSummary = savedMatch[1]; }
            else if (notFoundMatch) childStatus = 'skipped';
            else if (reusedMatch) childStatus = 'cached';

            stageNode.children.push({
                id: `${agent}.${i}`, label: childLabel, status: childStatus,
                kind: savedMatch ? 'result' : 'operation',
                summary: childSummary, children: [],
            });
        });

        // Update stage summary with more context
        const resultSteps = items.filter(s => s.text.match(/returned \d+ results?/i));
        const savedSteps = items.filter(s => s.text.match(/Report saved/i));
        const cachedSteps = items.filter(s => s.text.match(/reusing cached/i));
        if (cachedSteps.length) stageNode.status = 'cached';
        if (savedSteps.length) stageNode.summary = 'Report saved';
        else if (resultSteps.length) {
            const total = resultSteps.reduce((s, item) => {
                const m = item.text.match(/returned (\d+) results?/i);
                return s + (m ? parseInt(m[1]) : 0);
            }, 0);
            stageNode.summary = `${total} results across ${resultSteps.length} sources`;
        }

        rootChildren.push(stageNode);
    });

    // Render using the shared PipelineTree renderer
    const tmp = document.createElement('div');
    renderPipelineTree(rootChildren, tmp);
    return tmp.innerHTML;
}
