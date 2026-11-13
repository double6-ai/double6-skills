const $ = (id) => document.getElementById(id);
let job = null, picture = null, boxes = [], start = null, busy = false, pdfBoxes = {}, visited = new Set(), currentPage = 1;
let revoking=Promise.resolve();
let candidates=[], selectedCandidates=new Set(), focusedCandidate=null, detectionWarnings=[];
function pickedCandidates(page=null) {
  return candidates.filter(item=>selectedCandidates.has(item.id)&&(page===null||item.page===page));
}
function currentDetectedBoxes() {return pickedCandidates(currentPage).flatMap(item=>item.rectangles||[]);}
function uniqueBoxes(regions) {return [...new Map(regions.map(region=>[JSON.stringify(region),region])).values()];}
function exportTerms() {return [...new Set([...pickedCandidates().filter(item=>item.source==='text').map(item=>item.text),...decodeTerms($('terms').value)])];}
function exportPages() {
  const pages={...pdfBoxes,[currentPage]:boxes};
  for(const item of pickedCandidates())if(item.page)pages[item.page]=[...(pages[item.page]||[]),...item.rectangles];
  return Object.entries(pages).filter(([,regions])=>regions.length).map(([page,regions])=>({page:Number(page),rectangles:uniqueBoxes(regions)}));
}
function highlightText() {
  if(!job?.preview)return;
  const spans=candidates.flatMap(item=>(item.spans||[]).map(span=>({...span,item}))).sort((a,b)=>a.start-b.start);
  const fragment=document.createDocumentFragment();let offset=0;
  for(const span of spans){
    if(span.start<offset)continue;
    fragment.append(document.createTextNode(job.preview.slice(offset,span.start)));
    const mark=document.createElement('mark');mark.textContent=job.preview.slice(span.start,span.end);mark.dataset.candidate=span.item.id;
    mark.className=selectedCandidates.has(span.item.id)?'candidate-mark':'candidate-mark is-skipped';
    if(focusedCandidate===span.item.id)mark.classList.add('is-focused');
    mark.title=span.item.label+'：'+(selectedCandidates.has(span.item.id)?'已勾选':'已取消');
    fragment.append(mark);offset=span.end;
  }
  fragment.append(document.createTextNode(job.preview.slice(offset)));$('word-preview').replaceChildren(fragment);
}
async function locateCandidate(item) {
  if(busy)return;
  focusedCandidate=item.id;
  if(item.page){
    if(job.kind==='pdf'&&currentPage!==item.page){setBusy(true);try{await loadPdfPage(item.page);$('pdf-page').value=String(item.page);}catch(error){status(error.message);}finally{setBusy(false);}}
    draw();$('canvas').scrollIntoView({block:'center',behavior:'instant'});
  }else{
    highlightText();
    const mark=[...$('word-preview').querySelectorAll('mark')].find(node=>node.dataset.candidate===item.id);
    if(mark)mark.scrollIntoView({block:'center',behavior:'instant'});
  }
}
function renderCandidates() {
  $('detection-summary').textContent=`发现 ${candidates.length} 项疑似内容，已勾选 ${selectedCandidates.size} 项。请逐项核对。`;
  $('detection-warnings').hidden=!detectionWarnings.length;$('detection-warnings').textContent=detectionWarnings.join(' ');
  $('suggestions').replaceChildren();
  if(!candidates.length){$('suggestions').textContent='本次未检出疑似项。请仍检查姓名、地址、图片内容及业务上下文，可手动补选。';return;}
  const groups=new Map();for(const item of candidates){if(!groups.has(item.type))groups.set(item.type,[]);groups.get(item.type).push(item);}
  for(const items of groups.values()){
    const group=document.createElement('fieldset');group.className='candidate-group';
    const legend=document.createElement('legend');const category=document.createElement('label');category.className='candidate-type';
    const toggle=document.createElement('input');toggle.type='checkbox';toggle.disabled=busy;toggle.dataset.group=items[0].type;
    const available=items.filter(item=>item.selectable!==false),checked=available.filter(item=>selectedCandidates.has(item.id)).length;
    toggle.checked=available.length>0&&checked===available.length;toggle.indeterminate=checked>0&&checked<available.length;
    toggle.onchange=()=>{for(const item of available){if(toggle.checked)selectedCandidates.add(item.id);else selectedCandidates.delete(item.id);}candidateChanged();};
    category.append(toggle,document.createTextNode(items[0].label+`（${items.length}）`));legend.append(category);group.append(legend);
    for(const item of items){
      const row=document.createElement('div');row.className='candidate-row';row.dataset.candidate=item.id;
      const label=document.createElement('label');label.className='candidate-choice';
      const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=selectedCandidates.has(item.id);checkbox.disabled=busy||item.selectable===false;checkbox.dataset.candidate=item.id;
      checkbox.onchange=()=>{if(checkbox.checked)selectedCandidates.add(item.id);else selectedCandidates.delete(item.id);candidateChanged();};
      const value=document.createElement('span');value.className='candidate-value';const text=document.createElement('strong');text.textContent=item.text;
      const hint=document.createElement('small');hint.textContent=(item.page?`第 ${item.page} 页 · `:`出现 ${(item.spans||[]).length} 次 · `)+(item.selectable===false?'需手动调整范围':item.source==='ocr'?'图片文字识别，请核对字形':item.reason);
      value.append(text,hint);label.append(checkbox,value);
      const locate=document.createElement('button');locate.type='button';locate.className='text-button candidate-locate';locate.textContent='定位';locate.disabled=busy;locate.onclick=()=>locateCandidate(item);
      row.append(label,locate);group.append(row);
    }
    $('suggestions').append(group);
  }
}
function candidateChanged() {
  const focused=document.activeElement, id=focused?.dataset.candidate, group=focused?.dataset.group;
  invalidate();renderCandidates();highlightText();draw();
  if(id)$('suggestions').querySelector(`input[data-candidate="${id}"]`)?.focus();
  else if(group)$('suggestions').querySelector(`input[data-group="${group}"]`)?.focus();
}
function appendDetection(result) {
  const remaining=200-candidates.length;
  for(const item of result.candidates.slice(0,remaining)){candidates.push(item);if(item.selectable!==false)selectedCandidates.add(item.id);}
  if(result.truncated||result.candidates.length>remaining)detectionWarnings.push('检测建议超过 200 项，超出部分未列出；请拆分材料后处理。');
  for(const warning of result.warnings||[])if(!detectionWarnings.includes(warning))detectionWarnings.push(warning);
  renderCandidates();highlightText();draw();
}
async function runDetection() {
  candidates=[];selectedCandidates=new Set();focusedCandidate=null;detectionWarnings=[];
  if(job.detection){appendDetection(job.detection);return;}
  const total=job.kind==='pdf'?job.pages.length:1;
  for(let page=1;page<=total;page++){
    status(`正在本机检测${job.kind==='pdf'?`第 ${page} / ${total} 页`:'图片文字'}…`,'busy');
    $('detection-summary').textContent=`正在检测 ${page} / ${total}，请稍候…`;
    try{appendDetection(await request('api/detect',JSON.stringify({id:job.id,page}),{'Content-Type':'application/json'}));}
    catch(error){detectionWarnings.push(`第 ${page} 页检测未完成：${error.message} 请手动检查该页。`);renderCandidates();}
  }
}
$('select-all').onclick=()=>{for(const item of candidates)if(item.selectable!==false)selectedCandidates.add(item.id);candidateChanged();};
$('deselect-all').onclick=()=>{selectedCandidates.clear();candidateChanged();};

const canvas = $('canvas'), ctx = canvas.getContext('2d');
const checkNames = {covered_text_not_revealed:'删除后未露出原先被遮盖的文字',neutral_output_filename:'下载使用中性新文件名，未带出原文件名',deterministic_pdf_matches_source_plan:'实际PDF与原件和补选计划的重建结果一致',text_encoding_readable:'原编码可重新读取',utf8_readable:'文本可用UTF-8重新读取',keep_phrases_preserved:'关键保留句仍在副本中',formula_text_neutralized:'公式样式文本已转为普通文字',hidden_carriers_absent:'未带入图片、备注、批注或嵌入对象',external_links_absent:'外部链接已移除',formulas_hidden_absent:'公式与隐藏表行列已移除',hidden_slides_absent:'隐藏幻灯片未带入',image_only_pdf:'按明确选择生成图像化PDF',pdf_not_rasterized:'PDF未整页图像化',selected_text_removed:'框内原文字已删除',outside_text_positions_preserved:'框外文字与位置保留',outside_page_pixels_preserved:'框外页面像素保留',pdf_hidden_objects_absent:'已支持的隐藏PDF对象清理',output_format_matches_request:'实际编码符合选择的输出格式',outside_pixels_within_jpeg_tolerance:'JPEG框外误差在明确容差内',odf_clean_container:'ODF原容器未复制',odf_reopened:'ODF副本可重新读取',original_objects_absent:'原PDF对象和隐藏附件未带入',metadata_removed:'图片元数据已移除',selected_regions_solid:'框选区域已实色覆盖',outside_pixels_preserved:'框选之外的像素保留',selected_strings_absent:'补选原文未在导出包中检出',media_embeddings_comments_absent:'图片、嵌入文件、批注与自定义 XML 未带入',external_relationships_absent:'外部超链接关系已移除',revision_hidden_markup_absent:'修订和隐藏文字标记已移除',original_properties_absent:'作者与文档属性已清理',internal_relationships_valid:'内部文件引用完整',editable_document_reopened:'可编辑 Word 结构可重新读取'};
function status(message='', tone='error') {
  $('status').textContent=message;
  $('status').hidden=!message;
  $('status').dataset.tone=tone;
  if(message && tone==='error')$('status').scrollIntoView({block:'nearest',behavior:'instant'});
}
function syncWorkspace() {
  const ready=Boolean(job), complete=ready&&!$('result').hidden;
  $('empty-state').hidden=ready;
  $('selected-file').hidden=!ready;
  $('clear').disabled=busy;
  const current=complete?2:ready?1:0;
  ['step-import','step-review','step-export'].forEach((id,index)=>{
    $(id).classList.toggle('is-current',index===current);
    $(id).classList.toggle('is-done',index<current);
    if(index===current)$(id).setAttribute('aria-current','step');else $(id).removeAttribute('aria-current');
  });
}
function setBusy(value) {
  busy=value;
  $('work').setAttribute('aria-busy',String(value));
  $('dropzone').classList.toggle('is-disabled',value);
  $('export').textContent=value?'处理中…':'导出并复检 →';
  for(const id of ['stop','file','clear','undo','terms','keep','clean-only','loss','reviewed','add-selection','export','encoding','pdf-page','pdf-loss','pdf-mode','pdf-keep','clear-annotations','output-format','select-all','deselect-all'])$(id).disabled=value;
  for(const control of $('suggestions').querySelectorAll('button,input'))control.disabled=value||candidates.find(item=>item.id===control.dataset.candidate)?.selectable===false;
  if(!value){const raster=$('pdf-mode').value==='rasterize';$('pdf-keep').disabled=raster;$('clear-annotations').disabled=raster;}
  syncWorkspace();
}
function invalidate() { const had=$('download').hasAttribute('href'),id=job?.id;$('download').removeAttribute('href');$('result').hidden=true; $('reviewed').checked=false;syncWorkspace();if(had&&id){revoking=request('api/invalidate',JSON.stringify({id}),{'Content-Type':'application/json'});revoking.catch(()=>status('旧下载撤销未确认，请先清空会话。'));} }
async function request(path, body, headers={}) {
  const response=await fetch(path,{method:'POST',body,headers});
  const data=await response.json();
  if(!response.ok) throw new Error(data.error || '处理未完成。');
  return data;
}
function draw(extra=null) {
  ctx.clearRect(0,0,canvas.width,canvas.height);if(!picture)return;
  ctx.drawImage(picture,0,0);ctx.fillStyle='black';
  for(const b of [...boxes,...(extra?[extra]:[])])ctx.fillRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);
  const scale=canvas.width/(canvas.getBoundingClientRect().width||canvas.width);
  for(const item of candidates.filter(item=>item.page===currentPage)){
    const selected=selectedCandidates.has(item.id);
    for(const b of item.rectangles||[]){
      ctx.fillStyle=selected?'rgba(220,114,42,.22)':'rgba(102,116,138,.06)';ctx.strokeStyle=focusedCandidate===item.id?'#355edb':selected?'#c67227':'#7c899e';ctx.lineWidth=(focusedCandidate===item.id?3:1.5)*scale;
      ctx.setLineDash(selected?[]:[4*scale,3*scale]);ctx.fillRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);ctx.setLineDash([]);
    }
  }
  $('region-count').textContent=`本页已勾选 ${currentDetectedBoxes().length} 处检测区域 · 手动补选 ${boxes.length} 处`;if(job?.kind==='pdf'){$('pdf-progress').textContent=`已查看 ${visited.size} / ${job.pages.length} 页；框选坐标使用当前页144dpi像素。`;}
}
function point(event) { const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(canvas.width,(event.clientX-r.left)*canvas.width/r.width)),Math.max(0,Math.min(canvas.height,(event.clientY-r.top)*canvas.height/r.height))]; }
function encodeTerm(text) {return text.replace(/\\/g,'\\\\').replace(/\r\n/g,'\\n').replace(/\n/g,'\\n').replace(/\r/g,'\\n');}
function decodeLine(line) {
  let out='';
  for (let i=0;i<line.length;i++) {
    if (line[i]==='\\' && line[i+1]==='n') {out+='\n';i++;}
    else if (line[i]==='\\' && line[i+1]==='\\') {out+='\\';i++;}
    else out+=line[i];
  }
  return out.trim();
}
function decodeTerms(value) {return value?value.split('\n').map(decodeLine).filter(Boolean):[];}
function addTerm(text) {text=text.trim();if(!text)return;const items=decodeTerms($('terms').value);if(!items.includes(text))items.push(text);$('terms').value=items.map(encodeTerm).join('\n');invalidate();}
canvas.addEventListener('pointerdown',e=>{if(busy)return;invalidate();start=point(e);canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{if(start){const end=point(e);draw([...start,...end]);}});
canvas.addEventListener('pointerup',async e=>{
  if(!start||busy)return;const end=point(e);let region=[...start,...end];start=null;
  if(Math.abs(region[0]-region[2])<2||Math.abs(region[1]-region[3])<2){draw();return;}
  setBusy(true);
  try{
    if(job?.kind==='pdf'&&$('pdf-mode').value==='preserve'){
      const result=await request('api/snap-pdf',JSON.stringify({id:job.id,page:currentPage,rectangle:region}),{'Content-Type':'application/json'});region=result.rectangle;status('已对齐完整字符，请核对黑块显示的实际范围。','info');
    }
    boxes.push(region);invalidate();draw();
  }catch(error){status(error.message);draw();}finally{setBusy(false);}
});
canvas.addEventListener('pointercancel',()=>{start=null;draw();});
$('undo').onclick=()=>{boxes.pop();invalidate();draw();};
$('terms').oninput=()=>{invalidate();};$('keep').oninput=invalidate;
$('loss').onchange=invalidate;$('clean-only').onchange=invalidate;$('pdf-loss').onchange=invalidate;$('pdf-keep').oninput=invalidate;$('clear-annotations').onchange=invalidate;
$('output-format').onchange=()=>{invalidate();$('format-notice').textContent=$('output-format').value===job?.input_extension?'保持原格式，生成新文件。':'已明确选择格式转换，将生成新文件。';};
$('pdf-mode').onchange=()=>{invalidate();const raster=$('pdf-mode').value==='rasterize';$('pdf-loss-label').hidden=!raster;$('pdf-keep').disabled=raster;$('clear-annotations').disabled=raster;if(raster){$('pdf-keep').value='';$('clear-annotations').checked=false;}};
async function loadPdfPage(number){pdfBoxes[currentPage]=boxes;currentPage=number;boxes=pdfBoxes[number]||[];picture=new Image();picture.src=`file/${job.id}/page/${number}`;await picture.decode();canvas.width=picture.width;canvas.height=picture.height;visited.add(number);draw();invalidate();}
$('pdf-page').onchange=async()=>{if(busy||!job)return;setBusy(true);try{await loadPdfPage(Number($('pdf-page').value));}catch(e){status(e.message);}finally{setBusy(false);}};
$('encoding').onchange=()=>{resetWorkspace();status('编码已改变，请重新选择原文件。','info');};
$('add-selection').onclick=()=>{const sel=window.getSelection();if(sel&&$('word-preview').contains(sel.anchorNode)&&$('word-preview').contains(sel.focusNode))addTerm(sel.toString());else status('请先在预览中选中需要隐去的文字。');};
$('file').onchange=async()=>{
  if(busy)return;
  const file=$('file').files[0];if(!file)return;
  invalidate();$('work').hidden=true;status('正在本机读取文件…','busy');candidates=[];selectedCandidates.clear();detectionWarnings=[];setBusy(true);
  try{
    const ext=file.name.split('.').pop().toLowerCase();const kind=({docx:'word',doc:'word',rtf:'word',odt:'word',xls:'excel',ods:'excel',ppt:'pdf',odp:'slides',txt:'text',md:'markdown',markdown:'markdown',csv:'csv',tsv:'tsv',pdf:'pdf',xlsx:'excel',xlsm:'excel',pptx:'slides'})[ext]||'image';
    const legacy={doc:'.docx',rtf:'.docx',xls:'.xlsx',ppt:'.pdf'};let conversion='';
    if(legacy[ext]){if(!window.confirm(`此原格式暂不能安全导出。是否明确选择转换为${legacy[ext]}并读取预览？会调用本机LibreOffice，原件不改动。`))throw new Error('未同意转换，未读取旧格式内容。');conversion=legacy[ext];}
    job=await request('api/import',file,{'Content-Type':'application/octet-stream','X-File-Kind':kind,'X-File-Extension':'.'+ext,'X-Text-Encoding':$('encoding').value,'X-File-Name':encodeURIComponent(file.name),'X-Convert-To':conversion});
    $('filename').textContent=file.name;
    $('file-meta').textContent=`${file.size<1048576?(file.size/1024).toFixed(1)+' KB':(file.size/1048576).toFixed(1)+' MB'} · ${ext.toUpperCase()}`;
    $('output-format').replaceChildren(...job.output_options.map(ext=>{const o=document.createElement('option');o.value=ext;o.textContent=ext===job.input_extension?'保持原格式 '+ext:'明确转换为 '+ext;return o;}));
    if(conversion)$('output-format').value=conversion;
    $('format-notice').textContent=conversion?'已明确选择转换，原件保持不变。':job.original_format_supported?'默认保持原格式，生成新文件。':'此旧格式暂不能安全原格式导出；只有明确选择转换格式才会导出。';
    $('pdf-mode').value='preserve';$('pdf-keep').value='';$('pdf-keep').disabled=false;$('clear-annotations').checked=false;$('clear-annotations').disabled=false;boxes=[];$('terms').value='';$('keep').value='';$('loss').checked=false;$('clean-only').checked=false;$('pdf-loss').checked=false;pdfBoxes={};visited=new Set();currentPage=1;
    $('image-work').hidden=!['image','pdf'].includes(kind);$('word-work').hidden=['image','pdf'].includes(kind);$('pdf-controls').hidden=kind!=='pdf';$('pdf-loss-label').hidden=true;
    if(kind==='pdf'){
      $('pdf-page').replaceChildren(...job.pages.map(p=>{const o=document.createElement('option');o.value=p.page;o.textContent=`第${p.page}页`;return o;}));$('image-work').querySelector('p').textContent=job.notice+' 彩色框表示疑似敏感区域，勾选后实色覆盖；请核对范围。';await loadPdfPage(1);
    }else
    if(kind==='image'){
      $('image-work').querySelector('p').textContent='彩色框是本地 OCR 检测建议，勾选后导出为实色覆盖。可拖动补画，也可取消误报；默认保持原图片格式。';
      picture=new Image();picture.src=`file/${job.id}/preview`;await picture.decode();canvas.width=job.width;canvas.height=job.height;draw();
    }else{
      $('word-notice').textContent=job.notice;$('word-preview').textContent=job.preview;
      $('word-counts').textContent=kind==='word'?`检测到图片 ${job.removed.images} 个、批注部件 ${job.removed.comment_parts} 个、删除/移出修订 ${job.removed.deleted_or_moved_fragments} 处。`:Object.entries(job.removed||{}).map(([k,v])=>`${({hidden_sheets:'隐藏工作表',hidden_rows:'隐藏行',hidden_columns:'隐藏列',hidden_format_cells:'隐藏格式单元格',formulas:'缓存公式',uncached_formulas:'缺少缓存公式',hidden_slides:'隐藏幻灯片'})[k]||k}: ${v}`).join('；');

    }
    $('work').hidden=false;syncWorkspace();await runDetection();status();
    if(window.matchMedia('(max-width: 760px)').matches)$('work').scrollIntoView({block:'start',behavior:'instant'});
  }catch(e){resetWorkspace();status(e.message);}finally{setBusy(false);}
};
$('dropzone').addEventListener('dragover',event=>{event.preventDefault();if(!busy)$('dropzone').classList.add('is-dragging');});
$('dropzone').addEventListener('dragleave',event=>{if(!$('dropzone').contains(event.relatedTarget))$('dropzone').classList.remove('is-dragging');});
$('dropzone').addEventListener('drop',event=>{
  event.preventDefault();$('dropzone').classList.remove('is-dragging');
  if(busy)return;
  const files=event.dataTransfer.files;
  if(files.length!==1){status('请每次选择一份材料。');return;}
  $('file').files=files;$('file').onchange();
});
for(const id of ['help-link','privacy-link'])$(id).onclick=()=>{$('usage').open=true;};
$('export').onclick=async()=>{
  if(!job||busy)return;setBusy(true);$('result').hidden=true;status('正在本机导出并复检…','busy');
  try{
    await revoking;
    if(job.kind==='pdf'){pdfBoxes[currentPage]=boxes;if(visited.size!==job.pages.length)throw new Error('请先逐页查看全部PDF，再导出。');}
    const data=await request('api/export',JSON.stringify({id:job.id,output_format:$('output-format').value,pdf_mode:$('pdf-mode').value,clear_annotations:job.kind==='pdf'&&$('clear-annotations').checked,rectangles:uniqueBoxes([...boxes,...currentDetectedBoxes()]),terms:exportTerms(),keep:(job.kind==='pdf'?$('pdf-keep'):$('keep')).value.split('\n').map(x=>x.trim()).filter(Boolean),reviewed:$('reviewed').checked,acknowledge_loss:job.kind==='pdf'?$('pdf-loss').checked:$('loss').checked,pages:exportPages(),reviewed_pages:[...visited],clean_only:$('clean-only').checked}),{'Content-Type':'application/json'});
    $('report-scope').textContent=data.report.scope;$('checks').replaceChildren();
    for(const [key,ok] of Object.entries(data.report.checks)){const li=document.createElement('li');li.textContent=(ok?'✓ ':'× ')+(checkNames[key]||key);$('checks').append(li);}
    for(const key of data.report.not_checked||[]){const li=document.createElement('li');li.className='not-checked';li.textContent='未检查：'+(key==='keep_phrases_preserved'?'未声明关键保留项，请打开副本核对业务内容':key);$('checks').append(li);}
    $('download').href=data.download;$('result').hidden=false;status();$('result').scrollIntoView({block:'start',behavior:'instant'});
  }catch(e){status(e.message);}finally{setBusy(false);}
};
function resetWorkspace(){
  candidates=[];selectedCandidates.clear();focusedCandidate=null;detectionWarnings=[];
  job=null;revoking=Promise.resolve();picture=null;boxes=[];start=null;pdfBoxes={};visited=new Set();currentPage=1;$('pdf-page').replaceChildren();$('pdf-progress').textContent='';$('pdf-loss').checked=false;$('pdf-mode').value='preserve';$('pdf-keep').value='';$('clear-annotations').checked=false;$('clear-annotations').disabled=false;$('output-format').replaceChildren();$('format-notice').textContent='';canvas.width=1;canvas.height=1;
  $('file').value='';$('filename').textContent='';$('file-meta').textContent='';$('terms').value='';$('keep').value='';$('word-preview').textContent='';$('suggestions').replaceChildren();$('detection-summary').textContent='';$('detection-warnings').hidden=true;$('word-notice').textContent='';$('word-counts').textContent='';$('loss').checked=false;$('clean-only').checked=false;$('reviewed').checked=false;$('download').removeAttribute('href');$('work').hidden=true;$('result').hidden=true;syncWorkspace();
}
$('clear').onclick=async()=>{if(busy)return;setBusy(true);try{await request('api/clear','{}',{'Content-Type':'application/json'});resetWorkspace();status('会话已清空。','info');}catch(e){status(e.message);}finally{setBusy(false);}};

$('stop').onclick=async()=>{
  if(busy||!window.confirm('结束工具并清空本次材料？已下载的副本仍保存在下载目录。'))return;
  setBusy(true);
  try{await request('api/stop','{}',{'Content-Type':'application/json'});resetWorkspace();status('工具已结束，可关闭此标签页。下次双击安装生成的启动文件即可重新打开。','info');}
  catch(e){status('工具未能确认结束，请关闭启动进程后重新打开。');setBusy(false);}
};
syncWorkspace();
