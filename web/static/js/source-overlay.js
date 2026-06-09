// source-overlay.js — 3-pane source interrogation overlay
// Left: report  |  Middle: chat  |  Right: source viewer
// Ephemeral chat history (in-memory only). Threads persist via /api/signals/threads/create.

// ── State ────────────────────────────────────────────────────────────────────

let _sovCompany       = null;
let _sovMessages      = [];   // in-memory chat history [{role, content}]
let _sovSending       = false;
let _sovSections      = [];   // sections of currently viewed source doc
let _sovHighlightText = null;
let _sovResizing      = null; // 'l' | 'r'
let _sovPending       = null; // { text, rect, context } pending thread creation
                               // context: 'doc' | 'chat'


// ── Open / Close ─────────────────────────────────────────────────────────────

function openSourceOverlay(company) {
    _sovCompany   = company;
    _sovMessages  = [];
    _sovSending   = false;

    const el = document.getElementById('source-overlay');
    if (!el) return;

    document.getElementById('sov-title').textContent = company + ' — Source Interrogation';
    el.style.display = 'flex';

    // Restore saved pane widths
    const lw = localStorage.getItem('sov_report_w');
    const rw = localStorage.getItem('sov_sources_w');
    if (lw) document.getElementById('sov-report').style.width  = lw + 'px';
    if (rw) document.getElementById('sov-sources').style.width = rw + 'px';

    _sovLoadReport();
    _sovLoadSources();
    _sovRenderMessages();

    // Focus input
    setTimeout(() => {
        const inp = document.getElementById('sov-input');
        if (inp) inp.focus();
    }, 80);
}

function closeSourceOverlay() {
    const el = document.getElementById('source-overlay');
    if (el) el.style.display = 'none';
    _sovCloseThreadPopover();
    _sovCompany  = null;
    _sovMessages = [];
}


// ── Left pane: Report ─────────────────────────────────────────────────────────

function _sovLoadReport() {
    const container = document.getElementById('sov-report-content');
    if (!container) return;

    // Reuse the already-rendered report from the right pane
    const existing = document.getElementById('right-content');
    if (existing && existing.innerHTML.trim()) {
        container.innerHTML = existing.innerHTML;
        return;
    }
    container.innerHTML = '<p style="color:var(--text-muted);font-size:12px">No report available.</p>';
}


// ── Right pane: Sources list ──────────────────────────────────────────────────

async function _sovLoadSources() {
    const container = document.getElementById('sov-source-list');
    if (!container || !_sovCompany) return;
    container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px">Loading…</div>';

    try {
        const resp = await fetch(`/api/companies/${encodeURIComponent(_sovCompany)}/sources`);
        if (!resp.ok) { container.innerHTML = _sovNoSources(); return; }
        const data = await resp.json();
        const sources = data.sources || [];
        if (!sources.length) { container.innerHTML = _sovNoSources(); return; }

        const TYPE_LABELS = {
            sec_10k: '10-K Annual Report', sec_8k: '8-K Filing',
            news_article: 'News', analyst: 'Analyst Estimates',
            propublica: 'ProPublica 990', reddit_post: 'Reddit', blind_post: 'Blind',
        };
        const groups = {};
        for (const s of sources) {
            const g = s.source_type || 'other';
            if (!groups[g]) groups[g] = [];
            groups[g].push(s);
        }
        let html = '';
        for (const [type, items] of Object.entries(groups)) {
            const label = TYPE_LABELS[type] || type.replace(/_/g, ' ');
            html += `<div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);padding:10px 4px 4px">${label}</div>`;
            for (const s of items) {
                const date = s.source_date ? s.source_date.slice(0, 10) : '';
                html += `<div class="sov-source-card" onclick="sovOpenSourceViewer(${s.id})">
                    <div style="font-size:12px;font-weight:500;color:var(--text-primary);line-height:1.4">${_sovEsc(s.title || 'Untitled')}</div>
                    <div style="display:flex;gap:6px;margin-top:3px;align-items:center">
                        <span style="font-size:10px;background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.25);color:#a5b4fc;border-radius:4px;padding:1px 6px">${type.replace(/_/g,' ')}</span>
                        ${date ? `<span style="font-size:10px;color:var(--text-muted)">${date}</span>` : ''}
                    </div>
                </div>`;
            }
        }
        document.getElementById('sov-meta').textContent = `${sources.length} source${sources.length !== 1 ? 's' : ''}`;
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div style="color:var(--text-muted);font-size:12px;padding:8px">Error: ${e.message}</div>`;
    }
}

function _sovNoSources() {
    return '<div style="color:var(--text-muted);font-size:12px;padding:8px">No sources captured yet. Run a financial analysis first.</div>';
}

function sovShowSourceList() {
    document.getElementById('sov-source-list').style.display   = '';
    document.getElementById('sov-source-viewer').style.display = 'none';
}


// ── Right pane: Source viewer ─────────────────────────────────────────────────

async function sovOpenSourceViewer(sourceId, highlightText) {
    _sovHighlightText = highlightText || null;

    const list   = document.getElementById('sov-source-list');
    const viewer = document.getElementById('sov-source-viewer');
    const body   = document.getElementById('sov-viewer-body');
    const tabs   = document.getElementById('sov-viewer-tabs');
    const title  = document.getElementById('sov-viewer-title');

    list.style.display   = 'none';
    viewer.style.display = 'flex';
    body.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px">Loading…</div>';
    tabs.innerHTML = '';

    try {
        const resp = await fetch(`/api/sources/${sourceId}`);
        if (!resp.ok) { body.innerHTML = '<div style="color:var(--text-muted)">Source not found.</div>'; return; }
        const doc = await resp.json();
        _sovSections = doc.sections || [];
        title.textContent = doc.title || 'Source';

        // Wire up the "Open" link
        const urlLink = document.getElementById('sov-viewer-url');
        if (urlLink) {
            if (doc.url) {
                urlLink.href = doc.url;
                urlLink.style.display = '';
            } else {
                urlLink.style.display = 'none';
            }
        }

        if (_sovSections.length) {
            tabs.innerHTML = _sovSections.map((s, i) =>
                `<button class="sov-section-tab ${i === 0 ? 'active' : ''}"
                         onclick="_sovShowSection(${i})"
                         data-idx="${i}">${_sovEsc(s.section_label)}</button>`
            ).join('');
            _sovRenderSection(0);
        } else {
            const content = doc.content || '';
            if (content.length < 300 && doc.url) {
                const dateStr = doc.source_date ? doc.source_date.slice(0, 10) : '';
                body.innerHTML = `
                    <div style="display:flex;flex-direction:column;gap:12px;padding:4px 0">
                        <div style="font-size:13px;font-weight:600;color:var(--text-primary);line-height:1.5">${_sovEsc(doc.title || 'Untitled')}</div>
                        ${dateStr ? `<div style="font-size:11px;color:var(--text-muted)">${dateStr}</div>` : ''}
                        ${content ? `<div style="font-size:12px;color:var(--text-secondary);line-height:1.6;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:10px 12px">${_sovEsc(content)}</div>` : ''}
                        <a href="${_sovEsc(doc.url)}" target="_blank"
                           style="display:inline-flex;align-items:center;gap:6px;color:#a5b4fc;font-size:11px;text-decoration:none;background:rgba(99,102,241,0.12);border:1px solid rgba(99,102,241,0.25);border-radius:6px;padding:6px 10px;width:fit-content">
                            ↗ View full post on ${_sovEsc(doc.source_type || 'source')}
                        </a>
                        <div style="font-size:10px;color:var(--text-muted)">Full content may require login on the source site.</div>
                    </div>`;
            } else {
                body.innerHTML = `<div style="white-space:pre-wrap;line-height:1.7">${_sovEsc(content || '(no content)')}</div>`;
                if (_sovHighlightText) _sovApplyHighlight(body, _sovHighlightText);
                _sovInitDocSelection(body);
            }
        }
    } catch (e) {
        body.innerHTML = `<div style="color:var(--text-muted)">Error: ${e.message}</div>`;
    }
}

function _sovShowSection(idx) {
    document.querySelectorAll('.sov-section-tab').forEach((t, i) =>
        t.classList.toggle('active', i === idx));
    _sovRenderSection(idx);
}

function _sovRenderSection(idx) {
    const body = document.getElementById('sov-viewer-body');
    const sec  = _sovSections[idx];
    if (!sec) return;
    body.innerHTML = `<div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);margin-bottom:8px">${_sovEsc(sec.section_label)}</div><div style="white-space:pre-wrap">${_sovEsc(sec.content || '')}</div>`;
    if (_sovHighlightText) _sovApplyHighlight(body, _sovHighlightText);
    _sovInitDocSelection(body);
}

function _sovApplyHighlight(container, text) {
    if (!text || text.length < 8) return;
    const snippet = text.slice(0, 100);
    const walker  = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        const idx = node.textContent.indexOf(snippet);
        if (idx !== -1) {
            const mark  = document.createElement('mark');
            mark.className = 'sov-highlight';
            const range = document.createRange();
            range.setStart(node, idx);
            range.setEnd(node, Math.min(idx + snippet.length, node.textContent.length));
            range.surroundContents(mark);
            mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
            break;
        }
    }
}


// ── Middle pane: Chat ─────────────────────────────────────────────────────────

function sovHandleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sovSend(); }
}

async function sovSend() {
    const input = document.getElementById('sov-input');
    const text  = (input.value || '').trim();
    if (!text || _sovSending) return;

    _sovSending = true;
    input.value = '';
    input.style.height = '';

    _sovMessages.push({ role: 'user', content: text });
    _sovRenderMessages();
    _sovScrollBottom();

    const typingEl = _sovAppendTyping();

    const payload = {
        messages: _sovMessages.slice(-20).map(m => ({ role: m.role, content: m.content })),
        context:  { company: _sovCompany, type: 'source_mode' },
    };

    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        const reader  = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer    = '';
        let assistantText = '';
        let assistantEl   = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const evt = JSON.parse(line.slice(6));

                    if (evt.type === 'tool_call') {
                        typingEl.remove();
                        _sovAppendToolCall(evt.name);

                    } else if (evt.type === 'tool_progress') {
                        _sovUpdateToolProgress(evt.text || '');

                    } else if (evt.type === 'tool_result') {
                        _sovCloseToolCall();
                        // append a fresh typing indicator to show LLM is synthesizing
                        _sovAppendTyping();

                    } else if (evt.type === 'message') {
                        // Remove any typing/tool indicators
                        document.querySelectorAll('.sov-typing, .sov-tool-bubble').forEach(e => e.remove());
                        if (evt.text && evt.text.trim()) {
                            assistantText = evt.text;
                            _sovMessages.push({ role: 'assistant', content: assistantText });
                            assistantEl = _sovAppendMsg('assistant', assistantText);
                            sovInterceptSourceLinks(assistantEl);
                            _sovInitChatSelection(assistantEl);
                        }

                    } else if (evt.type === 'error') {
                        document.querySelectorAll('.sov-typing, .sov-tool-bubble').forEach(e => e.remove());
                        _sovAppendMsg('error', evt.text || 'Unknown error');
                    }
                } catch {}
            }
        }
    } catch (e) {
        document.querySelectorAll('.sov-typing, .sov-tool-bubble').forEach(el => el.remove());
        _sovAppendMsg('error', `Connection error: ${e.message}`);
    }

    _sovSending = false;
    _sovScrollBottom();
}

function _sovRenderMessages() {
    const container = document.getElementById('sov-messages');
    if (!container) return;
    container.innerHTML = '';
    if (_sovMessages.length === 0) {
        container.innerHTML = `<div style="color:var(--text-muted);font-size:12px;text-align:center;margin-top:40px">Ask anything about ${_sovEsc(_sovCompany || 'this company')}'s captured sources.</div>`;
        return;
    }
    for (const m of _sovMessages) {
        _sovAppendMsg(m.role, m.content);
    }
}

function _sovAppendMsg(role, content) {
    const container = document.getElementById('sov-messages');
    const el = document.createElement('div');
    el.className = `sov-msg sov-msg-${role}`;

    if (role === 'user') {
        el.style.cssText = 'align-self:flex-end;max-width:80%;background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.25);border-radius:10px 10px 2px 10px;padding:8px 12px;font-size:13px;color:var(--text-primary)';
        el.textContent = content;
    } else if (role === 'assistant') {
        el.style.cssText = 'align-self:flex-start;max-width:90%;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:2px 10px 10px 10px;padding:10px 14px;font-size:13px;color:var(--text-primary);line-height:1.6';
        el.innerHTML = marked.parse ? marked.parse(content) : content;
    } else {
        el.style.cssText = 'align-self:flex-start;max-width:90%;color:#ef4444;font-size:12px;padding:4px 0';
        el.textContent = 'Error: ' + content;
    }

    container.appendChild(el);
    _sovScrollBottom();
    return el;
}

function _sovAppendTyping() {
    const container = document.getElementById('sov-messages');
    const el = document.createElement('div');
    el.className = 'sov-typing';
    el.style.cssText = 'align-self:flex-start;color:var(--text-muted);font-size:12px;padding:6px 0;display:flex;gap:4px;align-items:center';
    el.innerHTML = '<span style="animation:sov-blink 1s infinite">●</span><span style="animation:sov-blink 1s infinite .3s">●</span><span style="animation:sov-blink 1s infinite .6s">●</span>';
    container.appendChild(el);
    _sovScrollBottom();
    return el;
}

function _sovAppendToolCall(name) {
    const container = document.getElementById('sov-messages');
    const el = document.createElement('div');
    el.className = 'sov-tool-bubble';
    el.style.cssText = 'align-self:flex-start;background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.2);border-radius:8px;padding:6px 12px;font-size:11px;color:#a5b4fc;display:flex;align-items:center;gap:8px';
    const label = name === 'search_sources' ? 'Searching captured sources' : `Calling ${name}`;
    el.innerHTML = `<span style="display:inline-block;width:10px;height:10px;border:2px solid #a5b4fc;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite"></span>${label}…<span class="sov-tool-progress" style="color:var(--text-muted);font-size:10px"></span>`;
    container.appendChild(el);
    _sovScrollBottom();
}

function _sovUpdateToolProgress(text) {
    const bubble = document.querySelector('.sov-tool-bubble');
    if (!bubble) return;
    const prog = bubble.querySelector('.sov-tool-progress');
    if (prog && text) prog.textContent = ' — ' + text.slice(0, 60);
}

function _sovCloseToolCall() {
    document.querySelectorAll('.sov-tool-bubble').forEach(e => e.remove());
}

function _sovScrollBottom() {
    const c = document.getElementById('sov-messages');
    if (c) c.scrollTop = c.scrollHeight;
}

// Intercept [chunk hint](source:ID) sentinels — auto-open source viewer on right
function sovInterceptSourceLinks(el) {
    if (!el) return;
    el.querySelectorAll('a[href^="source:"]').forEach((a, i) => {
        const sourceId  = a.getAttribute('href').replace('source:', '').trim();
        const chunkText = a.textContent.replace(/^[""]|[""]…?$/g, '').trim();
        if (!sourceId) return;

        const btn = document.createElement('button');
        btn.style.cssText = 'background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.3);border-radius:4px;color:#a5b4fc;cursor:pointer;font-size:11px;padding:2px 8px;margin:0 2px';
        btn.textContent = '↗ View Source';
        btn.onclick = () => sovOpenSourceViewer(parseInt(sourceId), chunkText);
        a.replaceWith(btn);

        // Auto-open first citation in the right pane
        if (i === 0) sovOpenSourceViewer(parseInt(sourceId), chunkText);
    });
}


// ── Resize ────────────────────────────────────────────────────────────────────

function _sovInitResize() {
    const lHandle = document.getElementById('sov-resize-l');
    const rHandle = document.getElementById('sov-resize-r');
    const report  = document.getElementById('sov-report');
    const sources = document.getElementById('sov-sources');

    function onDown(which, e) {
        e.preventDefault();
        _sovResizing = which;
        document.body.style.cursor      = 'col-resize';
        document.body.style.userSelect  = 'none';
        lHandle.classList.add('active');
        rHandle.classList.add('active');
    }

    lHandle.addEventListener('mousedown', e => onDown('l', e));
    rHandle.addEventListener('mousedown', e => onDown('r', e));

    document.addEventListener('mousemove', e => {
        if (!_sovResizing) return;
        const body = document.getElementById('sov-body');
        if (!body) return;
        const br = body.getBoundingClientRect();

        if (_sovResizing === 'l' && report) {
            const w = Math.min(600, Math.max(150, e.clientX - br.left));
            report.style.width = w + 'px';
        } else if (_sovResizing === 'r' && sources) {
            const w = Math.min(600, Math.max(150, br.right - e.clientX));
            sources.style.width = w + 'px';
        }
    });

    document.addEventListener('mouseup', () => {
        if (!_sovResizing) return;
        lHandle.classList.remove('active');
        rHandle.classList.remove('active');
        if (report)  localStorage.setItem('sov_report_w',  parseInt(report.style.width  || 0));
        if (sources) localStorage.setItem('sov_sources_w', parseInt(sources.style.width || 0));
        _sovResizing = null;
        document.body.style.cursor     = '';
        document.body.style.userSelect = '';
    });
}

document.addEventListener('DOMContentLoaded', _sovInitResize);


// ── Highlight → Thread (doc pane) ────────────────────────────────────────────

function _sovInitDocSelection(container) {
    container.removeEventListener('mouseup', _sovOnDocSelect);
    container.addEventListener('mouseup', _sovOnDocSelect);
}

function _sovOnDocSelect(e) {
    const sel  = window.getSelection();
    const text = sel ? sel.toString().trim() : '';
    if (!text || text.length < 5) { _sovCloseThreadPopover(); return; }
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    _sovPending = { text, context: 'doc' };
    _sovShowThreadPopover(text, rect);
}


// ── Highlight → Thread (chat pane) ───────────────────────────────────────────

function _sovInitChatSelection(msgEl) {
    msgEl.addEventListener('mouseup', _sovOnChatSelect);
}

function _sovOnChatSelect(e) {
    const sel  = window.getSelection();
    const text = sel ? sel.toString().trim() : '';
    if (!text || text.length < 5) return;
    // Only fire if selection is within this message bubble
    if (!e.currentTarget.contains(sel.anchorNode)) return;
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    _sovPending = { text, context: 'chat' };
    _sovShowThreadPopover(text, rect);
}


// ── Thread popover ────────────────────────────────────────────────────────────

function _sovShowThreadPopover(text, rect) {
    const pop = document.getElementById('sov-thread-popover');
    if (!pop) return;
    document.getElementById('sov-tp-quote').textContent =
        text.length > 120 ? text.slice(0, 120) + '…' : text;
    document.getElementById('sov-tp-title').value =
        text.length > 80 ? text.slice(0, 80) : text;
    document.getElementById('sov-tp-note').value = '';

    // Position below selection, constrained to viewport
    const top  = Math.min(rect.bottom + window.scrollY + 8, window.innerHeight - 240);
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - 320));
    pop.style.top     = top + 'px';
    pop.style.left    = left + 'px';
    pop.style.display = 'block';
    document.getElementById('sov-tp-title').select();
}

function _sovCloseThreadPopover() {
    const pop = document.getElementById('sov-thread-popover');
    if (pop) pop.style.display = 'none';
    _sovPending = null;
}

async function _sovSaveThread() {
    if (!_sovPending) return;
    const title = (document.getElementById('sov-tp-title').value || '').trim();
    const note  = (document.getElementById('sov-tp-note').value  || '').trim();
    if (!title) { document.getElementById('sov-tp-title').focus(); return; }

    const btn = document.getElementById('sov-tp-save');
    btn.disabled    = true;
    btn.textContent = 'Saving…';

    const origin = _sovPending.context === 'chat' ? `[Source Chat — ${_sovCompany}]` : `[Source Doc — ${_sovCompany}]`;
    let content = _sovPending.text;
    if (note) content += `\n\n**Note:** ${note}`;
    content = `${origin}\n\n${content}`;

    try {
        const resp = await fetch('/api/signals/threads/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, content }),
        });
        const data = await resp.json();
        if (data.ok) {
            _sovCloseThreadPopover();
            _sovShowToast('Thread created');
        } else {
            _sovShowToast('Failed: ' + (data.error || 'unknown'));
        }
    } catch (e) {
        _sovShowToast('Error: ' + e.message);
    } finally {
        btn.disabled    = false;
        btn.textContent = 'Create Thread';
    }
}

function _sovShowToast(msg) {
    const t = document.createElement('div');
    t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:rgba(30,30,30,.95);border:1px solid rgba(255,255,255,.12);border-radius:8px;color:#fff;font-size:12px;padding:8px 16px;z-index:1200;pointer-events:none';
    t.textContent   = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2200);
}


// ── Helpers ───────────────────────────────────────────────────────────────────

function _sovEsc(str) {
    return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
