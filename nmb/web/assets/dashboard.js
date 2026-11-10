
  let serverList = [];
  let snifferActive = false;
  let gaugeScaleMax = 100;
  let selectedEngine = 'ookla';
  let userManuallySelectedEngine = false;
  let searchDebounceTimer = null;
  let currentTranslations = (typeof window !== 'undefined' && window.__INITIAL_TRANSLATIONS__) ? window.__INITIAL_TRANSLATIONS__ : {};
  let currentLang = (typeof window !== 'undefined' && window.__INITIAL_LANG__) ? window.__INITIAL_LANG__ : 'en';

  async function loadTranslations(lang) {
    const targetLang = lang || currentLang;
    if (window.__INITIAL_LANG__ === targetLang && window.__INITIAL_TRANSLATIONS__ && Object.keys(currentTranslations).length > 0) {
      currentLang = targetLang;
      const sel = document.getElementById('lang-select');
      if (sel) sel.value = currentLang;
      applyTranslations();
      return;
    }
    try {
      const res = await fetch('/api/i18n?lang=' + encodeURIComponent(targetLang));
      if (res.ok) {
        const d = await res.json();
        currentTranslations = d.translations || {};
        currentLang = d.lang || targetLang;
        const sel = document.getElementById('lang-select');
        if (sel) sel.value = currentLang;
        applyTranslations();
      }
    } catch (e) {
      console.error('loadTranslations error:', e);
    }
  }

  function t(key, fallback) {
    return currentTranslations[key] || fallback || key;
  }

  // Failed rows: name the known Ookla pause in the page language, otherwise show the engine's text.
  // A link to a service's front page (older Cloudflare rows) is not a link to the result.
  function isGenericResultUrl(url) {
    return /^https?:\/\/speed\.cloudflare\.com\/?$/i.test(String(url || '').trim());
  }

  function speedErrorText(err) {
    const e = String(err || '');
    const m = e.match(/^Ookla rate limit.*?(\d+) min/);
    if (m) return t('speed_err_ookla_paused', 'Ookla refused this box for testing too often; paused for {min} min').replace('{min}', m[1]);
    return e || t('speed_err_unknown', 'unknown error');
  }

  // Ookla refuses a box that tests too often; say so wherever the schedule is shown.
  function ooklaWarningText(w) {
    if (!w) return '';
    let text;
    if (w.code === 'ookla_rate_limit_risk') {
      text = t('ookla_warn_risk', 'This schedule runs every {interval} min. Ookla blocks boxes that test too often, so the box runs Ookla at most every {safe} min; RTR-NetTest, Cloudflare and iPerf3 run every time.')
        .replace('{interval}', w.interval_min).replace('{safe}', w.safe_interval_min);
    } else {
      text = t('ookla_warn_paused_only', 'Ookla refused tests from this box.');
    }
    if (w.paused_min) {
      text += ' ' + t('ookla_warn_paused', 'Ookla is paused for {paused} min; until then the box measures with RTR-NetTest.').replace('{paused}', w.paused_min);
    }
    return text;
  }

  function renderOoklaWarning(w) {
    const box = document.getElementById('sched-ookla-warning');
    if (!box) return;
    const text = ooklaWarningText(w);
    box.style.display = text ? 'block' : 'none';
    box.textContent = text ? '⚠️ ' + text : '';
  }

  function applyTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const k = el.getAttribute('data-i18n');
      if (currentTranslations[k]) {
        el.textContent = currentTranslations[k];
      }
    });
    document.querySelectorAll('[data-i18n-html]').forEach(el => {
      const k = el.getAttribute('data-i18n-html');
      if (currentTranslations[k]) {
        el.innerHTML = currentTranslations[k];
      }
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const k = el.getAttribute('data-i18n-placeholder');
      if (currentTranslations[k]) {
        el.placeholder = currentTranslations[k];
      }
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      const k = el.getAttribute('data-i18n-title');
      if (currentTranslations[k]) {
        el.title = currentTranslations[k];
      }
    });
    document.querySelectorAll('[data-i18n-label]').forEach(el => {
      const k = el.getAttribute('data-i18n-label');
      if (currentTranslations[k]) {
        el.label = currentTranslations[k];
      }
    });
    if (typeof cachedGuestWifiStatus !== 'undefined' && cachedGuestWifiStatus) {
      renderGuestWifiStatus(cachedGuestWifiStatus);
    }
    if (typeof selectedEngine !== 'undefined' && typeof selectEngine === 'function') {
      selectEngine(selectedEngine, true);
    }
    const uaModeSel = document.getElementById('cfg-ua-mode');
    if (uaModeSel && typeof onCfgUaModeChange === 'function') {
      onCfgUaModeChange(uaModeSel.value);
    }
    if (typeof updateWgQrTip === 'function') {
      updateWgQrTip();
    }
    if (typeof checkAntiBanAndInterfaceStatus === 'function') {
      checkAntiBanAndInterfaceStatus();
    }
    if (typeof updateWifiChannelOptions === 'function') {
      const bSel = document.getElementById('cfg-wifi-band');
      const cSel = document.getElementById('cfg-wifi-channel');
      const curCh = cSel ? cSel.value : null;
      updateWifiChannelOptions(bSel ? bSel.value : 'auto', curCh);
    }
    if (typeof renderWifiCapabilities === 'function' && window._wifiCaps) {
      renderWifiCapabilities(window._wifiCaps, (window._wifiCaps && window._wifiCaps.current_status) || {});
    }
  }


  // ==========================================
  // Dynamic Design Theme Engine
  // ==========================================
  function switchTheme(theme, showNotice) {
    const validThemes = ['default', 'prtd', 'proudride', 'amoled', 'asuswrt', 'asus_camo', 'tp_gold', 'mountain_hago', 'ndefault'];
    if (!validThemes.includes(theme)) theme = 'default';
    document.documentElement.setAttribute('data-theme', theme);
    document.body.className = document.body.className.split(' ').filter(c => !c.startsWith('theme-')).join(' ') + ' theme-' + theme;
    try {
      localStorage.setItem('nmb_theme', theme);
    } catch (e) {}
    const sel = document.getElementById('theme-select');
    if (sel && sel.value !== theme) sel.value = theme;

    // Highlight active card
    updateThemeCardsHighlight(theme);

    // Persist immediately to backend server so it stays permanently
    try {
      fetch('/api/theme', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme: theme })
      }).catch(e => {});
    } catch (e) {}

    if (showNotice !== false && typeof showToast === 'function') {
      showToast(t('theme_applied', 'Theme applied: ') + theme);
    }
  }

  function updateThemeCardsHighlight(theme) {
    document.querySelectorAll('.theme-card').forEach(el => {
      const cardTheme = el.getAttribute('data-theme-name');
      if (cardTheme === theme) {
        el.classList.add('active');
      } else {
        el.classList.remove('active');
      }
    });
  }

  function initTheme() {
    let saved = '';
    try {
      saved = localStorage.getItem('nmb_theme');
    } catch (e) {}
    if (!saved) {
      saved = document.documentElement.getAttribute('data-theme') || '__NMB_INITIAL_THEME__' || 'default';
    }
    switchTheme(saved, false);
  }

  async function switchLanguage(lang) {
    currentLang = lang;
    document.documentElement.lang = lang;
    localStorage.setItem('nmb_lang', lang);
    showToast('Changing language to ' + lang.toUpperCase() + '...');
    try {
      const res = await fetch('/api/i18n', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lang: lang })
      });
      if (res.ok) {
        const d = await res.json();
        currentTranslations = d.translations || {};
        applyTranslations();
        showToast('Language updated: ' + lang.toUpperCase());
      }
    } catch (e) {
      await loadTranslations(lang);
    }
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Value as a JS literal for inline handlers: HTML-escaping alone is decoded before the JS runs.
  function jsArg(value) {
    return escapeHtml(JSON.stringify(value === undefined ? null : value));
  }

  function sanitizeUrl(url) {
    if (!url) return '';
    const clean = String(url).trim();
    if (clean.startsWith('http://') || clean.startsWith('https://')) {
      return clean;
    }
    return '';
  }

  function showToast(msg) {
    const el = document.getElementById('toast-msg');
    el.innerText = msg;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 4000);
  }

  function onMemoryProfileSelectChange(val) {
    window.memoryProfileDirty = true;
  }

  async function saveMemoryProfileOnly() {
    const sel = document.getElementById('cfg-memory-profile');
    const prof = sel ? sel.value : 'auto';
    showToast(t('toast_saving', 'Saving...'));
    try {
      const res = await fetch('/api/system/memory_profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memory_profile: prof })
      });
      if (res.ok) {
        window.memoryProfileDirty = false;
        showToast(t('toast_mem_saved', 'Memory profile updated successfully!'));
        refreshStatus();
      } else {
        const err = await res.json();
        showToast('Error: ' + (err.message || 'Failed to save profile'));
      }
    } catch (e) {
      showToast('Error saving memory profile');
    }
  }

  async function trimMemoryNow() {
    const btn = document.querySelector('button[onclick="trimMemoryNow()"]');
    if (btn) btn.disabled = true;
    showToast('🧹 Trimming process heap...');
    try {
      const res = await fetch('/api/system/trim_memory', { method: 'POST' });
      if (res.ok) {
        showToast(t('toast_mem_trimmed', 'Process heap trimmed and memory released to the OS!'));
        refreshStatus();
      } else {
        showToast('Error trimming memory');
      }
    } catch (e) {
      showToast('Error trimming memory');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.app-tab-btn').forEach(el => el.classList.remove('active'));
    const t = document.getElementById(tabId);
    if (t) t.classList.add('active');
    const b = Array.from(document.querySelectorAll('.app-tab-btn')).find(el => (el.getAttribute('onclick') || '').includes(tabId));
    if (b) {
      b.classList.add('active');
      b.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
    }

    if (tabId === 'tab-script' && serverList.length === 0) {
      loadServers();
    }
    if (tabId === 'tab-terminal') {
      initTerminal();
    }
    if (tabId === 'tab-tasks') {
      startTasksAutoRefresh();
    } else {
      stopTasksAutoRefresh();
    }
    if (tabId === 'tab-info') {
      loadConfig();
      loadGuestWifiStatus();
      loadSystemInfo();
    }
    if (tabId === 'tab-iperf') {
      loadIperfStatus();
    }
    if (tabId === 'tab-traceroute') {
      loadTracerouteStatus();
    }
    if (tabId === 'tab-ooni') {
      loadOoniStatus();
    }
    if (tabId === 'tab-remote') {
      loadRemoteAccessStatus();
    }
    if (tabId === 'tab-explorer') {
      loadNetworkDevices();
      loadWifiUplink();
      loadGuestWifiStatus();
    }
    if (tabId === 'tab-wifi') {
      fetchWifiCapabilities();
      loadGuestWifiStatus();
      loadMacInfo();
    }
    if (tabId === 'tab-tuning') {
      loadKernelStatus();
    }
    if (tabId === 'tab-adblock') {
      loadAdblockStatus();
      loadAdblockCharts();
      loadAdblockQueryLog();
      startAdblockPolling();
    } else {
      stopAdblockPolling();
    }
    if (tabId === 'tab-telegram') {
      loadTelegramStatus();
    }
    if (tabId === 'tab-llm') {
      loadLlmBundle();
    }
    if (tabId === 'tab-syslog') {
      if (devLogActiveSubtab === 'syslog') {
        fetchSystemSyslog(true);
      } else if (devLogActiveSubtab === 'devlog') {
        fetchDevLogs(true);
      }
    }
  }

  // =========================================================================
  // Multi-Port Matrix & Hardware Network Drivers Subsystem
  // =========================================================================
  let cachedPortsData = null;
  let driverInstallPollTimer = null;

  async function loadLanTopology() {
    try {
      const res = await fetch('/api/network/lan-topology');
      if (!res.ok) return;
      renderLanTopology(await res.json());
    } catch (e) {
      console.error('Failed to load LAN topology:', e);
    }
  }

  function renderLanPortCheckboxes(containerId, ports, selected) {
    const box = document.getElementById(containerId);
    if (!box) return;
    if (!ports.length) {
      box.innerHTML = '<span style="font-size: 12px; color: var(--text-muted);">' + t('lanpt_no_ports', 'No wired ports detected.') + '</span>';
      return;
    }
    box.innerHTML = ports.map(p => {
      const speed = p.carrier && p.speed_mbps ? p.speed_mbps + ' Mbps' : (p.carrier ? 'UP' : 'DOWN');
      const name = escapeHtml(p.name);
      return `<label style="display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 6px 10px; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 6px;">
        <input type="checkbox" value="${name}" ${selected.includes(p.name) ? 'checked' : ''}>
        <b>${name}</b> <span style="color: #94a3b8;">${escapeHtml(p.chipset || '')} · ${speed}</span>
      </label>`;
    }).join('');
  }

  function renderLanTopology(data) {
    document.getElementById('lanpt-lag-enabled').checked = !!data.lag_enabled;
    document.getElementById('lanpt-pt-enabled').checked = !!data.lan_passthrough_enabled;
    document.getElementById('lanpt-lag-mode').value = data.lag_mode;
    document.getElementById('lanpt-hash').value = data.lag_hash_policy;
    document.getElementById('lanpt-lacp').value = data.lacp_rate;
    document.getElementById('lanpt-uplink').textContent = data.wan_interface || '--';
    renderLanPortCheckboxes('lanpt-lag-ports', data.ports || [], data.lag_ports || []);
    renderLanPortCheckboxes('lanpt-pt-ports', data.ports || [], data.passthrough_ports || []);

    const rt = data.runtime || {};
    const state = document.getElementById('lanpt-state');
    state.textContent = rt.applied ? t('lanpt_state_active', 'Active')
      : (rt.requested ? t('lanpt_state_pending', 'Saved, not active yet') : t('lanpt_state_off', 'Off'));
    state.style.color = rt.applied ? '#34d399' : (rt.requested ? '#fbbf24' : '#94a3b8');

    let runtimeText = '';
    if (rt.applied && data.lag_enabled) {
      runtimeText = `${rt.lag_active_ports}/${(rt.lag_members || []).length} ${t('lanpt_links_up', 'links up')} · ${rt.lag_theoretical_mbps} Mbps`;
      if (rt.lag_mixed_speeds && data.lag_mode === '802.3ad') {
        runtimeText += ' · ' + t('lanpt_mixed_speeds', 'Ports run at different speeds; 802.3ad only combines ports of equal speed.');
      }
    }
    document.getElementById('lanpt-lag-runtime').textContent = runtimeText;
    updateLanTopologyVisibility();
  }

  function updateLanTopologyVisibility() {
    const lagOn = document.getElementById('lanpt-lag-enabled').checked;
    const mode = document.getElementById('lanpt-lag-mode').value;
    document.getElementById('lanpt-lag-section').hidden = !lagOn;
    document.getElementById('lanpt-pt-section').hidden = !document.getElementById('lanpt-pt-enabled').checked;
    document.getElementById('lanpt-uplink-row').hidden = lagOn;
    document.getElementById('lanpt-hash-wrap').hidden = !['802.3ad', 'balance-xor', 'balance-tlb'].includes(mode);
    document.getElementById('lanpt-lacp-wrap').hidden = mode !== '802.3ad';
  }

  async function saveLanTopology() {
    const checked = (id) => Array.from(document.querySelectorAll('#' + id + ' input:checked')).map(el => el.value);
    const payload = {
      lag_enabled: document.getElementById('lanpt-lag-enabled').checked,
      lag_ports: checked('lanpt-lag-ports'),
      lag_mode: document.getElementById('lanpt-lag-mode').value,
      lag_hash_policy: document.getElementById('lanpt-hash').value,
      lacp_rate: document.getElementById('lanpt-lacp').value,
      lan_passthrough_enabled: document.getElementById('lanpt-pt-enabled').checked,
      passthrough_ports: checked('lanpt-pt-ports'),
    };
    try {
      const res = await fetch('/api/network/lan-topology', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(t('error_prefix', 'Error: ') + (data.message || res.status));
        return;
      }
      renderLanTopology(data);
      showToast(t('lanpt_saved', 'LAN topology saved. The network daemon applies it shortly.'));
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  function renderPurgeSummary(summary) {
    const box = document.getElementById('purge-categories');
    if (!box) return;
    const fallback = { measurements: 'Measurements', events: 'Events and alerts', reports: 'Saved reports', backups: 'Backups', logs: 'Logs' };
    box.innerHTML = Object.keys(fallback).map(c => {
      const info = summary[c] || { items: 0, bytes: 0 };
      const size = info.bytes ? ' · ' + (info.bytes / 1048576).toFixed(1) + ' MB' : '';
      return `<label style="display: flex; align-items: center; gap: 8px; font-size: 13px;">
        <input type="checkbox" value="${c}"> <span>${t('purge_cat_' + c, fallback[c])}: <b>${escapeHtml(info.items)}</b> ${t('purge_items', 'items')}${size}</span>
      </label>`;
    }).join('');
  }

  async function loadPurgeSummary() {
    try {
      const res = await fetch('/api/system/purge');
      if (res.ok) renderPurgeSummary((await res.json()).summary);
    } catch (e) {
      console.error('Failed to load purge summary:', e);
    }
  }

  async function runPurge() {
    const categories = Array.from(document.querySelectorAll('#purge-categories input:checked')).map(el => el.value);
    const confirmEl = document.getElementById('purge-confirm');
    if (!categories.length || confirmEl.value !== 'PURGE') {
      showToast(t('purge_need_selection', 'Select a category and type PURGE.'));
      return;
    }
    try {
      const res = await fetch('/api/system/purge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ categories: categories, confirm: 'PURGE' })
      });
      const data = await res.json();
      confirmEl.value = '';
      if (data.summary) renderPurgeSummary(data.summary);
      showToast(res.ok ? t('purge_done', 'Selected data deleted.') : t('error_prefix', 'Error: ') + JSON.stringify(data.errors || data.message));
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  // Name form fields that have no label, and keep the document language current.
  function enhanceAccessibility(root) {
    (root || document).querySelectorAll('input, select, textarea').forEach(el => {
      if (el.id && document.querySelector('label[for="' + el.id + '"]')) return;
      if (el.closest('label') || el.getAttribute('aria-label')) return;
      const name = el.placeholder || el.title || el.name || el.id;
      if (name) el.setAttribute('aria-label', name);
    });
  }
  document.addEventListener('DOMContentLoaded', () => enhanceAccessibility());

  async function loadInterfaceMatrix() {
    try {
      const res = await fetch('/api/system/ports');
      if (!res.ok) return;
      const data = await res.json();
      cachedPortsData = data;
      renderInterfaceMatrix(data);
      updateSpeedtestInterfaceDropdown(data.interfaces);
      loadLanTopology();
    } catch (e) {
      console.error('Failed to load interface matrix:', e);
    }
  }

  function renderInterfaceMatrix(data) {
    const tbody = document.getElementById('port-matrix-tbody');
    if (!tbody) return;
    if (!data.interfaces || data.interfaces.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 20px;">No physical network controllers detected.</td></tr>';
      return;
    }

    if (data.wan_mode && document.getElementById('matrix-wan-mode')) {
      document.getElementById('matrix-wan-mode').value = data.wan_mode;
    }

    let rowsHtml = '';
    data.interfaces.forEach((iface, idx) => {
      const isUp = iface.carrier || iface.operstate === 'up';
      const statusBadge = isUp
        ? `<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981;">🟢 UP (${iface.speed_mbps ? iface.speed_mbps + ' Mbps' : 'Active'})</span>`
        : `<span class="badge-pill" style="background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid #ef4444;">🔴 DOWN</span>`;

      const ipList = (iface.ipv4 && iface.ipv4.length) ? escapeHtml(iface.ipv4.join(', ')) : '<span style="color: var(--text-muted);">None</span>';
      const macStr = iface.mac ? `<code style="font-size: 11px; color: #94a3b8;">${escapeHtml(iface.mac)}</code>` : '--';

      const drvStr = iface.driver ? `<b>${escapeHtml(iface.driver)}</b>${iface.firmware_version ? ' (' + escapeHtml(iface.firmware_version) + ')' : ''}` : '<span style="color: #ef4444;">No Driver</span>';

      const busIcon = iface.bus_type === 'pci' ? '🖥️ PCIe' : iface.bus_type === 'usb' ? '🔌 USB' : '📦 Onboard';
      const busStr = `${busIcon} <span style="font-size: 11px; color: #94a3b8;">${escapeHtml(iface.bus_path || '')}</span>`;

      rowsHtml += `<tr>
        <td style="font-weight: 700; color: #f1f5f9; font-size: 13px;">
          ${escapeHtml(iface.name)} ${iface.is_wireless ? '📶' : '🌐'}
        </td>
        <td style="font-size: 12px; color: #cbd5e1;">${escapeHtml(iface.chipset || 'Standard Ethernet')}</td>
        <td style="font-size: 12px;">${drvStr}</td>
        <td style="font-size: 12px;">${busStr}</td>
        <td>${statusBadge}</td>
        <td style="font-size: 12px;">${macStr}<br><span style="font-size: 11px; color: #38bdf8;">${ipList}</span></td>
        <td>
          <select id="matrix-role-${escapeHtml(iface.name)}" class="form-input port-role-select" data-iface="${escapeHtml(iface.name)}" style="padding: 5px 8px; font-size: 12px; width: 100%;">
            <option value="wan1" ${iface.role === 'wan1' ? 'selected' : ''}>🌐 WAN 1 (Primary)</option>
            <option value="wan2" ${iface.role === 'wan2' ? 'selected' : ''}>🌐 WAN 2 (Secondary)</option>
            <option value="lan" ${iface.role === 'lan' ? 'selected' : ''}>🏠 LAN (br-lan Bridge)</option>
            <option value="guest" ${iface.role === 'guest' ? 'selected' : ''}>📶 ${escapeHtml(t('role_guest_wifi', 'Guest Wi-Fi client'))}</option>
            ${iface.is_wireless || /^wl/.test(iface.name || '') ? `<option value="wifi_main" ${iface.role === 'wifi_main' ? 'selected' : ''}>📡 ${escapeHtml(t('role_main_wifi', 'Main Wi-Fi client (measuring)'))}</option>` : ''}
            <option value="dmz" ${iface.role === 'dmz' ? 'selected' : ''}>🛡️ DMZ (Isolated)</option>
            <option value="unassigned" ${iface.role === 'unassigned' ? 'selected' : ''}>⚪ Unassigned / Disabled</option>
          </select>
        </td>
      </tr>`;
    });
    tbody.innerHTML = rowsHtml;
  }

  function updateSpeedtestInterfaceDropdown(interfaces) {
    const sel = document.getElementById('speedtest-target-iface');
    if (!sel || !interfaces) return;
    const curVal = sel.value || 'auto';
    let opts = '<option value="auto">' + t('target_iface_default', '🌐 Default (Routing)') + '</option>';
    interfaces.forEach(i => {
      opts += `<option value="${escapeHtml(i.name)}">🌐 ${escapeHtml(i.name)} (${escapeHtml(i.chipset || i.driver || 'NIC')}${i.role ? ' - ' + escapeHtml(i.role.toUpperCase()) : ''})</option>`;
    });
    sel.innerHTML = opts;
    if (curVal) sel.value = curVal;
  }

  function toggleWan2StaticFields(val) {
    const isStatic = val === 'static';
    const ipWrap = document.getElementById('wan2-static-ip-wrap');
    const nmWrap = document.getElementById('wan2-static-netmask-wrap');
    const gwWrap = document.getElementById('wan2-static-gw-wrap');
    if (ipWrap) ipWrap.style.display = isStatic ? 'block' : 'none';
    if (nmWrap) nmWrap.style.display = isStatic ? 'block' : 'none';
    if (gwWrap) gwWrap.style.display = isStatic ? 'block' : 'none';
  }

  async function saveInterfaceMatrix() {
    const selects = document.querySelectorAll('.port-role-select');
    let wan1 = '';
    let wan2 = '';
    const lanPorts = [];
    let guest = '';
    let wifiMain = '';
    let dmz = '';

    selects.forEach(sel => {
      const iface = sel.dataset.iface;
      const role = sel.value;
      if (role === 'wan1') wan1 = iface;
      else if (role === 'wan2') wan2 = iface;
      else if (role === 'lan') lanPorts.push(iface);
      else if (role === 'guest') guest = iface;
      else if (role === 'wifi_main') wifiMain = iface;
      else if (role === 'dmz') dmz = iface;
    });

    if (!wan1 && selects.length > 0) {
      wan1 = selects[0].dataset.iface;
    }

    const wanMode = document.getElementById('matrix-wan-mode') ? document.getElementById('matrix-wan-mode').value : 'single';
    const payload = {
      wan1: wan1,
      wan2: wan2,
      wan_mode: wanMode,
      lan_ports: lanPorts,
      guest: guest,
      wifi_main: wifiMain,
      dmz: dmz,
    };

    try {
      showToast(t('saving_settings', 'Saving port matrix & network routing...'));
      const res = await fetch('/api/system/interface_roles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        showToast(data.message || t('settings_saved', 'Port roles saved and applied successfully!'));
        loadInterfaceMatrix();
      } else {
        showToast('Error: ' + (data.message || 'Failed to save port assignments'));
      }
    } catch (e) {
      showToast('Error saving port roles: ' + e);
    }
  }

  async function loadDriverStatus() {
    try {
      const res = await fetch('/api/system/drivers');
      if (!res.ok) return;
      const data = await res.json();
      renderDriverStatus(data);
    } catch (e) {
      console.error('Failed to load driver status:', e);
    }
  }

  function renderDriverStatus(data) {
    const banner = document.getElementById('driver-health-banner');
    const bannerTitle = document.getElementById('driver-health-title');
    const bannerDesc = document.getElementById('driver-health-desc');
    const missingBox = document.getElementById('missing-firmware-box');
    const missingList = document.getElementById('missing-firmware-list');

    if (data.all_drivers_ready) {
      if (banner) {
        banner.style.background = 'rgba(16, 185, 129, 0.1)';
        banner.style.borderColor = 'rgba(16, 185, 129, 0.3)';
        const iconSpan = banner.querySelector('span');
        if (iconSpan) iconSpan.innerText = '✅';
      }
      if (bannerTitle) {
        bannerTitle.innerText = 'All Network Drivers Operational';
        bannerTitle.style.color = '#34d399';
      }
      if (bannerDesc) bannerDesc.innerText = 'All physical network controllers have active kernel drivers and loaded firmware.';
      if (missingBox) missingBox.style.display = 'none';
    } else {
      if (banner) {
        banner.style.background = 'rgba(239, 68, 68, 0.12)';
        banner.style.borderColor = '#ef4444';
        const iconSpan = banner.querySelector('span');
        if (iconSpan) iconSpan.innerText = '⚠️';
      }
      if (bannerTitle) {
        bannerTitle.innerText = `Driver Attention Needed (${data.unsupported_controllers_count} unsupported / ${data.missing_firmware_count} missing firmware)`;
        bannerTitle.style.color = '#f87171';
      }
      if (bannerDesc) bannerDesc.innerText = 'Some network controllers require vendor firmware or kernel driver package installation.';

      if (data.missing_firmware && data.missing_firmware.length > 0 && missingBox && missingList) {
        missingBox.style.display = 'block';
        missingList.innerHTML = data.missing_firmware.map(f => `• ${escapeHtml(f)}`).join('<br>');
      } else if (missingBox) {
        missingBox.style.display = 'none';
      }
    }

    // Render Controllers Table
    const ctrlTbody = document.getElementById('controllers-table-tbody');
    if (ctrlTbody && data.controllers) {
      if (data.controllers.length === 0) {
        ctrlTbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 16px;">No physical controllers detected.</td></tr>';
      } else {
        let ctrlRows = '';
        data.controllers.forEach(c => {
          const typeIcon = c.type === 'pci' ? '🖥️ PCIe' : c.type === 'usb' ? '🔌 USB' : '📦 Onboard';
          const hasDrv = c.has_driver;
          const stBadge = hasDrv
            ? '<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981;">Ready</span>'
            : '<span class="badge-pill" style="background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid #ef4444;">No Driver</span>';

          const hwIds = `<code style="font-size: 11px;">${escapeHtml(c.vendor_id || '')}:${escapeHtml(c.device_id || '')}</code>`;
          ctrlRows += `<tr>
            <td style="font-weight: 600;">${typeIcon}</td>
            <td style="font-size: 12px; color: #94a3b8;">${escapeHtml(c.slot || '--')}</td>
            <td style="font-size: 12px; font-weight: 600; color: #f1f5f9;">${escapeHtml(c.chipset_name || 'Generic Network Controller')}</td>
            <td>${hwIds}</td>
            <td style="font-size: 12px;"><b>${escapeHtml(c.driver || 'none')}</b></td>
            <td>${stBadge}</td>
          </tr>`;
        });
        ctrlTbody.innerHTML = ctrlRows;
      }
    }

    // Render Recommended Packages
    const recsWrap = document.getElementById('recommended-packages-wrap');
    if (recsWrap && data.recommended_packages) {
      if (data.recommended_packages.length === 0) {
        recsWrap.innerHTML = '<div style="color: #94a3b8; font-size: 12px;">All default Linux kernel network drivers are up to date.</div>';
      } else {
        let recsHtml = '';
        data.recommended_packages.forEach(pkg => {
          recsHtml += `<div style="padding: 10px 14px; background: rgba(30, 41, 59, 0.6); border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.08); display: flex; flex-direction: column; justify-content: space-between; gap: 8px;">
            <div>
              <div style="font-weight: 700; font-size: 13px; color: #38bdf8; font-family: monospace;">${escapeHtml(pkg.package)}</div>
              <div style="font-size: 11.5px; color: #94a3b8; margin-top: 2px;">${escapeHtml(pkg.description)}</div>
            </div>
            <div>
              <button type="button" class="btn-secondary" style="font-size: 11px; padding: 4px 10px;" onclick="installDrivers(${jsArg(pkg.package)})">📦 Install ${escapeHtml(pkg.package)}</button>
            </div>
          </div>`;
        });
        recsWrap.innerHTML = recsHtml;
      }
    }

    // Check if installation is in progress
    if (data.install_status && data.install_status.in_progress) {
      showDriverInstallTerminal(data.install_status);
      startDriverInstallPolling();
    }
  }

  async function installDrivers(pkgName) {
    try {
      showToast(t('installing_drivers', 'Starting driver & firmware installation: ') + pkgName);
      const res = await fetch('/api/system/install_drivers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ package: pkgName || 'all' })
      });
      const data = await res.json();
      if (res.ok) {
        showDriverInstallTerminal({ in_progress: true, output: `Starting driver installation [${pkgName}]...
` });
        startDriverInstallPolling();
      } else {
        showToast('Error: ' + (data.message || 'Driver installation could not be started'));
      }
    } catch (e) {
      showToast('Error triggering driver installation: ' + e);
    }
  }

  function showDriverInstallTerminal(status) {
    const card = document.getElementById('driver-install-terminal-card');
    const term = document.getElementById('driver-install-terminal');
    const badge = document.getElementById('driver-install-badge');
    if (!card || !term) return;
    card.style.display = 'block';
    term.textContent = status.output || 'Installation task running...';
    term.scrollTop = term.scrollHeight;

    if (badge) {
      if (status.in_progress) {
        badge.innerText = 'Installing...';
        badge.style.background = 'rgba(234, 179, 8, 0.2)';
        badge.style.color = '#facc15';
        badge.style.border = '1px solid #eab308';
      } else if (status.status === 'ok') {
        badge.innerText = 'Completed Successfully';
        badge.style.background = 'rgba(16, 185, 129, 0.2)';
        badge.style.color = '#34d399';
        badge.style.border = '1px solid #10b981';
      } else {
        badge.innerText = 'Failed';
        badge.style.background = 'rgba(239, 68, 68, 0.2)';
        badge.style.color = '#f87171';
        badge.style.border = '1px solid #ef4444';
      }
    }
  }

  function startDriverInstallPolling() {
    if (driverInstallPollTimer) clearInterval(driverInstallPollTimer);
    driverInstallPollTimer = setInterval(async () => {
      try {
        const res = await fetch('/api/system/drivers/status');
        if (!res.ok) return;
        const status = await res.json();
        showDriverInstallTerminal(status);
        if (!status.in_progress) {
          clearInterval(driverInstallPollTimer);
          driverInstallPollTimer = null;
          showToast(status.status === 'ok' ? 'Driver installation finished successfully!' : 'Driver installation encountered an error.');
          loadDriverStatus();
          loadInterfaceMatrix();
        }
      } catch (e) {
        console.error('Polling driver install status error:', e);
      }
    }, 2000);
  }


  loadInterfaceMatrix();
  loadDriverStatus();

  // =========================================================================
  // DNS Ad-Blocker & Sinkhole (Pi-hole Engine)
  // =========================================================================
  let adblockPollTimer = null;
  let adblockCountdownInterval = null;
  let cachedAdblockStatus = null;
  let cachedAdblockCharts = null;
  let cachedAdblockLogs = [];
  let currentAdblockSubtab = 'dash';
  let activeAdblockLogStatusFilter = 'all';

  function switchAdblockSubtab(subtabId) {
    currentAdblockSubtab = subtabId;
    const subtabs = ['dash', 'log', 'domains', 'adlists', 'localdns', 'guide'];
    subtabs.forEach(id => {
      const pane = document.getElementById('subtab-adblock-' + id);
      const btn = document.getElementById('btn-adblock-subtab-' + id);
      if (pane) pane.style.display = (id === subtabId) ? 'block' : 'none';
      if (btn) {
        if (id === subtabId) {
          btn.classList.add('active');
          const nav = btn.closest('.adblock-subnav') || btn.parentElement;
          if (nav && typeof nav.scrollTo === 'function') {
            const left = btn.offsetLeft - nav.offsetLeft - 16;
            nav.scrollTo({ left: Math.max(0, left), behavior: 'smooth' });
          }
        } else {
          btn.classList.remove('active');
        }
      }
    });

    if (subtabId === 'dash') {
      loadAdblockStatus();
      loadAdblockCharts();
    } else if (subtabId === 'log') {
      loadAdblockQueryLog();
    } else if (subtabId === 'domains') {
      loadAdblockDomains();
    } else if (subtabId === 'adlists') {
      loadAdblockAdlists();
    } else if (subtabId === 'localdns') {
      loadAdblockLocalDns();
    }
  }

  function toggleAdblockDisableMenu(e) {
    if (e) e.stopPropagation();
    const menu = document.getElementById('adblock-disable-menu');
    if (!menu) return;
    menu.style.display = (menu.style.display === 'none' || !menu.style.display) ? 'block' : 'none';
  }

  document.addEventListener('click', (e) => {
    const menu = document.getElementById('adblock-disable-menu');
    const btn = document.getElementById('btn-toggle-adblock');
    if (menu && menu.style.display === 'block') {
      if (btn && btn.contains(e.target)) return;
      if (!menu.contains(e.target)) {
        menu.style.display = 'none';
      }
    }
  });

  async function pauseAdblock(seconds) {
    const menu = document.getElementById('adblock-disable-menu');
    if (menu) menu.style.display = 'none';

    try {
      showToast(t('adblock_toast_pausing', 'Pausing Adblock...') + (seconds > 0 ? ` (${seconds}s)` : ''));
      const res = await fetch('/api/adblock/disable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duration: seconds })
      });
      const data = await res.json();
      if (res.ok) {
        showToast(t('adblock_toast_paused', 'Adblock paused') + (seconds > 0 ? ` (${seconds}s)` : ''));
        loadAdblockStatus();
      }
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  async function resumeAdblock() {
    const menu = document.getElementById('adblock-disable-menu');
    if (menu) menu.style.display = 'none';

    try {
      showToast(t('adblock_toast_enabling', 'Enabling Adblock...'));
      const res = await fetch('/api/adblock/enable', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast(t('adblock_toast_active', 'Adblock is active. Ad filtering is running.'));
        loadAdblockStatus();
      }
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  async function loadAdblockStatus() {
    try {
      const res = await fetch('/api/adblock/status');
      if (!res.ok) return;
      const data = await res.json();
      cachedAdblockStatus = data;
      renderAdblockStatus(data);
    } catch (e) {
      console.error('Failed to load adblock status:', e);
    }
  }

  function renderAdblockStatus(data) {
    if (!data) return;

    // Toggle button & pause countdown
    const toggleBtn = document.getElementById('btn-toggle-adblock');
    const pauseBadge = document.getElementById('adblock-pause-countdown');
    const timerTxt = document.getElementById('adblock-pause-timer-txt');

    if (data.enabled) {
      if (toggleBtn) {
        toggleBtn.innerHTML = t('adblock_active_btn', '🛡️ Ad-Blocker: Active ▾');
        toggleBtn.style.background = 'linear-gradient(135deg, #10b981 0%, #059669 100%)';
      }
      if (pauseBadge) pauseBadge.style.display = 'none';
      if (adblockCountdownInterval) {
        clearInterval(adblockCountdownInterval);
        adblockCountdownInterval = null;
      }
    } else {
      if (toggleBtn) {
        toggleBtn.innerHTML = t('adblock_paused_btn', '⏸️ Ad-Blocker: Paused ▾');
        toggleBtn.style.background = 'linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)';
      }
      if (data.disabled_seconds_left && data.disabled_seconds_left > 0) {
        if (pauseBadge) pauseBadge.style.display = 'inline-flex';
        let leftSec = data.disabled_seconds_left;
        const fmtTimer = (s) => {
          const m = Math.floor(s / 60);
          const sec = s % 60;
          return (m < 10 ? '0' : '') + m + ':' + (sec < 10 ? '0' : '') + sec;
        };
        if (timerTxt) timerTxt.innerText = fmtTimer(leftSec);

        if (!adblockCountdownInterval) {
          adblockCountdownInterval = setInterval(() => {
            leftSec--;
            if (leftSec <= 0) {
              clearInterval(adblockCountdownInterval);
              adblockCountdownInterval = null;
              loadAdblockStatus();
            } else {
              if (timerTxt) timerTxt.innerText = fmtTimer(leftSec);
            }
          }, 1000);
        }
      } else {
        if (pauseBadge) pauseBadge.style.display = 'none';
      }
    }

    // Metric cards
    const blkToday = document.getElementById('adblock-stat-blocked');
    const blkPct = document.getElementById('adblock-stat-pct');
    const totalQ = document.getElementById('adblock-stat-queries');
    const gravCount = document.getElementById('adblock-stat-gravity');
    const upstreams = document.getElementById('adblock-stat-upstream');

    if (blkToday) blkToday.innerText = (data.blocked_queries || 0).toLocaleString();
    if (blkPct) blkPct.innerText = (data.blocked_percentage || 0.0) + '%';
    if (totalQ) totalQ.innerText = (data.total_queries || 0).toLocaleString();
    if (gravCount) gravCount.innerText = (data.domains_in_blocklist || 0).toLocaleString();
    if (upstreams && data.upstreams) upstreams.innerText = data.upstreams.join(', ');

    // Guide box IP
    const guideIp = document.getElementById('adblock-guide-ip');
    if (guideIp && data.guide && data.guide.box_ip) {
      guideIp.innerText = data.guide.box_ip;
    }

    // Whitelist and blacklist badges
    const wlBadge = document.getElementById('adblock-wl-badge');
    if (wlBadge) wlBadge.innerText = data.whitelist_count || 0;
    const blBadge = document.getElementById('adblock-bl-badge');
    if (blBadge) blBadge.innerText = data.blacklist_count || 0;
    const rwlBadge = document.getElementById('adblock-regex-wl-badge');
    if (rwlBadge) rwlBadge.innerText = data.regex_whitelist_count || 0;
    const rblBadge = document.getElementById('adblock-regex-bl-badge');
    if (rblBadge) rblBadge.innerText = data.regex_blacklist_count || 0;

    // Top Blocked Domains Table
    const topBlockedTbody = document.getElementById('adblock-top-blocked-tbody');
    if (topBlockedTbody) {
      const topB = data.top_blocked_domains || [];
      if (topB.length === 0) {
        topBlockedTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted); font-size: 12px;">' + t('adblock_empty_blocked', 'No blocked requests') + '</td></tr>';
      } else {
        topBlockedTbody.innerHTML = topB.map(item => `
          <tr>
            <td style="font-size: 11.5px; font-weight: 600; color: #f87171; word-break: break-all;">${escapeHtml(item.domain)}</td>
            <td style="font-size: 11.5px; font-weight: 700; text-align: right; color: #cbd5e1;">${item.count.toLocaleString()}</td>
            <td style="text-align: center;">
              <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; color: #34d399;" title="${t('adblock_allow_title', 'Allow (add to allowlist)')}" onclick="quickWhitelist(${jsArg(item.domain)})">${t('adblock_btn_allow', '✅ Allow')}</button>
            </td>
          </tr>
        `).join('');
      }
    }

    // Top Queried Permitted Domains Table
    const topQueriedTbody = document.getElementById('adblock-top-queried-tbody');
    if (topQueriedTbody) {
      const topQ = data.top_queried_domains || [];
      if (topQ.length === 0) {
        topQueriedTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted); font-size: 12px;">' + t('adblock_empty_queried', 'No recorded requests') + '</td></tr>';
      } else {
        topQueriedTbody.innerHTML = topQ.map(item => `
          <tr>
            <td style="font-size: 11.5px; font-weight: 600; color: #38bdf8; word-break: break-all;">${escapeHtml(item.domain)}</td>
            <td style="font-size: 11.5px; font-weight: 700; text-align: right; color: #cbd5e1;">${item.count.toLocaleString()}</td>
            <td style="text-align: center;">
              <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; color: #f87171;" title="${t('adblock_block_title', 'Block (add to blocklist)')}" onclick="quickBlacklist(${jsArg(item.domain)})">${t('adblock_btn_block', '⛔ Block')}</button>
            </td>
          </tr>
        `).join('');
      }
    }

    // Top Clients Table
    const topClientsTbody = document.getElementById('adblock-top-clients-tbody');
    if (topClientsTbody) {
      const topC = data.top_clients || [];
      if (topC.length === 0) {
        topClientsTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted); font-size: 12px;">' + t('adblock_empty_clients', 'No clients recorded') + '</td></tr>';
      } else {
        topClientsTbody.innerHTML = topC.map(item => `
          <tr>
            <td style="font-size: 11px;">
              <div style="font-weight: 700; color: #f1f5f9; cursor: pointer;" onclick="filterLogByClient(${jsArg(item.ip)})">${escapeHtml(item.ip)}</div>
              <div style="font-size: 11px; color: #94a3b8;">${escapeHtml(item.hostname || item.ip)}</div>
            </td>
            <td style="font-size: 11.5px; font-weight: 700; text-align: right; color: #cbd5e1;">${item.total.toLocaleString()}</td>
            <td style="font-size: 11.5px; font-weight: 700; text-align: right; color: ${item.blocked > 0 ? '#f87171' : '#64748b'};">${escapeHtml(item.blocked_pct)}%</td>
          </tr>
        `).join('');
      }
    }
  }

  async function loadAdblockCharts() {
    try {
      const res = await fetch('/api/adblock/charts');
      if (!res.ok) return;
      const data = await res.json();
      cachedAdblockCharts = data;
      renderAdblockTimeline(data.timeline || []);
      renderQueryTypes(data.query_types || {});
      renderUpstreamDestinations(data.upstreams || {});
    } catch (e) {
      console.error('Failed to load adblock charts:', e);
    }
  }

  // Pure SVG Interactive 24-Hour Timeline Chart
  function renderAdblockTimeline(timeline) {
    const svg = document.getElementById('adblock-timeline-svg');
    if (!svg) return;

    if (!timeline || timeline.length === 0) {
      svg.innerHTML = '<text x="400" y="100" fill="#64748b" text-anchor="middle" font-size="13">Nincsenek adatok a grafikonhoz</text>';
      return;
    }

    // Aggregate into 48 intervals (30 mins each) for clean display
    const aggregated = [];
    const step = Math.max(1, Math.floor(timeline.length / 48));
    for (let i = 0; i < timeline.length; i += step) {
      const chunk = timeline.slice(i, i + step);
      let tot = 0, blk = 0;
      chunk.forEach(c => { tot += (c.total || 0); blk += (c.blocked || 0); });
      aggregated.push({
        time_str: chunk[chunk.length - 1].time_str,
        total: tot,
        blocked: blk,
        allowed: Math.max(0, tot - blk)
      });
    }

    let maxVal = 10;
    aggregated.forEach(p => {
      if (p.total > maxVal) maxVal = p.total;
    });
    // Add 15% headroom
    maxVal = Math.ceil(maxVal * 1.15);

    const W = 800;
    const H = 200;
    const padL = 40;
    const padR = 20;
    const padT = 15;
    const padB = 30;
    const chartW = W - padL - padR;
    const chartH = H - padT - padB;

    let svgHtml = '';

    // Grid lines
    const gridSteps = 4;
    for (let g = 0; g <= gridSteps; g++) {
      const yVal = Math.round((maxVal / gridSteps) * g);
      const yPos = padT + chartH - (g / gridSteps) * chartH;
      svgHtml += `<line x1="${padL}" y1="${yPos}" x2="${W - padR}" y2="${yPos}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3" />`;
      svgHtml += `<text x="${padL - 8}" y="${yPos + 4}" fill="#64748b" font-size="10" text-anchor="end" font-family="monospace">${yVal}</text>`;
    }

    const n = aggregated.length;
    const colW = (chartW / n) * 0.75;
    const gap = (chartW / n) * 0.25;

    aggregated.forEach((p, idx) => {
      const x = padL + idx * (colW + gap);
      const totH = (p.total / maxVal) * chartH;
      const blkH = (p.blocked / maxVal) * chartH;
      const allowH = totH - blkH;

      const yAllowed = padT + chartH - allowH;
      const yBlocked = yAllowed - blkH;

      // Base allowed bar (teal)
      if (allowH > 0) {
        svgHtml += `<rect x="${x}" y="${yAllowed}" width="${colW}" height="${allowH}" fill="#10b981" rx="1.5" />`;
      }
      // Stacked blocked bar (red)
      if (blkH > 0) {
        svgHtml += `<rect x="${x}" y="${yBlocked}" width="${colW}" height="${blkH}" fill="#ef4444" rx="1.5" />`;
      }

      // Transparent hit-target for hover tooltips
      const pct = p.total > 0 ? ((p.blocked / p.total) * 100).toFixed(1) + '%' : '0.0%';
      svgHtml += `<rect x="${x - gap/2}" y="${padT}" width="${colW + gap}" height="${chartH}" fill="transparent" style="cursor: pointer;"
        onmousemove="showChartTooltip(event, ${jsArg(p.time_str)}, ${p.total}, ${p.blocked}, '${pct}')"
        onmouseleave="hideChartTooltip()" />`;

      // X-axis time labels every 8 bars (~4 hours)
      if (idx % 8 === 0 || idx === n - 1) {
        svgHtml += `<text x="${x + colW / 2}" y="${H - 10}" fill="#94a3b8" font-size="10" text-anchor="middle" font-family="monospace">${escapeHtml(p.time_str)}</text>`;
      }
    });

    svg.innerHTML = svgHtml;
  }

  function showChartTooltip(event, timeStr, total, blocked, pct) {
    const tooltip = document.getElementById('adblock-chart-tooltip');
    const wrap = document.getElementById('adblock-timeline-chart-wrap');
    if (!tooltip || !wrap) return;

    const rect = wrap.getBoundingClientRect();
    const x = event.clientX - rect.left + 15;
    const y = event.clientY - rect.top - 20;

    tooltip.style.left = Math.min(x, rect.width - 150) + 'px';
    tooltip.style.top = Math.max(10, y) + 'px';
    tooltip.innerHTML = `
      <div style="font-weight: 700; color: #38bdf8; margin-bottom: 2px;">🕒 ${timeStr}</div>
      <div>${t('adblock_tooltip_total', 'Total requests:')} <b>${total}</b></div>
      <div style="color: #f87171;">${t('adblock_tooltip_blocked', 'Blocked:')} <b>${blocked}</b> (${pct})</div>
    `;
    tooltip.style.display = 'block';
  }

  function hideChartTooltip() {
    const tooltip = document.getElementById('adblock-chart-tooltip');
    if (tooltip) tooltip.style.display = 'none';
  }

  function renderQueryTypes(qtypes) {
    const container = document.getElementById('adblock-qtypes-container');
    if (!container) return;

    let total = 0;
    Object.values(qtypes).forEach(v => { total += v; });

    const keys = ['A', 'AAAA', 'HTTPS', 'PTR', 'TXT', 'SRV'];
    const colors = {
      'A': '#38bdf8',
      'AAAA': '#a855f7',
      'HTTPS': '#10b981',
      'PTR': '#f59e0b',
      'TXT': '#64748b',
      'SRV': '#ec4899'
    };

    let html = '';
    keys.forEach(k => {
      const cnt = qtypes[k] || 0;
      const pct = total > 0 ? ((cnt / total) * 100).toFixed(1) : '0.0';
      const col = colors[k] || '#94a3b8';

      html += `
        <div>
          <div style="display: flex; justify-content: space-between; font-size: 11.5px; margin-bottom: 4px;">
            <span style="font-weight: 700; color: ${col}; font-family: monospace;">${escapeHtml(k)}</span>
            <span style="color: #cbd5e1; font-family: monospace;">${cnt.toLocaleString()} (${pct}%)</span>
          </div>
          <div style="background: rgba(255,255,255,0.06); height: 6px; border-radius: 3px; overflow: hidden;">
            <div style="background: ${col}; width: ${pct}%; height: 100%; border-radius: 3px; transition: width 0.3s ease;"></div>
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  }

  function renderUpstreamDestinations(upstreams) {
    const container = document.getElementById('adblock-upstreams-container');
    if (!container) return;

    let total = 0;
    Object.values(upstreams).forEach(v => { total += v; });

    const friendlyNames = {
      'cache': t('adblock_upstream_cache', '⚡ Local Cache'),
      'blocked': t('adblock_upstream_blocked', '🛑 Sinkhole (Blocked)'),
      'local_dns': '🏠 Helyi DNS (custom.list)',
      '1.1.1.1': '🌐 Cloudflare (1.1.1.1)',
      '1.0.0.1': '🌐 Cloudflare Sec (1.0.0.1)',
      '9.9.9.9': '🛡️ Quad9 DNS (9.9.9.9)',
      '149.112.112.112': '🛡️ Quad9 Sec',
      '8.8.8.8': '🌐 Google DNS (8.8.8.8)'
    };

    const colors = {
      'cache': '#38bdf8',
      'blocked': '#ef4444',
      'local_dns': '#34d399',
      '1.1.1.1': '#f59e0b',
      '1.0.0.1': '#fbbf24',
      '9.9.9.9': '#a855f7',
      '149.112.112.112': '#c084fc',
      '8.8.8.8': '#60a5fa'
    };

    let html = '';
    const sortedKeys = Object.keys(upstreams).sort((a, b) => upstreams[b] - upstreams[a]);
    if (sortedKeys.length === 0) {
      container.innerHTML = '<div style="font-size: 12px; color: var(--text-muted); text-align: center; padding: 10px;">' + t('adblock_empty_upstreams', 'No answered requests yet') + '</div>';
      return;
    }

    sortedKeys.forEach(k => {
      const cnt = upstreams[k] || 0;
      const pct = total > 0 ? ((cnt / total) * 100).toFixed(1) : '0.0';
      const name = friendlyNames[k] || k;
      const col = colors[k] || '#94a3b8';

      html += `
        <div>
          <div style="display: flex; justify-content: space-between; font-size: 11.5px; margin-bottom: 4px;">
            <span style="font-weight: 600; color: #f1f5f9;">${escapeHtml(name)}</span>
            <span style="color: #cbd5e1; font-family: monospace;">${cnt.toLocaleString()} (${pct}%)</span>
          </div>
          <div style="background: rgba(255,255,255,0.06); height: 6px; border-radius: 3px; overflow: hidden;">
            <div style="background: ${col}; width: ${pct}%; height: 100%; border-radius: 3px; transition: width 0.3s ease;"></div>
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  }

  function setAdblockLogFilter(status) {
    activeAdblockLogStatusFilter = status;
    const btns = {
      'all': document.getElementById('btn-adblock-filter-all'),
      'BLOCKED': document.getElementById('btn-adblock-filter-blocked'),
      'ALLOWED': document.getElementById('btn-adblock-filter-allowed'),
      'CACHED': document.getElementById('btn-adblock-filter-cached')
    };
    Object.keys(btns).forEach(k => {
      if (btns[k]) {
        btns[k].className = (k === status) ? 'btn-primary' : 'btn-secondary';
      }
    });
    filterAdblockLog();
  }

  function filterLogByClient(ip) {
    switchAdblockSubtab('log');
    const input = document.getElementById('adblock-log-filter');
    if (input) {
      input.value = ip;
      filterAdblockLog();
    }
  }

  async function loadAdblockQueryLog() {
    try {
      const res = await fetch('/api/adblock/querylog?limit=100');
      if (!res.ok) return;
      const data = await res.json();
      cachedAdblockLogs = data.queries || [];
      renderAdblockQueryLog(cachedAdblockLogs);
    } catch (e) {
      console.error('Failed to load adblock query log:', e);
    }
  }

  function renderAdblockQueryLog(queries) {
    const tbody = document.getElementById('adblock-querylog-tbody');
    if (!tbody) return;
    if (!queries || queries.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); font-size: 12px;">' + t('adblock_empty_querylog', 'No DNS queries logged') + '</td></tr>';
      return;
    }

    tbody.innerHTML = queries.map(q => {
      let stBadge = '';
      if (q.status === 'BLOCKED') {
        const reason = q.reason ? ` (${escapeHtml(q.reason)})` : '';
        stBadge = `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 700;">🛑 BLOCKED${reason}</span>`;
      } else if (q.status === 'CACHED') {
        stBadge = `<span class="badge" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 700;">⚡ CACHED</span>`;
      } else {
        const upTxt = q.upstream ? ` (${escapeHtml(q.upstream)})` : '';
        stBadge = `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 700;">🟢 ALLOWED${upTxt}</span>`;
      }

      const clientDisplay = q.client_name && q.client_name !== q.client_ip
        ? `<div style="font-weight: 600; color: #f1f5f9;">${escapeHtml(q.client_name)}</div><div style="font-size: 11px; color: #94a3b8;">${escapeHtml(q.client_ip)}</div>`
        : `<div style="font-family: monospace; color: #cbd5e1;">${escapeHtml(q.client_ip || '')}</div>`;

      return `<tr>
        <td style="font-size: 11.5px; color: #94a3b8; font-family: monospace;">${escapeHtml(q.time_str || '')}</td>
        <td style="font-size: 11.5px;">${clientDisplay}</td>
        <td><span class="badge" style="background: rgba(255,255,255,0.06); color: #cbd5e1; font-size: 11px; padding: 2px 5px; border-radius: 3px; font-family: monospace;">${escapeHtml(q.type || 'A')}</span></td>
        <td>${stBadge}</td>
        <td style="font-size: 11.5px; color: var(--text-muted); font-family: monospace;">${q.latency_ms ? q.latency_ms.toFixed(1) + 'ms' : '<0.1ms'}</td>
        <td style="font-size: 11.5px; font-weight: 600; color: ${q.status === 'BLOCKED' ? '#f87171' : '#f1f5f9'}; word-break: break-all;">${escapeHtml(q.domain || '')}</td>
        <td style="text-align: center; white-space: nowrap;">
          <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; color: #f87171; margin-right: 4px;" title="${t('adblock_block_title', 'Block (add to blocklist)')}" onclick="quickBlacklist(${jsArg(q.domain)})">${t('adblock_btn_block', '⛔ Block')}</button>
          <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; color: #34d399;" title="${t('adblock_allow_title', 'Allow (add to allowlist)')}" onclick="quickWhitelist(${jsArg(q.domain)})">${t('adblock_btn_allow', '✅ Allow')}</button>
        </td>
      </tr>`;
    }).join('');
  }

  function filterAdblockLog() {
    const filterInput = document.getElementById('adblock-log-filter');
    const term = filterInput ? filterInput.value.toLowerCase().trim() : '';

    let filtered = cachedAdblockLogs;
    if (activeAdblockLogStatusFilter !== 'all') {
      filtered = filtered.filter(q => q.status === activeAdblockLogStatusFilter);
    }
    if (term) {
      filtered = filtered.filter(q =>
        (q.domain && q.domain.toLowerCase().includes(term)) ||
        (q.client_ip && q.client_ip.toLowerCase().includes(term)) ||
        (q.client_name && q.client_name.toLowerCase().includes(term)) ||
        (q.type && q.type.toLowerCase().includes(term))
      );
    }
    renderAdblockQueryLog(filtered);
  }

  async function quickBlacklist(domain) {
    if (!domain) return;
    try {
      const res = await fetch('/api/adblock/blacklist/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: domain })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_toast_blacklisted', `'${domain}' added to blacklist (instantly blocked)`));
        loadAdblockStatus();
        loadAdblockQueryLog();
      } else {
        showToast(t('adblock_toast_add_err', 'Error adding domain'));
      }
    } catch (e) {
      showToast(t('common_err', 'Error: ') + e);
    }
  }

  async function quickWhitelist(domain) {
    if (!domain) return;
    try {
      const res = await fetch('/api/adblock/whitelist/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: domain })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_toast_whitelisted', `'${domain}' added to whitelist (always allowed)`));
        loadAdblockStatus();
        loadAdblockQueryLog();
      } else {
        showToast(t('adblock_toast_add_err', 'Error adding domain'));
      }
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  // Subtab 3: Whitelist, Blacklist, RegEx Management
  async function loadAdblockDomains() {
    try {
      const [wlRes, blRes, rgxRes] = await Promise.all([
        fetch('/api/adblock/whitelist'),
        fetch('/api/adblock/blacklist'),
        fetch('/api/adblock/regex')
      ]);

      if (wlRes.ok) {
        const wlData = await wlRes.json();
        const wlTbody = document.getElementById('adblock-wl-tbody');
        if (wlTbody) {
          const list = wlData.whitelist || [];
          if (list.length === 0) {
            wlTbody.innerHTML = '<tr><td style="color: var(--text-muted); font-size: 12px; text-align: center;">' + t('adblock_empty_wl', 'No allowlisted domains') + '</td></tr>';
          } else {
            wlTbody.innerHTML = list.map(d => `
              <tr>
                <td style="font-size: 12px; font-weight: 600; color: #34d399;">${escapeHtml(d)}</td>
                <td style="text-align: right; width: 40px;">
                  <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; color: #f87171;" onclick="removeAdblockWhitelist(${jsArg(d)})">✕</button>
                </td>
              </tr>
            `).join('');
          }
        }
      }

      if (blRes.ok) {
        const blData = await blRes.json();
        const blTbody = document.getElementById('adblock-bl-tbody');
        if (blTbody) {
          const list = blData.blacklist || [];
          if (list.length === 0) {
            blTbody.innerHTML = '<tr><td style="color: var(--text-muted); font-size: 12px; text-align: center;">' + t('adblock_bl_empty', 'No custom blocked domains') + '</td></tr>';
          } else {
            blTbody.innerHTML = list.map(d => `
              <tr>
                <td style="font-size: 12px; font-weight: 600; color: #f87171;">${escapeHtml(d)}</td>
                <td style="text-align: right; width: 40px;">
                  <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; color: #f87171;" onclick="removeAdblockBlacklist(${jsArg(d)})">✕</button>
                </td>
              </tr>
            `).join('');
          }
        }
      }

      if (rgxRes.ok) {
        const rgxData = await rgxRes.json();
        const rgx = rgxData.regex || { blacklist: [], whitelist: [] };

        const rwlTbody = document.getElementById('adblock-regex-wl-tbody');
        if (rwlTbody) {
          const list = rgx.whitelist || [];
          if (list.length === 0) {
            rwlTbody.innerHTML = '<tr><td style="color: var(--text-muted); font-size: 12px; text-align: center;">' + t('adblock_regex_wl_empty', 'No RegEx allow rules defined') + '</td></tr>';
          } else {
            rwlTbody.innerHTML = list.map(it => `
              <tr>
                <td style="font-size: 11.5px; font-weight: 600; color: #34d399; font-family: monospace;">${escapeHtml(it.pattern)}</td>
                <td style="text-align: right; width: 40px;">
                  <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; color: #f87171;" onclick="removeAdblockRegexFilter(${jsArg(it.pattern)}, 'white')">✕</button>
                </td>
              </tr>
            `).join('');
          }
        }

        const rblTbody = document.getElementById('adblock-regex-bl-tbody');
        if (rblTbody) {
          const list = rgx.blacklist || [];
          if (list.length === 0) {
            rblTbody.innerHTML = '<tr><td style="color: var(--text-muted); font-size: 12px; text-align: center;">' + t('adblock_regex_bl_empty', 'No RegEx block rules defined') + '</td></tr>';
          } else {
            rblTbody.innerHTML = list.map(it => `
              <tr>
                <td style="font-size: 11.5px; font-weight: 600; color: #f87171; font-family: monospace;">${escapeHtml(it.pattern)}</td>
                <td style="text-align: right; width: 40px;">
                  <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; color: #f87171;" onclick="removeAdblockRegexFilter(${jsArg(it.pattern)}, 'black')">✕</button>
                </td>
              </tr>
            `).join('');
          }
        }
      }
    } catch (e) {
      console.error('Failed to load adblock domains:', e);
    }
  }

  async function addAdblockWhitelist() {
    const input = document.getElementById('adblock-wl-input');
    if (!input || !input.value.trim()) return;
    const dom = input.value.trim();
    try {
      const res = await fetch('/api/adblock/whitelist/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: dom })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_toast_wl_added', `'${dom}' added to whitelist`));
        input.value = '';
        loadAdblockDomains();
        loadAdblockStatus();
      } else {
        showToast(t('adblock_toast_invalid_dom', 'Invalid domain name'));
      }
    } catch (e) {
      showToast(t('common_err', 'Error: ') + e);
    }
  }

  async function removeAdblockWhitelist(dom) {
    try {
      const res = await fetch('/api/adblock/whitelist/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: dom })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_toast_wl_removed', `'${dom}' removed from whitelist`));
        loadAdblockDomains();
        loadAdblockStatus();
      }
    } catch (e) {
      showToast(t('common_err', 'Error: ') + e);
    }
  }

  async function addAdblockBlacklist() {
    const input = document.getElementById('adblock-bl-input');
    if (!input || !input.value.trim()) return;
    const dom = input.value.trim();
    try {
      const res = await fetch('/api/adblock/blacklist/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: dom })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_toast_bl_added', `'${dom}' added to blacklist`));
        input.value = '';
        loadAdblockDomains();
        loadAdblockStatus();
      } else {
        showToast(t('adblock_toast_invalid_dom', 'Invalid domain name'));
      }
    } catch (e) {
      showToast(t('common_err', 'Error: ') + e);
    }
  }

  async function removeAdblockBlacklist(dom) {
    try {
      const res = await fetch('/api/adblock/blacklist/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: dom })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_toast_bl_removed', `'${dom}' removed from blacklist`));
        loadAdblockDomains();
        loadAdblockStatus();
      }
    } catch (e) {
      showToast(t('common_err', 'Error: ') + e);
    }
  }

  async function addAdblockRegexFilter(kind) {
    const input = document.getElementById(kind === 'white' ? 'adblock-regex-wl-input' : 'adblock-regex-bl-input');
    if (!input || !input.value.trim()) return;
    const pat = input.value.trim();
    try {
      const res = await fetch('/api/adblock/regex/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern: pat, kind: kind })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_regex_added', 'RegEx rule added') + ` (${kind})`);
        input.value = '';
        loadAdblockDomains();
        loadAdblockStatus();
      } else {
        showToast(data.message || data.error || t('adblock_invalid_regex', 'Invalid RegEx pattern'));
        loadAdblockStatus();
      }
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  // Subtab 4: Adlists / Gravity Sources
  async function loadAdblockAdlists() {
    try {
      const res = await fetch('/api/adblock/adlists');
      if (!res.ok) return;
      const data = await res.json();
      const tbody = document.getElementById('adblock-adlists-tbody');
      if (!tbody) return;

      const lists = data.adlists || [];
      if (lists.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); font-size: 12px;">' + t('adblock_empty_lists', 'No blocklists configured') + '</td></tr>';
        return;
      }

      tbody.innerHTML = lists.map(item => `
        <tr>
          <td style="text-align: center;">
            <input type="checkbox" ${item.enabled ? 'checked' : ''} onchange="toggleAdblockAdlistSource(${jsArg(item.url)}, this.checked)" style="transform: scale(1.2); cursor: pointer;">
          </td>
          <td>
            <div style="font-weight: 700; color: #f1f5f9; font-size: 12px;">${escapeHtml(item.name || 'Blocklist')}</div>
            <div style="font-size: 11px; color: #38bdf8; word-break: break-all;">${escapeHtml(item.url)}</div>
          </td>
          <td style="text-align: right; font-weight: 700; color: #34d399; font-size: 12px; font-family: monospace;">
            ${(item.count || 0).toLocaleString()}
          </td>
          <td style="font-size: 11px; color: #94a3b8;">
            ${item.updated_at ? escapeHtml(item.updated_at.replace('T', ' ').slice(0, 19)) : t('adblock_list_not_updated', 'Not updated yet')}
          </td>
          <td style="text-align: center;">
            <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; color: #f87171;" onclick="removeAdblockAdlistSource(${jsArg(item.url)})">✕</button>
          </td>
        </tr>
      `).join('');
    } catch (e) {
      console.error('Failed to load adlists:', e);
    }
  }

  async function addAdblockAdlistSource() {
    const urlInput = document.getElementById('adblock-adlist-url-input');
    const nameInput = document.getElementById('adblock-adlist-name-input');
    if (!urlInput || !urlInput.value.trim()) return;

    const url = urlInput.value.trim();
    const name = nameInput ? nameInput.value.trim() : '';

    try {
      const res = await fetch('/api/adblock/adlists/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url, name: name })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_list_added', 'New blocklist source added'));
        urlInput.value = '';
        if (nameInput) nameInput.value = '';
        loadAdblockAdlists();
      } else {
        showToast(t('adblock_invalid_url', 'Invalid URL format'));
      }
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  async function toggleAdblockAdlistSource(url, enabled) {
    try {
      const res = await fetch('/api/adblock/adlists/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url, enabled: enabled })
      });
      if (res.ok) {
        showToast(enabled ? t('adblock_list_on', 'Blocklist enabled') : t('adblock_list_off', 'Blocklist disabled'));
      }
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  async function removeAdblockAdlistSource(url) {
    try {
      const res = await fetch('/api/adblock/adlists/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_toast_src_deleted', 'Blocklist source deleted'));
        loadAdblockAdlists();
      }
    } catch (e) {
      showToast(t('common_err', 'Error: ') + e);
    }
  }

  // Subtab 5: Local DNS Records
  async function loadAdblockLocalDns() {
    try {
      const res = await fetch('/api/adblock/localdns');
      if (!res.ok) return;
      const data = await res.json();
      const tbody = document.getElementById('adblock-localdns-tbody');
      if (!tbody) return;

      const records = data.records || [];
      if (records.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); font-size: 12px;" data-i18n="adblock_localdns_none">' + t('adblock_localdns_none', 'No configured local DNS records') + '</td></tr>';
        return;
      }

      tbody.innerHTML = records.map(r => `
        <tr>
          <td style="font-weight: 700; color: #38bdf8; font-size: 12.5px; font-family: monospace;">${escapeHtml(r.domain)}</td>
          <td style="font-weight: 700; color: #34d399; font-size: 12.5px; font-family: monospace;">${escapeHtml(r.ip)}</td>
          <td style="text-align: center;">
            <span class="badge" style="font-size: 11px; background: rgba(255,255,255,0.06); color: #cbd5e1;">${r.ip.includes(':') ? 'AAAA' : 'A'}</span>
          </td>
          <td style="text-align: center;">
            <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; color: #f87171;" onclick="removeAdblockLocalDnsRecord(${jsArg(r.domain)})">✕</button>
          </td>
        </tr>
      `).join('');
    } catch (e) {
      console.error('Failed to load local DNS records:', e);
    }
  }

  async function addAdblockLocalDnsRecord() {
    const domInput = document.getElementById('adblock-localdns-domain-input');
    const ipInput = document.getElementById('adblock-localdns-ip-input');
    if (!domInput || !ipInput || !domInput.value.trim() || !ipInput.value.trim()) {
      showToast(t('adblock_toast_specify_domain_ip', 'Please specify both hostname and IP address!'));
      return;
    }
    const dom = domInput.value.trim();
    const ip = ipInput.value.trim();

    try {
      const res = await fetch('/api/adblock/localdns/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: dom, ip: ip })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_toast_localdns_saved', `Local record saved: ${dom} -> ${ip}`));
        domInput.value = '';
        ipInput.value = '';
        loadAdblockLocalDns();
      } else {
        showToast(t('adblock_toast_invalid_ip_dom', 'Invalid IP address or hostname format'));
      }
    } catch (e) {
      showToast(t('common_err', 'Error: ') + e);
    }
  }

  async function removeAdblockLocalDnsRecord(domain) {
    try {
      const res = await fetch('/api/adblock/localdns/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: domain })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(t('adblock_toast_localdns_deleted', `Local record deleted: ${domain}`));
        loadAdblockLocalDns();
      }
    } catch (e) {
      showToast(t('common_err', 'Error: ') + e);
    }
  }

  async function updateGravity() {
    try {
      showToast(t('adblock_toast_updating_gravity', 'Updating Gravity (downloading blocklists in background)...'));
      switchAdblockSubtab('adlists');

      const logBox = document.getElementById('adblock-gravity-log');
      const badge = document.getElementById('adblock-gravity-status-badge');
      if (logBox) logBox.innerText = t('adblock_log_starting_gravity', 'Gravity update triggered, downloading external lists...');
      if (badge) {
        badge.innerText = t('status_in_progress', 'In Progress...');
        badge.style.color = '#fbbf24';
        badge.style.background = 'rgba(245, 158, 11, 0.15)';
      }

      const res = await fetch('/api/adblock/update', { method: 'POST' });
      if (!res.ok) return;

      const pollGravityTimer = setInterval(async () => {
        try {
          const stRes = await fetch('/api/adblock/update/status');
          if (stRes.ok) {
            const stData = await stRes.json();
            if (logBox && stData.output) logBox.innerText = stData.output;
            if (!stData.in_progress) {
              clearInterval(pollGravityTimer);
              if (badge) {
                badge.innerText = stData.status === 'ok' ? t('status_success', 'Success') : t('status_completed', 'Completed');
                badge.style.color = '#34d399';
                badge.style.background = 'rgba(16, 185, 129, 0.15)';
              }
              showToast(t('adblock_gravity_updated', 'Gravity successfully updated!'));
              loadAdblockStatus();
              loadAdblockAdlists();
            }
          }
        } catch (e) {}
      }, 1500);
    } catch (e) {
      showToast(t('adblock_gravity_err', 'Error updating gravity: ') + e);
    }
  }

  function startAdblockPolling() {
    if (adblockPollTimer) clearInterval(adblockPollTimer);
    adblockPollTimer = setInterval(() => {
      if (currentAdblockSubtab === 'dash') {
        loadAdblockStatus();
      } else if (currentAdblockSubtab === 'log') {
        loadAdblockQueryLog();
      }
    }, 4000);
  }

  function stopAdblockPolling() {
    if (adblockPollTimer) {
      clearInterval(adblockPollTimer);
      adblockPollTimer = null;
    }
    if (adblockCountdownInterval) {
      clearInterval(adblockCountdownInterval);
      adblockCountdownInterval = null;
    }
  }

  function updateServerSelectVisibility(engine) {
    const currentEngine = (engine || selectedEngine || window.currentAutomatedEngine || 'ookla').toLowerCase();
    const homeServerWrap = document.getElementById('home-target-server-container');
    const schedServerWrap = document.getElementById('sched-target-server-wrap');
    const schedIperfWrap = document.getElementById('sched-iperf-target-wrap');

    const isOoklaOrMixed = (currentEngine === 'ookla' || currentEngine === 'all');
    const isIperf = (currentEngine === 'iperf3');

    if (homeServerWrap) {
      homeServerWrap.style.display = isOoklaOrMixed ? 'flex' : 'none';
    }
    if (schedServerWrap) {
      schedServerWrap.style.display = isOoklaOrMixed ? 'block' : 'none';
    }
    if (schedIperfWrap) {
      schedIperfWrap.style.display = isIperf ? 'block' : 'none';
    }
  }

  function onSchedEngineSelectChange(val) {
    selectEngine(val);
  }

  // Fast.com: every Netflix server with its latency and share of the transfer.
  function renderFastcomDetail(det) {
    const box = document.getElementById('home-fastcom-detail');
    if (!box) return;
    if (!det || !det.servers || !det.servers.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
    const n = v => (v === null || v === undefined || v === '') ? '--' : escapeHtml(String(v));
    const c = det.client || {};
    const rows = det.servers.map(s => `<tr${s.host === det.closest_server ? ' style="color:#f8fafc; font-weight:600;"' : ''}>
        <td title="${n(s.host)}">${n(s.label)}</td><td>${n([s.city, s.country].filter(Boolean).join(', '))}</td>
        <td style="text-align:right;">${n(s.latency_ms)}</td><td style="text-align:right;">${n(s.tcp_connect_ms)}</td>
        <td style="text-align:right;">${n(s.download_mbps)}</td><td style="text-align:right;">${n(s.upload_mbps)}</td></tr>`).join('');
    const d = det.download || {}, u = det.upload || {};
    box.innerHTML = `
      <div style="font-size: 12px; color:#94a3b8; margin-bottom: 6px;">${escapeHtml(t('fc_seen_as', 'Fast.com sees you as'))}: <b style="color:#e2e8f0;">${n(c.isp)}</b> (AS${n(c.asn)}), ${n([c.city, c.country].filter(Boolean).join(', '))}, ${n(c.ip)}</div>
      <div style="font-size: 12px; color:#94a3b8; margin-bottom: 6px;">⬇️ ${escapeHtml(t('fc_stable', 'stable'))} ${n(d.stable_mbps)} · ${escapeHtml(t('fc_mean', 'mean'))} ${n(d.mean_mbps)} · ${escapeHtml(t('fc_peak', 'peak'))} ${n(d.peak_mbps)} Mbps &nbsp; ⬆️ ${escapeHtml(t('fc_stable', 'stable'))} ${n(u.stable_mbps)} · ${escapeHtml(t('fc_mean', 'mean'))} ${n(u.mean_mbps)} · ${escapeHtml(t('fc_peak', 'peak'))} ${n(u.peak_mbps)} Mbps</div>
      <div style="font-size: 12px; color:#94a3b8; margin-bottom: 6px;">${escapeHtml(t('fc_loaded', 'Latency under load'))}: ⬇️ ${n(det.loaded_latency_down_ms)} ms · ⬆️ ${n(det.loaded_latency_up_ms)} ms</div>
      <table class="data-table" style="font-size: 12px; width: 100%;">
        <thead><tr><th>${escapeHtml(t('fc_col_server', 'Netflix server'))}</th><th>${escapeHtml(t('fc_col_place', 'Place'))}</th>
          <th style="text-align:right;">${escapeHtml(t('fc_col_latency', 'Latency ms'))}</th><th style="text-align:right;">TCP ms</th>
          <th style="text-align:right;">⬇️ Mbps</th><th style="text-align:right;">⬆️ Mbps</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    box.style.display = 'block';
  }

  function renderHomeEngineCard(engine, dataOverride) {
    const data = dataOverride || window.lastStatusData;
    if (!data) return;
    const targetEng = (engine || selectedEngine || window.currentAutomatedEngine || 'ookla').toLowerCase();
    
    // Locate speedtest record for targetEng
    let latest = null;
    if (targetEng === 'all') {
      latest = data.latest_speedtest;
    } else {
      if (window.latestPerEngine && window.latestPerEngine[targetEng]) {
        latest = window.latestPerEngine[targetEng];
      } else if (window.allRecentSpeedtests && window.allRecentSpeedtests.length) {
        latest = window.allRecentSpeedtests.find(s => (s.engine || '').toLowerCase() === targetEng && s.status === 'ok') || null;
      }
      if (!latest && data.latest_speedtest && (data.latest_speedtest.engine || 'ookla').toLowerCase() === targetEng) {
        latest = data.latest_speedtest;
      }
    }

    const elPublicIp = document.getElementById('home-public-ip');
    const elEngine = document.getElementById('home-engine');
    const elTimestamp = document.getElementById('home-timestamp');
    const elDownload = document.getElementById('home-download');
    const elUpload = document.getElementById('home-upload');
    const elLatency = document.getElementById('home-latency');
    const elBufferbloat = document.getElementById('home-bufferbloat');
    const elServerLink = document.getElementById('home-server-link');
    const elScriptBox = document.getElementById('home-script-box');

    const contractDown = (data.contract && data.contract.contract_down_mbps) ? parseFloat(data.contract.contract_down_mbps) : 0;
    const contractUp = (data.contract && data.contract.contract_up_mbps) ? parseFloat(data.contract.contract_up_mbps) : 0;

    if (latest) {
      let ipDisplay = '';
      const v4 = escapeHtml(latest.client_ip || (data.system_info && data.system_info.public_ipv4) || (data.system_info && data.system_info.wan_ip) || '');
      const v6 = escapeHtml(latest.client_ipv6 || (data.system_info && data.system_info.public_ipv6) || '');
      if (v4 && v6) {
        ipDisplay = `<span style="color:#38bdf8; font-weight:600;" title="IPv4">${v4}</span> <span style="color:var(--text-muted); font-size:11px;">/</span> <span style="color:#a78bfa; font-size:11px; word-break:break-all;" title="IPv6">${v6}</span>`;
      } else if (v4) {
        ipDisplay = `<span style="color:#38bdf8; font-weight:600;">${v4}</span>`;
      } else if (v6) {
        ipDisplay = `<span style="color:#a78bfa; font-size:11px; word-break:break-all;">${v6}</span>`;
      } else {
        ipDisplay = '--';
      }
      if (elPublicIp) elPublicIp.innerHTML = ipDisplay;

      const engName = escapeHtml((latest.engine || targetEng).toUpperCase());
      const coloSafe = escapeHtml(latest.colo || '');
      if (elEngine) elEngine.innerHTML = `<span class="badge badge-ok">${engName}</span> ${coloSafe ? '<b>[' + coloSafe + ']</b>' : ''}`;

      if (elTimestamp && latest.ts) {
        const d = new Date(latest.ts);
        elTimestamp.innerText = d.getFullYear() + '.' + String(d.getMonth()+1).padStart(2,'0') + '.' + String(d.getDate()).padStart(2,'0') + '. ' + String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0') + ':' + String(d.getSeconds()).padStart(2,'0');
        if (latest.selected_server_id && latest.server_id && String(latest.selected_server_id) !== String(latest.server_id)) {
          const n = document.createElement('div');
          n.style.cssText = 'font-size: 11.5px; color: #fbbf24; margin-top: 2px; white-space: normal;';
          n.textContent = t('home_other_server', 'This result is from server #{used}, before the current choice (#{chosen}).')
            .replace('{used}', latest.server_id).replace('{chosen}', latest.selected_server_id);
          elTimestamp.appendChild(n);
        }
        if (latest.next_possible_ts) {
          const nx = new Date(latest.next_possible_ts);
          const n2 = document.createElement('div');
          n2.style.cssText = 'font-size: 11.5px; color: #94a3b8; margin-top: 2px; white-space: normal;';
          n2.textContent = t('home_next_ookla', 'Next Ookla test from {time}.').replace('{time}', String(nx.getHours()).padStart(2,'0') + ':' + String(nx.getMinutes()).padStart(2,'0'));
          elTimestamp.appendChild(n2);
        }
        if (latest.newer_failure && latest.newer_failure.ts) {
          const f = new Date(latest.newer_failure.ts);
          const hm = String(f.getHours()).padStart(2,'0') + ':' + String(f.getMinutes()).padStart(2,'0');
          const note = document.createElement('div');
          note.style.cssText = 'font-size: 11.5px; color: #fbbf24; margin-top: 2px; white-space: normal;';
          note.textContent = t('home_newer_failure', 'Newer attempt at {time} gave no result: {reason}').replace('{time}', hm).replace('{reason}', speedErrorText(latest.newer_failure.error));
          elTimestamp.appendChild(note);
        }
      }

      const downMbps = (latest.down_bps !== null && latest.down_bps !== undefined) ? (latest.down_bps / 1000000.0) : null;
      const upMbps = (latest.up_bps !== null && latest.up_bps !== undefined) ? (latest.up_bps / 1000000.0) : null;
      const latMs = (latest.ping_us || 0) / 1000.0;

      let downPct = (latest.down_pct_of_offered !== undefined && latest.down_pct_of_offered !== null) ? latest.down_pct_of_offered : ((contractDown > 0 && downMbps !== null) ? (downMbps / contractDown) * 100.0 : null);
      let upPct = (latest.up_pct_of_offered !== undefined && latest.up_pct_of_offered !== null) ? latest.up_pct_of_offered : ((contractUp > 0 && upMbps !== null) ? (upMbps / contractUp) * 100.0 : null);

      if (elDownload) {
        if (downMbps !== null) {
          let downBadge = '';
          if (downPct !== null && contractDown > 0) {
            const badgeClass = downPct >= 80 ? 'badge-ok' : (downPct >= 60 ? 'badge-warn' : 'badge-crit');
            downBadge = ` <span class="badge ${badgeClass}" style="margin-left: 8px; font-size: 13px; font-weight: 700;">${downPct.toFixed(1)}% ${t('of_offered', 'of offered')} ${contractDown} Mbps</span>`;
          }
          elDownload.innerHTML = downMbps.toFixed(2) + ' Mbps' + downBadge;
        } else {
          elDownload.innerHTML = `<span style="color:#94a3b8;">-- Mbps (${t('upload_only', 'Upload Only')})</span>`;
        }
      }

      if (elUpload) {
        if (upMbps !== null) {
          let upBadge = '';
          if (upPct !== null && contractUp > 0) {
            const badgeClass = upPct >= 80 ? 'badge-ok' : (upPct >= 60 ? 'badge-warn' : 'badge-crit');
            upBadge = ` <span class="badge ${badgeClass}" style="margin-left: 8px; font-size: 13px; font-weight: 700;">${upPct.toFixed(1)}% ${t('of_offered', 'of offered')} ${contractUp} Mbps</span>`;
          }
          elUpload.innerHTML = upMbps.toFixed(2) + ' Mbps' + upBadge;
        } else {
          elUpload.innerHTML = `<span style="color:#94a3b8;">-- Mbps</span>`;
        }
      }

      if (elLatency) elLatency.innerText = (latMs > 0 ? latMs.toFixed(2) : '--') + ' ms';
      if (elBufferbloat) elBufferbloat.innerText = latest.bufferbloat_grade ? `${latest.bufferbloat_grade} (+${latest.bufferbloat_delta_ms || 0} ms)` : (latest.jitter_us ? `Jitter: ${(latest.jitter_us/1000.0).toFixed(2)} ms` : '--');

      let srvNameSafe = escapeHtml(latest.server_name || latest.server_host || '--');
      let srvDisplay = srvNameSafe;
      if (latest.result_url && !isGenericResultUrl(latest.result_url)) {
        let safeUrl = sanitizeUrl(latest.result_url);
        if (safeUrl) {
          srvDisplay += ` — <a href="${safeUrl}" target="_blank" rel="noopener noreferrer" style="color:#38bdf8; text-decoration:none;">🔗 ${t('open_result_link', 'Open Result Link')}</a>`;
        }
      }
      if ((latest.engine || '').toLowerCase() === 'cloudflare' && srvDisplay === srvNameSafe) {
        srvDisplay += ` <span style="color:#94a3b8; font-size: 11.5px;">(${escapeHtml(t('cf_no_result_page', 'Cloudflare gives no page for a single result'))})</span>`;
      }
      if (elServerLink) elServerLink.innerHTML = srvDisplay;
      renderFastcomDetail((latest.engine || '').toLowerCase() === 'fastcom' ? latest.fastcom_detail : null);
    } else {
      renderFastcomDetail(null);
      const fallbackIp = escapeHtml((data.system_info && (data.system_info.public_ipv4 || data.system_info.wan_ip)) || data.public_ip || '--');
      if (elPublicIp) elPublicIp.innerText = fallbackIp;
      if (elEngine) elEngine.innerHTML = `<span class="badge badge-ok">${targetEng.toUpperCase()}</span>`;
      if (elTimestamp) elTimestamp.innerHTML = `<span style="color:#94a3b8;">-- (${t('no_test_recorded', 'No measurement recorded yet with this engine')})</span>`;
      if (elDownload) elDownload.innerHTML = `<span style="color:#94a3b8;">-- Mbps</span>`;
      if (elUpload) elUpload.innerHTML = `<span style="color:#94a3b8;">-- Mbps</span>`;
      if (elLatency) elLatency.innerHTML = `<span style="color:#94a3b8;">-- ms</span>`;
      if (elBufferbloat) elBufferbloat.innerHTML = `<span style="color:#94a3b8;">--</span>`;
      if (elServerLink) elServerLink.innerHTML = `<span style="color:#38bdf8; font-weight:600;">⚡ ${t('ready_to_benchmark', 'Ready to benchmark — Click "Run Speedtest Now"')}</span>`;
    }

    if (elScriptBox) {
      if (targetEng === 'cloudflare') {
        elScriptBox.textContent = `#!/bin/sh
# ==============================================================================
# NetworkMeasureBox - Realtime Cloudflare Edge Speedtest Execution
# Measurement Engine: Cloudflare Edge (speed.cloudflare.com)
# ==============================================================================

# Direct CDN edge transfer benchmark with HTTP/HTTPS payload:
curl -s -X GET "https://speed.cloudflare.com/__down?bytes=25000000" -o /dev/null
curl -s -X POST "https://speed.cloudflare.com/__up" --data-binary @chunk_10mb.bin -o /dev/null
`;
      } else if (targetEng === 'rtr') {
        elScriptBox.textContent = `#!/bin/sh
# ==============================================================================
# NetworkMeasureBox - Realtime RTR-NetTest Execution
# Measurement Engine: RTR-NetTest (netztest.at / Open-RMBT, BEREC Standard)
# ==============================================================================

# Open European standard WebSocket speed measurement against Vienna 100G cluster:
python3 -m nmb.speed.rtr --json
`;
      } else if (targetEng === 'iperf3') {
        const ipHost = (data && data.iperf_target_host) || 'speedtest.init7.net';
        const ipPort = (data && data.iperf_port) || 5203;
        elScriptBox.textContent = `#!/bin/sh
# ==============================================================================
# NetworkMeasureBox - Realtime iPerf3 Bandwidth & Jitter Probing
# Measurement Engine: iPerf3 (RFC 2544 / RFC 6349 TCP & UDP Probing)
# ==============================================================================

# Multi-stream bidirectional throughput probing with BBR congestion control:
iperf3 -c ${ipHost} -p ${ipPort} -J -b 1000M -P 4 -C bbr
`;
      } else if (targetEng === 'all') {
        elScriptBox.textContent = `#!/bin/sh
# ==============================================================================
# NetworkMeasureBox - Multi-Engine Sequential Suite Execution
# Sequence: 1. Ookla Speedtest -> 2. Cloudflare Edge -> 3. RTR-NetTest -> 4. iPerf3
# ==============================================================================

/usr/local/bin/speedtest --accept-license --accept-gdpr --format=json
curl -s "https://speed.cloudflare.com/__down?bytes=25000000" -o /dev/null
python3 -m nmb.speed.rtr --json
iperf3 -c speedtest.init7.net -p 5203 -J -b 1000M -C bbr
`;
      } else {
        const sid = (data && data.scheduled_server && data.scheduled_server.id) ? data.scheduled_server.id : null;
        elScriptBox.textContent = `#!/bin/sh
# ==============================================================================
# NetworkMeasureBox - Realtime Ookla Speedtest Execution
# Target Server: ${sid ? '#' + sid : 'automatic (nearest)'}
# ==============================================================================

/usr/local/bin/speedtest --accept-license --accept-gdpr --format=json${sid ? ' --server-id ' + sid : ''}
`;
      }
    }
  }

  function markViewPill(eng) {
    document.querySelectorAll('.engine-pill').forEach(el => { el.classList.remove('active'); el.setAttribute('aria-pressed', 'false'); });
    const pill = document.getElementById('pill-engine-' + eng);
    if (pill) { pill.classList.add('active'); pill.setAttribute('aria-pressed', 'true'); }
  }

  // Home page: show the latest result of one engine, or the newest of any ("all"). Changes no setting.
  function viewEngine(eng) {
    window.homeViewEngine = eng;
    try { localStorage.setItem('nmb_home_view', eng); } catch (e) {}
    markViewPill(eng);
    renderHomeEngineCard(eng);
  }

  async function selectEngine(eng, skipSave) {
    if (!eng) return;
    selectedEngine = eng.toLowerCase();

    // The home page buttons only choose which result is shown (viewEngine); this follows the setting.

    // 1b. Update active engine badge on Dashboard
    const activeBadge = document.getElementById('home-active-engine-badge');
    if (activeBadge) {
      const labels = { ookla: 'Ookla', cloudflare: 'Cloudflare', fastcom: 'Fast.com', rtr: 'RTR-NetTest', iperf3: 'iPerf3',
                       all: t('home_view_mixed_short', 'Mixed') };
      activeBadge.innerText = labels[selectedEngine] || selectedEngine;
      if (selectedEngine === 'ookla') {
        activeBadge.style.background = 'rgba(2,132,199,0.25)';
        activeBadge.style.color = '#38bdf8';
        activeBadge.style.borderColor = '#0284c7';
      } else if (selectedEngine === 'cloudflare') {
        activeBadge.style.background = 'rgba(245,158,11,0.25)';
        activeBadge.style.color = '#fbbf24';
        activeBadge.style.borderColor = '#f59e0b';
      } else if (selectedEngine === 'fastcom') {
        activeBadge.style.background = 'rgba(229,9,20,0.25)';
        activeBadge.style.color = '#f87171';
        activeBadge.style.borderColor = '#e50914';
      } else if (selectedEngine === 'rtr') {
        activeBadge.style.background = 'rgba(16,185,129,0.25)';
        activeBadge.style.color = '#34d399';
        activeBadge.style.borderColor = '#10b981';
      } else if (selectedEngine === 'iperf3') {
        activeBadge.style.background = 'rgba(168,85,247,0.25)';
        activeBadge.style.color = '#c084fc';
        activeBadge.style.borderColor = '#a855f7';
      } else {
        activeBadge.style.background = 'rgba(234,179,8,0.25)';
        activeBadge.style.color = '#fde047';
        activeBadge.style.borderColor = '#eab308';
      }
    }

    // 2. Instantly update engine description
    const descEl = document.getElementById('engine-desc-text');
    if (descEl) {
      if (selectedEngine === 'ookla') {
        descEl.innerHTML = t('engine_desc_ookla', '⚡ <b>Ookla Speedtest:</b> Global server fleet, selectable target server, detailed download/upload and bufferbloat.');
      } else if (selectedEngine === 'cloudflare') {
        descEl.innerHTML = t('engine_desc_cloudflare', '☁️ <b>Cloudflare Edge (cloudflare-speed-cli):</b> Direct CDN edge speed measurement (speed.cloudflare.com), airport PoP code (e.g. BUD), ASN and loaded latency.');
      } else if (selectedEngine === 'fastcom') {
        descEl.innerHTML = t('engine_desc_fastcom', '🎬 <b>Fast.com (Netflix):</b> Netflix Open Connect servers near you, several at once: download, upload, unloaded and loaded latency, ISP and per-server detail.');
      } else if (selectedEngine === 'rtr') {
        descEl.innerHTML = t('engine_desc_rtr', '🇦🇹 <b>RTR-NetTest (netztest.at / Open-RMBT):</b> Open European standard (BEREC) measurement on Vienna 100G cluster with shareable report link.');
      } else if (selectedEngine === 'iperf3') {
        descEl.innerHTML = t('engine_desc_iperf3', '⚡ <b>iPerf3 Bandwidth & Jitter:</b> Precision bidirectional TCP/UDP throughput and jitter/loss probing against configured server.');
      } else if (selectedEngine === 'all') {
        descEl.innerHTML = t('engine_desc_all', '🏆 <b>Combined (All Engines):</b> Sequentially executes all measurement engines, providing a side-by-side comparison.');
      }
    }

    // 3. Update server / target input row visibility
    updateServerSelectVisibility(selectedEngine);

    // 4. The results card follows the setting until a view button was pressed
    if (!window.homeViewEngine) { markViewPill(selectedEngine); renderHomeEngineCard(selectedEngine); }

    // 5. Synchronize Schedule & Settings dropdowns
    if (document.getElementById('sched-engine-select')) {
      document.getElementById('sched-engine-select').value = selectedEngine;
    }
    if (document.getElementById('cfg-sched-engine')) {
      document.getElementById('cfg-sched-engine').value = selectedEngine;
    }
    window.currentAutomatedEngine = selectedEngine;

    // 6. Save in background immediately to backend config & database
    if (!skipSave) {
      showToast(t('engine_selected', 'Selected measurement engine: ') + selectedEngine.toUpperCase() + t('engine_saved_active', ' (Active & Saved)'));
      try {
        await fetch('/api/speedtest/engine', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ engine: selectedEngine })
        });
      } catch (err) {
        console.warn('Background engine save error:', err);
      }
    }
  }

  async function refreshStatus() {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) return;
      const data = await res.json();
      window.lastStatusData = data;
      window.latestPerEngine = data.latest_per_engine || {};
      window.allRecentSpeedtests = data.speed_tests || [];

      // Header metadata
      if (data.system_info) {
        document.getElementById('hdr-box-id').innerText = data.system_info.box_id || 'nmb-01';
        document.getElementById('hdr-fw-ver').innerText = data.system_info.firmware_version || '2.5.0';
        document.getElementById('hdr-mode').innerText = data.system_info.mode || 'standalone';
        const wanV4 = escapeHtml(data.system_info.public_ipv4 || data.system_info.wan_ip || '');
        const wanV6 = escapeHtml(data.system_info.public_ipv6 || '');
        if (wanV4 && wanV6) {
          document.getElementById('hdr-wan-ip').innerHTML = `<span style="color:#38bdf8;">${wanV4}</span> <span style="font-size: 11px; color:#a78bfa;" title="${wanV6}">[v6]</span>`;
        } else {
          document.getElementById('hdr-wan-ip').innerText = wanV4 || wanV6 || '--';
        }
        document.getElementById('hdr-wan-iface').innerText = data.system_info.wan_interface || 'eth0';
        document.getElementById('hdr-uptime').innerText = data.system_info.uptime || '--';
      }

      // Terminal Box ID sync
      const termBoxId = document.getElementById('term-box-id');
      if (termBoxId && data.box_id) termBoxId.innerText = data.box_id;

      // Drive Configuration status sync
      if (data.drive_config) {
        const drivePathEl = document.getElementById('drive-cfg-path');
        const driveBadgeEl = document.getElementById('drive-cfg-status-badge');
        if (drivePathEl && data.drive_config.path) drivePathEl.innerText = data.drive_config.path;
        if (driveBadgeEl) {
          if (data.drive_config.exists) {
            driveBadgeEl.innerText = t('drive_status_synced', '✅ Active and Synchronized');
            driveBadgeEl.style.color = '#34d399';
            driveBadgeEl.style.borderColor = '#10b981';
          } else if (data.drive_config.is_writable) {
            driveBadgeEl.innerText = t('drive_status_ready', '⚡ Ready for Synchronization');
            driveBadgeEl.style.color = '#38bdf8';
            driveBadgeEl.style.borderColor = '#0284c7';
          } else {
            driveBadgeEl.innerText = t('drive_status_readonly', '⚠️ Read-Only / No Drive Detected');
            driveBadgeEl.style.color = '#f59e0b';
            driveBadgeEl.style.borderColor = '#d97706';
          }
        }
      }

      if (data.auth_enabled) {
        const badge = document.getElementById('hdr-auth-badge');
        const userSpan = document.getElementById('hdr-auth-user');
        if (badge && userSpan) {
          userSpan.textContent = data.admin_username || 'admin';
          badge.style.display = 'inline-flex';
        }
      }

            // Memory Telemetry & Profile
      if (data.memory) {
        const memTot = data.memory.ram_total_mb || 0;
        const memAvail = data.memory.ram_available_mb || 0;
        const memUsed = Math.max(0, memTot - memAvail);
        const memPct = memTot > 0 ? Math.min(100, Math.max(0, Math.round((memUsed / memTot) * 100))) : 0;
        const isLow = !!data.memory.is_low_memory;
        const confProf = data.memory.configured_profile || 'auto';
        const effProf = data.memory.effective_profile || (isLow ? 'low' : 'standard');

        const hdrRam = document.getElementById('hdr-ram-val');
        if (hdrRam) {
          hdrRam.innerText = `${memAvail} / ${memTot} MB`;
          hdrRam.title = `Total: ${memTot} MB, Avail: ${memAvail} MB (${100 - memPct}% free)`;
        }

        const elTot = document.getElementById('mem-stat-total');
        if (elTot) elTot.innerText = `${memTot} MB`;

        const elAvail = document.getElementById('mem-stat-avail');
        if (elAvail) elAvail.innerText = `${memAvail} MB`;

        const elAvailPct = document.getElementById('mem-stat-avail-pct');
        if (elAvailPct) elAvailPct.innerText = `${100 - memPct}% Free`;

        const elTarget = document.getElementById('mem-stat-target');
        if (elTarget) elTarget.innerText = isLow ? '≤ 768MB (Router Target)' : 'Standard / High RAM';

        const elProf = document.getElementById('mem-stat-active-prof');
        if (elProf) elProf.innerText = effProf.toUpperCase();

        const elSqlite = document.getElementById('mem-stat-sqlite-cache');
        if (elSqlite) {
          elSqlite.innerText = effProf === 'low' ? 'SQLite: 4MB Cache (File Temp)' : (effProf === 'performance' ? 'SQLite: 64MB Cache' : 'SQLite: 16MB Cache');
        }

        const elVm = document.getElementById('mem-stat-vm-buffers');
        if (elVm) {
          elVm.innerText = effProf === 'low' ? 'Bounded 4MB (min_free: 8M)' : (effProf === 'performance' ? 'High 64MB (min_free: 64M)' : 'Standard 16MB');
        }

        const elPill = document.getElementById('mem-profile-pill');
        if (elPill) elPill.innerText = `Profile: ${confProf.toUpperCase()} (${effProf.toUpperCase()})`;

        const elLowPill = document.getElementById('mem-low-pill');
        if (elLowPill) elLowPill.style.display = isLow ? 'inline-flex' : 'none';

        const elUsedLbl = document.getElementById('mem-used-pct-label');
        if (elUsedLbl) elUsedLbl.innerText = `${memPct}% (${memUsed} MB used)`;

        const elBar = document.getElementById('mem-used-bar');
        if (elBar) {
          elBar.style.width = `${memPct}%`;
          if (memPct > 85) elBar.style.background = '#ef4444';
          else if (memPct > 70) elBar.style.background = '#f59e0b';
          else elBar.style.background = 'linear-gradient(90deg, #10b981, #38bdf8)';
        }

        const selProf = document.getElementById('cfg-memory-profile');
        if (selProf && document.activeElement !== selProf && !window.memoryProfileDirty) {
          selProf.value = confProf;
        }
      }

      // Measuring banner tracking
      const isMeas = data.is_measuring || false;
      document.getElementById('measuring-banner').style.display = isMeas ? 'flex' : 'none';
      document.getElementById('btn-home-measure').disabled = isMeas;

      // Default password warning banner tracking
      const isDefPass = data.default_password_active || false;
      const defPassEl = document.getElementById('default-pass-banner');
      if (defPassEl) defPassEl.style.display = isDefPass ? 'flex' : 'none';

      // Render Dashboard speedtest card based on selected engine
      renderHomeEngineCard(window.homeViewEngine || selectedEngine, data);

      // Script preview box (in Schedule tab)
      if (data.latest_script && document.getElementById('script-preview-box')) {
        document.getElementById('script-preview-box').textContent = data.latest_script;
      }

      // Contract information (Tab 9 & header - safe null checks)
      if (data.contract) {
        const ispName = data.contract.isp_name || (data.system_info && data.system_info.wan_ip ? 'Internet (' + data.system_info.wan_ip + ')' : t('not_specified', 'Not specified'));
        const circuit = data.contract.circuit_id ? ' / ' + data.contract.circuit_id : '';
        const elIsp = document.getElementById('contract-isp-display');
        if (elIsp) elIsp.innerText = ispName + circuit;
        const elTech = document.getElementById('contract-tech-display');
        if (elTech) elTech.innerText = data.contract.connection_type || 'Optical Fiber (FTTH / GPON)';
        const elDownOff = document.getElementById('contract-down-offered');
        if (elDownOff) elDownOff.innerText = data.contract.contract_down_mbps ? parseFloat(data.contract.contract_down_mbps).toFixed(2) + ' Mbps' : '--';
        const elDownGuar = document.getElementById('contract-down-guar');
        if (elDownGuar) elDownGuar.innerText = data.contract.guaranteed_down_mbps ? parseFloat(data.contract.guaranteed_down_mbps).toFixed(2) + ' Mbps' : '--';
        const elUpOff = document.getElementById('contract-up-offered');
        if (elUpOff) elUpOff.innerText = data.contract.contract_up_mbps ? parseFloat(data.contract.contract_up_mbps).toFixed(2) + ' Mbps' : '--';
        const elUpGuar = document.getElementById('contract-up-guar');
        if (elUpGuar) elUpGuar.innerText = data.contract.guaranteed_up_mbps ? parseFloat(data.contract.guaranteed_up_mbps).toFixed(2) + ' Mbps' : '--';
      }

      // Populate Live SLA & Contracted Speed Audit Card in Subtab 6
      const contractDownVal = (data.contract && data.contract.contract_down_mbps) ? parseFloat(data.contract.contract_down_mbps) : 0;
      const contractUpVal = (data.contract && data.contract.contract_up_mbps) ? parseFloat(data.contract.contract_up_mbps) : 0;
      if (document.getElementById('sla-last-down-pct')) {
        if (data.latest_speedtest && contractDownVal > 0) {
          const lDownMbps = (data.latest_speedtest.down_bps || 0) / 1000000.0;
          const lDownPct = (data.latest_speedtest.down_pct_of_offered !== undefined && data.latest_speedtest.down_pct_of_offered !== null) ? data.latest_speedtest.down_pct_of_offered : ((lDownMbps / contractDownVal) * 100.0);
          document.getElementById('sla-last-down-pct').innerText = lDownPct.toFixed(1) + ' %';
          document.getElementById('sla-last-down-pct').style.color = lDownPct >= 80 ? '#34d399' : (lDownPct >= 60 ? '#fbbf24' : '#f87171');
          document.getElementById('sla-last-down-detail').innerText = `${lDownMbps.toFixed(2)} Mbps ${t('of_offered', 'of offered')} ${contractDownVal} Mbps`;
        }
        if (data.latest_speedtest && contractUpVal > 0) {
          const lUpMbps = (data.latest_speedtest.up_bps || 0) / 1000000.0;
          const lUpPct = (data.latest_speedtest.up_pct_of_offered !== undefined && data.latest_speedtest.up_pct_of_offered !== null) ? data.latest_speedtest.up_pct_of_offered : ((lUpMbps / contractUpVal) * 100.0);
          document.getElementById('sla-last-up-pct').innerText = lUpPct.toFixed(1) + ' %';
          document.getElementById('sla-last-up-pct').style.color = lUpPct >= 80 ? '#34d399' : (lUpPct >= 60 ? '#fbbf24' : '#f87171');
          document.getElementById('sla-last-up-detail').innerText = `${lUpMbps.toFixed(2)} Mbps ${t('of_offered', 'of offered')} ${contractUpVal} Mbps`;
        }
        if (data.speed && contractDownVal > 0) {
          const avgD = data.speed.avg_down_mbps || 0;
          const avgDPct = (data.speed.avg_down_pct_of_offered !== undefined && data.speed.avg_down_pct_of_offered !== null) ? data.speed.avg_down_pct_of_offered : ((avgD / contractDownVal) * 100.0);
          document.getElementById('sla-avg-down-pct').innerText = avgDPct.toFixed(1) + ' %';
          document.getElementById('sla-avg-down-pct').style.color = avgDPct >= 80 ? '#34d399' : (avgDPct >= 60 ? '#fbbf24' : '#f87171');
          document.getElementById('sla-avg-down-detail').innerText = `${t('speed_avg_24h', '24h Rolling Average:')} ${avgD.toFixed(2)} Mbps (${contractDownVal} Mbps ${t('of_offered', 'offered')})`;
        }
        if (data.speed && contractUpVal > 0) {
          const avgU = data.speed.avg_up_mbps || 0;
          const avgUPct = (data.speed.avg_up_pct_of_offered !== undefined && data.speed.avg_up_pct_of_offered !== null) ? data.speed.avg_up_pct_of_offered : ((avgU / contractUpVal) * 100.0);
          document.getElementById('sla-avg-up-pct').innerText = avgUPct.toFixed(1) + ' %';
          document.getElementById('sla-avg-up-pct').style.color = avgUPct >= 80 ? '#34d399' : (avgUPct >= 60 ? '#fbbf24' : '#f87171');
          document.getElementById('sla-avg-up-detail').innerText = `${t('speed_avg_24h', '24h Rolling Average:')} ${avgU.toFixed(2)} Mbps (${contractUpVal} Mbps ${t('of_offered', 'offered')})`;
        }
      }

      // Scheduled server & automated mode synchronization
      const sched = data.scheduled_server;
      const bannerEl = document.getElementById('script-server-banner');
      const resetBtn = document.getElementById('btn-reset-default-server');
      if (bannerEl) {
        if (sched && sched.id) {
          bannerEl.innerHTML = `<span style="color:#38bdf8;">#${escapeHtml(sched.id)}</span> — <b>${escapeHtml(sched.name || t('custom_server', 'Custom Server'))}</b> <code style="color:#94a3b8; font-size:12px;">(${escapeHtml(sched.host || '')})</code>`;
          if (resetBtn) resetBtn.style.display = 'inline-block';
        } else {
          bannerEl.innerText = t('target_server_auto', 'Automatic closest benchmark server (Auto)');
          if (resetBtn) resetBtn.style.display = 'none';
        }
      }

      if (data.contract && data.contract.contract_down_mbps) {
        globalContractDownMbps = parseFloat(data.contract.contract_down_mbps) || 1000.0;
        updateGateCalculatedBadge();
      }

      // Automated schedule mode badge on Dashboard
      const schedMode = data.schedule_mode || 'scheduled';
      const modeBadge = document.getElementById('home-mode-badge');
      if (modeBadge) {
        if (schedMode === 'manual') {
          modeBadge.innerText = t('mode_manual', '🔴 Manual Mode (Timer Disabled)');
          modeBadge.style.background = 'rgba(239, 68, 68, 0.15)';
          modeBadge.style.color = '#f87171';
          modeBadge.style.borderColor = '#ef4444';
        } else {
          const cronDesc = data.schedule_cron_desc || (data.schedule_cron ? data.schedule_cron : 'Scheduled');
          const gatePct = (data.idle_threshold_percent !== undefined) ? data.idle_threshold_percent : 2.0;
          const capMbps = (data.contract && data.contract.contract_down_mbps) ? data.contract.contract_down_mbps : 1000.0;
          const limitMbps = (data.traffic_stop_enabled ? Math.max(0.2, Math.min(0.5, (capMbps * gatePct) / 100.0)) : (capMbps * gatePct) / 100.0).toFixed(1);
          globalTrafficStop = !!data.traffic_stop_enabled;
          const stopToggle = document.getElementById('traffic-stop-toggle');
          if (stopToggle) stopToggle.checked = globalTrafficStop;
          const gateInfo = data.scheduler_status && data.scheduler_status.traffic_gate;
          const ooklaWarn = data.scheduler_status ? data.scheduler_status.ookla_warning : null;
          renderOoklaWarning(ooklaWarn);
          const visibilityWarning = gateInfo && gateInfo.visibility === 'none' ? ` &nbsp;|&nbsp; ⚠️ ${escapeHtml(t('gate_no_visibility', 'No speed tests: other devices\' traffic is not visible to the box'))}` : '';
          // The full Ookla warning sits under the schedule settings; here only a short note, full text on hover.
          let ooklaShort = '';
          if (ooklaWarn) {
            ooklaShort = ooklaWarn.code === 'ookla_paused'
              ? t('ookla_badge_paused', 'Ookla paused for {min} min').replace('{min}', ooklaWarn.paused_min)
              : t('ookla_badge_hourly', 'Ookla at most every {safe} min').replace('{safe}', ooklaWarn.safe_interval_min);
          }
          const ooklaBadge = ooklaWarn ? ` &nbsp;|&nbsp; <span title="${escapeHtml(ooklaWarningText(ooklaWarn))}">⚠️ ${escapeHtml(ooklaShort)}</span>` : '';
          const label = (k, fb) => String(t(k, fb)).replace(/^[^\p{L}]+/u, '').replace(/\s*:\s*$/, '');
          modeBadge.style.whiteSpace = 'normal';
          modeBadge.style.maxWidth = '100%';
          modeBadge.innerHTML = `🟢 <b>${escapeHtml(label('mode_scheduled', 'Automated Schedule'))}:</b> ${escapeHtml(cronDesc)} &nbsp;|&nbsp; 🛡️ <b>${escapeHtml(label('accuracy_gate', 'Accuracy Gate'))}:</b> &lt; ${gatePct.toFixed(1)}% (max ${limitMbps} Mbps)${visibilityWarning}${ooklaBadge}`;
          modeBadge.style.background = 'rgba(16, 185, 129, 0.15)';
          modeBadge.style.color = '#34d399';
          modeBadge.style.borderColor = '#10b981';
        }
      }

      // Sync Tab 10 schedule controls ONLY when user has no unsaved changes and is not actively focusing any schedule input!
      if (!schedFormDirty && !isScheduleInputActive()) {
        const radMan = document.getElementById('radio-mode-manual');
        const radSched = document.getElementById('radio-mode-scheduled');
        if (radMan && radSched) {
          if (schedMode === 'manual') {
            radMan.checked = true;
            onSchedModeRadioChange('manual');
          } else {
            radSched.checked = true;
            onSchedModeRadioChange('scheduled');
          }
        }

        if (data.schedule_cron && document.getElementById('sched-interval-select')) {
          const selectEl = document.getElementById('sched-interval-select');
          const customWrap = document.getElementById('sched-custom-cron-wrap');
          const customInp = document.getElementById('sched-custom-cron-input');
          let matched = false;
          for (let opt of selectEl.options) {
            if (opt.value === data.schedule_cron) {
              selectEl.value = data.schedule_cron;
              matched = true;
              if (customWrap) customWrap.style.display = 'none';
              break;
            }
          }
          if (!matched) {
            selectEl.value = 'custom';
            if (customWrap) customWrap.style.display = 'block';
            if (customInp) customInp.value = data.schedule_cron;
          }
        }
        if (data.iperf_target_host !== undefined) showIperfAutoCurrent(data.iperf_target_host, data.iperf_port, data.iperf_auto);
        if (data.engine_intervals && !schedFormDirty && !isScheduleInputActive()) {
          for (const k of ['ookla', 'rtr', 'cloudflare', 'fastcom', 'iperf3']) {
            const el = document.getElementById('sched-int-' + k);
            if (el && document.activeElement !== el && data.engine_intervals[k] !== undefined) el.value = data.engine_intervals[k];
          }
        }
        if (Array.isArray(data.mixed_engines) && !schedFormDirty && !isScheduleInputActive()) {
          document.querySelectorAll('.sched-mix').forEach(cb => { cb.checked = data.mixed_engines.includes(cb.dataset.engine); });
        }
        if (data.automated_engine) {
          window.currentAutomatedEngine = data.automated_engine;
          if (document.getElementById('sched-engine-select')) {
            document.getElementById('sched-engine-select').value = data.automated_engine;
          }
          if (!selectedEngine) {
            selectEngine(data.automated_engine, true);
          }
        }

        const dataLimitInput = document.getElementById('daily-data-limit');
        if (dataLimitInput && data.daily_data_limit_mb !== undefined && document.activeElement !== dataLimitInput) {
          dataLimitInput.value = data.daily_data_limit_mb;
        }
        if (typeof loadDataCap === 'function') loadDataCap();
        if (data.idle_threshold_mode && document.getElementById('sched-gate-mode')) {
          document.getElementById('sched-gate-mode').value = data.idle_threshold_mode;
          onSchedGateModeChange(data.idle_threshold_mode);
        }
        if (data.idle_threshold_percent !== undefined && document.getElementById('sched-gate-percent')) {
          document.getElementById('sched-gate-percent').value = data.idle_threshold_percent;
        }
        if (data.idle_threshold_kbps !== undefined && document.getElementById('sched-gate-kbps')) {
          document.getElementById('sched-gate-kbps').value = data.idle_threshold_kbps;
        }
        updateGateCalculatedBadge();

        const schedInput = document.getElementById('sched-server-id-input');
        if (schedInput) {
          if (sched && sched.id) {
            schedInput.value = sched.id;
          } else {
            schedInput.value = '';
          }
        }

        const schedIperfHostEl = document.getElementById('sched-iperf-host');
        const schedIperfPortEl = document.getElementById('sched-iperf-port');
        if (schedIperfHostEl && document.activeElement !== schedIperfHostEl && !schedFormDirty) {
          schedIperfHostEl.value = data.iperf_target_host || 'speedtest.init7.net';
        }
        if (schedIperfPortEl && document.activeElement !== schedIperfPortEl && !schedFormDirty) {
          schedIperfPortEl.value = data.iperf_port || 5203;
        }
        const schedIperfInfo = document.getElementById('sched-iperf-resolved-info');
        if (schedIperfInfo && data.iperf_target_host) {
          schedIperfInfo.innerHTML = `🎯 <b>${escapeHtml(data.iperf_target_host)}</b> <code style="color:#94a3b8;">(:${data.iperf_port || 5201})</code>`;
        }
      }

      // Sync home quick interval select
      const homeIntSelect = document.getElementById('home-interval-select');
      if (homeIntSelect && document.activeElement !== homeIntSelect) {
        if (schedMode === 'manual') {
          homeIntSelect.value = 'manual';
        } else if (data.schedule_cron) {
          for (let opt of homeIntSelect.options) {
            if (opt.value === data.schedule_cron) {
              homeIntSelect.value = data.schedule_cron;
              break;
            }
          }
        }
      }

      // Sync target server dropdown & inputs
      const homeSelect = document.getElementById('home-target-server-select');
      const schedResolved = document.getElementById('sched-server-resolved-name');
      const schedInputEl = document.getElementById('sched-server-id-input');

      if (sched && sched.id) {
        if (schedInputEl && document.activeElement !== schedInputEl && !schedFormDirty && !isScheduleInputActive()) schedInputEl.value = sched.id;
        if (schedResolved) {
          schedResolved.innerHTML = `🎯 <b>${escapeHtml(sched.name || t('server_prefix', 'Server') + ' #' + sched.id)}</b> <code style="color:#94a3b8;">(${escapeHtml(sched.host || '')})</code>`;
        }
        if (homeSelect && document.activeElement !== homeSelect) {
          let hasOption = Array.from(homeSelect.options).some(o => o.value == sched.id);
          if (hasOption) {
            homeSelect.value = sched.id;
            const customWrap = document.getElementById('home-custom-server-wrap');
            if (customWrap) customWrap.style.display = 'none';
          } else {
            homeSelect.value = 'custom';
            const customWrap = document.getElementById('home-custom-server-wrap');
            if (customWrap) customWrap.style.display = 'flex';
            const customIn = document.getElementById('home-custom-server-id');
            if (customIn && document.activeElement !== customIn) customIn.value = sched.id;
          }
        }
      } else {
        if (schedResolved) schedResolved.innerText = '🌐 ' + t('target_server_auto', 'Automatic closest benchmark server (Auto)');
        if (homeSelect && document.activeElement !== homeSelect) {
          homeSelect.value = 'auto';
          const customWrap = document.getElementById('home-custom-server-wrap');
          if (customWrap) customWrap.style.display = 'none';
        }
      }

      // Latency chart (Tab 2)
      if (data.chart_svg) {
        document.getElementById('chart-latency').innerHTML = data.chart_svg;
      }

      // Probe stats table (Tab 2)
      if (data.target_stats && data.target_stats.length > 0) {
        let pHtml = '';
        data.target_stats.forEach(t => {
          pHtml += `<tr>
            <td><b>${escapeHtml(t.label || t.addr)}</b> <code style="font-size:11px; color:#94a3b8;">(${escapeHtml(t.addr)})</code></td>
            <td>${t.sent.toLocaleString()}</td>
            <td>${t.lost.toLocaleString()}</td>
            <td><b>${(t.loss_pct || 0).toFixed(2)}%</b></td>
            <td>${(t.avg_rtt_ms || 0).toFixed(2)} ms</td>
            <td>${(t.p95_rtt_ms || 0).toFixed(2)} ms</td>
          </tr>`;
        });
        document.getElementById('probe-table-body').innerHTML = pHtml;
      }

      // Speedtest table (Tab 3)
      if (data.speed_tests && data.speed_tests.length > 0) {
        let sHtml = '';
        let totDown = 0, totUp = 0, totLat = 0, countOk = 0;
        const cDown = (data.contract && data.contract.contract_down_mbps) ? parseFloat(data.contract.contract_down_mbps) : 0;
        const cUp = (data.contract && data.contract.contract_up_mbps) ? parseFloat(data.contract.contract_up_mbps) : 0;

        function renderRowPctBadge(pct) {
          if (pct === null || pct === undefined || isNaN(pct) || pct <= 0) return '';
          let color = '#34d399';
          let bg = 'rgba(16, 185, 129, 0.15)';
          let border = 'rgba(16, 185, 129, 0.3)';
          if (pct < 60) {
            color = '#f87171';
            bg = 'rgba(239, 68, 68, 0.15)';
            border = 'rgba(239, 68, 68, 0.3)';
          } else if (pct < 80) {
            color = '#fbbf24';
            bg = 'rgba(245, 158, 11, 0.15)';
            border = 'rgba(245, 158, 11, 0.3)';
          }
          return `<span class="badge" style="background:${bg}; color:${color}; border:1px solid ${border}; margin-left:6px; font-size:11px; font-weight:700;">${pct.toFixed(1)}%</span>`;
        }

        // Only measurements are listed; skipped and failed runs are counted in one line
        // (the reports and the CSV export still contain them).
        const skippedCount = data.speed_tests.filter(st => st.status !== 'ok').length;
        data.speed_tests.filter(st => st.status === 'ok').forEach(st => {
          const d = new Date(st.ts);
          const dtStr = d.getFullYear() + '.' + String(d.getMonth()+1).padStart(2,'0') + '.' + String(d.getDate()).padStart(2,'0') + ' ' + String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
          const dMbps = (st.down_bps || 0) / 1000000.0;
          const uMbps = (st.up_bps || 0) / 1000000.0;
          const lat = (st.ping_us || 0) / 1000.0;
          if (st.status === 'ok') {
            totDown += dMbps; totUp += uMbps; totLat += lat; countOk++;
          }
          const bb = st.bufferbloat_grade ? `<span class="badge badge-ok">${escapeHtml(st.bufferbloat_grade)} (+${st.bufferbloat_delta_ms || 0}ms)</span>` : '--';
          
          let engineBadge = `<span class="badge">${escapeHtml(String(st.engine || '?').toUpperCase())}</span>`;
          if (st.engine === 'ookla') {
            engineBadge = '<span class="badge" style="background:rgba(2,132,199,0.2);color:#38bdf8;border:1px solid #0284c7;">OOKLA</span>';
          } else if (st.engine === 'iperf3') {
            engineBadge = '<span class="badge" style="background:rgba(168,85,247,0.2);color:#c084fc;border:1px solid #a855f7;">IPERF3</span>';
          } else if (st.engine === 'cloudflare') {
            engineBadge = `<span class="badge" style="background:rgba(245,158,11,0.2);color:#fbbf24;border:1px solid #f59e0b;">CLOUDFLARE ${st.colo ? '[' + escapeHtml(st.colo) + ']' : ''}</span>`;
          } else if (st.engine === 'fastcom') {
            engineBadge = `<span class="badge" style="background:rgba(229,9,20,0.2);color:#f87171;border:1px solid #e50914;">FAST.COM ${st.colo ? '[' + escapeHtml(st.colo) + ']' : ''}</span>`;
          } else if (st.engine === 'rtr' || st.engine === 'rtr-nettest') {
            engineBadge = '<span class="badge" style="background:rgba(16,185,129,0.2);color:#34d399;border:1px solid #10b981;">RTR-NETTEST</span>';
          }

          let safeServerName = escapeHtml(st.server_name || st.server_host || '--');
          let link = safeServerName;
          if (st.result_url && !isGenericResultUrl(st.result_url)) {
            let safeUrl = sanitizeUrl(st.result_url);
            if (safeUrl) {
              link = `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer" style="color:#38bdf8; text-decoration:none; font-weight:600;">🔗 ${safeServerName || t('open_result_link', 'View Official Result')}</a>`;
            }
          }

          const dPct = (st.down_pct_of_offered !== undefined && st.down_pct_of_offered !== null) ? st.down_pct_of_offered : (cDown > 0 ? (dMbps / cDown) * 100.0 : null);
          const uPct = (st.up_pct_of_offered !== undefined && st.up_pct_of_offered !== null) ? st.up_pct_of_offered : (cUp > 0 ? (uMbps / cUp) * 100.0 : null);

          let clientIpCell = '';
          const stV4 = escapeHtml(st.client_ip);
          const stV6 = escapeHtml(st.client_ipv6);
          const ispName = escapeHtml(st.isp_name || (data.isp && data.isp.name) || 'ISP');
          const ispBadge = `<span class="badge" style="background:rgba(56,189,248,0.12); color:#38bdf8; border:1px solid rgba(56,189,248,0.3); font-size: 11px; margin-top:2px; display:inline-block; max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${ispName}">🏢 ${ispName}</span>`;

          if (stV4 && stV6) {
            clientIpCell = `<div style="font-size:11px; line-height:1.3;"><span style="color:#38bdf8;" title="IPv4">${stV4}</span><br><span style="color:#a78bfa; font-size: 11px;" title="IPv6">${stV6}</span><br>${ispBadge}</div>`;
          } else if (stV4) {
            clientIpCell = `<div style="font-size:11px; line-height:1.3;"><code style="color:#38bdf8;">${stV4}</code><br>${ispBadge}</div>`;
          } else if (stV6) {
            clientIpCell = `<div style="font-size:11px; line-height:1.3;"><code style="color:#a78bfa; font-size: 11px;">${stV6}</code><br>${ispBadge}</div>`;
          } else {
            clientIpCell = `<div><code>--</code><br>${ispBadge}</div>`;
          }

          sHtml += `<tr>
            <td style="white-space: nowrap;">${dtStr}</td>
            <td style="white-space: nowrap;">${engineBadge}</td>
            ${st.status === 'skipped_busy'
              ? `<td colspan="2" style="white-space: nowrap;" title="${escapeHtml(st.error || '')}">— ${escapeHtml(t('speed_skipped', 'Skipped, no measurement'))}</td>`
              : st.status !== 'ok'
              ? `<td colspan="2" style="color:#f87171; white-space: normal; max-width: 320px;" title="${escapeHtml(st.error || '')}">✖ ${escapeHtml(t('speed_failed', 'No result'))}: ${escapeHtml(speedErrorText(st.error))}</td>`
              : `<td style="white-space: nowrap;"><b>${dMbps.toFixed(2)} Mbps</b> ${renderRowPctBadge(dPct)}</td>
            <td style="white-space: nowrap;"><b>${uMbps.toFixed(2)} Mbps</b> ${renderRowPctBadge(uPct)}</td>`}
            <td style="white-space: nowrap;">${st.status === 'ok' ? lat.toFixed(2) + ' ms' : '--'}</td>
            <td style="white-space: nowrap;">${bb}</td>
            <td style="white-space: nowrap;">${clientIpCell}</td>
            <td style="white-space: nowrap;">${link}</td>
          </tr>`;
        });
        if (skippedCount > 0) {
          sHtml += `<tr><td colspan="8" style="color: var(--text-muted); font-size: 12px;">${escapeHtml(t('speed_skipped_hidden', '{n} runs without a result (skipped, failed or Ookla paused) are not listed.').replace('{n}', skippedCount))}</td></tr>`;
        }
        document.getElementById('speed-table-body').innerHTML = sHtml;

        cachedSpeedTests = data.speed_tests || [];
        cachedSpeedContract = data.contract || null;
        renderSpeedChart(cachedSpeedTests, currentSpeedChartMode, cachedSpeedContract);

        if (countOk > 0) {
          const avgD = totDown / countOk;
          const avgU = totUp / countOk;
          const avgDPct = (data.speed && data.speed.avg_down_pct_of_offered) ? data.speed.avg_down_pct_of_offered : (cDown > 0 ? (avgD / cDown) * 100.0 : null);
          const avgUPct = (data.speed && data.speed.avg_up_pct_of_offered) ? data.speed.avg_up_pct_of_offered : (cUp > 0 ? (avgU / cUp) * 100.0 : null);
          document.getElementById('avg-down-display').innerHTML = `<b>${avgD.toFixed(2)} Mbps</b> ${renderRowPctBadge(avgDPct)}`;
          document.getElementById('avg-up-display').innerHTML = `<b>${avgU.toFixed(2)} Mbps</b> ${renderRowPctBadge(avgUPct)}`;
          document.getElementById('avg-lat-display').innerHTML = `<b>${(totLat / countOk).toFixed(2)} ms</b>`;
        }
      }

      // Portscan checks (Tab 4)
      if (data.port_checks && data.port_checks.length > 0) {
        let pcHtml = '';
        data.port_checks.forEach(pc => {
          const isOk = pc.verdict === 'ok';
          const badge = isOk ? `<span class="badge badge-ok">${t('portscan_neutral', 'Neutral')}</span>` : `<span class="badge badge-crit">${t('portscan_throttled', 'Throttled / Blocked')}</span>`;
          const rate = pc.bps ? (pc.bps / 1000000.0).toFixed(2) + ' Mbps' : '--';
          const ratio = pc.ratio ? (pc.ratio * 100).toFixed(0) + '%' : '100%';
          const safeEndpoint = escapeHtml(pc.endpoint || '--');
          const safeProto = escapeHtml((pc.proto || 'tcp').toUpperCase());
          pcHtml += `<tr>
            <td><b>${escapeHtml(pc.port)}</b></td>
            <td><span class="badge badge-warn">${safeProto}</span></td>
            <td>${safeEndpoint}</td>
            <td>${rate}</td>
            <td>${ratio}</td>
            <td>${badge}</td>
          </tr>`;
        });
        document.getElementById('portscan-table-body').innerHTML = pcHtml;
      }

      // System event logs (Tab 5)
      if (data.system_events && data.system_events.length > 0) {
        let lHtml = '';
        data.system_events.forEach(e => {
          const d = new Date(e.ts);
          const dtStr = d.getFullYear() + '.' + String(d.getMonth()+1).padStart(2,'0') + '.' + String(d.getDate()).padStart(2,'0') + ' ' + String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0') + ':' + String(d.getSeconds()).padStart(2,'0');
          const badgeClass = e.severity === 'crit' ? 'badge-crit' : (e.severity === 'warn' ? 'badge-warn' : 'badge-ok');
          const safeSource = escapeHtml(e.source || '');
          const safeKind = escapeHtml(e.kind || '');
          let safeDetail = escapeHtml(e.detail || '')
            .replace(/IPv4: ([0-9.]+)/g, '<span style="color:#38bdf8; font-weight:600;">IPv4: $1</span>')
            .replace(/IPv6: ([0-9a-fA-F:]+)/g, '<span style="color:#a78bfa; font-weight:600;">IPv6: $1</span>');
          lHtml += `<tr>
            <td style="font-family:monospace; color:#94a3b8;">${dtStr}</td>
            <td><span class="badge ${badgeClass}">${escapeHtml((e.severity || '').toUpperCase())}</span></td>
            <td><b>${safeSource}</b></td>
            <td><code>${safeKind}</code></td>
            <td style="color:#f1f5f9;">${safeDetail}</td>
          </tr>`;
        });
        document.getElementById('syslog-table-body').innerHTML = lHtml;
      } else {
        const tbody = document.getElementById('syslog-table-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">No system events recorded.</td></tr>';
      }

      // Live Traffic gauges & clients (Tab 8 QoS)
      if (data.live_traffic) {
        renderSpeedometer('gauge-needle-up', 'gauge-arc-up', 'gauge-text-up', data.live_traffic.tx_mbps || 0);
        renderSpeedometer('gauge-needle-down', 'gauge-arc-down', 'gauge-text-down', data.live_traffic.rx_mbps || 0);

        const clients = data.live_traffic.clients || [];
        let cHtml = '';
        clients.forEach(c => {
          const upW = Math.min(100, Math.max(3, (c.up_kbps / 1000.0) * 10));
          const downW = Math.min(100, Math.max(3, (c.down_kbps / 1000.0) * 10));
          const icon = c.icon === 'speedtest' ? '⚡' : (c.icon === 'desktop' ? '💻' : (c.icon === 'server' ? '🖧' : '📱'));
          cHtml += `<div class="client-row">
            <div class="client-icon">${icon}</div>
            <div class="client-info">
              <div class="client-name" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</div>
            </div>
            <div class="client-bars">
              <div class="client-bar-track"><div class="client-bar-fill-up" style="width: ${upW}%;"></div></div>
              <div class="client-bar-track"><div class="client-bar-fill-down" style="width: ${downW}%;"></div></div>
            </div>
            <div class="client-rates">
              <div class="rate-up">${c.up_kbps.toFixed(1)} Kb</div>
              <div class="rate-down">${c.down_kbps.toFixed(1)} Kb</div>
            </div>
          </div>`;
        });
        document.getElementById('qos-clients-list').innerHTML = cHtml || '<div style="color:var(--text-muted); text-align:center; padding:10px;">' + t('qos_no_clients', 'No active client traffic detected') + '</div>';
      }

      // Wi-Fi Telemetry & Dynamic Hardware Capabilities Sync
      if (data.wifi && data.wifi.capabilities) {
        renderWifiCapabilities(data.wifi.capabilities, data.wifi.live_status || (data.wifi.capabilities && data.wifi.capabilities.current_status) || {});
      }

    } catch (e) {
      console.error('Error refreshing status:', e);
    }
  }

  // ==========================================
  // Interactive Speedtest & Unified Telemetry Chart
  // ==========================================
  let currentSpeedChartMode = 'combined'; // 'combined' | 'throughput' | 'latency'
  let cachedSpeedTests = [];
  let cachedSpeedContract = null;

  function setSpeedChartMode(mode) {
    currentSpeedChartMode = mode;
    ['combined', 'throughput', 'latency'].forEach(m => {
      const btn = document.getElementById('btn-speed-chart-mode-' + m);
      if (btn) btn.className = (m === mode) ? 'btn-primary' : 'btn-secondary';
    });

    const legDown = document.getElementById('speed-legend-down');
    const legUp = document.getElementById('speed-legend-up');
    const legLat = document.getElementById('speed-legend-lat');
    if (legDown) legDown.style.display = (mode === 'latency') ? 'none' : 'flex';
    if (legUp) legUp.style.display = (mode === 'latency') ? 'none' : 'flex';
    if (legLat) legLat.style.display = (mode === 'throughput') ? 'none' : 'flex';

    renderSpeedChart(cachedSpeedTests, currentSpeedChartMode, cachedSpeedContract);
  }

  function renderSpeedChart(tests, mode, contract) {
    const wrap = document.getElementById('speed-chart-svg-wrap');
    if (!wrap) return;

    if (!tests || tests.length === 0) {
      wrap.innerHTML = `<div style="display:flex; align-items:center; justify-content:center; height:240px; color:var(--text-muted); font-size:13px;">
        ${t('speed_no_data', 'No speed test results yet')}
      </div>`;
      return;
    }

    const container = document.getElementById('speed-chart-container');
    const containerWidth = (container ? container.clientWidth : 0) || window.innerWidth || 800;
    const isMobile = (window.innerWidth <= 768) || (containerWidth < 550);

    // Sort chronologically (oldest to newest)
    // On mobile screens, show the latest 14 data points for finger-friendly spacing (22-28px between points)
    // On desktop screens, show up to 30 points
    const sorted = [...tests]
      .filter(t => t && (t.status === 'ok' || t.down_bps || t.up_bps))
      .sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
    const list = isMobile ? sorted.slice(-14) : sorted.slice(-30);

    if (list.length === 0) {
      wrap.innerHTML = `<div style="display:flex; align-items:center; justify-content:center; height:240px; color:var(--text-muted); font-size:13px;">
        ${t('speed_no_valid_data', 'No valid measurement data')}
      </div>`;
      return;
    }

    const W = isMobile ? 500 : 900;
    const H = isMobile ? 380 : 270;
    const padL = isMobile ? (mode === 'latency' ? 56 : 54) : 60;
    const padR = (mode === 'combined') ? (isMobile ? 56 : 60) : (isMobile ? 20 : 25);
    const padT = isMobile ? 30 : 25;
    const padB = isMobile ? 50 : 40;
    const chartW = W - padL - padR;
    const chartH = H - padT - padB;

    let maxMbps = 10;
    const contractDown = (contract && contract.contract_down_mbps) ? parseFloat(contract.contract_down_mbps) : 0;
    const contractUp = (contract && contract.contract_up_mbps) ? parseFloat(contract.contract_up_mbps) : 0;
    if (contractDown > maxMbps) maxMbps = contractDown;
    if (contractUp > maxMbps) maxMbps = contractUp;

    let maxLat = 10;

    list.forEach(item => {
      const dM = (item.down_bps || 0) / 1000000.0;
      const uM = (item.up_bps || 0) / 1000000.0;
      const lat = (item.ping_us || 0) / 1000.0;
      if (dM > maxMbps) maxMbps = dM;
      if (uM > maxMbps) maxMbps = uM;
      if (lat > maxLat) maxLat = lat;
    });

    function niceCeil(v) {
      if (v <= 20) return Math.ceil(v / 5) * 5;
      if (v <= 100) return Math.ceil(v / 10) * 10;
      if (v <= 500) return Math.ceil(v / 50) * 50;
      if (v <= 1000) return Math.ceil(v / 100) * 100;
      return Math.ceil(v / 250) * 250;
    }
    maxMbps = niceCeil(maxMbps * 1.15);
    maxLat = niceCeil(maxLat * 1.25);

    const contractLeg = document.getElementById('speed-legend-contract');
    if (contractLeg) {
      contractLeg.style.display = (contractDown > 0 || contractUp > 0) ? 'flex' : 'none';
    }

    let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%; height:100%; display:block; user-select:none;" preserveAspectRatio="none">
      <defs>
        <linearGradient id="speedDownGrad" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.38"/>
          <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.02"/>
        </linearGradient>
        <linearGradient id="speedUpGrad" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#34d399" stop-opacity="0.25"/>
          <stop offset="100%" stop-color="#34d399" stop-opacity="0.01"/>
        </linearGradient>
      </defs>`;

    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const y = padT + chartH - (i / steps) * chartH;
      svg += `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="rgba(255,255,255,0.07)" stroke-dasharray="3,3" />`;
      
      const yFontSize = isMobile ? "13.5" : "10.5";
      const yFontWeight = isMobile ? "700" : "normal";
      if (mode !== 'latency') {
        const valM = Math.round((maxMbps / steps) * i);
        svg += `<text x="${padL - 6}" y="${y + 4}" fill="#38bdf8" font-size="${yFontSize}" font-weight="${yFontWeight}" text-anchor="end" font-family="monospace">${valM}M</text>`;
      } else {
        const valL = Math.round((maxLat / steps) * i);
        svg += `<text x="${padL - 6}" y="${y + 4}" fill="#fbbf24" font-size="${yFontSize}" font-weight="${yFontWeight}" text-anchor="end" font-family="monospace">${valL}ms</text>`;
      }

      if (mode === 'combined') {
        const valL = Math.round((maxLat / steps) * i);
        svg += `<text x="${W - padR + 6}" y="${y + 4}" fill="#fbbf24" font-size="${yFontSize}" font-weight="${yFontWeight}" text-anchor="start" font-family="monospace">${valL}ms</text>`;
      }
    }

    if (mode !== 'latency' && contractDown > 0 && contractDown <= maxMbps) {
      const yContract = padT + chartH - (contractDown / maxMbps) * chartH;
      svg += `<line x1="${padL}" y1="${yContract}" x2="${W - padR}" y2="${yContract}" stroke="#ec4899" stroke-width="1.5" stroke-dasharray="4,4" opacity="0.85" />`;
      svg += `<text x="${W - padR - 6}" y="${yContract - 5}" fill="#ec4899" font-size="${isMobile ? '10.5' : '9.5'}" text-anchor="end" font-weight="600">SLA: ${contractDown}M</text>`;
    }

    const n = list.length;
    const getX = (idx) => (n <= 1) ? (padL + chartW / 2) : (padL + (idx / (n - 1)) * chartW);
    const getYDown = (mbps) => padT + chartH - Math.min(chartH, (mbps / maxMbps) * chartH);
    const getYUp = (mbps) => padT + chartH - Math.min(chartH, (mbps / maxMbps) * chartH);
    const getYLat = (lat) => padT + chartH - Math.min(chartH, (lat / maxLat) * chartH);

    const ptsDown = [];
    const ptsUp = [];
    const ptsLat = [];

    list.forEach((item, idx) => {
      const x = getX(idx);
      const dM = (item.down_bps || 0) / 1000000.0;
      const uM = (item.up_bps || 0) / 1000000.0;
      const lat = (item.ping_us || 0) / 1000.0;
      ptsDown.push({ x, y: getYDown(dM), val: dM });
      ptsUp.push({ x, y: getYUp(uM), val: uM });
      ptsLat.push({ x, y: getYLat(lat), val: lat });
    });

    const lineStroke = isMobile ? "3" : "2.5";
    const latStroke = isMobile ? "2.5" : "2";

    if (mode !== 'latency' && ptsDown.length > 0) {
      let areaD = `M ${ptsDown[0].x},${padT + chartH} L ${ptsDown[0].x},${ptsDown[0].y}`;
      let lineD = `M ${ptsDown[0].x},${ptsDown[0].y}`;
      for (let i = 1; i < ptsDown.length; i++) {
        areaD += ` L ${ptsDown[i].x},${ptsDown[i].y}`;
        lineD += ` L ${ptsDown[i].x},${ptsDown[i].y}`;
      }
      areaD += ` L ${ptsDown[ptsDown.length - 1].x},${padT + chartH} Z`;
      svg += `<path d="${areaD}" fill="url(#speedDownGrad)" />`;
      svg += `<path d="${lineD}" fill="none" stroke="#38bdf8" stroke-width="${lineStroke}" stroke-linejoin="round" stroke-linecap="round" />`;
    }

    if (mode !== 'latency' && ptsUp.length > 0) {
      let areaU = `M ${ptsUp[0].x},${padT + chartH} L ${ptsUp[0].x},${ptsUp[0].y}`;
      let lineU = `M ${ptsUp[0].x},${ptsUp[0].y}`;
      for (let i = 1; i < ptsUp.length; i++) {
        areaU += ` L ${ptsUp[i].x},${ptsUp[i].y}`;
        lineU += ` L ${ptsUp[i].x},${ptsUp[i].y}`;
      }
      areaU += ` L ${ptsUp[ptsUp.length - 1].x},${padT + chartH} Z`;
      svg += `<path d="${areaU}" fill="url(#speedUpGrad)" />`;
      svg += `<path d="${lineU}" fill="none" stroke="#34d399" stroke-width="${lineStroke}" stroke-linejoin="round" stroke-linecap="round" />`;
    }

    if (mode !== 'throughput' && ptsLat.length > 0) {
      let lineL = `M ${ptsLat[0].x},${ptsLat[0].y}`;
      for (let i = 1; i < ptsLat.length; i++) {
        lineL += ` L ${ptsLat[i].x},${ptsLat[i].y}`;
      }
      const latStrokeDash = (mode === 'combined') ? 'stroke-dasharray="4,3"' : '';
      svg += `<path d="${lineL}" fill="none" stroke="#fbbf24" stroke-width="${latStroke}" ${latStrokeDash} stroke-linejoin="round" stroke-linecap="round" />`;
    }

    svg += `<line id="speed-chart-crosshair" x1="0" y1="${padT}" x2="0" y2="${padT + chartH}" stroke="#64748b" stroke-width="1.5" stroke-dasharray="3,3" opacity="0" pointer-events="none" />`;

    const dotR = isMobile ? "5.5" : "3.5";
    const dotStrkW = isMobile ? "2.5" : "1.5";
    const labelInterval = isMobile ? Math.max(1, Math.floor(n / 4)) : Math.max(1, Math.floor(n / 6));

    list.forEach((item, idx) => {
      const x = getX(idx);
      const d = new Date(item.ts);
      const timeStr = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
      const dateStr = String(d.getMonth() + 1).padStart(2, '0') + '/' + String(d.getDate()).padStart(2, '0');

      if (idx % labelInterval === 0 || idx === n - 1) {
        const timeFontSize = isMobile ? "13" : "10";
        const dateFontSize = isMobile ? "11" : "8.5";
        svg += `<text x="${x}" y="${H - 16}" fill="#cbd5e1" font-size="${timeFontSize}" font-weight="${isMobile ? '700' : 'normal'}" text-anchor="middle" font-family="monospace">${timeStr}</text>`;
        svg += `<text x="${x}" y="${H - 3}" fill="#94a3b8" font-size="${dateFontSize}" text-anchor="middle" font-family="monospace">${dateStr}</text>`;
      }

      if (mode !== 'latency') {
        svg += `<circle id="dot-down-${idx}" cx="${x}" cy="${ptsDown[idx].y}" r="${dotR}" fill="#38bdf8" stroke="#0a0f1d" stroke-width="${dotStrkW}" pointer-events="none" />`;
      }
      if (mode !== 'latency') {
        svg += `<circle id="dot-up-${idx}" cx="${x}" cy="${ptsUp[idx].y}" r="${dotR}" fill="#34d399" stroke="#0a0f1d" stroke-width="${dotStrkW}" pointer-events="none" />`;
      }
      if (mode !== 'throughput') {
        svg += `<circle id="dot-lat-${idx}" cx="${x}" cy="${ptsLat[idx].y}" r="${dotR}" fill="#fbbf24" stroke="#0a0f1d" stroke-width="${dotStrkW}" pointer-events="none" />`;
      }
    });

    const colStep = (n > 1) ? (chartW / (n - 1)) : chartW;
    list.forEach((item, idx) => {
      const x = getX(idx);
      const hitX = (idx === 0) ? (x - padL) : (x - colStep / 2);
      const hitW = (idx === 0 || idx === n - 1) ? (colStep / 2 + 15) : colStep;

      svg += `<rect x="${hitX}" y="${padT}" width="${hitW}" height="${chartH}" fill="transparent" style="cursor:crosshair;"
        onmousemove="onSpeedChartHover(event, ${idx})"
        onmouseleave="onSpeedChartLeave()"
        ontouchstart="onSpeedChartTouch(event, ${idx})"
        ontouchmove="onSpeedChartTouch(event, ${idx})" />`;
    });

    svg += `</svg>`;
    wrap.innerHTML = svg;
    window._currentSpeedChartList = list;
    window._currentSpeedChartMeta = { W, H, padL, padR, padT, padB, chartW, chartH, n, getX, isMobile };
  }

  function onSpeedChartHover(event, idx) {
    showSpeedChartTooltip(event, idx);
  }

  function onSpeedChartTouch(event, idx) {
    if (event.touches && event.touches.length > 0) {
      showSpeedChartTooltip(event.touches[0], idx);
    }
  }

  function onSpeedChartLeave() {
    hideSpeedChartTooltip();
  }

  function showSpeedChartTooltip(pointerEvent, idx) {
    const list = window._currentSpeedChartList;
    const meta = window._currentSpeedChartMeta;
    if (!list || !meta || idx < 0 || idx >= list.length) return;

    const item = list[idx];
    const tooltip = document.getElementById('speed-chart-tooltip');
    const container = document.getElementById('speed-chart-container');
    const crosshair = document.getElementById('speed-chart-crosshair');
    if (!tooltip || !container) return;

    const rect = container.getBoundingClientRect();
    const xPos = meta.getX(idx);

    if (crosshair) {
      crosshair.setAttribute('x1', xPos);
      crosshair.setAttribute('x2', xPos);
      crosshair.setAttribute('opacity', '0.75');
    }

    const activeR = meta.isMobile ? '7.5' : '6.5';
    const normalR = meta.isMobile ? '4.5' : '3.5';

    for (let i = 0; i < meta.n; i++) {
      const dDot = document.getElementById('dot-down-' + i);
      const uDot = document.getElementById('dot-up-' + i);
      const lDot = document.getElementById('dot-lat-' + i);
      const isAct = (i === idx);
      if (dDot) dDot.setAttribute('r', isAct ? activeR : normalR);
      if (uDot) uDot.setAttribute('r', isAct ? activeR : normalR);
      if (lDot) lDot.setAttribute('r', isAct ? activeR : normalR);
    }

    const d = new Date(item.ts);
    const dtStr = d.getFullYear() + '.' + String(d.getMonth() + 1).padStart(2, '0') + '.' + String(d.getDate()).padStart(2, '0') + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0') + ':' + String(d.getSeconds()).padStart(2, '0');
    const dMbps = (item.down_bps || 0) / 1000000.0;
    const uMbps = (item.up_bps || 0) / 1000000.0;
    const lat = (item.ping_us || 0) / 1000.0;
    const jitter = item.jitter_ms !== undefined ? `${item.jitter_ms.toFixed(1)} ms` : (item.jitter_us ? `${(item.jitter_us / 1000.0).toFixed(1)} ms` : null);

    let engineBadge = '<span class="badge" style="background:rgba(2,132,199,0.2);color:#38bdf8;border:1px solid #0284c7;font-size: 11px;">OOKLA</span>';
    if (item.engine === 'cloudflare') {
      engineBadge = `<span class="badge" style="background:rgba(245,158,11,0.2);color:#fbbf24;border:1px solid #f59e0b;font-size: 11px;">CLOUDFLARE ${item.colo ? '[' + escapeHtml(item.colo) + ']' : ''}</span>`;
    } else if (item.engine === 'fastcom') {
      engineBadge = `<span class="badge" style="background:rgba(229,9,20,0.2);color:#f87171;border:1px solid #e50914;font-size: 11px;">FAST.COM ${item.colo ? '[' + escapeHtml(item.colo) + ']' : ''}</span>`;
    } else if (item.engine === 'rtr' || item.engine === 'rtr-nettest') {
      engineBadge = '<span class="badge" style="background:rgba(16,185,129,0.2);color:#34d399;border:1px solid #10b981;font-size: 11px;">RTR-NETTEST</span>';
    } else if (item.engine === 'iperf3') {
      engineBadge = '<span class="badge" style="background:rgba(168,85,247,0.2);color:#c084fc;border:1px solid #a855f7;font-size: 11px;">IPERF3</span>';
    }

    const bb = item.bufferbloat_grade ? `<span class="badge badge-ok" style="font-size: 11px;">${escapeHtml(item.bufferbloat_grade)} (+${item.bufferbloat_delta_ms || 0}ms)</span>` : '';

    let content = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:4px; gap:8px;">
        <span style="font-weight:700; color:#f8fafc; font-size:11.5px;">🕒 ${dtStr}</span>
        ${engineBadge}
      </div>
      <div style="display:grid; grid-template-columns:auto 1fr; gap:4px 10px; font-size:12px; margin-bottom:6px;">
        <span style="color:#38bdf8; font-weight:600;">${t('speed_tip_down', '⬇️ Download:')}</span>
        <span style="font-weight:700; color:#f8fafc; text-align:right;">${dMbps.toFixed(2)} Mbps</span>
        <span style="color:#34d399; font-weight:600;">${t('speed_tip_up', '⬆️ Upload:')}</span>
        <span style="font-weight:700; color:#f8fafc; text-align:right;">${uMbps.toFixed(2)} Mbps</span>
        <span style="color:#fbbf24; font-weight:600;">🏓 Ping RTT:</span>
        <span style="font-weight:700; color:#f8fafc; text-align:right;">${lat.toFixed(2)} ms</span>
        ${jitter ? `<span style="color:#cbd5e1;">〰️ Jitter:</span><span style="text-align:right; color:#cbd5e1;">${jitter}</span>` : ''}
        ${bb ? `<span style="color:#cbd5e1;">📶 Bufferbloat:</span><span style="text-align:right;">${bb}</span>` : ''}
      </div>
    `;

    const sName = item.server_name || item.server_host || '';
    if (sName) {
      content += `<div style="font-size: 11px; color:#94a3b8; border-top:1px solid rgba(255,255,255,0.06); padding-top:4px;">📍 ${t('server_prefix', 'Server')}: <b>${escapeHtml(sName)}</b></div>`;
    }
    if (item.client_ip || item.client_ipv6) {
      content += `<div style="font-size: 11px; color:#64748b; font-family:monospace;">🌐 IP: ${escapeHtml(item.client_ip || '')} ${item.client_ipv6 ? '[' + escapeHtml(item.client_ipv6) + ']' : ''}</div>`;
    }

    tooltip.innerHTML = content;

    const scaleX = rect.width / meta.W;
    const clientX = xPos * scaleX;

    if (rect.width < 500) {
      tooltip.style.left = '50%';
      tooltip.style.top = '10px';
      tooltip.style.transform = 'translateX(-50%)';
      tooltip.style.width = 'calc(100% - 20px)';
      tooltip.style.maxWidth = '320px';
    } else {
      tooltip.style.width = 'auto';
      tooltip.style.maxWidth = '280px';
      if (clientX > rect.width * 0.65) {
        tooltip.style.transform = 'translate(-102%, -60%)';
      } else {
        tooltip.style.transform = 'translate(6%, -60%)';
      }
      tooltip.style.left = `${clientX}px`;
      tooltip.style.top = '100px';
    }

    tooltip.style.display = 'block';
  }

  function hideSpeedChartTooltip() {
    const tooltip = document.getElementById('speed-chart-tooltip');
    if (tooltip) tooltip.style.display = 'none';
    const crosshair = document.getElementById('speed-chart-crosshair');
    if (crosshair) crosshair.setAttribute('opacity', '0');

    const meta = window._currentSpeedChartMeta;
    if (meta) {
      const normalR = meta.isMobile ? '4.5' : '3.5';
      for (let i = 0; i < meta.n; i++) {
        const dDot = document.getElementById('dot-down-' + i);
        const uDot = document.getElementById('dot-up-' + i);
        const lDot = document.getElementById('dot-lat-' + i);
        if (dDot) dDot.setAttribute('r', normalR);
        if (uDot) uDot.setAttribute('r', normalR);
        if (lDot) lDot.setAttribute('r', normalR);
      }
    }
  }

  window.addEventListener('resize', () => {
    if (cachedSpeedTests && cachedSpeedTests.length > 0) {
      renderSpeedChart(cachedSpeedTests, currentSpeedChartMode, cachedSpeedContract);
    }
  });

  function updateGaugeScale(val) {
    if (val === 'auto') {
      gaugeScaleMax = 100;
    } else {
      gaugeScaleMax = parseFloat(val) || 100;
    }
  }

  function renderSpeedometer(needleId, arcId, textId, mbps) {
    const textEl = document.getElementById(textId);
    if (textEl) textEl.textContent = mbps.toFixed(1);

    if (document.getElementById('qos-scale-select').value === 'auto') {
      if (mbps > 500) gaugeScaleMax = 1000;
      else if (mbps > 100) gaugeScaleMax = 500;
      else if (mbps > 50) gaugeScaleMax = 100;
      else gaugeScaleMax = 50;
    }

    const pct = Math.min(1.0, Math.max(0.0, mbps / gaugeScaleMax));
    const angle = -120 + (pct * 240);
    const needleEl = document.getElementById(needleId);
    if (needleEl) needleEl.setAttribute('transform', `rotate(${angle} 100 100)`);

    const arcEl = document.getElementById(arcId);
    if (arcEl) {
      const fullOffset = 335;
      const offset = fullOffset - (pct * fullOffset);
      arcEl.setAttribute('stroke-dashoffset', offset);
    }
  }

  async function triggerSpeedtest(customServerId) {
    if (!customServerId) {
      const homeSelect = document.getElementById('home-target-server-select');
      if (homeSelect) {
        const val = homeSelect.value;
        if (val === 'custom') {
          const cInput = document.getElementById('home-custom-server-id');
          if (cInput && cInput.value && cInput.value.match(/^\d+$/)) {
            customServerId = parseInt(cInput.value);
          }
        } else if (val && val !== 'auto' && val.match(/^\d+$/)) {
          customServerId = parseInt(val);
        }
      }
    }

    showToast(`${t('measuring_started', 'Starting measurement')} [${selectedEngine.toUpperCase()}]${customServerId ? ' #' + customServerId : ''}...`);
    document.getElementById('measuring-banner').style.display = 'flex';
    document.getElementById('btn-home-measure').disabled = true;

    try {
      const payload = { engine: selectedEngine };
      const targetIfaceEl = document.getElementById('speedtest-target-iface');
      if (targetIfaceEl && targetIfaceEl.value && targetIfaceEl.value !== 'auto') {
        payload.interface = targetIfaceEl.value;
      }
      if (customServerId) {
        payload.server_id = parseInt(customServerId);
      }
      const res = await fetch('/api/speedtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        showToast(t('measuring_started', 'Speedtest measurement started!'));
      } else {
        const err = await res.json();
        showToast(err.message || t('measuring_error', 'Error starting measurement.'));
      }
    } catch (e) {
      showToast('Error: ' + e);
    }
    setTimeout(refreshStatus, 1500);
  }

  async function stopSpeedtest() {
    try {
      await fetch('/api/speedtest/stop', { method: 'POST' });
      document.getElementById('measuring-banner').style.display = 'none';
      document.getElementById('btn-home-measure').disabled = false;
      showToast(t('measuring_stopped', 'Measurement stopped.'));
      setTimeout(refreshStatus, 1000);
    } catch (e) {
      showToast('Error: ' + e);
    }
  }

  async function triggerPortCheck() {
    showToast(t('portscan_started', 'Port neutrality audit started...'));
    try {
      await fetch('/api/portcheck', { method: 'POST' });
      setTimeout(refreshStatus, 3000);
    } catch (e) {
      showToast('Error: ' + e);
    }
  }

  // Dynamic Live Server Directory & Search
  function onServerSearchInput(val) {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      loadServers(val);
    }, 350);
  }

  // The home page list of Ookla servers comes from Ookla's current list, not a built-in one.
  async function loadHomeOoklaServers(refresh = false) {
    const group = document.getElementById('home-ookla-server-group');
    const select = document.getElementById('home-target-server-select');
    if (!group || !select) return;
    const btn = document.getElementById('btn-home-ookla-refresh');
    if (refresh && btn) btn.disabled = true;
    try {
      const res = await fetch(refresh ? '/api/speedtest/servers?refresh=1' : '/api/speedtest/servers');
      if (!res.ok) return;
      const data = await res.json();
      const keep = select.value;
      group.innerHTML = (data.servers || []).slice(0, 40).map(s =>
        `<option value="${escapeHtml(String(s.id))}">#${escapeHtml(String(s.id))} ${escapeHtml(s.sponsor || s.name || '')} (${escapeHtml(s.location || s.name || '')})</option>`
      ).join('');
      if (keep && Array.from(select.options).some(o => o.value == keep)) select.value = keep;
      if (refresh) showToast(t('ookla_servers_refreshed', 'Ookla server list updated.'));
    } catch (e) {
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function loadServers(query = '', refresh = false) {
    const tbody = document.getElementById('script-servers-tbody');
    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">${t('searching_servers', 'Searching speedtest benchmark network...')}</td></tr>`;
    try {
      const params = new URLSearchParams();
      if (query) params.set('q', query);
      if (refresh) params.set('refresh', '1');
      const url = '/api/speedtest/servers' + (params.toString() ? '?' + params.toString() : '');
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      serverList = data.servers || [];
      renderCatalog(serverList);
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--red);">Error loading servers: ${escapeHtml(e)}</td></tr>`;
    }
  }

  function renderCatalog(servers) {
    const tbody = document.getElementById('script-servers-tbody');
    if (!servers || servers.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">${t('no_servers_found', 'No matching servers found. Try another city or server ID.')}</td></tr>`;
      return;
    }
    let html = '';
    servers.slice(0, 80).forEach(s => {
      const sid = s.id;
      const sName = escapeQuotes(s.name || s.sponsor || 'Unknown');
      const sHost = escapeQuotes(s.host || '');
      html += `<tr>
        <td><code>#${escapeHtml(sid)}</code></td>
        <td><b>${escapeHtml(s.sponsor || s.name || '--')}</b></td>
        <td>${escapeHtml(s.location || s.name || '--')}</td>
        <td>${escapeHtml(s.country || '--')}</td>
        <td style="text-align: center;">
          <button type="button" class="btn-primary" style="padding: 4px 10px; font-size: 11px;" onclick="setDefaultServer(${jsArg(sid)}, ${jsArg(s.name || s.sponsor || 'Unknown')}, ${jsArg(s.host || '')})">⭐ ${t('servers_btn_use', 'Use as Target Server')}</button>
          <button type="button" class="btn-secondary" style="padding: 4px 10px; font-size: 11px;" onclick="runSingleServerTest(${jsArg(sid)})">${t('server_test_btn', '▶ Test to this server')}</button>
        </td>
      </tr>`;
    });
    tbody.innerHTML = html;
  }

  function escapeQuotes(str) {
    return (str || '').replace(/'/g, "\'").replace(/"/g, '&quot;');
  }

  async function setDefaultServer(id, name, host) {
    try {
      const res = await fetch('/api/speedtest/default-server', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server_id: id, server_name: name, server_host: host })
      });
      if (res.ok) {
        showToast(id ? `${t('server_saved', 'Target server saved: ')} ${name} (#${id})` : t('target_server_auto', 'Restored to automatic closest server.'));
        refreshStatus();
      }
    } catch (e) {
      showToast('Error saving server: ' + e);
    }
  }

  async function runSingleServerTest(id) {
    showToast(`${t('measuring_started', 'Starting test to server')} #${id}...`);
    triggerSpeedtest(id);
    switchTab('tab-home');
  }

  function setManualServerDirect(action) {
    const input = document.getElementById('sched-server-id-input') || document.getElementById('home-custom-server-id');
    if (!input) return;
    const val = (input.value || '').trim();
    if (!val || !val.match(/^[0-9]+$/)) {
      showToast(t('err_server_id', 'Please enter a numeric Ookla server ID.'));
      return;
    }
    const sid = parseInt(val);
    if (action === 'default') {
      setDefaultServer(sid, `${t('custom_server', 'Custom Server')} #${sid}`, '');
    } else {
      runSingleServerTest(sid);
    }
  }

  function filterLogTable(q) {
    q = (q || '').toLowerCase();
    const rows = document.querySelectorAll('#syslog-table-body tr');
    rows.forEach(r => {
      const txt = r.textContent.toLowerCase();
      r.style.display = txt.includes(q) ? '' : 'none';
    });
  }

  // Hardware & Linux Kernel Syslog System (Router-Grade Diagnostics)
  let devLogActiveSubtab = 'syslog';
  let devLogLive = true;
  let devLogLevelFilter = 'ALL';
  let devLogSearchDebounce = null;
  let devLogAutoScroll = true;

  let syslogLive = true;
  let syslogSourceFilter = 'all';
  let syslogSearchDebounce = null;
  let syslogAutoScroll = true;

  function switchSyslogSubtab(mode) {
    devLogActiveSubtab = mode;
    const btnSys = document.getElementById('btn-subtab-syslog');
    const btnDev = document.getElementById('btn-subtab-devlog');
    const btnAudit = document.getElementById('btn-subtab-audit');
    const paneSys = document.getElementById('syslog-subtab-syslog');
    const paneDev = document.getElementById('syslog-subtab-devlog');
    const paneAudit = document.getElementById('syslog-subtab-audit');

    if (btnSys) btnSys.className = (mode === 'syslog') ? 'app-tab-btn active' : 'app-tab-btn';
    if (btnDev) btnDev.className = (mode === 'devlog') ? 'app-tab-btn active' : 'app-tab-btn';
    if (btnAudit) btnAudit.className = (mode === 'audit') ? 'app-tab-btn active' : 'app-tab-btn';

    if (paneSys) paneSys.style.display = (mode === 'syslog') ? 'block' : 'none';
    if (paneDev) paneDev.style.display = (mode === 'devlog') ? 'block' : 'none';
    if (paneAudit) paneAudit.style.display = (mode === 'audit') ? 'block' : 'none';

    if (mode === 'syslog') {
      fetchSystemSyslog(true);
    } else if (mode === 'devlog') {
      fetchDevLogs(true);
    }
  }

  function toggleSyslogLive(enabled) {
    syslogLive = !!enabled;
    const dot = document.getElementById('syslog-live-dot');
    if (dot) {
      dot.style.background = syslogLive ? '#10b981' : '#64748b';
      dot.style.boxShadow = syslogLive ? '0 0 6px #10b981' : 'none';
    }
    if (syslogLive) {
      fetchSystemSyslog(false);
    }
  }

  function setSyslogSourceFilter(src) {
    syslogSourceFilter = src;
    document.querySelectorAll('#syslog-source-pills .lvl-btn').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-src') === src);
    });
    fetchSystemSyslog(true);
  }

  function onSyslogSearchKeyup(e) {
    if (syslogSearchDebounce) clearTimeout(syslogSearchDebounce);
    syslogSearchDebounce = setTimeout(() => {
      fetchSystemSyslog(true);
    }, 250);
  }

  function downloadSystemSyslog() {
    const sev = (document.getElementById('syslog-severity-select') || {}).value || 'all';
    const lines = (document.getElementById('syslog-lines-select') || {}).value || '2000';
    const q = (document.getElementById('syslog-search-input') || {}).value || '';
    const url = `/api/system/syslog/download?source=${encodeURIComponent(syslogSourceFilter)}&severity=${encodeURIComponent(sev)}&lines=${encodeURIComponent(lines)}&search=${encodeURIComponent(q)}`;
    window.location.href = url;
  }

  async function fetchSystemSyslog(forceScroll) {
    const sev = (document.getElementById('syslog-severity-select') || {}).value || 'all';
    const lines = (document.getElementById('syslog-lines-select') || {}).value || '300';
    const q = (document.getElementById('syslog-search-input') || {}).value || '';
    const url = `/api/system/syslog?source=${encodeURIComponent(syslogSourceFilter)}&severity=${encodeURIComponent(sev)}&lines=${encodeURIComponent(lines)}&search=${encodeURIComponent(q)}`;

    try {
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === 'ok') {
        renderSystemSyslog(data, forceScroll);
      }
    } catch (e) {
      // ignore network glitches during switching
    }
  }

  function renderSystemSyslog(data, forceScroll) {
    const term = document.getElementById('syslog-terminal');
    if (!term) return;

    const isAtBottom = term.scrollHeight - term.scrollTop - term.clientHeight < 60;
    syslogAutoScroll = forceScroll ? true : isAtBottom;

    const entries = data.entries || [];
    const stats = data.stats || {};

    const cntAll = document.getElementById('syslog-cnt-all');
    if (cntAll) cntAll.innerText = String(stats.total_raw || entries.length);
    const cntKernel = document.getElementById('syslog-cnt-kernel');
    if (cntKernel) cntKernel.innerText = String(stats.kernel || 0);
    const cntNet = document.getElementById('syslog-cnt-network');
    if (cntNet) cntNet.innerText = String(stats.network || 0);

    const footer = document.getElementById('syslog-footer-info');
    if (footer) {
      footer.innerHTML = `Host: <b style="color:#38bdf8;">${escapeHtml(data.hostname || 'speedtest')}</b> &bull; Displaying: <b>${escapeHtml(entries.length)}</b> lines &bull; Kernel: <b style="color:#38bdf8;">${stats.kernel || 0}</b> &bull; Network & PHY: <b style="color:#34d399;">${stats.network || 0}</b> &bull; Link Events: <b style="color:#f59e0b;">${stats.links || 0}</b> &bull; Errors: <b style="color:${stats.errors ? '#f87171' : '#94a3b8'};">${stats.errors || 0}</b> &bull; System Time: <code>${escapeHtml(data.system_time || '')}</code>`;
    }

    if (entries.length === 0) {
      term.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:40px;">No system log entries matching the selected filters.</div>';
      return;
    }

    let html = '';
    entries.forEach(e => {
      let tagClass = 'syslog-tag-system';
      if (e.category === 'kernel') tagClass = 'syslog-tag-kernel';
      else if (e.category === 'network') tagClass = 'syslog-tag-network';
      else if (e.category === 'nmb') tagClass = 'syslog-tag-nmb';
      else if (e.category === 'security') tagClass = 'syslog-tag-security';

      let msgClass = 'syslog-msg';
      let badgeHtml = '';
      if (e.level === 'link_up') {
        msgClass += ' syslog-msg-link-up';
        badgeHtml = '<span class="syslog-badge-tag syslog-badge-linkup">LINK UP</span>';
      } else if (e.level === 'link_down') {
        msgClass += ' syslog-msg-link-down';
        badgeHtml = '<span class="syslog-badge-tag syslog-badge-linkdown">LINK DOWN</span>';
      } else if (e.level === 'stacktrace') {
        msgClass += ' syslog-msg-stacktrace';
        badgeHtml = '<span class="syslog-badge-tag" style="background:#4a044e; color:#f0abfc; border:1px solid #d946ef;">STACK</span>';
      } else if (e.level === 'error') {
        msgClass += ' syslog-msg-error';
        badgeHtml = '<span class="syslog-badge-tag syslog-badge-error">ERR</span>';
      } else if (e.level === 'warn') {
        msgClass += ' syslog-msg-warn';
        badgeHtml = '<span class="syslog-badge-tag syslog-badge-warn">WARN</span>';
      }

      // Format message with highlighted tokens
      let msgSafe = escapeHtml(e.msg || e.raw);
      // Highlight MAC addresses
      msgSafe = msgSafe.replace(/([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})/g, '<span style="color:#fbbf24; font-weight:600;">$1</span>');
      // Highlight IPv4 addresses
      msgSafe = msgSafe.replace(/((?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)[.](?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)[.](?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)[.](?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?))/g, '<span style="color:#60a5fa; font-weight:600;">$1</span>');
      // Highlight Link is Up / Link is Down
      msgSafe = msgSafe.replace(/(Link (?:is )?Up[^<]*)/gi, '<b style="color:#34d399;">🟢 $1</b>');
      msgSafe = msgSafe.replace(/(Link (?:is )?DOWN[^<]*)/gi, '<b style="color:#f87171;">🔴 $1</b>');

      html += `<div class="syslog-row">
        <span class="syslog-ts">${escapeHtml(e.ts || '')}</span>
        <span class="syslog-host">${escapeHtml(e.host || '')}</span>
        <span class="syslog-tag ${tagClass}" title="${escapeHtml(e.tag || '')}">${escapeHtml(e.tag || '')}</span>
        <span class="${msgClass}">${badgeHtml}${msgSafe}</span>
      </div>`;
    });

    term.innerHTML = html;

    if (syslogAutoScroll) {
      term.scrollTop = term.scrollHeight;
    }
  }

  function toggleDevLogLive(enabled) {
    devLogLive = !!enabled;
    const dot = document.getElementById('devlog-live-dot');
    if (dot) {
      dot.style.background = devLogLive ? '#10b981' : '#64748b';
      dot.style.boxShadow = devLogLive ? '0 0 6px #10b981' : 'none';
    }
    if (devLogLive) {
      fetchDevLogs(false);
    }
  }

  function setDevLogLevelFilter(lvl) {
    devLogLevelFilter = lvl;
    document.querySelectorAll('.devlog-level-pills .lvl-btn').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-lvl') === lvl);
    });
    fetchDevLogs(true);
  }

  function onDevLogSearchKeyup(e) {
    if (devLogSearchDebounce) clearTimeout(devLogSearchDebounce);
    devLogSearchDebounce = setTimeout(() => {
      fetchDevLogs(true);
    }, 250);
  }

  async function fetchDevLogs(forceScroll) {
    const comp = (document.getElementById('devlog-comp-select') || {}).value || '';
    const q = (document.getElementById('devlog-search-input') || {}).value || '';
    const url = `/api/dev/logs?level=${encodeURIComponent(devLogLevelFilter)}&component=${encodeURIComponent(comp)}&search=${encodeURIComponent(q)}&limit=300`;

    try {
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === 'ok') {
        renderDevLogs(data, forceScroll);
      }
    } catch (e) {
      // ignore network errors during tab switches
    }
  }

  function renderDevLogs(data, forceScroll) {
    const term = document.getElementById('devlog-terminal');
    if (!term) return;

    // Check if user is scrolled near bottom
    const isAtBottom = term.scrollHeight - term.scrollTop - term.clientHeight < 60;
    if (forceScroll) {
      devLogAutoScroll = true;
    } else {
      devLogAutoScroll = isAtBottom;
    }

    const records = data.records || [];
    const countSpan = document.getElementById('cnt-all');
    if (countSpan) countSpan.innerText = String(records.length);

    // Update daemon level dropdown if changed
    const dSelect = document.getElementById('devlog-daemon-level-select');
    if (dSelect && data.current_level && dSelect.value !== data.current_level) {
      dSelect.value = data.current_level;
    }

    // Update status footer
    const footer = document.getElementById('devlog-footer-info');
    if (footer) {
      footer.innerHTML = `Records: <b>${escapeHtml(records.length)}</b> (Buffer: ${data.total_buffered || 0} / ${data.capacity || 5000}) &bull; Active file: <code style="color:#38bdf8;">${escapeHtml(data.log_file || '/var/log/nmb/nmb_developer.log')}</code> &bull; Daemon Level: <b style="color:#f59e0b;">${escapeHtml(data.current_level || 'DEBUG')}</b>`;
    }

    if (records.length === 0) {
      term.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:40px;">No developer log entries matching the selected filters.</div>';
      return;
    }

    let html = '';
    records.forEach(r => {
      const lvl = (r.level || 'INFO').toLowerCase();
      let badgeClass = 'devlog-badge-info';
      if (lvl === 'trace') badgeClass = 'devlog-badge-trace';
      else if (lvl === 'debug') badgeClass = 'devlog-badge-debug';
      else if (lvl === 'warn' || lvl === 'warning') badgeClass = 'devlog-badge-warn';
      else if (lvl === 'error' || lvl === 'critical') badgeClass = 'devlog-badge-error';

      const loc = `${r.filename || 'code'}:${r.line} in ${r.func || '?'}`;
      let excHtml = '';
      if (r.exc) {
        excHtml = `<pre class="devlog-exc">${escapeHtml(r.exc)}</pre>`;
      }

      html += `<div class="devlog-row">
        <span class="devlog-ts">${escapeHtml(r.ts_iso || '')}</span>
        <span class="devlog-badge ${badgeClass}">${escapeHtml(r.level)}</span>
        <span class="devlog-meta" title="${escapeHtml(r.logger)} [${escapeHtml(loc)}]">${escapeHtml(r.logger)}</span>
        <span class="devlog-thread" title="${escapeHtml(r.thread)}">[${escapeHtml(r.thread)}]</span>
        <span class="devlog-msg">${escapeHtml(r.message)}${excHtml}</span>
      </div>`;
    });

    term.innerHTML = html;

    if (devLogAutoScroll) {
      term.scrollTop = term.scrollHeight;
    }
  }


  async function changeDaemonLogLevel(newLevel) {
    try {
      const res = await fetch('/api/dev/loglevel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level: newLevel, persist: true })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(`✅ Daemon log level successfully set: ${data.new_level}`);
        fetchDevLogs(true);
      } else {
        showToast(`❌ Error updating log level: ${data.message || 'Error'}`);
      }
    } catch (e) {
      showToast('Network error: ' + e);
    }
  }

  async function clearDevLogBuffer() {
    if (!confirm('Are you sure you want to clear the in-memory developer log buffer?')) return;
    try {
      const res = await fetch('/api/dev/logs/clear', { method: 'POST' });
      if (res.ok) {
        showToast('🗑️ Developer log buffer cleared.');
        fetchDevLogs(true);
      }
    } catch (e) {
      showToast('Error clearing log buffer: ' + e);
    }
  }

  async function triggerTotalLogPurge() {
    const confirmMsg = getTranslation('confirm_total_log_purge', localStorage.getItem('nmb_lang') || 'en', 'Are you sure you want to completely purge ALL system logs, kernel buffers, developer files, and audit records? This cannot be undone.');
    if (!confirm(confirmMsg)) return;

    showToast('Executing total log purge (journal, files, database, memory)...');
    try {
      const res = await fetch('/api/system/logs/purge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: 'PURGE', include_db: true, include_journal: true }),
      });
      const d = await res.json();
      if (res.ok && d.status === 'ok') {
        const doneMsg = getTranslation('msg_total_log_purge_done', localStorage.getItem('nmb_lang') || 'en', 'Total log purge completed successfully!');
        showToast(doneMsg);
        if (typeof fetchSystemSyslog === 'function') fetchSystemSyslog(true);
        if (typeof fetchDevLogs === 'function') fetchDevLogs(true);
        if (typeof refreshStatus === 'function') refreshStatus();
      } else {
        showToast('Log purge error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('Log purge request failed: ' + e);
    }
  }

  function downloadDevLog() {
    window.location.href = '/api/dev/logs/download';
  }

  // Sniffer Control
  async function toggleSniffer() {
    const btn = document.getElementById('btn-sniffer-toggle');
    const iface = document.getElementById('sniffer-iface-select').value;
    const action = snifferActive ? 'stop' : 'start';
    btn.disabled = true;
    try {
      const res = await fetch('/api/sniffer/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: action, iface: iface })
      });
      if (res.ok) {
        snifferActive = (action === 'start');
        btn.innerText = snifferActive ? t('sniffer_btn_stop', '⏹️ Stop Sniffing') : t('sniffer_btn_start', '▶️ Start Sniffing');
        btn.className = snifferActive ? 'btn-danger' : 'btn-primary';
        showToast(snifferActive ? t('sniffer_started', 'Packet capture started!') : t('sniffer_stopped', 'Packet capture stopped.'));
      }
    } catch (e) {
      showToast('Error: ' + e);
    } finally {
      btn.disabled = false;
      pollSnifferStats();
    }
  }

  async function pollSnifferStats() {
    const snifferTab = document.getElementById('tab-sniffer');
    if (!snifferTab || !snifferTab.classList.contains('active')) return;
    try {
      const res = await fetch('/api/sniffer/stats');
      if (!res.ok) return;
      const s = await res.json();
      snifferActive = s.running;

      document.getElementById('sniffer-total-packets').innerText = (s.total_packets || 0).toLocaleString();
      document.getElementById('sniffer-total-bytes').innerText = ((s.total_bytes || 0) / 1024.0).toFixed(1) + ' KB';
      document.getElementById('sniffer-pps').innerText = Math.round(s.pps || 0) + ' pps';
      document.getElementById('sniffer-drops').innerText = s.dropped_packets || 0;

      const fBody = document.getElementById('sniffer-flows-body');
      if (s.recent_packets && s.recent_packets.length > 0) {
        let fHtml = '';
        s.recent_packets.slice(-25).reverse().forEach(p => {
          const d = new Date(p.ts * 1000);
          const tStr = String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0') + ':' + String(d.getSeconds()).padStart(2,'0') + '.' + String(d.getMilliseconds()).padStart(3,'0');
          const safeSrc = escapeHtml(p.src_ip);
          const safeDst = escapeHtml(p.dst_ip);
          const safeProto = escapeHtml((p.proto || 'IP').toUpperCase());
          const safeInfo = escapeHtml(p.info || '');
          fHtml += `<tr>
            <td style="font-family:monospace; color:#94a3b8;">${tStr}</td>
            <td><code>${safeSrc}:${p.src_port || 0}</code></td>
            <td><code>${safeDst}:${p.dst_port || 0}</code></td>
            <td><span class="badge badge-warn">${safeProto}</span></td>
            <td>${p.length || 0} B</td>
            <td style="color:#94a3b8; font-size:11.5px;">${safeInfo}</td>
          </tr>`;
        });
        fBody.innerHTML = fHtml;
      }
    } catch (e) {}
  }

  function downloadPcap() {
    window.location.href = '/api/sniffer/pcap';
  }

  async function clearSniffer() {
    try {
      await fetch('/api/sniffer/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'clear' })
      });
      showToast(t('sniffer_cleared', 'Packet buffer cleared.'));
      pollSnifferStats();
    } catch (e) {}
  }

  // Network & MAC Management
  async function loadMacInfo() {
    try {
      const res = await fetch('/api/network/mac');
      if (!res.ok) return;
      const d = await res.json();
      document.getElementById('mac-current').innerText = d.current_mac || '--';
      document.getElementById('mac-factory').innerText = d.factory_mac || '--';
      if (!document.getElementById('input-wan-mac').value && d.current_mac) {
        document.getElementById('input-wan-mac').value = d.current_mac;
      }
    } catch (e) {}
  }

  async function applyMacAddress() {
    const val = document.getElementById('input-wan-mac').value.trim();
    if (!val) return;
    try {
      const res = await fetch('/api/network/mac', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'set', mac: val })
      });
      const d = await res.json();
      if (d.status === 'ok') {
        showToast(t('mac_updated', 'New WAN MAC address successfully applied: ') + d.current_mac);
        loadMacInfo();
      } else {
        showToast('Error configuring WAN MAC address.');
      }
    } catch (e) {
      showToast('Error: ' + e);
    }
  }

  async function resetMacAddress() {
    try {
      const res = await fetch('/api/network/mac', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'reset' })
      });
      const d = await res.json();
      if (d.status === 'ok') {
        showToast(t('mac_reset', 'WAN MAC restored to factory address: ') + d.current_mac);
        loadMacInfo();
      }
    } catch (e) {
      showToast('Error: ' + e);
    }
  }

  // DNS Management
  async function testDnsResolution() {
    const host = document.getElementById('dns-test-host').value.trim() || 'google.com';
    showToast('Testing DNS resolution: ' + host + '...');
    try {
      const res = await fetch('/api/network/dns/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host: host })
      });
      const d = await res.json();
      if (d.status === 'ok') {
        showToast(`DNS Successful (${d.rtt_ms} ms): ${d.ip}`);
      } else {
        showToast('DNS error: ' + (d.error || 'Timeout'));
      }
    } catch (e) {
      showToast('Error: ' + e);
    }
  }

  async function enforceDnsFallback() {
    showToast('Enforcing configured DNS fallbacks...');
    try {
      const res = await fetch('/api/network/dns/fallback', { method: 'POST' });
      const d = await res.json();
      showToast('DNS fallback active: ' + (d.servers || []).join(', '));
      document.getElementById('dns-active-servers').innerText = (d.servers || []).join(', ');
    } catch (e) {
      showToast('Error: ' + e);
    }
  }

  async function savePppoeSettings() {
    saveRouterSettings();
  }

  // Router Subtab Switching
  function switchRouterSubtab(subtabId) {
    document.querySelectorAll('.router-subtab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.router-subtab-btn').forEach(el => el.classList.remove('active'));
    const c = document.getElementById(subtabId);
    if (c) c.classList.add('active');
    const b = document.getElementById('btn-' + subtabId);
    if (b) {
      b.classList.add('active');
      const nav = b.closest('.router-subnav') || b.parentElement;
      if (nav && typeof nav.scrollTo === 'function') {
        const left = b.offsetLeft - nav.offsetLeft - 16;
        nav.scrollTo({ left: Math.max(0, left), behavior: 'smooth' });
      }
    }
    if (subtabId === 'rsub-guest') {
      loadGuestWifiStatus();
    }
    if (subtabId === 'rsub-ports') {
      loadInterfaceMatrix();
      loadDriverStatus();
    }
    if (subtabId === 'rsub-system') {
      loadSystemInfo();
      loadInvasiveLogPreview();
      checkAntiBanAndInterfaceStatus();
    }
    if (subtabId === 'rsub-kernel') {
      loadKernelStatus();
    }
    if (subtabId === 'rsub-backup') {
      loadBackupsList();
    }
    if (subtabId === 'rsub-heal') {
      loadHealStatus();
      checkStableUpdates();
    }
    if (subtabId === 'rsub-telegram') {
      loadTelegramStatus();
    }
  }

  // WAN Protocol change handler (DHCP, PPPoE, Static)
  function onWanProtoChange(val) {
    const pppoeCard = document.getElementById('wan-pppoe-card');
    if (pppoeCard) pppoeCard.style.display = (val === 'pppoe') ? 'block' : 'none';
    const staticCard = document.getElementById('wan-static-card');
    if (staticCard) staticCard.style.display = (val === 'static') ? 'block' : 'none';
  }

  // =========================================================================
  // Wi-Fi IEEE 802.11 Multi-Band (2.4 - 6 GHz) & Hardware Capabilities Engine
  // =========================================================================
  window._wifiCaps = null;

  async function fetchWifiCapabilities() {
    try {
      const res = await fetch('/api/network/wifi/capabilities');
      if (!res.ok) return;
      const data = await res.json();
      window._wifiCaps = data;
      const bSel = document.getElementById('cfg-wifi-band');
      const cSel = document.getElementById('cfg-wifi-channel');
      const curCh = cSel ? cSel.value : null;
      updateWifiChannelOptions(bSel ? bSel.value : 'auto', curCh);
      renderWifiCapabilities(data, data.current_status || {});
    } catch (e) {
      console.debug('Wi-Fi capabilities fetch error:', e);
    }
  }

  function renderWifiCapabilities(caps, liveStatus) {
    if (!caps) return;
    window._wifiCaps = caps;

    // 1. Hardware Info & AP Mode Badge
    const hwBadge = document.getElementById('wifi-hw-badge');
    if (hwBadge) {
      const iface = caps.interface || 'wlan0';
      const phy = caps.phy_name || 'phy0';
      const drv = caps.driver || 'unknown';
      const apOk = caps.ap_mode_supported !== false;
      hwBadge.innerHTML = `<span>${t('device_interface', 'Interface')}: <b>${escapeHtml(iface)}</b> (${escapeHtml(phy)}) | Driver: <b>${escapeHtml(drv)}</b> | AP Mode: ${apOk ? '✅ ' + t('wifi_supported', 'Supported') : '⚠️ ' + t('wifi_limited', 'Limited')}</span>`;
      hwBadge.style.color = apOk ? '#38bdf8' : '#f59e0b';
      hwBadge.style.borderColor = apOk ? 'rgba(56, 189, 248, 0.4)' : 'rgba(245, 158, 11, 0.4)';
      hwBadge.style.background = apOk ? 'rgba(56, 189, 248, 0.1)' : 'rgba(245, 158, 11, 0.1)';
    }

    // 2. Frequency Bands Badges (2.4 GHz, 5 GHz, 6 GHz)
    const bandsContainer = document.getElementById('wifi-caps-bands');
    if (bandsContainer && caps.supported_bands) {
      const bands = [
        { id: '2.4ghz', label: '2.4 GHz' },
        { id: '5ghz', label: '5 GHz' },
        { id: '6ghz', label: '6 GHz (Wi-Fi 6E/7)' }
      ];
      bandsContainer.innerHTML = bands.map(b => {
        const supported = caps.supported_bands.includes(b.id);
        const style = supported
          ? 'background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);'
          : 'background: rgba(148, 163, 184, 0.1); color: #64748b; border: 1px solid rgba(148, 163, 184, 0.2);';
        const prefix = supported ? '✓ ' : '✗ ';
        const suffix = supported ? '' : ' (' + t('not_supported', 'Not supported') + ')';
        return `<span class="badge" style="${style}">${prefix}${escapeHtml(b.label)}${suffix}</span>`;
      }).join('');
    }

    // 3. Standards Badges (b, g, a, n, ac, ax, be)
    const stdsContainer = document.getElementById('wifi-caps-standards');
    if (stdsContainer && caps.supported_standards) {
      const stdList = [
        { id: 'b', label: '802.11b' },
        { id: 'g', label: '802.11g' },
        { id: 'a', label: '802.11a' },
        { id: 'n', label: '802.11n (Wi-Fi 4)' },
        { id: 'ac', label: '802.11ac (Wi-Fi 5)' },
        { id: 'ax', label: '802.11ax (Wi-Fi 6/6E)' },
        { id: 'be', label: '802.11be (Wi-Fi 7)' }
      ];
      stdsContainer.innerHTML = stdList.map(s => {
        const supported = caps.supported_standards.includes(s.id);
        const style = supported
          ? 'background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); font-weight: 600;'
          : 'background: rgba(148, 163, 184, 0.1); color: #64748b; border: 1px solid rgba(148, 163, 184, 0.2);';
        const prefix = supported ? '✓ ' : '✗ ';
        return `<span class="badge" style="${style}">${prefix}${escapeHtml(s.label)}</span>`;
      }).join('');
    }

    // 4. Widths and Features
    const featContainer = document.getElementById('wifi-caps-features');
    if (featContainer) {
      const widths = [20, 40, 80, 160, 320];
      const supWidths = caps.supported_widths || ['20', '40'];
      let html = widths.map(w => {
        const supported = supWidths.includes(w) || supWidths.includes(String(w));
        const style = supported
          ? 'background: rgba(139, 92, 246, 0.2); color: #a78bfa; border: 1px solid rgba(139, 92, 246, 0.4);'
          : 'background: rgba(148, 163, 184, 0.1); color: #64748b; border: 1px solid rgba(148, 163, 184, 0.2);';
        return `<span class="badge" style="${style}">${supported ? '✓ ' : '✗ '}${escapeHtml(w)} MHz</span>`;
      }).join('');
      if (caps.wpa3_supported) {
        html += `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);">✓ WPA3-SAE & PMF</span>`;
      }
      featContainer.innerHTML = html;
    }

    // 5. Live Telemetry
    if (liveStatus) {
      const fEl = document.getElementById('wifi-live-freq');
      if (fEl) fEl.innerText = liveStatus.frequency_mhz ? `${liveStatus.frequency_mhz} MHz` : (liveStatus.channel ? `Ch ${liveStatus.channel}` : t('inactive', 'Inactive'));
      const cEl = document.getElementById('wifi-live-channel');
      if (cEl) cEl.innerText = liveStatus.channel ? `${t('wifi_channel_prefix', 'Csatorna')} ${liveStatus.channel}` : '--';
      const wEl = document.getElementById('wifi-live-width');
      if (wEl) wEl.innerText = liveStatus.channel_width_mhz ? `${liveStatus.channel_width_mhz} MHz` : '--';
      const txEl = document.getElementById('wifi-live-txpower');
      if (txEl) txEl.innerText = (liveStatus.txpower_dbm !== undefined && liveStatus.txpower_dbm > 0) ? `${liveStatus.txpower_dbm.toFixed(1)} dBm` : '--';
      const stEl = document.getElementById('wifi-live-clients');
      if (stEl) stEl.innerText = `${liveStatus.connected_stations || 0} ${t('clients_count', 'clients')}`;
    }

    // 6. Dynamic Form Dropdown Constraints based on Hardware Support
    const stripNotSupported = (s) => (s || '').replace(/\s*\((?:Hardveresen nem támogatott|Hardver nem támogatja|Nem támogatott|Hardware not supported|Not supported|Nicht unterstützt|Non supporté|Не підтримується)\)/gi, '').trim();
    const notSupSuffix = ' (' + t('not_supported', 'Not supported') + ')';

    const bandSel = document.getElementById('cfg-wifi-band');
    if (bandSel && caps.supported_bands) {
      for (let opt of bandSel.options) {
        if (opt.value === 'auto') continue;
        const sup = caps.supported_bands.includes(opt.value);
        opt.disabled = !sup;
        const cleanText = stripNotSupported(opt.text);
        opt.text = sup ? cleanText : cleanText + notSupSuffix;
      }
    }

    const stdSel = document.getElementById('cfg-wifi-standard');
    if (stdSel && caps.supported_standards) {
      for (let opt of stdSel.options) {
        if (opt.value === 'auto') continue;
        const sup = caps.supported_standards.includes(opt.value);
        opt.disabled = !sup;
        const cleanText = stripNotSupported(opt.text);
        opt.text = sup ? cleanText : cleanText + notSupSuffix;
      }
    }

    const widthSel = document.getElementById('cfg-wifi-channel-width');
    if (widthSel && caps.supported_widths) {
      for (let opt of widthSel.options) {
        if (opt.value === 'auto') continue;
        const wVal = parseInt(opt.value);
        const sup = caps.supported_widths.includes(wVal) || caps.supported_widths.includes(String(wVal));
        opt.disabled = !sup;
        const cleanText = stripNotSupported(opt.text);
        opt.text = sup ? cleanText : cleanText + notSupSuffix;
      }
    }

    const secSel = document.getElementById('cfg-wifi-security');
    if (secSel) {
      for (let opt of secSel.options) {
        if (opt.value === 'wpa3' || opt.value === 'mixed') {
          const sup = !!caps.wpa3_supported;
          opt.disabled = !sup;
          const cleanText = stripNotSupported(opt.text);
          opt.text = sup ? cleanText : cleanText + notSupSuffix;
        }
      }
    }
  }

  function updateWifiChannelOptions(band, selectedChannel) {
    const chSel = document.getElementById('cfg-wifi-channel');
    if (!chSel) return;
    const currentVal = (selectedChannel !== undefined && selectedChannel !== null) ? parseInt(selectedChannel) : parseInt(chSel.value || 0);

    const chPrefix = t('wifi_channel_prefix', 'Csatorna');
    const autoLabel = t('wifi_channel_auto', 'Auto (automatic channel selection / ACS)');
    const recTag = t('wifi_channel_non_overlapping', ' (Non-overlapping - Recommended)');
    const notSupSuffix = ' (' + t('not_supported', 'Not supported') + ')';
    const caps = window._wifiCaps;

    let html = `<option value="0">${autoLabel}</option>`;

    if (band === '5ghz') {
      const sup5 = (caps && caps.channels && caps.channels['5ghz']) ? caps.channels['5ghz'] : null;
      const ch5 = [
        { ch: 36, mhz: 5180, desc: 'UNII-1 (Indoor)' },
        { ch: 40, mhz: 5200, desc: 'UNII-1' },
        { ch: 44, mhz: 5220, desc: 'UNII-1' },
        { ch: 48, mhz: 5240, desc: 'UNII-1' },
        { ch: 52, mhz: 5260, desc: 'DFS UNII-2A' },
        { ch: 56, mhz: 5280, desc: 'DFS UNII-2A' },
        { ch: 60, mhz: 5300, desc: 'DFS UNII-2A' },
        { ch: 64, mhz: 5320, desc: 'DFS UNII-2A' },
        { ch: 100, mhz: 5500, desc: 'DFS UNII-2C' },
        { ch: 104, mhz: 5520, desc: 'DFS UNII-2C' },
        { ch: 108, mhz: 5540, desc: 'DFS UNII-2C' },
        { ch: 112, mhz: 5560, desc: 'DFS UNII-2C' },
        { ch: 116, mhz: 5580, desc: 'DFS UNII-2C' },
        { ch: 120, mhz: 5600, desc: 'DFS UNII-2C (Weather Radar)' },
        { ch: 124, mhz: 5620, desc: 'DFS UNII-2C (Weather Radar)' },
        { ch: 128, mhz: 5640, desc: 'DFS UNII-2C (Weather Radar)' },
        { ch: 132, mhz: 5660, desc: 'DFS UNII-2C' },
        { ch: 136, mhz: 5680, desc: 'DFS UNII-2C' },
        { ch: 140, mhz: 5700, desc: 'DFS UNII-2C' },
        { ch: 149, mhz: 5745, desc: 'UNII-3' },
        { ch: 153, mhz: 5765, desc: 'UNII-3' },
        { ch: 157, mhz: 5785, desc: 'UNII-3' },
        { ch: 161, mhz: 5805, desc: 'UNII-3' },
      ];
      ch5.forEach(item => {
        const isSup = !sup5 || sup5.includes(item.ch);
        const dis = isSup ? '' : ' disabled';
        const suff = isSup ? '' : notSupSuffix;
        html += `<option value="${escapeHtml(item.ch)}"${dis}>${chPrefix} ${escapeHtml(item.ch)} (${escapeHtml(item.mhz)} MHz) - ${escapeHtml(item.desc)}${suff}</option>`;
      });
    } else if (band === '6ghz') {
      const sup6 = (caps && caps.channels && caps.channels['6ghz']) ? caps.channels['6ghz'] : null;
      const ch6 = [
        1, 5, 9, 13, 17, 21, 33, 37, 41, 45, 49, 65, 69, 73, 77, 81,
        97, 101, 105, 109, 113, 129, 133, 137, 141, 145, 161, 165, 169, 173, 177,
        193, 197, 201, 205, 209, 225, 229, 233
      ];
      ch6.forEach(ch => {
        const freq = 5950 + ch * 5;
        const isSup = sup6 && sup6.includes(ch);
        const dis = isSup ? '' : ' disabled';
        const suff = isSup ? '' : notSupSuffix;
        html += `<option value="${ch}"${dis}>${chPrefix} ${ch} (${freq} MHz) [6 GHz PSC]${suff}</option>`;
      });
    } else {
      // 2.4 GHz
      const sup24 = (caps && caps.channels && caps.channels['2.4ghz']) ? caps.channels['2.4ghz'] : null;
      for (let ch = 1; ch <= 13; ch++) {
        const freq = 2407 + ch * 5;
        const tag = (ch === 1 || ch === 6 || ch === 11) ? recTag : '';
        const isSup = !sup24 || sup24.includes(ch);
        const dis = isSup ? '' : ' disabled';
        const suff = isSup ? '' : notSupSuffix;
        html += `<option value="${ch}"${dis}>${chPrefix} ${ch} (${freq} MHz)${tag}${suff}</option>`;
      }
    }

    chSel.innerHTML = html;
    chSel.value = String(currentVal);
    if (chSel.value !== String(currentVal)) {
      chSel.value = '0';
    }
  }

  function onWifiBandChange(userTriggered = true) {
    const bandSel = document.getElementById('cfg-wifi-band');
    const noticeEl = document.getElementById('wifi-6ghz-notice');
    const secSel = document.getElementById('cfg-wifi-security');
    const stdSel = document.getElementById('cfg-wifi-standard');
    if (!bandSel) return;
    const band = bandSel.value;

    if (noticeEl) {
      noticeEl.style.display = (band === '6ghz') ? 'block' : 'none';
    }

    if (band === '6ghz') {
      if (secSel) {
        secSel.value = 'wpa3';
        const wpa2Opt = secSel.querySelector('option[value="wpa2"]');
        if (wpa2Opt) wpa2Opt.disabled = true;
      }
      if (stdSel && userTriggered) {
        if (stdSel.value !== 'ax' && stdSel.value !== 'be') {
          stdSel.value = 'auto';
        }
      }
    } else {
      if (secSel) {
        const wpa2Opt = secSel.querySelector('option[value="wpa2"]');
        if (wpa2Opt) wpa2Opt.disabled = false;
      }
    }

    updateWifiChannelOptions(band);
  }

  function onWifiStandardChange() {
    const stdSel = document.getElementById('cfg-wifi-standard');
    const bandSel = document.getElementById('cfg-wifi-band');
    if (!stdSel || !bandSel) return;
    const std = stdSel.value;
    if (std === 'ac' || std === 'a') {
      if (bandSel.value === '2.4ghz') {
        showToast('Notice: 802.11ac / 802.11a standards require the 5 GHz frequency band.');
        bandSel.value = '5ghz';
        onWifiBandChange();
      }
    }
  }

  function onWifiSecurityChange() {
    const secSel = document.getElementById('cfg-wifi-security');
    const bandSel = document.getElementById('cfg-wifi-band');
    if (bandSel && bandSel.value === '6ghz' && secSel && secSel.value === 'wpa2') {
      showToast('IEEE 802.11 Requirement: The 6 GHz band strictly requires WPA3-Personal (SAE) authentication!');
      secSel.value = 'wpa3';
    }
  }

  // Dashboard Server Selection and Copy
  function onHomeServerSelect(val) {
    const wrap = document.getElementById('home-custom-server-wrap');
    if (val === 'custom') {
      if (wrap) wrap.style.display = 'flex';
      return;
    }
    if (wrap) wrap.style.display = 'none';
    if (val === 'auto') {
      setDefaultServer(null, t('target_server_auto', 'Automatic Closest Server (Auto)'), '');
    } else {
      const selectEl = document.getElementById('home-target-server-select');
      const text = selectEl.options[selectEl.selectedIndex].text;
      setDefaultServer(parseInt(val), text, '');
    }
  }

  function applyHomeCustomServer() {
    const input = document.getElementById('home-custom-server-id');
    const val = (input.value || '').trim();
    if (!val || !val.match(/^\d+$/)) {
      showToast(t('err_server_id', 'Please enter a numeric Ookla server ID.'));
      return;
    }
    const sid = parseInt(val);
    setDefaultServer(sid, t('custom_server', 'Custom Server') + ' #' + sid, '');
  }

  function copyScriptToClipboard() {
    const el = document.getElementById('home-script-box');
    const text = el ? el.textContent : '';
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        showToast(t('cmd_copied', 'Command copied to clipboard!'));
      }).catch(() => {
        showToast(t('cmd_copied', 'Command copied to clipboard!'));
      });
    } else {
      showToast('Clipboard unavailable.');
    }
  }

  // Tab 10 Schedule Controls
  let schedFormDirty = false;

  function markSchedDirty() {
    schedFormDirty = true;
    const banner = document.getElementById('sched-feedback-banner');
    if (banner) {
      banner.innerHTML = `<span style="color:#fbbf24; font-weight:600;">${t('sched_unsaved_warning', '⚠️ Unsaved changes — click «Save Scheduling Settings» to apply!')}</span>`;
    }
  }

  function isScheduleInputActive() {
    const active = document.activeElement;
    if (!active) return false;
    const schedIds = [
      'sched-interval-select',
      'sched-custom-cron-input',
      'radio-mode-manual',
      'radio-mode-scheduled',
      'sched-engine-select',
      'sched-int-ookla',
      'sched-int-rtr',
      'sched-int-cloudflare',
      'sched-int-fastcom',
      'sched-int-iperf3',
      'sched-server-id-input',
      'sched-gate-mode',
      'sched-gate-percent',
      'sched-gate-kbps',
      'home-interval-select'
    ];
    return schedIds.includes(active.id);
  }

  function resetScheduleForm() {
    schedFormDirty = false;
    const banner = document.getElementById('sched-feedback-banner');
    if (banner) {
      banner.innerHTML = `<span style="color:#94a3b8;">${t('sched_reverted', 'Settings restored from server.')}</span>`;
    }
    refreshStatus();
    showToast(t('sched_reverted', 'Settings restored from server.'));
  }

  function onSchedModeRadioChange(mode) {
    const lblMan = document.getElementById('lbl-mode-manual');
    const lblSched = document.getElementById('lbl-mode-scheduled');
    const intervalBox = document.getElementById('sched-interval-container');
    if (mode === 'manual') {
      if (lblMan) { lblMan.style.borderColor = '#f87171'; lblMan.style.background = 'rgba(239, 68, 68, 0.1)'; }
      if (lblSched) { lblSched.style.borderColor = '#334155'; lblSched.style.background = '#0f172a'; }
      if (intervalBox) intervalBox.style.opacity = '0.45';
    } else {
      if (lblSched) { lblSched.style.borderColor = '#0284c7'; lblSched.style.background = 'rgba(2, 132, 199, 0.1)'; }
      if (lblMan) { lblMan.style.borderColor = '#334155'; lblMan.style.background = '#0f172a'; }
      if (intervalBox) intervalBox.style.opacity = '1.0';
    }
  }

  async function quickResolveServerId() {
    const input = document.getElementById('sched-server-id-input');
    const nameEl = document.getElementById('sched-server-resolved-name');
    markSchedDirty();
    const val = (input.value || '').trim();
    if (!val) {
      nameEl.innerText = t('target_server_auto', 'Auto (No custom server selected)');
      return;
    }
    nameEl.innerText = t('searching_servers', 'Searching speedtest benchmark network...');
    try {
      const res = await fetch('/api/speedtest/servers?q=' + encodeURIComponent(val));
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const srv = (data.servers || []).find(s => String(s.id) === val) || (data.servers || [])[0];
      if (srv) {
        nameEl.innerHTML = `✅ <b>${escapeHtml(srv.sponsor || srv.name)}</b> <code style="color:#94a3b8;">(${escapeHtml(srv.location || srv.host || '')})</code>`;
      } else {
        nameEl.innerHTML = `⚠️ Server #${val} (engine will attempt target during test)`;
      }
    } catch (e) {
      nameEl.innerText = t('server_prefix', 'Server') + ' #' + val;
    }
  }

  function clearSchedServer() {
    document.getElementById('sched-server-id-input').value = '';
    document.getElementById('sched-server-resolved-name').innerText = t('target_server_auto', 'Automatic Closest Server (Auto)');
    markSchedDirty();
  }

  let globalContractDownMbps = 1000.0;

  let globalTrafficStop = false;

  async function saveDailyDataLimit(value) {
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ daily_data_limit_mb: Number(value) || 0 })
      });
      if (!res.ok) throw new Error(res.status);
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  async function toggleTrafficStop(enabled) {
    try {
      const res = await fetch('/api/speedtest/traffic-stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: enabled })
      });
      if (!res.ok) throw new Error(res.status);
      globalTrafficStop = enabled;
      updateGateCalculatedBadge();
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  function updateGateCalculatedBadge() {
    const badge = document.getElementById('sched-gate-badge');
    const pctInput = document.getElementById('sched-gate-percent');
    if (!badge) return;
    const pct = pctInput ? parseFloat(pctInput.value) || 2.0 : 2.0;
    const capMbps = globalContractDownMbps || 1000.0;
    const limitMbps = (globalTrafficStop ? Math.max(0.2, Math.min(0.5, capMbps * (pct / 100.0))) : capMbps * (pct / 100.0)).toFixed(1);
    badge.innerText = `Gate: max ${limitMbps} Mbps (${capMbps} Mbps link - < ${pct.toFixed(1)}%)`;
  }

  function onSchedIntervalChange(val) {
    const customWrap = document.getElementById('sched-custom-cron-wrap');
    if (customWrap) {
      customWrap.style.display = (val === 'custom') ? 'block' : 'none';
      if (val === 'custom') {
        const inp = document.getElementById('sched-custom-cron-input');
        if (inp && !inp.value) inp.value = '15';
      }
    }
  }

  function onCfgSchedCronChange(val) {
    const customWrap = document.getElementById('cfg-sched-custom-cron-wrap');
    if (customWrap) {
      customWrap.style.display = (val === 'custom') ? 'block' : 'none';
      if (val === 'custom') {
        const inp = document.getElementById('cfg-sched-custom-cron-input');
        if (inp && !inp.value) inp.value = '15';
      }
    }
  }

  function onSchedGateModeChange(val) {
    const pWrap = document.getElementById('sched-gate-percent-wrap');
    const fWrap = document.getElementById('sched-gate-fixed-wrap');
    if (pWrap) pWrap.style.display = (val === 'percent') ? 'block' : 'none';
    if (fWrap) fWrap.style.display = (val === 'fixed') ? 'block' : 'none';
    updateGateCalculatedBadge();
  }

  function onCfgGateModeChange(val) {
    const pWrap = document.getElementById('cfg-gate-percent-wrap');
    const fWrap = document.getElementById('cfg-gate-fixed-wrap');
    if (pWrap) pWrap.style.display = (val === 'percent') ? 'block' : 'none';
    if (fWrap) fWrap.style.display = (val === 'fixed') ? 'block' : 'none';
  }

  const UA_PRESETS_MAP = {
    headless_chrome_linux: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/133.0.6943.126 Safari/537.36",
    headless_chrome_arm: "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/133.0.6943.126 Safari/537.36",
    chrome_windows: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.126 Safari/537.36",
    chrome_linux: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.126 Safari/537.36",
    chrome_mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.126 Safari/537.36",
    firefox_linux: "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0",
    firefox_windows: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    safari_mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
    chrome_android: "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.126 Mobile Safari/537.36",
    nmb_native: "NetworkMeasureBox/2.5 (Linux; Headless Diagnostics Client)"
  };

  function onCfgUaModeChange(mode) {
    const uaInp = document.getElementById('cfg-user-agent');
    const hint = document.getElementById('cfg-ua-mode-hint');
    const activeDisp = document.getElementById('cfg-ua-active-display');
    if (!uaInp) return;

    if (mode === 'auto_fresh') {
      if (hint) hint.textContent = t('ua_hint_auto_fresh', 'Auto-Fresh mode automatically generates a realistic, modern Headless Chrome identifier on each measurement.');
      if (activeDisp && (!activeDisp.textContent || activeDisp.textContent === 'Betöltés...' || activeDisp.textContent === 'Loading...')) {
        activeDisp.textContent = UA_PRESETS_MAP.headless_chrome_linux;
      }
    } else if (mode === 'custom') {
      if (hint) hint.textContent = t('ua_hint_custom', 'Custom User-Agent: Exact string entered below will be sent on all outbound HTTP probes.');
      if (uaInp.value && activeDisp) activeDisp.textContent = uaInp.value;
    } else if (UA_PRESETS_MAP[mode]) {
      uaInp.value = UA_PRESETS_MAP[mode];
      if (hint) hint.textContent = t('ua_hint_preset', 'Selected standard preset profile:') + ' ' + mode;
      if (activeDisp) activeDisp.textContent = UA_PRESETS_MAP[mode];
    }
  }

  async function generateFreshUa(category) {
    try {
      const resp = await fetch('/api/user-agent/fresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category: category || 'headless' })
      });
      if (resp.ok) {
        const d = await resp.json();
        const uaInp = document.getElementById('cfg-user-agent');
        const modeSel = document.getElementById('cfg-ua-mode');
        const activeDisp = document.getElementById('cfg-ua-active-display');
        if (uaInp && d.user_agent) {
          uaInp.value = d.user_agent;
          if (modeSel) modeSel.value = 'custom';
          if (activeDisp) activeDisp.textContent = d.user_agent;
          onCfgUaModeChange('custom');
          showToast(t('ua_toast_generated', '🎲 Fresh User-Agent generated! Save settings to apply.'));
        }
      }
    } catch (e) {
      console.error('generateFreshUa error:', e);
      const patch = Math.floor(Math.random() * 80) + 60;
      const fallbackUa = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/133.0.6943.' + patch + ' Safari/537.36';
      const uaInp = document.getElementById('cfg-user-agent');
      if (uaInp) {
        uaInp.value = fallbackUa;
        const modeSel = document.getElementById('cfg-ua-mode');
        if (modeSel) modeSel.value = 'custom';
        const activeDisp = document.getElementById('cfg-ua-active-display');
        if (activeDisp) activeDisp.textContent = fallbackUa;
        showToast(t('ua_toast_set', '🎲 Fresh User-Agent applied!'));
      }
    }
  }

  function copyActiveUa() {
    const el = document.getElementById('cfg-ua-active-display');
    if (el && el.textContent) {
      navigator.clipboard.writeText(el.textContent.trim());
      showToast(t('ua_toast_copied', '📋 User-Agent copied to clipboard!'));
    }
  }

  function copyInputUa() {
    const el = document.getElementById('cfg-user-agent');
    if (el && el.value) {
      navigator.clipboard.writeText(el.value.trim());
      showToast(t('ua_toast_copied', '📋 User-Agent copied to clipboard!'));
    }
  }

  function resetUaToDefault() {
    const modeSel = document.getElementById('cfg-ua-mode');
    const uaInp = document.getElementById('cfg-user-agent');
    if (modeSel) modeSel.value = 'auto_fresh';
    if (uaInp) uaInp.value = '';
    onCfgUaModeChange('auto_fresh');
    showToast(t('ua_toast_reset', '🔄 Reset to dynamic Auto-Fresh mode.'));
  }

  async function saveScheduleSettings() {
    const modeRadio = document.querySelector('input[name="sched_mode_radio"]:checked');
    const mode = modeRadio ? modeRadio.value : 'scheduled';
    const intervalSelect = document.getElementById('sched-interval-select').value;
    let cron = intervalSelect;
    if (intervalSelect === 'custom') {
      const customInp = document.getElementById('sched-custom-cron-input');
      cron = (customInp && customInp.value ? customInp.value : '').trim() || '*/15 * * * *';
    }
    const engine = document.getElementById('sched-engine-select').value;
    const srvIdInput = document.getElementById('sched-server-id-input');
    const rawSrvId = (srvIdInput.value || '').trim();
    const serverId = rawSrvId && rawSrvId.match(/^\d+$/) ? parseInt(rawSrvId) : null;
    const gateMode = document.getElementById('sched-gate-mode') ? document.getElementById('sched-gate-mode').value : 'percent';
    const gatePercent = document.getElementById('sched-gate-percent') ? parseFloat(document.getElementById('sched-gate-percent').value) || 2.0 : 2.0;
    const gateKbps = document.getElementById('sched-gate-kbps') ? parseInt(document.getElementById('sched-gate-kbps').value) || 500 : 500;

    showToast(t('toast_saving', 'Applying settings, please wait...'));
    try {
      const res = await fetch('/api/speedtest/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          schedule_mode: mode,
          schedule_cron: cron,
          automated_engine: engine,
          server_id: serverId,
          idle_threshold_mode: gateMode,
          idle_threshold_percent: gatePercent,
          idle_threshold_kbps: gateKbps,
          ookla_interval_min: Math.max(60, parseInt((document.getElementById('sched-int-ookla') || {}).value || '60', 10) || 60),
          rtr_interval_min: Math.max(0, parseInt((document.getElementById('sched-int-rtr') || {}).value || '0', 10) || 0),
          cloudflare_interval_min: Math.max(0, parseInt((document.getElementById('sched-int-cloudflare') || {}).value || '0', 10) || 0),
          fastcom_interval_min: Math.max(0, parseInt((document.getElementById('sched-int-fastcom') || {}).value || '0', 10) || 0),
          iperf3_interval_min: Math.max(0, parseInt((document.getElementById('sched-int-iperf3') || {}).value || '0', 10) || 0),
          mixed_engines: Array.from(document.querySelectorAll('.sched-mix')).filter(cb => cb.checked).map(cb => cb.dataset.engine),
          iperf_target_host: (document.getElementById('sched-iperf-host') ? document.getElementById('sched-iperf-host').value : '').trim(),
          iperf_port: (document.getElementById('sched-iperf-port') ? parseInt(document.getElementById('sched-iperf-port').value) : 5201) || 5201
        })
      });
      if (res.ok) {
        schedFormDirty = false;
        window.currentAutomatedEngine = engine;
        selectEngine(engine, true);
        const banner = document.getElementById('sched-feedback-banner');
        if (banner) {
          banner.innerHTML = `<span style="color:#34d399; font-weight:600;">${t('sched_saved', '✅ Automated schedule and Traffic Gate (< 2%) successfully saved!')}</span>`;
        }
        showToast(t('sched_saved', '✅ Automated schedule and Traffic Gate (< 2%) successfully saved!'));
        try {
          const saved = await res.clone().json();
          renderOoklaWarning(saved.ookla_warning);
          if (saved.ookla_warning && saved.ookla_warning.code === 'ookla_rate_limit_risk') showToast('⚠️ ' + ooklaWarningText(saved.ookla_warning));
        } catch (e) { /* refreshStatus shows the warning again */ }
        refreshStatus();
      } else {
        const err = await res.json();
        showToast('Error: ' + (err.message || 'Failed to save settings'));
      }
    } catch (e) {
      showToast('Network error: ' + e);
    }
  }

  async function onHomeIntervalSelect(val) {
    if (val === 'manual') {
      await saveQuickSchedule('manual', '0 * * * *');
    } else {
      await saveQuickSchedule('scheduled', val);
    }
  }

  async function saveQuickSchedule(mode, cron) {
    showToast(t('toast_saving', 'Applying settings, please wait...'));
    try {
      const res = await fetch('/api/speedtest/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          schedule_mode: mode,
          schedule_cron: cron
        })
      });
      if (res.ok) {
        showToast(t('sched_saved', '✅ Automated schedule and Traffic Gate (< 2%) successfully saved!'));
        refreshStatus();
      } else {
        const err = await res.json();
        showToast('Error: ' + (err.message || 'Failed to save settings'));
      }
    } catch (e) {
      showToast('Network error: ' + e);
    }
  }

  // Load configuration from API into router tab inputs
  async function loadConfig() {
    try {
      const res = await fetch('/api/config');
      if (!res.ok) return;
      const d = await res.json();

      const publicResults = document.getElementById('cfg-public-results');
      if (publicResults) publicResults.checked = !!d.public_results;

      // WAN
      if (document.getElementById('cfg-wan-proto')) document.getElementById('cfg-wan-proto').value = d.wan_proto || 'dhcp';
      if (document.getElementById('cfg-wan-ip')) document.getElementById('cfg-wan-ip').value = d.wan_ip || '';
      if (document.getElementById('cfg-wan-netmask')) document.getElementById('cfg-wan-netmask').value = d.wan_netmask || '255.255.255.0';
      if (document.getElementById('cfg-wan-gateway')) document.getElementById('cfg-wan-gateway').value = d.wan_gateway || '';
      onWanProtoChange(d.wan_proto || 'dhcp');

      if (document.getElementById('cfg-pppoe-user')) document.getElementById('cfg-pppoe-user').value = d.pppoe_user || '';
      if (document.getElementById('cfg-pppoe-vlan')) document.getElementById('cfg-pppoe-vlan').value = d.pppoe_vlan || 0;
      if (document.getElementById('cfg-pppoe-service')) document.getElementById('cfg-pppoe-service').value = d.pppoe_service_name || '';

      if (document.getElementById('cfg-dns-mode')) document.getElementById('cfg-dns-mode').value = d.dns_mode || 'auto';
      if (document.getElementById('cfg-dns-primary')) document.getElementById('cfg-dns-primary').value = d.dns_primary || '1.1.1.1';
      if (document.getElementById('cfg-dns-secondary')) document.getElementById('cfg-dns-secondary').value = d.dns_secondary || '8.8.8.8';

      // LAN
      if (document.getElementById('cfg-lan-ip')) document.getElementById('cfg-lan-ip').value = d.gateway_ip || '192.168.100.1';
      if (document.getElementById('cfg-lan-netmask')) document.getElementById('cfg-lan-netmask').value = d.gateway_netmask || '255.255.255.0';
      if (document.getElementById('cfg-dhcp-enabled')) document.getElementById('cfg-dhcp-enabled').value = (d.dhcp_enabled !== false) ? 'true' : 'false';
      if (document.getElementById('cfg-dhcp-start')) document.getElementById('cfg-dhcp-start').value = d.dhcp_range_start || '192.168.100.100';
      if (document.getElementById('cfg-dhcp-end')) document.getElementById('cfg-dhcp-end').value = d.dhcp_range_end || '192.168.100.200';
      if (document.getElementById('cfg-dhcp-lease')) document.getElementById('cfg-dhcp-lease').value = d.dhcp_lease_time || '12h';

      // Wi-Fi
      if (document.getElementById('cfg-wifi-enabled')) document.getElementById('cfg-wifi-enabled').value = (d.wifi_enabled !== false) ? 'true' : 'false';
      if (document.getElementById('cfg-wifi-ssid')) document.getElementById('cfg-wifi-ssid').value = d.wifi_ssid || 'NMB-Diagnostic';
      const pskEl = document.getElementById('cfg-wifi-psk');
      if (pskEl) {
        pskEl.value = '';
        pskEl.placeholder = d.wifi_psk_set
          ? t('wifi_psk_set', 'Set. Leave empty to keep it.')
          : t('wifi_psk_unset', 'Not set: the access point stays off until you set a password (8-63 characters).');
      }
      if (document.getElementById('cfg-wifi-country')) document.getElementById('cfg-wifi-country').value = d.wifi_country_code || 'auto';
      if (document.getElementById('cfg-wifi-band')) document.getElementById('cfg-wifi-band').value = d.wifi_band || 'auto';
      if (document.getElementById('cfg-wifi-standard')) document.getElementById('cfg-wifi-standard').value = d.wifi_standard || 'auto';
      if (document.getElementById('cfg-wifi-channel-width')) document.getElementById('cfg-wifi-channel-width').value = d.wifi_channel_width || 'auto';
      if (document.getElementById('cfg-wifi-security')) document.getElementById('cfg-wifi-security').value = d.wifi_security || 'wpa2';
      updateWifiChannelOptions(d.wifi_band || 'auto', d.wifi_channel || 0);
      onWifiBandChange(false);

      // Dedicated Guest Wi-Fi Receiver
      if (document.getElementById('cfg-guest-wifi-enabled')) document.getElementById('cfg-guest-wifi-enabled').value = (d.guest_wifi_enabled ? 'true' : 'false');
      if (document.getElementById('cfg-guest-wifi-iface')) document.getElementById('cfg-guest-wifi-iface').value = d.guest_wifi_interface || 'wlan0';
      if (document.getElementById('cfg-guest-wifi-ssid')) document.getElementById('cfg-guest-wifi-ssid').value = d.guest_wifi_ssid || '';
      if (document.getElementById('cfg-guest-wifi-metric')) document.getElementById('cfg-guest-wifi-metric').value = d.guest_wifi_metric || 600;
      if (document.getElementById('cfg-guest-wifi-autorecon')) document.getElementById('cfg-guest-wifi-autorecon').value = (d.guest_wifi_auto_reconnect !== false ? 'true' : 'false');

      // Mode
      const modeVal = d.network_mode || 'standalone';
      const r = document.querySelector(`input[name="net_mode_radio"][value="${modeVal}"]`);
      if (r) r.checked = true;

      // Schedule & Traffic Gate
      if (document.getElementById('cfg-sched-mode')) document.getElementById('cfg-sched-mode').value = d.schedule_mode || 'scheduled';
      if (document.getElementById('cfg-sched-cron')) {
        const sel = document.getElementById('cfg-sched-cron');
        let matched = false;
        for (let opt of sel.options) {
          if (opt.value === d.schedule_cron) {
            sel.value = d.schedule_cron;
            matched = true;
            break;
          }
        }
        if (!matched && d.schedule_cron) {
          sel.value = 'custom';
          const cw = document.getElementById('cfg-sched-custom-cron-wrap');
          const ci = document.getElementById('cfg-sched-custom-cron-input');
          if (cw) cw.style.display = 'block';
          if (ci) ci.value = d.schedule_cron;
        }
      }
      if (document.getElementById('cfg-sched-engine')) document.getElementById('cfg-sched-engine').value = d.automated_engine || 'ookla';
      if (document.getElementById('cfg-sched-server-id')) document.getElementById('cfg-sched-server-id').value = d.speedtest_server_id || '';
      if (document.getElementById('cfg-sched-gate-mode')) {
        document.getElementById('cfg-sched-gate-mode').value = d.idle_threshold_mode || 'percent';
        onCfgGateModeChange(d.idle_threshold_mode || 'percent');
      }
      if (document.getElementById('cfg-sched-gate-percent')) document.getElementById('cfg-sched-gate-percent').value = (d.idle_threshold_percent !== undefined) ? d.idle_threshold_percent : 2.0;
      if (document.getElementById('cfg-sched-idle-kbps')) document.getElementById('cfg-sched-idle-kbps').value = d.idle_threshold_kbps || 500;

      // User-Agent & Headless Client
      if (document.getElementById('cfg-ua-mode')) document.getElementById('cfg-ua-mode').value = d.user_agent_mode || 'auto_fresh';
      if (document.getElementById('cfg-user-agent')) document.getElementById('cfg-user-agent').value = d.user_agent || '';
      if (document.getElementById('cfg-ua-active-display')) document.getElementById('cfg-ua-active-display').textContent = d.effective_user_agent || d.user_agent || 'HeadlessChrome/133.0.6943.126';
      onCfgUaModeChange(d.user_agent_mode || 'auto_fresh');

      // Contract / ISP
      if (document.getElementById('cfg-isp-name')) document.getElementById('cfg-isp-name').value = d.isp_name || '';
      if (document.getElementById('cfg-conn-type')) document.getElementById('cfg-conn-type').value = d.connection_type || 'fiber';
      if (document.getElementById('cfg-account-id')) document.getElementById('cfg-account-id').value = d.circuit_id || d.account_id || '';
      if (document.getElementById('cfg-contract-down')) document.getElementById('cfg-contract-down').value = d.contract_down_mbps || '';
      if (document.getElementById('cfg-guaranteed-down')) document.getElementById('cfg-guaranteed-down').value = d.guaranteed_down_mbps || '';
      if (document.getElementById('cfg-contract-up')) document.getElementById('cfg-contract-up').value = d.contract_up_mbps || '';
      if (document.getElementById('cfg-guaranteed-up')) document.getElementById('cfg-guaranteed-up').value = d.guaranteed_up_mbps || '';

      // System
      if (document.getElementById('cfg-memory-profile')) document.getElementById('cfg-memory-profile').value = d.memory_profile || 'auto';

      // Sync active theme highlight
      if (d.theme) {
        const localTheme = localStorage.getItem('nmb_theme');
        if (!localTheme) {
          switchTheme(d.theme, false);
        } else {
          updateThemeCardsHighlight(localTheme);
        }
      } else {
        updateThemeCardsHighlight(document.documentElement.getAttribute('data-theme') || 'default');
      }
    } catch (e) {
      console.error('loadConfig error:', e);
    }
  }

  // Save all router settings to /api/config
  async function saveRouterSettings() {
    showToast(t('toast_saving', 'Applying settings, please wait...'));
    const modeRadio = document.querySelector('input[name="net_mode_radio"]:checked');
    const pppoePass = (document.getElementById('cfg-pppoe-pass').value || '').trim();
    const wifiPass = (document.getElementById('cfg-wifi-psk').value || '').trim();
    const adminPass = (document.getElementById('cfg-admin-pass').value || '').trim();

    const schedCronVal = (document.getElementById('cfg-sched-cron').value === 'custom' && document.getElementById('cfg-sched-custom-cron-input'))
      ? ((document.getElementById('cfg-sched-custom-cron-input').value || '').trim() || '*/15 * * * *')
      : document.getElementById('cfg-sched-cron').value;

    const payload = {
      network_mode: modeRadio ? modeRadio.value : 'standalone',
      wan_proto: document.getElementById('cfg-wan-proto').value,
      wan_ip: document.getElementById('cfg-wan-ip') ? document.getElementById('cfg-wan-ip').value : '',
      wan_netmask: document.getElementById('cfg-wan-netmask') ? document.getElementById('cfg-wan-netmask').value : '255.255.255.0',
      wan_gateway: document.getElementById('cfg-wan-gateway') ? document.getElementById('cfg-wan-gateway').value : '',
      pppoe_enabled: document.getElementById('cfg-wan-proto').value === 'pppoe',
      pppoe_user: document.getElementById('cfg-pppoe-user').value,
      pppoe_vlan: parseInt(document.getElementById('cfg-pppoe-vlan').value) || 0,
      pppoe_service_name: document.getElementById('cfg-pppoe-service').value,
      dns_mode: document.getElementById('cfg-dns-mode').value,
      dns_primary: document.getElementById('cfg-dns-primary').value,
      dns_secondary: document.getElementById('cfg-dns-secondary').value,

      gateway_ip: document.getElementById('cfg-lan-ip').value,
      gateway_netmask: document.getElementById('cfg-lan-netmask').value,
      dhcp_enabled: document.getElementById('cfg-dhcp-enabled').value === 'true',
      dhcp_range_start: document.getElementById('cfg-dhcp-start').value,
      dhcp_range_end: document.getElementById('cfg-dhcp-end').value,
      dhcp_lease_time: document.getElementById('cfg-dhcp-lease').value,

      wifi_enabled: document.getElementById('cfg-wifi-enabled').value === 'true',
      wifi_ssid: document.getElementById('cfg-wifi-ssid').value,
      wifi_country_code: document.getElementById('cfg-wifi-country') ? document.getElementById('cfg-wifi-country').value : 'auto',
      wifi_band: document.getElementById('cfg-wifi-band') ? document.getElementById('cfg-wifi-band').value : 'auto',
      wifi_standard: document.getElementById('cfg-wifi-standard') ? document.getElementById('cfg-wifi-standard').value : 'auto',
      wifi_channel_width: document.getElementById('cfg-wifi-channel-width') ? document.getElementById('cfg-wifi-channel-width').value : 'auto',
      wifi_channel: parseInt(document.getElementById('cfg-wifi-channel').value) || 0,
      wifi_security: document.getElementById('cfg-wifi-security').value,

      // Dedicated Guest Wi-Fi Receiver
      guest_wifi_enabled: document.getElementById('cfg-guest-wifi-enabled') ? document.getElementById('cfg-guest-wifi-enabled').value === 'true' : false,
      guest_wifi_interface: document.getElementById('cfg-guest-wifi-iface') ? document.getElementById('cfg-guest-wifi-iface').value : 'wlan0',
      guest_wifi_ssid: document.getElementById('cfg-guest-wifi-ssid') ? document.getElementById('cfg-guest-wifi-ssid').value : '',
      guest_wifi_password: document.getElementById('cfg-guest-wifi-pass') ? document.getElementById('cfg-guest-wifi-pass').value : '',
      guest_wifi_metric: document.getElementById('cfg-guest-wifi-metric') ? parseInt(document.getElementById('cfg-guest-wifi-metric').value) || 600 : 600,
      guest_wifi_auto_reconnect: document.getElementById('cfg-guest-wifi-autorecon') ? document.getElementById('cfg-guest-wifi-autorecon').value === 'true' : true,

      schedule_mode: document.getElementById('cfg-sched-mode').value,
      schedule_cron: schedCronVal,
      automated_engine: document.getElementById('cfg-sched-engine').value,
      speedtest_server_id: (document.getElementById('cfg-sched-server-id').value || '').trim(),
      idle_threshold_mode: document.getElementById('cfg-sched-gate-mode') ? document.getElementById('cfg-sched-gate-mode').value : 'percent',
      idle_threshold_percent: document.getElementById('cfg-sched-gate-percent') ? parseFloat(document.getElementById('cfg-sched-gate-percent').value) || 2.0 : 2.0,
      idle_threshold_kbps: document.getElementById('cfg-sched-idle-kbps') ? parseInt(document.getElementById('cfg-sched-idle-kbps').value) || 500 : 500,

      user_agent_mode: document.getElementById('cfg-ua-mode') ? document.getElementById('cfg-ua-mode').value : 'auto_fresh',
      user_agent: document.getElementById('cfg-user-agent') ? document.getElementById('cfg-user-agent').value.trim() : '',

      isp_name: document.getElementById('cfg-isp-name').value,
      connection_type: document.getElementById('cfg-conn-type').value,
      circuit_id: document.getElementById('cfg-account-id').value,
      contract_down_mbps: parseFloat(document.getElementById('cfg-contract-down').value) || 0,
      guaranteed_down_mbps: parseFloat(document.getElementById('cfg-guaranteed-down').value) || 0,
      contract_up_mbps: parseFloat(document.getElementById('cfg-contract-up').value) || 0,
      guaranteed_up_mbps: parseFloat(document.getElementById('cfg-guaranteed-up').value) || 0,

      memory_profile: document.getElementById('cfg-memory-profile') ? document.getElementById('cfg-memory-profile').value : 'auto',
      theme: localStorage.getItem('nmb_theme') || document.documentElement.getAttribute('data-theme') || 'default',
    };

    if (pppoePass) payload.pppoe_password = pppoePass;
    if (wifiPass) payload.wifi_psk = wifiPass;
    if (adminPass) payload.admin_password = adminPass;

    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        showToast(t('router_saved', '✅ Advanced router settings successfully saved and applied!'));
        refreshStatus();
      } else {
        const err = await res.json();
        showToast('Error saving settings: ' + (err.message || err.error || 'Unknown error'));
      }
    } catch (e) {
      showToast('Network error: ' + e);
    }
  }

  async function reloadDaemons() {
    showToast(t('toast_saving', 'Applying settings, please wait...'));
    try {
      const res = await fetch('/api/system/reload', { method: 'POST' });
      if (res.ok) showToast(t('services_reloaded', '✅ Network services successfully reloaded!'));
      else showToast('Error reloading network services.');
    } catch (e) {
      showToast('Error: ' + e);
    }
  }

  async function rebootBox() {
    if (!confirm(t('confirm_reboot', 'Are you sure you want to reboot the NetworkMeasureBox device?'))) return;
    showToast(t('rebooting_wait', 'Device is restarting... Please wait approximately 60 seconds.'));
    try {
      await fetch('/api/system/reboot', { method: 'POST' });
    } catch (e) {}
  }

  // =========================================================================
  // Backup & Disaster Recovery Client Engine
  // =========================================================================
  async function loadBackupsList() {
    const tbody = document.getElementById('backup-list-tbody');
    if (!tbody) return;
    try {
      const res = await fetch('/api/backup/list');
      if (!res.ok) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #f87171; padding: 16px;">Failed to load backups.</td></tr>';
        return;
      }
      const data = await res.json();
      const list = data.backups || [];
      if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">No backup archives stored on device.</td></tr>';
        return;
      }
      let html = '';
      for (const b of list) {
        const isSafety = b.is_safety_snapshot || (b.comment && b.comment.toLowerCase().includes('safety'));
        let typeBadge = '';
        if (isSafety) {
          typeBadge = '<span class="badge-pill" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid #d97706; font-size: 11px;">🛡️ Safety Rollback</span>';
        } else if (b.type === 'config') {
          typeBadge = '<span class="badge-pill" style="background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid #7e22ce; font-size: 11px;">⚙️ Config</span>';
        } else {
          typeBadge = '<span class="badge-pill" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid #0284c7; font-size: 11px;">💾 Full</span>';
        }

        const dateStr = b.created_iso ? b.created_iso.replace('T', ' ') : (b.created ? new Date(b.created * 1000).toLocaleString() : '-');
        const commentEsc = escapeHtml(b.comment || '-');
        const filenameEsc = escapeHtml(b.filename);

        html += `<tr>
          <td style="font-family: monospace; font-size: 12px;">
            <div style="font-weight: 600; color: #ffffff;">${filenameEsc}</div>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">${dateStr}</div>
          </td>
          <td>${typeBadge}</td>
          <td style="font-family: monospace; font-size: 12px; color: #94a3b8;">${escapeHtml(b.size_human || '')}</td>
          <td style="font-size: 12px; color: #cbd5e1;">${commentEsc}</td>
          <td style="text-align: right; white-space: nowrap;">
            <a href="/api/backup/download?file=${encodeURIComponent(b.filename)}" class="btn-secondary" style="font-size: 11px; padding: 4px 8px; text-decoration: none; display: inline-block; margin-right: 4px;">📥 Download</a>
            <button type="button" class="btn-primary" style="font-size: 11px; padding: 4px 8px; margin-right: 4px;" onclick="restoreLocalBackup(${jsArg(b.filename)})">${t('backup_action_restore', '🔄 Restore')}</button>
            <button type="button" class="btn-danger" style="font-size: 11px; padding: 4px 8px; background: #dc2626; border-color: #ef4444; color: white;" onclick="deleteLocalBackup(${jsArg(b.filename)})">🗑️</button>
          </td>
        </tr>`;
      }
      tbody.innerHTML = html;
    } catch (e) {
      console.error('Failed to load backups list:', e);
      tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #f87171; padding: 16px;">Error connecting to backup service.</td></tr>';
    }
  }

  async function createBackup(type, saveLocal) {
    const commentInput = document.getElementById(type === 'full' ? 'backup-comment-full' : 'backup-comment-cfg');
    const comment = commentInput ? commentInput.value.trim() : '';
    showToast(t('backup_creating', 'Creating backup snapshot...'));
    try {
      const res = await fetch('/api/backup/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: type, comment: comment })
      });
      const data = await res.json();
      if (!res.ok || data.status !== 'ok') {
        showToast('Error: ' + (data.message || 'Failed to create backup'));
        return;
      }
      showToast('Backup created: ' + data.filename);
      if (commentInput) commentInput.value = '';
      await loadBackupsList();
      if (!saveLocal && data.download_url) {
        window.location.href = data.download_url;
      }
    } catch (e) {
      showToast('Network error creating backup: ' + e);
    }
  }

  async function restoreLocalBackup(filename) {
    const confirmMsg = t('backup_confirm_restore', 'Are you sure you want to restore the device to this state? An automated safety backup of the current state will be created first.');
    if (!confirm(confirmMsg)) return;

    showToast('Restoring system state from ' + filename + '... Please wait.');
    try {
      const res = await fetch('/api/backup/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: filename, restore_db: true, restore_vpn: true })
      });
      const data = await res.json();
      if (!res.ok || data.status !== 'ok') {
        showToast('Restore failed: ' + (data.message || 'Unknown error'));
        alert('Restore error: ' + (data.message || 'Unknown error'));
        return;
      }
      showToast('✅ State restored successfully! Reloading web interface...');
      setTimeout(() => { window.location.reload(); }, 2500);
    } catch (e) {
      showToast('Restore network error: ' + e);
    }
  }

  async function uploadAndRestoreBackup() {
    const fileInput = document.getElementById('backup-upload-file');
    const statusEl = document.getElementById('backup-upload-status');
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
      showToast('Please select a .tar.gz backup archive file to upload.');
      return;
    }
    const file = fileInput.files[0];
    const confirmMsg = t('backup_confirm_restore', 'Are you sure you want to restore the device to this state? An automated safety backup of the current state will be created first.');
    if (!confirm(confirmMsg)) return;

    if (statusEl) {
      statusEl.style.display = 'block';
      statusEl.style.background = '#1e293b';
      statusEl.style.color = '#38bdf8';
      statusEl.style.border = '1px solid #0284c7';
      statusEl.textContent = '⏳ Uploading and verifying backup archive (' + (file.size / 1024).toFixed(1) + ' KB)...';
    }

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch('/api/backup/upload', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (!res.ok || data.status !== 'ok') {
        const errMsg = data.message || 'Failed to apply backup';
        if (statusEl) {
          statusEl.style.background = 'rgba(239, 68, 68, 0.15)';
          statusEl.style.color = '#f87171';
          statusEl.style.border = '1px solid #dc2626';
          statusEl.textContent = '❌ Restore failed: ' + errMsg;
        }
        showToast('Restore failed: ' + errMsg);
        return;
      }

      if (statusEl) {
        statusEl.style.background = 'rgba(16, 185, 129, 0.15)';
        statusEl.style.color = '#34d399';
        statusEl.style.border = '1px solid #059669';
        statusEl.textContent = '✅ ' + (data.message || 'Backup verified and successfully restored! Reloading interface in 3 seconds...');
      }
      showToast('✅ Restore completed successfully! Reloading...');
      setTimeout(() => { window.location.reload(); }, 3000);
    } catch (e) {
      if (statusEl) {
        statusEl.style.background = 'rgba(239, 68, 68, 0.15)';
        statusEl.style.color = '#f87171';
        statusEl.style.border = '1px solid #dc2626';
        statusEl.textContent = '❌ Upload error: ' + e;
      }
      showToast('Upload error: ' + e);
    }
  }

  async function deleteLocalBackup(filename) {
    if (!confirm('Are you sure you want to permanently delete backup ' + filename + '?')) return;
    showToast('Deleting backup: ' + filename);
    try {
      const res = await fetch('/api/backup/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: filename })
      });
      const data = await res.json();
      if (!res.ok || data.status !== 'ok') {
        showToast('Error deleting backup: ' + (data.message || 'Failed'));
        return;
      }
      showToast('Backup deleted.');
      await loadBackupsList();
    } catch (e) {
      showToast('Error: ' + e);
    }
  }

  async function executeFactoryReset() {
    const confirmMsg = t('backup_confirm_reset', 'CAUTION! Are you sure you want to execute factory reset? All custom network and VPN configurations will be reverted to defaults!');
    if (!confirm(confirmMsg)) return;

    const check = prompt('Type RESET to confirm complete factory reset:');
    if (check !== 'RESET') {
      showToast('Factory reset cancelled.');
      return;
    }

    const keepDb = document.getElementById('reset-keep-db') ? document.getElementById('reset-keep-db').checked : true;
    showToast('Executing factory reset... Automated safety backup is being created.');

    try {
      const res = await fetch('/api/backup/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: 'RESET', keep_measurements: keepDb })
      });
      const data = await res.json();
      if (!res.ok || data.status !== 'ok') {
        showToast('Factory reset failed: ' + (data.message || 'Unknown error'));
        alert('Factory reset failed: ' + (data.message || 'Unknown error'));
        return;
      }
      alert('Factory reset completed successfully. The system will now reload.');
      setTimeout(() => { window.location.reload(); }, 2000);
    } catch (e) {
      showToast('Factory reset network error: ' + e);
    }
  }

  async function executeFactoryResetFromSettings() {
    const keepDb = document.getElementById('sys-reset-keep-db') ? document.getElementById('sys-reset-keep-db').checked : true;
    const confirmMsg = t('factory_reset_confirm', 'WARNING! Are you sure you want to restore factory defaults? All custom network and VPN configurations will be reset!');
    if (!confirm(confirmMsg)) return;

    const check = prompt(t('factory_reset_prompt', 'To confirm factory reset, type: RESET (or click Cancel)'));
    if (check !== 'RESET') {
      showToast(t('factory_reset_cancelled', 'Factory reset cancelled.'));
      return;
    }

    showToast(t('factory_reset_in_progress', 'Factory reset in progress... Automated safety backup is being created.'));

    try {
      const res = await fetch('/api/backup/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: 'RESET', keep_measurements: keepDb })
      });
      const data = await res.json();
      if (!res.ok || data.status !== 'ok') {
        showToast(t('factory_reset_failed', 'Factory reset failed: ') + (data.message || 'Unknown error'));
        alert(t('factory_reset_failed', 'Factory reset failed: ') + (data.message || 'Unknown error'));
        return;
      }
      alert(t('factory_reset_success', 'Factory reset completed successfully! The page will reload in 2 seconds.'));
      setTimeout(() => { window.location.reload(); }, 2000);
    } catch (e) {
      showToast(t('network_error', 'Network error: ') + e);
    }
  }

  async function syncDriveConfigNow() {
    const msgEl = document.getElementById('drive-sync-msg');
    showToast(t('drive_toast_syncing', 'Syncing configuration to drive...'));
    if (msgEl) msgEl.innerText = t('drive_toast_syncing', 'Syncing configuration to drive...');
    try {
      const res = await fetch('/api/config/drive-sync', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast('✅ ' + (data.message || t('drive_toast_synced', '✅ Successfully synchronized to boot drive!')));
        if (msgEl) {
          msgEl.innerText = t('drive_toast_synced', '✅ Successfully synchronized to boot drive!');
          msgEl.style.color = '#34d399';
        }
        const b = document.getElementById('drive-cfg-status-badge');
        if (b) {
          b.innerText = t('drive_status_synced', '✅ Active and Synchronized');
          b.style.color = '#34d399';
          b.style.borderColor = '#10b981';
        }
      } else {
        showToast(data.message || t('drive_toast_failed', 'Failed to synchronize configuration.'));
        if (msgEl) {
          msgEl.innerText = data.message || t('drive_toast_failed', 'Failed to synchronize configuration.');
          msgEl.style.color = '#f59e0b';
        }
      }
    } catch (e) {
      showToast(t('error', 'Error: ') + e);
      if (msgEl) msgEl.innerText = t('network_error', 'Network error: ') + e;
    }
  }

  // =========================================================================
  // Self-Healing, Multi-Tier Escalation & Stable Updates Engine
  // =========================================================================
  async function loadHealStatus() {
    try {
      const res = await fetch('/api/heal/status');
      if (!res.ok) return;
      const data = await res.json();
      const audit = data.audit || {};
      const state = data.state || {};

      // 1. Overall status badge
      const badge = document.getElementById('heal-overall-badge');
      if (badge) {
        const st = audit.overall_status || 'unknown';
        if (st === 'healthy') {
          badge.className = 'badge-pill';
          badge.style.background = 'rgba(16, 185, 129, 0.15)';
          badge.style.color = '#34d399';
          badge.style.border = '1px solid #059669';
          badge.textContent = '✔ HEALTHY';
        } else if (st === 'warning') {
          badge.className = 'badge-pill';
          badge.style.background = 'rgba(245, 158, 11, 0.15)';
          badge.style.color = '#fbbf24';
          badge.style.border = '1px solid #d97706';
          badge.textContent = '▲ WARNING (' + audit.warning_count + ')';
        } else {
          badge.className = 'badge-pill';
          badge.style.background = 'rgba(239, 68, 68, 0.15)';
          badge.style.color = '#f87171';
          badge.style.border = '1px solid #dc2626';
          badge.textContent = '✖ CRITICAL ISSUES (' + audit.critical_count + ')';
        }
      }

      // 2. Streaks and timestamps
      const streakEl = document.getElementById('heal-streak-count');
      if (streakEl) streakEl.textContent = state.consecutive_clean_audits || 0;

      const timeEl = document.getElementById('heal-last-audit-time');
      if (timeEl && audit.timestamp) {
        timeEl.textContent = new Date(audit.timestamp * 1000).toLocaleTimeString();
      }

      // 3. Components table
      const tbody = document.getElementById('heal-components-tbody');
      if (tbody && audit.components) {
        let html = '';
        const catTitles = {
          binaries: '⚙️ External & Compiled Binaries',
          symlinks: '🔗 CLI Symlinks (/usr/local/bin)',
          database: '💾 SQLite Database & Tables',
          config: '📄 System Configuration',
          filesystem: '📁 Filesystem Permissions',
          services: '🐧 Systemd Units & Timers',
          network: '🌐 Network Stack & DNS',
        };

        for (const [catKey, catTitle] of Object.entries(catTitles)) {
          const catData = audit.components[catKey];
          if (!catData || !catData.items) continue;
          html += `<tr style="background: rgba(255, 255, 255, 0.03);"><td colspan="3" style="font-weight: 700; color: #38bdf8; padding: 8px 12px;">${catTitle}</td></tr>`;
          for (const item of catData.items) {
            let statusPill = '';
            if (item.status === 'ok') {
              statusPill = '<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #059669; font-size: 11px;">✔ OK</span>';
            } else if (item.status === 'warning') {
              statusPill = '<span class="badge-pill" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid #d97706; font-size: 11px;">▲ WARN</span>';
            } else {
              statusPill = '<span class="badge-pill" style="background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid #dc2626; font-size: 11px;">✖ FAIL</span>';
            }
            html += `<tr>
              <td style="font-weight: 600; color: #ffffff; padding: 7px 12px;">${escapeHtml(item.label || item.id)}</td>
              <td style="padding: 7px 12px;">${statusPill}</td>
              <td style="font-size: 11.5px; color: ${item.status === 'ok' ? '#94a3b8' : '#fca5a5'}; padding: 7px 12px;">${escapeHtml(item.message || '')}</td>
            </tr>`;
          }
        }
        tbody.innerHTML = html;
      }

      // 4. Escalation tracking container
      const escContainer = document.getElementById('heal-escalation-container');
      if (escContainer) {
        const comps = state.components || {};
        const entries = Object.values(comps);
        if (entries.length === 0) {
          escContainer.innerHTML = '<div style="font-size: 12px; color: #34d399; text-align: center; padding: 20px;">✔ No recurring component failures tracked. System baseline clean.</div>';
        } else {
          let escHtml = '<div style="display: flex; flex-direction: column; gap: 8px;">';
          for (const c of entries) {
            const isResolved = c.resolved;
            const tierBadge = c.last_tier_attempted ? `<span class="badge-pill" style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #d97706; font-size: 11px;">Tier ${escapeHtml(c.last_tier_attempted)}</span>` : '';
            const statusBadge = isResolved
              ? '<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #059669; font-size: 11px;">RESOLVED</span>'
              : '<span class="badge-pill" style="background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid #dc2626; font-size: 11px;">ACTIVE ISSUE</span>';
            escHtml += `<div style="padding: 8px 10px; background: rgba(0,0,0,0.25); border-radius: 6px; border: 1px solid rgba(255,255,255,0.05); font-size: 11.5px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <strong style="color: #ffffff;">${escapeHtml(c.label || c.id)}</strong>
                <div style="display: flex; gap: 4px;">${tierBadge}${statusBadge}</div>
              </div>
              <div style="color: #94a3b8; font-size: 11px;">Consecutive failures: <strong style="color: ${c.consecutive_failures > 1 ? '#f87171' : '#fbbf24'};">${c.consecutive_failures || 0}</strong> | Total: ${c.total_failures || 0}</div>
              ${c.last_actions && c.last_actions.length ? `<div style="color: #38bdf8; font-size: 11px; margin-top: 2px;">Last action: ${escapeHtml(c.last_actions[c.last_actions.length - 1])}</div>` : ''}
            </div>`;
          }
          escHtml += '</div>';
          escContainer.innerHTML = escHtml;
        }
      }
    } catch (e) {
      console.error('Error loading self-heal status:', e);
    }
  }

  async function triggerHealAudit() {
    showToast('Running comprehensive component health audit...');
    try {
      const res = await fetch('/api/heal/audit', { method: 'POST' });
      if (!res.ok) {
        showToast('Health audit failed.');
        return;
      }
      showToast('Health audit complete.');
      await loadHealStatus();
    } catch (e) {
      showToast('Error running audit: ' + e);
    }
  }

  async function triggerAutoHeal(tier) {
    const tierMsg = tier ? (' (Forcing Escalation Tier ' + tier + ')') : ' with adaptive escalation';
    showToast('Executing automated self-healing' + tierMsg + '...');
    try {
      const res = await fetch('/api/heal/fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier: tier })
      });
      const data = await res.json();
      const repairs = data.repairs_executed || [];
      if (repairs.length > 0) {
        alert('Self-Healing Completed:\n\n' + repairs.join('\n'));
      } else {
        showToast('Self-healing check completed: All components healthy.');
      }
      await loadHealStatus();
    } catch (e) {
      showToast('Error during self-healing: ' + e);
    }
  }

  async function checkStableUpdates(showToastAlert) {
    try {
      const res = await fetch('/api/heal/updates');
      if (!res.ok) return;
      const data = await res.json();

      const curEl = document.getElementById('heal-cur-ver');
      if (curEl) curEl.textContent = data.current_version || '2.5.0';

      const availEl = document.getElementById('heal-avail-ver');
      if (availEl) availEl.textContent = data.available_version || data.current_version || '2.5.0';

      const tagEl = document.getElementById('heal-stability-tag');
      if (tagEl) {
        if (data.is_stable) {
          tagEl.style.background = 'rgba(16, 185, 129, 0.15)';
          tagEl.style.color = '#34d399';
          tagEl.style.border = '1px solid #059669';
          tagEl.textContent = '✔ STABLE RELEASE';
        } else {
          tagEl.style.background = 'rgba(239, 68, 68, 0.15)';
          tagEl.style.color = '#f87171';
          tagEl.style.border = '1px solid #dc2626';
          tagEl.textContent = '▲ UNSTABLE / PRE-RELEASE';
        }
      }

      const msgEl = document.getElementById('heal-update-msg');
      if (msgEl) {
        let msg = escapeHtml(data.message || 'System software is up to date.');
        if (data.changelog && data.changelog.length) {
          msg += '<br><span style="color: #38bdf8; font-weight: 600;">Recent commits:</span><br>' + data.changelog.slice(0, 3).map(c => '• ' + escapeHtml(c)).join('<br>');
        }
        msgEl.innerHTML = msg;
      }

      const btnApply = document.getElementById('btn-apply-update');
      if (btnApply) {
        if (data.update_available && data.is_stable) {
          btnApply.style.opacity = '1';
          btnApply.style.cursor = 'pointer';
          btnApply.disabled = false;
        } else {
          btnApply.style.opacity = '0.5';
          btnApply.style.cursor = 'not-allowed';
          btnApply.disabled = true;
        }
      }

      if (showToastAlert) {
        showToast(data.update_available ? 'Stable update available!' : 'System is already up to date.');
      }
    } catch (e) {
      console.error('Error checking stable updates:', e);
    }
  }

  async function applyStableUpdate() {
    if (!confirm(t('confirm_apply_update', 'Apply stable update with automatic safety rollback protection? An atomic pre-update backup checkpoint will be created before applying.'))) {
      return;
    }

    showToast('Creating safety checkpoint and applying stable update...');
    try {
      const res = await fetch('/api/heal/update/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      const data = await res.json();
      if (data.started) {
        pollGithubUpdate();
        return;
      }
      if (data.success) {
        alert(t('update_applied_success', 'Update Applied Successfully! Version: ') + data.new_version + ' (' + data.checkpoint + '). Reloading dashboard...');
        setTimeout(() => { window.location.reload(); }, 2000);
      } else {
        if (data.rolled_back) {
          alert(t('update_rollback_applied', '⚠️ UPDATE VERIFICATION FAILED — AUTOMATIC ROLLBACK APPLIED! Reason: ') + data.error);
        } else {
          alert('Update failed: ' + (data.error || 'Unknown error'));
        }
        await loadHealStatus();
        await checkStableUpdates(false);
      }
    } catch (e) {
      showToast('Error applying update: ' + e);
    }
  }

  // The GitHub update restarts the web server, so failed requests while it runs are expected.
  async function pollGithubUpdate() {
    const msgEl = document.getElementById('heal-update-msg');
    const btn = document.getElementById('btn-apply-update');
    if (btn) btn.disabled = true;
    const stepNames = {
      download: t('upd_step_download', 'downloading from GitHub'),
      test: t('upd_step_test', 'testing the new version'),
      backup: t('upd_step_backup', 'saving settings and measurements'),
      install: t('upd_step_install', 'installing'),
      verify: t('upd_step_verify', 'checking the services'),
    };
    const deadline = Date.now() + 3600 * 1000;
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 5000));
      let st;
      try {
        const res = await fetch('/api/heal/update/status', { cache: 'no-store' });
        if (!res.ok) continue;
        st = await res.json();
      } catch (e) {
        continue;
      }
      if (st.state === 'running') {
        if (msgEl) msgEl.textContent = t('upd_running', 'Updating, step {n} of {total}: {step}')
          .replace('{n}', st.step_no || 1).replace('{total}', st.steps || 5).replace('{step}', stepNames[st.step] || st.step || '');
        continue;
      }
      if (st.state === 'success') {
        if (msgEl) msgEl.textContent = t('upd_done', 'Update finished. Reloading the page...');
        setTimeout(() => { window.location.reload(); }, 3000);
        return;
      }
      if (st.state === 'failed' || st.state === 'rolled_back') {
        const head = st.state === 'rolled_back'
          ? t('upd_rolled_back', 'The update failed and the previous version was put back.')
          : t('upd_failed', 'The update failed; nothing was changed.');
        if (msgEl) msgEl.textContent = head + ' ' + (st.message || '');
        if (btn) btn.disabled = false;
        return;
      }
    }
    if (btn) btn.disabled = false;
  }

  // ==========================================
  // Interactive CLI Terminal Controller
  // ==========================================
  let terminalHistory = [];
  let terminalHistoryIdx = -1;

  function initTerminal() {
    try {
      const saved = localStorage.getItem('nmb_term_history');
      if (saved) terminalHistory = JSON.parse(saved);
    } catch (e) {}

    const boxId = (window.lastStatusData && window.lastStatusData.box_id) || 'nmb-01';
    const boxIdEl = document.getElementById('term-box-id');
    if (boxIdEl) boxIdEl.innerText = boxId;

    const screen = document.getElementById('cli-terminal-screen');
    if (screen && !screen.innerText.trim()) {
      screen.innerText = 
`================================================================================
NetworkMeasureBox Linux Interactive Diagnostics Shell
Box ID: ${boxId} | Firmware: 4047 (Universal)
Type any Linux command below, or click any of the quick shortcuts above.
Use UP/DOWN arrow keys for command history.
================================================================================

`;
    }

    const input = document.getElementById('cli-term-input');
    if (input && !input.dataset.bound) {
      input.dataset.bound = 'true';
      input.addEventListener('keydown', function(e) {
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (terminalHistory.length === 0) return;
          if (terminalHistoryIdx === -1) terminalHistoryIdx = terminalHistory.length - 1;
          else if (terminalHistoryIdx > 0) terminalHistoryIdx--;
          input.value = terminalHistory[terminalHistoryIdx] || '';
        } else if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (terminalHistoryIdx !== -1) {
            if (terminalHistoryIdx < terminalHistory.length - 1) {
              terminalHistoryIdx++;
              input.value = terminalHistory[terminalHistoryIdx] || '';
            } else {
              terminalHistoryIdx = -1;
              input.value = '';
            }
          }
        }
      });
    }
  }

  async function submitTerminalCmd(e) {
    if (e) e.preventDefault();
    const input = document.getElementById('cli-term-input');
    if (!input) return;
    const cmd = input.value.trim();
    if (!cmd) return;
    input.value = '';
    terminalHistoryIdx = -1;

    // Save to history
    if (!terminalHistory.length || terminalHistory[terminalHistory.length - 1] !== cmd) {
      terminalHistory.push(cmd);
      if (terminalHistory.length > 50) terminalHistory.shift();
      try { localStorage.setItem('nmb_term_history', JSON.stringify(terminalHistory)); } catch (err) {}
    }

    await execTerminalCommand(cmd);
  }

  function execQuickTermCmd(cmd) {
    const input = document.getElementById('cli-term-input');
    if (input) input.value = cmd;
    execTerminalCommand(cmd);
  }

  async function execTerminalCommand(cmd) {
    const screen = document.getElementById('cli-terminal-screen');
    const badge = document.getElementById('term-status-badge');
    const runBtn = document.getElementById('btn-term-run');
    if (!screen) return;

    screen.innerText += `root@box:~# ${cmd}
`;
    screen.scrollTop = screen.scrollHeight;
    if (badge) {
      badge.innerText = t('status_running', 'RUNNING...');
      badge.style.color = '#fbbf24';
      badge.style.borderColor = '#f59e0b';
    }
    if (runBtn) runBtn.disabled = true;

    try {
      const res = await fetch('/api/terminal/exec', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd })
      });
      const data = await res.json();
      const code = data.exit_code !== undefined ? data.exit_code : (res.ok ? 0 : 1);
      const dur = data.duration_ms ? ` (${data.duration_ms}ms)` : '';
      const codeBadge = code === 0 ? `[Exit 0${dur}]` : `[Exit ${code}${dur}]`;

      screen.innerText += `${data.output || '(No output)'}
${codeBadge}

`;
    } catch (err) {
      screen.innerText += `Network error executing command: ${err}
[Exit -1]

`;
    } finally {
      if (badge) {
        badge.innerText = 'ONLINE';
        badge.style.color = '#34d399';
        badge.style.borderColor = '#10b981';
      }
      if (runBtn) runBtn.disabled = false;
      screen.scrollTop = screen.scrollHeight;
      const input = document.getElementById('cli-term-input');
      if (input) input.focus();
    }
  }

  function clearTerminalScreen() {
    const screen = document.getElementById('cli-terminal-screen');
    if (screen) {
      screen.innerText = 'Screen cleared.\n\n';
    }
  }

  function copyTerminalOutput() {
    const screen = document.getElementById('cli-terminal-screen');
    if (!screen) return;
    navigator.clipboard.writeText(screen.innerText).then(() => {
      showToast(t('terminal_copied', 'Terminal output copied to clipboard!'));
    }).catch(() => {
      showToast(t('terminal_copy_failed', 'Failed to copy terminal output.'));
    });
  }

  // ==========================================
  // Invasive System Diagnostics & AI Developer Snapshot
  // ==========================================
  let invasiveLogMarkdown = '';

  async function loadInvasiveLogPreview() {
    const previewEl = document.getElementById('invasive-log-preview');
    const updatedEl = document.getElementById('invasive-last-updated');
    if (!previewEl) return;
    try {
      const res = await fetch('/api/dev/invasive-log.md');
      if (res.ok) {
        invasiveLogMarkdown = await res.text();
        previewEl.innerText = invasiveLogMarkdown;
        if (updatedEl) {
          const nowStr = new Date().toLocaleTimeString();
          updatedEl.innerText = t('status_updated', 'Updated: ') + nowStr;
        }
      }
    } catch (e) {
      if (previewEl) previewEl.innerText = t('error', 'Error: ') + e;
    }
  }

  async function refreshInvasiveLog() {
    const previewEl = document.getElementById('invasive-log-preview');
    if (previewEl) previewEl.innerText = t('invasive_loading', 'Loading deep system diagnostic snapshot...');
    try {
      const res = await fetch('/api/dev/invasive-log/generate', { method: 'POST' });
      if (res.ok) {
        const d = await res.json();
        invasiveLogMarkdown = d.markdown || '';
        if (previewEl) previewEl.innerText = invasiveLogMarkdown;
        showToast(t('invasive_toast_refreshed', 'Deep diagnostic snapshot refreshed successfully!'));
        const updatedEl = document.getElementById('invasive-last-updated');
        if (updatedEl) updatedEl.innerText = t('status_updated', 'Updated: ') + new Date().toLocaleTimeString();
      } else {
        showToast(t('invasive_toast_refresh_failed', 'Failed to refresh diagnostic snapshot.'));
      }
    } catch (e) {
      showToast(t('network_error', 'Network error: ') + e);
    }
    checkAntiBanAndInterfaceStatus();
  }

  async function copyInvasiveLog() {
    if (!invasiveLogMarkdown) {
      try {
        const res = await fetch('/api/dev/invasive-log.md');
        if (res.ok) invasiveLogMarkdown = await res.text();
      } catch (e) {}
    }
    if (!invasiveLogMarkdown) {
      showToast(t('invasive_toast_copy_empty', 'No diagnostic content available to copy.'));
      return;
    }
    navigator.clipboard.writeText(invasiveLogMarkdown).then(() => {
      showToast(t('invasive_toast_copied', '📋 Full developer diagnostic log copied to clipboard!'));
    }).catch(() => {
      showToast(t('terminal_copy_failed', 'Failed to copy to clipboard.'));
    });
  }

  async function checkAntiBanAndInterfaceStatus() {
    // 1. Preferred Measurement Interface (Wired Priority)
    const cableTxt = document.getElementById('diag-cable-txt');
    const cableBadge = document.getElementById('diag-cable-badge');
    if (cableTxt) {
      try {
        const res = await fetch('/api/network/preferred-interface');
        if (res.ok) {
          const d = await res.json();
          const ifaceInfo = `${d.interface}${d.bound_ip ? ' - ' + d.bound_ip : ''}`;
          if (d.is_wired) {
            cableTxt.innerText = t('invasive_cable_wired', 'Wired cable active ({iface}) [PRIORITIZED]').replace('{iface}', ifaceInfo);
            if (cableBadge) cableBadge.style.color = '#34d399';
          } else {
            cableTxt.innerText = t('invasive_cable_wireless', 'Wireless Wi-Fi ({iface})').replace('{iface}', ifaceInfo);
            if (cableBadge) cableBadge.style.color = '#fbbf24';
          }
        }
      } catch (e) {
        cableTxt.innerText = 'N/A';
      }
    }

    // 2. Ookla Anti-Ban Quarantine Status
    const antibanTxt = document.getElementById('diag-antiban-txt');
    const antibanBadge = document.getElementById('diag-antiban-badge');
    if (antibanTxt) {
      try {
        const res = await fetch('/api/speed/anti-ban');
        if (res.ok) {
          const d = await res.json();
          const q = d.quarantined_servers || {};
          const count = Object.keys(q).length;
          if (count === 0) {
            antibanTxt.innerText = t('invasive_antiban_healthy', 'Active (0 servers quarantined - Healthy)');
            if (antibanBadge) antibanBadge.style.color = '#10b981';
          } else {
            antibanTxt.innerText = t('invasive_antiban_quarantine', 'Active ({count} servers quarantined)').replace('{count}', count);
            if (antibanBadge) antibanBadge.style.color = '#f59e0b';
          }
        }
      } catch (e) {
        antibanTxt.innerText = t('status_active', 'Active');
      }
    }
    // 3. Crash Incident Reports
    loadCrashReports();
  }

  async function enforceWiredPriority() {
    try {
      const res = await fetch('/api/network/enforce-wired-priority', { method: 'POST' });
      if (res.ok) {
        const d = await res.json();
        showToast(d.adjusted ? t('invasive_toast_priority_set', 'Wired route priority enforced (metric 50)!') : t('invasive_toast_priority_optimal', 'Wired route is already optimal or no active cable.'));
        checkAntiBanAndInterfaceStatus();
      }
    } catch (e) {
      showToast(t('invasive_toast_priority_failed', 'Error enforcing route priority.'));
    }
  }

  async function loadCrashReports() {
    const crashTxt = document.getElementById('diag-crash-txt');
    const crashBadge = document.getElementById('diag-crash-badge');
    const clearBtn = document.getElementById('btn-clear-crashes');
    if (!crashTxt) return;
    try {
      const res = await fetch('/api/dev/crashes');
      if (res.ok) {
        const d = await res.json();
        const count = (d.crashes || []).length;
        if (count === 0) {
          crashTxt.innerText = t('invasive_crash_clean', '0 errors recorded (Clean)');
          if (crashBadge) crashBadge.style.color = '#10b981';
          if (clearBtn) clearBtn.style.display = 'none';
        } else {
          crashTxt.innerText = t('invasive_crash_detected', '{count} crash report(s) captured!').replace('{count}', count);
          if (crashBadge) crashBadge.style.color = '#ef4444';
          if (clearBtn) clearBtn.style.display = 'inline-block';
        }
      }
    } catch (e) {
      crashTxt.innerText = 'N/A';
    }
  }

  async function clearCrashReports() {
    try {
      const res = await fetch('/api/dev/crashes/clear', { method: 'POST' });
      if (res.ok) {
        showToast(t('invasive_toast_crashes_cleared', 'Crash reports cleared successfully.'));
        loadCrashReports();
      }
    } catch (e) {
      showToast(t('invasive_toast_crashes_failed', 'Error clearing crash reports.'));
    }
  }

  async function clearOoklaQuarantine() {
    try {
      const res = await fetch('/api/speed/anti-ban/clear', { method: 'POST' });
      if (res.ok) {
        showToast(t('invasive_toast_quarantine_cleared', 'Ookla server quarantine cleared successfully.'));
        checkAntiBanAndInterfaceStatus();
      }
    } catch (e) {
      showToast(t('invasive_toast_quarantine_failed', 'Error clearing server quarantine.'));
    }
  }

  // ==========================================
  // iPerf3 Benchmark Client & Server Daemon
  // ==========================================
  let iperfPollingTimer = null;

  function onIperfProtoChange(val) {
    const udpWrap = document.getElementById('iperf-udp-options');
    if (udpWrap) udpWrap.style.display = (val === 'udp') ? 'grid' : 'none';
  }

  async function runIperfTest() {
    const host = (document.getElementById('iperf-host').value || '').trim();
    if (!host) {
      showToast('Please enter an iPerf3 target host.');
      return;
    }
    const port = parseInt(document.getElementById('iperf-port').value) || 5201;
    const duration = parseInt(document.getElementById('iperf-duration').value) || 10;
    const protocol = document.getElementById('iperf-protocol').value;
    const parallel = parseInt(document.getElementById('iperf-parallel').value) || 1;
    const dirVal = document.getElementById('iperf-reverse').value;
    const isBidir = (dirVal === 'bidir');
    const reverse = (dirVal === 'true');
    const targetBw = document.getElementById('iperf-target-bw') ? document.getElementById('iperf-target-bw').value : '100M';

    document.getElementById('btn-iperf-run').disabled = true;
    document.getElementById('iperf-running-indicator').style.display = 'inline-block';
    showToast('Starting iPerf3 test...');

    try {
      const res = await fetch('/api/iperf/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host: host,
          port: port,
          duration: duration,
          udp: protocol === 'udp',
          parallel: parallel,
          reverse: reverse,
          bidir: isBidir,
          direction: dirVal,
          target_bandwidth: targetBw
        })
      });
      if (!res.ok) {
        const err = await res.json();
        showToast('iPerf error: ' + (err.message || 'Busy'));
      }
      pollIperfStatus();
    } catch (e) {
      showToast('iPerf run error: ' + e);
      document.getElementById('btn-iperf-run').disabled = false;
      document.getElementById('iperf-running-indicator').style.display = 'none';
    }
  }

  async function pollIperfStatus() {
    if (iperfPollingTimer) clearTimeout(iperfPollingTimer);
    try {
      const res = await fetch('/api/iperf/status');
      if (res.ok) {
        const d = await res.json();
        updateIperfUI(d);
        if (d.is_running) {
          document.getElementById('btn-iperf-run').disabled = true;
          document.getElementById('iperf-running-indicator').style.display = 'inline-block';
          iperfPollingTimer = setTimeout(pollIperfStatus, 1500);
          return;
        }
      }
    } catch (e) {}
    document.getElementById('btn-iperf-run').disabled = false;
    document.getElementById('iperf-running-indicator').style.display = 'none';
  }

  function updateIperfUI(d) {
    if (d.server) {
      const badge = document.getElementById('iperf-server-badge');
      const btn = document.getElementById('btn-iperf-server-toggle');
      const isRunning = Boolean(d.server.is_running || d.server.server_running);
      if (isRunning) {
        badge.textContent = `Daemon: Active (Port ${d.server.port || 5201}${d.server.pid ? ', PID ' + d.server.pid : ''})`;
        badge.style.background = 'rgba(16, 185, 129, 0.15)';
        badge.style.color = '#34d399';
        badge.style.borderColor = '#10b981';
        btn.textContent = '⏹️ Stop iPerf Server';
        btn.className = 'btn-danger';
      } else {
        badge.textContent = 'Daemon: Inactive';
        badge.style.background = 'rgba(148, 163, 184, 0.15)';
        badge.style.color = '#94a3b8';
        badge.style.borderColor = '#475569';
        btn.textContent = '▶️ Start iPerf Server';
        btn.className = 'btn-secondary';
      }
    }
    if (d.latest) {
      const l = d.latest;
      const isOk = (l.status === 'ok');
      const isUdp = ((l.protocol || '').toUpperCase() === 'UDP');
      const isBidir = Boolean(l.is_bidirectional || l.bidir || l.direction === 'bidir');

      const cardDown = document.getElementById('iperf-card-download');
      const cardUp = document.getElementById('iperf-card-upload');
      const resDown = document.getElementById('iperf-res-down');
      const resUp = document.getElementById('iperf-res-up');
      const resLabel = document.getElementById('iperf-res-label');

      if (cardDown && cardUp) {
        if (isOk && isBidir) {
          cardDown.style.display = 'block';
          cardUp.style.display = 'block';
          if (resDown) resDown.textContent = (l.download_mbps != null) ? `${l.download_mbps} Mbps` : '-- Mbps';
          if (resUp) resUp.textContent = (l.upload_mbps != null) ? `${l.upload_mbps} Mbps` : '-- Mbps';
          if (resLabel) resLabel.textContent = l.direction === 'sequential' ? t('iperf_dir_both_short', 'download, then upload') : 'Combined Total';
        } else {
          cardDown.style.display = 'none';
          cardUp.style.display = 'none';
          if (resLabel) {
            resLabel.textContent = (l.direction === 'download') ? 'Download Throughput' : 'Upload Throughput';
          }
        }
      }

      if (document.getElementById('iperf-res-mbps')) {
        document.getElementById('iperf-res-mbps').textContent = (isOk && l.mbps != null) ? `${l.mbps} Mbps` : '-- Mbps';
      }
      if (document.getElementById('iperf-res-retransmits')) {
        let retVal = '--';
        if (isOk) {
          retVal = isUdp ? 'N/A (UDP)' : (l.retransmits != null ? l.retransmits : 0);
        }
        document.getElementById('iperf-res-retransmits').textContent = retVal;
      }
      if (document.getElementById('iperf-res-jitter')) {
        let jitVal = '--';
        if (isOk) {
          jitVal = isUdp ? (l.jitter_ms != null ? `${l.jitter_ms} ms` : '0.00 ms') : 'N/A (TCP)';
        }
        document.getElementById('iperf-res-jitter').textContent = jitVal;
      }
      if (document.getElementById('iperf-res-loss')) {
        let lossVal = '--%';
        if (isOk) {
          lossVal = isUdp ? (l.lost_percent != null ? `${l.lost_percent}%` : '0.00%') : '0% (TCP)';
        }
        document.getElementById('iperf-res-loss').textContent = lossVal;
      }
      if (document.getElementById('iperf-result-ts')) {
        const tsVal = l.timestamp ? new Date(l.timestamp).toLocaleString() : (l.ts ? new Date(l.ts * 1000).toLocaleString() : '--');
        document.getElementById('iperf-result-ts').textContent = tsVal;
      }
      if (document.getElementById('iperf-raw-log')) {
        if (isOk && l.raw_output) {
          document.getElementById('iperf-raw-log').textContent = l.raw_output;
        } else if (l.error) {
          document.getElementById('iperf-raw-log').innerHTML = `<span style="color: #f87171; font-weight: bold;">Error: ${escapeHtml(l.error)}</span>
${l.cmd ? 'Command: ' + escapeHtml(l.cmd) : ''}`;
        } else {
          document.getElementById('iperf-raw-log').textContent = l.raw_output || 'No output available';
        }
      }
    }
  }

  async function toggleIperfServer() {
    const badge = document.getElementById('iperf-server-badge');
    const isRunning = badge.textContent.includes('Active');
    const action = isRunning ? 'stop' : 'start';
    const port = parseInt(document.getElementById('iperf-port').value) || 5201;
    showToast(isRunning ? 'Stopping iPerf3 server...' : 'Starting iPerf3 server on port ' + port + '...');
    try {
      const res = await fetch('/api/iperf/server', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: action, port: port })
      });
      if (res.ok) {
        const d = await res.json();
        showToast(d.message || 'iPerf server updated');
        loadIperfStatus();
      }
    } catch (e) {
      showToast('Error toggling server: ' + e);
    }
  }

  async function loadIperfStatus() {
    try {
      const res = await fetch('/api/iperf/status');
      if (res.ok) {
        const d = await res.json();
        updateIperfUI(d);
      }
    } catch (e) {}
  }

  // ==========================================
  // Public iPerf3 Servers Browser & Probing
  // ==========================================
  let cachedPublicServers = [];
  let currentServerPickContext = 'client';
  let activeContinentFilter = 'all';

  function openPublicServersModal(ctx) {
    currentServerPickContext = ctx || 'client';
    const modal = document.getElementById('iperf-servers-modal');
    if (modal) modal.style.display = 'flex';
    if (!cachedPublicServers || cachedPublicServers.length === 0) {
      loadPublicServers(false);
    } else {
      renderPublicServers(cachedPublicServers);
    }
  }

  function closePublicServersModal() {
    const modal = document.getElementById('iperf-servers-modal');
    if (modal) modal.style.display = 'none';
  }

  async function loadPublicServers(forceRefresh) {
    const listEl = document.getElementById('iperf-modal-server-list');
    const badgeEl = document.getElementById('iperf-modal-count-badge');
    const srcEl = document.getElementById('iperf-modal-source-label');
    if (listEl) listEl.innerHTML = '<div style="text-align: center; color: #38bdf8; padding: 30px 0;">🌐 Fetching live iPerf3 servers online... please wait.</div>';
    if (badgeEl) badgeEl.innerText = 'Loading...';

    try {
      const url = '/api/iperf/servers' + (forceRefresh ? '?refresh=1' : '');
      const res = await fetch(url);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      cachedPublicServers = data.servers || [];
      if (badgeEl) badgeEl.innerText = `${cachedPublicServers.length} servers`;
      if (srcEl) srcEl.innerText = `Source: ${data.source || 'online'} (${data.cached ? 'cached' : 'live'})`;
      renderPublicServers(cachedPublicServers);
    } catch (e) {
      if (listEl) listEl.innerHTML = `<div style="text-align: center; color: #ef4444; padding: 30px 0;">Failed to load servers: ${escapeHtml(e.message)}</div>`;
      if (badgeEl) badgeEl.innerText = 'Error';
    }
  }

  function filterPublicContinent(cont, btnEl) {
    activeContinentFilter = cont;
    document.querySelectorAll('#iperf-modal-continents button').forEach(b => b.classList.remove('active-filter'));
    if (btnEl) btnEl.classList.add('active-filter');
    renderPublicServers(cachedPublicServers);
  }

  function onPublicServerSearch(query) {
    renderPublicServers(cachedPublicServers);
  }

  function renderPublicServers(servers) {
    const listEl = document.getElementById('iperf-modal-server-list');
    if (!listEl) return;
    const q = (document.getElementById('iperf-modal-search') ? document.getElementById('iperf-modal-search').value : '').trim().toLowerCase();

    const filtered = (servers || []).filter(s => {
      if (activeContinentFilter !== 'all') {
        if (activeContinentFilter === 'Other') {
          if (['Europe', 'North America', 'Asia'].includes(s.continent)) return false;
        } else if (s.continent !== activeContinentFilter) {
          return false;
        }
      }
      if (q) {
        const text = `${s.host} ${s.site || ''} ${s.country || ''} ${s.provider || ''} ${s.continent || ''}`.toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });

    if (filtered.length === 0) {
      listEl.innerHTML = '<div style="text-align: center; color: #94a3b8; padding: 30px 0;">No matching servers found for your filter.</div>';
      return;
    }

    listEl.innerHTML = filtered.map((s, idx) => {
      const flag = getFlagEmoji(s.country);
      const speedBadge = s.speed ? `<span style="font-size: 11px; background: rgba(56, 189, 248, 0.2); color: #38bdf8; padding: 2px 7px; border-radius: 4px; margin-left: 6px;">${escapeHtml(s.speed)}</span>` : '';
      const safeHost = escapeHtml(s.host);
      const safeSite = escapeHtml(s.site || s.country || 'Global');
      const safeProvider = escapeHtml(s.provider || '');
      const safePortRange = escapeHtml(s.port_range || String(s.port));
      return `
        <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;">
          <div style="display: flex; align-items: center; gap: 12px; flex: 1; min-width: 250px;">
            <div style="font-size: 24px;">${flag}</div>
            <div>
              <div style="font-size: 13.5px; font-weight: 700; color: #ffffff;">
                ${safeSite} <span style="font-size: 12px; color: #38bdf8; font-weight: normal;">• ${safeProvider}</span>
                ${speedBadge}
              </div>
              <div style="font-size: 12px; color: #94a3b8; font-family: monospace; margin-top: 2px;">
                ${safeHost}:${safePortRange}
              </div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span id="probe-badge-${idx}" style="font-size: 11.5px; color: #94a3b8; min-width: 70px; text-align: right;"></span>
            <button type="button" class="btn-secondary" style="font-size: 11.5px; padding: 5px 11px;" onclick="probeServerModal(${jsArg(s.host)}, ${jsArg(s.port)}, 'probe-badge-${idx}', this)">⚡ Ping</button>
            <button type="button" class="btn-primary" style="font-size: 11.5px; padding: 5px 12px;" onclick="selectPublicServer(${jsArg(s.host)}, ${jsArg(s.port)}, ${jsArg(s.provider || '')}, ${jsArg(s.site || s.country || 'Global')}, ${jsArg(s.speed || '')})">🎯 Select Server</button>
          </div>
        </div>
      `;
    }).join('');
  }

  function getFlagEmoji(countryCode) {
    if (!countryCode || countryCode.length !== 2) return '🌐';
    try {
      const codePoints = countryCode
        .toUpperCase()
        .split('')
        .map(char => 127397 + char.charCodeAt(0));
      return String.fromCodePoint(...codePoints);
    } catch (e) {
      return '🌐';
    }
  }


  async function probeServerModal(host, port, badgeId, btnEl) {
    const badge = document.getElementById(badgeId);
    if (badge) badge.innerHTML = '<span style="color:#fbbf24;">...</span>';
    if (btnEl) btnEl.disabled = true;
    try {
      const res = await fetch(`/api/iperf/probe?host=${encodeURIComponent(host)}&port=${port}`);
      if (res.ok) {
        const d = await res.json();
        if (d.reachable) {
          if (badge) badge.innerHTML = `<span style="color:#34d399; font-weight:600;">✅ ${escapeHtml(d.rtt_ms)}ms</span>`;
        } else {
          if (badge) badge.innerHTML = `<span style="color:#f87171;" title="${escapeHtml(d.error || 'Timeout')}">❌ Offline</span>`;
        }
      }
    } catch (e) {
      if (badge) badge.innerHTML = '<span style="color:#f87171;">❌ Error</span>';
    } finally {
      if (btnEl) btnEl.disabled = false;
    }
  }

  function selectPublicServer(host, port, provider, site, speed) {
    if (currentServerPickContext === 'sched') {
      const h = document.getElementById('sched-iperf-host');
      const p = document.getElementById('sched-iperf-port');
      const info = document.getElementById('sched-iperf-resolved-info');
      if (h) h.value = host;
      if (p) p.value = port;
      if (info) info.innerHTML = `🎯 <b>${escapeHtml(site || provider || host)}</b> <code style="color:#94a3b8;">(${escapeHtml(host)}:${escapeHtml(port)})</code> ${speed ? '[' + escapeHtml(speed) + ']' : ''}`;
      markSchedDirty();
      showToast(`Selected scheduled iPerf3 server: ${host}:${port}`);
    } else {
      const h = document.getElementById('iperf-host');
      const p = document.getElementById('iperf-port');
      const badge = document.getElementById('iperf-selected-server-badge');
      if (h) h.value = host;
      if (p) p.value = port;
      if (badge) {
        badge.style.display = 'block';
        badge.innerHTML = `🎯 <b>Selected Server:</b> ${escapeHtml(site)} • ${escapeHtml(provider)} (<code>${escapeHtml(host)}:${escapeHtml(port)}</code>) ${speed ? `[<b>${escapeHtml(speed)}</b>]` : ''}`;
      }
      showToast(`Selected iPerf3 target: ${host}:${port}`);
    }
    closePublicServersModal();
  }

  // Saves the host and port from the iPerf3 tab as the server of scheduled iPerf3 tests.
  async function saveIperfForAutomatic() {
    const host = (document.getElementById('iperf-host').value || '').trim();
    const port = parseInt(document.getElementById('iperf-port').value) || 5201;
    if (!host) { showToast(t('iperf_need_host', 'Enter or pick an iPerf3 server first.')); return; }
    const btn = document.getElementById('btn-iperf-save-auto');
    if (btn) btn.disabled = true;
    try {
      let reachable = false;
      try {
        const pr = await fetch(`/api/iperf/probe?host=${encodeURIComponent(host)}&port=${port}`);
        if (pr.ok) reachable = !!(await pr.json()).reachable;
      } catch (e) {}
      const res = await fetch('/api/speedtest/schedule', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          iperf_target_host: host, iperf_port: port,
          iperf_duration: parseInt(document.getElementById('iperf-duration').value) || 10,
          iperf_protocol: document.getElementById('iperf-protocol').value,
          iperf_parallel: parseInt(document.getElementById('iperf-parallel').value) || 4,
          iperf_direction: ({ 'false': 'upload', 'true': 'download', 'bidir': 'bidir', 'seq': 'both' })[document.getElementById('iperf-reverse').value] || 'both',
        })
      });
      if (!res.ok) { showToast(t('iperf_save_failed', 'Could not save the iPerf3 server.')); return; }
      const sh = document.getElementById('sched-iperf-host');
      const sp = document.getElementById('sched-iperf-port');
      if (sh) sh.value = host;
      if (sp) sp.value = port;
      showIperfAutoCurrent(host, port, (await res.json()).iperf_auto);
      showToast(reachable
        ? t('iperf_saved_ok', '✅ Saved: automatic iPerf3 tests use {host}:{port}.').replace('{host}', host).replace('{port}', port)
        : t('iperf_saved_unreachable', '⚠️ Saved {host}:{port}, but it does not answer now; automatic iPerf3 tests wait until it does.').replace('{host}', host).replace('{port}', port));
    } catch (e) {
      showToast('Error: ' + e);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  let iperfExtraServers = [];

  function renderIperfExtraList() {
    const el = document.getElementById('iperf-extra-list');
    if (!el) return;
    if (!iperfExtraServers.length) { el.textContent = ''; return; }
    el.innerHTML = escapeHtml(t('iperf_extra_label', 'Also tested one after the other:')) + ' ' + iperfExtraServers.map((sv, i) =>
      `<code>${escapeHtml(sv)}</code> <button type="button" class="btn-secondary" style="padding: 0 6px; font-size: 11px;" aria-label="${escapeHtml(t('remove', 'Remove'))} ${escapeHtml(sv)}" onclick="removeIperfExtraServer(${i})">✖</button>`
    ).join(' ');
  }

  async function saveIperfExtraServers() {
    const res = await fetch('/api/speedtest/schedule', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ iperf_extra_servers: iperfExtraServers.join(', ') }) });
    if (res.ok) {
      const d = await res.json();
      iperfExtraServers = ((d.iperf_auto && d.iperf_auto.extra_servers) || '').split(',').map(x => x.trim()).filter(Boolean);
      renderIperfExtraList();
    }
    return res.ok;
  }

  async function addIperfExtraServer() {
    const host = (document.getElementById('iperf-host').value || '').trim();
    const port = parseInt(document.getElementById('iperf-port').value) || 5201;
    if (!host) { showToast(t('iperf_need_host', 'Enter or pick an iPerf3 server first.')); return; }
    const item = host + ':' + port;
    if (!iperfExtraServers.includes(item)) iperfExtraServers.push(item);
    showToast(await saveIperfExtraServers() ? t('iperf_extra_added', 'Added to the automatic list: {server}').replace('{server}', item)
                                            : t('iperf_save_failed', 'Could not save the iPerf3 server.'));
  }

  async function removeIperfExtraServer(i) {
    iperfExtraServers.splice(i, 1);
    await saveIperfExtraServers();
  }

  function showIperfAutoCurrent(host, port, auto) {
    const el = document.getElementById('iperf-auto-current');
    if (!el) return;
    let txt = host ? t('iperf_auto_current', 'Automatic tests use: {server}').replace('{server}', host + ':' + (port || 5201)) : '';
    if (host && auto) {
      const dirs = { both: t('iperf_dir_both_short', 'download, then upload'), download: t('iperf_dir_down_short', 'download'),
                     upload: t('iperf_dir_up_short', 'upload'), bidir: t('iperf_dir_bidir_short', 'both ways at once') };
      txt += ` · ${auto.parallel}× ${String(auto.protocol || 'tcp').toUpperCase()}, ${auto.duration} s, ${dirs[auto.direction] || auto.direction}`;
    }
    el.textContent = txt;
    if (auto && auto.direction && !window.iperfDirSynced) {
      const sel = document.getElementById('iperf-reverse');
      const map = { both: 'seq', download: 'true', upload: 'false', bidir: 'bidir' };
      if (sel && document.activeElement !== sel && map[auto.direction]) sel.value = map[auto.direction];
      const par = document.getElementById('iperf-parallel');
      if (par && auto.parallel && Array.from(par.options).some(o => o.value == auto.parallel)) par.value = auto.parallel;
      window.iperfDirSynced = true;
    }
    if (auto && auto.extra_servers !== undefined) {
      iperfExtraServers = String(auto.extra_servers || '').split(',').map(x => x.trim()).filter(Boolean);
      renderIperfExtraList();
    }
  }

  async function probeCurrentIperfServer() {
    const host = (document.getElementById('iperf-host').value || '').trim();
    const port = parseInt(document.getElementById('iperf-port').value) || 5201;
    if (!host) {
      showToast('Please enter an iPerf3 target host first.');
      return;
    }
    showToast(`Pinging ${host}:${port}...`);
    try {
      const res = await fetch(`/api/iperf/probe?host=${encodeURIComponent(host)}&port=${port}`);
      if (res.ok) {
        const d = await res.json();
        if (d.reachable) {
          showToast(`✅ ${host}:${port} is reachable! Ping (RTT): ${d.rtt_ms} ms`);
        } else {
          showToast(`❌ Cannot connect to ${host}:${port}: ${d.error || 'Timed out'}`);
        }
      }
    } catch (e) {
      showToast('Error testing connection: ' + e);
    }
  }

  // ==========================================
  // Traceroute Engine (Live Streaming & Protocol Selection)
  // ==========================================
  let traceroutePollingTimer = null;
  let latestTracerouteHopsData = [];
  let latestTracerouteMeta = null;

  function setTracerouteTarget(target) {
    const el = document.getElementById('traceroute-target');
    if (el) {
      el.value = target;
      el.focus();
    }
  }

  async function runTracerouteTest() {
    const target = (document.getElementById('traceroute-target').value || '').trim() || '1.1.1.1';
    const maxHops = parseInt(document.getElementById('traceroute-max-hops').value) || 30;
    const methodEl = document.getElementById('traceroute-method');
    const method = methodEl ? methodEl.value : 'icmp';
    const ipVerEl = document.getElementById('traceroute-ip-version');
    const ipVersion = ipVerEl ? ipVerEl.value : 'auto';

    const btnRun = document.getElementById('btn-traceroute-run');
    const btnStop = document.getElementById('btn-traceroute-stop');
    const indicator = document.getElementById('traceroute-indicator');

    if (btnRun) btnRun.disabled = true;
    if (btnStop) btnStop.style.display = 'inline-block';
    if (indicator) indicator.style.display = 'inline-block';

    const startedMsg = t('traceroute_toast_started', 'Starting visual traceroute to {target}...').replace('{target}', target);
    showToast(startedMsg);

    try {
      const res = await fetch('/api/traceroute/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host: target, max_hops: maxHops, method: method, ip_version: ipVersion })
      });
      if (!res.ok) {
        const err = await res.json();
        showToast('Traceroute error: ' + (err.message || 'Busy'));
      }
      pollTracerouteStatus();
    } catch (e) {
      showToast('Traceroute failed: ' + e);
      if (btnRun) btnRun.disabled = false;
      if (btnStop) btnStop.style.display = 'none';
      if (indicator) indicator.style.display = 'none';
    }
  }

  async function stopTracerouteTest() {
    try {
      await fetch('/api/traceroute/stop', { method: 'POST' });
      showToast(t('traceroute_toast_stopped', 'Traceroute stopped.'));
    } catch (e) {
      showToast('Error stopping traceroute: ' + e);
    }
  }

  async function pollTracerouteStatus() {
    if (traceroutePollingTimer) clearTimeout(traceroutePollingTimer);
    try {
      const res = await fetch('/api/traceroute/status');
      if (res.ok) {
        const d = await res.json();
        latestTracerouteMeta = d.latest;
        if (d.latest && d.latest.hops) {
          latestTracerouteHopsData = d.latest.hops;
          renderTracerouteHops(d.latest.hops, d.latest);
        }
        if (d.is_running) {
          const btnRun = document.getElementById('btn-traceroute-run');
          const btnStop = document.getElementById('btn-traceroute-stop');
          const indicator = document.getElementById('traceroute-indicator');
          if (btnRun) btnRun.disabled = true;
          if (btnStop) btnStop.style.display = 'inline-block';
          if (indicator) indicator.style.display = 'inline-block';

          traceroutePollingTimer = setTimeout(pollTracerouteStatus, 1000);
          return;
        }
      }
    } catch (e) {}

    const btnRun = document.getElementById('btn-traceroute-run');
    const btnStop = document.getElementById('btn-traceroute-stop');
    const indicator = document.getElementById('traceroute-indicator');
    if (btnRun) btnRun.disabled = false;
    if (btnStop) btnStop.style.display = 'none';
    if (indicator) indicator.style.display = 'none';
  }

  function renderTracerouteHops(hops, meta) {
    const tbody = document.getElementById('traceroute-table-body');
    if (!tbody) return;

    if (!hops || hops.length === 0) {
      tbody.innerHTML = '<tr><td colspan="11" style="text-align:center; color: var(--text-muted);">' + t('no_hops_captured', 'No hops captured.') + '</td></tr>';
      return;
    }

    // Update Summary Cards if meta is available
    if (meta) {
      const targetEl = document.getElementById('tr-stat-target');
      const hopsEl = document.getElementById('tr-stat-hops');
      const rttEl = document.getElementById('tr-stat-rtt');
      const lossEl = document.getElementById('tr-stat-loss');
      const carriersEl = document.getElementById('tr-stat-carriers');

      if (targetEl) targetEl.textContent = meta.target + (meta.resolved_ip && meta.resolved_ip !== meta.target ? ' (' + meta.resolved_ip + ')' : '');
      if (hopsEl) hopsEl.textContent = (meta.total_hops || hops.length) + (meta.destination_reached ? ' 🎯' : '');
      if (rttEl) rttEl.textContent = meta.dest_rtt_ms !== null && meta.dest_rtt_ms !== undefined ? meta.dest_rtt_ms + ' ms' : '--';
      if (lossEl) {
        const lossRate = meta.loss_pct !== undefined ? meta.loss_pct : (meta.loss_hops ? Math.round(meta.loss_hops / hops.length * 100) : 0);
        lossEl.textContent = lossRate + '%';
        lossEl.style.color = lossRate === 0 ? '#10b981' : (lossRate < 30 ? '#f59e0b' : '#ef4444');
      }
      if (carriersEl) {
        const carr = meta.carriers || [];
        carriersEl.textContent = carr.length > 0 ? carr.join(' → ') : '--';
        carriersEl.title = carr.join(', ');
      }
    }

    // Determine max RTT for scaling the bar
    let maxRtt = 20;
    hops.forEach(h => {
      if (h.rtt_ms && h.rtt_ms > maxRtt) maxRtt = h.rtt_ms;
    });

    let html = '';
    hops.forEach(h => {
      const rtts = h.rtts || [];
      const rtt1 = rtts[0] !== undefined ? `${rtts[0]} ms` : (h.rtt_ms !== null && h.rtt_ms !== undefined ? `${h.rtt_ms} ms` : '*');
      const rtt2 = rtts[1] !== undefined ? `${rtts[1]} ms` : '*';
      const rtt3 = rtts[2] !== undefined ? `${rtts[2]} ms` : '*';
      const isLoss = h.ip === '*' || (rtts.length === 0 && h.rtt_ms === null);
      const statusPill = isLoss
        ? '<span class="badge-pill" style="background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid #ef4444; font-size: 11px;">Packet Loss (*)</span>'
        : '<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981; font-size: 11px;">OK</span>';

      // Hop Type Pill
      let typePill = '';
      const hType = h.hop_type || (h.ip === '*' ? 'timeout' : 'public');
      if (hType === 'target') {
        typePill = '<span class="badge" style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid #38bdf8; font-size: 11px; padding: 2px 6px;">🎯 Target</span>';
      } else if (hType === 'lan') {
        typePill = '<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981; font-size: 11px; padding: 2px 6px;">🏠 LAN</span>';
      } else if (hType === 'cgnat') {
        typePill = '<span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; font-size: 11px; padding: 2px 6px;">📡 CGNAT</span>';
      } else if (hType === 'timeout') {
        typePill = '<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; font-size: 11px; padding: 2px 6px;">⚠️ Timeout</span>';
      } else {
        typePill = '<span class="badge" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569; font-size: 11px; padding: 2px 6px;">🌐 Public</span>';
      }

      // Country with flag emoji and badge
      let countryHtml = '--';
      if (h.ip !== '*' && h.country && h.country !== '--') {
        const flag = h.flag || '🌐';
        const cName = escapeHtml(h.country);
        const cCode = h.country_code ? `<span class="badge" style="font-size: 11px; padding: 2px 5px; margin-left: 4px; background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);">${escapeHtml(h.country_code)}</span>` : '';
        countryHtml = `<span style="font-size: 14px; margin-right: 4px;">${flag}</span> <span style="font-weight: 600; color: #f1f5f9;">${cName}</span> ${cCode}`;
      } else if (h.ip === '*') {
        countryHtml = '<span style="color: #64748b;">--</span>';
      }

      // Provider / Carrier / AS
      let ispHtml = '--';
      if (h.ip !== '*' && h.isp && h.isp !== '--') {
        const ispName = escapeHtml(h.isp);
        const asInfo = h.as ? `<span style="color: #94a3b8; font-size: 11px; margin-left: 4px; font-family: monospace;">(${escapeHtml(h.as)})</span>` : '';
        ispHtml = `<span style="font-weight: 600; color: #38bdf8;">${ispName}</span> ${asInfo}`;
      } else if (h.ip === '*') {
        ispHtml = '<span style="color: #64748b;">-- (Silent Hop / Timeout)</span>';
      }

      // Latency Bar Graph
      let latencyBarHtml = '<span style="color: #64748b; font-size: 11px;">--</span>';
      if (h.rtt_ms !== null && h.rtt_ms !== undefined) {
        const pct = Math.min(100, Math.max(8, Math.round((h.rtt_ms / maxRtt) * 100)));
        let barColor = '#10b981';
        if (h.rtt_ms > 80) barColor = '#ef4444';
        else if (h.rtt_ms > 40) barColor = '#f59e0b';
        else if (h.rtt_ms > 20) barColor = '#38bdf8';

        latencyBarHtml = `
          <div style="display: flex; align-items: center; gap: 6px;">
            <div style="flex: 1; background: #1e293b; border-radius: 3px; height: 8px; overflow: hidden;">
              <div style="width: ${pct}%; background: ${barColor}; height: 100%; border-radius: 3px; transition: width 0.3s ease;"></div>
            </div>
            <span style="font-size: 11px; font-family: monospace; color: ${barColor}; font-weight: 600; min-width: 48px; text-align: right;">${escapeHtml(h.rtt_ms)} ms</span>
          </div>`;
      }

      html += `<tr>
        <td style="font-weight: 700; color: #38bdf8;">${escapeHtml(h.hop)}</td>
        <td>${typePill}</td>
        <td style="font-family: monospace; font-weight: 600; color: #e2e8f0;">${escapeHtml(h.ip)}</td>
        <td style="color: #cbd5e1; font-family: monospace; font-size: 12px;">${escapeHtml(h.hostname || h.host || '--')}</td>
        <td>${countryHtml}</td>
        <td>${ispHtml}</td>
        <td style="font-family: monospace; color: #94a3b8;">${rtt1}</td>
        <td style="font-family: monospace; color: #94a3b8;">${rtt2}</td>
        <td style="font-family: monospace; color: #94a3b8;">${rtt3}</td>
        <td>${latencyBarHtml}</td>
        <td>${statusPill}</td>
      </tr>`;
    });
    tbody.innerHTML = html;
  }

  function copyTracerouteText() {
    if (!latestTracerouteHopsData || latestTracerouteHopsData.length === 0) {
      showToast(t('no_hops_captured', 'No hops captured.'));
      return;
    }
    let text = '=== NetworkMeasureBox Traceroute Results ===\n';
    if (latestTracerouteMeta) {
      text += `Target: ${latestTracerouteMeta.target} (${latestTracerouteMeta.resolved_ip || '--'})\n`;
      text += `Method: ${(latestTracerouteMeta.method || 'icmp').toUpperCase()}\n`;
      text += `Total Hops: ${latestTracerouteMeta.total_hops || latestTracerouteHopsData.length}\n`;
      text += `Target Latency: ${latestTracerouteMeta.dest_rtt_ms || '--'} ms\n`;
      text += `Carriers: ${(latestTracerouteMeta.carriers || []).join(' -> ') || '--'}\n\n`;
    }
    text += 'Hop | IP Address       | Hostname                       | RTT     | Country | Carrier\n';
    text += '----+------------------+--------------------------------+---------+---------+-------------------\n';
    latestTracerouteHopsData.forEach(h => {
      const hopNo = String(h.hop).padStart(3, ' ');
      const ip = (h.ip || '*').padEnd(16, ' ');
      const host = (h.hostname || h.host || '--').slice(0, 30).padEnd(30, ' ');
      const rtt = (h.rtt_ms !== null && h.rtt_ms !== undefined ? `${h.rtt_ms} ms` : '*').padEnd(7, ' ');
      const country = (h.country_code || h.country || '--').slice(0, 7).padEnd(7, ' ');
      const carrier = (h.isp || '--').slice(0, 25);
      text += `${hopNo} | ${ip} | ${host} | ${rtt} | ${country} | ${carrier}\n`;
    });

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        showToast(t('traceroute_toast_copied', 'Route copied to clipboard!'));
      }).catch(() => {
        _fallbackCopy(text);
      });
    } else {
      _fallbackCopy(text);
    }
  }

  function _fallbackCopy(str) {
    const el = document.createElement('textarea');
    el.value = str;
    document.body.appendChild(el);
    el.select();
    document.execCommand('copy');
    document.body.removeChild(el);
    showToast(t('traceroute_toast_copied', 'Route copied to clipboard!'));
  }

  async function loadTracerouteStatus() {
    try {
      const res = await fetch('/api/traceroute/status');
      if (res.ok) {
        const d = await res.json();
        latestTracerouteMeta = d.latest;
        if (d.latest && d.latest.hops) {
          latestTracerouteHopsData = d.latest.hops;
          renderTracerouteHops(d.latest.hops, d.latest);
        }
        if (d.is_running) {
          pollTracerouteStatus();
        }
      }
    } catch (e) {}
  }

  // ==========================================
  // OONI Probe Censorship & Internet Freedom
  // ==========================================
  let ooniPollingTimer = null;

  async function toggleOoni(enabled) {
    try {
      const res = await fetch('/api/ooni/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: enabled })
      });
      if (!res.ok) throw new Error(res.status);
      if (!enabled) showToast(t('ooni_off_notice', 'OONI Probe is switched off. Turn it on to run tests.'));
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
    loadOoniStatus();
  }

  async function loadOoniStatus() {
    try {
      const res = await fetch('/api/ooni/status');
      const ooniToggle = document.getElementById('ooni-enabled-toggle');
      if (ooniToggle && res.ok) ooniToggle.checked = !!(await res.clone().json()).enabled;
      if (!res.ok) return;
      const d = await res.json();

      // Badges
      const instBadge = document.getElementById('ooni-installed-badge');
      if (instBadge) {
        if (d.installed) {
          instBadge.textContent = 'OONI Probe v' + (d.version || '3.31.0');
          instBadge.style.color = '#38bdf8';
          instBadge.style.borderColor = 'rgba(56, 189, 248, 0.4)';
        } else {
          instBadge.textContent = 'OONI Probe Not Installed';
          instBadge.style.color = '#ef4444';
          instBadge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        }
      }

      const verdBadge = document.getElementById('ooni-verdict-badge');
      if (verdBadge) {
        if (d.freedom_verdict === 'clean') {
          verdBadge.innerHTML = '🟢 Clean / No Censorship Detected';
          verdBadge.style.color = '#10b981';
          verdBadge.style.background = 'rgba(16, 185, 129, 0.15)';
          verdBadge.style.borderColor = 'rgba(16, 185, 129, 0.3)';
        } else {
          verdBadge.innerHTML = '🔴 ' + d.total_anomalies_historical + ' Anomalies / Blocks Detected';
          verdBadge.style.color = '#ef4444';
          verdBadge.style.background = 'rgba(239, 68, 68, 0.15)';
          verdBadge.style.borderColor = 'rgba(239, 68, 68, 0.3)';
        }
      }

      // Running State
      const ind = document.getElementById('ooni-running-indicator');
      const msg = document.getElementById('ooni-running-msg');
      const bar = document.getElementById('ooni-progress-bar');
      const pct = document.getElementById('ooni-progress-txt');

      if (d.running) {
        if (ind) ind.style.display = 'block';
        if (msg) msg.textContent = 'Running OONI Probe test [' + (d.current_test || 'test') + ']...';
        const p = d.progress_percent || 10;
        if (bar) bar.style.width = p + '%';
        if (pct) pct.textContent = p + '%';
        setOoniButtonsDisabled(true);
        if (ooniPollingTimer) clearTimeout(ooniPollingTimer);
        ooniPollingTimer = setTimeout(loadOoniStatus, 2000);
      } else {
        if (ind) ind.style.display = 'none';
        setOoniButtonsDisabled(false);
      }

      // Latest Findings Box
      if (d.latest && d.latest.findings && d.latest.findings.length > 0) {
        const detBox = document.getElementById('ooni-latest-detail-box');
        const detTxt = document.getElementById('ooni-latest-findings');
        if (detBox && detTxt) {
          detBox.style.display = 'block';
          detTxt.innerHTML = d.latest.findings.map(f => {
            const isWarn = f.includes('Blocked') || f.includes('Anomalies') || f.includes('generic_timeout') || f.includes('connection_refused');
            const col = isWarn ? '#f59e0b' : '#38bdf8';
            return `<div style="color: ${col}; margin-bottom: 2px;">• ${escapeHtml(f)}</div>`;
          }).join('');
        }
      }

      // History Table
      renderOoniHistory(d.history || []);
    } catch (e) {
      console.error('loadOoniStatus error:', e);
    }
  }

  function setOoniButtonsDisabled(disabled) {
    ['btn-ooni-websites', 'btn-ooni-middlebox', 'btn-ooni-im', 'btn-ooni-circumvention'].forEach(id => {
      const b = document.getElementById(id);
      if (b) b.disabled = disabled;
    });
  }

  async function runOoniTest(testType) {
    let url = null;
    if (testType === 'websites') {
      const inp = document.getElementById('ooni-custom-url');
      if (inp && inp.value.trim()) {
        url = inp.value.trim();
      }
    }

    setOoniButtonsDisabled(true);
    const ind = document.getElementById('ooni-running-indicator');
    const msg = document.getElementById('ooni-running-msg');
    if (ind) ind.style.display = 'block';
    if (msg) msg.textContent = 'Initiating OONI Probe [' + testType + '] test...';
    showToast('Starting OONI Probe ' + testType + ' test...');

    try {
      const res = await fetch('/api/ooni/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ test_type: testType, url: url }),
      });
      const d = await res.json();
      if (!res.ok) {
        showToast('OONI error: ' + (d.message || 'Busy'));
      }
      setTimeout(loadOoniStatus, 1500);
    } catch (e) {
      showToast('OONI request failed: ' + e);
      setOoniButtonsDisabled(false);
      if (ind) ind.style.display = 'none';
    }
  }

  function renderOoniHistory(history) {
    const tbody = document.getElementById('ooni-history-table-body');
    const netLbl = document.getElementById('ooni-network-label');
    if (!tbody) return;

    if (!history || history.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No OONI tests recorded yet. Click one of the test buttons above to run your first censorship check.</td></tr>';
      return;
    }

    if (netLbl && history[0]) {
      netLbl.textContent = 'Monitored ASN: AS' + history[0].asn + ' (' + history[0].network_name + ', ' + history[0].country_code + ')';
    }

    let html = '';
    history.forEach(item => {
      const anom = item.anomaly_count || 0;
      const isClean = anom === 0;
      const verdBadge = isClean
        ? '<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">🟢 Clean</span>'
        : `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">🔴 ${anom} Anomalies</span>`;

      let icon = '🌐';
      if (item.name === 'middlebox') icon = '📦';
      else if (item.name === 'im') icon = '💬';
      else if (item.name === 'circumvention') icon = '🧅';

      const timeStr = item.start_time ? item.start_time.substring(0, 19).replace('T', ' ') + ' UTC' : '--';

      html += `<tr>
        <td style="font-weight: 700;">#${escapeHtml(item.id)}</td>
        <td style="font-weight: 600;">${icon} ${escapeHtml(item.name)}</td>
        <td>AS${escapeHtml(item.asn || '--')} (${escapeHtml(item.network_name || 'ISP')})</td>
        <td style="color: var(--text-muted); font-size: 12px;">${timeStr}</td>
        <td style="font-weight: 700; color: ${isClean ? '#10b981' : '#ef4444'};">${anom}</td>
        <td>${item.total_count || 1}</td>
        <td>${verdBadge}</td>
        <td>
          <button type="button" class="btn-secondary" style="font-size: 11px; padding: 4px 10px;" onclick="openOoniRunDetails(${jsArg(item.id)})">
            🔍 Details
          </button>
        </td>
      </tr>`;
    });
    tbody.innerHTML = html;
  }

  // ==========================================
  // OONI Measurement Details & Deep Inspector
  // ==========================================
  let currentOoniMeasurements = [];
  let currentOoniFilter = 'all';
  let currentOoniRawJson = null;

  async function openOoniRunDetails(runId) {
    const modal = document.getElementById('ooni-details-modal');
    const spinner = document.getElementById('ooni-measurements-spinner');
    const container = document.getElementById('ooni-measurements-container');
    const deepBox = document.getElementById('ooni-deep-inspect-box');
    const title = document.getElementById('ooni-modal-title');
    const subtitle = document.getElementById('ooni-modal-subtitle');
    const badge = document.getElementById('ooni-modal-anom-badge');
    const searchBox = document.getElementById('ooni-search-box');

    if (!modal) return;
    modal.style.display = 'flex';
    if (spinner) spinner.style.display = 'block';
    if (container) container.style.display = 'none';
    if (deepBox) deepBox.style.display = 'none';
    if (searchBox) searchBox.value = '';
    currentOoniFilter = 'all';
    updateOoniFilterButtons();

    try {
      const res = await fetch(`/api/ooni/run?id=${runId}`);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      const run = data.summary || data.run || {};
      const measurements = data.measurements || [];
      currentOoniMeasurements = measurements;

      if (title) {
        let icon = '🌐';
        const testName = run.name || measurements[0]?.test_group || measurements[0]?.test_name || 'Test';
        if (testName.includes('middlebox')) icon = '📦';
        else if (testName.includes('im')) icon = '💬';
        else if (testName.includes('circumvention')) icon = '🧅';
        title.innerHTML = `${icon} OONI Run #${run.run_id || run.id || runId} (${escapeHtml(testName)})`;
      }

      const anomCount = data.anomalies !== undefined ? data.anomalies : (run.anomaly_count !== undefined ? run.anomaly_count : measurements.filter(m => m.is_anomaly).length);
      const cleanCount = measurements.length - anomCount;

      if (badge) {
        if (anomCount > 0) {
          badge.className = 'badge';
          badge.style.background = 'rgba(239, 68, 68, 0.2)';
          badge.style.color = '#ef4444';
          badge.style.border = '1px solid rgba(239, 68, 68, 0.4)';
          badge.textContent = `🔴 ${anomCount} Anomalies`;
        } else {
          badge.className = 'badge';
          badge.style.background = 'rgba(16, 185, 129, 0.2)';
          badge.style.color = '#10b981';
          badge.style.border = '1px solid rgba(16, 185, 129, 0.4)';
          badge.textContent = '🟢 All Clean';
        }
      }

      if (subtitle) {
        const timeStr = run.start_time ? run.start_time.substring(0, 19).replace('T', ' ') + ' UTC' : '--';
        subtitle.textContent = `Network: AS${run.asn || '--'} (${run.network_name || 'ISP'}) • Time: ${timeStr} • Total Targets: ${measurements.length}`;
      }

      const cntAll = document.getElementById('ooni-cnt-all');
      const cntAnom = document.getElementById('ooni-cnt-anom');
      const cntClean = document.getElementById('ooni-cnt-clean');
      if (cntAll) cntAll.textContent = measurements.length;
      if (cntAnom) cntAnom.textContent = anomCount;
      if (cntClean) cntClean.textContent = cleanCount;

      if (spinner) spinner.style.display = 'none';
      if (container) container.style.display = 'block';

      applyOoniFilter();
    } catch (e) {
      console.error('Failed to load OONI run details:', e);
      if (spinner) spinner.innerHTML = `<span style="color: #ef4444;">Failed to load run details: ${escapeHtml(e.message)}</span>`;
    }
  }

  function closeOoniModal() {
    const modal = document.getElementById('ooni-details-modal');
    if (modal) modal.style.display = 'none';
  }

  function setOoniFilter(type) {
    currentOoniFilter = type;
    updateOoniFilterButtons();
    applyOoniFilter();
  }

  function updateOoniFilterButtons() {
    const btnAll = document.getElementById('btn-ooni-filter-all');
    const btnAnom = document.getElementById('btn-ooni-filter-anom');
    const btnClean = document.getElementById('btn-ooni-filter-clean');
    if (btnAll) btnAll.className = (currentOoniFilter === 'all') ? 'btn-primary' : 'btn-secondary';
    if (btnAnom) btnAnom.className = (currentOoniFilter === 'anomalies') ? 'btn-primary' : 'btn-secondary';
    if (btnClean) btnClean.className = (currentOoniFilter === 'clean') ? 'btn-primary' : 'btn-secondary';
  }

  function applyOoniFilter() {
    const searchVal = (document.getElementById('ooni-search-box')?.value || '').trim().toLowerCase();
    const filtered = currentOoniMeasurements.filter(m => {
      if (currentOoniFilter === 'anomalies' && !m.is_anomaly) return false;
      if (currentOoniFilter === 'clean' && m.is_anomaly) return false;
      if (searchVal) {
        const url = (m.url || '').toLowerCase();
        const testName = (m.test_name || '').toLowerCase();
        const idStr = String(m.id || '');
        if (!url.includes(searchVal) && !testName.includes(searchVal) && !idStr.includes(searchVal)) return false;
      }
      return true;
    });
    renderOoniMeasurements(filtered);
  }

  function renderOoniMeasurements(list) {
    const tbody = document.getElementById('ooni-measurements-tbody');
    if (!tbody) return;

    if (!list || list.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 20px;">No measurements match the current filter.</td></tr>';
      return;
    }

    let html = '';
    list.forEach(m => {
      const isAnom = !!m.is_anomaly;
      let badge = '';
      if (isAnom) {
        let reason = 'Blocked';
        if (m.test_keys && m.test_keys.blocking) {
          reason = `Blocked (${m.test_keys.blocking})`;
        } else if (m.failure) {
          reason = `Fail (${m.failure})`;
        }
        badge = `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">🔴 ${escapeHtml(reason)}</span>`;
      } else {
        badge = `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">🟢 Accessible</span>`;
      }

      let urlDisplay = m.url ? `<a href="${escapeHtml(sanitizeUrl(m.url))}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8; text-decoration: underline;">${escapeHtml(m.url)}</a>` : `<span style="color: var(--text-muted);">${escapeHtml(m.test_name || 'Standard Test')}</span>`;

      const runtimeStr = m.runtime ? `${Number(m.runtime).toFixed(2)}s` : '--';

      html += `<tr>
        <td style="font-weight: 700; color: #94a3b8;">#${escapeHtml(m.id)}</td>
        <td style="word-break: break-all; max-width: 380px;">${urlDisplay}</td>
        <td><span style="font-size: 11.5px; color: #cbd5e1;">${escapeHtml(m.test_name || '--')}</span></td>
        <td>${badge}</td>
        <td style="color: var(--text-muted); font-size: 12px;">${runtimeStr}</td>
        <td>
          <button type="button" class="btn-secondary" style="font-size: 11px; padding: 3px 8px;" onclick="inspectOoniMeasurement(${jsArg(m.id)})">
            🔬 Inspect
          </button>
        </td>
      </tr>`;
    });
    tbody.innerHTML = html;
  }

  async function inspectOoniMeasurement(msmtId) {
    const deepBox = document.getElementById('ooni-deep-inspect-box');
    const deepTitle = document.getElementById('ooni-deep-title');
    const deepContent = document.getElementById('ooni-deep-content');
    const rawPre = document.getElementById('ooni-raw-json-pre');

    if (!deepBox || !deepContent) return;
    deepBox.style.display = 'block';
    deepContent.innerHTML = '<div style="color: #38bdf8; padding: 10px 0;">Loading deep measurement diagnostics...</div>';
    if (rawPre) rawPre.style.display = 'none';

    try {
      const res = await fetch(`/api/ooni/measurement?id=${msmtId}`);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      currentOoniRawJson = data.raw_json || data.measurement_json || data;

      if (rawPre) {
        rawPre.textContent = JSON.stringify(currentOoniRawJson, null, 2);
      }

      const m = currentOoniRawJson;
      const tk = m.test_keys || {};
      const v = data.verdict || {};
      const pr = data.probe || {};
      const resv = data.resolver || {};
      const url = data.url || m.input || tk.input || m.url || `Measurement #${msmtId}`;

      if (deepTitle) {
        deepTitle.innerHTML = `🔬 Diagnostics for: <span style="color: #ffffff;">${escapeHtml(url)}</span>`;
      }

      let cardsHtml = '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-top: 8px;">';

      // 1. Summary & Anomaly Card
      const isAnomaly = !!m.is_anomaly || !!tk.blocking || !!v.blocking || (v.accessible === false);
      const blockingType = v.blocking || tk.blocking || (isAnomaly ? 'Anomalous behavior detected' : 'None (Accessible)');
      const probeAsn = pr.asn || (m.probe_asn ? `AS${m.probe_asn}` : '--');
      const probeNet = pr.network || m.probe_network_name || '';
      const resvAsn = resv.asn || (m.resolver_asn ? `AS${m.resolver_asn}` : (tk.resolver_asn ? `AS${tk.resolver_asn}` : '--'));
      const resvIp = resv.ip || v.client_resolver || '';

      cardsHtml += `
        <div style="background: rgba(255,255,255,0.03); border: 1px solid #334155; border-radius: 6px; padding: 10px;">
          <div style="font-weight: 700; color: #38bdf8; margin-bottom: 6px;">📋 Censorship Verdict</div>
          <div><b>Status:</b> ${isAnomaly ? '<span style="color: #ef4444; font-weight: 700;">🔴 ANOMALY / BLOCKED</span>' : '<span style="color: #10b981; font-weight: 700;">🟢 ACCESSIBLE / OK</span>'}</div>
          <div><b>Blocking Type:</b> <span style="color: #f1f5f9;">${escapeHtml(String(blockingType))}</span></div>
          <div><b>Resolver:</b> <span style="color: #cbd5e1;">${escapeHtml(String(resvAsn))} ${resvIp ? '(' + escapeHtml(resvIp) + ')' : ''}</span></div>
          <div><b>Probe Network:</b> <span style="color: #cbd5e1;">${escapeHtml(String(probeAsn))} ${probeNet ? '(' + escapeHtml(probeNet) + ')' : ''}</span></div>
        </div>
      `;

      // 2. DNS Consistency Card
      let dnsDetails = 'No DNS queries recorded';
      if (data.dns_queries && data.dns_queries.length > 0) {
        dnsDetails = data.dns_queries.map(q => {
          const qname = (q.query_type || 'A') + ' ' + (q.hostname || '');
          const answers = (q.answers || []).join(', ') || 'No answers';
          const fail = q.failure ? `<span style="color: #ef4444;"> [Failed: ${escapeHtml(q.failure)}]</span>` : '';
          return `<div style="margin-bottom: 4px; padding: 4px; background: rgba(0,0,0,0.2); border-radius: 4px;">• <b>${escapeHtml(qname)}</b>${fail}<br>&nbsp;&nbsp;Answers: <span style="color: #94a3b8;">${escapeHtml(answers)}</span></div>`;
        }).join('');
      } else if (tk.queries && tk.queries.length > 0) {
        dnsDetails = tk.queries.map(q => {
          const qname = (q.query_type || 'A') + ' ' + (q.hostname || '');
          const answers = (q.answers || []).map(a => `${a.answer_type || 'A'}: ${a.ipv4 || a.ipv6 || a.hostname || a.ttl || ''}`).join(', ') || 'No answers';
          const fail = q.failure ? `<span style="color: #ef4444;"> [Failed: ${escapeHtml(q.failure)}]</span>` : '';
          return `<div style="margin-bottom: 4px; padding: 4px; background: rgba(0,0,0,0.2); border-radius: 4px;">• <b>${escapeHtml(qname)}</b>${fail}<br>&nbsp;&nbsp;Answers: <span style="color: #94a3b8;">${escapeHtml(answers)}</span></div>`;
        }).join('');
      } else if (tk.dns_experiment_failure) {
        dnsDetails = `<span style="color: #ef4444;">DNS Failure: ${escapeHtml(tk.dns_experiment_failure)}</span>`;
      }
      cardsHtml += `
        <div style="background: rgba(255,255,255,0.03); border: 1px solid #334155; border-radius: 6px; padding: 10px;">
          <div style="font-weight: 700; color: #38bdf8; margin-bottom: 6px;">🌐 DNS Resolution & Tampering</div>
          <div><b>DNS Consistency:</b> ${v.dns_consistency ? `<span style="color: #10b981;">${escapeHtml(v.dns_consistency)}</span>` : (tk.dns_consistency ? `<span style="color: #10b981;">${escapeHtml(tk.dns_consistency)}</span>` : '<span style="color: #94a3b8;">N/A</span>')}</div>
          <div style="margin-top: 6px; max-height: 120px; overflow-y: auto;">${dnsDetails}</div>
        </div>
      `;

      // 3. TCP Connect Card
      let tcpDetails = 'No TCP connect events';
      if (data.tcp_connects && data.tcp_connects.length > 0) {
        tcpDetails = data.tcp_connects.map(t => {
          const ep = `${t.ip}:${t.port}`;
          const ok = t.success;
          const statusTxt = ok ? '<span style="color: #10b981;">Connected</span>' : `<span style="color: #ef4444;">Failed (${escapeHtml(t.failure || 'Blocked')})</span>`;
          return `<div style="margin-bottom: 2px;">• <b>${escapeHtml(ep)}</b>: ${statusTxt}</div>`;
        }).join('');
      } else if (tk.tcp_connect && tk.tcp_connect.length > 0) {
        tcpDetails = tk.tcp_connect.map(t => {
          const ep = `${t.ip}:${t.port}`;
          const ok = t.status && t.status.success;
          const statusTxt = ok ? '<span style="color: #10b981;">Connected</span>' : `<span style="color: #ef4444;">Failed (${escapeHtml(t.status?.failure || 'Blocked')})</span>`;
          return `<div style="margin-bottom: 2px;">• <b>${escapeHtml(ep)}</b>: ${statusTxt}</div>`;
        }).join('');
      }
      cardsHtml += `
        <div style="background: rgba(255,255,255,0.03); border: 1px solid #334155; border-radius: 6px; padding: 10px;">
          <div style="font-weight: 700; color: #38bdf8; margin-bottom: 6px;">🔌 TCP Connect & Handshake</div>
          <div style="max-height: 120px; overflow-y: auto;">${tcpDetails}</div>
        </div>
      `;

      // 4. HTTP Response / Middlebox Card
      let httpDetails = 'No HTTP requests recorded';
      if (data.http_requests && data.http_requests.length > 0) {
        httpDetails = data.http_requests.map(r => {
          const code = r.status_code || r.failure || 'No response';
          return `<div style="margin-bottom: 2px;">• <b>${escapeHtml(r.method || 'GET')} ${escapeHtml(r.url || '')}</b><br>&nbsp;&nbsp;Status: <span style="color: #38bdf8;">${escapeHtml(String(code))}</span></div>`;
        }).join('');
      } else if (tk.requests && tk.requests.length > 0) {
        httpDetails = tk.requests.map(r => {
          const code = r.response ? r.response.code : (r.failure || 'No response');
          const bodyLen = (r.response && r.response.body) ? (typeof r.response.body === 'string' ? r.response.body.length : (r.response.body.value ? r.response.body.value.length : 'N/A')) : '0';
          return `<div style="margin-bottom: 2px;">• <b>${escapeHtml(r.request?.method || 'GET')} ${escapeHtml(r.request?.url || '')}</b><br>&nbsp;&nbsp;Code: <span style="color: #38bdf8;">${escapeHtml(String(code))}</span> • Body: ${bodyLen} bytes</div>`;
        }).join('');
      } else if (tk.received) {
        httpDetails = `Received: <pre style="font-size: 11px; margin: 2px 0;">${escapeHtml(JSON.stringify(tk.received))}</pre>`;
      }
      cardsHtml += `
        <div style="background: rgba(255,255,255,0.03); border: 1px solid #334155; border-radius: 6px; padding: 10px;">
          <div style="font-weight: 700; color: #38bdf8; margin-bottom: 6px;">📦 HTTP Traffic & Middlebox</div>
          <div style="max-height: 120px; overflow-y: auto;">${httpDetails}</div>
        </div>
      `;

      cardsHtml += '</div>';
      deepContent.innerHTML = cardsHtml;
      deepBox.scrollIntoView({ behavior: 'smooth' });
    } catch (e) {
      console.error('Failed to inspect measurement:', e);
      deepContent.innerHTML = `<span style="color: #ef4444;">Failed to retrieve measurement details: ${escapeHtml(e.message)}</span>`;
    }
  }

  function toggleOoniRawJson() {
    const rawPre = document.getElementById('ooni-raw-json-pre');
    if (!rawPre) return;
    rawPre.style.display = (rawPre.style.display === 'none') ? 'block' : 'none';
  }

  function copyOoniRawJson() {
    if (!currentOoniRawJson) {
      showToast('No measurement data to copy');
      return;
    }
    const text = JSON.stringify(currentOoniRawJson, null, 2);
    navigator.clipboard.writeText(text).then(() => {
      showToast('Measurement JSON copied to clipboard!');
    }).catch(e => {
      showToast('Failed to copy: ' + e);
    });
  }


  // ==========================================
  // Network Explorer & Device Inventory
  // ==========================================
  let cachedNetworkDevices = [];
  let cachedNetworkSummary = null;

  async function loadNetworkDevices() {
    const sel = document.getElementById('explorer-iface-select');
    const iface = sel ? sel.value : 'any';
    try {
      const res = await fetch('/api/network/devices?iface=' + encodeURIComponent(iface));
      if (res.ok) {
        const d = await res.json();
        cachedNetworkDevices = d.devices || [];
        cachedNetworkSummary = d;
        renderDeviceList(cachedNetworkDevices, d);
      }
    } catch (e) {
      console.error('loadNetworkDevices error:', e);
    }
  }

  async function triggerNetworkSweep() {
    const sel = document.getElementById('explorer-iface-select');
    const iface = sel ? sel.value : 'any';
    showToast('Scanning subnets & discovering connected LAN/Guest devices...');
    const btn = document.getElementById('btn-explorer-scan');
    if (btn) btn.disabled = true;

    try {
      await fetch('/api/network/devices/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ iface: iface })
      });
      setTimeout(async () => {
        await loadNetworkDevices();
        await loadGuestWifiStatus();
        if (btn) btn.disabled = false;
        showToast('Device discovery completed.');
      }, 4000);
    } catch (e) {
      showToast(t('guest_toast_scan_err', 'Scan error: ') + e);
      if (btn) btn.disabled = false;
    }
  }

  function filterDevicesTable(q) {
    q = (q || '').toLowerCase().trim();
    if (!q) {
      renderDeviceList(cachedNetworkDevices, cachedNetworkSummary);
      return;
    }
    const filtered = cachedNetworkDevices.filter(dev => {
      return (dev.ip || '').toLowerCase().includes(q) ||
             (dev.mac || '').toLowerCase().includes(q) ||
             (dev.vendor || '').toLowerCase().includes(q) ||
             (dev.hostname || '').toLowerCase().includes(q) ||
             (dev.interface || dev.iface || '').toLowerCase().includes(q);
    });
    renderDeviceList(filtered, cachedNetworkSummary);
  }

  function renderDeviceList(devices, summary) {
    const tbody = document.getElementById('explorer-table-body');
    const badge = document.getElementById('explorer-count-badge');
    const totalCount = summary ? summary.total : devices.length;
    const lanCount = summary ? summary.lan_count : devices.filter(d => !d.is_guest).length;
    const guestCount = summary ? summary.guest_count : devices.filter(d => d.is_guest).length;
    if (badge) {
      badge.innerHTML = `<b>${totalCount} Devices Discovered</b> <span style="opacity: 0.85; font-size: 11px;">(Wired LAN: ${lanCount} | Guest Wi-Fi: ${guestCount})</span>`;
    }
    if (!devices || devices.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 24px;">No devices detected on this interface. Click "Scan Subnets Now" to sweep connected networks.</td></tr>';
      return;
    }
    let html = '';
    devices.forEach(d => {
      const safeIp = escapeHtml(d.ip);
      const safeMac = escapeHtml(d.mac || '--');
      const safeVendor = escapeHtml(d.vendor || '');
      const safeHostname = escapeHtml(d.hostname || '--');
      const rawIface = d.interface || d.iface || 'eth0';
      const safeIface = escapeHtml(rawIface);
      const isGuest = Boolean(d.is_guest || rawIface.startsWith('wlan'));

      const ifaceBadge = isGuest
        ? `<span class="badge-pill" style="background: rgba(168, 85, 247, 0.18); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); font-size: 11px;">📶 Guest (${safeIface})</span>`
        : `<span class="badge-pill" style="background: rgba(56, 189, 248, 0.12); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 11px;">🏠 Wired (${safeIface})</span>`;

      const vendorBadge = d.vendor && d.vendor !== 'Unknown' && d.vendor !== 'Unknown Vendor'
        ? `<span class="badge-pill" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid #0284c7; font-size: 11px;">${safeVendor}</span>`
        : `<span style="color: var(--text-muted); font-size: 12px;">Generic / Unknown</span>`;
      const stateBadge = (d.status === 'active' || d.state === 'REACHABLE' || d.state === 'PERMANENT')
        ? `<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981; font-size: 11px;">Active</span>`
        : `<span class="badge-pill" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569; font-size: 11px;">Seen</span>`;

      html += `<tr>
        <td style="font-family: monospace; font-weight: 700; color: #f1f5f9; white-space: nowrap;">${safeIp}</td>
        <td style="font-family: monospace; color: #cbd5e1; white-space: nowrap;">${safeMac}</td>
        <td style="white-space: nowrap;">${vendorBadge}</td>
        <td style="color: #38bdf8; font-weight: 500; white-space: nowrap;">${safeHostname}</td>
        <td style="white-space: nowrap;">${ifaceBadge}</td>
        <td style="white-space: nowrap;">${stateBadge}</td>
      </tr>`;
    });
    tbody.innerHTML = html;
  }

  // ==========================================
  // Dedicated Guest Wi-Fi Receiver & Client Station Probe
  // ==========================================
  let cachedGuestWifiStatus = null;

  function renderGuestWifiStatus(d) {
    if (!d) return;
    const isConn = !!d.connected;

    // 1. Update Subtab Badge
    const subtabBadge = document.getElementById('guest-wifi-badge-pill');
    if (subtabBadge) {
      if (isConn) {
        subtabBadge.style.background = 'rgba(16, 185, 129, 0.15)';
        subtabBadge.style.color = '#34d399';
        subtabBadge.style.border = '1px solid #10b981';
        subtabBadge.innerHTML = `🟢 ${t('status_connected', 'Connected')}: <b>${escapeHtml(d.ssid)}</b>`;
      } else {
        subtabBadge.style.background = 'rgba(148, 163, 184, 0.15)';
        subtabBadge.style.color = '#94a3b8';
        subtabBadge.style.border = '1px solid #475569';
        subtabBadge.innerHTML = `⚪ ${t('status_not_connected', 'Not Connected')}`;
      }
    }

    // 2. Update Explorer Banner
    const expStatusText = document.getElementById('explorer-guest-status-text');
    const expDetailsText = document.getElementById('explorer-guest-details-text');
    if (expStatusText && d.unassigned) {
      expStatusText.style.background = 'rgba(148, 163, 184, 0.15)';
      expStatusText.style.color = '#94a3b8';
      expStatusText.style.border = '1px solid #475569';
      expStatusText.innerHTML = `⚪ ${escapeHtml(t('guest_unassigned', 'No interface has the guest role'))}`;
      if (expDetailsText) {
        expDetailsText.textContent = d.main_interface
          ? t('guest_unassigned_main', '{iface} is the main Wi-Fi client. To probe a guest network, give a wireless interface the guest role under Ports & Drivers.').replace('{iface}', d.main_interface)
          : t('guest_unassigned_hint', 'To probe a guest network, give a wireless interface the guest role under Ports & Drivers.');
      }
    } else if (expStatusText) {
      if (isConn) {
        expStatusText.style.background = 'rgba(16, 185, 129, 0.15)';
        expStatusText.style.color = '#34d399';
        expStatusText.style.border = '1px solid #10b981';
        expStatusText.innerHTML = `🟢 ${t('status_connected', 'Connected')}: <b>${escapeHtml(d.ssid)}</b> (${escapeHtml(d.ip_address || 'DHCP')})`;
        if (expDetailsText) {
          let isoBadge = '';
          let isoDesc = '';
          if (d.is_isolated_subnet === true) {
            isoBadge = `<span style="color:#34d399; font-weight:700;">[${t('guest_iso_verified', 'ISOLATED GUEST SUBNET VERIFIED')}]</span>`;
            isoDesc = t('guest_iso_verified_desc', 'Guest Wi-Fi client operates on an isolated subnet, completely separated from the wired LAN.');
          } else if (d.is_isolated_subnet === false) {
            isoBadge = `<span style="color:#fbbf24; font-weight:700;">[${t('guest_iso_shared', 'SHARED BROADCAST DOMAIN')}]</span>`;
            isoDesc = t('guest_iso_shared_desc', 'Both Wi-Fi station and wired LAN share the same subnet. The upstream router does not isolate this guest Wi-Fi from the LAN.');
          } else {
            isoDesc = escapeHtml(d.isolation_verdict || '');
          }
          expDetailsText.innerHTML = `${t('guest_subnet', 'Guest Subnet')}: <b><code style="color:#e9d5ff;">${escapeHtml(d.subnet || '--')}</code></b> (${t('gateway', 'Gateway')}: ${escapeHtml(d.gateway || '--')}) | ${t('wifi_signal', 'Signal')}: <b>${escapeHtml(d.signal_percent)}%</b>. ${isoBadge} ${isoDesc}`;
        }
      } else {
        expStatusText.style.background = 'rgba(148, 163, 184, 0.15)';
        expStatusText.style.color = '#94a3b8';
        expStatusText.style.border = '1px solid #475569';
        expStatusText.innerHTML = `⚪ ${t('status_not_connected', 'Not Connected')}`;
        if (expDetailsText) {
          expDetailsText.innerHTML = t('guest_wifi_not_connected_hint', 'Wi-Fi receiver is not connected to a guest network. Click settings to configure connection.');
        }
      }
    }

    // 3. Update Subtab Status Grid
    if (document.getElementById('guest-wifi-stat-ssid')) {
      document.getElementById('guest-wifi-stat-ssid').textContent = d.ssid || (isConn ? t('status_connected', 'Connected') : t('status_not_connected', 'Not Connected'));
      document.getElementById('guest-wifi-stat-ip').textContent = d.cidr || d.ip_address || '--';
      document.getElementById('guest-wifi-stat-gw').textContent = d.gateway || '--';
      document.getElementById('guest-wifi-stat-sig').textContent = (d.signal_percent || 0) + '%';
      const sigbar = document.getElementById('guest-wifi-stat-sigbar');
      if (sigbar) sigbar.style.width = (d.signal_percent || 0) + '%';
      document.getElementById('guest-wifi-stat-sec').textContent = `${t('channel_abbr', 'Ch:')} ${d.channel || '--'} | ${d.security || 'WPA2'}`;
      document.getElementById('guest-wifi-stat-mac').textContent = d.mac_address || '--';
      if (document.getElementById('guest-wifi-stat-metric')) {
        document.getElementById('guest-wifi-stat-metric').textContent = d.route_metric || 600;
      }
    }

    // 4. Update Isolation text
    const isoText = document.getElementById('guest-wifi-isolation-text');
    if (isoText) {
      isoText.textContent = d.isolation_verdict || t('guest_wifi_ready', 'Guest Wi-Fi telemetry ready.');
    }
  }

  async function loadGuestWifiStatus() {
    try {
      const res = await fetch('/api/wifi/guest/status');
      if (!res.ok) return;
      const d = await res.json();
      cachedGuestWifiStatus = d;
      renderGuestWifiStatus(d);

      // 5. Prepopulate configuration inputs if available
      if (d.ssid && document.getElementById('cfg-guest-wifi-ssid') && !document.getElementById('cfg-guest-wifi-ssid').value) {
        document.getElementById('cfg-guest-wifi-ssid').value = d.ssid;
      }
      loadSavedGuestWifiConnections();
    } catch (e) {
      console.debug('loadGuestWifiStatus error:', e);
    }
  }

  async function scanGuestWifiNetworks() {
    const btn = document.getElementById('btn-scan-guest-wifi');
    const tableWrap = document.getElementById('guest-wifi-scan-table-wrap');
    const tbody = document.getElementById('guest-wifi-scan-tbody');
    if (btn) btn.disabled = true;
    showToast(t('guest_toast_scanning', 'Scanning nearby Wi-Fi networks via wlan0...'));
    if (tableWrap) tableWrap.style.display = 'block';
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 16px;">' + t('guest_scan_in_progress', 'Scanning frequencies (2.4 GHz & 5 GHz)... Please wait.') + '</td></tr>';

    try {
      const res = await fetch('/api/wifi/guest/scan');
      if (res.ok) {
        const d = await res.json();
        const nets = d.networks || [];
        if (nets.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #f87171; padding: 16px;">' + t('guest_scan_no_ap', 'No Wi-Fi access points detected. Ensure wireless antenna is connected.') + '</td></tr>';
          return;
        }
        let html = '';
        nets.forEach(n => {
          const isHidden = !!(n.is_hidden || !n.ssid || n.ssid.startsWith('<Hidden'));
          const safeSsid = isHidden
            ? '<span class="badge" style="background:rgba(234,179,8,0.15);color:#facc15;border:1px solid rgba(234,179,8,0.3);font-size:11px;">🔒 ' + t('guest_badge_hidden', 'Hidden SSID') + '</span> ' + escapeHtml(n.ssid)
            : escapeHtml(n.ssid);
          const safeBssid = escapeHtml(n.bssid);
          const safeSec = escapeHtml(n.security);
          const inUseBadge = n.in_use
            ? '<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981; font-size: 11px;">Active</span>'
            : '<span style="color: var(--text-muted); font-size: 11px;">' + t('guest_state_available', 'Available') + '</span>';

          html += `<tr>
            <td>${inUseBadge}</td>
            <td style="font-weight: 700; color: #f1f5f9;">${safeSsid}</td>
            <td>
              <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 50px; height: 6px; background: #334155; border-radius: 3px; overflow: hidden;">
                  <div style="width: ${escapeHtml(n.signal)}%; height: 100%; background: #10b981;"></div>
                </div>
                <span style="font-size: 12px; font-weight: 600;">${escapeHtml(n.signal)}%</span>
              </div>
            </td>
            <td style="font-family: monospace;">${escapeHtml(n.channel)}</td>
            <td><span class="badge-pill" style="background: rgba(56, 189, 248, 0.12); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 11px;">${safeSec}</span></td>
            <td style="font-family: monospace; font-size: 11.5px; color: #94a3b8;">${safeBssid}</td>
            <td>
              <button type="button" class="btn-primary" style="font-size: 11px; padding: 4px 10px;" onclick="selectScannedGuestWifi(${jsArg(n.ssid)}, ${jsArg(n.security)}, ${isHidden ? 'true' : 'false'})">
                ${t('guest_btn_select', 'Select ➡️')}
              </button>
            </td>
          </tr>`;
        });
        tbody.innerHTML = html;
        showToast(t('guest_toast_scan_completed', 'Scan completed: ') + `${nets.length} ` + t('guest_toast_scan_count_suffix', 'Wi-Fi networks found.'));
      }
    } catch (e) {
      showToast(t('guest_toast_scan_err', 'Scan error: ') + e);
      if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: #f87171;">Error: ${escapeHtml(String(e))}</td></tr>`;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function selectScannedGuestWifi(ssid, sec, isHidden) {
    const input = document.getElementById('cfg-guest-wifi-ssid');
    const hiddenBox = document.getElementById('cfg-guest-wifi-hidden');
    const secSelect = document.getElementById('cfg-guest-wifi-sec');
    const passInput = document.getElementById('cfg-guest-wifi-pass');

    if (input) {
      if (isHidden || !ssid || ssid.startsWith('<Hidden')) {
        input.value = '';
        input.placeholder = t('guest_ph_hidden_ssid', 'Enter exact hidden network name (SSID)...');
        input.focus();
      } else {
        input.value = ssid;
      }
    }
    if (hiddenBox) {
      hiddenBox.checked = !!(isHidden || (ssid && ssid.startsWith('<Hidden')));
    }
    if (secSelect) {
      const secUpper = (sec || '').toUpperCase();
      if (secUpper.includes('SAE') || secUpper.includes('WPA3')) {
        secSelect.value = 'sae';
      } else if (secUpper.includes('OPEN') || secUpper.includes('NONE')) {
        secSelect.value = 'open';
      } else {
        secSelect.value = 'wpa-psk';
      }
      onGuestWifiSecChange();
    }
    if (passInput && (!sec || !sec.toUpperCase().includes('OPEN'))) {
      passInput.focus();
    }
    showToast(t('guest_toast_selected', 'Selected: ') + `"${ssid || 'Hidden Wi-Fi'}".`);
  }

  function onGuestWifiSecChange() {
    const sec = document.getElementById('cfg-guest-wifi-sec')?.value || 'wpa-psk';
    const passWrap = document.getElementById('cfg-guest-wifi-pass-wrap');
    const passInput = document.getElementById('cfg-guest-wifi-pass');
    if (sec === 'open') {
      if (passInput) {
        passInput.disabled = true;
        passInput.value = '';
        passInput.placeholder = t('guest_ph_open_pass', '(Open network - no password required)');
      }
      if (passWrap) passWrap.style.opacity = '0.6';
    } else {
      if (passInput) {
        passInput.disabled = false;
        passInput.placeholder = t('guest_ph_pass', 'Enter Wi-Fi password...');
      }
      if (passWrap) passWrap.style.opacity = '1.0';
    }
  }

  async function connectGuestWifi() {
    const ssid = (document.getElementById('cfg-guest-wifi-ssid')?.value || '').trim();
    const pass = (document.getElementById('cfg-guest-wifi-pass')?.value || '').trim();
    const metric = parseInt(document.getElementById('cfg-guest-wifi-metric')?.value, 10) || 600;
    const iface = (document.getElementById('cfg-guest-wifi-iface')?.value || 'wlan0').trim();
    const hidden = !!document.getElementById('cfg-guest-wifi-hidden')?.checked;

    if (!ssid) {
      showToast(t('guest_toast_enter_ssid', 'Please enter or select a Wi-Fi SSID.'));
      return;
    }

    showToast(t('guest_toast_connecting', 'Connecting: ') + `${iface} -> "${ssid}" (${hidden ? t('yes', 'Yes') : t('no', 'No')})...`);
    try {
      const res = await fetch('/api/wifi/guest/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ssid: ssid,
          password: pass,
          interface: iface,
          metric: metric,
          hidden: hidden,
          save: true
        })
      });
      const d = await res.json();
      if (res.ok && d.status === 'ok') {
        showToast('✅ ' + d.message);
        await loadGuestWifiStatus();
        await loadSavedGuestWifiConnections();
        await loadNetworkDevices();
      } else {
        showToast('❌ ' + (d.message || t('guest_err_connect', 'Connection error')));
      }
    } catch (e) {
      showToast(t('guest_err_connect', 'Connection error: ') + e);
    }
  }

  async function loadSavedGuestWifiConnections() {
    const tbody = document.getElementById('guest-wifi-saved-tbody');
    if (!tbody) return;
    try {
      const res = await fetch('/api/wifi/guest/saved');
      if (!res.ok) return;
      const d = await res.json();
      const list = d.saved_networks || [];
      if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 12px;">' + t('guest_no_saved_profiles', 'No saved Wi-Fi profiles found on this device.') + '</td></tr>';
        return;
      }
      let html = '';
      list.forEach(item => {
        const statusBadge = item.in_use
          ? '<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981; font-size: 11px;">' + t('guest_state_active_connected', '🟢 Active / Connected') + '</span>'
          : '<span class="badge-pill" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569; font-size: 11px;">' + t('guest_state_saved', '⚪ Saved') + '</span>';
        const targetId = item.uuid || item.name;
        html += `<tr>
          <td style="font-weight: 700; color: #f1f5f9;">${escapeHtml(item.ssid || item.name)}</td>
          <td>${statusBadge}</td>
          <td style="font-family: monospace; font-size: 11px; color: #94a3b8;">${escapeHtml(item.uuid || '--')}</td>
          <td style="display: flex; gap: 6px;">
            ${!item.in_use ? `<button type="button" class="btn-primary" style="font-size: 11px; padding: 3px 8px;" onclick="activateSavedWifi(${jsArg(targetId)})">${t('guest_btn_connect_now', '⚡ Connect')}</button>` : ''}
            <button type="button" class="btn-danger" style="font-size: 11px; padding: 3px 8px;" onclick="forgetSavedWifi(${jsArg(targetId)})">${t('guest_btn_delete', '🗑️ Delete')}</button>
          </td>
        </tr>`;
      });
      tbody.innerHTML = html;
    } catch (e) {
      console.debug('loadSavedGuestWifiConnections error:', e);
    }
  }

  async function activateSavedWifi(id) {
    showToast(t('guest_toast_connecting_profile', 'Connecting to saved profile...'));
    try {
      const res = await fetch('/api/wifi/guest/saved/activate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: id })
      });
      const d = await res.json();
      if (res.ok && d.status === 'ok') {
        showToast(t('guest_toast_connected', '✅ Connected!'));
        await loadGuestWifiStatus();
        await loadSavedGuestWifiConnections();
      } else {
        showToast('❌ ' + (d.message || t('guest_err_connect', 'Connection error')));
      }
    } catch (e) {
      showToast(t('vpn_err_create', 'Operation error: ') + e);
    }
  }

  async function forgetSavedWifi(id) {
    if (!confirm(t('guest_confirm_forget', 'Are you sure you want to forget this saved Wi-Fi profile?'))) return;
    try {
      const res = await fetch('/api/wifi/guest/saved/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: id })
      });
      const d = await res.json();
      if (res.ok && d.status === 'ok') {
        showToast(t('guest_toast_profile_deleted', '✅ Wi-Fi profile deleted!'));
        await loadSavedGuestWifiConnections();
      } else {
        showToast('❌ ' + (d.message || t('guest_err_delete', 'Error deleting profile')));
      }
    } catch (e) {
      showToast(t('vpn_err_create', 'Operation error: ') + e);
    }
  }

  async function disconnectGuestWifi() {
    if (!confirm(t('guest_confirm_disconnect', 'Disconnect wireless interface from Guest Wi-Fi?'))) return;
    const iface = (document.getElementById('cfg-guest-wifi-iface').value || 'wlan0').trim();
    showToast(`Disconnecting ${iface}...`);
    try {
      const res = await fetch('/api/wifi/guest/disconnect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interface: iface, disable: true })
      });
      const d = await res.json();
      showToast(d.message || 'Disconnected.');
      await loadGuestWifiStatus();
      await loadNetworkDevices();
    } catch (e) {
      showToast('Error: ' + e);
    }
  }

  // ==========================================
  // LLM Diagnostic Bundle
  // ==========================================
  let cachedLlmMarkdown = '';

  async function loadLlmBundle() {
    const preview = document.getElementById('llm-bundle-preview');
    if (preview) preview.textContent = 'Generating comprehensive diagnostic bundle for LLMs...';
    try {
      const res = await fetch('/api/diagnostics/llm');
      if (res.ok) {
        const d = await res.json();
        cachedLlmMarkdown = d.markdown || '';
        if (preview) preview.textContent = cachedLlmMarkdown;
      }
    } catch (e) {
      if (preview) preview.textContent = 'Failed to load diagnostics: ' + e;
    }
  }

  function copyLlmBundle() {
    if (!cachedLlmMarkdown) {
      showToast('Diagnostic bundle not ready yet.');
      return;
    }
    navigator.clipboard.writeText(cachedLlmMarkdown).then(() => {
      showToast('✅ Diagnostic bundle copied to clipboard! Paste directly into ChatGPT, Claude or Gemini.');
    }).catch(err => {
      const ta = document.createElement('textarea');
      ta.value = cachedLlmMarkdown;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      showToast('✅ Diagnostic bundle copied to clipboard!');
    });
  }

  function downloadLlmBundle() {
    window.location.href = '/download/diagnostics.md';
  }

  // ==========================================
  // Admin Credentials Update
  // ==========================================
  async function updateAdminCredentials() {
    const username = (document.getElementById('cfg-admin-user').value || '').trim();
    const password = (document.getElementById('cfg-admin-pass').value || '').trim();
    if (!username) {
      showToast('Username cannot be empty.');
      return;
    }
    showToast('Updating admin credentials...');
    try {
      const res = await fetch('/api/system/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username, password: password })
      });
      if (res.ok) {
        showToast('✅ Admin credentials updated! Please keep your new login safe.');
        document.getElementById('cfg-admin-pass').value = '';
      } else {
        const err = await res.json();
        showToast('Error: ' + (err.message || 'Failed'));
      }
    } catch (e) {
      showToast('Error updating credentials: ' + e);
    }
  }

  // Results without password on the local network
  async function savePublicResults(enabled) {
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ public_results: !!enabled })
      });
      showToast(res.ok ? (enabled ? '✅ /results is open on the local network.' : '🔒 /results needs the password again.') : 'Error saving the setting.');
    } catch (e) {
      showToast('Error saving the setting: ' + e);
    }
  }

  // Where speed tests run, and the Wi-Fi uplink
  function renderWifiUplink(d) {
    const link = document.getElementById('meas-link');
    if (link && document.activeElement !== link && d.measurement_link) link.value = d.measurement_link;
    const sel = document.getElementById('wu-iface');
    if (sel && document.activeElement !== sel) {
      const keep = sel.value;
      sel.innerHTML = '<option value="auto">auto</option>' + (d.interfaces || []).map(i => `<option value="${escapeHtml(i)}">${escapeHtml(i)}</option>`).join('');
      sel.value = keep && Array.from(sel.options).some(o => o.value === keep) ? keep : 'auto';
    }
    const ssid = document.getElementById('wu-ssid');
    if (ssid && document.activeElement !== ssid && !ssid.value) ssid.value = d.ssid_configured || '';
    const en = document.getElementById('wu-enabled');
    if (en && document.activeElement !== en) en.checked = !!d.enabled;
    const hid = document.getElementById('wu-hidden');
    if (hid && document.activeElement !== hid) hid.checked = !!d.hidden;
    const ph = document.getElementById('wu-pass-hint');
    if (ph) ph.textContent = d.password_set ? t('wu_pass_saved', 'A password is saved; leave empty to keep it.') : '';
    // Device explorer: the main Wi-Fi client's own banner
    const mst = document.getElementById('explorer-main-status-text');
    const mdt = document.getElementById('explorer-main-details-text');
    if (mst) {
      const on = !!d.connected;
      mst.style.background = on ? 'rgba(16, 185, 129, 0.15)' : 'rgba(148, 163, 184, 0.15)';
      mst.style.color = on ? '#34d399' : '#94a3b8';
      mst.style.border = on ? '1px solid #10b981' : '1px solid #475569';
      mst.innerHTML = on ? `🟢 ${t('status_connected', 'Connected')}: <b>${escapeHtml(d.ssid || '?')}</b> (${escapeHtml(d.ip || 'DHCP')})`
                         : `⚪ ${escapeHtml(d.interface ? t('wu_not_connected', 'Not connected over Wi-Fi.') : t('wu_no_iface', 'No wireless interface found.'))}`;
      if (mdt) {
        const band = d.frequency_mhz ? (d.frequency_mhz >= 5925 ? '6 GHz' : d.frequency_mhz >= 4900 ? '5 GHz' : '2.4 GHz') : '';
        const linkName = { auto: t('meas_link_auto', 'Ethernet when a cable is connected, otherwise Wi-Fi'), ethernet: t('meas_link_eth', 'Ethernet only'), wifi: t('meas_link_wifi', 'Wi-Fi only') }[d.measurement_link] || '';
        const parts = [`${escapeHtml(t('wu_iface', 'Wireless interface'))}: <b>${escapeHtml(d.interface || '--')}</b>`];
        if (on) parts.push(`${escapeHtml(t('gateway', 'Gateway'))}: ${escapeHtml(d.gateway || '--')}`);
        if (d.signal_dbm != null) parts.push(`${escapeHtml(t('wifi_signal', 'Signal'))}: <b>${escapeHtml(String(d.signal_dbm))} dBm</b>`);
        if (band) parts.push(band);
        if (d.bitrate) parts.push(escapeHtml(d.bitrate));
        if (linkName) parts.push(`${escapeHtml(t('meas_link_label', 'Speed tests run over:'))} ${escapeHtml(linkName)}`);
        mdt.innerHTML = parts.join(' · ');
      }
    }
    const st = document.getElementById('wu-status');
    if (st) {
      if (d.connected) {
        const band = d.frequency_mhz ? (d.frequency_mhz >= 5925 ? '6 GHz' : d.frequency_mhz >= 4900 ? '5 GHz' : '2.4 GHz') : '';
        st.textContent = t('wu_connected', 'Connected: {ssid} on {iface}, {ip}').replace('{ssid}', d.ssid || '?').replace('{iface}', d.interface || '?').replace('{ip}', d.ip || '?')
          + (d.signal_dbm != null ? `, ${d.signal_dbm} dBm` : '') + (band ? `, ${band}` : '') + (d.bitrate ? `, ${d.bitrate}` : '');
      } else {
        st.textContent = d.interface ? t('wu_not_connected', 'Not connected over Wi-Fi.') : t('wu_no_iface', 'No wireless interface found.');
      }
      if (d.message) st.textContent = d.message + ' ' + st.textContent;
    }
  }

  async function loadWifiUplink() {
    try { const r = await fetch('/api/wifi-uplink/status'); if (r.ok) renderWifiUplink(await r.json()); } catch (e) {}
    loadWifiShare();
    loadUsbUplink();
    loadStorage();
  }

  function renderWifiShare(d) {
    const en = document.getElementById('ws-enabled');
    if (en && document.activeElement !== en) en.checked = !!d.enabled;
    const sel = document.getElementById('ws-lan');
    if (sel && document.activeElement !== sel) {
      const ports = (d.ports || []).slice();
      if (d.lan_interface && !ports.includes(d.lan_interface)) ports.unshift(d.lan_interface);
      sel.innerHTML = ports.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join('');
      sel.value = d.lan_interface || ports[0] || '';
    }
    const addr = document.getElementById('ws-addr');
    if (addr && document.activeElement !== addr && !addr.value) addr.value = d.address || '';
    const st = document.getElementById('ws-status');
    if (st) {
      let txt;
      if (d.active) {
        txt = t('ws_active', 'Sharing: {lan} ({addr}) gets the internet of {wifi}; DHCP {range}.')
          .replace('{lan}', d.lan_interface).replace('{addr}', d.address).replace('{wifi}', d.wifi || 'Wi-Fi').replace('{range}', d.dhcp_range);
        const n = (d.leases || []).length;
        if (n) txt += ' ' + t('ws_clients', 'Clients: {n}').replace('{n}', n) + ' (' + d.leases.map(l => l.ip + (l.hostname ? ' ' + l.hostname : '')).join(', ') + ')';
      } else {
        txt = d.enabled ? t('ws_waiting', 'Not sharing now: {reason}.').replace('{reason}', d.code ? t('ws_r_' + d.code, d.reason || '--').replace('{lan}', d.lan_interface || '') : (d.reason || '--')) : t('ws_off', 'Off.');
      }
      if (d.message) txt = d.message + ' ' + txt;
      st.textContent = txt;
    }
  }

  async function loadWifiShare() {
    try { const r = await fetch('/api/wifi-share/status'); if (r.ok) renderWifiShare(await r.json()); } catch (e) {}
  }

  async function saveWifiShare() {
    const body = {
      enabled: document.getElementById('ws-enabled').checked,
      lan_interface: document.getElementById('ws-lan').value,
      address: (document.getElementById('ws-addr').value || '').trim() || '192.168.77.1/24',
    };
    try {
      const r = await fetch('/api/wifi-share/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json();
      if (r.ok) renderWifiShare(d);
      showToast((r.ok ? '✔ ' : '✖ ') + (d.message || ''));
    } catch (e) { showToast('Error: ' + e); }
  }
  window.saveWifiShare = saveWifiShare;

  function renderUsbUplink(d) {
    const sel = document.getElementById('uu-iface');
    if (sel && document.activeElement !== sel) {
      const opts = ['auto'].concat(d.interfaces || []);
      if (d.interface_setting && !opts.includes(d.interface_setting)) opts.push(d.interface_setting);
      sel.innerHTML = opts.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('');
      sel.value = d.interface_setting || 'auto';
    }
    const en = document.getElementById('uu-enabled');
    if (en && document.activeElement !== en) en.checked = !!d.enabled;
    const lim = document.getElementById('uu-limit');
    if (lim && document.activeElement !== lim) lim.value = d.daily_limit_mb ?? 1024;
    const st = document.getElementById('uu-status');
    if (!st) return;
    const name = [d.manufacturer, d.product].filter(Boolean).join(' ') || d.driver || '';
    let txt;
    if (!d.interface) txt = t('uu_status_none', 'No phone, hotspot or modem on USB.');
    else if (d.connected) txt = t('uu_status_up', '{iface} ({device}): IP {ip}, gateway {gw}.')
      .replace('{iface}', d.interface).replace('{device}', name).replace('{ip}', d.ip || '--').replace('{gw}', d.gateway || '--');
    else txt = t('uu_status_down', '{iface} found ({device}), not connected.').replace('{iface}', d.interface).replace('{device}', name);
    txt += ' ' + t('uu_used', 'Used today by tests over USB: {used} MB').replace('{used}', d.used_today_mb ?? 0)
      + (d.daily_limit_mb ? ' / ' + d.daily_limit_mb + ' MB.' : ' (' + t('uu_no_limit', 'no limit') + ').');
    if (d.message) txt = d.message + ' ' + txt;
    st.textContent = txt;
  }

  async function loadUsbUplink() {
    try { const r = await fetch('/api/usb-uplink/status'); if (r.ok) renderUsbUplink(await r.json()); } catch (e) {}
  }

  async function saveUsbUplink() {
    const ml = document.getElementById('meas-link');
    const body = {
      enabled: document.getElementById('uu-enabled').checked,
      interface: document.getElementById('uu-iface').value,
      daily_limit_mb: parseInt(document.getElementById('uu-limit').value || '0', 10),
      measurement_link: ml ? ml.value : undefined,
    };
    try {
      const r = await fetch('/api/usb-uplink/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json();
      renderUsbUplink(d);
      showToast((r.ok ? '✔ ' : '✖ ') + (d.message || ''));
    } catch (e) { showToast('Error: ' + e); }
  }
  window.saveUsbUplink = saveUsbUplink;

  async function usbUplinkOff() {
    try {
      const r = await fetch('/api/usb-uplink/disconnect', { method: 'POST' });
      const d = await r.json();
      renderUsbUplink(d);
      const ml = document.getElementById('meas-link');
      if (ml && ml.value === 'usb') ml.value = 'auto';
      showToast((r.ok ? '✔ ' : '✖ ') + (d.message || ''));
    } catch (e) { showToast('Error: ' + e); }
  }
  window.usbUplinkOff = usbUplinkOff;

  function renderStorage(d) {
    const auto = document.getElementById('st-auto');
    if (!auto) return;
    if (document.activeElement !== auto) auto.checked = !!d.auto_cleanup;
    const mf = document.getElementById('st-min-free'), kd = document.getElementById('st-keep-days');
    if (mf && document.activeElement !== mf) mf.value = d.min_free_mb ?? 0;
    if (kd && document.activeElement !== kd) kd.value = d.keep_days ?? 7;
    const st = document.getElementById('st-status');
    if (!st) return;
    let txt = '';
    if (d.total_mb != null) {
      txt = t('st_status', '{free} MB free of {total} MB; cleanup starts below {target} MB.')
        .replace('{free}', d.free_mb).replace('{total}', d.total_mb).replace('{target}', d.target_free_mb);
    }
    const last = d.last_cleanup || {};
    if (last.status) {
      txt += ' ' + t('st_last', 'Last check: {result}, {n} item(s) deleted.')
        .replace('{result}', last.status).replace('{n}', (last.deleted || []).length);
    }
    st.textContent = txt.trim();
  }

  async function loadStorage() {
    try { const r = await fetch('/api/storage/status'); if (r.ok) renderStorage(await r.json()); } catch (e) {}
  }

  async function saveStorage() {
    const body = {
      auto_cleanup: document.getElementById('st-auto').checked,
      min_free_mb: parseInt(document.getElementById('st-min-free').value || '0', 10),
      keep_days: parseInt(document.getElementById('st-keep-days').value || '7', 10),
    };
    try {
      const r = await fetch('/api/storage/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json();
      showToast((r.ok ? '✔ ' : '✖ ') + (d.message || t('saved', 'Saved')));
      loadStorage();
    } catch (e) { showToast('Error: ' + e); }
  }
  window.saveStorage = saveStorage;

  async function cleanupStorageNow() {
    try {
      const r = await fetch('/api/storage/cleanup', { method: 'POST' });
      await r.json();
      loadStorage();
    } catch (e) { showToast('Error: ' + e); }
  }
  window.cleanupStorageNow = cleanupStorageNow;

  async function saveWifiUplink() {
    const body = {
      measurement_link: document.getElementById('meas-link').value,
      ssid: (document.getElementById('wu-ssid').value || '').trim(),
      password: document.getElementById('wu-pass').value || '',
      interface: document.getElementById('wu-iface').value,
      hidden: document.getElementById('wu-hidden').checked,
      enabled: document.getElementById('wu-enabled').checked,
    };
    const st = document.getElementById('wu-status');
    if (st) st.textContent = body.enabled ? t('wu_connecting', 'Connecting...') : t('toast_saving', 'Applying settings, please wait...');
    try {
      const r = await fetch('/api/wifi-uplink/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json();
      document.getElementById('wu-pass').value = '';
      renderWifiUplink(d);
      showToast((r.ok ? '✔ ' : '✖ ') + (d.message || ''));
    } catch (e) { showToast('Error: ' + e); }
  }

  async function wifiUplinkAction(action) {
    try {
      const r = await fetch('/api/wifi-uplink/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      const d = await r.json();
      renderWifiUplink(d);
      showToast((r.ok ? '✔ ' : '✖ ') + (d.message || ''));
    } catch (e) { showToast('Error: ' + e); }
  }

  // Central collector (opt-in)
  function renderCollectorStatus(d) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    const uid = document.getElementById('col-box-uid');
    if (uid) uid.textContent = d.box_uid || '--';
    set('col-url', d.url || '');
    set('col-case', d.case_id || '');
    set('col-interval', d.interval_min || 15);
    const chk = (id, v) => { const el = document.getElementById(id); if (el) el.checked = !!v; };
    chk('col-enabled', d.enabled);
    chk('col-diag', d.share_diagnostics);
    chk('col-remote', d.allow_remote_control);
    const th = document.getElementById('col-token-hint');
    if (th) th.textContent = d.token_set ? t('col_token_saved', 'A token is saved; leave empty to keep it.') : '';
    const st = document.getElementById('col-status');
    if (st) {
      const last = d.last || {};
      let txt = d.enabled ? t('col_on', 'Sending is on.') : t('col_off', 'Sending is off.');
      if (last.ts) txt += ' ' + t('col_last', 'Last upload:') + ' ' + new Date(last.ts * 1000).toLocaleString() + ' (' + (last.ok ? '✔' : '✖') + ' ' + (last.message || '') + ')';
      if (d.pending_speedtests) txt += ' ' + t('col_pending', 'Waiting to be sent: {n} speed test(s).').replace('{n}', d.pending_speedtests);
      st.textContent = txt;
    }
  }

  async function loadCollector() {
    try {
      const res = await fetch('/api/collector/status');
      if (res.ok) renderCollectorStatus(await res.json());
    } catch (e) {}
  }

  async function saveCollector() {
    const body = {
      url: (document.getElementById('col-url').value || '').trim(),
      token: (document.getElementById('col-token').value || '').trim(),
      case_id: (document.getElementById('col-case').value || '').trim(),
      interval_min: parseInt(document.getElementById('col-interval').value || '15', 10),
      enabled: document.getElementById('col-enabled').checked,
      share_diagnostics: document.getElementById('col-diag').checked,
      allow_remote_control: document.getElementById('col-remote').checked,
    };
    try {
      const res = await fetch('/api/collector/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await res.json();
      if (!res.ok) { showToast(d.message || 'Error'); return; }
      document.getElementById('col-token').value = '';
      renderCollectorStatus(d);
      if (body.enabled && !d.enabled) showToast(t('col_need_url', 'Set the collector address and token to turn sending on.'));
      else showToast(t('col_saved', 'Collector settings saved.'));
    } catch (e) {
      showToast('Error: ' + e);
    }
  }

  async function sendCollectorNow() {
    const st = document.getElementById('col-status');
    if (st) st.textContent = t('col_sending', 'Sending...');
    try {
      const res = await fetch('/api/collector/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      const d = await res.json();
      showToast((d.ok ? '✔ ' : '✖ ') + (d.message || ''));
    } catch (e) {
      showToast('Error: ' + e);
    }
    loadCollector();
  loadWifiUplink();
  }

  // Logout Handler
  function performLogout() {
    if (!confirm(t('logout_confirm', 'Are you sure you want to log out from NetworkMeasureBox?'))) {
      return;
    }
    showToast(t('logging_out', 'Logging out...'));
    try {
      localStorage.removeItem('nmb_token');
      sessionStorage.clear();
    } catch (e) {}

    try {
      const xhr = new XMLHttpRequest();
      xhr.open("GET", "/api/auth/logout", true, "logout_purge_user", "invalid_password");
      xhr.onreadystatechange = function() {
        if (xhr.readyState === 4) {
          window.location.href = "/logout";
        }
      };
      xhr.send();
      setTimeout(() => {
        window.location.href = "/logout";
      }, 400);
    } catch (err) {
      window.location.href = "/logout";
    }
  }

  // ==========================================
  // Distro-Aware Package Management
  // ==========================================
  let upgradePollTimer = null;

  async function loadSystemInfo() {
    try {
      const res = await fetch('/api/system/info');
      if (res.ok) {
        const d = await res.json();
        const badge = document.getElementById('os-distro-badge');
        if (badge) {
          const pm = d.package_manager ? ` (${d.package_manager.toUpperCase()})` : '';
          const hw = d.hardware_model ? ` • ${d.hardware_model}` : '';
          badge.textContent = `OS: ${d.distro_name || 'Linux'} ${d.distro_version || ''}${pm}${hw}`;
        }
      }
    } catch (e) {
      console.debug('loadSystemInfo error:', e);
    }
  }

  async function checkSystemUpdates() {
    const statusText = document.getElementById('update-status-text');
    const term = document.getElementById('upgrade-terminal-box');
    const badge = document.getElementById('os-distro-badge');
    const btn = document.getElementById('btn-check-updates');
    if (btn) btn.disabled = true;
    if (statusText) statusText.textContent = 'Checking package repositories...';
    if (term) term.textContent = 'Querying package manager repositories...';
    try {
      const res = await fetch('/api/system/updates/check');
      if (res.ok) {
        const d = await res.json();
        const pkgList = (d.packages && d.packages.length) ? d.packages.join('\n') : 'All system packages are up to date.';
        const pm = (d.package_manager || d.pkg_manager || 'apt').toUpperCase();
        if (term) {
          term.textContent = `Distro: ${d.distro || 'Linux'}
Package Manager: ${pm}
Upgradable Packages: ${d.upgradable_count || 0}

${pkgList}`;
        }
        if (badge && d.distro) {
          badge.textContent = `OS: ${d.distro} (${pm})`;
        }
        if (statusText) statusText.textContent = d.message || `${d.upgradable_count || 0} upgradable package(s) found.`;
      } else {
        if (statusText) statusText.textContent = 'Failed to check updates.';
      }
    } catch (e) {
      if (statusText) statusText.textContent = 'Error: ' + e;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function runSystemUpgrade() {
    if (!confirm('Start asynchronous system package upgrade in the background?')) return;
    const btn = document.getElementById('btn-run-upgrade');
    btn.disabled = true;
    showToast('System upgrade initiated in background...');
    try {
      await fetch('/api/system/updates/upgrade', { method: 'POST' });
      pollUpgradeStatus();
    } catch (e) {
      showToast('Error initiating upgrade: ' + e);
      btn.disabled = false;
    }
  }

  async function pollUpgradeStatus() {
    if (upgradePollTimer) clearTimeout(upgradePollTimer);
    try {
      const res = await fetch('/api/system/updates/status');
      if (res.ok) {
        const d = await res.json();
        const term = document.getElementById('upgrade-terminal-box');
        if (term) term.textContent = d.log || 'Upgrade in progress...';
        if (d.in_progress) {
          document.getElementById('btn-run-upgrade').disabled = true;
          upgradePollTimer = setTimeout(pollUpgradeStatus, 2000);
          return;
        } else {
          document.getElementById('btn-run-upgrade').disabled = false;
          if (d.last_status === 'success') {
            showToast('✅ System upgrade completed successfully!');
          }
        }
      }
    } catch (e) {}
  }

  // ==========================================
  // Linux Kernel & Hardware Offload Acceleration
  // ==========================================
  async function loadKernelStatus() {
    try {
      const res = await fetch('/api/system/kernel-tuning');
      if (!res.ok) return;
      const d = await res.json();
      if (document.getElementById('kernel-tcp-cc')) {
        document.getElementById('kernel-tcp-cc').textContent = (d.tcp_congestion_control || 'bbr').toUpperCase() + (d.is_fq_active ? ' (FQ Paced)' : '');
      }
      if (document.getElementById('kernel-rps-status')) {
        const cpus = d.cpu_count || 1;
        document.getElementById('kernel-rps-status').textContent = `${cpus} CPU Cores Active`;
      }
      if (document.getElementById('kernel-mem-status')) {
        document.getElementById('kernel-mem-status').textContent = `${d.rmem_max_mb || 64.0} MB`;
      }
      if (document.getElementById('kernel-busy-status')) {
        document.getElementById('kernel-busy-status').textContent = `${d.busy_poll_us || 50} µs`;
      }
      if (document.getElementById('kernel-version-text')) {
        document.getElementById('kernel-version-text').textContent = d.kernel_release || 'Linux';
      }

      const tbody = document.getElementById('kernel-iface-tbody');
      if (tbody && d.interfaces && d.interfaces.length > 0) {
        let html = '';
        d.interfaces.forEach(it => {
          const speedStr = (it.speed_mbps && it.speed_mbps > 0) ? `${it.speed_mbps} Mbps` : '--';
          const rpsBadge = it.rps_enabled ? `<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981;">Mask 0x${escapeHtml(it.rps_cpus)} (Active)</span>` : '<span class="badge-pill" style="color: #94a3b8;">Disabled</span>';
          const rfsStr = (it.rfs_flow_cnt > 0) ? `<span style="color: #38bdf8; font-weight: 600;">${escapeHtml(it.rfs_flow_cnt)} flows</span>` : '--';
          const xpsStr = (it.xps_cpus && it.xps_cpus !== '0') ? `<span style="color: #a855f7;">Mask 0x${escapeHtml(it.xps_cpus)}</span>` : '--';
          html += `<tr>
            <td style="font-weight: 700; color: #ffffff;">${escapeHtml(it.name)}</td>
            <td>${escapeHtml(speedStr)}</td>
            <td>${it.mtu || 1500}</td>
            <td>${rpsBadge}</td>
            <td>${escapeHtml(rfsStr)}</td>
            <td>${escapeHtml(xpsStr)}</td>
            <td><span style="color: #10b981; font-weight: 600;">TSO, GSO, GRO, Checksum</span></td>
          </tr>`;
        });
        tbody.innerHTML = html;
      }
    } catch (e) {
      console.debug('loadKernelStatus error:', e);
    }
  }

  async function applyKernelTuning() {
    const btn = document.getElementById('btn-apply-kernel-tuning');
    if (btn) btn.disabled = true;
    showToast('Optimizing Linux kernel network stack and multi-core RPS queues...');
    try {
      const res = await fetch('/api/system/kernel-tuning/apply', { method: 'POST' });
      if (res.ok) {
        const d = await res.json();
        showToast('Kernel network stack successfully optimized for maximum performance!');
        loadKernelStatus();
      } else {
        showToast('Kernel optimization returned error');
      }
    } catch (e) {
      showToast('Error applying kernel tuning: ' + e);
    } finally {
      if (btn) btn.disabled = false;
    }
  }


  // ==========================================
  // Remote Access & VPN & Proxy Subtabs
  // ==========================================
  let activeRemoteSubtab = 'vpnhub';
  let lastWireguardPeers = [];
  let lastOpenvpnClients = [];
  let lastWireguardStatus = null;
  let lastOpenvpnStatus = null;

  function switchRemoteSubtab(tabName) {
    activeRemoteSubtab = tabName;
    ['vpnhub', 'tailscale', 'guide', 'wireguard', 'openvpn', 'duckdns', 'proxy'].forEach(t => {
      const btn = document.getElementById('btn-subtab-' + t);
      const pane = document.getElementById('subtab-content-' + t);
      if (btn) {
        if (t === tabName) {
          btn.classList.add('active');
          const nav = btn.closest('.remote-subnav') || btn.parentElement;
          if (nav && typeof nav.scrollTo === 'function') {
            const left = btn.offsetLeft - nav.offsetLeft - 16;
            nav.scrollTo({ left: Math.max(0, left), behavior: 'smooth' });
          }
        } else {
          btn.classList.remove('active');
        }
      }
      if (pane) pane.style.display = (t === tabName) ? 'block' : 'none';
    });

    if (tabName === 'vpnhub') {
      loadWireguardStatus();
      loadOpenvpnStatus();
      loadTailscaleStatus();
      loadPortGuideStatus();
    } else if (tabName === 'tailscale') {
      loadTailscaleStatus();
    } else if (tabName === 'guide') {
      loadPortGuideStatus();
    } else if (tabName === 'duckdns') {
      loadDuckdnsStatus();
    } else if (tabName === 'wireguard') {
      loadWireguardStatus();
    } else if (tabName === 'openvpn') {
      loadOpenvpnStatus();
    } else if (tabName === 'proxy') {
      loadProxyStatus();
    }
  }

  function loadRemoteAccessStatus() {
    loadDuckdnsStatus();
    loadWireguardStatus();
    loadOpenvpnStatus();
    loadTailscaleStatus();
    loadProxyStatus();
    loadPortGuideStatus();
  }

  function renderVpnHub() {
    // 1. Update WireGuard KPI Badge & Toggle
    const wgBadge = document.getElementById('pivpn-wg-badge');
    const wgBtn = document.getElementById('pivpn-btn-wg-toggle');
    if (wgBadge && lastWireguardStatus) {
      const isUp = !!(lastWireguardStatus.active || lastWireguardStatus.running);
      wgBadge.className = 'badge';
      if (isUp) {
        wgBadge.style.background = 'rgba(16, 185, 129, 0.15)';
        wgBadge.style.color = '#10b981';
        wgBadge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
        wgBadge.textContent = t('vpn_wg_active', '🟢 Active (Port 51820)');
      } else {
        wgBadge.style.background = 'rgba(148, 163, 184, 0.15)';
        wgBadge.style.color = '#94a3b8';
        wgBadge.style.border = '1px solid #475569';
        wgBadge.textContent = t('vpn_status_stopped', '⚫ Stopped');
      }
      if (wgBtn) {
        wgBtn.className = isUp ? 'btn-danger' : 'btn-primary';
        wgBtn.textContent = isUp ? t('vpn_btn_stop', '⏹️ Stop') : t('vpn_btn_start', '▶️ Start');
      }
    }

    // 2. Update OpenVPN KPI Badge & Toggle
    const ovpnBadge = document.getElementById('pivpn-ovpn-badge');
    const ovpnBtn = document.getElementById('pivpn-btn-ovpn-toggle');
    if (ovpnBadge && lastOpenvpnStatus) {
      const isUp = !!(lastOpenvpnStatus.active || lastOpenvpnStatus.running);
      ovpnBadge.className = 'badge';
      if (isUp) {
        ovpnBadge.style.background = 'rgba(16, 185, 129, 0.15)';
        ovpnBadge.style.color = '#10b981';
        ovpnBadge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
        ovpnBadge.textContent = t('vpn_ovpn_active', '🟢 Active (Port 1194)');
      } else {
        ovpnBadge.style.background = 'rgba(148, 163, 184, 0.15)';
        ovpnBadge.style.color = '#94a3b8';
        ovpnBadge.style.border = '1px solid #475569';
        ovpnBadge.textContent = t('vpn_status_stopped', '⚫ Stopped');
      }
      if (ovpnBtn) {
        ovpnBtn.className = isUp ? 'btn-danger' : 'btn-primary';
        ovpnBtn.textContent = isUp ? t('vpn_btn_stop', '⏹️ Stop') : t('vpn_btn_start', '▶️ Start');
      }
    }

    // 3. Render Combined Clients Table
    const tbody = document.getElementById('pivpn-clients-tbody');
    const totalBadge = document.getElementById('pivpn-total-clients-badge');
    if (!tbody) return;

    const totalCount = lastWireguardPeers.length + lastOpenvpnClients.length;
    if (totalBadge) totalBadge.textContent = `${totalCount} ${t('vpn_clients_count', 'Clients')}`;

    if (totalCount === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 18px;">' + t('vpn_no_clients', 'No configured VPN clients yet. Use the 1-click PiVPN generator above to create your first client profile.') + '</td></tr>';
      return;
    }

    let html = '';

    // Render WireGuard peers
    lastWireguardPeers.forEach(p => {
      const hsSec = p.latest_handshake || 0;
      let hsDisplay = '--';
      let isConnected = false;
      if (hsSec > 0) {
        if (hsSec < 180) {
          isConnected = true;
          hsDisplay = `<span style="color: #10b981; font-weight: 600;">${t('vpn_active_status', 'Active')} (${escapeHtml(p.latest_handshake_ago || hsSec + 's')})</span>`;
        } else {
          hsDisplay = `<span style="color: var(--text-muted);">${escapeHtml(p.latest_handshake_ago || Math.floor(hsSec / 60) + 'm')}</span>`;
        }
      }
      const statusBadge = isConnected
        ? '<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + t('vpn_status_connected', '🟢 Connected') + '</span>'
        : '<span class="badge" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569; padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + t('vpn_status_offline', 'Offline') + '</span>';

      const rxFormatted = formatBytes(p.transfer_rx || 0);
      const txFormatted = formatBytes(p.transfer_tx || 0);
      let ipDisplay = p.allowed_ips || p.client_ip || '--';

      html += `<tr>
        <td style="white-space: nowrap;"><span class="badge-pill" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 11px; font-weight: 700; white-space: nowrap;">🛡️ WireGuard</span></td>
        <td style="font-weight: 700; color: #f1f5f9; white-space: nowrap;">${escapeHtml(p.name)}</td>
        <td style="font-family: monospace; font-size: 12px; color: #cbd5e1; white-space: nowrap;">${escapeHtml(ipDisplay)}</td>
        <td style="white-space: nowrap;">${statusBadge}</td>
        <td style="font-size: 12px; color: var(--text-muted); white-space: nowrap;">${escapeHtml(p.endpoint || '--')}</td>
        <td style="font-size: 12px; white-space: nowrap;">↓ ${rxFormatted} / ↑ ${txFormatted}</td>
        <td style="font-size: 12px; white-space: nowrap;">${hsDisplay}</td>
        <td style="display: flex; gap: 6px; white-space: nowrap; flex-wrap: nowrap;">
          <button type="button" class="btn-primary" style="font-size: 11px; padding: 3px 8px; white-space: nowrap;" onclick="showWireguardQr(${jsArg(p.id)}, ${jsArg(p.name)})">
            📱 QR
          </button>
          <a href="/api/wireguard/peer/config?id=${escapeHtml(p.id)}" download="${escapeHtml(p.name)}.conf" class="btn-secondary" style="font-size: 11px; padding: 3px 8px; text-decoration: none; white-space: nowrap;">
            📥 .conf
          </a>
          <button type="button" class="btn-danger" style="font-size: 11px; padding: 3px 8px; white-space: nowrap;" onclick="deleteWireguardPeer(${jsArg(p.id)}, ${jsArg(p.name)})">
            ✕
          </button>
        </td>
      </tr>`;
    });

    // Render OpenVPN clients
    lastOpenvpnClients.forEach(c => {
      const isConnected = !!c.connected;
      const statusBadge = isConnected
        ? '<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + t('vpn_status_connected', '🟢 Connected') + '</span>'
        : '<span class="badge" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569; padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + t('vpn_status_offline', 'Offline') + '</span>';

      const rxFormatted = formatBytes(c.bytes_received || 0);
      const txFormatted = formatBytes(c.bytes_sent || 0);

      html += `<tr>
        <td style="white-space: nowrap;"><span class="badge-pill" style="background: rgba(251, 191, 36, 0.15); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.3); font-size: 11px; font-weight: 700; white-space: nowrap;">🔒 OpenVPN</span></td>
        <td style="font-weight: 700; color: #f1f5f9; white-space: nowrap;">${escapeHtml(c.name)}</td>
        <td style="font-family: monospace; font-size: 12px; color: #cbd5e1; white-space: nowrap;">${t('vpn_dynamic_pki', '(Dynamic PKI)')}</td>
        <td style="white-space: nowrap;">${statusBadge}</td>
        <td style="font-size: 12px; color: var(--text-muted); white-space: nowrap;">${escapeHtml(c.real_address || '--')}</td>
        <td style="font-size: 12px; white-space: nowrap;">↓ ${rxFormatted} / ↑ ${txFormatted}</td>
        <td style="font-size: 12px; color: var(--text-muted); white-space: nowrap;">${escapeHtml(c.connected_since || '--')}</td>
        <td style="display: flex; gap: 6px; white-space: nowrap; flex-wrap: nowrap;">
          <a href="/api/openvpn/client/config?name=${encodeURIComponent(c.name)}" download="${escapeHtml(c.name)}.ovpn" class="btn-primary" style="font-size: 11px; padding: 3px 8px; text-decoration: none; white-space: nowrap;">
            📥 .ovpn
          </a>
          <button type="button" class="btn-danger" style="font-size: 11px; padding: 3px 8px; white-space: nowrap;" onclick="deleteOpenvpnClient(${jsArg(c.name)})">
            ✕
          </button>
        </td>
      </tr>`;
    });

    tbody.innerHTML = html;
  }

  async function loadPortGuideStatus() {
    try {
      const res = await fetch('/api/wireguard/endpoints');
      if (res.ok) {
        const d = await res.json();
        const eps = d.endpoints || [];
        let lanIp = window.location.hostname || '192.168.1.100';
        let pubIp = '--';
        let ipv6 = '--';

        eps.forEach(ep => {
          if (ep.type === 'lan' && ep.host) lanIp = ep.host;
          else if ((ep.type === 'duckdns' || ep.type === 'wan') && ep.host) pubIp = ep.host;
          else if (ep.type === 'ipv6' && ep.host) ipv6 = ep.host;
        });

        if (document.getElementById('pivpn-lan-ip')) document.getElementById('pivpn-lan-ip').textContent = lanIp;
        if (document.getElementById('pivpn-pub-ip')) document.getElementById('pivpn-pub-ip').textContent = pubIp;
        if (document.getElementById('pivpn-pub-ipv6')) document.getElementById('pivpn-pub-ipv6').textContent = ipv6;

        if (document.getElementById('guide-val-lan')) document.getElementById('guide-val-lan').textContent = lanIp;
        if (document.getElementById('guide-val-pub4')) document.getElementById('guide-val-pub4').textContent = pubIp;
        if (document.getElementById('guide-val-ipv6')) document.getElementById('guide-val-ipv6').textContent = ipv6;
        if (document.getElementById('guide-cgnat-ipv6')) document.getElementById('guide-cgnat-ipv6').textContent = ipv6;

        document.querySelectorAll('.guide-box-lan').forEach(el => { el.textContent = lanIp; });
      }
    } catch (e) {
      console.debug('loadPortGuideStatus error:', e);
    }
  }

  async function pivpnQuickAddClient() {
    const proto = document.getElementById('pivpn-quick-proto')?.value || 'wireguard';
    const nameInput = document.getElementById('pivpn-quick-name');
    const name = (nameInput?.value || '').trim();
    if (!name) {
      showToast(t('vpn_toast_client_name', 'Please enter a client name.'));
      return;
    }
    showToast(t('vpn_toast_generating', 'Generating client profile...') + ` (${proto.toUpperCase()})...`);
    if (proto === 'wireguard') {
      try {
        const res = await fetch('/api/wireguard/peer/add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name })
        });
        const d = await res.json();
        if (res.ok && (d.status === 'ok' || d.peer)) {
          showToast(t('vpn_toast_created', 'Client profile created successfully: ') + name);
          if (nameInput) nameInput.value = '';
          await loadWireguardStatus();
          showWireguardQr(d.peer ? d.peer.id : (d.id || name), name);
        } else {
          showToast('❌ ' + (d.message || t('vpn_err_create', 'Failed to create profile')));
        }
      } catch (e) {
        showToast(t('vpn_err_create', 'Operation error: ') + e);
      }
    } else {
      try {
        const res = await fetch('/api/openvpn/client/add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name })
        });
        const d = await res.json();
        if (res.ok && d.status === 'ok') {
          showToast(t('vpn_toast_created', 'Client profile created successfully: ') + name);
          if (nameInput) nameInput.value = '';
          await loadOpenvpnStatus();
          const dlLink = document.createElement('a');
          dlLink.href = `/api/openvpn/client/config?name=${encodeURIComponent(name)}`;
          dlLink.download = `${name}.ovpn`;
          document.body.appendChild(dlLink);
          dlLink.click();
          document.body.removeChild(dlLink);
        } else {
          showToast('❌ ' + (d.message || t('vpn_err_create', 'Failed to create profile')));
        }
      } catch (e) {
        showToast(t('vpn_err_create', 'Operation error: ') + e);
      }
    }
  }

  // ---- DynDNS (DuckDNS / dynv6) ----
  let savedDuckdnsConfig = {
    enabled: false,
    provider: 'duckdns',
    domain: '',
    token_set: false,
    interval_min: 10,
    custom_ip: '',
    custom_ipv6: '',
    ipv6_mode: 'auto',
    fqdn: '',
  };
  let duckdnsCountdownTimer = null;
  let duckdnsNextTs = 0;

  function onDynDnsProviderChange() {
    const prov = document.getElementById('duckdns-provider')?.value || 'duckdns';
    const domLabel = document.getElementById('duckdns-domain-label');
    const domSuffix = document.getElementById('duckdns-domain-suffix');
    const zoneHint = document.getElementById('duckdns-zone-hint');
    const tokHint = document.getElementById('duckdns-token-hint');
    const domInput = document.getElementById('duckdns-domain');

    if (prov === 'dynv6') {
      if (domLabel) domLabel.textContent = t('ddns_zone_label', 'dynv6 zone name (e.g. my-box.v6.army):');
      if (domSuffix) domSuffix.style.display = 'none';
      if (zoneHint) zoneHint.style.display = 'block';
      if (tokHint) tokHint.style.display = 'block';
      if (domInput && (!domInput.value || domInput.placeholder === 'my-box')) domInput.placeholder = 'my-box.v6.army';
    } else {
      if (domLabel) domLabel.textContent = t('duckdns_domain', 'DuckDNS Aldomain (.duckdns.org):');
      if (domSuffix) domSuffix.style.display = 'inline';
      if (zoneHint) zoneHint.style.display = 'none';
      if (tokHint) tokHint.style.display = 'none';
      if (domInput && domInput.placeholder === 'my-box.v6.army') domInput.placeholder = 'my-box';
    }
  }

  function onDynDnsIpv6ModeChange() {
    const mode = document.getElementById('duckdns-ipv6-mode')?.value || 'auto';
    const wrap = document.getElementById('duckdns-custom-ipv6-wrap');
    if (wrap) wrap.style.display = (mode === 'custom') ? 'block' : 'none';
  }

  function updateDuckdnsCountdown() {
    const el = document.getElementById('duckdns-countdown-badge');
    if (!el) return;
    if (!duckdnsNextTs || duckdnsNextTs <= 0 || !savedDuckdnsConfig.enabled) {
      el.textContent = '--';
      return;
    }
    const diff = Math.max(0, Math.round(duckdnsNextTs - Date.now() / 1000));
    if (diff <= 0) {
      el.textContent = t('duckdns_syncing', 'Syncing...');
      return;
    }
    const m = Math.floor(diff / 60);
    const s = diff % 60;
    el.textContent = `${m}m ${s < 10 ? '0' : ''}${s}s`;
  }

  function checkDuckdnsUnsavedChanges() {
    const alertEl = document.getElementById('duckdns-unsaved-alert');
    const badgeEl = document.getElementById('duckdns-config-state-badge');
    if (!alertEl || !badgeEl) return;

    const enNow = !!document.getElementById('duckdns-enabled')?.checked;
    const provNow = document.getElementById('duckdns-provider')?.value || 'duckdns';
    const domNow = (document.getElementById('duckdns-domain')?.value || '').trim();
    const intNow = parseInt(document.getElementById('duckdns-interval')?.value, 10) || 10;
    const custNow = (document.getElementById('duckdns-custom-ip')?.value || '').trim();
    const custV6Now = (document.getElementById('duckdns-custom-ipv6')?.value || '').trim();
    const v6ModeNow = document.getElementById('duckdns-ipv6-mode')?.value || 'auto';
    const tokNow = (document.getElementById('duckdns-token')?.value || '').trim();

    const isChanged = (
      enNow !== savedDuckdnsConfig.enabled ||
      provNow !== (savedDuckdnsConfig.provider || 'duckdns') ||
      domNow !== savedDuckdnsConfig.domain ||
      intNow !== savedDuckdnsConfig.interval_min ||
      custNow !== savedDuckdnsConfig.custom_ip ||
      custV6Now !== (savedDuckdnsConfig.custom_ipv6 || '') ||
      v6ModeNow !== (savedDuckdnsConfig.ipv6_mode || 'auto') ||
      tokNow.length > 0
    );

    if (isChanged) {
      alertEl.style.display = 'block';
      badgeEl.className = 'badge';
      badgeEl.style.background = 'rgba(245, 158, 11, 0.15)';
      badgeEl.style.color = '#f59e0b';
      badgeEl.style.border = '1px solid rgba(245, 158, 11, 0.35)';
      badgeEl.textContent = t('duckdns_badge_unsaved', '⚠️ Unsaved');   // short: the long warning squeezed the title
    } else {
      alertEl.style.display = 'none';
      badgeEl.className = 'badge';
      badgeEl.style.background = savedDuckdnsConfig.enabled ? 'rgba(16, 185, 129, 0.15)' : 'rgba(148, 163, 184, 0.15)';
      badgeEl.style.color = savedDuckdnsConfig.enabled ? '#10b981' : '#94a3b8';
      badgeEl.style.border = savedDuckdnsConfig.enabled ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid #475569';
      badgeEl.textContent = savedDuckdnsConfig.enabled ? t('duckdns_saved_active', 'Saved & Active') : t('duckdns_saved_inactive', 'Disabled');
    }
  }

  async function loadDuckdnsStatus() {
    try {
      const res = await fetch('/api/duckdns/status');
      if (!res.ok) return;
      const d = await res.json();

      const prov = d.provider || 'duckdns';
      const effInterval = d.update_interval_min || d.interval_min || 10;
      savedDuckdnsConfig = {
        enabled: !!d.enabled,
        provider: prov,
        domain: d.domain || '',
        token_set: !!d.token_set,
        interval_min: effInterval,
        custom_ip: d.custom_ip || '',
        custom_ipv6: d.custom_ipv6 || '',
        ipv6_mode: d.ipv6_mode || 'auto',
        fqdn: d.fqdn || (d.domain ? (prov === 'dynv6' || d.domain.includes('.') ? d.domain : d.domain + '.duckdns.org') : ''),
      };

      duckdnsNextTs = d.next_update_ts || 0;
      if (!duckdnsCountdownTimer) {
        duckdnsCountdownTimer = setInterval(updateDuckdnsCountdown, 1000);
      }
      updateDuckdnsCountdown();

      const provSelect = document.getElementById('duckdns-provider');
      const enChbox = document.getElementById('duckdns-enabled');
      const domInput = document.getElementById('duckdns-domain');
      const intInput = document.getElementById('duckdns-interval');
      const custInput = document.getElementById('duckdns-custom-ip');
      const custV6Input = document.getElementById('duckdns-custom-ipv6');
      const v6ModeSelect = document.getElementById('duckdns-ipv6-mode');

      if (provSelect && !provSelect.dataset.focused) {
        provSelect.value = prov;
        onDynDnsProviderChange();
      }
      if (enChbox && d.enabled !== undefined && !enChbox.dataset.focused) enChbox.checked = !!d.enabled;
      if (domInput && d.domain !== undefined && !domInput.dataset.focused) domInput.value = d.domain || '';
      if (intInput && !intInput.dataset.focused) intInput.value = effInterval;
      if (custInput && d.custom_ip !== undefined && !custInput.dataset.focused) custInput.value = d.custom_ip || '';
      if (custV6Input && d.custom_ipv6 !== undefined && !custV6Input.dataset.focused) custV6Input.value = d.custom_ipv6 || '';
      if (v6ModeSelect && !v6ModeSelect.dataset.focused) {
        v6ModeSelect.value = d.ipv6_mode || 'auto';
        onDynDnsIpv6ModeChange();
      }

      // Update Saved Configuration Summary Box
      const svProv = document.getElementById('duckdns-saved-provider');
      if (svProv) svProv.textContent = (prov === 'dynv6') ? 'dynv6.com' : 'DuckDNS';

      const svFqdn = document.getElementById('duckdns-saved-fqdn');
      if (svFqdn) svFqdn.textContent = savedDuckdnsConfig.fqdn || '(' + t('not_specified', 'Not specified') + ')';

      const svInt = document.getElementById('duckdns-saved-interval');
      if (svInt) svInt.textContent = `${effInterval} ${t('duckdns_minutes_abbr', 'min')}`;

      const svEn = document.getElementById('duckdns-saved-enabled');
      if (svEn) {
        svEn.textContent = d.enabled ? ('🟢 ' + t('duckdns_saved_active', 'Enabled')) : ('⚪ ' + t('duckdns_saved_inactive', 'Disabled'));
      }

      const svTok = document.getElementById('duckdns-saved-token-state');
      if (svTok) {
        svTok.textContent = d.token_set ? '•••••••••••• (' + t('token_set', 'Set') + ')' : t('not_specified', 'Not specified');
      }

      const svV6Mode = document.getElementById('duckdns-saved-ipv6-mode');
      if (svV6Mode) svV6Mode.textContent = d.ipv6_mode || 'auto';

      const svCust = document.getElementById('duckdns-saved-custom-ip');
      if (svCust) {
        svCust.textContent = d.custom_ip ? d.custom_ip : 'Automatikus WAN IPv4';
      }

      // Update Live Status Card
      const badge = document.getElementById('duckdns-status-badge');
      if (badge) {
        if (!d.enabled) {
          badge.className = 'badge';
          badge.style.background = 'rgba(148, 163, 184, 0.15)';
          badge.style.color = '#94a3b8';
          badge.style.border = '1px solid #475569';
          badge.textContent = t('duckdns_saved_inactive', 'Disabled');
        } else if (d.last_status === 'OK' || d.last_status === 'success') {
          badge.className = 'badge';
          badge.style.background = 'rgba(16, 185, 129, 0.15)';
          badge.style.color = '#10b981';
          badge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
          badge.textContent = t('ddns_synced', '🟢 Synchronized (OK)');
        } else if (d.last_status === 'KO' || d.last_status === 'failed') {
          badge.className = 'badge';
          badge.style.background = 'rgba(239, 68, 68, 0.15)';
          badge.style.color = '#ef4444';
          badge.style.border = '1px solid rgba(239, 68, 68, 0.3)';
          badge.textContent = t('ddns_error', '🔴 Error (KO)');
        } else {
          badge.className = 'badge';
          badge.style.background = 'rgba(56, 189, 248, 0.15)';
          badge.style.color = '#38bdf8';
          badge.style.border = '1px solid rgba(56, 189, 248, 0.3)';
          badge.textContent = d.last_status || t('ddns_waiting', 'Waiting');
        }
      }

      const fqdnEl = document.getElementById('duckdns-detected-fqdn');
      if (fqdnEl) fqdnEl.textContent = savedDuckdnsConfig.fqdn || '--';

      const ipEl = document.getElementById('duckdns-detected-ip');
      if (ipEl) ipEl.textContent = d.detected_ip || d.last_ip || '--';

      const ipV6El = document.getElementById('duckdns-detected-ipv6');
      if (ipV6El) ipV6El.textContent = d.detected_ipv6 || d.last_ipv6 || d.custom_ipv6 || t('ddns_no_ipv6', '(No global IPv6)');

      const timeEl = document.getElementById('duckdns-last-time');
      if (timeEl) timeEl.textContent = d.last_update ? d.last_update.substring(0, 19).replace('T', ' ') : 'Soha';

      const nextEl = document.getElementById('duckdns-next-time');
      if (nextEl) nextEl.textContent = d.next_update ? d.next_update.substring(0, 19).replace('T', ' ') : '--';

      const msgBox = document.getElementById('duckdns-msg-box');
      if (msgBox) {
        msgBox.textContent = `[${prov.toUpperCase()}] FQDN: ${savedDuckdnsConfig.fqdn || '--'} • WAN IPv4: ${d.detected_ip || d.last_ip || '--'} • WAN IPv6: ${d.detected_ipv6 || d.last_ipv6 || '--'} • ${t('ddns_response', 'Response')}: ${d.last_message || d.last_status || t('ddns_done', 'Done')}`;
      }

      checkDuckdnsUnsavedChanges();
    } catch (e) {
      console.error('loadDuckdnsStatus error:', e);
    }
  }

  async function saveDuckdnsSettings() {
    const btn = document.getElementById('btn-save-duckdns');
    const oldText = btn ? btn.textContent : '';
    if (btn) {
      btn.disabled = true;
      btn.textContent = '💾 ' + t('saving', 'Saving...');
    }

    const provider = document.getElementById('duckdns-provider')?.value || 'duckdns';
    const enabled = !!document.getElementById('duckdns-enabled')?.checked;
    const domain = (document.getElementById('duckdns-domain')?.value || '').trim();
    const token = (document.getElementById('duckdns-token')?.value || '').trim();
    const interval_min = parseInt(document.getElementById('duckdns-interval')?.value, 10) || 10;
    const custom_ip = (document.getElementById('duckdns-custom-ip')?.value || '').trim();
    const custom_ipv6 = (document.getElementById('duckdns-custom-ipv6')?.value || '').trim();
    const ipv6_mode = document.getElementById('duckdns-ipv6-mode')?.value || 'auto';

    try {
      const res = await fetch('/api/duckdns/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled,
          provider,
          domain,
          token,
          interval_min,
          update_interval_min: interval_min,
          custom_ip,
          custom_ipv6,
          ipv6_mode,
        }),
      });
      const d = await res.json();
      if (res.ok) {
        const tokInput = document.getElementById('duckdns-token');
        if (tokInput && token) tokInput.value = '';
        showToast(t('dyndns_saved_success', `✅ ${provider === 'dynv6' ? 'dynv6.com' : 'DuckDNS'} settings saved successfully! Interval: ${interval_min} min`));
        await loadDuckdnsStatus();
        // The update itself runs a moment later in the background: show its result too.
        setTimeout(() => loadDuckdnsStatus(), 6000);
        setTimeout(() => loadDuckdnsStatus(), 20000);

        // Highlight card to visually confirm save
        const svCard = document.getElementById('duckdns-saved-card');
        if (svCard) {
          svCard.style.transition = 'background 0.3s ease, border-color 0.3s ease';
          svCard.style.background = 'rgba(16, 185, 129, 0.18)';
          svCard.style.borderColor = '#10b981';
          setTimeout(() => {
            svCard.style.background = 'rgba(56, 189, 248, 0.06)';
            svCard.style.borderColor = 'rgba(56, 189, 248, 0.25)';
          }, 1500);
        }
      } else {
        showToast(t('dyndns_save_err', '❌ DynDNS save error: ') + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast(t('dyndns_save_err', '❌ DynDNS save error: ') + e);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = oldText;
      }
    }
  }

  async function updateDuckdnsNow() {
    const btn = document.getElementById('btn-update-duckdns');
    const oldText = btn ? btn.textContent : '';
    if (btn) {
      btn.disabled = true;
      btn.textContent = '🔄 ' + t('updating', 'Updating...');
    }
    const prov = document.getElementById('duckdns-provider')?.value || 'duckdns';
    showToast(t('dyndns_syncing', `Starting Dynamic DNS synchronization (${prov === 'dynv6' ? 'dynv6.com' : 'DuckDNS'})...`));
    try {
      const res = await fetch('/api/duckdns/update', { method: 'POST' });
      const d = await res.json();
      if (res.ok && (d.success || d.status === 'ok')) {
        showToast(t('dyndns_synced_success', `✅ DynDNS updated! IP: ${d.ip || 'OK'} ${d.ipv6 ? 'IPv6: ' + d.ipv6 : ''}`));
      } else {
        showToast(t('dyndns_resp_msg', 'DynDNS response: ') + (d.status || d.message || 'Failed'));
      }
      setTimeout(loadDuckdnsStatus, 800);
    } catch (e) {
      showToast(t('dyndns_sync_err', 'DynDNS sync error: ') + e);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = oldText;
      }
    }
  }

  // ---- WireGuard ----
  let wireguardIsActive = false;

  async function loadWireguardStatus() {
    try {
      const res = await fetch('/api/wireguard/status');
      if (!res.ok) return;
      const d = await res.json();
      wireguardIsActive = !!(d.active || d.running);
      lastWireguardStatus = d;
      lastWireguardPeers = d.peers || [];
      renderVpnHub();

      const portInput = document.getElementById('wg-port');
      const subnetInput = document.getElementById('wg-subnet');
      const subnet6Input = document.getElementById('wg-subnet-ipv6');
      const dnsInput = document.getElementById('wg-dns');
      const endpointInput = document.getElementById('wg-endpoint');
      if (portInput && d.port && !portInput.dataset.focused) portInput.value = d.port;
      if (subnetInput && d.subnet && !subnetInput.dataset.focused) subnetInput.value = d.subnet;
      if (subnet6Input && d.subnet_ipv6 && !subnet6Input.dataset.focused) subnet6Input.value = d.subnet_ipv6;
      if (dnsInput && d.dns && !dnsInput.dataset.focused) dnsInput.value = d.dns;
      if (endpointInput && d.endpoint && !endpointInput.dataset.focused) endpointInput.value = d.endpoint;

      const badge = document.getElementById('wg-status-badge');
      if (badge) {
        if (d.active || d.running) {
          badge.className = 'badge';
          badge.style.background = 'rgba(16, 185, 129, 0.15)';
          badge.style.color = '#10b981';
          badge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
          badge.textContent = `🟢 Running (Port ${d.port || 51820})`;
        } else {
          badge.className = 'badge';
          badge.style.background = 'rgba(148, 163, 184, 0.15)';
          badge.style.color = '#94a3b8';
          badge.style.border = '1px solid #475569';
          badge.textContent = '⚫ Stopped';
        }
      }

      const toggleBtn = document.getElementById('btn-wg-toggle');
      if (toggleBtn) {
        if (d.active || d.running) {
          toggleBtn.className = 'btn-danger';
          toggleBtn.textContent = '⏹️ Stop WireGuard';
        } else {
          toggleBtn.className = 'btn-primary';
          toggleBtn.textContent = '▶️ Start WireGuard';
        }
      }

      renderWireguardPeers(d.peers || []);
    } catch (e) {
      console.error('loadWireguardStatus error:', e);
    }
  }

  function renderWireguardPeers(peers) {
    const tbody = document.getElementById('wg-peers-tbody');
    if (!tbody) return;

    if (!peers || peers.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 16px;">No WireGuard peers configured yet. Use the form above to add a client peer.</td></tr>';
      return;
    }

    let html = '';
    peers.forEach(p => {
      const hsSec = p.latest_handshake || 0;
      let hsDisplay = '--';
      let isConnected = false;
      if (hsSec > 0) {
        if (hsSec < 180) {
          isConnected = true;
          hsDisplay = `<span style="color: #10b981; font-weight: 600;">Active (${escapeHtml(p.latest_handshake_ago || hsSec + 's ago')})</span>`;
        } else {
          hsDisplay = `<span style="color: var(--text-muted);">${escapeHtml(p.latest_handshake_ago || Math.floor(hsSec / 60) + 'm ago')}</span>`;
        }
      }

      const statusBadge = isConnected
        ? '<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 2px 6px; border-radius: 4px; font-size: 11px;">🟢 Connected</span>'
        : '<span class="badge" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569; padding: 2px 6px; border-radius: 4px; font-size: 11px;">Offline</span>';

      const rxFormatted = formatBytes(p.transfer_rx || 0);
      const txFormatted = formatBytes(p.transfer_tx || 0);

      let ipDisplay = p.allowed_ips;
      if (!ipDisplay) {
        ipDisplay = p.client_ip || '--';
        if (p.client_ipv6) ipDisplay += '<br><span style="color: #94a3b8; font-size: 11px;">' + escapeHtml(p.client_ipv6) + '</span>';
      }

      html += `<tr>
        <td style="font-weight: 700; color: #38bdf8;">${escapeHtml(p.name)}</td>
        <td style="font-family: monospace; font-size: 12px; color: #cbd5e1;">${escapeHtml(ipDisplay)}</td>
        <td>${statusBadge}</td>
        <td style="font-size: 12px; color: var(--text-muted);">${escapeHtml(p.endpoint || '--')}</td>
        <td style="font-size: 12px;">↓ ${rxFormatted} / ↑ ${txFormatted}</td>
        <td style="font-size: 12px;">${hsDisplay}</td>
        <td style="display: flex; gap: 6px;">
          <a href="/api/wireguard/peer/config?id=${escapeHtml(p.id)}" download="${escapeHtml(p.name)}.conf" class="btn-secondary" style="font-size: 11px; padding: 3px 8px; text-decoration: none;">
            📥 .conf
          </a>
          <button type="button" class="btn-secondary" style="font-size: 11px; padding: 3px 8px;" onclick="showWireguardQr(${jsArg(p.id)}, ${jsArg(p.name)})">
            📱 QR
          </button>
          <button type="button" class="btn-danger" style="font-size: 11px; padding: 3px 8px;" onclick="deleteWireguardPeer(${jsArg(p.id)}, ${jsArg(p.name)})">
            ✕
          </button>
        </td>
      </tr>`;
    });
    tbody.innerHTML = html;
  }

  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  async function saveWireguardSettings() {
    const port = parseInt(document.getElementById('wg-port')?.value, 10) || 51820;
    const subnet = (document.getElementById('wg-subnet')?.value || '').trim() || '10.8.0.1/24';
    const subnet_ipv6 = (document.getElementById('wg-subnet-ipv6')?.value || '').trim() || 'fd42:42:42::1/64';
    const dns = (document.getElementById('wg-dns')?.value || '').trim();
    const endpoint = (document.getElementById('wg-endpoint')?.value || '').trim();

    try {
      const res = await fetch('/api/wireguard/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port, subnet, subnet_ipv6, dns, endpoint }),
      });
      const d = await res.json();
      if (res.ok) {
        showToast('WireGuard server settings saved');
        loadWireguardStatus();
      } else {
        showToast('WireGuard save error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('WireGuard save error: ' + e);
    }
  }

  async function toggleWireguardServer() {
    const nextState = !wireguardIsActive;
    showToast(nextState ? 'Starting WireGuard VPN server...' : 'Stopping WireGuard VPN server...');
    try {
      const res = await fetch('/api/wireguard/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable: nextState }),
      });
      const d = await res.json();
      if (res.ok) {
        showToast(`WireGuard server ${nextState ? 'started' : 'stopped'}`);
        setTimeout(loadWireguardStatus, 800);
      } else {
        showToast('WireGuard toggle error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('WireGuard toggle error: ' + e);
    }
  }

  async function addWireguardPeer() {
    const nameInput = document.getElementById('wg-new-peer-name');
    const ipInput = document.getElementById('wg-new-peer-ip');
    const ip6Input = document.getElementById('wg-new-peer-ipv6');
    const name = (nameInput?.value || '').trim();
    const client_ip = (ipInput?.value || '').trim();
    const client_ipv6 = (ip6Input?.value || '').trim();

    if (!name) {
      showToast('Please provide a client peer name (e.g. phone-pixel)');
      if (nameInput) nameInput.focus();
      return;
    }

    showToast('Generating Elliptic Curve keys & WireGuard peer configuration...');
    try {
      const res = await fetch('/api/wireguard/peer/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, client_ip, client_ipv6 }),
      });
      const d = await res.json();
      if (res.ok && d.peer) {
        showToast(`Peer "${name}" generated successfully!`);
        if (nameInput) nameInput.value = '';
        if (ipInput) ipInput.value = '';
        if (ip6Input) ip6Input.value = '';
        loadWireguardStatus();
        showWireguardQr(d.peer.id, d.peer.name);
      } else {
        showToast('Add peer error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('Add peer request error: ' + e);
    }
  }

  async function deleteWireguardPeer(id, name) {
    if (!confirm(`Are you sure you want to delete WireGuard client peer "${name}"?`)) return;
    try {
      const res = await fetch('/api/wireguard/peer/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      });
      if (res.ok) {
        showToast(`Peer "${name}" removed`);
        loadWireguardStatus();
      } else {
        const d = await res.json();
        showToast('Delete peer error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('Delete peer error: ' + e);
    }
  }

  let currentWgPeerId = '';
  let currentWgPeerName = '';
  let cachedWgEndpoints = [];

  function getSelectedWgEndpoint() {
    const select = document.getElementById('wg-qr-endpoint-select');
    if (!select) return '';
    if (select.value === 'custom') {
      const customInput = document.getElementById('wg-qr-custom-endpoint');
      return (customInput?.value || '').trim();
    }
    return select.value;
  }

  function updateWgQrTip() {
    const select = document.getElementById('wg-qr-endpoint-select');
    const tipDiv = document.getElementById('wg-qr-endpoint-tip');
    const customWrap = document.getElementById('wg-qr-custom-endpoint-wrap');
    if (!select || !tipDiv) return;

    const val = select.value;
    if (val === 'custom') {
      if (customWrap) customWrap.style.display = 'block';
      tipDiv.style.background = 'rgba(148, 163, 184, 0.1)';
      tipDiv.style.borderColor = 'rgba(148, 163, 184, 0.25)';
      tipDiv.style.color = '#cbd5e1';
      tipDiv.innerHTML = '✏️ ' + (t('wireguard_custom_endpoint_placeholder', 'Enter the desired host and port (e.g. 192.168.1.100:51820).'));
      return;
    }
    if (customWrap) customWrap.style.display = 'none';

    const selectedOpt = select.options[select.selectedIndex];
    const epType = selectedOpt ? selectedOpt.dataset.type : '';

    if (epType === 'lan') {
      tipDiv.style.background = 'rgba(16, 185, 129, 0.1)';
      tipDiv.style.borderColor = 'rgba(16, 185, 129, 0.25)';
      tipDiv.style.color = '#a7f3d0';
      tipDiv.innerHTML = t('wireguard_tip_lan', '💡 <strong>Recommended for devices on local Wi-Fi:</strong> Phone connects directly to the box on LAN (0ms NAT latency, no loopback issues).');
    } else if (epType === 'ipv6') {
      tipDiv.style.background = 'rgba(168, 85, 247, 0.1)';
      tipDiv.style.borderColor = 'rgba(168, 85, 247, 0.25)';
      tipDiv.style.color = '#e9d5ff';
      tipDiv.innerHTML = t('wireguard_tip_ipv6', '⚡ <strong>Direct IPv6 connection:</strong> Bypasses IPv4 NAT and router port forwarding if cellular carrier supports IPv6.');
    } else {
      // ddns or wan
      tipDiv.style.background = 'rgba(245, 158, 11, 0.12)';
      tipDiv.style.borderColor = 'rgba(245, 158, 11, 0.3)';
      tipDiv.style.color = '#fde68a';
      tipDiv.innerHTML = t('wireguard_tip_wan', '⚠️ <strong>For remote cellular access:</strong> Forward UDP port <strong>51820</strong> on your main router (e.g. 192.168.1.1) to this box. When connected to local Wi-Fi, select Local LAN.');
    }
  }

  function updateWgDownloadBtn() {
    const btn = document.getElementById('wg-qr-download-btn');
    if (!btn || !currentWgPeerId) return;
    const ep = getSelectedWgEndpoint();
    btn.href = `/api/wireguard/peer/config?id=${encodeURIComponent(currentWgPeerId)}&endpoint=${encodeURIComponent(ep)}`;
    btn.download = `${currentWgPeerName || 'wireguard'}.conf`;
  }

  async function onWireguardQrEndpointChange() {
    updateWgQrTip();
    updateWgDownloadBtn();
    await fetchAndRenderWgQr();
  }

  let customWgEpTimer = null;
  function onWireguardQrCustomEndpointInput() {
    clearTimeout(customWgEpTimer);
    customWgEpTimer = setTimeout(() => {
      updateWgDownloadBtn();
      fetchAndRenderWgQr();
    }, 400);
  }

  async function fetchAndRenderWgQr() {
    const img = document.getElementById('wg-qr-img');
    if (!img || !currentWgPeerId) return;

    const ep = getSelectedWgEndpoint();
    const epQuery = ep ? `&endpoint=${encodeURIComponent(ep)}` : '';
    try {
      const res = await fetch(`/api/wireguard/peer/qr?id=${encodeURIComponent(currentWgPeerId)}${epQuery}`);
      if (res.ok) {
        const d = await res.json();
        if (d.qr_data_uri) {
          img.src = d.qr_data_uri;
          return;
        }
      }
      img.src = `/api/wireguard/peer/qr?id=${encodeURIComponent(currentWgPeerId)}&raw=1${epQuery}&t=${Date.now()}`;
    } catch (e) {
      img.src = `/api/wireguard/peer/qr?id=${encodeURIComponent(currentWgPeerId)}&raw=1${epQuery}&t=${Date.now()}`;
    }
  }

  async function showWireguardQr(peerId, peerName) {
    currentWgPeerId = peerId;
    currentWgPeerName = peerName;

    const modal = document.getElementById('wg-qr-modal');
    const title = document.getElementById('wg-qr-peer-title');
    const select = document.getElementById('wg-qr-endpoint-select');
    const img = document.getElementById('wg-qr-img');
    if (!modal || !img) return;

    if (title) title.textContent = `📱 WireGuard QR: ${peerName}`;
    img.src = '';
    modal.style.display = 'flex';

    if (select) {
      try {
        const epRes = await fetch('/api/wireguard/endpoints');
        if (epRes.ok) {
          const epData = await epRes.json();
          if (epData.endpoints && epData.endpoints.length > 0) {
            cachedWgEndpoints = epData.endpoints;
          }
        }
      } catch (err) {
        console.warn('Failed to fetch wireguard endpoints:', err);
      }

      let html = '';
      cachedWgEndpoints.forEach(ep => {
        const isSelected = ep.is_default ? 'selected' : '';
        html += `<option value="${escapeHtml(ep.endpoint)}" data-type="${escapeHtml(ep.type)}" ${isSelected}>${escapeHtml(ep.label)}</option>`;
      });
      html += `<option value="custom" data-type="custom">` + escapeHtml(t('wireguard_custom_option', '✏️ Specify custom address (Custom host:port)...')) + `</option>`;
      select.innerHTML = html;
    }

    updateWgQrTip();
    updateWgDownloadBtn();
    await fetchAndRenderWgQr();
  }

  // ---- OpenVPN ----
  let openvpnIsActive = false;

  async function loadOpenvpnStatus() {
    try {
      const res = await fetch('/api/openvpn/status');
      if (!res.ok) return;
      const d = await res.json();
      openvpnIsActive = !!(d.active || d.running);
      lastOpenvpnStatus = d;
      lastOpenvpnClients = d.clients || [];
      renderVpnHub();

      const protoSelect = document.getElementById('ovpn-proto');
      const portInput = document.getElementById('ovpn-port');
      const subnetInput = document.getElementById('ovpn-subnet');
      const subnet6Input = document.getElementById('ovpn-subnet-ipv6');
      const dnsInput = document.getElementById('ovpn-dns');
      const endpointInput = document.getElementById('ovpn-endpoint');
      if (protoSelect && d.proto) protoSelect.value = d.proto;
      if (portInput && d.port && !portInput.dataset.focused) portInput.value = d.port;
      if (subnetInput && d.subnet && !subnetInput.dataset.focused) subnetInput.value = d.subnet;
      if (subnet6Input && d.subnet_ipv6 && !subnet6Input.dataset.focused) subnet6Input.value = d.subnet_ipv6;
      if (dnsInput && d.dns && !dnsInput.dataset.focused) dnsInput.value = d.dns;
      if (endpointInput && d.endpoint && !endpointInput.dataset.focused) endpointInput.value = d.endpoint;

      const badge = document.getElementById('ovpn-status-badge');
      if (badge) {
        if (d.active || d.running) {
          badge.className = 'badge';
          badge.style.background = 'rgba(16, 185, 129, 0.15)';
          badge.style.color = '#10b981';
          badge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
          badge.textContent = `🟢 Running (${(d.proto || 'udp').toUpperCase()} ${d.port || 1194})`;
        } else {
          badge.className = 'badge';
          badge.style.background = 'rgba(148, 163, 184, 0.15)';
          badge.style.color = '#94a3b8';
          badge.style.border = '1px solid #475569';
          badge.textContent = '⚫ Stopped';
        }
      }

      const toggleBtn = document.getElementById('btn-ovpn-toggle');
      if (toggleBtn) {
        if (d.active || d.running) {
          toggleBtn.className = 'btn-danger';
          toggleBtn.textContent = '⏹️ Stop OpenVPN';
        } else {
          toggleBtn.className = 'btn-primary';
          toggleBtn.textContent = '▶️ Start OpenVPN';
        }
      }

      renderOpenvpnClients(d.clients || []);
    } catch (e) {
      console.error('loadOpenvpnStatus error:', e);
    }
  }

  function renderOpenvpnClients(clients) {
    const tbody = document.getElementById('ovpn-clients-tbody');
    if (!tbody) return;

    if (!clients || clients.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 16px;">No OpenVPN client certificates generated yet. Use the form above to add a client.</td></tr>';
      return;
    }

    let html = '';
    clients.forEach(c => {
      const isConnected = !!c.connected;
      const statusBadge = isConnected
        ? '<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 2px 6px; border-radius: 4px; font-size: 11px;">🟢 Connected</span>'
        : '<span class="badge" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569; padding: 2px 6px; border-radius: 4px; font-size: 11px;">Offline</span>';

      const rxFormatted = formatBytes(c.bytes_received || 0);
      const txFormatted = formatBytes(c.bytes_sent || 0);

      html += `<tr>
        <td style="font-weight: 700; color: #38bdf8;">${escapeHtml(c.name)}</td>
        <td>${statusBadge}</td>
        <td style="font-size: 12px; color: var(--text-muted);">${escapeHtml(c.real_address || '--')}</td>
        <td style="font-size: 12px;">↓ ${rxFormatted} / ↑ ${txFormatted}</td>
        <td style="font-size: 12px; color: var(--text-muted);">${escapeHtml(c.connected_since || '--')}</td>
        <td style="display: flex; gap: 6px;">
          <a href="/api/openvpn/client/config?name=${encodeURIComponent(c.name)}" download="${escapeHtml(c.name)}.ovpn" class="btn-secondary" style="font-size: 11px; padding: 3px 8px; text-decoration: none;">
            📥 .ovpn
          </a>
          <button type="button" class="btn-danger" style="font-size: 11px; padding: 3px 8px;" onclick="deleteOpenvpnClient(${jsArg(c.name)})">
            ✕
          </button>
        </td>
      </tr>`;
    });
    tbody.innerHTML = html;
  }

  async function saveOpenvpnSettings() {
    const proto = document.getElementById('ovpn-proto')?.value || 'udp';
    const port = parseInt(document.getElementById('ovpn-port')?.value, 10) || 1194;
    const subnet = (document.getElementById('ovpn-subnet')?.value || '').trim() || '10.9.0.0';
    const subnet_ipv6 = (document.getElementById('ovpn-subnet-ipv6')?.value || '').trim() || 'fd42:42:43::/64';
    const dns = (document.getElementById('ovpn-dns')?.value || '').trim();
    const endpoint = (document.getElementById('ovpn-endpoint')?.value || '').trim();

    try {
      const res = await fetch('/api/openvpn/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proto, port, subnet, subnet_ipv6, dns, endpoint }),
      });
      const d = await res.json();
      if (res.ok) {
        showToast('OpenVPN server settings saved');
        loadOpenvpnStatus();
      } else {
        showToast('OpenVPN save error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('OpenVPN save error: ' + e);
    }
  }

  async function toggleOpenvpnServer() {
    const nextState = !openvpnIsActive;
    showToast(nextState ? 'Starting OpenVPN server...' : 'Stopping OpenVPN server...');
    try {
      const res = await fetch('/api/openvpn/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable: nextState }),
      });
      const d = await res.json();
      if (res.ok) {
        showToast(`OpenVPN server ${nextState ? 'started' : 'stopped'}`);
        setTimeout(loadOpenvpnStatus, 800);
      } else {
        showToast('OpenVPN toggle error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('OpenVPN toggle error: ' + e);
    }
  }

  async function addOpenvpnClient() {
    const nameInput = document.getElementById('ovpn-new-client-name');
    const name = (nameInput?.value || '').trim();

    if (!name) {
      showToast('Please provide a client name (e.g. tablet-client)');
      if (nameInput) nameInput.focus();
      return;
    }

    showToast('Generating Elliptic Curve client certificate & unified .ovpn profile...');
    try {
      const res = await fetch('/api/openvpn/client/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const d = await res.json();
      if (res.ok) {
        showToast(`Client "${name}" generated successfully!`);
        if (nameInput) nameInput.value = '';
        loadOpenvpnStatus();
        const a = document.createElement('a');
        a.href = `/api/openvpn/client/config?name=${encodeURIComponent(name)}`;
        a.download = `${name}.ovpn`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      } else {
        showToast('Add client error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('Add client request error: ' + e);
    }
  }

  async function deleteOpenvpnClient(name) {
    if (!confirm(`Are you sure you want to revoke & delete OpenVPN client "${name}"?`)) return;
    try {
      const res = await fetch('/api/openvpn/client/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (res.ok) {
        showToast(`Client "${name}" deleted`);
        loadOpenvpnStatus();
      } else {
        const d = await res.json();
        showToast('Delete client error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('Delete client error: ' + e);
    }
  }

  // ---- HTTPS CONNECT Proxy ----
  let proxyIsActive = false;

  function toggleProxyAuthFields() {
    const chk = document.getElementById('proxy-auth-enable');
    const fields = document.getElementById('proxy-auth-fields');
    if (fields) {
      fields.style.display = (chk && chk.checked) ? 'grid' : 'none';
    }
  }

  async function loadProxyStatus() {
    try {
      const res = await fetch('/api/proxy/status');
      if (!res.ok) return;
      const d = await res.json();
      proxyIsActive = !!(d.running || d.active);

      const portInput = document.getElementById('proxy-port');
      const dnsInput = document.getElementById('proxy-dns');
      const ipv6Chk = document.getElementById('proxy-ipv6-enable');
      const authChk = document.getElementById('proxy-auth-enable');
      const userInput = document.getElementById('proxy-username');
      const passInput = document.getElementById('proxy-password');
      const tlsChk = document.getElementById('proxy-tls-enable');

      if (portInput && d.port && !portInput.dataset.focused) portInput.value = d.port;
      if (dnsInput && d.dns && !dnsInput.dataset.focused) dnsInput.value = d.dns;
      if (ipv6Chk && d.listen_ipv6 !== undefined) ipv6Chk.checked = !!d.listen_ipv6;
      if (authChk && d.auth_enabled !== undefined) {
        authChk.checked = !!d.auth_enabled;
        toggleProxyAuthFields();
      }
      if (userInput && d.username && !userInput.dataset.focused) userInput.value = d.username;
      if (tlsChk && d.tls_enabled !== undefined) tlsChk.checked = !!d.tls_enabled;

      const badge = document.getElementById('proxy-status-badge');
      if (badge) {
        if (d.running || d.active) {
          badge.className = 'badge';
          badge.style.background = 'rgba(16, 185, 129, 0.15)';
          badge.style.color = '#10b981';
          badge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
          badge.textContent = `🟢 Running (Port ${d.port || 8443})`;
        } else {
          badge.className = 'badge';
          badge.style.background = 'rgba(148, 163, 184, 0.15)';
          badge.style.color = '#94a3b8';
          badge.style.border = '1px solid #475569';
          badge.textContent = '⚫ Stopped';
        }
      }

      const toggleBtn = document.getElementById('btn-proxy-toggle');
      if (toggleBtn) {
        if (d.running || d.active) {
          toggleBtn.className = 'btn-danger';
          toggleBtn.textContent = '⏹️ Stop Proxy';
        } else {
          toggleBtn.className = 'btn-primary';
          toggleBtn.textContent = '▶️ Start Proxy';
        }
      }

      const stats = d.stats || {};
      const actEl = document.getElementById('proxy-stat-active');
      const totEl = document.getElementById('proxy-stat-total');
      const trfEl = document.getElementById('proxy-stat-traffic');
      const uptEl = document.getElementById('proxy-stat-uptime');

      const activeConns = stats.active_connections !== undefined ? stats.active_connections : (d.active_connections || 0);
      const totalConns = stats.total_connections !== undefined ? stats.total_connections : (d.total_connections || 0);
      const bytesRx = stats.bytes_rx !== undefined ? stats.bytes_rx : (d.bytes_rx || 0);
      const bytesTx = stats.bytes_tx !== undefined ? stats.bytes_tx : (d.bytes_tx || 0);
      const uptimeSec = stats.uptime_sec !== undefined ? stats.uptime_sec : (d.uptime_seconds || 0);

      if (actEl) actEl.textContent = activeConns;
      if (totEl) totEl.textContent = totalConns;
      if (trfEl) {
        const rx = formatBytes(bytesRx);
        const tx = formatBytes(bytesTx);
        trfEl.textContent = `↓ ${rx} / ↑ ${tx}`;
      }
      if (uptEl) {
        if (uptimeSec > 0) {
          const m = Math.floor(uptimeSec / 60);
          const s = uptimeSec % 60;
          uptEl.textContent = `${m}m ${s}s`;
        } else {
          uptEl.textContent = (d.running || d.active) ? 'Just started' : 'Offline';
        }
      }
    } catch (e) {
      console.error('loadProxyStatus error:', e);
    }
  }

  async function saveProxySettings() {
    const port = parseInt(document.getElementById('proxy-port')?.value, 10) || 8443;
    const dns = (document.getElementById('proxy-dns')?.value || '').trim();
    const listen_ipv6 = !!document.getElementById('proxy-ipv6-enable')?.checked;
    const auth_enabled = !!document.getElementById('proxy-auth-enable')?.checked;
    const username = (document.getElementById('proxy-username')?.value || '').trim();
    const password = (document.getElementById('proxy-password')?.value || '').trim();
    const tls_enabled = !!document.getElementById('proxy-tls-enable')?.checked;

    try {
      const res = await fetch('/api/proxy/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port, dns, listen_ipv6, auth_enabled, username, password, tls_enabled }),
      });
      const d = await res.json();
      if (res.ok) {
        showToast('HTTPS Proxy settings saved');
        loadProxyStatus();
      } else {
        showToast('Proxy save error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('Proxy save error: ' + e);
    }
  }

  async function toggleProxyServer() {
    const nextState = !proxyIsActive;
    const endpoint = nextState ? '/api/proxy/start' : '/api/proxy/stop';
    showToast(nextState ? 'Starting HTTPS CONNECT proxy server...' : 'Stopping HTTPS proxy server...');
    try {
      const res = await fetch(endpoint, { method: 'POST' });
      const d = await res.json();
      if (res.ok) {
        showToast(`HTTPS Proxy ${nextState ? 'started' : 'stopped'}`);
        setTimeout(loadProxyStatus, 800);
      } else {
        showToast('Proxy toggle error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('Proxy toggle error: ' + e);
    }
  }

  // ==========================================
  // Tailscale Mesh Network Integration
  // ==========================================
  let lastTailscaleStatus = null;

  async function loadTailscaleStatus() {
    try {
      const res = await fetch('/api/tailscale/status');
      if (!res.ok) return;
      const d = await res.json();
      lastTailscaleStatus = d;

      // Badges
      const pBadge = document.getElementById('pivpn-ts-badge');
      const tBadge = document.getElementById('tailscale-status-badge');
      const pToggle = document.getElementById('pivpn-btn-ts-toggle');
      const pIp = document.getElementById('pivpn-ts-ip');
      const pDns = document.getElementById('pivpn-ts-dns');

      let stateText = d.backend_state || 'Stopped';
      let badgeBg = 'rgba(100, 116, 139, 0.2)';
      let badgeColor = '#94a3b8';
      let isRunning = false;

      if (!d.installed) {
        stateText = 'Not Installed';
        badgeBg = 'rgba(239, 68, 68, 0.2)';
        badgeColor = '#ef4444';
      } else if (d.backend_state === 'Running') {
        stateText = 'Connected';
        badgeBg = 'rgba(16, 185, 129, 0.2)';
        badgeColor = '#10b981';
        isRunning = true;
      } else if (d.backend_state === 'NeedsLogin') {
        stateText = 'Needs Login';
        badgeBg = 'rgba(245, 158, 11, 0.2)';
        badgeColor = '#f59e0b';
      } else if (d.backend_state === 'Starting') {
        stateText = 'Starting...';
        badgeBg = 'rgba(56, 189, 248, 0.2)';
        badgeColor = '#38bdf8';
      }

      [pBadge, tBadge].forEach(b => {
        if (!b) return;
        b.textContent = stateText;
        b.style.background = badgeBg;
        b.style.color = badgeColor;
        b.style.border = `1px solid ${badgeColor}40`;
      });

      if (pToggle) {
        pToggle.textContent = isRunning ? 'Disconnect' : 'Connect';
      }

      // IPs and DNS
      const ips = d.tailscale_ips || [];
      const ipv4 = ips.find(ip => ip.includes('.')) || '--';
      const ipv6 = ips.find(ip => ip.includes(':')) || '--';
      const dnsName = d.dns_name ? d.dns_name.replace(/\.$/, '') : '--';

      if (pIp) pIp.textContent = ipv4;
      if (pDns) pDns.textContent = dnsName !== '--' ? dnsName : '--';

      const elIp = document.getElementById('tailscale-ip-val');
      if (elIp) elIp.textContent = ipv4;
      const elIpv6 = document.getElementById('tailscale-ipv6-val');
      if (elIpv6) elIpv6.textContent = ipv6;
      const elDns = document.getElementById('tailscale-dns-val');
      if (elDns) elDns.textContent = dnsName;
      const elHost = document.getElementById('tailscale-hostname-val');
      if (elHost) elHost.textContent = (d.self && d.self.HostName) ? d.self.HostName : 'networkmeasurebox';

      // Direct Links Banner
      const directBox = document.getElementById('tailscale-direct-links');
      const linkIp = document.getElementById('tailscale-link-ip');
      const linkIpText = document.getElementById('tailscale-link-ip-text');
      const linkMagic = document.getElementById('tailscale-link-magic');

      if (isRunning && ipv4 !== '--') {
        const curPort = (window.location.port && window.location.port !== '80' && window.location.port !== '443') ? (':' + window.location.port) : '';
        const proto = window.location.protocol || 'http:';
        if (directBox) directBox.style.display = 'block';
        if (linkIp) linkIp.href = proto + '//' + ipv4 + curPort + '/';
        if (linkIpText) linkIpText.textContent = ipv4 + curPort;
        if (linkMagic && dnsName !== '--') {
          linkMagic.style.display = 'inline-block';
          linkMagic.href = proto + '//' + dnsName + curPort + '/';
        } else if (linkMagic) {
          linkMagic.style.display = 'none';
        }
      } else {
        if (directBox) directBox.style.display = 'none';
      }

      // Login URL Banner
      const loginBanner = document.getElementById('tailscale-login-banner');
      const authBtn = document.getElementById('tailscale-auth-url-btn');
      if (d.auth_url) {
        if (loginBanner) loginBanner.style.display = 'flex';
        if (authBtn) authBtn.href = d.auth_url;
      } else {
        if (loginBanner) loginBanner.style.display = 'none';
      }

      // Checkboxes from config
      if (d.config) {
        const cSsh = document.getElementById('tailscale-cfg-ssh');
        if (cSsh && !cSsh.dataset.focused) cSsh.checked = d.config.ssh !== false;
        const cRoutes = document.getElementById('tailscale-cfg-accept-routes');
        if (cRoutes && !cRoutes.dataset.focused) cRoutes.checked = !!d.config.accept_routes;
        const cDns = document.getElementById('tailscale-cfg-accept-dns');
        if (cDns && !cDns.dataset.focused) cDns.checked = !!d.config.accept_dns;
        const cExit = document.getElementById('tailscale-cfg-exit-node');
        if (cExit && !cExit.dataset.focused) cExit.checked = !!d.config.exit_node;
      }

      // Peers table
      const tbody = document.getElementById('tailscale-peers-tbody');
      const countEl = document.getElementById('tailscale-peer-count');
      if (tbody) {
        const peers = d.peers || [];
        if (countEl) countEl.textContent = peers.length + ' ' + t('tailscale_devices', 'devices');
        if (peers.length === 0) {
          tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 18px;">${isRunning ? t('tailscale_no_peers', 'No other active peers on the network.') : t('tailscale_disconnected', 'Tailscale is not connected.')}</td></tr>`;
        } else {
          tbody.innerHTML = peers.map(p => {
            const pIp = (p.TailscaleIPs && p.TailscaleIPs.length > 0) ? p.TailscaleIPs[0] : '--';
            const isOnline = p.Online;
            const statusBadge = isOnline ? 
              '<span class="badge" style="background:rgba(16,185,129,0.15); color:#10b981; border:1px solid rgba(16,185,129,0.3);">Online</span>' : 
              '<span class="badge" style="background:rgba(100,116,139,0.15); color:#94a3b8; border:1px solid rgba(100,116,139,0.3);">Offline</span>';
            const name = p.HostName || p.DNSName || '--';
            const os = p.OS || '--';
            return `<tr>
              <td style="font-weight:600; color:#e2e8f0;">${escapeHtml(name)}</td>
              <td><code style="color:#38bdf8;">${escapeHtml(pIp)}</code></td>
              <td>${escapeHtml(os)}</td>
              <td>${statusBadge}</td>
            </tr>`;
          }).join('');
        }
      }
    } catch (e) {
      console.error('Tailscale status fetch error:', e);
    }
  }

  async function connectTailscale() {
    try {
      const authKey = document.getElementById('tailscale-auth-key-input')?.value?.trim() || '';
      const ssh = document.getElementById('tailscale-cfg-ssh')?.checked ?? true;
      const acceptRoutes = document.getElementById('tailscale-cfg-accept-routes')?.checked ?? false;
      const acceptDns = document.getElementById('tailscale-cfg-accept-dns')?.checked ?? false;
      const exitNode = document.getElementById('tailscale-cfg-exit-node')?.checked ?? false;

      showToast('Connecting to Tailscale...');
      const res = await fetch('/api/tailscale/up', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          auth_key: authKey,
          ssh: ssh,
          accept_routes: acceptRoutes,
          accept_dns: acceptDns,
          exit_node: exitNode
        })
      });
      const data = await res.json();
      if (data.ok) {
        showToast('Tailscale command executed successfully!');
        if (data.auth_url) {
          window.open(data.auth_url, '_blank');
        }
      } else {
        showToast('Tailscale: ' + (data.error || 'Failed to start'));
      }
      setTimeout(loadTailscaleStatus, 1500);
    } catch (e) {
      showToast('Tailscale error: ' + e);
    }
  }

  async function disconnectTailscale() {
    try {
      showToast('Disconnecting Tailscale...');
      const res = await fetch('/api/tailscale/down', { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        showToast('Tailscale disconnected.');
      } else {
        showToast('Tailscale: ' + (data.error || 'Failed'));
      }
      setTimeout(loadTailscaleStatus, 1000);
    } catch (e) {
      showToast('Tailscale error: ' + e);
    }
  }

  async function logoutTailscale() {
    if (!confirm(t('tailscale_logout_confirm', 'Log out of the Tailscale account on this device?'))) return;
    try {
      showToast('Logging out from Tailscale...');
      const res = await fetch('/api/tailscale/logout', { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        showToast('Tailscale logged out.');
      } else {
        showToast('Tailscale: ' + (data.error || 'Failed'));
      }
      setTimeout(loadTailscaleStatus, 1000);
    } catch (e) {
      showToast('Tailscale error: ' + e);
    }
  }

  async function toggleTailscaleConnection() {
    if (lastTailscaleStatus && lastTailscaleStatus.backend_state === 'Running') {
      await disconnectTailscale();
    } else {
      await connectTailscale();
    }
  }

  async function saveTailscaleConfig() {
    try {
      const authKey = document.getElementById('tailscale-auth-key-input')?.value?.trim() || '';
      const ssh = document.getElementById('tailscale-cfg-ssh')?.checked ?? true;
      const acceptRoutes = document.getElementById('tailscale-cfg-accept-routes')?.checked ?? false;
      const acceptDns = document.getElementById('tailscale-cfg-accept-dns')?.checked ?? false;
      const exitNode = document.getElementById('tailscale-cfg-exit-node')?.checked ?? false;

      const res = await fetch('/api/tailscale/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          auth_key: authKey,
          ssh: ssh,
          accept_routes: acceptRoutes,
          accept_dns: acceptDns,
          exit_node: exitNode
        })
      });
      const data = await res.json();
      if (data.ok) {
        showToast(t('tailscale_saved_ok', 'Tailscale settings saved successfully!'));
      } else {
        showToast(t('save_err', 'Error saving settings: ') + (data.error || 'Failed'));
      }
    } catch (e) {
      showToast(t('net_err', 'Network error: ') + e);
    }
  }

  // ==========================================
  // Telegram Bot & Alerts Integration
  // ==========================================
  let lastTelegramStatus = null;
  let telegramFormLoaded = false;

  function clearTelegramDirty() {
    ['telegram-cfg-enabled', 'telegram-cfg-token', 'telegram-cfg-chats', 'telegram-cfg-alert-loss', 'telegram-cfg-loss-thresh', 'telegram-cfg-alert-latency', 'telegram-cfg-lat-thresh'].forEach(id => {
      const el = document.getElementById(id);
      if (el) delete el.dataset.dirty;
    });
  }

  async function loadTelegramStatus(forceFormReload = false) {
    try {
      const res = await fetch('/api/telegram/status');
      if (!res.ok) return;
      const d = await res.json();
      lastTelegramStatus = d;

      // Populate form fields ONLY on initial load or explicit user-triggered refresh.
      // Background interval polls must NEVER overwrite form fields while the user is typing or viewing!
      if (!telegramFormLoaded || forceFormReload) {
        const elEnabled = document.getElementById('telegram-cfg-enabled');
        if (elEnabled && (forceFormReload || !elEnabled.dataset.dirty)) {
          elEnabled.checked = !!d.enabled;
        }

        const elToken = document.getElementById('telegram-cfg-token');
        if (elToken && (forceFormReload || (!elToken.dataset.dirty && document.activeElement !== elToken))) {
          // If server has a token, populate it; if empty, do not overwrite user input
          if (forceFormReload || !elToken.value) {
            elToken.value = d.bot_token || d.token || '';
          }
        }

        const elChats = document.getElementById('telegram-cfg-chats');
        if (elChats && (forceFormReload || (!elChats.dataset.dirty && document.activeElement !== elChats))) {
          if (forceFormReload || !elChats.value) {
            elChats.value = (d.chat_ids || d.allowed_chat_ids || []).join(', ');
          }
        }

        const elLoss = document.getElementById('telegram-cfg-alert-loss');
        if (elLoss && (forceFormReload || !elLoss.dataset.dirty)) {
          elLoss.checked = d.alert_on_loss !== false;
        }

        const elLossThresh = document.getElementById('telegram-cfg-loss-thresh');
        if (elLossThresh && (forceFormReload || (!elLossThresh.dataset.dirty && document.activeElement !== elLossThresh))) {
          const val = d.loss_threshold_pct !== undefined ? d.loss_threshold_pct : (d.alert_loss_threshold_pct ?? 5.0);
          elLossThresh.value = val;
        }

        const elLat = document.getElementById('telegram-cfg-alert-latency');
        if (elLat && (forceFormReload || !elLat.dataset.dirty)) {
          elLat.checked = d.alert_on_latency !== false;
        }

        const elLatThresh = document.getElementById('telegram-cfg-lat-thresh');
        if (elLatThresh && (forceFormReload || (!elLatThresh.dataset.dirty && document.activeElement !== elLatThresh))) {
          const val = d.latency_threshold_ms !== undefined ? d.latency_threshold_ms : (d.alert_latency_threshold_ms ?? 100.0);
          elLatThresh.value = val;
        }

        if (forceFormReload) {
          clearTelegramDirty();
        }
        telegramFormLoaded = true;
      }

      // Update saved token badge indicator
      const tokBadge = document.getElementById('telegram-token-saved-badge');
      if (tokBadge) {
        tokBadge.style.display = (d.token_set || d.bot_token || d.token) ? 'inline-flex' : 'none';
      }
      const tokInput = document.getElementById('telegram-cfg-token');
      if (tokInput && d.token_set && !tokInput.value) {
        tokInput.placeholder = t('telegram_token_saved_ph', '•••••••••••• (Saved - type to replace)');
      }

      // Badges
      const mainBadge = document.getElementById('telegram-main-badge');
      const rsubBadge = document.getElementById('rsub-telegram-badge');
      const svcBadge = document.getElementById('telegram-stat-service');

      let stateText = 'Inactive';
      let badgeBg = 'rgba(100, 116, 139, 0.2)';
      let badgeColor = '#94a3b8';

      if (d.service_active) {
        stateText = 'Running & Active';
        badgeBg = 'rgba(16, 185, 129, 0.2)';
        badgeColor = '#10b981';
      } else if (d.enabled) {
        stateText = 'Stopped / Offline';
        badgeBg = 'rgba(245, 158, 11, 0.2)';
        badgeColor = '#f59e0b';
      } else {
        stateText = 'Disabled';
        badgeBg = 'rgba(100, 116, 139, 0.2)';
        badgeColor = '#94a3b8';
      }

      [mainBadge, rsubBadge].forEach(b => {
        if (!b) return;
        b.textContent = stateText;
        b.style.background = badgeBg;
        b.style.color = badgeColor;
        b.style.border = `1px solid ${badgeColor}40`;
      });

      if (svcBadge) {
        svcBadge.textContent = d.service_active ? 'Active (Running)' : 'Inactive (Dead)';
        svcBadge.style.background = d.service_active ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)';
        svcBadge.style.color = d.service_active ? '#10b981' : '#f87171';
      }

      // Bot details
      const userEl = document.getElementById('telegram-stat-username');
      const nameEl = document.getElementById('telegram-stat-first-name');
      const apiEl = document.getElementById('telegram-stat-api');
      const rsubBotName = document.getElementById('rsub-telegram-botname');

      if (userEl) userEl.textContent = d.bot_username ? '@' + d.bot_username : '--';
      if (rsubBotName) rsubBotName.textContent = d.bot_username ? '@' + d.bot_username : (d.enabled ? t('telegram_not_logged_in', 'Not signed in') : t('status_disabled', 'Disabled'));
      if (nameEl) nameEl.textContent = d.bot_first_name || '--';
      if (apiEl) {
        if (d.can_connect) {
          apiEl.textContent = '✅ Connected (Token Valid)';
          apiEl.style.color = '#10b981';
        } else if (d.bot_token || d.token || d.token_set) {
          apiEl.textContent = '❌ Invalid Token / No Connection';
          apiEl.style.color = '#ef4444';
        } else {
          apiEl.textContent = '⚪ Token nincs megadva';
          apiEl.style.color = '#94a3b8';
        }
      }
    } catch (e) {
      console.error('Telegram status fetch error:', e);
    }
  }

  function toggleTelegramTokenVisibility() {
    const el = document.getElementById('telegram-cfg-token');
    if (el) {
      el.type = (el.type === 'password') ? 'text' : 'password';
      el.focus();
    }
  }

  async function saveTelegramConfig() {
    try {
      const enabled = document.getElementById('telegram-cfg-enabled')?.checked ?? false;
      const botToken = document.getElementById('telegram-cfg-token')?.value?.trim() || '';
      const chatsRaw = document.getElementById('telegram-cfg-chats')?.value?.trim() || '';
      const chatIds = chatsRaw ? chatsRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
      const alertOnLoss = document.getElementById('telegram-cfg-alert-loss')?.checked ?? true;
      const lossThreshold = parseFloat(document.getElementById('telegram-cfg-loss-thresh')?.value) || 5.0;
      const alertOnLatency = document.getElementById('telegram-cfg-alert-latency')?.checked ?? true;
      const latencyThreshold = parseFloat(document.getElementById('telegram-cfg-lat-thresh')?.value) || 100.0;

      showToast(t('telegram_saving', 'Saving Telegram settings...'));
      const res = await fetch('/api/telegram/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: enabled,
          bot_token: botToken,
          token: botToken,
          chat_ids: chatIds,
          allowed_chat_ids: chatIds,
          alert_on_loss: alertOnLoss,
          loss_threshold_pct: lossThreshold,
          alert_loss_threshold_pct: lossThreshold,
          alert_on_latency: alertOnLatency,
          latency_threshold_ms: latencyThreshold,
          alert_latency_threshold_ms: latencyThreshold
        })
      });
      const data = await res.json();
      if (data.ok || data.status === 'ok') {
        showToast(t('telegram_saved_ok', 'Telegram settings saved successfully!'));
        clearTelegramDirty();
        setTimeout(() => loadTelegramStatus(true), 1000);
      } else {
        showToast(t('save_err', 'Error: ') + (data.error || data.message || 'Failed to save'));
      }
    } catch (e) {
      showToast(t('net_err', 'Network error: ') + e);
    }
  }

  async function sendTelegramTestNotification() {
    const resBox = document.getElementById('telegram-test-result');
    try {
      const chatId = document.getElementById('telegram-test-chat-id')?.value?.trim() || '';
      if (resBox) {
        resBox.style.display = 'block';
        resBox.style.background = 'rgba(56, 189, 248, 0.15)';
        resBox.style.color = '#38bdf8';
        resBox.textContent = t('telegram_test_sending', 'Sending test notification to Telegram...');
      }

      const res = await fetch('/api/telegram/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: chatId })
      });
      const data = await res.json();
      if (data.ok || data.status === 'ok') {
        if (resBox) {
          resBox.style.background = 'rgba(16, 185, 129, 0.15)';
          resBox.style.color = '#10b981';
          resBox.textContent = t('telegram_test_success', '✅ Test notification sent successfully to Telegram!');
        }
        showToast(t('telegram_test_toast_success', 'Test message sent!'));
      } else {
        if (resBox) {
          resBox.style.background = 'rgba(239, 68, 68, 0.15)';
          resBox.style.color = '#f87171';
          resBox.textContent = t('telegram_test_fail', '❌ Sending failed: ') + (data.error || data.message || 'Unknown error');
        }
        showToast(t('telegram_test_toast_fail', 'Test message failed!'));
      }
    } catch (e) {
      if (resBox) {
        resBox.style.background = 'rgba(239, 68, 68, 0.15)';
        resBox.style.color = '#f87171';
        resBox.textContent = t('telegram_test_network_err', '❌ Network error: ') + e;
      }
      showToast(t('net_err', 'Network error: ') + e);
    }
  }

  async function controlTelegramService(action) {
    try {
      showToast(t('telegram_service_action', `Telegram daemon: ${action}...`));
      const res = await fetch('/api/telegram/service', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: action })
      });
      const data = await res.json();
      if (data.ok || data.status === 'ok') {
        showToast(t('telegram_daemon_action_ok', `Telegram daemon successfully updated: ${action}`));
      } else {
        showToast(t('common_err', 'Error: ') + (data.error || data.message || 'Failed'));
      }
      setTimeout(loadTelegramStatus, 1500);
    } catch (e) {
      showToast(t('error_prefix', 'Error: ') + e);
    }
  }

  // Initialization
  ['duckdns-domain', 'duckdns-token', 'duckdns-interval', 'duckdns-custom-ip', 'wg-port', 'wg-subnet', 'wg-subnet-ipv6', 'wg-dns', 'wg-endpoint', 'ovpn-port', 'ovpn-subnet', 'ovpn-subnet-ipv6', 'ovpn-dns', 'ovpn-endpoint', 'proxy-port', 'proxy-dns', 'proxy-username', 'proxy-password', 'tailscale-auth-key-input', 'telegram-cfg-token', 'telegram-cfg-chats', 'telegram-cfg-loss-thresh', 'telegram-cfg-lat-thresh'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('focus', () => el.dataset.focused = '1');
      el.addEventListener('blur', () => delete el.dataset.focused);
    }
  });

  // Track user edits on Telegram form to prevent background polling wipeouts
  ['telegram-cfg-token', 'telegram-cfg-chats', 'telegram-cfg-loss-thresh', 'telegram-cfg-lat-thresh'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('input', () => el.dataset.dirty = '1');
      el.addEventListener('change', () => el.dataset.dirty = '1');
      el.addEventListener('paste', () => el.dataset.dirty = '1');
    }
  });
  ['telegram-cfg-enabled', 'telegram-cfg-alert-loss', 'telegram-cfg-alert-latency'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', () => el.dataset.dirty = '1');
    }
  });

  setInterval(() => {
    const remoteTab = document.getElementById('tab-remote');
    if (remoteTab && remoteTab.classList.contains('active')) {
      if (activeRemoteSubtab === 'vpnhub') {
        if (wireguardIsActive) loadWireguardStatus();
        if (openvpnIsActive) loadOpenvpnStatus();
        loadTailscaleStatus();
      } else if (activeRemoteSubtab === 'tailscale') {
        loadTailscaleStatus();
      } else if (activeRemoteSubtab === 'proxy' && proxyIsActive) {
        loadProxyStatus();
      } else if (activeRemoteSubtab === 'wireguard' && wireguardIsActive) {
        loadWireguardStatus();
      } else if (activeRemoteSubtab === 'openvpn' && openvpnIsActive) {
        loadOpenvpnStatus();
      } else if (activeRemoteSubtab === 'duckdns') {
        loadDuckdnsStatus();
      }
    }
    const telegramTab = document.getElementById('tab-telegram');
    if (telegramTab && telegramTab.classList.contains('active')) {
      loadTelegramStatus(false);
    }
  }, 3000);

  const userLang = localStorage.getItem('nmb_lang') || window.__INITIAL_LANG__ || 'en';
  loadTranslations(userLang);
  initTheme();
  updateServerSelectVisibility(selectedEngine);
  refreshStatus();
  loadConfig();

  // Non-blocking staggered background warming for secondary tabs
  setTimeout(() => {
    fetchWifiCapabilities();
    loadGuestWifiStatus();
  }, 1200);

  setTimeout(() => {
    loadNetworkDevices();
    loadIperfStatus();
    loadSystemInfo();
    loadKernelStatus();
    loadMacInfo();
  }, 2500);
  setInterval(refreshStatus, 3000);
  try { const v = localStorage.getItem('nmb_home_view'); if (v) { window.homeViewEngine = v; markViewPill(v); } } catch (e) {}
  loadHomeOoklaServers();
  loadCollector();
  setInterval(() => loadHomeOoklaServers(false), 5 * 60 * 1000);
  setInterval(pollSnifferStats, 2000);
  setInterval(() => {
    const syslogTab = document.getElementById('tab-syslog');
    if (syslogTab && syslogTab.classList.contains('active')) {
      if (devLogActiveSubtab === 'syslog' && syslogLive) {
        fetchSystemSyslog(false);
      } else if (devLogActiveSubtab === 'devlog' && devLogLive) {
        fetchDevLogs(false);
      }
    }
  }, 2500);


  // --- REAL-TIME TASK MANAGER & PROCESS MONITOR (HTOP WEB VIEW) ---
  const tasksState = {
    pollingTimer: null,
    pollIntervalMs: 2000,
    searchQuery: '',
    categoryFilter: 'all',
    sortKey: 'cpu_percent',
    sortAsc: false,
    processes: [],
    telemetry: null
  };

  async function loadTasksOverview() {
    try {
      const res = await fetch('/api/system/tasks?limit=200');
      if (!res.ok) return;
      const data = await res.json();
      if (!data || data.status !== 'ok') return;

      tasksState.telemetry = data;
      tasksState.processes = data.processes || [];

      // Update CPU meters
      const cpu = data.cpu || {};
      const totalCpu = typeof cpu.total_percent === 'number' ? cpu.total_percent.toFixed(1) : (typeof cpu.total_usage_pct === 'number' ? cpu.total_usage_pct.toFixed(1) : '0.0');
      const totalBadge = document.getElementById('tasks-cpu-total-badge');
      if (totalBadge) totalBadge.textContent = totalCpu + '% Total';

      const coresList = document.getElementById('tasks-cpu-cores-list');
      if (coresList && Array.isArray(cpu.cores)) {
        coresList.innerHTML = cpu.cores.map((c, i) => {
          const rawPct = (typeof c.percent === 'number') ? c.percent : (c.usage_pct || 0);
          const pct = Math.max(0, Math.min(100, rawPct)).toFixed(1);
          let barColor = '#10b981';
          if (rawPct > 85) barColor = '#ef4444';
          else if (rawPct > 60) barColor = '#f59e0b';
          else if (rawPct > 30) barColor = '#3b82f6';
          return `
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 2px;">
                <span>Core ${i}</span>
                <span style="color: ${barColor}; font-weight: bold;">${pct}%</span>
              </div>
              <div style="height: 6px; background: rgba(255,255,255,0.08); border-radius: 3px; overflow: hidden;">
                <div style="width: ${pct}%; height: 100%; background: ${barColor}; transition: width 0.3s ease;"></div>
              </div>
            </div>
          `;
        }).join('');
      }

      const freqEl = document.getElementById('tasks-cpu-freq');
      if (freqEl) freqEl.textContent = cpu.cpu_freq_mhz ? `${cpu.cpu_freq_mhz} MHz` : 'N/A';
      const tempEl = document.getElementById('tasks-cpu-temp');
      if (tempEl) tempEl.textContent = (cpu.temp_c || cpu.cpu_temp_c) ? `${cpu.temp_c || cpu.cpu_temp_c} °C` : 'N/A';

      // Update Memory & Swap
      const mem = data.memory || {};
      const memPct = (typeof mem.used_percent === 'number') ? mem.used_percent.toFixed(1) : (mem.used_pct ? mem.used_pct.toFixed(1) : '0.0');
      const memBadge = document.getElementById('tasks-mem-total-badge');
      if (memBadge) memBadge.textContent = `${memPct}% Used`;

      const ramText = document.getElementById('tasks-ram-text');
      if (ramText) ramText.textContent = `${mem.used_human || ((mem.used_mb || 0) + ' MB')} / ${mem.total_human || ((mem.total_mb || 0) + ' MB')}`;
      const ramPctEl = document.getElementById('tasks-ram-percent');
      if (ramPctEl) ramPctEl.textContent = `${memPct}%`;

      const ramTotal = mem.total_mb || 1;
      const usedPct = ((mem.used_mb || 0) / ramTotal * 100).toFixed(1);
      const buffPct = ((mem.buffers_mb || 0) / ramTotal * 100).toFixed(1);
      const cachePct = ((mem.cached_mb || 0) / ramTotal * 100).toFixed(1);

      const ramBarUsed = document.getElementById('tasks-ram-bar-used');
      if (ramBarUsed) ramBarUsed.style.width = usedPct + '%';
      const ramBarBuff = document.getElementById('tasks-ram-bar-buff');
      if (ramBarBuff) ramBarBuff.style.width = buffPct + '%';
      const ramBarCache = document.getElementById('tasks-ram-bar-cache');
      if (ramBarCache) ramBarCache.style.width = cachePct + '%';

      const swap = data.swap || {};
      const swapPct = (typeof swap.used_percent === 'number') ? swap.used_percent.toFixed(1) : (swap.used_pct ? swap.used_pct.toFixed(1) : '0.0');
      const swapText = document.getElementById('tasks-swap-text');
      if (swapText) swapText.textContent = `${swap.used_human || ((swap.used_mb || 0) + ' MB')} / ${swap.total_human || ((swap.total_mb || 0) + ' MB')}`;
      const swapPctEl = document.getElementById('tasks-swap-percent');
      if (swapPctEl) swapPctEl.textContent = `${swapPct}%`;
      const swapBar = document.getElementById('tasks-swap-bar');
      if (swapBar) swapBar.style.width = swapPct + '%';

      // Update Summary
      const summary = data.summary || {};
      const uptimeBadge = document.getElementById('tasks-uptime-badge');
      if (uptimeBadge) uptimeBadge.textContent = `Up: ${summary.uptime_formatted || (data.system && data.system.uptime_human) || '--'}`;

      const loadavgEl = document.getElementById('tasks-loadavg-text');
      if (loadavgEl) {
        if (summary.load_avg) {
          loadavgEl.textContent = `${summary.load_avg['1m']}  ${summary.load_avg['5m']}  ${summary.load_avg['15m']}`;
        } else if (data.system && data.system.loadavg_human) {
          loadavgEl.textContent = data.system.loadavg_human;
        }
      }

      const totalTasksEl = document.getElementById('tasks-count-total');
      if (totalTasksEl) totalTasksEl.textContent = summary.tasks_total || (data.stats && data.stats.total) || 0;
      const runningEl = document.getElementById('tasks-count-running');
      if (runningEl) runningEl.textContent = summary.tasks_running || (data.stats && data.stats.running) || 0;
      const sleepingEl = document.getElementById('tasks-count-sleeping');
      if (sleepingEl) sleepingEl.textContent = summary.tasks_sleeping || (data.stats && data.stats.sleeping) || 0;
      const zombieEl = document.getElementById('tasks-count-zombie');
      if (zombieEl) zombieEl.textContent = summary.tasks_zombie || (data.stats && data.stats.zombie) || 0;

      // Render processes table
      renderTasksTable();
    } catch (e) {
      console.error('loadTasksOverview error:', e);
    }
  }

  function renderTasksTable() {
    const tbody = document.getElementById('tasks-procs-tbody');
    if (!tbody) return;

    let procs = tasksState.processes.slice();

    // Category filter
    if (tasksState.categoryFilter === 'nmb') {
      procs = procs.filter(p => p.is_nmb);
    } else if (tasksState.categoryFilter === 'apps') {
      procs = procs.filter(p => !['root', 'syslog', 'messagebus', 'avahi', 'systemd-timesync'].includes(p.user));
    }

    // Search query filter
    if (tasksState.searchQuery) {
      const q = tasksState.searchQuery.toLowerCase();
      procs = procs.filter(p => {
        return (p.command && p.command.toLowerCase().includes(q)) ||
               (p.args && p.args.toLowerCase().includes(q)) ||
               (p.user && p.user.toLowerCase().includes(q)) ||
               String(p.pid).includes(q);
      });
    }

    // Sort
    const key = tasksState.sortKey;
    const asc = tasksState.sortAsc;
    procs.sort((a, b) => {
      let valA = a[key] !== undefined ? a[key] : (key === 'cpu_percent' ? a.cpu_pct : a.mem_pct);
      let valB = b[key] !== undefined ? b[key] : (key === 'cpu_percent' ? b.cpu_pct : b.mem_pct);
      if (typeof valA === 'string') valA = valA.toLowerCase();
      if (typeof valB === 'string') valB = valB.toLowerCase();
      if (valA < valB) return asc ? -1 : 1;
      if (valA > valB) return asc ? 1 : -1;
      return 0;
    });

    const countEl = document.getElementById('tasks-table-footer-count');
    if (countEl) countEl.textContent = `Showing ${procs.length} of ${tasksState.processes.length} processes`;

    if (procs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="13" style="text-align: center; padding: 20px; color: var(--text-muted);">${t('tasks_no_match', 'No processes matching filter')}</td></tr>`;
      return;
    }

    tbody.innerHTML = procs.map(p => {
      const isProtected = p.pid === 1 || (tasksState.telemetry && p.pid === tasksState.telemetry.server_pid);
      const isNmb = p.is_nmb;
      const rowBg = isNmb ? 'rgba(56, 189, 248, 0.05)' : 'transparent';
      const cmdDisplay = p.args ? p.args : p.command;
      const cpuVal = typeof p.cpu_percent === 'number' ? p.cpu_percent : (p.cpu_pct || 0);
      const memVal = typeof p.mem_percent === 'number' ? p.mem_percent : (p.mem_pct || 0);
      const cpuColor = cpuVal > 50 ? '#ef4444' : (cpuVal > 10 ? '#f59e0b' : '#38bdf8');
      const memColor = memVal > 20 ? '#ec4899' : '#a855f7';

      return `
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.04); background: ${rowBg};">
          <td style="padding: 6px 10px; color: #f8fafc; font-weight: bold; white-space: nowrap;">${escapeHtml(p.pid)}</td>
          <td style="padding: 6px 10px; color: ${p.user === 'root' ? '#f59e0b' : '#94a3b8'}; white-space: nowrap;">${escapeHtml(p.user)}</td>
          <td style="padding: 6px 10px; color: #64748b; white-space: nowrap;">${p.pri !== undefined ? p.pri : (p.priority || 0)}</td>
          <td style="padding: 6px 10px; color: #64748b; white-space: nowrap;">${p.ni !== undefined ? p.ni : (p.nice || 0)}</td>
          <td style="padding: 6px 10px; color: #64748b; white-space: nowrap;">${escapeHtml(p.virt_h || p.vsz_human || '-')}</td>
          <td style="padding: 6px 10px; color: #94a3b8; white-space: nowrap;">${escapeHtml(p.res_h || p.rss_human || '-')}</td>
          <td style="padding: 6px 10px; color: #64748b; white-space: nowrap;">${escapeHtml(p.shr_h || '-')}</td>
          <td style="padding: 6px 10px; color: ${(p.stat || p.state || '').startsWith('R') ? '#34d399' : '#94a3b8'}; font-weight: 600; white-space: nowrap;">${escapeHtml(p.stat || p.state)}</td>
          <td style="padding: 6px 10px; color: ${cpuColor}; font-weight: bold; white-space: nowrap;">${cpuVal.toFixed(1)}</td>
          <td style="padding: 6px 10px; color: ${memColor}; white-space: nowrap;">${memVal.toFixed(1)}</td>
          <td style="padding: 6px 10px; color: #94a3b8; white-space: nowrap;">${escapeHtml(p.time)}</td>
          <td style="padding: 6px 10px; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(cmdDisplay)}">
            ${isNmb ? '<span style="color: #38bdf8; font-weight: bold;">[NMB] </span>' : ''}${escapeHtml(cmdDisplay)}
          </td>
          <td style="padding: 6px 10px; text-align: center; white-space: nowrap;">
            ${isProtected ?
              '<span style="font-size: 11px; color: #64748b; white-space: nowrap;">(Protected)</span>' :
              `<div style="display: flex; gap: 4px; justify-content: center; flex-wrap: nowrap;">
                <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; background: rgba(239, 68, 68, 0.15); color: #f87171; border-color: rgba(239,68,68,0.3); white-space: nowrap;" onclick="promptKillProcess(${jsArg(p.pid)}, ${jsArg(p.command)}, 15)" title="Graceful SIGTERM">${t('tasks_btn_term', 'Term')}</button>
                <button type="button" class="btn-secondary" style="font-size: 11px; padding: 2px 6px; background: rgba(239, 68, 68, 0.3); color: #fca5a5; border-color: rgba(239,68,68,0.5); white-space: nowrap;" onclick="promptKillProcess(${jsArg(p.pid)}, ${jsArg(p.command)}, 9)" title="Force SIGKILL">${t('tasks_btn_kill', 'Kill')}</button>
              </div>`
            }
          </td>
        </tr>
      `;
    }).join('');
  }

  function sortTasksTable(key) {
    if (tasksState.sortKey === key) {
      tasksState.sortAsc = !tasksState.sortAsc;
    } else {
      tasksState.sortKey = key;
      tasksState.sortAsc = (key === 'user' || key === 'command');
    }
    renderTasksTable();
  }

  function onTasksSearchInput(val) {
    tasksState.searchQuery = (val || '').trim();
    renderTasksTable();
  }

  function setTasksCategoryFilter(cat) {
    tasksState.categoryFilter = cat;
    ['all', 'nmb', 'apps'].forEach(c => {
      const b = document.getElementById(`tasks-filter-btn-${c}`);
      if (b) {
        if (c === cat) b.classList.add('active');
        else b.classList.remove('active');
      }
    });
    renderTasksTable();
  }

  function changeTasksRefreshRate(msStr) {
    const ms = parseInt(msStr, 10);
    tasksState.pollIntervalMs = ms;
    startTasksAutoRefresh();
  }

  function startTasksAutoRefresh() {
    stopTasksAutoRefresh();
    loadTasksOverview();
    if (tasksState.pollIntervalMs > 0) {
      tasksState.pollingTimer = setInterval(loadTasksOverview, tasksState.pollIntervalMs);
    }
  }

  function stopTasksAutoRefresh() {
    if (tasksState.pollingTimer) {
      clearInterval(tasksState.pollingTimer);
      tasksState.pollingTimer = null;
    }
  }

  async function promptKillProcess(pid, comm, signal) {
    const sigName = signal === 9 ? 'SIGKILL' : 'SIGTERM';
    const confirmPrompt = t('tasks_confirm_kill', 'Are you sure you want to terminate this process?') + `
PID: ${pid}
Command: ${comm}
Signal: ${sigName}`;
    if (!confirm(confirmPrompt)) {
      return;
    }
    try {
      const res = await fetch('/api/system/tasks/kill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pid: pid, signal: signal })
      });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast(data.message || t('tasks_process_killed', 'Process terminated.'));
        loadTasksOverview();
      } else {
        showToast(t('tasks_err_kill', 'Error terminating process: ') + (data.message || data.error || 'Unknown error'));
      }
    } catch (e) {
      showToast('Network error: ' + e);
    }
  }

  // ---- Port forwarding (router mode): the owner's rules and UPnP / NAT-PMP ----
  function pfRowHtml(r) {
    const proto = (r && r.proto) || 'tcp';
    const opt = (v, label) => `<option value="${v}"${proto === v ? ' selected' : ''}>${label}</option>`;
    return `<tr>
      <td><input type="checkbox" class="pf-on"${!r || r.on !== false ? ' checked' : ''}></td>
      <td><input type="text" class="form-input pf-name" maxlength="32" value="${escapeHtml((r && r.name) || '')}" style="min-width: 90px;"></td>
      <td><select class="form-input pf-proto">${opt('tcp', 'TCP')}${opt('udp', 'UDP')}${opt('both', escapeHtml(t('pf_both', 'TCP and UDP')))}</select></td>
      <td><input type="text" class="form-input pf-ext" placeholder="8080" value="${escapeHtml((r && r.ext) || '')}" style="width: 100px;"></td>
      <td><input type="text" class="form-input pf-ip" placeholder="192.168.100.20" value="${escapeHtml((r && r.ip) || '')}" style="width: 140px;"></td>
      <td><input type="text" class="form-input pf-port" placeholder="=" value="${r && r.port ? escapeHtml(String(r.port)) : ''}" style="width: 80px;"></td>
      <td><button type="button" class="btn-secondary" style="padding: 4px 10px;" onclick="this.closest('tr').remove()">✕</button></td>
    </tr>`;
  }

  function pfAddRow() {
    const body = document.getElementById('pf-rules');
    if (body) body.insertAdjacentHTML('beforeend', pfRowHtml(null));
  }

  function renderPortForward(d) {
    const en = document.getElementById('pf-enabled');
    if (en) en.checked = !!d.enabled;
    const up = document.getElementById('pf-upnp');
    if (up) up.checked = !!d.upnp;
    const body = document.getElementById('pf-rules');
    if (body) body.innerHTML = (d.rules || []).map(pfRowHtml).join('');
    const st = document.getElementById('pf-status');
    if (st) st.textContent = d.router_mode
      ? t('pf_router_on', 'Router mode on {wan}: {count} rule(s) applied.').replace('{wan}', d.wan || '--').replace('{count}', d.applied_rules || 0)
      : t('pf_not_router', 'The box is not in router mode: the rules are saved and apply when router mode runs.');
    const hint = document.getElementById('pf-hint');
    if (hint) hint.textContent = t('pf_hint', 'Ports the box itself uses on the internet side: {ports}.').replace('{ports}', (d.reserved || []).join(', ') || '--');
    const us = document.getElementById('pf-upnp-status');
    const ul = document.getElementById('pf-upnp-list');
    if (us) {
      if (d.upnp && !d.upnp_installed) us.textContent = t('pf_upnp_missing', 'The UPnP service (miniupnpd) is not installed; run the installer again.');
      else if (d.upnp_running) us.textContent = (d.upnp_mappings || []).length ? t('pf_upnp_running', 'UPnP is running; ports opened by devices:') : t('pf_upnp_none', 'No port is open by UPnP right now.');
      else us.textContent = '';
    }
    if (ul) ul.innerHTML = (d.upnp_mappings || []).map(m =>
      `<li>${escapeHtml(String(m.proto).toUpperCase())} ${escapeHtml(String(m.ext))} → ${escapeHtml(m.ip)}:${escapeHtml(String(m.port))}${m.name ? ' (' + escapeHtml(m.name) + ')' : ''}</li>`).join('');
  }

  async function loadPortForward() {
    try { const r = await fetch('/api/port-forward'); if (r.ok) renderPortForward(await r.json()); } catch (e) {}
  }

  async function savePortForward() {
    const rules = Array.from(document.querySelectorAll('#pf-rules tr')).map(tr => ({
      on: tr.querySelector('.pf-on').checked,
      name: tr.querySelector('.pf-name').value.trim(),
      proto: tr.querySelector('.pf-proto').value,
      ext: tr.querySelector('.pf-ext').value.trim(),
      ip: tr.querySelector('.pf-ip').value.trim(),
      port: tr.querySelector('.pf-port').value.trim(),
    })).filter(r => r.ext || r.ip || r.name);
    const msg = document.getElementById('pf-msg');
    try {
      const r = await fetch('/api/port-forward/save', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: document.getElementById('pf-enabled').checked, upnp: document.getElementById('pf-upnp').checked, rules})});
      const d = await r.json();
      if (msg) { msg.textContent = r.ok ? t('pf_saved', 'Saved. Router mode applies it within a few seconds.') : (d.message || 'Error'); msg.style.color = r.ok ? '#34d399' : '#f87171'; }
      if (r.ok) { renderPortForward(d); setTimeout(loadPortForward, 6000); }
    } catch (e) {
      if (msg) { msg.textContent = 'Network error: ' + e; msg.style.color = '#f87171'; }
    }
  }
  window.pfAddRow = pfAddRow;
  window.loadPortForward = loadPortForward;
  window.savePortForward = savePortForward;

  // ---- Data caps for automatic tests (per link and per connection type) ----
  const DC_LINKS = ['wired', 'wifi', 'usb', 'lag'];

  function dcBar(used, cap) {
    if (!cap) return escapeHtml(String(Math.round(used))) + ' MB';
    const pct = Math.min(100, Math.round(used / cap * 100));
    const color = pct >= 100 ? '#f87171' : (pct >= 80 ? '#fbbf24' : '#34d399');
    return `<div style="display: flex; align-items: center; gap: 8px;"><div style="flex: 1; min-width: 80px; height: 8px; background: #1e293b; border-radius: 4px;">` +
      `<div style="width: ${pct}%; height: 8px; background: ${color}; border-radius: 4px;"></div></div>` +
      `<span>${escapeHtml(String(Math.round(used)))} / ${escapeHtml(String(cap))} MB</span></div>`;
  }

  function renderDataCap(d) {
    const period = document.getElementById('dc-period');
    if (period && document.activeElement !== period) period.value = d.period || 'month';
    const rd = document.getElementById('dc-reset-day');
    if (rd && document.activeElement !== rd) rd.value = d.reset_day || 1;
    (d.links || []).forEach(l => {
      const inp = document.getElementById('dc-cap-' + l.link);
      if (inp && document.activeElement !== inp) inp.value = l.cap_mb || 0;
      const used = document.getElementById('dc-used-' + l.link);
      if (used) {
        let html = dcBar(l.used_mb || 0, l.cap_mb || 0);
        if (l.type_cap_mb) html += `<div class="form-hint">${escapeHtml(t('dc_t_' + l.type, l.type))}: ${dcBar(l.type_used_mb || 0, l.type_cap_mb)}</div>`;
        if (l.reached) html += `<div class="form-hint" style="color: #f87171;">${escapeHtml(t('dc_reached', 'cap reached: automatic tests stop'))}</div>`;
        used.innerHTML = html;
      }
    });
    document.querySelectorAll('.dc-type').forEach(inp => {
      if (document.activeElement !== inp) inp.value = (d.by_type || {})[inp.dataset.type] || 0;
    });
    const cur = document.getElementById('dc-current');
    if (cur) cur.textContent = t('dc_current', 'Tests now use {link} ({iface}). Period since {start}, next reset {next}.')
      .replace('{link}', t('dc_link_' + (d.current_link || 'wired'), d.current_link || '--'))
      .replace('{iface}', d.current_iface || '--').replace('{start}', d.period_start || '--').replace('{next}', d.next_reset || '--');
  }

  async function loadDataCap() {
    try { const r = await fetch('/api/data-cap'); if (r.ok) renderDataCap(await r.json()); } catch (e) {}
  }

  async function saveDataCap() {
    const body = {period: document.getElementById('dc-period').value, reset_day: Number(document.getElementById('dc-reset-day').value) || 1, by_type: {}};
    DC_LINKS.forEach(l => { body[l + '_mb'] = Number(document.getElementById('dc-cap-' + l).value) || 0; });
    document.querySelectorAll('.dc-type').forEach(inp => { const v = Number(inp.value) || 0; if (v) body.by_type[inp.dataset.type] = v; });
    const msg = document.getElementById('dc-msg');
    try {
      const r = await fetch('/api/data-cap/save', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      const d = await r.json();
      if (msg) { msg.textContent = r.ok ? t('dc_saved', 'Saved.') : (d.message || 'Error'); msg.style.color = r.ok ? '#34d399' : '#f87171'; }
      if (r.ok) renderDataCap(d);
    } catch (e) {
      if (msg) { msg.textContent = 'Network error: ' + e; msg.style.color = '#f87171'; }
    }
  }
  window.loadDataCap = loadDataCap;
  window.saveDataCap = saveDataCap;
