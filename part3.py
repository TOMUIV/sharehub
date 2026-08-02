
PUBLIC_SCRIPT = """<script>
var P="__PREFIX__";
var INIT=__INIT__;
var MSG=__MSG__;
var DATA=INIT.data,USED=INIT.used,QUOTA=INIT.quota,PENDING=INIT.pending||0,RESERVED=INIT.reserved||0;
var dir='',q='';
var PAGE_SIZE=12,page=1,pageCount=1;
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
function nav(p){dir=p;page=1;try{history.pushState(null,'','#/'+p);}catch(e){}render();}
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
    empty.innerHTML='<div class="big">🗂️</div><div style="font-weight:700;color:var(--ink)">'+(dir?'该文件夹为空':'这里空空如也')+'</div><div style="margin-top:6px">'+(dir?'':'管理员上传文件后，就会展示在这里')+'</div>';
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
    var lb=document.createElement('span');lb.style.cssText='font-size:12px;color:var(--muted)';lb.textContent=it.is_dir?'文件夹':(it.icon+' 资源');
    bot.appendChild(lb);
    if(it.is_dir){
      var grp=document.createElement('div');grp.style.cssText='display:flex;gap:8px;align-items:center';
      var b=document.createElement('button');b.className='btn btn-ghost btn-sm';b.textContent='打开';
      b.onclick=function(e){e.stopPropagation();nav(it.path);};
      var z=document.createElement('button');z.className='btn btn-primary btn-sm';z.textContent='⬇ ZIP';
      z.onclick=function(e){e.stopPropagation();zipOne(it.path);};
      grp.appendChild(b);grp.appendChild(z);
      bot.appendChild(grp);
    }else{
      var a=document.createElement('a');a.className='btn btn-primary btn-sm';a.href=P+'/d?p='+encodeURIComponent(it.path);a.textContent='↓ 下载';
      a.addEventListener('click',function(e){e.stopPropagation();});
      bot.appendChild(a);
    }
    c.appendChild(top);c.appendChild(bot);
    if(selMode)c.onclick=function(){toggleSel(it.path);};
    g.appendChild(c);
  });
  var fc=0;DATA.forEach(function(x){if(!x.is_dir)fc++;});
  var free=Math.max(0,QUOTA-USED-RESERVED-PENDING);
  document.getElementById('st-count').innerHTML='<b>'+fc+'</b><span>文件</span>';
  document.getElementById('st-size').innerHTML='<b>'+fmt(USED)+'</b><span>已用空间</span>';
  document.getElementById('st-quota').innerHTML='<b>'+fmt(free)+'</b><span>可用空间</span>';
  var pUsed=QUOTA?Math.min(100,USED/QUOTA*100):0;
  var pPending=QUOTA?Math.min(Math.max(0,100-pUsed),PENDING/QUOTA*100):0;
  var pReserved=QUOTA?Math.min(Math.max(0,100-pUsed-pPending),RESERVED/QUOTA*100):0;
  var qb=document.getElementById('qbar');if(qb)qb.style.width=pUsed+'%';
  var q2=document.getElementById('qbar2');if(q2)q2.style.width=pPending+'%';
  var q3=document.getElementById('qbar3');if(q3)q3.style.width=pReserved+'%';
  var ql=document.getElementById('qlbl');
  if(ql)ql.textContent='已用 '+fmt(USED)+' · 预留 '+fmt(RESERVED)+' · 缓存 '+fmt(PENDING)+' · 可用 '+fmt(free)+' · 总量 '+fmt(QUOTA);
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
if(MSG)toast(MSG[0]==='ok',MSG[1]);
var bsel=document.getElementById('btnSel');
if(bsel){bsel.onclick=function(){selMode=!selMode;render();renderSel();};}
var bzip=document.getElementById('selZipBtn');
if(bzip){bzip.onclick=zipDown;}
var bclear=document.getElementById('selClearBtn');
if(bclear){bclear.onclick=function(){selected=[];selMode=false;render();renderSel();};}
var ball=document.getElementById('selAllBtn');
if(ball){ball.onclick=selAll;}
renderSel();
render();
</script>"""

PUBLIC_HTML = """<section class="hero">
  <div class="hrow">
    <div class="brand">
      <div class="logo">📁</div>
      <div><h1>共享资源库</h1></div>
    </div>
  </div>
  <div class="acts">
    <a class="btn btn-white btn-sm" href="__PREFIX__/admin">🔐 管理入口</a>
  </div>
  <div class="stats">
    <div class="stat" id="st-count"><b>-</b><span>文件</span></div>
    <div class="stat" id="st-size"><b>-</b><span>资源总量</span></div>
    <div class="stat" id="st-quota"><b>-</b><span>池容量</span></div>
  </div>
  <div class="quota"><div class="bar"><i id="qbar"></i><i id="qbar2"></i><i id="qbar3"></i></div><div class="lbl" id="qlbl"></div></div>
</section>
<nav class="crumbs" id="crumbs"></nav>
<div class="search"><span class="m">🔍</span><input id="q" type="text" placeholder="搜索当前目录…" autocomplete="off"></div>
<div class="gtool">
  <button class="btn btn-multi btn-sm" id="btnSel">☑ 多选</button>
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
  <button class="btn btn-ghost btn-sm" id="selClearBtn">取消</button>
</div>
"""
