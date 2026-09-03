// 医保智审 Web - 客户端交互
(function() {
  'use strict';

  // ---- 编码复制按钮 ----
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('.code-copy');
    if (!btn) return;
    var code = btn.getAttribute('data-code') || '';
    copyText(code).then(function() {
      var orig = btn.textContent;
      btn.classList.add('is-copied');
      btn.textContent = '已复制';
      setTimeout(function() {
        btn.classList.remove('is-copied');
        btn.textContent = orig;
      }, 1200);
    }).catch(function() {
      // fallback提示
      btn.textContent = '失败';
      setTimeout(function() { btn.textContent = '复制'; }, 1200);
    });
  });

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function(resolve, reject) {
      try {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        var ok = document.execCommand('copy');
        document.body.removeChild(ta);
        ok ? resolve() : reject();
      } catch (e) { reject(e); }
    });
  }

  // ---- 顶栏搜索框：保持聚焦 ----
  var topInput = document.querySelector('.topbar-search input');
  var heroInput = document.querySelector('.hero-search input');
  if (topInput && heroInput) {
    // 主页时点击顶栏搜索框不抢焦
    topInput.addEventListener('focus', function() {
      // 滚动到搜索区
    });
  }

  // ---- 结果页：检测 auto mode 时，输入框回车自动提交 ----
  var searchForm = document.querySelector('.searchbar-form');
  if (searchForm) {
    var input = searchForm.querySelector('input[name="q"]');
    if (input) {
      input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          searchForm.submit();
        }
      });
    }
  }

  // ---- 顶栏搜索框：提交时滚到结果 ----
  var topForm = document.querySelector('.topbar-search');
  if (topForm) {
    topForm.addEventListener('submit', function(e) {
      // 允许默认 GET 提交
    });
  }
})();
