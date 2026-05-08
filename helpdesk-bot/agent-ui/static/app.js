// HelpdeskBot demo — front-end controller.
// Vanilla JS to keep the demo dependency-free. Talks to /api/* on the
// FastAPI backend; the cookie set by /api/chat preserves agent
// conversation state across turns.

(() => {
  "use strict";

  const messagesEl = document.getElementById("messages");
  const composerEl = document.getElementById("composer");
  const inputEl = document.getElementById("composer-input");
  const sendBtn = document.getElementById("send-btn");
  const statusPill = document.getElementById("status-pill");
  const ticketListEl = document.getElementById("ticket-list");
  const refreshTicketsBtn = document.getElementById("refresh-tickets");
  const resetBtn = document.getElementById("reset-conversation");
  const ticketModal = document.getElementById("ticket-modal");
  const ticketModalTitle = document.getElementById("ticket-modal-title");
  const ticketModalFrom = document.getElementById("ticket-modal-from");
  const ticketModalSubject = document.getElementById("ticket-modal-subject");
  const ticketModalBody = document.getElementById("ticket-modal-body");
  const ticketModalClose = document.getElementById("ticket-modal-close");
  const ticketModalQuote = document.getElementById("ticket-modal-quote");

  let modalTicketId = null;
  let firstMessage = true;
  let busy = false;

  // ---- Status helpers ----

  function setStatus(label, kind) {
    statusPill.textContent = label;
    statusPill.className = `status-pill ${kind}`;
  }

  // ---- Tickets sidebar ----

  async function loadTickets() {
    try {
      const res = await fetch("/api/tickets");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const tickets = await res.json();
      renderTickets(tickets);
    } catch (err) {
      ticketListEl.innerHTML =
        `<li style="color:var(--danger);font-size:12px;">Failed to load tickets: ${escapeHtml(
          err.message,
        )}</li>`;
    }
  }

  function renderTickets(tickets) {
    if (!tickets.length) {
      ticketListEl.innerHTML =
        '<li style="color:var(--text-subtle);font-size:12px;font-style:italic;">No tickets in the store.</li>';
      return;
    }
    ticketListEl.innerHTML = "";
    for (const t of tickets) {
      const li = document.createElement("li");
      li.innerHTML = `
        <div class="ticket-id">${escapeHtml(t.id)}</div>
        <div class="ticket-subject">${escapeHtml(t.subject)}</div>
        <div class="ticket-from">${escapeHtml(t.sender)}</div>
      `;
      li.addEventListener("click", () => openTicketModal(t.id));
      ticketListEl.appendChild(li);
    }
  }

  async function openTicketModal(ticketId) {
    try {
      const res = await fetch(`/api/tickets/${encodeURIComponent(ticketId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const t = await res.json();
      modalTicketId = t.id;
      ticketModalTitle.textContent = t.id;
      ticketModalFrom.textContent = t.sender;
      ticketModalSubject.textContent = t.subject;
      ticketModalBody.textContent = t.body;
      ticketModal.classList.remove("hidden");
    } catch (err) {
      console.error(err);
    }
  }

  function closeTicketModal() {
    ticketModal.classList.add("hidden");
    modalTicketId = null;
  }

  ticketModalClose.addEventListener("click", closeTicketModal);
  ticketModal.addEventListener("click", (e) => {
    if (e.target === ticketModal) closeTicketModal();
  });
  ticketModalQuote.addEventListener("click", () => {
    if (modalTicketId) {
      inputEl.value = `Take care of ticket ${modalTicketId}`;
      autosizeInput();
      inputEl.focus();
    }
    closeTicketModal();
  });
  refreshTicketsBtn.addEventListener("click", loadTickets);

  // ---- Messages ----

  function clearEmptyState() {
    if (firstMessage) {
      messagesEl.innerHTML = "";
      firstMessage = false;
    }
  }

  function addUserMessage(text) {
    clearEmptyState();
    const wrap = document.createElement("div");
    wrap.className = "message user";
    wrap.innerHTML = `
      <div class="role-label">You</div>
      <div class="bubble"></div>
    `;
    wrap.querySelector(".bubble").textContent = text;
    messagesEl.appendChild(wrap);
    scrollToBottom();
  }

  function addAgentMessage(reply, toolCalls) {
    clearEmptyState();
    const wrap = document.createElement("div");
    wrap.className = "message agent";

    const label = document.createElement("div");
    label.className = "role-label";
    label.textContent = "HelpdeskBot";
    wrap.appendChild(label);

    const bubble = document.createElement("div");
    bubble.className = "bubble markdown";
    bubble.innerHTML = renderMarkdown(reply || "_(empty response)_");
    wrap.appendChild(bubble);

    wrap.appendChild(renderToolCallsBlock(toolCalls));

    messagesEl.appendChild(wrap);
    scrollToBottom();
  }

  function renderMarkdown(src) {
    // marked + DOMPurify are loaded globally from the CDN scripts in index.html.
    // Fall back to plain text if either fails to load (e.g. offline).
    if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
      const pre = document.createElement("div");
      pre.textContent = src;
      return pre.innerHTML;
    }
    const html = marked.parse(src, { breaks: true, gfm: true });
    return DOMPurify.sanitize(html);
  }

  function addErrorMessage(text) {
    clearEmptyState();
    const wrap = document.createElement("div");
    wrap.className = "message error";
    wrap.innerHTML = `
      <div class="role-label">Error</div>
      <div class="bubble"></div>
    `;
    wrap.querySelector(".bubble").textContent = text;
    messagesEl.appendChild(wrap);
    scrollToBottom();
  }

  function renderToolCallsBlock(toolCalls) {
    const container = document.createElement("div");
    container.className = "tool-calls";
    const count = toolCalls?.length || 0;

    const header = document.createElement("div");
    header.className = "tool-calls-header";
    header.innerHTML = `
      <span class="chevron">▶</span>
      <span class="tool-calls-title">Tool calls</span>
      <span class="tool-calls-count">${count}</span>
    `;
    container.appendChild(header);

    const body = document.createElement("div");
    body.className = "tool-calls-body";

    if (count === 0) {
      const empty = document.createElement("div");
      empty.className = "no-tools";
      empty.textContent = "The agent did not invoke any tools on this turn.";
      body.appendChild(empty);
    } else {
      toolCalls.forEach((tc, i) => {
        body.appendChild(renderToolCall(tc, i + 1, count));
      });
    }
    container.appendChild(body);

    header.addEventListener("click", () => {
      container.classList.toggle("open");
    });

    // Auto-open when there are tool calls so the dev sees them immediately.
    if (count > 0) container.classList.add("open");

    return container;
  }

  function renderToolCall(tc, index, total) {
    const card = document.createElement("div");
    card.className = "tool-call";

    const name = document.createElement("div");
    name.className = "tool-call-name";
    name.innerHTML = `
      <span class="icon"></span>
      <span class="fn">${escapeHtml(tc.name)}</span>
      <span class="step">step ${index} / ${total}</span>
    `;
    card.appendChild(name);

    const args = tc.arguments || {};
    if (Object.keys(args).length === 0) {
      const note = document.createElement("div");
      note.className = "kv-list";
      note.innerHTML = '<span class="k">arguments</span><span class="v null">(none)</span>';
      card.appendChild(note);
    } else {
      const kv = document.createElement("div");
      kv.className = "kv-list";
      for (const [k, v] of Object.entries(args)) {
        const kEl = document.createElement("span");
        kEl.className = "k";
        kEl.textContent = k;
        kv.appendChild(kEl);
        kv.appendChild(formatValue(v));
      }
      card.appendChild(kv);
    }

    if (tc.result !== null && tc.result !== undefined) {
      const section = document.createElement("div");
      section.className = "tool-call-section";

      const title = document.createElement("div");
      title.className = "tool-call-section-title";
      title.textContent = "Result";
      section.appendChild(title);

      const result = document.createElement("div");
      result.className = "tool-call-result";
      const resultStr = String(tc.result);
      if (/^Refused:/i.test(resultStr)) {
        result.classList.add("refused");
      }
      result.textContent = resultStr;
      section.appendChild(result);
      card.appendChild(section);
    }

    return card;
  }

  function formatValue(v) {
    const span = document.createElement("span");
    span.className = "v";
    if (v === null || v === undefined) {
      span.classList.add("null");
      span.textContent = "null";
    } else if (typeof v === "string") {
      span.classList.add("string");
      span.textContent = JSON.stringify(v);
    } else if (typeof v === "number") {
      span.classList.add("number");
      span.textContent = String(v);
    } else if (typeof v === "boolean") {
      span.classList.add("boolean");
      span.textContent = String(v);
    } else {
      span.classList.add("json");
      span.textContent = JSON.stringify(v, null, 2);
    }
    return span;
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ---- Composer ----

  function autosizeInput() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 180) + "px";
  }

  inputEl.addEventListener("input", autosizeInput);
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      composerEl.requestSubmit();
    }
  });

  composerEl.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;
    const text = inputEl.value.trim();
    if (!text) return;

    busy = true;
    sendBtn.disabled = true;
    setStatus("Thinking", "thinking");

    addUserMessage(text);
    inputEl.value = "";
    autosizeInput();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const data = await res.json();
          if (data?.detail) detail = data.detail;
        } catch (_) {}
        throw new Error(detail);
      }
      const data = await res.json();
      addAgentMessage(data.reply, data.tool_calls || []);
      setStatus("Ready", "ready");
    } catch (err) {
      addErrorMessage(err.message);
      setStatus("Error", "error");
    } finally {
      busy = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  });

  resetBtn.addEventListener("click", async () => {
    if (busy) return;
    try {
      await fetch("/api/reset", { method: "POST", credentials: "same-origin" });
    } catch (_) {}
    messagesEl.innerHTML = `
      <div class="empty-state">
        <h3>Conversation reset</h3>
        <p>The agent has fresh state. Send a new message to begin.</p>
      </div>
    `;
    firstMessage = true;
    setStatus("Ready", "ready");
  });

  // ---- Init ----

  async function rehydrateHistory() {
    try {
      const res = await fetch("/api/history", {credentials: "same-origin"});
      if (!res.ok) return;
      const data = await res.json();
      const turns = data?.turns || [];
      if (!turns.length) return;
      for (const t of turns) {
        addUserMessage(t.user);
        addAgentMessage(t.reply, t.tool_calls || []);
      }
    } catch (_) {
      /* offline or no session — fine to ignore */
    }
  }

  rehydrateHistory();
  loadTickets();
  inputEl.focus();
})();
