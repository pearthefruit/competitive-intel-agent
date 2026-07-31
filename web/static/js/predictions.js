/**
 * predictions.js — Predictions tab for SignalVault Signals module
 * Phases 1-3: loading, rendering, resolving falsifiable predictions.
 * Phase 4:
 *   - Surface 1: _renderPredictionsRibbon(parentKind, parentId, containerEl)
 *     Compact strip injected into signal/thread detail panes.
 *   - Surface 2: Timeline view inside Predictions tab (toggle button + _renderPredictionsTimeline)
 *   - Surface 3: Board overlay mini-panel (_overlayPredictionsOnBoard)
 *     APPROACH: Floating mini-panel (bottom-right of board container), NOT ghost nodes.
 *     Rationale: The board uses D3 force simulation with pinned positions saved to DB.
 *     Injecting synthetic nodes would break position persistence, physics freeze, and
 *     the domain-filter logic that checks real node attributes. A floating panel is
 *     fully decoupled from the D3 graph and cannot corrupt board state.
 */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────────────────
    let _predictionsCache = [];
    let _activeStatusFilter = '';
    let _predViewMode = 'list'; // 'list' | 'timeline'

    // ── Colours ────────────────────────────────────────────────────────────
    const STATUS_PILL = {
        open:      { bg: 'rgba(59,130,246,0.15)', color: '#3b82f6', border: 'rgba(59,130,246,0.3)',  label: 'Open',      dot: '#3b82f6' },
        confirmed: { bg: 'rgba(22,163,74,0.15)',  color: '#16a34a', border: 'rgba(22,163,74,0.3)',   label: 'Confirmed', dot: '#16a34a' },
        refuted:   { bg: 'rgba(239,68,68,0.15)',  color: '#ef4444', border: 'rgba(239,68,68,0.3)',   label: 'Refuted',   dot: '#ef4444' },
        dismissed: { bg: 'rgba(107,114,128,0.15)',color: '#6b7280', border: 'rgba(107,114,128,0.3)', label: 'Dismissed', dot: '#6b7280' },
        expired:   { bg: 'rgba(234,179,8,0.15)',  color: '#eab308', border: 'rgba(234,179,8,0.3)',   label: 'Expired',   dot: '#eab308' },
    };

    const INDICATOR_PILL = {
        leading:    { bg: 'rgba(168,85,247,0.15)',  color: '#a855f7', label: 'Leading' },
        concurrent: { bg: 'rgba(59,130,246,0.15)',  color: '#3b82f6', label: 'Concurrent' },
        lagging:    { bg: 'rgba(107,114,128,0.15)', color: '#6b7280', label: 'Lagging' },
    };

    // ── Public API ─────────────────────────────────────────────────────────

    window.loadPredictions = function (statusFilter) {
        if (statusFilter !== undefined) _activeStatusFilter = statusFilter;
        // Always reset to list mode when filter changes
        if (statusFilter !== undefined) _predViewMode = 'list';

        if (_predViewMode === 'timeline') {
            _loadPredictionsTimeline();
            return;
        }

        const params = new URLSearchParams();
        if (_activeStatusFilter) params.set('status', _activeStatusFilter);

        fetch('/api/predictions?' + params)
            .then(r => r.json())
            .then(data => {
                _predictionsCache = data.data || [];
                _renderPredictions(_predictionsCache);
            })
            .catch(err => {
                console.error('[predictions] load error:', err);
                _renderError('Failed to load predictions.');
            });
    };

    window.resolvePrediction = function (id, status) {
        const note = '';
        fetch(`/api/predictions/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status, resolution_note: note }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.error) { _showPredictionToast('Error: ' + data.error, true); return; }
                _showPredictionToast(`Prediction marked as ${status}.`);
                // Refresh whichever surfaces are showing this prediction
                if (document.getElementById('predictions-list')) loadPredictions();
                if (_activePredictionId === id && typeof openPredictionDetail === 'function') openPredictionDetail(id);
                if (typeof _overlayPredictionsOnBoard === 'function' && document.getElementById('sig-graph-container')) _overlayPredictionsOnBoard();
            })
            .catch(err => {
                console.error('[predictions] resolve error:', err);
                _showPredictionToast('Failed to resolve prediction.', true);
            });
    };

    // ── Rendering ──────────────────────────────────────────────────────────

    /**
     * Toggle the pane between list flow and full-height timeline flow.
     * List mode must keep the default block/overflow-y:auto behaviour or the
     * prediction cards stop scrolling, so the flex fill is opt-in via class.
     */
    function _setTimelineFill(on) {
        const tab = document.getElementById('sig-tab-predictions');
        if (tab) tab.classList.toggle('tl-fill', !!on);
    }

    // Dots are painted from data, so their handlers are delegated rather than
    // inlined — claim text routinely contains quotes and apostrophes, which
    // silently break inline onclick attributes built by string concatenation.
    let _tlDelegationBound = false;
    function _bindTimelineDelegation() {
        if (_tlDelegationBound) return;
        const container = document.getElementById('predictions-list');
        if (!container) return;
        container.addEventListener('click', (e) => {
            const hit = e.target.closest('.tl-dot-hit');
            if (hit && container.contains(hit)) {
                const id = parseInt(hit.dataset.predId, 10);
                if (!isNaN(id) && typeof openPredictionDetail === 'function') openPredictionDetail(id);
            }
        });
        _tlDelegationBound = true;
    }

    // Row count is derived from the band's height, so a pane resize has to
    // re-run the layout or the dots keep the old spread.
    let _tlResizeRaf = null;
    window.addEventListener('resize', () => {
        if (_predViewMode !== 'timeline') return;
        if (_tlResizeRaf) cancelAnimationFrame(_tlResizeRaf);
        _tlResizeRaf = requestAnimationFrame(() => _loadPredictionsTimeline());
    });

    function _renderPredictions(predictions) {
        const container = document.getElementById('predictions-list');
        if (!container) return;
        _setTimelineFill(false);

        if (!predictions.length) {
            container.innerHTML =
                _renderFilterRow() +
                `<div style="color:#6b7280;font-size:12px;text-align:center;padding:40px 0">
                    No predictions yet.<br>
                    <span style="font-size:11px;margin-top:6px;display:block">
                        Predictions are generated automatically when you capture a signal.
                    </span>
                    <button id="pred-backfill-btn" onclick="_runBackfill()"
                            style="margin-top:12px;padding:6px 16px;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.3);border-radius:8px;color:#3b82f6;font-size:11px;font-weight:600;cursor:pointer;transition:background .15s"
                            onmouseenter="this.style.background='rgba(59,130,246,0.2)'"
                            onmouseleave="this.style.background='rgba(59,130,246,0.1)'">
                        Backfill existing signals
                    </button>
                </div>`;
            return;
        }

        container.innerHTML = _renderFilterRow() + predictions.map(_renderCard).join('');
    }

    function _renderError(msg) {
        const container = document.getElementById('predictions-list');
        if (container) container.innerHTML = `<div style="color:#ef4444;font-size:12px;text-align:center;padding:40px 0">${msg}</div>`;
    }

    function _renderFilterRow() {
        const filters = [
            { label: 'All',       value: '' },
            { label: 'Open',      value: 'open' },
            { label: 'Confirmed', value: 'confirmed' },
            { label: 'Refuted',   value: 'refuted' },
            { label: 'Dismissed', value: 'dismissed' },
            { label: 'Expired',   value: 'expired' },
        ];
        const btns = filters.map(f => {
            const active = _activeStatusFilter === f.value;
            const style = active
                ? 'background:rgba(59,130,246,0.2);color:#3b82f6;border-color:rgba(59,130,246,0.4)'
                : 'background:rgba(255,255,255,0.04);color:#9ca3af;border-color:rgba(255,255,255,0.1)';
            return `<button onclick="loadPredictions('${f.value}')" style="padding:3px 10px;border:1px solid;border-radius:12px;font-size:11px;cursor:pointer;transition:all .15s;${style}">${f.label}</button>`;
        }).join('');

        // Timeline toggle — right-aligned
        const tlActive = _predViewMode === 'timeline';
        const tlStyle = tlActive
            ? 'background:rgba(168,85,247,0.2);color:#a855f7;border-color:rgba(168,85,247,0.4)'
            : 'background:rgba(255,255,255,0.04);color:#9ca3af;border-color:rgba(255,255,255,0.1)';
        const tlBtn = `<button onclick="_togglePredictionsView()" style="padding:3px 10px;border:1px solid;border-radius:12px;font-size:11px;cursor:pointer;transition:all .15s;margin-left:auto;${tlStyle}">&#128197; Timeline</button>`;

        return `<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:12px">${btns}${tlBtn}</div>`;
    }

    // Toggle between list and timeline
    window._togglePredictionsView = function () {
        _predViewMode = (_predViewMode === 'list') ? 'timeline' : 'list';
        if (_predViewMode === 'timeline') {
            _loadPredictionsTimeline();
        } else {
            loadPredictions();
        }
    };

    function _renderCard(p) {
        const sp = STATUS_PILL[p.status] || STATUS_PILL.open;
        const ip = INDICATOR_PILL[p.indicator_type] || INDICATOR_PILL.leading;
        const confidence = _renderConfidence(p.confidence || 3);
        const expectedBy = p.expected_by ? _formatDate(p.expected_by) : '—';
        const isOpen = p.status === 'open';

        const evParts = [];
        if (p.supports_count > 0) evParts.push(`<span style="color:#22c55e">${p.supports_count}&#8593;</span>`);
        if (p.refutes_count > 0) evParts.push(`<span style="color:#ef4444">${p.refutes_count}&#8595;</span>`);
        if (p.partial_count > 0) evParts.push(`<span style="color:#f59e0b">${p.partial_count}~</span>`);
        const evidenceBadge = p.evidence_count > 0
            ? `<span class="pred-evidence-badge" onclick="toggleEvidence(${p.id}, this)"
                 title="Click to see the signals recorded as evidence (${p.supports_count || 0} supporting, ${p.refutes_count || 0} refuting, ${p.partial_count || 0} partial)"
                 style="cursor:pointer; background:rgba(168,85,247,0.15); color:#a855f7;
                        border:1px solid rgba(168,85,247,0.3); border-radius:4px;
                        padding:2px 7px; font-size:11px; margin-left:6px;">
                 ${p.evidence_count} evidence${evParts.length ? ' &middot; ' + evParts.join(' ') : ''}</span>`
            : '';

        const overduePill = p.overdue
            ? `<span style="padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.04em;
                    background:rgba(234,179,8,0.15);color:#eab308;border:1px solid rgba(234,179,8,0.3)"
                    title="Past due but within the ${14}-day grace window — resolve it or it will auto-expire">Overdue</span>`
            : '';

        const sug = p.suggested_resolution;
        const suggestBanner = sug ? `
            <div style="margin-top:10px;padding:8px 10px;border-radius:8px;display:flex;justify-content:space-between;align-items:center;gap:10px;
                        background:${sug === 'confirmed' ? 'rgba(22,163,74,0.08)' : 'rgba(239,68,68,0.08)'};
                        border:1px solid ${sug === 'confirmed' ? 'rgba(22,163,74,0.3)' : 'rgba(239,68,68,0.3)'}">
                <span style="font-size:11px;color:${sug === 'confirmed' ? '#16a34a' : '#ef4444'}">
                    ${sug === 'confirmed'
                        ? `${p.supports_count} supporting signals &mdash; suggested resolution: <strong>Confirm</strong>`
                        : `${p.refutes_count} refuting signals &mdash; suggested resolution: <strong>Refute</strong>`}
                </span>
                <button onclick="resolvePrediction(${p.id},'${sug}')"
                    style="padding:4px 12px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap;
                           background:${sug === 'confirmed' ? 'rgba(22,163,74,0.18)' : 'rgba(239,68,68,0.18)'};
                           border:1px solid ${sug === 'confirmed' ? 'rgba(22,163,74,0.4)' : 'rgba(239,68,68,0.4)'};
                           color:${sug === 'confirmed' ? '#16a34a' : '#ef4444'}">Apply</button>
            </div>` : '';

        const actionBtns = isOpen ? `
            <div style="display:flex;gap:6px;margin-top:10px">
                <button onclick="resolvePrediction(${p.id},'confirmed')"
                    style="flex:1;padding:5px 0;background:rgba(22,163,74,0.12);border:1px solid rgba(22,163,74,0.3);border-radius:6px;color:#16a34a;font-size:11px;font-weight:600;cursor:pointer;transition:background .15s"
                    onmouseenter="this.style.background='rgba(22,163,74,0.22)'" onmouseleave="this.style.background='rgba(22,163,74,0.12)'">
                    &#10003; Confirm
                </button>
                <button onclick="resolvePrediction(${p.id},'refuted')"
                    style="flex:1;padding:5px 0;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);border-radius:6px;color:#ef4444;font-size:11px;font-weight:600;cursor:pointer;transition:background .15s"
                    onmouseenter="this.style.background='rgba(239,68,68,0.22)'" onmouseleave="this.style.background='rgba(239,68,68,0.12)'">
                    &#10007; Refute
                </button>
                <button onclick="resolvePrediction(${p.id},'dismissed')"
                    style="flex:1;padding:5px 0;background:rgba(107,114,128,0.1);border:1px solid rgba(107,114,128,0.3);border-radius:6px;color:#6b7280;font-size:11px;font-weight:600;cursor:pointer;transition:background .15s"
                    onmouseenter="this.style.background='rgba(107,114,128,0.2)'" onmouseleave="this.style.background='rgba(107,114,128,0.1)'">
                    &mdash; Dismiss
                </button>
            </div>` : '';

        const resolvedNote = (!isOpen && p.resolution_note) ? `
            <div style="margin-top:8px;padding:6px 8px;background:rgba(255,255,255,0.03);border-radius:6px;font-size:11px;color:#9ca3af;font-style:italic">"${_escHtml(p.resolution_note)}"</div>` : '';

        // Provenance: the signal/thread this prediction was generated from
        const ptTrunc = p.parent_title && p.parent_title.length > 70 ? p.parent_title.substring(0, 68) + '…' : (p.parent_title || '');
        const parentLine = p.parent_title ? `
            <div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.05);font-size:11px;color:#6b7280">
                From ${_escHtml(p.parent_kind || 'signal')}:
                <span onclick="_openPredictionParent('${_escHtml(p.parent_kind)}', ${p.parent_id})"
                      style="color:#3b82f6;cursor:pointer" title="${_escHtml(p.parent_title)}">${_escHtml(ptTrunc)} &rarr;</span>
            </div>` : '';

        return `
        <div class="pred-card" style="border:1px solid rgba(255,255,255,0.08);border-radius:10px;background:rgba(255,255,255,0.03);padding:12px;margin-bottom:10px">
            <!-- Header row: status + indicator + confidence + date -->
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px">
                <span style="padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.04em;
                    background:${sp.bg};color:${sp.color};border:1px solid ${sp.border}">${sp.label}</span>
                ${overduePill}
                <span style="padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;
                    background:${ip.bg};color:${ip.color}">${ip.label}</span>
                ${evidenceBadge}
                <span style="margin-left:auto;font-size:10px;color:#6b7280">Due ${expectedBy}</span>
                <span style="font-size:11px" title="Confidence">${confidence}</span>
            </div>
            <!-- Claim (click opens full detail in the right pane) -->
            <div onclick="openPredictionDetail(${p.id})" title="Open prediction detail"
                 style="font-size:12px;color:#e5e7eb;line-height:1.55;font-weight:500;margin-bottom:6px;cursor:pointer"
                 onmouseenter="this.style.color='#fff'" onmouseleave="this.style.color='#e5e7eb'">${_escHtml(p.claim)}</div>
            <!-- Mechanism -->
            ${p.mechanism ? `<div style="font-size:11px;color:#9ca3af;line-height:1.5;margin-bottom:4px"><span style="color:#6b7280;font-weight:600">Why: </span>${_escHtml(p.mechanism)}</div>` : ''}
            <!-- Falsifier -->
            ${p.falsifier ? `<div style="font-size:11px;color:#9ca3af;line-height:1.5"><span style="color:#6b7280;font-weight:600">Falsifier: </span>${_escHtml(p.falsifier)}</div>` : ''}
            ${parentLine}
            ${resolvedNote}
            ${suggestBanner}
            ${actionBtns}
        </div>`;
    }

    // Open the parent signal/thread a prediction was generated from.
    // Closes the overlay first so the detail pane is visible.
    window._openPredictionParent = function (kind, id) {
        if (typeof closePredictionsOverlay === 'function') closePredictionsOverlay();
        if (kind === 'thread') {
            if (typeof switchSignalTab === 'function') switchSignalTab('threads');
            if (typeof openThreadDetail === 'function') openThreadDetail(id);
        } else {
            if (typeof switchSignalTab === 'function') switchSignalTab('raw');
            if (typeof openSignalDetail === 'function') openSignalDetail(id);
        }
    };

    function _renderConfidence(score) {
        const filled = Math.round(score);
        let stars = '';
        for (let i = 1; i <= 5; i++) {
            stars += `<span style="color:${i <= filled ? '#eab308' : '#374151'}">&#9733;</span>`;
        }
        return `<span style="font-size:11px" title="Confidence ${filled}/5">${stars}</span>`;
    }

    function _formatDate(iso) {
        try {
            const d = new Date(iso);
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        } catch (_) { return iso; }
    }

    function _escHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // ── Evidence panel ─────────────────────────────────────────────────────

    window.toggleEvidence = async function (predId, el) {
        const existing = document.getElementById(`evidence-${predId}`);
        if (existing) { existing.remove(); return; }

        const res = await fetch(`/api/predictions/${predId}/evidence`);
        const json = await res.json();
        const items = json.data || [];

        const container = document.createElement('div');
        container.id = `evidence-${predId}`;
        container.style.cssText = 'margin-top:8px; padding:8px; background:rgba(255,255,255,0.03); border-radius:6px;';

        if (items.length === 0) {
            container.innerHTML = '<div style="color:#6b7280; font-size:11px;">No evidence signals yet.</div>';
        } else {
            container.innerHTML = items.map(e => `
                <div style="display:flex; gap:8px; align-items:baseline; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05);">
                    <span style="color:${e.stance==='supports'?'#22c55e':e.stance==='refutes'?'#ef4444':'#f59e0b'};
                                 font-size:10px; font-weight:600; min-width:52px;">${e.stance}</span>
                    <span style="color:#d1d5db; font-size:11px; flex:1;">${_escHtml(e.title)}</span>
                    <span style="color:#6b7280; font-size:10px;">${(e.weight*100).toFixed(0)}%</span>
                </div>
            `).join('');
        }

        el.closest('.pred-card').appendChild(container);
    };

    // ── Toast ──────────────────────────────────────────────────────────────

    function _showPredictionToast(msg, isError) {
        if (typeof _showToast === 'function') {
            _showToast(msg, isError ? 'error' : 'success');
            return;
        }
        const el = document.createElement('div');
        el.textContent = msg;
        el.style.cssText = `position:fixed;bottom:24px;right:24px;z-index:9999;padding:10px 18px;border-radius:8px;font-size:12px;font-weight:600;
            background:${isError ? '#7f1d1d' : '#14532d'};color:${isError ? '#fca5a5' : '#86efac'};
            border:1px solid ${isError ? '#dc2626' : '#16a34a'};box-shadow:0 4px 16px rgba(0,0,0,.5)`;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 3000);
    }

    // ══════════════════════════════════════════════════════════════════════
    // SURFACE 1: Predictions Ribbon
    // Injected into signal + thread detail panes after their main render.
    // ══════════════════════════════════════════════════════════════════════

    /**
     * Fetch and render a compact predictions strip into `containerEl`.
     * If there are 0 predictions, renders nothing (empty — no placeholder).
     *
     * @param {string} parentKind  'signal' | 'thread' | 'narrative'
     * @param {number} parentId    The parent record's primary key
     * @param {HTMLElement|null} containerEl  Target div (e.g. #signal-detail-predictions)
     */
    window._renderPredictionsRibbon = function (parentKind, parentId, containerEl) {
        if (!containerEl) return;
        containerEl.innerHTML = ''; // clear while loading

        fetch(`/api/predictions/for/${encodeURIComponent(parentKind)}/${parentId}`)
            .then(r => r.json())
            .then(json => {
                const preds = (json.data || []).slice(0, 3);

                if (!preds.length) {
                    // Show generate button for signals only
                    if (parentKind === 'signal') {
                        containerEl.innerHTML = `
                            <div style="padding:8px 0">
                                <button onclick="typeof _triggerSignalPredictions === 'function' && _triggerSignalPredictions(${parentId}, this)"
                                        style="font-size:11px;color:#6b7280;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:3px 10px;cursor:pointer;transition:color .15s,background .15s"
                                        onmouseenter="this.style.color='#9ca3af';this.style.background='rgba(255,255,255,0.08)'"
                                        onmouseleave="this.style.color='#6b7280';this.style.background='rgba(255,255,255,0.04)'">
                                    Generate predictions
                                </button>
                            </div>`;
                    }
                    return;
                }

                const items = preds.map(p => {
                    const sp = STATUS_PILL[p.status] || STATUS_PILL.open;
                    const date = p.expected_by ? _formatDate(p.expected_by) : '';
                    const claimTrunc = p.claim && p.claim.length > 80 ? p.claim.substring(0, 78) + '…' : (p.claim || '');
                    return `<div onclick="openPredictionDetail(${p.id})" style="display:flex;align-items:center;gap:6px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05);cursor:pointer;border-radius:4px"
                                 onmouseenter="this.style.background='rgba(59,130,246,0.08)'" onmouseleave="this.style.background=''" title="${_escHtml(p.claim)} — open detail">
                        <span style="color:${sp.dot};font-size:9px;flex-shrink:0">&#9679;</span>
                        <span style="font-size:11px;color:#d1d5db;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${_escHtml(claimTrunc)}</span>
                        ${date ? `<span style="font-size:10px;color:#6b7280;white-space:nowrap;flex-shrink:0">${date}</span>` : ''}
                    </div>`;
                }).join('');

                containerEl.innerHTML = `
                    <div style="margin-top:10px;padding:10px 12px;background:rgba(59,130,246,0.06);border:1px solid rgba(59,130,246,0.18);border-radius:8px">
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
                            <span style="font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">Predictions</span>
                            <span onclick="openPredictionsOverlay()" style="font-size:10px;color:#3b82f6;cursor:pointer;font-weight:600">View all &rarr;</span>
                        </div>
                        ${items}
                    </div>`;
            })
            .catch(err => {
                console.warn('[predictions ribbon] fetch error:', err);
            });
    };

    // "View all" now routes to the Predictions tab (the real destination).
    // Kept as named functions so existing callers keep working.
    window.openPredictionsOverlay = function () {
        if (typeof switchModule === 'function') switchModule('signals');
        if (typeof switchSignalTab === 'function') switchSignalTab('predictions');
    };
    window.closePredictionsOverlay = function () { /* no-op: tab-based now */ };

    // ══════════════════════════════════════════════════════════════════════
    // Prediction Detail — shared right pane
    // Opened by clicking a prediction anywhere (list card, board panel row,
    // timeline dot, ribbon). Shows the claim + full fields, the source it was
    // generated from, and the evidence signals — then resolve actions.
    // ══════════════════════════════════════════════════════════════════════

    let _activePredictionId = null;

    window.openPredictionDetail = function (predId) {
        _activePredictionId = predId;
        const detailBody = (typeof _showDetailPane === 'function')
            ? _showDetailPane('Prediction Detail')
            : document.getElementById('signals-detail-body');
        if (!detailBody) return;
        detailBody.innerHTML = `<div style="padding:24px;color:#6b7280;font-size:12px">Loading prediction…</div>`;

        fetch(`/api/predictions/${predId}`)
            .then(r => r.json())
            .then(json => {
                if (_activePredictionId !== predId) return; // superseded
                if (!json.prediction) { detailBody.innerHTML = `<div style="padding:24px;color:#ef4444;font-size:12px">Prediction not found.</div>`; return; }
                detailBody.innerHTML = _renderPredictionDetail(json.prediction, json.evidence || []);
            })
            .catch(() => {
                detailBody.innerHTML = `<div style="padding:24px;color:#ef4444;font-size:12px">Failed to load prediction.</div>`;
            });
    };

    function _renderPredictionDetail(p, evidence) {
        const sp = STATUS_PILL[p.status] || STATUS_PILL.open;
        const ip = INDICATOR_PILL[p.indicator_type] || INDICATOR_PILL.leading;
        const isOpen = p.status === 'open';
        const expectedBy = p.expected_by ? _formatDate(p.expected_by) : '—';

        const overduePill = p.overdue
            ? `<span style="padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;background:rgba(234,179,8,0.15);color:#eab308;border:1px solid rgba(234,179,8,0.3)">Overdue</span>` : '';

        // Source (generated-from) block
        const sourceBlock = p.parent_id ? `
            <div style="margin-top:16px">
                <div style="font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Generated from</div>
                <div onclick="_openPredictionParent('${_escHtml(p.parent_kind || 'signal')}', ${p.parent_id})"
                     style="padding:8px 10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:8px;cursor:pointer;display:flex;align-items:center;gap:8px"
                     onmouseenter="this.style.background='rgba(59,130,246,0.08)'" onmouseleave="this.style.background='rgba(255,255,255,0.03)'">
                    <span style="font-size:9px;color:#6b7280;text-transform:uppercase;flex-shrink:0">${_escHtml(p.parent_kind || 'signal')}</span>
                    <span style="font-size:12px;color:#d1d5db;flex:1">${_escHtml(p.parent_title || '(source ' + p.parent_id + ')')}</span>
                    <span style="color:#3b82f6;font-size:12px">&rarr;</span>
                </div>
            </div>` : '';

        // Evidence block
        let evidenceBlock = '';
        if (evidence.length) {
            const rows = evidence.map(e => {
                const col = e.stance === 'supports' ? '#22c55e' : e.stance === 'refutes' ? '#ef4444' : '#f59e0b';
                return `<div onclick="_openPredictionEvidenceSignal(${e.signal_id})"
                             style="padding:7px 10px;border-bottom:1px solid rgba(255,255,255,0.05);cursor:pointer;display:flex;gap:8px;align-items:baseline"
                             onmouseenter="this.style.background='rgba(255,255,255,0.03)'" onmouseleave="this.style.background=''">
                    <span style="color:${col};font-size:10px;font-weight:600;min-width:54px;text-transform:capitalize">${_escHtml(e.stance)}</span>
                    <span style="color:#d1d5db;font-size:12px;flex:1">${_escHtml(e.title || '')}</span>
                    <span style="color:#6b7280;font-size:10px">${Math.round((e.weight || 0) * 100)}%</span>
                </div>${e.note ? `<div style="font-size:10px;color:#6b7280;font-style:italic;padding:0 10px 6px 64px">${_escHtml(e.note)}</div>` : ''}`;
            }).join('');
            evidenceBlock = `
                <div style="margin-top:16px">
                    <div style="font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">
                        Evidence signals (${evidence.length})
                    </div>
                    <div style="border:1px solid rgba(255,255,255,0.08);border-radius:8px;overflow:hidden">${rows}</div>
                </div>`;
        } else {
            evidenceBlock = `
                <div style="margin-top:16px">
                    <div style="font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Evidence signals</div>
                    <div style="font-size:11px;color:#6b7280;padding:10px;background:rgba(255,255,255,0.02);border-radius:8px">No signals matched to this prediction yet. New signals are checked against open predictions on capture.</div>
                </div>`;
        }

        const sug = p.suggested_resolution;
        const suggestBanner = sug ? `
            <div style="margin-top:14px;padding:8px 10px;border-radius:8px;display:flex;justify-content:space-between;align-items:center;gap:10px;
                        background:${sug === 'confirmed' ? 'rgba(22,163,74,0.08)' : 'rgba(239,68,68,0.08)'};
                        border:1px solid ${sug === 'confirmed' ? 'rgba(22,163,74,0.3)' : 'rgba(239,68,68,0.3)'}">
                <span style="font-size:11px;color:${sug === 'confirmed' ? '#16a34a' : '#ef4444'}">
                    ${sug === 'confirmed' ? `${p.supports_count} supporting signals — suggested: <strong>Confirm</strong>` : `${p.refutes_count} refuting signals — suggested: <strong>Refute</strong>`}
                </span>
                <button onclick="resolvePrediction(${p.id},'${sug}')" style="padding:4px 12px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap;background:${sug === 'confirmed' ? 'rgba(22,163,74,0.18)' : 'rgba(239,68,68,0.18)'};border:1px solid ${sug === 'confirmed' ? 'rgba(22,163,74,0.4)' : 'rgba(239,68,68,0.4)'};color:${sug === 'confirmed' ? '#16a34a' : '#ef4444'}">Apply</button>
            </div>` : '';

        const actionBtns = isOpen ? `
            <div style="display:flex;gap:6px;margin-top:16px">
                <button onclick="resolvePrediction(${p.id},'confirmed')" style="flex:1;padding:7px 0;background:rgba(22,163,74,0.12);border:1px solid rgba(22,163,74,0.3);border-radius:6px;color:#16a34a;font-size:12px;font-weight:600;cursor:pointer">&#10003; Confirm</button>
                <button onclick="resolvePrediction(${p.id},'refuted')" style="flex:1;padding:7px 0;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);border-radius:6px;color:#ef4444;font-size:12px;font-weight:600;cursor:pointer">&#10007; Refute</button>
                <button onclick="resolvePrediction(${p.id},'dismissed')" style="flex:1;padding:7px 0;background:rgba(107,114,128,0.1);border:1px solid rgba(107,114,128,0.3);border-radius:6px;color:#6b7280;font-size:12px;font-weight:600;cursor:pointer">&mdash; Dismiss</button>
            </div>` : '';

        const resolvedNote = (!isOpen && p.resolution_note)
            ? `<div style="margin-top:12px;padding:8px 10px;background:rgba(255,255,255,0.03);border-radius:6px;font-size:11px;color:#9ca3af;font-style:italic">"${_escHtml(p.resolution_note)}"</div>` : '';

        return `
        <div style="padding:16px 20px">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:10px">
                <span style="padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.04em;background:${sp.bg};color:${sp.color};border:1px solid ${sp.border}">${sp.label}</span>
                ${overduePill}
                <span style="padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;background:${ip.bg};color:${ip.color}">${ip.label}</span>
                <span style="margin-left:auto;font-size:11px;color:#6b7280">Due ${expectedBy}</span>
                <span style="font-size:11px">${_renderConfidence(p.confidence || 3)}</span>
            </div>
            <div style="font-size:14px;color:#e5e7eb;line-height:1.55;font-weight:500;margin-bottom:12px">${_escHtml(p.claim)}</div>
            ${p.mechanism ? `<div style="font-size:12px;color:#9ca3af;line-height:1.55;margin-bottom:8px"><span style="color:#6b7280;font-weight:600">Why: </span>${_escHtml(p.mechanism)}</div>` : ''}
            ${p.falsifier ? `<div style="font-size:12px;color:#9ca3af;line-height:1.55"><span style="color:#6b7280;font-weight:600">Falsifier: </span>${_escHtml(p.falsifier)}</div>` : ''}
            ${suggestBanner}
            ${actionBtns}
            ${resolvedNote}
            ${sourceBlock}
            ${evidenceBlock}
        </div>`;
    }

    // Open an evidence signal in the shared pane, then restore focus context.
    window._openPredictionEvidenceSignal = function (signalId) {
        if (typeof switchSignalTab === 'function' && typeof _signalTab !== 'undefined' && _signalTab !== 'raw' && _signalTab !== 'graph') {
            switchSignalTab('raw');
        }
        if (typeof openSignalDetail === 'function') openSignalDetail(signalId);
    };

    // ── Per-signal prediction trigger ──────────────────────────────────────

    /**
     * Trigger prediction generation for a single signal on demand.
     * Called from the "Generate predictions" button in the signal detail pane.
     */
    window._triggerSignalPredictions = async function (signalId, buttonEl) {
        buttonEl.disabled = true;
        buttonEl.textContent = 'Generating…';
        try {
            const res = await fetch(`/api/signals/${signalId}/generate-predictions`, { method: 'POST' });
            const json = await res.json();
            if (json.error) throw new Error(json.error);
            buttonEl.textContent = '✓ Check back in ~10s';
            buttonEl.style.color = '#22c55e';
        } catch (e) {
            buttonEl.textContent = 'Failed';
            buttonEl.style.color = '#ef4444';
            setTimeout(() => {
                buttonEl.disabled = false;
                buttonEl.textContent = 'Generate predictions';
                buttonEl.style.color = '';
            }, 2000);
        }
    };

    // ══════════════════════════════════════════════════════════════════════
    // SURFACE 2: Timeline View
    // Horizontal timeline of predictions plotted by expected_by date.
    // Triggered by the "Timeline" toggle in the Predictions tab filter row.
    // ══════════════════════════════════════════════════════════════════════

    function _loadPredictionsTimeline() {
        fetch('/api/predictions')
            .then(r => r.json())
            .then(json => {
                const container = document.getElementById('predictions-list');
                if (!container) return;
                // Render header row with toggle set to timeline mode
                container.innerHTML = _renderFilterRow();
                _renderPredictionsTimeline(json.data || []);
            })
            .catch(err => {
                console.error('[predictions timeline] load error:', err);
                _renderError('Failed to load predictions for timeline.');
            });
    }

    let _tlZoom = 1; // 1 | 1.5 | 2 | 3 | 4 — inner width multiplier

    window._tlZoomStep = function (dir) {
        const steps = [1, 1.5, 2, 3, 4];
        const idx = steps.indexOf(_tlZoom);
        const next = steps[Math.min(steps.length - 1, Math.max(0, idx + dir))];
        if (next === _tlZoom) return;
        _tlZoom = next;
        _loadPredictionsTimeline();
    };

    /**
     * Render a div-based horizontal timeline of dated predictions.
     * Appended directly to #predictions-list (after filter row).
     * Zoomable: inner axis width = _tlZoom × container, scrolls horizontally.
     * Claim labels only render at zoom ≥ 2 (dots + tooltips below that).
     * @param {Array} predictions  All predictions from /api/predictions
     */
    window._renderPredictionsTimeline = function (predictions) {
        const container = document.getElementById('predictions-list');
        if (!container) return;
        _setTimelineFill(true);
        _bindTimelineDelegation();

        // Filter to predictions with expected_by dates, sorted ascending
        const dated = predictions
            .filter(p => p.expected_by)
            .sort((a, b) => a.expected_by.localeCompare(b.expected_by));

        if (!dated.length) {
            _setTimelineFill(false);   // nothing to fill; let the message center normally
            container.innerHTML += '<div style="color:#6b7280;text-align:center;padding:40px">No dated predictions to display.</div>';
            return;
        }

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        // Overdue predictions (due before today, still open) get a gutter count
        // instead of being clamped onto the "Today" line.
        const overdue = dated.filter(p => new Date(p.expected_by) < today && p.status === 'open');
        const future = dated.filter(p => new Date(p.expected_by) >= today);

        // Axis: today → latest expected_by + 1 month padding, max 12 months out
        const maxMs = future.length ? Math.max(...future.map(p => new Date(p.expected_by).getTime())) : today.getTime();
        const maxDate = new Date(Math.min(maxMs + 30 * 86400000, today.getTime() + 365 * 86400000));
        maxDate.setDate(1);
        maxDate.setMonth(maxDate.getMonth() + 1);

        const totalMs = maxDate - today;

        // Month markers — with year on January and on the first marker
        const months = [];
        const cursor = new Date(today);
        cursor.setDate(1);
        cursor.setMonth(cursor.getMonth() + 1);
        let first = true;
        while (cursor <= maxDate && totalMs > 0) {
            const pct = ((cursor - today) / totalMs) * 100;
            const yr = (first || cursor.getMonth() === 0) ? ` '${String(cursor.getFullYear()).slice(2)}` : '';
            months.push({ label: cursor.toLocaleDateString('en-US', { month: 'short' }) + yr, pct });
            cursor.setMonth(cursor.getMonth() + 1);
            first = false;
        }

        const monthMarkersHtml = months.map(m =>
            `<div style="position:absolute;left:${m.pct.toFixed(1)}%;top:0;bottom:0;border-left:1px dashed rgba(255,255,255,0.06);pointer-events:none">
                <span style="position:absolute;top:-18px;left:2px;font-size:9px;color:#4b5563;white-space:nowrap">${m.label}</span>
            </div>`
        ).join('');

        const showLabels = _tlZoom >= 2;

        const overdueChip = overdue.length
            ? `<span onclick="loadPredictions('open')" title="${overdue.length} open predictions past their due date — click to review in list view"
                     style="font-size:10px;color:#eab308;background:rgba(234,179,8,0.12);border:1px solid rgba(234,179,8,0.3);border-radius:10px;padding:2px 8px;cursor:pointer;font-weight:600">&#9888; ${overdue.length} overdue</span>`
            : '';

        const zoomControls = `
            <div style="display:flex;align-items:center;gap:6px">
                ${overdueChip}
                <span style="font-size:10px;color:#6b7280;margin-left:6px">Zoom</span>
                <button onclick="_tlZoomStep(-1)" ${_tlZoom <= 1 ? 'disabled' : ''} style="width:22px;height:22px;border:1px solid rgba(255,255,255,0.15);border-radius:6px;background:rgba(255,255,255,0.04);color:#9ca3af;font-size:13px;cursor:pointer;line-height:1;${_tlZoom <= 1 ? 'opacity:0.35;cursor:default' : ''}">&minus;</button>
                <span style="font-size:10px;color:#9ca3af;min-width:26px;text-align:center">${_tlZoom}x</span>
                <button onclick="_tlZoomStep(1)" ${_tlZoom >= 4 ? 'disabled' : ''} style="width:22px;height:22px;border:1px solid rgba(255,255,255,0.15);border-radius:6px;background:rgba(255,255,255,0.04);color:#9ca3af;font-size:13px;cursor:pointer;line-height:1;${_tlZoom >= 4 ? 'opacity:0.35;cursor:default' : ''}">+</button>
            </div>`;

        // Shell first, dots second. The number of rows depends on how tall the
        // band actually ends up, and that is only knowable once it is in the DOM
        // and flex has resolved — so the dots are rendered in a second pass below.
        const timelineHtml = `
            <div id="predictions-timeline" style="margin-top:8px;margin-bottom:4px">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-shrink:0">
                    <span style="font-size:10px;color:#6b7280">${future.length} upcoming · dots are clickable${showLabels ? '' : ' · zoom in for labels'}</span>
                    ${zoomControls}
                </div>
                <div class="tl-scroll" style="overflow-x:auto;overflow-y:hidden;padding-bottom:6px">
                    <div class="tl-inner" style="position:relative;width:${(_tlZoom * 100).toFixed(0)}%;min-width:100%;padding:0 8px">
                        <div style="position:relative;height:20px;margin-bottom:4px;flex-shrink:0">${monthMarkersHtml}</div>
                        <div class="tl-band" id="tl-band" style="position:relative;min-height:120px;border-top:2px solid rgba(255,255,255,0.12);border-bottom:1px solid rgba(255,255,255,0.05)">
                            <div style="position:absolute;left:0;top:0;bottom:0;border-left:2px solid rgba(59,130,246,0.6);z-index:3;pointer-events:none">
                                <span style="position:absolute;top:2px;left:4px;font-size:8px;color:#3b82f6;font-weight:700;white-space:nowrap">Today</span>
                            </div>
                        </div>
                    </div>
                </div>
                <div style="display:flex;gap:12px;margin-top:10px;flex-wrap:wrap;flex-shrink:0">
                    ${Object.entries(STATUS_PILL).map(([k, v]) =>
                        `<span style="font-size:10px;color:${v.color};display:flex;align-items:center;gap:3px">
                            <span style="width:8px;height:8px;border-radius:50%;background:${v.dot};display:inline-block"></span>${v.label}
                        </span>`
                    ).join('')}
                </div>
            </div>`;

        container.innerHTML += timelineHtml;
        _paintTimelineDots(future, today, totalMs, showLabels);
    };

    /**
     * Second render pass: fill the (now measured) band with dots.
     *
     * Rows are derived from the band's real height rather than hardcoded, so the
     * timeline uses whatever vertical space the pane gives it. The previous fixed
     * 3 rows meant ~175 predictions piled into a 76px strip — dots overlapped each
     * other and the 9px hit targets were nearly unclickable.
     */
    function _paintTimelineDots(future, today, totalMs, showLabels, _retry) {
        const band = document.getElementById('tl-band');
        if (!band) return;

        const ROW_H = showLabels ? 34 : 26;   // per-row pitch, incl. label space
        const PAD = 6;

        // A band measuring 0 means flex has not resolved yet (tab still being
        // shown). Measuring anyway would silently collapse to the 3-row minimum,
        // which is the exact bug this pass exists to fix — so wait one frame.
        if (!band.clientHeight && !_retry) {
            requestAnimationFrame(() => _paintTimelineDots(future, today, totalMs, showLabels, true));
            return;
        }
        const h = band.clientHeight || 120;
        // Clamped: below 3 rows the spread is pointless, above 14 the dots get
        // too fine to aim at even though they would technically fit.
        const rows = Math.max(3, Math.min(14, Math.floor((h - PAD * 2) / ROW_H)));

        // Lane packing, not round-robin. Round-robin (i % rows) spreads dots
        // evenly but makes vertical position meaningless — sparse weeks render as
        // tall a stack as busy ones, so the chart reads as a uniform grid and
        // hides the density it exists to show. Instead each dot takes the lowest
        // lane whose last dot is far enough left, so height genuinely tracks
        // how many predictions cluster on a date.
        const bandW = band.clientWidth || 800;
        const LABEL_MAX = _tlZoom >= 3 ? 130 : 90;
        const DOT_HALF = 11;
        const LABEL_HALF = LABEL_MAX / 2;   // labels are centred on their dot
        // Right edge of the last item placed in each lane, so collision tests
        // account for the label's real footprint rather than the dot's.
        const laneRight = new Array(rows).fill(-Infinity);
        const rowStep = (h - PAD * 2 - ROW_H) / Math.max(1, rows - 1);

        const dotsHtml = future.map((p) => {
            const pct = Math.max(0, Math.min(99, ((new Date(p.expected_by) - today) / totalMs) * 100));
            const x = (pct / 100) * bandW;

            // Label only where a lane can actually fit the text. Labelling every
            // dot at this density produced ~250 overlapping label pairs — the
            // claims rendered on top of each other and none were readable. A dot
            // that cannot be labelled still gets placed, just bare; the header
            // already tells the user to zoom in for labels.
            let row = -1, labelled = false;
            if (showLabels) {
                row = laneRight.findIndex(right => x - LABEL_HALF >= right);
                labelled = row !== -1;
            }
            if (row === -1) row = laneRight.findIndex(right => x - DOT_HALF >= right);
            if (row === -1) {
                // Every lane is occupied at this x — overflow into the lane with
                // the most room rather than dropping the dot.
                row = laneRight.indexOf(Math.min(...laneRight));
                labelled = false;
            }
            laneRight[row] = x + (labelled ? LABEL_HALF : DOT_HALF);

            const top = PAD + row * rowStep;
            const sp = STATUS_PILL[p.status] || STATUS_PILL.open;
            const claimTrunc = p.claim && p.claim.length > 40 ? p.claim.substring(0, 38) + '…' : (p.claim || '');
            const label = labelled
                ? `<span class="tl-dot-label" style="position:absolute;top:19px;font-size:8px;color:#9ca3af;white-space:nowrap;max-width:${LABEL_MAX}px;overflow:hidden;text-overflow:ellipsis;text-align:center;pointer-events:none">${_escHtml(claimTrunc)}</span>`
                : '';
            return `<div class="tl-dot-hit" data-pred-id="${p.id}"
                         style="position:absolute;left:${pct.toFixed(2)}%;top:${top.toFixed(1)}px;transform:translateX(-50%);z-index:2"
                         title="${_escHtml(p.claim)} — ${_formatDate(p.expected_by)}${p.parent_title ? ' (from: ' + _escHtml(p.parent_title) + ')' : ''}">
                    <div class="tl-dot" style="width:12px;height:12px;border-radius:50%;background:${sp.dot};box-shadow:0 0 6px ${sp.dot}66"></div>
                    ${label}
                </div>`;
        }).join('');

        // insertAdjacentHTML, not innerHTML — the "Today" marker is already a
        // child of the band and must survive the dot paint.
        band.insertAdjacentHTML('beforeend', dotsHtml);
    }

    // ══════════════════════════════════════════════════════════════════════
    // SURFACE 3: Board Overlay — Floating Mini-Panel
    //
    // APPROACH: floating div panel (position:absolute, bottom-right of board
    // container), NOT ghost nodes injected into the D3 simulation.
    //
    // Why NOT ghost nodes:
    //   1. Board positions are persisted to DB via /api/board/positions.
    //      Ghost nodes would get their positions saved on drag/physics-freeze,
    //      corrupting the predictions data with board layout coordinates.
    //   2. The D3 force simulation's collision/charge forces would push real
    //      thread nodes apart whenever ghost nodes are present, changing the
    //      layout on every board render.
    //   3. Ghost nodes require hooking into renderBoard() which is called
    //      frequently; any timing error leaves orphaned SVG elements.
    //   4. The board domain-filter logic reads `d.domain` from node data —
    //      synthetic nodes lack this field and would throw errors.
    //
    // The floating panel approach is zero-risk and fully decoupled from D3.
    // ══════════════════════════════════════════════════════════════════════

    let _boardPredPanel = null;
    let _boardPredData = []; // cached board predictions

    /**
     * Fetch open/confirmed predictions and render the board overlay mini-panel.
     * Called from loadBoard() after renderBoard() completes.
     */
    window._overlayPredictionsOnBoard = async function () {
        try {
            const res = await fetch('/api/predictions?board=1'); // board=1 already filters to open+confirmed
            const json = await res.json();
            _boardPredData = json.data || [];
            _renderBoardPredPanel(_boardPredData);
        } catch (err) {
            console.warn('[predictions board overlay] fetch error:', err);
        }
    };

    /**
     * Render (or update) the floating predictions panel on the board.
     * Optionally filtered by threadId when a thread is selected.
     * @param {Array}       allPreds   All board predictions (pre-fetched)
     * @param {number|null} threadId   If set, filter to predictions for this thread
     */
    function _renderBoardPredPanel(allPreds, threadId) {
        const container = document.getElementById('sig-graph-container');
        if (!container) return;

        // Remove existing panel
        if (_boardPredPanel) { _boardPredPanel.remove(); _boardPredPanel = null; }

        // Filter: if threadId given, show only thread-level predictions for that
        // thread; otherwise show all open predictions.
        const filtered = threadId != null
            ? allPreds.filter(p => p.parent_kind === 'thread' && p.parent_id === threadId)
            : allPreds.filter(p => p.status === 'open').slice(0, 8);

        const panel = document.createElement('div');
        panel.id = 'board-pred-panel';
        _boardPredPanel = panel;
        panel.style.cssText = [
            'position:absolute', 'bottom:16px', 'right:16px', 'width:230px',
            'background:rgba(10,10,10,0.92)', 'border:1px solid rgba(59,130,246,0.3)',
            'border-radius:10px', 'padding:10px 12px', 'z-index:20', 'pointer-events:all',
            'box-shadow:0 4px 20px rgba(0,0,0,0.6)', 'max-height:300px', 'overflow-y:auto',
        ].join(';');

        const title = threadId != null ? 'Predictions for thread' : `Open predictions (${filtered.length})`;
        const backToAll = threadId != null
            ? `<span onclick="_boardPredShowAll()" title="Show all open predictions" style="font-size:9px;color:#3b82f6;cursor:pointer;font-weight:600">&larr; All</span>`
            : '';

        const rows = filtered.length ? filtered.map(p => {
            const sp = STATUS_PILL[p.status] || STATUS_PILL.open;
            const date = p.expected_by ? _formatDate(p.expected_by) : '';
            const claimTrunc = p.claim && p.claim.length > 55 ? p.claim.substring(0, 53) + '…' : (p.claim || '');
            return `<div class="board-pred-row" data-pred-id="${p.id}"
                         style="padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.06);cursor:pointer;border-radius:4px"
                         title="${_escHtml(p.claim)} — open prediction detail"
                         onmouseenter="this.style.background='rgba(59,130,246,0.08)'" onmouseleave="this.style.background=''">
                <div style="display:flex;align-items:center;gap:5px">
                    <span style="color:${sp.dot};font-size:8px;flex-shrink:0">&#9679;</span>
                    <span style="font-size:10px;color:#d1d5db;flex:1;line-height:1.3">${_escHtml(claimTrunc)}</span>
                </div>
                <div style="font-size:9px;color:#6b7280;margin-top:2px;padding-left:13px">${date ? `Due ${date}` : ''}${p.parent_title ? `${date ? ' · ' : ''}from: ${_escHtml(p.parent_title.length > 40 ? p.parent_title.substring(0, 38) + '…' : p.parent_title)}` : ''}</div>
            </div>`;
        }).join('')
        : `<div style="font-size:10px;color:#6b7280;padding:8px 0;line-height:1.4">${threadId != null ? 'No predictions for this thread yet.' : 'No open predictions.'}</div>`;

        panel.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;gap:8px">
                <span style="font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">&#128302; ${_escHtml(title)}</span>
                <span style="display:flex;align-items:center;gap:8px">${backToAll}
                    <span onclick="_clearBoardPredPanel()" title="Hide panel" style="font-size:12px;color:#6b7280;cursor:pointer;line-height:1">&times;</span>
                </span>
            </div>
            ${rows}
            <div style="margin-top:8px;text-align:right">
                <span onclick="openPredictionsOverlay()" style="font-size:10px;color:#3b82f6;cursor:pointer;font-weight:600">All predictions &rarr;</span>
            </div>`;

        // Row click → open prediction detail in the shared pane (event delegation)
        panel.addEventListener('click', (e) => {
            const row = e.target.closest('.board-pred-row');
            if (!row) return;
            const id = parseInt(row.dataset.predId, 10);
            if (id && typeof openPredictionDetail === 'function') openPredictionDetail(id);
        });

        container.style.position = 'relative'; // ensure absolute children are positioned correctly
        container.appendChild(panel);
    }

    /**
     * Update the board panel to show predictions for a specific thread.
     * Called from openThreadDetail() when on the board tab.
     */
    window._updateBoardPredPanelForThread = function (threadId) {
        if (!_boardPredData.length) return; // overlay not yet loaded — skip
        _renderBoardPredPanel(_boardPredData, threadId);
    };

    /** Reset the board panel to show all open predictions (persist, don't hide). */
    window._boardPredShowAll = function () {
        if (!_boardPredData.length) return;
        _renderBoardPredPanel(_boardPredData, null);
    };

    /** Explicitly hide the board predictions panel (× button). */
    window._clearBoardPredPanel = function () {
        if (_boardPredPanel) { _boardPredPanel.remove(); _boardPredPanel = null; }
    };

    // ── Backfill ───────────────────────────────────────────────────────────

    /**
     * Run backfill endpoint to generate predictions for all signals that have none.
     * Called from the empty-state button in the Predictions tab.
     */
    window._runBackfill = function () {
        const btn = document.getElementById('pred-backfill-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
        fetch('/api/predictions/backfill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ limit: 100 }),
        })
            .then(r => r.json())
            .then(data => {
                const msg = (data.data && data.data.message) ? data.data.message : 'Done';
                if (btn) { btn.textContent = '✓ ' + msg; }
                // Reload predictions list after estimated completion time
                setTimeout(() => loadPredictions(), 15000);
            })
            .catch(() => {
                if (btn) { btn.textContent = 'Failed — retry'; btn.disabled = false; }
            });
    };

})();
