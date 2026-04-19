// SignalVault Clipper — popup script
// Grabs page URL + title + selected text and POSTs to local SignalVault.

const DEFAULT_ENDPOINT = 'http://localhost:5001/api/signals/manual';

let selectedSource = 'news';
let currentTab = null;
let pageSelection = '';

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

// ── Init: grab tab info + selected text ────────────────────────────────
async function init() {
    // Load endpoint override from storage
    const stored = await chrome.storage.local.get(['endpoint', 'lastSelection']);
    window._endpoint = stored.endpoint || DEFAULT_ENDPOINT;

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
