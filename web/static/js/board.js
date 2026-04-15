// ── Stacked board highlights ──
// Each highlight: {kind: 'entity'|'keyword', label, icon, threadIds: Set, key}
var _boardHighlights = [];  // var: accessible from base.html scripts outside this module
let _prevHighlightedIds = new Set();

function _hlKey(kind, label) { return `${kind}:${label.toLowerCase()}`; }

function _addBoardHighlight(hl) {
    // Toggle off if already exists
    const idx = _boardHighlights.findIndex(h => h.key === hl.key);
    if (idx !== -1) {
        _removeBoardHighlight(idx);
        return;
    }
    _boardHighlights.push(hl);
    _applyBoardHighlights();
    _renderHighlightPills();
}

function _removeBoardHighlight(idx) {
    _boardHighlights.splice(idx, 1);
    if (!_boardHighlights.length) {
        _clearBoardHighlight();
    } else {
        _applyBoardHighlights();
        _renderHighlightPills();
    }
}

function _clearBoardHighlight() {
    _boardHighlights = [];
    _prevHighlightedIds = new Set();
    _restoreHighlightPositions();
    document.querySelectorAll('.graph-node').forEach(n => {
        n.style.filter = '';
        n.style.pointerEvents = '';
        n.classList.remove('board-dimmed', 'board-highlighted');
        const badge = n.querySelector('.board-match-badge');
        if (badge) badge.remove();
    });
    document.querySelectorAll('.ent-chip-active').forEach(c => c.classList.remove('ent-chip-active'));
    _renderHighlightPills();
    const countEl = document.getElementById('board-search-count');
    if (countEl) countEl.textContent = '';
}

let _hlOriginalPositions = {}; // {nodeId: {x, y}} — saved before clustering
let _hlClusterAnim = null;
let _hlOriginalZoom = null; // saved zoom transform before auto-fit

function _applyBoardHighlights() {
    // Compute union of all highlighted thread IDs
    const unionIds = new Set();
    _boardHighlights.forEach(h => h.threadIds.forEach(id => unionIds.add(id)));

    // Track newly highlighted nodes for entrance animation
    const newlyHighlighted = new Set();
    unionIds.forEach(id => { if (!_prevHighlightedIds.has(id)) newlyHighlighted.add(id); });

    const allNodes = document.querySelectorAll('.graph-node');

    allNodes.forEach(n => {
        const nid = parseInt(n.dataset.nodeId);
        // Remove old badges
        const oldBadge = n.querySelector('.board-match-badge');
        if (oldBadge) oldBadge.remove();

        if (!_boardHighlights.length) {
            n.style.filter = '';
            n.classList.remove('board-dimmed', 'board-highlighted');
            n.style.pointerEvents = '';
            return;
        }

        if (unionIds.has(nid)) {
            const matchingHls = _boardHighlights.filter(h => h.threadIds.has(nid));
            const matchCount = matchingHls.length;
            const total = _boardHighlights.length;
            const glowIntensity = matchCount >= total ? '1.5' : '1.2';
            const glowColor = matchCount >= 2 ? 'rgba(6,182,212,0.7)' : 'rgba(168,85,247,0.5)';
            n.style.filter = `brightness(${glowIntensity}) drop-shadow(0 0 12px ${glowColor})`;
            n.classList.add('board-highlighted');

            // Entrance animation for newly highlighted nodes
            if (newlyHighlighted.has(nid)) {
                const circles = n.querySelectorAll('circle:not(.board-select-ring):not(.board-match-badge circle)');
                if (circles.length) {
                    circles.forEach(c => {
                        const orig = c.getAttribute('r');
                        if (orig) {
                            d3.select(c).transition().duration(150)
                                .attr('r', parseFloat(orig) * 1.15)
                              .transition().duration(200)
                                .attr('r', orig);
                        }
                    });
                } else {
                    // Multi-domain path arcs — flash brightness
                    n.style.transition = 'filter 0.15s';
                    n.style.filter = `brightness(2) drop-shadow(0 0 20px rgba(168,85,247,0.9))`;
                    setTimeout(() => {
                        n.style.filter = `brightness(${glowIntensity}) drop-shadow(0 0 12px ${glowColor})`;
                    }, 300);
                }
            }

            // Badge: show signal match count for single highlight, or N/M for multiple
            const sigMatchCount = matchingHls.reduce((sum, h) => sum + ((h.matchCounts && h.matchCounts[nid]) || 0), 0);
            const badgeText = total > 1 ? `${matchCount}/${total}` : (sigMatchCount > 0 ? `${sigMatchCount}` : null);
            const badgeColor = total > 1
                ? (matchCount >= total ? '#06b6d4' : matchCount >= 2 ? '#a855f7' : '#6b7280')
                : '#a855f7';

            if (badgeText) {
                const badge = document.createElementNS('http://www.w3.org/2000/svg', 'g');
                badge.classList.add('board-match-badge');
                const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                circle.setAttribute('cx', 18); circle.setAttribute('cy', -18);
                circle.setAttribute('r', 9);
                circle.setAttribute('fill', badgeColor);
                badge.appendChild(circle);
                const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                text.setAttribute('x', 18); text.setAttribute('y', -14);
                text.setAttribute('text-anchor', 'middle'); text.setAttribute('fill', '#fff');
                text.setAttribute('font-size', '10'); text.setAttribute('font-weight', '700');
                text.setAttribute('pointer-events', 'none');
                text.textContent = badgeText;
                badge.appendChild(text);
                n.appendChild(badge);
            }
        } else if (nid) {
            n.style.filter = 'brightness(0.25) saturate(0.3)';
            n.style.pointerEvents = 'none';
            n.classList.add('board-dimmed');
        }
    });

    // Raise highlighted nodes above dimmed ones (SVG z-order = DOM order)
    if (_boardHighlights.length) {
        allNodes.forEach(n => {
            const nid = parseInt(n.dataset.nodeId);
            if (unionIds.has(nid) && n.parentNode) {
                n.parentNode.appendChild(n); // re-append moves to end = top
            }
        });
    }

    // Cluster highlighted nodes toward their centroid + push dimmed nodes outward
    if (unionIds.size >= 2 && _boardHighlights.length) {
        _clusterHighlightedNodes(unionIds);
    }

    // Update tracking for next call
    _prevHighlightedIds = new Set(unionIds);
}

function _clusterHighlightedNodes(unionIds) {
    if (_hlClusterAnim) cancelAnimationFrame(_hlClusterAnim);

    // Only cluster if board tab is visible
    const graphTab = document.getElementById('sig-tab-graph');
    if (!graphTab || !graphTab.classList.contains('active')) return;

    const nodes = [];
    const allNids = [];
    document.querySelectorAll('.graph-node').forEach(n => {
        const nid = parseInt(n.dataset.nodeId);
        if (!nid || isNaN(nid)) return;
        allNids.push(nid);
        if (!unionIds.has(nid)) return;
        const transform = n.getAttribute('transform');
        if (!transform) return;
        const m = transform.match(/translate\(\s*([-\d.e+]+)[,\s]+([-\d.e+]+)\s*\)/);
        if (!m) return;
        const x = parseFloat(m[1]), y = parseFloat(m[2]);
        // Save original position if not already saved
        if (!_hlOriginalPositions[nid]) _hlOriginalPositions[nid] = { x, y };
        // Compute match relevance for ring assignment
        const matchCount = _boardHighlights.filter(h => h.threadIds.has(nid)).length;
        const d = n.__data__;
        const sigCount = d ? (d.signal_count || 1) : 1;
        const diameter = d ? ((d.type === 'narrative' ? 30 : Math.sqrt(sigCount) * 6 + 10) * 2) : 30;
        nodes.push({ el: n, nid, x, y, matchCount, sigCount, diameter });
    });

    console.log(`[cluster] ${nodes.length} highlighted nodes from ${allNids.length} total. unionIds:`, [...unionIds], 'matched nids:', nodes.map(n => n.nid));
    if (nodes.length < 2) return;

    // Sort by relevance: most highlight matches first, then by signal count
    nodes.sort((a, b) => b.matchCount - a.matchCount || b.sigCount - a.sigCount);

    // Assign nodes to concentric rings
    const rings = _assignRings(nodes);

    // Compute centroid of highlighted nodes
    const cx = nodes.reduce((s, n) => s + n.x, 0) / nodes.length;
    const cy = nodes.reduce((s, n) => s + n.y, 0) / nodes.length;

    // Compute ring radii from actual node sizes
    const padding = 12; // px between node edges (tightened)
    let cumulativeRadius = 0;
    const ringGap = 30; // gap between concentric rings (tightened)
    const ringTargets = rings.map((ringNodes, ri) => {
        const avgDiam = ringNodes.reduce((s, n) => s + n.diameter, 0) / ringNodes.length;
        const circumference = ringNodes.length * (avgDiam + padding);
        const radius = Math.max(ri === 0 ? 50 : 70, circumference / (2 * Math.PI));
        const r = ri === 0 ? radius : Math.max(radius, cumulativeRadius + ringGap + avgDiam / 2);
        cumulativeRadius = r;
        return { nodes: ringNodes, radius: r };
    });

    // Build target positions
    const targets = new Map(); // nid -> {tx, ty}
    ringTargets.forEach(ring => {
        ring.nodes.forEach((n, i) => {
            const angle = (i / ring.nodes.length) * Math.PI * 2 - Math.PI / 2; // start from top
            targets.set(n.nid, {
                tx: cx + Math.cos(angle) * ring.radius,
                ty: cy + Math.sin(angle) * ring.radius
            });
        });
    });

    // Push dimmed nodes out of the cluster area — only if they're inside it
    const outerRadius = cumulativeRadius + 20; // Tightened buffer
    const dimmedNodes = [];
    document.querySelectorAll('.graph-node.board-dimmed').forEach(n => {
        const nid = parseInt(n.dataset.nodeId);
        if (!nid) return;
        const transform = n.getAttribute('transform');
        if (!transform) return;
        const m = transform.match(/translate\(\s*([-\d.e+]+)[,\s]+([-\d.e+]+)\s*\)/);
        if (!m) return;
        const x = parseFloat(m[1]), y = parseFloat(m[2]);
        const dx = x - cx, dy = y - cy;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        // Only push if inside the cluster radius — leave distant nodes alone
        if (dist < outerRadius) {
            if (!_hlOriginalPositions[nid]) _hlOriginalPositions[nid] = { x, y };
            const pushDist = outerRadius + 30;
            dimmedNodes.push({ el: n, nid, x, y, tx: cx + (dx / dist) * pushDist, ty: cy + (dy / dist) * pushDist });
        }
    });

    // Animate
    let frame = 0;
    const totalFrames = 30;

    function animate() {
        frame++;
        const t = Math.min(frame / totalFrames, 1);
        const ease = t * (2 - t); // ease-out

        nodes.forEach(n => {
            const tgt = targets.get(n.nid);
            if (!tgt) return;
            const nx = n.x + (tgt.tx - n.x) * ease;
            const ny = n.y + (tgt.ty - n.y) * ease;
            n.el.setAttribute('transform', `translate(${nx},${ny})`);
            const d = n.el.__data__;
            if (d) { d.x = nx; d.y = ny; }
        });

        // Push dimmed nodes outward
        dimmedNodes.forEach(n => {
            const nx = n.x + (n.tx - n.x) * ease;
            const ny = n.y + (n.ty - n.y) * ease;
            n.el.setAttribute('transform', `translate(${nx},${ny})`);
        });

        if (frame < totalFrames) {
            _hlClusterAnim = requestAnimationFrame(animate);
        } else {
            _hlClusterAnim = null;
            _zoomToCluster(cx, cy, cumulativeRadius, nodes);
        }
    }
    _hlClusterAnim = requestAnimationFrame(animate);
}

// Split nodes into 1-3 concentric rings based on count
function _assignRings(sortedNodes) {
    const n = sortedNodes.length;
    if (n <= 8) return [sortedNodes];
    if (n <= 18) {
        const inner = Math.ceil(n * 0.4);
        return [sortedNodes.slice(0, inner), sortedNodes.slice(inner)];
    }
    // 3 rings: ~30% / ~35% / ~35%
    const r1 = Math.ceil(n * 0.3);
    const r2 = Math.ceil(n * 0.35);
    return [sortedNodes.slice(0, r1), sortedNodes.slice(r1, r1 + r2), sortedNodes.slice(r1 + r2)];
}

// Smooth zoom/pan to frame the cluster in the viewport
function _zoomToCluster(cx, cy, outerRadius, nodes) {
    const svgEl = document.querySelector('#sig-graph-container svg');
    if (!svgEl) return;
    const zb = svgEl.__zoomBehavior;
    if (!zb) return;

    // Save original zoom so we can restore on unhighlight.
    // ONLY save if we don't already have a baseline saved.
    // This prevents subsequent searches (while highights are active) from 
    // overwriting the 'home' position with a zoomed-in one.
    if (!_hlOriginalZoom) {
        _hlOriginalZoom = d3.zoomTransform(svgEl);
    }

    const svgRect = svgEl.getBoundingClientRect();
    const viewW = svgRect.width;
    const viewH = svgRect.height;
    if (!viewW || !viewH) return;

    // Largest node diameter for margin
    const maxDiam = nodes.reduce((m, n) => Math.max(m, n.diameter), 0);
    // clusterSpan is the diameter of the cluster edge-to-edge
    const clusterSpan = (outerRadius + maxDiam / 2) * 2;

    // Target scale: cluster fills ~90% of viewport (tighter framing)
    const targetScale = Math.min(viewW * 0.9 / clusterSpan, viewH * 0.9 / clusterSpan);
    // Clamp to zoom extent
    const scale = Math.max(0.3, Math.min(targetScale, 3));
    console.log(`[zoom] clustering around (${Math.round(cx)},${Math.round(cy)}) span=${Math.round(clusterSpan)} scale=${scale.toFixed(2)}`);

    const tx = viewW / 2 - cx * scale;
    const ty = viewH / 2 - cy * scale;

    const svg = d3.select(svgEl);
    const transform = d3.zoomIdentity.translate(tx, ty).scale(scale);
    svg.transition().duration(400).call(zb.transform, transform);
}

function _restoreHighlightPositions() {
    if (_hlClusterAnim) { cancelAnimationFrame(_hlClusterAnim); _hlClusterAnim = null; }

    const entries = Object.entries(_hlOriginalPositions);
    if (!entries.length) return;

    // Restore zoom transform
    if (_hlOriginalZoom) {
        const svgEl = document.querySelector('#sig-graph-container svg');
        if (svgEl && svgEl.__zoomBehavior) {
            d3.select(svgEl).transition().duration(300)
                .call(svgEl.__zoomBehavior.transform, _hlOriginalZoom);
        }
        _hlOriginalZoom = null;
    }

    let frame = 0;
    const totalFrames = 20;

    // Read current positions
    const current = {};
    entries.forEach(([nid]) => {
        const el = document.querySelector(`.graph-node[data-node-id="${nid}"]`);
        if (!el) return;
        const m = el.getAttribute('transform')?.match(/translate\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)/);
        if (m) current[nid] = { el, x: parseFloat(m[1]), y: parseFloat(m[2]) };
    });

    function animate() {
        frame++;
        const t = Math.min(frame / totalFrames, 1);
        const ease = t * (2 - t);

        entries.forEach(([nid, orig]) => {
            const c = current[nid];
            if (!c) return;
            const nx = c.x + (orig.x - c.x) * ease;
            const ny = c.y + (orig.y - c.y) * ease;
            c.el.setAttribute('transform', `translate(${nx},${ny})`);
            // Sync D3 data back to original position
            const d = c.el.__data__;
            if (d) { d.x = nx; d.y = ny; }
        });

        if (frame < totalFrames) {
            requestAnimationFrame(animate);
        } else {
            _hlOriginalPositions = {};
        }
    }
    requestAnimationFrame(animate);
}

function _renderHighlightPills() {
    const tray = document.getElementById('board-highlight-pills');
    const sel = document.getElementById('sig-graph-selection');
    if (!tray) return;
    if (!_boardHighlights.length) {
        tray.innerHTML = '';
        tray.style.display = 'none';
        if (sel) sel.innerHTML = '';
        return;
    }
    tray.style.display = 'flex';

    // Compute union of highlighted thread IDs
    const unionIds = new Set();
    _boardHighlights.forEach(h => h.threadIds.forEach(id => unionIds.add(id)));

    // Pills
    let html = _boardHighlights.map((h, i) => {
        const color = h.kind === 'keyword' ? '#a855f7' : '#06b6d4';
        return `<span class="board-hl-pill" style="display:inline-flex;align-items:center;gap:4px;padding:3px 8px;background:${color}18;border:1px solid ${color}44;border-radius:12px;font-size:10px;color:${color};font-weight:600;white-space:nowrap">
            ${h.icon} ${escHtml(h.label)} <span style="font-weight:400;color:var(--text-muted)">${h.threadIds.size}</span>
            <span onclick="_removeBoardHighlight(${i})" style="cursor:pointer;margin-left:2px;font-size:12px;color:var(--text-muted);line-height:1" title="Remove">&times;</span>
        </span>`;
    }).join('');

    // Action buttons when 2+ threads highlighted
    if (unionIds.size >= 2) {
        const btnBase = 'padding:3px 8px;border-radius:12px;font-size:10px;font-weight:600;cursor:pointer;white-space:nowrap;border:none;';
        if (unionIds.size <= 6) {
            html += `<span onclick="_linkHighlighted()" style="${btnBase}background:linear-gradient(135deg,#06b6d4,#a855f7);color:#fff" title="Create connections between highlighted threads">🔗 Link ${unionIds.size}</span>`;
        }
        const total = _boardHighlights.length;
        if (total >= 2) {
            // Compute match tiers — group threads by how many highlights they match
            const tierCounts = {};
            unionIds.forEach(nid => {
                const mc = _boardHighlights.filter(h => h.threadIds.has(nid)).length;
                tierCounts[mc] = (tierCounts[mc] || 0) + 1;
            });
            // Show tiered brainstorm buttons (highest tier first)
            const tiers = Object.keys(tierCounts).map(Number).sort((a, b) => b - a);
            tiers.forEach(tier => {
                const count = tierCounts[tier];
                if (count < 2) return; // need at least 2 to brainstorm
                const intensity = tier / total; // 0..1
                const bg = intensity >= 1 ? 'background:linear-gradient(135deg,#06b6d4,#a855f7)'
                    : intensity >= 0.5 ? 'background:linear-gradient(135deg,var(--accent),var(--purple))'
                    : 'background:var(--bg-tertiary);border:1px solid var(--border)';
                const color = intensity >= 0.5 ? 'color:#fff' : 'color:var(--text-muted)';
                html += `<span onclick="_brainstormHighlighted(${tier})" style="${btnBase}${bg};${color}" title="Brainstorm threads matching ${tier}/${total} highlights">🧠 ${tier}/${total} (${count})</span>`;
            });
        } else {
            html += `<span onclick="_brainstormHighlighted()" style="${btnBase}background:linear-gradient(135deg,var(--accent),var(--purple));color:#fff" title="Brainstorm connections between highlighted threads">🧠 Brainstorm ${unionIds.size}</span>`;
        }
    }

    html += `<span onclick="_clearBoardHighlight();document.getElementById('board-keyword-search').value=''" style="display:inline-flex;align-items:center;gap:3px;padding:3px 8px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);border-radius:12px;font-size:10px;color:#ef4444;font-weight:600;cursor:pointer;white-space:nowrap" title="Clear all highlights">✕ Clear</span>`;
    tray.innerHTML = html;
    if (sel) sel.innerHTML = `<span style="color:var(--text-muted)">${_boardHighlights.length} filter${_boardHighlights.length > 1 ? 's' : ''} · ${unionIds.size} threads</span>`;
}

function _getHighlightedThreadIds() {
    const ids = new Set();
    _boardHighlights.forEach(h => h.threadIds.forEach(id => ids.add(id)));
    return ids;
}

function _getHighlightContext() {
    return _boardHighlights.map(h => h.label).join(', ');
}

function _linkHighlighted() {
    const ids = [..._getHighlightedThreadIds()];
    if (ids.length < 2) return;

    // Safety limit — linking N nodes creates N*(N-1)/2 pairs
    if (ids.length > 5) {
        _showToast(`Too many threads (${ids.length}) — select 5 or fewer to link. Use brainstorm for larger groups.`, 'warn', 5000);
        return;
    }

    const context = _getHighlightContext();
    const sel = document.getElementById('sig-graph-selection');
    const pairs = [];
    for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
            pairs.push([ids[i], ids[j]]);
        }
    }

    _showConfirm(`Create ${pairs.length} connections between ${ids.length} threads?`, () => {
        if (sel) sel.innerHTML = `<span style="color:var(--accent)">🔗 Linking ${pairs.length} pair${pairs.length > 1 ? 's' : ''}...</span>`;

    // Create connections with highlight labels as context for LLM
    Promise.all(pairs.map(([a, b]) =>
        fetch('/api/board/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: a, target: b, label: context })
        }).then(r => r.json())
    )).then(results => {
        const labels = results.filter(r => r.label).map(r => r.label);
        if (sel) sel.innerHTML = `<span style="color:var(--green)">✓ ${pairs.length} connection${pairs.length > 1 ? 's' : ''} created</span>`;
        // Reload board to show new links
        loadBoard();
        setTimeout(() => { if (sel) sel.innerHTML = ''; }, 3000);
    });
    }); // end _showConfirm
}

function _brainstormHighlighted(matchFilter) {
    let ids;
    if (matchFilter != null && _boardHighlights.length >= 2) {
        // Filter to threads matching exactly matchFilter highlights
        ids = new Set();
        const allIds = _getHighlightedThreadIds();
        allIds.forEach(nid => {
            const mc = _boardHighlights.filter(h => h.threadIds.has(nid)).length;
            if (mc === matchFilter) ids.add(nid);
        });
    } else {
        ids = _getHighlightedThreadIds();
    }
    if (ids.size < 2) return;

    // Set board selected IDs to highlighted threads and open brainstorm
    _selectedThreadIds.clear();
    ids.forEach(id => _selectedThreadIds.add(id));

    // Update visual selection on graph nodes
    d3.selectAll('.graph-node').classed('selected', d => _selectedThreadIds.has(d.id));

    // Show brainstorm button and open
    const btn = document.getElementById('sig-brainstorm-btn');
    if (btn) btn.style.display = '';
    openBrainstormMode();
}

function _highlightEntityOnBoard(entityType, entityValue) {
    // Open Discovery Drawer to explore this entity
    const crumbNode = { type: 'entity', entityType, entityValue, label: entityValue };
    _openDiscoveryDrawer(crumbNode);
    _fetchDiscoveryResults(crumbNode);
}

function _boardKeywordSearch(query) {
    query = (query || '').trim();
    if (!query || query.length < 2) return;

    const key = _hlKey('keyword', query);
    // Toggle if already active
    const existing = _boardHighlights.findIndex(h => h.key === key);
    if (existing !== -1) {
        _removeBoardHighlight(existing);
        return;
    }

    const sel = document.getElementById('sig-graph-selection');
    if (sel) sel.innerHTML = `<span style="color:var(--accent)">Searching "${escHtml(query)}"...</span>`;

    fetch(`/api/signals/search?q=${encodeURIComponent(query)}`)
        .then(r => {
            if (!r.ok) throw new Error(`${r.status}`);
            return r.json();
        })
        .then(data => {
            if (data.error) {
                if (sel) sel.innerHTML = `<span style="color:var(--red)">${escHtml(data.error)}</span>`;
                return;
            }
            const threadIds = new Set((data.thread_matches || []).map(m => m.thread_id));
            const matchCounts = {};
            (data.thread_matches || []).forEach(m => { matchCounts[m.thread_id] = m.match_count; });
            _addBoardHighlight({
                kind: 'keyword', label: query, icon: '🔍',
                threadIds, matchCounts, key
            });
            // Clear the input for next keyword
            const input = document.getElementById('board-keyword-search');
            if (input) input.value = '';
        })
        .catch(err => {
            if (sel) sel.innerHTML = `<span style="color:var(--red)">Search failed — restart server to enable keyword search</span>`;
        });
}

function _proposeThreadSplit(threadId) {
    const btn = document.getElementById('split-thread-btn');
    if (btn) { btn.textContent = '✂️ Analyzing...'; btn.disabled = true; }

    fetch(`/api/signals/threads/${threadId}/propose-split`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (btn) { btn.textContent = '✂️ Split thread'; btn.disabled = false; }
            if (data.error) { if (btn) btn.textContent = data.error; return; }

            const splits = data.proposed_splits || [];
            const remaining = data.remaining;

            // Render split preview below the actions
            const actionsDiv = btn ? btn.parentElement : null;
            if (!actionsDiv) return;

            let previewHtml = `<div id="split-preview" style="margin-top:12px;padding:12px;background:var(--bg-primary);border:1px solid var(--purple);border-radius:10px">
                <div style="font-size:11px;font-weight:700;color:var(--purple);margin-bottom:10px">Proposed Split (${splits.length} sub-threads)</div>`;

            splits.forEach((s, i) => {
                previewHtml += `<div style="padding:8px 10px;background:var(--bg-tertiary);border-radius:6px;margin-bottom:6px;border-left:3px solid var(--purple)">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <div style="font-size:12px;font-weight:600;color:var(--text-primary)">${escHtml(s.title)}</div>
                        <span style="font-size:9px;color:var(--text-muted)">${s.signal_ids.length} signals</span>
                    </div>
                    <div style="font-size:10px;color:var(--text-muted);margin-top:3px">${escHtml(s.rationale || '')}</div>
                </div>`;
            });

            if (remaining && remaining.signal_ids && remaining.signal_ids.length) {
                previewHtml += `<div style="padding:8px 10px;background:var(--bg-tertiary);border-radius:6px;margin-bottom:6px;border-left:3px solid var(--border)">
                    <div style="font-size:12px;font-weight:600;color:var(--text-muted)">${escHtml(remaining.title || 'Remaining')}</div>
                    <div style="font-size:10px;color:var(--text-muted);margin-top:3px">${remaining.signal_ids.length} signals stay in original thread</div>
                </div>`;
            }

            previewHtml += `<div style="display:flex;gap:6px;margin-top:10px">
                <button onclick="_executeThreadSplit(${threadId})" style="padding:6px 14px;background:var(--purple);border:none;border-radius:6px;color:#fff;font-size:11px;font-weight:600;cursor:pointer">✂️ Execute Split</button>
                <button onclick="document.getElementById('split-preview').remove()" style="padding:6px 10px;background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;cursor:pointer">Cancel</button>
            </div></div>`;

            // Store splits data for execution
            window._pendingSplits = splits;

            const existing = document.getElementById('split-preview');
            if (existing) existing.remove();
            actionsDiv.insertAdjacentHTML('afterend', previewHtml);
        })
        .catch(() => { if (btn) { btn.textContent = '✂️ Split thread'; btn.disabled = false; } });
}

function _executeThreadSplit(threadId) {
    const splits = window._pendingSplits || [];
    if (!splits.length) return;

    const execBtn = document.querySelector('#split-preview button');
    if (execBtn) { execBtn.textContent = '✂️ Splitting...'; execBtn.disabled = true; }

    fetch(`/api/signals/threads/${threadId}/execute-split`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ splits })
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok) {
            window._pendingSplits = null;
            openThreadDetail(threadId);
            loadBoard();
            loadSignals();
        }
    });
}

function _deleteThread(threadId) {
    _showConfirm('Delete this thread? Signals will be unlinked but not deleted.', () => {
        fetch('/api/signals/threads/' + threadId, { method: 'DELETE' })
            .then(r => r.json())
            .then(() => {
                closeSignalDetail();
                loadSignals();
                if (_signalTab === 'graph') loadBoard();
            });
    }, { danger: true, confirmText: 'Delete' });
}

// ─── Thread Lab — moved to thread-lab.js ─────────────────────────────────────
// All _lab* functions, _openThreadLab, _openOrganizeLab now live in thread-lab.js

// ─── Thread actions ───────────────────────────────────────────────────────────

function _threadActionResearch(companyName) {
    switchModule('research');
    _prefillResearchChat(companyName);
}

function _threadActionDiscover(niche) {
    switchModule('prospecting');
    const input = document.getElementById('prospect-niche-input');
    if (input) input.value = niche;
}

function _threadActionSearchMore(query, patternId) {
    // Run a targeted search and link results to this pattern
    const btn = event.target.closest('button');
    const actionsDiv = btn ? btn.parentElement : null;
    if (btn) { btn.textContent = '📡 Searching...'; btn.disabled = true; }

    fetch('/api/signals/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, pattern_id: patternId })
    })
    .then(r => r.json())
    .then(data => {
        if (btn) {
            const parts = [];
            if (data.new_inserted > 0) parts.push(`${data.new_inserted} new`);
            if (data.linked_to_pattern > 0) parts.push(`${data.linked_to_pattern} linked`);
            if (data.filtered_stale > 0) parts.push(`${data.filtered_stale} stale filtered`);
            btn.textContent = parts.length ? `✓ ${parts.join(', ')}` : '✓ No new signals';
            btn.style.color = data.linked_to_pattern > 0 ? 'var(--green)' : 'var(--text-muted)';
        }
        // Show audit trail below the button
        if (actionsDiv && data.audit) {
            const auditEl = document.createElement('div');
            auditEl.style.cssText = 'margin-top:8px;padding:10px 12px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:8px;font-size:10px';
            auditEl.innerHTML = `<div style="font-weight:700;color:var(--text-secondary);margin-bottom:6px">Search Audit</div>` +
                (data.audit.sources || []).map(s =>
                    `<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border)">
                        <span style="color:var(--text-secondary)">${escHtml(s.source)}</span>
                        <span style="color:var(--text-muted)"><span class="exec-query-chip">${escHtml(s.query)}</span> ${s.raw} found → ${s.after_filter} fresh</span>
                    </div>`
                ).join('') +
                (data.filtered_stale > 0 ? `<div style="margin-top:4px;color:var(--text-muted)">🕐 ${data.filtered_stale} article(s) older than 30 days filtered out</div>` : '');
            actionsDiv.appendChild(auditEl);
        }
        // Reload feed and refresh this pattern's detail
        loadSignals();
        if (_signalTab === 'graph') loadBoard();
        if (patternId) setTimeout(() => openThreadDetail(patternId), 500);
    })
    .catch(() => {
        if (btn) { btn.textContent = 'Search failed'; btn.style.color = 'var(--red)'; }
    });
}

function _threadActionSearchInternal(threadId, threadTitle) {
    const btn = event.target.closest('button');
    const actionsDiv = btn ? btn.parentElement : null;
    if (btn) { btn.disabled = true; }

    const stopWords = new Set(['the', 'and', 'for', 'with', 'from', 'this', 'that', 'are', 'was', 'has', 'have', 'will', 'not', 'but', 'all', 'its', 'into', 'amid', 'over', 'under', 'about', 'between', 'after', 'before', 'during', 'while', 'amid']);
    const keywords = threadTitle.toLowerCase()
        .split(/[\s\-_,./]+/)
        .filter(w => w.length >= 3 && !stopWords.has(w));

    if (!keywords.length) {
        if (btn) btn.textContent = '🔍 No keywords extracted';
        return;
    }

    const matches = (_signalsCache || []).filter(sig => {
        const text = ((sig.title || '') + ' ' + (sig.body || '')).toLowerCase();
        return keywords.some(kw => text.includes(kw));
    }).slice(0, 15);

    if (btn) btn.textContent = matches.length ? `🔍 ${matches.length} matching signals found` : '🔍 No matches in existing signals';

    if (!matches.length || !actionsDiv) return;

    const resultsEl = document.createElement('div');
    resultsEl.style.cssText = 'margin-top:8px;padding:10px 12px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:8px';
    resultsEl.innerHTML = `<div style="font-weight:700;color:var(--text-secondary);margin-bottom:6px;font-size:10px">Matching existing signals</div>` +
        matches.map(s => `<div id="isig-${threadId}-${s.id}" style="display:flex;align-items:start;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px solid var(--border)">
            <span style="font-size:11px;color:var(--text-secondary);line-height:1.4;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(s.title)}">${escHtml(s.title)}</span>
            <button onclick="_addSingleSignalToThread(${s.id},${threadId},this)" style="flex-shrink:0;padding:2px 8px;background:var(--accent);border:none;border-radius:4px;color:white;font-size:10px;font-weight:700;cursor:pointer">+</button>
        </div>`).join('');
    actionsDiv.appendChild(resultsEl);
}

function _addSingleSignalToThread(sigId, threadId, btn) {
    if (btn) { btn.textContent = '…'; btn.disabled = true; }
    fetch('/api/signals/review-queue/bulk-assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_ids: [sigId], thread_id: threadId })
    }).then(r => r.json()).then(() => {
        if (btn) { btn.textContent = '✓'; btn.style.background = 'var(--green)'; }
        const row = document.getElementById(`isig-${threadId}-${sigId}`);
        if (row) row.style.opacity = '0.5';
        loadSignals();
        if (_signalTab === 'graph') loadBoard();
    }).catch(() => {
        if (btn) { btn.textContent = '✗'; btn.disabled = false; }
    });
}

function openEntityPopover(event, entityType, entityValue) {
    event.stopPropagation();
    // Remove any existing popover
    document.querySelectorAll('.ent-popover').forEach(p => p.remove());

    const icon = {company: '🏢', sector: '📊', geography: '📍'}[entityType] || '🔹';

    // Create popover shell with loading state
    const pop = document.createElement('div');
    pop.className = 'ent-popover';
    pop.innerHTML = `
        <div class="ent-popover-header">
            <span style="font-size:18px">${icon}</span>
            <div>
                <div class="ent-popover-title">${escHtml(entityValue)}</div>
                <div class="ent-popover-subtitle">${escHtml(entityType)}</div>
            </div>
        </div>
        <div class="ent-popover-body" style="text-align:center;padding:20px;color:var(--text-muted);font-size:11px">Loading...</div>
    `;
    document.body.appendChild(pop);

    // Position near the click
    const rect = event.target.getBoundingClientRect();
    let top = rect.bottom + 6;
    let left = rect.left;
    // Keep within viewport
    if (top + 300 > window.innerHeight) top = rect.top - 300;
    if (left + 360 > window.innerWidth) left = window.innerWidth - 370;
    pop.style.top = Math.max(8, top) + 'px';
    pop.style.left = Math.max(8, left) + 'px';

    // Close on outside click
    setTimeout(() => {
        document.addEventListener('click', function _close(e) {
            if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener('click', _close); }
        });
    }, 50);

    // Fetch context
    fetch(`/api/signals/entity-context/${encodeURIComponent(entityType)}/${encodeURIComponent(entityValue)}`)
        .then(r => r.json())
        .then(ctx => {
            let bodyHtml = '';
            let actionsHtml = '';

            if (entityType === 'company') {
                if (ctx.dossier) {
                    const d = ctx.dossier;
                    bodyHtml = `
                        <div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:6px">${escHtml(d.company_name)}</div>
                        ${d.sector ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">Sector: ${escHtml(d.sector)}</div>` : ''}
                        ${d.description ? `<div style="font-size:11px;color:var(--text-secondary);margin-bottom:8px;line-height:1.4">${escHtml(d.description.substring(0, 200))}</div>` : ''}
                        ${d.analyses && d.analyses.length ? `<div style="font-size:10px;color:var(--text-muted)">${d.analyses.length} analyses: ${d.analyses.map(a => a.analysis_type).join(', ')}</div>` : ''}
                    `;
                    actionsHtml = `
                        <button class="ent-popover-btn ent-popover-btn-primary" onclick="document.querySelector('.ent-popover').remove();switchModule('research')">Open in Research →</button>
                    `;
                } else {
                    bodyHtml = `<div style="font-size:11px;color:var(--text-muted)">No dossier exists yet for this company.</div>`;
                    actionsHtml = `
                        <button class="ent-popover-btn ent-popover-btn-primary" onclick="document.querySelector('.ent-popover').remove();switchModule('research');_prefillResearchChat('${escHtml(entityValue.replace(/'/g, "\\'"))}')">Research →</button>
                        <button class="ent-popover-btn" onclick="document.querySelector('.ent-popover').remove();switchModule('prospecting');document.getElementById('prospect-niche-input').value='${escHtml(entityValue)}'">Discover →</button>
                    `;
                }
            } else if (entityType === 'sector') {
                if (ctx.campaigns && ctx.campaigns.length) {
                    bodyHtml = `<div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">${ctx.campaigns.length} related campaign(s):</div>` +
                        ctx.campaigns.map(c => `<div style="font-size:11px;padding:4px 0;border-bottom:1px solid var(--border)">${escHtml(c.niche)} <span style="color:var(--text-muted)">(${c.status})</span></div>`).join('');
                } else {
                    bodyHtml = `<div style="font-size:11px;color:var(--text-muted)">No campaigns match this sector yet.</div>`;
                }
                actionsHtml = `
                    <button class="ent-popover-btn ent-popover-btn-primary" onclick="document.querySelector('.ent-popover').remove();switchModule('prospecting');document.getElementById('prospect-niche-input').value='${escHtml(entityValue)}'">Explore as Niche →</button>
                `;
            } else if (entityType === 'geography') {
                bodyHtml = `<div style="font-size:11px;color:var(--text-muted)">Mentioned in ${ctx.signal_count} signal(s).</div>`;
                actionsHtml = `
                    <button class="ent-popover-btn" onclick="document.querySelector('.ent-popover').remove();document.getElementById('signals-search').value='${escHtml(entityValue)}';renderActiveSignalTab()">Filter feed →</button>
                `;
            }

            pop.querySelector('.ent-popover-body').innerHTML = bodyHtml;
            if (actionsHtml) {
                const actDiv = document.createElement('div');
                actDiv.className = 'ent-popover-actions';
                actDiv.innerHTML = actionsHtml;
                pop.appendChild(actDiv);
            }

            // Add signal count footer
            if (ctx.signal_count > 0) {
                const footer = document.createElement('div');
                footer.style.cssText = 'padding:6px 16px 10px;font-size:10px;color:var(--text-muted)';
                footer.textContent = `Appears in ${ctx.signal_count} signal(s)`;
                pop.appendChild(footer);
            }
        })
        .catch(() => {
            pop.querySelector('.ent-popover-body').innerHTML = '<div style="color:var(--red);font-size:11px">Failed to load context</div>';
        });
}

// ===================== GRAPH VIEW =====================

var _graphData = null;  // var: accessible from base.html scripts outside this module
let _graphSimulation = null;
var _selectedThreadIds = new Set();  // var: accessible from base.html scripts outside this module
let _graphMode = 'patterns'; // 'patterns' or 'signals'
let _zoomedPatternId = null;

let _boardPhysicsOn = false;
let _boardPhysicsSim = null;

function _toggleBoardPhysics() {
    _boardPhysicsOn = !_boardPhysicsOn;
    const btn = document.getElementById('board-physics-btn');
    btn.style.background = _boardPhysicsOn ? 'var(--accent)' : 'var(--bg-tertiary)';
    btn.style.color = _boardPhysicsOn ? '#fff' : 'var(--text-muted)';
    btn.style.borderColor = _boardPhysicsOn ? 'var(--accent)' : 'var(--border)';

    if (_boardPhysicsOn) {
        loadBoard(); // re-render with physics enabled
    } else {
        // Stop simulation and freeze current positions
        if (_boardPhysicsSim) {
            _boardPhysicsSim.stop();
            _boardPhysicsSim = null;
        }
        // Save ALL node positions from the simulation (not just pinned)
        // Read positions directly from DOM transforms (most reliable source)
        const allPositions = [];
        document.querySelectorAll('.graph-node').forEach(el => {
            const nid = parseInt(el.dataset.nodeId);
            const ntype = el.dataset.nodeType || 'thread';
            const transform = el.getAttribute('transform');
            if (!transform || !nid) return;
            const m = transform.match(/translate\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)/);
            if (m) {
                allPositions.push({
                    node_type: ntype,
                    node_id: nid,
                    x: parseFloat(m[1]),
                    y: parseFloat(m[2]),
                    pinned: true,
                });
            }
        });
        if (allPositions.length) {
            console.log(`[physics] Freezing ${allPositions.length} node positions`);
            fetch('/api/board/positions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ positions: allPositions })
            }).then(() => loadBoard());
            return;
        }
        loadBoard();
    }
}

function loadGraph() {
    const params = new URLSearchParams();
    const minSig = document.getElementById('gf-min-signals');
    const limit = document.getElementById('gf-limit');
    const domain = document.getElementById('gf-domain');
    const status = document.getElementById('gf-status');
    if (minSig && parseInt(minSig.value) > 0) params.set('min_signals', minSig.value);
    if (limit) params.set('limit', limit.value || '200');
    if (domain && domain.value) params.set('domain', domain.value);
    if (status) params.set('status', status.value || 'all');
    const qs = params.toString();
    fetch('/api/signals/graph' + (qs ? '?' + qs : ''))
        .then(r => r.json())
        .then(data => {
            _graphData = data;
            if (data.nodes.length) renderGraph(data);
            else {
                const empty = document.getElementById('signals-graph-empty');
                if (empty) empty.style.display = 'flex';
                d3.select('#sig-graph-svg').style('display', 'none');
            }
        })
        .catch(e => console.error('[graph] load error:', e));
}

function renderGraph(data) {
    const container = document.getElementById('sig-graph-container');
    const svg = d3.select('#sig-graph-svg');
    const empty = document.getElementById('signals-graph-empty');
    const controls = document.getElementById('sig-graph-controls');

    const searchBar = document.getElementById('board-search-bar');
    if (!data.nodes.length) { empty.style.display = 'flex'; if (searchBar) searchBar.style.display = 'none'; return; }
    empty.style.display = 'none';
    svg.style('display', 'block');
    controls.style.display = 'flex';
    if (searchBar) searchBar.style.display = 'flex';

    // Show unassigned signal count
    const unassigned = data.unassigned_signals || 0;
    const sel = document.getElementById('sig-graph-selection');
    if (sel && unassigned > 0 && _selectedThreadIds.size === 0) {
        sel.innerHTML = `<span style="color:var(--text-muted)">${data.assigned_signals || 0} signals in ${data.nodes.length} threads · </span><span style="color:var(--purple)">${unassigned} unassigned</span> <span style="color:var(--text-muted);font-size:10px;cursor:pointer" onclick="runResynthesize()" title="Run thread detection on unassigned signals">(re-detect)</span>`;
    }

    // Clear previous
    svg.selectAll('*').remove();
    _selectedThreadIds.clear();
    _updateBrainstormBtn();

    const width = container.clientWidth;
    const height = container.clientHeight - 40; // leave room for controls

    svg.attr('viewBox', [0, 0, width, height]);

    const zoomGroup = svg.append('g').attr('class', 'graph-zoom-group');
    const zoomBehavior = d3.zoom()
        .scaleExtent([0.3, 4])
        .filter(event => {
            if (event.type === 'wheel') return true;
            // Check all ancestors for graph-node class
            let el = event.target;
            while (el && el !== svg.node()) {
                if (el.classList && el.classList.contains('graph-node')) return false;
                el = el.parentNode;
            }
            return !event.button;
        })
        .on('zoom', (event) => zoomGroup.attr('transform', event.transform));
    svg.call(zoomBehavior);
    svg.on('dblclick.zoom', null);
    svg.node().__zoomBehavior = zoomBehavior;

    // Build D3 force simulation
    const nodes = data.nodes.map(d => ({...d}));
    const links = data.edges.map(d => ({...d}));

    _graphSimulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(70))
        .force('charge', d3.forceManyBody().strength(-80))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(d => Math.sqrt(d.signal_count || 1) * 6 + 16));

    // Edges (inside zoom group)
    const link = zoomGroup.append('g')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('class', d => 'graph-edge' + (d.manual ? ' manual' : ''))
        .attr('stroke-width', d => Math.max(1, d.weight * 1.5));

    // Edge labels
    const linkLabel = zoomGroup.append('g')
        .selectAll('text')
        .data(links)
        .join('text')
        .attr('class', 'graph-edge-label')
        .attr('text-anchor', 'middle')
        .text(d => d.shared_entities.slice(0, 2).map(e => e.name).join(', '));

    // Nodes (inside zoom group)
    const node = zoomGroup.append('g')
        .selectAll('g')
        .data(nodes)
        .join('g')
        .attr('class', 'graph-node')
        .call(d3.drag()
            .on('start', (event, d) => { d.fx = d.x; d.fy = d.y; d._dragMoved = false; })
            .on('drag', (event, d) => {
                if (!d._dragMoved) { d._dragMoved = true; if (!event.active) _graphSimulation.alphaTarget(0.3).restart(); }
                d.fx = event.x; d.fy = event.y;
            })
            .on('end', (event, d) => { if (!event.active) _graphSimulation.alphaTarget(0); d.fx = null; d.fy = null; })
        )
        .on('click', (event, d) => {
            event.stopPropagation();
            if (event.shiftKey) {
                _toggleThreadSelection(d.id);
            } else {
                openThreadDetail(d.id);
            }
        })
        .on('dblclick', (event, d) => {
            event.stopPropagation();
            _zoomIntoPattern(d.id);
            openThreadDetail(d.id);
        });

    const _lifecycle = d => (d.momentum && d.momentum.lifecycle) || 'active';
    const nodeR = d => {
        const base = Math.sqrt(d.signal_count || 1) * 6 + 10;
        const lc = _lifecycle(d);
        if (lc === 'dormant') return base * 0.6;
        if (lc === 'cooling') return base * 0.8;
        return base;
    };
    const nodeOpacity = d => {
        const lc = _lifecycle(d);
        if (lc === 'dormant') return 0.3;
        if (lc === 'cooling') return 0.5;
        return 0.75;
    };

    // Selection ring (outer glow) — rendered first so it's behind the main circle
    node.append('circle')
        .attr('class', 'select-ring')
        .attr('r', d => nodeR(d) + 6)
        .attr('fill', 'none')
        .attr('stroke', '#fff')
        .attr('stroke-width', 2)
        .attr('stroke-dasharray', '4 3');

    // Main node: donut if noise exists, solid circle otherwise
    const arc = d3.arc();
    node.each(function(d) {
        const g = d3.select(this);
        const r = nodeR(d);
        const color = _DOMAIN_COLORS[_parseDomains(d.domain)[0]] || '#6b7280';
        const op = nodeOpacity(d);
        const total = d.total_count || d.signal_count || 1;
        const noise = d.noise_count || 0;
        const sigRatio = total > 0 ? (total - noise) / total : 1;

        if (noise > 0) {
            // Donut: signal portion in domain color, noise in dark
            const thickness = Math.max(4, r * 0.3);
            // Signal arc
            g.append('path')
                .attr('class', 'node-circle')
                .attr('d', arc({ innerRadius: r - thickness, outerRadius: r, startAngle: 0, endAngle: sigRatio * 2 * Math.PI }))
                .attr('fill', color)
                .attr('fill-opacity', op);
            // Noise arc
            g.append('path')
                .attr('d', arc({ innerRadius: r - thickness, outerRadius: r, startAngle: sigRatio * 2 * Math.PI, endAngle: 2 * Math.PI }))
                .attr('fill', '#ef4444')
                .attr('fill-opacity', op * 0.5);
            // Inner fill
            g.append('circle')
                .attr('r', r - thickness)
                .attr('fill', color)
                .attr('fill-opacity', op * 0.2);
        } else {
            g.append('circle')
                .attr('class', 'node-circle')
                .attr('r', r)
                .attr('fill', color)
                .attr('fill-opacity', op);
        }
    });

    // Selection checkmark
    node.append('text')
        .attr('class', 'select-check')
        .attr('dx', d => nodeR(d) - 2)
        .attr('dy', d => -nodeR(d) + 4)
        .attr('font-size', '12px')
        .attr('fill', '#22c55e')
        .text('✓');

    // Node labels
    node.append('text')
        .attr('class', 'node-label')
        .attr('dy', d => nodeR(d) + 14)
        .attr('text-anchor', 'middle')
        .text(d => d.title.length > 35 ? d.title.substring(0, 33) + '…' : d.title);

    // Signal count inside node
    node.append('text')
        .attr('class', 'node-count')
        .attr('dy', 4)
        .attr('text-anchor', 'middle')
        .text(d => d.signal_count || '');

    // Tick
    _graphSimulation.on('tick', () => {
        link
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y);
        linkLabel
            .attr('x', d => (d.source.x + d.target.x) / 2)
            .attr('y', d => (d.source.y + d.target.y) / 2);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // Click background to deselect
    svg.on('click', (event) => {
        if (event.target === svg.node()) {
            _selectedThreadIds.clear();
            _updateGraphSelection();
            _updateBrainstormBtn();
        }
    });
}

function _toggleThreadSelection(threadId) {
    if (_selectedThreadIds.has(threadId)) {
        _selectedThreadIds.delete(threadId);
    } else {
        if (_selectedThreadIds.size >= 4) return; // max 4
        _selectedThreadIds.add(threadId);
    }
    _updateGraphSelection();
    _updateBrainstormBtn();
}

function _updateGraphSelection() {
    d3.selectAll('.graph-node').classed('selected', d => _selectedThreadIds.has(d.id));
    d3.selectAll('.graph-edge').classed('highlighted', d =>
        _selectedThreadIds.has(d.source.id || d.source) && _selectedThreadIds.has(d.target.id || d.target)
    );
}

function _updateBrainstormBtn() {
    const btn = document.getElementById('sig-brainstorm-btn');
    const sel = document.getElementById('sig-graph-selection');
    if (!btn) return;
    if (_selectedThreadIds.size >= 2) {
        btn.style.display = 'block';
        sel.innerHTML = `${_selectedThreadIds.size} threads selected · <span style="color:var(--accent);cursor:pointer" onclick="linkSelectedThreads()">Link</span>`;
    } else {
        btn.style.display = 'none';
        sel.textContent = _selectedThreadIds.size === 1 ? '1 thread selected — Shift+click another to brainstorm' : 'Click to inspect · Shift+click to select';
    }
}

function linkSelectedThreads() {
    if (_selectedThreadIds.size < 2) return;
    const ids = [..._selectedThreadIds];
    const promises = [];
    for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
            promises.push(
                fetch('/api/board/connect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ source: ids[i], target: ids[j], label: '' })
                })
            );
        }
    }
    Promise.all(promises).then(() => loadGraph());
}

function _toggleExecDomain(domain) {
    if (_execExpandedDomains.has(domain)) {
        _execExpandedDomains.delete(domain);
    } else {
        _execExpandedDomains.add(domain);
    }
    // Toggle the DOM directly without full re-render
    const el = document.querySelector(`.exec-step[data-domain="${domain}"]`);
    if (el) el.classList.toggle('open');
}

function _graphZoom(factor) {
    const svg = d3.select('#sig-graph-svg');
    const zb = svg.node().__zoomBehavior;
    if (zb) svg.transition().duration(300).call(zb.scaleBy, factor);
}
function _graphReset() {
    const svg = d3.select('#sig-graph-svg');
    const zb = svg.node().__zoomBehavior;
    if (zb) svg.transition().duration(300).call(zb.transform, d3.zoomIdentity);
}
function _adjustGraphSpacing(val) {
    if (!_graphSimulation) return;
    const v = parseInt(val);
    _graphSimulation.force('charge').strength(-v * 2);
    _graphSimulation.force('link').distance(v);
    _graphSimulation.alpha(0.5).restart();
}

function _showSignalNodeDetail(s) {
    ++_detailRequestId;
    const detailBody = _showDetailPane('Signal Detail');
    const snDoms = _parseDomains(s.domain);
    const domColor = _DOMAIN_COLORS[snDoms[0]] || '#6b7280';
    const dateStr = s.published_at ? s.published_at.substring(0, 10) : '';
    const isNoise = s.signal_status === 'noise';
    const patternId = _zoomedPatternId;
    const patternNode = _graphData?.nodes.find(n => n.id === patternId);
    const patternTitle = patternNode ? patternNode.title : '';

    detailBody.innerHTML = `
        ${patternTitle ? `<div style="padding:8px 16px;border-bottom:1px solid var(--border);font-size:11px;display:flex;align-items:center;gap:4px">
            <span style="color:var(--accent);cursor:pointer" onclick="openThreadDetail(${patternId})">📊 ${escHtml(patternTitle)}</span>
            <span style="color:var(--text-muted)">→</span>
            <span style="color:var(--text-secondary);font-weight:600">Signal</span>
        </div>` : ''}
        <div class="sig-detail-card" style="border:none;border-radius:0">
            <div class="sig-detail-hero" style="border-left: 4px solid ${domColor}">
                <h2>${escHtml(s.title)}</h2>
                <div class="sig-detail-meta">
                    ${_renderDomainBadges(s.domain, '10px')}
                    <span style="font-size:11px;color:var(--text-muted)">${escHtml(s.source_name || s.source)}</span>
                    <span style="font-size:11px;color:var(--text-muted)">${escHtml(dateStr)}</span>
                    ${isNoise ? '<span style="font-size:10px;color:var(--red);font-weight:600">NOISE</span>' : ''}
                </div>
            </div>
            <div class="sig-detail-body-text" id="sig-node-body-${s.id}">
                ${s.body_snippet ? `<div style="margin-bottom:8px">${escHtml(s.body_snippet)}${s.body_len > 300 ? '...' : ''}</div>` : ''}
                ${s.url ? `<div style="color:var(--accent);cursor:pointer;font-size:11px" onclick="_fetchSignalNodeArticle(${s.id})">Load full article →</div>` : ''}
            </div>
            <div style="padding:12px 20px;border-top:1px solid var(--border);display:flex;gap:8px;flex-wrap:wrap">
                ${s.url ? `<a href="${escHtml(s.url)}" target="_blank" rel="noopener" style="color:var(--accent);font-size:11px;text-decoration:none">Open source →</a>` : ''}
            </div>
        </div>
    `;
}

function _fetchSignalNodeArticle(sigId) {
    const el = document.getElementById('sig-node-body-' + sigId);
    if (!el) return;
    el.innerHTML = '<span style="color:var(--text-muted)">Loading...</span>';
    fetch('/api/signals/' + sigId + '/fetch-article', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            el.textContent = data.ok && data.body ? data.body : 'Could not load article text';
        })
        .catch(() => { el.textContent = 'Failed to fetch'; });
}

function _zoomIntoPattern(patternId) {
    _graphMode = 'signals';
    _zoomedPatternId = patternId;

    // Show back button and pattern label
    document.getElementById('sig-graph-back').style.display = 'block';
    const label = document.getElementById('sig-graph-pattern-label');
    const patternNode = _graphData?.nodes.find(n => n.id === patternId);
    label.textContent = (patternNode ? patternNode.title : `Thread ${patternId}`) + ' — Signals';
    label.style.display = 'block';
    document.getElementById('sig-graph-container').style.boxShadow = 'inset 0 0 0 2px var(--accent)';
    document.getElementById('sig-graph-container').style.borderRadius = '8px';

    // Fetch signals for this pattern and render sub-graph
    fetch(`/api/signals/patterns/${patternId}/signals`)
        .then(r => r.json())
        .then(data => _renderSignalSubGraph(data))
        .catch(e => console.error('[graph] zoom-in error:', e));
}

let _zoomedFromBoard = false;

function _zoomOutToPatterns() {
    _graphMode = 'patterns';
    _zoomedPatternId = null;
    document.getElementById('sig-graph-back').style.display = 'none';
    document.getElementById('sig-graph-pattern-label').style.display = 'none';
    document.getElementById('sig-graph-container').style.boxShadow = '';
    document.getElementById('sig-graph-container').style.borderRadius = '';
    if (_zoomedFromBoard && _boardData) {
        _zoomedFromBoard = false;
        renderBoard(_boardData);
    } else if (_graphData) {
        renderGraph(_graphData);
    }
}

function _renderSignalSubGraph(data) {
    const container = document.getElementById('sig-graph-container');
    const svg = d3.select('#sig-graph-svg');
    svg.selectAll('*').remove();

    const width = container.clientWidth;
    const height = container.clientHeight - 40;
    svg.attr('viewBox', [0, 0, width, height]);

    const signals = data.signals || [];
    const edges = data.edges || [];
    const pattern = data.pattern || {};
    const domColor = _DOMAIN_COLORS[pattern.domain] || '#6b7280';

    if (!signals.length) return;

    // Zoom behavior
    const zoomGroup = svg.append('g');
    const zoomBehavior = d3.zoom()
        .scaleExtent([0.3, 4])
        .filter(event => {
            if (event.type === 'wheel') return true;
            if (event.target.closest && event.target.closest('.signal-node')) return false;
            return !event.button;
        })
        .on('zoom', (event) => zoomGroup.attr('transform', event.transform));
    svg.call(zoomBehavior);
    svg.on('dblclick.zoom', null);
    svg.node().__zoomBehavior = zoomBehavior;

    const nodes = signals.map(s => ({...s}));
    const links = edges.map(e => ({...e}));

    // Source icon mapping
    const srcIcons = { google_news: '📰', reddit: '💬', hackernews: '🟧', fred: '📈', targeted: '🎯' };

    const spacing = Math.max(40, 120 / Math.sqrt(signals.length));
    const sim = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(spacing))
        .force('charge', d3.forceManyBody().strength(-60))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(22));
    _graphSimulation = sim;

    // Edges
    const link = zoomGroup.append('g')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('class', 'signal-edge');

    // Edge labels
    const linkLabel = zoomGroup.append('g')
        .selectAll('text')
        .data(links)
        .join('text')
        .attr('class', 'graph-edge-label')
        .attr('text-anchor', 'middle')
        .text(d => (d.shared || []).slice(0, 1).map(e => e.name).join(''));

    // Signal nodes
    const node = zoomGroup.append('g')
        .selectAll('g')
        .data(nodes)
        .join('g')
        .attr('class', d => 'signal-node' + (d.signal_status === 'noise' ? ' noise' : ''))
        .call(d3.drag()
            .on('start', (event, d) => { d.fx = d.x; d.fy = d.y; d._dragMoved = false; })
            .on('drag', (event, d) => {
                if (!d._dragMoved) { d._dragMoved = true; if (!event.active) sim.alphaTarget(0.3).restart(); }
                d.fx = event.x; d.fy = event.y;
            })
            .on('end', (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
        )
        .on('click', (event, d) => {
            event.stopPropagation();
            _showSignalNodeDetail(d);
        });

    // Signal circles
    node.append('circle')
        .attr('r', 16)
        .attr('fill', domColor)
        .attr('fill-opacity', 0.6)
        .attr('stroke', domColor)
        .attr('stroke-width', 2);

    // Source icon inside
    node.append('text')
        .attr('dy', 5)
        .attr('text-anchor', 'middle')
        .attr('font-size', '12px')
        .text(d => srcIcons[d.source] || '•');

    // Title labels — larger, wrapped
    node.append('text')
        .attr('dy', 32)
        .attr('text-anchor', 'middle')
        .attr('font-size', '11px')
        .attr('fill', 'var(--text-secondary)')
        .attr('font-weight', '600')
        .text(d => d.title.length > 45 ? d.title.substring(0, 43) + '…' : d.title);

    sim.on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        linkLabel.attr('x', d => (d.source.x + d.target.x) / 2)
            .attr('y', d => (d.source.y + d.target.y) / 2);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
}

function toggleGraphFullscreen() {
    const tab = document.getElementById('sig-tab-graph');
    tab.classList.toggle('graph-fullscreen');
    // Re-render graph at new size after transition
    if (_graphData) setTimeout(() => renderGraph(_graphData), 50);
}

// ===================== BOARD =====================

let _boardData = null;
let _boardZoomTransform = null; // persist zoom across reloads
let _connectingFrom = null; // thread id when drawing a connection
let _boardSelectedIds = new Set(); // shift-click multi-select for narrative creation
let _expandedNarratives = new Set(); // narrative IDs that are expanded to show child threads

function loadBoard() {
    // Restore Board subtab (Graph | Chains) — defined in chains.js
    if (typeof _restoreBoardSubtab === 'function') _restoreBoardSubtab();

    // Collapse detail pane in board view for full width
    const detailPane = document.getElementById('signals-detail');
    if (detailPane && !_activeThreadId && !_activeNarrativeId) detailPane.style.display = 'none';

    fetch('/api/board')
        .then(r => r.json())
        .then(data => {
            _boardData = data;
            // Apply global domain filter to board nodes
            const allActive = _activeDomains.size === _ALL_DOMAINS.length;
            const filtered = allActive ? data : {
                ...data,
                nodes: data.nodes.filter(n => {
                    if (n.type === 'narrative') return true; // narratives always shown
                    // Multi-domain threads: check if any domain matches
                    const domains = (n.domain || '').split('|').map(d => d.trim());
                    return domains.some(d => _activeDomains.has(d));
                }),
                edges: data.edges // edges filtered by renderBoard's visibleThreadIds
            };
            renderBoard(filtered);
            // Re-apply any active highlights after board re-render
            if (_boardHighlights.length) {
                setTimeout(() => { _applyBoardHighlights(); _renderHighlightPills(); }, 50);
            }
        });
}

function renderBoard(data) {
    const container = document.getElementById('sig-graph-container');
    const svg = d3.select('#sig-graph-svg');
    const empty = document.getElementById('signals-graph-empty');
    const controls = document.getElementById('sig-graph-controls');

    empty.style.display = 'none';
    svg.style('display', 'block');
    controls.style.display = 'flex';
    const searchBar2 = document.getElementById('board-search-bar');
    if (searchBar2) searchBar2.style.display = 'flex';
    // Show timeline if was visible
    const tlPanel = document.getElementById('board-timeline');
    if (tlPanel) tlPanel.style.display = _timelineVisible ? '' : 'none';

    // Sync physics button state
    const physBtn = document.getElementById('board-physics-btn');
    if (physBtn) {
        physBtn.style.background = _boardPhysicsOn ? 'var(--accent)' : 'var(--bg-tertiary)';
        physBtn.style.color = _boardPhysicsOn ? '#fff' : 'var(--text-muted)';
        physBtn.style.borderColor = _boardPhysicsOn ? 'var(--accent)' : 'var(--border)';
    }

    svg.selectAll('*').remove();
    // Remove old notes
    container.querySelectorAll('.board-note').forEach(n => n.remove());

    const width = container.clientWidth;
    const height = container.clientHeight - 40;
    // No viewBox — let D3 zoom be the sole viewport controller
    svg.attr('width', '100%').attr('height', '100%').attr('viewBox', null);

    const zoomGroup = svg.append('g').attr('class', 'graph-zoom-group');
    const zoomBehavior = d3.zoom()
        .scaleExtent([0.2, 5])
        .filter(event => {
            if (event.type === 'wheel') return true;
            if (event.target.closest && event.target.closest('.graph-node')) return false;
            if (event.target.closest && event.target.closest('.board-note')) return false;
            return !event.button;
        })
        .on('zoom', (event) => {
            _boardZoomTransform = event.transform;
            zoomGroup.attr('transform', event.transform);
            // Move HTML notes with the zoom
            container.querySelectorAll('.board-note').forEach(n => {
                const ox = parseFloat(n.dataset.bx);
                const oy = parseFloat(n.dataset.by);
                n.style.left = (event.transform.x + ox * event.transform.k) + 'px';
                n.style.top = (event.transform.y + oy * event.transform.k) + 'px';
                n.style.transform = `scale(${event.transform.k})`;
                n.style.transformOrigin = '0 0';
            });
        });
    svg.call(zoomBehavior);
    svg.on('dblclick.zoom', null);
    svg.node().__zoomBehavior = zoomBehavior;
    // Restore previous zoom transform if available (prevents flash on reload)
    if (_boardZoomTransform) {
        // Apply directly to avoid triggering a zoom event that causes jitter
        zoomGroup.attr('transform', _boardZoomTransform);
        // Sync D3's internal zoom state
        svg.call(zoomBehavior.transform, _boardZoomTransform);
    }

    // Double-click on empty space → create note (use event coordinates to avoid zoom interference)
    svg.on('dblclick', (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (event.target.closest('.graph-node')) return;
        const [x, y] = d3.pointer(event, zoomGroup.node());
        _showInlineInput(event.clientX, event.clientY, 'Add a note...', '', (text) => {
            if (!text) return;
            fetch('/api/board/notes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, x, y })
            }).then(() => loadBoard());
        });
    });

    // Filter nodes: narratives moved to Chain Board in Causal tab — hide them here
    const visibleNodes = data.nodes.filter(d => {
        if (d.type === 'narrative' || d.type === 'narrative_thread') return false;
        return true;
    });

    const nodes = visibleNodes.map(d => {
        const copy = {...d};
        if (copy.x == null) { copy.x = Math.random() * (width - 100) + 50; copy.y = Math.random() * (height - 100) + 50; }
        return copy;
    });

    // Edges (only between visible thread nodes)
    const visibleThreadIds = new Set(nodes.filter(n => n.type !== 'narrative').map(n => n.id));
    const edgeData = (data.edges || []).filter(e => visibleThreadIds.has(e.source) && visibleThreadIds.has(e.target));
    const nodeMap = {};
    nodes.forEach(n => nodeMap[typeof n.id === 'string' ? n.id : n.id] = n);

    const link = zoomGroup.append('g').selectAll('line').data(edgeData).join('line')
        .attr('stroke', 'var(--accent)').attr('stroke-width', 2).attr('stroke-opacity', 0.5)
        .attr('stroke-dasharray', '6 4');

    const linkLabel = zoomGroup.append('g').selectAll('text').data(edgeData).join('text')
        .attr('text-anchor', 'middle').attr('font-size', 10).attr('fill', 'var(--text-muted)')
        .text(d => d.label || '');

    // Temporary line for drawing connections
    const connectLine = zoomGroup.append('line').attr('class', 'board-connect-line').style('display', 'none');

    // Nodes
    const nodeR = d => d.type === 'narrative' ? 30 : Math.sqrt(d.signal_count || 1) * 6 + 10;
    let _boardDragged = false;

    const node = zoomGroup.append('g').selectAll('g').data(nodes).join('g')
        .attr('class', 'graph-node')
        .attr('data-node-id', d => d.type === 'narrative' ? d.node_id : d.id)
        .attr('data-node-type', d => d.type === 'narrative' ? 'narrative' : 'thread')
        .attr('transform', d => `translate(${d.x},${d.y})`)
        .call(d3.drag()
            .on('start', function(event, d) {
                _boardDragged = false;
                d._el = d3.select(this);
            })
            .on('drag', function(event, d) {
                _boardDragged = true;
                d.x = event.x; d.y = event.y;
                d._el.attr('transform', `translate(${d.x},${d.y})`);
                _updateBoardEdges(link, linkLabel, edgeData, nodeMap);
            })
            .on('end', (event, d) => {
                if (_boardDragged) {
                    d.pinned = true;
                    _saveBoardPositions(nodes);
                }
                delete d._el;
            })
        )
        .on('click', (event, d) => {
            event.stopPropagation();
            if (_boardDragged) return;
            if (_connectingFrom != null && _connectingFrom !== d.id) {
                // Block narrative-to-narrative connections
                const fromNode = nodes.find(n => n.id === _connectingFrom);
                if (fromNode && fromNode.type === 'narrative' && d.type === 'narrative') {
                    _cancelConnect();
                    const sel = document.getElementById('sig-graph-selection');
                    if (sel) sel.innerHTML = '<span style="color:var(--red)">Narratives connect through shared threads, not directly</span>';
                    setTimeout(() => _cancelConnect(), 3000);
                    return;
                }
                const fromId = _connectingFrom;
                _cancelConnect();
                _showInlineInput(event.clientX, event.clientY, 'Label (optional — AI will suggest)', '', (label) => {
                    const sel = document.getElementById('sig-graph-selection');
                    if (sel) sel.innerHTML = '<span style="color:var(--accent)">Connecting + AI analyzing...</span>';
                    fetch('/api/board/connect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ source: fromId, target: d.id, label })
                    })
                    .then(r => r.json())
                    .then(result => {
                        loadBoard();
                        if (result.assessment) {
                            const a = result.assessment;
                            const color = a.makes_sense ? 'var(--green)' : 'var(--red)';
                            if (sel) sel.innerHTML = `<span style="color:${color};font-weight:600">${a.makes_sense ? '✓' : '✗'} "${result.label}"</span> <span style="color:var(--text-muted)">— ${escHtml(a.reasoning || '')}</span>`;
                            setTimeout(() => { if (sel) sel.innerHTML = ''; }, 8000);
                        }
                    });
                });
            } else if (event.shiftKey) {
                // Shift-click: toggle selection for narrative creation
                if (_boardSelectedIds.has(d.id)) _boardSelectedIds.delete(d.id);
                else _boardSelectedIds.add(d.id);
                node.select('.board-select-ring').attr('opacity', dd => _boardSelectedIds.has(dd.id) ? 1 : 0);
                _updateBoardSelectionBar(nodes);
            } else if (d.type === 'narrative') {
                _showNarrativeInBoardPane(d.node_id);
            } else {
                openThreadDetail(d.id);
            }
        })
        .on('dblclick', (event, d) => {
            event.stopPropagation();
            if (d.type === 'narrative') {
                _expandedNarratives.add(d.node_id);
                loadBoard();
            } else if (d.type === 'narrative_thread') {
                _expandedNarratives.delete(d.narrative_id);
                loadBoard();
            } else {
                // Regular thread node — zoom into signal sub-graph
                _zoomedFromBoard = true;
                // Ensure _graphData has this node so _zoomIntoPattern can find the title
                if (!_graphData) _graphData = { nodes: [] };
                if (!_graphData.nodes.find(n => n.id === d.id)) {
                    _graphData.nodes.push({ id: d.id, title: d.title, domain: d.domain, signal_count: d.signal_count });
                }
                _zoomIntoPattern(d.id);
                openThreadDetail(d.id);
            }
        })
        .on('contextmenu', (event, d) => {
            event.preventDefault();
            event.stopPropagation();
            if (d.type === 'narrative') return; // no context menu for narrative super-nodes

            const multiSelected = _boardSelectedIds.size > 1 && _boardSelectedIds.has(d.id);

            if (multiSelected) {
                const ids = [..._boardSelectedIds];
                const count = ids.length;
                _showContextMenu([
                    { label: `Link ${count} threads`, icon: '🔗', action: `_boardLinkSelected([${ids}])` },
                    { label: `Merge ${count} threads`, icon: '🔀', action: `_boardMergeSelected([${ids}])` },
                    { label: `Create chain from ${count}`, icon: '⛓️', action: `_createChainFromThreads([${ids}])` },
                    { label: 'Brainstorm connections', icon: '🧠', action: `openBrainstormMode()` },
                    'separator',
                    { label: `Delete ${count} threads`, icon: '🗑️', action: `_boardBulkDelete([${ids}])`, color: '#ef4444' },
                ], event.clientX, event.clientY, `${count} threads selected`);
            } else {
                const sigCount = d.signal_count || 0;
                const items = [
                    { label: 'Rename', icon: '✏️', action: `_renameThread(${d.id})` },
                ];
                if (sigCount >= 6) {
                    items.push({ label: 'Split thread', icon: '✂️', action: `_splitThreadFromMenu(${d.id})` });
                }
                items.push(
                    { label: 'Add to chain', icon: '⛓️', action: `_addThreadToChainFromMenu(${d.id})` },
                    { label: 'Find similar', icon: '🔍', submenu: [
                        { label: 'By shared entities', icon: '🏢', action: `_findSimilarByEntities(${d.id})` },
                        { label: 'By domain', icon: '🎯', action: `_findSimilarByDomain(${d.id})` },
                        { label: 'By signal count', icon: '📊', action: `_findSimilarBySize(${d.id})` },
                    ]},
                    'separator',
                    { label: 'Delete', icon: '🗑️', action: `_deleteThread(${d.id})`, color: '#ef4444' },
                );
                _showContextMenu(items, event.clientX, event.clientY, d.title.substring(0, 40));
            }
        })
        .on('auxclick', (event, d) => {
            if (event.button !== 1) return;
            event.preventDefault();
            event.stopPropagation();
            if (d.type === 'narrative') return;
            _startBoardConnect(d.id, d.x, d.y);
        });

    // Prevent default middle-click autoscroll on SVG
    svg.on('auxclick', (event) => { if (event.button === 1) event.preventDefault(); });

    // Draw nodes
    node.each(function(d) {
        const g = d3.select(this);

        if (d.type === 'narrative') {
            // Narrative super-node: rounded rectangle
            const w = 160, h = 56, rx = 10;
            // Selection ring
            g.append('rect').attr('class', 'board-select-ring')
                .attr('x', -w/2 - 4).attr('y', -h/2 - 4).attr('width', w + 8).attr('height', h + 8)
                .attr('rx', rx + 2).attr('fill', 'none')
                .attr('stroke', 'var(--accent)').attr('stroke-width', 2.5)
                .attr('opacity', _boardSelectedIds.has(d.id) ? 1 : 0);
            // Background
            g.append('rect').attr('x', -w/2).attr('y', -h/2).attr('width', w).attr('height', h)
                .attr('rx', rx).attr('fill', '#1a1a2e').attr('stroke', 'var(--purple)').attr('stroke-width', 1.5);
            // Title
            g.append('text').attr('text-anchor', 'middle').attr('y', -10)
                .attr('fill', '#fff').attr('font-size', 11).attr('font-weight', 700).attr('pointer-events', 'none')
                .text(d.title.length > 22 ? d.title.substring(0, 20) + '…' : d.title);
            // Evidence bar
            const ev = d.evidence || {};
            const sup = ev.supporting || 0, con = ev.contradicting || 0, neu = ev.neutral || 0;
            const total = sup + con + neu;
            if (total > 0) {
                const barW = w - 24, barH = 4, barX = -barW/2, barY = 4;
                g.append('rect').attr('x', barX).attr('y', barY).attr('width', barW).attr('height', barH).attr('rx', 2).attr('fill', '#333');
                if (sup > 0) g.append('rect').attr('x', barX).attr('y', barY).attr('width', barW * sup/total).attr('height', barH).attr('rx', 2).attr('fill', '#22c55e');
                if (con > 0) g.append('rect').attr('x', barX + barW * (1 - con/total)).attr('y', barY).attr('width', barW * con/total).attr('height', barH).attr('rx', 2).attr('fill', '#ef4444');
            }
            // Stats line
            g.append('text').attr('text-anchor', 'middle').attr('y', 20)
                .attr('fill', 'var(--text-muted)').attr('font-size', 9).attr('pointer-events', 'none')
                .text(`${d.thread_count} threads · ${d.signal_count} signals`);
            // Expand hint
            g.append('text').attr('text-anchor', 'middle').attr('y', h/2 + 14)
                .attr('fill', 'var(--text-muted)').attr('font-size', 8).attr('pointer-events', 'none')
                .text('double-click to expand');
        } else {
            // Thread node (regular or narrative_thread): circle
            const r = nodeR(d);
            const isNarrThread = d.type === 'narrative_thread';
            const doms = _parseDomains(d.domain);
            const primaryColor = isNarrThread ? '#8b5cf6' : (_DOMAIN_COLORS[doms[0]] || '#6b7280');
            // Selection ring
            g.append('circle').attr('class', 'board-select-ring')
                .attr('r', r + 5).attr('fill', 'none')
                .attr('stroke', 'var(--accent)').attr('stroke-width', 2.5)
                .attr('opacity', _boardSelectedIds.has(d.id) ? 1 : 0);
            // Main circle — split colors for multi-domain
            if (!isNarrThread && doms.length > 1) {
                const sliceAngle = (Math.PI * 2) / doms.length;
                for (let di = 0; di < doms.length; di++) {
                    const startAngle = -Math.PI / 2 + di * sliceAngle;
                    const endAngle = startAngle + sliceAngle;
                    const arc = d3.arc().innerRadius(0).outerRadius(r).startAngle(startAngle).endAngle(endAngle);
                    g.append('path').attr('d', arc()).attr('fill', _DOMAIN_COLORS[doms[di]] || '#6b7280').attr('fill-opacity', 0.8);
                }
            } else {
                g.append('circle').attr('r', r).attr('fill', primaryColor).attr('fill-opacity', isNarrThread ? 0.6 : 0.8)
                    .attr('stroke', isNarrThread ? '#8b5cf6' : 'none').attr('stroke-width', isNarrThread ? 1.5 : 0);
            }
            // Signal count inside
            if (d.signal_count > 0) {
                g.append('text').attr('text-anchor', 'middle').attr('dy', '0.35em')
                    .attr('fill', '#fff').attr('font-size', Math.min(r * 0.7, 14)).attr('font-weight', 700).attr('pointer-events', 'none')
                    .text(d.signal_count);
            }
            // Title below
            g.append('text').attr('y', r + 14).attr('text-anchor', 'middle')
                .attr('fill', 'var(--text-secondary)').attr('font-size', 11).attr('font-weight', 600)
                .text(d.title.length > 30 ? d.title.substring(0, 28) + '…' : d.title);
            // Domain labels or collapse hint
            const domLabel = isNarrThread ? 'dbl-click to collapse' : doms.map(dm => _DOMAIN_LABELS[dm] || dm).join(' · ');
            const labelColor = isNarrThread ? 'var(--purple)' : (doms.length > 1 ? 'var(--text-muted)' : primaryColor);
            g.append('text').attr('y', r + 26).attr('text-anchor', 'middle')
                .attr('fill', labelColor).attr('font-size', 9).attr('font-weight', 600)
                .text(domLabel);
        }
    });

    // Draw connection lines between sibling narrative threads
    const narrativeThreadNodes = nodes.filter(n => n.type === 'narrative_thread');
    const siblingGroups = {};
    narrativeThreadNodes.forEach(n => {
        const key = n.narrative_id;
        if (!siblingGroups[key]) siblingGroups[key] = [];
        siblingGroups[key].push(n);
    });
    const siblingLinks = [];
    Object.values(siblingGroups).forEach(group => {
        for (let i = 0; i < group.length; i++) {
            for (let j = i + 1; j < group.length; j++) {
                siblingLinks.push({ source: group[i], target: group[j] });
            }
        }
    });
    zoomGroup.insert('g', ':first-child').selectAll('line').data(siblingLinks).join('line')
        .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
        .attr('stroke', '#8b5cf6').attr('stroke-width', 1).attr('stroke-opacity', 0.3)
        .attr('stroke-dasharray', '4 4');

    _updateBoardEdges(link, linkLabel, edgeData, nodeMap);

    // Make edge labels clickable to edit — show placeholder for empty labels on hover
    linkLabel.style('cursor', 'pointer').style('pointer-events', 'all')
        .text(d => d.label || '···')
        .attr('fill', d => d.label ? 'var(--text-muted)' : 'transparent')
        .on('mouseenter', function(event, d) { if (!d.label) d3.select(this).attr('fill', 'var(--text-muted)'); })
        .on('mouseleave', function(event, d) { if (!d.label) d3.select(this).attr('fill', 'transparent'); })
        .on('click', (event, d) => {
            event.stopPropagation();
            _showInlineInput(event.clientX, event.clientY, 'Edit label', d.label || '', (newLabel) => {
                fetch(`/api/board/connect/${d.id}/label`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ label: newLabel })
                }).then(() => loadBoard());
            });
        });

    // Physics mode — live force simulation (toggle via button)
    if (_boardPhysicsOn) {
        // Stop any existing sim
        if (_boardPhysicsSim) _boardPhysicsSim.stop();
        const threadNodes = nodes.filter(n => n.type !== 'narrative');
        _boardPhysicsSim = d3.forceSimulation(threadNodes)
            .force('link', d3.forceLink(edgeData).id(d => d.id).distance(100))
            .force('charge', d3.forceManyBody().strength(-120))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(d => nodeR(d) + 10));
        _boardPhysicsSim.on('tick', () => {
            node.attr('transform', d => `translate(${d.x},${d.y})`);
            _updateBoardEdges(link, linkLabel, edgeData, nodeMap);
            // Update sibling lines too
            zoomGroup.selectAll('line[stroke="#8b5cf6"]')
                .attr('x1', function() { const d = d3.select(this).datum(); return d?.source?.x || 0; })
                .attr('y1', function() { const d = d3.select(this).datum(); return d?.source?.y || 0; });
        });
    } else {
        if (_boardPhysicsSim) { _boardPhysicsSim.stop(); _boardPhysicsSim = null; }
    }

    // Render sticky notes as HTML overlays (positioned in zoom-transformed space)
    const initTransform = d3.zoomTransform(svg.node());
    (data.notes || []).forEach(note => {
        const div = document.createElement('div');
        div.className = 'board-note';
        div.style.background = note.color || '#eab308';
        div.style.left = (initTransform.x + note.x * initTransform.k) + 'px';
        div.style.top = (initTransform.y + note.y * initTransform.k) + 'px';
        div.style.transform = `scale(${initTransform.k})`;
        div.style.transformOrigin = '0 0';
        div.dataset.bx = note.x;
        div.dataset.by = note.y;
        div.dataset.id = note.id;
        div.innerHTML = `${escHtml(note.text)}<button class="board-note-delete" onclick="event.stopPropagation();_deleteBoardNote(${note.id})">×</button>`;
        div.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            _showInlineInput(e.clientX, e.clientY, 'Edit note', note.text, (newText) => {
                if (newText !== null && newText !== '') {
                    fetch(`/api/board/notes/${note.id}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ text: newText })
                    }).then(() => loadBoard());
                }
            });
        });
        // Drag note
        let dragStartX, dragStartY, noteStartX, noteStartY;
        div.addEventListener('mousedown', (e) => {
            if (e.target.classList.contains('board-note-delete')) return;
            e.stopPropagation();
            dragStartX = e.clientX; dragStartY = e.clientY;
            noteStartX = parseFloat(div.dataset.bx); noteStartY = parseFloat(div.dataset.by);
            const onMove = (me) => {
                const t = d3.zoomTransform(svg.node());
                const dx = (me.clientX - dragStartX) / t.k;
                const dy = (me.clientY - dragStartY) / t.k;
                div.dataset.bx = noteStartX + dx;
                div.dataset.by = noteStartY + dy;
                div.style.left = (t.x + (noteStartX + dx) * t.k) + 'px';
                div.style.top = (t.y + (noteStartY + dy) * t.k) + 'px';
            };
            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                fetch(`/api/board/notes/${note.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ x: parseFloat(div.dataset.bx), y: parseFloat(div.dataset.by) })
                });
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
        container.appendChild(div);
    });

    // Cancel connection on escape or click on empty space
    function _cancelConnect() {
        _connectingFrom = null;
        connectLine.style('display', 'none');
        svg.on('mousemove.connect', null);
        const sel = document.getElementById('sig-graph-selection');
        if (sel) sel.innerHTML = `<span style="color:var(--text-muted)">${nodes.length} threads · ${(data.notes||[]).length} notes · middle-click to connect · double-click to add note</span>`;
    }
    // Cancel connection: Escape, left-click empty space, or right-click empty space
    document.addEventListener('keydown', function _escConn(e) {
        if (e.key === 'Escape') {
            _cancelConnect();
            const inp = document.getElementById('board-inline-input'); if (inp) inp.remove();
            // Clear all highlights if active
            if (_boardHighlights.length) {
                _clearBoardHighlight();
            }
        }
    });
    svg.on('contextmenu.cancel', (event) => {
        if (!event.target.closest('.graph-node') && _connectingFrom != null) { event.preventDefault(); _cancelConnect(); }
    });
    svg.on('click.cancel', (event) => {
        if (event.target.closest('.graph-node')) return;
        _cancelConnect();
        // Clear board selection if clicking empty space (without shift)
        if (!event.shiftKey && _boardSelectedIds.size > 0) {
            _boardSelectedIds.clear();
            node.select('.board-select-ring').attr('opacity', 0);
            _updateBoardSelectionBar(nodes);
        }
        // Dismiss detail pane on empty board click
        if (_activeThreadId || _activeSignalId || _activeNarrativeId) {
            closeSignalDetail();
        }
    });

    // Set up drag-to-reassign drop targets
    _setupBoardDropTargets(svg, zoomGroup, nodes);

    // Status text
    const sel = document.getElementById('sig-graph-selection');
    if (sel) sel.innerHTML = `<span style="color:var(--text-muted)">${nodes.length} threads · ${(data.notes||[]).length} notes · drag signals to reassign</span>`;
}

function _updateBoardEdges(link, linkLabel, edgeData, nodeMap) {
    link.attr('x1', d => nodeMap[d.source]?.x || 0).attr('y1', d => nodeMap[d.source]?.y || 0)
        .attr('x2', d => nodeMap[d.target]?.x || 0).attr('y2', d => nodeMap[d.target]?.y || 0);
    linkLabel.attr('x', d => ((nodeMap[d.source]?.x||0) + (nodeMap[d.target]?.x||0)) / 2)
        .attr('y', d => ((nodeMap[d.source]?.y||0) + (nodeMap[d.target]?.y||0)) / 2 - 6);
}

function _saveBoardPositions(nodes) {
    const positions = nodes.filter(n => n.pinned).map(n => {
        if (n.type === 'narrative') return { node_type: 'narrative', node_id: n.node_id, x: n.x, y: n.y, pinned: true };
        return { node_type: 'thread', node_id: n.id, x: n.x, y: n.y, pinned: true };
    });
    fetch('/api/board/positions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ positions })
    });
}

function _deleteBoardNote(noteId) {
    fetch(`/api/board/notes/${noteId}`, { method: 'DELETE' }).then(() => loadBoard());
}

// ===================== SIGNAL DRAG-TO-REASSIGN =====================

let _dragSelectedSignals = new Set();
let _dragFromThreadId = null;
let _dragBadge = null;

function _toggleDragSelect(sigId) {
    if (_dragSelectedSignals.has(sigId)) _dragSelectedSignals.delete(sigId);
    else _dragSelectedSignals.add(sigId);
    const el = document.querySelector(`[data-drag-select="${sigId}"]`);
    if (el) el.classList.toggle('checked', _dragSelectedSignals.has(sigId));
}

// Set up drag events on the detail pane (delegated)
document.addEventListener('dragstart', function(e) {
    const item = e.target.closest('.sig-draggable');
    if (!item) return;
    const sigId = parseInt(item.dataset.sigId);
    _dragFromThreadId = parseInt(item.dataset.fromThread);

    // If this signal isn't selected, select only it
    if (!_dragSelectedSignals.has(sigId)) {
        _dragSelectedSignals.clear();
        document.querySelectorAll('[data-drag-select]').forEach(el => el.classList.remove('checked'));
        _dragSelectedSignals.add(sigId);
        const el = document.querySelector(`[data-drag-select="${sigId}"]`);
        if (el) el.classList.add('checked');
    }

    // Dim dragged items
    _dragSelectedSignals.forEach(id => {
        const el = document.getElementById(`sig-item-${id}`);
        if (el) el.classList.add('sig-dragging');
    });

    // Create floating badge
    _dragBadge = document.createElement('div');
    _dragBadge.className = 'sig-drag-badge';
    _dragBadge.textContent = `${_dragSelectedSignals.size} signal${_dragSelectedSignals.size > 1 ? 's' : ''}`;
    document.body.appendChild(_dragBadge);

    e.dataTransfer.setData('text/plain', JSON.stringify([..._dragSelectedSignals]));
    e.dataTransfer.effectAllowed = 'move';
    // Use transparent drag image (we show our own badge)
    const img = new Image(); img.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
    e.dataTransfer.setDragImage(img, 0, 0);
});

document.addEventListener('drag', function(e) {
    if (_dragBadge && e.clientX > 0) {
        _dragBadge.style.left = (e.clientX + 12) + 'px';
        _dragBadge.style.top = (e.clientY - 12) + 'px';
    }
});

document.addEventListener('dragend', function(e) {
    // Clean up
    _dragSelectedSignals.forEach(id => {
        const el = document.getElementById(`sig-item-${id}`);
        if (el) el.classList.remove('sig-dragging');
    });
    if (_dragBadge) { _dragBadge.remove(); _dragBadge = null; }
    // Remove drop target highlights
    document.querySelectorAll('.graph-node.drop-target').forEach(n => n.classList.remove('drop-target'));
});

// Board drop handling — set up in renderBoard
function _setupBoardDropTargets(svg, zoomGroup, nodes) {
    const svgEl = svg.node();

    svgEl.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';

        // Find nearest thread node
        const [mx, my] = d3.pointer(e, zoomGroup.node());
        let closest = null, closestDist = Infinity;
        nodes.forEach(n => {
            if (n.type === 'narrative') return;
            if (n.id === _dragFromThreadId) return; // can't drop on source
            const dist = Math.sqrt((n.x - mx) ** 2 + (n.y - my) ** 2);
            const r = Math.sqrt(n.signal_count || 1) * 6 + 10;
            if (dist < r + 30 && dist < closestDist) { closest = n; closestDist = dist; }
        });

        // Highlight drop target
        document.querySelectorAll('.graph-node.drop-target').forEach(n => n.classList.remove('drop-target'));
        if (closest) {
            const nodeEl = document.querySelector(`.graph-node[data-node-id="${closest.id}"]`);
            if (nodeEl) nodeEl.classList.add('drop-target');
        }
    });

    svgEl.addEventListener('dragleave', function(e) {
        if (!svgEl.contains(e.relatedTarget)) {
            document.querySelectorAll('.graph-node.drop-target').forEach(n => n.classList.remove('drop-target'));
        }
    });

    svgEl.addEventListener('drop', function(e) {
        e.preventDefault();
        const targetEl = document.querySelector('.graph-node.drop-target');
        const signalIds = [..._dragSelectedSignals];
        if (!signalIds.length) return;

        if (targetEl) {
            // Drop on existing thread
            const toThreadId = parseInt(targetEl.dataset.nodeId);
            if (!toThreadId) return;
            targetEl.classList.remove('drop-target');
            targetEl.classList.add('absorbing');
            setTimeout(() => targetEl.classList.remove('absorbing'), 500);

            fetch('/api/signals/reassign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ signal_ids: signalIds, from_thread_id: _dragFromThreadId, to_thread_id: toThreadId })
            })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    _dragSelectedSignals.clear();
                    openThreadDetail(_dragFromThreadId);
                    loadBoard();
                }
            });
        } else {
            // Drop on empty space — create new thread
            const [dropX, dropY] = d3.pointer(e, zoomGroup.node());
            _showInlineInput(e.clientX, e.clientY, 'New thread name...', '', (title) => {
                if (!title) return;
                fetch('/api/signals/patterns', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title, signal_ids: signalIds })
                })
                .then(r => r.json())
                .then(data => {
                    if (data.ok) {
                        const newThreadId = data.pattern_id || data.cluster_id || data.id;
                        // Remove from old thread
                        if (_dragFromThreadId) {
                            fetch('/api/signals/reassign', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ signal_ids: signalIds, from_thread_id: _dragFromThreadId, to_thread_id: newThreadId })
                            }).then(() => {
                                // Save position at drop location
                                fetch('/api/board/positions', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ positions: [{ node_type: 'thread', node_id: newThreadId, x: dropX, y: dropY, pinned: true }] })
                                }).then(() => {
                                    _dragSelectedSignals.clear();
                                    openThreadDetail(_dragFromThreadId);
                                    loadBoard();
                                });
                            });
                        }
                    }
                });
            });
        }
    });
}

function _showNarrativeInBoardPane(narrativeId) {
    _activeNarrativeId = narrativeId;
    const detailBody = _showDetailPane('Narrative Detail');
    detailBody.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)">Loading narrative...</div>';

    fetch(`/api/narratives/${narrativeId}`)
        .then(r => r.json())
        .then(n => {
            if (n.error) { detailBody.innerHTML = `<div style="color:var(--red);padding:20px">${n.error}</div>`; return; }
            const ev = n.evidence || {};
            const sup = ev.supporting || 0, con = ev.contradicting || 0, neu = ev.neutral || 0;
            const total = sup + con + neu;
            const subClaims = n.sub_claims || [];
            const threads = n.threads || [];
            const queries = n.search_queries || [];

            detailBody.innerHTML = `
                <div style="padding:20px">
                    <h2 style="font-size:16px;font-weight:700;margin-bottom:8px">📖 ${escHtml(n.title)}</h2>
                    <div style="font-size:12px;color:var(--text-secondary);line-height:1.5;margin-bottom:12px;padding:10px;background:var(--bg-tertiary);border-radius:8px;border-left:3px solid var(--purple)">${escHtml(n.thesis)}</div>
                    ${n.reasoning ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:12px"><strong>Reasoning:</strong> ${escHtml(n.reasoning)}</div>` : ''}

                    ${total > 0 ? `<div style="margin-bottom:16px">
                        <div style="font-size:10px;font-weight:700;color:var(--text-muted);margin-bottom:4px">EVIDENCE</div>
                        <div style="display:flex;height:8px;border-radius:4px;overflow:hidden;background:var(--bg-tertiary);margin-bottom:4px">
                            ${sup > 0 ? `<div style="width:${sup/total*100}%;background:#22c55e"></div>` : ''}
                            ${neu > 0 ? `<div style="width:${neu/total*100}%;background:#6b7280"></div>` : ''}
                            ${con > 0 ? `<div style="width:${con/total*100}%;background:#ef4444"></div>` : ''}
                        </div>
                        <div style="display:flex;gap:12px;font-size:10px">
                            <span style="color:#22c55e">${sup} supporting</span>
                            <span style="color:#6b7280">${neu} neutral</span>
                            <span style="color:#ef4444">${con} contradicting</span>
                        </div>
                    </div>` : ''}

                    <div style="font-size:10px;font-weight:700;color:var(--text-muted);margin-bottom:6px">SUB-CLAIMS (${subClaims.length})</div>
                    ${subClaims.map((sc, i) => {
                        const thread = threads[i];
                        const sigCount = thread ? thread.signal_count || 0 : 0;
                        return `<div style="padding:8px 12px;background:var(--bg-tertiary);border-radius:8px;margin-bottom:6px;border-left:2px solid var(--purple)">
                            <div style="font-size:11px;font-weight:600;color:var(--text-primary)">${escHtml(sc.claim)}</div>
                            <div style="font-size:10px;color:var(--text-muted);margin-top:4px">${sigCount} signals ${thread ? `· <span style="color:var(--accent);cursor:pointer" onclick="openThreadDetail(${thread.id})">View thread →</span>` : ''}</div>
                        </div>`;
                    }).join('')}

                    <div style="display:flex;gap:8px;align-items:center;margin-top:16px">
                        <button onclick="runNarrativeSearch(${n.id})" id="narrative-search-btn" style="padding:6px 14px;background:var(--bg-tertiary);border:1px solid var(--accent);border-radius:6px;color:var(--accent);font-size:11px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:4px">🔍 Run Search</button>
                        <button onclick="_expandedNarratives.add(${n.id});loadBoard()" style="padding:6px 14px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;cursor:pointer">Expand on board</button>
                        <button onclick="deleteNarrative(${n.id})" style="padding:6px 10px;background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:10px;cursor:pointer;margin-left:auto">Delete</button>
                    </div>
                    <div id="narrative-search-log" style="display:none;margin-top:12px;max-height:200px;overflow-y:auto;font-size:10px;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:8px"></div>
                </div>`;
        });
}

function _boardAutoLayout() {
    if (!_boardData || !_boardData.nodes.length) return;
    const btn = document.getElementById('board-autolayout-btn');
    btn.textContent = '🔄 Arranging...';
    btn.disabled = true;

    const container = document.getElementById('sig-graph-container');
    const width = container.clientWidth;
    const height = container.clientHeight - 40;

    // Only auto-layout unpinned nodes; pinned nodes stay fixed
    const nodes = _boardData.nodes.filter(n => n.type !== 'narrative_thread' || _expandedNarratives.has(n.narrative_id))
        .filter(n => n.type !== 'narrative' || !_expandedNarratives.has(n.node_id))
        .map(d => {
            const copy = {...d};
            if (copy.x == null) copy.x = width / 2;
            if (copy.y == null) copy.y = height / 2;
            // Auto-layout ignores pinning — rearranges everything
            copy.fx = null; copy.fy = null;
            return copy;
        });

    const edges = (_boardData.edges || []).filter(e => {
        const ids = new Set(nodes.map(n => typeof n.id === 'string' ? n.id : n.id));
        return ids.has(e.source) && ids.has(e.target);
    });

    // Domain cluster positions — arrange domains in a grid
    const domList = Object.keys(_DOMAIN_COLORS);
    const cols = 3, rows = Math.ceil(domList.length / cols);
    const cellW = width / (cols + 1), cellH = height / (rows + 1);
    const domPos = {};
    domList.forEach((dom, i) => {
        domPos[dom] = { x: cellW * ((i % cols) + 1), y: cellH * (Math.floor(i / cols) + 1) };
    });

    const sim = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(edges).id(d => d.id).distance(120))
        .force('charge', d3.forceManyBody().strength(-150))
        .force('collision', d3.forceCollide().radius(d => Math.max(20, Math.sqrt(d.signal_count || 1) * 5 + 15)))
        // Pull nodes toward their domain cluster
        .force('x', d3.forceX(d => {
            const dom = _parseDomains(d.domain || '')[0];
            return (domPos[dom] || { x: width / 2 }).x;
        }).strength(0.3))
        .force('y', d3.forceY(d => {
            const dom = _parseDomains(d.domain || '')[0];
            return (domPos[dom] || { y: height / 2 }).y;
        }).strength(0.3))
        .stop();

    // Run simulation synchronously
    for (let i = 0; i < 300; i++) sim.tick();

    // Save all positions and mark as pinned
    const positions = nodes.map(n => ({
        node_type: n.type === 'narrative' ? 'narrative' : 'thread',
        node_id: n.type === 'narrative' ? n.node_id : n.id,
        x: n.x, y: n.y, pinned: true
    }));

    // Update board data in memory so renderBoard picks it up
    for (const n of nodes) {
        const orig = _boardData.nodes.find(o => o.id === n.id);
        if (orig) { orig.x = n.x; orig.y = n.y; orig.pinned = true; }
    }

    fetch('/api/board/positions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ positions })
    }).then(() => {
        btn.textContent = '🔄 Auto-layout';
        btn.disabled = false;
        loadBoard();
    });
}

function _updateBoardSelectionBar(nodes) {
    const sel = document.getElementById('sig-graph-selection');
    if (!sel) return;
    const count = _boardSelectedIds.size;
    if (count === 0) {
        sel.innerHTML = `<span style="color:var(--text-muted)">${(nodes||[]).length} threads · middle-click to connect · shift-click to select · double-click to add note</span>`;
    } else if (count === 1) {
        sel.innerHTML = `<span style="color:var(--accent);font-weight:600">1 selected</span> <span style="color:var(--text-muted)">— shift-click more to create narrative</span> <span style="color:var(--text-muted);cursor:pointer;text-decoration:underline" onclick="_boardSelectedIds.clear();loadBoard()">clear</span>`;
    } else {
        const ids = [..._boardSelectedIds];
        sel.innerHTML = `<span style="color:var(--accent);font-weight:600">${count} selected</span> <button onclick="_boardBrainstorm()" style="margin-left:8px;padding:4px 12px;background:linear-gradient(135deg,var(--accent),var(--purple));border:none;border-radius:6px;color:#fff;font-size:10px;font-weight:600;cursor:pointer">🧠 Brainstorm</button> <button onclick="_boardCreateNarrative()" style="margin-left:4px;padding:4px 12px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:6px;color:#fff;font-size:10px;font-weight:600;cursor:pointer">📖 Create Narrative</button> <span style="color:var(--text-muted);cursor:pointer;text-decoration:underline;margin-left:4px" onclick="_boardSelectedIds.clear();loadBoard()">clear</span>`;
    }
}

// ── Board Context Menu Helpers ──

function _startBoardConnect(nodeId, nx, ny) {
    // Reuse existing connection mode
    const svg = d3.select('#sig-graph-svg');
    const connectLine = svg.select('.board-connect-line');
    const zoomGroup = svg.select('.zoom-group');
    _connectingFrom = nodeId;
    connectLine.attr('x1', nx).attr('y1', ny).style('display', 'block');
    const sel = document.getElementById('sig-graph-selection');
    const thread = (_threadsCache || []).find(t => t.id === nodeId);
    if (sel) sel.innerHTML = `<span style="color:var(--accent);font-weight:600">🔗 Connecting from "${escHtml((thread?.title || '').substring(0,30))}" — click target node · Esc to cancel</span>`;
    svg.on('mousemove.connect', (mEvent) => {
        const [mx, my] = d3.pointer(mEvent, zoomGroup.node());
        connectLine.attr('x2', mx).attr('y2', my);
    });
}

function _boardLinkSelected(ids) {
    // Create thread_links between all pairs of selected nodes
    const pairs = [];
    for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
            pairs.push([ids[i], ids[j]]);
        }
    }
    Promise.all(pairs.map(([a, b]) =>
        fetch('/api/board/connect', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: a, target: b, label: '' })
        })
    )).then(() => {
        _showToast(`${pairs.length} connections created`, 'success');
        _boardSelectedIds.clear();
        loadBoard();
    });
}

function _boardMergeSelected(ids) {
    // Select the threads in the narrative selection set, then call merge
    _selectedThreadsForNarrative.clear();
    ids.forEach(id => _selectedThreadsForNarrative.add(id));
    _mergeThreads();
}

function _boardBulkDelete(ids) {
    _bulkDeleteThreads(ids);
}

function _findSimilarByEntities(threadId) {
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    if (!thread) return;
    _openDiscoveryDrawer({ type: 'thread', threadId, title: thread.title, method: 'entities' });
    _fetchDiscoveryResults(_discoveryBreadcrumb[0]);
}

function _findSimilarByDomain(threadId) {
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    if (!thread) return;
    _openDiscoveryDrawer({ type: 'thread', threadId, title: thread.title, method: 'domain' });
    _fetchDiscoveryResults(_discoveryBreadcrumb[0]);
}

function _findSimilarBySize(threadId) {
    const thread = (_threadsCache || []).find(t => t.id === threadId);
    if (!thread) return;
    _openDiscoveryDrawer({ type: 'thread', threadId, title: thread.title, method: 'size' });
    _fetchDiscoveryResults(_discoveryBreadcrumb[0]);
}

function _createNarrativeFromHypothesis(title, reasoning) {
    closeBrainstorm();
    document.getElementById('narrative-modal').style.display = 'flex';
    document.getElementById('narrative-thesis').value = title;
    document.getElementById('narrative-reasoning').value = reasoning;
    document.getElementById('narrative-thesis').focus();
}

function _boardBrainstorm() {
    const ids = [..._boardSelectedIds];
    if (ids.length < 2) return;
    _selectedThreadIds.clear();
    ids.forEach(id => _selectedThreadIds.add(id));
    d3.selectAll('.graph-node').classed('selected', d => _selectedThreadIds.has(d.id));
    const btn = document.getElementById('sig-brainstorm-btn');
    if (btn) btn.style.display = '';
    openBrainstormMode();
}

function _boardCreateNarrative() {
    const ids = [..._boardSelectedIds];
    const threads = ids.map(id => (_boardData?.nodes || []).find(n => n.id === id)).filter(Boolean);
    const titles = threads.map(t => t.title).join('; ');
    document.getElementById('narrative-modal').style.display = 'flex';
    document.getElementById('narrative-thesis').value = '';
    document.getElementById('narrative-reasoning').value = 'Based on these threads: ' + titles;
    document.getElementById('narrative-thesis').focus();
    window._pendingNarrativeThreadIds = ids;
}

