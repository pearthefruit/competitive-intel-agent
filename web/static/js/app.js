// ===================== MARKED CONFIG =====================
// Make external links open in new tab; keep internal report links in-app
// Superscript citation links (¹²³...) get styled like Perplexity
const renderer = new marked.Renderer();
const SUPERSCRIPT_RE = /^[¹²³⁴⁵⁶⁷⁸⁹⁰]+$/;
renderer.link = function({ href, title, tokens }) {
    try {
        const h = href || '';
        const text = this.parser.parseInline(tokens);
        // Internal report links handled by click interception
        if (h.match(/reports[\\\/].+\.md$/)) {
            const titleAttr = title ? ` title="${title}"` : '';
            return `<a href="${h}"${titleAttr}>${text}</a>`;
        }
        const titleAttr = title ? ` title="${title}"` : '';
        // Superscript citation links → styled badge that opens in new tab
        const plainText = text.replace(/<[^>]+>/g, '').trim();
        if (SUPERSCRIPT_RE.test(plainText)) {
            return `<a href="${h}" class="citation"${titleAttr} target="_blank" rel="noopener noreferrer">${plainText}</a>`;
        }
        // Regular external links → new tab
        return `<a href="${h}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
    } catch (e) {
        // Fallback: render a basic link so parsing never breaks
        return `<a href="${href || '#'}" target="_blank" rel="noopener noreferrer">${href || 'link'}</a>`;
    }
};
marked.setOptions({ renderer });

// ===================== TOAST =====================
function showToast(message, type = 'info', duration = 6000) {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.innerHTML = `<span>${message}</span><button class="toast-close" onclick="this.parentElement.remove()">&times;</button>`;
    container.appendChild(el);
    if (duration > 0) setTimeout(() => { if (el.parentElement) el.remove(); }, duration);
}

// ===================== UTILS =====================
function cleanProgress(text) {
    // Strip [tag] prefix from progress lines: "[financial] Analyzing..." → "Analyzing..."
    return text.replace(/^\[[\w]+\]\s*/, '').trim() || text;
}

function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function _formatBody(text) {
    // Add paragraph breaks to wall-of-text article bodies.
    // Respects existing newlines, inserts breaks every ~4 sentences.
    if (!text) return '';
    const escaped = escHtml(text);
    // Split on existing double-newlines first (already has paragraphs)
    const paras = escaped.split(/\n\s*\n/);
    if (paras.length > 2) return paras.map(p => p.replace(/\n/g, ' ').trim()).filter(Boolean).map(p => `<p style="margin:0 0 12px">${p}</p>`).join('');
    // No existing paragraphs — split by sentences
    const flat = escaped.replace(/\n/g, ' ').replace(/\s+/g, ' ').trim();
    // Split on sentence-ending punctuation followed by a space and capital letter
    const sentences = flat.split(/(?<=[.!?])\s+(?=[A-Z""])/);
    if (sentences.length <= 4) return `<p style="margin:0">${flat}</p>`;
    let html = '';
    for (let i = 0; i < sentences.length; i += 4) {
        html += `<p style="margin:0 0 12px">${sentences.slice(i, i + 4).join(' ')}</p>`;
    }
    return html;
}
function displayReportType(t) {
    if (!t) return 'report';
    // lens_workforce-management → workforce management
    if (t.startsWith('lens_')) t = t.slice(5);
    return t.replace(/[-_]/g, ' ');
}
function _fmtTok(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
}
function _utcToLocal(utcStr) {
    if (!utcStr) return '';
    try {
        const d = new Date(utcStr.endsWith('Z') ? utcStr : utcStr + 'Z');
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch { return utcStr.slice(11, 16); }
}

function formatArgs(args) {
    if (!args) return '';
    return Object.entries(args).map(([k,v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ');
}

function toolIcon(name) {
    const icons = {
        financial_analysis: '📊', hiring_analysis: '👥', competitor_analysis: '⚔️',
        sentiment_analysis: '💬', patent_analysis: '🔬', techstack_analysis: '🛠️',
        seo_analysis: '🔍', pricing_analysis: '💰', compare_companies: '⚖️',
        landscape_analysis: '🗺️', company_profile: '🏢', generate_briefing: '📋',
        web_search: '🌐', news_search: '📰', think: '🧠',
        scrape_page: '🕷️', lookup_ticker: '📈', search_sec: '🏛️',
    };
    return icons[name] || '⚙️';
}

function toolLabel(name) {
    return (name || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

/** Open fullscreen execution overlay for a completed tool call. */
function openExecOverlay(msgIdx) {
    const chat = getActiveChat();
    if (!chat) return;
    const m = chat.messages[msgIdx];
    if (!m || m.role !== 'tool_call' || !m.result) return;

    const overlay = document.getElementById('exec-overlay');
    const iconEl = document.getElementById('exec-overlay-icon');
    const titleEl = document.getElementById('exec-overlay-title');
    const subtitleEl = document.getElementById('exec-overlay-subtitle');
    const metaEl = document.getElementById('exec-overlay-meta');
    const bodyEl = document.getElementById('exec-overlay-body');

    iconEl.innerHTML = toolIcon(m.name);
    titleEl.textContent = toolLabel(m.name);
    subtitleEl.textContent = formatArgs(m.args);
    metaEl.innerHTML = `<span>&#10003; Done &mdash; ${(m.steps || []).length} steps</span>`;

    // Render the flowchart tree in the overlay body
    // Prefer structuredSteps (proper tree data) over flat string parsing
    const structuredSteps = m.structuredSteps || [];
    const steps = m.steps || [];

    if (structuredSteps.length > 0) {
        // Use structured events → proper flowchart
        const treeNodes = _structuredStepsToTree(structuredSteps, m.name, m.args);
        if (treeNodes) {
            renderPipelineTree(treeNodes, bodyEl);
        } else {
            bodyEl.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center">No structured execution data.</div>';
        }
    } else if (steps.length) {
        // Fallback: bridge parser for tools without structured events
        const isTreeTool = ['score_lens', 'score_prospect', 'full_analysis', 'financial_analysis',
                            'sentiment_analysis', 'techstack_analysis', 'competitor_analysis',
                            'patent_analysis', 'seo_audit', 'pricing_analysis'].includes(m.name);
        if (isTreeTool) {
            bodyEl.innerHTML = _buildToolStepsTree(steps, m.name);
        } else {
            bodyEl.innerHTML = `<div class="tool-progress-log" style="max-height:none;padding-left:0">${steps.map(s => `<div class="tool-progress-step"><span class="tool-step-check">&#10003;</span> ${escHtml(cleanProgress(s))}</div>`).join('')}</div>`;
        }
    } else {
        bodyEl.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center">No execution steps recorded.</div>';
    }

    overlay.classList.add('visible');
    document.body.style.overflow = 'hidden';
}

function closeExecOverlay() {
    const overlay = document.getElementById('exec-overlay');
    overlay.classList.remove('visible');
    document.body.style.overflow = '';
}

// Close overlay on Escape
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeExecOverlay();
});

function formatDate(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return 'Today';
    const y = new Date(now); y.setDate(now.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return 'Yesterday';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

// Keyboard: Ctrl+N new chat
document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
        e.preventDefault();
        newChat();
        document.getElementById('chat-input').focus();
    }
});

// ── Native UI helpers (R8: no browser dialogs) ──

/** Toast notification — replaces alert(). Auto-dismisses after duration. */
function _showToast(message, type, duration) {
    type = type || 'info';
    duration = duration || 4000;
    const colors = { error: '#ef4444', success: '#22c55e', info: 'var(--accent)', warn: '#eab308' };
    const icons = { error: '✕', success: '✓', info: 'ℹ', warn: '⚠' };
    const toast = document.createElement('div');
    toast.style.cssText = `position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:9999;padding:10px 20px;background:var(--bg-secondary);border:1px solid ${colors[type]};border-radius:8px;color:${colors[type]};font-size:12px;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,.4);display:flex;align-items:center;gap:8px;opacity:0;transition:opacity 0.2s`;
    toast.innerHTML = `<span style="font-size:14px">${icons[type]}</span><span style="color:var(--text-primary);font-weight:400">${escHtml(message)}</span>`;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.style.opacity = '1');
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 200); }, duration);
}

/** Confirm dialog — replaces confirm(). Calls onConfirm if user clicks Yes. */
function _showConfirm(message, onConfirm, opts) {
    opts = opts || {};
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;backdrop-filter:blur(2px)';
    const box = document.createElement('div');
    box.style.cssText = 'background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px;padding:20px 24px;max-width:360px;box-shadow:0 8px 32px rgba(0,0,0,.5)';
    const dangerColor = opts.danger ? '#ef4444' : 'var(--accent)';
    box.innerHTML = `
        <div style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:12px">${escHtml(message)}</div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
            <button class="cf-cancel" style="padding:6px 14px;background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;cursor:pointer">${opts.cancelText || 'Cancel'}</button>
            <button class="cf-ok" style="padding:6px 14px;background:${dangerColor};border:none;border-radius:6px;color:#fff;font-size:11px;font-weight:600;cursor:pointer">${opts.confirmText || 'Confirm'}</button>
        </div>`;
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    const dismiss = () => overlay.remove();
    box.querySelector('.cf-cancel').onclick = dismiss;
    box.querySelector('.cf-ok').onclick = () => { dismiss(); onConfirm(); };
    overlay.addEventListener('click', e => { if (e.target === overlay) dismiss(); });
    document.addEventListener('keydown', function _esc(e) {
        if (e.key === 'Escape') { dismiss(); document.removeEventListener('keydown', _esc); }
    });
}

// Inline input popup — replaces browser prompt()
function _showInlineInput(x, y, placeholder, defaultVal, onSubmit) {
    const existing = document.getElementById('board-inline-input');
    if (existing) existing.remove();
    const div = document.createElement('div');
    div.id = 'board-inline-input';
    // Keep within viewport
    const vw = window.innerWidth, vh = window.innerHeight;
    const left = Math.min(x, vw - 280), top = Math.min(y, vh - 50);
    div.style.cssText = `position:fixed;left:${left}px;top:${top}px;z-index:200;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:8px;box-shadow:0 4px 16px rgba(0,0,0,.5);display:flex;gap:4px;align-items:center`;
    div.innerHTML = `<input type="text" value="${escHtml(defaultVal || '')}" placeholder="${escHtml(placeholder)}" style="padding:6px 10px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);font-size:12px;width:180px;outline:none" autofocus>
        <button class="iip-ok" style="padding:6px 10px;background:var(--accent);border:none;border-radius:6px;color:#fff;font-size:11px;font-weight:600;cursor:pointer">OK</button>
        <button class="iip-cancel" style="padding:6px 6px;background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;cursor:pointer">✕</button>`;
    document.body.appendChild(div);
    const input = div.querySelector('input');
    const dismiss = () => div.remove();
    const submit = () => { const v = input.value; dismiss(); onSubmit(v); };
    div.querySelector('.iip-ok').onclick = submit;
    div.querySelector('.iip-cancel').onclick = dismiss;
    input.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') dismiss(); });
    // Click outside to dismiss
    setTimeout(() => document.addEventListener('mousedown', function _outside(e) {
        if (!div.contains(e.target)) { dismiss(); document.removeEventListener('mousedown', _outside); }
    }), 0);
    requestAnimationFrame(() => { input.focus(); input.select(); });
}

