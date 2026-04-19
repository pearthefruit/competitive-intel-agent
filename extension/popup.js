// SignalVault Clipper — popup script
// Grabs page URL + title + selected text and POSTs to local SignalVault.

const DEFAULT_ENDPOINT = 'http://localhost:5001/api/signals/manual';
const DEFAULT_THREADS_ENDPOINT = 'http://localhost:5001/api/signals/threads';

let selectedSource = 'news';
let currentTab = null;
let pageSelection = '';
let threads = []; // [{id, title}]
let selectedThreadId = null;

const $ = (id) => document.getElementById(id);

// ── Source detection ───────────────────────────────────────────────────
function detectSource(url) {
    if (!url) return 'news';
    const u = url.toLowerCase();
    if (u.includes('linkedin.com')) return 'linkedin';
    if (u.includes('twitter.com') || u.includes('x.com')) return 'twitter';
    if (u.includes('reddit.com')) return 'reddit';
    if (u.includes('news.ycombinator.com')) return 'hackernews';
    return 'news';
}

function setSource(src) {
    selectedSource = src;
    document.querySelectorAll('.src-pill').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.source === src);
    });
}

// ── Thread picker ──────────────────────────────────────────────────────
function threadsEndpoint() {
    // Derive /api/signals/threads from /api/signals/manual endpoint
    const ep = window._endpoint || DEFAULT_ENDPOINT;
    return ep.replace(/\/manual\/?$/, '/threads');
}

async function loadThreads() {
    try {
        const res = await fetch(threadsEndpoint());
        if (!res.ok) return;
        const data = await res.json();
        threads = (data.threads || []).map(t => ({ id: t.id, title: t.title }));
        const dl = $('thread-list');
        dl.innerHTML = threads.map(t => `<option value="${t.title.replace(/"/g, '&quot;')}" data-id="${t.id}"></option>`).join('');
    } catch (e) {
        console.warn('[clipper] failed to load threads:', e);
    }
}

function resolveThreadId() {
    const val = $('thread-input').value.trim();
    if (!val) return null;
    const match = threads.find(t => t.title === val);
    return match ? match.id : null;
}

// After a successful capture, tell any open SignalVault tabs to refresh.
async function refreshSignalVaultTabs() {
    try {
        // Derive host from the capture endpoint so a custom port still works
        const ep = window._endpoint || DEFAULT_ENDPOINT;
        const u = new URL(ep);
        const pattern = `${u.protocol}//${u.host}/*`;
        const tabs = await chrome.tabs.query({ url: pattern });
        for (const t of tabs) {
            try {
                await chrome.scripting.executeScript({
                    target: { tabId: t.id },
                    func: () => { window._signalVaultRefresh?.(); }
                });
            } catch (e) { /* tab may be restricted — ignore */ }
        }
    } catch (e) {
        console.warn('[clipper] refresh-signalvault failed:', e);
    }
}

// ── Init: grab tab info + selected text ────────────────────────────────
async function init() {
    // Load endpoint override from storage
    const stored = await chrome.storage.local.get(['endpoint', 'lastSelection']);
    window._endpoint = stored.endpoint || DEFAULT_ENDPOINT;

    // Kick off threads fetch in parallel
    loadThreads();

    // Get active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
        $('status').textContent = 'No active tab';
        $('status').className = 'status error';
        return;
    }
    currentTab = tab;

    $('url-display').textContent = tab.url || '';
    setSource(detectSource(tab.url));

    // Ask the content script for page data (article title, meta, last selection)
    let pageData = null;
    try {
        pageData = await new Promise((resolve) => {
            chrome.tabs.sendMessage(tab.id, { type: 'get-page-data' }, (resp) => {
                if (chrome.runtime.lastError) resolve(null);
                else resolve(resp);
            });
            setTimeout(() => resolve(null), 500);
        });
    } catch (e) { /* ignore */ }

    // Title — prefer page article title (og:title / h1) over tab title
    const articleTitle = pageData?.articleTitle || tab.title || '';
    $('title').value = articleTitle;

    // Selection — prefer content script's live capture; fall back to storage cache
    let selection = pageData?.selection || '';
    if (!selection && stored.lastSelection && stored.lastSelection.url === tab.url) {
        // Accept cached selection if recorded in the last 5 minutes
        if (Date.now() - (stored.lastSelection.at || 0) < 5 * 60 * 1000) {
            selection = stored.lastSelection.text || '';
        }
    }

    if (selection) {
        $('content').value = selection;
        $('content').placeholder = 'Selection captured — edit or add a note';
    } else if (pageData?.articleText) {
        $('content').value = pageData.articleText;
        $('content').placeholder = 'Article body extracted — edit or clear as needed';
    } else if (pageData?.ogDesc || pageData?.metaDesc) {
        $('content').value = pageData.ogDesc || pageData.metaDesc;
        $('content').placeholder = 'Description pre-filled — edit or clear as needed';
    }

    window._author = pageData?.author || '';
    window._publishedTime = pageData?.publishedTime ? pageData.publishedTime.substring(0, 10) : '';

    $('title').focus();
    $('title').select();
}

// ── Save handler ──────────────────────────────────────────────────────
async function save() {
    const btn = $('save-btn');
    const status = $('status');
    btn.disabled = true;
    btn.textContent = 'Saving…';
    status.className = 'status';
    status.textContent = '';

    const title = $('title').value.trim();
    const url = currentTab?.url || '';
    const content = $('content').value.trim();

    if (!title && !content) {
        status.className = 'status error';
        status.textContent = 'Need at least a title or content';
        btn.disabled = false;
        btn.textContent = 'Capture to SignalVault';
        return;
    }

    // If no content, use title as content so the endpoint accepts it
    const body = {
        content: content || title,
        title: title,
        url: url,
        source: selectedSource,
        author: window._author || '',
        published_at: window._publishedTime || '',
    };
    const threadId = resolveThreadId();
    if (threadId) body.thread_id = threadId;

    try {
        const res = await fetch(window._endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (res.ok && data.ok !== false) {
            status.className = 'status success';
            const assignment = data.thread_assignment?.thread_title;
            status.textContent = assignment ? `✓ Saved → ${assignment}` : '✓ Captured';
            btn.textContent = '✓ Captured';
            // Trigger refresh in any open SignalVault tabs
            refreshSignalVaultTabs();
            setTimeout(() => window.close(), 1200);
        } else {
            status.className = 'status error';
            status.textContent = data.error || 'Capture failed';
            btn.disabled = false;
            btn.textContent = 'Capture to SignalVault';
        }
    } catch (e) {
        status.className = 'status error';
        status.textContent = 'Could not reach SignalVault at ' + window._endpoint + '. Is it running?';
        btn.disabled = false;
        btn.textContent = 'Capture to SignalVault';
    }
}

// ── Wire up events ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    init();

    document.querySelectorAll('.src-pill').forEach(btn => {
        btn.addEventListener('click', () => setSource(btn.dataset.source));
    });

    $('save-btn').addEventListener('click', save);

    const threadInput = $('thread-input');
    const threadClear = $('thread-clear');
    threadInput?.addEventListener('input', () => {
        threadClear.classList.toggle('visible', !!threadInput.value.trim());
    });
    threadClear?.addEventListener('click', () => {
        threadInput.value = '';
        threadClear.classList.remove('visible');
        threadInput.focus();
    });

    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            save();
        }
    });

    $('settings-link').addEventListener('click', (e) => {
        e.preventDefault();
        const current = window._endpoint || DEFAULT_ENDPOINT;
        const next = prompt('SignalVault endpoint URL:', current);
        if (next && next !== current) {
            chrome.storage.local.set({ endpoint: next.trim() });
            window._endpoint = next.trim();
            $('status').className = 'status success';
            $('status').textContent = 'Endpoint saved';
        }
    });
});
