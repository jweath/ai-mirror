'use strict';
const $ = id => document.getElementById(id);
const base = document.body.dataset.base;
const section = document.body.dataset.section;
let user, board, editing = null;
const opened = new Set();
const labels = {unknown: '—', outreach: 'Outreach', scheduled: 'Scheduled', completed: 'Completed', planning: 'Planning', drafting: 'In progress', ready: 'Ready', submitted: 'Submitted'};
const dateFields = ['scheduled_date', 'completed_date', 'target_date', 'source_date', 'presentation_date'];
function el(tag, text, css) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (css) n.className = css; return n; }
function say(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
function day(value) { return value ? new Intl.DateTimeFormat('en-US', {month:'short', day:'numeric', timeZone:'UTC'}).format(new Date(value.slice(0,10) + 'T12:00:00Z')) : ''; }
function link(parent, href, text) { if (!href) return; try { if (new URL(href).protocol !== 'https:') return; const a = el('a', text); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; parent.append(a); } catch {} }
async function api(path, method = 'GET', data) {
  const response = await fetch(base + '/api/' + path, {method, credentials:'same-origin', headers:{'Content-Type':'application/json', 'X-CSRF-Token':user?.csrf || ''}, ...(data === undefined ? {} : {body:JSON.stringify(data)})});
  const body = await response.json();
  if (!response.ok) { if (response.status === 401) { $('workspace').hidden = true; $('login').hidden = false; } throw new Error(typeof body.detail === 'string' ? body.detail : 'Check the dates and links, then try saving again.'); }
  return body;
}
for (const a of document.querySelectorAll('[data-section-link]')) if (a.dataset.sectionLink === section) a.setAttribute('aria-current','page');
for (const name of ['paper','creative']) { const select = document.querySelector(`[name="${name}"]`); for (const value of ['unknown','planning','drafting','ready','submitted']) { const option = el('option', value === 'unknown' ? 'Not recorded' : labels[value]); option.value = value; select.append(option); } }
function members(profiles) {
 const list=el('div',undefined,'member-list');
 for(const person of profiles || []) { const item=el('span',undefined,'member');const photo=el('span',person.name.split(/\s+/).map(n=>n[0]).slice(0,2).join(''),'avatar fallback');
  if(person.photo) { try {const u=new URL(person.photo);if(u.protocol==='https:' && (u.hostname.endsWith('.slack-edge.com') || u.hostname==='secure.gravatar.com')){const img=el('img',undefined,'avatar');img.src=u.href;img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';img.addEventListener('error',()=>img.replaceWith(photo),{once:true});item.append(img);}else item.append(photo);}catch{item.append(photo);}}else item.append(photo);
  item.append(el('span',person.name));list.append(item);
 }return list;
}

function render() {
  const query = $('search').value.toLowerCase().trim(), filter = $('filter').value;
  const groups = board.groups.filter(g => (filter === 'all' || g.progress.interview === filter) && [g.name, ...g.members, g.progress.entrepreneur, g.progress.company, g.progress.next_step].join(' ').toLowerCase().includes(query));
  const table = el('table'), head = el('thead'), headings = el('tr');
  for (const h of ['Group','Entrepreneur','Interview','Deliverables','Next step']) { const th = el('th',h); th.scope = 'col'; headings.append(th); } head.append(headings); table.append(head);
  const tbody = el('tbody');
  for (const g of groups) {
    const p = g.progress, row = el('tr');
    function cell(label) { const td = el('td'); td.dataset.label = label; row.append(td); return td; }
    const group = cell('Group'); group.append(el('h2',g.name), g.member_profiles?.length ? members(g.member_profiles) : el('p',g.members.join(' · '),'members'));
    const founder = cell('Entrepreneur'); founder.append(el('p',p.entrepreneur || '—')); if (p.company) founder.append(el('p',p.company,'muted'));
    const interview = cell('Interview'); interview.append(el('p',labels[p.interview],p.interview === 'completed' ? 'complete' : ''));
    if (p.interview === 'completed' && p.completed_date) interview.append(el('p',day(p.completed_date),'muted'));
    if (p.interview === 'scheduled' && p.scheduled_date) interview.append(el('p',day(p.scheduled_date),'muted'));
    const deliverables = cell('Deliverables'); deliverables.append(el('p','Paper: ' + labels[p.paper]), el('p','Creative: ' + labels[p.creative]));
    const next = cell('Next step'); next.append(el('p',p.next_step || '—')); if (p.owner || p.target_date) next.append(el('p',[p.owner, day(p.target_date)].filter(Boolean).join(' · '),'muted'));
    const detailRow = el('tr','', 'detail-row'), detailCell = el('td'); detailCell.colSpan = 5;
    const details = el('details'); details.open = opened.has(g.id); const summary = el('summary','Details and sources'); details.append(summary);
    details.addEventListener('toggle', () => details.open ? opened.add(g.id) : opened.delete(g.id));
    const content = el('div',undefined,'detail-content');
    if (p.blocker) content.append(el('p','Blocker: ' + p.blocker));
    if (p.creative_format) content.append(el('p','Creative format: ' + p.creative_format));
    if (p.interview === 'completed' && !p.completed_date) content.append(el('p','Interview reported complete; exact date not recorded.'));
    if (p.presentation_date) content.append(el('p','Presentation: ' + day(p.presentation_date)));
    const links = el('nav',undefined,'source-links'); link(links,g.slack_url,'Team Slack'); link(links,p.document_url,'Group document'); link(links,p.creative_url,'Creative product'); link(links,p.source_url,'Source'); content.append(links);
    content.append(el('p',g.revision ? `${p.verified ? 'Instructor verified' : 'Reported'} · ${g.reporter} · saved ${day(g.updated)}` : p.source_url ? `Imported source${p.source_date ? ' · ' + day(p.source_date) : ''}` : 'No milestone update recorded.','muted'));
    const historyButton = el('button','Update history','secondary'); historyButton.addEventListener('click',async () => { historyButton.disabled = true; try { const data = await api('groups/' + encodeURIComponent(g.id) + '/history'); const list = el('ul'); for (const update of data.updates) list.append(el('li',`${day(update.updated)} · ${update.reporter} · interview: ${labels[update.progress.interview]}, paper: ${labels[update.progress.paper]}, creative: ${labels[update.progress.creative]}`)); if (!data.updates.length) list.append(el('li','No earlier saved updates.')); historyButton.replaceWith(list); } catch (e) { say(e.message,true); historyButton.disabled = false; } });
    content.append(historyButton);
    if (g.editable) { const edit = el('button','Update group'); edit.addEventListener('click',() => openEditor(g)); content.append(edit); }
    details.append(content); detailCell.append(details); detailRow.append(detailCell); tbody.append(row,detailRow);
  }
  table.append(tbody); $('groups').replaceChildren(table);
  if (!groups.length) $('groups').replaceChildren(el('p','No groups match this search.'));
  $('summary').textContent = `${groups.length} of ${board.groups.length} groups · ${board.groups.filter(g=>g.progress.interview === 'completed').length} interviews reported complete · checked ${new Intl.DateTimeFormat('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/New_York'}).format(new Date(board.checked))} ET`;
}
function openEditor(group) {
  editing = group; $('editor-title').textContent = group.name; $('edit-error').textContent = '';
  const form = $('edit-form');
  for (const [name,value] of Object.entries(group.progress)) { const field = form.elements.namedItem(name); if (!field) continue; if (field.type === 'checkbox') field.checked = user.role === 'instructor' && value; else field.value = value ?? ''; }
  $('verified-label').hidden = user.role !== 'instructor'; $('presentation-label').hidden = user.role !== 'instructor';
  form.elements.namedItem('completed_date').max = new Date().toISOString().slice(0,10);
  $('editor').showModal();
}
$('cancel').addEventListener('click',()=>$('editor').close());
$('editor').addEventListener('close',()=>{editing = null;});
$('edit-form').addEventListener('submit',async event => {
  event.preventDefault(); $('save').disabled = true; $('edit-error').textContent = '';
  try {
    const progress = {...editing.progress};
    for (const [name,value] of new FormData(event.target)) progress[name] = dateFields.includes(name) ? value || null : value;
    progress.verified = user.role === 'instructor' && event.target.elements.namedItem('verified').checked;
    const updated = await api('groups/' + encodeURIComponent(editing.id),'PUT',{revision:editing.revision,progress});
    board.groups = board.groups.map(g=>g.id === updated.id ? updated : g); $('editor').close(); render(); say('Group update saved.');
  } catch(e) { $('edit-error').textContent = e.message; } finally { $('save').disabled = false; }
});
async function refresh() { board = await api('sections/' + section); render(); }
$('search').addEventListener('input',()=>board && render()); $('filter').addEventListener('change',()=>board && render());
$('refresh').addEventListener('click',async e=>{e.target.disabled=true;try{await refresh();say('');}catch(err){say(err.message,true);}finally{e.target.disabled=false;}});
$('logout').addEventListener('click',async()=>{try{await api('logout','POST'); location.reload();}catch(e){say(e.message,true);}});
(async()=>{
  const session = await api('session'); user = session.user; $('preview').hidden = !session.preview;
  if (!session.slack_enabled && !user) { $('sign-in').hidden = true; say('Slack sign-in is being connected.'); }
  if (!user) return;
  $('login').hidden = true;
  for(const a of document.querySelectorAll('[data-section-link]')) a.hidden = !user.sections.includes(a.dataset.sectionLink);
  $('workspace').hidden = false; $('logout').hidden = session.preview;
  $('deadline').textContent = `Both deliverables are due November 10 before ${section === '1135' ? '11:35 a.m.' : '2:55 p.m.'} Eastern. Submit through your shared group Google Doc with working links and commenter access for John.`;
  await refresh();
  setInterval(()=>{ if (!editing && !document.hidden && !document.activeElement.closest('#groups')) refresh().catch(e=>say(e.message,true)); },30000);
})().catch(e=>say(e.message,true));
