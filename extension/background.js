// SignalVault Clipper — background service worker
// Registers a context menu item for right-click capture of selected text.

chrome.runtime.onInstalled.addListener(() => {
    chrome.contextMenus.create({
        id: 'signalvault-capture-selection',
        title: 'Capture selection to SignalVault',
        contexts: ['selection'],
    });
    chrome.contextMenus.create({
        id: 'signalvault-capture-page',
        title: 'Capture page to SignalVault',
        contexts: ['page'],
    });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
    if (!tab) return;
    if (info.menuItemId === 'signalvault-capture-selection' || info.menuItemId === 'signalvault-capture-page') {
        // Open the popup (same UI as toolbar click). Chrome doesn't let service
        // workers programmatically open popups, so open a window instead.
        chrome.action.openPopup?.().catch(() => {
            // Fallback for browsers without openPopup: open popup in a small window
            chrome.windows.create({
                url: chrome.runtime.getURL('popup.html'),
                type: 'popup',
                width: 400,
                height: 520,
            });
        });
    }
});
