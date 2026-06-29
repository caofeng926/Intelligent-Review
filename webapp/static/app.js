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

  // ---- 最近搜索 (localStorage) ----
  var RECENT_KEY = 'medaudit_recent_searches_v1';
  var RECENT_MAX = 10;
  var RECENT_MIN_LEN = 1;

  function loadRecentSearches() {
    try {
      var raw = localStorage.getItem(RECENT_KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return [];
      return arr.filter(function(x) { return typeof x === 'string' && x.length >= RECENT_MIN_LEN && x.length <= 80; });
    } catch (e) { return []; }
  }
  function saveRecentSearches(items) {
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(items)); } catch (e) {}
  }
  function addRecentSearch(q) {
    if (!q) return null;
    q = String(q).trim();
    if (q.length < RECENT_MIN_LEN || q.length > 80) return null;
    var items = loadRecentSearches();
    items = items.filter(function(x) { return x !== q; });
    items.unshift(q);
    if (items.length > RECENT_MAX) items = items.slice(0, RECENT_MAX);
    saveRecentSearches(items);
    return items;
  }
  function clearRecentSearches() {
    try { localStorage.removeItem(RECENT_KEY); } catch (e) {}
  }
  function searchUrlFor(q) { return '/search?q=' + encodeURIComponent(q); }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function(c) {
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];
    });
  }
  function renderRecentSearches() {
    var container = document.getElementById('hero-recent-chips');
    if (!container) return;
    var clearBtn = document.getElementById('hero-recent-clear');
    var items = loadRecentSearches();
    var html;
    if (items.length === 0) {
      var hints = ['艾附暖宫丸', 'afngw', 'ZD03AAA0043010100166', '阿莫西林'];
      html = hints.map(function(q) {
        return '<a class="chip chip-ghost chip-hint" href="' + searchUrlFor(q) + '">' + escapeHtml(q) + '</a>';
      }).join('');
      if (clearBtn) clearBtn.hidden = true;
    } else {
      html = items.map(function(q) {
        return '<a class="chip chip-ghost chip-recent" href="' + searchUrlFor(q) + '" title="搜索: ' + escapeHtml(q) + '">' + escapeHtml(q) + '</a>';
      }).join('');
      if (clearBtn) clearBtn.hidden = false;
    }
    container.innerHTML = html;
  }
  function initRecentSearches() {
    renderRecentSearches();
    var clearBtn = document.getElementById('hero-recent-clear');
    if (clearBtn) {
      clearBtn.addEventListener('click', function() {
        clearRecentSearches();
        renderRecentSearches();
      });
    }
    document.querySelectorAll('form').forEach(function(form) {
      var input = form.querySelector('input[name="q"]');
      if (!input) return;
      form.addEventListener('submit', function() {
        var q = (input.value || '').trim();
        if (q) addRecentSearch(q);
      });
    });
    window.addEventListener('storage', function(e) {
      if (e.key === RECENT_KEY) renderRecentSearches();
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initRecentSearches);
  } else {
    initRecentSearches();
  }
})();
