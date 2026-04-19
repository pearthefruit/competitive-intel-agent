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

// Find the main article text on the page.
// Strategy:
//   1. If <article> exists, use the one with most text.
//   2. Else find the DOM element whose descendant <p> tags have the most total text.
//   3. Last resort: concatenate all substantial <p> tags on the page.
function extractArticleText() {
    try {
        // Candidate 1: <article> tags (deep descendants, not just direct children)
        const articles = Array.from(document.querySelectorAll('article'));
        if (articles.length) {
            articles.sort((a, b) => (b.innerText?.length || 0) - (a.innerText?.length || 0));
            const text = (articles[0].innerText || '').trim();
            if (text.length >= 200) return cleanArticleText(text);
        }

        // Candidate 2: find the element containing the most substantive <p> text (descendants)
        let best = null;
        let bestScore = 0;
        document.querySelectorAll('main, [role="main"], [role="article"], section, div').forEach(el => {
            const paras = el.querySelectorAll('p');
            if (paras.length < 2) return;
            let score = 0;
            paras.forEach(p => {
                const len = (p.innerText || '').trim().length;
                if (len > 30) score += len;  // only count article-like paragraphs
            });
            if (score > bestScore) {
                bestScore = score;
                best = el;
            }
        });
        if (best && bestScore >= 200) {
            const texts = [];
            best.querySelectorAll('p').forEach(p => {
                const t = (p.innerText || '').trim();
                if (t.length > 30) texts.push(t);
            });
            if (texts.length) return cleanArticleText(texts.join('\n\n'));
        }

        // Candidate 3 (last resort): collect all substantial <p> tags document-wide
        const allPs = [];
        document.querySelectorAll('p').forEach(p => {
            const t = (p.innerText || '').trim();
            if (t.length > 50) allPs.push(t);
        });
        if (allPs.length >= 3) {
            return cleanArticleText(allPs.join('\n\n'));
        }
    } catch (e) { /* ignore */ }
    return '';
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
