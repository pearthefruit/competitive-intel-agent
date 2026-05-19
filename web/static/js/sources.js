// sources.js — RAG Source UI (Phase 1c)
// Handles: right-pane Sources tab, source viewer, source mode chat banner,
//          and intercepting [Source: url](source:{id}) sentinel links in chat.

// ── State ────────────────────────────────────────────────────────────────────
let _sourceModeActive = false;
let _sourceModeCompany = null;
let _currentSourceId = null;
let _currentSections = [];
let _currentHighlightText = null;


// ── Right pane tab switching ─────────────────────────────────────────────────

function switchRightPaneTab(tab) {
    // 'report' | 'sources'
    document.getElementById('rp-tab-report').classList.toggle('active', tab === 'report');
    document.getElementById('rp-tab-sources').classList.toggle('active', tab === 'sources');
    // Show/hide panels
    document.getElementById('right-content').style.display = tab === 'report' ? '' : 'none';
    document.getElementById('sources-panel').style.display = tab === 'sources' ? '' : 'none';
    document.getElementById('source-viewer-panel').style.display = 'none';
    // Load sources if switching to sources tab
    if (tab === 'sources' && window._activeDossierData) {
        _loadSourcesForCompany(window._activeDossierData.company_name);
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
        if (!sources.length) {
            container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px">No sources captured yet. Run a financial analysis first.</div>';
            if (chatBtn) chatBtn.style.display = 'none';
            return;
        }
        // Group by source_type
        const groups = {};
        for (const s of sources) {
            const g = s.source_type || 'other';
            if (!groups[g]) groups[g] = [];
            groups[g].push(s);
        }
        const TYPE_LABELS = {
            sec_10k: '10-K Annual Report', sec_8k: '8-K Material Events',
            news_article: 'News Articles', propublica: 'ProPublica 990',
            reddit_post: 'Reddit', blind_post: 'Blind',
        };
        let html = '';
        for (const [type, items] of Object.entries(groups)) {
            html += `<div class="source-group-label">${TYPE_LABELS[type] || type.replace(/_/g,' ')}</div>`;
            for (const s of items) {
                const date = s.source_date ? s.source_date.slice(0,10) : '';
                html += `<div class="source-card" onclick="openSourceViewer(${s.id})">
                    <div class="source-card-title">${_escHtml(s.title || 'Untitled')}</div>
                    <div class="source-card-meta">
                        <span class="source-type-badge">${type.replace(/_/g,' ')}</span>
                        ${date ? `<span>${date}</span>` : ''}
                    </div>
                </div>`;
            }
        }
        container.innerHTML = html;
        if (chatBtn) chatBtn.style.display = '';
    } catch (e) {
        container.innerHTML = `<div style="color:var(--text-muted);font-size:12px;padding:8px">Error loading sources: ${e.message}</div>`;
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

        if (_currentSections.length > 0) {
            // 10-K with sections — render section tabs
            sectionTabs.innerHTML = _currentSections.map((s, i) =>
                `<button class="source-section-tab ${i===0?'active':''}"
                         onclick="_showSection(${i})"
                         data-section-idx="${i}">${_escHtml(s.section_label)}</button>`
            ).join('');
            _renderSectionContent(0);
        } else {
            // Short source — render flat content
            const content = doc.content || '(no content)';
            body.innerHTML = `<pre style="white-space:pre-wrap;font-family:inherit">${_escHtml(content)}</pre>`;
            if (highlightText) _highlightInBody(body, highlightText);
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
    if (!window._activeDossierData) return;
    _sourceModeActive = true;
    _sourceModeCompany = window._activeDossierData.company_name;

    const banner = document.getElementById('source-mode-banner');
    if (banner) {
        banner.style.display = 'flex';
        const label = document.getElementById('source-mode-label');
        if (label) label.textContent = `Source Mode — ${_sourceModeCompany}`;
    }
    const input = document.getElementById('chat-input') || document.querySelector('#chat-input,textarea[placeholder]');
    if (input) input.placeholder = `Ask about ${_sourceModeCompany}'s captured sources…`;

    // Switch right pane back to sources tab so user can see what we're searching
    switchRightPaneTab('sources');
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
    // Replace [Source: url](source:123) sentinel pattern with clickable button
    // The pattern comes from the chat tool handler in agents/chat.py
    if (!msgEl) return;
    const anchors = msgEl.querySelectorAll('a[href^="source:"]');
    anchors.forEach(a => {
        const href = a.getAttribute('href') || '';
        const sourceId = href.replace('source:', '').trim();
        const chunkText = a.textContent || '';
        if (!sourceId) return;
        const btn = document.createElement('button');
        btn.className = 'source-link-btn';
        btn.style.cssText = 'background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.3);border-radius:4px;color:#a5b4fc;cursor:pointer;font-size:11px;padding:2px 8px;margin-left:4px';
        btn.textContent = '↗ View Source';
        btn.onclick = () => openSourceViewer(parseInt(sourceId), chunkText);
        a.replaceWith(btn);
    });
}


// ── Helpers ───────────────────────────────────────────────────────────────────

function _escHtml(str) {
    return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
