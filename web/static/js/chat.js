// ===================== STATE =====================
const STORAGE_KEY = 'signalvault_chats';
let chats = [];
let activeChatId = null;
let sendingChats = new Set();  // track which chats are currently processing
let messageQueue = [];
let currentReportFilename = null;
let allReports = [];
let allCompanies = [];
let openCompanies = new Set();
let companySortMode = 'recent'; // 'recent' or 'alpha'

// Context pill state
let activeContext = null;       // { company, type, label }
let contextDismissed = false;
let resumePromptShown = false;

// ===================== SPLIT VIEW STATE =====================
let _splitActive = false;
let _splitFocusedSide = 'left';
let _wasExpandedBeforeSplit = false;
const _emptyPanel = () => ({ type: null, reportFilename: null, dossierName: null, briefingData: null, dossierData: null, company: null, analysisType: null, date: null });
let _splitPanels = { left: _emptyPanel(), right: _emptyPanel() };

function _isInSplitPanel(filename, dossierName) {
    if (!_splitActive) return false;
    for (const side of ['left', 'right']) {
        const p = _splitPanels[side];
        if (filename && p.reportFilename === filename) return side;
        if (dossierName && p.dossierName === dossierName) return side;
    }
    return false;
}

function setContext(company, type, label) {
    activeContext = { company: company, type: type, label: label };
    contextDismissed = false;
    resumePromptShown = false;
    renderContextPill();
}

function clearContextPill() {
    contextDismissed = true;
    renderContextPill();
}

function clearContextFull() {
    activeContext = null;
    contextDismissed = false;
    resumePromptShown = false;
    renderContextPill();
}

function renderContextPill() {
    const bar = document.getElementById('context-pill-bar');
    const text = document.getElementById('context-pill-text');
    if (!activeContext || contextDismissed) {
        bar.style.display = 'none';
        return;
    }
    text.textContent = 'Viewing: ' + activeContext.company + ' \u00b7 ' + activeContext.label;
    bar.style.display = 'block';
}

function getContextCompany() {
    return activeContext ? activeContext.company : null;
}

function findExistingCompanyChat(company) {
    if (!company) return null;
    const lc = company.toLowerCase();
    const chat = getActiveChat();
    return chats.find(c => c.id !== (chat ? chat.id : '') && (c.company || '').toLowerCase() === lc && c.messages.length > 0);
}

function showResumePrompt(company, existingChat) {
    return new Promise(resolve => {
        const bar = document.getElementById('resume-prompt');
        const text = document.getElementById('resume-prompt-text');
        text.textContent = `Continue previous ${company} conversation?`;
        bar.style.display = 'flex';

        const yesBtn = document.getElementById('resume-yes-btn');
        const newBtn = document.getElementById('resume-new-btn');

        function cleanup() {
            bar.style.display = 'none';
            yesBtn.removeEventListener('click', onYes);
            newBtn.removeEventListener('click', onNew);
        }
        function onYes() { cleanup(); resolve('resume'); }
        function onNew() { cleanup(); resolve('new'); }

        yesBtn.addEventListener('click', onYes);
        newBtn.addEventListener('click', onNew);
    });
}

function hideResumePrompt() {
    document.getElementById('resume-prompt').style.display = 'none';
}

// ===================== INIT =====================
document.addEventListener('DOMContentLoaded', () => {
    loadChats();
    renderChatList();
    loadReports();
    refreshUsageBadge();
    // Start with a fresh chat or load the most recent
    if (chats.length) {
        loadChat(chats[0].id);
    } else {
        newChat();
    }
});

// ===================== LOCAL STORAGE =====================
function loadChats() {
    try { chats = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
    catch { chats = []; }
}

function saveChats() {
    if (chats.length > 30) chats = chats.slice(0, 30);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(chats));
}

function getActiveChat() {
    return chats.find(c => c.id === activeChatId);
}

// ===================== LEFT TABS =====================
function switchLeftTab(tab) {
    document.querySelectorAll('.left-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.left-panel').forEach(p => p.classList.remove('active'));
    const idx = tab === 'chats' ? 1 : 2;
    document.querySelector(`.left-tab:nth-child(${idx})`).classList.add('active');
    document.getElementById(`panel-${tab}`).classList.add('active');
    if (tab === 'companies') loadCompanies();
}

function switchModule(mod) {
    document.querySelectorAll('.module-item').forEach(m => m.classList.remove('active'));
    document.querySelectorAll('.workspace').forEach(w => w.classList.remove('active'));
    document.querySelector(`.module-item[data-module="${mod}"]`).classList.add('active');
    document.getElementById(`workspace-${mod}`).classList.add('active');
    if (mod === 'prospecting') { loadCampaigns(); _loadLenses(); }
    if (mod === 'signals') { loadSignals(); loadSignalFreshness(); }
}

// ===================== CHAT LIST =====================
function renderChatList() {
    const filter = (document.getElementById('chat-filter').value || '').toLowerCase();
    const list = document.getElementById('chat-list');
    const filtered = chats.filter(c => !filter || (c.title || '').toLowerCase().includes(filter) || (c.company || '').toLowerCase().includes(filter));

    list.innerHTML = filtered.map(c => `
        <div class="chat-item ${c.id === activeChatId ? 'active' : ''}" onclick="loadChat('${c.id}')">
            <button class="chat-item-delete" onclick="event.stopPropagation();deleteChat('${c.id}')" title="Delete">&times;</button>
            <div class="chat-item-title">${escHtml(c.title || 'New Chat')}</div>
            <div class="chat-item-meta">
                <span class="chat-item-date">${formatDate(c.created)}</span>
                ${c.company ? `<span class="chat-item-company">${escHtml(c.company)}</span>` : ''}
            </div>
        </div>
    `).join('');
}

function newChat() {
    const chat = { id: 'chat_' + Date.now(), title: '', company: null, messages: [], created: Date.now() };
    chats.unshift(chat);
    activeChatId = chat.id;
    saveChats();
    renderChatList();
    renderMessages();
    document.getElementById('chat-input').focus();
}

function loadChat(id) {
    // Exit split view or focus mode so chat is visible
    if (_splitActive) {
        const remaining = _splitPanels[_splitFocusedSide];
        _exitSplitView();
        if (remaining.type === 'report' && remaining.reportFilename) {
            openReport(remaining.reportFilename);
        } else if (remaining.type === 'briefing' && remaining.dossierName) {
            openDossier(remaining.dossierName);
        }
    }
    const rp = document.getElementById('right-pane');
    if (rp && rp.classList.contains('expanded')) {
        collapseReport();
    }
    activeChatId = id;
    renderChatList();
    renderMessages();
}

function deleteChat(id) {
    chats = chats.filter(c => c.id !== id);
    saveChats();
    if (id === activeChatId) {
        if (chats.length) loadChat(chats[0].id);
        else newChat();
    } else {
        renderChatList();
    }
}

// ===================== REPORT LIST (kept for openReport compat) =====================
async function loadReports() {
    try {
        const resp = await fetch('/api/reports');
        allReports = await resp.json();
    } catch { allReports = []; }
}

// ===================== COMPANY LIST (unified sidebar) =====================
let activeDossierName = null;

async function loadCompanies() {
    try {
        const resp = await fetch('/api/companies');
        if (!resp.ok) { console.error('Companies API error:', resp.status); allCompanies = []; }
        else { allCompanies = await resp.json(); }
    } catch (e) { console.error('loadCompanies failed:', e); allCompanies = []; }
    renderCompanyList();
}

function refreshSidebar() {
    // Reload companies panel if visible, and always refresh allReports for openReport compat
    loadReports();
    const panel = document.getElementById('panel-companies');
    if (panel && panel.classList.contains('active')) loadCompanies();
}

// --- LLM Usage Tracking ---
async function refreshUsageBadge() {
    try {
        const resp = await fetch('/api/llm-usage');
        const data = await resp.json();
        const badge = document.getElementById('llm-usage-badge');
        if (!badge || data.error) return;

        const t = data.today || {};
        const total = t.total || 0;
        const success = t.success || 0;
        const failed = total - success;
        const totalTokens = (t.input_tokens || 0) + (t.output_tokens || 0);

        // Badge shows calls + token count
        const tokStr = totalTokens > 0 ? ` · ${_fmtTok(totalTokens)}` : '';
        badge.textContent = `${total} calls${tokStr}`;
        badge.classList.remove('warning', 'danger');
        if (failed > 5) badge.classList.add('danger');
        else if (failed > 0) badge.classList.add('warning');

        // Update global sidebar badge (visible in all modules)
        const globalBadge = document.getElementById('global-llm-text');
        if (globalBadge) globalBadge.textContent = totalTokens > 0 ? `${_fmtTok(totalTokens)}` : `${total}`;

        // Render panel content
        const panel = document.getElementById('llm-usage-content');
        if (!panel) return;
        let html = '';
        html += `<div class="llm-usage-row"><span>Total calls</span><span class="cnt">${total}</span></div>`;
        html += `<div class="llm-usage-row"><span>Successful</span><span class="cnt">${success}</span></div>`;
        if (failed) html += `<div class="llm-usage-row error"><span>Failed/Rate-limited</span><span class="cnt">${failed}</span></div>`;
        if (totalTokens > 0) {
            html += `<div class="llm-usage-row"><span>Input tokens</span><span class="cnt">${_fmtTok(t.input_tokens||0)}</span></div>`;
            html += `<div class="llm-usage-row"><span>Output tokens</span><span class="cnt">${_fmtTok(t.output_tokens||0)}</span></div>`;
            html += `<div class="llm-usage-row"><span>Total tokens</span><span class="cnt" style="color:#a855f7">${_fmtTok(totalTokens)}</span></div>`;
        }

        // By provider — with per-model token counts
        const byProvider = {};
        (t.by_provider || []).forEach(r => {
            const key = `${r.provider}/${r.model}`;
            if (!byProvider[key]) byProvider[key] = { success: 0, fail: 0, in_tok: 0, out_tok: 0 };
            if (r.status === 'success') byProvider[key].success += r.cnt;
            else byProvider[key].fail += r.cnt;
            byProvider[key].in_tok += (r.input_tokens || 0);
            byProvider[key].out_tok += (r.output_tokens || 0);
        });
        const providers = Object.entries(byProvider);
        if (providers.length) {
            html += '<div class="llm-usage-divider"></div>';
            providers.forEach(([name, counts]) => {
                const short = name.split('/').pop().replace(/-/g, ' ').slice(0, 25);
                const failStr = counts.fail ? ` <span style="color:#ef4444">(${counts.fail} fail)</span>` : '';
                const modelTok = (counts.in_tok + counts.out_tok) > 0 ? ` <span style="color:#a855f7">${_fmtTok(counts.in_tok + counts.out_tok)}</span>` : '';
                html += `<div class="llm-usage-row"><span>${escHtml(short)}</span><span class="cnt">${counts.success}${failStr}${modelTok}</span></div>`;
            });
        }

        // Per-caller breakdown — which functions are making LLM calls
        const callers = (t.by_caller || []);
        if (callers.length) {
            html += '<div class="llm-usage-divider"></div>';
            html += '<div style="color:var(--accent);font-weight:600;margin-bottom:4px">By Function</div>';
            callers.forEach(c => {
                const name = (c.caller || 'unknown').split(':').pop().replace(/_/g, ' ');
                const callerTok = (c.input_tokens || 0) + (c.output_tokens || 0);
                const avgMs = Math.round(c.avg_duration_ms || 0);
                const failCnt = (c.cnt || 0) - (c.success || 0);
                const failStr = failCnt > 0 ? ` <span style="color:#ef4444">(${failCnt}✗)</span>` : '';
                html += `<div class="llm-usage-row"><span>${escHtml(name)}</span><span class="cnt">${c.success || 0}${failStr} · ${_fmtTok(callerTok)} · ${avgMs}ms</span></div>`;
            });
        }

        // Recent errors
        const errors = data.recent_errors || [];
        if (errors.length) {
            html += '<div class="llm-usage-divider"></div>';
            html += '<div style="color:#ef4444;font-weight:600;margin-bottom:4px">Recent Errors</div>';
            errors.slice(0, 5).forEach(e => {
                const time = _utcToLocal(e.created_at);
                const err = (e.error || '').slice(0, 60);
                html += `<div style="color:var(--text-muted);font-size:11px;margin-bottom:2px">${time} ${escHtml(e.provider)}/${escHtml(e.model?.split('/').pop() || '')} — ${escHtml(err)}</div>`;
            });
        }

        // All-time totals
        const a = data.all_time || {};
        if (a.total) {
            html += '<div class="llm-usage-divider"></div>';
            const allTok = (a.input_tokens || 0) + (a.output_tokens || 0);
            const allFailed = (a.total || 0) - (a.success || 0);
            html += `<div style="color:var(--text-muted);font-weight:600;margin-bottom:4px">All Time</div>`;
            html += `<div class="llm-usage-row"><span>Total calls</span><span class="cnt">${a.total.toLocaleString()}</span></div>`;
            html += `<div class="llm-usage-row"><span>Successful</span><span class="cnt">${(a.success||0).toLocaleString()}</span></div>`;
            if (allFailed) html += `<div class="llm-usage-row error"><span>Failed/Rate-limited</span><span class="cnt">${allFailed.toLocaleString()}</span></div>`;
            if (allTok > 0) html += `<div class="llm-usage-row"><span>Total tokens</span><span class="cnt" style="color:#a855f7">${_fmtTok(allTok)}</span></div>`;
        }

        panel.innerHTML = html;
        // Also update floating panel if it exists
        const floatPanel = document.getElementById('llm-usage-content-float');
        if (floatPanel) floatPanel.innerHTML = html;
    } catch {}
}

function toggleUsagePanel() {
    let panel = document.getElementById('llm-usage-panel');
    // If panel doesn't exist or is inside a hidden workspace, create a floating one
    if (!panel || !panel.offsetParent) {
        let floating = document.getElementById('llm-usage-floating');
        if (!floating) {
            floating = document.createElement('div');
            floating.id = 'llm-usage-floating';
            floating.className = 'llm-usage-panel llm-usage-floating';
            floating.innerHTML = '<div class="llm-usage-title">API Usage Today</div><div id="llm-usage-content-float">Loading...</div>';
            document.body.appendChild(floating);
        }
        const visible = floating.style.display === 'block';
        floating.style.display = visible ? 'none' : 'block';
        if (!visible) {
            // Copy content from original panel if it exists
            refreshUsageBadge().then(() => {
                const orig = document.getElementById('llm-usage-content');
                const dest = document.getElementById('llm-usage-content-float');
                if (orig && dest) dest.innerHTML = orig.innerHTML;
            });
        }
        return;
    }
    const visible = panel.style.display !== 'none';
    panel.style.display = visible ? 'none' : 'block';
    if (!visible) refreshUsageBadge();
}

// Refresh usage badge periodically
setInterval(refreshUsageBadge, 15000);

function _formatSidebarDate(dateStr) {
    if (!dateStr) return '';
    let ds = dateStr;
    if (!ds.includes('T') && ds.includes(' ')) ds = ds.replace(' ', 'T');
    
    // Add Z if it's missing and it looks like UTC (which our DB timestamps are)
    if (!ds.includes('Z') && !ds.includes('+')) ds += 'Z';
    
    const d = new Date(ds);
    if (isNaN(d.getTime())) return '';
    
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    let h = d.getHours(), ampm = h >= 12 ? 'p' : 'a';
    h = h % 12 || 12;
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${mm}-${dd} ${h}:${min}${ampm}`;
}

function toggleCompanySort() {
    companySortMode = companySortMode === 'recent' ? 'alpha' : 'recent';
    const btn = document.getElementById('company-sort-btn');
    if (btn) {
        btn.textContent = companySortMode === 'recent' ? 'New' : 'A-Z';
        btn.title = companySortMode === 'recent' ? 'Sorted by recent' : 'Sorted alphabetically';
    }
    renderCompanyList();
}

function toggleCompany(name) {
    if (openCompanies.has(name)) openCompanies.delete(name);
    else openCompanies.add(name);
    renderCompanyList();
}

function renderCompanyList() {
    const filter = (document.getElementById('company-filter').value || '').toLowerCase();
    const list = document.getElementById('company-list');

    let filtered = allCompanies.filter(c =>
        !filter
        || c.name.toLowerCase().includes(filter)
        || (c.sector || '').toLowerCase().includes(filter)
        || (c.analyses || []).some(a => a.type.toLowerCase().includes(filter))
    );

    if (companySortMode === 'alpha') {
        filtered = [...filtered].sort((a, b) => a.name.localeCompare(b.name));
    }
    // 'recent' keeps the API order (already sorted by last_updated desc)

    if (!filtered.length) {
        list.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px">No companies yet. Start a chat to generate intelligence.</div>';
        return;
    }

    list.innerHTML = filtered.map(company => {
        const isOpen = openCompanies.has(company.name);
        const chevron = '&#9654;';
        const starHtml = company.has_briefing ? '<span class="company-briefing-star" title="Has intelligence briefing">&#9733;</span>' : '';
        const sectorHtml = company.sector ? `<span class="company-sector">${escHtml(company.sector)}</span>` : '';

        let itemsHtml = '';
        if (isOpen) {
            // Briefing link
            if (company.has_briefing) {
                const briefActive = activeDossierName === company.name ? ' active' : '';
                const briefDateStr = _formatSidebarDate(company.briefing_generated_at);
                const displayDate = briefDateStr ? `<span class="report-date" style="font-size:10px; margin-left:auto; opacity:0.7">${briefDateStr}</span>` : '';
                
                itemsHtml += `<div class="company-briefing-link${briefActive}" onclick="openDossier('${escHtml(company.name)}')" onmousedown="handleSidebarMouseDown(event,'briefing',null,'${escHtml(company.name)}')">
                    <span style="display:flex; align-items:center; width:100%">
                        &#9733; Intelligence Briefing
                        ${displayDate}
                    </span>
                </div>`;
            }

                // Analysis items
                (company.analyses || []).forEach(a => {
                    const isActive = currentReportFilename === a.report_file ? ' active' : '';
                    const noReport = !a.has_report ? ' no-report' : '';
                    const dateStr = _formatSidebarDate(a.date);
                itemsHtml += `<div class="report-item can-drag${isActive}" onclick="openReport('${escHtml(a.report_file)}')" onmousedown="handleSidebarMouseDown(event,'report','${escHtml(a.report_file)}','${escHtml(company.name)}')">
                    <span class="report-type-dot dot-${a.type}"></span>
                    <div class="report-rename-wrap">
                        <span class="report-name-text">${escHtml(a.type)}</span>
                        <span class="rename-btn" onclick="renameReport('${escHtml(a.report_file)}', event)" title="Rename report">Edit</span>
                    </div>
                    <span class="report-date">${dateStr}</span></div>`;
            });

            // Orphan reports (files not linked to any dossier_analyses row)
            (company.orphan_reports || []).forEach(fn => {
                const isActive = currentReportFilename === fn ? ' active' : '';
                itemsHtml += `<div class="report-item can-drag${isActive}" onclick="openReport('${escHtml(fn)}')" onmousedown="handleSidebarMouseDown(event,'report','${escHtml(fn)}','${escHtml(company.name)}')">
                    <span class="report-type-dot"></span>
                    <div class="report-rename-wrap">
                        <span class="report-name-text">${escHtml(fn.replace(/\.md$/, ''))}</span>
                        <span class="rename-btn" onclick="renameReport('${escHtml(fn)}', event)" title="Rename report">Edit</span>
                    </div>
                    <span class="report-date"></span></div>`;
            });

            // Generate briefing button
            if (!company.has_briefing && company.analysis_count >= 2) {
                itemsHtml += `<div style="padding:4px 8px 8px"><button class="company-gen-briefing-btn" onclick="event.stopPropagation();generateBriefing('${escHtml(company.name)}')">Generate Briefing</button></div>`;
            }
        }

        const isActive = activeDossierName === company.name;
        return `<div class="company-group${isOpen ? ' open' : ''}">
            <div class="company-group-header${isActive ? ' active' : ''}" onclick="openDossier('${escHtml(company.name)}')">
                <span class="company-group-chevron" onclick="event.stopPropagation();toggleCompany('${escHtml(company.name)}')">${chevron}</span>
                <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${escHtml(company.name)}</span>
                <span class="rename-btn" onclick="renameCompany('${escHtml(company.name)}', event)" title="Rename company">Edit</span>
                <span class="rename-btn" onclick="deleteCompany('${escHtml(company.name)}', event)" title="Delete company" style="color:var(--red)">&times;</span>
                ${starHtml}
                ${sectorHtml}
                <span class="company-group-count">${company.analysis_count || 0}</span>
            </div>
            ${isOpen ? `<div class="company-group-items">${itemsHtml}</div>` : ''}
        </div>`;
    }).join('');
}

async function deleteCompany(nameEscaped, event) {
    if (event) event.stopPropagation();
    const d = document.createElement('div');
    d.innerHTML = nameEscaped;
    const name = d.textContent;

    _showConfirm(`Delete "${name}" and all its analyses, lens scores, and events? This cannot be undone.`, async () => {
    try {
        const resp = await fetch(`/api/dossiers/${encodeURIComponent(name)}/delete`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) {
            _showToast(data.error || 'Delete failed', 'error');
            return;
        }
        openCompanies.delete(name);
        if (activeDossierName === name) activeDossierName = null;
        loadCompanies();
        const rightContent = document.getElementById('right-content');
        if (rightContent && activeDossierName === null) rightContent.innerHTML = '';
        _showToast(`Deleted "${name}"`, 'success');
    } catch (e) {
        _showToast('Delete failed: ' + e.message, 'error');
    }
    }, { danger: true, confirmText: 'Delete' });
}

async function renameCompany(oldNameEscaped, event) {
    if (event) event.stopPropagation();
    // Unescape name in case it was HTML escaped in the template
    const d = document.createElement('div');
    d.innerHTML = oldNameEscaped;
    const oldName = d.textContent;

    const newName = await showPromptModal(`Rename ${oldName} to:`);
    if (!newName || newName === oldName) return;

    try {
        const resp = await fetch(`/api/dossiers/${encodeURIComponent(oldName)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName })
        });
        const text = await resp.text();
        let data;
        try { data = JSON.parse(text); } catch (e) { data = { error: 'Server returned non-JSON response: ' + text.slice(0, 100) }; }

        if (!resp.ok) {
            _showToast(data.error || 'Rename failed', 'error');
            return;
        }
        if (openCompanies.has(oldName)) {
            openCompanies.delete(oldName);
            openCompanies.add(newName);
        }
        if (activeDossierName === oldName) activeDossierName = newName;
        loadCompanies();
        if (activeContext && activeContext.company === oldName) {
            setContext(newName, activeContext.type, activeContext.label);
        }
    } catch (e) {
        console.error('Rename error:', e);
        _showToast('Rename failed: ' + e.message, 'error');
    }
}

async function openDossier(companyName) {
    try {
        // If split view is active, load into focused panel
        if (_splitActive) {
            await _loadIntoSplitPanel(_splitFocusedSide, 'briefing', companyName);
            renderCompanyList();
            return;
        }

        // Pre-fetch available lenses for pill bar
        if (!_cachedLenses) {
            try {
                const lensResp = await fetch('/api/lenses');
                if (lensResp.ok) _cachedLenses = await lensResp.json();
            } catch {}
        }

        const resp = await fetch(`/api/dossiers/${encodeURIComponent(companyName)}`);
        if (!resp.ok) return;
        const dossier = await resp.json();
        activeDossierName = companyName;
        currentReportFilename = null;
        _activeDashboardLens = null;
        const dLabel = dossier.briefing_json ? 'intelligence briefing' : 'dossier';
        setContext(companyName, dossier.briefing_json ? 'briefing' : 'dossier', dLabel);
        renderCompanyList();
        showDossierDetail(dossier);
    } catch (e) {
        console.error('Failed to load dossier:', e);
    }
}

function showDossierDetail(d) {
    const rp = document.getElementById('right-pane');
    currentReportFilename = null;

    // Try to show briefing if available
    if (d.briefing_json) {
        try {
            const briefing = typeof d.briefing_json === 'string' ? JSON.parse(d.briefing_json) : d.briefing_json;
            showBriefing(d, briefing);
            return;
        } catch (e) { console.error('Failed to parse briefing:', e); }
    }

    // Fall back to legacy view
    showLegacyDossierDetail(d);
}

async function deleteOrphanAnalysis(analysisId, event) {
    if (event) event.stopPropagation();
    try {
        const resp = await fetch(`/api/analyses/${analysisId}`, {method: 'DELETE'});
        if (resp.ok) {
            refreshSidebar();
        }
    } catch (e) { console.error('Failed to delete orphan analysis:', e); }
}

async function renameReport(oldFilenameEscaped, event) {
    if (event) event.stopPropagation();
    // Unescape filename in case it was HTML escaped
    const d = document.createElement('div');
    d.innerHTML = oldFilenameEscaped;
    const oldFilename = d.textContent;

    const oldName = oldFilename.replace(/\.md$/, '');
    const newName = await showPromptModal(`Rename report to:`, oldName);
    if (!newName || newName === oldName) return;

    try {
        const resp = await fetch(`/api/reports/${encodeURIComponent(oldFilename)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_filename: newName })
        });
        const text = await resp.text();
        let data;
        try { data = JSON.parse(text); } catch (e) { data = { error: 'Server returned non-JSON: ' + text.slice(0, 100) }; }

        if (!resp.ok) {
            _showToast(data.error || 'Rename failed', 'error');
            return;
        }
        if (currentReportFilename === oldFilename) {
            currentReportFilename = data.new_filename;
        }
        loadCompanies();
        if (currentReportFilename === data.new_filename) {
            openReport(data.new_filename);
        }
    } catch (e) {
        console.error('Rename report error:', e);
        _showToast('Rename failed: ' + e.message, 'error');
    }
}

function _scoreColorClass(score) {
    if (score >= 80) return 'vanguard';
    if (score >= 60) return 'contender';
    if (score >= 40) return 'exposed';
    if (score >= 20) return 'laggard';
    return 'liability';
}

// Global store for source key facts — populated when briefing is rendered
let _sourceKeyFacts = {};
let _sourceAnalysisExists = {};
// Global store for active briefing data — used by dashboard expand mode
let _activeBriefingData = null;
let _activeDossierData = null;
let _activeDashboardLens = null; // lens override for expanded dashboard view

const _VALID_SOURCES = ['hiring','financial','patents','techstack','sentiment','competitors','seo','pricing','profile','landscape','compare','analysis','brand_ad','executive_signals'];

// Match source tags including hyphens (e.g. [lens_ctv-ad-sales], [brand_ad])
const _SOURCE_TAG_RE = /\[([\w][\w,\s-]*)\]/g;

function _isSourceTag(tag) {
    // Accept known sources, lens_ prefixed tags, and any underscore/hyphen tag that looks like a source
    if (_VALID_SOURCES.includes(tag)) return true;
    if (tag.startsWith('lens_')) return true;
    if (/^[a-z][a-z0-9_-]+$/.test(tag)) return true;
    return false;
}

function _sourceBadgeClass(tag) {
    // Map to a known source class for coloring, or fall back to generic
    if (_VALID_SOURCES.includes(tag)) return `source-${tag}`;
    if (tag.startsWith('lens_')) return 'source-lens';
    return 'source-profile';
}

function _sourceBadgeDisplayName(tag) {
    return tag.replace(/^lens_/, '').replace(/[-_]/g, ' ');
}

function _renderSourceBadge(tag) {
    const cls = _sourceBadgeClass(tag);
    const name = _sourceBadgeDisplayName(tag);
    return `<span class="source-badge ${cls}" onclick="event.stopPropagation();showSourcePopover(event,'${tag}')" title="Click to see evidence from ${name} analysis">${name}</span>`;
}

function _renderCitedText(text) {
    // Replace [source] and [source1, source2] tags with clickable badges
    if (!text) return '';
    return escHtml(text).replace(_SOURCE_TAG_RE, (match, inner) => {
        const sources = inner.split(',').map(s => s.trim().toLowerCase().replace(/\s+/g, '_')).filter(s => s);
        const badges = sources
            .filter(s => _isSourceTag(s))
            .map(s => _renderSourceBadge(s));
        return badges.length ? badges.join(' ') : match;
    });
}

function _stripCitations(text) {
    // Remove [source] tags from text, return clean prose
    if (!text) return '';
    return escHtml(text).replace(new RegExp('\\s*' + _SOURCE_TAG_RE.source, 'g'), (match, inner) => {
        const sources = inner.split(',').map(s => s.trim().toLowerCase()).filter(s => s);
        const allValid = sources.every(s => _isSourceTag(s));
        return allValid ? '' : match;
    }).replace(/\s{2,}/g, ' ').trim();
}

function _extractSources(text) {
    // Extract unique source tags from text, return as array
    if (!text) return [];
    const found = new Set();
    text.replace(_SOURCE_TAG_RE, (match, inner) => {
        inner.split(',').map(s => s.trim().toLowerCase()).filter(s => _isSourceTag(s)).forEach(s => found.add(s));
    });
    return [...found];
}

// Priority keys per analysis type — show these first in popover
const _SOURCE_PRIORITY_KEYS = {
    hiring: ['total_open_roles','engineering_ratio','ai_ml_ratio','top_departments','seniority_skew','growth_signal','hiring_trend','top_strategic_tags'],
    sentiment: ['overall_sentiment','glassdoor_rating','recommend_to_friend_pct','top_pros','top_cons','culture_themes','sentiment_trend'],
    financial: ['revenue','revenue_growth','market_cap','valuation','headcount','profitability','cash_position','financial_health'],
    patents: ['total_patents','ai_ml_patents','top_patent_areas','patent_trend','rd_intensity','recent_patents'],
    competitors: ['key_competitors','market_position','competitive_advantages','competitive_moat','threat_level'],
    techstack: ['frontend_framework','analytics_tools','ab_testing_tools','infrastructure_provider','tech_modernity_signals'],
    seo: ['seo_overall_assessment','aeo_readiness_signals','seo_schema_types','pages_analyzed'],
    pricing: ['pricing_model','pricing_tiers','price_range','target_segment','has_free_tier'],
    profile: ['sector','key_products','revenue','headcount','key_competitors','business_model'],
    brand_ad: ['active_ad_channels','ctv_activity','ad_spend_signal','recent_campaigns','content_output','influencer_activity','channel_expansion_signals'],
    executive_signals: ['organizational_commitment','leadership_stability','leadership_investment_domains','recent_executive_hires','open_executive_searches','notable_signals'],
};

const _SOURCE_LABELS = {
    hiring: 'Hiring Intelligence',
    sentiment: 'Employee Sentiment',
    financial: 'Financial Data',
    patents: 'Patent & IP',
    competitors: 'Competitive Landscape',
    techstack: 'Tech Stack',
    seo: 'SEO/AEO Audit',
    pricing: 'Pricing Analysis',
    profile: 'Company Profile',
    landscape: 'Market Landscape',
    compare: 'Comparison',
    analysis: 'Analysis',
    brand_ad: 'Brand & Advertising',
    executive_signals: 'Executive Signals',
};

function showSourcePopover(event, type) {
    // Remove any existing popover
    dismissSourcePopover();

    const facts = _sourceKeyFacts[type];
    const badge = event.target;
    const rect = badge.getBoundingClientRect();

    const pop = document.createElement('div');
    pop.className = 'source-popover';
    pop.id = 'active-source-popover';

    const displayName = _sourceBadgeDisplayName(type);
    const label = _SOURCE_LABELS[type] || (displayName.charAt(0).toUpperCase() + displayName.slice(1));
    const badgeCls = _sourceBadgeClass(type);
    let html = `<div class="source-popover-header"><span class="source-badge ${badgeCls}">${escHtml(displayName)}</span> ${escHtml(label)}</div>`;

    if (facts && Object.keys(facts).length) {
        // Sort entries by priority for this source type
        const priority = _SOURCE_PRIORITY_KEYS[type] || [];
        const allEntries = Object.entries(facts).filter(([k, v]) => v !== null && v !== undefined && v !== '');
        const sorted = allEntries.sort((a, b) => {
            const ai = priority.indexOf(a[0]);
            const bi = priority.indexOf(b[0]);
            if (ai >= 0 && bi >= 0) return ai - bi;
            if (ai >= 0) return -1;
            if (bi >= 0) return 1;
            return 0;
        });
        const shown = sorted.slice(0, 5);
        shown.forEach(([key, val]) => {
            const fmtLabel = key.replace(/_/g, ' ').replace(/\bpct\b/g, '%');
            let value;
            if (Array.isArray(val)) {
                value = val.slice(0, 3).join(', ');
                if (val.length > 3) value += ` (+${val.length - 3} more)`;
            } else {
                value = String(val);
            }
            html += `<div class="source-popover-fact"><strong>${escHtml(fmtLabel)}:</strong> ${escHtml(value)}</div>`;
        });
        if (sorted.length > 5) {
            html += `<div class="source-popover-fact" style="color:var(--text-muted);font-style:italic">+ ${sorted.length - 5} more facts</div>`;
        }
    } else if (_sourceAnalysisExists[type]) {
        html += `<div class="source-popover-fact" style="font-style:italic">Facts are being extracted. Reopen the briefing in a moment.</div>`;
    } else {
        html += `<div class="source-popover-fact" style="font-style:italic">No structured facts extracted yet. Run this analysis to populate.</div>`;
    }

    // Detect which split panel the badge lives in (if any) so scrollToSourceReport
    // targets the correct panel when both panels have briefings.
    let originPanel = '';
    if (_splitActive) {
        const leftContent = document.getElementById('split-content-left');
        const rightContent = document.getElementById('split-content-right');
        if (leftContent && leftContent.contains(badge)) originPanel = 'left';
        else if (rightContent && rightContent.contains(badge)) originPanel = 'right';
    }
    html += `<div class="source-popover-link" onclick="dismissSourcePopover();scrollToSourceReport('${type}','${originPanel}')">View full report &rarr;</div>`;

    pop.innerHTML = html;
    document.body.appendChild(pop);

    // Position below the badge, clamped to viewport
    const popRect = pop.getBoundingClientRect();
    let top = rect.bottom + 6;
    let left = rect.left;
    if (top + popRect.height > window.innerHeight - 10) top = rect.top - popRect.height - 6;
    if (left + popRect.width > window.innerWidth - 10) left = window.innerWidth - popRect.width - 10;
    pop.style.top = top + 'px';
    pop.style.left = Math.max(10, left) + 'px';

    // Dismiss on outside click (after a tick to avoid immediate dismiss)
    setTimeout(() => {
        document.addEventListener('click', _popoverOutsideClick, { once: true });
    }, 10);
}

function _popoverOutsideClick(e) {
    const pop = document.getElementById('active-source-popover');
    if (pop && !pop.contains(e.target)) {
        dismissSourcePopover();
    } else if (pop) {
        // Re-attach if click was inside popover
        setTimeout(() => {
            document.addEventListener('click', _popoverOutsideClick, { once: true });
        }, 10);
    }
}

function toggleScoreTooltip(icon) {
    const parent = icon.closest('.maturity-label') || icon.closest('.dash-hero-label');
    if (!parent) return;
    const tooltip = parent.nextElementSibling;
    if (tooltip && tooltip.classList.contains('score-tooltip')) {
        const showing = tooltip.style.display === 'none';
        tooltip.style.display = showing ? 'block' : 'none';
        if (showing) {
            setTimeout(() => {
                document.addEventListener('click', function _dismiss(e) {
                    if (!tooltip.contains(e.target) && e.target !== icon) {
                        tooltip.style.display = 'none';
                        document.removeEventListener('click', _dismiss);
                    }
                });
            }, 10);
        }
    }
}

function toggleMethodologyTip(tipId) {
    const tip = document.getElementById(tipId);
    if (tip) tip.style.display = tip.style.display === 'none' ? 'block' : 'none';
}

function dismissSourcePopover() {
    const pop = document.getElementById('active-source-popover');
    if (pop) pop.remove();
}

function scrollToSourceReport(type, originPanel) {
    // If in dashboard/expanded mode, restore original briefing first
    const rp = document.getElementById('right-pane');
    if (rp && rp.classList.contains('expanded') && _originalReportHTML) {
        _restoreOriginalReport();
        rp.classList.remove('expanded');
        document.getElementById('expand-icon-open').style.display = '';
        document.getElementById('expand-icon-close').style.display = 'none';
        document.getElementById('expand-btn').title = 'Focus mode';
        if (savedRightWidth) {
            rp.style.width = savedRightWidth + 'px';
            rp.style.minWidth = savedRightWidth + 'px';
        } else {
            rp.style.width = '';
            rp.style.minWidth = '';
        }
    }

    // In split view, .right-body is display:none so its .briefing-section elements
    // are hidden. Scope search to the originating split panel.
    let searchRoot = document;
    if (_splitActive) {
        if (originPanel) {
            // Badge told us which panel it lives in
            const panelContent = document.getElementById('split-content-' + originPanel);
            if (panelContent) searchRoot = panelContent;
        } else {
            // Fallback: pick whichever panel has briefing sections
            const leftContent = document.getElementById('split-content-left');
            const rightContent = document.getElementById('split-content-right');
            if (leftContent && leftContent.querySelector('.briefing-section')) {
                searchRoot = leftContent;
            } else if (rightContent && rightContent.querySelector('.briefing-section')) {
                searchRoot = rightContent;
            }
        }
    }

    const sections = searchRoot.querySelectorAll('.briefing-section');
    for (const sec of sections) {
        const title = sec.querySelector('.briefing-section-title');
        if (title && title.textContent.includes('Source Reports')) {
            sec.classList.add('open');
            const row = sec.querySelector(`.staleness-row[data-source-type="${type}"]`);
            if (row) {
                row.style.background = 'rgba(59,130,246,0.15)';
                row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                setTimeout(() => { row.style.background = ''; }, 2000);
            }
            return;
        }
    }
}

function renderScoreRing(score, size) {
    size = size || 120;
    const radius = (size - 16) / 2;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (score / 100) * circumference;
    const cc = _scoreColorClass(score);
    return `<div class="maturity-ring" style="width:${size}px;height:${size}px">
        <svg width="${size}" height="${size}">
            <circle class="ring-bg" cx="${size/2}" cy="${size/2}" r="${radius}" />
            <circle class="ring-fill ring-${cc}" cx="${size/2}" cy="${size/2}" r="${radius}"
                    stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" />
        </svg>
        <div class="maturity-value score-${cc}">${score}</div>
    </div>`;
}

function renderSubScore(label, score, algoData) {
    const cc = _scoreColorClass(score);
    let infoIcon = '';
    if (algoData && algoData.algorithmic_score !== undefined) {
        const algoScore = algoData.algorithmic_score;
        const conf = algoData.algorithmic_confidence;
        const signals = algoData.signals_used || [];
        const confPct = conf !== undefined ? Math.round(conf * 100) + '%' : '?';
        const delta = score - algoScore;
        const deltaStr = delta > 0 ? `+${delta}` : delta < 0 ? `${delta}` : '±0';
        let tipRows = signals.map(s => `<div class="methodology-tip-row">${escHtml(s)}</div>`).join('');
        if (!tipRows) tipRows = '<div class="methodology-tip-row" style="font-style:italic">No structured signals</div>';
        const tipId = 'algo-tip-' + label.replace(/[^a-zA-Z]/g, '');
        infoIcon = ` <span class="score-info-icon" onclick="event.stopPropagation();toggleMethodologyTip('${tipId}')" style="font-size:11px">&#9432;</span>
            <div class="methodology-tip" id="${tipId}">
                <div class="methodology-tip-title">Algorithmic Base: ${algoScore}/100 → Final: ${score}/100 (${deltaStr})</div>
                <div class="methodology-tip-row"><strong>Confidence:</strong> ${confPct}</div>
                <div style="margin-top:4px;font-size:12px;font-weight:600;color:var(--text-secondary)">Signals:</div>
                ${tipRows}
            </div>`;
    }
    return `<div class="sub-score-row">
        <span class="sub-score-label">${escHtml(label)}${infoIcon}</span>
        <div class="sub-score-bar"><div class="sub-score-fill" style="width:${score}%;background:var(--${cc === 'vanguard' ? 'green' : cc === 'contender' ? 'accent' : cc === 'exposed' ? 'yellow' : 'red'})"></div></div>
        <span class="sub-score-value score-${cc}">${score}</span>
    </div>`;
}

function _briefingSection(title, body, open) {
    return `<div class="briefing-section${open ? ' open' : ''}">
        <div class="briefing-section-header" onclick="this.parentElement.classList.toggle('open')">
            <span class="briefing-section-title">${escHtml(title)}</span>
            <span class="briefing-section-chevron">&#9660;</span>
        </div>
        <div class="briefing-section-body">${body}</div>
    </div>`;
}

// ---- Dynamic scoring section (lens-parameterized) ----

function _renderScoringSection(scoring, isFullBriefing) {
    // Extract lens metadata with legacy fallbacks
    const lensInfo = scoring._lens || {};
    const scoringLabel = lensInfo.score_label || 'Digital Maturity Score';
    const dims = scoring._dimensions || [
        {key:'tech_modernity', label:'Tech Modernity', weight:0.30},
        {key:'data_analytics', label:'Data & Analytics', weight:0.25},
        {key:'ai_readiness', label:'AI Readiness', weight:0.25},
        {key:'organizational_readiness', label:'Org Readiness', weight:0.20},
    ];
    const lensLabels = scoring._lens_labels || [
        {min_score:80, label:'Digital Vanguard'},
        {min_score:60, label:'Digital Contender'},
        {min_score:40, label:'Digitally Exposed'},
        {min_score:20, label:'Digital Laggard'},
        {min_score:0, label:'Digital Liability'},
    ];

    const score = scoring.overall_score || 0;
    const label = scoring.overall_label || '';
    const subs = scoring.sub_scores || {};

    let html = '';
    html += renderScoreRing(score, 120);
    html += `<div class="score-tooltip-wrap"><div class="maturity-label score-${_scoreColorClass(score)}">${escHtml(label)} <span class="score-info-icon" onclick="event.stopPropagation();toggleScoreTooltip(this)">&#9432;</span></div>
    <div class="score-tooltip" style="display:none">
        <div class="score-tooltip-title">${escHtml(scoringLabel)}</div>
        <div class="score-tooltip-body">
            ${isFullBriefing ? 'Scores this company across weighted dimensions:' : 'Lens scoring overlay — scores from a separate lens evaluation:'}
            <div class="score-tooltip-dims">`;
    dims.forEach(d => {
        const wPct = Math.round((d.weight || 0) * 100);
        html += `<div><strong>${escHtml(d.label)} (${wPct}%)</strong></div>`;
    });
    html += `</div><div class="score-tooltip-tiers">`;
    lensLabels.forEach(tier => {
        const cc = _scoreColorClass(tier.min_score);
        html += `<span class="score-${cc}">&#9679;</span> ${tier.min_score}+ ${escHtml(tier.label)} &nbsp;`;
    });
    html += `</div></div></div></div>`;

    if (!isFullBriefing) {
        html += `<div style="font-size:11px;color:var(--text-muted);text-align:center;margin-top:4px;font-style:italic">Scoring overlay — briefing content reflects a different lens</div>`;
    }

    // Sub-scores
    dims.forEach(d => {
        const sub = subs[d.key] || {};
        html += renderSubScore(d.label, sub.score || 0, sub);
    });

    // Sub-score rationales with source badges
    html += `<div style="margin-top:8px">`;
    dims.forEach(d => {
        const sub = subs[d.key] || {};
        if (sub.rationale) {
            const sources = _extractSources(sub.rationale);
            const badges = sources.map(s =>
                _renderSourceBadge(s)
            ).join(' ');
            html += `<div style="margin-bottom:6px"><span style="font-size:15px;font-weight:600;color:var(--text-secondary)">${escHtml(d.label)}:</span> <span style="font-size:15px;color:var(--text-muted)">${_stripCitations(sub.rationale)}</span> ${badges}</div>`;
        }
    });
    html += `</div>`;

    return html;
}

// ---- Extracted render functions for lens-parameterized sections ----

function _renderOpportunitiesSection(opps) {
    if (!opps || !opps.length) return '';
    let oppHtml = '';
    opps.forEach(opp => {
        const pClass = `opp-priority-${opp.priority || 'medium'}`;
        const explicitSources = opp.source_analyses || [];
        const inlineSources = _extractSources((opp.evidence || '') + ' ' + (opp.detail || ''));
        const allSources = [...new Set([...explicitSources, ...inlineSources])];
        const sourceBadges = allSources.map(s =>
            _renderSourceBadge(s)
        ).join(' ');
        oppHtml += `<div class="opp-card" onclick="this.classList.toggle('expanded')">
            <div class="opp-card-header">
                <span class="opp-service">${escHtml(opp.service || '')}</span>
                <span class="opp-priority ${pClass}">${escHtml(opp.priority || '')}</span>
            </div>
            <div class="opp-evidence">${_renderCitedText(opp.evidence || '')}</div>
            <div class="opp-meta">
                <span>${escHtml(opp.estimated_scope || '')}</span>
            </div>
            ${opp.why_now ? `<div class="opp-why-now">${_renderCitedText(opp.why_now)}</div>` : ''}
            <div class="opp-detail">
                ${opp.detail ? `<div class="opp-detail-text">${_renderCitedText(opp.detail)}</div>` : ''}
                ${allSources.length ? `<div class="opp-source-links"><span style="font-size:14px;color:var(--text-muted);margin-right:2px">Sources:</span>${sourceBadges}</div>` : ''}
            </div>
        </div>`;
    });
    return `<div style="padding:0 12px 12px">
        <div style="font-size:15px;font-weight:600;color:var(--text-primary);margin-bottom:8px">Consulting Opportunities <span class="score-info-icon" onclick="event.stopPropagation();toggleMethodologyTip('scope-methodology')">&#9432;</span></div>
        <div class="methodology-tip" id="scope-methodology">
            <div class="methodology-tip-title">Scope Estimation Methodology</div>
            Estimates based on typical Big 4 / MBB engagement structures (blended daily rate ~$3-5K/consultant):
            <div class="methodology-tip-row"><strong>$500K-1M, 3-6 mo</strong> — Small team (2-3). Assessments, strategy design, POC, governance frameworks.</div>
            <div class="methodology-tip-row"><strong>$1-3M, 6-12 mo</strong> — Medium team (4-6). Platform implementation, org redesign, single workstream.</div>
            <div class="methodology-tip-row"><strong>$2-5M, 9-18 mo</strong> — Large team (6-10). Multi-workstream programs, enterprise rollout. $10B+ revenue companies.</div>
            <div class="methodology-tip-row"><strong>$5M+, 12-24 mo</strong> — Full transformation (10+). Company-wide digital transformation. $50B+ companies only.</div>
            <div class="methodology-tip-note">Scaled to company size using revenue, headcount, and hiring velocity. Conservative estimates preferred.</div>
        </div>
        ${oppHtml}</div>`;
}

function _renderRiskSection(risks) {
    if (!risks || !risks.length) return '';
    let riskHtml = '';
    risks.forEach(r => {
        const sev = r.severity || 'medium';
        riskHtml += `<div class="risk-card risk-${sev}">
            <div class="risk-category">${escHtml(r.category || '')} - ${escHtml(sev)}</div>
            <div class="risk-desc">${_renderCitedText(r.description || '')}</div>
        </div>`;
    });
    return _briefingSection('Risk Profile', riskHtml, false);
}

function _renderAssessmentSection(text) {
    if (!text) return '';
    return _briefingSection('Strategic Assessment', `<div style="font-size:14px;color:var(--text-secondary);line-height:1.6;white-space:pre-wrap">${_renderCitedText(text)}</div>`, false);
}

// ---- Lens section swapping ----

function _enrichScoringFromLensData(lensScoreData) {
    // Build scoring object from lens_scores data, enriching with lens config metadata
    const scoring = lensScoreData.score_data || lensScoreData;
    const lc = lensScoreData.lens_config || {};
    if (!scoring._lens_labels && lc.labels && lc.labels.length) scoring._lens_labels = lc.labels;
    if (!scoring._lens) scoring._lens = {};
    if (!scoring._lens.score_label && lc.score_label) scoring._lens.score_label = lc.score_label;
    if (!scoring._lens.name && lensScoreData.lens_name) scoring._lens.name = lensScoreData.lens_name;
    if (!scoring._dimensions && lc.dimensions) {
        scoring._dimensions = lc.dimensions.map(d => ({key: d.key, label: d.label, weight: d.weight}));
    }
    return scoring;
}

function _swapAllLensSections(lensScoreData, briefingData, isFullBriefing) {
    // 1. Swap scoring
    const scoringContainer = document.getElementById('scoring-swap-area');
    if (scoringContainer) {
        const scoring = isFullBriefing ? (briefingData.scoring || briefingData.digital_maturity || {}) : _enrichScoringFromLensData(lensScoreData);
        scoringContainer.innerHTML = _renderScoringSection(scoring, isFullBriefing);
    }

    // 2. Swap opportunities
    const oppsContainer = document.getElementById('opps-swap-area');
    if (oppsContainer) {
        if (isFullBriefing && briefingData) {
            oppsContainer.innerHTML = _renderOpportunitiesSection(briefingData.engagement_opportunities || []);
        } else {
            const sd = lensScoreData.score_data || lensScoreData;
            const opps = sd.engagement_opportunities || [];
            if (opps.length) {
                oppsContainer.innerHTML = _renderOpportunitiesSection(opps);
            } else {
                const lensId = lensScoreData.lens_id || (sd._lens || {}).id;
                const companyName = (_activeDossierData || {}).company_name || '';
                oppsContainer.innerHTML = `<div style="padding:12px;text-align:center;color:var(--text-muted);font-size:13px">
                    Opportunities not available for this score version.
                    <span style="color:var(--accent);cursor:pointer" onclick="_scoreLensViaPill('${escHtml(companyName)}', ${lensId})">Rescore to generate.</span>
                </div>`;
            }
        }
    }

    // 3. Swap risk profile
    const riskContainer = document.getElementById('risk-swap-area');
    if (riskContainer) {
        if (isFullBriefing && briefingData) {
            riskContainer.innerHTML = _renderRiskSection(briefingData.risk_profile || []);
        } else {
            const sd = lensScoreData.score_data || lensScoreData;
            const risks = sd.risk_profile || [];
            if (risks.length) {
                riskContainer.innerHTML = _renderRiskSection(risks);
            } else {
                riskContainer.innerHTML = '';
            }
        }
    }

    // 4. Swap strategic assessment
    const assessContainer = document.getElementById('assessment-swap-area');
    if (assessContainer) {
        if (isFullBriefing && briefingData) {
            assessContainer.innerHTML = _renderAssessmentSection(briefingData.strategic_assessment || '');
        } else {
            const sd = lensScoreData.score_data || lensScoreData;
            const text = sd.strategic_assessment || '';
            if (text) {
                assessContainer.innerHTML = _renderAssessmentSection(text);
            } else {
                assessContainer.innerHTML = '';
            }
        }
    }

    // 5. Update active pill
    document.querySelectorAll('#lens-pill-bar .lens-pill').forEach(p => p.classList.remove('active'));
    if (isFullBriefing) {
        const bp = document.getElementById('briefing-lens-pill');
        if (bp) bp.classList.add('active');
    } else {
        const lensId = lensScoreData.lens_id || (lensScoreData.score_data || lensScoreData)._lens?.id;
        const tp = document.getElementById(`lens-pill-${lensId}`);
        if (tp) tp.classList.add('active');
    }
}

// ---- Pill click handlers ----

async function handleLensPillClick(lensId, isFullBriefing) {
    if (isFullBriefing) {
        _swapAllLensSections(null, _activeBriefingData, true);
        return;
    }
    const scored = (_activeDossierData.lens_scores || []).find(s => s.lens_id === lensId);
    if (scored) {
        _swapAllLensSections(scored, null, false);
    } else {
        await _scoreLensViaPill((_activeDossierData || {}).company_name, lensId);
    }
}

async function _scoreLensViaPill(companyName, lensId) {
    const pill = document.getElementById(`lens-pill-${lensId}`);
    if (!pill || !companyName) return;

    pill.classList.add('lens-pill-loading');
    const origInner = pill.innerHTML;

    try {
        const resp = await fetch(`/api/dossiers/${encodeURIComponent(companyName)}/score-lens`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lens_id: lensId })
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Scoring failed', 'error');
            pill.classList.remove('lens-pill-loading');
            pill.innerHTML = origInner;
            return;
        }

        const data = await resp.json();
        const scoreData = data.score;

        // Update pill to scored state
        pill.classList.remove('lens-pill-loading', 'lens-pill-unscored');
        pill.style.borderStyle = '';
        pill.style.opacity = '';
        const sc = scoreData.overall_score || 0;
        const cc = _scoreColorClass(sc);
        const pillScore = pill.querySelector('.lens-pill-score');
        if (pillScore) {
            pillScore.textContent = sc;
            pillScore.className = `lens-pill-score score-${cc}`;
            pillScore.style.color = '';
        }

        // Update dossier cache
        if (!_activeDossierData.lens_scores) _activeDossierData.lens_scores = [];
        const lensInfo = (_cachedLenses || []).find(l => l.id === lensId);
        const lsEntry = {
            lens_id: lensId,
            lens_name: lensInfo ? lensInfo.name : 'Lens',
            overall_score: sc,
            overall_label: scoreData.overall_label,
            score_data: scoreData,
            lens_config: lensInfo ? (lensInfo.config || lensInfo) : {},
        };
        _activeDossierData.lens_scores = _activeDossierData.lens_scores.filter(s => s.lens_id !== lensId);
        _activeDossierData.lens_scores.push(lsEntry);

        // Swap to the new lens view
        _swapAllLensSections(lsEntry, null, false);
    } catch (e) {
        showToast('Scoring failed: ' + e.message, 'error');
        pill.classList.remove('lens-pill-loading');
        pill.innerHTML = origInner;
    }
}

// ---- Dashboard (expanded) lens pill handler ----

async function handleDashLensPillClick(lensId, isFullBriefing) {
    if (isFullBriefing) {
        _activeDashboardLens = null;
    } else {
        const scored = (_activeDossierData.lens_scores || []).find(s => s.lens_id === lensId);
        if (scored) {
            _activeDashboardLens = scored;
        } else {
            // Score the unscored lens, then rebuild
            const companyName = (_activeDossierData || {}).company_name;
            if (!companyName) return;
            // Reuse the existing score-via-pill logic but rebuild dashboard after
            await _scoreLensViaDashPill(companyName, lensId);
            return;
        }
    }
    // Rebuild the dashboard with the new active lens
    const content = document.getElementById('right-content');
    if (content) _buildBriefingDashboard(content);
}

async function _scoreLensViaDashPill(companyName, lensId) {
    try {
        const resp = await fetch(`/api/dossiers/${encodeURIComponent(companyName)}/score-lens`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lens_id: lensId })
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Scoring failed', 'error');
            return;
        }
        const data = await resp.json();
        const scoreData = data.score;
        const sc = scoreData.overall_score || 0;

        // Update dossier cache
        if (!_activeDossierData.lens_scores) _activeDossierData.lens_scores = [];
        const lensInfo = (_cachedLenses || []).find(l => l.id === lensId);
        const lsEntry = {
            lens_id: lensId,
            lens_name: lensInfo ? lensInfo.name : 'Lens',
            overall_score: sc,
            overall_label: scoreData.overall_label,
            score_data: scoreData,
            lens_config: lensInfo ? (lensInfo.config || lensInfo) : {},
        };
        _activeDossierData.lens_scores = _activeDossierData.lens_scores.filter(s => s.lens_id !== lensId);
        _activeDossierData.lens_scores.push(lsEntry);

        // Set as active and rebuild
        _activeDashboardLens = lsEntry;
        const content = document.getElementById('right-content');
        if (content) _buildBriefingDashboard(content);
    } catch (e) {
        showToast('Scoring failed: ' + e.message, 'error');
    }
}

// Render briefing HTML into a target element (for split panels).
// Does NOT set global state or update header.
function _renderBriefingInto(dossier, b, targetEl) {
    showBriefing(dossier, b, targetEl);
}

function showBriefing(dossier, b, _targetEl) {
    const isSplitTarget = !!_targetEl;
    if (!isSplitTarget) {
        _activeBriefingData = b;
        _activeDossierData = dossier;
    }
    const rp = document.getElementById('right-pane');
    const identity = b.subject_identity || {};
    if (!isSplitTarget) {
        document.getElementById('right-company').textContent = identity.name || dossier.company_name;
        document.getElementById('right-type').textContent = '';
        document.getElementById('right-date').textContent = '';
    }

    // Populate source key facts for popover references (no LLM needed)
    _sourceKeyFacts = {};
    _sourceAnalysisExists = {};
    (dossier.analyses || []).forEach(a => {
        _sourceAnalysisExists[a.analysis_type] = true;
        if (a.key_facts_json && !_sourceKeyFacts[a.analysis_type]) {
            try {
                _sourceKeyFacts[a.analysis_type] = JSON.parse(a.key_facts_json);
            } catch {}
        }
    });

    let html = '';

    // --- Header ---
    html += `<div class="briefing-header">
        <div class="briefing-header-title">Intelligence Briefing</div>
        <div class="briefing-header-company">${escHtml(identity.name || dossier.company_name)}</div>
        ${identity.sector ? `<div class="briefing-header-sector">${escHtml(identity.sector)}</div>` : ''}
        <div class="briefing-header-meta">`;
    if (identity.hq_location) html += `<span>${escHtml(identity.hq_location)}</span>`;
    if (identity.founded) html += `<span>Est. ${identity.founded}</span>`;
    if (identity.headcount) html += `<span>${escHtml(String(identity.headcount))} employees</span>`;
    if (dossier.briefing_generated_at) {
        let dateStr = dossier.briefing_generated_at;
        if (!dateStr.includes('T') && dateStr.includes(' ')) dateStr = dateStr.replace(' ', 'T');
        const d = new Date(dateStr);
        if (!isNaN(d.getTime())) {
            html += `<span>Last Refreshed: ${d.toLocaleString()}</span>`;
        }
    }
    html += `</div>`;

    // Staleness check — normalize timestamps to UTC for comparison
    if (dossier.briefing_generated_at && dossier.analyses && dossier.analyses.length) {
        const briefingDate = new Date(dossier.briefing_generated_at);
        // Analysis timestamps may lack timezone — append Z to treat as UTC
        let latestTs = dossier.analyses[0].created_at;
        if (latestTs && !latestTs.includes('+') && !latestTs.endsWith('Z')) {
            latestTs = latestTs.replace(' ', 'T') + 'Z';
        }
        const latestAnalysis = new Date(latestTs);
        if (latestAnalysis > briefingDate) {
            html += `<div class="briefing-stale-badge">Briefing outdated - new analyses available</div>`;
        }
    }

    html += `<div class="briefing-actions">
        <button class="briefing-btn briefing-btn-primary" onclick="generateBriefing('${escHtml(dossier.company_name)}')">Generate Briefing</button>
    </div></div>`;

    // --- Scoring Section (lens-parameterized) ---
    const scoring = b.scoring || b.digital_maturity || {};
    const briefingLensId = (scoring._lens || {}).id;

    html += `<div style="padding:16px 12px">`;

    // Lens pill bar — briefing lens + all other lenses (scored & unscored)
    const lensScores = dossier.lens_scores || [];
    const allLenses = _cachedLenses || [];
    const scoredMap = {};
    lensScores.forEach(ls => { scoredMap[ls.lens_id] = ls; });

    html += `<div id="lens-pill-bar" class="lens-bar" style="margin-bottom:12px">`;
    // Briefing's own lens pill (always first, marked as active)
    const briefingLensName = (scoring._lens || {}).name || 'Briefing Score';
    const briefingScore = scoring.overall_score || 0;
    const bcc = _scoreColorClass(briefingScore);
    html += `<div class="lens-pill active" id="briefing-lens-pill" onclick="handleLensPillClick(null, true)">
        <span class="lens-pill-score score-${bcc}">${briefingScore}</span>
        <span class="lens-pill-name">${escHtml(briefingLensName)}</span>
        <span style="font-size:9px;color:var(--green);margin-left:4px">Full</span>
    </div>`;
    // All other lenses — scored or unscored
    allLenses.forEach(lens => {
        if (lens.id === briefingLensId) return; // skip briefing lens (already shown)
        const scored = scoredMap[lens.id];
        if (scored) {
            const lsScore = scored.overall_score || 0;
            const lcc = _scoreColorClass(lsScore);
            html += `<div class="lens-pill" id="lens-pill-${lens.id}" onclick="handleLensPillClick(${lens.id}, false)">
                <span class="lens-pill-score score-${lcc}">${lsScore}</span>
                <span class="lens-pill-name">${escHtml(lens.name)}</span>
            </div>`;
        } else {
            html += `<div class="lens-pill lens-pill-unscored" id="lens-pill-${lens.id}" onclick="handleLensPillClick(${lens.id}, false)">
                <span class="lens-pill-score" style="color:var(--text-muted)">--</span>
                <span class="lens-pill-name">${escHtml(lens.name)}</span>
            </div>`;
        }
    });
    // "+ New Lens" pseudo-pill
    html += `<div class="lens-pill" style="border-style:dashed;color:var(--accent);font-size:11px" onclick="openLensBuilder()">+ New Lens</div>`;
    html += `</div>`;

    // Data confidence indicator
    const conf = b.data_confidence || {};
    if (conf.jobs_analyzed !== undefined || conf.overall_confidence) {
        const confClass = `conf-${conf.overall_confidence || 'medium'}`;
        html += `<div class="data-confidence-bar">
            <span class="conf-badge ${confClass}">${escHtml(conf.overall_confidence || 'unknown')}</span>`;
        if (conf.jobs_analyzed) html += `<span>${conf.jobs_analyzed} roles analyzed</span>`;
        if (conf.scrape_coverage) html += `<span>· ${escHtml(conf.scrape_coverage.split('(')[0].trim())}</span>`;
        const avail = conf.analyses_available || [];
        html += `<span>· ${avail.length} analyses</span>`;
        if (conf.classification_mode === 'fast') html += `<span>· heuristic</span>`;
        html += `</div>`;
    }

    // Swappable scoring area (donut ring, sub-scores, rationales)
    html += `<div id="scoring-swap-area">`;
    html += _renderScoringSection(scoring, true);
    html += `</div></div>`;

    // --- Hiring Trajectory (if available) ---
    const traj = b.hiring_trajectory;
    if (traj && traj.trend) {
        let trajHtml = '';
        if (traj.velocity) {
            const trendUp = ['accelerating','growing'].includes(traj.trend);
            const trendDown = ['decelerating','shrinking'].includes(traj.trend);
            const arrowClass = trendUp ? 'trajectory-up' : trendDown ? 'trajectory-down' : 'trajectory-stable';
            const arrow = trendUp ? '&#9650;' : trendDown ? '&#9660;' : '&#8226;';
            trajHtml += `<div class="trajectory-row">
                <span class="trajectory-arrow ${arrowClass}">${arrow}</span>
                <span style="color:var(--text-primary);font-weight:600">${escHtml(traj.velocity)}</span>
                <span style="color:var(--text-muted)">· ${escHtml(traj.trend)}</span>
            </div>`;
        }
        if (traj.department_shifts && traj.department_shifts.length) {
            traj.department_shifts.forEach(shift => {
                const arrowClass = shift.direction === 'up' ? 'trajectory-up' : shift.direction === 'down' ? 'trajectory-down' : 'trajectory-stable';
                const arrow = shift.direction === 'up' ? '↑' : shift.direction === 'down' ? '↓' : '→';
                trajHtml += `<div class="trajectory-row">
                    <span class="trajectory-arrow ${arrowClass}">${arrow}</span>
                    <span style="color:var(--text-secondary)">${escHtml(shift.department || '')}</span>
                    <span style="color:var(--text-muted);font-size:12px">${escHtml(shift.detail || '')}</span>
                </div>`;
            });
        }
        if (traj.interpretation) {
            trajHtml += `<div style="font-size:15px;color:var(--text-muted);margin-top:6px;line-height:1.5">${_renderCitedText(traj.interpretation)}</div>`;
        }
        html += _briefingSection('Hiring Trajectory', trajHtml, true);
    }

    // --- Consulting Opportunities (lens-parameterized, swappable) ---
    html += `<div id="opps-swap-area">`;
    html += _renderOpportunitiesSection(b.engagement_opportunities || []);
    html += `</div>`;

    // --- Budget & Appetite ---
    const budget = b.budget_signals || {};
    if (Object.keys(budget).length) {
        let budgetHtml = '';
        const confClass = `confidence-${budget.confidence || 'medium'}`;
        budgetHtml += `<div class="budget-row"><span class="budget-label">Can Afford</span><span class="budget-value">${budget.can_afford ? 'Yes' : 'Unlikely'}</span> <span class="confidence-badge ${confClass}">${escHtml(budget.confidence || '')} confidence</span></div>`;
        if (budget.evidence) budgetHtml += `<div style="font-size:15px;color:var(--text-muted);margin:4px 0 8px">${_renderCitedText(budget.evidence)}</div>`;
        if (budget.revenue_trend) budgetHtml += `<div class="budget-row"><span class="budget-label">Revenue Trend</span><span class="budget-value">${escHtml(budget.revenue_trend)}</span></div>`;
        if (budget.hiring_trend) budgetHtml += `<div class="budget-row"><span class="budget-label">Hiring Trend</span><span class="budget-value">${escHtml(budget.hiring_trend)}</span></div>`;
        if (budget.investment_areas && budget.investment_areas.length) {
            budgetHtml += `<div class="budget-row"><span class="budget-label">Investing In</span><span class="budget-value">${budget.investment_areas.map(a => escHtml(a)).join(', ')}</span></div>`;
        }
        html += _briefingSection('Budget & Appetite Signals', budgetHtml, false);
    }

    // --- Competitive Pressure ---
    const comp = b.competitive_pressure || {};
    if (Object.keys(comp).length) {
        let compHtml = '';
        if (comp.urgency) {
            const urgClass = comp.urgency === 'high' ? 'confidence-high' : comp.urgency === 'medium' ? 'confidence-medium' : 'confidence-low';
            compHtml += `<div style="margin-bottom:8px">Transformation urgency: <span class="confidence-badge ${urgClass}">${escHtml(comp.urgency)}</span></div>`;
        }
        if ((comp.competitors || []).length) {
            compHtml += `<div class="competitor-header"><span>Competitor</span><span>Digital Maturity</span><span>Threat Assessment</span></div>`;
        }
        (comp.competitors || []).forEach(c => {
            compHtml += `<div class="competitor-row">
                <span class="competitor-name">${escHtml(c.name || '')}</span>
                <span class="competitor-maturity">${escHtml(c.digital_maturity_estimate || '')}</span>
                <span class="competitor-threat">${_renderCitedText(c.threat || '')}</span>
            </div>`;
        });
        if (comp.urgency_drivers && comp.urgency_drivers.length) {
            compHtml += `<div style="margin-top:8px;font-size:15px;color:var(--text-muted)"><strong>Drivers:</strong> ${comp.urgency_drivers.map(d => _renderCitedText(d)).join(' | ')}</div>`;
        }
        html += _briefingSection('Competitive Pressure', compHtml, false);
    }

    // --- Financial Position ---
    const fin = b.financial_position || {};
    if (Object.keys(fin).length) {
        let finHtml = '';
        if (fin.summary) finHtml += `<div style="font-size:15px;color:var(--text-secondary);margin-bottom:10px;line-height:1.5">${_renderCitedText(fin.summary)}</div>`;
        if (fin.metrics && fin.metrics.length) {
            finHtml += '<div class="metric-grid">';
            fin.metrics.forEach(m => {
                finHtml += `<div class="metric-card"><div class="metric-card-label">${escHtml(m.label || '')}</div><div class="metric-card-value">${_renderCitedText(m.value || '')}</div></div>`;
            });
            finHtml += '</div>';
        }
        html += _briefingSection('Financial Position', finHtml, false);
    }

    // --- Innovation & IP ---
    const ip = b.innovation_ip || {};
    if (Object.keys(ip).length) {
        let ipHtml = '';
        if (ip.patent_count !== undefined) {
            const patentDisplay = ip.patent_count === -1 ? 'Not analyzed' : ip.patent_count;
            ipHtml += `<div class="budget-row"><span class="budget-label">Patents</span><span class="budget-value">${patentDisplay}</span></div>`;
        }
        if (ip.rd_intensity) ipHtml += `<div class="budget-row"><span class="budget-label">R&D Intensity</span><span class="budget-value">${escHtml(ip.rd_intensity)}</span></div>`;
        if (ip.top_areas && ip.top_areas.length) {
            ipHtml += `<div class="budget-row"><span class="budget-label">Top Areas</span><span class="budget-value">${ip.top_areas.map(a => escHtml(a)).join(', ')}</span></div>`;
        }
        if (ip.assessment) ipHtml += `<div style="font-size:15px;color:var(--text-muted);margin-top:8px;line-height:1.5">${_renderCitedText(ip.assessment)}</div>`;
        html += _briefingSection('Innovation & IP', ipHtml, false);
    }

    // --- Talent & Culture ---
    const talent = b.talent_culture || {};
    if (Object.keys(talent).length) {
        let talHtml = '';
        if (talent.sentiment) talHtml += `<div class="budget-row"><span class="budget-label">Sentiment</span><span class="budget-value">${escHtml(talent.sentiment)}</span></div>`;
        if (talent.hiring_momentum) talHtml += `<div style="font-size:15px;color:var(--text-secondary);margin:4px 0 8px;line-height:1.5">${_renderCitedText(talent.hiring_momentum)}</div>`;
        // Department focus as mini bars
        const deptFocus = talent.department_focus || {};
        if (Object.keys(deptFocus).length) {
            talHtml += `<div style="margin:8px 0">`;
            const sorted = Object.entries(deptFocus).sort((a, b) => b[1] - a[1]);
            sorted.forEach(([dept, raw]) => {
                const pct = String(raw).replace('%', '');
                talHtml += `<div class="sub-score-row"><span class="sub-score-label">${escHtml(dept)}</span><div class="sub-score-bar"><div class="sub-score-fill" style="width:${pct}%;background:var(--accent)"></div></div><span class="sub-score-value" style="color:var(--text-secondary)">${pct}%</span></div>`;
            });
            talHtml += `</div>`;
        }
        if (talent.top_skills && talent.top_skills.length) {
            talHtml += `<div class="skill-tags">${talent.top_skills.map(s => `<span class="skill-tag">${escHtml(s)}</span>`).join('')}</div>`;
        }
        if (talent.assessment) talHtml += `<div style="font-size:15px;color:var(--text-muted);margin-top:8px;line-height:1.5">${_renderCitedText(talent.assessment)}</div>`;
        html += _briefingSection('Talent & Culture', talHtml, false);
    }

    // --- Risk Profile (lens-parameterized, swappable) ---
    html += `<div id="risk-swap-area">`;
    html += _renderRiskSection(b.risk_profile || []);
    html += `</div>`;

    // --- Strategic Assessment (lens-parameterized, swappable) ---
    html += `<div id="assessment-swap-area">`;
    html += _renderAssessmentSection(b.strategic_assessment || '');
    html += `</div>`;

    // --- Intelligence Timeline (from dossier events) ---
    const changeEvents = (dossier.events || []).filter(e => e.event_type === 'change_detected');
    const otherEvents = (dossier.events || []).filter(e => e.event_type !== 'change_detected');
    if (changeEvents.length || otherEvents.length) {
        let timeHtml = '';
        changeEvents.forEach(evt => {
            let data = {};
            try { data = JSON.parse(evt.data_json || '{}'); } catch {}
            const field = data.field || '';
            const changeType = data.change_type || '';
            let colorClass = 'change-neutral';
            if (changeType === 'increased') colorClass = 'change-positive';
            else if (changeType === 'decreased') colorClass = 'change-negative';
            timeHtml += `<div class="change-row ${colorClass}">
                <span class="change-field">${escHtml(field.replace(/_/g, ' '))}</span>
                <span class="change-arrow"><span class="change-new">${escHtml(evt.title || '')}</span></span>
                <span class="change-source">${escHtml(evt.event_date || '')}</span>
            </div>`;
        });
        otherEvents.forEach(evt => {
            timeHtml += `<div class="timeline-event">
                <div class="timeline-date">${escHtml(evt.event_date || '')}</div>
                <div class="timeline-type">${escHtml(evt.event_type)}</div>
                <div><div class="timeline-title">${escHtml(evt.title)}</div></div>
            </div>`;
        });
        html += _briefingSection(`Intelligence Timeline (${changeEvents.length + otherEvents.length})`, timeHtml, false);
    }

    // --- Data Confidence ---
    if (conf && (conf.caveats && conf.caveats.length || conf.analyses_missing && conf.analyses_missing.length)) {
        let confHtml = '';
        if (conf.scrape_coverage) confHtml += `<div class="budget-row"><span class="budget-label">Scrape Coverage</span><span class="budget-value">${escHtml(conf.scrape_coverage)}</span></div>`;
        if (conf.jobs_analyzed) confHtml += `<div class="budget-row"><span class="budget-label">Jobs Analyzed</span><span class="budget-value">${conf.jobs_analyzed}</span></div>`;
        if (conf.analyses_available && conf.analyses_available.length) {
            confHtml += `<div class="budget-row"><span class="budget-label">Completed</span><span class="budget-value">${conf.analyses_available.map(a => `<span class="source-badge source-${a}">${a}</span>`).join(' ')}</span></div>`;
        }
        if (conf.analyses_missing && conf.analyses_missing.length) {
            confHtml += `<div class="budget-row"><span class="budget-label">Missing</span><span class="budget-value" style="color:var(--text-muted)">${conf.analyses_missing.join(', ')}</span></div>`;
        }
        if (conf.caveats && conf.caveats.length) {
            confHtml += `<div style="margin-top:8px;font-size:15px;color:var(--text-muted)">`;
            conf.caveats.forEach(c => { confHtml += `<div style="margin-bottom:3px">⚠ ${escHtml(c)}</div>`; });
            confHtml += `</div>`;
        }
        confHtml += `<div style="margin-top:6px"><span class="score-info-icon" onclick="event.stopPropagation();toggleMethodologyTip('confidence-methodology')">&#9432;</span>
            <div class="methodology-tip" id="confidence-methodology">
                <div class="methodology-tip-title">Confidence Methodology</div>
                <div class="methodology-tip-row"><strong>Jobs Analyzed</strong> — &gt;100 = high confidence, 30-100 = medium, &lt;30 = low for hiring signals</div>
                <div class="methodology-tip-row"><strong>Scrape Coverage</strong> — Whether the scrape covered the full ATS board or a limited sample</div>
                <div class="methodology-tip-row"><strong>Analysis Coverage</strong> — How many of the 12 analysis types have been completed</div>
                <div class="methodology-tip-note">Missing analyses create blind spots in specific briefing dimensions. Scores for dimensions without supporting data default to 50.</div>
            </div></div>`;
        html += _briefingSection('Data Confidence', confHtml, false);
    }

    // --- Source Reports ---
    if (dossier.analyses && dossier.analyses.length) {
        let srcHtml = '';
        const byType = {};
        dossier.analyses.forEach(a => {
            if (!byType[a.analysis_type]) byType[a.analysis_type] = [];
            byType[a.analysis_type].push(a);
        });
        const now = new Date();
        Object.entries(byType).forEach(([type, runs]) => {
            const latest = runs[0];
            const lastDate = new Date(latest.created_at);
            const days = Math.floor((now - lastDate) / (1000 * 60 * 60 * 24));
            let freshness = 'fresh', flabel = 'Fresh';
            if (days >= 90) { freshness = 'very-stale'; flabel = `${days}d ago`; }
            else if (days >= 30) { freshness = 'stale'; flabel = `${days}d ago`; }
            else if (days >= 7) { freshness = 'recent'; flabel = `${days}d ago`; }
            else { flabel = days === 0 ? 'Today' : `${days}d ago`; }
            srcHtml += `<div class="staleness-row" data-source-type="${escHtml(type)}">
                <span style="color:var(--text-primary);font-weight:500;min-width:80px">${escHtml(type)}</span>
                <span class="staleness-badge staleness-${freshness}">${flabel}</span>
                <span style="font-size:14px;color:var(--text-muted)">${runs.length} run${runs.length > 1 ? 's' : ''}</span>
                ${latest.report_file ? `<span style="font-size:12px;color:var(--accent);cursor:pointer" onclick="openReport('${escHtml(latest.report_file.replace(/^reports[\\/\\\\]/, ''))}')">View report</span>` : ''}
            </div>`;
        });
        html += _briefingSection('Source Reports', srcHtml, false);
    }

    const writeTarget = _targetEl || document.getElementById('right-content');
    writeTarget.innerHTML = html;

    if (!isSplitTarget) {
        openRightPane();
        // If already in expanded/focus mode, rebuild the dashboard view
        if (rp.classList.contains('expanded')) {
            _buildCardGrid(rp);
        }
    }
}

// ========== LENS SCORES ==========

let _cachedLenses = null;
let _activeLensDetail = null;

function _buildLensScoresSection(dossier) {
    const scores = dossier.lens_scores || [];
    if (!scores.length) return '';

    let body = '<div class="lens-bar">';
    scores.forEach((ls, idx) => {
        const s = ls.overall_score || 0;
        const cc = _scoreColorClass(s);
        body += `<div class="lens-pill${idx === 0 ? ' active' : ''}" onclick="expandLensDetail('${escHtml(dossier.company_name)}', ${idx})" data-lens-idx="${idx}">
            <span class="lens-pill-score score-${cc}">${s}</span>
            <span class="lens-pill-name">${escHtml(ls.lens_name)}</span>
        </div>`;
    });
    body += '</div>';

    // Auto-expand first lens detail
    if (scores.length) {
        body += `<div id="lens-detail-container">${_renderLensDetail(scores[0])}</div>`;
    }

    return _briefingSection('Lens Scores', body, true);
}

function _renderLensDetail(ls) {
    const scoreData = ls.score_data || {};
    const config = ls.lens_config || {};
    const dims = config.dimensions || [];
    const s = scoreData.overall_score || ls.overall_score || 0;
    const label = scoreData.overall_label || ls.overall_label || '';
    const cc = _scoreColorClass(s);
    const scoreLabel = config.score_label || 'Score';

    let html = `<div class="lens-detail-card">
        <div class="lens-detail-header">
            ${renderScoreRing(s, 80)}
            <div class="lens-detail-meta">
                <div class="lens-detail-label">${escHtml(ls.lens_name)}</div>
                <div class="lens-detail-tier score-${cc}">${escHtml(label)}</div>
                ${ls.scored_at ? `<div class="lens-detail-scored">Scored ${_formatLensDate(ls.scored_at)}</div>` : ''}
            </div>
        </div>
        <div class="lens-detail-dims">`;

    // Dimension cards
    dims.forEach(dim => {
        const sub = (scoreData.sub_scores || {})[dim.key] || {};
        const ds = sub.score || 0;
        const color = _dimColorHex(ds);
        const wPct = Math.round((dim.weight || 0) * 100) + '%';
        const rationale = sub.rationale || 'No data available';
        const signals = (sub.signals || []);

        let signalHtml = signals.map(sig => {
            if (typeof sig === 'string') {
                const urlMatch = sig.match(/https?:\/\/[^\s)]+/);
                if (urlMatch) {
                    const url = urlMatch[0];
                    const text = sig.replace(url, '').trim() || url;
                    return `<a class="icp-signal-tag" href="${escHtml(url)}" target="_blank" rel="noopener">${escHtml(text)}</a>`;
                }
                return `<span class="icp-signal-tag">${escHtml(sig)}</span>`;
            }
            const text = sig.text || '';
            const url = sig.url;
            if (url) return `<a class="icp-signal-tag" href="${escHtml(url)}" target="_blank" rel="noopener">${escHtml(text)}</a>`;
            return `<span class="icp-signal-tag">${escHtml(text)}</span>`;
        }).join('');

        html += `<div class="icp-dim-card" onclick="if(!event.target.closest('a')){this.classList.toggle('expanded')}">
            <div class="icp-dim-card-header">
                <span class="dim-chevron">&#9654;</span>
                <span class="icp-dim-name">
                    ${escHtml(dim.label)}
                    <span class="dim-weight">(${wPct})</span>
                </span>
                <span class="icp-dim-score-pill" style="color:${color}">${ds}</span>
            </div>
            <div class="icp-dim-bar"><div class="icp-dim-fill" style="width:${ds}%;background:${color}"></div></div>
            <div class="icp-dim-card-body">
                <div class="icp-dim-rationale">${_renderCitedText(rationale)}</div>
                ${signalHtml ? `<div class="icp-dim-signals">${signalHtml}</div>` : ''}
            </div>
        </div>`;
    });

    html += '</div>';

    // Recommended angle
    if (scoreData.recommended_angle) {
        html += `<div class="lens-detail-footer">
            <div class="lens-footer-label">Recommended Angle</div>
            <div class="lens-footer-text">${_renderCitedText(scoreData.recommended_angle)}</div>
        </div>`;
    }

    // Key risks
    if (scoreData.key_risks && scoreData.key_risks.length) {
        html += `<div class="lens-detail-footer" style="border-top:none;padding-top:0">
            <div class="lens-footer-label">Key Risks</div>
            <ul class="lens-risks-list">${scoreData.key_risks.map(r => `<li>${_renderCitedText(r)}</li>`).join('')}</ul>
        </div>`;
    }

    html += '</div>';
    return html;
}

function _dimColorHex(score) {
    if (score >= 80) return '#22c55e';
    if (score >= 60) return '#3b82f6';
    if (score >= 40) return '#f59e0b';
    return '#ef4444';
}

function _formatLensDate(dateStr) {
    try {
        if (!dateStr.includes('T') && dateStr.includes(' ')) dateStr = dateStr.replace(' ', 'T');
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr;
        const now = new Date();
        const days = Math.floor((now - d) / (1000 * 60 * 60 * 24));
        if (days === 0) return 'today';
        if (days === 1) return 'yesterday';
        if (days < 7) return `${days}d ago`;
        return d.toLocaleDateString();
    } catch { return dateStr; }
}

function expandLensDetail(companyName, idx) {
    // Find the active dossier's lens scores
    const dossier = _activeDossierData;
    if (!dossier || !dossier.lens_scores) return;
    const scores = dossier.lens_scores;
    if (idx >= scores.length) return;

    // Update active pill
    document.querySelectorAll('.lens-pill').forEach((p, i) => {
        p.classList.toggle('active', i === idx);
    });

    // Render detail
    const container = document.getElementById('lens-detail-container');
    if (container) {
        container.innerHTML = _renderLensDetail(scores[idx]);
    }
}

let _briefingInProgress = false;

function generateBriefing(companyName) {
    if (_briefingInProgress) return;
    _showLensPicker(companyName);
}

async function _showLensPicker(companyName) {
    // Ensure lenses are loaded
    if (!_cachedLenses) {
        try {
            const resp = await fetch('/api/lenses');
            if (resp.ok) _cachedLenses = await resp.json();
        } catch {}
    }
    const lenses = _cachedLenses || [];
    if (!lenses.length) {
        // No lenses cached — just generate with default
        _executeGenerateBriefing(companyName, null);
        return;
    }

    // Determine the last-used lens for this company
    let defaultLensId = null;
    const b = _activeBriefingData;
    if (b && b.scoring && b.scoring._lens) {
        defaultLensId = b.scoring._lens.id;
    }

    // Remove any existing picker
    const existing = document.querySelector('.lens-picker-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'niche-builder-overlay lens-picker-overlay';
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

    let pillsHtml = '';
    lenses.forEach(lens => {
        const isDefault = lens.id === defaultLensId;
        pillsHtml += `<div class="lens-picker-pill${isDefault ? ' active' : ''}" data-lens-id="${lens.id}" onclick="_selectLensForBriefing(this, ${lens.id})">
            <div style="font-size:14px;font-weight:600;color:var(--text-primary)">${escHtml(lens.name)}</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">${escHtml((lens.config || {}).score_label || lens.description || '')}</div>
            ${isDefault ? '<div style="font-size:10px;color:var(--green);margin-top:2px">Last used</div>' : ''}
        </div>`;
    });

    overlay.innerHTML = `<div class="niche-builder-modal" style="max-width:460px">
        <div class="niche-builder-header">
            <h2>Choose Lens for ${escHtml(companyName)}</h2>
            <button class="icp-wizard-close" onclick="this.closest('.lens-picker-overlay').remove()">&times;</button>
        </div>
        <div style="padding:16px 20px">
            <div style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select the evaluation lens for this briefing. The lens determines scoring dimensions, rubrics, and how consulting opportunities are framed.</div>
            <div class="lens-picker-grid">${pillsHtml}</div>
            <div style="margin-top:16px;text-align:right">
                <button class="dash-refresh-btn" style="padding:8px 20px;font-size:13px" onclick="_confirmLensPicker('${escHtml(companyName)}')">Generate Briefing</button>
            </div>
        </div>
    </div>`;

    document.body.appendChild(overlay);

    // ESC to close
    const escHandler = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', escHandler); } };
    document.addEventListener('keydown', escHandler);
    overlay._escHandler = escHandler;
}

function _selectLensForBriefing(el, lensId) {
    el.closest('.lens-picker-grid').querySelectorAll('.lens-picker-pill').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
}

function _confirmLensPicker(companyName) {
    const overlay = document.querySelector('.lens-picker-overlay');
    const active = overlay ? overlay.querySelector('.lens-picker-pill.active') : null;
    const lensId = active ? parseInt(active.dataset.lensId) : null;
    if (overlay) {
        if (overlay._escHandler) document.removeEventListener('keydown', overlay._escHandler);
        overlay.remove();
    }
    _executeGenerateBriefing(companyName, lensId);
}

async function _executeGenerateBriefing(companyName, lensId) {
    if (_briefingInProgress) return;
    _briefingInProgress = true;

    // Switch to target company's view first so "Generating..." shows on the right dossier
    if (activeDossierName !== companyName) {
        await openDossier(companyName);
    }

    // Disable all briefing buttons to prevent duplicate clicks
    const allBtns = document.querySelectorAll('.briefing-btn-primary, .company-gen-briefing-btn');
    const origTexts = [];
    allBtns.forEach(b => { origTexts.push(b.textContent); b.disabled = true; b.textContent = 'Generating...'; });

    const resetBtns = () => {
        allBtns.forEach((b, i) => { b.disabled = false; b.textContent = origTexts[i] || 'Generate Briefing'; });
        _briefingInProgress = false;
    };

    try {
        const body = lensId ? {lens_id: lensId} : {};
        const resp = await fetch(`/api/dossiers/${encodeURIComponent(companyName)}/briefing`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (data.ok) {
            _briefingInProgress = false;
            await loadCompanies();
            await openDossier(companyName);
        } else {
            showToast(data.error || 'Briefing generation failed', 'error', 8000);
            resetBtns();
        }
    } catch (e) {
        showToast('Error generating briefing: ' + e.message, 'error');
        resetBtns();
    }
}

// ========== LENS BUILDER MODAL ==========

function closeLensBuilder() {
    const overlay = document.querySelector('.lens-builder-overlay');
    if (overlay) {
        if (overlay._escHandler) document.removeEventListener('keydown', overlay._escHandler);
        overlay.remove();
    }
}

function openLensBuilder() {
    document.querySelectorAll('.lens-dropdown').forEach(d => d.remove());
    const existing = document.querySelector('.lens-builder-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'niche-builder-overlay lens-builder-overlay';
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeLensBuilder(); });

    overlay.innerHTML = `<div class="niche-builder-modal" style="max-width:520px">
        <div class="niche-builder-header">
            <h2>Create New Lens</h2>
            <button class="icp-wizard-close" onclick="closeLensBuilder()">&times;</button>
        </div>
        <div class="niche-builder-body" id="lens-builder-body">
            <div id="lens-builder-step1">
                <div class="icp-field">
                    <label>Lens Name</label>
                    <input type="text" id="lb-name" placeholder="e.g. CTV Ad Sales Readiness, Cloud Migration Fit">
                </div>
                <div class="icp-field">
                    <label>Description</label>
                    <textarea id="lb-description" rows="3" placeholder="Describe what this lens evaluates. What dimensions matter? What makes a company score high vs low?" style="width:100%;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);padding:8px;font-size:13px;resize:vertical"></textarea>
                </div>
                <div style="font-size:12px;color:var(--text-muted);margin-top:8px">The AI will generate scoring dimensions, weights, rubrics, and tier labels based on your description.</div>
            </div>
            <div id="lens-builder-step2" style="display:none">
                <div id="lb-config-preview"></div>
            </div>
        </div>
        <div class="niche-builder-footer" id="lens-builder-footer">
            <button class="briefing-btn" onclick="closeLensBuilder()">Cancel</button>
            <button class="briefing-btn briefing-btn-primary" id="lb-generate-btn" onclick="generateLensConfig()">Generate Lens</button>
        </div>
    </div>`;

    document.body.appendChild(overlay);
    const escHandler = (e) => { if (e.key === 'Escape') closeLensBuilder(); };
    document.addEventListener('keydown', escHandler);
    overlay._escHandler = escHandler;
    setTimeout(() => document.getElementById('lb-name')?.focus(), 100);
}

async function generateLensConfig() {
    const name = document.getElementById('lb-name')?.value.trim();
    const description = document.getElementById('lb-description')?.value.trim();
    if (!name || !description) { showToast('Please provide a name and description', 'error'); return; }

    const btn = document.getElementById('lb-generate-btn');
    btn.disabled = true;
    btn.textContent = 'Generating...';

    try {
        const resp = await fetch('/api/lenses/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, description}),
        });
        const data = await resp.json();
        if (!data.ok || !data.lens) {
            showToast(data.error || 'Failed to generate lens', 'error');
            btn.disabled = false; btn.textContent = 'Generate Lens';
            return;
        }

        const lens = data.lens;
        const config = lens.config;

        document.getElementById('lens-builder-step1').style.display = 'none';
        document.getElementById('lens-builder-step2').style.display = 'block';

        let previewHtml = `<div style="margin-bottom:12px"><strong style="color:var(--text-primary)">${escHtml(lens.name)}</strong> <span style="color:var(--text-muted);font-size:12px">(${escHtml(lens.slug)})</span></div>`;
        previewHtml += `<div style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">${escHtml(config.score_label || 'Score')}</div>`;

        previewHtml += `<div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:6px">Dimensions</div>`;
        (config.dimensions || []).forEach(d => {
            const wPct = Math.round((d.weight || 0) * 100);
            previewHtml += `<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:13px">
                <span style="color:var(--text-primary);min-width:140px">${escHtml(d.label)}</span>
                <div class="sub-score-bar" style="flex:1;height:6px"><div class="sub-score-fill" style="width:${wPct}%;background:var(--accent)"></div></div>
                <span style="color:var(--text-muted);font-size:12px;min-width:30px">${wPct}%</span>
            </div>`;
        });

        previewHtml += `<div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin-top:12px;margin-bottom:6px">Tier Labels</div>`;
        (config.labels || []).forEach(tier => {
            const cc = _scoreColorClass(tier.min_score);
            previewHtml += `<span class="score-${cc}" style="margin-right:8px;font-size:12px">&#9679; ${tier.min_score}+ ${escHtml(tier.label)}</span>`;
        });

        document.getElementById('lb-config-preview').innerHTML = previewHtml;
        document.getElementById('lens-builder-footer').innerHTML = `<button class="briefing-btn" onclick="closeLensBuilder()">Close</button>`;

        _cachedLenses = null;
        showToast(`Lens "${lens.name}" created successfully`, 'success');
    } catch (e) {
        showToast('Error generating lens: ' + e.message, 'error');
        btn.disabled = false; btn.textContent = 'Generate Lens';
    }
}

function showLegacyDossierDetail(d) {
    _activeDossierData = d;
    const rp = document.getElementById('right-pane');
    document.getElementById('right-company').textContent = d.company_name;
    document.getElementById('right-type').textContent = d.sector || 'Company Dossier';
    document.getElementById('right-date').textContent = `Updated ${d.updated_at || ''}`;
    currentReportFilename = null;

    let html = '';

    // Generate Briefing button
    html += `<div style="padding:12px;text-align:center;border-bottom:1px solid var(--border);margin-bottom:12px">
        <button class="briefing-btn briefing-btn-primary" onclick="generateBriefing('${escHtml(d.company_name)}')">Generate Intelligence Briefing</button>
        <div style="font-size:14px;color:var(--text-muted);margin-top:4px">Requires at least 2 analyses</div>
    </div>`;

    // Key facts section
    const allFacts = {};
    (d.analyses || []).forEach(a => {
        if (a.key_facts_json) {
            try {
                const facts = JSON.parse(a.key_facts_json);
                Object.assign(allFacts, facts);
            } catch {}
        }
    });

    if (Object.keys(allFacts).length) {
        html += '<div class="dossier-detail-section"><h3>Key Facts</h3><div class="fact-grid">';
        const display = ['revenue', 'market_cap', 'headcount', 'ceo', 'hq_location', 'founded',
                         'patent_count', 'sentiment_score', 'hiring_trend', 'sector'];
        display.forEach(k => {
            if (allFacts[k] !== undefined && allFacts[k] !== null) {
                const label = k.replace(/_/g, ' ');
                html += `<div class="fact-item"><div class="fact-label">${escHtml(label)}</div><div class="fact-value">${escHtml(String(allFacts[k]))}</div></div>`;
            }
        });
        html += '</div>';
        ['key_products', 'key_competitors', 'key_risks', 'top_patent_areas'].forEach(k => {
            if (Array.isArray(allFacts[k]) && allFacts[k].length) {
                const label = k.replace(/_/g, ' ');
                html += `<div style="margin-top:8px"><div class="fact-label">${escHtml(label)}</div><div class="fact-value">${allFacts[k].map(v => escHtml(String(v))).join(', ')}</div></div>`;
            }
        });
        html += '</div>';
    }

    // Recent changes detected between scans
    const changeEvents = (d.events || []).filter(e => e.event_type === 'change_detected');
    if (changeEvents.length) {
        html += `<div class="dossier-detail-section"><h3>Recent Changes (${changeEvents.length})</h3>`;
        changeEvents.forEach(evt => {
            let data = {};
            try { data = JSON.parse(evt.data_json || '{}'); } catch {}
            const field = data.field || '';
            const pct = data.pct_change;
            const changeType = data.change_type || '';
            let colorClass = 'change-neutral';
            if (changeType === 'increased') colorClass = 'change-positive';
            else if (changeType === 'decreased') colorClass = 'change-negative';
            else if (changeType === 'changed') {
                const newVal = String(data.new_value || '').toLowerCase();
                if (newVal === 'negative' || newVal === 'shrinking') colorClass = 'change-negative';
                else if (newVal === 'positive' || newVal === 'growing') colorClass = 'change-positive';
            }
            const source = (evt.description || '').replace('Detected during ', '').replace(' analysis', '');
            html += `<div class="change-row ${colorClass}">
                <span class="change-field">${escHtml(field.replace(/_/g, ' '))}</span>
                <span class="change-arrow">`;
            if (data.old_value !== undefined && data.old_value !== null && !data.items_added) {
                html += `<span class="change-old">${escHtml(String(data.old_value))}</span> <span style="color:var(--text-muted)">-></span> <span class="change-new">${escHtml(String(data.new_value))}</span>`;
            } else if (data.items_added && data.items_added.length) {
                html += `<span class="change-new">+${data.items_added.map(i => escHtml(i)).join(', ')}</span>`;
                if (data.items_removed && data.items_removed.length) {
                    html += ` <span class="change-old">-${data.items_removed.map(i => escHtml(i)).join(', ')}</span>`;
                }
            } else {
                html += `<span class="change-new">${escHtml(String(data.new_value || ''))}</span>`;
            }
            html += '</span>';
            if (pct !== undefined && pct !== null) {
                const pctClass = pct > 0 ? 'change-pct-up' : 'change-pct-down';
                html += ` <span class="change-pct ${pctClass}">${pct > 0 ? '+' : ''}${pct}%</span>`;
            }
            html += `<span class="change-source">${escHtml(source)} ${escHtml(evt.event_date || '')}</span>`;
            html += '</div>';
        });
        html += '</div>';
    }

    // Analysis history with staleness
    if (d.analyses && d.analyses.length) {
        html += '<div class="dossier-detail-section"><h3>Analysis History</h3>';
        const byType = {};
        d.analyses.forEach(a => {
            if (!byType[a.analysis_type]) byType[a.analysis_type] = [];
            byType[a.analysis_type].push(a);
        });
        const now = new Date();
        Object.entries(byType).forEach(([type, runs]) => {
            const latest = runs[0];
            const lastDate = new Date(latest.created_at);
            const days = Math.floor((now - lastDate) / (1000 * 60 * 60 * 24));
            let freshness = 'fresh', label = 'Fresh';
            if (days >= 90) { freshness = 'very-stale'; label = `${days}d ago`; }
            else if (days >= 30) { freshness = 'stale'; label = `${days}d ago`; }
            else if (days >= 7) { freshness = 'recent'; label = `${days}d ago`; }
            else { label = days === 0 ? 'Today' : `${days}d ago`; }
            html += `<div class="staleness-row">
                <span style="color:var(--text-primary);font-weight:500;min-width:80px">${escHtml(type)}</span>
                <span class="staleness-badge staleness-${freshness}">${label}</span>
                <span style="font-size:14px;color:var(--text-muted)">${runs.length} run${runs.length > 1 ? 's' : ''}</span>
                ${latest.report_file ? `<span style="font-size:12px;color:var(--accent);cursor:pointer" onclick="openReport('${escHtml(latest.report_file.replace(/^reports[\\/\\\\]/, ''))}')">View report</span>` : ''}
            </div>`;
        });
        html += '</div>';
    }

    // Lens scores (if any)
    html += _buildLensScoresSection(d);

    // Lens scoring now handled via pill bar in briefing view

    // Timeline events (non-change events)
    const otherEvents = (d.events || []).filter(e => e.event_type !== 'change_detected');
    if (otherEvents.length) {
        html += `<div class="dossier-detail-section"><h3>Timeline (${otherEvents.length} events)</h3>`;
        otherEvents.forEach(evt => {
            html += `<div class="timeline-event">
                <div class="timeline-date">${escHtml(evt.event_date || '')}</div>
                <div class="timeline-type">${escHtml(evt.event_type)}</div>
                <div>
                    <div class="timeline-title">${escHtml(evt.title)}</div>
                    ${evt.description ? `<div class="timeline-desc">${escHtml(evt.description)}</div>` : ''}
                </div>
            </div>`;
        });
        html += '</div>';
    }

    if (!html) {
        html = '<div style="padding:20px;text-align:center;color:var(--text-muted)">No data in this dossier yet. Run analyses to populate it.</div>';
    }

    document.getElementById('right-content').innerHTML = html;
    openRightPane();
}

// ===================== MESSAGES =====================
function getChatCol() {
    const c = document.getElementById('chat-messages');
    return c.querySelector('.chat-col') || c;
}

// Auto-scroll gating: disabled when user scrolls up, re-enabled on new message send
let _chatAutoScroll = true;
let _chatScrollProgrammatic = false;
(function() {
    const c = document.getElementById('chat-messages');
    if (!c) return;
    c.addEventListener('scroll', () => {
        if (_chatScrollProgrammatic) return;
        const nearBottom = c.scrollHeight - c.scrollTop - c.clientHeight < 120;
        _chatAutoScroll = nearBottom;
    });
})();
function _scrollChatBottom() {
    if (!_chatAutoScroll) return;
    const c = document.getElementById('chat-messages');
    if (!c) return;
    _chatScrollProgrammatic = true;
    c.scrollTop = c.scrollHeight;
    requestAnimationFrame(() => { _chatScrollProgrammatic = false; });
}

function renderMessages() {
    const chat = getActiveChat();
    const container = document.getElementById('chat-messages');
    const welcome = document.getElementById('welcome');

    if (!chat || !chat.messages.length) {
        welcome.style.display = 'flex';
        const msgs = container.querySelectorAll('.msg');
        msgs.forEach(m => m.remove());
        return;
    }

    welcome.style.display = 'none';

    // Remember which thinking/tool bubbles are expanded before re-render
    const expandedSet = new Set();
    container.querySelectorAll('.thinking-bubble.expanded').forEach(el => {
        const idx = el.getAttribute('data-msg-idx');
        if (idx) expandedSet.add('t' + idx);
    });
    container.querySelectorAll('.tool-call-bubble.expanded').forEach(el => {
        const idx = el.getAttribute('data-msg-idx');
        if (idx) expandedSet.add('c' + idx);
    });

    let html = '';
    let msgIdx = 0;
    let inToolGroup = false;
    const msgs = chat.messages;
    msgs.forEach((m, i) => {
        const isGroupable = m.role === 'tool_call' || m.role === 'thinking';
        // Open a tool-group wrapper when entering a run of tool/thinking messages
        if (isGroupable && !inToolGroup) {
            html += '<div class="tool-group">';
            inToolGroup = true;
        }
        // Close the wrapper when leaving a run
        if (!isGroupable && inToolGroup) {
            html += '</div>';
            inToolGroup = false;
        }

        if (m.role === 'user') {
            html += `<div class="msg msg-user"><div class="msg-bubble">${escHtml(m.content)}</div></div>`;
        } else if (m.role === 'assistant') {
            html += `<div class="msg msg-assistant"><div class="msg-bubble">${marked.parse(m.content || '')}</div></div>`;
        } else if (m.role === 'thinking') {
            const preview = (m.content || '').slice(0, 100) + (m.content.length > 100 ? '...' : '');
            const isExpanded = expandedSet.has('t' + msgIdx);
            html += `<div class="msg msg-thinking">
                <div class="thinking-bubble${isExpanded ? ' expanded' : ''}" data-msg-idx="${msgIdx}" onclick="if(!window.getSelection().toString())this.classList.toggle('expanded')">
                    <div class="thinking-label">Reasoning</div>
                    <div class="thinking-preview">${escHtml(preview)}</div>
                    <div class="thinking-content">${escHtml(m.content)}</div>
                </div>
            </div>`;
        } else if (m.role === 'tool_call') {
            const hasResult = !!m.result;
            const isExpanded = expandedSet.has('c' + msgIdx);
            const steps = m.steps || [];
            const isTreeTool = ['score_lens', 'score_prospect', 'full_analysis', 'financial_analysis',
                                'sentiment_analysis', 'techstack_analysis', 'competitor_analysis',
                                'patent_analysis', 'seo_audit', 'pricing_analysis'].includes(m.name);

            // For completed tree tools: compact bubble + "View Execution" button (opens fullscreen overlay)
            // For running tools or non-tree tools: flat step list as before
            let stepsHtml = '';
            if (!hasResult && steps.length) {
                // Still running — show live flat step list
                stepsHtml = `<div class="tool-progress-log">${steps.map(s => `<div class="tool-progress-step"><span class="tool-step-check">&#10003;</span> ${escHtml(cleanProgress(s))}</div>`).join('')}</div>`;
            } else if (hasResult && !isTreeTool && steps.length) {
                // Completed non-tree tool — flat list on expand
                stepsHtml = `<div class="tool-progress-log">${steps.map(s => `<div class="tool-progress-step"><span class="tool-step-check">&#10003;</span> ${escHtml(cleanProgress(s))}</div>`).join('')}</div>`;
            }
            // For completed tree tools: no inline stepsHtml — flowchart opens in overlay

            const statusHtml = hasResult
                ? `<div class="tool-call-status"><span class="tool-done-check">&#10003;</span> <span class="tool-status-text" style="color:var(--green)">Done${steps.length ? ` — ${steps.length} step${steps.length !== 1 ? 's' : ''}` : ''}</span></div>`
                : `<div class="tool-call-status"><div class="tool-spinner"></div> <span class="tool-status-text">Running ${escHtml(toolLabel(m.name))}...</span></div>`;

            const chevron = hasResult && !isTreeTool ? `<span class="tool-expand-chevron">&#9660;</span>` : '';

            // "View Execution" button for completed tree tools
            const execBtn = hasResult && isTreeTool && steps.length
                ? `<div class="report-link" onclick="event.stopPropagation();openExecOverlay(${msgIdx})" style="margin-top:4px">View Execution &rarr;</div>`
                : '';

            html += `<div class="msg msg-tool">
                <div class="tool-call-bubble${hasResult ? (isExpanded ? ' expanded' : '') : ' running'}" data-msg-idx="${msgIdx}" onclick="if(!window.getSelection().toString())this.classList.toggle('expanded')">
                    <div class="tool-call-header">
                        <div class="tool-call-icon">${toolIcon(m.name)}</div>
                        <span class="tool-call-name">${escHtml(toolLabel(m.name))}</span>
                        ${chevron}
                    </div>
                    <div class="tool-call-args">${escHtml(formatArgs(m.args))}</div>
                    ${statusHtml}
                    ${stepsHtml}
                    ${m.result ? `<div class="tool-result-content">${escHtml(m.result)}</div>` : ''}
                </div>
                ${execBtn}
                ${m.reportFile ? `<div class="report-link" onclick="openReport('${m.reportFile}')">View Report &rarr;</div>` : ''}
            </div>`;
        }
        msgIdx++;
    });
    if (inToolGroup) html += '</div>'; // close trailing tool-group

    // Keep welcome div hidden but in DOM, wrap everything in centered inner container
    container.innerHTML = `<div class="chat-col"><div id="welcome" class="welcome" style="display:none">
        <div class="welcome-title">Signal Vault</div>
        <div class="welcome-sub">Ask about any company.</div>
        <div class="quick-actions">
            <div class="quick-action" onclick="quickAction('full_analysis', 'Run a full analysis on ')">Full Analysis<span>Financial, competitors, patents, sentiment</span></div>
            <div class="quick-action" onclick="quickAction('compare', 'Compare ', ' and ')">Compare Companies<span>Side-by-side competitive analysis</span></div>
            <div class="quick-action" onclick="quickAction('landscape', 'Run a landscape analysis on ')">Landscape Analysis<span>Discover competitors automatically</span></div>
            <div class="quick-action" onclick="quickAction('freeform')">Ask Anything<span>Free-form research question</span></div>
        </div>
    </div>` + html + `</div>`;
    _scrollChatBottom();
}

// ===================== SEND MESSAGE =====================
async function sendMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;

    let chat = getActiveChat();
    if (!chat) { newChat(); chat = getActiveChat(); }

    // Resume prompt: if this is first message, context has a company, and a prior chat exists for that company
    const ctxCompany = getContextCompany();
    if (chat.messages.length === 0 && ctxCompany && !resumePromptShown) {
        const existing = findExistingCompanyChat(ctxCompany);
        if (existing) {
            resumePromptShown = true;
            const choice = await showResumePrompt(ctxCompany, existing);
            if (choice === 'resume') {
                // Switch to the existing chat and send the message there
                loadChat(existing.id);
                chat = getActiveChat();
            }
            // 'new' → continue in current empty chat
        }
    }

    // Clear input immediately
    input.value = '';
    autoResize(input);

    if (!chat.title) {
        chat.title = text.slice(0, 60);
        saveChats();
        renderChatList();
    }

    // Seed company from active context
    if (!chat.company && ctxCompany) {
        chat.company = ctxCompany;
        saveChats();
        renderChatList();
    }

    // Add user message to chat right away
    chat.messages.push({ role: 'user', content: text });
    saveChats();
    renderMessages();
    document.getElementById('welcome').style.display = 'none';

    if (sendingChats.has(chat.id)) {
        // This chat is already processing — queue it for re-processing
        messageQueue.push(chat.id);
        updateSendBtn();
        return;
    }

    await processChat(chat);
}

async function processChat(chat) {
    sendingChats.add(chat.id);
    updateSendBtn();

    // Typing indicator
    const container = document.getElementById('chat-messages');
    const col = getChatCol();
    const typingEl = document.createElement('div');
    typingEl.className = 'msg msg-assistant';
    typingEl.id = 'typing';
    typingEl.innerHTML = '<div class="msg-bubble"><div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div>';
    col.appendChild(typingEl);
    _chatAutoScroll = true; // user just sent — always scroll
    _scrollChatBottom();

    // API messages (only user + assistant)
    const apiMessages = chat.messages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ role: m.role, content: m.content }));

    // Build payload with optional company context
    const payload = { messages: apiMessages };
    const ctxCompany = activeContext ? activeContext.company : (chat.company || null);
    if (ctxCompany) {
        payload.context = { company: ctxCompany, type: activeContext ? activeContext.type : 'inferred' };
    }

    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

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
                    const event = JSON.parse(line.slice(6));
                    handleSSE(event, chat);
                } catch {}
            }
        }
    } catch (e) {
        console.error('[chat] Connection error:', e);
        chat.messages.push({ role: 'assistant', content: `Connection error: ${e.message || 'stream interrupted'}. The server may have restarted — you can ask me to continue where we left off.` });
    }

    // Kill any stale running tool calls — mark them as cancelled
    for (const m of chat.messages) {
        if (m.role === 'tool_call' && !m.result) {
            m.result = '(Interrupted — server disconnected before this tool completed)';
        }
    }

    const t = document.getElementById('typing');
    if (t) t.remove();

    saveChats();
    renderMessages();
    renderChatList();
    refreshSidebar();

    // Check if this chat has queued follow-up messages
    const idx = messageQueue.indexOf(chat.id);
    if (idx !== -1) {
        messageQueue.splice(idx, 1);
        updateSendBtn();
        await processChat(chat);
        return;
    }

    sendingChats.delete(chat.id);
    updateSendBtn();
}

function updateSendBtn() {
    const btn = document.getElementById('send-btn');
    btn.disabled = false;
    const chat = getActiveChat();
    const isSending = chat && sendingChats.has(chat.id);
    const queued = messageQueue.filter(id => id === (chat && chat.id)).length;
    if (isSending && queued > 0) {
        btn.textContent = `Sending... (${queued} queued)`;
    } else if (isSending) {
        btn.textContent = 'Sending...';
    } else {
        btn.textContent = 'Send';
    }
}

function handleSSE(event, chat) {
    if (event.type === 'thinking') {
        // Remove typing indicator
        const t = document.getElementById('typing');
        if (t) t.remove();
        chat.messages.push({ role: 'thinking', content: event.text });
        saveChats();
        renderMessages();
        // Re-add typing indicator — agent is still working
        {
            const container = document.getElementById('chat-messages');
            const typingEl = document.createElement('div');
            typingEl.className = 'msg msg-assistant';
            typingEl.id = 'typing';
            typingEl.innerHTML = '<div class="msg-bubble"><div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div>';
            getChatCol().appendChild(typingEl);
            _scrollChatBottom();
        }

    } else if (event.type === 'tool_call') {
        // Remove typing indicator — the tool call bubble with spinner replaces it
        const t = document.getElementById('typing');
        if (t) t.remove();
        chat.messages.push({ role: 'tool_call', name: event.name, args: event.args, result: null, reportFile: null, steps: [] });
        // Auto-detect company from tool args
        if (!chat.company && event.args) {
            const detected = event.args.company || event.args.company_name || event.args.company_a || null;
            if (detected) { chat.company = detected; }
        }
        saveChats();
        renderMessages();
        // Scroll chat to show new tool bubble
        _scrollChatBottom();

    } else if (event.type === 'tool_progress') {
        // Accumulate progress steps in the tool_call message data
        const isStructured = event.structured === true;
        const rawText = event.text || '';
        const cleaned = isStructured ? null : cleanProgress(rawText);
        for (let i = chat.messages.length - 1; i >= 0; i--) {
            if (chat.messages[i].role === 'tool_call' && !chat.messages[i].result) {
                if (!chat.messages[i].steps) chat.messages[i].steps = [];
                if (!chat.messages[i].structuredSteps) chat.messages[i].structuredSteps = [];
                if (isStructured) {
                    // Store structured event for tree rendering
                    chat.messages[i].structuredSteps.push({
                        event: event.event,
                        source: event.source,
                        label: event.label,
                        status: event.status,
                        summary: event.summary,
                        detail: event.detail,
                        company: event.company,
                        analysis_type: event.analysis_type,
                        path: event.path,
                        model: event.model,
                    });
                } else {
                    // Store RAW text (with [agent] prefix) for tree parsing,
                    // cleaned text is only used for live DOM display
                    const steps = chat.messages[i].steps;
                    if (!steps.length || steps[steps.length - 1] !== rawText) {
                        steps.push(rawText);
                    }
                }
                break;
            }
        }
        // Live-update the DOM: append step to the progress log
        const runningBubbles = document.querySelectorAll('.tool-call-bubble.running');
        const bubble = runningBubbles[runningBubbles.length - 1];
        if (bubble) {
            let log = bubble.querySelector('.tool-progress-log');
            if (!log) {
                log = document.createElement('div');
                log.className = 'tool-progress-log';
                const status = bubble.querySelector('.tool-call-status');
                if (status) status.after(log);
            }
            if (isStructured) {
                // Render structured event as a styled step
                const evType = event.event || '';
                const src = event.label || event.source || evType;
                const summary = event.summary || event.detail || '';
                const statusCls = event.status === 'done' ? 'color:var(--green)' : event.status === 'skipped' ? 'color:var(--yellow)' : event.status === 'error' ? 'color:var(--red)' : 'color:var(--purple)';
                const icon = event.status === 'done' ? '&#10003;' : event.status === 'skipped' ? '&#8212;' : event.status === 'error' ? '&#10007;' : '&#9654;';
                const step = document.createElement('div');
                step.className = 'tool-progress-step';
                step.innerHTML = `<span style="${statusCls};font-size:10px">${icon}</span> <strong style="font-size:10px">${escHtml(src)}</strong>${summary ? ` <span style="color:var(--text-muted);font-size:10px">${escHtml(summary)}</span>` : ''}`;
                log.appendChild(step);
                // Update spinner text
                const statusText = bubble.querySelector('.tool-status-text');
                if (statusText) statusText.textContent = `${src}${summary ? ' — ' + summary : ''}`;
            } else {
                const step = document.createElement('div');
                step.className = 'tool-progress-step';
                step.innerHTML = `<span class="tool-step-check">&#10003;</span> ${escHtml(cleaned)}`;
                log.appendChild(step);
                // Update the spinner status text to show current step
                const statusText = bubble.querySelector('.tool-status-text');
                if (statusText) statusText.textContent = cleaned;
            }
        }
        // Auto-scroll the progress log inside the running bubble (not the outer group)
        if (_chatAutoScroll) {
            const runningLog = document.querySelector('.tool-call-bubble.running .tool-progress-log');
            if (runningLog) runningLog.scrollTop = runningLog.scrollHeight;
        }
        _scrollChatBottom();

    } else if (event.type === 'tool_result') {
        for (let i = chat.messages.length - 1; i >= 0; i--) {
            if (chat.messages[i].role === 'tool_call' && chat.messages[i].name === event.name && !chat.messages[i].result) {
                chat.messages[i].result = event.result;
                const match = event.result.match(/saved to:\s*(?:reports[\/\\])?(.+\.md)/i);
                if (match) {
                    chat.messages[i].reportFile = match[1];
                    const reportName = match[1].replace(/\.md$/, '').replace(/_/g, ' ');
                    showToast(`<strong>${escHtml(reportName)}</strong> ready — <a href="#" onclick="event.preventDefault();openReport('${escHtml(match[1])}');this.closest('.toast').remove()" style="color:var(--accent);text-decoration:underline">View Report</a>`, 'success', 8000);
                }
                break;
            }
        }
        saveChats();
        renderMessages();
        // Re-add typing indicator — LLM is still processing the tool result
        {
            const container = document.getElementById('chat-messages');
            const typingEl = document.createElement('div');
            typingEl.className = 'msg msg-assistant';
            typingEl.id = 'typing';
            typingEl.innerHTML = '<div class="msg-bubble"><div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div>';
            getChatCol().appendChild(typingEl);
            _scrollChatBottom();
        }

    } else if (event.type === 'message') {
        const t = document.getElementById('typing');
        if (t) t.remove();
        if (event.text && event.text.trim()) {
            chat.messages.push({ role: 'assistant', content: event.text });
            saveChats();
            renderMessages();
        }

    } else if (event.type === 'error') {
        const t = document.getElementById('typing');
        if (t) t.remove();
        chat.messages.push({ role: 'assistant', content: 'Error: ' + event.text });
        saveChats();
        renderMessages();
    }
}

// ===================== QUICK ACTIONS =====================
function showPromptModal(label, defaultValue = '') {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'prompt-overlay';
        overlay.innerHTML = `
            <div class="prompt-modal">
                <div class="prompt-modal-title">${label}</div>
                <input class="prompt-modal-input" type="text" value="${escHtml(defaultValue)}" autofocus />
                <div class="prompt-modal-buttons">
                    <button class="prompt-modal-btn cancel">Cancel</button>
                    <button class="prompt-modal-btn confirm">OK</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        const inp = overlay.querySelector('.prompt-modal-input');
        const close = (val) => { overlay.remove(); resolve(val); };
        overlay.querySelector('.cancel').onclick = () => close(null);
        overlay.querySelector('.confirm').onclick = () => close(inp.value.trim() || null);
        inp.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') close(inp.value.trim() || null);
            if (e.key === 'Escape') close(null);
        });
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(null); });
        setTimeout(() => {
            inp.focus();
            if (defaultValue) inp.select();
        }, 50);
    });
}

async function quickAction(type, prefix, joiner) {
    const input = document.getElementById('chat-input');
    if (type === 'freeform') { input.focus(); return; }
    if (type === 'compare') {
        const a = await showPromptModal('First company:');
        if (!a) return;
        const b = await showPromptModal('Second company:');
        if (!b) return;
        input.value = `${prefix}${a}${joiner}${b}`;
    } else {
        const name = await showPromptModal('Company name:');
        if (!name) return;
        input.value = `${prefix}${name}`;
    }
    sendMessage();
}

// ===================== RIGHT PANE =====================
// Renders a report into a target container. Returns { company, type, date } or null.
async function _renderReportInto(filename, targetEl) {
    const resp = await fetch(`/api/reports/${encodeURIComponent(filename)}/content`);
    if (!resp.ok) { console.error('Report API error:', resp.status, filename); return null; }
    const data = await resp.json();

    let parsedHtml = '';
    try {
        parsedHtml = marked.parse(data.content || '');
    } catch (parseErr) {
        console.error('Markdown parse error:', parseErr);
        parsedHtml = '<pre style="white-space:pre-wrap;color:var(--text-secondary)">' + escHtml(data.content || '') + '</pre>';
    }

    targetEl.innerHTML = parsedHtml;
    targetEl.parentElement.scrollTop = 0;

    // Intercept clicks on report file links
    targetEl.querySelectorAll('a').forEach(link => {
        const href = link.getAttribute('href') || '';
        if (href.match(/reports[\\\/].+\.md$/)) {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const fn = href.replace(/^reports[\\\/]/, '');
                openReport(fn);
            });
            link.style.cursor = 'pointer';
        }
    });

    return { company: data.company || '', type: data.type || '', date: data.date || '' };
}

async function openReport(filename) {
    try {
        // If split view is active, load into focused panel
        if (_splitActive) {
            await _loadIntoSplitPanel(_splitFocusedSide, 'report', filename);
            renderCompanyList();
            return;
        }

        const contentEl = document.getElementById('right-content');
        const meta = await _renderReportInto(filename, contentEl);
        if (!meta) return;

        currentReportFilename = filename;
        activeDossierName = null;
        _activeBriefingData = null;
        _activeDossierData = null;

        // Track active company for sidebar highlighting
        const ownerCompany = allCompanies.find(c =>
            (c.analyses || []).some(a => a.report_file === filename) ||
            (c.orphan_reports || []).includes(filename)
        );
        if (ownerCompany) openCompanies.add(ownerCompany.name);

        // Add breadcrumb if company is known
        const typeLabel = displayReportType(meta.type);
        if (meta.company) {
            const breadcrumbHtml = `<div class="report-breadcrumb">
                <span class="breadcrumb-company" onclick="openDossier('${escHtml(meta.company)}')">${escHtml(meta.company)}</span>
                <span class="breadcrumb-sep">›</span>
                <span class="breadcrumb-current">${escHtml(typeLabel !== 'report' ? typeLabel + ' report' : 'report')}</span>
            </div>`;
            contentEl.innerHTML = breadcrumbHtml + contentEl.innerHTML;
        }

        // Set header
        document.getElementById('right-company').textContent = meta.company;
        document.getElementById('right-type').textContent = typeLabel;
        document.getElementById('right-date').textContent = meta.date;

        openRightPane();
        setContext(meta.company, 'report', (typeLabel || 'report') + ' report');
        renderCompanyList();

        // If in expanded/focus mode, rebuild card grid for this report
        const rp = document.getElementById('right-pane');
        if (rp.classList.contains('expanded')) {
            _buildCardGrid(rp);
        }
    } catch (e) {
        console.error('Failed to load report:', e);
    }
}

function openRightPane() {
    const rp = document.getElementById('right-pane');
    // Don't reset width if in expanded/focus mode
    if (!rp.classList.contains('expanded')) {
        if (savedRightWidth) {
            rp.style.width = savedRightWidth + 'px';
            rp.style.minWidth = savedRightWidth + 'px';
        } else {
            rp.style.width = '';
            rp.style.minWidth = '';
        }
    }
    rp.classList.add('open');
}

function closeRightPane() {
    const rp = document.getElementById('right-pane');
    if (_splitActive) {
        _wasExpandedBeforeSplit = false; // don't restore expanded on close
        _exitSplitView();
    }
    if (rp.classList.contains('expanded')) collapseReport();
    rp.classList.remove('open');
    rp.style.width = '';
    rp.style.minWidth = '';
    currentReportFilename = null;
    activeDossierName = null;
    _activeBriefingData = null;
    _activeDossierData = null;
    openCompanies.clear();
    clearContextFull();
    renderCompanyList();
}

// --- Expand / Focus Mode ---
let _originalReportHTML = null;

// Sections with tables or source lists should span full width
const WIDE_KEYWORDS = ['profile', 'comparison', 'side-by-side', 'head-to-head', 'source', 'individual report'];

function _sectionIsWide(heading, content) {
    const h = heading.toLowerCase();
    if (WIDE_KEYWORDS.some(kw => h.includes(kw))) return true;
    if (content.querySelector('table')) return true;
    return false;
}

function _buildCardGrid(container) {
    const content = container.querySelector('#right-content');
    if (!content) return;

    // Save original HTML for restore
    _originalReportHTML = content.innerHTML;

    // If we have briefing data, build a proper dashboard
    if (_activeBriefingData) {
        _buildBriefingDashboard(content);
        return;
    }

    // --- Markdown report: split by H2 ---
    const children = Array.from(content.children);
    if (!children.length) return;

    const sections = [];
    let current = null;

    for (const el of children) {
        if (el.tagName === 'H2') {
            if (current) sections.push(current);
            current = { heading: el.textContent, elements: [el] };
        } else if (el.tagName === 'H1') {
            if (current) sections.push(current);
            current = null;
            if (!sections.length) {
                sections.push({ heading: '__intro__', elements: [el] });
            }
        } else if (el.tagName === 'HR') {
            continue;
        } else {
            if (current) {
                current.elements.push(el);
            } else {
                if (sections.length && sections[0].heading === '__intro__') {
                    sections[0].elements.push(el);
                } else {
                    sections.unshift({ heading: '__intro__', elements: [el] });
                }
            }
        }
    }
    if (current) sections.push(current);

    if (sections.filter(s => s.heading !== '__intro__').length < 2) return;

    const grid = document.createElement('div');
    grid.className = 'report-grid';

    for (const section of sections) {
        if (section.heading === '__intro__') continue;

        const card = document.createElement('div');
        card.className = 'report-card';

        const tempDiv = document.createElement('div');
        section.elements.forEach(el => tempDiv.appendChild(el.cloneNode(true)));

        if (_sectionIsWide(section.heading, tempDiv)) {
            card.classList.add('card-wide');
        }

        section.elements.forEach(el => card.appendChild(el.cloneNode(true)));
        grid.appendChild(card);
    }

    content.innerHTML = '';
    const intro = sections.find(s => s.heading === '__intro__');
    if (intro) {
        intro.elements.forEach(el => content.appendChild(el.cloneNode(true)));
    }
    content.appendChild(grid);
}

function _dashCard(title, bodyHtml, wide) {
    return `<div class="dash-card${wide ? ' card-wide' : ''}">
        <div class="dash-card-title">${escHtml(title)}</div>
        ${bodyHtml}
    </div>`;
}

function _buildBriefingDashboard(content) {
    const b = _activeBriefingData;
    const dossier = _activeDossierData;
    if (!b) return;

    const identity = b.subject_identity || {};
    const briefingScoring = b.scoring || b.digital_maturity || {};
    const isLensOverride = !!_activeDashboardLens;
    const activeScoring = isLensOverride ? _enrichScoringFromLensData(_activeDashboardLens) : briefingScoring;
    const score = activeScoring.overall_score || 0;
    const label = activeScoring.overall_label || '';
    const subs = activeScoring.sub_scores || {};
    const conf = b.data_confidence || {};
    const lensInfo = activeScoring._lens || {};
    const scoringLabel = lensInfo.score_label || (isLensOverride ? (_activeDashboardLens.lens_name || 'Lens Score') : 'Digital Maturity Score');
    const dims = activeScoring._dimensions || [
        {key:'tech_modernity', label:'Tech Modernity', weight:0.30},
        {key:'data_analytics', label:'Data & Analytics', weight:0.25},
        {key:'ai_readiness', label:'AI Readiness', weight:0.25},
        {key:'organizational_readiness', label:'Org Readiness', weight:0.20},
    ];
    const lensLabels = activeScoring._lens_labels || [
        {min_score:80, label:'Digital Vanguard'},
        {min_score:60, label:'Digital Contender'},
        {min_score:40, label:'Digitally Exposed'},
        {min_score:20, label:'Digital Laggard'},
        {min_score:0, label:'Digital Liability'},
    ];

    let html = '';

    // --- Lens pill bar (same as normal view) ---
    const briefingLensId = (briefingScoring._lens || {}).id;
    const lensScores = dossier.lens_scores || [];
    const allLenses = _cachedLenses || [];
    const scoredMap = {};
    lensScores.forEach(ls => { scoredMap[ls.lens_id] = ls; });

    html += `<div id="dash-lens-pill-bar" class="lens-bar" style="margin-bottom:12px;padding:0 16px">`;
    // Briefing's own lens pill
    const bPillScore = briefingScoring.overall_score || 0;
    const bPillCC = _scoreColorClass(bPillScore);
    const bPillName = (briefingScoring._lens || {}).name || 'Briefing Score';
    html += `<div class="lens-pill${!isLensOverride ? ' active' : ''}" onclick="handleDashLensPillClick(null, true)">
        <span class="lens-pill-score score-${bPillCC}">${bPillScore}</span>
        <span class="lens-pill-name">${escHtml(bPillName)}</span>
        <span style="font-size:9px;color:var(--green);margin-left:4px">Full</span>
    </div>`;
    // Other lenses — scored or unscored
    allLenses.forEach(lens => {
        if (lens.id === briefingLensId) return;
        const scored = scoredMap[lens.id];
        const isActive = isLensOverride && _activeDashboardLens && _activeDashboardLens.lens_id === lens.id;
        if (scored) {
            const lsScore = scored.overall_score || 0;
            const lcc = _scoreColorClass(lsScore);
            html += `<div class="lens-pill${isActive ? ' active' : ''}" onclick="handleDashLensPillClick(${lens.id}, false)">
                <span class="lens-pill-score score-${lcc}">${lsScore}</span>
                <span class="lens-pill-name">${escHtml(lens.name)}</span>
            </div>`;
        } else {
            html += `<div class="lens-pill lens-pill-unscored" onclick="handleDashLensPillClick(${lens.id}, false)">
                <span class="lens-pill-score" style="color:var(--text-muted)">--</span>
                <span class="lens-pill-name">${escHtml(lens.name)}</span>
            </div>`;
        }
    });
    html += `<div class="lens-pill" style="border-style:dashed;color:var(--accent);font-size:11px" onclick="openLensBuilder()">+ New Lens</div>`;
    html += `</div>`;

    // Lens overlay disclaimer when viewing non-briefing lens
    if (isLensOverride) {
        html += `<div style="font-size:11px;color:var(--text-muted);text-align:center;margin-bottom:8px;font-style:italic">Scoring overlay — briefing content reflects a different lens</div>`;
    }

    // --- Hero strip: identity | donut | sub-scores ---
    let metaParts = [];
    if (identity.hq_location) metaParts.push(identity.hq_location);
    if (identity.founded) metaParts.push('Est. ' + identity.founded);
    if (identity.headcount) metaParts.push(identity.headcount + ' employees');

    let barsHtml = '';
    dims.forEach(d => {
        const sub = subs[d.key] || {};
        barsHtml += renderSubScore(d.label, sub.score || 0, sub);
    });

    let confLine = '';
    if (conf.overall_confidence) confLine += conf.overall_confidence.toUpperCase();
    if (conf.jobs_analyzed) confLine += ` · ${conf.jobs_analyzed} roles`;
    const avail = conf.analyses_available || [];
    if (avail.length) confLine += ` · ${avail.length} analyses`;

    // Build rationale HTML for the right half of the hero row
    let rationaleHtml = '';
    dims.forEach(d => {
        const sub = subs[d.key] || {};
        if (sub.rationale) {
            const sources = _extractSources(sub.rationale);
            const badges = sources.map(s =>
                _renderSourceBadge(s)
            ).join(' ');
            rationaleHtml += `<div class="dash-rationale-entry"><div class="dash-rationale-label">${escHtml(d.label)}</div><div class="dash-rationale-text" onclick="this.classList.toggle('expanded')" title="Click to expand">${_stripCitations(sub.rationale)}</div>${badges ? `<div style="margin-top:4px">${badges}</div>` : ''}</div>`;
        }
    });

    // Build dynamic tooltip
    let tooltipDims = '';
    dims.forEach(d => {
        const wPct = Math.round((d.weight || 0) * 100);
        tooltipDims += `<div><strong>${escHtml(d.label)} (${wPct}%)</strong></div>`;
    });
    let tooltipTiers = '';
    lensLabels.forEach(tier => {
        const cc = _scoreColorClass(tier.min_score);
        tooltipTiers += `<span class="score-${cc}">&#9679;</span> ${tier.min_score}+ ${escHtml(tier.label)} &nbsp;`;
    });

    html += `<div class="dash-hero-row">
        <div class="dash-hero-left">
            <div class="dash-hero-identity">
                <div class="dash-hero-company">${escHtml(identity.name || dossier.company_name)}</div>
                ${identity.sector ? `<div class="dash-hero-sector">${escHtml(identity.sector)}</div>` : ''}
                <div class="dash-hero-detail">${escHtml(metaParts.join(' · '))}</div>
                <div class="dash-hero-timestamp" style="font-size: 11px; color: var(--text-muted); margin-top: 4px; font-style: italic;">
                    Last Refreshed: ${(() => {
                        if (!dossier.briefing_generated_at) return 'Never';
                        let ds = dossier.briefing_generated_at;
                        if (!ds.includes('T') && ds.includes(' ')) ds = ds.replace(' ', 'T');
                        const d = new Date(ds);
                        return isNaN(d.getTime()) ? 'Never' : d.toLocaleString();
                    })()}
                </div>
                <button class="dash-refresh-btn" onclick="event.stopPropagation();generateBriefing('${escHtml(dossier.company_name)}')">&#x21bb; Refresh Briefing</button>
            </div>
            <div class="dash-hero-score">
                ${renderScoreRing(score, 100)}
                <div class="score-tooltip-wrap"><div class="dash-hero-label score-${_scoreColorClass(score)}">${escHtml(label)} <span class="score-info-icon" onclick="event.stopPropagation();toggleScoreTooltip(this)">&#9432;</span></div>
                <div class="score-tooltip" style="display:none">
                    <div class="score-tooltip-title">${escHtml(scoringLabel)}</div>
                    <div class="score-tooltip-body">
                        Scores this company across weighted dimensions:
                        <div class="score-tooltip-dims">${tooltipDims}</div>
                        <div class="score-tooltip-tiers">${tooltipTiers}</div>
                    </div>
                </div></div>
                ${confLine ? `<div class="dash-hero-meta">${escHtml(confLine)}</div>` : ''}
            </div>
            <div class="dash-hero-bars">${barsHtml}</div>
        </div>
        <div class="dash-hero-right">
            <div class="dash-hero-right-title">Score Rationale</div>
            ${rationaleHtml}
        </div>
    </div>`;

    // --- Consulting Opportunities (right after hero, before card grid) ---
    const lensSD = isLensOverride ? (_activeDashboardLens.score_data || {}) : null;
    const opps = isLensOverride ? (lensSD.engagement_opportunities || []) : (b.engagement_opportunities || []);
    if (opps.length) {
        let oppHtml = '<div class="opp-inner-grid">';
        opps.forEach(opp => {
            const pClass = `opp-priority-${opp.priority || 'medium'}`;
            const explicitSources = opp.source_analyses || [];
            const inlineSources = _extractSources((opp.evidence || '') + ' ' + (opp.detail || ''));
            const allSources = [...new Set([...explicitSources, ...inlineSources])];
            const sourceBadges = allSources.map(s =>
                _renderSourceBadge(s)
            ).join(' ');
            oppHtml += `<div class="opp-card" onclick="this.classList.toggle('expanded')">
                <div class="opp-card-header"><span class="opp-service">${escHtml(opp.service || '')}</span><span class="opp-priority ${pClass}">${escHtml(opp.priority || '')}</span></div>
                <div class="opp-evidence">${_renderCitedText(opp.evidence || '')}</div>
                <div class="opp-meta"><span>${escHtml(opp.estimated_scope || '')}</span></div>
                ${opp.why_now ? `<div class="opp-why-now">${_renderCitedText(opp.why_now)}</div>` : ''}
                <div class="opp-detail">
                    ${opp.detail ? `<div class="opp-detail-text">${_renderCitedText(opp.detail)}</div>` : ''}
                    ${allSources.length ? `<div class="opp-source-links"><span style="font-size:14px;color:var(--text-muted);margin-right:2px">Sources:</span>${sourceBadges}</div>` : ''}
                </div>
            </div>`;
        });
        oppHtml += '</div>';
        const oppTitle = `Consulting Opportunities <span class="score-info-icon" onclick="event.stopPropagation();toggleMethodologyTip('dash-scope-methodology')">&#9432;</span>
            <div class="methodology-tip" id="dash-scope-methodology" style="display:none">
                <div class="methodology-tip-title">Scope Estimation Methodology</div>
                Estimates based on typical Big 4 / MBB engagement structures (blended daily rate ~$3-5K/consultant):
                <div class="methodology-tip-row"><strong>$500K-1M, 3-6 mo</strong> — Small team (2-3). Assessments, strategy design, POC, governance frameworks.</div>
                <div class="methodology-tip-row"><strong>$1-3M, 6-12 mo</strong> — Medium team (4-6). Platform implementation, org redesign, single workstream.</div>
                <div class="methodology-tip-row"><strong>$2-5M, 9-18 mo</strong> — Large team (6-10). Multi-workstream programs, enterprise rollout. $10B+ revenue companies.</div>
                <div class="methodology-tip-row"><strong>$5M+, 12-24 mo</strong> — Full transformation (10+). Company-wide digital transformation. $50B+ companies only.</div>
                <div class="methodology-tip-note">Scaled to company size using revenue, headcount, and hiring velocity. Conservative estimates preferred.</div>
            </div>`;
        html += `<div class="dash-card" style="margin-bottom:16px">
            <div class="dash-card-title">${oppTitle}</div>
            ${oppHtml}
        </div>`;
    } else if (isLensOverride) {
        const rescoreLensId = _activeDashboardLens.lens_id || '';
        const rescoreCompany = escHtml((dossier || {}).company_name || '');
        html += `<div class="dash-card" style="margin-bottom:16px">
            <div class="dash-card-title">Consulting Opportunities</div>
            <div style="padding:16px;text-align:center;color:var(--text-muted);font-size:13px">
                Opportunities not available for this lens score version.
                <span style="color:var(--accent);cursor:pointer" onclick="_scoreLensViaDashPill('${rescoreCompany}', ${rescoreLensId})">Rescore to generate.</span>
            </div>
        </div>`;
    }

    // --- Card grid ---
    let cards = '';

    // Hiring Trajectory
    const traj = b.hiring_trajectory;
    if (traj && traj.trend) {
        let trajHtml = '';
        if (traj.velocity) {
            const trendUp = ['accelerating','growing'].includes(traj.trend);
            const trendDown = ['decelerating','shrinking'].includes(traj.trend);
            const arrowClass = trendUp ? 'trajectory-up' : trendDown ? 'trajectory-down' : 'trajectory-stable';
            const arrow = trendUp ? '&#9650;' : trendDown ? '&#9660;' : '&#8226;';
            trajHtml += `<div class="trajectory-row"><span class="trajectory-arrow ${arrowClass}">${arrow}</span><span style="color:var(--text-primary);font-weight:600">${escHtml(traj.velocity)}</span> <span style="color:var(--text-muted)">· ${escHtml(traj.trend)}</span></div>`;
        }
        if (traj.department_shifts && traj.department_shifts.length) {
            traj.department_shifts.forEach(shift => {
                const arrow = shift.direction === 'up' ? '↑' : shift.direction === 'down' ? '↓' : '→';
                const arrowClass = shift.direction === 'up' ? 'trajectory-up' : shift.direction === 'down' ? 'trajectory-down' : 'trajectory-stable';
                trajHtml += `<div class="trajectory-row"><span class="trajectory-arrow ${arrowClass}">${arrow}</span><span style="color:var(--text-secondary);font-size:14px">${escHtml(shift.department || '')}</span> <span style="color:var(--text-muted);font-size:11px">${escHtml(shift.detail || '')}</span></div>`;
            });
        }
        if (traj.interpretation) trajHtml += `<div style="font-size:14px;color:var(--text-muted);margin-top:6px;line-height:1.5">${_renderCitedText(traj.interpretation)}</div>`;
        cards += _dashCard('Hiring Trajectory', trajHtml, false);
    }

    // Budget & Appetite
    const budget = b.budget_signals || {};
    if (Object.keys(budget).length) {
        let bHtml = '';
        const confClass = `confidence-${budget.confidence || 'medium'}`;
        bHtml += `<div class="budget-row"><span class="budget-label">Can Afford</span><span class="budget-value">${budget.can_afford ? 'Yes' : 'Unlikely'}</span> <span class="confidence-badge ${confClass}">${escHtml(budget.confidence || '')} conf.</span></div>`;
        if (budget.revenue_trend) bHtml += `<div class="budget-row"><span class="budget-label">Revenue</span><span class="budget-value">${_renderCitedText(budget.revenue_trend)}</span></div>`;
        if (budget.hiring_trend) bHtml += `<div class="budget-row"><span class="budget-label">Hiring</span><span class="budget-value">${_renderCitedText(budget.hiring_trend)}</span></div>`;
        if (budget.investment_areas && budget.investment_areas.length) bHtml += `<div class="budget-row"><span class="budget-label">Investing In</span><span class="budget-value">${budget.investment_areas.map(a => _renderCitedText(a)).join(', ')}</span></div>`;
        if (budget.evidence) bHtml += `<div style="font-size:15px;color:var(--text-muted);margin-top:6px">${_renderCitedText(budget.evidence)}</div>`;
        cards += _dashCard('Budget & Appetite', bHtml, false);
    }

    // Competitive Pressure
    const comp = b.competitive_pressure || {};
    if (Object.keys(comp).length) {
        let cHtml = '';
        if (comp.urgency) {
            const urgClass = comp.urgency === 'high' ? 'confidence-high' : comp.urgency === 'medium' ? 'confidence-medium' : 'confidence-low';
            cHtml += `<div style="margin-bottom:6px">Urgency: <span class="confidence-badge ${urgClass}">${escHtml(comp.urgency)}</span></div>`;
        }
        if ((comp.competitors || []).length) {
            cHtml += `<div class="competitor-header"><span>Competitor</span><span>Digital Maturity</span><span>Threat Assessment</span></div>`;
        }
        (comp.competitors || []).forEach(c => {
            cHtml += `<div class="competitor-row"><span class="competitor-name">${escHtml(c.name || '')}</span><span class="competitor-maturity">${_renderCitedText(c.digital_maturity_estimate || '')}</span><span class="competitor-threat">${_renderCitedText(c.threat || '')}</span></div>`;
        });
        cards += _dashCard('Competitive Pressure', cHtml, false);
    }

    // Financial Position
    const fin = b.financial_position || {};
    if (Object.keys(fin).length) {
        let fHtml = '';
        if (fin.metrics && fin.metrics.length) {
            fHtml += '<div class="metric-grid">';
            fin.metrics.forEach(m => {
                fHtml += `<div class="metric-card"><div class="metric-card-label">${escHtml(m.label || '')}</div><div class="metric-card-value">${_renderCitedText(m.value || '')}</div></div>`;
            });
            fHtml += '</div>';
        }
        if (fin.summary) fHtml += `<div style="font-size:14px;color:var(--text-muted);margin-top:8px;line-height:1.5">${_renderCitedText(fin.summary)}</div>`;
        cards += _dashCard('Financial Position', fHtml, false);
    }

    // Innovation & IP
    const ip = b.innovation_ip || {};
    if (Object.keys(ip).length) {
        let ipHtml = '';
        if (ip.patent_count !== undefined) {
            const pd = ip.patent_count === -1 ? 'N/A' : ip.patent_count;
            ipHtml += `<div class="budget-row"><span class="budget-label">Patents</span><span class="budget-value">${pd}</span></div>`;
        }
        if (ip.rd_intensity) ipHtml += `<div class="budget-row"><span class="budget-label">R&D</span><span class="budget-value">${escHtml(ip.rd_intensity)}</span></div>`;
        if (ip.top_areas && ip.top_areas.length) ipHtml += `<div class="budget-row"><span class="budget-label">Focus</span><span class="budget-value">${ip.top_areas.map(a => _renderCitedText(a)).join(', ')}</span></div>`;
        if (ip.assessment) ipHtml += `<div style="font-size:15px;color:var(--text-muted);margin-top:6px;line-height:1.5">${_renderCitedText(ip.assessment)}</div>`;
        cards += _dashCard('Innovation & IP', ipHtml, false);
    }

    // Talent & Culture
    const talent = b.talent_culture || {};
    if (Object.keys(talent).length) {
        let tHtml = '';
        if (talent.sentiment) tHtml += `<div class="budget-row"><span class="budget-label">Sentiment</span><span class="budget-value">${escHtml(talent.sentiment)}</span></div>`;
        const deptFocus = talent.department_focus || {};
        if (Object.keys(deptFocus).length) {
            const sorted = Object.entries(deptFocus).sort((a, b) => b[1] - a[1]);
            sorted.forEach(([dept, raw]) => {
                const pct = String(raw).replace('%', '');
                tHtml += `<div class="sub-score-row"><span class="sub-score-label">${escHtml(dept)}</span><div class="sub-score-bar"><div class="sub-score-fill" style="width:${pct}%;background:var(--accent)"></div></div><span class="sub-score-value" style="color:var(--text-secondary)">${pct}%</span></div>`;
            });
        }
        if (talent.top_skills && talent.top_skills.length) tHtml += `<div class="skill-tags" style="margin-top:6px">${talent.top_skills.map(s => `<span class="skill-tag">${escHtml(s)}</span>`).join('')}</div>`;
        if (talent.assessment) tHtml += `<div style="font-size:14px;color:var(--text-muted);margin-top:8px;line-height:1.5">${_renderCitedText(talent.assessment)}</div>`;
        cards += _dashCard('Talent & Culture', tHtml, false);
    }

    // Risk Profile (wide with 2-col inner grid)
    const risks = isLensOverride ? (lensSD.risk_profile || []) : (b.risk_profile || []);
    if (risks.length) {
        let rHtml = '<div class="risk-inner-grid">';
        risks.forEach(r => {
            const sev = r.severity || 'medium';
            rHtml += `<div class="risk-card risk-${sev}"><div class="risk-category">${escHtml(r.category || '')} - ${escHtml(sev)}</div><div class="risk-desc">${_renderCitedText(r.description || '')}</div></div>`;
        });
        rHtml += '</div>';
        cards += _dashCard('Risk Profile', rHtml, true);
    }

    // Strategic Assessment (wide, paragraph blocks matching report view)
    const stratText = isLensOverride ? (lensSD.strategic_assessment || '') : (b.strategic_assessment || '');
    if (stratText) {
        // Split on double newlines, or fall back to sentence groups if no double newlines
        let paras = stratText.split(/\n\s*\n/).filter(p => p.trim());
        if (paras.length <= 1) {
            // No double newlines — split on single newlines
            paras = stratText.split(/\n/).filter(p => p.trim());
        }
        if (paras.length <= 1) {
            // Still one block — split into ~4 chunks by sentences
            const sentences = stratText.split(/(?<=[.!?])\s+/).filter(s => s.trim());
            const chunkSize = Math.ceil(sentences.length / 4);
            paras = [];
            for (let i = 0; i < sentences.length; i += chunkSize) {
                paras.push(sentences.slice(i, i + chunkSize).join(' '));
            }
        }
        const stratHtml = paras.map(p => `<p style="font-size:15px;color:var(--text-secondary);line-height:1.7;margin:0 0 14px 0">${_renderCitedText(p.trim())}</p>`).join('');
        cards += _dashCard('Strategic Assessment', stratHtml, true);
    }

    // Data Confidence
    if (conf && (conf.caveats && conf.caveats.length || conf.analyses_missing && conf.analyses_missing.length)) {
        let dcHtml = '';
        if (conf.overall_confidence) {
            const confClass = `confidence-${conf.overall_confidence}`;
            dcHtml += `<div class="budget-row"><span class="budget-label">Confidence</span><span class="confidence-badge ${confClass}">${escHtml(conf.overall_confidence.toUpperCase())}</span></div>`;
        }
        if (conf.scrape_coverage) dcHtml += `<div class="budget-row"><span class="budget-label">Scrape Coverage</span><span class="budget-value">${escHtml(conf.scrape_coverage)}</span></div>`;
        if (conf.jobs_analyzed) dcHtml += `<div class="budget-row"><span class="budget-label">Jobs Analyzed</span><span class="budget-value">${conf.jobs_analyzed}</span></div>`;
        if (conf.analyses_available && conf.analyses_available.length) {
            dcHtml += `<div class="budget-row"><span class="budget-label">Completed</span><span class="budget-value">${conf.analyses_available.map(a => `<span class="source-badge source-${a}" title="${a} analysis">${a}</span>`).join(' ')}</span></div>`;
        }
        if (conf.analyses_missing && conf.analyses_missing.length) {
            dcHtml += `<div class="budget-row"><span class="budget-label">Missing</span><span class="budget-value" style="color:var(--text-muted)">${conf.analyses_missing.join(', ')}</span></div>`;
        }
        if (conf.caveats && conf.caveats.length) {
            dcHtml += `<div style="margin-top:8px;font-size:15px;color:var(--text-muted)">`;
            conf.caveats.forEach(c => { dcHtml += `<div style="margin-bottom:3px">⚠ ${escHtml(c)}</div>`; });
            dcHtml += `</div>`;
        }
        cards += _dashCard('Data Confidence', dcHtml, false);
    }

    // Source Reports
    if (dossier && dossier.analyses && dossier.analyses.length) {
        let srcHtml = '';
        const byType = {};
        dossier.analyses.forEach(a => {
            if (!byType[a.analysis_type]) byType[a.analysis_type] = [];
            byType[a.analysis_type].push(a);
        });
        const now = new Date();
        Object.entries(byType).forEach(([type, runs]) => {
            const latest = runs[0];
            const lastDate = new Date(latest.created_at);
            const days = Math.floor((now - lastDate) / (1000 * 60 * 60 * 24));
            let freshness = 'fresh', flabel = 'Fresh';
            if (days >= 90) { freshness = 'very-stale'; flabel = `${days}d ago`; }
            else if (days >= 30) { freshness = 'stale'; flabel = `${days}d ago`; }
            else if (days >= 7) { freshness = 'recent'; flabel = `${days}d ago`; }
            else { flabel = days === 0 ? 'Today' : `${days}d ago`; }
            srcHtml += `<div class="staleness-row" data-source-type="${escHtml(type)}">
                <span style="color:var(--text-primary);font-weight:500;min-width:80px">${escHtml(type)}</span>
                <span class="staleness-badge staleness-${freshness}">${flabel}</span>
                <span style="font-size:14px;color:var(--text-muted)">${runs.length} run${runs.length > 1 ? 's' : ''}</span>
                ${latest.report_file ? `<span style="font-size:12px;color:var(--accent);cursor:pointer" onclick="openReport('${escHtml(latest.report_file.replace(/^reports[\\/\\\\]/, ''))}')">View report</span>` : ''}
            </div>`;
        });
        cards += _dashCard('Source Reports', srcHtml, false);
    }

    html += `<div class="dash-grid">${cards}</div>`;
    content.innerHTML = html;

    /* Equalize card heights per row — if a card's content is less than
       half the tallest card in its row, let it keep its natural height
       instead of stretching to match. */
    requestAnimationFrame(() => {
        const grid = content.querySelector('.dash-grid');
        if (!grid) return;
        const cards = Array.from(grid.querySelectorAll('.dash-card:not(.card-wide)'));
        if (!cards.length) return;

        // Temporarily set align-self:start on all to measure natural heights
        cards.forEach(c => c.style.alignSelf = 'start');

        // Group cards into rows by their offsetTop
        const rows = [];
        let currentRow = [cards[0]];
        let currentTop = cards[0].offsetTop;
        for (let i = 1; i < cards.length; i++) {
            if (Math.abs(cards[i].offsetTop - currentTop) < 5) {
                currentRow.push(cards[i]);
            } else {
                rows.push(currentRow);
                currentRow = [cards[i]];
                currentTop = cards[i].offsetTop;
            }
        }
        rows.push(currentRow);

        // For each row: if no card is less than half the tallest, stretch all
        rows.forEach(row => {
            const heights = row.map(c => c.offsetHeight);
            const maxH = Math.max(...heights);
            const tooShort = heights.filter(h => h <= maxH * 0.5).length;
            if (tooShort < 2) {
                // Stretch all cards in this row to the tallest
                row.forEach(c => { c.style.alignSelf = ''; c.style.minHeight = maxH + 'px'; });
            }
            // else: leave align-self:start — cards keep natural heights
        });
    });
}

function _restoreOriginalReport() {
    if (!_originalReportHTML) return;
    const content = document.getElementById('right-content');
    if (content) content.innerHTML = _originalReportHTML;
    _originalReportHTML = null;
}

function toggleExpandReport() {
    const rp = document.getElementById('right-pane');
    // If split is active, the expand button acts as "exit split"
    if (_splitActive) {
        const remaining = _splitPanels[_splitFocusedSide];
        _exitSplitView();
        if (remaining.type === 'report' && remaining.reportFilename) {
            openReport(remaining.reportFilename);
        } else if (remaining.type === 'briefing' && remaining.dossierName) {
            openDossier(remaining.dossierName);
        }
        return;
    }
    if (rp.classList.contains('expanded')) {
        collapseReport();
    } else {
        expandReport();
    }
}

function expandReport() {
    const rp = document.getElementById('right-pane');
    rp.classList.add('expanded');
    document.getElementById('expand-icon-open').style.display = 'none';
    document.getElementById('expand-icon-close').style.display = '';
    document.getElementById('expand-btn').title = 'Exit focus mode (Esc)';
    if (!_splitActive) _buildCardGrid(rp);
}

function collapseReport() {
    const rp = document.getElementById('right-pane');
    rp.classList.remove('expanded');
    document.getElementById('expand-icon-open').style.display = '';
    document.getElementById('expand-icon-close').style.display = 'none';
    document.getElementById('expand-btn').title = 'Focus mode';
    _activeDashboardLens = null;
    if (!_splitActive) _restoreOriginalReport();
    // Restore saved width
    if (savedRightWidth) {
        rp.style.width = savedRightWidth + 'px';
        rp.style.minWidth = savedRightWidth + 'px';
    } else {
        rp.style.width = '';
        rp.style.minWidth = '';
    }
}

// --- Overflow menu & delete confirmation ---
function toggleOverflowMenu(e) {
    e.stopPropagation();
    const menu = document.getElementById('overflow-menu');
    menu.classList.toggle('open');
}

function confirmDeleteReport() {
    document.getElementById('overflow-menu').classList.remove('open');
    const name = currentReportFilename || activeDossierName || 'this item';
    _showConfirm(`Delete "${name}"? This cannot be undone.`, () => {
        deleteCurrentReport();
    }, { danger: true, confirmText: 'Delete' });
}

// Close overflow menu when clicking elsewhere
document.addEventListener('click', function(e) {
    const menu = document.getElementById('overflow-menu');
    if (menu && !e.target.closest('.right-actions')) {
        menu.classList.remove('open');
    }
});

// Esc key to exit focus mode (or close overflow menu)
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        const menu = document.getElementById('overflow-menu');
        if (menu && menu.classList.contains('open')) {
            menu.classList.remove('open');
            e.preventDefault();
            return;
        }
        // Exit prospect detail fullscreen
        const detailPane = document.getElementById('pane-detail');
        if (detailPane && detailPane.classList.contains('fullscreen')) {
            toggleDetailFullscreen();
            e.preventDefault();
            return;
        }
        // Exit split view first if active
        if (_splitActive) {
            toggleExpandReport(); // reuses the "exit split" logic
            e.preventDefault();
            return;
        }
        const rp = document.getElementById('right-pane');
        if (rp && rp.classList.contains('expanded')) {
            collapseReport();
            e.preventDefault();
        }
    }
});

function printReport() {
    // Button feedback
    const btn = document.querySelector('.right-btn');
    const origText = btn ? btn.textContent : '';
    if (btn) { btn.textContent = 'Exporting...'; btn.disabled = true; }
    const resetBtn = () => { if (btn) { btn.textContent = origText; btn.disabled = false; } };

    // Determine export type: report file or briefing/dossier
    if (currentReportFilename) {
        // Server-side PDF from markdown report
        fetch(`/api/reports/${currentReportFilename}/pdf`)
            .then(resp => {
                if (!resp.ok) throw new Error('PDF export failed');
                return resp.blob();
            })
            .then(blob => {
                _downloadBlob(blob, currentReportFilename.replace('.md', '.pdf'));
                resetBtn();
            })
            .catch(err => {
                console.error('PDF export error:', err);
                showToast('PDF export failed — check console for details.', 'error');
                resetBtn();
            });
    } else if (activeDossierName) {
        // Server-side PDF from briefing/dossier
        fetch(`/api/dossiers/${encodeURIComponent(activeDossierName)}/pdf`)
            .then(resp => {
                if (!resp.ok) throw new Error('Briefing PDF export failed');
                return resp.blob();
            })
            .then(blob => {
                const safeName = activeDossierName.toLowerCase().replace(/\s+/g, '_');
                _downloadBlob(blob, `${safeName}_briefing.pdf`);
                resetBtn();
            })
            .catch(err => {
                console.error('PDF export error:', err);
                showToast('PDF export failed — check console for details.', 'error');
                resetBtn();
            });
    } else {
        resetBtn();
    }
}

function _downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

async function deleteCurrentReport() {
    if (!currentReportFilename) return;
    _showConfirm('Delete this report?', async () => {
        try {
            await fetch(`/api/reports/${currentReportFilename}`, { method: 'DELETE' });
            closeRightPane();
            refreshSidebar();
        } catch {}
    }, { danger: true, confirmText: 'Delete' });
}

// ===================== SPLIT VIEW =====================

function _enterSplitView() {
    if (_splitActive) return;
    _splitActive = true;
    _splitFocusedSide = 'left';
    const rp = document.getElementById('right-pane');

    // Track if user was already in expanded/focus mode
    _wasExpandedBeforeSplit = rp.classList.contains('expanded');
    // If in expanded mode, remove it (split-active has its own fullscreen)
    if (_wasExpandedBeforeSplit) {
        rp.classList.remove('expanded');
        if (_originalReportHTML) { _originalReportHTML = null; }
    }

    rp.classList.add('split-active');

    // Update expand button to "Exit split view"
    document.getElementById('expand-icon-open').style.display = 'none';
    document.getElementById('expand-icon-close').style.display = '';
    document.getElementById('expand-btn').title = 'Exit split view (Esc)';

    const rightBody = rp.querySelector('.right-body');
    const container = document.createElement('div');
    container.className = 'split-container';
    container.id = 'split-container';
    container.innerHTML = `
        <div class="split-panel focused" id="split-panel-left">
            <div class="split-panel-header" onclick="_focusSplitPanel('left')">
                <span class="split-panel-title" id="split-title-left"></span>
                <span class="split-panel-badge" id="split-badge-left"></span>
                <button class="split-panel-close" onclick="event.stopPropagation(); closeSplitPanel('left')" title="Close">&times;</button>
            </div>
            <div class="split-panel-body" onclick="_focusSplitPanel('left')">
                <div class="md-content" id="split-content-left"></div>
            </div>
        </div>
        <div class="split-divider" id="split-divider"></div>
        <div class="split-panel" id="split-panel-right">
            <div class="split-panel-header" onclick="_focusSplitPanel('right')">
                <span class="split-panel-title" id="split-title-right"></span>
                <span class="split-panel-badge" id="split-badge-right"></span>
                <button class="split-panel-close" onclick="event.stopPropagation(); closeSplitPanel('right')" title="Close">&times;</button>
            </div>
            <div class="split-panel-body" onclick="_focusSplitPanel('right')">
                <div class="md-content" id="split-content-right"></div>
            </div>
        </div>`;
    rightBody.after(container);
    _initSplitDivider();
}

function _focusSplitPanel(side) {
    _splitFocusedSide = side;
    const left = document.getElementById('split-panel-left');
    const right = document.getElementById('split-panel-right');
    if (left) left.classList.toggle('focused', side === 'left');
    if (right) right.classList.toggle('focused', side === 'right');
}

function _exitSplitView() {
    if (!_splitActive) return;
    _splitActive = false;
    const rp = document.getElementById('right-pane');
    rp.classList.remove('split-active');

    // Restore expand button
    document.getElementById('expand-icon-open').style.display = '';
    document.getElementById('expand-icon-close').style.display = 'none';
    document.getElementById('expand-btn').title = 'Focus mode';

    // If user was in expanded mode before split, restore it
    if (_wasExpandedBeforeSplit) {
        rp.classList.add('expanded');
        document.getElementById('expand-icon-open').style.display = 'none';
        document.getElementById('expand-icon-close').style.display = '';
        document.getElementById('expand-btn').title = 'Exit focus mode (Esc)';
    } else {
        // Restore saved width
        if (savedRightWidth) {
            rp.style.width = savedRightWidth + 'px';
            rp.style.minWidth = savedRightWidth + 'px';
        } else {
            rp.style.width = '';
            rp.style.minWidth = '';
        }
    }
    _wasExpandedBeforeSplit = false;

    const container = document.getElementById('split-container');
    if (container) container.remove();
    _splitPanels.left = _emptyPanel();
    _splitPanels.right = _emptyPanel();
}

async function _loadIntoSplitPanel(side, type, identifier) {
    const contentEl = document.getElementById('split-content-' + side);
    const titleEl = document.getElementById('split-title-' + side);
    const badgeEl = document.getElementById('split-badge-' + side);
    if (!contentEl) return;

    if (type === 'report') {
        const meta = await _renderReportInto(identifier, contentEl);
        if (!meta) return;
        titleEl.textContent = meta.company;
        badgeEl.textContent = displayReportType(meta.type);
        _splitPanels[side] = {
            type: 'report', reportFilename: identifier, dossierName: null,
            briefingData: null, dossierData: null,
            company: meta.company, analysisType: meta.type, date: meta.date,
        };
    } else if (type === 'briefing') {
        try {
            const resp = await fetch('/api/dossiers/' + encodeURIComponent(identifier));
            if (!resp.ok) return;
            const dossier = await resp.json();
            if (dossier.briefing_json) {
                const briefing = typeof dossier.briefing_json === 'string'
                    ? JSON.parse(dossier.briefing_json) : dossier.briefing_json;
                _renderBriefingInto(dossier, briefing, contentEl);
                titleEl.textContent = dossier.company_name;
                badgeEl.textContent = 'briefing';
                _splitPanels[side] = {
                    type: 'briefing', reportFilename: null, dossierName: identifier,
                    briefingData: briefing, dossierData: dossier,
                    company: dossier.company_name, analysisType: 'briefing', date: '',
                };
            }
        } catch (e) { console.error('Failed to load briefing for split:', e); }
    }
}

async function _moveCurrentToSplitPanel(side) {
    if (currentReportFilename) {
        await _loadIntoSplitPanel(side, 'report', currentReportFilename);
    } else if (activeDossierName) {
        await _loadIntoSplitPanel(side, 'briefing', activeDossierName);
    }
}

function closeSplitPanel(side) {
    const otherSide = side === 'left' ? 'right' : 'left';
    const remaining = _splitPanels[otherSide];
    _exitSplitView();
    if (remaining.type === 'report' && remaining.reportFilename) {
        openReport(remaining.reportFilename);
    } else if (remaining.type === 'briefing' && remaining.dossierName) {
        openDossier(remaining.dossierName);
    }
}

function _initSplitDivider() {
    const divider = document.getElementById('split-divider');
    const container = document.getElementById('split-container');
    const leftPanel = document.getElementById('split-panel-left');
    const rightPanel = document.getElementById('split-panel-right');
    if (!divider || !container || !leftPanel) return;

    let dragging = false;
    let startX, startLeftWidth;

    divider.addEventListener('mousedown', e => {
        e.preventDefault();
        dragging = true;
        startX = e.clientX;
        startLeftWidth = leftPanel.offsetWidth;
        divider.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', function _splitMove(e) {
        if (!dragging) return;
        const delta = e.clientX - startX;
        const cw = container.offsetWidth;
        const newLeft = Math.max(200, Math.min(startLeftWidth + delta, cw - 200));
        const pct = (newLeft / cw) * 100;
        leftPanel.style.flex = '0 0 ' + pct + '%';
        rightPanel.style.flex = '0 0 ' + (100 - pct) + '%';
    });

    document.addEventListener('mouseup', function _splitUp() {
        if (!dragging) return;
        dragging = false;
        divider.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    });
}

// Drop zone show/hide
// ===================== CUSTOM DRAG FOR SPLIT VIEW =====================
// Uses mouse events instead of HTML5 DnD for cross-browser reliability
let _dragState = null;

function _ensureDropOverlay() {
    let overlay = document.getElementById('drop-zone-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'drop-zone-overlay';
        overlay.id = 'drop-zone-overlay';
        overlay.innerHTML = '<div class="drop-zone" data-side="left">\u25C0 Left panel</div>'
            + '<div class="drop-zone" data-side="right">Right panel \u25B6</div>';
        document.body.appendChild(overlay);
    }
    return overlay;
}

function _showDropZones() {
    _ensureDropOverlay().classList.add('visible');
}

function _hideDropZones() {
    const overlay = document.getElementById('drop-zone-overlay');
    if (!overlay) return;
    overlay.classList.remove('visible');
    overlay.querySelectorAll('.drop-zone').forEach(z => z.classList.remove('drag-over'));
}

function handleSidebarMouseDown(e, type, filename, company) {
    if (e.button !== 0) return;
    _dragState = {
        type: type,
        filename: filename,
        dossier: type === 'briefing' ? company : null,
        company: company,
        startX: e.clientX,
        startY: e.clientY,
        active: false,
    };
    document.addEventListener('mousemove', _onDragMouseMove);
    document.addEventListener('mouseup', _onDragMouseUp);
}

function _onDragMouseMove(e) {
    if (!_dragState) return;

    if (!_dragState.active) {
        const dx = Math.abs(e.clientX - _dragState.startX);
        const dy = Math.abs(e.clientY - _dragState.startY);
        if (dx < 6 && dy < 6) return;
        _dragState.active = true;
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'grabbing';
        _showDropZones();
    }

    // Highlight the zone under cursor
    const overlay = document.getElementById('drop-zone-overlay');
    if (overlay) {
        overlay.querySelectorAll('.drop-zone').forEach(zone => {
            const r = zone.getBoundingClientRect();
            zone.classList.toggle('drag-over',
                e.clientX >= r.left && e.clientX <= r.right &&
                e.clientY >= r.top && e.clientY <= r.bottom);
        });
    }
}

function _onDragMouseUp(e) {
    document.removeEventListener('mousemove', _onDragMouseMove);
    document.removeEventListener('mouseup', _onDragMouseUp);
    if (!_dragState) return;

    const wasActive = _dragState.active;
    const payload = { ..._dragState };

    if (wasActive) {
        // Find which zone the cursor is over BEFORE hiding
        let droppedSide = null;
        const overlay = document.getElementById('drop-zone-overlay');
        if (overlay) {
            overlay.querySelectorAll('.drop-zone').forEach(zone => {
                const r = zone.getBoundingClientRect();
                if (e.clientX >= r.left && e.clientX <= r.right &&
                    e.clientY >= r.top && e.clientY <= r.bottom) {
                    droppedSide = zone.dataset.side;
                }
            });
        }

        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        _hideDropZones();

        // Eat the click event that follows mouseup so onclick doesn't fire
        document.addEventListener('click', function _eatClick(ev) {
            ev.stopPropagation();
            ev.preventDefault();
            document.removeEventListener('click', _eatClick, true);
        }, true);

        if (droppedSide) {
            _handleSplitDrop(droppedSide, payload);
        }
    }
    // If !wasActive, the mouseup is a normal click — onclick handler fires naturally

    _dragState = null;
}

async function _handleSplitDrop(side, payload) {
    const otherSide = side === 'left' ? 'right' : 'left';

    const existing = _isInSplitPanel(payload.filename, payload.dossier);
    if (existing) {
        showToast('Already open in the other panel', 'warning');
        return;
    }

    if (!_splitActive) {
        const rp = document.getElementById('right-pane');
        if (!rp.classList.contains('open')) openRightPane();
        _enterSplitView();
        await _moveCurrentToSplitPanel(otherSide);
    }

    if (payload.type === 'report' && payload.filename) {
        await _loadIntoSplitPanel(side, 'report', payload.filename);
    } else if (payload.type === 'briefing' && payload.dossier) {
        await _loadIntoSplitPanel(side, 'briefing', payload.dossier);
    }
}

// ===================== RESIZE HANDLE =====================
let savedRightWidth = null;
(function() {
    const handle = document.getElementById('resize-handle');
    const rightPane = document.getElementById('right-pane');
    let dragging = false;
    let startX, startWidth;

    handle.addEventListener('mousedown', e => {
        if (!rightPane.classList.contains('open')) return;
        e.preventDefault();
        dragging = true;
        startX = e.clientX;
        startWidth = rightPane.offsetWidth;
        handle.classList.add('dragging');
        rightPane.classList.add('resizing');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', e => {
        if (!dragging) return;
        // Dragging left increases right pane width
        const delta = startX - e.clientX;
        const newWidth = Math.max(320, Math.min(startWidth + delta, window.innerWidth - 500));
        rightPane.style.width = newWidth + 'px';
        rightPane.style.minWidth = newWidth + 'px';
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove('dragging');
        rightPane.classList.remove('resizing');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        // Remember the resized width for subsequent report/briefing opens
        savedRightWidth = rightPane.offsetWidth;
    });
})();

