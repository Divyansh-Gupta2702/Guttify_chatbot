const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");

// A fresh session id every page load — refreshing the page means the
// server starts a brand-new (empty) conversation_history for this session.
let sessionId = null;

// True once the backend reports status "SESSION_ENDED" (see
// guttify_agent.py — set after a recommendation is followed by a
// satisfied/closing remark, per satisfaction_checker.py). Nothing about
// this is persisted anywhere on purpose: a page refresh re-runs this
// script from scratch, requests a brand-new session, and the chat is
// fully usable again.
let chatEnded = false;

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// Safely render a minimal subset of Markdown (bold, line breaks)
// after HTML-escaping to prevent XSS.
function renderMarkdown(text) {
  // First escape all HTML
  let html = escapeHtml(text);
  // Convert **text** to <strong>text</strong>
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // Convert line breaks to <br>
  html = html.replace(/\n/g, "<br>");
  return html;
}

// Turns any http(s)/www URL in bot text into a clickable link.
// Runs after Markdown rendering so links inside bold text work.
function linkify(text) {
  const urlPattern = /((https?:\/\/|www\.)[^\s<]+)/gi;
  return text.replace(urlPattern, (match) => {
    const href = match.startsWith("http") ? match : `https://${match}`;
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${match}</a>`;
  });
}

function addMessage(text, sender, variant = "") {
  const div = document.createElement("div");
  div.className = `msg ${sender} ${variant}`.trim();
  if (sender === "bot") {
    // Render markdown (bold, line breaks) then linkify URLs
    div.innerHTML = linkify(renderMarkdown(text));
  } else {
    div.textContent = text;
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

// Display product recommendation cards with clickable links
function addProducts(products) {
  if (!products || !products.length) return;
  const wrap = document.createElement("div");
  wrap.className = "products";
  products.forEach(p => {
    const card = document.createElement("article");
    card.className = "product-card";
    const body = document.createElement("div");
    const h = document.createElement("h3");
    h.textContent = p.product_name || "Guttify product";
    const desc = (p.intended_support && p.intended_support[0]) || "";
    const d = document.createElement("p");
    d.textContent = desc;
    body.append(h, d);
    const url = p.product_url || p.url;
    if (url) {
      const a = document.createElement("a");
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = "View Product";
      a.className = "product-link";
      body.appendChild(a);
    }
    card.appendChild(body);
    wrap.appendChild(card);
  });
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function initSession() {
  const res = await fetch("/api/session", { method: "POST" });
  const data = await res.json();
  sessionId = data.session_id;
  addMessage(
    "Hi! I'm GutGPT, Guttify's gut-health assessment assistant. Tell me what you're experiencing.",
    "bot"
  );
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  // Blocks typing/Enter/click from doing anything once the chat has
  // ended, even if the disabled attribute below was somehow bypassed
  // (e.g. a request already in flight when the chat ended).
  if (chatEnded) return;

  const message = input.value.trim();
  if (!message || !sessionId) return;

  addMessage(message, "user");
  input.value = "";
  input.disabled = true;

  const thinking = addMessage("Thinking…", "bot", "thinking");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });

    if (!res.ok) throw new Error(`Request failed: ${res.status}`);
    const data = await res.json();

    thinking.remove();
    addMessage(data.reply, "bot", data.status === "SAFETY_REVIEW" ? "safety" : "");

    // Display product cards for recommendations
    if (data.status === "RECOMMENDATION_FOUND" || data.status === "AMBIGUOUS") {
      addProducts(data.recommendations || []);
    }

    if (data.status === "SESSION_ENDED") {
      lockChat();
      return; // only explicit conversation-ending events lock the chat
    }
  } catch (err) {
    thinking.remove();
    addMessage("Something went wrong reaching the assistant. Please try again.", "bot");
  } finally {
    if (!chatEnded) {
      input.disabled = false;
      input.focus();
    }
  }
});

/** Disables the input and Send button both visually (see the
 * :disabled styling in style.css) and functionally — no further
 * /api/chat calls are made for this session once this has run. */
function lockChat() {
  chatEnded = true;
  input.disabled = true;
  form.querySelector("button[type='submit']").disabled = true;
  input.blur();
}


initSession();
