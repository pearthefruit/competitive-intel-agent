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
    const stored = await chrome.storage.local.get(['endpoint']);
    window._endpoint = stored.endpoint || DEFAULT_ENDPOINT;

    // Get active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
        $('status').textContent = 'No active tab';
        $('status').className = 'status error';
        return;
    }
    currentTab = tab;

    $('title').value = tab.title || '';
    $('url-display').textContent = tab.url || '';
    setSource(detectSource(tab.url));

    // Grab selected text + og:description from the page
    try {
        const results = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: () => {
                const sel = window.getSelection()?.toString() || '';
                const ogDesc = document.querySelector('meta[property="og:description"]')?.content || '';
                const metaDesc = document.querySelector('meta[name="description"]')?.content || '';
                const author = document.querySelector('meta[name="author"]')?.content
                    || document.querySelector('meta[property="article:author"]')?.content
                    || '';
                const publishedTime = document.querySelector('meta[property="article:published_time"]')?.content
                    || document.querySelector('meta[name="pubdate"]')?.content
                    || '';
                return { sel, ogDesc, metaDesc, author, publishedTime };
            }
        });
        const r = results?.[0]?.result || {};
        pageSelection = r.sel || '';
        // Fill content with selection OR og:description as a preview
        if (pageSelection) {
            $('content').value = pageSelection;
        } else if (r.ogDesc || r.metaDesc) {
            $('content').value = r.ogDesc || r.metaDesc;
            $('content').placeholder = 'Description pre-filled — edit or clear as needed';
        }
        // Stash author/date for POST
        window._author = r.author || '';
        window._publishedTime = r.publishedTime ? r.publishedTime.substring(0, 10) : '';
    } catch (e) {
        console.warn('[clipper] scripting failed:', e);
    }

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
