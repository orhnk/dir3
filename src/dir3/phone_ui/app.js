/* dir3 phone UI - works inside the Android WebView and in a normal browser. */
(function () {
  'use strict';

  var Bridge = window.Dir3Bridge || null;
  var STORE = {
    base: 'dir3.base',
    token: 'dir3.token',
    horizon: 'dir3.horizon',
    plan: 'dir3.cachedPlan'
  };

  // Served by `dir3 serve` (or opened in a phone browser): the page already
  // lives on the server, so its own origin is the default base URL.
  var sameOrigin = /^https?:$/.test(window.location.protocol) && !Bridge
    ? window.location.origin
    : '';

  var state = {
    base: localStorage.getItem(STORE.base) || sameOrigin || '',
    token: localStorage.getItem(STORE.token) || '',
    horizon: parseInt(localStorage.getItem(STORE.horizon) || '14', 10) || 14,
    plan: null,
    online: false,
    view: 'month',
    calendar: null,
    editor: null,
    editorPath: null,
    alarmSound: '',
    editingEvent: null,
    saveTimer: null
  };

  function $(id) { return document.getElementById(id); }
  function all(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }

  function toast(message) {
    var node = $('toast');
    node.textContent = message;
    node.classList.add('show');
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(function () { node.classList.remove('show'); }, 2600);
  }

  function bridge(method) {
    if (!Bridge || typeof Bridge[method] !== 'function') return null;
    try {
      return Bridge[method].apply(Bridge, Array.prototype.slice.call(arguments, 1));
    } catch (err) {
      console.warn('bridge ' + method + ' failed', err);
      return null;
    }
  }

  function readNativeConfig() {
    var raw = bridge('getConfig');
    if (!raw) return;
    try {
      var cfg = JSON.parse(raw);
      if (cfg && cfg.base) state.base = cfg.base;
      if (cfg && typeof cfg.token === 'string') state.token = cfg.token;
      if (cfg && typeof cfg.horizon === 'number' && cfg.horizon > 0) state.horizon = cfg.horizon;
      if (cfg && typeof cfg.alarmSound === 'string') state.alarmSound = cfg.alarmSound;
    } catch (err) { /* ignore */ }
  }

  function saveConfig(base, token) {
    state.base = (base || '').replace(/\/+$/, '');
    state.token = token || '';
    localStorage.setItem(STORE.base, state.base);
    localStorage.setItem(STORE.token, state.token);
    bridge('saveConfig', state.base, state.token);
  }

  function apiUrl(path) {
    var join = path.indexOf('?') >= 0 ? '&' : '?';
    return state.base.replace(/\/+$/, '') + path + join + 'token=' + encodeURIComponent(state.token || '');
  }

  function api(path, options) {
    options = options || {};
    if (!state.base) return Promise.reject(new Error('Sunucu adresi ayarlanmadı'));
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = setTimeout(function () { if (controller) controller.abort(); }, options.timeout || 20000);
    var init = {
      method: options.method || 'GET',
      headers: { 'Content-Type': 'application/json', 'X-Dir3-Token': state.token || '' },
      signal: controller ? controller.signal : undefined
    };
    if (options.body) init.body = JSON.stringify(options.body);
    return fetch(apiUrl(path), init).then(function (response) {
      clearTimeout(timer);
      return response.text().then(function (text) {
        var data = {};
        try { data = text ? JSON.parse(text) : {}; } catch (err) { data = { error: text }; }
        if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
        return data;
      });
    }, function (err) {
      clearTimeout(timer);
      throw err;
    });
  }

  function setOnline(online) {
    state.online = online;
    var dot = $('netDot');
    dot.classList.toggle('online', online);
    dot.classList.toggle('offline', !online && !!state.base);
    $('offlineBanner').classList.toggle('hidden', online || !state.plan);
  }

  function planEventById(id) {
    if (!state.plan) return null;
    for (var i = 0; i < state.plan.events.length; i += 1) {
      if (state.plan.events[i].id === id) return state.plan.events[i];
    }
    return null;
  }

  function alarmFor(event) {
    if (!state.plan || !event.alarm_ids) return [];
    return state.plan.alarms.filter(function (alarm) {
      return event.alarm_ids.indexOf(alarm.id) >= 0;
    });
  }

  /* ---------------------------------------------------------------- plan */

  function loadPlan(force) {
    var query = '/api/plan?until=' + encodeURIComponent(state.horizon);
    if (force) query += '&refresh=1';
    return api(query).then(function (doc) {
      applyPlan(doc);
      setOnline(true);
      return doc;
    }).catch(function (err) {
      setOnline(false);
      var cached = bridge('getCachedPlan') || localStorage.getItem(STORE.plan);
      if (cached) {
        try {
          applyPlan(JSON.parse(cached));
        } catch (parseError) {
          console.warn('cached plan broken', parseError);
        }
      }
      if (!cached) toast('Plan yüklenemedi: ' + err.message);
      return null;
    });
  }

  function applyPlan(doc) {
    state.plan = doc;
    var title = doc.title || 'dir3 plan';
    $('planTitle').textContent = title + ' · ' + (doc.events ? doc.events.length : 0) + ' event';
    document.title = title + ' · dir3';
    localStorage.setItem(STORE.plan, JSON.stringify(doc));
    if ($('runUntil') && !$('runUntil').dataset.touched) {
      $('runUntil').value = doc.source && doc.source.days ? doc.source.days : state.horizon;
    }
    renderCalendar();
    renderAgenda();
    if (state.editorPath) refreshEditorMtime();
  }

  function hexAlpha(hex, alpha) {
    var clean = String(hex || '#a4bdfc').replace('#', '');
    if (clean.length === 3) clean = clean[0] + clean[0] + clean[1] + clean[1] + clean[2] + clean[2];
    var r = parseInt(clean.slice(0, 2), 16);
    var g = parseInt(clean.slice(2, 4), 16);
    var b = parseInt(clean.slice(4, 6), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
  }

  function readableOn(hex) {
    var clean = String(hex || '#a4bdfc').replace('#', '');
    if (clean.length === 3) clean = clean[0] + clean[0] + clean[1] + clean[1] + clean[2] + clean[2];
    var r = parseInt(clean.slice(0, 2), 16);
    var g = parseInt(clean.slice(2, 4), 16);
    var b = parseInt(clean.slice(4, 6), 16);
    return (r * 299 + g * 587 + b * 114) / 1000 > 145 ? '#101418' : '#f2f7fa';
  }

  function toCalendarEvent(event) {
    var color = event.color || '#a4bdfc';
    return {
      id: event.id,
      calendarId: event.source === 'phone' ? 'phone' : 'plan',
      title: event.title || event.name,
      start: event.start,
      end: event.end,
      category: 'time',
      isReadOnly: event.source !== 'phone',
      color: readableOn(color),
      backgroundColor: hexAlpha(color, 0.26),
      borderColor: color,
      dragBackgroundColor: hexAlpha(color, 0.4)
    };
  }

  function theme() {
    return {
      common: {
        backgroundColor: '#0f1317',
        border: '1px solid #242c34',
        dayName: { color: '#93a1b0' },
        holiday: { color: '#ff9b9b' },
        saturday: { color: '#9ecbff' }
      },
      month: {
        dayName: { color: '#93a1b0' },
        dayGrid: { borderRight: '1px solid #202830', borderBottom: '1px solid #202830' },
        weekend: { backgroundColor: 'transparent' },
        today: { color: '#07221e' },
        pastDay: { color: '#6d7a87' }
      },
      week: {
        dayName: { color: '#93a1b0' },
        dayGrid: { borderRight: '1px solid #202830' },
        timeGrid: { borderLeft: '1px solid #202830' },
        today: { color: '#07221e' }
      },
      day: {
        dayName: { color: '#93a1b0' },
        timeGrid: { borderLeft: '1px solid #202830' },
        today: { color: '#07221e' }
      }
    };
  }

  function initCalendar() {
    if (state.calendar || !window.tui || !window.tui.Calendar) return;
    state.calendar = new window.tui.Calendar('#calendar', {
      defaultView: state.view,
      usageStatistics: false,
      theme: theme(),
      calendars: [
        { id: 'plan', name: 'Plan', backgroundColor: 'transparent', borderColor: 'transparent', color: '#e8eef4' },
        { id: 'phone', name: 'Telefon', backgroundColor: 'transparent', borderColor: 'transparent', color: '#e8eef4' }
      ],
      week: { startDayOfWeek: 1, hourStart: 0, hourEnd: 24, taskView: false, eventView: ['time'] },
      month: { startDayOfWeek: 1, isAlways6Weeks: false, visibleWeeksCount: 0 },
      gridSelection: { enableDblClick: false, enableClick: true }
    });
    state.calendar.on('selectDateTime', function (info) {
      openEventDialog(null, info.start, info.end);
    });
    state.calendar.on('clickEvent', function (info) {
      var event = planEventById(info.event.id);
      if (!event) return;
      if (event.source === 'phone') openEventDialog(event);
      else openDetail(event);
    });
    state.calendar.on('clickDayName', function (info) {
      state.calendar.setDate(new Date(info.date));
      state.calendar.changeView('day');
      $('viewSelect').value = 'day';
      refreshRangeLabel();
    });
  }

  function renderCalendar() {
    initCalendar();
    if (!state.calendar || !state.plan) return;
    try { state.calendar.clear(); } catch (err) { /* first render */ }
    var events = (state.plan.events || []).filter(function (event) { return event.start; }).map(toCalendarEvent);
    if (events.length) state.calendar.createEvents(events);
    refreshRangeLabel();
  }

  // toastui hands back Date objects in v2, plain date strings in some builds.
  function asDate(value) {
    return value instanceof Date ? value : new Date(value);
  }

  function refreshRangeLabel() {
    if (!state.calendar) return;
    var start = asDate(state.calendar.getDateRangeStart());
    var end = asDate(state.calendar.getDateRangeEnd());
    var label = $('calRange');
    if (isNaN(start.getTime()) || isNaN(end.getTime())) { label.textContent = '—'; return; }
    if (state.view === 'day') {
      label.textContent = start.toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', weekday: 'short' });
    } else if (state.view === 'week') {
      label.textContent = start.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' }) + ' – ' +
        new Date(end.getTime() - 86400000).toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
    } else {
      label.textContent = start.toLocaleDateString('tr-TR', { month: 'long', year: 'numeric' });
    }
  }

  function sameDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  function clock(iso) {
    var d = new Date(iso);
    return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
  }

  function renderAgenda() {
    var box = $('dayAgenda');
    if (!state.plan || state.view !== 'day') { box.classList.add('hidden'); return; }
    var today = new Date();
    var rows = (state.plan.events || []).filter(function (event) {
      return event.start && sameDay(new Date(event.start), today);
    });
    if (!rows.length) { box.classList.add('hidden'); return; }
    box.classList.remove('hidden');
    var html = '<h3>Bugün</h3>';
    rows.forEach(function (event) {
      var alarms = alarmFor(event);
      html += '<div class="agenda-row">' +
        '<div class="agenda-time">' + clock(event.start) + '</div>' +
        '<div class="agenda-name">' + escapeHtml(event.title || event.name) +
        (alarms.length ? '<span class="agenda-alarm">⏰ ' + clock(alarms[0].trigger) + '</span>' : '') +
        '</div></div>';
    });
    box.innerHTML = html;
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* -------------------------------------------------------------- dialogs */

  function openDialog(id) {
    var dialog = $(id);
    if (dialog.showModal) dialog.showModal();
    else dialog.setAttribute('open', 'open');
  }

  function closeDialog(id) {
    var dialog = $(id);
    if (dialog.close) dialog.close();
    else dialog.removeAttribute('open');
  }

  function isoDate(date) {
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
  }

  function pad(value) { return value < 10 ? '0' + value : String(value); }

  function clockValue(date) { return pad(date.getHours()) + ':' + pad(date.getMinutes()); }

  function openEventDialog(event, start, end) {
    state.editingEvent = event || null;
    $('eventDialogTitle').textContent = event ? 'Event düzenle' : 'Yeni event';
    $('evDelete').classList.toggle('hidden', !event);
    $('evId').value = event ? event.id : '';
    $('evTitle').value = event ? event.name : '';
    var startDate = event ? new Date(event.start) : (start || new Date());
    var endDate = event ? new Date(event.end) : (end || new Date(startDate.getTime() + 3600000));
    $('evDate').value = isoDate(startDate);
    $('evStart').value = clockValue(startDate);
    $('evEnd').value = clockValue(endDate);
    $('evColor').value = event && event.color ? event.color : '#46d6db';
    $('evNotes').value = event && event.notes ? event.notes : '';
    var alarm = event ? (alarmFor(event)[0] || null) : null;
    $('evAlarm').value = 'start';
    if (!alarm) $('evAlarm').value = 'none';
    else if (alarm.offset_seconds === -300) $('evAlarm').value = 'start-5';
    else if (alarm.offset_seconds === -600) $('evAlarm').value = 'start-10';
    else if (alarm.offset_seconds === -900) $('evAlarm').value = 'start-15';
    else if (alarm.offset_seconds === -1800) $('evAlarm').value = 'start-30';
    else if (alarm.when === 'end') $('evAlarm').value = 'end';
    $('evSpeak').checked = !!(alarm && alarm.speak);
    $('evSound').value = (alarm && alarm.sound) || '';
    openDialog('eventDialog');
    setTimeout(function () { $('evTitle').focus(); }, 80);
  }

  function alarmPayload() {
    var choice = $('evAlarm').value;
    if (choice === 'none') return [];
    var spec = {
      when: choice === 'end' ? 'end' : 'start',
      offset_seconds: 0,
      speak: $('evSpeak').checked,
      sound: $('evSound').value.trim() ? $('evSound').value.trim() : null,
      label: $('evTitle').value.trim(),
      full_screen: true,
      vibrate: true,
      snooze_minutes: 5,
      snooze_limit: 3,
      dismiss: ['button'],
      enabled: true
    };
    if (choice === 'start-5') spec.offset_seconds = -300;
    if (choice === 'start-10') spec.offset_seconds = -600;
    if (choice === 'start-15') spec.offset_seconds = -900;
    if (choice === 'start-30') spec.offset_seconds = -1800;
    return [spec];
  }

  function submitEvent(event) {
    event.preventDefault();
    if (!state.base) { toast('Önce sunucu adresini ayarla'); return; }
    var payload = {
      id: $('evId').value || undefined,
      title: $('evTitle').value.trim(),
      date: $('evDate').value,
      start: $('evStart').value,
      end: $('evEnd').value || null,
      color: $('evColor').value,
      notes: $('evNotes').value,
      alarms: alarmPayload()
    };
    api('/api/events', { method: 'POST', body: payload }).then(function () {
      closeDialog('eventDialog');
      toast('Event kaydedildi');
      return loadPlan(true);
    }).catch(function (err) { toast('Kaydedilemedi: ' + err.message); });
  }

  function deleteEvent() {
    var id = $('evId').value;
    if (!id || !confirm('Bu event silinsin mi?')) return;
    api('/api/events?id=' + encodeURIComponent(id), { method: 'DELETE' }).then(function () {
      closeDialog('eventDialog');
      toast('Event silindi');
      return loadPlan(true);
    }).catch(function (err) { toast('Silinemedi: ' + err.message); });
  }

  function openDetail(event) {
    state.editingEvent = event;
    $('detailTitle').textContent = event.title || event.name;
    var alarms = alarmFor(event);
    var rows = '';
    rows += '<div class="detail-row"><div class="k">Tür</div><div class="v">' +
      (event.source === 'phone' ? 'Telefon eventi (düzenlenebilir)' : 'Plan eventi (Python)') + '</div></div>';
    rows += '<div class="detail-row"><div class="k">Tarih</div><div class="v">' +
      new Date(event.start).toLocaleDateString('tr-TR', { weekday: 'long', day: 'numeric', month: 'long' }) + '</div></div>';
    rows += '<div class="detail-row"><div class="k">Saat</div><div class="v">' +
      clock(event.start) + ' – ' + clock(event.end) + '</div></div>';
    if (alarms.length) {
      rows += '<div class="detail-row"><div class="k">Alarm</div><div class="v">' +
        alarms.map(function (alarm) {
          var extra = [];
          if (alarm.speak) extra.push('sesli okuma');
          if (alarm.vibrate) extra.push('titreşim');
          if (alarm.snooze_limit) extra.push(alarm.snooze_minutes + ' dk snooze');
          return '<div class="detail-alarm"><span class="bell">⏰</span><span>' +
            clock(alarm.trigger) + ' · ' + escapeHtml(alarm.label || event.name) +
            (extra.length ? '<br><span class="muted">' + extra.join(' · ') + '</span>' : '') +
            '</span></div>';
        }).join('') + '</div></div>';
    } else {
      rows += '<div class="detail-row"><div class="k">Alarm</div><div class="v muted">yok</div></div>';
    }
    if (event.notes) rows += '<div class="detail-row"><div class="k">Not</div><div class="v">' + escapeHtml(event.notes) + '</div></div>';
    $('detailBody').innerHTML = rows;
    $('detailEditCode').classList.toggle('hidden', event.source === 'phone');
    openDialog('detailDialog');
  }

  /* ---------------------------------------------------------------- files */

  function loadFiles() {
    if (!state.base) { $('fileList').innerHTML = '<li class="muted">Sunucu ayarlanmadı.</li>'; return; }
    api('/api/files').then(function (data) {
      var planfile = state.plan && state.plan.source ? state.plan.source.planfile : '';
      var html = '';
      data.files.forEach(function (file) {
        var current = planfile && planfile.indexOf(file.path) >= 0;
        html += '<li data-path="' + escapeHtml(file.path) + '" class="' + (current ? 'current' : '') + '">' +
          '<span class="file-icon">▤</span><div class="file-meta">' +
          '<div class="file-name">' + escapeHtml(file.name) + (current ? ' · ana plan' : '') + '</div>' +
          '<div class="file-sub">' + escapeHtml(file.path) + ' · ' + Math.max(1, Math.round(file.size / 1024)) + ' KB</div>' +
          '</div><span class="muted">›</span></li>';
      });
      $('fileList').innerHTML = html || '<li class="muted">Düzenlenebilir dosya yok.</li>';
      all('#fileList li[data-path]').forEach(function (row) {
        row.addEventListener('click', function () { openEditor(row.getAttribute('data-path')); });
      });
    }).catch(function (err) {
      $('fileList').innerHTML = '<li class="muted">Dosyalar yüklenemedi: ' + escapeHtml(err.message) + '</li>';
    });
  }

  function ensureEditor() {
    if (state.editor) return state.editor;
    state.editor = CodeMirror.fromTextArea($('editorArea'), {
      mode: { name: 'python', version: 3, singleLineStringErrors: false },
      theme: 'material-darker',
      lineNumbers: true,
      indentUnit: 4,
      tabSize: 4,
      indentWithTabs: false,
      lineWrapping: false,
      viewportMargin: Infinity
    });
    state.editor.setSize('100%', '100%');
    state.editor.on('keydown', function (cm, event) {
      if ((event.ctrlKey || event.metaKey) && event.key === 's') {
        event.preventDefault();
        saveFile();
      }
    });
    return state.editor;
  }

  function openEditor(path) {
    if (!state.base) { toast('Önce sunucu adresi ayarla'); return; }
    $('editorOverlay').classList.remove('hidden');
    $('editorName').textContent = 'Yükleniyor…';
    $('editorPath').textContent = path;
    api('/api/file?path=' + encodeURIComponent(path)).then(function (data) {
      $('editorName').textContent = data.path.split('/').pop();
      $('editorPath').textContent = data.path;
      state.editorPath = data.path;
      var editor = ensureEditor();
      editor.setValue(data.text);
      editor.clearHistory();
      setTimeout(function () { editor.refresh(); editor.focus(); }, 60);
    }).catch(function (err) {
      $('editorName').textContent = 'Açılamadı';
      toast(err.message);
    });
  }

  function saveFile() {
    if (!state.editorPath || !state.editor) return;
    $('editorSave').textContent = 'Kaydediliyor…';
    api('/api/file', {
      method: 'PUT',
      body: { path: state.editorPath, text: state.editor.getValue() }
    }).then(function (data) {
      $('editorSave').textContent = 'Kaydet';
      toast('Kaydedildi' + (data.backup ? ' · yedek: ' + data.backup : ''));
      loadFiles();
      loadPlan(true);
    }).catch(function (err) {
      $('editorSave').textContent = 'Kaydet';
      toast('Kaydedilemedi: ' + err.message);
    });
  }

  function refreshEditorMtime() { /* placeholder: server returns mtime; the editor stays as-is */ }

  /* ------------------------------------------------------------------ run */

  function runAction(action, dryRun) {
    if (!state.base) { toast('Önce sunucu adresini ayarla'); return; }
    if (action === 'clear' && !confirm('dir3 etiketli TÜM eventler takvimden silinsin mi?')) return;
    var body = {
      action: action,
      until: $('runUntil').value || null,
      from: $('runFrom').value || null,
      offline: $('runOffline').checked,
      dry_run: !!dryRun
    };
    $('runOutput').textContent = 'çalışıyor…';
    all('#view-run button').forEach(function (button) { button.disabled = true; });
    api('/api/run', { method: 'POST', body: body, timeout: 250000 }).then(function (data) {
      $('runOutput').textContent = data.output || ('çıkış kodu ' + data.exit_code);
      toast(data.ok ? 'Tamam' : 'Hata (kod ' + data.exit_code + ')');
      if (action !== 'clear') loadPlan(true);
    }).catch(function (err) {
      $('runOutput').textContent = 'Hata: ' + err.message;
    }).then(function () {
      all('#view-run button').forEach(function (button) { button.disabled = false; });
    });
  }

  /* -------------------------------------------------------------- settings */

  function fillSettings() {
    $('setBase').value = state.base;
    $('setToken').value = state.token;
    $('setHorizon').value = state.horizon;
    $('soundHint').textContent = state.alarmSound ? 'Özel alarm sesi seçili' : 'Sistem sesi';
    var version = bridge('getVersion');
    $('appVersion').textContent = version ? ('Sürüm ' + version) : 'Tarayıcı modu (native alarm yok)';
  }

  function applySettings() {
    saveConfig($('setBase').value.trim(), $('setToken').value.trim());
    state.horizon = parseInt($('setHorizon').value || '14', 10) || 14;
    localStorage.setItem(STORE.horizon, String(state.horizon));
    bridge('setHorizon', state.horizon);
    toast('Ayarlar kaydedildi');
    loadPlan(true);
    loadFiles();
    refreshStatus();
  }

  function refreshStatus() {
    if (!state.base) return;
    api('/api/status', { timeout: 6000 }).then(function (data) {
      setOnline(true);
      $('planTitle').textContent = (data.title || 'dir3') + ' · ' + data.host;
    }).catch(function () { setOnline(false); });
  }

  /* ---------------------------------------------------------------- wiring */

  function switchTab(name) {
    all('.view').forEach(function (view) { view.classList.remove('active'); });
    $('view-' + name).classList.add('active');
    all('.bottomnav button').forEach(function (button) {
      button.classList.toggle('active', button.getAttribute('data-tab') === name);
    });
    $('fab').classList.toggle('hidden', name !== 'calendar');
    if (name === 'files') loadFiles();
    if (name === 'calendar' && state.calendar) {
      setTimeout(function () { state.calendar.render(); refreshRangeLabel(); }, 40);
    }
    if (name === 'settings') fillSettings();
    if (name === 'run' && state.plan) {
      $('runUntil').value = state.plan.source && state.plan.source.days ? state.plan.source.days : state.horizon;
    }
  }

  function bind() {
    all('.bottomnav button').forEach(function (button) {
      button.addEventListener('click', function () { switchTab(button.getAttribute('data-tab')); });
    });
    all('[data-close]').forEach(function (button) {
      button.addEventListener('click', function () { closeDialog(button.getAttribute('data-close')); });
    });
    $('btnRefresh').addEventListener('click', function () { loadPlan(true).then(function () { toast('Yenilendi'); }); });
    $('btnReloadFiles').addEventListener('click', loadFiles);
    $('fab').addEventListener('click', function () { openEventDialog(null, new Date(), new Date(Date.now() + 3600000)); });
    $('eventForm').addEventListener('submit', submitEvent);
    $('evDelete').addEventListener('click', deleteEvent);
    $('editorSave').addEventListener('click', saveFile);
    $('editorClose').addEventListener('click', function () {
      $('editorOverlay').classList.add('hidden');
      state.editorPath = null;
    });
    $('btnToday').addEventListener('click', function () { state.calendar.today(); refreshRangeLabel(); });
    $('btnPrev').addEventListener('click', function () { state.calendar.prev(); refreshRangeLabel(); });
    $('btnNext').addEventListener('click', function () { state.calendar.next(); refreshRangeLabel(); });
    $('viewSelect').addEventListener('change', function (event) {
      state.view = event.target.value;
      state.calendar.changeView(state.view);
      $('dayAgenda').classList.toggle('hidden', state.view !== 'day');
      renderAgenda();
      refreshRangeLabel();
    });
    $('detailEditCode').addEventListener('click', function () {
      var path = state.plan && state.plan.source ? state.plan.source.planfile : 'gebetsplan.py';
      closeDialog('detailDialog');
      switchTab('files');
      openEditor(path);
    });
    $('runCompile').addEventListener('click', function () { runAction('compile', false); });
    $('runDry').addEventListener('click', function () { runAction('compile', true); });
    $('runSync').addEventListener('click', function () { runAction('sync', false); });
    $('runClear').addEventListener('click', function () { runAction('clear', false); });
    $('runUntil').addEventListener('input', function () { $('runUntil').dataset.touched = '1'; });
    $('setSave').addEventListener('click', applySettings);
    $('setSync').addEventListener('click', function () {
      saveConfig($('setBase').value.trim(), $('setToken').value.trim());
      runAction('sync', false);
      switchTab('run');
    });
    $('ttsTry').addEventListener('click', function () {
      var text = $('ttsText').value || 'Fajr vakti geldi';
      if (bridge('speak', text) === null && window.speechSynthesis) {
        var utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'tr-TR';
        window.speechSynthesis.speak(utterance);
      }
    });
    $('ttsAlarmTry').addEventListener('click', function () {
      if (bridge('testAlarm', $('ttsText').value || 'Fajr vakti geldi') === null) {
        toast('Alarm ekranı yalnızca uygulamada çalışır');
      }
    });
    $('pickSound').addEventListener('click', function () {
      if (bridge('pickSound') === null) toast('Ses seçimi yalnızca uygulamada çalışır');
    });
    $('permAsk').addEventListener('click', function () { bridge('requestPermissions'); toast('İzin istekleri gönderildi'); });
    $('permExact').addEventListener('click', function () { bridge('openExactAlarmSettings'); });
    $('permBattery').addEventListener('click', function () { bridge('openBatterySettings'); });
  }

  function boot() {
    readNativeConfig();
    // A token in the URL (printed by `dir3 serve`) wins once.
    var params = new URLSearchParams(window.location.search);
    if (params.get('token')) {
      state.token = params.get('token');
      localStorage.setItem(STORE.token, state.token);
      bridge('saveConfig', state.base, state.token);
    }
    fillSettings();
    bind();
    initCalendar();
    if (!state.base) {
      switchTab('settings');
      toast('Bilgisayarda `dir3 serve <plan>` çalıştır, URL ve token gir');
      return;
    }
    loadPlan(false);
    refreshStatus();
    loadFiles();
  }

  // Native back button: close the editor/dialog first, leave the app last.
  window.dir3HandleBack = function () {
    var editor = $('editorOverlay');
    if (editor && !editor.classList.contains('hidden')) {
      editor.classList.add('hidden');
      state.editorPath = null;
      return true;
    }
    var open = all('dialog[open]');
    if (open.length) {
      open.forEach(function (dialog) { closeDialog(dialog.id); });
      return true;
    }
    return false;
  };
  window.dir3OnResume = function () {
    readNativeConfig();
    if (document.getElementById('view-settings').classList.contains('active')) fillSettings();
    if (state.base) refreshStatus();
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
