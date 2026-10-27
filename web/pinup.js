'use strict';
let token = '';
let snapshot = null;
let editing = null;
let loading = false;
const $ = id => document.getElementById(id);
function el(tag, text, cls) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; }
function say(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
function link(url, text, cls) { try { const parsed = new URL(url); if (parsed.protocol !== 'https:' || parsed.username || parsed.password) return null; const node = el('a', text, cls); node.href = url; node.target = '_blank'; node.rel = 'noopener noreferrer'; return node; } catch { return null; } }
function dateTime(value) { return value ? new Date(value).toLocaleString(undefined, {timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) + ' ET' : 'Not recorded'; }
function dateOnly(value) { return new Date(value + 'T12:00:00Z').toLocaleDateString(undefined, {timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric'}); }
async function api(path, method = 'GET', body) {
  const response = await fetch('/api/' + path, {method, cache: 'no-store', headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) { if (response.status === 401) closeSession(); throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the source links, date, and field lengths.'); }
  return data;
}
async function action(button, fn) { button.disabled = true; try { await fn(); } catch (error) { say(error.message, true); } finally { button.disabled = false; } }
function closeSession() { token = ''; snapshot = null; editing = null; $('projects').replaceChildren(); $('workspace').hidden = true; $('login').hidden = false; $('editor').close(); $('pin-form').reset(); $('sync').textContent = ''; }
async function refresh(quiet = false) {
  if (loading || editing) return;
  loading = true;
  try {
    const session = token;
    const data = await api('pinup');
    if (token !== session || !token) return;
    const changed = JSON.stringify(snapshot?.projects) !== JSON.stringify(data.projects);
    snapshot = data; $('login').hidden = true; $('workspace').hidden = false;
    $('course-label').textContent = snapshot.course ? snapshot.sprint.replace(/^sprint-/, 'Sprint ') : 'Course setup needed';
    $('sync').textContent = 'Board checked ' + dateTime(snapshot.generated_at);
    $('setup').hidden = !!snapshot.course && !!snapshot.active;
    $('setup').textContent = !snapshot.course ? 'Import the verified roster in the instructor workspace to populate this board.' : 'Course is inactive. Saved records are visible; automatic collection is paused.';
    if (changed) render(); if (!quiet) say('');
  } finally { loading = false; }
}
function hasGap(project) { return !project.collection_enabled || project.evidence_stale || !project.evidence?.complete; }
function members(profiles) {
 const list=el('div',undefined,'member-list');
 for(const person of profiles || []) { const item=el('span',undefined,'member');const photo=el('span',person.name.split(/\s+/).map(n=>n[0]).slice(0,2).join(''),'avatar fallback');
  if(person.photo) { try {const u=new URL(person.photo);if(u.protocol==='https:' && (u.hostname.endsWith('.slack-edge.com') || u.hostname==='secure.gravatar.com')){const img=el('img',undefined,'avatar');img.src=u.href;img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';img.addEventListener('error',()=>img.replaceWith(photo),{once:true});item.append(img);}else item.append(photo);}catch{item.append(photo);}}else item.append(photo);
  item.append(el('span',person.name));list.append(item);
 }return list;
}

function render() {
  if (!snapshot) return;
  // Preserve expanded source sections when saved records refresh.
  const opened = new Set([...$('projects').querySelectorAll('details[open]')].map(node => node.dataset.key));
  const query = $('search').value.trim().toLowerCase(); const filter = $('filter').value;
  const projects = snapshot.projects.filter(p => (!query || (p.name + ' ' + p.owners.map(s => s.name).join(' ')).toLowerCase().includes(query)) && (filter === 'all' || (filter === 'missing' && (!p.pin.goal || !p.pin.live_url)) || (filter === 'review' && hasGap(p))));
  $('projects').replaceChildren(); $('result-count').textContent = `${projects.length} of ${snapshot.projects.length} projects`;
  if (!projects.length) $('projects').append(el('p', snapshot.projects.length ? 'No projects match this view.' : 'No configured projects yet.', 'missing'));
  for (const project of projects) {
    const card = el('article', undefined, 'project-card'); card.append(el('h2', project.name), members(project.owners));
    const links = el('div', undefined, 'project-links');
    for (const [url, title, cls] of [[project.pin.live_url, 'Open product', 'product-link'], [project.repository_url, 'GitHub'], [project.issues_url, 'Issues'], [project.channel_url, 'Slack']]) { const a = link(url, title, cls); if (a) links.append(a); }
    card.append(links);
    for (const [label, text] of [['Desired outcome', project.pin.goal], ['Next useful test', project.pin.next_test], ['Commitment', project.pin.commitment]]) card.append(el('h3', label), el('p', text || 'No statement recorded', 'pin-text' + (text ? '' : ' missing')));
    if (project.pin.commitment_date) card.append(el('p', 'Stated date: ' + dateOnly(project.pin.commitment_date), 'fine'));
    if (!project.pin.live_url) card.append(el('p', 'Testable build link not recorded.', 'fine'));
    const source = el('div', undefined, 'provenance');
    const sourceLabel = project.pin.source_kind === 'student_statement' ? 'Student statement' : 'Instructor note';
    const sourceLink = link(project.pin.source_url, sourceLabel);
    source.append(sourceLink || el('span', 'Pin not set'));
    const edit = el('button', 'Edit pin', 'secondary edit-pin'); edit.addEventListener('click', () => editPin(project)); source.append(edit); card.append(source);
    if (project.pin.source_url) card.append(el('p', 'Source: ' + dateTime(project.pin.source_at) + ' · saved ' + dateTime(project.pin_updated_at), 'fine'));
    if (project.pin_stale) card.append(el('p', 'Pin source is more than a week old. Revisit it with the owner.', 'notice'));
    const git = el('details'); git.dataset.key = project.id + '/git'; git.open = opened.has(git.dataset.key);
    const gitState = !project.collection_enabled ? 'Disabled' : !project.evidence ? 'Not collected' : !project.evidence.complete ? 'Incomplete' : project.evidence_stale ? 'Stale' : 'Current';
    git.append(el('summary', 'GitHub evidence · ' + gitState));
    git.append(el('p', 'Last collection attempt: ' + dateTime(project.evidence?.collected_at), 'fine'));
    if (!project.collection_enabled) git.append(el('p', 'GitHub collection is disabled.', 'notice'));
    if (project.evidence_stale) git.append(el('p', project.evidence ? 'Saved evidence is more than 48 hours old.' : 'No repository evidence collected yet.', 'notice'));
    for (const warning of project.evidence?.warnings || []) git.append(el('p', warning, 'notice'));
    const items = project.evidence?.items || [];
    if (items.length) { const list = el('ul', undefined, 'evidence-list'); for (const item of items.slice(0, 8)) { const li = el('li'); li.append(link(item.url, item.text.split('\n')[0] || item.type) || el('span', item.text || item.type)); li.append(el('span', [item.type.replace('_', ' '), item.state, item.author, item.at ? dateTime(item.at) : null].filter(Boolean).join(' · '), 'fine')); list.append(li); } git.append(list); }
    else git.append(el('p', project.evidence?.complete ? 'No items in the collection window.' : 'No evidence available from this collection.', 'fine'));
    if (project.evidence) git.append(el('p', 'Rolling window since ' + dateTime(project.evidence.since) + '. Showing up to eight recent items.', 'fine'));
    card.append(git);
    const updates = el('details'); updates.dataset.key = project.id + '/slack'; updates.open = opened.has(updates.dataset.key); updates.append(el('summary', 'Captured project updates'));
    for (const entry of project.updates) { const box = el('div', undefined, 'update'); const owner = project.owners.find(s => s.id === entry.student_id); box.append(el('strong', owner?.name || entry.student_id), el('p', entry.text), el('span', 'Captured ' + dateTime(entry.created_at) + ' ', 'fine')); const a = link(entry.source.url, 'Source'); if (a) box.append(a); updates.append(box); }
    if (!project.updates.length) updates.append(el('p', 'No scoped replies captured. Open Slack for the full conversation.', 'fine'));
    card.append(updates); $('projects').append(card);
  }
}
function editPin(project) {
  editing = project; $('editor-title').textContent = project.name; $('editor-error').textContent = '';
  for (const [field, key] of [['goal', 'goal'], ['next-test', 'next_test'], ['commitment', 'commitment'], ['commitment-date', 'commitment_date'], ['live-url', 'live_url'], ['source-url', 'source_url'], ['source-kind', 'source_kind']]) $(field).value = project.pin[key] || '';
  if (project.pin.source_at) { const date = new Date(project.pin.source_at); $('source-at').value = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 19); } else $('source-at').value = '';
  $('editor').showModal(); $('goal').focus();
}
$('login-form').addEventListener('submit', event => { event.preventDefault(); token = $('token').value; $('token').value = ''; action(event.submitter, () => refresh()); });
$('refresh').addEventListener('click', event => action(event.currentTarget, () => refresh()));
$('collect').addEventListener('click', event => action(event.currentTarget, async () => { say('Collecting the configured repositories…'); const result = await api(snapshot?.activity_source === 'slack' ? 'collect-slack' : 'collect', 'POST'); await refresh(true); say(result.status === 'disabled' ? 'Enable GitHub collection in the saved course configuration first.' : 'Collection finished. ' + result.warnings.join(' ')); }));
$('logout').addEventListener('click', () => { closeSession(); say('Session closed.'); });
$('search').addEventListener('input', render); $('filter').addEventListener('change', render);
$('cancel').addEventListener('click', () => $('editor').close());
$('editor').addEventListener('close', () => { editing = null; $('pin-form').reset(); });
$('pin-form').addEventListener('submit', async event => {
  event.preventDefault(); if (!editing) return; $('save').disabled = true; $('editor-error').textContent = '';
  try {
    const pin = {goal: $('goal').value, next_test: $('next-test').value, commitment: $('commitment').value, commitment_date: $('commitment-date').value || null, live_url: $('live-url').value, source_url: $('source-url').value, source_kind: $('source-kind').value, source_at: $('source-at').value ? new Date($('source-at').value).toISOString() : null};
    await api('pinup/projects/' + encodeURIComponent(editing.id), 'PUT', {pin, expected_revision: editing.revision}); $('editor').close(); editing = null; await refresh(true); say('Private project pin saved.');
  } catch (error) { $('editor-error').textContent = error.message; } finally { $('save').disabled = false; }
});
setInterval(() => { if (token && !document.hidden && !editing) refresh(true).catch(() => { $('sync').textContent = 'Board refresh failed · saved view retained'; say('Could not refresh. The board may be out of date.', true); }); }, 30000);
document.addEventListener('visibilitychange', () => { if (token && !document.hidden && !editing) refresh(true).catch(error => say(error.message, true)); });
