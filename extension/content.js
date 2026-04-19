// SignalVault Clipper — content script
// Watches text selection on every page and caches the most recent selection
// so the popup can read it even after focus moves to the popup (which clears
// the selection on many sites like LinkedIn).

let lastSelectionText = '';
let lastSelectionAt = 0;

function captureSelection() {
    try {
        const sel = window.getSelection()?.toString() || '';
        if (sel.length >= 3) {
            lastSelectionText = sel;
            lastSelectionAt = Date.now();
            chrome.storage.local.set({
                lastSelection: {
                    text: sel,
                    url: location.href,
                    title: document.title,
                    at: lastSelectionAt,
                }
            });
        }
    } catch (e) { /* chrome.storage might be unavailable in some frames */ }
}

// Selection changes fire frequently; throttle via mouseup/keyup which
// are the points when the user "commits" a selection.
document.addEventListener('mouseup', captureSelection);
document.addEventListener('keyup', (e) => {
    // Only capture on shift/arrow-based keyboard selection
    if (e.shiftKey || e.key === 'End' || e.key === 'Home') captureSelection();
});

// Elements we never want to pull text from — sidebars, nav, messaging widgets, etc.
const _EXCLUDE_SELECTOR = [
    'aside', 'nav', 'footer', 'header',
    '[role="complementary"]', '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    // LinkedIn-specific: the messaging overlay + feed chrome
    '.msg-overlay', '.msg-overlay-list-bubble', '.msg-conversations',
    '[aria-label*="messaging" i]', '[data-id="msg-overlay"]',
    // Common chat/comment containers
    '.comments', '.comment-list', '.chat', '.chat-window',
].join(',');

function _insideExcluded(el) {
    return !!el.closest(_EXCLUDE_SELECTOR);
}

// Find the main article text on the page.
// Strategy:
//   1. If <article> exists (not inside excluded chrome), use the longest.
//   2. Localize to the subtree around the page's <h1> when possible.
//   3. Else score containers by <p> text, ignoring excluded subtrees.
//   4. Last resort: concat all substantial <p> tags outside excluded chrome.
function extractArticleText() {
    try {
        // Candidate 1: <article> tags outside chrome
        const articles = Array.from(document.querySelectorAll('article'))
            .filter(a => !_insideExcluded(a));
        if (articles.length) {
            articles.sort((a, b) => (b.innerText?.length || 0) - (a.innerText?.length || 0));
            const text = (articles[0].innerText || '').trim();
            if (text.length >= 200) return cleanArticleText(text);
        }

        // Candidate 2: localize near the first <h1> (which usually titles the article)
        const h1 = document.querySelector('main h1, [role="main"] h1, h1');
        if (h1 && !_insideExcluded(h1)) {
            // Walk up until we find an ancestor with substantial paragraph text
            let node = h1.parentElement;
            while (node && node !== document.body) {
                const text = _scoreContainer(node);
                if (text && text.length >= 300) return cleanArticleText(text);
                node = node.parentElement;
            }
        }

        // Candidate 3: scan all containers, excluding chrome
        let best = null;
        let bestScore = 0;
        document.querySelectorAll('main, [role="main"], [role="article"], section, div').forEach(el => {
            if (_insideExcluded(el)) return;
            const paras = el.querySelectorAll('p');
            if (paras.length < 2) return;
            let score = 0;
            paras.forEach(p => {
                if (_insideExcluded(p)) return;
                const len = (p.innerText || '').trim().length;
                if (len > 30) score += len;
            });
            if (score > bestScore) {
                bestScore = score;
                best = el;
            }
        });
        if (best && bestScore >= 200) {
            const text = _scoreContainer(best);
            if (text) return cleanArticleText(text);
        }

        // Candidate 4 (last resort): all substantial <p> tags outside excluded chrome
        const allPs = [];
        document.querySelectorAll('p').forEach(p => {
            if (_insideExcluded(p)) return;
            const t = (p.innerText || '').trim();
            if (t.length > 50) allPs.push(t);
        });
        if (allPs.length >= 3) {
            return cleanArticleText(allPs.join('\n\n'));
        }
    } catch (e) { /* ignore */ }
    return '';
}

// Collect article-like paragraphs from a container, skipping excluded subtrees.
function _scoreContainer(el) {
    const texts = [];
    el.querySelectorAll('p').forEach(p => {
        if (_insideExcluded(p)) return;
        const t = (p.innerText || '').trim();
        if (t.length > 30) texts.push(t);
    });
    return texts.length ? texts.join('\n\n') : '';
}

function cleanArticleText(text) {
    // No length cap — full article, scrollbar handles overflow in the popup.
    return (text || '')
        .replace(/\n{3,}/g, '\n\n')
        .replace(/[ \t]+/g, ' ')
        .trim();
}

// Reply to popup requests with latest selection + article meta + extracted body
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg?.type === 'get-page-data') {
        // Article title — prefer og:title, then <h1>, then <title>
        const ogTitle = document.querySelector('meta[property="og:title"]')?.content || '';
        const twTitle = document.querySelector('meta[name="twitter:title"]')?.content || '';
        const h1 = document.querySelector('article h1, main h1, h1')?.textContent?.trim() || '';
        const articleTitle = ogTitle || twTitle || h1 || document.title;

        const ogDesc = document.querySelector('meta[property="og:description"]')?.content || '';
        const metaDesc = document.querySelector('meta[name="description"]')?.content || '';
        const author = document.querySelector('meta[name="author"]')?.content
            || document.querySelector('meta[property="article:author"]')?.content || '';
        const publishedTime = document.querySelector('meta[property="article:published_time"]')?.content
            || document.querySelector('meta[name="pubdate"]')?.content || '';

        const articleText = extractArticleText();

        sendResponse({
            selection: lastSelectionText,
            selectionAt: lastSelectionAt,
            articleTitle, articleText, ogDesc, metaDesc, author, publishedTime,
        });
        return true;
    }
});
