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
                loadPredictions();
            })
            .catch(err => {
                console.error('[predictions] resolve error:', err);
                _showPredictionToast('Failed to resolve prediction.', true);
            });
    };

    // ── Rendering ──────────────────────────────────────────────────────────

    function _renderPredictions(predictions) {
        const container = document.getElementById('predictions-list');
        if (!container) return;

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

        const evidenceBadge = p.evidence_count > 0
            ? `<span class="pred-evidence-badge" onclick="toggleEvidence(${p.id}, this)"
                 style="cursor:pointer; background:rgba(168,85,247,0.15); color:#a855f7;
                        border:1px solid rgba(168,85,247,0.3); border-radius:4px;
                        padding:2px 7px; font-size:11px; margin-left:6px;">
                 ${p.evidence_count} evidence</span>`
            : '';

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

        return `
        <div class="pred-card" style="border:1px solid rgba(255,255,255,0.08);border-radius:10px;background:rgba(255,255,255,0.03);padding:12px;margin-bottom:10px">
            <!-- Header row: status + indicator + confidence + date -->
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px">
                <span style="padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.04em;
                    background:${sp.bg};color:${sp.color};border:1px solid ${sp.border}">${sp.label}</span>
                <span style="padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;
                    background:${ip.bg};color:${ip.color}">${ip.label}</span>
                ${evidenceBadge}
                <span style="margin-left:auto;font-size:10px;color:#6b7280">Due ${expectedBy}</span>
                <span style="font-size:11px" title="Confidence">${confidence}</span>
            </div>
            <!-- Claim -->
            <div style="font-size:12px;color:#e5e7eb;line-height:1.55;font-weight:500;margin-bottom:6px">${_escHtml(p.claim)}</div>
            <!-- Mechanism -->
            ${p.mechanism ? `<div style="font-size:11px;color:#9ca3af;line-height:1.5;margin-bottom:4px"><span style="color:#6b7280;font-weight:600">Why: </span>${_escHtml(p.mechanism)}</div>` : ''}
            <!-- Falsifier -->
            ${p.falsifier ? `<div style="font-size:11px;color:#9ca3af;line-height:1.5"><span style="color:#6b7280;font-weight:600">Falsifier: </span>${_escHtml(p.falsifier)}</div>` : ''}
            ${resolvedNote}
            ${actionBtns}
        </div>`;
    }

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
                    return `<div style="display:flex;align-items:center;gap:6px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05)">
                        <span style="color:${sp.dot};font-size:9px;flex-shrink:0">&#9679;</span>
                        <span style="font-size:11px;color:#d1d5db;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${_escHtml(p.claim)}">${_escHtml(claimTrunc)}</span>
                        ${date ? `<span style="font-size:10px;color:#6b7280;white-space:nowrap;flex-shrink:0">${date}</span>` : ''}
                    </div>`;
                }).join('');

                containerEl.innerHTML = `
                    <div style="margin-top:10px;padding:10px 12px;background:rgba(59,130,246,0.06);border:1px solid rgba(59,130,246,0.18);border-radius:8px">
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
                            <span style="font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">Predictions</span>
                            <span onclick="typeof switchSignalTab === 'function' && switchSignalTab('predictions')" style="font-size:10px;color:#3b82f6;cursor:pointer;font-weight:600">View all &rarr;</span>
                        </div>
                        ${items}
                    </div>`;
            })
            .catch(err => {
                console.warn('[predictions ribbon] fetch error:', err);
            });
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

    /**
     * Render a div-based horizontal timeline of dated predictions.
     * Appended directly to #predictions-list (after filter row).
     * @param {Array} predictions  All predictions from /api/predictions
     */
    window._renderPredictionsTimeline = function (predictions) {
        const container = document.getElementById('predictions-list');
        if (!container) return;

        // Filter to predictions with expected_by dates, sorted ascending
        const dated = predictions
            .filter(p => p.expected_by)
            .sort((a, b) => a.expected_by.localeCompare(b.expected_by));

        if (!dated.length) {
            container.innerHTML += '<div style="color:#6b7280;text-align:center;padding:40px">No dated predictions to display.</div>';
            return;
        }

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        // Use today as axis start; axis end = latest expected_by + 1 month padding, max 12 months out
        const maxMs = Math.max(...dated.map(p => new Date(p.expected_by).getTime()));
        const maxDate = new Date(Math.min(maxMs + 30 * 86400000, today.getTime() + 365 * 86400000));
        maxDate.setDate(1); // snap to month start
        maxDate.setMonth(maxDate.getMonth() + 1); // add one month of padding

        const totalMs = maxDate - today;
        if (totalMs <= 0) {
            container.innerHTML += '<div style="color:#6b7280;text-align:center;padding:40px">All predictions are overdue.</div>';
            return;
        }

        // Build month markers
        const months = [];
        const cursor = new Date(today);
        cursor.setDate(1);
        cursor.setMonth(cursor.getMonth() + 1); // first whole month after today
        while (cursor <= maxDate) {
            const pct = ((cursor - today) / totalMs) * 100;
            months.push({ label: cursor.toLocaleDateString('en-US', { month: 'short' }), pct });
            cursor.setMonth(cursor.getMonth() + 1);
        }

        // Stagger dots to reduce vertical overlap — assign row based on expected_by proximity
        // Simple approach: assign each dot to row 0, 1, or 2 based on insertion order
        const ROWS = 3;
        const rowCounters = Array(ROWS).fill(0);
        const dottedPreds = dated.map((p, i) => {
            const pct = ((new Date(p.expected_by) - today) / totalMs) * 100;
            const row = i % ROWS; // simple round-robin stagger
            rowCounters[row]++;
            return { ...p, pct: Math.max(0, Math.min(99, pct)), row };
        });

        const monthMarkersHtml = months.map(m =>
            `<div style="position:absolute;left:${m.pct.toFixed(1)}%;top:0;bottom:0;border-left:1px dashed rgba(255,255,255,0.06);pointer-events:none">
                <span style="position:absolute;top:-18px;left:2px;font-size:9px;color:#4b5563;white-space:nowrap">${m.label}</span>
            </div>`
        ).join('');

        // Dot rows — 3 rows, each 28px tall
        const rowHeight = 28;
        const dotsHtml = dottedPreds.map(p => {
            const sp = STATUS_PILL[p.status] || STATUS_PILL.open;
            const topPx = p.row * rowHeight + 4;
            const claimTrunc = p.claim && p.claim.length > 40 ? p.claim.substring(0, 38) + '…' : (p.claim || '');
            return `<div style="position:absolute;left:${p.pct.toFixed(1)}%;top:${topPx}px;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;z-index:2"
                         title="${_escHtml(p.claim)} — ${_formatDate(p.expected_by)}">
                <div style="width:10px;height:10px;border-radius:50%;background:${sp.dot};box-shadow:0 0 6px ${sp.dot}55;cursor:default;flex-shrink:0"></div>
                <span style="font-size:8px;color:#9ca3af;white-space:nowrap;max-width:70px;overflow:hidden;text-overflow:ellipsis;margin-top:2px;text-align:center">${_escHtml(claimTrunc)}</span>
            </div>`;
        }).join('');

        // X-axis baseline
        const timelineHtml = `
            <div id="predictions-timeline" style="position:relative;margin-top:24px;margin-bottom:12px;padding:0 8px">
                <!-- Month labels + markers -->
                <div style="position:relative;height:20px;margin-bottom:4px">${monthMarkersHtml}</div>
                <!-- Axis bar -->
                <div style="position:relative;height:${ROWS * rowHeight + 16}px;border-top:2px solid rgba(255,255,255,0.12);border-bottom:1px solid rgba(255,255,255,0.05)">
                    ${dotsHtml}
                    <!-- Today marker -->
                    <div style="position:absolute;left:0;top:0;bottom:0;border-left:2px solid rgba(59,130,246,0.6);z-index:3">
                        <span style="position:absolute;top:2px;left:4px;font-size:8px;color:#3b82f6;font-weight:700;white-space:nowrap">Today</span>
                    </div>
                </div>
                <!-- Legend -->
                <div style="display:flex;gap:12px;margin-top:10px;flex-wrap:wrap">
                    ${Object.entries(STATUS_PILL).map(([k, v]) =>
                        `<span style="font-size:10px;color:${v.color};display:flex;align-items:center;gap:3px">
                            <span style="width:8px;height:8px;border-radius:50%;background:${v.dot};display:inline-block"></span>${v.label}
                        </span>`
                    ).join('')}
                </div>
            </div>`;

        container.innerHTML += timelineHtml;
    };

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

        // Filter: if threadId given, show only thread-level predictions for that thread
        // otherwise show all open predictions for all threads
        let preds;
        if (threadId != null) {
            preds = allPreds.filter(p => p.parent_kind === 'thread' && p.parent_id === threadId);
        } else {
            preds = allPreds.filter(p => p.status === 'open').slice(0, 8);
        }

        if (!preds.length) return; // nothing to show — keep board clean

        const panel = document.createElement('div');
        panel.id = 'board-pred-panel';
        _boardPredPanel = panel;
        panel.style.cssText = [
            'position:absolute',
            'bottom:16px',
            'right:16px',
            'width:220px',
            'background:rgba(10,10,10,0.92)',
            'border:1px solid rgba(59,130,246,0.3)',
            'border-radius:10px',
            'padding:10px 12px',
            'z-index:20',
            'pointer-events:all',
            'box-shadow:0 4px 20px rgba(0,0,0,0.6)',
            'max-height:280px',
            'overflow-y:auto',
        ].join(';');

        const title = threadId != null
            ? `Predictions for thread`
            : `Open predictions (${preds.length})`;

        const rows = preds.map(p => {
            const sp = STATUS_PILL[p.status] || STATUS_PILL.open;
            const date = p.expected_by ? _formatDate(p.expected_by) : '';
            const claimTrunc = p.claim && p.claim.length > 55 ? p.claim.substring(0, 53) + '…' : (p.claim || '');
            return `<div style="padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.06);cursor:default" title="${_escHtml(p.claim)}">
                <div style="display:flex;align-items:center;gap:5px">
                    <span style="color:${sp.dot};font-size:8px;flex-shrink:0">&#9679;</span>
                    <span style="font-size:10px;color:#d1d5db;flex:1;line-height:1.3">${_escHtml(claimTrunc)}</span>
                </div>
                ${date ? `<div style="font-size:9px;color:#6b7280;margin-top:2px;padding-left:13px">Due ${date}</div>` : ''}
            </div>`;
        }).join('');

        panel.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                <span style="font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">&#128302; ${_escHtml(title)}</span>
                <span onclick="this.closest('#board-pred-panel').remove()" style="font-size:12px;color:#6b7280;cursor:pointer;line-height:1">&times;</span>
            </div>
            ${rows}
            <div style="margin-top:8px;text-align:right">
                <span onclick="switchSignalTab('predictions')" style="font-size:10px;color:#3b82f6;cursor:pointer;font-weight:600">All predictions &rarr;</span>
            </div>`;

        container.style.position = 'relative'; // ensure absolute children are positioned correctly
        container.appendChild(panel);
    }

    /**
     * Update the board panel to show predictions for a specific thread.
     * Called from openThreadDetail() when on the board tab.
     * @param {number} threadId
     */
    window._updateBoardPredPanelForThread = function (threadId) {
        if (!_boardPredData.length) return; // overlay not yet loaded — skip
        _renderBoardPredPanel(_boardPredData, threadId);
    };

    /**
     * Clear the board predictions panel (called when detail pane closes).
     */
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
