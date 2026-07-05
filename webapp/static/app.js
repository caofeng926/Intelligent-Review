// 医保智审 Web - 客户端交互
(function() {
  'use strict';

  // ---- 编码复制按钮 ----
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('.code-copy');
    if (!btn) return;
    var code = btn.getAttribute('data-code') || '';
    copyText(code).then(function() {
      btn.classList.add('is-copied');
      showToast('已复制：' + code, 'success');
      setTimeout(function() { btn.classList.remove('is-copied'); }, 1200);
    }).catch(function() {
      showToast('复制失败，请手动复制', 'error');
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
    var container = document.getElementById('hero-chips');
    if (!container) return;
    var clearBtn = document.getElementById('hero-clear');
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
    var clearBtn = document.getElementById('hero-clear');
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

  // ---- Ctrl/Cmd+K shortcut to focus search ----
  document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      var input = document.querySelector('.topbar-search input');
      if (input) { input.focus(); input.select(); }
    } else if (e.key === 'Escape') {
      var modal = document.querySelector('.modal.is-show');
      if (modal) modal.classList.remove('is-show');
    }
  });

  // ---- Toast 通知系统 ----
  var toastContainer;
  function ensureToastContainer() {
    if (toastContainer) return toastContainer;
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container';
    toastContainer.setAttribute('role', 'status');
    toastContainer.setAttribute('aria-live', 'polite');
    document.body.appendChild(toastContainer);
    return toastContainer;
  }
  function showToast(message, kind) {
    kind = kind || 'info';
    var container = ensureToastContainer();
    var toast = document.createElement('div');
    toast.className = 'toast toast--' + kind;
    toast.textContent = message;
    container.appendChild(toast);
    requestAnimationFrame(function() { toast.classList.add('is-show'); });
    setTimeout(function() {
      toast.classList.remove('is-show');
      setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
    }, 2200);
  }

  // 覆盖复制按钮反馈：用 toast 替代文本变化
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('.code-copy');
    if (!btn) return;
    // 已由上方 handler 处理复制逻辑，这里仅增强反馈
  });

  // ---- 滚动感知顶栏 ----
  var topbar = document.querySelector('.topbar');
  if (topbar) {
    var scrollTimer;
    window.addEventListener('scroll', function() {
      if (scrollTimer) return;
      scrollTimer = requestAnimationFrame(function() {
        scrollTimer = null;
        if (window.scrollY > 8) {
          topbar.classList.add('is-scrolled');
        } else {
          topbar.classList.remove('is-scrolled');
        }
      });
    }, { passive: true });
  }

  // ---- 入场动画 (IntersectionObserver) ----
  function initEntranceAnimations() {
    var targets = document.querySelectorAll('.std-card, .quick-card, .info-banner, .list-row, .cat-card');
    if (!targets.length) return;
    if (!('IntersectionObserver' in window)) {
      targets.forEach(function(el) { el.classList.add('is-visible'); });
      return;
    }
    var io = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.06, rootMargin: '0px 0px -40px 0px' });
    targets.forEach(function(el) { io.observe(el); });
  }

  // ---- 平滑滚动 (锚点 / pager) ----
  document.addEventListener('click', function(e) {
    var link = e.target.closest('a[href^="#"]');
    if (!link) return;
    var href = link.getAttribute('href');
    if (href === '#' || href.length < 2) return;
    var target = document.querySelector(href);
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  // ---- 初始化 ----
  function init() {
    initRecentSearches();
    initEntranceAnimations();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
