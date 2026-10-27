'use strict';
const $ = id => document.getElementById(id);
const base = document.body.dataset.base;
const section = document.body.dataset.section;
let user, board, editing = null, selected = null, detailRevision = null, detailGeneration = 0;
let returnGroup = null, overviewScroll = 0;
const timelines = new Map();
const narrowScreen = window.matchMedia('(max-width:700px)');
narrowScreen.addEventListener('change',()=>{const details=$('project-current').querySelector('details');if(details)details.open=!narrowScreen.matches;});
const labels = {unknown: '—', outreach: 'Outreach', scheduled: 'Scheduled', completed: 'Completed', planning: 'Planning', drafting: 'In progress', ready: 'Ready', submitted: 'Submitted'};
const fieldLabels = {entrepreneur:'Entrepreneur', company:'Company', interview:'Interview', scheduled_date:'Scheduled date', completed_date:'Completed date', paper:'Paper', creative:'Creative product', creative_format:'Creative format', next_step:'Next step', owner:'Owner', target_date:'Target date', blocker:'Blocker', document_url:'Group document', creative_url:'Creative product link', source_url:'Source', source_date:'Source date', presentation_date:'Presentation', verified:'Verification'};
const dateFields = ['scheduled_date', 'completed_date', 'target_date', 'source_date', 'presentation_date'];
function el(tag, text, css) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (css) n.className = css; return n; }
function say(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
function day(value) { return value ? new Intl.DateTimeFormat('en-US', {month:'short', day:'numeric', timeZone:'UTC'}).format(new Date(value.slice(0,10) + 'T12:00:00Z')) : ''; }
function savedTime(value) { return new Intl.DateTimeFormat('en-US', {month:'short', day:'numeric', year:'numeric', hour:'numeric', minute:'2-digit', timeZone:'America/New_York', timeZoneName:'short'}).format(new Date(value)); }
function savedDay(value) { return new Intl.DateTimeFormat('en-US', {month:'short', day:'numeric', timeZone:'America/New_York'}).format(new Date(value)); }
function link(parent, href, text) { if (!href) return; try { if (new URL(href).protocol !== 'https:') return; const a = el('a', text); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; parent.append(a); } catch {} }
async function api(path, method = 'GET', data) {
  const response = await fetch(base + '/api/' + path, {method, credentials:'same-origin', headers:{'Content-Type':'application/json', 'X-CSRF-Token':user?.csrf || ''}, ...(data === undefined ? {} : {body:JSON.stringify(data)})});
  const body = await response.json();
  if (!response.ok) {
    if (response.status === 401) { $('workspace').hidden = true; $('login').hidden = false; if ($('editor').open) $('editor').close(); }
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Check the dates and links, then try saving again.');
  }
  return body;
}
for (const a of document.querySelectorAll('[data-section-link]')) if (a.dataset.sectionLink === section) a.setAttribute('aria-current','page');
for (const name of ['paper','creative']) { const select = document.querySelector(`[name="${name}"]`); for (const value of ['unknown','planning','drafting','ready','submitted']) { const option = el('option', value === 'unknown' ? 'Not recorded' : labels[value]); option.value = value; select.append(option); } }
function members(group) {
  const list = el('div',undefined,'member-list');
  for (const person of group.member_profiles?.length ? group.member_profiles : group.members.map(name=>({name}))) {
    const item=el('span',undefined,'member'), photo=el('span',person.name.split(/\s+/).map(n=>n[0]).slice(0,2).join(''),'avatar fallback');
    if (person.photo) {
      try {
        const u=new URL(person.photo);
        if (u.protocol==='https:' && (u.hostname.endsWith('.slack-edge.com') || u.hostname==='secure.gravatar.com')) {
          const img=el('img',undefined,'avatar'); img.src=u.href; img.alt=''; img.loading='lazy'; img.referrerPolicy='no-referrer'; img.addEventListener('error',()=>img.replaceWith(photo),{once:true}); item.append(img);
        } else item.append(photo);
      } catch { item.append(photo); }
    } else item.append(photo);
    item.append(el('span',person.name)); list.append(item);
  }
  return list;
}
function milestones(p) {
  const list=el('dl',undefined,'milestones');
  for (const [key,title] of [['interview','Interview'],['paper','Paper'],['creative','Creative']]) {
    const item=el('div'); item.append(el('dt',title),el('dd',labels[p[key]],['completed','ready','submitted'].includes(p[key])?'complete':'')); list.append(item);
  }
  return list;
}
function render() {
  const query = $('search').value.toLowerCase().trim(), filter = $('filter').value;
  const groups = board.groups.filter(g => (filter === 'all' || g.progress.interview === filter) && [g.name, ...g.members, g.progress.entrepreneur, g.progress.company, g.progress.next_step].join(' ').toLowerCase().includes(query));
  const grid=el('div',undefined,'project-grid');
  for (const g of groups) {
    const p=g.progress, card=el('a',undefined,'project-card'); card.href='#group='+encodeURIComponent(g.id); card.dataset.group=g.id; card.setAttribute('aria-label',g.name+' project updates');
    const top=el('div',undefined,'card-heading'); top.append(el('h2',g.name),el('span','→','card-arrow')); top.lastChild.setAttribute('aria-hidden','true');
    const founder=el('div',undefined,'card-founder'); founder.append(el('p',p.entrepreneur || p.company || 'Entrepreneur not recorded','founder-name')); if(p.company && p.entrepreneur) founder.append(el('p',p.company,'company'));
    card.append(top,founder,members(g),milestones(p));
    if(p.next_step) { const next=el('div',undefined,'card-next'); next.append(el('span','Next step','muted'),el('p',p.next_step)); card.append(next); }
    if(p.blocker) card.append(el('p','Blocker: '+p.blocker,'card-blocker'));
    if(g.revision || p.source_date) card.append(el('p',g.revision ? 'Updated '+savedDay(g.updated) : 'Source '+day(p.source_date),'card-date'));
    card.addEventListener('click',()=>{returnGroup=g.id;overviewScroll=window.scrollY;}); grid.append(card);
  }
  $('groups').replaceChildren(groups.length ? grid : el('p','No groups match this search.'));
  $('summary').textContent = `${groups.length} of ${board.groups.length} groups · ${board.groups.filter(g=>g.progress.interview === 'completed').length} interviews reported complete`;
}
function currentProject(g) {
  const p=g.progress, content=el('div',undefined,'current-project');
  content.append(el('h2',p.entrepreneur || p.company || 'Entrepreneur not recorded','project-founder')); if(p.company && p.entrepreneur) content.append(el('p',p.company,'company'));
  content.append(milestones(p));
  const details=el('details',undefined,'project-details'); details.open=!narrowScreen.matches; details.append(el('summary','Team and project details'),members(g));
  const facts=el('dl',undefined,'project-facts');
  for(const key of ['scheduled_date','completed_date','presentation_date','creative_format','next_step','owner','target_date','blocker']) {
    if (!p[key]) continue;
    const item=el('div'); item.append(el('dt',fieldLabels[key]),el('dd',dateFields.includes(key)?day(p[key]):p[key],key==='blocker'?'error':'')); facts.append(item);
  }
  details.append(facts);
  if(p.interview==='completed' && !p.completed_date) details.append(el('p','Interview reported complete; exact date not recorded.','muted'));
  const links=el('nav',undefined,'source-links'); links.setAttribute('aria-label','Project sources'); link(links,g.slack_url,'Team Slack'); link(links,p.document_url,'Group document'); link(links,p.creative_url,'Creative product'); link(links,p.source_url,'Source'); details.append(links); content.append(details);
  if(g.editable) { const edit=el('button','Update group'); edit.addEventListener('click',()=>openEditor(g)); content.append(edit); }
  $('project-current').replaceChildren(content);
}
function fieldValue(field,value) {
  if(value===null || value==='') return 'Removed';
  if(field==='verified') return value?'Instructor verified':'Not verified';
  if(dateFields.includes(field)) return day(value);
  return ['interview','paper','creative'].includes(field) ? (value==='unknown'?'Not recorded':labels[value]) : value;
}
function timelineEvent(update) {
  const item=el('li',undefined,'timeline-event'), article=el('article');
  const time=el('time',savedTime(update.updated)); time.dateTime=update.updated;
  const heading=el('div',undefined,'event-heading'); heading.append(el('h3',update.revision===0?'Imported project record':update.progress.verified?'Instructor-verified update':'Group update'),time); article.append(heading);
  if(update.revision>0) article.append(el('p',update.reporter,'event-reporter'));
  const changes=update.changes.filter(change=>change.field!=='verified'), list=el('dl',undefined,'event-changes');
  for(const change of changes) {
    const row=el('div'), value=el('dd'); row.append(el('dt',fieldLabels[change.field]));
    if(change.field.endsWith('_url') && change.after) link(value,change.after,'Open '+fieldLabels[change.field].toLowerCase());
    else value.append(el('span',fieldValue(change.field,change.after)));
    if(update.revision>0 && ['interview','paper','creative'].includes(change.field)) value.append(el('span','Previously '+(change.before==='unknown'?'not recorded':fieldValue(change.field,change.before)),'previous-value'));
    row.append(value); list.append(row);
  }
  if(changes.length) article.append(list);
  else article.append(el('p',update.revision===0?'No milestones were recorded in the initial import.':update.changes.length?fieldValue('verified',update.progress.verified):'Saved without changes to project progress.','muted'));
  if(update.revision>0 && update.progress.source_url && !changes.some(c=>c.field==='source_url')) { const source=el('div',undefined,'event-source'); link(source,update.progress.source_url,'Source'); if(update.progress.source_date) source.append(el('span',' · '+day(update.progress.source_date),'muted')); article.append(source); }
  item.append(article); return item;
}
function renderTimeline(state) {
  const list=el('ol',undefined,'timeline-list'); for(const update of state.updates) list.append(timelineEvent(update));
  $('timeline').replaceChildren(list);
  if(state.next_before!==null) {
    const more=el('button','Earlier updates','secondary'); more.addEventListener('click',async()=>{more.disabled=true;await loadTimeline(true);}); $('timeline').append(more);
  }
}
async function loadTimeline(older=false) {
  const id=selected, generation=detailGeneration, state=timelines.get(id);
  try {
    const data=await api('groups/'+encodeURIComponent(id)+'/timeline'+(older?'?before='+state.next_before:''));
    if(selected!==id || generation!==detailGeneration) return;
    const next={revision:detailRevision, updates:older?[...state.updates,...data.updates]:data.updates, next_before:data.next_before};
    timelines.set(id,next); renderTimeline(next);
    if(older) { const firstNew=$('timeline').querySelectorAll('.timeline-event')[state.updates.length]; if(firstNew){firstNew.tabIndex=-1;firstNew.focus({preventScroll:true});} }
  } catch(e) {
    if(selected!==id || generation!==detailGeneration) return;
    const retry=el('button',older?'Retry earlier updates':'Retry','secondary'); retry.addEventListener('click',()=>{retry.disabled=true;loadTimeline(older);});
    const error=el('p',e.message,'error'); error.setAttribute('role','alert');
    if(!older) $('timeline').replaceChildren(); else $('timeline').querySelector('button')?.remove();
    $('timeline').append(error,retry);
  }
}
function syncView(focus=false) {
  if(!board) return;
  const id=new URLSearchParams(location.hash.slice(1)).get('group');
  const group=board.groups.find(g=>g.id===id), wasSelected=selected;
  $('overview').hidden=!!id; $('project').hidden=!id;
  $('page-title').textContent=group?group.name:'Final projects'; document.title=(group?group.name+' · ':'Final projects · ')+'ENTR 5500';
  if(!id) {
    selected=null; detailRevision=null; detailGeneration++;
    if(focus && wasSelected) { const card=[...document.querySelectorAll('[data-group]')].find(n=>n.dataset.group===returnGroup); window.scrollTo(0,overviewScroll); (card || $('page-title')).focus({preventScroll:true}); }
    return;
  }
  if(!group) { selected=null; detailGeneration++; $('project-current').replaceChildren();$('timeline').replaceChildren(el('p','This group is not in your section.')); return; }
  if(selected!==id || detailRevision!==group.revision) {
    selected=id; detailRevision=group.revision; detailGeneration++; currentProject(group);
    const cached=timelines.get(id);
    if(cached?.revision===group.revision) renderTimeline(cached);
    else { $('timeline').replaceChildren(el('p','Loading updates…','muted')); loadTimeline(); }
  }
  if(focus) { window.scrollTo(0,0); $('page-title').focus({preventScroll:true}); }
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
    board.groups = board.groups.map(g=>g.id === updated.id ? updated : g); $('editor').close(); render(); syncView(); $('project-current').querySelector('button')?.focus({preventScroll:true}); say('Group update saved.');
  } catch(e) { $('edit-error').textContent = e.message; } finally { $('save').disabled = false; }
});
async function refresh() { board = await api('sections/' + section); render(); syncView(); }
window.addEventListener('hashchange',()=>{say('');syncView(true);});
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
  setInterval(()=>{ if (!editing && !document.hidden && !document.activeElement.closest('#groups, #timeline')) refresh().catch(e=>say(e.message,true)); },30000);
})().catch(e=>say(e.message,true));
