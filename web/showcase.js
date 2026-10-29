'use strict';
const profileLabels={name:'Current name',tagline:'Tagline',logo:'Logo',live_url:'Live link',tech:'Tech used',features:'Highlights',screenshots:'Screenshots'};
function projectName(p){return p.showcase?.name||p.name;}
function mediaUrl(p,m){return base+'/api/projects/'+encodeURIComponent(p.id)+'/media/'+m.asset_id;}
function profileImage(p,m,cls){const img=el('img',undefined,cls);img.src=mediaUrl(p,m);img.alt=m.alt;img.loading='lazy';img.addEventListener('error',()=>{const text=el('span','Image unavailable','fine');img.replaceWith(text);},{once:true});return img;}
function renderShowcase(p){
 const host=$('project-showcase');host.replaceChildren();const s=p.showcase;
 if(!s){if(canEdit()){const button=el('button','Add project profile','secondary');button.onclick=()=>editProfile(p);host.append(button);}return;}
 const section=el('section',undefined,'showcase');section.setAttribute('aria-label','Product profile');
 const intro=el('div',undefined,'showcase-intro');if(s.logo)intro.append(profileImage(p,s.logo,'project-logo'));
 const copy=el('div');if(s.tagline)copy.append(el('p',s.tagline,'project-tagline'));if(s.name&&s.name!==p.name)copy.append(el('p','Course record: '+p.name,'fine'));
 const live=link(s.live_url,'Open product ↗','product-link');if(live)copy.append(live);intro.append(copy);section.append(intro);
 const columns=el('div',undefined,'showcase-facts');
 if(s.features.length){const highlights=el('div');highlights.append(el('h2','Highlights'));const list=el('ul');for(const f of s.features)list.append(el('li',f));highlights.append(list);columns.append(highlights);}
 if(s.tech.length){const tech=el('div');tech.append(el('h2','Built with'),el('p',s.tech.join(' · ')));columns.append(tech);}section.append(columns);
 if(s.screenshots.length){const gallery=el('div',undefined,'project-gallery');gallery.setAttribute('aria-label','Product screenshots');for(const shot of s.screenshots){const figure=el('figure'),a=el('a');a.href=mediaUrl(p,shot);a.target='_blank';a.rel='noopener';a.append(profileImage(p,shot,'product-screenshot'));figure.append(a,el('figcaption',shot.alt));gallery.append(figure);}section.append(gallery);}
 if(s.notes)section.append(el('p',s.notes,'profile-notes'));
 const source=el('details',undefined,'profile-sources');source.append(el('summary','Sources and remaining details'));
 const links=el('div',undefined,'profile-source-links');for(const item of s.sources){const a=link(item.url,item.label);if(a)links.append(a);}source.append(links);
 source.append(el('p','Updated '+dateTime(p.showcase_updated_at)+'. Features reflect the linked reports; links have not been certified as working.','fine'));
 if(s.missing.length){source.append(el('p','Requested: '+s.missing.map(k=>profileLabels[k]).join(', ')+'.','fine'));const request=link(s.request_url,'Reply in Slack');if(request)source.append(request);}
 if(canEdit()&&!s.shared)source.append(el('p','This profile is visible only to the instructor.','fine'));section.append(source);
 if(canEdit()){const button=el('button','Edit profile','secondary');button.onclick=()=>editProfile(p);section.append(button);}host.append(section);
}
function editProfile(p){
 editing=p;
 const s=structuredClone(p.showcase||{name:p.name,tagline:'',live_url:'',tech:[],features:[],logo:null,screenshots:[],sources:[],notes:'',missing:[],request_url:'',shared:false});
 const dialog=el('dialog',undefined,'profile-editor'),form=el('form'),title=el('h2','Edit '+projectName(p)),inputs={};
 dialog.setAttribute('aria-label','Edit project profile');form.append(title);
 function field(key,label,value,multi=false){const id='profile-'+key,l=el('label',label),input=el(multi?'textarea':'input');l.htmlFor=id;input.id=id;input.value=value;inputs[key]=input;form.append(l,input);return input;}
 field('name','Current product / company name',s.name).maxLength=160;field('tagline','Tagline',s.tagline).maxLength=500;field('live_url','Live project link',s.live_url).type='url';
 field('tech','Tech used — one item per line',s.tech.join('\n'),true);field('features','3–5 highlights — one per line',s.features.join('\n'),true);
 field('notes','Context or limitations',s.notes,true).maxLength=2000;
 field('sources','Source links — one per line',s.sources.map(x=>x.url).join('\n'),true);
 field('request_url','Slack request thread',s.request_url).type='url';
 const logo=field('logo','Replace logo','');logo.type='file';logo.accept='image/png,image/jpeg,image/webp';
 const screenshots=field('screenshots','Add screenshots (up to 5 total)','');screenshots.type='file';screenshots.multiple=true;screenshots.accept=logo.accept;
 const media=el('div');function mediaList(){media.replaceChildren();const all=[...(s.logo?[['logo',s.logo]]:[]),...s.screenshots.map((m,i)=>[i,m])];for(const [key,m] of all){const row=el('div',undefined,'profile-media-row'),caption=el('input');caption.value=m.alt;caption.setAttribute('aria-label','Image description');caption.maxLength=400;caption.oninput=()=>m.alt=caption.value;const remove=el('button','Remove','secondary');remove.type='button';remove.onclick=()=>{if(key==='logo')s.logo=null;else s.screenshots.splice(key,1);mediaList();};row.append(caption,remove);media.append(row);}}mediaList();form.append(media);
 const missing=el('fieldset');missing.append(el('legend','Details still requested'));const checks={};for(const [key,label] of Object.entries(profileLabels)){const l=el('label'),c=el('input');c.type='checkbox';c.checked=s.missing.includes(key);checks[key]=c;l.append(c,document.createTextNode(' '+label));missing.append(l);}form.append(missing);
 const share=el('label'),shared=el('input');shared.type='checkbox';shared.checked=s.shared;share.append(shared,document.createTextNode(' Share with the course roster'));form.append(share);
 const error=el('p',undefined,'error');error.setAttribute('role','alert');const controls=el('div',undefined,'profile-actions'),cancel=el('button','Cancel','secondary'),save=el('button','Save profile');cancel.type='button';cancel.onclick=()=>dialog.close();save.type='submit';controls.append(cancel,save);form.append(error,controls);dialog.append(form);document.body.append(dialog);
 dialog.addEventListener('close',()=>{editing=null;dialog.remove();},{once:true});
 async function upload(file,alt,source){const r=await fetch(base+'/api/projects/'+encodeURIComponent(p.id)+'/media',{method:'POST',headers:{'X-CSRF-Token':user.csrf,'Content-Type':file.type},body:file});const data=await r.json();if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'Image upload failed');return {asset_id:data.asset_id,alt,source_url:source};}
 form.onsubmit=async e=>{e.preventDefault();save.disabled=true;error.textContent='';try{
  const lines=k=>inputs[k].value.split('\n').map(x=>x.trim()).filter(Boolean);const sources=lines('sources');if(!sources.length)throw new Error('Add the Slack or presentation source for this profile.');
  if(s.screenshots.length+screenshots.files.length>5)throw new Error('Choose up to five screenshots in total.');
  if(logo.files.length)s.logo=await upload(logo.files[0],inputs.name.value+' logo',sources[0]);
  for(const file of screenshots.files)s.screenshots.push(await upload(file,file.name.replace(/\.[^.]+$/,''),sources[0]));logo.value='';screenshots.value='';mediaList();
  const profile={...s,shared:shared.checked,name:inputs.name.value,tagline:inputs.tagline.value,live_url:inputs.live_url.value,tech:lines('tech'),features:lines('features'),notes:inputs.notes.value,sources:sources.map(url=>s.sources.find(x=>x.url===url)||{url,label:'Source'}),missing:Object.keys(checks).filter(k=>checks[k].checked),request_url:inputs.request_url.value};
  await api('projects/'+encodeURIComponent(p.id)+'/profile','PUT',{profile,expected_revision:p.showcase_revision});dialog.close();await refresh(true);say('Project profile saved.');
 }catch(e){error.textContent=e.message;}finally{save.disabled=false;}};
 dialog.showModal();inputs.name.focus();
}
