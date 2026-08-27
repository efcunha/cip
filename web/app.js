/* ─────────────────────────────────────────────────────────────────────────
   CIP — Cloud Intelligence Platform — Web UI (Round 22+)
   Features:
   - Chat multi-turn (conversation_id persiste, history injetada no LLM)
   - Streaming SSE (token-by-token)
   - Feedback por mensagem (👍/👎) — botão após cada resposta
   - Lista de conversas na sidebar (cria/seleciona/deleta)
   ───────────────────────────────────────────────────────────────────────── */

// ─── Elementos DOM ────────────────────────────────────────────────
const els = {
  apiUrl: document.getElementById("apiUrl"),
  apiKey: document.getElementById("apiKey"),
  tenantId: document.getElementById("tenantId"),
  cloudSelect: document.getElementById("cloudSelect"),
  reactMode: document.getElementById("reactMode"),
  streamMode: document.getElementById("streamMode"),
  questionInput: document.getElementById("questionInput"),
  chatForm: document.getElementById("chatForm"),
  sendBtn: document.getElementById("sendBtn"),
  charCount: document.getElementById("charCount"),
  messages: document.getElementById("messages"),
  clearBtn: document.getElementById("clearBtn"),
  healthBtn: document.getElementById("healthBtn"),
  statusDot: document.getElementById("statusDot"),
  statusText: document.getElementById("statusText"),
  convList: document.getElementById("convList"),         // opcional (adicionado abaixo)
  newConvBtn: document.getElementById("newConvBtn"),     // opcional
};

// ─── Estado ───────────────────────────────────────────────────────
let currentConvId = localStorage.getItem("cip.convId") || null;
const tenantId = () => els.tenantId.value.trim() || "default";

function authHeaders() {
  const h = { "Content-Type": "application/json", "X-Tenant-Id": tenantId() };
  if (els.apiKey.value.trim()) h["X-API-Key"] = els.apiKey.value.trim();
  return h;
}

// ─── HTTP helpers ─────────────────────────────────────────────────
async function api(path, opts = {}) {
  const url = `${els.apiUrl.value.replace(/\/$/, "")}${path}`;
  const resp = await fetch(url, { ...opts, headers: { ...authHeaders(), ...(opts.headers || {}) } });
  if (!resp.ok) {
    const t = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText} — ${t.slice(0, 200)}`);
  }
  return resp;
}

async function callHealth() {
  const r = await api("/health");
  return r.json();
}

// ─── Chat multi-turn ──────────────────────────────────────────────
async function listConversations() {
  const r = await api(`/chat/conversations?limit=20`);
  return r.json();
}

async function createConversation(title = null) {
  const r = await api("/chat/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
  return r.json();
}

async function getConversation(id) {
  const r = await api(`/chat/conversations/${id}`);
  return r.json();
}

async function deleteConversation(id) {
  await api(`/chat/conversations/${id}`, { method: "DELETE" });
}

async function sendConversationMessage(convId, question, opts) {
  const r = await api(`/chat/conversations/${convId}/messages`, {
    method: "POST",
    body: JSON.stringify({
      question,
      cloud: opts.cloud || null,
      stream: false,
    }),
  });
  return r.json();
}

async function sendFeedback(msgId, feedback, note = null) {
  const r = await api(`/chat/messages/${msgId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ feedback, note }),
  });
  return r.json();
}

// ─── /ask/stream (legacy single-turn) ────────────────────────────
async function callAskStream(question, opts, onDelta) {
  const params = new URLSearchParams();
  if (opts.cloud) params.set("cloud", opts.cloud);
  const url = `${els.apiUrl.value.replace(/\/$/, "")}/ask/stream?${params}`;
  const resp = await fetch(url, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ question, react_mode: !!opts.reactMode }),
  });
  if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalData = null;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nlIdx;
    while ((nlIdx = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, nlIdx);
      buffer = buffer.slice(nlIdx + 2);
      const ev = parseSSE(block);
      if (!ev) continue;
      if (ev.event === "chunk") {
        try { onDelta(JSON.parse(ev.data).delta || ""); } catch (_) {}
      } else if (ev.event === "done") {
        try { finalData = JSON.parse(ev.data); } catch (_) {}
      } else if (ev.event === "error") {
        try { throw new Error(JSON.parse(ev.data).message || "stream error"); } catch (_) {}
      }
    }
  }
  return finalData;
}

function parseSSE(block) {
  let event = "message", data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  return { event, data };
}

async function callAsk(question, opts) {
  const r = await api("/ask", {
    method: "POST",
    body: JSON.stringify({ question, cloud: opts.cloud, react_mode: !!opts.reactMode }),
  });
  return r.json();
}

// ─── Render helpers ───────────────────────────────────────────────
function escapeHtml(s) {
  if (!s) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function formatAnswer(text) {
  let html = escapeHtml(text || "");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/`(.+?)`/g, "<code>$1</code>");
  html = html.replace(/\n/g, "<br>");
  return html;
}

function renderSidebar(convList) {
  if (!els.convList) return;
  els.convList.innerHTML = "";
  if (!convList || convList.length === 0) {
    els.convList.innerHTML = `<div class="conv-empty">Nenhuma conversa ainda.</div>`;
    return;
  }
  for (const c of convList) {
    const div = document.createElement("div");
    div.className = "conv-item" + (c.id === currentConvId ? " active" : "");
    div.innerHTML = `
      <span class="conv-title">${escapeHtml(c.title || "(sem titulo)")}</span>
      <button class="conv-del" title="Apagar">×</button>
    `;
    div.querySelector(".conv-title").addEventListener("click", () => loadConversation(c.id));
    div.querySelector(".conv-del").addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm(`Apagar conversa "${c.title || c.id}"?`)) return;
      await deleteConversation(c.id);
      if (currentConvId === c.id) {
        currentConvId = null;
        localStorage.removeItem("cip.convId");
        clearMessages();
      }
      await refreshConvList();
    });
    els.convList.appendChild(div);
  }
}

async function refreshConvList() {
  try {
    const data = await listConversations();
    renderSidebar(data.items || []);
  } catch (e) {
    console.warn("Falha ao listar conversas:", e);
  }
}

function clearMessages() {
  els.messages.innerHTML = `
    <div class="welcome">
      <h2>👋 Bem-vindo ao CIP</h2>
      <p>LLM especialista em <strong>AWS</strong>, <strong>GCP</strong> e <strong>Azure</strong>.</p>
      <p>Faça uma pergunta técnica ou revise código IaC. As respostas vêm com citações de fontes oficiais.</p>
      <p class="hint">💡 Comece com um dos exemplos na barra lateral, ou digite sua própria pergunta abaixo.</p>
    </div>
  `;
}

function addUserMessage(text) {
  appendMessage({ role: "user", content: text });
}

function appendAssistantMessage(text, meta) {
  const div = appendMessage({ role: "assistant", content: text });
  if (meta) {
    const metaDiv = document.createElement("div");
    metaDiv.className = "meta";
    if (meta.has_grounding !== undefined) {
      const b = document.createElement("span");
      b.className = "badge " + (meta.has_grounding ? "sources" : "no-grounding");
      b.textContent = meta.has_grounding
        ? `✓ ${meta.sources_count || 0} fontes`
        : "✗ sem grounding";
      metaDiv.appendChild(b);
    }
    if (meta.latency_ms) {
      const b = document.createElement("span");
      b.className = "badge latency";
      b.textContent = `⏱ ${(meta.latency_ms / 1000).toFixed(1)}s`;
      metaDiv.appendChild(b);
    }
    div.querySelector(".content").appendChild(metaDiv);
  }
  return div;
}

function appendStreamingAssistant() {
  removeWelcome();
  const div = document.createElement("div");
  div.className = "message assistant";
  div.innerHTML = `
    <div class="avatar">🤖</div>
    <div class="content">
      <div class="role">CIP</div>
      <div class="text"><span class="typing"></span></div>
    </div>
  `;
  els.messages.appendChild(div);
  els.messages.scrollTop = els.messages.scrollHeight;
  return div.querySelector(".text");
}

function removeWelcome() {
  const w = els.messages.querySelector(".welcome");
  if (w) w.remove();
}

function appendMessage({ role, content, msg_id = null }) {
  removeWelcome();
  const div = document.createElement("div");
  div.className = `message ${role}`;
  if (msg_id) div.dataset.msgId = msg_id;

  const avatar = role === "user" ? "👤" : "🤖";
  div.innerHTML = `
    <div class="avatar">${avatar}</div>
    <div class="content">
      <div class="role">${role === "user" ? "Você" : "CIP"}</div>
      <div class="text">${formatAnswer(content)}</div>
    </div>
  `;

  // Se for assistant, adiciona barra de feedback (será populada quando msg_id conhecido)
  if (role === "assistant") {
    const fb = document.createElement("div");
    fb.className = "feedback-bar hidden";
    fb.innerHTML = `
      <button class="fb-up" title="Útil">👍</button>
      <button class="fb-down" title="Não útil">👎</button>
      <input class="fb-note" placeholder="(opcional) por que?" maxlength="500"/>
      <span class="fb-status"></span>
    `;
    fb.querySelector(".fb-up").addEventListener("click", () =>
      submitFeedbackFromBar(div, "up"));
    fb.querySelector(".fb-down").addEventListener("click", () =>
      submitFeedbackFromBar(div, "down"));
    fb.querySelector(".fb-note").addEventListener("input", () => {
      fb.dataset.hasNote = (fb.querySelector(".fb-note").value || "").trim() !== "";
    });
    div.querySelector(".content").appendChild(fb);
  }

  els.messages.appendChild(div);
  els.messages.scrollTop = els.messages.scrollHeight;
  return div;
}

async function submitFeedbackFromBar(div, feedback) {
  const msgId = div.dataset.msgId;
  if (!msgId) return;
  const fb = div.querySelector(".feedback-bar");
  const note = (fb.querySelector(".fb-note")?.value || "").trim() || null;
  const status = fb.querySelector(".fb-status");
  fb.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    await sendFeedback(msgId, feedback, note);
    status.textContent = feedback === "up" ? "✓ Obrigado!" : "✓ Anotado, vamos melhorar.";
    fb.dataset.decided = feedback;
    fb.querySelectorAll("button").forEach((b) => {
      if (b.classList.contains(`fb-${feedback}`)) b.classList.add("selected");
      else b.classList.add("faded");
    });
  } catch (e) {
    status.textContent = `Erro: ${e.message}`;
    fb.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}

async function loadConversation(id) {
  try {
    const conv = await getConversation(id);
    currentConvId = id;
    localStorage.setItem("cip.convId", id);
    els.messages.innerHTML = "";
    for (const m of conv.messages || []) {
      appendMessage({
        role: m.role, content: m.content, msg_id: m.role === "assistant" ? m.id : null,
      });
    }
    await refreshConvList();
  } catch (e) {
    addMessage("assistant", `❌ Não consegui carregar a conversa: ${e.message}`);
  }
}

// ─── Status indicator ────────────────────────────────────────────
function setStatus(s) {
  els.statusDot.className = "dot " + s;
  els.statusText.textContent =
    s === "online" ? "Conectado" :
    s === "error" ? "Erro de conexão" :
    s === "busy" ? "Processando..." : "Desconectado";
}

// ─── Send (multi-turn quando há conv, single-turn caso contrário) ──
async function sendMessage() {
  const question = els.questionInput.value.trim();
  if (!question) return;

  const opts = {
    cloud: els.cloudSelect.value || null,
    reactMode: els.reactMode.checked,
  };

  els.questionInput.value = "";
  els.charCount.textContent = "0";
  els.sendBtn.disabled = true;
  setStatus("busy");

  try {
    // ── Modo multi-turn (cria conversa se não houver) ─────────────
    if (!currentConvId) {
      const conv = await createConversation(question.slice(0, 80));
      currentConvId = conv.id;
      localStorage.setItem("cip.convId", conv.id);
      await refreshConvList();
    }

    addUserMessage(question);

    if (els.streamMode.checked) {
      // Streaming direto (legacy /ask/stream — sem multi-turn com histórico
      // porque /ask/stream não aceita conversation_id; use POST /chat/.../messages
      // com stream=true se quiser SSE multi-turn)
      const textDiv = appendStreamingAssistant();
      await callAskStream(question, opts, (delta) => {
        const typing = textDiv.querySelector(".typing");
        if (typing) textDiv.innerHTML = formatAnswer(delta);
        else textDiv.innerHTML += formatAnswer(delta);
        els.messages.scrollTop = els.messages.scrollHeight;
      });
    } else {
      // Multi-turn: persiste user + assistant, injeta histórico no LLM
      const asst = await sendConversationMessage(currentConvId, question, opts);
      appendAssistantMessage(asst.content, {
        has_grounding: asst.sources && asst.sources.length > 0,
        sources_count: (asst.sources || []).length,
        latency_ms: asst.latency_ms,
      });
      // Atualiza a div mais recente com o msg_id (para feedback)
      const lastDiv = els.messages.lastElementChild;
      if (lastDiv && asst.id) lastDiv.dataset.msgId = asst.id;
    }
    setStatus("online");
  } catch (err) {
    setStatus("error");
    appendAssistantMessage(`❌ **Erro**: ${err.message}\n\nVerifique se a API está rodando em ${els.apiUrl.value} e se a API key/tenant estão corretos.`);
  } finally {
    els.sendBtn.disabled = false;
  }
}

// ─── Event listeners ────────────────────────────────────────────
els.chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage();
});

els.questionInput.addEventListener("input", () => {
  els.charCount.textContent = els.questionInput.value.length;
});

els.questionInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

els.clearBtn.addEventListener("click", () => {
  clearMessages();
  currentConvId = null;
  localStorage.removeItem("cip.convId");
  refreshConvList();
});

if (els.newConvBtn) {
  els.newConvBtn.addEventListener("click", () => {
    currentConvId = null;
    localStorage.removeItem("cip.convId");
    clearMessages();
    refreshConvList();
    els.questionInput.focus();
  });
}

els.healthBtn.addEventListener("click", async () => {
  try {
    const h = await callHealth();
    setStatus("online");
    appendAssistantMessage(`✅ **API Saudável**\n\n` +
      `- **Versão**: ${h.version || "—"}\n` +
      `- **Env**: ${h.env || "—"}\n` +
      `- **Readonly**: ${h.readonly || "—"}\n` +
      `- **Status**: ${h.status || "ok"}`);
  } catch (err) {
    setStatus("error");
    appendAssistantMessage(`❌ **Falha no health check**\n\n\`${err.message}\`\n\nVerifique se a API está rodando. Em dev: \`make up\`.`);
  }
});

document.querySelectorAll(".example").forEach((btn) => {
  btn.addEventListener("click", () => {
    els.questionInput.value = btn.dataset.q;
    els.charCount.textContent = els.questionInput.value.length;
    els.questionInput.focus();
  });
});

// ─── Init: carrega conversa ativa ou cria uma nova ─────────────
(async () => {
  await refreshConvList();
  if (currentConvId) {
    await loadConversation(currentConvId);
  }
  setStatus("desconectado");
  // Testa conexão
  try {
    await callHealth();
    setStatus("online");
  } catch (_) {}
})();
