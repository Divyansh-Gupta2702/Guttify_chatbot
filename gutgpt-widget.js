(() => {
  "use strict";

  /*
   * GutGPT embeddable widget
   *
   * Shopify installation:
   *   <script src="https://api.yourdomain.com/gutgpt-widget.js"></script>
   *
   * The widget derives the API origin from the script URL, so the same file
   * works locally and in production without exposing any API secret.
   *
   * An optional host-page override is supported:
   *   window.GUTGPT_API_URL = "https://api.yourdomain.com";
   * before loading this script.
   */

  const scriptElement = document.currentScript;
  const configuredApiUrl = window.GUTGPT_API_URL || (
    scriptElement ? new URL(scriptElement.src, window.location.href).origin : window.location.origin
  );
  const GUTGPT_API_URL = configuredApiUrl.replace(/\/+$/, "");

  const ROOT_ID = "gutgpt-embeddable-widget";
  const REQUEST_TIMEOUT_MS = 90000;

  if (document.getElementById(ROOT_ID)) return;

  const host = document.createElement("div");
  host.id = ROOT_ID;
  host.setAttribute("aria-label", "GutGPT chatbot");
  document.body.appendChild(host);

  const shadow = host.attachShadow({ mode: "open" });

  shadow.innerHTML = `
    <style>
      :host { all: initial; }
      *, *::before, *::after { box-sizing: border-box; }

      .launcher {
        position: fixed;
        z-index: 2147483000;
        right: 22px;
        bottom: 22px;
        width: 66px;
        height: 66px;
        padding: 0;
        border: 3px solid #fff;
        border-radius: 50%;
        background: linear-gradient(135deg, #7b2cff, #5d19d8);
        color: #fff;
        box-shadow: 0 10px 30px rgba(50,25,70,.30), 0 0 0 4px rgba(106,63,150,.12);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        font: 700 20px/1 Inter, system-ui, sans-serif;
        transition: transform .2s ease, box-shadow .2s ease;
      }

      .launcher:hover {
        transform: scale(1.06);
        box-shadow: 0 14px 35px rgba(50,25,70,.38), 0 0 0 5px rgba(106,63,150,.16);
      }

      .launcher:active { transform: scale(.96); }

      .launcher-mark {
        width: 34px;
        height: 34px;
        border: 2px solid #fff;
        border-radius: 10px;
        display: grid;
        place-items: center;
        position: relative;
      }

      .launcher-mark::after {
        content: "";
        position: absolute;
        bottom: -5px;
        left: 7px;
        width: 9px;
        height: 9px;
        border-left: 2px solid #fff;
        border-bottom: 2px solid #fff;
        transform: skewY(-25deg);
      }

      .launcher-mark span {
        width: 5px;
        height: 5px;
        border-radius: 50%;
        background: #fff;
        box-shadow: 8px 0 0 #fff, -8px 0 0 #fff;
      }

      .panel {
        position: fixed;
        z-index: 2147483001;
        right: 22px;
        bottom: 96px;
        width: min(390px, calc(100vw - 28px));
        height: min(650px, calc(100vh - 120px));
        min-height: 430px;
        display: none;
        flex-direction: column;
        overflow: hidden;
        border: 1px solid #e8dfea;
        border-radius: 18px;
        background: #faf8fb;
        box-shadow: 0 20px 60px rgba(35,25,45,.22);
        color: #241f2b;
        font: 14px/1.45 Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }

      .panel.open { display: flex; }

      .head {
        padding: 14px 16px;
        color: #fff;
        background: linear-gradient(135deg, #c93f8f, #6a3f96);
        display: flex;
        justify-content: space-between;
        align-items: center;
      }

      .head-copy h2 {
        margin: 0;
        font: 600 17px/1.2 Georgia, serif;
      }

      .head-copy p {
        margin: 3px 0 0;
        opacity: .88;
        font-size: 11px;
      }

      .head-actions { display: flex; align-items: center; gap: 7px; }
      .close {
        border: 0;
        background: transparent;
        color: #fff;
        font-size: 25px;
        cursor: pointer;
        padding: 2px 6px;
        line-height: 1;
      }

      .bristol-stool-chart {
        display: block;
        width: 100%;
        max-width: 100%;
        height: auto;
        margin: 8px 0 12px;
        border-radius: 8px;
        background: #fff;
      }
      .bristol-chart-fallback { padding:10px 12px; border:1px solid #d8c9e4; border-radius:8px; background:#faf7fc; color:#42245b; }
      .bristol-options { display:flex; flex-wrap:wrap; gap:6px; margin:4px 0 12px; }
      .bristol-options button { border:1px solid #8b65a7; border-radius:8px; background:#f7f0fc; color:#42245b; padding:7px 10px; font:inherit; cursor:pointer; }
      .bristol-options button:disabled { opacity:.5; cursor:not-allowed; }
      .customer-intake {
        flex: 1;
        overflow-y: auto;
        padding: 18px 16px;
        background: #fff;
      }
      .customer-intake[hidden], .messages[hidden], .composer[hidden] { display: none !important; }
      .intake-title { margin: 0 0 6px; font-size: 17px; font-weight: 700; }
      .intake-copy { margin: 0 0 14px; color: #655d6b; font-size: 12px; }
      .intake-form { display: grid; gap: 11px; padding: 0; background: transparent; border-top: 0; }
      .intake-form label { display: grid; gap: 5px; color: #342b3b; font-size: 12px; font-weight: 600; }
      .intake-form input { width: 100%; min-height: 40px; border: 1px solid #ded5e4; border-radius: 9px; padding: 9px 10px; font: inherit; color: #241f2b; background: #fff; }
      .intake-form input:focus { outline: 2px solid #a77af0; outline-offset: 1px; }
      .consent-row { display: flex !important; grid-template-columns: 18px 1fr; align-items: start; gap: 8px !important; font-weight: 400 !important; line-height: 1.4; }
      .consent-row input { width: 16px; min-height: 16px; margin: 2px 0 0; }
      .intake-submit { min-height: 42px; border: 0; border-radius: 10px; color: #fff; font: 600 14px/1.2 inherit; background: linear-gradient(135deg, #8134ed, #6020cf); cursor: pointer; }
      .intake-submit:disabled { opacity: .55; cursor: wait; }
      .intake-error { margin: 0; color: #a51d36; font-size: 12px; }
      .messages {
        flex: 1;
        overflow-y: auto;
        overscroll-behavior: contain;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      .assessment-actions {
        padding: 0 16px 8px;
        display: flex;
        justify-content: space-between;
        gap: 8px;
        flex-wrap: wrap;
      }
      .history-button {
        border: 1px solid #d8cce2;
        border-radius: 999px;
        padding: 7px 12px;
        color: #51415e;
        background: #fff;
        font: 600 12px/1.2 inherit;
        cursor: pointer;
      }
      .assessment-history, .history-detail {
        margin: 0 12px 10px;
        padding: 12px;
        border: 1px solid #e8deed;
        border-radius: 12px;
        background: #fff;
        max-height: 260px;
        overflow-y: auto;
      }
      .assessment-history[hidden], .history-detail[hidden] { display: none !important; }
      .history-heading { margin: 0 0 10px; font-size: 13px; font-weight: 700; color: #342b3b; }
      .history-item { padding: 9px 0; border-top: 1px solid #eee8f1; display: grid; gap: 5px; }
      .history-item:first-of-type { border-top: 0; }
      .history-meta { color: #766b7d; font-size: 11px; }
      .history-view, .history-back {
        justify-self: start;
        border: 0;
        border-radius: 7px;
        padding: 6px 10px;
        color: #fff;
        background: #7135ce;
        font: 600 11px/1.2 inherit;
        cursor: pointer;
      }
      .history-summary {
        margin: 10px 0 12px;
        padding: 10px;
        border-radius: 9px;
        background: #faf7fc;
        color: #342b3b;
        font-size: 12px;
        line-height: 1.5;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }
      .history-transcript { display: grid; gap: 8px; }
      .history-message { white-space: pre-wrap; overflow-wrap: anywhere; padding: 8px 10px; border-radius: 10px; font-size: 12px; }
      .history-message.user { margin-left: 18%; background: #7135ce; color: #fff; }
      .history-message.assistant { margin-right: 8%; background: #f5f1f7; color: #342b3b; }
      .history-empty { color: #766b7d; font-size: 12px; }
      .assessment-actions[hidden] { display: none !important; }
      .new-assessment-button {
        border: 1px solid #8b65a7;
        border-radius: 999px;
        padding: 7px 12px;
        color: #6020cf;
        background: #fff;
        font: 600 12px/1.2 inherit;
        cursor: pointer;
      }
      .new-assessment-button:disabled { opacity: .55; cursor: wait; }

      .msg {
        max-width: 88%;
        padding: 10px 12px;
        border-radius: 13px;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }

      .bot {
        align-self: flex-start;
        background: #fff;
        border: 1px solid #ece3f0;
        border-bottom-left-radius: 4px;
      }

      .user {
        align-self: flex-end;
        color: #fff;
        background: #6a3f96;
        border-bottom-right-radius: 4px;
      }

      .thinking {
        color: #665f70;
        font-style: italic;
      }

      .error {
        background: #fbf1ea;
        color: #a9552e;
        border-color: #e8cdb8;
      }

      .products {
        width: 100%;
        display: flex;
        flex-direction: column;
        gap: 9px;
      }

      .product-card {
        background: #fff;
        border: 1px solid #e7ddea;
        border-radius: 12px;
        padding: 10px;
      }

      .product-card h3 {
        margin: 0 0 4px;
        font-size: 13px;
      }

      .product-card p {
        margin: 0 0 7px;
        color: #665f70;
        font-size: 11px;
      }

      .product-card a {
        display: inline-block;
        text-decoration: none;
        font-weight: 600;
        font-size: 11px;
        color: #a82e78;
      }

      form {
        display: flex;
        gap: 8px;
        padding: 11px;
        background: #fff;
        border-top: 1px solid #ece3f0;
      }

      input {
        min-width: 0;
        flex: 1;
        border: 1px solid #e2d8e7;
        border-radius: 999px;
        padding: 11px 13px;
        background: #fff;
        color: #241f2b;
        font: inherit;
        outline: none;
      }

      input:focus {
        border-color: #6a3f96;
        box-shadow: 0 0 0 2px rgba(106,63,150,.12);
      }

      button.send {
        width: 42px;
        height: 42px;
        border: 0;
        border-radius: 50%;
        background: linear-gradient(135deg, #8134ed, #6020cf);
        color: #fff;
        cursor: pointer;
        font-size: 21px;
        font-weight: 700;
        line-height: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0;
      }

      button:disabled, input:disabled {
        opacity: .55;
        cursor: not-allowed;
      }

      .status {
        min-height: 16px;
        padding: 0 14px 7px;
        color: #6c6573;
        font-size: 10px;
        background: #fff;
      }

      @media (max-width: 560px) {
        .launcher { right: 16px; bottom: 16px; }

        .panel {
          right: 0;
          bottom: 0;
          width: 100vw;
          height: 100dvh;
          max-height: 100dvh;
          min-height: 0;
          border-radius: 0;
        }
      }
    </style>

    <button class="launcher" type="button" aria-label="Open GutGPT" aria-expanded="false">
      <span class="launcher-mark" aria-hidden="true"><span></span></span>
    </button>

    <section class="panel" role="dialog" aria-label="GutGPT" aria-modal="false">
      <header class="head">
        <div class="head-copy">
          <h2>GutGPT</h2>
          <p>Guttify's gut-health assistant</p>
        </div>
        <div class="head-actions">
          <button class="close" type="button" aria-label="Close GutGPT">×</button>
        </div>
      </header>

      <section class="customer-intake" aria-label="Customer details">
        <h3 class="intake-title">Before we begin</h3>
        <p class="intake-copy">Please share a few details so GutGPT can start your gut-health assessment.</p>
        <form class="intake-form" autocomplete="on">
          <label>Full name<input name="name" type="text" maxlength="100" autocomplete="name" required placeholder="Your name" /></label>
          <label>Age<input name="age" type="number" min="1" max="120" inputmode="numeric" required placeholder="Your age" /></label>
          <label>Contact number<input name="contact" type="text" inputmode="numeric" pattern="[0-9]{7,15}" minlength="7" maxlength="15" autocomplete="tel" required placeholder="Digits only (7–15 digits)" /></label>
          <label>Location<input name="city" type="text" maxlength="100" autocomplete="address-level2" required placeholder="Your location" /></label>
          <label class="consent-row"><input name="consent" type="checkbox" required /><span>I agree to have these details stored to support this assessment.</span></label>
          <p class="intake-error" aria-live="polite" hidden></p>
          <button class="intake-submit" type="submit">Save details and continue</button>
        </form>
      </section>
      <main class="messages" aria-live="polite" aria-label="GutGPT conversation" hidden></main>
      <div class="assessment-actions" hidden>
        <button class="history-button" type="button">Assessment History</button>
        <button class="new-assessment-button" type="button">＋ Start a New Assessment</button>
      </div>
      <section class="assessment-history" aria-label="Assessment history" hidden>
        <h3 class="history-heading">Your previous assessments</h3>
        <div class="history-list"></div>
      </section>
      <section class="history-detail" aria-label="Previous assessment details" hidden>
        <button class="history-back" type="button">← Back to current chat</button>
        <h3 class="history-heading history-detail-title"></h3>
        <div class="history-summary"></div>
        <h4 class="history-heading">Full conversation</h4>
        <div class="history-transcript"></div>
      </section>
      <div class="status" aria-live="polite"></div>

      <form class="composer" autocomplete="off" hidden>
        <input
          type="text"
          maxlength="4000"
          placeholder="Tell me what you're experiencing…"
          aria-label="Message GutGPT"
          required
        />
        <button class="send" type="submit" aria-label="Send message">✓</button>
      </form>
    </section>
  `;

  const $ = (selector) => shadow.querySelector(selector);
  const launcher = $(".launcher");
  const panel = $(".panel");
  const messages = $(".messages");
  const assessmentActions = $(".assessment-actions");
  const newAssessmentButton = $(".new-assessment-button");
  const historyButton = $(".history-button");
  const assessmentHistory = $(".assessment-history");
  const historyList = $(".history-list");
  const historyDetail = $(".history-detail");
  const historyDetailTitle = $(".history-detail-title");
  const historySummary = $(".history-summary");
  const historyTranscript = $(".history-transcript");
  const historyBack = $(".history-back");
  const intake = $(".customer-intake");
  const intakeForm = $(".intake-form");
  const intakeSubmit = $(".intake-submit");
  const intakeError = $(".intake-error");
  const form = $(".composer");
  const input = $(".composer input");
  const sendButton = $(".send");
  const status = $(".status");
  // GutGPT is English-only. The widget always sends English and never
  // translates user messages or bot responses.
  const language = "en";

  const UI_TEXT = {
    en: {
      greeting: (name) => `Hi ${name}! I'm GutGPT, Guttify's gut-health assessment assistant. Tell me what you're experiencing.`,
      placeholder: "Tell me what you're experiencing…",
      aria: "Message GutGPT",
      saving: "Saving your details…",
      validation: "Please complete every field and agree to the storage notice.",
      retry: "I couldn't safely restore your GutGPT session right now. Please retry.",
      intakeTitle: "Before we begin", intakeCopy: "Please share a few details so GutGPT can start your gut-health assessment.",
      labels: ["Full name", "Age", "Contact number", "Location"], consent: "I agree to have these details stored to support this assessment.",
      save: "Save details and continue", restored: (name) => `Welcome back, ${name}! Your profile is restored. You can start a new assessment.`,
      resumed: (name) => `Welcome back, ${name}! I've restored your unfinished assessment so you can continue.`,
      retryAssessment: "I couldn't recover your assessment progress. Your assessment has not been restarted. Please retry."
    }
  };
  function currentText() { return UI_TEXT[language] || UI_TEXT.en; }
  function applyLanguage() {
    const t = currentText();
    input.placeholder = t.placeholder;
    input.setAttribute("aria-label", t.aria);
    const title = $(".intake-title"), copy = $(".intake-copy");
    if (title) title.textContent = t.intakeTitle;
    if (copy) copy.textContent = t.intakeCopy;
    const labels = intakeForm.querySelectorAll("label:not(.consent-row)");
    labels.forEach((label, index) => {
      const textNode = Array.from(label.childNodes).find(node => node.nodeType === Node.TEXT_NODE);
      if (textNode && t.labels[index]) textNode.textContent = t.labels[index];
    });
    const consent = intakeForm.querySelector(".consent-row span");
    if (consent) consent.textContent = t.consent;
    if (intakeSubmit) intakeSubmit.textContent = t.save;
  }
  applyLanguage();

  let sessionId = null;
  const SESSION_ID_STORAGE_KEY = "gutgpt_session_id_v1";
  function getStoredSessionId() {
    try { return window.sessionStorage.getItem(SESSION_ID_STORAGE_KEY) || ""; } catch (_) { return ""; }
  }
  function setStoredSessionId(value) {
    try { window.sessionStorage.setItem(SESSION_ID_STORAGE_KEY, value); } catch (_) {}
  }
  let initSessionPromise = null;
  let customerRegistered = false;
  const GUEST_TOKEN_STORAGE_KEY = "gutgpt_guest_token_v1";
  // Guest JWTs are now held in a persistent HttpOnly cookie by the API.
  // sessionStorage is read only as a one-time migration path for older tabs.
  try { window.localStorage.removeItem(GUEST_TOKEN_STORAGE_KEY); } catch (_) {}
  try { window.localStorage.removeItem("gutgpt_customer_id_v1"); } catch (_) {}
  function getLegacyGuestToken() {
    try { return window.sessionStorage.getItem(GUEST_TOKEN_STORAGE_KEY) || ""; } catch (_) { return ""; }
  }
  function clearLegacyGuestToken() {
    try { window.sessionStorage.removeItem(GUEST_TOKEN_STORAGE_KEY); } catch (_) {}
  }
  let busy = false;
  let ended = false;

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value ?? "");
    return div.innerHTML;
  }

  const BRISTOL_STOOL_CHART_URL = `${GUTGPT_API_URL}/assets/bristol-stool-chart.png`;

  function renderMarkdown(value) {
    let html = escapeHtml(value);
    // This exact marker is authored only by the backend questionnaire. The
    // source is an embedded static image, not user-controlled HTML.
    html = html.replace(
      "[[BRISTOL_STOOL_CHART]]",
      `<img class="bristol-stool-chart" src="${BRISTOL_STOOL_CHART_URL}" alt="Bristol Stool Chart showing stool types 1 through 7" loading="eager"><div class="bristol-options" aria-label="Choose your Bristol stool type">${[1,2,3,4,5,6,7].map(type => `<button type="button" data-bristol-type="${type}" aria-label="Select Bristol stool type ${type}">Type ${type}</button>`).join("")}</div>`
    );
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  function addMessage(text, sender, variant = "") {
    const el = document.createElement("div");
    el.className = `msg ${sender} ${variant}`.trim();

    if (sender === "bot") {
      el.innerHTML = renderMarkdown(text);
    } else {
      el.textContent = text;
    }

    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
    return el;
  }

  function addProducts(products) {
    if (!Array.isArray(products) || products.length === 0) return;

    const wrap = document.createElement("div");
    wrap.className = "products";

    products.forEach((product) => {
      const card = document.createElement("article");
      card.className = "product-card";

      const title = document.createElement("h3");
      title.textContent = product.product_name || "Guttify product";

      const description = document.createElement("p");
      const support = Array.isArray(product.intended_support)
        ? product.intended_support[0]
        : "";
      description.textContent = support || "";

      card.append(title, description);

      const url = product.product_url || product.url;
      if (typeof url === "string" && /^https?:\/\//i.test(url)) {
        const link = document.createElement("a");
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "View Product";
        card.appendChild(link);
      }

      wrap.appendChild(card);
    });

    messages.appendChild(wrap);
    messages.scrollTop = messages.scrollHeight;
  }

  function setBusy(value) {
    busy = value;
    input.disabled = value || ended;
    sendButton.disabled = value || ended;
  }

  function showError(message) {
    addMessage(message, "bot", "error");
  }

  async function fetchJson(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const response = await fetch(`${GUTGPT_API_URL}${path}`, {
        credentials: "include",
        ...options,
        signal: controller.signal,
      });

      if (!response.ok) {
        let serverMessage = "";
        try {
          const errorData = await response.json();
          serverMessage = typeof errorData.detail === "string" ? errorData.detail : "";
        } catch (_) {
          // Keep the HTTP status as the fallback error.
        }
        const error = new Error(`HTTP_${response.status}`);
        error.status = response.status;
        error.serverMessage = serverMessage;
        throw error;
      }

      const data = await response.json();
      if (!data || typeof data !== "object") {
        throw new Error("INVALID_RESPONSE");
      }
      return data;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function _initSession() {
    // Do not accept chat input until customer restoration and assessment resume
    // have both completed. A resume failure is not the same as no active assessment.
    sessionId = null;
    status.textContent = "Connecting…";
    customerRegistered = false;
    intake.hidden = false;
    messages.hidden = true;
    form.hidden = true;
    input.disabled = true;
    let resumeFailed = false;

    try {
      // Prefer restoring an existing browser session before considering creation.
      // A new session is permitted only when no stored session exists or the
      // backend explicitly confirms that the stored session expired (HTTP 410).
      const existingSessionId = getStoredSessionId();
      const guestToken = getLegacyGuestToken();
      let restored;

      if (existingSessionId) {
        sessionId = existingSessionId;
        try {
          restored = await fetchJson("/api/customer/restore", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId, guest_token: guestToken }),
          });
        } catch (restoreError) {
          // Network errors, rate limits, server errors and DB failures are not
          // authoritative proof of expiry. Do not replace the stored session
          // unless the backend explicitly returns HTTP 410 for that session.
          if (existingSessionId && restoreError?.status === 410) {
            const created = await fetchJson("/api/session", { method: "POST" });
            if (typeof created.session_id !== "string" || !created.session_id) throw new Error("INVALID_SESSION");
            sessionId = created.session_id;
            restored = await fetchJson("/api/customer/restore", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ session_id: sessionId, guest_token: guestToken }),
            });
          } else {
            // Only clear a credential when the server explicitly rejects it.
            if (restoreError?.status === 401) {
              clearLegacyGuestToken();
              status.textContent = "";
              intake.hidden = false;
              messages.hidden = true;
              form.hidden = true;
              input.disabled = true;
              return;
            }
            throw restoreError;
          }
        }
      } else {
        // First visit: there is no existing session to restore, so create one.
        const created = await fetchJson("/api/session", { method: "POST" });
        if (typeof created.session_id !== "string" || !created.session_id) throw new Error("INVALID_SESSION");
        sessionId = created.session_id;
        setStoredSessionId(sessionId);
        try {
          restored = await fetchJson("/api/customer/restore", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId, guest_token: guestToken }),
          });
        } catch (restoreError) {
          if (restoreError?.status === 401) {
            clearLegacyGuestToken();
            status.textContent = "";
            intake.hidden = false;
            messages.hidden = true;
            form.hidden = true;
            input.disabled = true;
            intakeError.hidden = true;
            return;
          }
          throw restoreError;
        }
      }
      setStoredSessionId(sessionId);

      if (!restored || restored.status !== "RESTORED") {
        // Do not infer that registration is needed from an unexpected response.
        throw new Error("CUSTOMER_RESTORE_INVALID_RESPONSE");
      }

      clearLegacyGuestToken();
      customerRegistered = true;
      intake.hidden = true;
      messages.hidden = false;
      assessmentActions.hidden = false;
      form.hidden = true;
      input.disabled = true;

      let resume;
      try {
        resume = await fetchJson("/api/customer/resume", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId }),
        });
      } catch (resumeError) {
        console.error("GutGPT assessment resume failed", resumeError);
        resumeFailed = true;
      }

      const safeName = String(restored.customer?.name || "there").replace(/[<>]/g, "");
      if (resumeFailed || !resume || !["RESUMED", "NO_ACTIVE_ASSESSMENT"].includes(resume.status)) {
        // Fail closed: do not expose the answer form or create a new assessment.
        form.hidden = true;
        input.disabled = true;
        addMessage(
          currentText().retryAssessment,
          "bot"
        );
        status.textContent = "Saved assessment progress could not be recovered. Chat is paused to protect your existing assessment.";
        return;
      }

      if (resume.status === "RESUMED") {
        if (!(resume.status === "RESUMED" && Array.isArray(resume.messages)) || typeof resume.assessment_id !== "string" || !resume.assessment_id) {
          console.error("GutGPT resume response is missing assessment data");
          form.hidden = true;
          input.disabled = true;
          addMessage(
            "Welcome back, " + safeName + ". The server response did not contain valid assessment details. Your assessment has not been restarted. Please refresh to retry.",
            "bot"
          );
          status.textContent = "Assessment restoration is incomplete. Chat is paused.";
          return;
        }

        addMessage(currentText().resumed(safeName), "bot");
        for (const item of resume.messages) {
          if (item && (item.role === "user" || item.role === "assistant") && typeof item.content === "string") {
            addMessage(item.content, item.role === "assistant" ? "bot" : "user");
          }
        }
        // A checkpoint may contain an active next question that was not yet
        // appended to the durable transcript. Restore that prompt from the
        // backend's deterministic state, rather than inferring it from text.
        const pendingQuestion = resume.pending_question;
        if (pendingQuestion && typeof pendingQuestion.text === "string" && pendingQuestion.text.trim()) {
          let pendingText = pendingQuestion.text;
          if (pendingQuestion.display_asset === "bristol_stool_chart"
              && !pendingText.includes("[[BRISTOL_STOOL_CHART]]")) {
            pendingText = "[[BRISTOL_STOOL_CHART]]\n" + pendingText;
          }
          const lastAssistant = [...resume.messages].reverse().find(
            (item) => item && item.role === "assistant" && typeof item.content === "string"
          );
          const withoutChartMarker = (value) => String(value || "")
            .replace("[[BRISTOL_STOOL_CHART]]", "")
            .trim();
          if (lastAssistant && withoutChartMarker(lastAssistant.content) === withoutChartMarker(pendingText)) {
            // If the saved transcript contains the prompt but predates the
            // chart marker, enrich that existing bubble rather than duplicate it.
            if (pendingQuestion.display_asset === "bristol_stool_chart"
                && !lastAssistant.content.includes("[[BRISTOL_STOOL_CHART]]")) {
              const lastBot = [...messages.querySelectorAll(".msg.bot")].reverse()[0];
              if (lastBot) lastBot.innerHTML = renderMarkdown(pendingText);
            }
          } else {
            addMessage(pendingText, "bot");
          }
        }
        // An empty transcript is still a resumed assessment if the backend has
        // returned its canonical assessment ID; do not silently start over.
        form.hidden = false;
        input.disabled = false;
        status.textContent = "";
        input.focus();
        return;
      }

      else if (resume.status === "NO_ACTIVE_ASSESSMENT") {
        // Only this explicit backend status permits the new-assessment welcome.
        addMessage(currentText().restored(safeName), "bot");
        form.hidden = false;
        input.disabled = false;
        status.textContent = "";
        input.focus();
        return;
      }

      // Unknown status is an error, not proof that no assessment exists.
      console.error("Unexpected GutGPT resume status", resume.status);
      form.hidden = true;
      input.disabled = true;
      addMessage(
        "Welcome back, " + safeName + ". I couldn't verify your saved assessment status. Your assessment has not been restarted. Please refresh to retry.",
        "bot"
      );
      status.textContent = "Assessment status could not be verified. Chat is paused.";
    } catch (error) {
      console.error("GutGPT session initialization failed", error);
      status.textContent = "";
      input.disabled = true;
      form.hidden = true;
      intakeError.textContent = currentText().retry;
      intakeError.hidden = false;
    }
  }

  function initSession() {
    if (initSessionPromise) return initSessionPromise;
    initSessionPromise = _initSession().finally(() => { initSessionPromise = null; });
    return initSessionPromise;
  }

  const contactInput = intakeForm.querySelector('input[name="contact"]');
  contactInput.addEventListener("input", () => { contactInput.value = contactInput.value.replace(/[^0-9]/g, "").slice(0, 15); });

  intakeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !sessionId || customerRegistered) return;
    const formData = new FormData(intakeForm);
    const customer = {
      session_id: sessionId,
      name: String(formData.get("name") || "").trim(),
      age: Number(formData.get("age")),
      contact: String(formData.get("contact") || "").trim(),
      city: String(formData.get("city") || "").trim(),
      consent: formData.get("consent") === "on",
    };
    if (!customer.name || !Number.isInteger(customer.age) || customer.age < 1 || customer.age > 120 || !/^[0-9]{7,15}$/.test(customer.contact) || !customer.city || !customer.consent) {
      intakeError.textContent = currentText().validation;
      intakeError.hidden = false;
      return;
    }
    busy = true;
    intakeSubmit.disabled = true;
    intakeError.hidden = true;
    status.textContent = currentText().saving;
    try {
      const data = await fetchJson("/api/customer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(customer),
      });
      if (data.status !== "REGISTERED") throw new Error("REGISTRATION_FAILED");
      customerRegistered = true;
      clearLegacyGuestToken();
      intake.hidden = true;
      messages.hidden = false;
      form.hidden = false;
      input.disabled = false;
      sendButton.disabled = false;
      status.textContent = "";
      addMessage(currentText().greeting(customer.name.replace(/[<>]/g, "")), "bot");
      applyLanguage();
      input.focus();
    } catch (error) {
      console.error("GutGPT customer registration failed", error);
      if (error?.status === 410) {
        intakeError.textContent = "Your session expired. Please refresh the page and try again.";
      } else if (error?.serverMessage === "CUSTOMER_REGISTRATION_REQUIRED") {
        intakeError.textContent = "Please submit your customer details before continuing.";
      } else {
        intakeError.textContent = error?.serverMessage || "We couldn't save your details. Please check them and try again.";
      }
      intakeError.hidden = false;
    } finally {
      busy = false;
      intakeSubmit.disabled = false;
      status.textContent = "";
    }
  });

  function formatHistoryDate(value) {
    if (!value) return "Date unavailable";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toLocaleString();
  }

  async function loadAssessmentHistory() {
    if (!sessionId || !customerRegistered) throw new Error("CUSTOMER_SESSION_REQUIRED");
    const data = await fetchJson("/api/customer/assessments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (data.status !== "OK" || !Array.isArray(data.assessments)) {
      throw new Error("ASSESSMENT_HISTORY_INVALID_RESPONSE");
    }
    historyList.replaceChildren();
    if (data.assessments.length === 0) {
      const empty = document.createElement("p");
      empty.className = "history-empty";
      empty.textContent = "No previous assessments yet. Your completed and in-progress assessments will appear here.";
      historyList.appendChild(empty);
      return;
    }

    for (const item of data.assessments) {
      const row = document.createElement("article");
      row.className = "history-item";
      const title = document.createElement("strong");
      title.textContent = item.summary || "Gut-health assessment";
      const meta = document.createElement("span");
      meta.className = "history-meta";
      const statusLabel = String(item.status || "saved").replaceAll("_", " ");
      meta.textContent = `${statusLabel} · ${formatHistoryDate(item.started_at)}`;
      const view = document.createElement("button");
      view.type = "button";
      view.className = "history-view";
      view.textContent = "View summary & conversation";
      view.addEventListener("click", () => viewAssessmentHistoryItem(item.assessment_id));
      row.append(title, meta, view);
      historyList.appendChild(row);
    }
  }

  async function viewAssessmentHistoryItem(assessmentId) {
    if (!sessionId || !assessmentId) return;
    status.textContent = "Loading saved assessment…";
    historyButton.disabled = true;
    newAssessmentButton.disabled = true;
    try {
      const data = await fetchJson("/api/customer/assessments/detail", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, assessment_id: assessmentId }),
      });
      if (data.status !== "OK" || !data.assessment || !Array.isArray(data.messages)) {
        throw new Error("ASSESSMENT_DETAIL_INVALID_RESPONSE");
      }

      historyDetailTitle.textContent = `${data.assessment.summary || "Gut-health assessment"} · ${String(data.assessment.status || "saved").replaceAll("_", " ")}`;
      historySummary.textContent = data.symptom_summary || "No symptom summary was saved for this assessment.";
      historyTranscript.replaceChildren();
      if (data.messages.length === 0) {
        const empty = document.createElement("p");
        empty.className = "history-empty";
        empty.textContent = "No conversation messages were saved for this assessment.";
        historyTranscript.appendChild(empty);
      } else {
        for (const message of data.messages) {
          const bubble = document.createElement("div");
          bubble.className = `history-message ${message.role === "user" ? "user" : "assistant"}`;
          bubble.textContent = message.content || "";
          historyTranscript.appendChild(bubble);
        }
      }

      messages.hidden = true;
      form.hidden = true;
      assessmentHistory.hidden = true;
      historyDetail.hidden = false;
      status.textContent = "";
    } catch (error) {
      console.error("GutGPT assessment history detail failed", error);
      status.textContent = "I couldn't load that saved assessment. Please try again.";
    } finally {
      historyButton.disabled = false;
      newAssessmentButton.disabled = false;
    }
  }

  historyButton.addEventListener("click", async () => {
    if (historyButton.disabled || !sessionId || !customerRegistered) return;
    const shouldOpen = assessmentHistory.hidden;
    historyDetail.hidden = true;
    if (!shouldOpen) {
      assessmentHistory.hidden = true;
      return;
    }
    historyButton.disabled = true;
    status.textContent = "Loading assessment history…";
    try {
      await loadAssessmentHistory();
      assessmentHistory.hidden = false;
      status.textContent = "";
    } catch (error) {
      console.error("GutGPT assessment history load failed", error);
      status.textContent = "Assessment history is temporarily unavailable. Please try again.";
    } finally {
      historyButton.disabled = false;
    }
  });

  historyBack.addEventListener("click", () => {
    historyDetail.hidden = true;
    assessmentHistory.hidden = true;
    messages.hidden = false;
    form.hidden = false;
    input.disabled = busy || ended;
    messages.scrollTop = messages.scrollHeight;
  });

  newAssessmentButton.addEventListener("click", async () => {
    if (busy || !sessionId || !customerRegistered) return;
    newAssessmentButton.disabled = true;
    input.disabled = true;
    status.textContent = "Starting a new assessment…";
    try {
      const created = await fetchJson("/api/session/new-assessment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      if (created?.status !== "CREATED" || typeof created.session_id !== "string" || !created.session_id) {
        throw new Error("NEW_ASSESSMENT_INVALID_RESPONSE");
      }

      // Adopt the new session only after the server confirms creation.
      sessionId = created.session_id;
      setStoredSessionId(sessionId);
      ended = false;
      assessmentHistory.hidden = true;
      historyDetail.hidden = true;
      messages.hidden = false;
      messages.replaceChildren();
      addMessage(
        "Your previous assessment has been preserved. Let's begin a new assessment. What digestive concern would you like help with?",
        "bot"
      );
      form.hidden = false;
      input.disabled = false;
      status.textContent = "";
      input.focus();
    } catch (error) {
      console.error("GutGPT new assessment creation failed", error);
      input.disabled = false;
      status.textContent = "I couldn't start a new assessment. Your previous assessment is safe; please try again.";
    } finally {
      newAssessmentButton.disabled = false;
    }
  });

  async function startNextAssessmentSession() {
    // Called only after the backend confirms the current assessment completed.
    // Keep the visible transcript, but route subsequent messages through a fresh
    // session so the rule engine's terminal state cannot leak into the next assessment.
    const created = await fetchJson("/api/session", { method: "POST" });
    if (typeof created.session_id !== "string" || !created.session_id) throw new Error("INVALID_SESSION");
    const nextSessionId = created.session_id;
    const guestToken = getLegacyGuestToken();
    const restored = await fetchJson("/api/customer/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: nextSessionId, guest_token: guestToken }),
    });
    if (!restored || restored.status !== "RESTORED") throw new Error("CUSTOMER_RESTORE_INVALID_RESPONSE");
    // Adopt the ID only after identity restoration succeeds.
    sessionId = nextSessionId;
    setStoredSessionId(sessionId);
    customerRegistered = true;
    ended = false;
  }

  async function sendMessage(retryingExpiredSession = false) {
    if (busy || ended || !sessionId || !customerRegistered) return;
    let retryMessage = null;

    const message = input.value.trim();
    if (!message) return;
    const messageId = (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function")
      ? globalThis.crypto.randomUUID()
      : ("msg-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2));

    addMessage(message, "user");
    input.value = "";
    setBusy(true);

    const thinking = addMessage("Thinking…", "bot", "thinking");

    try {
      const data = await fetchJson("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          language,
          message_id: messageId,
        }),
      });

      if (typeof data.reply !== "string") {
        throw new Error("INVALID_RESPONSE");
      }

      thinking.remove();
      let replyText = data.reply;
      if (data.question_metadata && data.question_metadata.display_asset === "bristol_stool_chart"
          && !replyText.includes("[[BRISTOL_STOOL_CHART]]")) {
        replyText = "[[BRISTOL_STOOL_CHART]]\n" + replyText;
      }
      const botReply = addMessage(
        replyText,
        "bot",
        data.status === "SAFETY_REVIEW" ? "error" : ""
      );

      if (
        data.status === "RECOMMENDATION_FOUND" ||
        data.status === "AMBIGUOUS"
      ) {
        addProducts(data.recommendations);
      }

      if (data.status === "SESSION_ENDED") {
        ended = true;
        status.textContent = "";
      }

      // A completed diagnosis belongs to the old session. Persist it there,
      // then establish exactly one clean session for the next assessment.
      if (data.assessment_complete === true || ["DIAGNOSIS", "RECOMMENDATION_FOUND", "AMBIGUOUS", "DIAGNOSIS_COMPLETE", "RECOMMENDATION_COMPLETE"].includes(data.status)) {
        try {
          await startNextAssessmentSession();
          status.textContent = "Ready for a new assessment.";
          // Recovery for a widget that was already sitting in a completed
          // session before this patch: retry the user's symptom exactly once
          // on the newly authenticated session instead of making them resend it.
          if (data.status === "DIAGNOSIS_COMPLETE") {
            const retryId = (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function")
              ? globalThis.crypto.randomUUID()
              : ("msg-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2));
            const retried = await fetchJson("/api/chat", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ session_id: sessionId, message, language, message_id: retryId }),
            });
            if (typeof retried.reply === "string") {
              botReply.remove();
              addMessage(retried.reply, "bot", retried.status === "SAFETY_REVIEW" ? "error" : "");
              if (["RECOMMENDATION_FOUND", "AMBIGUOUS"].includes(retried.status)) addProducts(retried.recommendations);
            }
          }
        } catch (transitionError) {
          // Keep the old ID if transition failed; never invent a successful
          // transition or clear the existing session on a temporary failure.
          console.error("GutGPT post-assessment session transition failed", transitionError);
          status.textContent = "Assessment saved. Could not start a new session yet; please retry shortly.";
        }
      }
    } catch (error) {
      console.error("GutGPT chat request failed", error);
      thinking.remove();

      if (error?.name === "AbortError") {
        showError("The request took too long. Please try again.");
      } else if (error?.serverMessage) {
        showError(error.serverMessage);
      } else if (error?.status === 410) {
        if (!retryingExpiredSession) {
          showError("This chat session expired. Starting a new session and resending your message.");
          await initSession();
          if (sessionId) retryMessage = message;
        } else {
          showError("The new chat session also expired. Please send your message again.");
        }
      } else {
        showError("Something went wrong reaching GutGPT. Please try again.");
      }
    } finally {
      setBusy(false);
      if (retryMessage && !ended) {
        input.value = retryMessage;
        // Retry at most once after creating a fresh session; a repeated 410
        // is surfaced to the user rather than entering a retry loop.
        void sendMessage(true);
      } else if (!ended) {
        input.focus();
      }
    }
  }

  launcher.addEventListener("click", () => {
    const isOpen = panel.classList.toggle("open");
    launcher.setAttribute("aria-expanded", String(isOpen));
    if (isOpen) input.focus();
  });

  $(".close").addEventListener("click", () => {
    panel.classList.remove("open");
    launcher.setAttribute("aria-expanded", "false");
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendMessage();
  });

  messages.addEventListener("error", (event) => {
    const image = event.target;
    if (!image || !image.matches || !image.matches(".bristol-stool-chart")) return;
    console.warn("GutGPT Bristol Stool Chart image failed to load");
    const fallback = document.createElement("p");
    fallback.className = "bristol-chart-fallback";
    fallback.textContent = "The chart image could not be displayed. You can still choose a Bristol type from 1 to 7 using the buttons below, or describe your stool in words.";
    image.replaceWith(fallback);
  }, true);

  messages.addEventListener("click", (event) => {
    const button = event.target && event.target.closest ? event.target.closest("[data-bristol-type]") : null;
    if (!button || !messages.contains(button) || busy || ended) return;
    const type = Number(button.getAttribute("data-bristol-type"));
    if (!Number.isInteger(type) || type < 1 || type > 7) return;
    input.value = `Bristol type ${type}`;
    void sendMessage();
  });

  // The widget performs only lightweight DOM work synchronously. Network
  // initialization is deferred so loading the Shopify page is not blocked.
  const start = () => void initSession();
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(start, { timeout: 1000 });
  } else {
    window.setTimeout(start, 0);
  }
})();
