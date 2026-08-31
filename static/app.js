const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");

const feedbackOverlay = document.getElementById("feedback-overlay");
const feedbackConfirmation = document.getElementById("feedback-confirmation");
const ratingButtons = Array.from(document.querySelectorAll(".rating-btn"));

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

// Guards against the rating popup ever showing twice in one chat
// session, and against a second rating being submitted for one.
let feedbackShown = false;
let feedbackSubmitted = false;

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

    if (data.status === "SESSION_ENDED") {
      lockChat();
      showFeedbackModal();
      return; // leave the input locked — no further messages this session
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

function showFeedbackModal() {
  if (feedbackShown) return; // only ever shown once per chat session
  feedbackShown = true;
  feedbackOverlay.hidden = false;
}

function hideFeedbackModal() {
  feedbackOverlay.hidden = true;
}

ratingButtons.forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (feedbackSubmitted) return; // prevents accidental multiple submissions
    feedbackSubmitted = true;

    const rating = Number(btn.dataset.rating);
    ratingButtons.forEach((b) => {
      b.disabled = true;
      b.classList.toggle("selected", b === btn);
    });

    try {
      await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, rating }),
      });
    } catch (err) {
      console.error("Feedback submit failed:", err);
    }

    feedbackConfirmation.hidden = false;
    setTimeout(hideFeedbackModal, 1800);
  });
});

initSession();
