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

// Self-contained inline extractor used as a fallback when the persistent
// content script isn't on the tab (e.g., tab opened before extension install).
// Must be self-contained — runs in the tab's isolated world, no closures.
function _inlineExtract() {
    const EXCLUDE = [
        'aside', 'nav', 'footer', 'header',
        '[role="complementary"]', '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
        '.msg-overlay', '.msg-overlay-list-bubble', '.msg-conversations',
        '[aria-label*="messaging" i]', '[data-id="msg-overlay"]',
        '.comments', '.comment-list', '.chat', '.chat-window',
    ].join(',');
    const excluded = (el) => !!el.closest(EXCLUDE);
    const clean = (t) => (t || '').replace(/\n{3,}/g, '\n\n').replace(/[ \t]+/g, ' ').trim();

    const scoreContainer = (el) => {
        const texts = [];
        el.querySelectorAll('p').forEach(p => {
            if (excluded(p)) return;
            const t = (p.innerText || '').trim();
            if (t.length > 30) texts.push(t);
        });
        return texts.join('\n\n');
    };

    let articleText = '';
    try {
        const articles = Array.from(document.querySelectorAll('article')).filter(a => !excluded(a));
        if (articles.length) {
            articles.sort((a, b) => (b.innerText?.length || 0) - (a.innerText?.length || 0));
            const t = (articles[0].innerText || '').trim();
            if (t.length >= 200) articleText = clean(t);
        }
        if (!articleText) {
            const h1 = document.querySelector('main h1, [role="main"] h1, h1');
            if (h1 && !excluded(h1)) {
                let node = h1.parentElement;
                while (node && node !== document.body) {
                    const t = scoreContainer(node);
                    if (t.length >= 300) { articleText = clean(t); break; }
                    node = node.parentElement;
                }
            }
        }
        if (!articleText) {
            let best = null, bestScore = 0;
            document.querySelectorAll('main, [role="main"], [role="article"], section, div').forEach(el => {
                if (excluded(el)) return;
                const paras = el.querySelectorAll('p');
                if (paras.length < 2) return;
                let score = 0;
                paras.forEach(p => {
                    if (excluded(p)) return;
                    const len = (p.innerText || '').trim().length;
                    if (len > 30) score += len;
                });
                if (score > bestScore) { bestScore = score; best = el; }
            });
            if (best && bestScore >= 200) articleText = clean(scoreContainer(best));
        }
        if (!articleText) {
            const ps = [];
            document.querySelectorAll('p').forEach(p => {
                if (excluded(p)) return;
                const t = (p.innerText || '').trim();
                if (t.length > 50) ps.push(t);
            });
            if (ps.length >= 3) articleText = clean(ps.join('\n\n'));
        }
    } catch (e) {}

    const ogTitle = document.querySelector('meta[property="og:title"]')?.content || '';
    const twTitle = document.querySelector('meta[name="twitter:title"]')?.content || '';
    const h1text = document.querySelector('article h1, main h1, h1')?.textContent?.trim() || '';
    const articleTitle = ogTitle || twTitle || h1text || document.title;

    const ogDesc = document.querySelector('meta[property="og:description"]')?.content || '';
    const metaDesc = document.querySelector('meta[name="description"]')?.content || '';
    const author = document.querySelector('meta[name="author"]')?.content
        || document.querySelector('meta[property="article:author"]')?.content || '';
    const publishedTime = document.querySelector('meta[property="article:published_time"]')?.content
        || document.querySelector('meta[name="pubdate"]')?.content || '';
    const selection = window.getSelection()?.toString() || '';

    return {
        selection, articleTitle, articleText,
        ogDesc, metaDesc, author, publishedTime,
    };
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

    // Always inject fresh — works on any tab regardless of whether the
    // persistent content script was previously loaded. No per-tab reload.
    let pageData = null;
    try {
        const results = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: _inlineExtract,
        });
        pageData = results?.[0]?.result || null;
    } catch (e) {
        console.warn('[clipper] inline extract failed:', e);
    }

    // If the inline extract got no selection (site cleared it on focus change)
    // fall back to the cached selection from the content script, if any.
    if (pageData && !pageData.selection && stored.lastSelection
        && stored.lastSelection.url === tab.url
        && Date.now() - (stored.lastSelection.at || 0) < 5 * 60 * 1000) {
        pageData.selection = stored.lastSelection.text || '';
    }

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
