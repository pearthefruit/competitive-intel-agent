// ===================== TIMELINE STRIP =====================

var _timelineVisible = false;  // var: accessed from board.js (separate script scope)
let _timelineData = null;

function _toggleTimeline() {
    const panel = document.getElementById('board-timeline');
    const btn = document.getElementById('board-timeline-btn');
    const icon = document.getElementById('timeline-toggle-icon');
    _timelineVisible = !_timelineVisible;
    if (panel) panel.style.display = _timelineVisible ? '' : 'none';
    if (btn) {
        btn.style.background = _timelineVisible ? 'var(--accent)' : 'var(--bg-tertiary)';
        btn.style.color = _timelineVisible ? '#fff' : 'var(--text-muted)';
        btn.style.borderColor = _timelineVisible ? 'var(--accent)' : 'var(--border)';
    }
    if (icon) icon.textContent = _timelineVisible ? '▼' : '▲';
    if (_timelineVisible && !_timelineData) _loadTimeline();
}

function _loadTimeline() {
    const c = document.getElementById('timeline-content');
    if (c) c.innerHTML = '<div style="padding:12px;font-size:10px;color:var(--text-muted)">Loading timeline...</div>';
    fetch('/api/signals/timeline?days=60')
        .then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        })
        .then(data => {
            _timelineData = data;
            _renderTimeline(data);
        })
        .catch(e => {
            if (c) c.innerHTML = `<div style="padding:12px;font-size:10px;color:var(--red)">Timeline unavailable — restart server to enable (${escHtml(e.message)})</div>`;
        });
}

function _renderTimeline(data) {
    const container = document.getElementById('timeline-content');
    if (!container) return;
    if (!data) { container.innerHTML = '<div style="padding:12px;font-size:10px;color:var(--text-muted)">No timeline data</div>'; return; }

    const signals = data.signals || [];
    const threadSpans = data.thread_spans || [];
    if (!signals.length) {
        container.innerHTML = '<div style="padding:12px;font-size:10px;color:var(--text-muted)">No signal data for timeline</div>';
        return;
    }

    // Date range
    const dates = signals.map(s => (s.published_at || '').substring(0, 10)).filter(d => d && d.length === 10).sort();
    if (!dates.length) { container.innerHTML = '<div style="padding:12px;font-size:10px;color:var(--text-muted)">No dated signals</div>'; return; }
    const minDate = new Date(dates[0]);
    const maxDate = new Date(dates[dates.length - 1]);
    if (isNaN(minDate) || isNaN(maxDate)) { container.innerHTML = '<div style="padding:12px;font-size:10px;color:var(--text-muted)">Invalid date range</div>'; return; }
    const rangeDays = Math.max(1, (maxDate - minDate) / 86400000);

    // Sort threads by first signal date, then by count
    const sorted = [...threadSpans].sort((a, b) => a.first.localeCompare(b.first) || b.count - a.count);

    // Layout: each thread gets a horizontal bar
    const barHeight = 16;
    const barGap = 3;
    const leftPad = 140; // thread title label width
    const totalWidth = Math.max(container.clientWidth - 24, 600);
    const chartWidth = totalWidth - leftPad;
    const totalHeight = Math.max(sorted.length * (barHeight + barGap) + 30, 80);

    const dateToX = (dateStr) => {
        const d = new Date(dateStr);
        return leftPad + ((d - minDate) / 86400000 / rangeDays) * chartWidth;
    };

    let svg = `<svg width="${totalWidth}" height="${totalHeight}" style="font-family:inherit">`;

    // Date axis at top
    const axisDates = [];
    const stepDays = Math.max(1, Math.round(rangeDays / 8));
    for (let d = new Date(minDate); d <= maxDate; d.setDate(d.getDate() + stepDays)) {
        axisDates.push(new Date(d));
    }
    axisDates.forEach(d => {
        const x = dateToX(d.toISOString().substring(0, 10));
        const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        svg += `<line x1="${x}" y1="14" x2="${x}" y2="${totalHeight}" stroke="var(--border)" stroke-width="0.5" stroke-dasharray="2 3"/>`;
        svg += `<text x="${x}" y="10" text-anchor="middle" fill="var(--text-muted)" font-size="8">${label}</text>`;
    });

    // Thread bars
    sorted.forEach((t, i) => {
        const y = 20 + i * (barHeight + barGap);
        const domColor = _DOMAIN_COLORS[_parseDomains(t.domain)[0]] || '#6b7280';

        // Thread label (clickable)
        const labelText = t.title.length > 22 ? t.title.substring(0, 20) + '…' : t.title;
        svg += `<text x="${leftPad - 6}" y="${y + barHeight / 2 + 3}" text-anchor="end" fill="var(--text-secondary)" font-size="9" font-weight="600" style="cursor:pointer" onclick="openThreadDetail(${t.thread_id})">${escHtml(labelText)}</text>`;

        // Background bar (thread span)
        const x1 = dateToX(t.first);
        const x2 = dateToX(t.last);
        const barW = Math.max(x2 - x1, 4);
        svg += `<rect x="${x1}" y="${y}" width="${barW}" height="${barHeight}" rx="3" fill="${domColor}" fill-opacity="0.15" stroke="${domColor}" stroke-opacity="0.3" stroke-width="0.5"/>`;

        // Signal dots on the bar
        const threadSigs = signals.filter(s => s.thread_id === t.thread_id);
        // Group by date for coverage density
        const byDate = {};
        threadSigs.forEach(s => {
            const d = (s.published_at || '').substring(0, 10);
            if (!byDate[d]) byDate[d] = [];
            byDate[d].push(s);
        });
        Object.entries(byDate).forEach(([date, sigs]) => {
            const x = dateToX(date);
            const r = Math.min(2 + sigs.length, 6); // bigger dot = more coverage
            svg += `<circle cx="${x}" cy="${y + barHeight / 2}" r="${r}" fill="${domColor}" fill-opacity="0.8">
                <title>${date}: ${sigs.length} signal${sigs.length > 1 ? 's' : ''}</title>
            </circle>`;
        });
    });

    // Unassigned signals as faded dots along the bottom
    const unassigned = signals.filter(s => !s.thread_id);
    if (unassigned.length) {
        const uy = totalHeight - 8;
        svg += `<text x="${leftPad - 6}" y="${uy + 3}" text-anchor="end" fill="var(--text-muted)" font-size="8" font-style="italic">unassigned</text>`;
        unassigned.forEach(s => {
            const x = dateToX((s.published_at || '').substring(0, 10));
            svg += `<circle cx="${x}" cy="${uy}" r="2" fill="var(--text-muted)" fill-opacity="0.4"><title>${escHtml(s.title?.substring(0, 60) || '')}</title></circle>`;
        });
    }

    svg += '</svg>';
    container.innerHTML = svg;
}

