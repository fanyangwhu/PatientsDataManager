// 通用交互
function confirmDelete(pid){
  return confirm('确定删除记录 #' + pid + '？\n该操作不可恢复，但系统会在审计日志中保留该记录的内容快照。');
}

function toggleExtra(btn){
  var items = document.querySelectorAll('.extra-filter');
  var showing = false;
  items.forEach(function(el){ if (el.style.display !== 'none') showing = true; });
  items.forEach(function(el){ el.style.display = showing ? 'none' : 'flex'; });
  btn.textContent = showing ? '更多筛选' : '收起筛选';
}

function openDeleteModal(fid, label, usage){
  var m = document.getElementById('delModal');
  document.getElementById('delForm').action = '/fields/' + fid + '/delete';
  document.getElementById('delTitle').textContent = '删除字段「' + label + '」';
  document.getElementById('delDesc').innerHTML =
    '该字段当前已录入 <strong>' + usage + '</strong> 条数据。彻底删除后这些数据将一并消失且无法恢复。';
  m.classList.add('show');
}

function closeModal(){
  document.getElementById('delModal').classList.remove('show');
}

function toggleEdit(uid){
  var row = document.getElementById('edit-' + uid);
  if (row) row.style.display = (row.style.display === 'none') ? 'table-row' : 'none';
}

// 点击遮罩关闭弹窗
document.addEventListener('click', function(e){
  var m = document.getElementById('delModal');
  if (m && e.target === m) closeModal();
});

// 导出菜单点击外部收起
document.addEventListener('click', function(e){
  var box = document.getElementById('expbox');
  if (box && !e.target.closest('.btn-row')) box.style.display = 'none';
});

// 复制文本到剪贴板（兼容 http 内网环境：navigator.clipboard 在非 HTTPS 下不可用）
function copyText(text, btn){
  var done = function(){
    var old = btn.textContent;
    btn.textContent = '已复制';
    btn.classList.add('btn-copied');
    setTimeout(function(){ btn.textContent = old; btn.classList.remove('btn-copied'); }, 1500);
  };
  if (navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(text).then(done, function(){ fallbackCopy(text, done); });
  } else {
    fallbackCopy(text, done);
  }
}

function fallbackCopy(text, done){
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); done(); } catch(e){ window.prompt('请手动复制下面的地址：', text); }
  document.body.removeChild(ta);
}

// 刷新局域网地址（强制服务端重新探测）
function refreshLan(){
  location.href = location.pathname + '?lan_refresh=' + Date.now();
}
