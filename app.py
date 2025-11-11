import json
from pathlib import Path

import requests
import yaml
from flask import Flask, render_template_string, request, redirect, url_for, jsonify

# ========= CONFIG LOADING =========
CONFIG_PATH = Path(__file__).with_name("config.yaml")


def load_config():
    """
    Load configuration from config.yaml.

    Example structure:

    bridge:
      host: "127.0.0.1"
      port: 8080

    nuki:
      token: "CHANGE_ME"
      id: 123456789
      device_type: 0

    web:
      port: 5000
      language: "en"   # or "it"
    """
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"Config file not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_cfg = load_config()

BRIDGE_HOST = _cfg["bridge"]["host"]
BRIDGE_PORT = _cfg["bridge"]["port"]

TOKEN = _cfg["nuki"]["token"]
NUKI_ID = _cfg["nuki"]["id"]
DEVICE_TYPE = _cfg["nuki"].get("device_type", 0)

WEB_PORT = _cfg.get("web", {}).get("port", 5000)

# Default UI language ("en" or "it")
DEFAULT_LANG = _cfg.get("web", {}).get("language", "en").lower()

# ========= UI STRINGS (I18N) =========
STRINGS = {
    "en": {
        "html_lang": "en",
        "subtitle": "Secure remote control – instant actions and live lock status.",
        "bridge_label": "Bridge:",
        "error_keyword": "Error",

        "lock_state_title": "Lock state",
        "state_details_title": "State details",
        "state_details_subtitle": "Technical view",

        "lock_label": "Lock",
        "door_label": "Door",
        "battery_label": "Battery",
        "last_update_label": "Last update",

        "reading_state": "Reading state…",
        "refresh_state": "Refresh state",

        "btn_lock": "Lock",
        "btn_unlock": "Unlock",
        "btn_unlatch": "Open door",
        "btn_lockngo": "Lock'n'Go",

        "normalized_json_summary": "Normalized JSON (for debug / integrations)",
        "footer_http_api": "HTTP API",

        # JS summary text pieces
        "summary_lock_prefix": "Lock: ",
        "summary_lock_state_prefix": "Lock: state=",
        "summary_door_prefix": "Door: ",
        "summary_door_state_prefix": "Door: doorState=",
        "summary_batt_prefix": "Battery: ",
        "summary_batt_critical_prefix": "Battery critical: ",
        "summary_last_update_prefix": "Last update: ",
        "no_state_data": "No state data available",

        "error_prefix": "Error: ",
        "js_error_prefix": "JS error: ",

        "critical_label": "Critical",
        "ok_label": "OK",

        "date_locale": "en-GB",

        # Language switcher labels
        "lang_en_label": "EN",
        "lang_it_label": "IT",
    },
    "it": {
        "html_lang": "it",
        "subtitle": "Controllo remoto sicuro – azioni immediate e stato live della serratura.",
        "bridge_label": "Bridge:",
        "error_keyword": "Errore",

        "lock_state_title": "Stato serratura",
        "state_details_title": "Dettagli stato",
        "state_details_subtitle": "Vista tecnica",

        "lock_label": "Serratura",
        "door_label": "Porta",
        "battery_label": "Batteria",
        "last_update_label": "Ultimo aggiornamento",

        "reading_state": "Lettura stato in corso…",
        "refresh_state": "Aggiorna stato",

        "btn_lock": "Chiudi",
        "btn_unlock": "Sblocca",
        "btn_unlatch": "Apri porta",
        "btn_lockngo": "Lock'n'Go",

        "normalized_json_summary": "JSON normalizzato (per debug / integrazioni)",
        "footer_http_api": "HTTP API",

        # JS summary text pieces
        "summary_lock_prefix": "Serratura: ",
        "summary_lock_state_prefix": "Serratura: state=",
        "summary_door_prefix": "Porta: ",
        "summary_door_state_prefix": "Porta: doorState=",
        "summary_batt_prefix": "Batteria: ",
        "summary_batt_critical_prefix": "Batteria critica: ",
        "summary_last_update_prefix": "Ultimo aggiornamento: ",
        "no_state_data": "Nessun dato di stato disponibile",

        "error_prefix": "Errore: ",
        "js_error_prefix": "Errore JS: ",

        "critical_label": "Critica",
        "ok_label": "OK",

        "date_locale": "it-IT",

        # Language switcher labels
        "lang_en_label": "EN",
        "lang_it_label": "IT",
    },
}

if DEFAULT_LANG not in STRINGS:
    DEFAULT_LANG = "en"


def get_lang():
    """
    Determine current UI language.

    Priority:
    1. "lang" query string parameter
    2. DEFAULT_LANG from config
    """
    lang = request.args.get("lang") or DEFAULT_LANG
    lang = lang.lower()
    return lang if lang in STRINGS else DEFAULT_LANG


# ====================================

app = Flask(__name__)


def get_state():
    """
    Call /lockState on the bridge to obtain the LIVE state of the Nuki lock.
    """
    try:
        resp = requests.get(
            f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/lockState",
            params={
                "nukiId": NUKI_ID,
                "deviceType": DEVICE_TYPE,
                "token": TOKEN,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def send_action(action: int):
    """
    Send a lockAction to the bridge.

    action:
      1 = unlock
      2 = lock
      3 = unlatch (open door)
      4 = lock'n'go
      5 = lock'n'go + unlatch
    """
    try:
        resp = requests.get(
            f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/lockAction",
            params={
                "nukiId": NUKI_ID,
                "deviceType": DEVICE_TYPE,
                "action": action,
                "token": TOKEN,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


HTML_TEMPLATE = """
<!doctype html>
<html lang="{{ ui.html_lang }}">
<head>
  <meta charset="utf-8">
  <title>Nuki Web Control</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #020617;
      --card-border: #1e293b;
      --accent: #3b82f6;
      --accent-soft: #1d4ed8;
      --danger: #ef4444;
      --success: #22c55e;
      --warning: #f97316;
      --text-main: #e5e7eb;
      --text-muted: #9ca3af;
      --chip-bg: #111827;
      --chip-border: #374151;
      --radius-lg: 16px;
      --radius-md: 10px;
      --shadow-soft: 0 18px 45px rgba(15,23,42,0.65);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      padding: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at top, #1d283a 0, #020617 55%, #000 100%);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      align-items: flex-start;
      justify-content: center;
    }

    .page {
      width: 100%;
      max-width: 960px;
      padding: 24px 12px 40px;
    }

    .shell {
      background: rgba(15,23,42,0.9);
      border-radius: 28px;
      border: 1px solid rgba(148,163,184,0.12);
      box-shadow: var(--shadow-soft);
      padding: 20px 22px 24px;
      backdrop-filter: blur(22px);
    }

    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 18px;
    }

    .title-group {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .title {
      font-size: 1.3rem;
      font-weight: 600;
      letter-spacing: 0.02em;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .title-pill {
      font-size: 0.7rem;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid rgba(148,163,184,0.6);
      color: var(--text-muted);
    }

    .subtitle {
      font-size: 0.85rem;
      color: var(--text-muted);
    }

    .endpoint-pill {
      font-size: 0.75rem;
      padding: 4px 8px;
      border-radius: 999px;
      border: 1px solid rgba(148,163,184,0.4);
      color: var(--text-muted);
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    .endpoint-pill code {
      font-family: ui-monospace, Menlo, Monaco, "SF Mono", "Roboto Mono", monospace;
      font-size: 0.73rem;
      color: #e5e7eb;
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(0, 1.4fr);
      gap: 16px;
    }

    @media (max-width: 768px) {
      .layout {
        grid-template-columns: minmax(0, 1fr);
      }
      .header {
        flex-direction: column;
        align-items: flex-start;
      }
    }

    .card {
      background: linear-gradient(135deg, rgba(15,23,42,0.96), rgba(15,23,42,0.86));
      border-radius: var(--radius-lg);
      border: 1px solid var(--card-border);
      padding: 14px 14px 16px;
    }

    .card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 10px;
    }

    .card-title {
      font-size: 0.9rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
    }

    .card-header small {
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    .status-row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      margin-top: 4px;
    }

    .chip {
      background: var(--chip-bg);
      border-radius: var(--radius-md);
      padding: 8px 10px;
      border: 1px solid var(--chip-border);
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .chip-label {
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .chip-value {
      font-size: 0.92rem;
      font-weight: 500;
    }

    .chip-value.ok {
      color: var(--success);
    }

    .chip-value.warn {
      color: var(--warning);
    }

    .chip-value.danger {
      color: var(--danger);
    }

    .chip-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 0.72rem;
      border: 1px solid rgba(148,163,184,0.4);
      color: var(--text-muted);
      margin-top: 2px;
    }

    .msg {
      margin-bottom: 8px;
      padding: 8px 10px;
      border-radius: var(--radius-md);
      font-size: 0.85rem;
      border: 1px solid rgba(148,163,184,0.3);
      background: rgba(15,23,42,0.9);
    }

    .msg-ok {
      border-color: rgba(34,197,94,0.6);
      background: rgba(22,163,74,0.12);
      color: #bbf7d0;
    }

    .msg-error {
      border-color: rgba(239,68,68,0.7);
      background: rgba(239,68,68,0.12);
      color: #fecaca;
    }

    .buttons-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }

    .buttons-grid form {
      margin: 0;
    }

    button {
      width: 100%;
      border: none;
      padding: 9px 0;
      border-radius: 999px;
      font-size: 0.95rem;
      cursor: pointer;
      font-weight: 500;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: transform 0.07s ease, box-shadow 0.07s ease, background 0.12s ease;
    }

    button:active {
      transform: translateY(1px);
      box-shadow: none;
    }

    .btn-lock {
      background: linear-gradient(135deg, #ef4444, #b91c1c);
      color: #fff;
      box-shadow: 0 6px 16px rgba(239,68,68,0.45);
    }
    .btn-unlock {
      background: linear-gradient(135deg, #22c55e, #15803d);
      color: #fff;
      box-shadow: 0 6px 16px rgba(34,197,94,0.45);
    }
    .btn-unlatch {
      background: linear-gradient(135deg, #f97316, #c2410c);
      color: #fff;
      box-shadow: 0 6px 16px rgba(249,115,22,0.45);
    }
    .btn-ln {
      background: linear-gradient(135deg, #3b82f6, #1d4ed8);
      color: #fff;
      box-shadow: 0 6px 16px rgba(59,130,246,0.45);
    }

    .btn-secondary {
      background: rgba(15,23,42,0.9);
      color: var(--text-main);
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 0.8rem;
      border: 1px solid rgba(148,163,184,0.6);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    .btn-icon {
      font-size: 1rem;
    }

    .details {
      margin-top: 6px;
      border-radius: var(--radius-md);
      border: 1px solid var(--card-border);
      background: radial-gradient(circle at top left, rgba(30,64,175,0.33), rgba(15,23,42,0.96));
      padding: 8px 10px;
    }

    .details summary {
      cursor: pointer;
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    pre {
      white-space: pre-wrap;
      font-family: ui-monospace, Menlo, Monaco, "SF Mono", "Roboto Mono", monospace;
      font-size: 0.8rem;
      margin-top: 4px;
      color: #e5e7eb;
    }

    .footer {
      margin-top: 10px;
      text-align: right;
      font-size: 0.76rem;
      color: var(--text-muted);
      opacity: 0.9;
    }

    /* Language switcher */
    .lang-switcher {
      display: inline-flex;
      gap: 4px;
      align-items: center;
    }

    .lang-btn {
      border-radius: 999px;
      border: 1px solid rgba(148,163,184,0.6);
      background: rgba(15,23,42,0.9);
      color: var(--text-main);
      font-size: 0.75rem;
      padding: 3px 8px 3px 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      opacity: 0.9;
    }

    .lang-btn span.flag {
      font-size: 0.9rem;
    }

    .lang-btn.active {
      background: linear-gradient(135deg, #3b82f6, #1d4ed8);
      color: #fff;
      border-color: transparent;
      opacity: 1;
    }
  </style>

  <script>
    // UI strings injected from Flask (per language)
    window.UI = {{ ui_json | safe }};
    window.CURRENT_LANG = "{{ lang }}";
  </script>

  <script>
    function formatTimestamp(ts) {
      if (!ts) return "";
      try {
        const d = new Date(ts);
        const locale = (window.UI && window.UI.date_locale) || "en-GB";
        return d.toLocaleString(locale, { timeZone: "Europe/Rome" });
      } catch (e) {
        return ts;
      }
    }

    // Extracts battery percentage from multiple possible formats
    function extractBatteryPercent(data) {
      if (typeof data.batteryCharge === "number") {
        return data.batteryCharge;
      }

      if (typeof data.batteryChargeState === "number") {
        return data.batteryChargeState;
      }

      if (data.batteryChargeState && typeof data.batteryChargeState.chargeLevel === "number") {
        return data.batteryChargeState.chargeLevel;
      }

      if (typeof data.batteryLevel === "number") {
        return data.batteryLevel;
      }

      return null;
    }

    function extractBatteryStatusLabel(data) {
      if (data.batteryChargeState && data.batteryChargeState.state) {
        return data.batteryChargeState.state;
      }
      return null;
    }

    function buildStateSummary(data) {
      const UI = window.UI || {};
      let parts = [];

      if (data.stateName) {
        parts.push(UI.summary_lock_prefix + data.stateName + " (state=" + data.state + ")");
      } else if (data.state !== undefined) {
        parts.push(UI.summary_lock_state_prefix + data.state);
      }

      if (data.doorStateName) {
        parts.push(UI.summary_door_prefix + data.doorStateName + " (doorState=" + data.doorState + ")");
      }

      const battPct = extractBatteryPercent(data);
      if (battPct !== null) {
        parts.push(UI.summary_batt_prefix + battPct + "%");
      } else if (data.batteryCritical !== undefined) {
        parts.push(UI.summary_batt_critical_prefix + data.batteryCritical);
      }

      if (data.timestamp) {
        parts.push(UI.summary_last_update_prefix + formatTimestamp(data.timestamp));
      }

      if (parts.length === 0) {
        return UI.no_state_data || "No state data available";
      }
      return parts.join(" • ");
    }

    function batteryClass(battPct, batteryCritical) {
      if (batteryCritical === true) return "danger";
      if (battPct === null || battPct === undefined) return "";
      if (battPct <= 20) return "danger";
      if (battPct <= 40) return "warn";
      return "ok";
    }

    async function refreshState() {
      const UI = window.UI || {};
      try {
        const res = await fetch("/api/state?lang=" + encodeURIComponent(window.CURRENT_LANG || ""));
        const data = await res.json();

        const stateEl = document.getElementById("state-text");
        const rawEl = document.getElementById("state-raw");

        const lockEl = document.getElementById("chip-lock");
        const doorEl = document.getElementById("chip-door");
        const battEl = document.getElementById("chip-batt");
        const timeEl = document.getElementById("chip-time");

        if (data.error) {
          stateEl.textContent = (UI.error_prefix || "Error: ") + data.error;
          rawEl.textContent = "";

          lockEl.querySelector(".chip-value").textContent = "-";
          doorEl.querySelector(".chip-value").textContent = "-";
          battEl.querySelector(".chip-value").textContent = "-";
          battEl.querySelector(".chip-value").className = "chip-value";
          timeEl.querySelector(".chip-value").textContent = "-";
          return;
        }

        stateEl.textContent = buildStateSummary(data);

        const battPct = extractBatteryPercent(data);
        const battLabel = extractBatteryStatusLabel(data);

        const normalized = {
          state: data.state,
          stateName: data.stateName,
          doorState: data.doorState,
          doorStateName: data.doorStateName,
          batteryCritical: data.batteryCritical,
          batteryPercent: battPct,
          batteryRawField: data.batteryChargeState,
          batteryStatusLabel: battLabel,
          trigger: data.trigger,
          timestamp_raw: data.timestamp,
          timestamp_local: data.timestamp ? formatTimestamp(data.timestamp) : null
        };

        rawEl.textContent = JSON.stringify(normalized, null, 2);

        lockEl.querySelector(".chip-value").textContent =
          data.stateName ? data.stateName + " (state=" + data.state + ")" :
          (data.state !== undefined ? "state=" + data.state : "-");

        doorEl.querySelector(".chip-value").textContent =
          data.doorStateName ? data.doorStateName + " (doorState=" + data.doorState + ")" :
          (data.doorState !== undefined ? "doorState=" + data.doorState : "-");

        const battValueEl = battEl.querySelector(".chip-value");
        battValueEl.className = "chip-value";
        if (battPct !== null) {
          battValueEl.textContent = battPct.toString() + "%";
        } else if (data.batteryCritical !== undefined) {
          battValueEl.textContent = data.batteryCritical
            ? (UI.critical_label || "Critical")
            : (UI.ok_label || "OK");
        } else {
          battValueEl.textContent = "-";
        }
        const cls = batteryClass(battPct, data.batteryCritical);
        if (cls) battValueEl.classList.add(cls);

        const battExtraEl = battEl.querySelector(".chip-pill");
        if (battLabel) {
          battExtraEl.textContent = battLabel;
          battExtraEl.style.display = "inline-flex";
        } else if (data.batteryCritical === true) {
          battExtraEl.textContent = UI.critical_label || "Critical";
          battExtraEl.style.display = "inline-flex";
        } else {
          battExtraEl.style.display = "none";
        }

        const timeValueEl = timeEl.querySelector(".chip-value");
        if (data.timestamp) {
          timeValueEl.textContent = formatTimestamp(data.timestamp);
        } else {
          timeValueEl.textContent = "-";
        }

      } catch (e) {
        const stateEl = document.getElementById("state-text");
        const rawEl = document.getElementById("state-raw");
        stateEl.textContent = (UI.js_error_prefix || "JS error: ") + e;
        rawEl.textContent = "";
      }
    }

    function setLang(lang) {
      const url = new URL(window.location.href);
      url.searchParams.set("lang", lang);
      window.location.href = url.toString();
    }

    function initLangButtons() {
      const current = window.CURRENT_LANG || "en";
      const buttons = document.querySelectorAll(".lang-btn");
      buttons.forEach(btn => {
        const lang = btn.getAttribute("data-lang");
        if (lang === current) {
          btn.classList.add("active");
        }
        btn.addEventListener("click", () => setLang(lang));
      });
    }

    window.refreshState = refreshState;

    window.addEventListener("DOMContentLoaded", () => {
      initLangButtons();
      refreshState();
    });
  </script>
</head>

<body>
  <div class="page">
    <div class="shell">
      <div class="header">
        <div class="title-group">
          <div class="title">
            Nuki Web Control
            <span class="title-pill">Raspberry Pi · RaspiNukiBridge</span>
          </div>
          <div class="subtitle">
            {{ ui.subtitle }}
          </div>
        </div>

        <div style="display:flex; flex-direction:column; align-items:flex-end; gap:8px;">
          <div class="endpoint-pill">
            <span>{{ ui.bridge_label }}</span>
            <code>{{ bridge_host }}:{{ bridge_port }}</code>
          </div>
          <div class="lang-switcher" aria-label="Language">
            <button type="button" class="lang-btn" data-lang="en">
              <span class="flag">🇬🇧</span>
              <span>{{ ui.lang_en_label }}</span>
            </button>
            <button type="button" class="lang-btn" data-lang="it">
              <span class="flag">🇮🇹</span>
              <span>{{ ui.lang_it_label }}</span>
            </button>
          </div>
        </div>
      </div>

      {% if msg %}
        <div class="msg {% if ui.error_keyword in msg %}msg-error{% else %}msg-ok{% endif %}">
          {{ msg }}
        </div>
      {% endif %}

      <div class="layout">
        <!-- Left column: state + commands -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">{{ ui.lock_state_title }}</div>
            <small>NukiID: {{ nuki_id }}</small>
          </div>

          <div class="status-row" style="margin-bottom: 8px;">
            <div class="chip" id="chip-lock">
              <div class="chip-label">{{ ui.lock_label }}</div>
              <div class="chip-value">-</div>
            </div>
            <div class="chip" id="chip-door">
              <div class="chip-label">{{ ui.door_label }}</div>
              <div class="chip-value">-</div>
            </div>
            <div class="chip" id="chip-batt">
              <div class="chip-label">{{ ui.battery_label }}</div>
              <div class="chip-value">-</div>
              <span class="chip-pill" style="display:none;"></span>
            </div>
            <div class="chip" id="chip-time">
              <div class="chip-label">{{ ui.last_update_label }}</div>
              <div class="chip-value">-</div>
            </div>
          </div>

          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
            <div style="font-size:0.86rem; color:var(--text-muted);">
              <span id="state-text">{{ ui.reading_state }}</span>
            </div>
            <button type="button" class="btn-secondary" onclick="refreshState()">
              <span class="btn-icon">🔄</span>
              {{ ui.refresh_state }}
            </button>
          </div>

          <div class="buttons-grid" style="margin-top:12px;">
            <form method="post" action="/action/lock?lang={{ lang }}">
              <button class="btn-lock" type="submit">
                <span class="btn-icon">🔒</span> {{ ui.btn_lock }}
              </button>
            </form>

            <form method="post" action="/action/unlock?lang={{ lang }}">
              <button class="btn-unlock" type="submit">
                <span class="btn-icon">🔓</span> {{ ui.btn_unlock }}
              </button>
            </form>

            <form method="post" action="/action/unlatch?lang={{ lang }}">
              <button class="btn-unlatch" type="submit">
                <span class="btn-icon">🚪</span> {{ ui.btn_unlatch }}
              </button>
            </form>

            <form method="post" action="/action/lockngo?lang={{ lang }}">
              <button class="btn-ln" type="submit">
                <span class="btn-icon">🚶‍♂️</span> {{ ui.btn_lockngo }}
              </button>
            </form>
          </div>
        </div>

        <!-- Right column: JSON details -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">{{ ui.state_details_title }}</div>
            <small>{{ ui.state_details_subtitle }}</small>
          </div>
          <div class="details">
            <details open>
              <summary>{{ ui.normalized_json_summary }}</summary>
              <pre id="state-raw">{}</pre>
            </details>
          </div>

          <div class="footer">
            {{ ui.footer_http_api }}: <code>/lockState</code> • <code>/lockAction</code> • <code>/list</code>
          </div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""


@app.route("/")
def index():
    """
    Main page: renders the HTML control panel.
    """
    msg = request.args.get("msg", "")
    lang = get_lang()
    ui = STRINGS[lang]
    ui_json = json.dumps(ui, ensure_ascii=False)

    return render_template_string(
        HTML_TEMPLATE,
        msg=msg,
        bridge_host=BRIDGE_HOST,
        bridge_port=BRIDGE_PORT,
        nuki_id=NUKI_ID,
        ui=ui,
        ui_json=ui_json,
        lang=lang,
    )


@app.route("/api/state")
def api_state():
    """
    API endpoint: returns current lock state as JSON.
    """
    return jsonify(get_state())


@app.route("/action/<cmd>", methods=["POST"])
def action(cmd):
    """
    Handle lock actions triggered by the UI buttons.
    """
    lang = get_lang()
    ui = STRINGS[lang]

    mapping = {
        "unlock": 1,   # unlock
        "lock": 2,     # lock
        "unlatch": 3,  # open door
        "lockngo": 4,  # lock'n'go
        # optionally: "lockngounlatch": 5
    }

    if cmd not in mapping:
        msg = f"{ui['error_prefix']}unknown command."
        return redirect(url_for("index", msg=msg, lang=lang))

    result = send_action(mapping[cmd])

    if "error" in result:
        msg = f"{ui['error_prefix']}{result['error']}"
    else:
        if result.get("success"):
            msg = f"OK (batteryCritical={result.get('batteryCritical', False)})"
        else:
            if lang == "it":
                msg = f"Risposta bridge: {result}"
            else:
                msg = f"Bridge response: {result}"

    return redirect(url_for("index", msg=msg, lang=lang))


if __name__ == "__main__":
    # Listen on all interfaces so the app is reachable from your network/VPN
    app.run(host="0.0.0.0", port=WEB_PORT)
