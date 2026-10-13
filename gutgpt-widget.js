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

  let sessionId = null;
  let busy = false;
  let ended = false;

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value ?? "");
    return div.innerHTML;
  }

  const BRISTOL_STOOL_CHART_DATA_URI = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAcFBQYFBAcGBgYIBwcICxILCwoKCxYPEA0SGhYbGhkWGRgcICgiHB4mHhgZIzAkJiorLS4tGyIyNTEsNSgsLSz/2wBDAQcICAsJCxULCxUsHRkdLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCz/wAARCAMiBEwDASIAAhEBAxEB/8QAHAABAAICAwEAAAAAAAAAAAAAAAUGBAcBAgMI/8QAVhAAAQMDAQQECAcMCQQBAwQDAQACAwQFEQYHEiExE0FRcRQWIjIzYYGRCBU0UlShsRgjN0JTcnSTssHR4TU2VVZic5KU0hckQ4KiJbPCJ2Pw8WR1o//EABsBAQACAwEBAAAAAAAAAAAAAAAEBQEDBgIH/8QAMhEBAAIBAgUDAgYCAgMBAQAAAAECAwQRBRIhMTITQVEUIgYVM1JhcSOhFoFCkdGx8P/aAAwDAQACEQMRAD8A3+mURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAymURAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERB5VFVT0cXSVM8cD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mrnx573jBI9XHggjNjMUdRshtkMzGyRPD2ua4ZDgXHgQovZLDFTa011DBG2OJlaxrWNGA0eVwAUfpi1bUNF079NW6326roBI4wV00hxE0nnjOT3YWboTSWsNI68uRfDBUWa4zdJPVvlBldgHDg0csk8kGHtNsVJX7WtI0rY2wNrzIKl8Y3XStyN4EjtGR7VtmgtdBa4RDQUUFLG0BoEUYbwHIcOa1TrSwbRLptEpL1bLZQS09oe7wIvnDd9p+eMra9udVvtlM6vYyOsMbTM1hy0PxxA9WUgUjbd+Ci4/nx/tBV+07LtQXLT9AZtoF0ZSVFNG4wMHBrS0HdHHq5KZ2tWXV+pbY2zWGipZ7fOwOnfLKGPa8OyAM9WMKa2ft1ZBaDSaoo6Sl8FZHDTeDyB+81rcZdx58AjKvastFNsz2L3OmsAkY9+Gvnccvc55ALie7gpvZ/oyx2nRFvbHQU08tTA2WeaSMPdI5wyeJ71Yr/ZaXUVgrLTWA9BVRljiOY7CO4rWVsg2qaIoxZKG3W+/UEOW0tQ+TdcxnUCMjkjDi00MOjvhCvtVoHQ2+7URnlpm+axwBIIHVy+srps2tdJq3XGqdR3qFlZV01YaanjmG8IWjPIHuA96sGg9D3ei1BWas1VUxVF8rG9G2OLiynZ2A9vco676P1VpTWFZqPRAp6uC4neq7dO7dBd2tPtKDw216ft1s05Bqm3QRUN1t1TGY5YWhm+CfNIHP/8AteO26KOs2cWa5uijirZqunHT7uHtDmOOM9meK7zaY1xtGutH43wUtmslHIJTSQP3nTuHbz+tZe3unY/Z9bqceQx1zgjGOobrxwWBcbPo2w0enoqD4spp45Ih0rpIw50pI4uJPEkqkbJ4viPXmsNM0ry63UkzZIWk5DCTxA9/1LsJ9q9gom2igttvvEDGBlPcHv3XhuOG83PMKw7N9E1Ok6Gsq7rUtqrzc5OlqpG8geOGg9fNBdURF6BERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERA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ERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQf//Z";

  function renderMarkdown(value) {
    let html = escapeHtml(value);
    // This exact marker is authored only by the backend questionnaire. The
    // source is an embedded static image, not user-controlled HTML.
    html = html.replace(
      "[[BRISTOL_STOOL_CHART]]",
      `<img class="bristol-stool-chart" src="${BRISTOL_STOOL_CHART_DATA_URI}" alt="Bristol Stool Chart showing stool types 1 through 7" loading="eager">`
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
    sessionId = null;
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

  async function sendMessage(retryingExpiredSession = false) {
    if (busy || ended || !sessionId) return;
    let retryMessage = null;

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

  // The widget performs only lightweight DOM work synchronously. Network
  // initialization is deferred so loading the Shopify page is not blocked.
  const start = () => void initSession();
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(start, { timeout: 1000 });
  } else {
    window.setTimeout(start, 0);
  }
})();
