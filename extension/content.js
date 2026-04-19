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
//   1. If <article> exists, use the biggest one by text length.
//   2. Else find the element with the densest cluster of <p> tags.
//   3. Extract text, trim whitespace, cap at 4000 chars.
function extractArticleText() {
    try {
        // Candidate 1: <article> tags
        const articles = Array.from(document.querySelectorAll('article'));
        if (articles.length) {
            articles.sort((a, b) => (b.innerText?.length || 0) - (a.innerText?.length || 0));
            const text = (articles[0].innerText || '').trim();
            if (text.length >= 200) return cleanArticleText(text);
        }

        // Candidate 2: find the element whose direct <p> children have the most total text
        let best = null;
        let bestScore = 0;
        document.querySelectorAll('main, [role="main"], [role="article"], div, section').forEach(el => {
            const paras = el.querySelectorAll(':scope > p, :scope > div > p');
            if (paras.length < 3) return;
            let score = 0;
            paras.forEach(p => { score += (p.innerText || '').length; });
            if (score > bestScore) {
                bestScore = score;
                best = el;
            }
        });
        if (best && bestScore >= 400) {
            return cleanArticleText(best.innerText || '');
        }
    } catch (e) { /* ignore */ }
    return '';
}

function cleanArticleText(text) {
    return (text || '')
        .replace(/\n{3,}/g, '\n\n')
        .replace(/[ \t]+/g, ' ')
        .trim()
        .slice(0, 4000);
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
