const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");

// A fresh session id every page load — refreshing the page means the
// server starts a brand-new (empty) conversation_history for this session.
let sessionId = null;

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// Turns any http(s)/www URL in bot text into a clickable link. Everything
// else is HTML-escaped first, so this cannot be used to inject markup.
function linkify(text) {
  const urlPattern = /((https?:\/\/|www\.)[^\s<]+)/gi;
  return escapeHtml(text).replace(urlPattern, (match) => {
    const href = match.startsWith("http") ? match : `https://${match}`;
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${match}</a>`;
  });
}

function addMessage(text, sender, variant = "") {
  const div = document.createElement("div");
  div.className = `msg ${sender} ${variant}`.trim();
  if (sender === "bot") {
    div.innerHTML = linkify(text);
  } else {
    div.textContent = text;
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

async function initSession() {
  const res = await fetch("/api/session", { method: "POST" });
  const data = await res.json();
  sessionId = data.session_id;
  addMessage(
    "Hi! I'm Guttify's product recommendation assistant. Tell me what you're experiencing.",
    "bot"
  );
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
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
  } catch (err) {
    thinking.remove();
    addMessage("Something went wrong reaching the assistant. Please try again.", "bot");
  } finally {
    input.disabled = false;
    input.focus();
  }
});

initSession();
