'use strict';
const $ = id => document.getElementById(id);
const base = document.body.dataset.base, mode = document.body.dataset.mode;
let user, overview, people, homeData, learningData, githubData, refreshing = false;
let prepSnapshot='current';
const searches={projects:'',people:''};
const titles = {overview:'Instructor home', projects:'Projects', people:'People', prep:'Class prep', checkins:'Check-ins', connections:'Connections', setup:'GitHub setup'};
function el(tag, text, cls) { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(cls)node.className=cls; return node; }
function link(href,text,cls) { const node=el('a',text,cls); try { const url=new URL(href,location.origin); if(url.protocol!=='https:' && !(url.origin===location.origin && url.pathname.startsWith('/entr/'))) return el('span',text); if(url.origin===location.origin && !url.pathname.startsWith('/entr/'))return el('span',text); node.href=url.href; } catch { return el('span',text); } return node; }
function say(text,error=false) { $('message').textContent=text; $('message').classList.toggle('error',error); }
function date(value, time=false) { if(!value)return ''; const parsed=new Date(value); if(Number.isNaN(parsed.valueOf()))return ''; return new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',...(time?{hour:'numeric',minute:'2-digit'}:{})}).format(parsed); }
function allowed(item) { const selected=$('course-filter').value; return selected==='all' || `${item.course}:${item.section}`===selected || (!item.section && item.course===selected.split(':')[0]); }
function view() { return titles[location.hash.slice(1)] ? location.hash.slice(1) : 'overview'; }
async function api(path, method='GET') {
 const response=await fetch(base+'/api/'+path,{method,credentials:'same-origin',headers:{'X-CSRF-Token':user?.csrf || ''}});
 const data=await response.json();
 if(!response.ok) { if([401,403].includes(response.status)) { $('content').replaceChildren(); $('controls').hidden=true; $('footer').hidden=true; $('sidebar').hidden=true; $('login').hidden=false; } throw new Error(typeof data.detail==='string'?data.detail:'The workspace could not be loaded.'); }
 return data;
}
function members(profiles) {
 const list=el('div',undefined,'member-list');
 for(const person of profiles || []) { const item=el('span',undefined,'member');const photo=el('span',person.name.split(/\s+/).map(n=>n[0]).slice(0,2).join(''),'avatar fallback');
  if(person.photo) { try {const u=new URL(person.photo);if(u.protocol==='https:' && (u.hostname.endsWith('.slack-edge.com') || u.hostname==='secure.gravatar.com')){const img=el('img',undefined,'avatar');img.src=u.href;img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';img.addEventListener('error',()=>img.replaceWith(photo),{once:true});item.append(img);}else item.append(photo);}catch{item.append(photo);}}else item.append(photo);
  item.append(el('span',person.name));list.append(item);
 }return list;
}
function responseDetail(person,post) {
 const details=el('details',undefined,'prep-response'),title=el('summary',person.name+' · '+person.group);details.append(title);
 const fields=[['recommendation','Recommendation'],['detail','Case detail'],['question','Discussion question']],identified=fields.some(([key])=>post[key]);
 if(!post.complete)details.append(el('p','Review this post to confirm its preparation response.','muted small'));
 for(const [key,label] of fields)if(post[key])details.append(el('h4',label),el('p',post[key]));
 if(identified){const original=el('details');original.append(el('summary','Original post'),el('p',post.text,'source-text'));details.append(original);}else details.append(el('p',post.text,'source-text'));
 details.append(link(post.url,'Open in Slack','small'));return details;
}
function showPrep() {
 if(!learningData){$('content').replaceChildren(el('p','Loading prep responses…','empty'));return;}
 const content=el('div',undefined,'learning');
 const chooser=el('div',undefined,'snapshot-choice');
 for(const [value,label] of [['current','Latest responses'],['cutoff','At prep cutoff']]) {const button=el('button',label,'secondary');button.setAttribute('aria-pressed',String(prepSnapshot===value));button.addEventListener('click',()=>{prepSnapshot=value;showPrep();});chooser.append(button);}content.append(chooser);
 if(learningData.error)content.append(el('p',learningData.error,'error'));
 let shown=0;
 for(const assignment of learningData.assignments || []) {
  const selectedSections=assignment.sections.filter(s=>allowed({course:'5500',section:s.id}));if(!selectedSections.length)continue;shown++;
  const heading=el('div',undefined,'learning-heading');heading.append(el('h2',assignment.title),link(assignment.source_url,'Assignment instructions'));content.append(heading);
  for(const section of selectedSections) {
   const article=el('section',undefined,'prep-section');article.append(el('h3','ENTR 5500 · '+(section.id==='1135'?'11:35':'2:55')));
   article.append(el('p','Prep cutoff '+date(section.prep_cutoff,true)+' Eastern · assignment due before class','muted small'));
   const channels=section.channels || [],connected=channels.filter(c=>c.complete).length;
   if(connected<channels.length)article.append(el('p',`${connected} of ${channels.length} project channels read completely. Unread channels do not establish missing work.`,'error'));
   if(prepSnapshot==='cutoff' && !section.cutoff_reached){article.append(el('p','The prep cutoff has not passed. Use latest responses while preparing.','empty'));content.append(article);continue;}
   const key=prepSnapshot==='cutoff'?'at_cutoff':'response',students=section.students,posts=students.filter(s=>s[key]);
   article.append(el('p',`${posts.filter(s=>s[key].complete).length} complete ${posts.filter(s=>s[key].complete).length===1?'response':'responses'} · ${posts.filter(s=>!s[key].complete).length} to review · ${students.length} students`,'prep-count'));
   const unmapped=students.filter(s=>!s.case);if(unmapped.length)article.append(el('p',[...new Set(unmapped.map(s=>s.group))].join(', ')+': case assignment needs confirmation.','error'));
   const cases=el('div',undefined,'prep-cases');
   for(const caseName of ['Dropbox','Cork’d']) {
    const panel=el('section');panel.append(el('h4',caseName));const answers=posts.filter(s=>s.case===caseName);
    if(!answers.length)panel.append(el('p','No responses captured yet.','empty'));
    else {const topics=[['Customer understanding',/usability|customer|consumer|testing/i],['Pricing and revenue',/revenue|paying|pricing|price|freemium|business version/i],['Focus and simplicity',/simple|simplicity|complex|features|focus/i],['Growth and distribution',/referral|marketing|growth|distribution|acquisition/i]];
     const themes=topics.map(([label,test])=>({label,answers:answers.filter(s=>test.test(s[key].text))})).filter(t=>t.answers.length);
     if(themes.length){const text=el('p',undefined,'muted small');text.append('Topics in the posts: '+themes.map(t=>t.label.toLowerCase()+' ('+t.answers.length+')').join(' · '));panel.append(text);}
     const questions=el('ul',undefined,'prep-questions');for(const person of answers.filter(s=>s[key].question)){const item=el('li');item.append(el('p',person[key].question),link(person[key].url,person.name+' · '+person.group,'small'));questions.append(item);}if(questions.childElementCount)panel.append(questions);
     const all=el('details');all.append(el('summary','Recommendations and case evidence ('+answers.length+')'));for(const person of answers)all.append(responseDetail(person,person[key]));panel.append(all);
    }cases.append(panel);
   }article.append(cases);
   const coverage=el('details',undefined,'coverage');coverage.append(el('summary','Response coverage'));
   const [wrap,body]=table(['Student','Group','Response'],'coverage-table');for(const student of students){const row=el('tr');cell(row).append(el('span',student.name));cell(row,'Group').append(el('span',student.group));const state=cell(row,'Response');state.append(el('span',student[key]?(student[key].complete?'Three parts captured':'Needs review'):'No response found'));if(student[key])state.append(' · ',link(student[key].url,'Source'));body.append(row);}coverage.append(wrap);article.append(coverage);
   content.append(article);
  }
 }
 if(!shown)content.append(el('p','No prep assignment is connected for this course selection.','empty'));
 $('content').replaceChildren(content);
}
function showCheckins() {
 const content=el('div',undefined,'learning');const rows=(learningData?.reflections || []).filter(r=>allowed({course:'5500',section:r.section}));
 if(learningData?.error)content.append(el('p',learningData.error,'error'));
 const dates=[...new Set(rows.map(r=>r.date))].sort().reverse();
 if(!dates.length)content.append(el('p','No reflections have been saved yet. The existing participation check-in now includes optional takeaway, muddiest point, and next-question fields.','empty'));
 for(const day of dates){const section=el('section',undefined,'prep-section');section.append(el('h2',date(day+'T12:00:00-05:00')));const answers=rows.filter(r=>r.date===day);section.append(el('p',`${answers.filter(r=>r.takeaway || r.muddy || r.next_question).length} reflections saved`,'muted small'));for(const r of answers.filter(r=>r.takeaway || r.muddy || r.next_question)){const detail=el('details',undefined,'prep-response');detail.append(el('summary',r.name+' · '+(r.section==='1135'?'11:35':'2:55')));for(const [key,label] of [['takeaway','Takeaway'],['muddy','Muddiest point'],['next_question','Next question or action']])if(r[key])detail.append(el('h4',label),el('p',r[key]));section.append(detail);}content.append(section);}
 $('content').replaceChildren(content);
}
function personalLearning(course) {
 const box=el('section',undefined,'work');box.append(el('h3','Your preparation'));
 for(const assignment of learningData?.assignments || [])for(const section of assignment.sections.filter(s=>s.id===course.section))for(const student of section.students){box.append(el('p',assignment.title),el('p','Instructor prep cutoff '+date(section.prep_cutoff,true)+' Eastern. Due before class.','muted small'));if(student.response)box.append(responseDetail(student,student.response));else box.append(el('p','No response captured yet. Post once in your project Slack channel; the bot reuses that post.','muted small'));}
 const mine=(learningData?.reflections || []).filter(r=>r.section===course.section && (r.takeaway || r.muddy || r.next_question)).slice(0,3);
 if(mine.length){box.append(el('h3','Your recent check-ins'));for(const r of mine){const item=el('details');item.append(el('summary',date(r.date+'T12:00:00-05:00')));for(const [key,label] of [['takeaway','Takeaway'],['muddy','Revisit'],['next_question','Next']])if(r[key])item.append(el('h4',label),el('p',r[key]));box.append(item);}}
 return box;
}

function courseCard(course, personal=false) {
 const card=el('section',undefined,'course-card');
 card.append(el('p',course.label,'eyebrow'),el('h2','ENTR '+course.course));if(personal)card.append(el('p',course.title,'course-title'));
 card.append(link(course.overview_url,course.course==='5000'?'Project overview →':'Final project overview →','primary'));
 if(!personal) {
  const metrics=el('div',undefined,'metrics');
  for(const metric of course.metrics) { const item=el('div'); item.append(el('strong',String(metric.value)),el('span',metric.label)); metrics.append(item); }
  card.append(metrics,el('p',`${course.students} students · ${course.groups} ${course.course==='5000'?'projects':'groups'}`,'course-meta'));
 } else if(course.my_work) {
  const work=el('div',undefined,'work'); work.append(el('h3',course.my_work.name));
  if(course.my_work.next_step){work.append(el('p',course.my_work.next_step));if(course.my_work.source_at){const source=el('p',undefined,'muted small');source.append(course.my_work.source_url?link(course.my_work.source_url,'Reported '+date(course.my_work.source_at)):el('span','Reported '+date(course.my_work.source_at)));work.append(source);}}
  const links=el('div',undefined,'course-links'); links.append(link(course.my_work.href,'Team Slack'));if(course.course==='5000')links.append(link(base+'/#setup','GitHub setup'));
  if(course.my_work.document_url)links.append(link(course.my_work.document_url,course.course==='5000'?'Repository':'Group document'));
  work.append(links);card.append(work);
 }
 if(personal && course.course==='5500' && learningData?.assignments?.some(a=>a.sections.some(s=>s.id===course.section && s.students.length)))card.append(personalLearning(course));
 if(personal) {
  const upcoming=el('div',undefined,'work');upcoming.append(el('h3','Upcoming'));
  if(course.brief.expired || !course.brief.connected)upcoming.append(el('p',course.brief.expired?'The course brief needs review. Use the course home for current instructions.':'Current coursework could not be loaded.','muted small'));
  else if(course.brief.actions.length) {
   const list=el('ul',undefined,'action-list');
   for(const action of course.brief.actions.slice(0,3)) { const li=el('li');li.append(link(action.href,action.title)); if(action.due)li.append(el('p',date(action.due,true)+' Eastern','muted small'));if(action.detail)li.append(el('p',action.detail));if(action.source_url!==action.href)li.append(link(action.source_url,'Instructions','small'));list.append(li); }upcoming.append(list);
  } else upcoming.append(el('p','No confirmed due items in the published brief.','muted small'));
  card.append(upcoming);
 }
 const links=el('nav',undefined,'course-links');links.hidden=!personal;links.setAttribute('aria-label',`ENTR ${course.course} ${course.label}`);links.append(link(course.home_url,'Course home'),link(course.assignments_url,'Assignments'));if(personal)links.append(link(course.slack_url,'Class Slack'));card.append(links);
 return card;
}
function showHome() {
 $('title').textContent='My courses';document.title='My courses · ENTR';
 const courses=el('div',undefined,'course-grid');for(const course of homeData.courses)courses.append(courseCard(course,true));

 const tools=el('nav',undefined,'tool-row');tools.setAttribute('aria-label','Shared course tools');tools.append(link(homeData.name_practice_url,'Name practice'),link(homeData.grades_url,'eLC: quizzes and grades'),link('/entr/general/tools-and-workflows/','AI use and course workflows'));
 $('content').replaceChildren(courses,tools);$('footer').hidden=false;$('checked').textContent='Coursework comes from the published course brief.';
}
function showOverview() {
 const grid=el('div',undefined,'course-grid');for(const course of overview.courses.filter(allowed))grid.append(courseCard(course));
 const review=el('section',undefined,'attention'), changes=el('section');review.append(el('h2','Needs attention'));changes.append(el('h2','Recent changes'));
 const alerts=overview.alerts.filter(allowed), list=el('ul',undefined,'review-list');
 for(const alert of alerts) { const li=el('li');li.append(el('h3',alert.title),el('p',alert.detail));if(alert.href)li.append(link(alert.href,'Review','small'));list.append(li); }
 review.append(alerts.length?list:el('p','No recorded blockers or connection issues in this view.','empty'));
 const recent=overview.changes.filter(allowed).slice(0,8), updates=el('ul',undefined,'changes');
 for(const change of recent) { const li=el('li');li.append(el('p',`${change.kind} · ${date(change.at,true)}`,'meta'),link(change.href,change.name,'change-name'),el('p',change.text));updates.append(li); }
 changes.append(recent.length?updates:el('p','No captured changes to show.','empty'));$('content').replaceChildren(review,grid,changes);
}
function searchControl(label,id) { const field=el('label',label,'search-label'),input=el('input');input.type='search';input.id=id;input.autocomplete='off';field.htmlFor=id;field.append(input);return [field,input]; }
function table(headers,cls) { const wrap=el('div',undefined,'table-wrap'),t=el('table',undefined,cls),head=el('thead'),row=el('tr'),body=el('tbody');for(const label of headers){const cell=el('th',label);cell.scope='col';row.append(cell);}head.append(row);t.append(head,body);wrap.append(t);return [wrap,body]; }
function cell(row,label) { const td=el('td');if(label)td.dataset.label=label;row.append(td);return td; }
function showProjects() {
 const [field,input]=searchControl('Find a project or group','project-search');input.value=searches.projects;const [wrap,body]=table(['Project / group','Next step','Blocker',''],'project-table');
 const status=el('p',undefined,'empty');status.setAttribute('role','status');
 function render() { const query=input.value.toLowerCase().trim(),rows=overview.projects.filter(allowed).filter(p=>[p.name,p.next_step,p.blocker].join(' ').toLowerCase().includes(query));body.replaceChildren();
  for(const project of rows) { const row=el('tr');const name=cell(row);name.append(el('strong',project.name),members(project.members),el('p',`ENTR ${project.course} · ${project.section==='115'?'1:15':project.section==='1135'?'11:35':'2:55'}`,'muted small'));cell(row,'Next step').append(el('p',project.next_step || '—'));cell(row,'Blocker').append(el('p',project.blocker || '—'));const source=cell(row);source.append(link(project.overview_url,'Open overview'));if(project.source_url){source.append(el('br'),link(project.source_url,'Source','small'));}body.append(row); }
  status.textContent=rows.length?`${rows.length} ${rows.length===1?'project or group':'projects and groups'}`:'No matching projects or groups.';
 }
 input.addEventListener('input',()=>{searches[view()]=input.value;render();});render();$('content').replaceChildren(field,wrap,status);
}
function showPeople() {
 const [field,input]=searchControl('Find a student or group','people-search');input.value=searches.people;const [wrap,body]=table(['Student','Enrollment and group','Source'],'people-table');const status=el('p',undefined,'empty');status.setAttribute('role','status');
 function render() { const query=input.value.toLowerCase().trim();const rows=people.people.map(p=>({...p,enrollments:p.enrollments.filter(allowed)})).filter(p=>p.enrollments.length && [p.name,...p.enrollments.map(e=>e.group_name)].join(' ').toLowerCase().includes(query));body.replaceChildren();
  for(const person of rows) { const row=el('tr');cell(row).append(members([person]));const enrollments=cell(row,'Enrollment and group');for(const grant of person.enrollments)enrollments.append(el('p',`ENTR ${grant.course} · ${grant.section==='115'?'1:15':grant.section==='1135'?'11:35':'2:55'} · ${grant.group_name}`));const source=cell(row);const details=el('details'),list=el('ul');details.append(el('summary','Identity and sources'));for(const grant of person.enrollments)list.append(el('li',`${grant.source} · ${grant.source_id}`));details.append(el('p',person.slack_id,'source-detail'),list);source.append(details);body.append(row); }
  status.textContent=rows.length?`${rows.length} ${rows.length===1?'student':'students'} · source rosters remain authoritative`:'No matching students.';
 }
 input.addEventListener('input',()=>{searches[view()]=input.value;render();});render();$('content').replaceChildren(field,wrap,status);
}
function showConnections() {
 const [wrap,body]=table(['Record','Current connection','Review'],'connection-table');
 const rows=[['Instructions and dates','Read from the published course brief.','Course homes','/entr/']];
 if(overview.courses.some(c=>c.course==='5000'))rows.push(['5000 project evidence',overview.courses.find(c=>c.course==='5000').metrics.map(m=>`${m.value} ${m.label.toLowerCase()}`).join(' · '),'Project overview','/entr/5000/2026/fall/']);
 if(overview.courses.some(c=>c.course==='5500'))rows.push(['5500 group progress','Source imports and group reports, with revision history.','Final project guide','/entr/5500/assignments/final-group-project/']);
 rows.push(['Participation',overview.learning_connected?'Prep and reflections connected here. Attendance review, corrections, and grade exports remain in instOS.':overview.participation.detail,'',''],['Name practice','The existing Face Book tool.','Open name practice','https://the-face-book-production.up.railway.app'],['Quizzes and grades','eLC remains the official record.','Open eLC','https://elc.uga.edu/'],['Recordings and summaries','Originals and transcription remain local. Reviewed summaries are published on the course site.','Class notes','/entr/'],['AI assistants','Use ChatGPT or Claude under each assignment’s policy. No additional journal or whole-chat capture.','Course workflows','/entr/general/tools-and-workflows/']);
 if(overview.notifications)rows.push(['AI Mirror prompts',`${overview.notifications.mirror_enabled?'Enabled':'Class messaging off'} · ${overview.notifications.scheduled} saved schedule moments · ${overview.notifications.pending} pending messages${overview.notifications.hold?' · delivery hold':''}`,'Schedule and review',overview.notifications.href]);
 for(const [name,state,label,href] of rows){const row=el('tr');cell(row).append(el('span',name,'connection-name'));cell(row).append(el('p',state));if(href)cell(row).append(link(href,label));else cell(row);body.append(row);} $('content').replaceChildren(wrap);
}
function showSetup() {
 const content=el('div',undefined,'learning');const data=githubData;if(!data){content.append(el('p','Loading GitHub connections…'));$('content').replaceChildren(content);return;}
 if(mode==='instructor')content.append(el('p',data.projects.length+' projects · '+data.projects.filter(p=>!p.repository).length+' repository links needed · '+data.projects.reduce((n,p)=>n+p.members.filter(m=>!m.github_login).length,0)+' usernames needed','muted small'));
 const intro=el('section',undefined,'prep-section');intro.append(el('p','The repository owner installs the course app on the project repository. Partners share one installation and keep separate journals.'));
 if(data.app.error)intro.append(el('p',data.app.error,'error'));
 if(data.app.configured)intro.append(link(data.app.install_url,'Install on your project repository','button'));
 else if(data.can_register){const register=el('button','Register course app');register.addEventListener('click',async()=>{register.disabled=true;try{const result=await api('github/registration','POST');location.assign(result.url);}catch(error){say(error.message,true);register.disabled=false;}});intro.append(register);}
 else intro.append(el('p','John is finishing the course app setup.','muted'));
 intro.append(el('p',undefined,'small'));intro.lastChild.append(link(data.guide_url,'Setup instructions'));content.append(intro);
 for(const project of data.projects){const card=el('section',undefined,'prep-section');card.append(el('h2',project.project));if(project.repository)card.append(link('https://github.com/'+project.repository,project.repository));
  const ready=project.installed && project.issues_enabled;card.append(el('p',ready?'Connected · read-only project access':project.error || 'Needs a connection',ready?'':'muted'));
  if(project.checked_at)card.append(el('p','Checked '+date(project.checked_at,true)+' Eastern','muted small'));
  const logins=el('ul');for(const member of project.members)logins.append(el('li',member.name+': '+(member.github_login?'@'+member.github_login:'GitHub username needed')));card.append(logins);
  if(project.members.some(m=>!m.github_login) || !project.repository)card.append(el('p','In your project Slack channel, send John your GitHub username and project repository link so he can confirm the connection.','small'));
  if(project.repository){const check=el('button','Check connection','secondary');check.addEventListener('click',async()=>{check.disabled=true;try{await api('github/check/'+project.project_id,'POST');githubData=await api('github');showSetup();say('');}catch(error){say(error.message,true);check.disabled=false;}});card.append(check);}
  content.append(card);
 }$('content').replaceChildren(content);
}

function render() {
 if(mode==='instructor' && !overview)return;
 if(mode!=='instructor'){if(view()==='setup' && githubData){$('title').textContent='GitHub setup';document.title='GitHub setup · ENTR';showSetup();}else showHome();return;}
 const current=view();$('course-filter').hidden=current==='setup';$('title').textContent=titles[current];document.title=titles[current]+' · ENTR';for(const item of document.querySelectorAll('[data-view]')){if(item.dataset.view===current)item.setAttribute('aria-current','page');else item.removeAttribute('aria-current');}
 if(current==='overview')showOverview();else if(current==='projects')showProjects();else if(current==='people')showPeople();else if(current==='prep')showPrep();else if(current==='checkins')showCheckins();else if(current==='setup')showSetup();else showConnections();
 $('footer').hidden=false;$('checked').textContent=['prep','checkins'].includes(current)?(learningData?.checked_at?'Posts checked '+date(learningData.checked_at,true)+' Eastern':'Waiting for the first source read.'):'Checked '+date(overview.checked_at,true)+' Eastern';
}
async function refresh() {
 if(refreshing)return;refreshing=true;$('refresh').disabled=true;
 try { if(mode==='instructor'){overview=await api('overview');if(view()==='people')people=await api('directory');if(['prep','checkins'].includes(view()))learningData=await api('learning');}else {homeData=await api('home');learningData=await api('my-learning');}if(view()==='setup')githubData=await api('github');render();say(''); } catch(error){say(error.message,true);}finally{refreshing=false;$('refresh').disabled=false;}
}
$('course-filter').addEventListener('change',render);$('refresh').addEventListener('click',refresh);
window.addEventListener('hashchange',async()=>{if(!user)return;if(view()==='setup'){try{githubData=await api('github');}catch(error){say(error.message,true);return;}}if(mode!=='instructor'){render();return;}if(['people','prep','checkins'].includes(view())){try{if(view()==='people')people=await api('directory');else learningData=await api('learning');}catch(error){say(error.message,true);return;}}render();});
$('logout').addEventListener('click',async()=>{try{await api('logout','POST');location.assign(base+'/');}catch(error){say(error.message,true);}});
(async()=>{const session=await api('session');user=session.user;if(!user){$('login').hidden=false;if(!session.slack_enabled){$('sign-in').hidden=true;say('Slack sign-in is not connected.');}return;}
 for(const item of document.querySelectorAll('[data-view=setup]'))item.hidden=!user.grants.some(g=>g.course==='5000' && g.role==='instructor');
 $('logout').hidden=false;$('instructor-link').hidden=!user.grants.some(g=>g.role==='instructor');
 if(mode==='instructor'){ $('sidebar').hidden=false;$('controls').hidden=false;for(const grant of user.grants.filter(g=>g.role==='instructor')){const option=el('option',`ENTR ${grant.course} · ${grant.section==='115'?'1:15':grant.section==='1135'?'11:35':'2:55'}`);option.value=`${grant.course}:${grant.section}`;$('course-filter').append(option);}}
 await refresh();setInterval(()=>{if(!document.hidden && !document.activeElement.closest('input') && !document.querySelector('.learning details[open]'))refresh();},60000);
})().catch(error=>say(error.message,true));
