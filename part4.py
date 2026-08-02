
ADMIN_SCRIPT = """<script>
var P="__PREFIX__";
var INIT=__INIT__;
var MSG=__MSG__;
var DATA=INIT.data,USED=INIT.used,QUOTA=INIT.quota,PENDING=INIT.pending||0,RESERVED=INIT.reserved||0;
var dir='',q='';
var selMode=false,selected=[];
function inSel(p){return selected.indexOf(p)>=0;}
function toggleSel(p){var i=selected.indexOf(p);if(i>=0)selected.splice(i,1);else selected.push(p);render();renderSel();}
function selAll(){var items=DATA.filter(function(it){return inDir(dir,it.path);});
  var all=items.length>0&&items.every(function(it){return inSel(it.path);});
  if(all){var ps={};items.forEach(function(it){ps[it.path]=1;});selected=selected.filter(function(p){return !ps[p];});}
  else{items.forEach(function(it){if(selected.indexOf(it.path)<0)selected.push(it.path);});}
  render();renderSel();}
function renderSel(){
  var act=document.getElementById('btnSel');
  if(act)act.classList.toggle('on',selMode);
  var bar=document.getElementById('selbar');
  if(!bar)return;
  if(!selMode){bar.style.display='none';return;}
  bar.style.display='flex';
  document.getElementById('selcount').textContent='已选 '+selected.length+' 项';
  var z=document.getElementById('selZipBtn');if(z)z.disabled=selected.length===0;
  var d=document.getElementById('selDelBtn');if(d)d.disabled=selected.length===0;
}
function zipDown(){
  if(!selected.length){toast(false,'请先选择文件');return;}
  var f=document.createElement('form');f.method='POST';f.action=P+'/zip';f.style.display='none';
  selected.forEach(function(p){var i=document.createElement('input');i.type='hidden';i.name='path';i.value=p;f.appendChild(i);});
  document.body.appendChild(f);f.submit();
}
function zipOne(path){
  var f=document.createElement('form');f.method='POST';f.action=P+'/zip';f.style.display='none';
  var i=document.createElement('input');i.type='hidden';i.name='path';i.value=path;
  f.appendChild(i);document.body.appendChild(f);f.submit();
}
function batchDel(){
  if(!selected.length)return;
  if(!confirm('确认删除已选 '+selected.length+' 项？此操作不可恢复。'))return;
  var fd=new FormData();fd.append('op','delete');
  selected.forEach(function(p){fd.append('path',p);});
  fetch(P+'/admin/batch',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'已删除 '+j.done+' 项'+(j.failed&&j.failed.length?('，失败 '+j.failed.length+' 项'):''));
      if(j.failed&&j.failed.length)toast(false,j.failed.map(function(x){return x.path+':'+x.error;}).join('；'));
    }else{toast(false,j.error||'删除失败');}
    selected=[];selMode=false;refresh();renderSel();
  }).catch(function(){toast(false,'删除失败');});
}
var CHUNK=5*1024*1024,WORKERS=3;
var queue=[];var active=0;
var PAGE_SIZE=12,page=1,pageCount=1;
var TPAGE_SIZE=10,tPage=1,tPageCount=1;
function jpost(url,obj){var fd=new FormData();Object.keys(obj).forEach(function(k){fd.append(k,obj[k]);});return fetch(url,{method:'POST',body:fd}).then(function(r){return r.json();});}
function addFile(f,rel,targetDir){
  var path=rel||f.name;
  if(!path)return;
  var base=(typeof targetDir==='string')?targetDir:dir;
  if(base)path=base+'/'+path;
  var t={id:Math.random().toString(36).slice(2),file:f,path:path,name:path.split('/').pop(),
    size:f.size,lastModified:f.lastModified,upload_id:null,done:{},total:0,uploaded:0,status:'waiting',err:null};
  queue.push(t);tPage=1;pump();
}
function pump(){
  while(active<WORKERS){
    var t=null;
    for(var i=0;i<queue.length;i++){if(queue[i].status==='waiting'){t=queue[i];break;}}
    if(!t)return;
    active++;t.status='uploading';updateTaskRow(t);
    runTask(t).then(function(){active--;pump();});
  }
}
async function runTask(t){
  try{
    var fh='';
    if(t.size>0&&t.size<=64*1024*1024&&window.crypto&&crypto.subtle){
      try{fh=await fileHash(t.file);}catch(e){fh='';}
    }
    var init=await new Promise(function(res,rej){
      _initChain=_initChain.then(function(){
        jpost(P+'/admin/upload/init',{path:t.path,size:t.size,lastModified:t.lastModified,file_hash:fh}).then(res,rej);
      });
    });
    if(t.status==='cancelled'){
      if(init.upload_id){
        var rfd2=new FormData();rfd2.append('upload_id',init.upload_id);rfd2.append('release','1');
        fetch(P+'/admin/upload/cancel',{method:'POST',body:rfd2}).catch(function(){});
      }
      return;
    }
    if(init.error){fail(t,init.error);return;}
    t.upload_id=init.upload_id;t.total=init.total_chunks||1;
    _myUids[t.upload_id]=1;
    t.done={};t.uploaded=0;
    for(var k=0;k<(init.done||[]).length;k++){var di=init.done[k];t.done[di]=1;t.uploaded+=chunkLen(t,di);}
    updateTaskRow(t);
    for(var i=0;i<t.total;i++){
      if(t.status==='cancelled'||t.status==='paused')return;
      if(t.done[i])continue;
      var ok=await upChunk(t,i);
      if(t.status==='cancelled'||t.status==='paused')return;
      if(ok){t.done[i]=1;t.uploaded=Math.min(t.size,t.uploaded+chunkLen(t,i));updateTaskProgress(t);}
      else{fail(t,'分片 '+i+' 上传失败');return;}
    }
    if(t.status==='cancelled'||t.status==='paused')return;
    var comp=await jpost(P+'/admin/upload/complete',{upload_id:t.upload_id});
    if(t.status==='cancelled'||t.status==='paused')return;
    if(comp.error){fail(t,comp.error);return;}
    finish(t);
  }catch(e){fail(t,'网络错误，可重试');}
}
function chunkLen(t,i){if(t.size<=0)return 0;return i<t.total-1?CHUNK:(t.size-CHUNK*(t.total-1));}
function fileHash(blob){
  return blob.arrayBuffer().then(function(b){return crypto.subtle.digest('SHA-256',b);}).then(function(b){
    var a=new Uint8Array(b),h='';
    for(var i=0;i<a.length;i++)h+=('0'+a[i].toString(16)).slice(-2);
    return h;
  });
}
function upChunk(t,i){
  return new Promise(function(res){
    var blob=t.file.slice(i*CHUNK,Math.min(t.size,(i+1)*CHUNK));
    function sendChunk(hex){
      var x=new XMLHttpRequest();
      t._xhr=x;
      x.open('POST',P+'/admin/upload/chunk?upload_id='+encodeURIComponent(t.upload_id)+'&index='+i+(hex?'&sha256='+hex:''));
      x.onload=function(){t._xhr=null;res(x.status>=200&&x.status<300);};
      x.onerror=function(){t._xhr=null;res(false);};
      x.onabort=function(){t._xhr=null;res(false);};
      x.send(blob);
    }
    if(window.crypto&&crypto.subtle){
      blob.arrayBuffer().then(function(buf){return crypto.subtle.digest('SHA-256',buf);}).then(function(buf){
        if(t.status==='cancelled'||t.status==='paused'){res(false);return;}
        var arr=new Uint8Array(buf),hex='';
        for(var k=0;k<arr.length;k++)hex+=('0'+arr[k].toString(16)).slice(-2);
        sendChunk(hex);
      }).catch(function(){if(t.status==='cancelled'||t.status==='paused'){res(false);return;}sendChunk('');});
    }else{sendChunk('');}
  });
}
function fail(t,msg){t.status='failed';t.err=msg;updateTaskRow(t);renderBulk();toast(false,msg+'：'+t.name);refreshStats();if(!queue.some(function(x){return x.status==='uploading'||x.status==='waiting';}))finalizePool();}
var _doneTimer=null,_batchSize=0,_initChain=Promise.resolve(),_upSnap=null,_myUids={};
function snapUp(){_upSnap={};queue.forEach(function(t){_upSnap[t.id]=t.uploaded;});}
window.addEventListener('pagehide',function(){
  Object.keys(_myUids).forEach(function(u){
    var fd=new FormData();fd.append('upload_id',u);fd.append('release','1');
    try{navigator.sendBeacon(P+'/admin/upload/cancel',fd);}catch(e){}
  });
});
function showDone(n){
  var box=document.getElementById('tasks');
  if(!box)return;
  box.style.display='block';
  box.innerHTML='<div class="tdone">✓ 全部上传完成 · '+n+' 个文件</div>';
  clearTimeout(_doneTimer);
  _doneTimer=setTimeout(function(){box.style.display='none';},5000);
}
function finalizePool(){
  var n=0,f=0,p=0;
  queue.forEach(function(t){
    if(t.status==='done')n++;
    else if(t.status==='failed')f++;
    else if(t.status==='paused')p++;
  });
  var tp=document.getElementById('taskPager');
  if(!f&&!p){
    queue=[];
    renderBulk();
    updateTasksum();
    if(tp)tp.style.display='none';
    showDone(n);
  }else{
    renderBulk();
    updateTasksum();
    renderTasks();
    toast(f?false:true,(n+' 个完成'+(f?('，'+f+' 个失败'):'')+(p?('，'+p+' 个暂停'):'')));
  }
  refresh();
}
function finish(t){
  if(_batchSize<=1)toast(true,'上传完成：'+t.name);
  if(t.upload_id)delete _myUids[t.upload_id];
  t.status='done';t.uploaded=t.size;
  updateTaskRow(t);
  renderBulk();
  if(!queue.some(function(x){return x.status==='uploading'||x.status==='waiting';}))finalizePool();
}
function cancelTask(t){
  if(t._xhr){try{t._xhr.abort();}catch(e){}t._xhr=null;}
  t.status='cancelled';
  if(t.upload_id){
    delete _myUids[t.upload_id];
    var rfd=new FormData();rfd.append('upload_id',t.upload_id);rfd.append('release','1');
    fetch(P+'/admin/upload/cancel',{method:'POST',body:rfd}).catch(function(){});
  }
  queue=queue.filter(function(x){return x.id!==t.id;});
  removeTaskRow(t);refreshStats();
}
function pauseTask(t){
  if(t.status==='uploading'||t.status==='waiting'){
    if(t._xhr){try{t._xhr.abort();}catch(e){}t._xhr=null;}
    t.status='paused';updateTaskRow(t);renderBulk();refreshStats();
  }
}
function resumeTask(t){
  if(t.status==='paused'){t.status='waiting';updateTaskRow(t);renderBulk();pump();}
}
function retryTask(t){
  t.status='waiting';t.err=null;
  updateTaskRow(t);renderBulk();pump();
}
function buildTaskRow(t){
  var r=document.createElement('div');r.className='task';r.setAttribute('data-id',t.id);
  var ic=document.createElement('div');ic.className='tic';ic.textContent='📄';
  var nm=document.createElement('div');nm.className='nm';
  var pn=document.createElement('div');pn.className='pn';pn.textContent=t.name;pn.title=t.path;
  var ps=document.createElement('div');ps.className='ps';
  var extra='';
  if(t.status==='uploading'||t.status==='waiting'||t.status==='paused'){
    var dc=0;for(var kk in t.done)dc++;
    extra=' · 分片 '+dc+'/'+t.total;
  }
  ps.textContent=(t.path!==t.name?t.path+' · ':'')+fmt(t.size)+extra+(t.err?(' · '+t.err):'');
  nm.appendChild(pn);nm.appendChild(ps);
  r.appendChild(ic);r.appendChild(nm);
  var tb=document.createElement('div');tb.className='tbar';
  var ti=document.createElement('i');
  var pct=t.size?Math.round(t.uploaded/t.size*100):0;
  ti.style.width=pct+'%';tb.appendChild(ti);
  var st=document.createElement('div');st.className='st';
  r.appendChild(tb);r.appendChild(st);
  if(t.status==='failed'){
    tb.classList.add('err');
    st.className='st err';st.textContent='失败';
    var rb=document.createElement('button');rb.className='btn btn-ghost btn-xs';rb.textContent='重试';
    rb.onclick=function(){retryTask(t);};r.appendChild(rb);
  }else if(t.status==='waiting'){
    st.textContent='等待中';
  }else if(t.status==='paused'){
    st.textContent='已暂停 '+pct+'%';
    var rs=document.createElement('button');rs.className='btn btn-add btn-xs';rs.textContent='继续';
    rs.onclick=function(){resumeTask(t);};r.appendChild(rs);
  }else if(t.status==='done'){
    tb.classList.add('ok');
    st.className='st done';st.textContent='✓ 已完成';
  }else{
    st.textContent=pct+'% · '+fmt(t.uploaded);
    var pz=document.createElement('button');pz.className='btn btn-ghost btn-xs';pz.textContent='暂停';
    pz.onclick=function(){pauseTask(t);};r.appendChild(pz);
  }
  var cx=document.createElement('button');cx.className='btn btn-danger btn-xs';cx.textContent='取消';
  cx.onclick=function(){cancelTask(t);};
  r.appendChild(cx);
  return r;
}
function updateTasksum(){
  var s=document.getElementById('tasksum');
  if(!s)return;
  if(!queue.length){s.textContent='';}
  else{var up=queue.filter(function(x){return x.status==='uploading'||x.status==='waiting';}).length;
    s.textContent=up?(' · 上传中 '+up+' 个'):(' · 队列 '+queue.length+' 个');}
}
function renderTaskPager(){
  var tp=document.getElementById('taskPager');
  if(!tp)return;
  tPageCount=Math.max(1,Math.ceil(queue.length/TPAGE_SIZE));
  if(tPage>tPageCount)tPage=tPageCount;
  var tj0=document.getElementById('tpJump');if(tj0)tj0.value=tPage;
  if(queue.length<=TPAGE_SIZE){tp.style.display='none';return;}
  tp.style.display='flex';
  document.getElementById('tpInfo').textContent='任务 '+tPage+' / '+tPageCount+' 页 · 共 '+queue.length+' 个';
  var pv=document.getElementById('tpPrev'),nx=document.getElementById('tpNext');
  if(pv)pv.disabled=tPage<=1;
  if(nx)nx.disabled=tPage>=tPageCount;
  var j=document.getElementById('tpJump');if(j)j.max=tPageCount;
}
function renderTasks(){
  var box=document.getElementById('tasks');
  box.innerHTML='';
  renderBulk();
  updateTasksum();
  renderTaskPager();
  if(!queue.length){box.style.display='none';return;}
  box.style.display='block';
  queue.slice((tPage-1)*TPAGE_SIZE,tPage*TPAGE_SIZE).forEach(function(t){
    box.appendChild(buildTaskRow(t));
  });
}
function updateTaskProgress(t){
  var r=document.querySelector('#tasks .task[data-id="'+t.id+'"]');
  if(!r)return;
  var pct=t.size?Math.round(t.uploaded/t.size*100):0;
  var ti=r.querySelector('.tbar i');if(ti)ti.style.width=pct+'%';
  var st=r.querySelector('.st');if(st)st.textContent=pct+'% · '+fmt(t.uploaded);
  var ps=r.querySelector('.ps');if(ps){
    var dc=0;for(var kk in t.done)dc++;
    ps.textContent=(t.path!==t.name?t.path+' · ':'')+fmt(t.size)+' · 分片 '+dc+'/'+t.total+(t.err?(' · '+t.err):'');
  }
}
function updateTaskRow(t){
  var r=document.querySelector('#tasks .task[data-id="'+t.id+'"]');
  if(!r)return;
  r.replaceWith(buildTaskRow(t));
}
function removeTaskRow(t){
  var r=document.querySelector('#tasks .task[data-id="'+t.id+'"]');
  if(r)r.remove();
  renderBulk();
  updateTasksum();
  if(!queue.length){renderTasks();return;}
  renderTaskPager();
}
function renderBulk(){
  var canPause=queue.some(function(t){return t.status==='uploading'||t.status==='waiting';});
  var canResume=queue.some(function(t){return t.status==='paused';});
  var canRetry=queue.some(function(t){return t.status==='failed';});
  var canCancel=queue.length>0;
  var bar=document.getElementById('bulkBar');if(bar)bar.style.display=queue.length?'flex':'none';
  var b1=document.getElementById('btnPauseAll');if(b1)b1.disabled=!canPause;
  var b2=document.getElementById('btnResumeAll');if(b2)b2.disabled=!canResume;
  var b3=document.getElementById('btnRetryAll');if(b3)b3.disabled=!canRetry;
  var b5=document.getElementById('btnCancelFailed');if(b5)b5.disabled=!canRetry;
  var b4=document.getElementById('btnCancelAll');if(b4)b4.disabled=!canCancel;
  var st=document.getElementById('taskStatus');
  if(st){
    var active=queue.some(function(t){return t.status==='uploading'||t.status==='waiting';});
    if(!active){st.style.display='none';st.innerHTML='';}
    else{
      st.style.display='flex';st.innerHTML='';
      var done=0,up=0,wait=0,pause=0,fail=0;
      queue.forEach(function(t){
        if(t.status==='done')done++;
        else if(t.status==='uploading')up++;
        else if(t.status==='waiting')wait++;
        else if(t.status==='paused')pause++;
        else if(t.status==='failed')fail++;
      });
      var item=function(cls,label,n){
        if(n<=0)return;
        var s=document.createElement('div');s.className='stat '+cls;
        s.innerHTML='<b>'+n+'</b><span>'+label+'</span>';
        st.appendChild(s);
      };
      item('total','文件总数',queue.length);
      item('done','已完成',done);
      item('up','上传中',up);
      item('wait','等待',wait);
      item('pause','暂停',pause);
      item('fail','失败',fail);
    }
  }
}
function retryAll(){
  var any=false;
  queue.forEach(function(t){if(t.status==='failed'){t.status='waiting';t.err=null;any=true;}});
  if(any){renderTasks();pump();}
}
function addBatch(batch,targetDir){
  if(!batch.length)return;
  clearTimeout(_doneTimer);
  _batchSize=batch.length;
  if(typeof targetDir!=='string')targetDir=dir;
  batch.sort(function(a,b){return a.f.size-b.f.size;});
  var total=0;
  for(var i=0;i<batch.length;i++)total+=batch[i].f.size;
  fetch(P+'/api/files').then(function(r){return r.json();}).then(function(j){
    var used=j.used,quota=j.quota,rsrv=j.reserved||0;
    var inflight=0;
    queue.forEach(function(t){if(t.status==='waiting')inflight+=t.size;});
    var avail=quota-used-rsrv-(j.pending||0)-inflight;
    if(total>avail){
      toast(false,'所选内容共 '+fmt(total)+'，可用空间 '+fmt(Math.max(0,avail))+'，超出容量，未添加');
      return;
    }
    batch.forEach(function(x){addFile(x.f,x.rel,targetDir);});
    tPageCount=Math.max(1,Math.ceil(queue.length/TPAGE_SIZE));
    if(tPage>tPageCount)tPage=tPageCount;
    renderTasks();
  }).catch(function(){
    batch.forEach(function(x){addFile(x.f,x.rel,targetDir);});
    tPageCount=Math.max(1,Math.ceil(queue.length/TPAGE_SIZE));
    if(tPage>tPageCount)tPage=tPageCount;
    renderTasks();
  });
}
function onPicked(files){
  var batch=[];
  Array.prototype.forEach.call(files,function(f){
    var rel=f.webkitRelativePath||f.name;
    batch.push({f:f,rel:rel});
  });
  addBatch(batch,dir);
}
function gatherDropped(entries, cb){
  var batch=[];
  var pending=0;
  function done(){if(pending===0)cb(batch);}
  function walk(entry){
    if(!entry)return;
    pending++;
    if(entry.isFile){
      entry.file(function(f){
        batch.push({f:f,rel:entry.fullPath.split('/').filter(Boolean).join('/')});
        pending--;done();
      });
    }else if(entry.isDirectory){
      var rd=entry.createReader();var acc=[];
      (function next(){
        rd.readEntries(function(es){
          if(!es.length){
            acc.forEach(function(x){walk(x);});
            pending--;done();
            return;
          }
          acc=acc.concat(es);next();
        });
      })();
    }else{pending--;done();}
  }
  entries.forEach(function(e){walk(e);});
  if(!entries.length)done();
}
function render(){
  var items=DATA.filter(function(it){return inDir(dir,it.path);});
  if(q){var v=q.toLowerCase();items=items.filter(function(it){return it.name.toLowerCase().indexOf(v)>=0;});}
  items.sort(function(a,b){return (a.is_dir===b.is_dir)?a.name.localeCompare(b.name):(a.is_dir?-1:1);});
  var per=dir?(PAGE_SIZE-1):PAGE_SIZE;
  pageCount=Math.max(1,Math.ceil(items.length/per));
  if(page>pageCount)page=pageCount;
  var pj0=document.getElementById('pgJump');if(pj0)pj0.value=page;
  var g=document.getElementById('grid');
  g.innerHTML='';
  g.className='grid'+(selMode?' selmode':'');
  if(dir){
    var parent=dir.split('/').filter(Boolean).slice(0,-1).join('/');
    var bk=document.createElement('div');bk.className='card file-card back-card';
    var bt=document.createElement('div');bt.className='tile';bt.textContent='↰';
    var bm=document.createElement('div');bm.className='meta';
    var bn=document.createElement('div');bn.className='name';bn.textContent='返回上一级';
    var bs=document.createElement('div');bs.className='sub';bs.textContent=parent?('📁 '+parent):'📁 根目录';
    bm.appendChild(bn);bm.appendChild(bs);
    bk.appendChild(bt);bk.appendChild(bm);
    bk.onclick=function(){nav(parent);};
    g.appendChild(bk);
  }
  if(!items.length){
    var empty=document.createElement('div');empty.className='empty';
    empty.innerHTML='<div class="big">📤</div><div style="font-weight:700;color:var(--ink)">'+(dir?'该文件夹为空':'这里还没有内容')+'</div><div style="margin-top:6px">'+(dir?'':'拖拽文件/文件夹到上方，或点击按钮上传')+'</div>';
    g.appendChild(empty);
  }
  items.slice((page-1)*per,page*per).forEach(function(it){
    var c=document.createElement('div');c.className='card file-card';
    if(selMode)c.classList.add('selmode-card');
    c.classList.toggle('sel',inSel(it.path));
    var chk=document.createElement('div');chk.className='chk'+(inSel(it.path)?' on':'');chk.textContent=inSel(it.path)?'✓':'';
    c.appendChild(chk);
    var top=document.createElement('div');top.className='f-top';
    var t=document.createElement('div');t.className='tile';t.style.background=it.tile;t.textContent=it.icon;
    var m=document.createElement('div');m.className='meta';
    var n=document.createElement('div');n.className='name';n.title=it.name;n.textContent=it.name;
    var s=document.createElement('div');s.className='sub';
    s.textContent=it.is_dir?(it.file_count+' 个文件 · '+fmt(it.size)):(fmt(it.size)+' · '+it.mtime);
    m.appendChild(n);m.appendChild(s);top.appendChild(t);top.appendChild(m);
    var bot=document.createElement('div');bot.className='f-bot';
    var grp=document.createElement('div');grp.style.cssText='display:flex;gap:8px;align-items:center';
    var db=document.createElement('button');db.className='btn btn-danger btn-xs';db.textContent='🗑';
    db.onclick=function(e){e.stopPropagation();del(it.path,it.is_dir);};
    grp.appendChild(db);
    if(it.is_dir){
      var ob=document.createElement('button');ob.className='btn btn-ghost btn-xs';ob.textContent='打开';
      ob.onclick=function(e){e.stopPropagation();nav(it.path);};grp.appendChild(ob);
      var z=document.createElement('button');z.className='btn btn-primary btn-xs';z.textContent='⬇ ZIP';
      z.onclick=function(e){e.stopPropagation();zipOne(it.path);};grp.appendChild(z);
    }else{
      var a=document.createElement('a');a.className='btn btn-ghost btn-xs';a.href=P+'/d?p='+encodeURIComponent(it.path);a.textContent='下载';
      a.addEventListener('click',function(e){e.stopPropagation();});
      grp.appendChild(a);
    }
    bot.appendChild(grp);c.appendChild(top);c.appendChild(bot);
    if(selMode)c.onclick=function(){toggleSel(it.path);};
    g.appendChild(c);
  });
  var fc=0;DATA.forEach(function(x){if(!x.is_dir)fc++;});
  renderStats(fc);
  var qb=document.getElementById('qbar');if(qb)qb.style.width=(QUOTA?Math.min(100,USED/QUOTA*100):0)+'%';
  var pg=document.getElementById('pager');
  if(pg){
    if(items.length<=PAGE_SIZE){pg.style.display='none';}
    else{
      pg.style.display='flex';
      document.getElementById('pgInfo').textContent='第 '+page+' / '+pageCount+' 页 · 共 '+items.length+' 项';
      var pv=document.getElementById('pgPrev'),nx=document.getElementById('pgNext');
      if(pv)pv.disabled=page<=1;
      if(nx)nx.disabled=page>=pageCount;
      var j=document.getElementById('pgJump');if(j)j.max=pageCount;
    }
  }
  var cr=document.getElementById('crumbs');cr.innerHTML='';
  var root=document.createElement('a');root.textContent='🏠 根目录';root.href='javascript:void 0';root.onclick=function(){nav('');};cr.appendChild(root);
  if(dir){
    var acc='';
    dir.split('/').forEach(function(s){
      acc=acc?acc+'/'+s:s;
      var sp=document.createElement('span');sp.className='sep';sp.textContent='/';cr.appendChild(sp);
      var a=document.createElement('a');a.textContent=s;a.href='javascript:void 0';
      a.onclick=function(){nav(acc);};cr.appendChild(a);
    });
  }
}
function renderStats(fc){
  var rsvDisp=0;
  queue.forEach(function(t){rsvDisp+=Math.max(0,t.size-((_upSnap&&_upSnap[t.id])?(_upSnap[t.id]):t.uploaded));});
  var free=Math.max(0,QUOTA-USED-rsvDisp-PENDING);
  var over=(USED+rsvDisp+PENDING)>QUOTA;
  document.getElementById('st-count').innerHTML='<b>'+fc+'</b><span>文件</span>';
  document.getElementById('st-size').innerHTML='<b>'+fmt(USED)+'</b><span>已用空间</span>';
  document.getElementById('st-quota').innerHTML='<b>'+fmt(free)+'</b><span>可用空间</span>';
  var pUsed=QUOTA?Math.min(100,USED/QUOTA*100):0;
  var pPending=QUOTA?Math.min(Math.max(0,100-pUsed),PENDING/QUOTA*100):0;
  var pReserved=QUOTA?Math.min(Math.max(0,100-pUsed-pPending),rsvDisp/QUOTA*100):0;
  var qb=document.getElementById('qbar');if(qb)qb.style.width=pUsed+'%';
  var q2=document.getElementById('qbar2');if(q2)q2.style.width=pPending+'%';
  var q3=document.getElementById('qbar3');if(q3)q3.style.width=pReserved+'%';
  var ql=document.getElementById('qlbl');
  if(ql)ql.textContent=over?('⚠ 已用 '+fmt(USED)+' + 预留/缓存 '+fmt(RESERVED+PENDING)+' 超出容量 '+fmt(QUOTA)+'，请删除文件'):('已用 '+fmt(USED)+' · 预留 '+fmt(rsvDisp)+' · 缓存 '+fmt(PENDING)+' · 可用 '+fmt(free)+' · 总量 '+fmt(QUOTA));
}
function refreshStats(){
  snapUp();
  fetch(P+'/api/stats').then(function(r){return r.json();}).then(function(j){
    USED=j.used;QUOTA=j.quota;PENDING=j.pending||0;RESERVED=j.reserved||0;
    var fc=0;if(DATA)DATA.forEach(function(x){if(!x.is_dir)fc++;});
    renderStats(fc);
  }).catch(function(){});
}
setInterval(function(){
  if(queue.some(function(t){return t.status==='uploading'||t.status==='waiting';}))refreshStats();
},2500);
function del(path,isDir){
  var name=isDir?('文件夹「'+path+'」（含全部内容）'):('「'+path+'」');
  if(!confirm('确认删除 '+name+'？此操作不可恢复。'))return;
  var fd=new FormData();fd.append('path',path);fd.append('is_dir',isDir?1:0);
  fetch(P+'/admin/delete',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'已删除 '+path);refresh();}else{toast(false,j.error||'删除失败');}
  }).catch(function(){toast(false,'删除失败');});
}
function refresh(){
  snapUp();
  fetch(P+'/api/files').then(function(r){return r.json();}).then(function(j){
    DATA=j.data;USED=j.used;QUOTA=j.quota;PENDING=j.pending||0;render();
  }).catch(function(){});
}
function nav(p){dir=p;page=1;try{history.pushState(null,'','#/'+p);}catch(e){}render();}
window.addEventListener('popstate',function(){dir=(location.hash||'#/').slice(2).split('/').filter(Boolean).join('/');page=1;render();});
document.getElementById('q').addEventListener('input',function(){q=this.value;page=1;render();});
var pgPrev=document.getElementById('pgPrev');
if(pgPrev){pgPrev.onclick=function(){if(page>1){page--;render();}};}
var pgNext=document.getElementById('pgNext');
if(pgNext){pgNext.onclick=function(){if(page<pageCount){page++;render();}};}
var pgJump=document.getElementById('pgJump');
if(pgJump){pgJump.onclick=function(){this.select();};
  var jumpG=function(){var v=parseInt(pgJump.value);if(isNaN(v)){pgJump.value=page;return;}page=Math.max(1,Math.min(pageCount,v));pgJump.value=page;render();};
  pgJump.addEventListener('keydown',function(e){if(e.key==='Enter'){jumpG();}});
  pgJump.addEventListener('blur',jumpG);
  var pgGo=document.getElementById('pgGo');
  if(pgGo){pgGo.onclick=jumpG;}}
var tpPrev=document.getElementById('tpPrev');
if(tpPrev){tpPrev.onclick=function(){if(tPage>1){tPage--;renderTasks();}};}
var tpNext=document.getElementById('tpNext');
if(tpNext){tpNext.onclick=function(){if(tPage<tPageCount){tPage++;renderTasks();}};}
var tpJump=document.getElementById('tpJump');
if(tpJump){tpJump.onclick=function(){this.select();};
  var jumpT=function(){var v=parseInt(tpJump.value);if(isNaN(v)){tpJump.value=tPage;return;}tPage=Math.max(1,Math.min(tPageCount,v));tpJump.value=tPage;renderTasks();};
  tpJump.addEventListener('keydown',function(e){if(e.key==='Enter'){jumpT();}});
  tpJump.addEventListener('blur',jumpT);
  var tpGo=document.getElementById('tpGo');
  if(tpGo){tpGo.onclick=jumpT;}}
(function(){
  var zone=document.getElementById('zone'),fi=document.getElementById('fileInput'),di=document.getElementById('dirInput');
  if(di){di.setAttribute('webkitdirectory','');di.setAttribute('directory','');}
  zone.addEventListener('click',function(e){if(e.target.tagName!=='BUTTON'&&e.target.tagName!=='INPUT'&&e.target.closest('.acts')===null)fi.click();});
  zone.addEventListener('dragover',function(e){e.preventDefault();zone.classList.add('drag');});
  zone.addEventListener('dragleave',function(){zone.classList.remove('drag');});
  zone.addEventListener('drop',function(e){
    e.preventDefault();zone.classList.remove('drag');
    var items=e.dataTransfer.items||[];
    var entries=[];var plain=[];
    var startDir=dir;
    for(var i=0;i<items.length;i++){
      var ent=items[i].webkitGetAsEntry?items[i].webkitGetAsEntry():null;
      if(ent){entries.push(ent);}
      else if(items[i].getAsFile){plain.push(items[i].getAsFile());}
    }
    if(!entries.length){for(var j=0;j<e.dataTransfer.files.length;j++)plain.push(e.dataTransfer.files[j]);}
    var batch=[];plain.forEach(function(f){batch.push({f:f,rel:f.name});});
    if(entries.length){
      gatherDropped(entries,function(gb){addBatch(batch.concat(gb),startDir);});
    }else{
      addBatch(batch,startDir);
    }
  });
  document.getElementById('btnFiles').onclick=function(e){e.stopPropagation();fi.click();};
  document.getElementById('btnFolder').onclick=function(e){e.stopPropagation();di.click();};
  fi.addEventListener('change',function(){if(fi.files.length)onPicked(fi.files);fi.value='';});
  di.addEventListener('change',function(){if(di.files.length)onPicked(di.files);di.value='';});
})();
if(MSG)toast(MSG[0]==='ok',MSG[1]);
var bsel=document.getElementById('btnSel');
if(bsel){bsel.onclick=function(){selMode=!selMode;render();renderSel();};}
var bnf=document.getElementById('btnNewFolder');
if(bnf){bnf.onclick=function(){
  var name=prompt('新建文件夹名称','新建文件夹');
  if(name===null||!name.trim())return;
  var nm=name.trim();
  if(nm.indexOf('/')>=0||nm.indexOf('\\\\')>=0){toast(false,'文件夹名称不能包含斜杠');return;}
  var p=dir?(dir+'/'+nm):nm;
  var fd=new FormData();fd.append('path',p);
  fetch(P+'/admin/mkdir',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'已创建文件夹 '+p);refresh();}
    else{toast(false,j.error||'创建失败');}
  }).catch(function(){toast(false,'创建失败');});
};}
var bzip=document.getElementById('selZipBtn');
if(bzip){bzip.onclick=zipDown;}
var bclear=document.getElementById('selClearBtn');
if(bclear){bclear.onclick=function(){selected=[];selMode=false;render();renderSel();};}
var ball=document.getElementById('selAllBtn');
if(ball){ball.onclick=selAll;}
var bdel=document.getElementById('selDelBtn');
if(bdel){bdel.onclick=batchDel;}
var bpa=document.getElementById('btnPauseAll');
if(bpa){bpa.onclick=function(){queue.forEach(function(t){if(t.status==='uploading'||t.status==='waiting')pauseTask(t);});};}
var bra=document.getElementById('btnResumeAll');
if(bra){bra.onclick=function(){queue.forEach(function(t){if(t.status==='paused')resumeTask(t);});};}
var brt=document.getElementById('btnRetryAll');
if(brt){brt.onclick=retryAll;}
function cancelFailed(){
  var failed=[];
  queue.forEach(function(t){if(t.status==='failed')failed.push(t);});
  if(!failed.length){toast(false,'没有失败的上传任务');return;}
  if(!confirm('取消 '+failed.length+' 个失败的上传任务？其分片将保留为缓存。'))return;
  failed.forEach(function(t){cancelTask(t);});
  if(!queue.some(function(x){return x.status==='uploading'||x.status==='waiting'||x.status==='paused';})){
    var n=0;queue.forEach(function(t){if(t.status==='done')n++;});
    queue=[];
    renderBulk();
    updateTasksum();
    showDone(n);
  }
}
var bcf=document.getElementById('btnCancelFailed');
if(bcf){bcf.onclick=cancelFailed;}
var bca=document.getElementById('btnCancelAll');
if(bca){bca.onclick=function(){
  if(!queue.length){toast(false,'没有进行中的上传');return;}
  if(!confirm('取消全部 '+queue.length+' 个上传任务？分片将保留，可稍后继续。'))return;
  queue.slice().forEach(function(t){cancelTask(t);});
};}
var blog=document.getElementById('btnLog');
if(blog){blog.onclick=function(){
  var m=document.getElementById('logModal');m.style.display='flex';
  document.getElementById('logBody').textContent='加载中…';
  fetch(P+'/admin/log').then(function(r){return r.json();}).then(function(j){
    document.getElementById('logBody').textContent=j.log||j.error||'';
  }).catch(function(){document.getElementById('logBody').textContent='加载失败';});
};}
var lc=document.getElementById('logClose');
if(lc){lc.onclick=function(){document.getElementById('logModal').style.display='none';};}
var lm=document.getElementById('logModal');
if(lm){lm.addEventListener('click',function(e){if(e.target===lm)lm.style.display='none';});}
var bvc=document.getElementById('btnViewCache');
if(bvc){bvc.onclick=function(){
  var m=document.getElementById('cacheModal');m.style.display='flex';
  document.getElementById('cacheBody').textContent='加载中…';
  document.getElementById('cacheSum').textContent='';
  fetch(P+'/admin/cache').then(function(r){return r.json();}).then(function(j){
    document.getElementById('cacheSum').textContent='共 '+j.count+' 个会话';
    var body=document.getElementById('cacheBody');
    if(!j.items.length){body.innerHTML='<div style="padding:30px;text-align:center;color:var(--muted)">暂无缓存</div>';return;}
    var h='<table class="cache-table"><thead><tr><th>HASH</th><th>文件名</th><th>分片</th><th>大小</th><th>最后活动</th></tr></thead><tbody>';
    j.items.forEach(function(it){
      h+='<tr><td class="h">'+esc(it.hash)+'</td><td class="fn">'+esc(it.path)+'</td><td class="num">'+it.chunks_done+'/'+it.chunks_total+'</td><td class="num">'+esc(it.bytes_h)+'</td><td class="num">'+esc(it.last_activity)+'</td></tr>';
    });
    h+='</tbody></table>';
    body.innerHTML=h;
  }).catch(function(){document.getElementById('cacheBody').textContent='加载失败';});
};}
var ccl=document.getElementById('cacheClose');
if(ccl){ccl.onclick=function(){document.getElementById('cacheModal').style.display='none';};}
var cm2=document.getElementById('cacheModal');
if(cm2){cm2.addEventListener('click',function(e){if(e.target===cm2)cm2.style.display='none';});}
var bpurge=document.getElementById('btnPurge');
if(bpurge){bpurge.onclick=function(){
  if(!confirm('清除所有未完成上传的临时分片？（已完成上传的文件不受影响）'))return;
  fetch(P+'/admin/upload/clear',{method:'POST'}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'已清理 '+j.freed_h+' 临时分片');refresh();}
    else{toast(false,j.error||'清理失败');}
  }).catch(function(){toast(false,'清理失败');});
};}
var bpwd=document.getElementById('btnPwd');
if(bpwd){bpwd.onclick=function(){
  var oldp=prompt('请输入当前管理员密码：');
  if(oldp===null)return;
  var newp=prompt('请输入新密码（至少 5 位）：');
  if(newp===null||newp.length<5){toast(false,'新密码至少 5 位');return;}
  var fd=new FormData();fd.append('old_password',oldp);fd.append('new_password',newp);
  fetch(P+'/admin/password',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'密码已修改');}else{toast(false,j.error||'修改失败');}
  }).catch(function(){toast(false,'修改失败');});
};}
var bquota=document.getElementById('btnQuota');
if(bquota){bquota.onclick=function(){
  var cur=(QUOTA/1073741824).toFixed(1);
  var gb=prompt('设置池最大容量（GB，范围 0.5 ~ 200）：', cur);
  if(gb===null)return;
  var v=parseFloat(gb);
  if(isNaN(v)||v<0.5||v>200){toast(false,'容量需在 0.5 ~ 200 GB 之间');return;}
  if(v*1073741824 < USED){toast(false,'目标容量小于当前已用 '+fmt(USED)+'，请先删除部分文件');return;}
  var fd=new FormData();fd.append('gb',v);
  fetch(P+'/admin/quota',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(j){
    if(j.ok){toast(true,'池容量已设为 '+j.quota_h);refreshStats();}
    else{toast(false,j.error||'设置失败');}
  }).catch(function(){toast(false,'设置失败');});
};}
renderSel();
render();renderTasks();
</script>"""

ADMIN_HTML = """<section class="hero">
  <div class="hrow">
    <div class="brand">
      <div class="logo">🔐</div>
      <div><h1>管理后台</h1></div>
    </div>
  </div>
  <div class="acts">
    <a class="btn btn-white btn-sm" href="__PREFIX__/">🏠 回到前台</a>
    <a class="btn btn-ghost btn-sm" href="__PREFIX__/admin/logout">🚪 退出</a>
    <span class="act-sep"></span>
    <button class="btn btn-multi btn-sm" id="btnViewCache">📋 查看缓存</button>
    <button class="btn btn-multi btn-sm" id="btnPurge">🧹 清理缓存</button>
    <span class="act-sep"></span>
    <button class="btn btn-multi btn-sm" id="btnQuota">⚖️ 修改容量</button>
    <button class="btn btn-multi btn-sm" id="btnPwd">🔑 修改密码</button>
    <span class="act-sep"></span>
    <button class="btn btn-multi btn-sm" id="btnLog">📄 日志</button>
  </div>
  <div class="stats">
    <div class="stat" id="st-count"><b>-</b><span>文件</span></div>
    <div class="stat" id="st-size"><b>-</b><span>资源总量</span></div>
    <div class="stat" id="st-quota"><b>-</b><span>池容量</span></div>
  </div>
  <div class="quota"><div class="bar"><i id="qbar"></i><i id="qbar2"></i><i id="qbar3"></i></div><div class="lbl" id="qlbl"></div></div>
</section>
<div class="panel">
  <h3>☁️ 上传资源 <span id="tasksum" style="font-size:12px;color:var(--muted);font-weight:600"></span></h3>
  <div id="taskStatus" class="task-status"></div>
  <div class="zone" id="zone">
    <div class="big">☁️</div>
    <div style="font-weight:700;color:var(--ink);font-size:15px">拖拽文件或文件夹到此处，或点击选择文件</div>
    <div class="tip">3 并发分片 · 断点可续传</div>
    <div class="acts" style="justify-content:center;margin-top:14px">
      <button class="btn btn-add" id="btnFiles">📄 选择文件</button>
      <button class="btn btn-primary" id="btnFolder" style="padding:9px 22px">📁 选择文件夹</button>
    </div>
  </div>
  <input type="file" id="fileInput" multiple style="display:none">
  <input type="file" id="dirInput" webkitdirectory multiple style="display:none">
  <div class="acts" id="bulkBar" style="justify-content:center;margin-top:14px">
    <button class="btn btn-ghost btn-sm" id="btnPauseAll">⏸ 全部暂停</button>
    <button class="btn btn-add btn-sm" id="btnResumeAll">▶ 全部继续</button>
    <button class="btn btn-add btn-sm" id="btnRetryAll">↻ 全部重试</button>
    <button class="btn btn-ghost btn-sm" id="btnCancelFailed">✖ 取消失败</button>
    <button class="btn btn-danger btn-sm" id="btnCancelAll">✕ 全部取消</button>
  </div>
  <div id="tasks" style="margin-top:16px"></div>
  <div class="pager" id="taskPager" style="display:none">
    <button class="btn btn-ghost btn-xs" id="tpPrev">← 上一页</button>
    <span id="tpInfo"></span>
    <button class="btn btn-ghost btn-xs" id="tpNext">下一页 →</button>
    <span class="pg-jump">跳至<input id="tpJump" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="4">页</span><button class="btn btn-ghost btn-xs" id="tpGo">跳转</button>
  </div>
</div>
<div class="modal" id="logModal" style="display:none">
  <div class="modal-card">
    <div class="modal-head"><b>📄 服务器日志（最近 300 行）</b><button class="btn btn-ghost btn-xs" id="logClose">✕ 关闭</button></div>
    <pre id="logBody">加载中…</pre>
  </div>
</div>
<div class="modal" id="cacheModal" style="display:none">
  <div class="modal-card">
    <div class="modal-head"><b>📋 上传缓存（临时分片）</b><span id="cacheSum" style="font-size:12px;color:var(--muted);font-family:'Courier New',monospace"></span><button class="btn btn-ghost btn-xs" id="cacheClose">✕ 关闭</button></div>
    <div class="cache-body" id="cacheBody">加载中…</div>
  </div>
</div>
<nav class="crumbs" id="crumbs"></nav>
<div class="search"><span class="m">🔍</span><input id="q" type="text" placeholder="搜索当前目录…" autocomplete="off"></div>
<div class="gtool">
  <button class="btn btn-multi btn-sm" id="btnSel">☑ 多选</button>
  <button class="btn btn-add btn-sm" id="btnNewFolder">📁 新建文件夹</button>
</div>
<div class="grid" id="grid"></div>
<div class="pager" id="pager" style="display:none">
  <button class="btn btn-ghost btn-xs" id="pgPrev">← 上一页</button>
  <span id="pgInfo"></span>
  <button class="btn btn-ghost btn-xs" id="pgNext">下一页 →</button>
  <span class="pg-jump">跳至<input id="pgJump" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="4">页</span><button class="btn btn-ghost btn-xs" id="pgGo">跳转</button>
</div>
<div class="selbar" id="selbar" style="display:none">
  <span class="cnt" id="selcount">已选 0 项</span>
  <button class="btn btn-ghost btn-xs" id="selAllBtn">全选当前目录</button>
  <button class="btn btn-primary btn-sm" id="selZipBtn">↓ 打包下载 ZIP</button>
  <button class="btn btn-danger btn-sm" id="selDelBtn">🗑 删除</button>
  <button class="btn btn-ghost btn-sm" id="selClearBtn">取消</button>
</div>
"""
