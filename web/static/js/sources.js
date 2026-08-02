// sources.js — RAG Source UI (Phase 1c)
// Handles: right-pane Sources tab, source viewer, source mode chat banner,
//          and intercepting [Source: url](source:{id}) sentinel links in chat.

// ── State ────────────────────────────────────────────────────────────────────
let _sourceModeActive = false;
let _sourceModeCompany = null;
let _currentSourceId = null;
let _currentSections = [];
let _currentHighlightText = null;

// Documents to pin above the normal type-grouped list, newest signal wins.
// Set either by a chat turn (the ids search_sources actually returned) or by
// the search box. `var` not `let` — cross-module access, see the base.html rule.
var _relevantSourceIds = [];
var _relevantReason = '';       // shown under the heading: the query that produced it
var _lastSourcesCompany = null; // so the search box knows what it is searching
var _sourcesCache = [];         // last loaded list, reused when re-ranking


// ── Right pane tab switching ─────────────────────────────────────────────────

function switchRightPaneTab(tab) {
    // 'report' | 'sources'
    document.getElementById('rp-tab-report').classList.toggle('active', tab === 'report');
    document.getElementById('rp-tab-sources').classList.toggle('active', tab === 'sources');
    // Show/hide panels
    document.getElementById('right-content').style.display = tab === 'report' ? '' : 'none';
    document.getElementById('sources-panel').style.display = tab === 'sources' ? 'flex' : 'none';
    document.getElementById('source-viewer-panel').style.display = 'none';
    // Load sources if switching to sources tab
    if (tab === 'sources' && _activeDossierData) {
        _loadSourcesForCompany(_activeDossierData.company_name);
    }
}

function showSourcesList() {
    // From source viewer, go back to sources list
    document.getElementById('sources-panel').style.display = '';
    document.getElementById('source-viewer-panel').style.display = 'none';
    document.getElementById('rp-tab-sources').classList.add('active');
    document.getElementById('rp-tab-report').classList.remove('active');
}

// Called by showBriefing and showLegacyDossierDetail after they set _activeDossierData
function onDossierSelected(company) {
    const tabs = document.getElementById('right-pane-tabs');
    if (tabs) {
        tabs.style.display = 'flex';
        // Reset to report tab
        switchRightPaneTab('report');
    }
}

// Called when right pane closes
function onRightPaneClosed() {
    const tabs = document.getElementById('right-pane-tabs');
    if (tabs) tabs.style.display = 'none';
    document.getElementById('sources-panel').style.display = 'none';
    document.getElementById('source-viewer-panel').style.display = 'none';
}


// ── Sources list ─────────────────────────────────────────────────────────────

async function _loadSourcesForCompany(company) {
    const container = document.getElementById('sources-list-content');
    const chatBtn = document.getElementById('chat-with-sources-btn');
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px">Loading sources…</div>';
    try {
        const resp = await fetch(`/api/companies/${encodeURIComponent(company)}/sources`);
        if (!resp.ok) {
            container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px">No sources captured yet. Run a financial analysis first.</div>';
            if (chatBtn) chatBtn.style.display = 'none';
            return;
        }
        const data = await resp.json();
        const sources = data.sources || [];
        _lastSourcesCompany = company;
        _sourcesCache = sources;
        if (!sources.length) {
            container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px">No sources captured yet. Run a financial analysis first.</div>';
            if (chatBtn) chatBtn.style.display = 'none';
            return;
        }
        // Pinned "Relevant Sources" block. Rendered from the same source
        // objects as the rest of the list so a document never appears with
        // different metadata depending on where you look at it.
        const relevant = [];
        if (_relevantSourceIds && _relevantSourceIds.length) {
            const byId = new Map(sources.map(s => [String(s.id), s]));
            for (const id of _relevantSourceIds) {
                const hit = byId.get(String(id));
                if (hit) relevant.push(hit);
            }
        }
        const relevantIdSet = new Set(relevant.map(s => String(s.id)));

        // Group by source_type — excluding anything already pinned above, so
        // the same card is never shown twice.
        const groups = {};
        for (const s of sources) {
            if (relevantIdSet.has(String(s.id))) continue;
            const g = s.source_type || 'other';
            if (!groups[g]) groups[g] = [];
            groups[g].push(s);
        }
        const TYPE_LABELS = {
            sec_10k: '10-K Annual Report', sec_8k: '8-K Material Events',
            news_article: 'News Articles', propublica: 'ProPublica 990',
            reddit_post: 'Reddit', blind_post: 'Blind',
            hiring_data: 'Job Postings',
            analysis_report: 'Our Analysis (synthesis — not a source)',
        };
        // Source types that are our own LLM output rather than primary evidence.
        // Kept visually distinct and sorted last so the pane never presents a
        // report we wrote as if it were something we found.
        const SYNTHESIS_TYPES = new Set(['analysis_report']);
        let html = '';
        if (relevant.length) {
            html += `<div class="source-group-label relevant-label">
                        ★ Relevant Sources
                        <span class="relevant-clear" onclick="clearRelevantSources()">clear</span>
                     </div>`;
            if (_relevantReason) {
                html += `<div class="relevant-reason">${_escHtml(_relevantReason)}</div>`;
            }
            for (const s of relevant) {
                const date = s.source_date ? s.source_date.slice(0, 10) : '';
                const isSynth = s.source_type === 'analysis_report';
                html += `<div class="source-card relevant" onclick="openSourceViewer(${s.id})">
                    <div class="source-card-title">${_escHtml(s.title || 'Untitled')}</div>
                    <div class="source-card-meta">
                        <span class="source-type-badge${isSynth ? ' synthesis' : ''}">${isSynth ? 'synthesis' : (s.source_type || '').replace(/_/g,' ')}</span>
                        ${s._match_kind === 'literal' ? `<span class="match-badge">${s._hits} exact</span>` : ''}
                        ${date ? `<span>${date}</span>` : ''}
                    </div>
                </div>`;
            }
            html += '<div class="relevant-divider"></div>';
        }
        const orderedTypes = Object.keys(groups).sort((a, b) =>
            (SYNTHESIS_TYPES.has(a) ? 1 : 0) - (SYNTHESIS_TYPES.has(b) ? 1 : 0));
        for (const type of orderedTypes) {
            const items = groups[type];
            const isSynth = SYNTHESIS_TYPES.has(type);
            html += `<div class="source-group-label">${TYPE_LABELS[type] || type.replace(/_/g,' ')}</div>`;
            for (const s of items) {
                const date = s.source_date ? s.source_date.slice(0,10) : '';
                html += `<div class="source-card" onclick="openSourceViewer(${s.id})">
                    <div class="source-card-title">${_escHtml(s.title || 'Untitled')}</div>
                    <div class="source-card-meta">
                        <span class="source-type-badge${isSynth ? ' synthesis' : ''}">${isSynth ? 'synthesis' : type.replace(/_/g,' ')}</span>
                        ${date ? `<span>${date}</span>` : ''}
                    </div>
                </div>`;
            }
        }
        container.innerHTML = html;
        if (chatBtn) {
            chatBtn.style.display = '';
            chatBtn.dataset.company = company;
        }
    } catch (e) {
        container.innerHTML = `<div style="color:var(--text-muted);font-size:12px;padding:8px">Error loading sources: ${e.message}</div>`;
    }
}


// ── Relevant-source surfacing ────────────────────────────────────────────────

/** Pin a set of source ids to the top of the pane. Called by the chat stream
 *  with the ids search_sources actually returned for an answer. */
function setRelevantSources(ids, reason) {
    _relevantSourceIds = (ids || []).map(String);
    _relevantReason = reason || '';
    // Only re-render if the pane is actually showing; otherwise the pinned set
    // is picked up next time the list loads.
    const panel = document.getElementById('sources-panel');
    if (panel && panel.style.display !== 'none' && _lastSourcesCompany) {
        _loadSourcesForCompany(_lastSourcesCompany);
    }
}

function clearRelevantSources() {
    _relevantSourceIds = [];
    _relevantReason = '';
    const input = document.getElementById('sources-search-input');
    if (input) input.value = '';
    if (_lastSourcesCompany) _loadSourcesForCompany(_lastSourcesCompany);
}

let _sourceSearchTimer = null;

/** Ctrl-F over the captured sources. Debounced; no LLM on either path. */
function onSourcesSearchInput(value) {
    clearTimeout(_sourceSearchTimer);
    const q = (value || '').trim();
    if (!q) { clearRelevantSources(); return; }
    _sourceSearchTimer = setTimeout(() => _runSourcesSearch(q), 220);
}

async function _runSourcesSearch(q) {
    if (!_lastSourcesCompany) return;
    const status = document.getElementById('sources-search-status');
    if (status) status.textContent = 'searching…';
    try {
        const resp = await fetch(
            `/api/companies/${encodeURIComponent(_lastSourcesCompany)}/sources/search?q=${encodeURIComponent(q)}`);
        if (!resp.ok) { if (status) status.textContent = ''; return; }
        const data = await resp.json();
        const results = data.results || [];

        // Carry match metadata onto the cached source objects so the pinned
        // cards can show hit counts without a second lookup.
        const meta = new Map(results.map(r => [String(r.id), r]));
        for (const s of _sourcesCache) {
            const m = meta.get(String(s.id));
            s._match_kind = m ? m.match_kind : null;
            s._hits = m ? m.hits : 0;
        }

        const nLiteral = results.filter(r => r.match_kind === 'literal').length;
        setRelevantSources(results.map(r => r.id),
            results.length
                ? `"${q}" — ${nLiteral} exact match${nLiteral === 1 ? '' : 'es'}, ${results.length - nLiteral} related`
                : `"${q}" — no matches`);
        if (status) status.textContent = results.length ? '' : 'no matches';
    } catch (e) {
        if (status) status.textContent = '';
    }
}


// ── Source viewer ─────────────────────────────────────────────────────────────

async function openSourceViewer(sourceId, highlightText) {
    _currentSourceId = sourceId;
    _currentHighlightText = highlightText || null;

    document.getElementById('sources-panel').style.display = 'none';
    document.getElementById('source-viewer-panel').style.display = 'flex';
    document.getElementById('right-content').style.display = 'none';

    const body = document.getElementById('source-viewer-body');
    const sectionTabs = document.getElementById('source-viewer-section-tabs');
    body.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px">Loading…</div>';
    sectionTabs.innerHTML = '';

    try {
        const resp = await fetch(`/api/sources/${sourceId}`);
        if (!resp.ok) { body.innerHTML = '<div style="color:var(--text-muted)">Source not found.</div>'; return; }
        const doc = await resp.json();
        _currentSections = doc.sections || [];

        // Wire up the "Open" external link
        const urlLink = document.getElementById('source-viewer-url');
        if (urlLink) {
            if (doc.url) {
                urlLink.href = doc.url;
                urlLink.style.display = '';
            } else {
                urlLink.style.display = 'none';
            }
        }

        if (_currentSections.length > 0) {
            // 10-K with sections — render section tabs
            sectionTabs.innerHTML = _currentSections.map((s, i) =>
                `<button class="source-section-tab ${i===0?'active':''}"
                         onclick="_showSection(${i})"
                         data-section-idx="${i}">${_escHtml(s.section_label)}</button>`
            ).join('');
            _renderSectionContent(0);
        } else {
            const content = doc.content || '';
            if (content.length < 300 && doc.url) {
                // Short content (scraped metadata only) — show structured card
                const meta = doc.metadata || {};
                const dateStr = doc.source_date ? doc.source_date.slice(0, 10) : '';
                body.innerHTML = `
                    <div style="display:flex;flex-direction:column;gap:12px;padding:4px 0">
                        <div style="font-size:14px;font-weight:600;color:var(--text-primary);line-height:1.5">${_escHtml(doc.title || 'Untitled')}</div>
                        ${dateStr ? `<div style="font-size:11px;color:var(--text-muted)">${dateStr}</div>` : ''}
                        ${content ? `<div style="font-size:13px;color:var(--text-secondary);line-height:1.6;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:10px 12px">${_escHtml(content)}</div>` : ''}
                        <a href="${_escHtml(doc.url)}" target="_blank"
                           style="display:inline-flex;align-items:center;gap:6px;color:#a5b4fc;font-size:12px;text-decoration:none;background:rgba(99,102,241,0.12);border:1px solid rgba(99,102,241,0.25);border-radius:6px;padding:7px 12px;width:fit-content">
                            ↗ View full post on ${_escHtml(doc.source_type || 'source')}
                        </a>
                        <div style="font-size:11px;color:var(--text-muted);line-height:1.5">Full content may require login on the source site.</div>
                    </div>`;
            } else {
                body.innerHTML = `<div style="white-space:pre-wrap;line-height:1.7">${_escHtml(content || '(no content)')}</div>`;
                if (highlightText) _highlightInBody(body, highlightText);
            }
        }

        // Open the right pane if not open
        if (typeof openRightPane === 'function') openRightPane();
    } catch(e) {
        body.innerHTML = `<div style="color:var(--text-muted)">Error: ${e.message}</div>`;
    }
}

function _showSection(idx) {
    document.querySelectorAll('.source-section-tab').forEach((t, i) => {
        t.classList.toggle('active', i === idx);
    });
    _renderSectionContent(idx);
}

function _renderSectionContent(idx) {
    const body = document.getElementById('source-viewer-body');
    const section = _currentSections[idx];
    if (!section) return;
    const text = section.content || '(empty section)';
    body.innerHTML = `<div style="margin-bottom:8px;font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em">${_escHtml(section.section_label)}</div><pre style="white-space:pre-wrap;font-family:inherit">${_escHtml(text)}</pre>`;
    if (_currentHighlightText) _highlightInBody(body, _currentHighlightText);
}

function _highlightInBody(container, text) {
    if (!text || text.length < 10) return;
    const snippet = text.slice(0, 100);
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        const idx = node.textContent.indexOf(snippet);
        if (idx !== -1) {
            const span = document.createElement('mark');
            span.className = 'source-highlight';
            const range = document.createRange();
            range.setStart(node, idx);
            range.setEnd(node, Math.min(idx + snippet.length, node.textContent.length));
            range.surroundContents(span);
            span.scrollIntoView({behavior:'smooth', block:'center'});
            break;
        }
    }
}


// ── Source Mode chat ─────────────────────────────────────────────────────────

function enterSourceMode() {
    const btn = document.getElementById('chat-with-sources-btn');
    const company = (btn && btn.dataset.company)
        || (_activeDossierData && _activeDossierData.company_name);
    if (!company) return;
    _sourceModeActive  = true;
    _sourceModeCompany = company;
    if (typeof openSourceOverlay === 'function') {
        openSourceOverlay(company);
    }
}

function exitSourceMode() {
    _sourceModeActive = false;
    _sourceModeCompany = null;

    const banner = document.getElementById('source-mode-banner');
    if (banner) banner.style.display = 'none';

    const input = document.getElementById('chat-input') || document.querySelector('#chat-input,textarea[placeholder]');
    if (input) input.placeholder = 'Ask about a company…';
}

function isSourceModeActive() { return _sourceModeActive; }
function getSourceModeCompany() { return _sourceModeCompany; }


// ── Source link interception ─────────────────────────────────────────────────

function interceptSourceLinks(msgEl) {
    if (!msgEl) return;
    const anchors = msgEl.querySelectorAll('a[href^="source:"]');
    let firstCitation = null;
    anchors.forEach(a => {
        const href = a.getAttribute('href') || '';
        const sourceId = href.replace('source:', '').trim();
        // Strip the surrounding quotes we embed as the chunk hint
        const chunkText = a.textContent.replace(/^[""]|[""]…?$/g, '').trim();
        if (!sourceId) return;
        if (!firstCitation) firstCitation = { id: parseInt(sourceId), text: chunkText };
        const btn = document.createElement('button');
        btn.className = 'source-link-btn';
        // Superscript-style citations ([¹](source:ID)) render as compact chips;
        // chunk-hint links keep the full "View Source" button.
        const linkText = (a.textContent || '').trim();
        if (/^[¹²³⁴⁵⁶⁷⁸⁹⁰\d]{1,4}$/.test(linkText)) {
            btn.style.cssText = 'background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.3);border-radius:4px;color:#a5b4fc;cursor:pointer;font-size:10px;padding:0 4px;margin:0 1px;vertical-align:super;line-height:1.4';
            btn.textContent = linkText;
            btn.title = 'View stored source';
        } else {
            btn.style.cssText = 'background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.3);border-radius:4px;color:#a5b4fc;cursor:pointer;font-size:11px;padding:2px 8px;margin-left:4px';
            btn.textContent = '↗ View Source';
        }
        btn.onclick = () => openSourceViewer(parseInt(sourceId), chunkText);
        a.replaceWith(btn);
    });
    // In Source Mode: auto-open the first cited source with the chunk highlighted
    if (firstCitation && _sourceModeActive) {
        openSourceViewer(firstCitation.id, firstCitation.text);
    }
}


// ── Helpers ───────────────────────────────────────────────────────────────────

function _escHtml(str) {
    return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
