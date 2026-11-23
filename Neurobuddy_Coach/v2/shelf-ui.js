/* Coach Atlas central repository. No standalone Repository/EEG Collection tab. */
window.NeurobuddyShelf=(()=>{
 'use strict';
 const $=id=>document.getElementById(id);
 const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
 const tasks={oddball:'Oddball',sleep:'Sleep',motor:'Motor-imagery',unspecified:'Unspecified'};
 const suffix=(n,exts)=>exts.some(s=>String(n||'').toLowerCase().endsWith(s));
 const sig=['.set','.edf','.bdf','.vhdr','.fif','.fif.gz'];
 const previewable=name=>{const lower=String(name||'').toLowerCase();return ['readme','changes','license','citation'].includes(lower)||['.tsv','.csv','.txt','.json','.vhdr','.vmrk','.md'].some(ext=>lower.endsWith(ext));};
 const baseName=n=>{const s=String(n||'');const i=Math.max(s.lastIndexOf('/'),s.lastIndexOf('\\'));return i>=0?s.slice(i+1):s;};
 const fmtBytes=n=>{const v=Number(n||0);if(v>=1073741824)return (v/1073741824).toFixed(2)+' GB';if(v>=1048576)return (v/1048576).toFixed(1)+' MB';if(v>=1024)return Math.round(v/1024)+' KB';return v+' B';};
 const state={selectedShelfId:null,editing:null,importShelfId:null,importAthleteId:null,importSlot:'signal',dataset:null,expanded:new Set(),treeCache:new Map(),loading:false,uploading:false,selectedFiles:[],explorer:{history:[{tree:null,path:'',name:'OpenNeuro'}],index:0,selected:null,error:'',jobId:null,poll:null,review:null,previewToken:0,motorKey:null,motorFor:null,motorMap:{},correspondKey:null,correspondFor:null,correspondMap:{}}};
 let host;
 const backend=(path,opts={})=>host.api(path,opts);
 const json=(method,data)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const getTeams=()=>host.state.library.teams||[];
 const getShelf=id=>{for(const t of getTeams())for(const a of t.athletes)for(const s of (a.shelves||[]))if(s.id===id)return {team:t,athlete:a,shelf:s};return null;};
 const getAthlete=id=>{for(const t of getTeams())for(const a of t.athletes)if(a.id===id)return {team:t,athlete:a};return null;};
 function reqInfo(type){return {
  oddball:{message:'Required for P300: target/standard stimulus markers, embedded or supported events.tsv/.json. Response events support reaction times.',events:true,eventsLabel:'Stimulus events / task object',eventsHelp:'Add event.tsv, event.json or an equivalent supported annotation file when markers are not embedded'},
  sleep:{message:'Sleep EEG signal required. Scored sleep-stage annotations are recommended; optional YASA staging may work without them.',events:true,eventsLabel:'Sleep stages / annotations',eventsHelp:'Optional staged sleep annotations (.tsv, .csv, .json, .txt) when not embedded'},
  motor:{message:'Required for ERD/ERS: motor cue events and suitable C3/C4 channels. Physical exertion is not calculated.',events:true,eventsLabel:'Motor cue / event object',eventsHelp:'Add motor cue annotations when not embedded in the signal'},
  unspecified:{message:'Supported EEG signal required. General statistics work without task markers.',events:false,eventsLabel:'Events (optional)',eventsHelp:'No task object required'}
 }[type]||{message:'Select a task',events:false};}
 function updateRequirements(){const type=$('test-type').value,kind=$('file-type').value;
  $('type-requirements').innerHTML=`<strong>${esc(tasks[type])} · ${kind==='baseline'?'Baseline':'Testing'}</strong><span>${esc(reqInfo(type).message)}</span>`;}
 function statusPill(s){return s.ready?'<span class="shelf-badge ready">● Signal uploaded</span>':'<span class="shelf-badge">○ Awaiting signal</span>';}
 function slotMarkup(s,kind,label,desc,accept){
  const found=(s.files||[]).filter(f=>kind==='signal'?suffix(f.name,sig):kind==='companion'?suffix(f.name,['.fdt','.eeg','.vmrk']):suffix(f.name,['.csv','.tsv','.json','.txt']));
  return `<div class="file-slot"><div class="file-slot-head"><strong>${esc(label)}</strong><span class="slot-desc">${esc(desc||'')}</span></div>
   <div class="slot-existing">${found.map(f=>`<span class="slot-file" title="${esc(f.name)}">▤ ${esc(baseName(f.name))} <button type="button" data-delete-file="${esc(f.id)}" data-shelf-id="${esc(s.id)}" title="Remove file" aria-label="Remove ${esc(f.name)}">×</button></span>`).join('')||'<span class="missing-file">No file added</span>'}</div>
   <button type="button" class="slot-add" data-upload-slot="${kind}" data-shelf-id="${esc(s.id)}" data-accept="${esc(accept)}" ${kind==='signal'&&s.ready?'disabled title="Remove the existing signal before replacement"':''}>+ ${kind==='signal'?'Add EEG':kind==='events'?'Add object / events':'Add companion'}</button></div>`;
 }
 function renderShelf(s,idx){
  const primaryPath=s.files.find(f=>suffix(f.name,sig))?.name||'';
  const primary=primaryPath?baseName(primaryPath):'No EEG signal yet';
  const info=reqInfo(s.task_type);
  const sourceLine=s.source&&s.source.dataset_id?`<p class="shelf-source">OpenNeuro ${esc(s.source.dataset_id)} · snapshot ${esc(s.source.snapshot||'')} · detected ${esc(s.source.task_detected||'unspecified')}${s.source.validation?` · ${esc(s.source.validation)}`:''}</p>`:'';
  const signalSlots=slotMarkup(s,'signal','EEG Signal (.set / .edf / .fif …)','One primary signal per shelf','.set,.edf,.bdf,.vhdr,.fif,.gz');
  let companions='';
  if(primary.toLowerCase().endsWith('.set'))companions=slotMarkup(s,'companion','.fdt companion','Required only if the .set references external data','.fdt');
  else if(primary.toLowerCase().endsWith('.vhdr'))companions=slotMarkup(s,'companion','BrainVision companions','Select the matching .eeg and .vmrk','.eeg,.vmrk');
  const events=info.events?slotMarkup(s,'events',info.eventsLabel,info.eventsHelp,'.tsv,.csv,.json,.txt'):'';
  return `<article class="eeg-shelf ${state.selectedShelfId===s.id?'selected':''}" data-shelf="${esc(s.id)}">
    <div class="shelf-header"><div class="shelf-id"><span class="shelf-square">${s.classification==='baseline'?'B':'T'}${idx+1}</span><div><strong>${esc(s.classification==='baseline'?'Baseline EEG':'Testing EEG')} Shelf ${idx+1}</strong><small>${esc(tasks[s.task_type]||s.task_type)} · ${esc(primary)}</small></div></div>
      <div class="shelf-head-actions">${statusPill(s)}<button type="button" class="secondary-button small-btn" data-select-shelf="${esc(s.id)}" title="Open shelf file slots">${state.selectedShelfId===s.id?'Close':'Open'}</button><button type="button" class="icon-button" data-select-shelf="${esc(s.id)}" title="Set shelf selectors">⚙</button><button type="button" class="danger-icon" data-delete-shelf="${esc(s.id)}" title="Delete EEG shelf">×</button></div></div>
    <div class="shelf-body">${sourceLine}<div class="shelf-slots">${signalSlots}${companions}${events}</div><div class="shelf-foot"><button type="button" class="secondary-button small-btn" data-select-type="single" data-select-id="${esc(s.id)}" data-select-name="${esc(primary)}" ${s.ready?'draggable="true"':'disabled'}>↗ Drag / Test EEG</button></div></div>
  </article>`;
 }
 function render(){
  const teams=getTeams(),search=($('library-search').value||'').toLowerCase().trim();
  $('published-label').textContent=`${teams.length} team${teams.length===1?'':'s'} · v0.7.1`;
  let parts=[];
  for(const t of teams){
    let inn=[];
    for(const a of t.athletes){
      const shelves=a.shelves||[];
      if(search&&!`${t.name} ${a.name} ${shelves.flatMap(s=>[s.source_name,...s.files.map(f=>f.name)]).join(' ')}`.toLowerCase().includes(search))continue;
      const baseline=shelves.filter(s=>s.classification==='baseline'),testing=shelves.filter(s=>s.classification==='testing');
      const baselineTasks=[...new Set(baseline.map(s=>s.task_type))];
      const baselineMinimum=baselineTasks.length===1&&baselineTasks[0]==='oddball'?2:3;
      inn.push(`<details class="folder athlete-folder" open><summary><span>♙ ${esc(a.name)}</span><span class="small-count">${shelves.length} EEG shelves</span></summary>
       <div class="folder-inner"><div class="athlete-actions"><button class="secondary-button small-btn" type="button" draggable="true" data-select-type="athlete" data-select-id="${esc(a.id)}" data-select-name="${esc(a.name)}">↗ Drag Athlete</button><button class="secondary-button small-btn" type="button" data-add-shelf="${esc(a.id)}">+ EEG Shelf</button><button class="secondary-button small-btn" type="button" data-import-athlete="${esc(a.id)}">+ Import EEG File</button><button class="danger-icon" type="button" data-delete-athlete="${esc(a.id)}" title="Delete athlete">×</button></div>
        <div class="group-heading">BASELINE EEG · ${baseline.filter(s=>s.ready).length} / ${baselineMinimum} minimum uploaded</div>${baseline.map((s,i)=>renderShelf(s,i)).join('')||'<div class="empty-group">No baseline shelves</div>'}
        <div class="group-heading">TESTING EEG · ${testing.filter(s=>s.ready).length} uploaded</div>${testing.map((s,i)=>renderShelf(s,i)).join('')||'<div class="empty-group">No testing shelves</div>'}
        <button class="add-recording-end" type="button" data-import-athlete="${esc(a.id)}">＋ Import an EEG File <span>Downloads or Connector</span></button>
       </div></details>`);
    }
    if(search&&!inn.length&&!t.name.toLowerCase().includes(search))continue;
    parts.push(`<details class="folder team-folder" open><summary><span>▱ ${esc(t.name)}</span><span class="small-count">${t.athletes.length} athletes</span></summary><div class="folder-inner"><div class="team-actions"><button class="secondary-button small-btn" draggable="true" data-select-type="team" data-select-id="${esc(t.id)}" data-select-name="${esc(t.name)}" type="button">↗ Drag Team</button><button class="secondary-button small-btn" data-add-athlete="${esc(t.id)}" type="button">+ Add Athlete</button><button class="danger-icon" data-delete-team="${esc(t.id)}" title="Delete team" type="button">×</button></div>${inn.join('')||'<div class="empty-group">Click + Add Athlete to create three Baseline shelves and one Testing shelf.</div>'}</div></details>`);
  }
  $('library-tree').innerHTML=parts.join('')||`<div class="library-receiver"><span class="receiver-icon">▱</span><strong>${search?'No matching results':'Your EEG repository starts here'}</strong><p>${search?'Try a different search.':'Create a Team, add an Athlete and populate recording shelves.'}</p><small>Oddball needs two baseline shelves + one testing shelf. Sleep, motor, and unspecified stay at three + one.</small></div>`;
  updateRequirements();
 }
 async function refresh(){host.state.library=await backend('/v2/shelf-library');render();host.renderTarget();}
 function openName(type,parent){state.editing={type,parent};$('name-dialog-title').textContent=type==='team'?'Create Team':'Add Athlete';$('name-value').value='';$('name-dialog').showModal();$('name-value').focus();}
 async function submitName(e){e.preventDefault();const name=$('name-value').value.trim();if(!name)return;
  const context=state.editing;if(!context)return;
  const route=context.type==='team'?'/v2/shelf-teams':`/v2/shelf-teams/${encodeURIComponent(context.parent)}/athletes?task_type=${encodeURIComponent($('test-type').value)}`;
  const created=await backend(route,json('POST',{name}));$('name-dialog').close();await refresh();
  if(context.type==='athlete'){
    const row=getAthlete(created.id),first=row?.athlete.shelves?.[0];
    if(first){state.selectedShelfId=first.id;$('test-type').value=first.task_type;$('file-type').value=first.classification;render();}
  }
  host.notify(`${context.type==='team'?'Team':'Athlete'} created.`, 'success');}
 async function confirmAndDelete(path,description){if(!confirm(`Delete ${description}? This also deletes stored EEG files. Existing reports will be retained.`))return;await backend(path,{method:'DELETE'});if(host.state.target)host.state.target=null;state.selectedShelfId=null;await refresh();host.notify(`${description} deleted.`, 'success');}
 async function createShelf(aid){const payload={task_type:$('test-type').value,classification:$('file-type').value};const r=await backend(`/v2/shelf-athletes/${encodeURIComponent(aid)}/shelves`,json('POST',payload));await refresh();state.selectedShelfId=r.id;return r.id;}
 function selectShelf(id){const rec=getShelf(id);if(!rec)return;
  if(state.selectedShelfId===id){state.selectedShelfId=null;render();return;}
  state.selectedShelfId=id;$('test-type').value=rec.shelf.task_type;$('file-type').value=rec.shelf.classification;render();host.notify(`Selected ${rec.athlete.name} / ${rec.shelf.classification} EEG shelf.`);}
 async function changeSelectors(){updateRequirements();if(!state.selectedShelfId)return;
  const current=getShelf(state.selectedShelfId);if(!current)return;
  await backend(`/v2/shelves/${encodeURIComponent(state.selectedShelfId)}`,json('PATCH',{task_type:$('test-type').value,classification:$('file-type').value}));await refresh();}
 function setImportMessage(message, kind='normal'){
  const el=$('import-status');el.textContent=message;el.className='import-status'+(kind==='error'?' error':kind==='success'?' success':'');el.hidden=!message;
 }
 function showLocalImport(){
  $('import-actions').hidden=true;$('local-import').hidden=false;$('openneuro-import').hidden=true;
 }
 function openImport(shelfId,athleteId,slot='signal',autoLocal=false){
  state.importShelfId=shelfId;state.importAthleteId=athleteId;state.importSlot=slot;
  state.selectedFiles=[];state.uploading=false;
  const s=shelfId?getShelf(shelfId):null;
  $('import-title').textContent=slot==='signal'?'Import EEG Signal':slot==='companion'?'Add EEG Companion':'Add Events / Annotations';
  $('import-hint').textContent=s?`${s.athlete.name} · ${tasks[s.shelf.task_type]} · ${s.shelf.classification}`:'A new shelf will be created when you select a source.';
  $('import-actions').hidden=Boolean(autoLocal);$('local-import').hidden=!autoLocal;
  $('openneuro-import').hidden=true;$('openneuro-result').innerHTML='';
  if($('openneuro-explorer'))$('openneuro-explorer').hidden=true;
  if($('openneuro-setup'))$('openneuro-setup').hidden=false;
  if($('import-progress')){$('import-progress').hidden=true;$('import-progress').innerHTML='';}
  $('native-file-picker').value='';$('retry-upload').hidden=true;setImportMessage('');
  $('import-dialog').showModal();
  if(autoLocal){showLocalImport();browseLocal();}
 }
 function browseLocal(){
  if(state.uploading)return;
  const input=$('native-file-picker');input.value='';
  input.multiple=state.importSlot!=='signal';
  input.accept=state.importSlot==='signal'?'.set,.edf,.bdf,.vhdr,.fif,.fif.gz':state.importSlot==='companion'?'.fdt,.eeg,.vmrk':'.tsv,.csv,.json,.txt';
  state.selectedFiles=[];$('retry-upload').hidden=true;setImportMessage('');
  // Always use ONE native file-picker mechanism. File System Access fallbacks
  // could open a second picker or silently lose the first selection on Safari.
  // This click is synchronous with the user's Downloads/Choose File action.
  input.click();
 }
 async function uploadFiles(files){
  if(state.uploading||!files.length)return;
  state.selectedFiles=files;
  state.uploading=true;$('retry-upload').hidden=true;$('browse-local').disabled=true;
  setImportMessage(`Uploading ${files.map(f=>f.name).join(', ')}…`);
  let uploaded=false;
  try{
    let id=state.importShelfId;
    if(!id){id=await createShelf(state.importAthleteId);state.importShelfId=id;}
    const form=new FormData();form.append('slot',state.importSlot);
    for(const f of files)form.append('uploads',f,f.name);
    await backend(`/v2/shelves/${encodeURIComponent(id)}/files`,{method:'POST',body:form});
    uploaded=true;
    await refresh();
    $('import-dialog').close();
    state.selectedFiles=[];
    host.notify(`${files.map(f=>f.name).join(', ')} saved in EEG shelf.`, 'success');
  }catch(error){
    const message=uploaded?'File saved, but the library could not refresh. Refresh the page to see it.':error.message;
    setImportMessage(message,'error');
    // Allow the SAME chosen File objects to be uploaded again without invoking
    // the system picker. Do not retry if the upload itself succeeded.
    $('retry-upload').hidden=uploaded||!state.selectedFiles.length;
  }finally{
    state.uploading=false;$('browse-local').disabled=false;
  }
 }
 function location(){return state.explorer.history[state.explorer.index];}
 function childPath(parent,name){return parent?`${parent}/${name}`:name;}
 function extOf(name){const lower=name.toLowerCase();if(lower.endsWith('.fif.gz'))return '.fif.gz';const i=lower.lastIndexOf('.');return i>=0?lower.slice(i):'';}
 async function datasetLoad(){
  const input=$('dataset-id').value.trim();
  const match=input.match(/^(?:https?:\/\/openneuro\.org\/datasets\/)?(ds\d{6,8})(?:\/.*)?$/i);
  if(!match)throw new Error('Enter a valid public OpenNeuro dataset ID, such as ds003061, or a dataset URL.');
  $('openneuro-setup').hidden=true;$('openneuro-explorer').hidden=false;$('import-dialog').classList.add('explorer-open');
  setExplorerStatus('Loading published dataset metadata…');
  let dataset;
  try{dataset=await backend(`/v2/openneuro/${encodeURIComponent(match[1].toLowerCase())}`);}
  catch(error){$('openneuro-setup').hidden=false;$('openneuro-explorer').hidden=true;$('import-dialog').classList.remove('explorer-open');throw error;}
  state.dataset=dataset;state.treeCache=new Map();state.expanded=new Set();state.explorer.selected=null;state.explorer.review=null;
  state.explorer.motorKey=null;state.explorer.motorFor=null;state.explorer.motorMap={};
  state.explorer.correspondKey=null;state.explorer.correspondFor=null;state.explorer.correspondMap={};
  state.explorer.history=[{tree:null,path:'',name:dataset.id}];state.explorer.index=0;
  await loadTree(null,'');renderExplorer();setExplorerStatus('');
 }
 async function loadTree(tree,key){
  const ds=state.dataset;if(!ds)return;
  if(state.treeCache.has(key))return;
  setExplorerStatus('Loading folder…');
  const url=`/v2/openneuro/${encodeURIComponent(ds.id)}/tree?tag=${encodeURIComponent(ds.tag)}`+(tree?`&tree=${encodeURIComponent(tree)}`:'');
  try{const data=await backend(url);state.treeCache.set(key,data.files||[]);}
  catch(error){setExplorerStatus(error.message,'error');throw error;}
 }
 function setExplorerStatus(message,kind=''){const el=$('explorer-status');el.textContent=message||'';el.hidden=!message;el.className='helper'+(kind==='error'?' import-status error':'');$('explorer-retry').hidden=kind!=='error';}
 function renderExplorer(){
  const ds=state.dataset;if(!ds)return;
  const here=location();
  $('openneuro-summary').innerHTML=`<strong>${esc(ds.name||ds.id)}</strong><small>${esc(ds.id)} · published snapshot ${esc(ds.tag)}${ds.description?` · ${esc(ds.description)}`:''}${ds.doi?` · ${esc(ds.doi)}`:''}</small>`;
  const crumbs=[{path:'',label:ds.id}];
  if(here.path)here.path.split('/').forEach((part,i,all)=>crumbs.push({path:all.slice(0,i+1).join('/'),label:part}));
  $('explorer-crumbs').innerHTML=crumbs.map((c,i)=>`${i?'<span aria-hidden="true">/</span>':''}<button type="button" data-crumb="${esc(c.path)}">${esc(c.label)}</button>`).join('');
  $('explorer-back').disabled=state.explorer.index<=0;
  $('explorer-forward').disabled=state.explorer.index>=state.explorer.history.length-1;
  const pane=$('openneuro-result');const scroll=pane.scrollTop;
  const files=state.treeCache.get(here.path)||[];
  const rows=renderNodes(files,here.path,0);
  const noun=files.length===1?'item':'items';
  pane.innerHTML=`<p class="folder-count">${files.length} ${noun} in this folder</p><div class="remote-list">${rows||'<p class="helper">This folder is empty.</p>'}</div>`;
  pane.scrollTop=scroll;
  renderPreview();
  const labelKey=`${ds.id}|${ds.tag}|${here.path}`;
  if(folderLooksMotor(files)&&state.explorer.motorFor!==labelKey&&state.explorer.motorKey!==labelKey)void loadMotorLabels(here.path,labelKey);
  const sleepOpen=($('test-type')&&$('test-type').value)==='sleep';
  const hasSet=(files||[]).some(file=>String(file.filename||'').toLowerCase().endsWith('.set'));
  if(sleepOpen&&hasSet&&state.explorer.correspondFor!==labelKey&&state.explorer.correspondKey!==labelKey)void loadCorrespondence(here.path,labelKey);
 }
 function folderLooksMotor(files){
  return (files||[]).some(file=>/(?:^|_)task-(?:motion|motor|imagery|eegmmidb|motorimagery|motorloc|execution)(?:_|\.|$)/i.test(file.filename||''));
 }
 async function loadMotorLabels(folderPath,key){
  const ds=state.dataset;if(!ds)return;
  state.explorer.motorKey=key;
  try{
    const data=await backend(`/v2/openneuro/${encodeURIComponent(ds.id)}/motor-labels?tag=${encodeURIComponent(ds.tag)}&path=${encodeURIComponent(folderPath)}`);
    if(state.explorer.motorKey!==key)return;
    const map={};
    for(const item of data.labels||[])if(item&&item.path&&item.label)map[item.path]=item.label;
    state.explorer.motorFor=key;state.explorer.motorMap=map;renderExplorer();
  }catch(error){if(state.explorer.motorKey===key)state.explorer.motorFor=key;}
 }
 async function loadCorrespondence(folderPath,key){
  const ds=state.dataset;if(!ds||($('test-type')&&$('test-type').value)!=='sleep')return;
  state.explorer.correspondKey=key;
  try{
    const data=await backend(`/v2/openneuro/${encodeURIComponent(ds.id)}/sleep-correspondence?tag=${encodeURIComponent(ds.tag)}&path=${encodeURIComponent(folderPath)}`);
    if(state.explorer.correspondKey!==key)return;
    const map={};
    for(const item of data.labels||[])if(item&&item.path&&item.label==='Corresponding')map[item.path]=item.label;
    state.explorer.correspondFor=key;state.explorer.correspondMap=map;renderExplorer();
  }catch(error){if(state.explorer.correspondKey===key)state.explorer.correspondFor=key;}
 }
 function renderNodes(files,parentPath,depth){
  return files.map(f=>{
    const path=childPath(parentPath,f.filename);
    const isDir=!!f.directory;
    const opened=isDir&&state.expanded.has(f.id);
    const selected=!isDir&&state.explorer.selected&&state.explorer.selected.path===path;
    const signal=!isDir&&suffix(f.filename,sig);
    const fdtShelf=!isDir&&String(f.filename||'').toLowerCase().endsWith('.fdt')?shelfMatchingSet(f.filename):null;
    const fdtReady=Boolean(fdtShelf)&&!shelfHasFile(fdtShelf,f.filename);
    const labelKey=state.dataset?`${state.dataset.id}|${state.dataset.tag}|${location().path}`:'';
    const eventsFile=!isDir&&String(f.filename||'').toLowerCase().endsWith('_events.tsv');
    const sleepOpen=($('test-type')&&$('test-type').value)==='sleep';
    const motor=eventsFile&&state.explorer.motorFor===labelKey?state.explorer.motorMap[path]:'';
    const correspond=eventsFile&&sleepOpen&&state.explorer.correspondFor===labelKey?state.explorer.correspondMap[path]:'';
    const icon=isDir?(opened?'▾':'▸'):'▤';
    const nested=opened?renderNodes(state.treeCache.get(path)||[],path,depth+1):'';
    return `<div class="remote-node ${selected?'remote-selected':''}" style="--depth:${depth}">
      <button type="button" class="remote-entry" data-path="${esc(path)}" data-id="${esc(f.id)}" data-dir="${isDir?'1':'0'}"><span class="remote-icon" data-toggle="${isDir?'1':'0'}">${icon}</span><span class="remote-name">${esc(f.filename)}</span></button>
      ${motor?`<span class="remote-download" data-motor-label="${esc(motor)}">${esc(motor)}</span>`:''}
      ${correspond?`<span class="remote-download" data-corresponding="${esc(correspond)}">${esc(correspond)}</span>`:''}
      ${signal?`<button type="button" class="remote-download" data-download="${esc(path)}">Download</button>`:''}
      ${fdtReady?`<button type="button" class="remote-download" data-save-fdt="${esc(path)}">Add .fdt</button>`:''}
      ${!isDir?`<span class="remote-ext">${esc(extOf(f.filename)||'file')}</span><span class="remote-size">${fmtBytes(f.size)}</span>`:''}
    </div>${nested}`;
  }).join('');
 }
 function fileByPath(path){
  const parent=path.includes('/')?path.slice(0,path.lastIndexOf('/')):'';
  const name=baseName(path);
  return (state.treeCache.get(parent)||[]).find(f=>f.filename===name)||null;
 }
 function renderPreview(){
  const file=state.explorer.selected;
  const box=$('explorer-preview');
  const token=++state.explorer.previewToken;
  if(!file){box.innerHTML='<p class="helper">Select a file to read it. Download saves only the EEG file you click. A TSV, or the one .fdt the .set names, is saved only when you choose to add that file.</p>';return;}
  const signal=suffix(file.filename,sig);
  const tsv=String(file.filename||'').toLowerCase().endsWith('.tsv');
  const fdt=String(file.filename||'').toLowerCase().endsWith('.fdt');
  const fdtHits=fdt?shelvesNaming(file.filename):[];
  const fdtShelf=fdt?shelfMatchingSet(file.filename):null;
  const fdtReady=Boolean(fdtShelf)&&!shelfHasFile(fdtShelf,file.filename);
  const openable=!signal&&!fdt&&previewable(file.filename);
  box.innerHTML=`<strong>${esc(file.filename)}</strong>
    <dl class="preview-meta"><div><dt>Path</dt><dd>${esc(file.path)}</dd></div><div><dt>Extension</dt><dd>${esc(extOf(file.filename)||'none')}</dd></div><div><dt>Size</dt><dd>${fmtBytes(file.size)}</dd></div><div><dt>Snapshot</dt><dd>${esc(state.dataset.tag)}</dd></div><div><dt>Storage</dt><dd>${file.annexed?'Git Annex object':'Repository file'}</dd></div><div><dt>OpenNeuro id</dt><dd>${esc((file.id||'').slice(0,12))}</dd></div></dl>
    ${signal?`<button type="button" class="primary-button" id="download-signal" data-download="${esc(file.path)}">Download</button><p class="helper">Saves only this file onto the selected shelf. Other .set files, other runs, .fdt, JSON, and TSV files are not downloaded.</p>`:''}
    ${tsv?`<button type="button" class="primary-button" id="save-tsv" data-save-tsv="${esc(file.path)}">Add this TSV to the shelf</button><p class="helper">Saves only this TSV. Reading it does not save it, and no other file is added.</p>`:''}
    ${fdtReady?`<button type="button" class="primary-button" id="save-fdt" data-save-fdt="${esc(file.path)}">Add this .fdt to the shelf</button><p class="helper">Saves only the .fdt named by the .set already on this shelf. No other file is added.</p>`:''}
    ${fdt&&fdtShelf&&!fdtReady?'<p class="helper">This .fdt is already on the shelf with the .set.</p>':''}
    ${fdt&&!fdtShelf&&fdtHits.length>1?'<p class="helper">Open the shelf that already holds this .set, then add this .fdt.</p>':''}
    ${fdt&&!fdtShelf&&fdtHits.length<=1?'<p class="helper">The .set on the shelf does not name this .fdt, so it is not added.</p>':''}
    ${openable?'<p class="helper" id="file-preview-status">Opening this file…</p><pre id="file-preview" class="file-preview"></pre>':''}`;
  if(openable)void loadPreview(file,token);
 }
 async function loadPreview(file,token){
  const ds=state.dataset;
  if(!ds)return;
  try{
    const data=await backend(`/v2/openneuro/${encodeURIComponent(ds.id)}/file?tag=${encodeURIComponent(ds.tag)}&path=${encodeURIComponent(file.path)}`);
    if(token!==state.explorer.previewToken)return;
    const pre=$('file-preview');
    if(pre)pre.textContent=data.text||'';
    const status=$('file-preview-status');
    if(status)status.textContent=data.truncated?'Opened the start of this file. Nothing was saved.':'Opened for reading. Nothing was saved until you choose Add this TSV.';
  }catch(error){
    if(token!==state.explorer.previewToken)return;
    const status=$('file-preview-status');
    if(status){status.textContent=error.message||'Could not open this file.';status.className='helper import-status error';}
  }
 }
 async function openFolder(file,path,{recordHistory=true}={}){
  if(!state.treeCache.has(path))await loadTree(file.id,path);
  if(recordHistory){
    const next={tree:file.id,path,name:file.filename};
    state.explorer.history=state.explorer.history.slice(0,state.explorer.index+1);
    state.explorer.history.push(next);state.explorer.index+=1;
  }
  state.expanded.add(file.id);
  setExplorerStatus('');
  renderExplorer();
 }
 async function datasetRetry(){const here=location();setExplorerStatus('Retrying…');state.treeCache.delete(here.path);await loadTree(here.tree,here.path);setExplorerStatus('');renderExplorer();}
 function importBody(path,extra={}){
  const rec=state.importShelfId?getShelf(state.importShelfId):null;
  return {dataset_id:state.dataset.id,tag:state.dataset.tag,path,task_type:$('test-type').value,classification:$('file-type').value,
    shelf_id:state.importShelfId,athlete_id:state.importAthleteId||rec?.athlete.id||null,...extra};
 }
 async function downloadSignal(path){
  if(!state.dataset)throw new Error('Load a public dataset first.');
  const file=fileByPath(path);
  state.explorer.selected=file?{...file,path}: {filename:baseName(path),path,size:0,id:'',annexed:false};
  renderPreview();
  $('import-progress').hidden=false;
  $('import-progress').innerHTML='<p class="helper">Saving only this EEG file…</p>';
  await startImport(path,{});
 }
 function shelvesNaming(fdtName){
  const lower=String(fdtName||'').toLowerCase();
  if(!lower.endsWith('.fdt'))return [];
  const wanted=lower.slice(0,-4)+'.set';
  const hits=[];
  for(const t of getTeams())for(const a of t.athletes||[])for(const s of a.shelves||[]){
    if((s.files||[]).some(f=>baseName(f.name).toLowerCase()===wanted))hits.push(s.id);
  }
  return hits;
 }
 function shelfMatchingSet(fdtName){
  const hits=shelvesNaming(fdtName);
  const preferred=state.importShelfId||state.selectedShelfId;
  if(preferred&&hits.includes(preferred))return preferred;
  return hits.length===1?hits[0]:null;
 }
 function shelfHasFile(shelfId,filename){
  const found=getShelf(shelfId);
  return (found?.shelf.files||[]).some(f=>baseName(f.name)===filename);
 }
 async function saveFdt(path){
  if(!state.dataset)throw new Error('Load a public dataset first.');
  const filename=baseName(path);
  const shelfId=shelfMatchingSet(filename);
  if(!shelfId)throw new Error('Download the .set onto a shelf first, then add the .fdt that set names.');
  $('import-progress').hidden=false;
  $('import-progress').innerHTML=`<p class="helper">Saving only ${esc(filename)}…</p>`;
  const saved=await backend('/v2/openneuro/save-fdt',json('POST',{dataset_id:state.dataset.id,tag:state.dataset.tag,path,shelf_id:shelfId}));
  await refresh();
  state.importShelfId=saved.shelf_id;
  state.selectedShelfId=saved.shelf_id;
  render();
  renderPreview();
  host.notify(`Saved only ${filename} onto the shelf.`,'success');
 }
 async function saveTsv(path){
  if(!state.dataset)throw new Error('Load a public dataset first.');
  const shelfId=state.importShelfId||state.selectedShelfId;
  if(!shelfId)throw new Error('Download the .set onto a shelf first, then choose one TSV.');
  const saved=await backend('/v2/openneuro/save-tsv',json('POST',{dataset_id:state.dataset.id,tag:state.dataset.tag,path,shelf_id:shelfId}));
  await refresh();
  state.selectedShelfId=saved.shelf_id;
  render();
  host.notify(`Saved only ${baseName(path)} onto the shelf.`,'success');
 }
 function renderManifest(manifest){
  const files=(manifest.files||[]).filter(f=>f.selected||f.category==='required'||f.category==='unrelated').slice(0,18);
  const rows=files.map(f=>`<li class="${esc(f.category)}"><span>${f.selected?'•':'○'} ${esc(f.category)}</span><strong>${esc(f.filename)}</strong><small>${esc(f.reason||'')}</small></li>`).join('');
  const review=manifest.status==='needs_review'?`<div class="review-actions"><button type="button" class="primary-button" id="import-anyway">Import for shared EEG analysis</button>${['oddball','motor','sleep'].includes(manifest.task_detected)?`<button type="button" class="secondary-button" id="import-adopt">Use detected ${esc(manifest.task_detected)} and import</button>`:''}</div>`:'';
  const blocked=manifest.status==='blocked'?'<p class="import-status error">Import is blocked until the missing required file is available. Nothing was saved to the shelf.</p>':'';
  $('import-progress').hidden=false;
  $('import-progress').innerHTML=`<h3>Dependency check · ${esc(manifest.status)}</h3><p>${esc(manifest.summary||'')}</p><ul class="dependency-list">${rows}</ul>${(manifest.warnings||[]).map(w=>`<p class="helper">${esc(w)}</p>`).join('')}${(manifest.conflicts||[]).map(w=>`<p class="import-status error">${esc(w)}</p>`).join('')}${review}${blocked}`;
 }
 async function startImport(path,extra){
  const created=await backend('/v2/openneuro/import-recording',json('POST',importBody(path,extra)));
  state.explorer.jobId=created.id;
  await pollJob();
  if(state.explorer.poll)clearInterval(state.explorer.poll);
  state.explorer.poll=setInterval(()=>host.safe(pollJob),700);
 }
 async function pollJob(){
  const id=state.explorer.jobId;if(!id)return;
  const job=await backend(`/v2/import-jobs/${encodeURIComponent(id)}`);
  renderJob(job);
  if(['completed','failed','cancelled','interrupted'].includes(job.status)){
    if(state.explorer.poll){clearInterval(state.explorer.poll);state.explorer.poll=null;}
    if(job.status==='completed'){await refresh();if(job.shelf_id){state.importShelfId=job.shelf_id;state.selectedShelfId=job.shelf_id;render();}host.notify('Saved only this EEG file onto the shelf.','success');}
  }
 }
 function renderJob(job){
  const progress=job.progress||{};
  const percent=progress.percent===null||progress.percent===undefined?'size still unknown':`${progress.percent}%`;
  const bytes=progress.bytes_total?`${fmtBytes(progress.bytes_done)} / ${fmtBytes(progress.bytes_total)}`:'';
  const athlete=job.athlete_name||'selected athlete';
  const files=(progress.files||[]).map(f=>{const mark=f.status==='done'?'✓':f.status==='downloading'?'…':'○';return `<li><span>${mark}</span><strong>${esc(f.filename)}</strong><small>${esc(f.role)} · ${esc(f.status)}${f.size?` · ${fmtBytes(f.bytes||0)} / ${fmtBytes(f.size)}`:''}</small><em>${esc(f.reason||'')}</em></li>`;}).join('');
  const steps=`<li>${progress.validated?'✓':'○'} Recording validated</li><li>${progress.saved?'✓':'○'} Saved to EEG shelf</li>`;
  const controls=job.status==='running'||job.status==='queued'?'<button type="button" class="secondary-button" id="cancel-import">Cancel import</button>':(job.status==='failed'||job.status==='cancelled'||job.status==='interrupted'?'<button type="button" class="secondary-button" id="retry-import">Retry import</button>':'');
  $('import-progress').hidden=false;
  $('import-progress').innerHTML=`<h3>Importing EEG recording</h3><p>Dataset ${esc(job.dataset_id)} · snapshot ${esc(job.snapshot)} · ${esc(athlete)} · ${esc(job.classification)} · ${esc(job.task_type)}</p><p class="progress-meter"><span style="width:${Math.max(0,Math.min(100,Number(progress.percent)||0))}%"></span></p><p>${esc(progress.phase||job.status)} · ${esc(percent)} ${esc(bytes)}</p><ul class="import-checklist">${files}${steps}</ul>${job.error?`<p class="import-status error">${esc(job.error)}</p>`:''}${controls}`;
 }
 async function onExplorerClick(event){
  const download=event.target.closest('[data-download]');
  if(download){await downloadSignal(download.dataset.download);return;}
  const saveTsvButton=event.target.closest('[data-save-tsv]');
  if(saveTsvButton){await saveTsv(saveTsvButton.dataset.saveTsv);return;}
  const saveFdtButton=event.target.closest('[data-save-fdt]');
  if(saveFdtButton){await saveFdt(saveFdtButton.dataset.saveFdt);return;}
  const crumb=event.target.closest('[data-crumb]');
  if(crumb){
    const path=crumb.dataset.crumb;
    const known=state.explorer.history.find(item=>item.path===path);
    state.explorer.history=state.explorer.history.slice(0,state.explorer.index+1);
    state.explorer.history.push(known||{tree:null,path,name:baseName(path)||state.dataset.id});
    state.explorer.index+=1;
    if(!state.treeCache.has(path)){
      const parent=path.includes('/')?path.slice(0,path.lastIndexOf('/')):'';
      const file=fileByPath(path);
      if(!file)throw new Error('That folder is not in the loaded snapshot.');
      await loadTree(file.id,path);
    }
    renderExplorer();return;
  }
  const button=event.target.closest('.remote-entry');
  if(!button)return;
  const path=button.dataset.path;
  const file=fileByPath(path);
  if(!file)return;
  const toggle=event.target.closest('[data-toggle="1"]');
  if(button.dataset.dir==='1' && toggle){
    if(state.expanded.has(file.id))state.expanded.delete(file.id);
    else{state.expanded.add(file.id);if(!state.treeCache.has(path))await loadTree(file.id,path);}
    renderExplorer();return;
  }
  if(button.dataset.dir==='1'){await openFolder(file,path);return;}
  state.explorer.selected={...file,path};renderExplorer();
 }
 function install(config){host=config;
  $('add-team').addEventListener('click',()=>openName('team',null));
  $('name-form').addEventListener('submit',e=>host.safe(()=>submitName(e)));
  for(const id of ['name-cancel','name-cancel-bottom'])$(id).addEventListener('click',()=>$('name-dialog').close());
  $('test-type').addEventListener('change',()=>host.safe(changeSelectors));$('file-type').addEventListener('change',()=>host.safe(changeSelectors));
  $('test-type').addEventListener('change',()=>{state.explorer.correspondKey=null;state.explorer.correspondFor=null;state.explorer.correspondMap={};if(state.dataset)renderExplorer();});
  $('library-tree').addEventListener('click',e=>host.safe(async()=>{
   const b=e.target.closest('button');if(!b)return;
   if(b.dataset.addAthlete)return openName('athlete',b.dataset.addAthlete);
   if(b.dataset.deleteTeam)return confirmAndDelete(`/v2/shelf-teams/${encodeURIComponent(b.dataset.deleteTeam)}`,'team');
   if(b.dataset.deleteAthlete)return confirmAndDelete(`/v2/shelf-athletes/${encodeURIComponent(b.dataset.deleteAthlete)}`,'athlete');
   if(b.dataset.deleteShelf)return confirmAndDelete(`/v2/shelves/${encodeURIComponent(b.dataset.deleteShelf)}`,'shelf');
   if(b.dataset.deleteFile)return confirmAndDelete(`/v2/shelves/${encodeURIComponent(b.dataset.shelfId)}/files/${encodeURIComponent(b.dataset.deleteFile)}`,'file');
   if(b.dataset.addShelf){await createShelf(b.dataset.addShelf);return host.notify('New EEG shelf created.');}
   if(b.dataset.selectShelf)return selectShelf(b.dataset.selectShelf);
   if(b.dataset.importAthlete)return openImport(null,b.dataset.importAthlete,'signal');
   if(b.dataset.uploadSlot)return openImport(b.dataset.shelfId,null,b.dataset.uploadSlot);
   if(b.dataset.selectType)return host.linkTarget(b.dataset.selectType,b.dataset.selectId,b.dataset.selectName);
  }));
  $('library-search').addEventListener('input',render);
  $('native-file-picker').addEventListener('change',e=>{const files=Array.from(e.target.files||[]);if(files.length)void uploadFiles(files);});
  $('import-close').addEventListener('click',()=>$('import-dialog').close());
  $('choose-downloads').addEventListener('click',()=>{showLocalImport();browseLocal();});
  $('browse-local').addEventListener('click',browseLocal);
  $('retry-upload').addEventListener('click',()=>{if(state.selectedFiles.length)void uploadFiles(state.selectedFiles);});
  $('choose-connector').addEventListener('click',()=>{$('import-actions').hidden=true;$('openneuro-import').hidden=false;});
  $('load-openneuro').addEventListener('click',()=>host.safe(datasetLoad));
  $('explorer-back').addEventListener('click',()=>host.safe(async()=>{if(state.explorer.index<=0)return;state.explorer.index-=1;const here=location();if(!state.treeCache.has(here.path))await loadTree(here.tree,here.path);renderExplorer();}));
  $('explorer-forward').addEventListener('click',()=>host.safe(async()=>{if(state.explorer.index>=state.explorer.history.length-1)return;state.explorer.index+=1;const here=location();if(!state.treeCache.has(here.path))await loadTree(here.tree,here.path);renderExplorer();}));
  $('explorer-retry').addEventListener('click',()=>host.safe(datasetRetry));
  $('explorer-change').addEventListener('click',()=>{$('openneuro-explorer').hidden=true;$('openneuro-setup').hidden=false;$('import-dialog').classList.remove('explorer-open');});
  $('explorer-crumbs').addEventListener('click',e=>host.safe(()=>onExplorerClick(e)));
  $('openneuro-result').addEventListener('click',e=>host.safe(()=>onExplorerClick(e)));
  $('explorer-preview').addEventListener('click',e=>host.safe(()=>onExplorerClick(e)));
  $('import-progress').addEventListener('click',e=>host.safe(async()=>{
    const id=state.explorer.jobId;
    if(e.target.id==='cancel-import'&&id){await backend(`/v2/import-jobs/${encodeURIComponent(id)}/cancel`,{method:'POST'});await pollJob();return;}
    if(e.target.id==='retry-import'&&id){await backend(`/v2/import-jobs/${encodeURIComponent(id)}/retry`,{method:'POST'});if(state.explorer.poll)clearInterval(state.explorer.poll);state.explorer.poll=setInterval(()=>host.safe(pollJob),700);await pollJob();return;}
    if(e.target.id==='import-anyway'&&state.explorer.selected)return startImport(state.explorer.selected.path,{acknowledge_review:true});
    if(e.target.id==='import-adopt'&&state.explorer.selected)return startImport(state.explorer.selected.path,{acknowledge_review:true,adopt_detected_task:true});
  }));
  $('library-tree').addEventListener('dragstart',e=>{const b=e.target.closest('[data-select-type]');if(!b)return;e.dataTransfer.effectAllowed='copy';e.dataTransfer.setData('application/x-neurobuddy-source',JSON.stringify({type:b.dataset.selectType,id:b.dataset.selectId,name:b.dataset.selectName}));});
  updateRequirements();
 }
 return {install,render,refresh,findShelf:getShelf,findAthlete:getAthlete,requirements:reqInfo};
})();
