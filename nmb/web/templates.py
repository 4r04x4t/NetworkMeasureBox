"""Modern, zero-dependency embedded Web UI dashboard template for NetworkMeasureBox.

Open-source network quality, speed benchmark, and traffic diagnostics suite.
Includes multi-engine speed testing (Ookla, Cloudflare Edge, RTR-NetTest / Open-RMBT),
dual analog circular gauges, real-time packet sniffer & flow inspector, and dynamic server directory.
"""
from __future__ import annotations


def get_dashboard_html() -> str:
    """Return the complete single-page application HTML string."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NetworkMeasureBox - Universal Network Telemetry & Benchmark Probe</title>
  <style>
    :root {
      --bg: #0b101b;
      --card-bg: rgba(18, 24, 38, 0.85);
      --card-border: #26334d;
      --text: #f1f5f9;
      --text-muted: #8fa0ba;
      --brand-blue: #0284c7;
      --brand-blue-hover: #0369a1;
      --brand-blue-active: #075985;
      --accent-amber: #e5a93c;
      --dark-panel: #111622;
      --green: #10b981;
      --amber: #f59e0b;
      --red: #ef4444;
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: var(--font);
      line-height: 1.5;
      padding: 16px 20px 40px;
      min-height: 100vh;
    }
    .container { max-width: 1200px; margin: 0 auto; }

    /* Main Header */
    .app-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      padding: 12px 0 16px;
      margin-bottom: 12px;
      flex-wrap: wrap;
      gap: 12px;
      border-bottom: 1px solid #1e293b;
    }
    .app-header-left {
      font-size: 13px;
      line-height: 1.5;
    }
    .app-header-center {
      text-align: center;
      flex: 1;
      min-width: 280px;
    }
    .app-title {
      font-size: 24px;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: -0.2px;
    }
    .app-subtitle {
      font-size: 12.5px;
      color: var(--text-muted);
      margin-top: 2px;
    }
    .app-header-right {
      text-align: right;
      font-size: 13px;
      line-height: 1.5;
    }
    .meta-lbl { color: #ffffff; font-weight: 600; }
    .meta-val { color: #38bdf8; font-weight: 500; }

    /* Tab Bar */
    .app-tabs {
      display: flex;
      gap: 4px;
      background: #0d1424;
      padding: 4px;
      border-radius: 8px;
      margin-bottom: 20px;
      overflow-x: auto;
      border: 1px solid #1e293b;
    }
    .app-tab-btn {
      background: #1e293b;
      border: 1px solid #334155;
      color: #cbd5e1;
      font-size: 13px;
      font-weight: 600;
      padding: 8px 14px;
      border-radius: 6px;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.15s ease;
    }
    .app-tab-btn:hover {
      background: #334155;
      color: #ffffff;
    }
    .app-tab-btn.active {
      background: var(--brand-blue);
      color: #ffffff;
      border-color: var(--brand-blue);
      box-shadow: 0 2px 8px rgba(2, 132, 199, 0.4);
    }

    /* Content Cards */
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    .app-box {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 24px;
      backdrop-filter: blur(8px);
    }
    .stat-line {
      display: flex;
      justify-content: space-between;
      padding: 9px 0;
      border-bottom: 1px solid #1f293d;
      font-size: 14.5px;
    }
    .stat-lbl { color: var(--text-muted); font-weight: 500; }
    .stat-val { color: var(--text); font-weight: 600; }
    .stat-speed { font-size: 16px; color: #38bdf8; font-family: monospace; }
    .section-subtitle {
      font-size: 15px;
      font-weight: 700;
      color: #ffffff;
      margin: 20px 0 10px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* Engine Selector Pills */
    .engine-selector-box {
      background: #090e1a;
      border: 1px solid #1e293b;
      border-radius: 8px;
      padding: 14px 18px;
      margin-bottom: 20px;
    }
    .engine-pills {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    .engine-pill {
      background: #131c2e;
      border: 1px solid #26354f;
      color: #94a3b8;
      padding: 8px 16px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s ease;
    }
    .engine-pill:hover {
      background: #1e2c45;
      color: #f1f5f9;
      border-color: #38bdf8;
    }
    .engine-pill.active {
      background: rgba(2, 132, 199, 0.2);
      border-color: #38bdf8;
      color: #ffffff;
      box-shadow: 0 0 12px rgba(56, 189, 248, 0.3);
    }
    .engine-desc {
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 8px;
    }

    /* Terminal Preview Box */
    .terminal-box {
      background: #070b13;
      border: 1px solid #1a2336;
      border-radius: 6px;
      padding: 14px;
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      font-size: 12.5px;
      color: #a5f3fc;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-all;
      margin: 10px 0;
      max-height: 240px;
      overflow-y: auto;
    }

    /* Action Buttons */
    .action-buttons-row {
      display: flex;
      gap: 10px;
      margin-top: 20px;
      flex-wrap: wrap;
    }
    button {
      font-family: inherit;
    }
    .btn-primary {
      background: var(--brand-blue);
      color: #ffffff;
      border: 1px solid var(--brand-blue);
      font-size: 13.5px;
      font-weight: 600;
      padding: 9px 20px;
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }
    .btn-primary:hover { background: var(--brand-blue-hover); }
    .btn-secondary {
      background: #1e293b;
      color: #cbd5e1;
      border: 1px solid #334155;
      font-size: 13.5px;
      font-weight: 600;
      padding: 9px 16px;
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }
    .btn-secondary:hover { background: #334155; color: #ffffff; }
    .btn-danger {
      background: #dc2626;
      color: #ffffff;
      border: 1px solid #dc2626;
      font-size: 13.5px;
      font-weight: 600;
      padding: 9px 16px;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .btn-danger:hover { background: #b91c1c; }

    /* Tables */
    .data-table-wrap {
      overflow-x: auto;
      margin-top: 12px;
      border: 1px solid #1e293b;
      border-radius: 6px;
    }
    table.data-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      text-align: left;
    }
    table.data-table thead th {
      background: #172554;
      color: #ffffff;
      padding: 10px 14px;
      font-weight: 600;
      border-right: 1px solid rgba(255,255,255,0.1);
      white-space: nowrap;
    }
    table.data-table thead th:last-child { border-right: none; }
    table.data-table tbody td {
      padding: 10px 14px;
      border-bottom: 1px solid #1e293b;
      border-right: 1px solid #1e293b;
      color: #cbd5e1;
    }
    table.data-table tbody td:last-child { border-right: none; }
    table.data-table tbody tr:nth-child(even) { background: rgba(30, 41, 59, 0.4); }
    table.data-table tbody tr:hover { background: rgba(56, 189, 248, 0.08); }
    table.data-table tfoot td {
      padding: 10px 14px;
      background: #0f172a;
      color: #f1f5f9;
      font-weight: 600;
      border-top: 2px solid var(--brand-blue);
      border-right: 1px solid #1e293b;
    }
    table.data-table tfoot td:last-child { border-right: none; }

    /* Badges */
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }
    .badge-ok { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981; }
    .badge-warn { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; }
    .badge-crit { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; }

    /* Measuring active banner */
    .measuring-banner {
      background: rgba(2, 132, 199, 0.15);
      border: 1px solid var(--brand-blue);
      border-radius: 6px;
      padding: 14px 20px;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      gap: 12px;
      color: #38bdf8;
      font-weight: 600;
      animation: pulse-glow 2s infinite ease-in-out;
    }
    @keyframes pulse-glow {
      0%, 100% { box-shadow: 0 0 10px rgba(2, 132, 199, 0.2); }
      50% { box-shadow: 0 0 20px rgba(2, 132, 199, 0.5); }
    }
    .spinner-circle {
      width: 18px;
      height: 18px;
      border: 3px solid rgba(56, 189, 248, 0.3);
      border-top-color: #38bdf8;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* Live Bandwidth Monitor (QoS) */
    .qos-container {
      background: var(--dark-panel);
      border: 1px solid #1e293b;
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 24px;
    }
    .qos-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 12px;
      border-bottom: 1px solid #1e293b;
      flex-wrap: wrap;
      gap: 10px;
    }
    .qos-title {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 18px;
      font-weight: 700;
      color: #ffffff;
    }
    .qos-badge {
      background: #1e293b;
      border: 1px solid var(--accent-amber);
      color: var(--accent-amber);
      font-size: 11px;
      font-weight: 800;
      padding: 3px 8px;
      border-radius: 4px;
      letter-spacing: 0.5px;
    }
    .qos-controls {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .qos-gauges-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
      margin-bottom: 30px;
    }
    @media (max-width: 768px) {
      .qos-gauges-row { grid-template-columns: 1fr; }
    }
    .qos-gauge-box {
      background: #080c14;
      border: 1px solid #192233;
      border-radius: 8px;
      padding: 20px;
      text-align: center;
    }
    .qos-gauge-label {
      font-size: 14px;
      font-weight: 700;
      color: #94a3b8;
      margin-bottom: 10px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .qos-gauge-svg {
      width: 100%;
      max-width: 220px;
      height: auto;
      margin: 0 auto;
      display: block;
    }
    .qos-clients-panel {
      background: #080c14;
      border: 1px solid #192233;
      border-radius: 8px;
      padding: 16px 20px;
    }
    .qos-legend {
      display: flex;
      justify-content: flex-end;
      gap: 16px;
      font-size: 12px;
      color: #94a3b8;
      margin-bottom: 12px;
    }
    .legend-item { display: flex; align-items: center; gap: 6px; }
    .dot-up { width: 8px; height: 8px; background: #38bdf8; border-radius: 50%; }
    .dot-down { width: 8px; height: 8px; background: var(--accent-amber); border-radius: 50%; }
    .client-row {
      display: flex;
      align-items: center;
      padding: 10px 0;
      border-bottom: 1px solid #141c2c;
      font-size: 13px;
    }
    .client-row:last-child { border-bottom: none; }
    .client-icon { width: 32px; font-size: 18px; color: #94a3b8; text-align: center; }
    .client-info { flex: 1; min-width: 140px; padding: 0 10px; }
    .client-name { font-weight: 600; color: #f1f5f9; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .client-bars { flex: 2; padding: 0 10px; }
    .client-bar-track { height: 6px; background: #141c2b; border-radius: 3px; margin: 4px 0; overflow: hidden; }
    .client-bar-fill-up { height: 100%; background: #38bdf8; border-radius: 3px; width: 0%; transition: width 0.3s; }
    .client-bar-fill-down { height: 100%; background: var(--accent-amber); border-radius: 3px; width: 0%; transition: width 0.3s; }
    .client-rates { width: 90px; text-align: right; font-family: monospace; font-size: 12px; }
    .rate-up { color: #38bdf8; }
    .rate-down { color: var(--accent-amber); }

    /* Input & Forms */
    .form-group {
      margin-bottom: 16px;
    }
    .form-label {
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 6px;
    }
    .form-input {
      width: 100%;
      background: #090e1a;
      border: 1px solid #26354f;
      color: #ffffff;
      padding: 9px 14px;
      border-radius: 6px;
      font-size: 13.5px;
      outline: none;
      transition: border-color 0.15s;
    }
    .form-input:focus {
      border-color: var(--brand-blue);
      box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.2);
    }
    .search-row {
      display: flex;
      gap: 10px;
      align-items: center;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }

    /* Toast Notification */
    #toast-msg {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #1e293b;
      border: 1px solid var(--brand-blue);
      color: #ffffff;
      padding: 12px 20px;
      border-radius: 6px;
      font-size: 13.5px;
      font-weight: 500;
      display: none;
      box-shadow: 0 6px 20px rgba(0,0,0,0.5);
      z-index: 9999;
    }

    /* Router Sub-Navigation & Cards */
    .router-subnav {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 20px;
      border-bottom: 1px solid #1e293b;
      padding-bottom: 12px;
    }
    .router-subtab-btn {
      background: #0f172a;
      border: 1px solid #334155;
      color: #94a3b8;
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .router-subtab-btn:hover {
      background: #1e293b;
      color: #ffffff;
      border-color: #475569;
    }
    .router-subtab-btn.active {
      background: rgba(2, 132, 199, 0.2);
      border-color: #38bdf8;
      color: #ffffff;
      box-shadow: 0 0 10px rgba(56, 189, 248, 0.25);
    }
    .router-subtab-content {
      display: none;
    }
    .router-subtab-content.active {
      display: block;
      animation: fadeIn 0.2s ease-in-out;
    }
    .router-section-card {
      background: #090e1a;
      border: 1px solid #1e293b;
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 20px;
    }
    .router-row-2 {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
      margin-top: 12px;
    }
    .router-row-3 {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-top: 12px;
    }
    .form-hint {
      font-size: 11.5px;
      color: var(--text-muted);
      margin-top: 4px;
    }
    .badge-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 12px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
    }

    /* Developer Console Styles */
    .devlog-container {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .devlog-toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      background: #090e1a;
      padding: 10px 14px;
      border-radius: 6px;
      border: 1px solid #1e293b;
    }
    .devlog-toolbar-left, .devlog-toolbar-right {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .devlog-level-pills {
      display: flex;
      gap: 3px;
      background: #0d1527;
      padding: 3px;
      border-radius: 5px;
      border: 1px solid #1e293b;
    }
    .devlog-level-pills .lvl-btn {
      background: transparent;
      border: none;
      color: #94a3b8;
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .devlog-level-pills .lvl-btn:hover {
      color: #f1f5f9;
      background: rgba(255,255,255,0.05);
    }
    .devlog-level-pills .lvl-btn.active {
      background: #1e293b;
      color: #38bdf8;
      box-shadow: 0 1px 4px rgba(0,0,0,0.4);
    }
    .devlog-terminal {
      background: #040711;
      border: 1px solid #1e293b;
      border-radius: 6px;
      padding: 10px 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      font-size: 11.5px;
      line-height: 1.5;
      color: #e2e8f0;
      height: 520px;
      overflow-y: auto;
      overflow-x: auto;
      box-shadow: inset 0 2px 10px rgba(0,0,0,0.6);
    }
    .devlog-row {
      display: flex;
      gap: 8px;
      padding: 2px 4px;
      border-bottom: 1px solid rgba(255,255,255,0.03);
      white-space: pre-wrap;
      word-break: break-all;
    }
    .devlog-row:hover {
      background: rgba(255,255,255,0.02);
    }
    .devlog-ts { color: #64748b; font-size: 11px; flex-shrink: 0; min-width: 145px; }
    .devlog-badge {
      font-size: 10px;
      font-weight: 700;
      padding: 1px 5px;
      border-radius: 3px;
      text-transform: uppercase;
      flex-shrink: 0;
      text-align: center;
      min-width: 50px;
    }
    .devlog-badge-trace { background: rgba(192, 132, 252, 0.15); color: #c084fc; border: 1px solid rgba(192, 132, 252, 0.3); }
    .devlog-badge-debug { background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }
    .devlog-badge-info  { background: rgba(52, 211, 153, 0.15); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.3); }
    .devlog-badge-warn  { background: rgba(251, 191, 36, 0.15); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.3); }
    .devlog-badge-error { background: rgba(248, 113, 113, 0.15); color: #f87171; border: 1px solid rgba(248, 113, 113, 0.3); }
    .devlog-meta { color: #818cf8; font-size: 11px; flex-shrink: 0; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .devlog-thread { color: #eab308; font-size: 10.5px; flex-shrink: 0; max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .devlog-msg { color: #f1f5f9; flex: 1; word-break: break-word; }
    .devlog-exc { color: #f87171; background: rgba(239, 68, 68, 0.08); padding: 4px 8px; border-radius: 4px; margin-top: 4px; font-size: 11px; border-left: 3px solid #ef4444; }
    .devlog-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 11.5px;
      color: var(--text-muted);
      padding: 4px 6px;
    }
    .syslog-row {
      display: flex;
      gap: 8px;
      padding: 3px 6px;
      border-bottom: 1px solid rgba(255,255,255,0.03);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 11.5px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .syslog-row:hover {
      background: rgba(255,255,255,0.03);
    }
    .syslog-ts { color: #64748b; font-size: 11px; flex-shrink: 0; min-width: 125px; user-select: none; }
    .syslog-host { color: #94a3b8; font-size: 11px; flex-shrink: 0; min-width: 75px; user-select: none; }
    .syslog-tag {
      font-size: 11px;
      font-weight: 600;
      flex-shrink: 0;
      min-width: 120px;
      max-width: 170px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .syslog-tag-kernel   { color: #38bdf8; }
    .syslog-tag-network  { color: #34d399; }
    .syslog-tag-nmb      { color: #c084fc; }
    .syslog-tag-security { color: #fbbf24; }
    .syslog-tag-system   { color: #94a3b8; }
    .syslog-msg { color: #e2e8f0; flex: 1; word-break: break-word; }
    .syslog-msg-link-up {
      color: #34d399;
      font-weight: 600;
      background: rgba(16, 185, 129, 0.08);
      border-left: 3px solid #10b981;
      padding-left: 6px;
    }
    .syslog-msg-link-down {
      color: #f87171;
      font-weight: 600;
      background: rgba(239, 68, 68, 0.08);
      border-left: 3px solid #ef4444;
      padding-left: 6px;
    }
    .syslog-msg-stacktrace {
      color: #e879f9;
      font-weight: 500;
      background: rgba(232, 121, 249, 0.06);
      border-left: 3px solid #d946ef;
      padding-left: 6px;
    }
    .syslog-msg-error {
      color: #fca5a5;
      background: rgba(239, 68, 68, 0.05);
      padding-left: 4px;
    }
    .syslog-msg-warn {
      color: #fde047;
    }
    .syslog-badge-tag {
      font-size: 10px;
      padding: 1px 4px;
      border-radius: 3px;
      margin-right: 6px;
      text-transform: uppercase;
      font-weight: 700;
    }
    .syslog-badge-linkup { background: #065f46; color: #6ee7b7; border: 1px solid #10b981; }
    .syslog-badge-linkdown { background: #7f1d1d; color: #fca5a5; border: 1px solid #ef4444; }
    .syslog-badge-error { background: #7f1d1d; color: #fca5a5; }
    .syslog-badge-warn { background: #78350f; color: #fde047; }
  </style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <header class="app-header">
    <div class="app-header-left">
      <div><span class="meta-lbl" data-i18n="box_id">Device ID:</span> <span id="hdr-box-id" class="meta-val">nmb-01</span></div>
      <div><span class="meta-lbl" data-i18n="firmware">Firmware:</span> <span id="hdr-fw-ver" class="meta-val">2.5.0</span></div>
      <div><span class="meta-lbl" data-i18n="net_mode">Net Mode:</span> <span id="hdr-mode" class="meta-val">standalone</span></div>
    </div>
    <div class="app-header-center">
      <h1 class="app-title">NetworkMeasureBox</h1>
      <div class="app-subtitle" data-i18n="app_subtitle">Universal Network Quality, Speed Benchmark & Diagnostics Suite</div>
      <div style="margin-top: 6px; display: inline-flex; align-items: center; gap: 6px; background: rgba(30, 41, 59, 0.7); padding: 3px 8px; border-radius: 6px; border: 1px solid #334155;">
        <span style="font-size: 13px;">🌐</span>
        <select id="lang-select" onchange="switchLanguage(this.value)" style="background: transparent; color: #f1f5f9; border: none; font-size: 12px; font-weight: 600; cursor: pointer; outline: none;">
          <option value="en">English (EN)</option>
          <option value="hu">Magyar (HU)</option>
          <option value="de">Deutsch (DE)</option>
          <option value="uk">Українська (UK)</option>
          <option value="fr">Français (FR)</option>
        </select>
      </div>
    </div>
    <div class="app-header-right">
      <div><span class="meta-lbl" data-i18n="public_ip">Public IP:</span> <span id="hdr-wan-ip" class="meta-val">--</span></div>
      <div><span class="meta-lbl" data-i18n="wan_iface">WAN Interface:</span> <span id="hdr-wan-iface" class="meta-val">eth0</span></div>
      <div><span class="meta-lbl" data-i18n="system_time">System Time:</span> <span id="hdr-uptime" class="meta-val">--</span></div>
    </div>
  </header>

  <!-- Tab Navigation -->
  <div class="app-tabs">
    <button class="app-tab-btn active" onclick="switchTab('tab-home')" data-i18n="tab_home">Dashboard</button>
    <button class="app-tab-btn" onclick="switchTab('tab-ping')" data-i18n="tab_ping">Ping Telemetry</button>
    <button class="app-tab-btn" onclick="switchTab('tab-speed')" data-i18n="tab_speed">Speed Results</button>
    <button class="app-tab-btn" onclick="switchTab('tab-iperf')" data-i18n="tab_iperf">⚡ iPerf3 Tests</button>
    <button class="app-tab-btn" onclick="switchTab('tab-traceroute')" data-i18n="tab_traceroute">🔍 Traceroute</button>
    <button class="app-tab-btn" onclick="switchTab('tab-ooni')" data-i18n="tab_ooni">🛡️ Censorship (OONI)</button>
    <button class="app-tab-btn" onclick="switchTab('tab-remote')" data-i18n="tab_remote">🌐 Remote Access & VPN</button>
    <button class="app-tab-btn" onclick="switchTab('tab-explorer')" data-i18n="tab_explorer">🌐 Network Explorer</button>
    <button class="app-tab-btn" onclick="switchTab('tab-sniffer')" data-i18n="tab_sniffer">📡 Packet Sniffer</button>
    <button class="app-tab-btn" onclick="switchTab('tab-qos')" data-i18n="tab_qos">📊 Bandwidth Monitor</button>
    <button class="app-tab-btn" onclick="switchTab('tab-portscan')" data-i18n="tab_portscan">Port Neutrality</button>
    <button class="app-tab-btn" onclick="switchTab('tab-script')" data-i18n="tab_script">Measurement & Servers</button>
    <button class="app-tab-btn" onclick="switchTab('tab-syslog')" data-i18n="tab_syslog">🛠️ Developer & System Logs</button>
    <button class="app-tab-btn" onclick="switchTab('tab-info')" data-i18n="tab_router">🛠️ Router & System</button>
    <button class="app-tab-btn" onclick="switchTab('tab-llm')" data-i18n="tab_llm">🤖 AI Diagnostics (LLM)</button>
  </div>

  <!-- TAB 1: DASHBOARD -->
  <div id="tab-home" class="tab-content active">
    <!-- Measuring Banner -->
    <div id="measuring-banner" class="measuring-banner" style="display: none;">
      <div class="spinner-circle"></div>
      <span id="measuring-text" data-i18n="measuring_wait">Please wait! Measurement in progress...</span>
    </div>

    <!-- Engine Selector -->
    <div class="engine-selector-box">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
        <span style="font-weight: 700; font-size: 13.5px; color: #f1f5f9;" data-i18n="engine_select_title">Select Measurement Engine:</span>
        <span style="font-size: 12px; color: #94a3b8;" data-i18n="engine_select_desc">Choose measurement engine for test execution</span>
      </div>
      <div class="engine-pills">
        <div class="engine-pill active" id="pill-engine-ookla" onclick="selectEngine('ookla')">
          <span>⚡</span> Ookla Speedtest
        </div>
        <div class="engine-pill" id="pill-engine-cloudflare" onclick="selectEngine('cloudflare')">
          <span>☁️</span> Cloudflare Edge (speed.cloudflare.com)
        </div>
        <div class="engine-pill" id="pill-engine-rtr" onclick="selectEngine('rtr')">
          <span>🇦🇹</span> RTR-NetTest (netztest.at / Open-RMBT)
        </div>
        <div class="engine-pill" id="pill-engine-iperf3" onclick="selectEngine('iperf3')">
          <span>⚡</span> iPerf3 Bandwidth & Jitter Probing
        </div>
        <div class="engine-pill" id="pill-engine-all" onclick="selectEngine('all')">
          <span>🏆</span> Combined (All engines sequentially)
        </div>
      </div>
      <div class="engine-desc" id="engine-desc-text">
        ⚡ <b>Ookla Speedtest:</b> Global server network, selectable destination, detailed download/upload and bufferbloat.
      </div>
    </div>

    <!-- Target Server & Operating Mode Quick Settings -->
    <div style="background: #090e1a; border: 1px solid #1e293b; border-radius: 8px; padding: 14px 18px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;">
      <div style="display: flex; align-items: center; gap: 14px; flex-wrap: wrap;">
        <div id="home-target-server-container" style="display: flex; align-items: center; gap: 8px;">
          <span style="font-weight: 700; font-size: 13px; color: #f1f5f9;" data-i18n="target_server">🎯 Target Server:</span>
          <select id="home-target-server-select" class="form-input" style="width: auto; min-width: 250px; padding: 7px 12px; font-size: 13px;" onchange="onHomeServerSelect(this.value)">
            <option value="31717">🎯 #31717 - 2Connect Kft. (Budapest)</option>
            <option value="auto" data-i18n="target_server_auto">🌐 Automatic (Closest Server)</option>
            <option value="2063">Magyar Telekom (#2063 Budapest)</option>
            <option value="1038">DIGI Telecommunications (#1038 Budapest)</option>
            <option value="3733">Vodafone / One (#3733 Budapest)</option>
            <option value="3652">Yettel HU (#3652 Budapest)</option>
            <option value="custom" data-i18n="target_server_custom">✏️ Enter Custom Server ID...</option>
          </select>
          <div id="home-custom-server-wrap" style="display: none; align-items: center; gap: 6px;">
            <input type="text" id="home-custom-server-id" placeholder="pl. 31717" class="form-input" style="width: 100px; padding: 7px 10px; font-size: 13px;">
            <button class="btn-primary" style="padding: 7px 12px; font-size: 12px;" onclick="applyHomeCustomServer()">Select</button>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-weight: 700; font-size: 13px; color: #f1f5f9;" data-i18n="script_interval">⏱️ Interval:</span>
          <select id="home-interval-select" class="form-input" style="width: auto; min-width: 170px; padding: 7px 12px; font-size: 13px;" onchange="onHomeIntervalSelect(this.value)">
            <option value="*/5 * * * *">⚡ 5m (&lt; 2%)</option>
            <option value="*/10 * * * *">⚡ 10m</option>
            <option value="*/15 * * * *">⏱️ 15m</option>
            <option value="*/30 * * * *">⏱️ 30m</option>
            <option value="0 * * * *">🕐 1h</option>
            <option value="0 */2 * * *">🕑 2h</option>
            <option value="0 */4 * * *">🕓 4h</option>
            <option value="0 */6 * * *" selected>🕕 6h</option>
            <option value="0 */12 * * *">🕛 12h</option>
            <option value="0 3 * * *">🌙 24h</option>
            <option value="manual">🔴 Manual Only</option>
          </select>
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
        <span id="home-mode-badge" class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981;">
          🟢 Automated Schedule Active
        </span>
        <button class="btn-secondary" style="font-size: 12px; padding: 6px 12px;" onclick="switchTab('tab-script')">⚙️ Configure Schedule</button>
      </div>
    </div>

    <!-- Last Test Results Card -->
    <div class="app-box" id="home-results-card">
      <div class="stat-line"><span class="stat-lbl" data-i18n="public_ip">Public IP:</span> <span id="home-public-ip" class="stat-val">Loading...</span></div>
      <div class="stat-line"><span class="stat-lbl" data-i18n="meas_engine">Engine:</span> <span id="home-engine" class="stat-val">Ookla</span></div>
      <div class="stat-line"><span class="stat-lbl" data-i18n="timestamp">Timestamp:</span> <span id="home-timestamp" class="stat-val">--</span></div>
      <div class="stat-line"><span class="stat-lbl" data-i18n="download_speed">Download Speed:</span> <span id="home-download" class="stat-val stat-speed">-- Mbps</span></div>
      <div class="stat-line"><span class="stat-lbl" data-i18n="upload_speed">Upload Speed:</span> <span id="home-upload" class="stat-val stat-speed">-- Mbps</span></div>
      <div class="stat-line"><span class="stat-lbl" data-i18n="latency_ping">Latency (RTT):</span> <span id="home-latency" class="stat-val">-- ms</span></div>
      <div class="stat-line"><span class="stat-lbl" data-i18n="bufferbloat_grade">Bufferbloat Score:</span> <span id="home-bufferbloat" class="stat-val">--</span></div>
      <div class="stat-line"><span class="stat-lbl" data-i18n="server_url">Server / Result Link:</span> <span id="home-server-link" class="stat-val">--</span></div>

      <!-- Benchmark Script Preview -->
      <div style="margin-top: 24px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <div class="section-subtitle" style="margin: 0;" data-i18n="executed_cmd_title">Real-time Executed Linux Command & Telemetry Output:</div>
          <button class="btn-secondary" style="font-size: 11px; padding: 4px 10px;" onclick="copyScriptToClipboard()" data-i18n="btn_copy_cmd">📋 Copy Command</button>
        </div>
        <pre id="home-script-box" class="terminal-box">#!/bin/sh
# Real-time executed command updates dynamically when measurement is started</pre>
      </div>

      <div class="action-buttons-row">
        <button class="btn-primary" id="btn-home-measure" onclick="triggerSpeedtest()" data-i18n="btn_measure_now">▶️ Run Speedtest Now</button>
        <button class="btn-danger" id="btn-home-stop" onclick="stopSpeedtest()" data-i18n="btn_stop_measure">⏹️ Stop Measurement</button>
        <button class="btn-secondary" onclick="window.open('/dossier', '_blank')" data-i18n="btn_dossier">📄 Export Official Report (Dossier)</button>
      </div>
    </div>
  </div>

  <!-- TAB 2: PING TELEMETRY -->
  <div id="tab-ping" class="tab-content">
    <div class="app-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
        <div class="section-subtitle" style="margin: 0;" data-i18n="ping_title">ICMP Ping Telemetry & Gateway Latency</div>
        <button class="btn-secondary" style="font-size: 12px; padding: 6px 12px;" onclick="window.location.href='/export/csv'">📡 Ping CSV Export</button>
      </div>
      <div id="chart-latency" style="background: #070d18; border-radius: 6px; padding: 12px; margin-bottom: 20px;">
        <p style="text-align: center; color: var(--text-muted); padding: 40px;">Loading chart telemetry...</p>
      </div>

      <div class="section-subtitle">Monitored Reference Probe Endpoints</div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th data-i18n="ping_target">Target Host / IP</th>
              <th data-i18n="ping_sent">Packets Sent</th>
              <th data-i18n="ping_lost">Packets Lost</th>
              <th data-i18n="ping_loss_pct">Loss %</th>
              <th data-i18n="ping_avg_rtt">Avg RTT</th>
              <th data-i18n="ping_p95_rtt">p95 RTT</th>
            </tr>
          </thead>
          <tbody id="probe-table-body">
            <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Loading telemetry data...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 3: SPEED RESULTS -->
  <div id="tab-speed" class="tab-content">
    <div class="app-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
        <div>
          <div class="section-subtitle" style="margin: 0;" data-i18n="speed_title">Historical Speedtest Measurement Log</div>
          <p style="font-size: 12px; color: var(--text-muted); margin-top: 2px;" data-i18n="speed_desc">Complete audit trail of all speed tests with provider SLA tracking, latency, and bufferbloat metrics.</p>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn-primary" style="font-size: 12px; padding: 6px 12px;" onclick="triggerSpeedtest()" data-i18n="btn_measure_now">▶️ Run Speedtest Now</button>
          <button class="btn-secondary" style="font-size: 12px; padding: 6px 12px;" onclick="window.location.href='/export/speedtests.csv'">📊 Speedtest CSV Export</button>
        </div>
      </div>

      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th data-i18n="speed_col_time">Timestamp</th>
              <th data-i18n="speed_col_engine">Engine</th>
              <th data-i18n="speed_col_down">Download</th>
              <th data-i18n="speed_col_up">Upload</th>
              <th data-i18n="speed_col_lat">Latency</th>
              <th data-i18n="speed_col_bb">Bufferbloat</th>
              <th data-i18n="speed_col_client_ip">Client IP</th>
              <th data-i18n="speed_col_server">Server / Report Link</th>
            </tr>
          </thead>
          <tbody id="speed-table-body">
            <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">Loading benchmark results...</td></tr>
          </tbody>
          <tfoot id="speed-table-tfoot">
            <tr>
              <td><b>Average</b></td>
              <td>--</td>
              <td id="avg-down-display"><b>-- Mbps</b></td>
              <td id="avg-up-display"><b>-- Mbps</b></td>
              <td id="avg-lat-display"><b>-- ms</b></td>
              <td colspan="3"></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB: IPERF3 BENCHMARK -->
  <div id="tab-iperf" class="tab-content">
    <div class="app-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
        <div>
          <div class="section-subtitle" style="margin: 0;" data-i18n="iperf_title">⚡ iPerf3 Throughput & Network Performance Benchmark</div>
          <p style="font-size: 12.5px; color: var(--text-muted); margin-top: 4px;" data-i18n="iperf_desc">
            Raw TCP and UDP bandwidth testing against local LAN endpoints, remote high-speed iPerf3 servers, or the built-in server daemon.
          </p>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <span id="iperf-server-badge" class="badge-pill" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569;">
            Daemon: Inactive
          </span>
          <button id="btn-iperf-server-toggle" class="btn-secondary" style="font-size: 12px; padding: 6px 12px;" onclick="toggleIperfServer()">
            ▶️ Start iPerf Server
          </button>
        </div>
      </div>

      <!-- Test Configuration Form -->
      <div style="background: #090e1a; border: 1px solid #1e293b; border-radius: 8px; padding: 18px; margin-bottom: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
          <div style="font-size: 13.5px; font-weight: 700; color: #ffffff;" data-i18n="iperf_client_config">
            🛠️ Client Benchmark Configuration
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            <button class="btn-secondary" style="font-size: 12px; padding: 6px 13px; display: inline-flex; align-items: center; gap: 6px;" onclick="openPublicServersModal('client')">
              🌐 Browse Public Servers (170+ Global)
            </button>
            <button class="btn-secondary" style="font-size: 12px; padding: 6px 13px; display: inline-flex; align-items: center; gap: 6px;" onclick="probeCurrentIperfServer()">
              ⚡ Ping Server
            </button>
          </div>
        </div>
        <div id="iperf-selected-server-badge" style="display: none; background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; font-size: 12px; color: #38bdf8;">
        </div>
        <div class="router-row-3">
          <div class="form-group">
            <label class="form-label" data-i18n="iperf_target_host">Target iPerf3 Server Host / IP:</label>
            <input type="text" id="iperf-host" value="speedtest.init7.net" placeholder="e.g. speedtest.init7.net or 192.168.1.50" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label" data-i18n="iperf_port">Port:</label>
            <input type="number" id="iperf-port" value="5203" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label" data-i18n="iperf_duration">Duration (Seconds):</label>
            <input type="number" id="iperf-duration" value="10" class="form-input">
          </div>
        </div>
        <div class="router-row-3" style="margin-top: 10px;">
          <div class="form-group">
            <label class="form-label" data-i18n="iperf_protocol">Protocol:</label>
            <select id="iperf-protocol" class="form-input" onchange="onIperfProtoChange(this.value)">
              <option value="tcp" selected>TCP (Reliable Streams)</option>
              <option value="udp">UDP (Jitter & Packet Loss)</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label" data-i18n="iperf_parallel">Parallel Streams (-P):</label>
            <select id="iperf-parallel" class="form-input">
              <option value="1" selected>1 Stream</option>
              <option value="2">2 Streams</option>
              <option value="4">4 Streams</option>
              <option value="8">8 Streams</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label" data-i18n="iperf_direction">Direction:</label>
            <select id="iperf-reverse" class="form-input">
              <option value="false" selected data-i18n="iperf_dir_up">Client to Server (Upload)</option>
              <option value="true" data-i18n="iperf_dir_down">Server to Client (-R Reverse / Download)</option>
              <option value="bidir" data-i18n="iperf_dir_bidir">⚡ Simultaneous Both Ways / Full Duplex (--bidir)</option>
            </select>
          </div>
        </div>
        <div id="iperf-udp-options" class="router-row-2" style="display: none; margin-top: 10px;">
          <div class="form-group">
            <label class="form-label">Target Bandwidth (-b, for UDP):</label>
            <input type="text" id="iperf-target-bw" value="100M" placeholder="e.g. 100M, 500M, 1G" class="form-input">
          </div>
        </div>
        <div style="margin-top: 16px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
          <button id="btn-iperf-run" class="btn-primary" style="padding: 9px 20px;" onclick="runIperfTest()">
            ▶️ Run iPerf3 Benchmark
          </button>
          <span id="iperf-running-indicator" style="display: none; color: #38bdf8; font-size: 13px; font-weight: 600;">
            ⏳ Running benchmark... please wait.
          </span>
        </div>
      </div>

      <!-- Latest Results Card -->
      <div id="iperf-results-card" style="background: #090e1a; border: 1px solid #1e293b; border-radius: 8px; padding: 18px; margin-bottom: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <div style="font-size: 13.5px; font-weight: 700; color: #ffffff;" data-i18n="iperf_latest_results">
            📊 Latest iPerf3 Test Results
          </div>
          <span id="iperf-result-ts" style="font-size: 12px; color: var(--text-muted);">--</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px;">
          <div id="iperf-card-download" style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #0284c7; text-align: center; display: none;">
            <div style="font-size: 11.5px; color: #38bdf8; text-transform: uppercase; font-weight: 700;">⬇️ Download Speed</div>
            <div id="iperf-res-down" style="font-size: 24px; font-weight: 800; color: #38bdf8; font-family: monospace; margin-top: 4px;">-- Mbps</div>
          </div>
          <div id="iperf-card-upload" style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #059669; text-align: center; display: none;">
            <div style="font-size: 11.5px; color: #34d399; text-transform: uppercase; font-weight: 700;">⬆️ Upload Speed</div>
            <div id="iperf-res-up" style="font-size: 24px; font-weight: 800; color: #34d399; font-family: monospace; margin-top: 4px;">-- Mbps</div>
          </div>
          <div style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #1e293b; text-align: center;">
            <div id="iperf-res-label" style="font-size: 11.5px; color: var(--text-muted); text-transform: uppercase;">Throughput</div>
            <div id="iperf-res-mbps" style="font-size: 24px; font-weight: 800; color: #38bdf8; font-family: monospace; margin-top: 4px;">-- Mbps</div>
          </div>
          <div style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #1e293b; text-align: center;">
            <div style="font-size: 11.5px; color: var(--text-muted); text-transform: uppercase;">Retransmits</div>
            <div id="iperf-res-retransmits" style="font-size: 24px; font-weight: 800; color: #10b981; font-family: monospace; margin-top: 4px;">--</div>
          </div>
          <div style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #1e293b; text-align: center;">
            <div style="font-size: 11.5px; color: var(--text-muted); text-transform: uppercase;">Jitter</div>
            <div id="iperf-res-jitter" style="font-size: 24px; font-weight: 800; color: #fbbf24; font-family: monospace; margin-top: 4px;">-- ms</div>
          </div>
          <div style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #1e293b; text-align: center;">
            <div style="font-size: 11.5px; color: var(--text-muted); text-transform: uppercase;">Loss %</div>
            <div id="iperf-res-loss" style="font-size: 24px; font-weight: 800; color: #ef4444; font-family: monospace; margin-top: 4px;">--%</div>
          </div>
        </div>
        <div style="margin-top: 14px;">
          <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 6px;">Raw Terminal Output / Details:</div>
          <pre id="iperf-raw-log" class="terminal-box" style="max-height: 180px;">No test executed yet.</pre>
        </div>
      </div>
    </div>

    <!-- IPERF3 PUBLIC SERVERS BROWSER MODAL -->
    <div id="iperf-servers-modal" style="display: none; position: fixed; inset: 0; z-index: 99999; background: rgba(3, 7, 18, 0.85); backdrop-filter: blur(6px); align-items: center; justify-content: center; padding: 20px;">
      <div style="background: #0b1329; border: 1px solid #1e293b; border-radius: 12px; width: 100%; max-width: 900px; max-height: 85vh; display: flex; flex-direction: column; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7); overflow: hidden;">
        <!-- Header -->
        <div style="padding: 16px 20px; border-bottom: 1px solid #1e293b; display: flex; justify-content: space-between; align-items: center; background: #0f172a;">
          <div>
            <div style="font-size: 15px; font-weight: 700; color: #ffffff; display: flex; align-items: center; gap: 8px;">
              🌐 Public iPerf3 Servers Directory
              <span id="iperf-modal-count-badge" style="font-size: 11px; background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.35); padding: 2px 7px; border-radius: 10px;">Loading...</span>
            </div>
            <div style="font-size: 11.5px; color: #94a3b8; margin-top: 3px;">
              Dynamically fetched from global directories (export.iperf3serverlist.net & iperf.fr). Zero hardcoding.
            </div>
          </div>
          <button onclick="closePublicServersModal()" style="background: none; border: none; color: #94a3b8; font-size: 20px; cursor: pointer; padding: 4px 8px;">✕</button>
        </div>

        <!-- Controls & Search -->
        <div style="padding: 12px 20px; border-bottom: 1px solid #1e293b; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; background: #090e1a;">
          <input type="text" id="iperf-modal-search" placeholder="Search by Country, City, Host, or Provider (e.g. Vienna, DATAPACKET)..." class="form-input" style="flex: 1; min-width: 240px; padding: 7px 12px; font-size: 12.5px;" oninput="onPublicServerSearch(this.value)">
          <div style="display: flex; gap: 6px; flex-wrap: wrap;" id="iperf-modal-continents">
            <button class="btn-secondary active-filter" onclick="filterPublicContinent('all', this)" style="font-size: 11.5px; padding: 5px 10px;">All</button>
            <button class="btn-secondary" onclick="filterPublicContinent('Europe', this)" style="font-size: 11.5px; padding: 5px 10px;">🇪🇺 Europe</button>
            <button class="btn-secondary" onclick="filterPublicContinent('North America', this)" style="font-size: 11.5px; padding: 5px 10px;">🇺🇸 North America</button>
            <button class="btn-secondary" onclick="filterPublicContinent('Asia', this)" style="font-size: 11.5px; padding: 5px 10px;">🌏 Asia</button>
            <button class="btn-secondary" onclick="filterPublicContinent('Other', this)" style="font-size: 11.5px; padding: 5px 10px;">Other</button>
          </div>
          <button class="btn-secondary" onclick="loadPublicServers(true)" style="font-size: 11.5px; padding: 5px 12px; display: inline-flex; align-items: center; gap: 4px;">
            🔄 Refresh
          </button>
        </div>

        <!-- Server List Body -->
        <div id="iperf-modal-server-list" style="padding: 14px 20px; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 8px;">
          <div style="text-align: center; color: #94a3b8; padding: 30px 0;">Loading servers from directory...</div>
        </div>

        <!-- Footer -->
        <div style="padding: 10px 20px; border-top: 1px solid #1e293b; background: #0f172a; display: flex; justify-content: space-between; align-items: center; font-size: 11.5px; color: #94a3b8;">
          <span id="iperf-modal-source-label">Source: iperf3serverlist.net (live JSON)</span>
          <button class="btn-secondary" onclick="closePublicServersModal()" style="font-size: 12px; padding: 5px 14px;">Close</button>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB: TRACEROUTE -->
  <div id="tab-traceroute" class="tab-content">
    <div class="app-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
        <div>
          <div class="section-subtitle" style="margin: 0;" data-i18n="traceroute_title">🔍 Hop-by-Hop Visual Network Traceroute</div>
          <p style="font-size: 12.5px; color: var(--text-muted); margin-top: 4px;" data-i18n="traceroute_desc">
            Diagnose intermediate network latency, routing loops, peering bottlenecks, and carrier packet loss.
          </p>
        </div>
      </div>

      <div style="background: #090e1a; border: 1px solid #1e293b; border-radius: 8px; padding: 16px; margin-bottom: 20px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
        <div class="form-group" style="margin: 0; flex: 1; min-width: 240px;">
          <label class="form-label" data-i18n="traceroute_target">Destination Host / IP:</label>
          <input type="text" id="traceroute-target" value="1.1.1.1" placeholder="e.g. 1.1.1.1, 8.8.8.8, or cloudflare.com" class="form-input">
        </div>
        <div class="form-group" style="margin: 0; width: 120px;">
          <label class="form-label" data-i18n="traceroute_max_hops">Max Hops:</label>
          <input type="number" id="traceroute-max-hops" value="30" min="1" max="64" class="form-input">
        </div>
        <div style="margin-top: 22px;">
          <button id="btn-traceroute-run" class="btn-primary" style="padding: 9px 20px;" onclick="runTracerouteTest()">
            ▶️ Trace Route
          </button>
        </div>
        <div id="traceroute-indicator" style="display: none; margin-top: 22px; color: #38bdf8; font-size: 13px; font-weight: 600;">
          ⏳ Probing route hops...
        </div>
      </div>

      <!-- Hop Visual Table -->
      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 50px;">Hop</th>
              <th>IP Address</th>
              <th>Reverse DNS Hostname</th>
              <th data-i18n="traceroute_col_country">Country / Region</th>
              <th data-i18n="traceroute_col_isp">Provider / Carrier / ISP</th>
              <th>RTT 1</th>
              <th>RTT 2</th>
              <th>RTT 3</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="traceroute-table-body">
            <tr><td colspan="9" style="text-align: center; color: var(--text-muted);" data-i18n="traceroute_empty">Enter a destination and click Trace Route to begin.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB: OONI PROBE CENSORSHIP & INTERNET FREEDOM -->
  <div id="tab-ooni" class="tab-content">
    <div class="app-box">
      <!-- Title & Status Header -->
      <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; flex-wrap: wrap; gap: 14px;">
        <div>
          <div class="section-subtitle" style="margin: 0;" data-i18n="ooni_title">🛡️ Internet Censorship & Tampering Detector (OONI Probe)</div>
          <p style="font-size: 12.5px; color: var(--text-muted); margin-top: 4px;" data-i18n="ooni_desc">
            Powered by the Open Observatory of Network Interference (probe-cli). Detects DNS tampering, Deep Packet Inspection (DPI) middleboxes, website blocking, and messaging reachability.
          </p>
        </div>
        <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
          <span id="ooni-installed-badge" class="badge" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); padding: 5px 12px; border-radius: 6px; font-size: 12px; font-weight: 600;">
            OONI Probe Checking...
          </span>
          <span id="ooni-verdict-badge" class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 5px 12px; border-radius: 6px; font-size: 12px; font-weight: 600;">
            🟢 Open Network
          </span>
          <button class="btn-secondary" style="font-size: 12px; padding: 6px 14px;" onclick="loadOoniStatus()" data-i18n="btn_refresh">
            🔄 Refresh
          </button>
        </div>
      </div>

      <!-- Live Running Indicator Banner -->
      <div id="ooni-running-indicator" style="display: none; background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 8px; padding: 14px 18px; margin-bottom: 20px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <div class="spinner-circle" style="width: 18px; height: 18px; border-width: 2px;"></div>
            <span id="ooni-running-msg" style="color: #38bdf8; font-weight: 600; font-size: 13.5px;" data-i18n="ooni_running">OONI Probe Test in Progress...</span>
          </div>
          <span id="ooni-progress-txt" style="color: #38bdf8; font-size: 12.5px; font-weight: 700;">0%</span>
        </div>
        <div style="background: rgba(255, 255, 255, 0.1); border-radius: 4px; height: 6px; overflow: hidden;">
          <div id="ooni-progress-bar" style="background: #38bdf8; width: 0%; height: 100%; transition: width 0.3s ease;"></div>
        </div>
      </div>

      <!-- 4 Censorship Test Action Cards -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-bottom: 24px;">
        <!-- Card 1: Web Connectivity -->
        <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px;">
          <div style="font-weight: 700; font-size: 14px; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
            🌐 <span data-i18n="ooni_test_websites">Website Blocking & DNS Tampering</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;" data-i18n="ooni_desc_websites">
            Tests DNS resolution consistency, TCP connect, and TLS handshake against standard or custom websites.
          </p>
          <div style="margin-bottom: 10px;">
            <input type="text" id="ooni-custom-url" placeholder="https://example.com (or empty for default)" class="form-input" style="font-size: 12px; padding: 7px 10px;">
          </div>
          <button class="btn-primary" id="btn-ooni-websites" style="width: 100%; font-size: 12.5px; padding: 8px;" onclick="runOoniTest('websites')" data-i18n="ooni_btn_websites">
            ▶️ Run Website Test
          </button>
        </div>

        <!-- Card 2: Middleboxes & DPI -->
        <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px;">
          <div style="font-weight: 700; font-size: 14px; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
            📦 <span data-i18n="ooni_test_middlebox">Middlebox & DPI Inspection</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;" data-i18n="ooni_desc_middlebox">
            Detects HTTP header field manipulations, transparent proxy injections, and invalid request line filtering.
          </p>
          <div style="height: 38px;"></div>
          <button class="btn-primary" id="btn-ooni-middlebox" style="width: 100%; font-size: 12.5px; padding: 8px;" onclick="runOoniTest('middlebox')" data-i18n="ooni_btn_middlebox">
            ▶️ Test Middlebox / DPI
          </button>
        </div>

        <!-- Card 3: Instant Messaging -->
        <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px;">
          <div style="font-weight: 700; font-size: 14px; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
            💬 <span data-i18n="ooni_test_im">Instant Messaging Reachability</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;" data-i18n="ooni_desc_im">
            Verifies whether WhatsApp (web & API), Telegram, and Signal endpoints are uninhibited or blocked.
          </p>
          <div style="height: 38px;"></div>
          <button class="btn-primary" id="btn-ooni-im" style="width: 100%; font-size: 12.5px; padding: 8px;" onclick="runOoniTest('im')" data-i18n="ooni_btn_im">
            ▶️ Test Messaging Apps
          </button>
        </div>

        <!-- Card 4: Circumvention Tools -->
        <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px;">
          <div style="font-weight: 700; font-size: 14px; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
            🧅 <span data-i18n="ooni_test_circumvention">Tor & Circumvention Reachability</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;" data-i18n="ooni_desc_circumvention">
            Probes connectivity to Tor directory authorities, or_port nodes, and obfs4 censorship bridges.
          </p>
          <div style="height: 38px;"></div>
          <button class="btn-primary" id="btn-ooni-circumvention" style="width: 100%; font-size: 12.5px; padding: 8px;" onclick="runOoniTest('circumvention')" data-i18n="ooni_btn_circumvention">
            ▶️ Test Tor & Bridges
          </button>
        </div>
      </div>

      <!-- Latest Result Detail Box -->
      <div id="ooni-latest-detail-box" style="display: none; background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px; margin-bottom: 24px;">
        <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 10px; color: #38bdf8;" data-i18n="ooni_findings_title">
          📋 Latest Detailed Findings
        </div>
        <div id="ooni-latest-findings" style="font-family: monospace; font-size: 12px; line-height: 1.6; color: var(--text-main);"></div>
      </div>

      <!-- History Table -->
      <div style="margin-top: 10px;">
        <div style="font-weight: 700; font-size: 14px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
          <span data-i18n="ooni_history_title">📜 Recent Censorship Test History</span>
          <span id="ooni-network-label" style="font-size: 12px; font-weight: normal; color: var(--text-muted);">--</span>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th data-i18n="ooni_col_id">ID</th>
                <th data-i18n="ooni_col_category">Test Category</th>
                <th data-i18n="ooni_col_network">Monitored ASN / ISP</th>
                <th data-i18n="ooni_col_time">Start Time</th>
                <th data-i18n="ooni_col_anomalies">Anomalies / Blocks</th>
                <th data-i18n="ooni_col_total">Total Tests</th>
                <th data-i18n="ooni_col_verdict">Verdict</th>
                <th data-i18n="ooni_col_actions">Actions</th>
              </tr>
            </thead>
            <tbody id="ooni-history-table-body">
              <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">Loading OONI probe history...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- OONI Run Measurement Inspector Modal -->
      <div id="ooni-details-modal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.8); z-index: 9999; justify-content: center; align-items: center; padding: 20px;">
        <div style="background: #1e293b; border: 1px solid #334155; border-radius: 12px; max-width: 980px; width: 100%; max-height: 90vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 25px 50px rgba(0,0,0,0.6);">
          <!-- Modal Header -->
          <div style="padding: 16px 20px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.03);">
            <div>
              <div style="font-size: 15px; font-weight: 700; color: #38bdf8; display: flex; align-items: center; gap: 8px;">
                <span id="ooni-modal-title">🛡️ OONI Test Measurement Details</span>
                <span id="ooni-modal-anom-badge" class="badge"></span>
              </div>
              <div id="ooni-modal-subtitle" style="font-size: 12px; color: var(--text-muted); margin-top: 4px;"></div>
            </div>
            <button class="btn-secondary" style="padding: 5px 12px; font-size: 12px;" onclick="closeOoniModal()" data-i18n="ooni_modal_close">✕ Close</button>
          </div>

          <!-- Filter & Search Bar -->
          <div style="padding: 10px 20px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; background: rgba(0,0,0,0.2);">
            <div style="display: flex; gap: 6px;">
              <button id="btn-ooni-filter-all" class="btn-primary" style="font-size: 11.5px; padding: 4px 10px;" onclick="setOoniFilter('all')">All (<span id="ooni-cnt-all">0</span>)</button>
              <button id="btn-ooni-filter-anom" class="btn-secondary" style="font-size: 11.5px; padding: 4px 10px;" onclick="setOoniFilter('anomalies')">🔴 Anomalies (<span id="ooni-cnt-anom">0</span>)</button>
              <button id="btn-ooni-filter-clean" class="btn-secondary" style="font-size: 11.5px; padding: 4px 10px;" onclick="setOoniFilter('clean')">🟢 Clean (<span id="ooni-cnt-clean">0</span>)</button>
            </div>
            <div style="flex: 1; max-width: 320px;">
              <input type="text" id="ooni-search-box" class="form-input" style="font-size: 12px; padding: 5px 10px; width: 100%;" placeholder="Filter URL or test name..." oninput="applyOoniFilter()">
            </div>
          </div>

          <!-- Measurement Table Body -->
          <div style="overflow-y: auto; flex: 1; padding: 16px 20px;">
            <div id="ooni-measurements-spinner" style="text-align: center; padding: 40px; display: none;">
              <div class="spinner-circle" style="margin: 0 auto 12px;"></div>
              <span style="color: var(--text-muted); font-size: 13px;">Loading measurement details from OONI probe...</span>
            </div>
            <div id="ooni-measurements-container">
              <table class="data-table" style="font-size: 12px;">
                <thead>
                  <tr>
                    <th>Target URL / Input</th>
                    <th>Category</th>
                    <th>Status & Blocking</th>
                    <th>Runtime</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody id="ooni-measurements-tbody">
                </tbody>
              </table>
            </div>

            <!-- Deep Inspection Box -->
            <div id="ooni-deep-inspect-box" style="display: none; margin-top: 16px; background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 14px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <span id="ooni-deep-title" style="font-weight: 700; color: #38bdf8; font-size: 13px;">🔬 Deep Measurement Diagnostics</span>
                <button class="btn-secondary" style="font-size: 11px; padding: 2px 8px;" onclick="document.getElementById('ooni-deep-inspect-box').style.display='none'">Hide</button>
              </div>
              <div id="ooni-deep-content" style="font-size: 12px; line-height: 1.6;"></div>
              <div style="margin-top: 10px; display: flex; gap: 8px;">
                <button class="btn-secondary" style="font-size: 11px; padding: 4px 10px;" onclick="toggleOoniRawJson()" data-i18n="ooni_raw_json">📄 View Raw JSON</button>
                <button class="btn-secondary" style="font-size: 11px; padding: 4px 10px;" onclick="copyOoniRawJson()" data-i18n="ooni_copy_json">📋 Copy JSON</button>
              </div>
              <pre id="ooni-raw-json-pre" style="display: none; max-height: 250px; overflow-y: auto; background: #020617; border: 1px solid #1e293b; border-radius: 6px; padding: 10px; font-size: 11px; font-family: monospace; color: #cbd5e1; margin-top: 10px;"></pre>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>

  <!-- TAB: REMOTE ACCESS & VPN & PROXY -->
  <div id="tab-remote" class="tab-content">
    <div class="app-box">
      <!-- Title & Header -->
      <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; flex-wrap: wrap; gap: 14px;">
        <div>
          <div class="section-subtitle" style="margin: 0;" data-i18n="remote_title">Universal Remote Access, VPN Servers & HTTPS Proxy</div>
          <p style="font-size: 12.5px; color: var(--text-muted); margin-top: 4px;" data-i18n="remote_desc">
            Independent of network mode: secure remote access via DuckDNS DynDNS, WireGuard VPN, OpenVPN, and embedded HTTPS CONNECT proxy.
          </p>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn-secondary" style="font-size: 12px; padding: 6px 14px;" onclick="loadRemoteAccessStatus()" data-i18n="btn_refresh">🔄 Refresh</button>
        </div>
      </div>

      <!-- Remote Subtabs -->
      <div style="display: flex; gap: 8px; margin-bottom: 20px; border-bottom: 1px solid var(--border-color); padding-bottom: 12px; flex-wrap: wrap;">
        <button id="btn-subtab-duckdns" class="btn-primary" style="font-size: 12.5px; padding: 7px 16px;" onclick="switchRemoteSubtab('duckdns')" data-i18n="subtab_duckdns">🦆 DuckDNS (DynDNS)</button>
        <button id="btn-subtab-wireguard" class="btn-secondary" style="font-size: 12.5px; padding: 7px 16px;" onclick="switchRemoteSubtab('wireguard')" data-i18n="subtab_wireguard">🛡️ WireGuard Server</button>
        <button id="btn-subtab-openvpn" class="btn-secondary" style="font-size: 12.5px; padding: 7px 16px;" onclick="switchRemoteSubtab('openvpn')" data-i18n="subtab_openvpn">🔒 OpenVPN Server</button>
        <button id="btn-subtab-proxy" class="btn-secondary" style="font-size: 12.5px; padding: 7px 16px;" onclick="switchRemoteSubtab('proxy')" data-i18n="subtab_proxy">⚡ HTTPS Proxy</button>
      </div>

      <!-- SUBTAB 1: DUCKDNS -->
      <div id="subtab-content-duckdns" class="remote-subtab">
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px;">
          <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 18px;">
            <div style="font-weight: 700; font-size: 14px; margin-bottom: 12px; color: #38bdf8;" data-i18n="duckdns_title">DuckDNS Dynamic DNS Synchronization</div>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;" data-i18n="duckdns_desc">
              Automatically keeps your free DuckDNS hostname pointed at the device's public WAN IP address.
            </p>
            <div style="margin-bottom: 12px;">
              <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer;">
                <input type="checkbox" id="duckdns-enabled"> <span data-i18n="duckdns_enable">Enable DuckDNS Dynamic DNS Updater</span>
              </label>
            </div>
            <div style="margin-bottom: 12px;">
              <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="duckdns_domain">DuckDNS Subdomain (.duckdns.org):</label>
              <div style="display: flex; align-items: center; gap: 6px;">
                <input type="text" id="duckdns-domain" class="form-input" style="font-size: 13px; padding: 7px 10px; flex: 1;" placeholder="my-box">
                <span style="font-size: 12px; color: var(--text-muted);">.duckdns.org</span>
              </div>
            </div>
            <div style="margin-bottom: 12px;">
              <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="duckdns_token">DuckDNS Account Token:</label>
              <input type="password" id="duckdns-token" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" placeholder="00000000-0000-0000-0000-000000000000">
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 16px;">
              <div>
                <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="duckdns_interval">Update Interval (Minutes):</label>
                <input type="number" id="duckdns-interval" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" min="5" max="1440" value="10">
              </div>
              <div>
                <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="duckdns_custom_ip">Override Public IP (optional):</label>
                <input type="text" id="duckdns-custom-ip" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" placeholder="Auto-detect">
              </div>
            </div>
            <div style="display: flex; gap: 10px;">
              <button class="btn-primary" style="font-size: 12.5px; padding: 8px 16px;" onclick="saveDuckdnsSettings()" data-i18n="duckdns_btn_save">Save DuckDNS Settings</button>
              <button class="btn-secondary" style="font-size: 12.5px; padding: 8px 14px;" onclick="updateDuckdnsNow()" data-i18n="duckdns_btn_update">🔄 Force Update Now</button>
            </div>
          </div>

          <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 18px;">
            <div style="font-weight: 700; font-size: 14px; margin-bottom: 12px; color: #38bdf8;">DuckDNS Live Status</div>
            <div style="margin-bottom: 12px;">
              <span style="font-size: 12px; color: var(--text-muted);" data-i18n="duckdns_last_status">Last Update Status:</span>
              <span id="duckdns-status-badge" class="badge" style="margin-left: 8px;">Checking...</span>
            </div>
            <div style="margin-bottom: 12px;">
              <span style="font-size: 12px; color: var(--text-muted);" data-i18n="duckdns_last_ip">Detected Public IP:</span>
              <span id="duckdns-detected-ip" style="font-weight: 700; margin-left: 8px; color: #38bdf8;">--</span>
            </div>
            <div style="margin-bottom: 12px;">
              <span style="font-size: 12px; color: var(--text-muted);">Last Updated:</span>
              <span id="duckdns-last-time" style="margin-left: 8px; color: var(--text-main);">--</span>
            </div>
            <div style="margin-bottom: 12px;">
              <span style="font-size: 12px; color: var(--text-muted);">Next Scheduled:</span>
              <span id="duckdns-next-time" style="margin-left: 8px; color: var(--text-muted);">--</span>
            </div>
            <div id="duckdns-msg-box" style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px; font-family: monospace; font-size: 12px; color: #94a3b8; margin-top: 14px;">
              Ready.
            </div>
          </div>
        </div>
      </div>

      <!-- SUBTAB 2: WIREGUARD -->
      <div id="subtab-content-wireguard" class="remote-subtab" style="display: none;">
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-bottom: 20px;">
          <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
              <div style="font-weight: 700; font-size: 14px; color: #38bdf8;" data-i18n="wireguard_title">WireGuard High-Performance VPN Server</div>
              <span id="wg-status-badge" class="badge">--</span>
            </div>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;" data-i18n="wireguard_desc">
              Next-generation secure VPN server with instant peer creation, configuration download, and mobile QR code pairing.
            </p>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px;">
              <div>
                <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="wireguard_port">UDP Listen Port:</label>
                <input type="number" id="wg-port" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" value="51820">
              </div>
              <div>
                <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="wireguard_subnet">Server Tunnel Subnet:</label>
                <input type="text" id="wg-subnet" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" value="10.8.0.1/24">
              </div>
            </div>
            <div style="margin-bottom: 14px;">
              <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="wireguard_endpoint">Public Endpoint Host / DuckDNS:</label>
              <input type="text" id="wg-endpoint" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" placeholder="Auto (DuckDNS or WAN IP)">
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn-primary" style="font-size: 12.5px; padding: 8px 14px;" onclick="saveWireguardSettings()">Save Server Settings</button>
              <button id="btn-wg-toggle" class="btn-secondary" style="font-size: 12.5px; padding: 8px 14px;" onclick="toggleWireguardServer()">Toggle WireGuard</button>
            </div>
          </div>

          <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 18px;">
            <div style="font-weight: 700; font-size: 14px; margin-bottom: 12px; color: #38bdf8;" data-i18n="wireguard_btn_add_peer">➕ Add New Client Peer</div>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;">
              Generate cryptographic keys and create a ready-to-use client profile with 1-click QR code or .conf download.
            </p>
            <div style="margin-bottom: 12px;">
              <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="wireguard_peer_name">Client Peer Name:</label>
              <input type="text" id="wg-new-peer-name" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" placeholder="e.g. phone-pixel, laptop-work">
            </div>
            <div style="margin-bottom: 14px;">
              <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="wireguard_peer_ip">Client Tunnel IP (optional):</label>
              <input type="text" id="wg-new-peer-ip" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" placeholder="Auto-assign (e.g. 10.8.0.2)">
            </div>
            <button class="btn-primary" style="width: 100%; font-size: 12.5px; padding: 8px;" onclick="addWireguardPeer()">➕ Generate & Add Client Peer</button>
          </div>
        </div>

        <!-- WireGuard Peers Table -->
        <div style="font-weight: 700; font-size: 14px; margin-bottom: 10px;" data-i18n="wireguard_peers_title">Configured WireGuard Client Peers</div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th data-i18n="wireguard_col_name">Client Name</th>
                <th data-i18n="wireguard_col_ip">Tunnel IP</th>
                <th data-i18n="wireguard_col_status">Status</th>
                <th>Endpoint IP</th>
                <th data-i18n="wireguard_col_transfer">Transfer (RX / TX)</th>
                <th data-i18n="wireguard_col_handshake">Last Handshake</th>
                <th data-i18n="wireguard_col_actions">Actions</th>
              </tr>
            </thead>
            <tbody id="wg-peers-tbody">
              <tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No WireGuard peers configured yet.</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- SUBTAB 3: OPENVPN -->
      <div id="subtab-content-openvpn" class="remote-subtab" style="display: none;">
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-bottom: 20px;">
          <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
              <div style="font-weight: 700; font-size: 14px; color: #38bdf8;" data-i18n="openvpn_title">OpenVPN Elliptic Curve Tunnel Server</div>
              <span id="ovpn-status-badge" class="badge">--</span>
            </div>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;" data-i18n="openvpn_desc">
              Universal OpenVPN server with fast Elliptic Curve (prime256v1) PKI and unified standalone .ovpn profile download.
            </p>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px;">
              <div>
                <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="openvpn_proto">Protocol:</label>
                <select id="ovpn-proto" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;">
                  <option value="udp">UDP (Recommended)</option>
                  <option value="tcp">TCP</option>
                </select>
              </div>
              <div>
                <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="openvpn_port">Port:</label>
                <input type="number" id="ovpn-port" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" value="1194">
              </div>
            </div>
            <div style="margin-bottom: 14px;">
              <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="openvpn_endpoint">Public Hostname / DuckDNS:</label>
              <input type="text" id="ovpn-endpoint" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" placeholder="Auto (DuckDNS or WAN IP)">
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn-primary" style="font-size: 12.5px; padding: 8px 14px;" onclick="saveOpenvpnSettings()">Save Server Settings</button>
              <button id="btn-ovpn-toggle" class="btn-secondary" style="font-size: 12.5px; padding: 8px 14px;" onclick="toggleOpenvpnServer()">Toggle OpenVPN</button>
            </div>
          </div>

          <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 18px;">
            <div style="font-weight: 700; font-size: 14px; margin-bottom: 12px; color: #38bdf8;" data-i18n="openvpn_btn_add_client">➕ Add New Client</div>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;">
              Generates Elliptic Curve client certificate and creates a standalone unified .ovpn profile with embedded keys.
            </p>
            <div style="margin-bottom: 14px;">
              <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="openvpn_client_name">Client Identifier:</label>
              <input type="text" id="ovpn-new-client-name" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" placeholder="e.g. tablet-client, user-laptop">
            </div>
            <div style="height: 48px;"></div>
            <button class="btn-primary" style="width: 100%; font-size: 12.5px; padding: 8px;" onclick="addOpenvpnClient()">➕ Generate Client Certificate</button>
          </div>
        </div>

        <!-- OpenVPN Clients Table -->
        <div style="font-weight: 700; font-size: 14px; margin-bottom: 10px;" data-i18n="openvpn_clients_title">Configured OpenVPN Clients</div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th data-i18n="openvpn_col_name">Client Name</th>
                <th data-i18n="openvpn_col_status">Connection Status</th>
                <th data-i18n="openvpn_col_real_ip">Real Endpoint IP</th>
                <th data-i18n="openvpn_col_traffic">Traffic (RX / TX)</th>
                <th data-i18n="openvpn_col_connected">Connected Since</th>
                <th data-i18n="openvpn_col_actions">Actions</th>
              </tr>
            </thead>
            <tbody id="ovpn-clients-tbody">
              <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No OpenVPN clients configured yet.</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- SUBTAB 4: HTTPS PROXY -->
      <div id="subtab-content-proxy" class="remote-subtab" style="display: none;">
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-bottom: 20px;">
          <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
              <div style="font-weight: 700; font-size: 14px; color: #38bdf8;" data-i18n="proxy_title">Embedded HTTPS & HTTP CONNECT Proxy Server</div>
              <span id="proxy-status-badge" class="badge">--</span>
            </div>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;" data-i18n="proxy_desc">
              High-throughput forward proxy with HTTP CONNECT tunneling for end-to-end TLS / HTTPS encryption and optional authentication.
            </p>
            <div style="margin-bottom: 12px;">
              <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="proxy_port">Proxy Port:</label>
              <input type="number" id="proxy-port" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" value="8443">
            </div>
            <div style="margin-bottom: 12px;">
              <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer;">
                <input type="checkbox" id="proxy-auth-enable" onchange="toggleProxyAuthFields()"> <span data-i18n="proxy_auth_enable">Require Proxy Authentication (Basic Auth)</span>
              </label>
            </div>
            <div id="proxy-auth-fields" style="display: none; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px;">
              <div>
                <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="proxy_user">Proxy Username:</label>
                <input type="text" id="proxy-username" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" placeholder="proxyuser">
              </div>
              <div>
                <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;" data-i18n="proxy_pass">Proxy Password:</label>
                <input type="password" id="proxy-password" class="form-input" style="font-size: 13px; padding: 7px 10px; width: 100%;" placeholder="••••••••">
              </div>
            </div>
            <div style="margin-bottom: 16px;">
              <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer;">
                <input type="checkbox" id="proxy-tls-enable"> <span data-i18n="proxy_tls_enable">Encrypt Proxy Frontend (HTTPS-in-HTTPS)</span>
              </label>
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn-primary" style="font-size: 12.5px; padding: 8px 16px;" onclick="saveProxySettings()" data-i18n="proxy_btn_save">Save Proxy Settings</button>
              <button id="btn-proxy-toggle" class="btn-secondary" style="font-size: 12.5px; padding: 8px 14px;" onclick="toggleProxyServer()">Toggle Proxy</button>
            </div>
          </div>

          <!-- Proxy Real-Time Telemetry Card -->
          <div class="card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 18px;">
            <div style="font-weight: 700; font-size: 14px; margin-bottom: 12px; color: #38bdf8;">Live Proxy Telemetry</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
              <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;" data-i18n="proxy_stat_active">Active Connections:</div>
                <div id="proxy-stat-active" style="font-size: 20px; font-weight: 700; color: #10b981;">0</div>
              </div>
              <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; text-align: center;">
                <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;" data-i18n="proxy_stat_total">Total Handled:</div>
                <div id="proxy-stat-total" style="font-size: 20px; font-weight: 700; color: #38bdf8;">0</div>
              </div>
            </div>
            <div style="margin-top: 14px;">
              <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;" data-i18n="proxy_stat_traffic">Data Transferred:</div>
              <div id="proxy-stat-traffic" style="font-size: 14px; font-weight: 600; color: var(--text-main);">0 KB (RX) / 0 KB (TX)</div>
            </div>
            <div style="margin-top: 10px;">
              <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;" data-i18n="proxy_stat_uptime">Uptime:</div>
              <div id="proxy-stat-uptime" style="font-size: 13px; color: var(--text-muted);">--</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- QR Code Modal (for WireGuard) -->
  <div id="wg-qr-modal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 10000; justify-content: center; align-items: center; padding: 20px;">
    <div style="background: #1e293b; border: 1px solid #334155; border-radius: 12px; max-width: 420px; width: 100%; padding: 20px; text-align: center; box-shadow: 0 25px 50px rgba(0,0,0,0.6);">
      <div style="font-weight: 700; font-size: 16px; margin-bottom: 6px; color: #38bdf8;" id="wg-qr-peer-title">WireGuard QR Pairing</div>
      <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 16px;">
        Scan this QR code using the official WireGuard app on your iOS or Android device.
      </p>
      <div id="wg-qr-img-wrap" style="background: #ffffff; padding: 12px; border-radius: 8px; display: inline-block; margin-bottom: 16px;">
        <img id="wg-qr-img" src="" alt="WireGuard QR Code" style="width: 250px; height: 250px; display: block;">
      </div>
      <div>
        <button class="btn-primary" style="padding: 7px 20px; font-size: 12.5px;" onclick="document.getElementById('wg-qr-modal').style.display='none'">Done</button>
      </div>
    </div>
  </div>

  <!-- TAB: NETWORK EXPLORER -->
  <div id="tab-explorer" class="tab-content">
    <div class="app-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
        <div>
          <div class="section-subtitle" style="margin: 0;" data-i18n="explorer_title">🌐 Network Explorer & Device Inventory</div>
          <p style="font-size: 12.5px; color: var(--text-muted); margin-top: 4px;" data-i18n="explorer_desc">
            Discover all connected LAN, WAN, and Guest Wi-Fi devices in one unified view with automatic MAC vendor (OUI) lookup.
          </p>
        </div>
        <div style="display: flex; gap: 10px; align-items: center;">
          <select id="explorer-iface-select" class="form-input" style="width: auto; padding: 7px 12px; font-size: 13px;" onchange="loadNetworkDevices()">
            <option value="any">🌐 All Interfaces (Simultaneous LAN + Guest Wi-Fi)</option>
            <option value="eth0">🏠 Wired LAN (eth0)</option>
            <option value="wlan0">📶 Guest Wi-Fi Client (wlan0)</option>
          </select>
          <button id="btn-explorer-scan" class="btn-primary" style="font-size: 12.5px; padding: 7px 16px;" onclick="triggerNetworkSweep()">
            🔄 Scan Subnets Now
          </button>
        </div>
      </div>

      <!-- Dedicated Guest Wi-Fi Receiver Status & Integration Banner -->
      <div id="explorer-guest-banner" style="background: rgba(168, 85, 247, 0.1); border: 1px solid rgba(168, 85, 247, 0.35); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
        <div style="display: flex; align-items: center; gap: 12px;">
          <span style="font-size: 24px;">📶</span>
          <div>
            <div style="font-weight: 700; font-size: 13.5px; color: #e9d5ff; display: flex; align-items: center; gap: 8px;">
              <span>Guest Wi-Fi Client Probe:</span>
              <span id="explorer-guest-status-text" class="badge-pill" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569; font-size: 11px;">Loading...</span>
            </div>
            <div style="font-size: 12px; color: #d8b4fe; margin-top: 3px;" id="explorer-guest-details-text">
              Dual-homed: Wired eth0 connects to primary LAN, while wlan0 station connects to the isolated guest Wi-Fi.
            </div>
          </div>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn-secondary" style="font-size: 12px; padding: 6px 14px; border-color: rgba(168, 85, 247, 0.5); color: #e9d5ff;" onclick="switchTab('tab-info'); switchRouterSubtab('rsub-guest');">
            ⚙️ Guest Wi-Fi Settings & Scanner
          </button>
        </div>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
        <input type="text" id="explorer-search" placeholder="Filter devices by IP, MAC, Vendor or Hostname..." class="form-input" style="max-width: 320px; padding: 6px 12px; font-size: 12px;" onkeyup="filterDevicesTable(this.value)">
        <span id="explorer-count-badge" class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981;">0 Devices Discovered</span>
      </div>

      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>IP Address</th>
              <th>MAC Address</th>
              <th>Hardware Vendor (OUI)</th>
              <th>Hostname</th>
              <th>Interface</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="explorer-table-body">
            <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Loading discovered network devices...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 4: PORT AUDIT -->
  <div id="tab-portscan" class="tab-content">
    <div class="app-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
        <div>
          <div class="section-subtitle" style="margin: 0;" data-i18n="portscan_title">Net-Neutrality & Port Throttling Audit</div>
          <p style="font-size: 12.5px; color: var(--text-muted); margin-top: 4px;">
            Audits whether the ISP throttles or blocks specific ports (Web, DNS, Gaming, VPN, Tor).
          </p>
        </div>
        <button class="btn-primary" style="font-size: 12.5px; padding: 8px 16px;" onclick="triggerPortCheck()">⚡ Run Port Audit Now</button>
      </div>

      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th data-i18n="portscan_port">Port</th>
              <th data-i18n="portscan_proto">Protocol</th>
              <th data-i18n="portscan_target">Probe Endpoint</th>
              <th data-i18n="portscan_speed">Throughput</th>
              <th data-i18n="portscan_ratio">Ratio vs Port 443</th>
              <th data-i18n="portscan_verdict">Verdict</th>
            </tr>
          </thead>
          <tbody id="portscan-table-body">
            <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Loading port audit data...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 5: SYSTEM & DEVELOPER LOGS -->
  <div id="tab-syslog" class="tab-content">
    <div class="app-box">
      <!-- Subtab Selector & Action Toolbar -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid #1e293b; padding-bottom: 12px; flex-wrap: wrap; gap: 10px;">
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
          <button id="btn-subtab-syslog" class="app-tab-btn active" onclick="switchSyslogSubtab('syslog')" style="font-size: 13px;" data-i18n="subtab_system_syslog">🐧 Kernel & Hardware Syslog</button>
          <button id="btn-subtab-devlog" class="app-tab-btn" onclick="switchSyslogSubtab('devlog')" style="font-size: 13px;" data-i18n="subtab_devlog">🛠️ Developer Deep Console</button>
          <button id="btn-subtab-audit" class="app-tab-btn" onclick="switchSyslogSubtab('audit')" style="font-size: 13px;" data-i18n="subtab_audit">📋 System Audit Events</button>
        </div>
        <div>
          <button class="btn-danger" style="font-size: 12.5px; padding: 6px 14px; font-weight: 700; box-shadow: 0 2px 8px rgba(239, 68, 68, 0.25);" onclick="triggerTotalLogPurge()" data-i18n="btn_total_log_purge" title="Completely purge all system, kernel, file, and database logs">
            🔥 Total Log Purge
          </button>
        </div>
      </div>

      <!-- SUBTAB 0: HARDWARE & LINUX KERNEL SYSLOG (ROUTER GRADE) -->
      <div id="syslog-subtab-syslog" class="devlog-container" style="display: block;">
        <!-- Control Toolbar -->
        <div class="devlog-toolbar" style="flex-wrap: wrap; gap: 10px;">
          <div class="devlog-toolbar-left" style="flex-wrap: wrap; gap: 8px;">
            <!-- Live Stream Toggle -->
            <label style="display:flex; align-items:center; gap:6px; font-size:12px; font-weight:600; cursor:pointer; color:#38bdf8; user-select:none;">
              <input type="checkbox" id="syslog-live-chk" checked onchange="toggleSyslogLive(this.checked)">
              <span id="syslog-live-dot" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#10b981; box-shadow:0 0 6px #10b981;"></span>
              <span>Live Stream (2.5s)</span>
            </label>

            <!-- Source Filter Pills -->
            <div class="devlog-level-pills" id="syslog-source-pills">
              <button class="lvl-btn active" data-src="all" onclick="setSyslogSourceFilter('all')">🌐 ALL (<span id="syslog-cnt-all">0</span>)</button>
              <button class="lvl-btn" data-src="kernel" onclick="setSyslogSourceFilter('kernel')" style="color:#38bdf8;">🐧 KERNEL (dmesg) (<span id="syslog-cnt-kernel">0</span>)</button>
              <button class="lvl-btn" data-src="network" onclick="setSyslogSourceFilter('network')" style="color:#34d399;">🔌 NETWORK & PHY (<span id="syslog-cnt-network">0</span>)</button>
              <button class="lvl-btn" data-src="nmb" onclick="setSyslogSourceFilter('nmb')" style="color:#c084fc;">📦 NMB DAEMONS</button>
              <button class="lvl-btn" data-src="security" onclick="setSyslogSourceFilter('security')" style="color:#fbbf24;">🔐 SECURITY & SSH</button>
            </div>

            <!-- Severity / Event Quick-Filter -->
            <select id="syslog-severity-select" class="form-input" style="width:auto; padding:4px 8px; font-size:12px;" onchange="fetchSystemSyslog(true)">
              <option value="all">All Events & Severities</option>
              <option value="links">⚡ Link Up / Down & Wi-Fi only</option>
              <option value="errors">🚨 Errors, Panics & Stack Traces</option>
              <option value="warnings">⚠️ Warnings & Retries</option>
            </select>

            <!-- Line Count Selector -->
            <select id="syslog-lines-select" class="form-input" style="width:auto; padding:4px 8px; font-size:12px;" onchange="fetchSystemSyslog(true)">
              <option value="150">150 lines</option>
              <option value="300" selected>300 lines</option>
              <option value="600">600 lines</option>
              <option value="1200">1200 lines</option>
              <option value="2500">2500 lines</option>
            </select>

            <!-- Search Input -->
            <input type="text" id="syslog-search-input" placeholder="Search syslog / dmesg / eth0 / Wi-Fi..." class="form-input" style="padding:4px 8px; font-size:12px; width:220px;" onkeyup="onSyslogSearchKeyup(event)">
          </div>

          <div class="devlog-toolbar-right" style="gap: 8px;">
            <button class="btn-secondary" style="padding:4px 10px; font-size:12px;" onclick="downloadSystemSyslog()" title="Download raw system syslog file">📥 Download Raw Syslog (.log)</button>
            <button class="btn-danger" style="padding:4px 10px; font-size:12px; font-weight: 700;" onclick="triggerTotalLogPurge()" title="Purge all system, file, and database logs" data-i18n="btn_total_log_purge">🔥 Total Log Purge</button>
            <button class="btn-primary" style="padding:4px 10px; font-size:12px;" onclick="fetchSystemSyslog(true)">🔄 Refresh</button>
          </div>
        </div>

        <!-- Terminal Output Window (Syslog) -->
        <div id="syslog-terminal" class="devlog-terminal" style="max-height: 580px; min-height: 440px; background:#0b0f19; border: 1px solid #1e293b; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; line-height: 1.5; padding: 10px; overflow-y: auto;">
          <div style="color:var(--text-muted); text-align:center; padding:40px;">Connecting to system journal and kernel ring buffer...</div>
        </div>

        <!-- Terminal Status Footer -->
        <div class="devlog-footer" style="display:flex; justify-content:space-between; align-items:center; font-size:12px; padding:6px 12px; background:#0f172a; border-top:1px solid #1e293b; color:#94a3b8;">
          <div id="syslog-footer-info">Initializing hardware syslog feed...</div>
          <div><a href="javascript:void(0)" onclick="fetchSystemSyslog(true)" style="color:#38bdf8; text-decoration:none; font-weight:600;">Scroll to latest ⬇️</a></div>
        </div>
      </div>

      <!-- SUBTAB 1: DEVELOPER DEEP CONSOLE -->
      <div id="syslog-subtab-devlog" class="devlog-container" style="display: none;">
        <!-- Control Toolbar -->
        <div class="devlog-toolbar">
          <div class="devlog-toolbar-left">
            <!-- Live Stream Toggle -->
            <label style="display:flex; align-items:center; gap:6px; font-size:12px; font-weight:600; cursor:pointer; color:#38bdf8; user-select:none;">
              <input type="checkbox" id="devlog-live-chk" checked onchange="toggleDevLogLive(this.checked)">
              <span id="devlog-live-dot" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#10b981; box-shadow:0 0 6px #10b981;"></span>
              <span>Live Stream (2s)</span>
            </label>

            <!-- Level Filter Pills -->
            <div class="devlog-level-pills">
              <button class="lvl-btn active" data-lvl="ALL" onclick="setDevLogLevelFilter('ALL')">ALL (<span id="cnt-all">0</span>)</button>
              <button class="lvl-btn" data-lvl="TRACE" onclick="setDevLogLevelFilter('TRACE')" style="color:#c084fc;">TRACE</button>
              <button class="lvl-btn" data-lvl="DEBUG" onclick="setDevLogLevelFilter('DEBUG')" style="color:#38bdf8;">DEBUG</button>
              <button class="lvl-btn" data-lvl="INFO" onclick="setDevLogLevelFilter('INFO')" style="color:#34d399;">INFO</button>
              <button class="lvl-btn" data-lvl="WARN" onclick="setDevLogLevelFilter('WARN')" style="color:#fbbf24;">WARN</button>
              <button class="lvl-btn" data-lvl="ERROR" onclick="setDevLogLevelFilter('ERROR')" style="color:#f87171;">ERROR</button>
            </div>

            <!-- Component Filter -->
            <select id="devlog-comp-select" class="form-input" style="width:auto; padding:4px 8px; font-size:12px;" onchange="fetchDevLogs(true)">
              <option value="">All Components</option>
              <option value="nmb.speed">nmb.speed (Speedtest, Runner, Scheduler)</option>
              <option value="nmb.web">nmb.web (Web Server & REST API)</option>
              <option value="nmb.db">nmb.db (Database & WAL Queries)</option>
              <option value="nmb.netd">nmb.netd (Network Daemon, Wi-Fi, OS)</option>
              <option value="nmb.probe">nmb.probe (ICMP Probing, Telemetry)</option>
              <option value="nmb.sniffer">nmb.sniffer (Packet Sniffer)</option>
            </select>

            <!-- Search Input -->
            <input type="text" id="devlog-search-input" placeholder="Search logs (keyword / regex)..." class="form-input" style="padding:4px 8px; font-size:12px; width:200px;" onkeyup="onDevLogSearchKeyup(event)">
          </div>

          <div class="devlog-toolbar-right">
            <!-- Daemon Level Selector -->
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-size:12px; color:var(--text-muted); font-weight:600;">Daemon Level:</span>
              <select id="devlog-daemon-level-select" class="form-input" style="width:auto; padding:4px 8px; font-size:12px;" onchange="changeDaemonLogLevel(this.value)">
                <option value="DEBUG">DEBUG (Detailed)</option>
                <option value="TRACE">TRACE (Wire/Packet-level)</option>
                <option value="INFO">INFO (Normal)</option>
                <option value="WARNING">WARNING (Issues)</option>
                <option value="ERROR">ERROR (Errors only)</option>
              </select>
            </div>

            <button class="btn-secondary" style="padding:4px 10px; font-size:12px;" onclick="downloadDevLog()" title="Download full un-truncated developer log file">📥 Download (.log)</button>
            <button class="btn-danger" style="padding:4px 10px; font-size:12px;" onclick="clearDevLogBuffer()" title="Clear in-memory log buffer">🗑️ Clear Buffer</button>
            <button class="btn-danger" style="padding:4px 10px; font-size:12px; font-weight: 700;" onclick="triggerTotalLogPurge()" title="Purge all system, file, and database logs" data-i18n="btn_total_log_purge">🔥 Total Log Purge</button>
            <button class="btn-primary" style="padding:4px 10px; font-size:12px;" onclick="fetchDevLogs(true)">🔄 Refresh</button>
          </div>
        </div>

        <!-- Terminal Output Window -->
        <div id="devlog-terminal" class="devlog-terminal">
          <div style="color:var(--text-muted); text-align:center; padding:40px;">Loading developer logs...</div>
        </div>

        <!-- Terminal Status Footer -->
        <div class="devlog-footer">
          <div id="devlog-footer-info">Initializing log connection...</div>
          <div><a href="javascript:void(0)" onclick="fetchDevLogs(true)" style="color:#38bdf8; text-decoration:none;">Scroll to bottom ⬇️</a></div>
        </div>
      </div>

      <!-- SUBTAB 2: SYSTEM AUDIT EVENTS -->
      <div id="syslog-subtab-audit" style="display: none;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
          <div class="section-subtitle" style="margin: 0;" data-i18n="syslog_title">System Event Log & Audit Trail</div>
          <div style="display: flex; gap: 8px; align-items: center;">
            <input type="text" id="log-filter-input" placeholder="Filter system events..." class="form-input" style="max-width: 280px; padding: 6px 12px; font-size: 12px;" onkeyup="filterLogTable(this.value)">
            <button class="btn-danger" style="padding:6px 12px; font-size:12px; font-weight: 700;" onclick="triggerTotalLogPurge()" data-i18n="btn_total_log_purge">🔥 Total Log Purge</button>
          </div>
        </div>

        <div class="data-table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th data-i18n="speed_col_time">Timestamp</th>
                <th data-i18n="syslog_col_severity">Severity</th>
                <th data-i18n="syslog_col_source">Source</th>
                <th data-i18n="syslog_col_event">Event</th>
                <th data-i18n="syslog_col_detail">Details</th>
              </tr>
            </thead>
            <tbody id="syslog-table-body">
              <tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Loading system events...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 6: PACKET SNIFFER -->
  <div id="tab-sniffer" class="tab-content">
    <div class="app-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
        <div>
          <div class="section-subtitle" style="margin: 0;" data-i18n="sniffer_title">Network Packet Sniffer & Traffic Analyzer</div>
          <p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;" data-i18n="sniffer_desc">Inspect raw network packets across WAN, LAN, or Guest Wi-Fi interfaces simultaneously.</p>
        </div>
        <div style="display: flex; gap: 8px;">
          <select id="sniffer-iface-select" class="form-input" style="width: auto; padding: 6px 12px; font-size: 13px;">
            <option value="eth0">eth0 (Wired Primary LAN)</option>
            <option value="wlan0">wlan0 (Guest Wi-Fi Client Probe)</option>
            <option value="any">any (Simultaneous Multi-Interface)</option>
          </select>
          <button id="btn-sniffer-toggle" class="btn-primary" onclick="toggleSniffer()" data-i18n="sniffer_btn_start">▶️ Start Sniffing</button>
          <button class="btn-secondary" onclick="downloadPcap()" data-i18n="sniffer_btn_pcap">💾 Download PCAP</button>
          <button class="btn-danger" onclick="clearSniffer()" data-i18n="sniffer_btn_clear">🗑️ Clear Buffer</button>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 20px;">
        <div style="background: #090e1a; border: 1px solid #1e293b; padding: 14px; border-radius: 6px;">
          <div style="font-size: 12px; color: var(--text-muted);" data-i18n="sniffer_total_pkts">Total Packets:</div>
          <div id="sniffer-total-packets" style="font-size: 22px; font-weight: 700; color: #38bdf8;">0</div>
        </div>
        <div style="background: #090e1a; border: 1px solid #1e293b; padding: 14px; border-radius: 6px;">
          <div style="font-size: 12px; color: var(--text-muted);" data-i18n="sniffer_total_bytes">Total Bytes:</div>
          <div id="sniffer-total-bytes" style="font-size: 22px; font-weight: 700; color: #34d399;">0 KB</div>
        </div>
        <div style="background: #090e1a; border: 1px solid #1e293b; padding: 14px; border-radius: 6px;">
          <div style="font-size: 12px; color: var(--text-muted);">Packet Rate:</div>
          <div id="sniffer-pps" style="font-size: 22px; font-weight: 700; color: #fbbf24;">0 pps</div>
        </div>
        <div style="background: #090e1a; border: 1px solid #1e293b; padding: 14px; border-radius: 6px;">
          <div style="font-size: 12px; color: var(--text-muted);">Packet Drops / Errors:</div>
          <div id="sniffer-drops" style="font-size: 22px; font-weight: 700; color: #94a3b8;">0</div>
        </div>
      </div>

      <div class="section-subtitle">Recent Traffic Flows (Flow Inspector)</div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th data-i18n="speed_col_time">Timestamp</th>
              <th>Source IP : Port</th>
              <th>Destination IP : Port</th>
              <th data-i18n="portscan_proto">Protocol</th>
              <th>Size</th>
              <th>Flags / Info</th>
            </tr>
          </thead>
          <tbody id="sniffer-flows-body">
            <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Packet sniffer is inactive. Click Start Sniffing to observe live packet flows.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 7: SCRIPT & SERVERS FLEET -->
  <div id="tab-script" class="tab-content">
    <div class="app-box">
      <div class="section-subtitle" style="margin-top: 0;" data-i18n="script_title">Measurement Automation & Server Fleet</div>
      <p style="font-size: 12.5px; color: var(--text-muted); margin-bottom: 18px;">
        Schedule recurring tests, enforce network idle thresholds (<2%), and choose benchmark servers.
      </p>

      <!-- Automated Mode & Schedule Panel -->
      <div style="background: #090e1a; border: 1px solid #1e293b; border-radius: 8px; padding: 20px; margin-bottom: 24px;">
        <!-- Mode Selection: Manual vs Scheduled -->
        <div style="margin-bottom: 18px;">
          <div style="font-size: 11.5px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
            Measurement Trigger Mode:
          </div>
          <div style="display: flex; gap: 12px; flex-wrap: wrap;">
            <label id="lbl-mode-manual" style="cursor: pointer; flex: 1; min-width: 250px; background: #0f172a; border: 2px solid #334155; border-radius: 6px; padding: 12px 16px; display: flex; align-items: center; gap: 12px; transition: all 0.2s;">
              <input type="radio" name="sched_mode_radio" value="manual" id="radio-mode-manual" onchange="onSchedModeRadioChange('manual'); markSchedDirty();">
              <div>
                <div style="font-weight: 700; color: #f87171; font-size: 13.5px;" data-i18n="script_mode_manual">🔴 Manual Only</div>
                <div style="font-size: 11.5px; color: #94a3b8; margin-top: 2px;">No automated background testing. Tests only run when triggered manually.</div>
              </div>
            </label>
            <label id="lbl-mode-scheduled" style="cursor: pointer; flex: 1; min-width: 250px; background: #0f172a; border: 2px solid #0284c7; border-radius: 6px; padding: 12px 16px; display: flex; align-items: center; gap: 12px; transition: all 0.2s;">
              <input type="radio" name="sched_mode_radio" value="scheduled" id="radio-mode-scheduled" checked onchange="onSchedModeRadioChange('scheduled'); markSchedDirty();">
              <div>
                <div style="font-weight: 700; color: #34d399; font-size: 13.5px;" data-i18n="script_mode_scheduled">🟢 Automated Schedule</div>
                <div style="font-size: 11.5px; color: #94a3b8; margin-top: 2px;">Regular periodic tests execute automatically in background at scheduled intervals.</div>
              </div>
            </label>
          </div>
        </div>

        <!-- Scheduling Parameters Grid -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-bottom: 18px;">
          <!-- Interval / Frequency -->
          <div id="sched-interval-container">
            <label class="form-label" style="font-size: 12px;" data-i18n="script_interval">Measurement Interval:</label>
            <select id="sched-interval-select" class="form-input" onchange="onSchedIntervalChange(this.value); markSchedDirty();">
              <option value="*/5 * * * *">⚡ Every 5 minutes (Ultra frequent - strict &lt;2% gate)</option>
              <option value="*/10 * * * *">⚡ Every 10 minutes (Frequent)</option>
              <option value="*/15 * * * *">⏱️ Every 15 minutes</option>
              <option value="*/30 * * * *">⏱️ Every 30 minutes</option>
              <option value="0 * * * *">🕐 Every 1 hour</option>
              <option value="0 */2 * * *">🕑 Every 2 hours</option>
              <option value="0 */4 * * *">🕓 Every 4 hours</option>
              <option value="0 */6 * * *" selected>🕕 Every 6 hours (Recommended)</option>
              <option value="0 */12 * * *">🕛 Every 12 hours</option>
              <option value="0 3 * * *">🌙 Every 24 hours (Nightly at 03:00)</option>
              <option value="custom">✏️ Custom interval (Minutes or Cron expression)...</option>
            </select>
            <div id="sched-custom-cron-wrap" style="display: none; margin-top: 8px;">
              <input type="text" id="sched-custom-cron-input" placeholder="pl. 15 (perc) vagy */8 * * * * (cron)" class="form-input" oninput="markSchedDirty()">
              <div style="font-size: 11px; color: #94a3b8; margin-top: 3px;">Specify in minutes (e.g. <code>5</code>, <code>20</code>) or standard 5-field cron syntax.</div>
            </div>
          </div>

          <!-- Default Engine -->
          <div>
            <label class="form-label" style="font-size: 12px;" data-i18n="script_engine">Automated Engine:</label>
            <select id="sched-engine-select" class="form-input" onchange="markSchedDirty(); onSchedEngineSelectChange(this.value)">
              <option value="ookla" selected>⚡ Ookla Speedtest CLI</option>
              <option value="cloudflare">☁️ Cloudflare Edge (speed.cloudflare.com)</option>
              <option value="rtr">🇦🇹 RTR-NetTest (netztest.at / Open-RMBT)</option>
              <option value="iperf3">⚡ iPerf3 Symmetrical Bandwidth & Jitter</option>
              <option value="all">🏆 All 3 engines sequentially (Combined)</option>
            </select>
          </div>

          <!-- Target Server ID -->
          <div id="sched-target-server-wrap">
            <label class="form-label" style="font-size: 12px;">Automated Test Target Server:</label>
            <div style="display: flex; gap: 8px;">
              <input type="text" id="sched-server-id-input" placeholder="e.g. 31717 (blank = auto)" class="form-input" style="flex: 1;" oninput="markSchedDirty()">
              <button class="btn-secondary" style="font-size: 12px; white-space: nowrap; padding: 7px 12px;" onclick="quickResolveServerId()">Resolve</button>
              <button class="btn-secondary" style="font-size: 12px; white-space: nowrap; padding: 7px 12px;" onclick="clearSchedServer()">Auto</button>
            </div>
            <div id="sched-server-resolved-name" style="font-size: 11.5px; color: #38bdf8; margin-top: 5px;">
              Automatic selection
            </div>
          </div>

          <!-- iPerf3 Automated Target Endpoint -->
          <div id="sched-iperf-target-wrap" style="display: none;">
            <label class="form-label" style="font-size: 12px;">iPerf3 Automated Target Server & Port:</label>
            <div style="display: flex; gap: 8px;">
              <input type="text" id="sched-iperf-host" placeholder="pl. speedtest.init7.net" class="form-input" style="flex: 2;" oninput="markSchedDirty()">
              <input type="number" id="sched-iperf-port" value="5203" placeholder="5203" class="form-input" style="flex: 1; max-width: 90px;" oninput="markSchedDirty()">
              <button class="btn-secondary" style="font-size: 12px; white-space: nowrap; padding: 7px 12px;" onclick="openPublicServersModal('sched')">🌐 Browse</button>
            </div>
            <div id="sched-iperf-resolved-info" style="font-size: 11.5px; color: #38bdf8; margin-top: 5px;">
              Configured iPerf3 endpoint
            </div>
          </div>
        </div>

        <!-- Traffic Gate (< 2% Idle Load) Settings -->
        <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 8px; padding: 14px 16px; margin-bottom: 18px;">
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px;">
            <span style="font-size: 13px; font-weight: 700; color: #38bdf8; display: flex; align-items: center; gap: 6px;">
              🛡️ Traffic Gate: Idle Network Accuracy Gate (< 2% Network Usage)
            </span>
            <span id="sched-gate-badge" style="font-size: 11.5px; background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.35); padding: 3px 9px; border-radius: 5px; font-weight: 600;">
              Threshold: max 20.0 Mbps (on 1000 Mbps connection)
            </span>
          </div>
          <p style="font-size: 12px; color: #cbd5e1; margin-bottom: 12px; line-height: 1.5;">
            For automated testing, speedtests only trigger when current client traffic is <b>below 2.0%</b> of contracted bandwidth.
            This ensures measurements are <b>accurate and SLA-grade</b> without saturating your network or interfering with active streaming, downloads, or gaming.
          </p>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px;">
            <div>
              <label class="form-label" style="font-size: 11.5px;" data-i18n="script_gate_mode">Gate Mode:</label>
              <select id="sched-gate-mode" class="form-input" onchange="onSchedGateModeChange(this.value); markSchedDirty();">
                <option value="percent" selected>🟢 Strict &lt; 2% Idle Gate (Dynamic - Recommended)</option>
                <option value="fixed">Fixed bandwidth limit (kbps)</option>
              </select>
            </div>
            <div id="sched-gate-percent-wrap">
              <label class="form-label" style="font-size: 11.5px;" data-i18n="script_gate_pct">Max Network Usage (%):</label>
              <input type="number" id="sched-gate-percent" value="2.0" step="0.5" min="0.5" max="10.0" class="form-input" oninput="updateGateCalculatedBadge(); markSchedDirty()">
            </div>
            <div id="sched-gate-fixed-wrap" style="display: none;">
              <label class="form-label" style="font-size: 11.5px;" data-i18n="script_gate_kbps">Max Network Usage (kbps):</label>
              <input type="number" id="sched-gate-kbps" value="500" class="form-input" oninput="markSchedDirty()">
            </div>
          </div>
        </div>

        <!-- Save Button & Feedback -->
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; border-top: 1px solid #1e293b; padding-top: 14px;">
          <div id="sched-feedback-banner" style="font-size: 12.5px; color: #94a3b8;">
            Changes take effect immediately upon saving.
          </div>
          <div style="display: flex; gap: 10px;">
            <button type="button" class="btn-secondary" style="padding: 9px 18px; font-size: 13px;" onclick="resetScheduleForm()" data-i18n="sched_discard_btn">
              🔄 Discard / Reset
            </button>
            <button class="btn-primary" style="padding: 9px 22px; font-size: 13.5px;" onclick="saveScheduleSettings()" data-i18n="script_btn_save">
              💾 Save Scheduling Settings
            </button>
          </div>
        </div>
      </div>

      <!-- Server Fleet Explorer & Catalog -->
      <div class="section-subtitle" data-i18n="servers_title">Ookla & Global Benchmark Servers Fleet</div>
      <div class="search-row">
        <input type="text" id="server-search-input" placeholder="Search server by name, country, or ID..." data-i18n-placeholder="servers_search_placeholder" class="form-input" style="flex: 1; min-width: 250px;" oninput="onServerSearchInput(this.value)">
        <button class="btn-primary" style="padding: 8px 16px;" onclick="loadServers(document.getElementById('server-search-input').value)">🔍 Search</button>
        <div style="display: flex; gap: 6px;">
          <button class="btn-secondary" style="font-size: 12px; padding: 6px 12px;" onclick="loadServers('')">All</button>
          <button class="btn-secondary" style="font-size: 12px; padding: 6px 12px;" onclick="loadServers('hungary')">Hungary</button>
          <button class="btn-secondary" style="font-size: 12px; padding: 6px 12px;" onclick="loadServers('budapest')">Budapest</button>
        </div>
      </div>

      <div class="data-table-wrap" style="max-height: 400px; overflow-y: auto;">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 80px;">ID</th>
              <th>Provider / Server Name</th>
              <th>City / Location</th>
              <th>Country</th>
              <th style="text-align: center; width: 220px;">Action</th>
            </tr>
          </thead>
          <tbody id="script-servers-tbody">
            <tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">Loading servers...</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Script Preview -->
      <div style="margin-top: 24px;">
        <div class="section-subtitle" data-i18n="script_preview_title">Generated Benchmark Script:</div>
        <pre id="script-preview-box" class="terminal-box">#!/bin/sh
# The script dynamically generates matching the selected target server and configuration</pre>
      </div>
    </div>
  </div>

  <!-- TAB 8: BANDWIDTH MONITOR -->
  <div id="tab-qos" class="tab-content">
    <div class="qos-container">
      <div class="qos-header">
        <div class="qos-title">
          <span data-i18n="qos_title">Real-Time Bandwidth & Client Traffic Monitor</span>
          <span class="qos-badge">LIVE QoS</span>
        </div>
        <div class="qos-controls">
          <label style="font-size: 12px; color: #94a3b8;" data-i18n="qos_gauge_scale">Gauge Scale:</label>
          <select id="qos-scale-select" class="form-input" style="width: auto; padding: 4px 8px; font-size: 12px;" onchange="updateGaugeScale(this.value)">
            <option value="auto" selected>Automatic (Auto)</option>
            <option value="10">10 Mbps</option>
            <option value="50">50 Mbps</option>
            <option value="100">100 Mbps</option>
            <option value="500">500 Mbps</option>
            <option value="1000">1000 Mbps (1 Gbps)</option>
          </select>
        </div>
      </div>

      <!-- Gauges -->
      <div class="qos-gauges-row">
        <div class="qos-gauge-box">
          <div class="qos-gauge-label" data-i18n="qos_upload_gauge">Upload Bandwidth</div>
          <svg viewBox="0 0 200 200" class="qos-gauge-svg">
            <path d="M 30 150 A 80 80 0 1 1 170 150" fill="none" stroke="#1a2436" stroke-width="14" stroke-linecap="round"/>
            <path id="gauge-arc-up" d="M 30 150 A 80 80 0 1 1 170 150" fill="none" stroke="#38bdf8" stroke-width="14" stroke-linecap="round" stroke-dasharray="335" stroke-dashoffset="335" style="transition: stroke-dashoffset 0.5s ease;"/>
            <line id="gauge-needle-up" x1="100" y1="100" x2="100" y2="35" stroke="#38bdf8" stroke-width="3" stroke-linecap="round" transform="rotate(-120 100 100)" style="transition: transform 0.5s ease;"/>
            <circle cx="100" cy="100" r="8" fill="#38bdf8"/>
            <circle cx="100" cy="100" r="4" fill="#080c14"/>
            <text id="gauge-text-up" x="100" y="165" text-anchor="middle" fill="#ffffff" font-size="20" font-weight="700" font-family="monospace">0.0</text>
            <text x="100" y="182" text-anchor="middle" fill="#94a3b8" font-size="11" font-weight="600">Mbps</text>
          </svg>
        </div>

        <div class="qos-gauge-box">
          <div class="qos-gauge-label" data-i18n="qos_download_gauge">Download Bandwidth</div>
          <svg viewBox="0 0 200 200" class="qos-gauge-svg">
            <path d="M 30 150 A 80 80 0 1 1 170 150" fill="none" stroke="#1a2436" stroke-width="14" stroke-linecap="round"/>
            <path id="gauge-arc-down" d="M 30 150 A 80 80 0 1 1 170 150" fill="none" stroke="var(--accent-amber)" stroke-width="14" stroke-linecap="round" stroke-dasharray="335" stroke-dashoffset="335" style="transition: stroke-dashoffset 0.5s ease;"/>
            <line id="gauge-needle-down" x1="100" y1="100" x2="100" y2="35" stroke="var(--accent-amber)" stroke-width="3" stroke-linecap="round" transform="rotate(-120 100 100)" style="transition: transform 0.5s ease;"/>
            <circle cx="100" cy="100" r="8" fill="var(--accent-amber)"/>
            <circle cx="100" cy="100" r="4" fill="#080c14"/>
            <text id="gauge-text-down" x="100" y="165" text-anchor="middle" fill="#ffffff" font-size="20" font-weight="700" font-family="monospace">0.0</text>
            <text x="100" y="182" text-anchor="middle" fill="#94a3b8" font-size="11" font-weight="600">Mbps</text>
          </svg>
        </div>
      </div>

      <!-- Clients breakdown -->
      <div class="qos-clients-panel">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
          <div style="font-weight: 700; color: #f1f5f9; font-size: 13.5px;" data-i18n="qos_active_clients">Active Local Network Clients & Traffic</div>
          <div class="qos-legend">
            <div class="legend-item"><div class="dot-up"></div><span>Upload</span></div>
            <div class="legend-item"><div class="dot-down"></div><span>Download</span></div>
          </div>
        </div>
        <div id="qos-clients-list">
          <div style="color: var(--text-muted); font-size: 13px; text-align: center; padding: 20px;">Loading traffic telemetry...</div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 9: ADVANCED ROUTER CONFIGURATION -->
  <div id="tab-info" class="tab-content">
    <div class="app-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;">
        <div>
          <div class="section-subtitle" style="margin: 0;">Advanced Network & Router Configuration</div>
          <p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">Comprehensive router configuration: WAN, LAN, Wi-Fi AP, Operating Mode, Schedule, and ISP Profile</p>
        </div>
        <button class="btn-primary" style="padding: 9px 22px; font-size: 13.5px;" onclick="saveRouterSettings()">💾 Save & Apply Router Settings</button>
      </div>

      <!-- Router Subtab Navigation -->
      <div class="router-subnav">
        <button class="router-subtab-btn active" id="btn-rsub-wan" onclick="switchRouterSubtab('rsub-wan')" data-i18n="subtab_wan">🌐 WAN / Internet</button>
        <button class="router-subtab-btn" id="btn-rsub-lan" onclick="switchRouterSubtab('rsub-lan')" data-i18n="subtab_lan">🏠 LAN / Local Network</button>
        <button class="router-subtab-btn" id="btn-rsub-wifi" onclick="switchRouterSubtab('rsub-wifi')" data-i18n="subtab_wifi">📶 Wi-Fi Network (AP)</button>
        <button class="router-subtab-btn" id="btn-rsub-guest" onclick="switchRouterSubtab('rsub-guest')" data-i18n="subtab_guest_wifi">📶 Guest Wi-Fi Receiver</button>
        <button class="router-subtab-btn" id="btn-rsub-mode" onclick="switchRouterSubtab('rsub-mode')" data-i18n="subtab_mode">⚙️ Operation Mode</button>
        <button class="router-subtab-btn" id="btn-rsub-schedule" onclick="switchRouterSubtab('rsub-schedule')" data-i18n="subtab_schedule">⏱️ Measurement Schedule</button>
        <button class="router-subtab-btn" id="btn-rsub-isp" onclick="switchRouterSubtab('rsub-isp')" data-i18n="subtab_isp">📋 ISP Subscription</button>
        <button class="router-subtab-btn" id="btn-rsub-kernel" onclick="switchRouterSubtab('rsub-kernel')" data-i18n="subtab_kernel">⚡ Kernel Performance</button>
        <button class="router-subtab-btn" id="btn-rsub-system" onclick="switchRouterSubtab('rsub-system')" data-i18n="subtab_system">🛡️ Firewall & System</button>
      </div>

      <!-- SUBTAB 1: WAN / INTERNET -->
      <div id="rsub-wan" class="router-subtab-content active">
        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;" data-i18n="wan_title">🌐 WAN / Internet Uplink Configuration</div>
          <div class="router-row-2">
            <div class="form-group">
              <label class="form-label" data-i18n="wan_mode">Network Mode:</label>
              <select id="cfg-wan-proto" class="form-input" onchange="onWanProtoChange(this.value)">
                <option value="dhcp" selected>Dynamic IP (DHCP Client - Default)</option>
                <option value="pppoe">PPPoE (Point-to-Point Protocol over Ethernet)</option>
                <option value="static">Static IP (Manual Assignment)</option>
              </select>
              <div class="form-hint">Select the authentication method required by your Internet Service Provider.</div>
            </div>
            <div class="form-group">
              <label class="form-label">WAN Physical Interface:</label>
              <input type="text" id="cfg-wan-iface" value="eth0" class="form-input" readonly style="opacity: 0.8; cursor: not-allowed;">
              <div class="form-hint">Ethernet port connected to upstream modem or ONT.</div>
            </div>
          </div>
        </div>

        <!-- PPPoE Details -->
        <div class="router-section-card" id="wan-pppoe-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;">🔑 PPPoE Credentials & 802.1Q VLAN</div>
          <div class="router-row-3">
            <div class="form-group">
              <label class="form-label" data-i18n="wan_pppoe_user">PPPoE Username:</label>
              <input type="text" id="cfg-pppoe-user" placeholder="pl. ugyfel@szolgaltato" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="wan_pppoe_pass">PPPoE Password:</label>
              <input type="password" id="cfg-pppoe-pass" placeholder="••••••••" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label">Service Name (Optional):</label>
              <input type="text" id="cfg-pppoe-service" placeholder="pl. internet" class="form-input">
            </div>
          </div>
          <div class="router-row-2" style="margin-top: 10px;">
            <div class="form-group">
              <label class="form-label">802.1Q VLAN Tagging (VLAN ID):</label>
              <input type="number" id="cfg-pppoe-vlan" min="0" max="4094" placeholder="0 = nincs VLAN (pl. Telekom GPON: 10, Digi: 100)" class="form-input">
              <div class="form-hint">Fiber (FTTH) connections may require specific 802.1Q VLAN tagging.</div>
            </div>
            <div class="form-group">
              <label class="form-label">MTU Size (Maximum Transmission Unit):</label>
              <input type="number" id="cfg-wan-mtu" value="1492" min="576" max="1500" class="form-input">
              <div class="form-hint">Recommended: 1492 for PPPoE, 1500 for direct DHCP.</div>
            </div>
          </div>
        </div>

        <!-- Static IP Details -->
        <div class="router-section-card" id="wan-static-card" style="display: none;">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;">📌 Static WAN IP Configuration</div>
          <div class="router-row-3">
            <div class="form-group">
              <label class="form-label">Static WAN IP Address:</label>
              <input type="text" id="cfg-wan-ip" placeholder="e.g. 192.168.1.100 or static public IP" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label">WAN Subnet Mask:</label>
              <input type="text" id="cfg-wan-netmask" value="255.255.255.0" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="wan_gateway">Default Gateway:</label>
              <input type="text" id="cfg-wan-gateway" placeholder="pl. 192.168.1.1" class="form-input">
            </div>
          </div>
        </div>

        <!-- WAN MAC Spoofing -->
        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;">🎭 WAN MAC Address Cloning & Spoofing</div>
          <div style="display: flex; gap: 24px; margin-bottom: 14px; flex-wrap: wrap;">
            <div>Active MAC: <code id="mac-current" style="color: #38bdf8; font-weight: 700;">--</code></div>
            <div>Factory Hardware MAC: <code id="mac-factory" style="color: #94a3b8;">--</code></div>
          </div>
          <div class="router-row-2">
            <div class="form-group">
              <label class="form-label">Custom WAN MAC Address:</label>
              <input type="text" id="input-wan-mac" placeholder="pl. 00:11:22:33:44:55" class="form-input">
              <div class="form-hint">If your ISP binds connectivity to your previous router MAC, enter it here.</div>
            </div>
            <div class="form-group" style="display: flex; align-items: flex-end; gap: 10px;">
              <button class="btn-primary" style="padding: 9px 18px;" onclick="applyMacAddress()">💾 Apply MAC</button>
              <button class="btn-secondary" style="padding: 9px 18px;" onclick="resetMacAddress()">🔄 Reset to Factory</button>
            </div>
          </div>
        </div>

        <!-- DNS Configuration & Fallback Testing -->
        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;">🌐 DNS Resolution & Security Fallback</div>
          <div class="router-row-3">
            <div class="form-group">
              <label class="form-label">DNS Assignment Mode:</label>
              <select id="cfg-dns-mode" class="form-input">
                <option value="auto" selected>Automatic (ISP DNS via DHCP)</option>
                <option value="custom">Custom DNS Servers (Manual)</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Primary DNS Server:</label>
              <input type="text" id="cfg-dns-primary" value="1.1.1.1" placeholder="1.1.1.1 (Cloudflare)" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label">Secondary DNS Server:</label>
              <input type="text" id="cfg-dns-secondary" value="8.8.8.8" placeholder="8.8.8.8 (Google)" class="form-input">
            </div>
          </div>
          <div style="margin-top: 14px; background: rgba(15, 23, 42, 0.6); padding: 12px 16px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
            <div>
              <span style="font-weight: 600; color: #cbd5e1; font-size: 13px;">Active DNS Nameservers:</span>
              <span id="dns-active-servers" style="color: #34d399; font-family: monospace; margin-left: 8px;">1.1.1.1, 8.8.8.8, 9.9.9.9</span>
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
              <input type="text" id="dns-test-host" value="google.com" placeholder="Test host..." class="form-input" style="width: 140px; padding: 6px 10px; font-size: 12px;">
              <button class="btn-primary" style="padding: 6px 12px; font-size: 12px;" onclick="testDnsResolution()">🔍 Test DNS</button>
              <button class="btn-secondary" style="padding: 6px 12px; font-size: 12px;" onclick="enforceDnsFallback()">⚡ Enforce Fallback</button>
            </div>
          </div>
        </div>
      </div>

      <!-- SUBTAB 2: LAN / LOCAL NETWORK -->
      <div id="rsub-lan" class="router-subtab-content">
        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;" data-i18n="lan_title">Local Area Network (LAN & DHCP Server)</div>
          <div class="router-row-2">
            <div class="form-group">
              <label class="form-label" data-i18n="lan_ip">Router LAN IP Address:</label>
              <input type="text" id="cfg-lan-ip" value="192.168.100.1" class="form-input">
              <div class="form-hint">NetworkMeasureBox local gateway IP address (when in Router mode).</div>
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="lan_netmask">LAN Subnet Mask:</label>
              <input type="text" id="cfg-lan-netmask" value="255.255.255.0" class="form-input">
              <div class="form-hint">Default: 255.255.255.0 (/24 subnet, 254 usable addresses).</div>
            </div>
          </div>
        </div>

        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;">📡 Internal DHCP Server & Address Pool</div>
          <div class="router-row-3">
            <div class="form-group">
              <label class="form-label" data-i18n="dhcp_enable">Enable Local DHCP Server (dnsmasq):</label>
              <select id="cfg-dhcp-enabled" class="form-input">
                <option value="true" selected>Enabled (Active)</option>
                <option value="false">Disabled (Inactive)</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="dhcp_start">DHCP Range Start:</label>
              <input type="text" id="cfg-dhcp-start" value="192.168.100.100" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="dhcp_end">DHCP Range End:</label>
              <input type="text" id="cfg-dhcp-end" value="192.168.100.200" class="form-input">
            </div>
          </div>
          <div class="router-row-2" style="margin-top: 10px;">
            <div class="form-group">
              <label class="form-label" data-i18n="dhcp_lease">DHCP Lease Time:</label>
              <input type="text" id="cfg-dhcp-lease" value="12h" placeholder="e.g. 12h, 24h, 86400" class="form-input">
              <div class="form-hint">Validity lease duration of IP addresses assigned to client devices.</div>
            </div>
            <div class="form-group">
              <label class="form-label">LAN Physical Interface:</label>
              <input type="text" id="cfg-lan-iface" value="eth1" class="form-input" readonly style="opacity: 0.8; cursor: not-allowed;">
              <div class="form-hint">Ethernet port facing internal clients or switch.</div>
            </div>
          </div>
        </div>
      </div>

      <!-- SUBTAB 3: WI-FI WIRELESS AP (IEEE 802.11 Multi-Band 2.4 - 6 GHz) -->
      <div id="rsub-wifi" class="router-subtab-content">
        <!-- HARDWARE CAPABILITIES & TELEMETRY CARD -->
        <div class="router-section-card" style="border-left: 4px solid #38bdf8;">
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 14px;">
            <div>
              <div style="font-size: 15px; font-weight: 700; color: #ffffff;" data-i18n="wifi_hw_title">Detected Wi-Fi Hardware Capabilities:</div>
              <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">
                Dynamic physical hardware discovery (nl80211 / iw) & real-time telemetry
              </div>
            </div>
            <div id="wifi-hw-badge" class="badge-pill" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);">
              <span>🔍 Detecting capabilities...</span>
            </div>
          </div>

          <!-- Dynamic Capability Badges -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-bottom: 16px;">
            <!-- Bands Box -->
            <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 6px; padding: 12px;">
              <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; margin-bottom: 8px;">
                Supported Frequency Bands (2.4 - 6 GHz)
              </div>
              <div id="wifi-caps-bands" style="display: flex; flex-wrap: wrap; gap: 6px;">
                <span class="badge" style="background: #334155; color: #94a3b8;">2.4 GHz</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">5 GHz</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">6 GHz (Wi-Fi 6E/7)</span>
              </div>
            </div>

            <!-- Standards Box -->
            <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 6px; padding: 12px;">
              <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; margin-bottom: 8px;">
                Supported 802.11 Standards (a/b/g/n/ac/ax/be)
              </div>
              <div id="wifi-caps-standards" style="display: flex; flex-wrap: wrap; gap: 6px;">
                <span class="badge" style="background: #334155; color: #94a3b8;">802.11b</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">802.11g</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">802.11a</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">802.11n (Wi-Fi 4)</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">802.11ac (Wi-Fi 5)</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">802.11ax (Wi-Fi 6/6E)</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">802.11be (Wi-Fi 7)</span>
              </div>
            </div>

            <!-- Widths & Features Box -->
            <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 6px; padding: 12px;">
              <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; margin-bottom: 8px;">
                Channel Width & Security Capabilities
              </div>
              <div id="wifi-caps-features" style="display: flex; flex-wrap: wrap; gap: 6px;">
                <span class="badge" style="background: #334155; color: #94a3b8;">20 MHz</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">40 MHz</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">80 MHz</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">160 MHz</span>
                <span class="badge" style="background: #334155; color: #94a3b8;">320 MHz</span>
              </div>
            </div>
          </div>

          <!-- Realtime telemetry stats -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; background: rgba(15, 23, 42, 0.6); border: 1px solid #1e293b; border-radius: 6px; padding: 10px 14px;">
            <div>
              <div style="font-size: 11px; color: var(--text-muted);">Active Frequency</div>
              <div id="wifi-live-freq" style="font-size: 13px; font-weight: 700; color: #38bdf8; margin-top: 2px;">--</div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted);">Active Channel</div>
              <div id="wifi-live-channel" style="font-size: 13px; font-weight: 700; color: #ffffff; margin-top: 2px;">--</div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted);">Channel Width</div>
              <div id="wifi-live-width" style="font-size: 13px; font-weight: 700; color: #ffffff; margin-top: 2px;">--</div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted);">Transmit Power (Tx)</div>
              <div id="wifi-live-txpower" style="font-size: 13px; font-weight: 700; color: #10b981; margin-top: 2px;">--</div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted);">Connected Clients</div>
              <div id="wifi-live-clients" style="font-size: 13px; font-weight: 700; color: #f59e0b; margin-top: 2px;">0 clients</div>
            </div>
          </div>
        </div>

        <!-- CONFIGURATION CARD -->
        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;" data-i18n="wifi_title">Wi-Fi Management & Multi-Band AP (IEEE 802.11 2.4 - 6 GHz)</div>

          <div class="router-row-3">
            <div class="form-group">
              <label class="form-label" data-i18n="wifi_enable">Enable Wi-Fi Access Point (hostapd):</label>
              <select id="cfg-wifi-enabled" class="form-input">
                <option value="true" selected>Enabled (Active Broadcast)</option>
                <option value="false">Disabled (Radio Off)</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="wifi_ssid">Network Name (SSID):</label>
              <input type="text" id="cfg-wifi-ssid" value="NMB-Diagnostic" placeholder="e.g. NetworkMeasureBox-WiFi" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label">Regulatory Domain (Country):</label>
              <select id="cfg-wifi-country" class="form-input">
                <option value="HU" selected>HU - Hungary (ETSI / EU)</option>
                <option value="DE">DE - Germany (ETSI / EU)</option>
                <option value="FR">FR - France (ETSI / EU)</option>
                <option value="GB">GB - United Kingdom</option>
                <option value="US">US - United States (FCC)</option>
                <option value="00">00 - World Wide Default</option>
              </select>
            </div>
          </div>

          <div class="router-row-3" style="margin-top: 12px;">
            <div class="form-group">
              <label class="form-label" data-i18n="wifi_band">Frequency Band:</label>
              <select id="cfg-wifi-band" class="form-input" onchange="onWifiBandChange()">
                <option value="auto" selected>Auto (Optimal frequency band)</option>
                <option value="2.4ghz">2.4 GHz (Long range & wall penetration)</option>
                <option value="5ghz">5 GHz (High speed & clean spectrum)</option>
                <option value="6ghz">6 GHz (Wi-Fi 6E & 7 Ultra-low latency)</option>
              </select>
              <div class="form-hint" id="cfg-wifi-band-hint">Availability depends on attached Wi-Fi hardware controller.</div>
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="wifi_standard">Wireless Standard:</label>
              <select id="cfg-wifi-standard" class="form-input" onchange="onWifiStandardChange()">
                <option value="auto" selected>Auto (Highest supported standard)</option>
                <option value="be">IEEE 802.11be (Wi-Fi 7 - EHT)</option>
                <option value="ax">IEEE 802.11ax (Wi-Fi 6 & 6E - HE)</option>
                <option value="ac">IEEE 802.11ac (Wi-Fi 5 - VHT)</option>
                <option value="n">IEEE 802.11n (Wi-Fi 4 - HT)</option>
                <option value="g">IEEE 802.11g (2.4 GHz Legacy OFDM)</option>
                <option value="a">IEEE 802.11a (5 GHz Legacy OFDM)</option>
                <option value="b">IEEE 802.11b (2.4 GHz Legacy DSSS)</option>
              </select>
              <div class="form-hint" id="cfg-wifi-std-hint">Maximum standard supported by hardware.</div>
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="wifi_width">Channel Bandwidth:</label>
              <select id="cfg-wifi-channel-width" class="form-input">
                <option value="auto" selected>Auto (Hardware-matched maximum width)</option>
                <option value="20">20 MHz (Standard width, highest stability)</option>
                <option value="40">40 MHz (HT40 / VHT40)</option>
                <option value="80">80 MHz (VHT80 / HE80 / EHT80)</option>
                <option value="160">160 MHz (HE160 / EHT160 - High Throughput)</option>
                <option value="320">320 MHz (EHT320 - Wi-Fi 7 Ultra-Wide)</option>
              </select>
            </div>
          </div>

          <div class="router-row-3" style="margin-top: 12px;">
            <div class="form-group">
              <label class="form-label" data-i18n="wifi_channel">Wi-Fi Channel:</label>
              <select id="cfg-wifi-channel" class="form-input">
                <option value="0" selected>Auto (Automatic clean channel selection / ACS)</option>
              </select>
              <div class="form-hint" id="cfg-wifi-channel-hint">Channel list adjusts dynamically based on selected band.</div>
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="wifi_security">Security Protocol:</label>
              <select id="cfg-wifi-security" class="form-input" onchange="onWifiSecurityChange()">
                <option value="wpa2" selected>WPA2-Personal (AES) - Broad Compatibility</option>
                <option value="wpa3">WPA3-Personal (SAE) - Modern & Secure</option>
                <option value="mixed">WPA2/WPA3 Mixed (Transition Mode)</option>
              </select>
              <div class="form-hint" id="cfg-wifi-sec-hint">WPA3-SAE is mandatory for the 6 GHz band under IEEE 802.11ax/be.</div>
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="wifi_pass">Password (WPA Passphrase):</label>
              <input type="password" id="cfg-wifi-psk" value="NetworkMeasureBox123" placeholder="Minimum 8 characters..." class="form-input">
              <div class="form-hint">Password required for client diagnostic devices to connect.</div>
            </div>
          </div>

          <div id="wifi-6ghz-notice" style="display: none; margin-top: 14px; background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 6px; padding: 12px; font-size: 12.5px; color: #bae6fd;">
            ℹ️ <b>IEEE 802.11 6 GHz Operating Mandate:</b> 6 GHz operations (Wi-Fi 6E / Wi-Fi 7) strictly mandate WPA3-Personal (SAE) and Protected Management Frames (PMF - IEEE 802.11w). The system enforces these security layers automatically.
          </div>
        </div>
      </div>

      <!-- SUBTAB: GUEST WI-FI CLIENT PROBE -->
      <div id="rsub-guest" class="router-subtab-content">
        <!-- 1. Hero Overview Card -->
        <div class="router-section-card">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px; margin-bottom: 12px;">
            <div>
              <div style="font-size: 15px; font-weight: 700; color: #ffffff; display: flex; align-items: center; gap: 8px;">
                <span>📶</span> <span data-i18n="guest_wifi_title">Dedicated Guest Wi-Fi Client Probe (Standalone Mode)</span>
              </div>
              <p style="font-size: 12.5px; color: var(--text-muted); margin-top: 4px; line-height: 1.5;" data-i18n="guest_wifi_desc">
                Dual-homed operation: The box stays wired (eth0) to primary LAN, while the Wi-Fi station (wlan0) connects directly to the router's isolated Guest Wi-Fi. This overcomes AP client isolation to discover guest devices (Network Explorer) and sniff packets (Sniffer) simultaneously.
              </p>
            </div>
            <span id="guest-wifi-badge-pill" class="badge-pill" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569; font-size: 12px; padding: 5px 12px;">
              ⚪ Not Connected
            </span>
          </div>

          <!-- Network Isolation & Telemetry Banner -->
          <div id="guest-wifi-isolation-box" style="background: rgba(168, 85, 247, 0.1); border: 1px solid rgba(168, 85, 247, 0.35); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px;">
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
              <div style="display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 18px;">🛡️</span>
                <span id="guest-wifi-isolation-text" style="font-size: 12.5px; color: #e9d5ff; font-weight: 500;">
                  Evaluating guest subnet isolation...
                </span>
              </div>
              <span style="font-size: 11.5px; color: #c084fc; background: rgba(168, 85, 247, 0.2); padding: 3px 8px; border-radius: 4px;">
                Routing Metric: <b id="guest-wifi-stat-metric">600</b> (Wired eth0 retains default route)
              </span>
            </div>
          </div>

          <!-- Live Client Status Grid -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(51, 65, 85, 0.6); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
            <div>
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Connected SSID:</div>
              <div id="guest-wifi-stat-ssid" style="font-size: 13.5px; font-weight: 700; color: #38bdf8; margin-top: 2px;">--</div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Assigned IP & Netmask:</div>
              <div id="guest-wifi-stat-ip" style="font-size: 13.5px; font-weight: 700; color: #34d399; font-family: monospace; margin-top: 2px;">--</div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Guest Gateway:</div>
              <div id="guest-wifi-stat-gw" style="font-size: 13px; font-family: monospace; color: #f1f5f9; margin-top: 2px;">--</div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Wi-Fi Signal (RSSI):</div>
              <div style="display: flex; align-items: center; gap: 8px; margin-top: 4px;">
                <div style="width: 80px; height: 8px; background: #334155; border-radius: 4px; overflow: hidden;">
                  <div id="guest-wifi-stat-sigbar" style="width: 0%; height: 100%; background: #10b981; transition: width 0.3s;"></div>
                </div>
                <span id="guest-wifi-stat-sig" style="font-size: 12.5px; font-weight: 700; color: #f1f5f9;">0%</span>
              </div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Channel & Security:</div>
              <div id="guest-wifi-stat-sec" style="font-size: 12.5px; color: #cbd5e1; margin-top: 2px;">--</div>
            </div>
            <div>
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Client MAC Address:</div>
              <div id="guest-wifi-stat-mac" style="font-size: 12px; font-family: monospace; color: #94a3b8; margin-top: 2px;">--</div>
            </div>
          </div>
        </div>

        <!-- 2. Wi-Fi Scanner & Available Networks Picker -->
        <div class="router-section-card" style="margin-top: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px;">
            <div>
              <div style="font-size: 14px; font-weight: 700; color: #ffffff;">🔍 Scan Available Wi-Fi Networks (Scanner)</div>
              <p style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">
                Scan and pick your router's guest Wi-Fi SSID for immediate connection.
              </p>
            </div>
            <button id="btn-scan-guest-wifi" class="btn-primary" style="font-size: 12px; padding: 7px 16px;" onclick="scanGuestWifiNetworks()">
              🔍 Scan Wi-Fi Networks Now
            </button>
          </div>

          <div id="guest-wifi-scan-table-wrap" style="display: none; margin-top: 10px;" class="data-table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>SSID</th>
                  <th>Signal</th>
                  <th>Channel</th>
                  <th>Security</th>
                  <th>BSSID (MAC)</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody id="guest-wifi-scan-tbody">
                <tr><td colspan="7" style="text-align: center; color: var(--text-muted);">Click "Scan Wi-Fi Networks Now" to search for nearby APs...</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 3. Configuration & Connect Card -->
        <div class="router-section-card" style="margin-top: 14px;">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;">⚙️ Guest Wi-Fi Connection Settings</div>
          <div class="router-row-3">
            <div class="form-group">
              <label class="form-label">Guest Wi-Fi Client State:</label>
              <select id="cfg-guest-wifi-enabled" class="form-input">
                <option value="true">🟢 Enabled (Guest Wi-Fi Active)</option>
                <option value="false" selected>🔴 Disabled</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Wi-Fi Interface:</label>
              <input type="text" id="cfg-guest-wifi-iface" value="wlan0" class="form-input" readonly style="background: rgba(15, 23, 42, 0.4); color: #94a3b8;">
            </div>
            <div class="form-group">
              <label class="form-label">Route Metric:</label>
              <input type="number" id="cfg-guest-wifi-metric" value="600" class="form-input">
              <div class="form-hint">Higher metric (e.g. 600) ensures primary speedtest and internet benchmarks stay on wired eth0.</div>
            </div>
          </div>

          <div class="router-row-3" style="margin-top: 12px;">
            <div class="form-group">
              <label class="form-label">Guest Wi-Fi SSID:</label>
              <input type="text" id="cfg-guest-wifi-ssid" placeholder="e.g. Router_Guest or pick from table above" class="form-input">
              <div class="form-hint">Exact SSID broadcast by your upstream router guest network.</div>
            </div>
            <div class="form-group">
              <label class="form-label">Guest Wi-Fi Passphrase:</label>
              <input type="password" id="cfg-guest-wifi-pass" placeholder="Leave empty if open network..." class="form-input">
              <div class="form-hint">Leave empty if guest network has no password (Open).</div>
            </div>
            <div class="form-group">
              <label class="form-label">Automatic Reconnection:</label>
              <select id="cfg-guest-wifi-autorecon" class="form-input">
                <option value="true" selected>Yes (Reconnect on boot and link drops)</option>
                <option value="false">No (Manual only)</option>
              </select>
            </div>
          </div>

          <div style="display: flex; gap: 12px; margin-top: 18px; flex-wrap: wrap;">
            <button class="btn-primary" style="padding: 9px 20px;" onclick="connectGuestWifi()">
              ⚡ Save & Connect Now
            </button>
            <button class="btn-secondary" style="border: 1px solid #ef4444; color: #f87171; padding: 9px 18px;" onclick="disconnectGuestWifi()">
              🔌 Disconnect
            </button>
          </div>
        </div>
      </div>

      <!-- SUBTAB 4: OPERATING MODE -->
      <div id="rsub-mode" class="router-subtab-content">
        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;" data-i18n="mode_title">Device Operating Mode</div>
          <p style="font-size: 12.5px; color: var(--text-muted); margin-bottom: 16px;">
            Switch device role between Gateway Router, Transparent Bridge, AP, or Standalone Probe.
          </p>

          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px;">
            <!-- Mode A Card -->
            <label id="card-mode-a" style="cursor: pointer; background: #0f172a; border: 2px solid #334155; border-radius: 8px; padding: 18px; display: block; transition: all 0.2s;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 700; font-size: 14px; color: #38bdf8;" data-i18n="mode_router">Gateway Router (NAT & DHCP Server)</span>
                <input type="radio" name="net_mode_radio" value="mode_a" id="radio-mode-a">
              </div>
              <p style="font-size: 12px; color: #cbd5e1; line-height: 1.5; margin: 0;">
                Device operates as standalone gateway router and firewall. Connects to internet via WAN (PPPoE or DHCP) and provides NAT routing for LAN (eth1) and Wi-Fi clients.
              </p>
            </label>

            <!-- Mode B Card -->
            <label id="card-mode-b" style="cursor: pointer; background: #0f172a; border: 2px solid #334155; border-radius: 8px; padding: 18px; display: block; transition: all 0.2s;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 700; font-size: 14px; color: #fbbf24;" data-i18n="mode_bridge">Transparent Bridge / Inline Probe</span>
                <input type="radio" name="net_mode_radio" value="mode_b" id="radio-mode-b">
              </div>
              <p style="font-size: 12px; color: #cbd5e1; line-height: 1.5; margin: 0;">
                Device is placed inline between modem/ONT and router in transparent bridge (br0) mode. Non-intrusively monitors transit packets and latency without double-NAT.
              </p>
            </label>

            <!-- Standalone Card -->
            <label id="card-mode-standalone" style="cursor: pointer; background: #0f172a; border: 2px solid #0284c7; border-radius: 8px; padding: 18px; display: block; transition: all 0.2s;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 700; font-size: 14px; color: #34d399;" data-i18n="mode_client">Standalone Telemetry Client</span>
                <input type="radio" name="net_mode_radio" value="standalone" id="radio-mode-standalone" checked>
              </div>
              <p style="font-size: 12px; color: #cbd5e1; line-height: 1.5; margin: 0;">
                Connects with a single Ethernet cable to local router/switch as standard client, executing periodic ping, speed, and port throttling benchmarks.
              </p>
            </label>
          </div>
        </div>
      </div>

      <!-- SUBTAB 5: MEASUREMENT SCHEDULE -->
      <div id="rsub-schedule" class="router-subtab-content">
        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;" data-i18n="sched_title">Automated Benchmark Schedule & Precision Gate</div>
          <div class="router-row-3">
            <div class="form-group">
              <label class="form-label">Measurement Mode:</label>
              <select id="cfg-sched-mode" class="form-input">
                <option value="scheduled" selected>🟢 Automated Schedule (Active)</option>
                <option value="manual">🔴 Manual Testing (Timer Disabled)</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Schedule Cron / Frequency:</label>
              <select id="cfg-sched-cron" class="form-input" onchange="onCfgSchedCronChange(this.value)">
                <option value="*/5 * * * *">⚡ Every 5 minutes (Ultra frequent - strict &lt;2% gate)</option>
                <option value="*/10 * * * *">⚡ Every 10 minutes (Frequent)</option>
                <option value="*/15 * * * *">⏱️ Every 15 minutes</option>
                <option value="*/30 * * * *">⏱️ Every 30 minutes</option>
                <option value="0 * * * *">🕐 Every 1 hour</option>
                <option value="0 */2 * * *">🕑 Every 2 hours</option>
                <option value="0 */4 * * *">🕓 Every 4 hours</option>
                <option value="0 */6 * * *" selected>🕕 Every 6 hours (Recommended)</option>
                <option value="0 */12 * * *">🕛 Every 12 hours</option>
                <option value="0 3 * * *">🌙 Every 24 hours (Nightly at 03:00)</option>
                <option value="custom">✏️ Custom interval (Minutes or Cron expression)...</option>
              </select>
              <div id="cfg-sched-custom-cron-wrap" style="display: none; margin-top: 6px;">
                <input type="text" id="cfg-sched-custom-cron-input" placeholder="e.g. 15 (minutes) or */8 * * * * (cron)" class="form-input">
              </div>
            </div>
            <div class="form-group">
              <label class="form-label">Default Benchmark Engine:</label>
              <select id="cfg-sched-engine" class="form-input">
                <option value="ookla" selected>⚡ Ookla Speedtest CLI</option>
                <option value="cloudflare">☁️ Cloudflare Edge (speed.cloudflare.com)</option>
                <option value="rtr">🇦🇹 RTR-NetTest (netztest.at / Open-RMBT)</option>
                <option value="all">🏆 All 3 engines sequentially (Combined)</option>
              </select>
            </div>
          </div>
          <div class="router-row-2" style="margin-top: 10px;">
            <div class="form-group">
              <label class="form-label">Designated Server ID for Automated Runs:</label>
              <input type="text" id="cfg-sched-server-id" placeholder="e.g. 31717 (2Connect Budapest) or blank = auto" class="form-input">
              <div class="form-hint">When configured, automated background runs strictly target this server.</div>
            </div>
            <div class="form-group">
              <label class="form-label">Traffic Gate Accuracy Gate:</label>
              <select id="cfg-sched-gate-mode" class="form-input" onchange="onCfgGateModeChange(this.value)">
                <option value="percent" selected>🟢 Strict &lt; 2% Dynamic Idle Gate</option>
                <option value="fixed">Fixed threshold (kbps)</option>
              </select>
            </div>
          </div>
          <div class="router-row-2" style="margin-top: 10px;">
            <div class="form-group" id="cfg-gate-percent-wrap">
              <label class="form-label">Maximum Allowed Network Usage (%):</label>
              <input type="number" id="cfg-sched-gate-percent" value="2.0" step="0.5" min="0.5" max="10.0" class="form-input">
              <div class="form-hint">Tests only execute when current network traffic is below this percentage of contracted speed.</div>
            </div>
            <div class="form-group" id="cfg-gate-fixed-wrap" style="display: none;">
              <label class="form-label">Fixed Limit (kbps):</label>
              <input type="number" id="cfg-sched-idle-kbps" value="500" class="form-input">
              <div class="form-hint">If background traffic exceeds this speed (kbps), measurement is postponed.</div>
            </div>
          </div>
        </div>
      </div>

      <!-- SUBTAB 6: ISP SUBSCRIPTION PROFILE -->
      <div id="rsub-isp" class="router-subtab-content">
        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;" data-i18n="isp_title">ISP Subscription Profile & SLA Thresholds</div>
          <div class="router-row-3">
            <div class="form-group">
              <label class="form-label" data-i18n="isp_name">Provider Name (ISP):</label>
              <input type="text" id="cfg-isp-name" placeholder="e.g. Magyar Telekom, Vodafone, AT&T, Comcast, Local ISP" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="isp_type">Connection Type:</label>
              <select id="cfg-conn-type" class="form-input">
                <option value="fiber" selected>Fiber Optics (Fiber / FTTH / GPON)</option>
                <option value="docsis">Cable TV / DOCSIS / Coaxial</option>
                <option value="xdsl">xDSL (VDSL2 / ADSL2+)</option>
                <option value="fwa">Cellular / 4G / 5G / Fixed Wireless (FWA)</option>
                <option value="dialup">Telefonos modem / Dial-Up</option>
                <option value="satellite">Satellite (Starlink / Sat)</option>
                <option value="ethernet">Dedicated Leased Line / Ethernet</option>
                <option value="other">Other Network Type</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="isp_circuit">Circuit / Contract ID:</label>
              <input type="text" id="cfg-account-id" placeholder="e.g. CKT-2026-FIBER-01" class="form-input">
            </div>
          </div>
          <div class="router-row-2" style="margin-top: 10px;">
            <div class="form-group">
              <label class="form-label" data-i18n="isp_down_offered">Advertised Download Speed (Mbps):</label>
              <input type="number" id="cfg-contract-down" value="1000" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="isp_down_guaranteed">Guaranteed Download Speed (Mbps):</label>
              <input type="number" id="cfg-guaranteed-down" value="300" class="form-input">
            </div>
          </div>
          <div class="router-row-2" style="margin-top: 10px;">
            <div class="form-group">
              <label class="form-label" data-i18n="isp_up_offered">Advertised Upload Speed (Mbps):</label>
              <input type="number" id="cfg-contract-up" value="300" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="isp_up_guaranteed">Guaranteed Upload Speed (Mbps):</label>
              <input type="number" id="cfg-guaranteed-up" value="75" class="form-input">
            </div>
          </div>
        </div>

        <!-- Live SLA & Contracted Speed Audit Card -->
        <div class="router-section-card" style="margin-top: 14px;">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;" data-i18n="sla_audit_title">Live SLA & Contract Speed Audit</div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px;">
            <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);">
              <div style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;" data-i18n="sla_last_down">Last Download SLA:</div>
              <div id="sla-last-down-pct" style="font-size: 20px; font-weight: 700; color: #38bdf8; margin: 6px 0;">-- %</div>
              <div id="sla-last-down-detail" style="font-size: 12px; color: #cbd5e1;">-- Mbps of offered -- Mbps</div>
            </div>
            <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);">
              <div style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;" data-i18n="sla_last_up">Last Upload SLA:</div>
              <div id="sla-last-up-pct" style="font-size: 20px; font-weight: 700; color: #a78bfa; margin: 6px 0;">-- %</div>
              <div id="sla-last-up-detail" style="font-size: 12px; color: #cbd5e1;">-- Mbps of offered -- Mbps</div>
            </div>
            <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);">
              <div style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;" data-i18n="sla_avg_down">24h Average Download:</div>
              <div id="sla-avg-down-pct" style="font-size: 20px; font-weight: 700; color: #34d399; margin: 6px 0;">-- %</div>
              <div id="sla-avg-down-detail" style="font-size: 12px; color: #cbd5e1;">24h Average: -- Mbps</div>
            </div>
            <div style="background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);">
              <div style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;" data-i18n="sla_avg_up">24h Average Upload:</div>
              <div id="sla-avg-up-pct" style="font-size: 20px; font-weight: 700; color: #34d399; margin: 6px 0;">-- %</div>
              <div id="sla-avg-up-detail" style="font-size: 12px; color: #cbd5e1;">24h Average: -- Mbps</div>
            </div>
          </div>
        </div>
      </div>

      <!-- SUBTAB 7: FIREWALL, QOS & SYSTEM -->
      <!-- SUBTAB 8: KERNEL & HARDWARE PERFORMANCE -->
      <div id="rsub-kernel" class="router-subtab-content">
        <!-- Kernel Acceleration Summary Card -->
        <div class="router-section-card">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
            <div>
              <div style="font-size: 14px; font-weight: 700; color: #ffffff;" data-i18n="kernel_title">
                ⚡ Linux Kernel Network Stack & Hardware Offload Acceleration
              </div>
              <p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;" data-i18n="kernel_desc">
                Kernel-level tuning: Multi-core RPS packet steering, BBR pacing, 64MB buffers, and microsecond socket timestamping.
              </p>
            </div>
            <button id="btn-apply-kernel-tuning" class="btn-primary" style="padding: 7px 16px; font-size: 12px;" onclick="applyKernelTuning()" data-i18n="kernel_btn_apply">
              🚀 Optimize Kernel Network Stack Now
            </button>
          </div>

          <!-- Real-Time Kernel Indicators Grid -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 14px;">
            <div style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #1e293b;">
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">TCP Congestion Control</div>
              <div id="kernel-tcp-cc" style="font-size: 20px; font-weight: 800; color: #38bdf8; font-family: monospace; margin-top: 4px;">BBR (FQ Paced)</div>
              <div style="font-size: 11px; color: #10b981; margin-top: 4px;">🟢 Active & Enforced</div>
            </div>
            <div style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #1e293b;">
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Packet Steering (RPS/RFS)</div>
              <div id="kernel-rps-status" style="font-size: 20px; font-weight: 800; color: #10b981; font-family: monospace; margin-top: 4px;">All CPU Cores</div>
              <div style="font-size: 11px; color: #10b981; margin-top: 4px;">🟢 Parallel SoftIRQ Enabled</div>
            </div>
            <div style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #1e293b;">
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Hardware/Kernel Timestamps</div>
              <div id="kernel-ts-status" style="font-size: 20px; font-weight: 800; color: #a855f7; font-family: monospace; margin-top: 4px;">SO_TIMESTAMPNS</div>
              <div style="font-size: 11px; color: #10b981; margin-top: 4px;">🟢 Sub-µs Precision Active</div>
            </div>
            <div style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #1e293b;">
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Max Socket Memory (rmem/wmem)</div>
              <div id="kernel-mem-status" style="font-size: 20px; font-weight: 800; color: #fbbf24; font-family: monospace; margin-top: 4px;">64.0 MB</div>
              <div style="font-size: 11px; color: #10b981; margin-top: 4px;">🟢 10G Multi-Gigabit Ready</div>
            </div>
            <div style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #1e293b;">
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Kernel Socket Busy-Polling</div>
              <div id="kernel-busy-status" style="font-size: 20px; font-weight: 800; color: #34d399; font-family: monospace; margin-top: 4px;">50 µs</div>
              <div style="font-size: 11px; color: #10b981; margin-top: 4px;">🟢 Zero Context-Switch Ping</div>
            </div>
            <div style="background: #0f172a; padding: 14px; border-radius: 6px; border: 1px solid #1e293b;">
              <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Kernel Release</div>
              <div id="kernel-version-text" style="font-size: 16px; font-weight: 800; color: #e2e8f0; font-family: monospace; margin-top: 4px;">Linux 6.x</div>
              <div style="font-size: 11px; color: #94a3b8; margin-top: 4px;">Debian SMP PREEMPT</div>
            </div>
          </div>
        </div>

        <!-- Network Interface Multi-Queue & Offload Table -->
        <div class="router-section-card">
          <div style="font-size: 13.5px; font-weight: 700; color: #ffffff; margin-bottom: 12px;">
            🔀 Network Interface Multi-Queue, RPS & Hardware Offloads
          </div>
          <div style="overflow-x: auto;">
            <table class="data-table" style="width: 100%; font-size: 12.5px;">
              <thead>
                <tr>
                  <th>Interface</th>
                  <th>Speed</th>
                  <th>MTU</th>
                  <th>Multi-Core RPS</th>
                  <th>Flow Steering (RFS)</th>
                  <th>XPS Steering</th>
                  <th>Hardware Offloads</th>
                </tr>
              </thead>
              <tbody id="kernel-iface-tbody">
                <tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 16px;">Loading kernel interface telemetry...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- SUBTAB 9: SYSTEM & FIREWALL -->
      <div id="rsub-system" class="router-subtab-content">
        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;" data-i18n="fw_title">NAT Routing & Firewall Security</div>
          <div class="router-row-2">
            <div class="form-group">
              <label class="form-label">Smart Queue Management (SQM) / Bufferbloat Control:</label>
              <select id="cfg-sqm-algo" class="form-input">
                <option value="cake" selected>CAKE (Common Applications Kept Enhanced) - Recommended</option>
                <option value="fq_codel">fq_codel (Fair Queueing with CoDel)</option>
                <option value="disabled">Kikapcsolva</option>
              </select>
              <div class="form-hint">Mitigates latency spikes and bufferbloat under heavy bandwidth saturation.</div>
            </div>
          </div>
        </div>

        <!-- Custom Admin Credentials Card -->
        <div class="router-section-card">
          <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 14px;" data-i18n="sys_creds_title">Web Management Administrative Credentials</div>
          <div class="router-row-2">
            <div class="form-group">
              <label class="form-label" data-i18n="sys_username">Admin Username:</label>
              <input type="text" id="cfg-admin-user" value="admin" placeholder="e.g. admin or custom username..." class="form-input">
              <div class="form-hint">You may customize administrative username to any unique identifier.</div>
            </div>
            <div class="form-group">
              <label class="form-label" data-i18n="sys_pass">New Password:</label>
              <input type="password" id="cfg-admin-pass" placeholder="Enter new password (leave empty to keep unchanged)..." class="form-input">
              <div class="form-hint">Password required to authenticate to this web management dashboard.</div>
            </div>
          </div>
          <div style="margin-top: 12px;">
            <button class="btn-primary" style="padding: 7px 18px; font-size: 12.5px;" onclick="updateAdminCredentials()">
              Update Credentials
            </button>
          </div>
        </div>

        <!-- Distro Package Updates Card -->
        <div class="router-section-card">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 10px;">
            <div style="font-size: 14px; font-weight: 700; color: #ffffff;" data-i18n="sys_upg_title">Operating System Package Updates</div>
            <span id="os-distro-badge" class="badge-pill" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid #0284c7;">
              OS: Detecting...
            </span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;">
            Distro-aware package updates via native package manager (APT, DNF, Pacman, APK, Zypper).
          </p>
          <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px;">
            <button id="btn-check-updates" class="btn-secondary" style="padding: 7px 16px; font-size: 12.5px;" onclick="checkSystemUpdates()">
              🔍 Check for Updates
            </button>
            <button id="btn-run-upgrade" class="btn-primary" style="padding: 7px 16px; font-size: 12.5px;" onclick="runSystemUpgrade()">
              🚀 Upgrade System Packages Now
            </button>
            <span id="update-status-text" style="font-size: 12px; color: var(--text-muted);"></span>
          </div>
          <pre id="upgrade-terminal-box" class="terminal-box" style="max-height: 140px; font-size: 11.5px;">Package manager ready.</pre>

          <div style="margin-top: 20px; border-top: 1px solid #1e293b; padding-top: 16px; display: flex; gap: 12px; flex-wrap: wrap;">
            <button class="btn-secondary" style="padding: 9px 18px;" onclick="reloadDaemons()">🔄 Reload Services</button>
            <button class="btn-danger" style="padding: 9px 18px;" onclick="rebootBox()" data-i18n="sys_btn_reboot">⚠️ Reboot Device</button>
          </div>
        </div>
      </div>

      <!-- Bottom Sticky Save Bar -->
      <div style="margin-top: 24px; display: flex; justify-content: flex-end; gap: 12px;">
        <button class="btn-primary" style="padding: 10px 28px; font-size: 14px;" onclick="saveRouterSettings()">
          💾 Save All Router Settings
        </button>
      </div>
    </div>
  </div>

  <!-- TAB: AI DIAGNOSTICS (LLM BUNDLE) -->
  <div id="tab-llm" class="tab-content">
    <div class="app-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
        <div>
          <div class="section-subtitle" style="margin: 0;" data-i18n="ai_diag_title">🤖 AI Diagnostics & Diagnostic Report (LLM Snapshot)</div>
          <p style="font-size: 12.5px; color: var(--text-muted); margin-top: 4px;" data-i18n="ai_diag_desc">
            Comprehensive system, interface, routing, DNS, ping, QoS, and telemetry snapshot formatted in sanitized Markdown for ChatGPT, Claude, or Gemini deep analysis.
          </p>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn-primary" style="font-size: 12.5px; padding: 7px 16px;" onclick="copyLlmBundle()">
            📋 Copy Full Report
          </button>
          <button class="btn-secondary" style="font-size: 12.5px; padding: 7px 16px;" onclick="downloadLlmBundle()">
            💾 Download .md File
          </button>
          <button class="btn-secondary" style="font-size: 12.5px; padding: 7px 12px;" onclick="loadLlmBundle()">
            🔄 Refresh
          </button>
        </div>
      </div>

      <div style="position: relative;">
        <pre id="llm-bundle-preview" class="terminal-box" style="max-height: 540px; font-size: 12px; line-height: 1.5; white-space: pre-wrap; font-family: monospace;">Loading...</pre>
      </div>
    </div>
  </div>

</div>

<!-- Toast notification box -->
<div id="toast-msg"></div>

<script>
  let serverList = [];
  let snifferActive = false;
  let gaugeScaleMax = 100;
  let selectedEngine = 'ookla';
  let userManuallySelectedEngine = false;
  let searchDebounceTimer = null;
  let currentTranslations = {};
  let currentLang = 'en';

  async function loadTranslations(lang) {
    try {
      const res = await fetch('/api/i18n?lang=' + (lang || currentLang));
      if (res.ok) {
        const d = await res.json();
        currentTranslations = d.translations || {};
        currentLang = d.lang || 'en';
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
  }

  async function switchLanguage(lang) {
    currentLang = lang;
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

  function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.app-tab-btn').forEach(el => el.classList.remove('active'));
    const t = document.getElementById(tabId);
    if (t) t.classList.add('active');
    const b = Array.from(document.querySelectorAll('.app-tab-btn')).find(el => (el.getAttribute('onclick') || '').includes(tabId));
    if (b) b.classList.add('active');

    if (tabId === 'tab-script' && serverList.length === 0) {
      loadServers();
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
      loadGuestWifiStatus();
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
        latest = window.allRecentSpeedtests.find(s => (s.engine || '').toLowerCase() === targetEng) || null;
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
      if (elBufferbloat) elBufferbloat.innerText = latest.bufferbloat_grade ? `${latest.bufferbloat_grade} (+${latest.bufferbloat_delta_ms || 0} ms)` : (latest.jitter_us ? `Jitter: ${(latest.jitter_us/1000.0).toFixed(2)} ms` : 'A+');

      let srvNameSafe = escapeHtml(latest.server_name || latest.server_host || '--');
      let srvDisplay = srvNameSafe;
      if (latest.result_url) {
        let safeUrl = sanitizeUrl(latest.result_url);
        if (safeUrl) {
          srvDisplay += ` — <a href="${safeUrl}" target="_blank" rel="noopener noreferrer" style="color:#38bdf8; text-decoration:none;">🔗 ${t('open_result_link', 'Open Result Link')}</a>`;
        }
      }
      if (elServerLink) elServerLink.innerHTML = srvDisplay;
    } else {
      const fallbackIp = escapeHtml((data.system_info && (data.system_info.public_ipv4 || data.system_info.wan_ip)) || data.public_ip || '--');
      if (elPublicIp) elPublicIp.innerText = fallbackIp;
      if (elEngine) elEngine.innerHTML = `<span class="badge badge-ok">${targetEng.toUpperCase()}</span>`;
      if (elTimestamp) elTimestamp.innerHTML = `<span style="color:#94a3b8;">-- (${t('no_test_recorded', 'No measurement recorded yet with this engine')})</span>`;
      if (elDownload) elDownload.innerHTML = `<span style="color:#94a3b8;">-- Mbps</span>`;
      if (elUpload) elUpload.innerHTML = `<span style="color:#94a3b8;">-- Mbps</span>`;
      if (elLatency) elLatency.innerHTML = `<span style="color:#94a3b8;">-- ms</span>`;
      if (elBufferbloat) elBufferbloat.innerHTML = `<span style="color:#94a3b8;">--</span>`;
      if (elServerLink) elServerLink.innerHTML = `<span style="color:#38bdf8; font-weight:600;">⚡ ${t('ready_to_benchmark', 'Ready to benchmark — Click \"Run Speedtest Now\"')}</span>`;
    }

    if (elScriptBox) {
      if (targetEng === 'cloudflare') {
        elScriptBox.textContent = `#!/bin/sh\n# ==============================================================================\n# NetworkMeasureBox - Realtime Cloudflare Edge Speedtest Execution\n# Measurement Engine: Cloudflare Edge (speed.cloudflare.com)\n# ==============================================================================\n\n# Direct CDN edge transfer benchmark with HTTP/HTTPS payload:\ncurl -s -X GET "https://speed.cloudflare.com/__down?bytes=25000000" -o /dev/null\ncurl -s -X POST "https://speed.cloudflare.com/__up" --data-binary @chunk_10mb.bin -o /dev/null\n`;
      } else if (targetEng === 'rtr') {
        elScriptBox.textContent = `#!/bin/sh\n# ==============================================================================\n# NetworkMeasureBox - Realtime RTR-NetTest Execution\n# Measurement Engine: RTR-NetTest (netztest.at / Open-RMBT, BEREC Standard)\n# ==============================================================================\n\n# Open European standard WebSocket speed measurement against Vienna 100G cluster:\npython3 -m nmb.speed.rtr --json\n`;
      } else if (targetEng === 'iperf3') {
        const ipHost = (data && data.iperf_target_host) || 'speedtest.init7.net';
        const ipPort = (data && data.iperf_port) || 5203;
        elScriptBox.textContent = `#!/bin/sh\n# ==============================================================================\n# NetworkMeasureBox - Realtime iPerf3 Bandwidth & Jitter Probing\n# Measurement Engine: iPerf3 (RFC 2544 / RFC 6349 TCP & UDP Probing)\n# ==============================================================================\n\n# Multi-stream bidirectional throughput probing with BBR congestion control:\niperf3 -c ${ipHost} -p ${ipPort} -J -b 1000M -P 4 -C bbr\n`;
      } else if (targetEng === 'all') {
        elScriptBox.textContent = `#!/bin/sh\n# ==============================================================================\n# NetworkMeasureBox - Multi-Engine Sequential Suite Execution\n# Sequence: 1. Ookla Speedtest -> 2. Cloudflare Edge -> 3. RTR-NetTest -> 4. iPerf3\n# ==============================================================================\n\n/usr/local/bin/speedtest --accept-license --accept-gdpr --format=json\ncurl -s "https://speed.cloudflare.com/__down?bytes=25000000" -o /dev/null\npython3 -m nmb.speed.rtr --json\niperf3 -c speedtest.init7.net -p 5203 -J -b 1000M -C bbr\n`;
      } else {
        const sid = (data && data.scheduled_server && data.scheduled_server.id) ? data.scheduled_server.id : 31717;
        elScriptBox.textContent = `#!/bin/sh\n# ==============================================================================\n# NetworkMeasureBox - Realtime Ookla Speedtest Execution\n# Target Server: 2Connect Kft. (#${sid})\n# ==============================================================================\n\n/usr/local/bin/speedtest --accept-license --accept-gdpr --format=json --server-id ${sid}\n`;
      }
    }
  }

  async function selectEngine(eng, skipSave) {
    if (!eng) return;
    selectedEngine = eng.toLowerCase();

    // 1. Instantly switch visual pill state (0 ms)
    document.querySelectorAll('.engine-pill').forEach(el => el.classList.remove('active'));
    const pill = document.getElementById('pill-engine-' + selectedEngine);
    if (pill) pill.classList.add('active');

    // 2. Instantly update engine description
    const descEl = document.getElementById('engine-desc-text');
    if (descEl) {
      if (selectedEngine === 'ookla') {
        descEl.innerHTML = t('engine_desc_ookla', '⚡ <b>Ookla Speedtest:</b> Global server fleet, selectable target server (e.g. 2Connect #31717), detailed download/upload and bufferbloat.');
      } else if (selectedEngine === 'cloudflare') {
        descEl.innerHTML = t('engine_desc_cloudflare', '☁️ <b>Cloudflare Edge (cloudflare-speed-cli):</b> Direct CDN edge speed measurement (speed.cloudflare.com), airport PoP code (e.g. BUD), ASN and loaded latency.');
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

    // 4. Instantly switch dashboard results card and command preview to this engine (0 ms)
    renderHomeEngineCard(selectedEngine);

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
          document.getElementById('hdr-wan-ip').innerHTML = `<span style="color:#38bdf8;">${wanV4}</span> <span style="font-size:10px; color:#a78bfa;" title="${wanV6}">[v6]</span>`;
        } else {
          document.getElementById('hdr-wan-ip').innerText = wanV4 || wanV6 || '--';
        }
        document.getElementById('hdr-wan-iface').innerText = data.system_info.wan_interface || 'eth0';
        document.getElementById('hdr-uptime').innerText = data.system_info.uptime || '--';
      }

      // Measuring banner tracking
      const isMeas = data.is_measuring || false;
      document.getElementById('measuring-banner').style.display = isMeas ? 'flex' : 'none';
      document.getElementById('btn-home-measure').disabled = isMeas;

      // Render Dashboard speedtest card based on selected engine
      renderHomeEngineCard(selectedEngine, data);

      // Script preview box (in Schedule tab)
      if (data.latest_script && document.getElementById('script-preview-box')) {
        document.getElementById('script-preview-box').textContent = data.latest_script;
      }

      // Contract information (Tab 9 & header - safe null checks)
      if (data.contract) {
        const ispName = data.contract.isp_name || (data.system_info && data.system_info.wan_ip ? 'Internet (' + data.system_info.wan_ip + ')' : 'Nincs megadva');
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
          bannerEl.innerHTML = `<span style="color:#38bdf8;">#${escapeHtml(sched.id)}</span> — <b>${escapeHtml(sched.name || 'Egyedi Szerver')}</b> <code style="color:#94a3b8; font-size:12px;">(${escapeHtml(sched.host || '')})</code>`;
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
          const limitMbps = ((capMbps * gatePct) / 100.0).toFixed(1);
          modeBadge.innerHTML = `🟢 <b>${t('mode_scheduled', 'Automated Schedule')}:</b> ${cronDesc} &nbsp;|&nbsp; 🛡️ <b>${t('accuracy_gate', 'Accuracy Gate')}:</b> &lt; ${gatePct.toFixed(1)}% (max ${limitMbps} Mbps)`;
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
        if (data.automated_engine) {
          window.currentAutomatedEngine = data.automated_engine;
          if (document.getElementById('sched-engine-select')) {
            document.getElementById('sched-engine-select').value = data.automated_engine;
          }
          if (!selectedEngine) {
            selectEngine(data.automated_engine, true);
          }
        }

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
          schedResolved.innerHTML = `🎯 <b>${escapeHtml(sched.name || 'Szerver #' + sched.id)}</b> <code style="color:#94a3b8;">(${escapeHtml(sched.host || '')})</code>`;
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
            <td><b>${t.label || t.addr}</b> <code style="font-size:11px; color:#94a3b8;">(${t.addr})</code></td>
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

        data.speed_tests.forEach(st => {
          const d = new Date(st.ts);
          const dtStr = d.getFullYear() + '.' + String(d.getMonth()+1).padStart(2,'0') + '.' + String(d.getDate()).padStart(2,'0') + ' ' + String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
          const dMbps = (st.down_bps || 0) / 1000000.0;
          const uMbps = (st.up_bps || 0) / 1000000.0;
          const lat = (st.ping_us || 0) / 1000.0;
          if (st.status === 'ok') {
            totDown += dMbps; totUp += uMbps; totLat += lat; countOk++;
          }
          const bb = st.bufferbloat_grade ? `<span class="badge badge-ok">${st.bufferbloat_grade} (+${st.bufferbloat_delta_ms || 0}ms)</span>` : '--';
          
          let engineBadge = '<span class="badge" style="background:rgba(2,132,199,0.2);color:#38bdf8;border:1px solid #0284c7;">OOKLA</span>';
          if (st.engine === 'cloudflare') {
            engineBadge = `<span class="badge" style="background:rgba(245,158,11,0.2);color:#fbbf24;border:1px solid #f59e0b;">CLOUDFLARE ${st.colo ? '[' + st.colo + ']' : ''}</span>`;
          } else if (st.engine === 'rtr' || st.engine === 'rtr-nettest') {
            engineBadge = '<span class="badge" style="background:rgba(16,185,129,0.2);color:#34d399;border:1px solid #10b981;">RTR-NETTEST</span>';
          }

          let safeServerName = escapeHtml(st.server_name || st.server_host || '--');
          let link = safeServerName;
          if (st.result_url) {
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
          if (stV4 && stV6) {
            clientIpCell = `<div style="font-size:11px; line-height:1.3;"><span style="color:#38bdf8;" title="IPv4">${stV4}</span><br><span style="color:#a78bfa; font-size:10px;" title="IPv6">${stV6}</span></div>`;
          } else if (stV4) {
            clientIpCell = `<code style="color:#38bdf8;">${stV4}</code>`;
          } else if (stV6) {
            clientIpCell = `<code style="color:#a78bfa; font-size:10px;">${stV6}</code>`;
          } else {
            clientIpCell = '<code>--</code>';
          }

          sHtml += `<tr>
            <td>${dtStr}</td>
            <td>${engineBadge}</td>
            <td><b>${dMbps.toFixed(2)} Mbps</b> ${renderRowPctBadge(dPct)}</td>
            <td><b>${uMbps.toFixed(2)} Mbps</b> ${renderRowPctBadge(uPct)}</td>
            <td>${lat.toFixed(2)} ms</td>
            <td>${bb}</td>
            <td>${clientIpCell}</td>
            <td>${link}</td>
          </tr>`;
        });
        document.getElementById('speed-table-body').innerHTML = sHtml;

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
            <td><b>${pc.port}</b></td>
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
              <div class="client-name" title="${c.name}">${c.name}</div>
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
          if (cInput && cInput.value && cInput.value.match(/^\\d+$/)) {
            customServerId = parseInt(cInput.value);
          }
        } else if (val && val !== 'auto' && val.match(/^\\d+$/)) {
          customServerId = parseInt(val);
        }
      }
    }

    showToast(`${t('measuring_started', 'Starting measurement')} [${selectedEngine.toUpperCase()}]${customServerId ? ' #' + customServerId : ''}...`);
    document.getElementById('measuring-banner').style.display = 'flex';
    document.getElementById('btn-home-measure').disabled = true;

    try {
      const payload = { engine: selectedEngine };
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

  async function loadServers(query = '') {
    const tbody = document.getElementById('script-servers-tbody');
    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">${t('searching_servers', 'Searching speedtest benchmark network...')}</td></tr>`;
    try {
      const url = query ? `/api/speedtest/servers?q=${encodeURIComponent(query)}` : '/api/speedtest/servers';
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      serverList = data.servers || [];
      renderCatalog(serverList);
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--red);">Error loading servers: ${e}</td></tr>`;
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
        <td><code>#${sid}</code></td>
        <td><b>${s.sponsor || s.name || '--'}</b></td>
        <td>${s.location || s.name || '--'}</td>
        <td>${s.country || '--'}</td>
        <td style="text-align: center;">
          <button class="btn-primary" style="padding: 4px 10px; font-size: 11px;" onclick="setDefaultServer(${sid}, '${sName}', '${sHost}')">⭐ ${t('servers_btn_use', 'Use as Target Server')}</button>
          <button class="btn-secondary" style="padding: 4px 10px; font-size: 11px;" onclick="runSingleServerTest(${sid})">${t('server_test_btn', '▶ Test to this server')}</button>
        </td>
      </tr>`;
    });
    tbody.innerHTML = html;
  }

  function escapeQuotes(str) {
    return (str || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
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
      showToast('Please enter a valid numeric server ID (e.g. 31717)!');
      return;
    }
    const sid = parseInt(val);
    if (action === 'default') {
      setDefaultServer(sid, `Egyedi Szerver #${sid}`, '');
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
      footer.innerHTML = `Host: <b style="color:#38bdf8;">${escapeHtml(data.hostname || 'speedtest')}</b> &bull; Displaying: <b>${entries.length}</b> lines &bull; Kernel: <b style="color:#38bdf8;">${stats.kernel || 0}</b> &bull; Network & PHY: <b style="color:#34d399;">${stats.network || 0}</b> &bull; Link Events: <b style="color:#f59e0b;">${stats.links || 0}</b> &bull; Errors: <b style="color:${stats.errors ? '#f87171' : '#94a3b8'};">${stats.errors || 0}</b> &bull; System Time: <code>${data.system_time || ''}</code>`;
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
      msgSafe = msgSafe.replace(/(\b(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)[.](?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)[.](?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)[.](?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b)/g, '<span style="color:#60a5fa; font-weight:600;">$1</span>');
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
      footer.innerHTML = `Records: <b>${records.length}</b> (Buffer: ${data.total_buffered || 0} / ${data.capacity || 5000}) &bull; Active file: <code style="color:#38bdf8;">${data.log_file || '/var/log/nmb/nmb_developer.log'}</code> &bull; Daemon Level: <b style="color:#f59e0b;">${data.current_level || 'DEBUG'}</b>`;
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
        <span class="devlog-ts">${r.ts_iso || ''}</span>
        <span class="devlog-badge ${badgeClass}">${r.level}</span>
        <span class="devlog-meta" title="${escapeHtml(r.logger)} [${loc}]">${escapeHtml(r.logger)}</span>
        <span class="devlog-thread" title="${escapeHtml(r.thread)}">[${escapeHtml(r.thread)}]</span>
        <span class="devlog-msg">${escapeHtml(r.message)}${excHtml}</span>
      </div>`;
    });

    term.innerHTML = html;

    if (devLogAutoScroll) {
      term.scrollTop = term.scrollHeight;
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
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
        body: JSON.stringify({ include_db: true, include_journal: true }),
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
    if (b) b.classList.add('active');
    if (subtabId === 'rsub-guest') {
      loadGuestWifiStatus();
    }
    if (subtabId === 'rsub-system') {
      loadSystemInfo();
    }
    if (subtabId === 'rsub-kernel') {
      loadKernelStatus();
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
      const drv = caps.driver || 'ismeretlen';
      const apOk = caps.ap_mode_supported !== false;
      hwBadge.innerHTML = `<span>${t('device_interface', 'Interface')}: <b>${iface}</b> (${phy}) | Driver: <b>${drv}</b> | AP Mode: ${apOk ? '✅ ' + t('wifi_supported', 'Supported') : '⚠️ ' + t('wifi_limited', 'Limited')}</span>`;
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
        const suffix = supported ? '' : ' (' + t('not_supported', 'Not Supported') + ')';
        return `<span class="badge" style="${style}">${prefix}${b.label}${suffix}</span>`;
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
        return `<span class="badge" style="${style}">${prefix}${s.label}</span>`;
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
        return `<span class="badge" style="${style}">${supported ? '✓ ' : '✗ '}${w} MHz</span>`;
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
      if (cEl) cEl.innerText = liveStatus.channel ? `Csatorna ${liveStatus.channel}` : '--';
      const wEl = document.getElementById('wifi-live-width');
      if (wEl) wEl.innerText = liveStatus.channel_width_mhz ? `${liveStatus.channel_width_mhz} MHz` : '--';
      const txEl = document.getElementById('wifi-live-txpower');
      if (txEl) txEl.innerText = (liveStatus.txpower_dbm !== undefined && liveStatus.txpower_dbm > 0) ? `${liveStatus.txpower_dbm.toFixed(1)} dBm` : '--';
      const stEl = document.getElementById('wifi-live-clients');
      if (stEl) stEl.innerText = `${liveStatus.connected_stations || 0} ${t('clients_count', 'clients')}`;
    }

    // 6. Dynamic Form Dropdown Constraints based on Hardware Support
    const bandSel = document.getElementById('cfg-wifi-band');
    if (bandSel && caps.supported_bands) {
      for (let opt of bandSel.options) {
        if (opt.value === 'auto') continue;
        const sup = caps.supported_bands.includes(opt.value);
        opt.disabled = !sup;
        const cleanText = opt.text.replace(' (Hardveresen nem támogatott)', '').replace(' (Nem támogatott)', '').replace(' (Hardware not supported)', '');
        opt.text = sup ? cleanText : cleanText + ' (' + t('not_supported', 'Hardware not supported') + ')';
      }
    }

    const stdSel = document.getElementById('cfg-wifi-standard');
    if (stdSel && caps.supported_standards) {
      for (let opt of stdSel.options) {
        if (opt.value === 'auto') continue;
        const sup = caps.supported_standards.includes(opt.value);
        opt.disabled = !sup;
        const cleanText = opt.text.replace(' (Hardveresen nem támogatott)', '').replace(' (Nem támogatott)', '').replace(' (Hardware not supported)', '');
        opt.text = sup ? cleanText : cleanText + ' (' + t('not_supported', 'Hardware not supported') + ')';
      }
    }

    const widthSel = document.getElementById('cfg-wifi-channel-width');
    if (widthSel && caps.supported_widths) {
      for (let opt of widthSel.options) {
        if (opt.value === 'auto') continue;
        const wVal = parseInt(opt.value);
        const sup = caps.supported_widths.includes(wVal) || caps.supported_widths.includes(String(wVal));
        opt.disabled = !sup;
        const cleanText = opt.text.replace(' (Hardveresen nem támogatott)', '').replace(' (Nem támogatott)', '').replace(' (Hardware not supported)', '');
        opt.text = sup ? cleanText : cleanText + ' (' + t('not_supported', 'Hardware not supported') + ')';
      }
    }

    const secSel = document.getElementById('cfg-wifi-security');
    if (secSel) {
      for (let opt of secSel.options) {
        if (opt.value === 'wpa3' || opt.value === 'mixed') {
          if (!caps.wpa3_supported) {
            opt.disabled = true;
            const cleanText = opt.text.replace(' (Hardver nem támogatja)', '').replace(' (Hardware not supported)', '');
            opt.text = cleanText + (caps.wpa3_supported ? '' : ' (' + t('not_supported', 'Hardware not supported') + ')');
          }
        }
      }
    }
  }

  function updateWifiChannelOptions(band, selectedChannel) {
    const chSel = document.getElementById('cfg-wifi-channel');
    if (!chSel) return;
    const currentVal = (selectedChannel !== undefined && selectedChannel !== null) ? parseInt(selectedChannel) : parseInt(chSel.value || 0);

    let html = '<option value="0">Auto (Automatic Channel Selection / ACS)</option>';

    if (band === '5ghz') {
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
        html += `<option value="${item.ch}">Csatorna ${item.ch} (${item.mhz} MHz) - ${item.desc}</option>`;
      });
    } else if (band === '6ghz') {
      const ch6 = [
        1, 5, 9, 13, 17, 21, 33, 37, 41, 45, 49, 65, 69, 73, 77, 81,
        97, 101, 105, 109, 113, 129, 133, 137, 141, 145, 161, 165, 169, 173, 177,
        193, 197, 201, 205, 209, 225, 229, 233
      ];
      ch6.forEach(ch => {
        const freq = 5950 + ch * 5;
        html += `<option value="${ch}">Csatorna ${ch} (${freq} MHz) [6 GHz PSC]</option>`;
      });
    } else {
      // 2.4 GHz
      for (let ch = 1; ch <= 13; ch++) {
        const freq = 2407 + ch * 5;
        const tag = (ch === 1 || ch === 6 || ch === 11) ? ' (Non-overlapping - Recommended)' : '';
        html += `<option value="${ch}">Csatorna ${ch} (${freq} MHz)${tag}</option>`;
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
    if (!val || !val.match(/^\\d+$/)) {
      showToast('Please enter a valid numeric server ID (e.g. 31717)!');
      return;
    }
    const sid = parseInt(val);
    setDefaultServer(sid, 'Egyedi Szerver #' + sid, '');
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
        nameEl.innerHTML = `✅ <b>${srv.sponsor || srv.name}</b> <code style="color:#94a3b8;">(${srv.location || srv.host || ''})</code>`;
      } else {
        nameEl.innerHTML = `⚠️ Server #${val} (engine will attempt target during test)`;
      }
    } catch (e) {
      nameEl.innerText = 'Szerver #' + val;
    }
  }

  function clearSchedServer() {
    document.getElementById('sched-server-id-input').value = '';
    document.getElementById('sched-server-resolved-name').innerText = t('target_server_auto', 'Automatic Closest Server (Auto)');
    markSchedDirty();
  }

  let globalContractDownMbps = 1000.0;

  function updateGateCalculatedBadge() {
    const badge = document.getElementById('sched-gate-badge');
    const pctInput = document.getElementById('sched-gate-percent');
    if (!badge) return;
    const pct = pctInput ? parseFloat(pctInput.value) || 2.0 : 2.0;
    const capMbps = globalContractDownMbps || 1000.0;
    const limitMbps = (capMbps * (pct / 100.0)).toFixed(1);
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
    const serverId = rawSrvId && rawSrvId.match(/^\\d+$/) ? parseInt(rawSrvId) : null;
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
      await saveQuickSchedule('manual', '0 */6 * * *');
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
      if (document.getElementById('cfg-wifi-country')) document.getElementById('cfg-wifi-country').value = d.wifi_country_code || 'HU';
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

      // Contract / ISP
      if (document.getElementById('cfg-isp-name')) document.getElementById('cfg-isp-name').value = d.isp_name || '';
      if (document.getElementById('cfg-conn-type')) document.getElementById('cfg-conn-type').value = d.connection_type || 'fiber';
      if (document.getElementById('cfg-account-id')) document.getElementById('cfg-account-id').value = d.circuit_id || d.account_id || '';
      if (document.getElementById('cfg-contract-down')) document.getElementById('cfg-contract-down').value = d.contract_down_mbps || '';
      if (document.getElementById('cfg-guaranteed-down')) document.getElementById('cfg-guaranteed-down').value = d.guaranteed_down_mbps || '';
      if (document.getElementById('cfg-contract-up')) document.getElementById('cfg-contract-up').value = d.contract_up_mbps || '';
      if (document.getElementById('cfg-guaranteed-up')) document.getElementById('cfg-guaranteed-up').value = d.guaranteed_up_mbps || '';

      // System
      if (document.getElementById('cfg-sqm-algo')) document.getElementById('cfg-sqm-algo').value = d.sqm_algorithm || 'cake';

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
      wifi_country_code: document.getElementById('cfg-wifi-country') ? document.getElementById('cfg-wifi-country').value : 'HU',
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

      isp_name: document.getElementById('cfg-isp-name').value,
      connection_type: document.getElementById('cfg-conn-type').value,
      circuit_id: document.getElementById('cfg-account-id').value,
      contract_down_mbps: parseFloat(document.getElementById('cfg-contract-down').value) || 0,
      guaranteed_down_mbps: parseFloat(document.getElementById('cfg-guaranteed-down').value) || 0,
      contract_up_mbps: parseFloat(document.getElementById('cfg-contract-up').value) || 0,
      guaranteed_up_mbps: parseFloat(document.getElementById('cfg-guaranteed-up').value) || 0,

      sqm_algorithm: document.getElementById('cfg-sqm-algo').value,
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
          if (resLabel) resLabel.textContent = 'Combined Total';
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
          document.getElementById('iperf-raw-log').innerHTML = `<span style="color: #f87171; font-weight: bold;">Error: ${escapeHtml(l.error)}</span>\n${l.cmd ? 'Command: ' + escapeHtml(l.cmd) : ''}`;
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
      const speedBadge = s.speed ? `<span style="font-size: 10.5px; background: rgba(56, 189, 248, 0.2); color: #38bdf8; padding: 2px 7px; border-radius: 4px; margin-left: 6px;">${escapeHtml(s.speed)}</span>` : '';
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
            <button class="btn-secondary" style="font-size: 11.5px; padding: 5px 11px;" onclick="probeServerModal('${s.host}', ${s.port}, 'probe-badge-${idx}', this)">⚡ Ping</button>
            <button class="btn-primary" style="font-size: 11.5px; padding: 5px 12px;" onclick="selectPublicServer('${s.host}', ${s.port}, '${safeProvider}', '${safeSite}', '${s.speed || ''}')">🎯 Select Server</button>
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

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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
          if (badge) badge.innerHTML = `<span style="color:#34d399; font-weight:600;">✅ ${d.rtt_ms}ms</span>`;
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
      if (info) info.innerHTML = `🎯 <b>${site || provider || host}</b> <code style="color:#94a3b8;">(${host}:${port})</code> ${speed ? '[' + speed + ']' : ''}`;
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
        badge.innerHTML = `🎯 <b>Selected Server:</b> ${site} • ${provider} (<code>${host}:${port}</code>) ${speed ? `[<b>${speed}</b>]` : ''}`;
      }
      showToast(`Selected iPerf3 target: ${host}:${port}`);
    }
    closePublicServersModal();
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
  // Traceroute Engine
  // ==========================================
  let traceroutePollingTimer = null;

  async function runTracerouteTest() {
    const target = (document.getElementById('traceroute-target').value || '').trim() || '1.1.1.1';
    const maxHops = parseInt(document.getElementById('traceroute-max-hops').value) || 30;

    document.getElementById('btn-traceroute-run').disabled = true;
    document.getElementById('traceroute-indicator').style.display = 'inline-block';
    showToast('Starting traceroute to ' + target + '...');

    try {
      const res = await fetch('/api/traceroute/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host: target, max_hops: maxHops })
      });
      if (!res.ok) {
        const err = await res.json();
        showToast('Traceroute error: ' + (err.message || 'Busy'));
      }
      pollTracerouteStatus();
    } catch (e) {
      showToast('Traceroute failed: ' + e);
      document.getElementById('btn-traceroute-run').disabled = false;
      document.getElementById('traceroute-indicator').style.display = 'none';
    }
  }

  async function pollTracerouteStatus() {
    if (traceroutePollingTimer) clearTimeout(traceroutePollingTimer);
    try {
      const res = await fetch('/api/traceroute/status');
      if (res.ok) {
        const d = await res.json();
        if (d.latest && d.latest.hops) {
          renderTracerouteHops(d.latest.hops);
        }
        if (d.is_running) {
          document.getElementById('btn-traceroute-run').disabled = true;
          document.getElementById('traceroute-indicator').style.display = 'inline-block';
          traceroutePollingTimer = setTimeout(pollTracerouteStatus, 2000);
          return;
        }
      }
    } catch (e) {}
    document.getElementById('btn-traceroute-run').disabled = false;
    document.getElementById('traceroute-indicator').style.display = 'none';
  }

  function renderTracerouteHops(hops) {
    const tbody = document.getElementById('traceroute-table-body');
    if (!hops || hops.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; color: var(--text-muted);">' + t('no_hops_captured', 'No hops captured.') + '</td></tr>';
      return;
    }
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

      // Country with flag emoji and badge
      let countryHtml = '--';
      if (h.ip !== '*' && h.country && h.country !== '--') {
        const flag = h.flag || '🌐';
        const cName = escapeHtml(h.country);
        const cCode = h.country_code ? `<span class="badge" style="font-size: 10px; padding: 2px 5px; margin-left: 4px; background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);">${escapeHtml(h.country_code)}</span>` : '';
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

      html += `<tr>
        <td style="font-weight: 700; color: #38bdf8;">${h.hop}</td>
        <td style="font-family: monospace; font-weight: 600; color: #e2e8f0;">${escapeHtml(h.ip)}</td>
        <td style="color: #cbd5e1; font-family: monospace; font-size: 12px;">${escapeHtml(h.hostname || h.host || '--')}</td>
        <td>${countryHtml}</td>
        <td>${ispHtml}</td>
        <td style="font-family: monospace; color: #94a3b8;">${rtt1}</td>
        <td style="font-family: monospace; color: #94a3b8;">${rtt2}</td>
        <td style="font-family: monospace; color: #94a3b8;">${rtt3}</td>
        <td>${statusPill}</td>
      </tr>`;
    });
    tbody.innerHTML = html;
  }

  async function loadTracerouteStatus() {
    try {
      const res = await fetch('/api/traceroute/status');
      if (res.ok) {
        const d = await res.json();
        if (d.latest && d.latest.hops) {
          renderTracerouteHops(d.latest.hops);
        }
      }
    } catch (e) {}
  }

  // ==========================================
  // OONI Probe Censorship & Internet Freedom
  // ==========================================
  let ooniPollingTimer = null;

  async function loadOoniStatus() {
    try {
      const res = await fetch('/api/ooni/status');
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
        <td style="font-weight: 700;">#${item.id}</td>
        <td style="font-weight: 600;">${icon} ${item.name}</td>
        <td>AS${item.asn || '--'} (${escapeHtml(item.network_name || 'ISP')})</td>
        <td style="color: var(--text-muted); font-size: 12px;">${timeStr}</td>
        <td style="font-weight: 700; color: ${isClean ? '#10b981' : '#ef4444'};">${anom}</td>
        <td>${item.total_count || 1}</td>
        <td>${verdBadge}</td>
        <td>
          <button class="btn-secondary" style="font-size: 11px; padding: 4px 10px;" onclick="openOoniRunDetails(${item.id})">
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

      let urlDisplay = m.url ? `<a href="${escapeHtml(m.url)}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8; text-decoration: underline;">${escapeHtml(m.url)}</a>` : `<span style="color: var(--text-muted);">${escapeHtml(m.test_name || 'Standard Test')}</span>`;

      const runtimeStr = m.runtime ? `${Number(m.runtime).toFixed(2)}s` : '--';

      html += `<tr>
        <td style="font-weight: 700; color: #94a3b8;">#${m.id}</td>
        <td style="word-break: break-all; max-width: 380px;">${urlDisplay}</td>
        <td><span style="font-size: 11.5px; color: #cbd5e1;">${escapeHtml(m.test_name || '--')}</span></td>
        <td>${badge}</td>
        <td style="color: var(--text-muted); font-size: 12px;">${runtimeStr}</td>
        <td>
          <button class="btn-secondary" style="font-size: 11px; padding: 3px 8px;" onclick="inspectOoniMeasurement(${m.id})">
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
        httpDetails = `Received: <pre style="font-size: 10px; margin: 2px 0;">${escapeHtml(JSON.stringify(tk.received))}</pre>`;
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
      showToast('Scan error: ' + e);
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
        <td style="font-family: monospace; font-weight: 700; color: #f1f5f9;">${safeIp}</td>
        <td style="font-family: monospace; color: #cbd5e1;">${safeMac}</td>
        <td>${vendorBadge}</td>
        <td style="color: #38bdf8; font-weight: 500;">${safeHostname}</td>
        <td>${ifaceBadge}</td>
        <td>${stateBadge}</td>
      </tr>`;
    });
    tbody.innerHTML = html;
  }

  // ==========================================
  // Dedicated Guest Wi-Fi Receiver & Client Station Probe
  // ==========================================
  let cachedGuestWifiStatus = null;

  async function loadGuestWifiStatus() {
    try {
      const res = await fetch('/api/wifi/guest/status');
      if (!res.ok) return;
      const d = await res.json();
      cachedGuestWifiStatus = d;

      // 1. Update Subtab Badge
      const subtabBadge = document.getElementById('guest-wifi-badge-pill');
      if (subtabBadge) {
        if (d.connected) {
          subtabBadge.style.background = 'rgba(16, 185, 129, 0.15)';
          subtabBadge.style.color = '#34d399';
          subtabBadge.style.border = '1px solid #10b981';
          subtabBadge.innerHTML = `🟢 Csatlakozva: <b>${escapeHtml(d.ssid)}</b>`;
        } else {
          subtabBadge.style.background = 'rgba(148, 163, 184, 0.15)';
          subtabBadge.style.color = '#94a3b8';
          subtabBadge.style.border = '1px solid #475569';
          subtabBadge.innerHTML = '⚪ Not Connected';
        }
      }

      // 2. Update Explorer Banner
      const expStatusText = document.getElementById('explorer-guest-status-text');
      const expDetailsText = document.getElementById('explorer-guest-details-text');
      if (expStatusText) {
        if (d.connected) {
          expStatusText.style.background = 'rgba(16, 185, 129, 0.15)';
          expStatusText.style.color = '#34d399';
          expStatusText.style.border = '1px solid #10b981';
          expStatusText.innerHTML = `🟢 Csatlakozva: <b>${escapeHtml(d.ssid)}</b> (${escapeHtml(d.ip_address || 'DHCP')})`;
          if (expDetailsText) {
            expDetailsText.innerHTML = `Guest Subnet: <b><code style="color:#e9d5ff;">${escapeHtml(d.subnet || '--')}</code></b> (Gateway: ${escapeHtml(d.gateway || '--')}) | Signal: <b>${d.signal_percent}%</b>. ${escapeHtml(d.isolation_verdict)}`;
          }
        } else {
          expStatusText.style.background = 'rgba(148, 163, 184, 0.15)';
          expStatusText.style.color = '#94a3b8';
          expStatusText.style.border = '1px solid #475569';
          expStatusText.innerHTML = '⚪ Not Connected';
          if (expDetailsText) {
            expDetailsText.innerHTML = 'Wi-Fi receiver is not connected to a guest network. Click settings to configure connection.';
          }
        }
      }

      // 3. Update Subtab Status Grid
      if (document.getElementById('guest-wifi-stat-ssid')) {
        document.getElementById('guest-wifi-stat-ssid').textContent = d.ssid || (d.connected ? 'Connected' : 'Nincs csatlakozva');
        document.getElementById('guest-wifi-stat-ip').textContent = d.cidr || d.ip_address || '--';
        document.getElementById('guest-wifi-stat-gw').textContent = d.gateway || '--';
        document.getElementById('guest-wifi-stat-sig').textContent = (d.signal_percent || 0) + '%';
        const sigbar = document.getElementById('guest-wifi-stat-sigbar');
        if (sigbar) sigbar.style.width = (d.signal_percent || 0) + '%';
        document.getElementById('guest-wifi-stat-sec').textContent = `Csat: ${d.channel || '--'} | ${d.security || 'WPA2'}`;
        document.getElementById('guest-wifi-stat-mac').textContent = d.mac_address || '--';
        if (document.getElementById('guest-wifi-stat-metric')) {
          document.getElementById('guest-wifi-stat-metric').textContent = d.route_metric || 600;
        }
      }

      // 4. Update Isolation text
      const isoText = document.getElementById('guest-wifi-isolation-text');
      if (isoText) {
        isoText.textContent = d.isolation_verdict || 'Guest Wi-Fi telemetry ready.';
      }

      // 5. Prepopulate configuration inputs if available
      if (d.ssid && document.getElementById('cfg-guest-wifi-ssid') && !document.getElementById('cfg-guest-wifi-ssid').value) {
        document.getElementById('cfg-guest-wifi-ssid').value = d.ssid;
      }
    } catch (e) {
      console.debug('loadGuestWifiStatus error:', e);
    }
  }

  async function scanGuestWifiNetworks() {
    const btn = document.getElementById('btn-scan-guest-wifi');
    const tableWrap = document.getElementById('guest-wifi-scan-table-wrap');
    const tbody = document.getElementById('guest-wifi-scan-tbody');
    if (btn) btn.disabled = true;
    showToast('Scanning nearby Wi-Fi networks via wlan0...');
    if (tableWrap) tableWrap.style.display = 'block';
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 16px;">Scanning frequencies (2.4 GHz & 5 GHz)... Please wait.</td></tr>';

    try {
      const res = await fetch('/api/wifi/guest/scan');
      if (res.ok) {
        const d = await res.json();
        const nets = d.networks || [];
        if (nets.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #f87171; padding: 16px;">No Wi-Fi access points detected. Ensure wireless antenna is connected.</td></tr>';
          return;
        }
        let html = '';
        nets.forEach(n => {
          const safeSsid = escapeHtml(n.ssid);
          const safeBssid = escapeHtml(n.bssid);
          const safeSec = escapeHtml(n.security);
          const inUseBadge = n.in_use
            ? '<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981; font-size: 11px;">Active</span>'
            : '<span style="color: var(--text-muted); font-size: 11px;">Available</span>';

          html += `<tr>
            <td>${inUseBadge}</td>
            <td style="font-weight: 700; color: #f1f5f9;">${safeSsid}</td>
            <td>
              <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 50px; height: 6px; background: #334155; border-radius: 3px; overflow: hidden;">
                  <div style="width: ${n.signal}%; height: 100%; background: #10b981;"></div>
                </div>
                <span style="font-size: 12px; font-weight: 600;">${n.signal}%</span>
              </div>
            </td>
            <td style="font-family: monospace;">${n.channel}</td>
            <td><span class="badge-pill" style="background: rgba(56, 189, 248, 0.12); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.3); font-size: 11px;">${safeSec}</span></td>
            <td style="font-family: monospace; font-size: 11.5px; color: #94a3b8;">${safeBssid}</td>
            <td>
              <button class="btn-primary" style="font-size: 11px; padding: 4px 10px;" onclick="selectScannedGuestWifi('${escapeHtml(n.ssid)}', '${escapeHtml(n.security)}')">
                Select ➡️
              </button>
            </td>
          </tr>`;
        });
        tbody.innerHTML = html;
        showToast(`Scan completed: ${nets.length} Wi-Fi networks found.`);
      }
    } catch (e) {
      showToast('Scan error: ' + e);
      if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: #f87171;">Error: ${escapeHtml(String(e))}</td></tr>`;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function selectScannedGuestWifi(ssid, sec) {
    const input = document.getElementById('cfg-guest-wifi-ssid');
    if (input) input.value = ssid;
    const passInput = document.getElementById('cfg-guest-wifi-pass');
    if (passInput) passInput.focus();
    showToast(`Selected Wi-Fi: "${ssid}". Enter password if required and click Connect.`);
  }

  async function connectGuestWifi() {
    const ssid = (document.getElementById('cfg-guest-wifi-ssid').value || '').trim();
    const pass = (document.getElementById('cfg-guest-wifi-pass').value || '').trim();
    const metric = parseInt(document.getElementById('cfg-guest-wifi-metric').value) || 600;
    const iface = (document.getElementById('cfg-guest-wifi-iface').value || 'wlan0').trim();

    if (!ssid) {
      showToast('Please enter or select a Guest Wi-Fi SSID.');
      return;
    }

    showToast(`Connecting ${iface} to Guest Wi-Fi "${ssid}"... Please wait.`);
    try {
      const res = await fetch('/api/wifi/guest/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ssid: ssid,
          password: pass,
          interface: iface,
          metric: metric,
          save: true
        })
      });
      const d = await res.json();
      if (res.ok && d.status === 'ok') {
        showToast('✅ ' + d.message);
        await loadGuestWifiStatus();
        await loadNetworkDevices();
      } else {
        showToast('❌ ' + (d.message || 'Connection failed'));
      }
    } catch (e) {
      showToast('Error connecting: ' + e);
    }
  }

  async function disconnectGuestWifi() {
    if (!confirm('Disconnect wireless interface from Guest Wi-Fi?')) return;
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
        const pkgList = (d.packages && d.packages.length) ? d.packages.join('\\n') : 'All system packages are up to date.';
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
          const rpsBadge = it.rps_enabled ? `<span class="badge-pill" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981;">Mask 0x${it.rps_cpus} (Active)</span>` : '<span class="badge-pill" style="color: #94a3b8;">Disabled</span>';
          const rfsStr = (it.rfs_flow_cnt > 0) ? `<span style="color: #38bdf8; font-weight: 600;">${it.rfs_flow_cnt} flows</span>` : '--';
          const xpsStr = (it.xps_cpus && it.xps_cpus !== '0') ? `<span style="color: #a855f7;">Mask 0x${it.xps_cpus}</span>` : '--';
          html += `<tr>
            <td style="font-weight: 700; color: #ffffff;">${escapeHtml(it.name)}</td>
            <td>${speedStr}</td>
            <td>${it.mtu || 1500}</td>
            <td>${rpsBadge}</td>
            <td>${rfsStr}</td>
            <td>${xpsStr}</td>
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
  let activeRemoteSubtab = 'duckdns';

  function switchRemoteSubtab(tabName) {
    activeRemoteSubtab = tabName;
    ['duckdns', 'wireguard', 'openvpn', 'proxy'].forEach(t => {
      const btn = document.getElementById('btn-subtab-' + t);
      const pane = document.getElementById('subtab-content-' + t);
      if (btn) btn.className = (t === tabName) ? 'btn-primary' : 'btn-secondary';
      if (pane) pane.style.display = (t === tabName) ? 'block' : 'none';
    });

    if (tabName === 'duckdns') loadDuckdnsStatus();
    else if (tabName === 'wireguard') loadWireguardStatus();
    else if (tabName === 'openvpn') loadOpenvpnStatus();
    else if (tabName === 'proxy') loadProxyStatus();
  }

  function loadRemoteAccessStatus() {
    loadDuckdnsStatus();
    loadWireguardStatus();
    loadOpenvpnStatus();
    loadProxyStatus();
  }

  // ---- DuckDNS ----
  async function loadDuckdnsStatus() {
    try {
      const res = await fetch('/api/duckdns/status');
      if (!res.ok) return;
      const d = await res.json();

      const enChbox = document.getElementById('duckdns-enabled');
      const domInput = document.getElementById('duckdns-domain');
      const intInput = document.getElementById('duckdns-interval');
      const custInput = document.getElementById('duckdns-custom-ip');

      if (enChbox && d.enabled !== undefined) enChbox.checked = !!d.enabled;
      if (domInput && d.domain !== undefined && !domInput.dataset.focused) domInput.value = d.domain || '';
      if (intInput && d.interval_min !== undefined && !intInput.dataset.focused) intInput.value = d.interval_min || 10;
      if (custInput && d.custom_ip !== undefined && !custInput.dataset.focused) custInput.value = d.custom_ip || '';

      const badge = document.getElementById('duckdns-status-badge');
      if (badge) {
        if (!d.enabled) {
          badge.className = 'badge';
          badge.style.background = 'rgba(148, 163, 184, 0.15)';
          badge.style.color = '#94a3b8';
          badge.style.border = '1px solid #475569';
          badge.textContent = 'Disabled';
        } else if (d.last_status === 'OK') {
          badge.className = 'badge';
          badge.style.background = 'rgba(16, 185, 129, 0.15)';
          badge.style.color = '#10b981';
          badge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
          badge.textContent = '🟢 Synced (OK)';
        } else if (d.last_status === 'KO') {
          badge.className = 'badge';
          badge.style.background = 'rgba(239, 68, 68, 0.15)';
          badge.style.color = '#ef4444';
          badge.style.border = '1px solid rgba(239, 68, 68, 0.3)';
          badge.textContent = '🔴 Auth Error (KO)';
        } else {
          badge.className = 'badge';
          badge.style.background = 'rgba(56, 189, 248, 0.15)';
          badge.style.color = '#38bdf8';
          badge.style.border = '1px solid rgba(56, 189, 248, 0.3)';
          badge.textContent = d.last_status || 'Waiting';
        }
      }

      const ipEl = document.getElementById('duckdns-detected-ip');
      if (ipEl) ipEl.textContent = d.detected_ip || d.last_ip || '--';

      const timeEl = document.getElementById('duckdns-last-time');
      if (timeEl) timeEl.textContent = d.last_update ? d.last_update.substring(0, 19).replace('T', ' ') : 'Never';

      const nextEl = document.getElementById('duckdns-next-time');
      if (nextEl) nextEl.textContent = d.next_update ? d.next_update.substring(0, 19).replace('T', ' ') : '--';

      const msgBox = document.getElementById('duckdns-msg-box');
      if (msgBox) {
        msgBox.textContent = `FQDN: ${d.domain ? d.domain + '.duckdns.org' : '(none configured)'} • Public IP: ${d.detected_ip || '--'} • Response: ${d.last_status || 'Ready'}`;
      }
    } catch (e) {
      console.error('loadDuckdnsStatus error:', e);
    }
  }

  async function saveDuckdnsSettings() {
    const enabled = !!document.getElementById('duckdns-enabled')?.checked;
    const domain = (document.getElementById('duckdns-domain')?.value || '').trim();
    const token = (document.getElementById('duckdns-token')?.value || '').trim();
    const interval_min = parseInt(document.getElementById('duckdns-interval')?.value, 10) || 10;
    const custom_ip = (document.getElementById('duckdns-custom-ip')?.value || '').trim();

    try {
      const res = await fetch('/api/duckdns/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, domain, token, interval_min, custom_ip }),
      });
      const d = await res.json();
      if (res.ok) {
        showToast('DuckDNS settings successfully saved');
        loadDuckdnsStatus();
      } else {
        showToast('DuckDNS save error: ' + (d.message || 'Failed'));
      }
    } catch (e) {
      showToast('Save DuckDNS error: ' + e);
    }
  }

  async function updateDuckdnsNow() {
    showToast('Triggering DuckDNS DynDNS synchronization...');
    try {
      const res = await fetch('/api/duckdns/update', { method: 'POST' });
      const d = await res.json();
      if (res.ok && d.success) {
        showToast(`DuckDNS updated! IP: ${d.ip || 'OK'}`);
      } else {
        showToast('DuckDNS update returned: ' + (d.status || d.message || 'Failed'));
      }
      setTimeout(loadDuckdnsStatus, 1000);
    } catch (e) {
      showToast('DuckDNS update error: ' + e);
    }
  }

  // ---- WireGuard ----
  let wireguardIsActive = false;

  async function loadWireguardStatus() {
    try {
      const res = await fetch('/api/wireguard/status');
      if (!res.ok) return;
      const d = await res.json();
      wireguardIsActive = !!d.active;

      const portInput = document.getElementById('wg-port');
      const subnetInput = document.getElementById('wg-subnet');
      const endpointInput = document.getElementById('wg-endpoint');
      if (portInput && d.port && !portInput.dataset.focused) portInput.value = d.port;
      if (subnetInput && d.subnet && !subnetInput.dataset.focused) subnetInput.value = d.subnet;
      if (endpointInput && d.endpoint && !endpointInput.dataset.focused) endpointInput.value = d.endpoint;

      const badge = document.getElementById('wg-status-badge');
      if (badge) {
        if (d.active) {
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
        if (d.active) {
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
          hsDisplay = `<span style="color: #10b981; font-weight: 600;">Active (${p.latest_handshake_ago || hsSec + 's ago'})</span>`;
        } else {
          hsDisplay = `<span style="color: var(--text-muted);">${p.latest_handshake_ago || Math.floor(hsSec / 60) + 'm ago'}</span>`;
        }
      }

      const statusBadge = isConnected
        ? '<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 2px 6px; border-radius: 4px; font-size: 11px;">🟢 Connected</span>'
        : '<span class="badge" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #475569; padding: 2px 6px; border-radius: 4px; font-size: 11px;">Offline</span>';

      const rxFormatted = formatBytes(p.transfer_rx || 0);
      const txFormatted = formatBytes(p.transfer_tx || 0);

      html += `<tr>
        <td style="font-weight: 700; color: #38bdf8;">${escapeHtml(p.name)}</td>
        <td style="font-family: monospace; font-size: 12px; color: #cbd5e1;">${escapeHtml(p.allowed_ips || p.client_ip || '--')}</td>
        <td>${statusBadge}</td>
        <td style="font-size: 12px; color: var(--text-muted);">${escapeHtml(p.endpoint || '--')}</td>
        <td style="font-size: 12px;">↓ ${rxFormatted} / ↑ ${txFormatted}</td>
        <td style="font-size: 12px;">${hsDisplay}</td>
        <td style="display: flex; gap: 6px;">
          <a href="/api/wireguard/peer/config?id=${p.id}" download="${escapeHtml(p.name)}.conf" class="btn-secondary" style="font-size: 11px; padding: 3px 8px; text-decoration: none;">
            📥 .conf
          </a>
          <button class="btn-secondary" style="font-size: 11px; padding: 3px 8px;" onclick="showWireguardQr('${p.id}', '${escapeHtml(p.name)}')">
            📱 QR
          </button>
          <button class="btn-danger" style="font-size: 11px; padding: 3px 8px;" onclick="deleteWireguardPeer('${p.id}', '${escapeHtml(p.name)}')">
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
    const endpoint = (document.getElementById('wg-endpoint')?.value || '').trim();

    try {
      const res = await fetch('/api/wireguard/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port, subnet, endpoint }),
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
    const name = (nameInput?.value || '').trim();
    const client_ip = (ipInput?.value || '').trim();

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
        body: JSON.stringify({ name, client_ip }),
      });
      const d = await res.json();
      if (res.ok && d.peer) {
        showToast(`Peer "${name}" generated successfully!`);
        if (nameInput) nameInput.value = '';
        if (ipInput) ipInput.value = '';
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

  async function showWireguardQr(peerId, peerName) {
    const modal = document.getElementById('wg-qr-modal');
    const title = document.getElementById('wg-qr-peer-title');
    const img = document.getElementById('wg-qr-img');
    if (!modal || !img) return;

    if (title) title.textContent = `📱 WireGuard QR: ${peerName}`;
    try {
      const res = await fetch(`/api/wireguard/peer/qr?id=${encodeURIComponent(peerId)}`);
      const d = await res.json();
      if (d.qr_data_uri) {
        img.src = d.qr_data_uri;
      } else {
        img.src = `/api/wireguard/peer/qr?id=${encodeURIComponent(peerId)}&raw=1&t=${Date.now()}`;
      }
    } catch (e) {
      img.src = `/api/wireguard/peer/qr?id=${encodeURIComponent(peerId)}&raw=1&t=${Date.now()}`;
    }
    modal.style.display = 'flex';
  }

  // ---- OpenVPN ----
  let openvpnIsActive = false;

  async function loadOpenvpnStatus() {
    try {
      const res = await fetch('/api/openvpn/status');
      if (!res.ok) return;
      const d = await res.json();
      openvpnIsActive = !!d.active;

      const protoSelect = document.getElementById('ovpn-proto');
      const portInput = document.getElementById('ovpn-port');
      const endpointInput = document.getElementById('ovpn-endpoint');
      if (protoSelect && d.proto) protoSelect.value = d.proto;
      if (portInput && d.port && !portInput.dataset.focused) portInput.value = d.port;
      if (endpointInput && d.endpoint && !endpointInput.dataset.focused) endpointInput.value = d.endpoint;

      const badge = document.getElementById('ovpn-status-badge');
      if (badge) {
        if (d.active) {
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
        if (d.active) {
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
          <button class="btn-danger" style="font-size: 11px; padding: 3px 8px;" onclick="deleteOpenvpnClient('${escapeHtml(c.name)}')">
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
    const endpoint = (document.getElementById('ovpn-endpoint')?.value || '').trim();

    try {
      const res = await fetch('/api/openvpn/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proto, port, endpoint }),
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
      proxyIsActive = !!d.running;

      const portInput = document.getElementById('proxy-port');
      const authChk = document.getElementById('proxy-auth-enable');
      const userInput = document.getElementById('proxy-username');
      const passInput = document.getElementById('proxy-password');
      const tlsChk = document.getElementById('proxy-tls-enable');

      if (portInput && d.port && !portInput.dataset.focused) portInput.value = d.port;
      if (authChk && d.auth_enabled !== undefined) {
        authChk.checked = !!d.auth_enabled;
        toggleProxyAuthFields();
      }
      if (userInput && d.username && !userInput.dataset.focused) userInput.value = d.username;
      if (tlsChk && d.tls_enabled !== undefined) tlsChk.checked = !!d.tls_enabled;

      const badge = document.getElementById('proxy-status-badge');
      if (badge) {
        if (d.running) {
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
        if (d.running) {
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

      if (actEl) actEl.textContent = stats.active_connections || 0;
      if (totEl) totEl.textContent = stats.total_connections || 0;
      if (trfEl) {
        const rx = formatBytes(stats.bytes_rx || 0);
        const tx = formatBytes(stats.bytes_tx || 0);
        trfEl.textContent = `↓ ${rx} / ↑ ${tx}`;
      }
      if (uptEl) {
        const sec = stats.uptime_sec || 0;
        if (sec > 0) {
          const m = Math.floor(sec / 60);
          const s = sec % 60;
          uptEl.textContent = `${m}m ${s}s`;
        } else {
          uptEl.textContent = d.running ? 'Just started' : 'Offline';
        }
      }
    } catch (e) {
      console.error('loadProxyStatus error:', e);
    }
  }

  async function saveProxySettings() {
    const port = parseInt(document.getElementById('proxy-port')?.value, 10) || 8443;
    const auth_enabled = !!document.getElementById('proxy-auth-enable')?.checked;
    const username = (document.getElementById('proxy-username')?.value || '').trim();
    const password = (document.getElementById('proxy-password')?.value || '').trim();
    const tls_enabled = !!document.getElementById('proxy-tls-enable')?.checked;

    try {
      const res = await fetch('/api/proxy/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port, auth_enabled, username, password, tls_enabled }),
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

  // Initialization
  ['duckdns-domain', 'duckdns-token', 'duckdns-interval', 'duckdns-custom-ip', 'wg-port', 'wg-subnet', 'wg-endpoint', 'ovpn-port', 'ovpn-endpoint', 'proxy-port', 'proxy-username', 'proxy-password'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('focus', () => el.dataset.focused = '1');
      el.addEventListener('blur', () => delete el.dataset.focused);
    }
  });

  setInterval(() => {
    const remoteTab = document.getElementById('tab-remote');
    if (remoteTab && remoteTab.classList.contains('active')) {
      if (activeRemoteSubtab === 'proxy' && proxyIsActive) {
        loadProxyStatus();
      } else if (activeRemoteSubtab === 'wireguard' && wireguardIsActive) {
        loadWireguardStatus();
      } else if (activeRemoteSubtab === 'openvpn' && openvpnIsActive) {
        loadOpenvpnStatus();
      }
    }
  }, 3000);

  loadTranslations(localStorage.getItem('nmb_lang') || 'en');
  updateServerSelectVisibility(selectedEngine);
  refreshStatus();
  fetchWifiCapabilities();
  loadMacInfo();
  loadServers();
  loadConfig();
  loadNetworkDevices();
  loadIperfStatus();
  loadGuestWifiStatus();
  loadSystemInfo();
  loadKernelStatus();
  setInterval(refreshStatus, 3000);
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
</script>
</body>
</html>"""
