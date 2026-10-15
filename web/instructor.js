'use strict';
let token = '';
let current = null;
const $ = id => document.getElementById(id);
function el(tag, text, className) { const x = document.createElement(tag); if (text !== undefined) x.textContent = text; if (className) x.className = className; return x; }
function say(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
async function api(path, method = 'GET', body) {
  const response = await fetch('/api/' + path, {method, headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the configuration format and required fields.');
  return data;
}
async function action(button, fn) { button.disabled = true; try { await fn(); } catch (e) { say(e.message, true); } finally { button.disabled = false; } }
async function refresh() {
  current = await api('status');
  $('login').hidden = true; $('workspace').hidden = false;
  $('course-json').value = current.course ? JSON.stringify(current.course, null, 2) : '';
  $('metrics').replaceChildren();
  for (const [n, label] of [[current.course?.students.length || 0, 'students'], [current.course?.projects.length || 0, 'projects'], [current.course?.meetings.length || 0, 'scheduled moments'], [current.outbox.filter(x => x.status === 'uncertain').length, 'uncertain sends']]) {
    const metric = el('div'); metric.append(el('strong', n), el('span', label)); $('metrics').append(metric);
  }
  $('readiness').replaceChildren();
  if (current.requirements.length) { const list = el('ul'); for (const item of current.requirements) list.append(el('li', item)); $('readiness').append(list); }
  else $('readiness').append(el('p', 'Connected and active. Review the preview before changing dates.', 'notice'));
  $('digest-list').replaceChildren();
  for (const d of current.digests) { const b = el('button', new Date(d.created_at).toLocaleString() + ' · ' + d.provider, 'secondary'); b.addEventListener('click', () => action(b, () => openDigest(d.id))); $('digest-list').append(b); }
  if (!current.digests.length) $('digest-list').append(el('p', 'No digest yet. Once your roster is saved, prepare one to see everyone—including missing evidence.'));
  $('outbox').replaceChildren();
  const table = el('table'); const header = el('tr'); for (const h of ['Message', 'Status', 'Receipt / detail']) header.append(el('th', h)); table.append(header);
  for (const row of current.outbox) { const tr = el('tr'); tr.append(el('td', row.id), el('td', row.status), el('td', row.provider_ts || row.detail || 'Awaiting its due time and send gates')); table.append(tr); } $('outbox').append(table);
  const entries = await api('entries'); $('entries').replaceChildren();
  for (const entry of entries.entries) { const box = el('details'); box.append(el('summary', `${entry.student_id} · ${entry.kind}${entry.private ? ' · PRIVATE' : ''}`), el('p', entry.text)); if (entry.source.url) addLink(box, entry.source.url, 'Source'); $('entries').append(box); }
}
function addLink(parent, url, label) { try { const parsed = new URL(url); if (parsed.protocol !== 'https:') return; const a = el('a', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; parent.append(a); } catch {} }
async function openDigest(id) {
  const d = await api('digests/' + encodeURIComponent(id)); $('digest').replaceChildren();
  $('digest').append(el('p', 'Private draft · ' + d.provider + ' · ' + new Date(d.created_at).toLocaleString(), 'notice'));
  if (d.body.themes.length) { const list = el('ul'); d.body.themes.forEach(t => list.append(el('li', t))); $('digest').append(list); }
  for (const row of d.body.students) {
    const student = current.course.students.find(s => s.id === row.student_id);
    const project = current.course.projects.find(p => p.id === student?.project_id);
    const section = el('section', undefined, 'digest-row'); section.append(el('h3', student?.name || row.student_id), el('p', row.summary));
    const evidence = d.body.evidence.find(e => e.student_id === row.student_id);
    const details = el('details'); details.append(el('summary', 'Inspect evidence and gaps'));
    for (const source of evidence?.sources || []) { const p = el('p', `${source.private ? 'PRIVATE · ' : ''}${source.kind || source.type}: ${source.text}`, 'source-list'); if (source.url) { p.append(document.createTextNode(' ')); addLink(p, source.url, 'Open source'); } details.append(p); }
    for (const warning of evidence?.collection_warnings || []) details.append(el('p', warning, 'notice'));
    section.append(details);
    const label = el('label', 'One piece of feedback — edit before sharing'); const field = el('textarea'); field.value = row.feedback; field.id = 'feedback-' + row.student_id; label.htmlFor = field.id;
    section.append(label, field, el('p', 'Destination: ' + (project?.name || 'project') + ' project channel (' + (project?.channel_id || '') + '). Classmates can see this. Do not include private notes.', 'fine'));
    const checkLabel = el('label', undefined, 'check'); const check = el('input'); check.type = 'checkbox'; checkLabel.append(check, el('span', 'I reviewed the sources and this exact feedback, including what is safe to share.'));
    const b = el('button', 'Approve and queue feedback'); b.addEventListener('click', () => action(b, async () => { if (!check.checked) throw new Error('Review the feedback and check the confirmation first.'); const result = await api('feedback', 'POST', {digest_id: id, student_id: row.student_id, draft_hash: row.draft_hash, text: field.value, reviewed: true}); say('Feedback queued for ' + result.destination + '. Delivery still obeys the global send gates.'); b.textContent = 'Approved'; field.readOnly = true; }));
    section.append(checkLabel, b); $('digest').append(section);
  }
}
$('login-form').addEventListener('submit', e => { e.preventDefault(); token = $('token').value; $('token').value = ''; action(e.submitter, async () => { await refresh(); say('Private workspace open.'); }); });
$('refresh').addEventListener('click', e => action(e.target, async () => { await refresh(); say('Updated.'); }));
$('collect').addEventListener('click', e => action(e.target, async () => { const r = await api('collect', 'POST'); say(r.status === 'disabled' ? 'GitHub collection is disabled in course configuration.' : 'Evidence collected. ' + r.warnings.join(' ')); await refresh(); }));
$('generate').addEventListener('click', e => action(e.target, async () => { say('Preparing a private digest…'); const d = await api('digests', 'POST'); await refresh(); await openDigest(d.id); say('Draft ready. No feedback has been sent.'); }));
$('hold').addEventListener('click', e => action(e.target, async () => { await api('hold', 'POST'); await refresh(); say('New sends are held. Any in-flight send still needs its receipt checked.'); }));
$('logout').addEventListener('click', () => { token = ''; current = null; location.reload(); });
$('config-file').addEventListener('change', async e => { const file = e.target.files[0]; if (file) $('course-json').value = await file.text(); });
$('save-draft').addEventListener('click', e => action(e.target, async () => { const c = JSON.parse($('course-json').value); c.active = false; c.activated_at = null; await api('course', 'PUT', c); await refresh(); say('Inactive course draft saved.'); }));
$('preview').addEventListener('click', e => action(e.target, async () => { const r = await api('preview'); $('preview-output').hidden = false; $('preview-output').textContent = JSON.stringify(r.jobs, null, 2); say('Preview uses the saved configuration; no messages were sent.'); }));
$('activate').addEventListener('click', e => action(e.target, async () => { const c = JSON.parse($('course-json').value); if (!c.meetings?.length) throw new Error('Add and preview explicit class dates before activation.'); c.active = true; c.activated_at = new Date().toISOString(); await api('course', 'PUT', c); await refresh(); say('Course activated. Global sending must also be enabled in the service environment.'); }));
