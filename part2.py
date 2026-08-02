
PAGE_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📁</text></svg>">
<style>
:root{--paper:#f5efe1;--card:#fdf9ef;--ink:#2a2418;--muted:#8b7f64;--rule:#d9cfb6;--rule2:#b3a486;--accent:#b23a2b;--accent-deep:#8f2d21;--ring:rgba(178,58,43,.25);--shadow:3px 3px 0 rgba(42,36,24,.55)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;background:radial-gradient(1000px 500px at 88% -8%,rgba(178,58,43,.07),transparent 62%),radial-gradient(900px 480px at -8% 8%,rgba(42,36,24,.05),transparent 60%),var(--paper);color:var(--ink);min-height:100vh;-webkit-font-smoothing:antialiased}
body::before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.06;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
.wrap{max-width:1020px;margin:0 auto;padding:30px 20px 92px}
.hero{position:relative;border:2px solid var(--ink);background:var(--card);box-shadow:6px 6px 0 var(--ink);padding:20px 26px 20px;background-image:linear-gradient(rgba(42,36,24,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(42,36,24,.035) 1px,transparent 1px);background-size:22px 22px}
.hero::before{content:"";position:absolute;left:-2px;top:-2px;width:18px;height:18px;background:var(--accent)}
.hrow{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:14px}
.brand{display:flex;align-items:center;gap:14px}
.logo{width:50px;height:50px;background:var(--ink);color:var(--card);display:grid;place-items:center;font-size:25px;box-shadow:3px 3px 0 var(--accent);flex-shrink:0}
.brand h1{font-family:Georgia,"Times New Roman","Songti SC","STSong",serif;font-size:26px;font-weight:700;letter-spacing:.5px}
.brand .sub{font-size:11px;color:var(--muted);margin-top:4px;letter-spacing:1.5px;text-transform:uppercase;font-family:"Courier New",monospace}
.acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.act-sep{width:1px;height:20px;background:rgba(42,36,24,.28);margin:0 2px;align-self:center;flex-shrink:0}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}
.stat{border:1.5px solid var(--ink);background:var(--card);padding:8px 16px;min-width:118px;box-shadow:2px 2px 0 rgba(42,36,24,.35)}
.stat b{display:block;font-family:Georgia,serif;font-size:20px;font-weight:700}
.stat span{font-family:"Courier New",monospace;font-size:10px;letter-spacing:1px;color:var(--muted);text-transform:uppercase}
.quota{margin-top:14px;max-width:520px}
.quota .bar{height:12px;border:1.5px solid var(--ink);background:repeating-linear-gradient(45deg,rgba(42,36,24,.14) 0 4px,transparent 4px 8px);display:flex;overflow:hidden}
.quota .bar i{display:block;height:100%;width:0;transition:width .3s}
#qbar{background:var(--accent)}
#qbar2{background:repeating-linear-gradient(45deg,#caa53d 0 6px,#e2c05c 6px 12px)}
#qbar3{background:repeating-linear-gradient(135deg,#5b8dd6 0 6px,#8fb0e8 6px 12px)}
.quota .lbl{font-family:"Courier New",monospace;font-size:11px;margin-top:7px;color:var(--muted);letter-spacing:.3px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:8px 16px;border-radius:0;font-size:12px;font-weight:700;text-decoration:none;cursor:pointer;transition:transform .1s,box-shadow .1s,background .12s;white-space:nowrap;font-family:inherit;letter-spacing:.4px;text-transform:uppercase;border:1.5px solid var(--ink);background:var(--card);color:var(--ink)}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none;box-shadow:none}
.btn:hover{transform:translate(-1px,-1px);box-shadow:2px 2px 0 var(--ink)}
.btn:active{transform:none;box-shadow:none}
.btn-white{background:var(--ink);color:var(--card)}
.btn-white:hover{background:var(--accent-deep)}
.btn-primary{background:var(--ink);color:var(--card)}
.btn-primary:hover{background:var(--accent-deep)}
.btn-ghost{background:transparent}
.btn-danger{background:var(--accent);color:#fff7ea;border-color:var(--accent-deep)}
.btn-add{background:transparent;border-style:dashed}
.btn-multi{background:var(--card)}
.btn-multi.on{background:var(--ink);color:var(--card)}
.btn-sm{padding:6px 12px;font-size:11px}
.btn-xs{padding:4px 9px;font-size:10.5px}
.selbar{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);display:flex;align-items:center;gap:10px;padding:10px 16px;border:2px solid var(--ink);background:var(--card);box-shadow:5px 5px 0 var(--ink);z-index:50;flex-wrap:wrap;justify-content:center;max-width:96vw}
.selbar .cnt{font-size:13px;font-weight:700;color:var(--accent-deep);margin-right:2px;font-family:Georgia,serif}
.file-card{position:relative}
.chk{position:absolute;top:9px;right:9px;width:22px;height:22px;border:2px solid var(--ink);background:var(--card);display:none;place-items:center;font-size:13px;color:#fff;font-weight:800;line-height:1}
.chk.on{background:var(--accent);border-color:var(--accent)}
.selmode .chk{display:grid}
.file-card.sel{border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
.file-card.selmode-card{cursor:pointer}
.crumbs{display:flex;flex-wrap:wrap;align-items:center;gap:2px;font-size:12.5px;margin:18px 0 4px;font-family:"Courier New",monospace}
.crumbs a{color:var(--accent-deep);text-decoration:none;cursor:pointer;padding:3px 6px;border-bottom:1px solid transparent;font-weight:700}
.crumbs a:hover{border-bottom-color:var(--accent)}
.crumbs .sep{color:var(--rule2);padding:0 2px}
.search{position:relative;margin:12px 0 14px}
.search input{width:100%;padding:11px 16px 11px 40px;border:1.5px solid var(--ink);font-size:14px;background:var(--card);outline:none;font-family:inherit;box-shadow:2px 2px 0 rgba(42,36,24,.35);transition:box-shadow .12s}
.search input:focus{box-shadow:3px 3px 0 var(--ink)}
.search .m{position:absolute;left:13px;top:50%;transform:translateY(-50%);font-size:15px;opacity:.5;pointer-events:none}
.gtool{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
.pager{display:flex;align-items:center;justify-content:center;gap:12px;margin-top:18px;font-family:"Courier New",monospace;font-size:12px;color:var(--muted);flex-wrap:wrap}
.pg-jump{display:flex;align-items:center;gap:4px}
.pg-jump input{width:52px;padding:4px 6px;border:1.5px solid var(--ink);background:var(--card);font-family:"Courier New",monospace;font-size:12px;text-align:center;outline:none;color:var(--ink)}
.pg-jump input:focus{box-shadow:2px 2px 0 var(--ink)}
.card{background:var(--card);border:1.5px solid var(--ink);box-shadow:3px 3px 0 rgba(42,36,24,.5)}
.file-card{display:flex;flex-direction:column;padding:15px;transition:transform .12s,box-shadow .12s;position:relative}
.file-card::before{content:"";position:absolute;top:-1.5px;right:16px;width:30px;height:9px;background:var(--ink)}
.file-card:hover{transform:translate(-2px,-2px);box-shadow:6px 6px 0 var(--ink)}
.back-card{border-style:dashed;cursor:pointer}
.back-card .tile{border-style:dashed}
.back-card:hover{transform:translate(-2px,-2px);box-shadow:6px 6px 0 var(--ink)}
.f-top{display:flex;align-items:center;gap:13px}
.tile{width:50px;height:50px;border:1.5px solid var(--ink);display:grid;place-items:center;font-size:24px;flex-shrink:0}
.name{font-weight:700;font-size:14.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sub{font-size:11px;color:var(--muted);margin-top:3px;font-family:"Courier New",monospace}
.f-bot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:14px;padding-top:12px;border-top:1.5px dashed var(--rule2)}
.f-bot form{display:inline-flex}
.empty{grid-column:1/-1;padding:58px 20px;text-align:center;color:var(--muted);border:2px dashed var(--rule2);background:var(--card)}
.empty .big{font-size:42px;margin-bottom:12px}
.zone{position:relative;border:2px dashed var(--ink);padding:24px 20px;text-align:center;color:var(--muted);cursor:pointer;transition:background .15s;background:rgba(253,249,239,.5)}
.zone::before,.zone::after{content:"";position:absolute;width:14px;height:14px;border:2px solid var(--ink)}
.zone::before{top:-2px;left:-2px;border-right:0;border-bottom:0}
.zone::after{bottom:-2px;right:-2px;border-left:0;border-top:0}
.zone:hover,.zone.drag{background:rgba(178,58,43,.07);color:var(--ink)}
.zone.drag{outline:2px solid var(--accent)}
.zone .big{font-size:34px;margin-bottom:6px}
.zone .tip{font-size:11px;margin-top:7px;opacity:.72;font-family:"Courier New",monospace;letter-spacing:.3px}
.panel{background:var(--card);border:2px solid var(--ink);box-shadow:5px 5px 0 var(--ink);padding:20px;margin-top:30px;margin-bottom:18px}
.panel h3{font-size:14px;font-weight:800;margin-bottom:14px;display:flex;align-items:center;gap:8px;border-bottom:1.5px solid var(--ink);padding-bottom:10px;font-family:Georgia,serif;letter-spacing:.4px}
.task{display:flex;align-items:center;gap:12px;padding:9px 13px;border:1.5px solid var(--rule2);margin-bottom:8px;background:var(--card);box-shadow:2px 2px 0 rgba(42,36,24,.2)}
.task .tic{font-size:20px;flex-shrink:0}
.task .nm{flex:1;min-width:0}
.task .nm .pn{font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.task .nm .ps{font-size:11px;color:var(--muted);font-family:"Courier New",monospace}
.task .tbar{width:88px;height:8px;border:1px solid var(--ink);background:rgba(42,36,24,.08);overflow:hidden;flex-shrink:0}
.task .tbar i{display:block;height:100%;width:0;background:var(--accent);transition:width .15s}
.task .tbar.err{border-color:var(--accent-deep);background:rgba(178,58,43,.1)}
.task .tbar.err i{background:var(--accent-deep)}
.task .tbar.ok{border-color:#1f7a4d;background:rgba(31,122,77,.08)}
.task .tbar.ok i{background:#1f7a4d}
.task .st{font-size:10.5px;color:var(--muted);width:auto;min-width:74px;white-space:nowrap;text-align:right;flex-shrink:0;font-family:"Courier New",monospace}
.task .st.err{color:var(--accent-deep);font-weight:700}
.task .st.done{color:#1f7a4d;font-weight:700}
.tdone{display:flex;align-items:center;gap:10px;padding:14px 16px;border:2px solid #1f7a4d;background:#eef7f0;color:#1f7a4d;font-size:14px;font-weight:700;box-shadow:2px 2px 0 rgba(42,36,24,.2)}
.task-status{display:none;flex-wrap:wrap;gap:8px;margin:12px 0 16px}
.task-status .stat{border:1.5px solid var(--rule);background:var(--paper);min-width:0;padding:6px 14px;box-shadow:1.5px 1.5px 0 rgba(42,36,24,.35)}
.task-status .stat b{font-size:16px}
.task-status .stat span{font-size:9px}
.task-status .stat.total{border-color:var(--ink)}
.task-status .stat.total b{color:var(--ink)}
.task-status .stat.done b{color:#1f7a4d}
.task-status .stat.up b{color:#3b6db5}
.task-status .stat.wait b{color:#a07c15}
.task-status .stat.pause b{color:#777}
.task-status .stat.fail b{color:var(--accent-deep)}
.modal{position:fixed;inset:0;background:rgba(42,36,24,.55);z-index:100;display:flex;align-items:center;justify-content:center;padding:20px}
.modal-card{background:var(--card);border:2px solid var(--ink);box-shadow:8px 8px 0 var(--ink);max-width:860px;width:100%;max-height:82vh;display:flex;flex-direction:column;overflow:hidden}
.modal-head{display:flex;align-items:center;justify-content:space-between;padding:13px 18px;border-bottom:1.5px solid var(--ink);gap:10px}
.modal-head b{font-family:Georgia,serif;font-size:14px}
.cache-body{flex:1;overflow:auto;padding:6px 18px 14px}
.cache-table{width:100%;border-collapse:collapse;font-size:12.5px}
.cache-table th{text-align:left;font-family:"Courier New",monospace;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);border-bottom:1.5px solid var(--ink);padding:9px 10px;position:sticky;top:0;background:var(--card)}
.cache-table td{padding:8px 10px;border-bottom:1px dashed var(--rule2);vertical-align:top}
.cache-table tr:last-child td{border-bottom:none}
.cache-table .h{font-family:"Courier New",monospace;color:var(--accent-deep);font-size:11.5px;word-break:break-all}
.cache-table .fn{font-weight:700}
.cache-table .num{font-family:"Courier New",monospace;white-space:nowrap}
.modal-card pre{flex:1;overflow:auto;margin:0;padding:14px 18px;font-size:12px;line-height:1.55;background:#211d14;color:#d8cdb6;font-family:Consolas,Menlo,monospace;white-space:pre-wrap;word-break:break-all}
footer{text-align:center;margin-top:34px;font-size:11px;color:var(--muted);font-family:"Courier New",monospace;letter-spacing:.5px}
footer a{color:var(--accent-deep);text-decoration:none}
.auth{max-width:400px;margin:9vh auto 0}
.auth-card{padding:34px 30px;background:var(--card);border:2px solid var(--ink);box-shadow:8px 8px 0 var(--ink)}
.auth .logo{width:58px;height:58px;font-size:28px;background:var(--ink);color:var(--card);display:grid;place-items:center;margin:0 auto 16px;box-shadow:3px 3px 0 var(--accent)}
.auth h2{text-align:center;font-family:Georgia,serif;font-size:20px;font-weight:700;margin-bottom:22px;letter-spacing:.5px}
.auth input{width:100%;padding:11px 13px;border:1.5px solid var(--ink);font-size:14px;outline:none;background:var(--paper);box-shadow:2px 2px 0 rgba(42,36,24,.3);transition:box-shadow .12s}
.auth input:focus{box-shadow:3px 3px 0 var(--ink)}
.auth .btn{width:100%;padding:12px;margin-top:14px;font-size:13.5px}
#toasts{position:fixed;top:16px;left:0;right:0;z-index:999;pointer-events:none}
.titem-wrap{position:absolute;left:50%;transform:translateX(-50%);top:0}
.titem{color:#fff;padding:12px 24px;border-radius:0;font-size:13px;font-weight:700;min-width:260px;max-width:82vw;text-align:center;box-shadow:4px 4px 0 rgba(42,36,24,.55);opacity:0;transform:translateY(-18px);transition:opacity .22s ease,transform .22s ease;pointer-events:auto}
.titem.show{opacity:1;transform:translateY(0)}
.titem.ok{background:var(--ink)}
.titem.err{background:var(--accent-deep)}
</style>
<script>
window.fmt=function(b){if(b>=1073741824)return (b/1073741824).toFixed(1)+' GB';if(b>=1048576)return (b/1048576).toFixed(1)+' MB';if(b>=1024)return (b/1024).toFixed(1)+' KB';return b+' B';};
window._toastSeq=0;
window.toast=function(ok,text){
  var box=document.getElementById('toasts');
  if(!box)return;
  var w=document.createElement('div');w.className='titem-wrap';
  var t=document.createElement('div');t.className='titem'+(ok?' ok':' err');
  t.textContent=text;
  w.appendChild(t);
  box.appendChild(w);
  var wraps=box.querySelectorAll('.titem-wrap');
  while(wraps.length>4){wraps[0].remove();wraps=box.querySelectorAll('.titem-wrap');}
  for(var i=0;i<wraps.length;i++){
    if(wraps[i]!==w){
      var cur=parseFloat(wraps[i].style.top)||0;
      wraps[i].style.top=(cur+14)+'px';
    }
  }
  w.style.top='0px';
  w.style.zIndex=String(++window._toastSeq);
  requestAnimationFrame(function(){t.classList.add('show');});
  setTimeout(function(){t.classList.remove('show');setTimeout(function(){w.remove();},240);},3200);
};
window.esc=function(s){return String(s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});};
window.inDir=function(dir,path){var i=dir?path.indexOf(dir+'/'):0;if(dir&&i!==0)return false;var rest=dir?path.slice(dir.length+1):path;return rest.indexOf('/')<0;};
</script>
</head>
<body>
<div id="toasts"></div>
<div class="wrap">
"""

PAGE_FOOT = """
</div>
<script>
if(window.__msg&&window.__msg[1])window.toast(window.__msg[0]==='ok',window.__msg[1]);
</script>
</body>
</html>
"""


def page(title, body):
    return PAGE_HEAD.replace("{title}", title) + body + PAGE_FOOT
