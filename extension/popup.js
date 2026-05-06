// SignalVault Clipper — popup script

const DEFAULT_ENDPOINT = 'http://localhost:5001/api/signals/manual';
const DEFAULT_THREADS_ENDPOINT = 'http://localhost:5001/api/signals/threads';
const DEFAULT_THREAD_CREATE_ENDPOINT = 'http://localhost:5001/api/signals/threads/create';

let selectedSource = 'news';
let currentTab = null;
let pageSelection = '';
let threads = []; // [{id, title}]
let selectedThreadId = null;
let _mode = 'signal'; // 'signal' | 'document'
let _emailData = null; // {emailSubject, emailSender, emailDate, emailBodyHtml}
let _pageData = null;  // {articleTitle, articleText, articleHtml, author, publishedTime, ...}

const $ = (id) => document.getElementById(id);

// ── Email client detection ─────────────────────────────────────────────
function detectEmailClient(url) {
    if (!url) return null;
    if (url.includes('mail.google.com')) return 'gmail';
    if (url.includes('outlook.live.com') || url.includes('outlook.office.com')) return 'outlook';
    return null;
}

// ── Mode switcher ──────────────────────────────────────────────────────
function setMode(mode) {
    _mode = mode;
    $('mode-signal-btn').classList.toggle('active', mode === 'signal');
    $('mode-document-btn').classList.toggle('active', mode === 'document');
    $('signal-only').style.display = mode === 'signal' ? '' : 'none';
    $('doc-only').style.display = mode === 'document' ? '' : 'none';
}

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

// ── Inline extractor for regular pages ────────────────────────────────
// Self-contained — runs in tab's isolated world via executeScript.
function _inlineExtract() {
    const EXCLUDE = [
        'aside', 'nav', 'footer', 'header',
        '[role="complementary"]', '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
        '.msg-overlay', '.msg-overlay-list-bubble', '.msg-conversations',
        '[aria-label*="messaging" i]', '[data-id="msg-overlay"]',
        '.comments', '.comment-list', '.chat', '.chat-window',
        '[class*="related" i]', '[class*="recommend" i]', '[class*="sidebar" i]',
        '[class*="share" i]', '[class*="social-" i]', '[class*="more-from" i]',
        '[class*="newsletter-signup" i]', '[class*="promo-" i]',
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
    let articleHtml = '';
    let bestEl = null;
    try {
        const articles = Array.from(document.querySelectorAll('article')).filter(a => !excluded(a));
        if (articles.length) {
            articles.sort((a, b) => (b.innerText?.length || 0) - (a.innerText?.length || 0));
            const t = (articles[0].innerText || '').trim();
            if (t.length >= 200) { articleText = clean(t); bestEl = articles[0]; }
        }
        if (!articleText) {
            const CONTENT_SEL = [
                '[itemprop="articleBody"]', '.post-content', '.article-content', '.article-body',
                '.entry-content', '.post-body', '.prose', '.body.markup',
                '[class*="post-content" i]', '[class*="article-body" i]', '[class*="entry-content" i]',
            ];
            for (const sel of CONTENT_SEL) {
                const el = document.querySelector(sel);
                if (el && !excluded(el)) {
                    const t = (el.innerText || '').trim();
                    if (t.length >= 200) { articleText = clean(t); bestEl = el; break; }
                }
            }
        }
        if (!articleText) {
            const h1 = document.querySelector('main h1, [role="main"] h1, h1');
            if (h1 && !excluded(h1)) {
                let node = h1.parentElement;
                while (node && node !== document.body) {
                    const t = scoreContainer(node);
                    if (t.length >= 300) { articleText = clean(t); bestEl = node; break; }
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
            if (best && bestScore >= 200) { articleText = clean(scoreContainer(best)); bestEl = best; }
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
        if (bestEl) {
            const clone = bestEl.cloneNode(true);
            const STRIP = 'aside,nav,footer,[role="complementary"],[role="navigation"],' +
                '[class*="related" i],[class*="recommend" i],[class*="sidebar" i],' +
                '[class*="share" i],[class*="social-" i],[class*="more-from" i],' +
                '[class*="newsletter" i],[class*="promo-" i],[class*="more-stories" i]';
            clone.querySelectorAll(STRIP).forEach(el => el.remove());
            articleHtml = clone.innerHTML || '';
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
        selection, articleTitle, articleText, articleHtml,
        ogDesc, metaDesc, author, publishedTime,
    };
}

// ── Inline extractor for email clients ────────────────────────────────
// Self-contained — detects client from window.location.href.
function _inlineExtractEmail() {
    const url = window.location.href;
    let subject = '', sender = '', date = '', bodyHtml = '';

    if (url.includes('mail.google.com')) {
        subject = document.querySelector('h2.hP')?.textContent?.trim() || document.title;
        const senderEl = document.querySelector('.gD');
        sender = senderEl?.getAttribute('email') || senderEl?.textContent?.trim() || '';
        const dateEl = document.querySelector('.g3');
        date = dateEl?.getAttribute('title') || dateEl?.textContent?.trim() || '';
        const bodyEl = document.querySelector('.ii.gt') || document.querySelector('.a3s.aiL');
        bodyHtml = bodyEl?.innerHTML || '';
    } else if (url.includes('outlook.live.com') || url.includes('outlook.office.com')) {
        subject = document.querySelector('[data-automation-id="mailSubject"]')?.textContent?.trim() || document.title;
        sender = document.querySelector('[data-automation-id="senderName"]')?.textContent?.trim() || '';
        const dateEl = document.querySelector('[data-automation-id="receivedDateTime"]');
        date = dateEl?.textContent?.trim() || '';
        const bodyEl = document.querySelector('[data-automation-id="messageBody"]');
        bodyHtml = bodyEl?.innerHTML || '';
    }

    return { emailSubject: subject, emailSender: sender, emailDate: date, emailBodyHtml: bodyHtml };
}

// ── Refresh open SignalVault tabs ──────────────────────────────────────
async function refreshSignalVaultTabs() {
    try {
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

// ── Derive documents endpoint from signal endpoint ─────────────────────
function documentsEndpoint() {
    const ep = window._endpoint || DEFAULT_ENDPOINT;
    try {
        const u = new URL(ep);
        return `${u.protocol}//${u.host}/api/documents`;
    } catch {
        return DEFAULT_ENDPOINT.replace('/api/signals/manual', '/api/documents');
    }
}

// ── Init ───────────────────────────────────────────────────────────────
async function init() {
    const stored = await chrome.storage.local.get(['endpoint', 'lastSelection']);
    window._endpoint = stored.endpoint || DEFAULT_ENDPOINT;

    loadThreads();

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
        $('status').textContent = 'No active tab';
        $('status').className = 'status error';
        return;
    }
    currentTab = tab;

    $('url-display').textContent = tab.url || '';
    setSource(detectSource(tab.url));

    // Check for email client first
    const emailClient = detectEmailClient(tab.url);
    if (emailClient) {
        try {
            const results = await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                func: _inlineExtractEmail,
            });
            _emailData = results?.[0]?.result || null;
        } catch (e) {
            console.warn('[clipper] email extract failed:', e);
        }

        if (_emailData?.emailBodyHtml) {
            setMode('document');
            $('email-hint').style.display = 'block';
            $('title').value = _emailData.emailSubject || tab.title || '';
            $('doc-from-display').textContent = _emailData.emailSender || '';
            return;
        }
    }

    // Regular page extraction
    let pageData = null;
    try {
        const results = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: _inlineExtract,
        });
        pageData = results?.[0]?.result || null;
        _pageData = pageData;
    } catch (e) {
        console.warn('[clipper] inline extract failed:', e);
    }

    if (pageData && !pageData.selection && stored.lastSelection
        && stored.lastSelection.url === tab.url
        && Date.now() - (stored.lastSelection.at || 0) < 5 * 60 * 1000) {
        pageData.selection = stored.lastSelection.text || '';
    }

    const articleTitle = pageData?.articleTitle || tab.title || '';
    $('title').value = articleTitle;

    let selection = pageData?.selection || '';
    if (!selection && stored.lastSelection && stored.lastSelection.url === tab.url) {
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

// ── Save: document ─────────────────────────────────────────────────────
async function saveDocument() {
    const status = $('status');
    const btn = $('save-doc-btn');
    btn.disabled = true;
    btn.textContent = 'Saving…';
    status.className = 'status';
    status.textContent = '';

    const isEmail = !!_emailData?.emailBodyHtml;
    const htmlContent = isEmail ? _emailData.emailBodyHtml : (_pageData?.articleHtml || '');

    if (!htmlContent) {
        status.className = 'status error';
        status.textContent = 'No article content found on this page';
        btn.disabled = false;
        btn.textContent = 'Save as Document';
        return;
    }

    const title = $('title').value.trim()
        || (isEmail ? _emailData.emailSubject : _pageData?.articleTitle)
        || currentTab?.title || 'Document';
    const sender = isEmail ? (_emailData.emailSender || '') : '';
    const sourceUrl = currentTab?.url || '';
    const source = sender
        ? sender.replace(/^.*@/, '')
        : (sourceUrl ? (() => { try { return new URL(sourceUrl).hostname; } catch { return ''; } })() : '');
    const yearMatch = isEmail
        ? (_emailData.emailDate || '').match(/\d{4}/)
        : (_pageData?.publishedTime || '').match(/\d{4}/);
    const year = yearMatch ? parseInt(yearMatch[0]) : new Date().getFullYear();

    try {
        const res = await fetch(documentsEndpoint(), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                file_type: isEmail ? 'email' : 'article',
                content: htmlContent,
                title,
                sender,
                source,
                source_url: sourceUrl,
                year,
            }),
        });
        const data = await res.json();
        if (res.ok && data.ok !== false) {
            status.className = 'status success';
            status.textContent = `✓ Saved to Documents (${data.section_count} section${data.section_count !== 1 ? 's' : ''})`;
            btn.textContent = '✓ Saved';
            refreshSignalVaultTabs();
            setTimeout(() => window.close(), 1500);
        } else {
            status.className = 'status error';
            status.textContent = data.error || 'Save failed';
            btn.disabled = false;
            btn.textContent = 'Save as Document';
        }
    } catch (e) {
        status.className = 'status error';
        status.textContent = 'Could not reach SignalVault. Is it running?';
        btn.disabled = false;
        btn.textContent = 'Save as Document';
    }
}

// ── Save: signal ───────────────────────────────────────────────────────
function threadCreateEndpoint() {
    const ep = window._endpoint || DEFAULT_ENDPOINT;
    return ep.replace(/\/manual\/?$/, '/threads/create');
}

function _setBusy(busy, signalLabel, threadLabel) {
    $('save-signal-btn').disabled = busy;
    $('save-thread-btn').disabled = busy;
    $('save-signal-btn').textContent = signalLabel;
    $('save-thread-btn').textContent = threadLabel;
}

function _resetButtons() {
    _setBusy(false, 'Capture Signal', 'Create Thread');
}

async function saveSignal() {
    const status = $('status');
    _setBusy(true, 'Saving…', 'Create Thread');
    status.className = 'status';
    status.textContent = '';

    const title = $('title').value.trim();
    const url = currentTab?.url || '';
    const content = $('content').value.trim();

    if (!title && !content) {
        status.className = 'status error';
        status.textContent = 'Need at least a title or content';
        _resetButtons();
        return;
    }

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
            _setBusy(true, '✓ Captured', 'Create Thread');
            refreshSignalVaultTabs();
            setTimeout(() => window.close(), 1200);
        } else {
            status.className = 'status error';
            status.textContent = data.error || 'Capture failed';
            _resetButtons();
        }
    } catch (e) {
        status.className = 'status error';
        status.textContent = 'Could not reach SignalVault at ' + window._endpoint + '. Is it running?';
        _resetButtons();
    }
}

async function saveThread() {
    const status = $('status');
    _setBusy(true, 'Capture Signal', 'Creating…');
    status.className = 'status';
    status.textContent = '';

    const title = $('title').value.trim();
    const content = $('content').value.trim();
    const url = currentTab?.url || '';

    if (!title) {
        status.className = 'status error';
        status.textContent = 'Title required for new thread';
        _resetButtons();
        return;
    }

    try {
        const threadRes = await fetch(threadCreateEndpoint(), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title }),
        });
        const threadData = await threadRes.json();
        if (!threadRes.ok || threadData.ok === false || !threadData.thread_id) {
            status.className = 'status error';
            status.textContent = threadData.error || 'Thread creation failed';
            _resetButtons();
            return;
        }

        if (!content) {
            status.className = 'status success';
            status.textContent = '✓ Thread created';
            _setBusy(true, 'Capture Signal', '✓ Created');
            refreshSignalVaultTabs();
            setTimeout(() => window.close(), 1200);
            return;
        }

        const sigRes = await fetch(window._endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                content,
                title,
                url,
                source: selectedSource,
                author: window._author || '',
                published_at: window._publishedTime || '',
                thread_id: threadData.thread_id,
            }),
        });
        const sigData = await sigRes.json();
        if (sigRes.ok && sigData.ok !== false) {
            status.className = 'status success';
            status.textContent = '✓ Thread + signal captured';
            _setBusy(true, 'Capture Signal', '✓ Created');
            refreshSignalVaultTabs();
            setTimeout(() => window.close(), 1200);
        } else {
            status.className = 'status error';
            status.textContent = sigData.error || 'Thread created but signal capture failed';
            _resetButtons();
        }
    } catch (e) {
        status.className = 'status error';
        status.textContent = 'Could not reach SignalVault at ' + threadCreateEndpoint() + '. Is it running?';
        _resetButtons();
    }
}

// ── Wire up events ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    init();

    $('mode-signal-btn').addEventListener('click', () => setMode('signal'));
    $('mode-document-btn').addEventListener('click', () => setMode('document'));
    $('save-doc-btn').addEventListener('click', saveDocument);

    document.querySelectorAll('.src-pill').forEach(btn => {
        btn.addEventListener('click', () => setSource(btn.dataset.source));
    });

    $('save-signal-btn').addEventListener('click', saveSignal);
    $('save-thread-btn').addEventListener('click', saveThread);

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
            if (_mode === 'document') {
                saveDocument();
            } else if (e.shiftKey) {
                saveThread();
            } else {
                saveSignal();
            }
        }
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'D') {
            e.preventDefault();
            setMode('document');
            saveDocument();
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
