// ===================== DOCUMENTS MODULE =====================

let _docs = [];
let _activeDocId = null;
let _activeSections = [];   // [{index, label, text}]
let _activeAnnotations = []; // from server
let _pendingSelection = null; // {text, sectionIndex, sectionLabel, rect}

// ── Load & render list ──────────────────────────────────────────

async function loadDocuments() {
    try {
        const resp = await fetch('/api/documents');
        if (!resp.ok) return;
        _docs = await resp.json();
        renderDocList();
        if (_activeDocId) {
            const still = _docs.find(d => d.id === _activeDocId);
            if (still) openDoc(_activeDocId);
        }
    } catch (e) {
        console.warn('[docs] load failed', e);
    }
}

function renderDocList() {
    const el = document.getElementById('doc-list');
    if (!_docs.length) {
        el.innerHTML = '<div class="doc-empty-state">No documents yet.<br>Import a PDF, Markdown, Word, or EPUB file, or save an email via the browser extension.</div>';
        return;
    }
    el.innerHTML = _docs.map(d => {
        const active = d.id === _activeDocId ? ' active' : '';
        const isEmail = d.file_type === 'email';
        const meta = isEmail
            ? [d.sender, d.year].filter(Boolean).join(' · ')
            : [d.source, d.year].filter(Boolean).join(' · ');
        const annBadge = d.annotation_count > 0
            ? `<span class="doc-card-ann">${d.annotation_count} note${d.annotation_count !== 1 ? 's' : ''}</span>`
            : '';
        const senderChip = isEmail && d.sender
            ? `<div class="doc-card-sender">from: ${_esc(d.sender)}</div>`
            : '';
        return `<div class="doc-card${active}" onclick="openDoc('${d.id}')">
            <div class="doc-card-title">${_esc(d.title)}</div>
            ${senderChip}
            <div class="doc-card-meta">
                <span class="doc-card-type">${d.file_type.toUpperCase()}</span>
                ${meta ? `<span>${_esc(meta)}</span>` : ''}
                ${annBadge}
            </div>
        </div>`;
    }).join('');
}

// ── Open document ───────────────────────────────────────────────

async function openDoc(docId) {
    _activeDocId = docId;
    renderDocList();

    const resp = await fetch(`/api/documents/${encodeURIComponent(docId)}`);
    if (!resp.ok) return;
    const doc = await resp.json();

    _activeSections = JSON.parse(doc.extracted_text_json || '[]');
    _activeAnnotations = doc.annotations || [];

    // Header
    document.getElementById('doc-text-empty').style.display = 'none';
    const header = document.getElementById('doc-text-header');
    header.style.display = 'flex';
    const titleEl = document.getElementById('doc-text-doctitle');
    titleEl.textContent = doc.title;
    titleEl.title = 'Click to rename';
    titleEl.onclick = () => startRenameDoc(doc.id, doc.title);
    const sourceParts = doc.file_type === 'email' && doc.sender
        ? ['from: ' + doc.sender, doc.year].filter(Boolean).join(' · ')
        : [doc.source, doc.year].filter(Boolean).join(' · ');
    document.getElementById('doc-text-source').textContent = sourceParts;

    // Save copy button — only show if reference-only and file currently accessible
    const saveCopyBtn = document.getElementById('doc-save-copy-btn');
    saveCopyBtn.style.display = (doc.storage_mode === 'reference' && !doc.stored_path) ? '' : 'none';

    renderDocText();
    renderAnnotations();
}

function renderDocText() {
    const body = document.getElementById('doc-text-body');

    body.innerHTML = _activeSections.map(sec => {
        const labelHtml = sec.label
            ? `<div class="doc-section-label">${_esc(sec.label)}</div>`
            : '';
        const rendered = _renderMarkdown(sec.text);
        return `<div class="doc-section" data-section-index="${sec.index}" data-section-label="${_esc(sec.label || '')}">
            ${labelHtml}
            <div class="doc-section-text">${rendered}</div>
        </div>`;
    }).join('');

    // Apply annotation highlights by walking text nodes
    _applyAnnotationHighlights();

    body.removeEventListener('mouseup', _onTextSelect);
    body.addEventListener('mouseup', _onTextSelect);
}

function _renderMarkdown(text) {
    if (!text) return '';
    if (typeof marked !== 'undefined' && marked.parse) {
        const renderer = new marked.Renderer();
        renderer.link = function({ href, title, text }) {
            const t = title ? ` title="${title}"` : '';
            return `<a href="${href}"${t} target="_blank" rel="noopener">${text}</a>`;
        };
        return marked.parse(text, { breaks: false, gfm: true, renderer });
    }
    return text.split(/\n\n+/).map(p => `<p>${_esc(p)}</p>`).join('');
}

function _applyAnnotationHighlights() {
    for (const ann of _activeAnnotations) {
        if (!ann.selected_text) continue;
        const sectionEl = document.querySelector(
            `.doc-section[data-section-index="${ann.section_index}"] .doc-section-text`
        );
        if (!sectionEl) continue;
        const needle = ann.selected_text.replace(/\n/g, ' ').replace(/\s+/g, ' ').trim();
        if (!needle) continue;
        _highlightTextInNode(sectionEl, needle, ann.id);
    }
}

function _highlightTextInNode(root, needle, annId) {
    if (document.getElementById(`doc-hl-${annId}`)) return;

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    const textParts = [];
    let node;
    while ((node = walker.nextNode())) {
        textParts.push({ node, text: node.textContent });
    }

    const fullText = textParts.map(p => p.text).join('');
    const normFull = fullText.replace(/\s+/g, ' ');
    const normNeedle = needle.replace(/\s+/g, ' ');

    let searchTarget = normNeedle;
    let idx = normFull.indexOf(searchTarget);
    if (idx === -1 && normNeedle.length > 60) {
        searchTarget = normNeedle.slice(0, 60);
        idx = normFull.indexOf(searchTarget);
    }
    if (idx === -1) return;

    // Map normalized index → raw character positions
    function normToRaw(normPos) {
        let ri = 0, ni = 0;
        const chars = fullText;
        while (ni < normPos && ri < chars.length) {
            if (/\s/.test(chars[ri])) {
                ri++;
                while (ri < chars.length && /\s/.test(chars[ri])) ri++;
                ni++;
            } else { ri++; ni++; }
        }
        return ri;
    }
    const rawStart = normToRaw(idx);
    const rawEnd = normToRaw(idx + searchTarget.length);

    // Find the text node(s) that contain the match
    let offset = 0;
    let startNode = null, startOff = 0, endNode = null, endOff = 0;
    for (const part of textParts) {
        const partEnd = offset + part.text.length;
        if (!startNode && partEnd > rawStart) {
            startNode = part.node;
            startOff = rawStart - offset;
        }
        if (partEnd >= rawEnd) {
            endNode = part.node;
            endOff = rawEnd - offset;
            break;
        }
        offset = partEnd;
    }
    if (!startNode || !endNode) return;

    const range = document.createRange();
    range.setStart(startNode, startOff);
    range.setEnd(endNode, endOff);

    const span = document.createElement('span');
    span.className = 'doc-highlight';
    span.id = `doc-hl-${annId}`;
    span.title = 'Annotated';

    try {
        range.surroundContents(span);
    } catch {
        // Range crosses element boundaries — wrap each text node piece individually
        let inRange = false;
        for (const part of textParts) {
            const pEnd = (offset = textParts.indexOf(part) === 0 ? 0 : offset) + part.text.length;
            // Simpler: just mark the first text node
            if (part.node === startNode) {
                const r2 = document.createRange();
                r2.setStart(startNode, startOff);
                r2.setEnd(startNode, startNode === endNode ? endOff : startNode.textContent.length);
                const s2 = document.createElement('span');
                s2.className = 'doc-highlight';
                s2.id = `doc-hl-${annId}`;
                s2.title = 'Annotated';
                r2.surroundContents(s2);
                return;
            }
        }
    }
}

// ── Text selection & popover ────────────────────────────────────

function _onTextSelect(e) {
    const sel = window.getSelection();
    const text = sel ? sel.toString().trim() : '';
    if (!text || text.length < 5) {
        closeAnnotationPopover();
        return;
    }

    // Find which section the selection is in
    let sectionIndex = 0;
    let sectionLabel = '';
    const range = sel.getRangeAt(0);
    let node = range.commonAncestorContainer;
    while (node && node !== document.body) {
        if (node.dataset && node.dataset.sectionIndex !== undefined) {
            sectionIndex = parseInt(node.dataset.sectionIndex, 10);
            sectionLabel = node.dataset.sectionLabel || '';
            break;
        }
        node = node.parentNode;
    }

    const rect = range.getBoundingClientRect();
    _pendingSelection = { text, sectionIndex, sectionLabel, rect };
    _showAnnotationPopover(text, rect);
}

function _showAnnotationPopover(text, rect) {
    const popover = document.getElementById('doc-ann-popover');
    document.getElementById('doc-ann-popover-quote').textContent =
        text.length > 120 ? text.slice(0, 120) + '…' : text;
    document.getElementById('doc-ann-popover-note').value = '';
    document.getElementById('doc-ann-popover-title').value =
        text.length > 80 ? text.slice(0, 80) : text;
    document.getElementById('doc-ann-create-thread').checked = true;

    // Position below selection, keep within viewport
    const top = Math.min(rect.bottom + window.scrollY + 8,
        window.innerHeight - 220);
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - 320));
    popover.style.top = top + 'px';
    popover.style.left = left + 'px';
    popover.style.display = 'block';
}

function closeAnnotationPopover() {
    document.getElementById('doc-ann-popover').style.display = 'none';
    _pendingSelection = null;
}

async function saveAnnotation() {
    if (!_pendingSelection || !_activeDocId) return;

    const note = document.getElementById('doc-ann-popover-note').value.trim();
    const threadTitle = document.getElementById('doc-ann-popover-title').value.trim();
    const createThread = document.getElementById('doc-ann-create-thread').checked;

    const btn = document.querySelector('.doc-ann-popover-save');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
        const resp = await fetch(`/api/documents/${encodeURIComponent(_activeDocId)}/annotations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                selected_text: _pendingSelection.text,
                section_index: _pendingSelection.sectionIndex,
                section_label: _pendingSelection.sectionLabel,
                note,
                thread_title: threadTitle,
                create_thread: createThread,
            }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            alert(data.error || 'Failed to save annotation');
            return;
        }
        closeAnnotationPopover();
        window.getSelection()?.removeAllRanges();
        // Reload doc to get fresh annotations + update highlight
        await openDoc(_activeDocId);
        await loadDocuments(); // refresh count in list
    } catch (e) {
        console.warn('[docs] annotation save failed', e);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Save';
    }
}

// ── Annotations panel ───────────────────────────────────────────

function renderAnnotations() {
    const list = document.getElementById('doc-ann-list');
    const count = document.getElementById('doc-ann-count');
    count.textContent = _activeAnnotations.length;

    if (!_activeAnnotations.length) {
        list.innerHTML = '<div class="doc-ann-empty">Highlight text in the document to create annotations.</div>';
        return;
    }

    list.innerHTML = _activeAnnotations.map(a => {
        const sectionLabel = a.section_label
            ? `<div class="doc-ann-item-section">${_esc(a.section_label)}</div>`
            : '';
        const noteHtml = a.note
            ? `<div class="doc-ann-item-note">${_esc(a.note)}</div>`
            : '';
        const threadHtml = a.thread_title
            ? `<div class="doc-ann-item-thread">→ ${_esc(a.thread_title)}</div>`
            : '';
        return `<div class="doc-ann-item" onclick="scrollToHighlight(${a.id})" style="cursor:pointer">
            ${sectionLabel}
            <div class="doc-ann-item-quote">"${_esc(a.selected_text)}"</div>
            ${noteHtml}
            ${threadHtml}
            <div class="doc-ann-item-actions">
                <button class="doc-ann-del" onclick="event.stopPropagation();deleteAnnotation(${a.id})">Delete</button>
            </div>
        </div>`;
    }).join('');
}

function scrollToHighlight(annotationId) {
    const el = document.getElementById(`doc-hl-${annotationId}`);
    if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.style.background = 'rgba(168, 85, 247, .5)';
        setTimeout(() => { el.style.background = ''; }, 1200);
        return;
    }
    // No span (cross-paragraph or whitespace mismatch) — scroll to the section instead
    const ann = _activeAnnotations.find(a => a.id === annotationId);
    if (!ann) return;
    const sectionEl = document.querySelector(`.doc-section[data-section-index="${ann.section_index}"]`);
    if (sectionEl) sectionEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function deleteAnnotation(annotationId) {
    if (!_activeDocId) return;
    await fetch(`/api/documents/${encodeURIComponent(_activeDocId)}/annotations/${annotationId}`, {
        method: 'DELETE',
    });
    await openDoc(_activeDocId);
    await loadDocuments();
}

// ── Rename ──────────────────────────────────────────────────────

function startRenameDoc(docId, currentTitle) {
    const titleEl = document.getElementById('doc-text-doctitle');
    const input = document.createElement('input');
    input.className = 'doc-title-input';
    input.value = currentTitle;
    titleEl.replaceWith(input);
    input.focus();
    input.select();

    async function commit() {
        const newTitle = input.value.trim();
        if (newTitle && newTitle !== currentTitle) {
            await fetch(`/api/documents/${encodeURIComponent(docId)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle }),
            });
            await loadDocuments();
        }
        // Restore title element
        const restored = document.createElement('div');
        restored.id = 'doc-text-doctitle';
        restored.className = 'doc-text-doctitle';
        restored.textContent = newTitle || currentTitle;
        restored.title = 'Click to rename';
        restored.onclick = () => startRenameDoc(docId, restored.textContent);
        input.replaceWith(restored);
    }

    input.addEventListener('blur', commit);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { input.value = currentTitle; input.blur(); }
    });
}

// ── Save copy ───────────────────────────────────────────────────

async function saveDocCopy() {
    if (!_activeDocId) return;
    const btn = document.getElementById('doc-save-copy-btn');
    btn.disabled = true;
    btn.textContent = 'Saving...';
    try {
        const resp = await fetch(`/api/documents/${encodeURIComponent(_activeDocId)}/save-copy`, {
            method: 'POST',
        });
        const data = await resp.json();
        if (resp.ok) {
            btn.style.display = 'none';
        } else {
            alert(data.error || 'Could not save copy');
            btn.disabled = false;
            btn.textContent = 'Save copy';
        }
    } catch (e) {
        btn.disabled = false;
        btn.textContent = 'Save copy';
    }
}

// ── Delete document ─────────────────────────────────────────────

async function deleteActiveDoc() {
    if (!_activeDocId) return;
    const doc = _docs.find(d => d.id === _activeDocId);
    const name = doc ? doc.title : 'this document';
    if (!confirm(`Delete "${name}" and all its annotations?`)) return;

    await fetch(`/api/documents/${encodeURIComponent(_activeDocId)}`, { method: 'DELETE' });
    _activeDocId = null;
    _activeSections = [];
    _activeAnnotations = [];

    document.getElementById('doc-text-empty').style.display = '';
    document.getElementById('doc-text-header').style.display = 'none';
    document.getElementById('doc-text-body').innerHTML = '';
    document.getElementById('doc-ann-list').innerHTML =
        '<div class="doc-ann-empty">Highlight text in the document to create annotations.</div>';
    document.getElementById('doc-ann-count').textContent = '0';

    await loadDocuments();
}

// ── Import modal ────────────────────────────────────────────────

let _pickedFile = null; // File object from file picker

function openImportModal() {
    _pickedFile = null;
    document.getElementById('doc-import-path').value = '';
    document.getElementById('doc-import-path').readOnly = false;
    document.getElementById('doc-import-title').value = '';
    document.getElementById('doc-import-source').value = '';
    document.getElementById('doc-import-year').value = '';
    document.getElementById('doc-import-error').textContent = '';
    document.getElementById('doc-import-temp-warn').style.display = 'none';
    document.getElementById('doc-storage-ref').checked = true;
    document.getElementById('doc-import-submit').disabled = false;
    document.getElementById('doc-import-overlay').style.display = 'flex';
    setTimeout(() => document.getElementById('doc-import-path').focus(), 50);
}

function closeImportModal() {
    document.getElementById('doc-import-overlay').style.display = 'none';
    _pickedFile = null;
    // Reset file picker so the same file can be re-selected
    const picker = document.getElementById('doc-file-picker');
    if (picker) picker.value = '';
}

function onFilePicked(input) {
    const file = input.files[0];
    if (!file) return;
    _pickedFile = file;

    // Show filename in path field (read-only — file is uploaded, no path needed)
    const pathEl = document.getElementById('doc-import-path');
    pathEl.value = file.name;
    pathEl.readOnly = true;

    // Auto-fill title
    const titleEl = document.getElementById('doc-import-title');
    if (!titleEl.value) {
        titleEl.value = file.name.replace(/\.[^.]+$/, '');
    }

    // File picker = upload = always stored
    document.getElementById('doc-storage-stored').checked = true;
    document.getElementById('doc-import-temp-warn').style.display = 'none';
    document.getElementById('doc-import-error').textContent = '';
}

let _pathCheckTimer = null;
function onImportPathChange() {
    _pickedFile = null;
    document.getElementById('doc-import-path').readOnly = false;
    const path = document.getElementById('doc-import-path').value.trim();
    document.getElementById('doc-import-error').textContent = '';

    // Auto-fill title from filename
    const titleEl = document.getElementById('doc-import-title');
    if (!titleEl.value) {
        const filename = path.split(/[\\/]/).pop();
        titleEl.value = filename ? filename.replace(/\.[^.]+$/, '') : '';
    }

    // Temp file heuristic
    const lpath = path.toLowerCase();
    const isTemp = lpath.includes('\\downloads\\') || lpath.includes('/downloads/') ||
        lpath.includes('\\temp\\') || lpath.includes('/tmp/') ||
        lpath.includes('\\appdata\\local\\temp');
    document.getElementById('doc-import-temp-warn').style.display = isTemp ? 'block' : 'none';
    if (isTemp) document.getElementById('doc-storage-stored').checked = true;

    // Debounced path check — verify server can see the file
    clearTimeout(_pathCheckTimer);
    if (path.length > 5) {
        _pathCheckTimer = setTimeout(async () => {
            try {
                const r = await fetch('/api/documents/check-path', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path }),
                });
                const d = await r.json();
                const errEl = document.getElementById('doc-import-error');
                if (!d.exists) {
                    errEl.textContent = 'File not found — check the path is correct.';
                } else if (!d.is_file) {
                    errEl.textContent = 'Path is a directory, not a file.';
                }
            } catch {}
        }, 600);
    }
}

async function submitImport() {
    const title = document.getElementById('doc-import-title').value.trim();
    const source = document.getElementById('doc-import-source').value.trim();
    const year = parseInt(document.getElementById('doc-import-year').value) || null;

    const submitBtn = document.getElementById('doc-import-submit');
    const errorEl = document.getElementById('doc-import-error');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Importing...';
    errorEl.textContent = '';

    try {
        let resp, data;

        if (_pickedFile) {
            // File upload path
            const form = new FormData();
            form.append('file', _pickedFile);
            form.append('title', title);
            if (source) form.append('source', source);
            if (year) form.append('year', year);
            resp = await fetch('/api/documents/upload', { method: 'POST', body: form });
        } else {
            // Manual path reference
            const path = document.getElementById('doc-import-path').value.trim();
            if (!path) {
                errorEl.textContent = 'Select a file or paste a path.';
                return;
            }
            const storageMode = document.querySelector('input[name="storage_mode"]:checked')?.value || 'reference';
            resp = await fetch('/api/documents', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_path: path, title, source, year, storage_mode: storageMode }),
            });
        }

        data = await resp.json();
        if (!resp.ok) {
            errorEl.textContent = data.error || 'Import failed.';
            return;
        }
        closeImportModal();
        await loadDocuments();
        openDoc(data.id);
    } catch (e) {
        errorEl.textContent = 'Network error — is the server running?';
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Import';
    }
}

// ── Dismiss popover on outside click ───────────────────────────

document.addEventListener('mousedown', e => {
    const popover = document.getElementById('doc-ann-popover');
    if (popover && !popover.contains(e.target) && popover.style.display !== 'none') {
        closeAnnotationPopover();
    }
});

// ── Utility ─────────────────────────────────────────────────────

function _esc(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
