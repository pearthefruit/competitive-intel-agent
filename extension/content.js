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

// Reply to popup requests with latest selection + article meta
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
        sendResponse({
            selection: lastSelectionText,
            selectionAt: lastSelectionAt,
            articleTitle, ogDesc, metaDesc, author, publishedTime,
        });
        return true;
    }
});
