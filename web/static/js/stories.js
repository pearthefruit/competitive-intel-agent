// ── Stories: unified list of chains + narratives (Phase 2) ──────────────
// Both are "connected stories" — chains are empirically discovered sequences,
// narratives are user-authored hypotheses. Click an item to open the
// appropriate existing editor (chain or narrative detail).

var _storiesCache = [];  // var: shared across module boundaries

function loadStories() {
    var container = document.getElementById('stories-list');
    if (container) container.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:12px">Loading stories…</div>';
    fetch('/api/stories')
        .then(function(r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(function(data) {
            _storiesCache = data.stories || [];
            renderStoriesList();
        })
        .catch(function(e) {
            console.error('[stories] load error:', e);
            if (container) container.innerHTML = '<div style="padding:24px;text-align:center;color:#ef4444;font-size:12px">Failed to load stories: ' + (e.message || e) + '</div>';
        });
}

function renderStoriesList() {
    var container = document.getElementById('stories-list');
    if (!container) return;

    if (!_storiesCache.length) {
        container.innerHTML = `
            <div class="signals-empty" style="padding:40px 20px;text-align:center">
                <div style="font-size:32px;margin-bottom:12px">🧵</div>
                <div>No threads yet</div>
                <div style="color:var(--text-muted);font-size:12px;margin-top:6px">
                    A thread connects signals into a story — either as a cause/effect chain
                    or a hypothesis to test.
                </div>
            </div>`;
        return;
    }

    // Split by origin for cleaner rendering (empirical first, hypothesis second)
    var empirical = _storiesCache.filter(function(s) { return s.origin === 'empirical'; });
    var hypothesis = _storiesCache.filter(function(s) { return s.origin === 'hypothesis'; });

    var html = '';
    if (empirical.length) {
        html += _storiesSectionHtml('Chains', '🔗', empirical);
    }
    if (hypothesis.length) {
        html += _storiesSectionHtml('Hypotheses', '💭', hypothesis);
    }
    container.innerHTML = html;
}

function _storiesSectionHtml(label, icon, items) {
    var header = '<div style="display:flex;align-items:center;gap:6px;font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;margin:6px 2px 8px">' +
        '<span>' + icon + '</span><span>' + label + '</span>' +
        '<span style="color:var(--text-muted);font-weight:400;text-transform:none;letter-spacing:0">(' + items.length + ')</span>' +
        '</div>';
    var cards = items.map(_storyCardHtml).join('');
    return '<div style="margin-bottom:14px">' + header + cards + '</div>';
}

function _storyCardHtml(s) {
    var isEmpirical = s.origin === 'empirical';
    var badgeColor = isEmpirical ? 'var(--accent)' : 'var(--purple)';
    var badgeBg = isEmpirical ? 'rgba(59,130,246,0.1)' : 'rgba(168,85,247,0.1)';
    var badgeBorder = isEmpirical ? 'rgba(59,130,246,0.3)' : 'rgba(168,85,247,0.3)';
    var originLabel = isEmpirical ? 'empirical' : 'hypothesis';
    var meta = s.thread_count + (s.thread_count === 1 ? ' thread' : ' threads');
    if (s.signal_count) meta += ' · ' + s.signal_count + ' signal' + (s.signal_count === 1 ? '' : 's');
    var confidence = s.confidence_score ? ' · confidence ' + s.confidence_score + '/10' : '';
    var thesis = s.thesis ? '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">' + escHtml(s.thesis) + '</div>' : '';

    return '<div class="story-card" onclick="_openStory(\'' + s.type + '\',' + s.id + ')" ' +
        'style="padding:10px 12px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;margin-bottom:6px;cursor:pointer;transition:all 0.15s" ' +
        'onmouseenter="this.style.borderColor=\'' + badgeColor + '\'" ' +
        'onmouseleave="this.style.borderColor=\'var(--border)\'">' +
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:2px">' +
            '<span style="font-size:9px;font-weight:700;padding:2px 6px;border-radius:8px;background:' + badgeBg + ';border:1px solid ' + badgeBorder + ';color:' + badgeColor + '">' + originLabel + '</span>' +
            '<span style="font-size:13px;font-weight:600;color:var(--text-primary);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escHtml(s.title || '(untitled)') + '</span>' +
        '</div>' +
        '<div style="font-size:10px;color:var(--text-muted);margin-top:2px">' + escHtml(meta + confidence) + '</div>' +
        thesis +
    '</div>';
}

function _openStory(type, id) {
    // Phase 3: both chains and hypothesis narratives live in causal_paths.
    // Route both to the chain editor.
    switchSignalTab('causal');
    setTimeout(function() {
        if (typeof _selectCausalChain === 'function') _selectCausalChain(id);
    }, 50);
}
