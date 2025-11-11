import os
import yaml
import requests
from flask import Flask, render_template_string, request, redirect, url_for, jsonify


# ========= Configuration loading =========

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")


def load_config() -> dict:
    """Load configuration from config.yaml.

    Expected structure:

    bridge:
      host: "127.0.0.1"
      port: 8080

    nuki:
      token: "CHANGE_ME"
      id: 123456789
      device_type: 0

    web:
      port: 5000
      language: "en"
    """
    if not os.path.exists(CONFIG_PATH):
        raise RuntimeError(f"Config file not found: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return data


_cfg = load_config()

BRIDGE_HOST = _cfg.get("bridge", {}).get("host", "127.0.0.1")
BRIDGE_PORT = _cfg.get("bridge", {}).get("port", 8080)

NUKI_ID = _cfg.get("nuki", {}).get("id")
TOKEN = _cfg.get("nuki", {}).get("token", "")
DEVICE_TYPE = _cfg.get("nuki", {}).get("device_type", 0)

WEB_PORT = _cfg.get("web", {}).get("port", 5000)
DEFAULT_LANG = _cfg.get("web", {}).get("language", "en")


if NUKI_ID is None:
    raise RuntimeError("Missing 'nuki.id' in config.yaml")
if not TOKEN:
    raise RuntimeError("Missing 'nuki.token' in config.yaml")


# ========= Localization strings =========

STRINGS = {
    "en": {
        "html_lang": "en",
        "title": "Nuki Web Control",
        "subtitle": "Secure remote control – instant actions and live lock status.",
        "bridge_label": "Bridge:",

        "status_card_title": "Lock status",
        "status_card_subtitle": "NukiID: {nuki_id}",

        "chip_lock": "Lock",
        "chip_door": "Door",
        "chip_batt": "Battery",
        "chip_time": "Last update",

        "state_loading": "Reading state…",

        "btn_lock": "Lock",
        "btn_unlock": "Unlock",
        "btn_unlatch": "Open door",
        "btn_lockngo": "Lock'n'Go",

        "details_card_title": "State details",
        "details_card_subtitle": "Technical view",
        "details_summary": "Normalized JSON (for debug / integrations)",

        "lang_en_label": "EN",
        "lang_it_label": "IT",

        "unknown_command_msg": "Error: unknown command.",
        "bridge_error_prefix": "Error: ",
        "ok_msg": "OK (batteryCritical={batteryCritical})",
        "bridge_response_prefix": "Bridge response: ",
        "error_keyword": "Error",

        "js_label_state": "State: ",
        "js_label_door": "Door: ",
        "js_label_battery": "Battery: ",
        "js_label_last_update": "Last update: ",
        "js_error_prefix": "JS error: ",
    },
    "it": {
        "html_lang": "it",
        "title": "Nuki Web Control",
        "subtitle": "Controllo remoto sicuro – azioni immediate e stato live della serratura.",
        "bridge_label": "Bridge:",

        "status_card_title": "Stato serratura",
        "status_card_subtitle": "NukiID: {nuki_id}",

        "chip_lock": "Serratura",
        "chip_door": "Porta",
        "chip_batt": "Batteria",
        "chip_time": "Ultimo aggiornamento",

        "state_loading": "Lettura stato in corso…",

        "btn_lock": "Chiudi",
        "btn_unlock": "Sblocca",
        "btn_unlatch": "Apri porta",
        "btn_lockngo": "Lock'n'Go",

        "details_card_title": "Dettagli stato",
        "details_card_subtitle": "Vista tecnica",
        "details_summary": "JSON normalizzato (per debug / integrazioni)",

        "lang_en_label": "EN",
        "lang_it_label": "IT",

        "unknown_command_msg": "Errore: comando sconosciuto.",
        "bridge_error_prefix": "Errore: ",
        "ok_msg": "OK (batteryCritical={batteryCritical})",
        "bridge_response_prefix": "Risposta bridge: ",
        "error_keyword": "Errore",

        "js_label_state": "Stato: ",
        "js_label_door": "Porta: ",
        "js_label_battery": "Batteria: ",
        "js_label_last_update": "Ultimo aggiornamento: ",
        "js_error_prefix": "Errore JS: ",
    },
}


def resolve_lang() -> str:
    """Resolve current language from ?lang= query param or config default.

    Fallback to English if unknown code.
    """
    lang = request.args.get("lang") or DEFAULT_LANG or "en"
    if lang not in STRINGS:
        lang = "en"
    return lang


# ========= Bridge helpers =========


def get_state():
    """
    Call /lockState on RaspiNukiBridge to get LIVE Nuki state.
    Errors are normalized so we never leak the full URL or token.
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

    except requests.exceptions.ConnectionError:
        # Bridge not reachable at all (host down / port closed)
        return {"error": "Bridge unreachable (connection error while calling /lockState)."}

    except requests.exceptions.Timeout:
        # Bridge did not answer in time
        return {"error": "Bridge timeout while calling /lockState."}

    except requests.exceptions.HTTPError as e:
        # Bridge replied with 4xx / 5xx. Do NOT expose the full URL (contains token).
        status = e.response.status_code if e.response is not None else "HTTP error"
        return {"error": f"Bridge returned HTTP {status} for /lockState."}

    except Exception:
        # Generic, safe message
        return {"error": "Unexpected error while talking to the bridge (/lockState)."}



def send_action(action: int):
    """
    Send /lockAction to RaspiNukiBridge.

    action:
      1 = unlock
      2 = lock
      3 = unlatch (open door)
      4 = lock'n'go
      5 = lock'n'go + unlatch

    Errors are normalized so we never leak the full URL or token.
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

    except requests.exceptions.ConnectionError:
        return {"error": "Bridge unreachable (connection error while calling /lockAction)."}

    except requests.exceptions.Timeout:
        return {"error": "Bridge timeout while calling /lockAction."}

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "HTTP error"
        return {"error": f"Bridge returned HTTP {status} for /lockAction."}

    except Exception:
        return {"error": "Unexpected error while talking to the bridge (/lockAction)."}



# ========= HTML template =========

HTML_TEMPLATE = """<!doctype html>
<html lang="{{ ui.html_lang }}">
<head>
  <meta charset="utf-8">
  <title>{{ ui.title }}</title>
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

    .top-right-box {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
    }

    .lang-switcher {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      justify-content: flex-end;
    }

    .lang-btn {
      border-radius: 999px;
      border: 1px solid rgba(148,163,184,0.5);
      background: rgba(15,23,42,0.8);
      padding: 4px 8px;
      font-size: 0.75rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      color: var(--text-muted);
      width: auto;
      box-shadow: none;
    }

    .lang-btn .flag {
      font-size: 0.9rem;
    }

    .lang-btn.active {
      background: linear-gradient(135deg, #3b82f6, #1d4ed8);
      color: #fff;
      border-color: transparent;
    }

    .lang-btn.active .flag {
      filter: drop-shadow(0 0 3px rgba(15,23,42,0.8));
    }
  </style>

  <script>
    function formatTimestamp(ts) {
      if (!ts) return "";
      try {
        const d = new Date(ts);
        return d.toLocaleString("it-IT", { timeZone: "Europe/Rome" });
      } catch (e) {
        return ts;
      }
    }

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
      let parts = [];

      if (data.stateName) {
        parts.push("{{ ui.js_label_state }}" + data.stateName + " (state=" + data.state + ")");
      } else if (data.state !== undefined) {
        parts.push("{{ ui.js_label_state }}state=" + data.state);
      }

      if (data.doorStateName) {
        parts.push("{{ ui.js_label_door }}" + data.doorStateName + " (doorState=" + data.doorState + ")");
      }

      const battPct = extractBatteryPercent(data);
      if (battPct !== null) {
        parts.push("{{ ui.js_label_battery }}" + battPct + "%");
      } else if (data.batteryCritical !== undefined) {
        parts.push("{{ ui.js_label_battery }}" + (data.batteryCritical ? "CRITICAL" : "OK"));
      }

      if (data.timestamp) {
        parts.push("{{ ui.js_label_last_update }}" + formatTimestamp(data.timestamp));
      }

      if (parts.length === 0) {
        return "No state data available";
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
      const stateEl = document.getElementById("state-text");
      const rawEl = document.getElementById("state-raw");
      const lockEl = document.getElementById("chip-lock");
      const doorEl = document.getElementById("chip-door");
      const battEl = document.getElementById("chip-batt");
      const timeEl = document.getElementById("chip-time");

      try {
        const res = await fetch("/api/state");

        // Se proprio l'endpoint risponde 500/404 ecc.
        if (!res.ok) {
          stateEl.textContent = "{{ ui.bridge_error_prefix }}" +
            "HTTP " + res.status + " from /api/state";
          rawEl.textContent = "";

          lockEl.querySelector(".chip-value").textContent = "-";
          doorEl.querySelector(".chip-value").textContent = "-";
          battEl.querySelector(".chip-value").textContent = "-";
          battEl.querySelector(".chip-value").className = "chip-value";
          timeEl.querySelector(".chip-value").textContent = "-";
          return;
        }

        const data = await res.json();

        if (data.error) {
          // Errore lato bridge o lato requests
          stateEl.textContent = "{{ ui.bridge_error_prefix }}" + data.error;
          rawEl.textContent = "";

          lockEl.querySelector(".chip-value").textContent = "-";
          doorEl.querySelector(".chip-value").textContent = "-";
          battEl.querySelector(".chip-value").textContent = "-";
          battEl.querySelector(".chip-value").className = "chip-value";
          timeEl.querySelector(".chip-value").textContent = "-";
          return;
        }

        // --- da qui in giù rimane uguale a prima ---
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
          battValueEl.textContent = data.batteryCritical ? "CRITICAL" : "OK";
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
          battExtraEl.textContent = "CRITICAL";
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
        // Errore di rete / JS
        stateEl.textContent = "{{ ui.js_error_prefix }}" + e;
        rawEl.textContent = "";

        lockEl.querySelector(".chip-value").textContent = "-";
        doorEl.querySelector(".chip-value").textContent = "-";
        battEl.querySelector(".chip-value").textContent = "-";
        battEl.querySelector(".chip-value").className = "chip-value";
        timeEl.querySelector(".chip-value").textContent = "-";
      }
    }

    window.addEventListener("DOMContentLoaded", () => {
      refreshState();

      const langButtons = document.querySelectorAll(".lang-btn");
      langButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
          const lang = btn.getAttribute("data-lang");
          const url = new URL(window.location.href);
          url.searchParams.set("lang", lang);
          window.location.href = url.toString();
        });
      });
    });
  </script>
</head>

<body>
  <div class="page">
    <div class="shell">
      <div class="header">
        <div class="title-group">
          <div class="title">
            {{ ui.title }}
            <span class="title-pill">Raspberry Pi • RaspiNukiBridge</span>
          </div>
          <div class="subtitle">
            {{ ui.subtitle }}
          </div>
        </div>
        <div class="top-right-box">
          <div class="lang-switcher" aria-label="Language">
            {% for btn in lang_buttons %}
            <button type="button"
                    class="lang-btn {% if btn.code == lang %}active{% endif %}"
                    data-lang="{{ btn.code }}">
              <span>{{ btn.label }}</span>
            </button>
            {% endfor %}
          </div>
          <div class="endpoint-pill">
            <span>{{ ui.bridge_label }}</span>
            <code>{{ bridge_host }}:{{ bridge_port }}</code>
          </div>
        </div>
      </div>

      {% if msg %}
        <div class="msg {% if ui.error_keyword in msg %}msg-error{% else %}msg-ok{% endif %}">
          {{ msg }}
        </div>
      {% endif %}

      <div class="layout">
        <div class="card">
          <div class="card-header">
            <div class="card-title">{{ ui.status_card_title }}</div>
            <small>{{ ui.status_card_subtitle.format(nuki_id=nuki_id) }}</small>
          </div>

          <div class="status-row" style="margin-bottom: 8px;">
            <div class="chip" id="chip-lock">
              <div class="chip-label">{{ ui.chip_lock }}</div>
              <div class="chip-value">-</div>
            </div>
            <div class="chip" id="chip-door">
              <div class="chip-label">{{ ui.chip_door }}</div>
              <div class="chip-value">-</div>
            </div>
            <div class="chip" id="chip-batt">
              <div class="chip-label">{{ ui.chip_batt }}</div>
              <div class="chip-value">-</div>
              <span class="chip-pill" style="display:none;"></span>
            </div>
            <div class="chip" id="chip-time">
              <div class="chip-label">{{ ui.chip_time }}</div>
              <div class="chip-value">-</div>
            </div>
          </div>

          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
            <div style="font-size:0.86rem; color:var(--text-muted);">
              <span id="state-text">{{ ui.state_loading }}</span>
            </div>
            <button type="button" class="btn-secondary" onclick="refreshState()">
              <span class="btn-icon">🔄</span>
              Refresh
            </button>
          </div>

          <div class="buttons-grid" style="margin-top:12px;">
            <form method="post" action="/action/chiudi?lang={{ lang }}">
              <button class="btn-lock" type="submit">
                <span class="btn-icon">🔒</span> {{ ui.btn_lock }}
              </button>
            </form>

            <form method="post" action="/action/sblocca?lang={{ lang }}">
              <button class="btn-unlock" type="submit">
                <span class="btn-icon">🔓</span> {{ ui.btn_unlock }}
              </button>
            </form>

            <form method="post" action="/action/apri?lang={{ lang }}">
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

        <div class="card">
          <div class="card-header">
            <div class="card-title">{{ ui.details_card_title }}</div>
            <small>{{ ui.details_card_subtitle }}</small>
          </div>
          <div class="details">
            <details open>
              <summary>{{ ui.details_summary }}</summary>
              <pre id="state-raw">{}</pre>
            </details>
          </div>

          <div class="footer">
            HTTP API: <code>/lockState</code> • <code>/lockAction</code> • <code>/list</code>
          </div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""


app = Flask(__name__)


@app.route("/")
def index():
    lang = resolve_lang()
    ui = STRINGS[lang]

    msg = request.args.get("msg", "")

    lang_buttons = [
        {"code": "en", "label": STRINGS["en"]["lang_en_label"]},
        {"code": "it", "label": STRINGS["it"]["lang_it_label"]},
    ]

    return render_template_string(
        HTML_TEMPLATE,
        msg=msg,
        bridge_host=BRIDGE_HOST,
        bridge_port=BRIDGE_PORT,
        nuki_id=NUKI_ID,
        ui=ui,
        lang=lang,
        lang_buttons=lang_buttons,
    )


@app.route("/api/state")
def api_state():
    return jsonify(get_state())


@app.route("/action/<cmd>", methods=["POST"])
def action(cmd):
    lang = resolve_lang()
    ui = STRINGS[lang]

    mapping = {
        "sblocca": 1,   # unlock
        "chiudi": 2,    # lock
        "apri": 3,      # unlatch (open door)
        "lockngo": 4,   # lock'n'go
        # "lockngounlatch": 5,
    }

    if cmd not in mapping:
        return redirect(url_for("index", msg=ui["unknown_command_msg"], lang=lang))

    result = send_action(mapping[cmd])

    if "error" in result:
        msg = ui["bridge_error_prefix"] + str(result["error"])
    else:
        if result.get("success"):
            msg = ui["ok_msg"].format(
                batteryCritical=result.get("batteryCritical", False)
            )
        else:
            msg = ui["bridge_response_prefix"] + str(result)

    return redirect(url_for("index", msg=msg, lang=lang))


if __name__ == "__main__":
    # Listen on all interfaces so it is reachable from your LAN / VPN
    app.run(host="0.0.0.0", port=WEB_PORT)
