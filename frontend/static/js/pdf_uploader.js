/**
 * PDFUploader — universal reusable PDF upload/view/delete modal.
 *
 * Usage:
 *   PDFUploader.open({
 *     title:              'Payroll Documents',
 *     subtitle:           'April 2026 — ACME Ltd',
 *     listUrl:            '/payroll/137/documents',
 *     uploadUrl:          '/payroll/137/documents/upload',
 *     viewUrlTemplate:    '/payroll/137/documents/{id}',
 *     deleteUrlTemplate:  '/payroll/137/documents/{id}/delete',
 *     csrfToken:          '<token>',
 *     badgeSelector:      '#docsBadge',   // optional CSS selector for count badge
 *   });
 *
 *   PDFUploader.loadBadge(listUrl, badgeSelector);   // call on DOMContentLoaded
 */
const PDFUploader = (() => {
    'use strict';

    const MAX_BYTES = 500 * 1024;
    let _cfg = {};
    let _files = [];

    // ── Modal scaffold (created once, reused for every call) ─────────────────
    function _ensureModal() {
        if (document.getElementById('_pdfUplModal')) return;

        const wrap = document.createElement('div');
        wrap.innerHTML = `
<div id="_pdfUplModal"
     style="display:none;position:fixed;inset:0;z-index:10500;background:rgba(0,0,0,0.46);"
     onclick="if(event.target===this)PDFUploader.close()">
  <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
              width:min(700px,96vw);max-height:92vh;background:#fff;border-radius:14px;
              box-shadow:0 24px 64px rgba(0,0,0,0.24);display:flex;flex-direction:column;overflow:hidden;">

    <!-- Header -->
    <div style="display:flex;align-items:center;justify-content:space-between;
                padding:18px 22px 14px;border-bottom:1px solid #e2e8f0;flex-shrink:0;">
      <div>
        <div style="font-size:1rem;font-weight:700;color:#1e293b;">
          <i class="bi bi-paperclip me-2" style="color:#0369a1;"></i>
          <span id="_pdfUplTitle">Documents</span>
        </div>
        <div id="_pdfUplSubtitle" style="font-size:0.72rem;color:#64748b;margin-top:2px;"></div>
      </div>
      <button onclick="PDFUploader.close()"
              style="background:none;border:none;font-size:1.4rem;color:#94a3b8;cursor:pointer;padding:0 4px;line-height:1;">
        &times;
      </button>
    </div>

    <!-- Upload area -->
    <div style="padding:16px 22px;border-bottom:1px solid #f1f5f9;flex-shrink:0;background:#f8fafc;">
      <div style="font-size:0.78rem;font-weight:700;color:#334155;margin-bottom:10px;">
        <i class="bi bi-cloud-upload me-1"></i>Upload Documents
      </div>

      <div id="_pdfUplZone"
           ondragover="event.preventDefault();this.style.borderColor='#0369a1';this.style.background='#e0f2fe';"
           ondragleave="this.style.borderColor='#cbd5e1';this.style.background='#f1f5f9';"
           ondrop="PDFUploader._onDrop(event)"
           onclick="document.getElementById('_pdfUplInput').click()"
           style="border:2px dashed #cbd5e1;border-radius:8px;background:#f1f5f9;
                  padding:16px;text-align:center;cursor:pointer;transition:all 0.15s;">
        <i class="bi bi-file-earmark-pdf" style="font-size:1.9rem;color:#e2160a;"></i>
        <div style="font-size:0.78rem;color:#64748b;margin-top:6px;">
          Drag &amp; drop PDFs here, or <strong style="color:#0369a1;">click to browse</strong>
        </div>
        <div style="font-size:0.68rem;color:#94a3b8;margin-top:3px;">
          PDF only &middot; max 500 KB per file &middot; multiple files at once
        </div>
      </div>

      <input type="file" id="_pdfUplInput" accept=".pdf,application/pdf"
             multiple style="display:none;"
             onchange="PDFUploader._onSelect(this)">

      <!-- Queued files list -->
      <div id="_pdfUplQueue" style="display:none;margin-top:10px;max-height:150px;overflow-y:auto;"></div>

      <!-- Description + upload button -->
      <div style="display:flex;gap:8px;margin-top:10px;align-items:flex-end;">
        <div style="flex:1;">
          <input type="text" id="_pdfUplDesc" maxlength="500"
                 placeholder="Description (optional — applies to all selected files)"
                 style="width:100%;padding:7px 10px;border:1px solid #e2e8f0;border-radius:6px;
                        font-size:0.78rem;outline:none;color:#1e293b;">
        </div>
        <button onclick="PDFUploader._uploadAll()" id="_pdfUplBtn"
                style="padding:7px 18px;background:#0369a1;color:#fff;border:none;border-radius:6px;
                       font-size:0.78rem;font-weight:600;cursor:pointer;white-space:nowrap;flex-shrink:0;">
          <i class="bi bi-upload me-1"></i>Upload
        </button>
      </div>
      <div id="_pdfUplMsg" style="font-size:0.72rem;margin-top:6px;display:none;"></div>
    </div>

    <!-- Saved documents list -->
    <div style="flex:1;overflow-y:auto;padding:16px 22px;">
      <div style="font-size:0.78rem;font-weight:700;color:#334155;margin-bottom:10px;">
        <i class="bi bi-list-ul me-1"></i>Uploaded Documents
        <span id="_pdfUplCount" style="font-weight:400;color:#64748b;"></span>
      </div>
      <div id="_pdfUplList">
        <div style="text-align:center;padding:28px;color:#94a3b8;font-size:0.8rem;">
          <i class="bi bi-hourglass-split" style="font-size:1.5rem;display:block;margin-bottom:8px;"></i>
          Loading…
        </div>
      </div>
    </div>

  </div>
</div>`;
        document.body.appendChild(wrap.firstElementChild);
    }

    // ── Public API ────────────────────────────────────────────────────────────
    function open(cfg) {
        _cfg   = cfg;
        _files = [];
        _ensureModal();

        _el('_pdfUplTitle').textContent    = cfg.title    || 'Documents';
        _el('_pdfUplSubtitle').textContent = cfg.subtitle || '';
        _el('_pdfUplQueue').style.display  = 'none';
        _el('_pdfUplQueue').innerHTML      = '';
        _el('_pdfUplDesc').value           = '';
        _el('_pdfUplMsg').style.display    = 'none';
        _el('_pdfUplBtn').innerHTML        = '<i class="bi bi-upload me-1"></i>Upload';
        _el('_pdfUplModal').style.display  = 'block';
        document.body.style.overflow       = 'hidden';
        _loadList();
    }

    function close() {
        const m = _el('_pdfUplModal');
        if (m) m.style.display = 'none';
        document.body.style.overflow = '';
    }

    function loadBadge(listUrl, badgeSel) {
        fetch(listUrl)
            .then(r => r.json())
            .then(data => _applyBadge(badgeSel, _docs(data).length))
            .catch(() => {});
    }

    // ── File queuing ──────────────────────────────────────────────────────────
    function _onDrop(event) {
        event.preventDefault();
        const z = _el('_pdfUplZone');
        z.style.borderColor = '#cbd5e1';
        z.style.background  = '#f1f5f9';
        _addFiles(event.dataTransfer.files);
    }

    function _onSelect(input) {
        _addFiles(input.files);
        input.value = '';
    }

    function _addFiles(fileList) {
        const skipped = [];
        Array.from(fileList).forEach(f => {
            const isPdf = f.name.toLowerCase().endsWith('.pdf') || f.type === 'application/pdf';
            if (!isPdf)           { skipped.push(f.name + ' (not a PDF)');               return; }
            if (f.size > MAX_BYTES) { skipped.push(f.name + ' (' + _kb(f.size) + ' KB — max 500 KB)'); return; }
            if (_files.some(x => x.name === f.name && x.size === f.size)) return; // dedup
            _files.push(f);
        });
        if (skipped.length) _msg('Skipped: ' + skipped.join(' | '), 'error');
        _renderQueue();
    }

    function _removeFile(idx) {
        _files.splice(idx, 1);
        _renderQueue();
    }

    function _renderQueue() {
        const c   = _el('_pdfUplQueue');
        const btn = _el('_pdfUplBtn');
        if (!_files.length) {
            c.style.display = 'none';
            c.innerHTML     = '';
            if (btn) btn.innerHTML = '<i class="bi bi-upload me-1"></i>Upload';
            return;
        }
        c.style.display = 'block';
        c.innerHTML = _files.map((f, i) => `
            <div id="_pdfQRow_${i}"
                 style="display:flex;align-items:center;gap:8px;padding:6px 10px;
                        background:#fff;border:1px solid #e2e8f0;border-radius:6px;margin-bottom:5px;">
              <i class="bi bi-file-earmark-pdf-fill" style="color:#e2160a;font-size:1rem;flex-shrink:0;"></i>
              <div style="flex:1;min-width:0;font-size:0.78rem;font-weight:600;color:#1e293b;
                          overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                   title="${_esc(f.name)}">${_esc(f.name)}</div>
              <span style="font-size:0.68rem;color:#64748b;flex-shrink:0;">${_kb(f.size)} KB</span>
              <span id="_pdfQSt_${i}" style="font-size:0.78rem;flex-shrink:0;width:18px;text-align:center;"></span>
              <button onclick="PDFUploader._removeFile(${i})" id="_pdfQRm_${i}"
                      style="background:none;border:none;color:#94a3b8;cursor:pointer;
                             font-size:1rem;padding:0 2px;flex-shrink:0;">&times;</button>
            </div>`).join('');
        btn.innerHTML = _files.length > 1
            ? `<i class="bi bi-upload me-1"></i>Upload All (${_files.length})`
            : '<i class="bi bi-upload me-1"></i>Upload';
    }

    // ── Parallel upload ───────────────────────────────────────────────────────
    async function _uploadAll() {
        if (!_files.length) { _msg('Please select at least one PDF file.', 'error'); return; }

        const btn   = _el('_pdfUplBtn');
        const desc  = _el('_pdfUplDesc').value.trim();
        const batch = [..._files];

        btn.disabled  = true;
        btn.innerHTML = `<i class="bi bi-hourglass-split me-1"></i>Uploading ${batch.length}…`;
        _msg('Uploading ' + batch.length + ' file' + (batch.length > 1 ? 's' : '') + ' in parallel…', 'info');

        // Disable remove buttons & show spinners
        batch.forEach((_, i) => {
            const rm = _el('_pdfQRm_' + i);
            const st = _el('_pdfQSt_' + i);
            if (rm) rm.style.display = 'none';
            if (st) st.innerHTML = '<i class="bi bi-hourglass-split" style="color:#94a3b8;font-size:0.75rem;"></i>';
        });

        // Fire all uploads simultaneously
        const results = await Promise.allSettled(
            batch.map((file, i) => _uploadOne(file, desc, i))
        );

        let ok = 0, fail = 0;
        results.forEach((r, i) => {
            const st = _el('_pdfQSt_' + i);
            if (r.status === 'fulfilled' && r.value?.ok) {
                ok++;
                if (st) st.innerHTML = '<i class="bi bi-check-circle-fill" style="color:#16a34a;"></i>';
            } else {
                fail++;
                const errTip = _esc((r.reason?.message) || (r.value?.error) || 'Failed');
                if (st) st.innerHTML = `<i class="bi bi-x-circle-fill" style="color:#dc2626;" title="${errTip}"></i>`;
            }
        });

        btn.disabled  = false;
        btn.innerHTML = '<i class="bi bi-upload me-1"></i>Upload';
        _el('_pdfUplDesc').value = '';
        _files = [];

        if (fail === 0) {
            _msg(ok === 1 ? 'Uploaded successfully!' : ok + ' files uploaded!', 'ok');
            setTimeout(() => {
                _el('_pdfUplQueue').style.display = 'none';
                _el('_pdfUplQueue').innerHTML = '';
            }, 1500);
        } else if (ok > 0) {
            _msg(ok + ' uploaded, ' + fail + ' failed.', 'error');
        } else {
            _msg('All uploads failed — check browser console (F12).', 'error');
        }

        _loadList();
    }

    async function _uploadOne(file, description, idx) {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('description', description);

        const r = await fetch(_cfg.uploadUrl, {
            method:  'POST',
            headers: { 'X-CSRFToken': _cfg.csrfToken },
            body:    fd,
        });

        const raw = await r.text();
        console.log('[PDFUploader] Upload', file.name, '→ HTTP', r.status, '|', raw.substring(0, 180));

        let data;
        try { data = JSON.parse(raw); }
        catch (e) {
            console.error('[PDFUploader] Non-JSON response for', file.name, ':', raw.substring(0, 300));
            throw new Error('Server error (non-JSON response)');
        }

        if (!r.ok) throw new Error(data.error || 'HTTP ' + r.status);
        return data;
    }

    // ── Saved list ────────────────────────────────────────────────────────────
    function _loadList() {
        const body = _el('_pdfUplList');
        if (!body) return;
        body.innerHTML = `
            <div style="text-align:center;padding:28px;color:#94a3b8;font-size:0.8rem;">
              <i class="bi bi-hourglass-split" style="font-size:1.5rem;display:block;margin-bottom:8px;"></i>
              Loading…
            </div>`;

        fetch(_cfg.listUrl)
            .then(async r => {
                const txt = await r.text();
                console.log('[PDFUploader] List → HTTP', r.status, '|', txt.substring(0, 180));
                return JSON.parse(txt);
            })
            .then(data => {
                const docs  = _docs(data);
                const count = _el('_pdfUplCount');
                if (count) count.textContent = docs.length ? ' (' + docs.length + ')' : '';
                _applyBadge(_cfg.badgeSelector, docs.length);

                if (!docs.length) {
                    body.innerHTML = `
                        <div style="text-align:center;padding:32px;color:#94a3b8;font-size:0.82rem;">
                          <i class="bi bi-folder2-open" style="font-size:2rem;display:block;margin-bottom:8px;"></i>
                          No documents uploaded yet.
                        </div>`;
                    return;
                }

                body.innerHTML = docs.map(d => {
                    const viewUrl = (_cfg.viewUrlTemplate || '').replace('{id}', d.id);
                    return `
                    <div style="display:flex;align-items:center;gap:10px;padding:10px 12px;
                                border:1px solid #e2e8f0;border-radius:8px;margin-bottom:8px;background:#fff;">
                      <i class="bi bi-file-earmark-pdf-fill" style="color:#e2160a;font-size:1.25rem;flex-shrink:0;"></i>
                      <div style="flex:1;min-width:0;">
                        <div style="font-size:0.8rem;font-weight:600;color:#1e293b;overflow:hidden;
                                    text-overflow:ellipsis;white-space:nowrap;"
                             title="${_esc(d.filename)}">${_esc(d.filename)}</div>
                        <div style="font-size:0.68rem;color:#64748b;">
                          ${_esc(d.description || '')}${d.description ? ' &middot; ' : ''}${d.size_kb} KB
                          ${(d.stored_kb && d.stored_kb < d.size_kb)
                              ? `<span style="color:#16a34a;" title="Stored compressed">(${d.stored_kb} KB stored)</span>`
                              : ''}
                          &middot; ${_esc(d.uploaded_at)}
                        </div>
                      </div>
                      <a href="${_esc(viewUrl)}" target="_blank"
                         style="padding:5px 10px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:6px;
                                color:#0369a1;font-size:0.72rem;font-weight:600;text-decoration:none;
                                flex-shrink:0;white-space:nowrap;">
                        <i class="bi bi-eye me-1"></i>Preview
                      </a>
                      <button onclick="PDFUploader._delete(${d.id})"
                              style="padding:5px 10px;background:#fff0f0;border:1px solid #fecaca;border-radius:6px;
                                     color:#dc2626;font-size:0.72rem;font-weight:600;cursor:pointer;
                                     flex-shrink:0;white-space:nowrap;">
                        <i class="bi bi-trash me-1"></i>Delete
                      </button>
                    </div>`;
                }).join('');
            })
            .catch(err => {
                console.error('[PDFUploader] List error:', err);
                body.innerHTML = `<div style="text-align:center;padding:28px;color:#dc2626;font-size:0.8rem;">
                    Failed to load documents. Check console (F12).</div>`;
            });
    }

    // ── Delete ────────────────────────────────────────────────────────────────
    function _delete(docId) {
        if (!confirm('Delete this document? This cannot be undone.')) return;
        const url = (_cfg.deleteUrlTemplate || '').replace('{id}', docId);
        fetch(url, { method: 'POST', headers: { 'X-CSRFToken': _cfg.csrfToken } })
            .then(async r => JSON.parse(await r.text()))
            .then(data => {
                if (data.ok) _loadList();
                else alert(data.error || 'Delete failed.');
            })
            .catch(err => { console.error('[PDFUploader] Delete error:', err); alert('Network error.'); });
    }

    // ── Helpers ───────────────────────────────────────────────────────────────
    function _docs(data) {
        // handles both { documents: [...] } and bare array [] for backward compat
        if (Array.isArray(data)) return data;
        return Array.isArray(data.documents) ? data.documents : [];
    }

    function _applyBadge(sel, count) {
        if (!sel) return;
        const el = document.querySelector(sel);
        if (!el) return;
        if (count > 0) { el.textContent = count; el.style.display = 'inline-block'; }
        else             { el.style.display = 'none'; }
    }

    function _el(id)     { return document.getElementById(id); }
    function _kb(bytes)  { return (bytes / 1024).toFixed(1); }
    function _esc(str)   {
        return String(str || '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function _msg(text, type) {
        const el = _el('_pdfUplMsg');
        if (!el) return;
        el.textContent  = text;
        el.style.color  = type === 'ok' ? '#16a34a' : type === 'info' ? '#0369a1' : '#dc2626';
        el.style.display = 'block';
    }

    return { open, close, loadBadge, _onDrop, _onSelect, _removeFile, _uploadAll, _delete };
})();
