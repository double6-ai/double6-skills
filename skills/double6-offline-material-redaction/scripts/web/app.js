const $ = (id) => document.getElementById(id);
let job = null, picture = null, boxes = [], start = null, busy = false, pdfBoxes = {}, visited = new Set(), currentPage = 1;
let revoking=Promise.resolve();
const canvas = $('canvas'), ctx = canvas.getContext('2d');
const checkNames = {deterministic_pdf_matches_source_plan:'实际PDF与原件和补选计划的重建结果一致',text_encoding_readable:'原编码可重新读取',utf8_readable:'文本可用UTF-8重新读取',keep_phrases_preserved:'关键保留句仍在副本中',formula_text_neutralized:'公式样式文本已转为普通文字',hidden_carriers_absent:'未带入图片、备注、批注或嵌入对象',external_links_absent:'外部链接已移除',formulas_hidden_absent:'公式与隐藏表行列已移除',hidden_slides_absent:'隐藏幻灯片未带入',image_only_pdf:'按明确选择生成图像化PDF',pdf_not_rasterized:'PDF未整页图像化',selected_text_removed:'框内原文字已删除',outside_text_positions_preserved:'框外文字与位置保留',outside_page_pixels_preserved:'框外页面像素保留',pdf_hidden_objects_absent:'已支持的隐藏PDF对象清理',output_format_matches_request:'实际编码符合选择的输出格式',outside_pixels_within_jpeg_tolerance:'JPEG框外误差在明确容差内',odf_clean_container:'ODF原容器未复制',odf_reopened:'ODF副本可重新读取',original_objects_absent:'原PDF对象和隐藏附件未带入',metadata_removed:'图片元数据已移除',selected_regions_solid:'框选区域已实色覆盖',outside_pixels_preserved:'框选之外的像素保留',selected_strings_absent:'补选原文未在导出包中检出',media_embeddings_comments_absent:'图片、嵌入文件、批注与自定义 XML 未带入',external_relationships_absent:'外部超链接关系已移除',revision_hidden_markup_absent:'修订和隐藏文字标记已移除',original_properties_absent:'作者与文档属性已清理',internal_relationships_valid:'内部文件引用完整',editable_document_reopened:'可编辑 Word 结构可重新读取'};
function status(message='') { $('status').textContent=message; }
function setBusy(value) {
  busy=value;
  for(const id of ['stop','file','clear','undo','terms','keep','clean-only','loss','reviewed','add-selection','export','encoding','pdf-page','pdf-loss','pdf-mode','pdf-keep','output-format'])$(id).disabled=value;
  for(const button of $('suggestions').querySelectorAll('button'))button.disabled=value;
  if(!value)$('pdf-keep').disabled=$('pdf-mode').value==='rasterize';
}
function invalidate() { const had=$('download').hasAttribute('href'),id=job?.id;$('download').removeAttribute('href');$('result').hidden=true; $('reviewed').checked=false;if(had&&id){revoking=request('api/invalidate',JSON.stringify({id}),{'Content-Type':'application/json'});revoking.catch(()=>status('旧下载撤销未确认，请先清空会话。'));} }
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
  $('region-count').textContent=`已框选 ${boxes.length} 处`;if(job?.kind==='pdf'){$('pdf-progress').textContent=`已查看 ${visited.size} / ${job.pages.length} 页；框选坐标使用当前页144dpi像素。`;}
}
function point(event) { const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(canvas.width,(event.clientX-r.left)*canvas.width/r.width)),Math.max(0,Math.min(canvas.height,(event.clientY-r.top)*canvas.height/r.height))]; }
function addTerm(text) {text=text.trim();if(!text)return;const lines=$('terms').value.split('\n').filter(Boolean);if(!lines.includes(text))lines.push(text);$('terms').value=lines.join('\n');invalidate();}
canvas.addEventListener('pointerdown',e=>{if(busy)return;start=point(e);canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{if(start){const end=point(e);draw([...start,...end]);}});
canvas.addEventListener('pointerup',e=>{if(!start)return;const end=point(e);if(Math.abs(start[0]-end[0])>=2&&Math.abs(start[1]-end[1])>=2){boxes.push([...start,...end]);invalidate();}start=null;draw();});
canvas.addEventListener('pointercancel',()=>{start=null;draw();});
$('undo').onclick=()=>{boxes.pop();invalidate();draw();};
$('terms').oninput=invalidate;$('keep').oninput=invalidate;
$('loss').onchange=invalidate;$('clean-only').onchange=invalidate;$('pdf-loss').onchange=invalidate;$('pdf-keep').oninput=invalidate;
$('output-format').onchange=()=>{invalidate();$('format-notice').textContent=$('output-format').value===job?.input_extension?'保持原格式，生成新文件。':'已明确选择格式转换，将生成新文件。';};
$('pdf-mode').onchange=()=>{invalidate();const raster=$('pdf-mode').value==='rasterize';$('pdf-loss-label').hidden=!raster;$('pdf-keep').disabled=raster;if(raster)$('pdf-keep').value='';};
async function loadPdfPage(number){pdfBoxes[currentPage]=boxes;currentPage=number;boxes=pdfBoxes[number]||[];picture=new Image();picture.src=`file/${job.id}/page/${number}`;await picture.decode();canvas.width=picture.width;canvas.height=picture.height;visited.add(number);draw();invalidate();}
$('pdf-page').onchange=async()=>{if(busy||!job)return;setBusy(true);try{await loadPdfPage(Number($('pdf-page').value));}catch(e){status(e.message);}finally{setBusy(false);}};
$('encoding').onchange=()=>{resetWorkspace();status('编码已改变，请重新选择原文件。');};
$('add-selection').onclick=()=>{const sel=window.getSelection();if(sel&&$('word-preview').contains(sel.anchorNode)&&$('word-preview').contains(sel.focusNode))addTerm(sel.toString());else status('请先在预览中选中需要隐去的文字。');};
$('file').onchange=async()=>{
  if(busy)return;
  const file=$('file').files[0];if(!file)return;
  invalidate();$('work').hidden=true;status('正在本机读取文件…');setBusy(true);
  try{
    const ext=file.name.split('.').pop().toLowerCase();const kind=({docx:'word',doc:'word',rtf:'word',odt:'word',xls:'excel',ods:'excel',ppt:'pdf',odp:'slides',txt:'text',md:'markdown',markdown:'markdown',csv:'csv',tsv:'tsv',pdf:'pdf',xlsx:'excel',xlsm:'excel',pptx:'slides'})[ext]||'image';
    const legacy={doc:'.docx',rtf:'.docx',xls:'.xlsx',ppt:'.pdf'};let conversion='';
    if(legacy[ext]){if(!window.confirm(`此原格式暂不能安全导出。是否明确选择转换为${legacy[ext]}并读取预览？会调用本机LibreOffice，原件不改动。`))throw new Error('未同意转换，未读取旧格式内容。');conversion=legacy[ext];}
    job=await request('api/import',file,{'Content-Type':'application/octet-stream','X-File-Kind':kind,'X-File-Extension':'.'+ext,'X-Text-Encoding':$('encoding').value,'X-File-Name':encodeURIComponent(file.name),'X-Convert-To':conversion});
    $('filename').textContent=file.name;
    $('output-format').replaceChildren(...job.output_options.map(ext=>{const o=document.createElement('option');o.value=ext;o.textContent=ext===job.input_extension?'保持原格式 '+ext:'明确转换为 '+ext;return o;}));
    if(conversion)$('output-format').value=conversion;
    $('format-notice').textContent=conversion?'已明确选择转换，原件保持不变。':job.original_format_supported?'默认保持原格式，生成新文件。':'此旧格式暂不能安全原格式导出；只有明确选择转换格式才会导出。';
    $('pdf-mode').value='preserve';$('pdf-keep').value='';$('pdf-keep').disabled=false;boxes=[];$('terms').value='';$('keep').value='';$('loss').checked=false;$('clean-only').checked=false;$('pdf-loss').checked=false;pdfBoxes={};visited=new Set();currentPage=1;
    $('image-work').hidden=!['image','pdf'].includes(kind);$('word-work').hidden=['image','pdf'].includes(kind);$('pdf-controls').hidden=kind!=='pdf';$('pdf-loss-label').hidden=true;
    if(kind==='pdf'){
      $('pdf-page').replaceChildren(...job.pages.map(p=>{const o=document.createElement('option');o.value=p.page;o.textContent=`第${p.page}页`;return o;}));$('image-work').querySelector('p').textContent=job.notice;await loadPdfPage(1);
    }else
    if(kind==='image'){
      $('image-work').querySelector('p').textContent='拖动框选敏感区域，可框选多处；默认保持原图片格式，透明区铺白底；JPEG采用高质量重编码并检查误差。';
      picture=new Image();picture.src=`file/${job.id}/preview`;await picture.decode();canvas.width=job.width;canvas.height=job.height;draw();
    }else{
      $('word-notice').textContent=job.notice;$('word-preview').textContent=job.preview;
      $('word-counts').textContent=kind==='word'?`检测到图片 ${job.removed.images} 个、批注部件 ${job.removed.comment_parts} 个、删除/移出修订 ${job.removed.deleted_or_moved_fragments} 处。`:Object.entries(job.removed||{}).map(([k,v])=>`${({hidden_sheets:'隐藏工作表',hidden_rows:'隐藏行',hidden_columns:'隐藏列',hidden_format_cells:'隐藏格式单元格',formulas:'缓存公式',uncached_formulas:'缺少缓存公式',hidden_slides:'隐藏幻灯片'})[k]||k}: ${v}`).join('；');
      $('suggestions').replaceChildren();
      for(const text of job.suggestions){const b=document.createElement('button');b.type='button';b.textContent=`补选：${text}`;b.onclick=()=>addTerm(text);$('suggestions').append(b);}
      if(!job.suggestions.length)$('suggestions').textContent='未发现电话或邮箱格式；请自行检查姓名、机构和其它敏感文字。';
    }
    $('work').hidden=false;status();
  }catch(e){job=null;status(e.message);}finally{setBusy(false);}
};
$('export').onclick=async()=>{
  if(!job||busy)return;setBusy(true);$('result').hidden=true;status('正在本机导出并复检…');
  try{
    await revoking;
    if(job.kind==='pdf'){pdfBoxes[currentPage]=boxes;if(visited.size!==job.pages.length)throw new Error('请先逐页查看全部PDF，再导出。');}
    const data=await request('api/export',JSON.stringify({id:job.id,output_format:$('output-format').value,pdf_mode:$('pdf-mode').value,rectangles:boxes,terms:$('terms').value.split('\n').map(x=>x.trim()).filter(Boolean),keep:(job.kind==='pdf'?$('pdf-keep'):$('keep')).value.split('\n').map(x=>x.trim()).filter(Boolean),reviewed:$('reviewed').checked,acknowledge_loss:job.kind==='pdf'?$('pdf-loss').checked:$('loss').checked,pages:Object.entries(pdfBoxes).filter(([,v])=>v.length).map(([page,rectangles])=>({page:Number(page),rectangles})),reviewed_pages:[...visited],clean_only:$('clean-only').checked}),{'Content-Type':'application/json'});
    $('report-scope').textContent=data.report.scope;$('checks').replaceChildren();
    for(const [key,ok] of Object.entries(data.report.checks)){const li=document.createElement('li');li.textContent=(ok?'✓ ':'× ')+(checkNames[key]||key);$('checks').append(li);}
    for(const key of data.report.not_checked||[]){const li=document.createElement('li');li.textContent='未检查：'+(key==='keep_phrases_preserved'?'未声明关键保留项，请打开副本核对业务内容':key);$('checks').append(li);}
    $('download').href=data.download;$('result').hidden=false;status();$('result').scrollIntoView({block:'start',behavior:'instant'});
  }catch(e){status(e.message);}finally{setBusy(false);}
};
function resetWorkspace(){
  job=null;revoking=Promise.resolve();picture=null;boxes=[];start=null;pdfBoxes={};visited=new Set();currentPage=1;$('pdf-page').replaceChildren();$('pdf-progress').textContent='';$('pdf-loss').checked=false;$('pdf-mode').value='preserve';$('pdf-keep').value='';$('output-format').replaceChildren();$('format-notice').textContent='';canvas.width=1;canvas.height=1;
  $('file').value='';$('filename').textContent='';$('terms').value='';$('keep').value='';$('word-preview').textContent='';$('suggestions').replaceChildren();$('word-notice').textContent='';$('word-counts').textContent='';$('loss').checked=false;$('clean-only').checked=false;$('reviewed').checked=false;$('download').removeAttribute('href');$('work').hidden=true;$('result').hidden=true;
}
$('clear').onclick=async()=>{if(busy)return;setBusy(true);try{await request('api/clear','{}',{'Content-Type':'application/json'});resetWorkspace();status('会话已清空。');}catch(e){status(e.message);}finally{setBusy(false);}};

$('stop').onclick=async()=>{
  if(busy||!window.confirm('结束工具并清空本次材料？已下载的副本仍保存在下载目录。'))return;
  setBusy(true);
  try{await request('api/stop','{}',{'Content-Type':'application/json'});resetWorkspace();status('工具已结束，可关闭此标签页。下次双击安装生成的启动文件即可重新打开。');}
  catch(e){status('工具未能确认结束，请关闭启动进程后重新打开。');setBusy(false);}
};
