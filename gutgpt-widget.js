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
      .language {
        max-width: 118px;
        border: 1px solid rgba(255,255,255,.45);
        border-radius: 8px;
        padding: 6px 8px;
        background: rgba(255,255,255,.12);
        color: #fff;
        font: 12px/1.2 Inter, system-ui, sans-serif;
        outline: none;
      }
      .language option { color: #241f2b; background: #fff; }

      .close {
        border: 0;
        background: transparent;
        color: #fff;
        font-size: 25px;
        cursor: pointer;
        padding: 2px 6px;
        line-height: 1;
      }

      .messages {
        flex: 1;
        overflow-y: auto;
        overscroll-behavior: contain;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

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
          <select class="language" aria-label="Language">
            <option value="en">English</option>
            <option value="hi">हिन्दी</option>
            
            <option value="bn">বাংলা</option>
            <option value="mr">मराठी</option>
            <option value="ta">தமிழ்</option>
            <option value="te">తెలుగు</option>
            <option value="gu">ગુજરાતી</option>
            <option value="kn">ಕನ್ನಡ</option>
            <option value="ml">മലയാളം</option>
            <option value="pa">ਪੰਜਾਬੀ</option>
            <option value="or">ଓଡ଼ିଆ</option>
          </select>
          <button class="close" type="button" aria-label="Close GutGPT">×</button>
        </div>
      </header>

      <main class="messages" aria-live="polite" aria-label="GutGPT conversation"></main>
      <div class="status" aria-live="polite"></div>

      <form autocomplete="off">
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
  const form = $("form");
  const input = $("input");
  const sendButton = $(".send");
  const status = $(".status");
  const language = $(".language");

  let sessionId = null;
  let busy = false;
  let ended = false;

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value ?? "");
    return div.innerHTML;
  }

  function renderMarkdown(value) {
    let html = escapeHtml(value);
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

  async function initSession() {
    // A page refresh must always start a completely new assessment.
    // Do not restore an old session from localStorage: the backend session
    // contains assessment-completion state.
    status.textContent = "Connecting…";

    try {
      const data = await fetchJson("/api/session", { method: "POST" });

      if (typeof data.session_id !== "string" || !data.session_id) {
        throw new Error("INVALID_SESSION");
      }

      sessionId = data.session_id;

      addMessage(
        "Hi! I'm GutGPT, Guttify's gut-health assessment assistant. Tell me what you're experiencing.",
        "bot"
      );
      status.textContent = "";
    } catch (error) {
      console.error("GutGPT session initialization failed", error);
      status.textContent = "";
      showError("I couldn't connect to GutGPT right now. Please try again.");
    }
  }

  async function sendMessage() {
    if (busy || ended || !sessionId) return;

    const message = input.value.trim();
    if (!message) return;

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
          language: language.value,
        }),
      });

      if (typeof data.reply !== "string") {
        throw new Error("INVALID_RESPONSE");
      }

      thinking.remove();
      addMessage(
        data.reply,
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
    } catch (error) {
      console.error("GutGPT chat request failed", error);
      thinking.remove();

      if (error?.name === "AbortError") {
        showError("The request took too long. Please try again.");
      } else if (error?.serverMessage) {
        // The backend may return a localized translation-unavailable message.
        // Preserve it instead of replacing it with a generic English error.
        showError(error.serverMessage);
      } else if (error?.status === 410) {
        showError("This chat session expired. A new chat session will be started.");
        await initSession();
      } else {
        showError("Something went wrong reaching GutGPT. Please try again.");
      }
    } finally {
      setBusy(false);
      if (!ended) input.focus();
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

  language.addEventListener("change", () => {
    if (busy) return;
    // A language change starts a clean assessment so state from the previous
    // language cannot leak into the new conversation.
    sessionId = null;
    ended = false;
    messages.innerHTML = "";
    void initSession();
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
