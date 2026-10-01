(() => {
  const TAG = "guttify-gutgpt";

  class GuttifyGutGPT extends HTMLElement {
    static get observedAttributes() { return ["api-url","title","subtitle","position","theme","avatar"]; }

    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this.sessionId = null;
      this.busy = false;
      this.ended = false;
    }

    connectedCallback() {
      if (this.shadowRoot.querySelector(".launcher")) return;
      this.render();
      this.bind();
      this.init();
    }

    attributeChangedCallback() {
      if (this.isConnected && this.shadowRoot.querySelector(".launcher")) this.render();
    }

    get apiUrl() { return (this.getAttribute("api-url") || "").replace(/\/+$/, ""); }
    get titleText() { return this.getAttribute("title") || "GutGPT"; }
    get subtitleText() { return this.getAttribute("subtitle") || "Your gut health assistant"; }
    get position() { return this.getAttribute("position") || "bottom-right"; }
    get avatarUrl() { 
      const base = this.getAttribute("avatar") || "/vendor/gutgpt-avatar.png";
      // Allow cache-busting via avatar-version attribute, or use a fixed version
      const version = this.getAttribute("avatar-version") || "1";
      return base + (base.includes("?") ? "&" : "?") + "v=" + version;
    }

    render() {
      const right = this.position !== "bottom-left";
      this.shadowRoot.innerHTML = `
        <style>
          :host { all: initial; }
          *, *::before, *::after { box-sizing: border-box; }
          .launcher {
            position: fixed; z-index: 2147483000; bottom: 22px; ${right ? "right:22px" : "left:22px"};
            width: 68px; height: 68px; padding: 0; border: 3px solid #fff; border-radius: 50%;
            cursor: pointer; background: linear-gradient(135deg,#7b2cff,#5d19d8);
            box-shadow:0 10px 30px rgba(50,25,70,.30), 0 0 0 4px rgba(106,63,150,.12);
            overflow: hidden; display:flex; align-items:center; justify-content:center;
            transition:transform .2s ease, box-shadow .2s ease;
          }
          .launcher:hover { transform:scale(1.06); box-shadow:0 14px 35px rgba(50,25,70,.38), 0 0 0 5px rgba(106,63,150,.16); }
          .launcher:active { transform:scale(.96); }
          .launcher img { width:100%; height:100%; object-fit:cover; display:block; border-radius:50%; }
          .panel {
            position:fixed; z-index:2147483001; bottom:92px; ${right ? "right:22px" : "left:22px"};
            width:min(390px,calc(100vw - 28px)); height:min(650px,calc(100vh - 120px));
            min-height:430px; display:none; flex-direction:column; overflow:hidden;
            border:1px solid #e8dfea; border-radius:18px; background:#faf8fb;
            box-shadow:0 20px 60px rgba(35,25,45,.22);
            color:#241f2b; font:14px/1.45 Inter,system-ui,sans-serif;
          }
          .panel.open { display:flex; }
          .head { padding:14px 16px; color:#fff; background:linear-gradient(135deg,#c93f8f,#6a3f96); display:flex; justify-content:space-between; align-items:center; }
          .head h2 { margin:0; font:600 17px/1.2 Georgia,serif; }
          .head p { margin:3px 0 0; opacity:.88; font-size:11px; }
          .close { border:0; background:transparent; color:#fff; font-size:23px; cursor:pointer; padding:2px 6px; }
          .messages { flex:1; overflow:auto; padding:16px; display:flex; flex-direction:column; gap:10px; }
          .msg { max-width:88%; padding:10px 12px; border-radius:13px; white-space:pre-wrap; overflow-wrap:anywhere; }
          .bot { align-self:flex-start; background:#fff; border:1px solid #ece3f0; border-bottom-left-radius:4px; }
          .user { align-self:flex-end; color:#fff; background:#6a3f96; border-bottom-right-radius:4px; }
          .thinking { color:#665f70; font-style:italic; }
          .safety { background:#fbf1ea; color:#a9552e; border-color:#e8cdb8; }
          .products { display:flex; flex-direction:column; gap:9px; margin-top:3px; }
          .card { background:#fff; border:1px solid #e7ddea; border-radius:12px; padding:10px; display:flex; gap:10px; align-items:center; }
          .pic { width:52px; height:52px; flex:0 0 52px; border-radius:10px; object-fit:cover; background:linear-gradient(135deg,#f3d9e9,#e5dcf0); }
          .card h3 { margin:0 0 3px; font-size:13px; }
          .card p { margin:0 0 7px; color:#665f70; font-size:11px; }
          .card a { display:inline-block; text-decoration:none; font-weight:600; font-size:11px; color:#a82e78; }
          form { display:flex; gap:8px; padding:11px; background:#fff; border-top:1px solid #ece3f0; }
          input { min-width:0; flex:1; border:1px solid #e2d8e7; border-radius:999px; padding:11px 13px; font:inherit; outline:none; }
          input:focus { border-color:#6a3f96; box-shadow:0 0 0 2px rgba(106,63,150,.12); }
          button.send { width:42px; height:42px; border:0; border-radius:50%; background:linear-gradient(135deg,#8134ed,#6020cf); color:#fff; cursor:pointer; font-size:23px; font-weight:700; line-height:1; display:flex; align-items:center; justify-content:center; padding:0; transition:transform .15s ease; }
          button.send:hover { transform:scale(1.05); }
          button.send:active { transform:scale(.94); }
          button:disabled, input:disabled { opacity:.55; cursor:not-allowed; }
          @media (max-width:560px) {
            .launcher { bottom:16px; ${right ? "right:16px" : "left:16px"}; }
            .panel { bottom:0; ${right ? "right:0" : "left:0"}; width:100vw; height:100dvh; max-height:100dvh; border-radius:0; }
          }
        </style>
        <button class="launcher" type="button" aria-label="Open GutGPT"><img src="${this.escape(this.avatarUrl)}" alt="GutGPT" /></button>
        <section class="panel" role="dialog" aria-label="${this.escape(this.titleText)}">
          <header class="head">
            <div><h2>${this.escape(this.titleText)}</h2><p>${this.escape(this.subtitleText)}</p></div>
            <button class="close" aria-label="Close">×</button>
          </header>
          <main class="messages" aria-live="polite"></main>
          <form autocomplete="off">
            <input aria-label="Message GutGPT" placeholder="Tell me what you're experiencing…" required />
            <button class="send" type="submit" aria-label="Send">✓</button>
          </form>
        </section>`;
    }

    bind() {
      const $ = s => this.shadowRoot.querySelector(s);
      $(".launcher").onclick = () => { $(".panel").classList.add("open"); $("input").focus(); };
      $(".close").onclick = () => $(".panel").classList.remove("open");
      $("form").onsubmit = e => { e.preventDefault(); this.send(); };
    }

    async init() {
      if (!this.apiUrl) { this.addMessage("GutGPT is not configured yet.", "bot", "safety"); return; }
      this.sessionId = `guttify_${crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2)}`;
      try {
        const res = await fetch(`${this.apiUrl}/api/session`, { method: "POST" });
        if (!res.ok) throw new Error("session");
        const data = await res.json();
        this.sessionId = data.session_id || this.sessionId;
        this.addMessage("Hi! I'm GutGPT, Guttify's gut-health assessment assistant. Tell me what you're experiencing.", "bot");
      } catch {
        this.addMessage("Something went wrong connecting to GutGPT. Please try again later.", "bot", "safety");
      }
    }

    async send() {
      if (this.busy || this.ended || !this.sessionId) return;
      const input = this.shadowRoot.querySelector("input");
      const text = input.value.trim();
      if (!text) return;
      this.addMessage(text, "user"); input.value = ""; input.disabled = true;
      this.busy = true;
      const thinking = this.addMessage("Thinking…", "bot", "thinking");
      try {
        const res = await fetch(`${this.apiUrl}/api/chat`, {
          method:"POST", headers:{"Content-Type":"application/json"},
          body:JSON.stringify({session_id:this.sessionId, message:text})
        });
        if (!res.ok) throw new Error("chat");
        const data = await res.json();
        thinking.remove();
        this.addMessage(data.reply || "", "bot", data.status === "SAFETY_REVIEW" ? "safety" : "");
        if (data.status === "RECOMMENDATION_FOUND" || data.status === "AMBIGUOUS") this.addProducts(data.recommendations || []);
        if (data.status === "SESSION_ENDED") this.ended = true;
      } catch {
        thinking.remove();
        this.addMessage("Something went wrong reaching the assistant. Please try again.", "bot", "safety");
      } finally {
        this.busy = false;
        input.disabled = this.ended;
        if (!this.ended) input.focus();
      }
    }

    addMessage(text, sender, variant="") {
      const el = document.createElement("div");
      el.className = `msg ${sender} ${variant}`;
      el.textContent = text;
      this.shadowRoot.querySelector(".messages").appendChild(el);
      const box = this.shadowRoot.querySelector(".messages"); box.scrollTop = box.scrollHeight;
      return el;
    }

    addProducts(products) {
      if (!products.length) return;
      const wrap = document.createElement("div"); wrap.className = "products";
      products.forEach(p => {
        const card = document.createElement("article"); card.className = "card";
        // API returns product_name, not image - use placeholder
        const placeholder=document.createElement("div"); placeholder.className="pic"; card.appendChild(placeholder);
        const body=document.createElement("div");
        const h=document.createElement("h3"); h.textContent=p.product_name || "Guttify product";
        // Use first intended_support item as description
        const desc = (p.intended_support && p.intended_support[0]) || "";
        const d=document.createElement("p"); d.textContent=desc;
        body.append(h,d);
        const url = p.product_url || p.url;
        if (url) { const a=document.createElement("a"); a.href=url; a.target="_blank"; a.rel="noopener noreferrer"; a.textContent="View Product"; body.appendChild(a); }
        card.appendChild(body); wrap.appendChild(card);
      });
      this.shadowRoot.querySelector(".messages").appendChild(wrap);
      this.shadowRoot.querySelector(".messages").scrollTop = 1e9;
    }

    escape(s) { const d=document.createElement("div"); d.textContent=s; return d.innerHTML; }
  }

  if (!customElements.get(TAG)) customElements.define(TAG, GuttifyGutGPT);
})();