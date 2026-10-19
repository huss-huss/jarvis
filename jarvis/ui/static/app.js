(() => {
  const transcript = document.getElementById("transcript");
  const toolFeed = document.getElementById("toolFeed");
  const reminderList = document.getElementById("reminderList");
  const taskList = document.getElementById("taskList");
  const caps = document.getElementById("caps");
  const statusDot = document.getElementById("statusDot");
  const statusLabel = document.getElementById("statusLabel");
  const modelName = document.getElementById("modelName");
  const ragProject = document.getElementById("ragProject");
  const composer = document.getElementById("composer");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("sendBtn");
  const talkBtn = document.getElementById("talkBtn");
  const stopBtn = document.getElementById("stopBtn");
  const wakeHint = document.getElementById("wakeHint");
  const newChatBtn = document.getElementById("newChatBtn");
  const confirmDialog = document.getElementById("confirmDialog");
  const confirmPrompt = document.getElementById("confirmPrompt");
  const confirmForm = document.getElementById("confirmForm");
  const toasts = document.getElementById("toasts");

  let busy = false;
  let voiceOn = false;
  let connected = false;
  let assistantEl = null;
  let es = null;

  function refreshButtons() {
    sendBtn.disabled = busy || !connected;
    talkBtn.disabled = busy || !connected || !voiceOn;
    talkBtn.textContent = voiceOn ? "Talk" : "Loading…";
  }

  function setBusy(v) {
    busy = v;
    refreshButtons();
  }

  function setStatus(status) {
    const s = status || "idle";
    statusLabel.textContent = s.replaceAll("_", " ");
    statusDot.className = "status-dot " + s;
    talkBtn.classList.toggle("hot", s === "listening");
    if (stopBtn) {
      stopBtn.hidden = !(s === "speaking" || s === "listening" || s === "thinking" || s === "executing");
    }
  }

  function setConnected(ok) {
    connected = ok;
    if (!ok) {
      setStatus("offline");
      wakeHint.textContent = "Disconnected — retrying…";
    }
    refreshButtons();
  }

  function addBubble(role, content) {
    const wrap = document.createElement("article");
    wrap.className = "bubble " + role;
    wrap.innerHTML =
      '<div class="who">' +
      (role === "user" ? "You" : "Jarvis") +
      '</div><div class="body"></div>';
    wrap.querySelector(".body").textContent = content || "";
    transcript.appendChild(wrap);
    transcript.scrollTop = transcript.scrollHeight;
    return wrap.querySelector(".body");
  }

  function renderHistory(messages) {
    transcript.innerHTML = "";
    assistantEl = null;
    (messages || []).forEach((m) => {
      if (m.role === "user" || m.role === "assistant") {
        addBubble(m.role, m.content);
      }
    });
  }

  function renderCaps(capabilities) {
    caps.innerHTML = "";
    const labels = {
      memory: "Memory",
      rag: "RAG",
      productivity: "Tasks",
      proactive: "Jobs",
      browser: "Browser",
      terminal: "Terminal",
      voice: "Voice",
    };
    Object.entries(labels).forEach(([key, label]) => {
      const el = document.createElement("span");
      el.className = "cap" + (capabilities && capabilities[key] ? " on" : "");
      el.textContent = label;
      caps.appendChild(el);
    });
  }

  function renderList(el, items, mapper) {
    el.innerHTML = "";
    if (!items || !items.length) {
      const li = document.createElement("li");
      li.className = "meta";
      li.textContent = "None";
      el.appendChild(li);
      return;
    }
    items.forEach((item) => {
      const li = document.createElement("li");
      li.innerHTML = mapper(item);
      el.appendChild(li);
    });
  }

  function renderPanels({ reminders, tasks }) {
    renderList(
      reminderList,
      reminders,
      (r) =>
        "<div><strong>" +
        escapeHtml(r.message) +
        '</strong></div><div class="meta">' +
        escapeHtml(r.scheduled_at || "") +
        "</div>"
    );
    renderList(
      taskList,
      tasks,
      (t) =>
        "<div><strong>" +
        escapeHtml(t.title) +
        '</strong></div><div class="meta">' +
        escapeHtml(t.due_at || "no due date") +
        "</div>"
    );
  }

  function pushTool(msg) {
    const li = document.createElement("li");
    const phase = msg.phase || "";
    li.innerHTML =
      '<div class="name">' +
      escapeHtml(msg.name || "tool") +
      '</div><div class="meta">' +
      escapeHtml(phase) +
      (msg.detail ? " · " + escapeHtml(String(msg.detail).slice(0, 120)) : "") +
      "</div>";
    toolFeed.prepend(li);
    while (toolFeed.children.length > 40) toolFeed.removeChild(toolFeed.lastChild);
  }

  function toast(title, message) {
    const el = document.createElement("div");
    el.className = "toast";
    el.innerHTML =
      "<strong>" +
      escapeHtml(title || "Jarvis") +
      "</strong>" +
      escapeHtml(message || "");
    toasts.appendChild(el);
    setTimeout(() => el.remove(), 7000);
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function applyVoiceState(capabilities, hint) {
    voiceOn = !!(capabilities && capabilities.voice);
    if (hint) {
      wakeHint.textContent = hint;
    } else if (voiceOn) {
      wakeHint.textContent = "Tap Talk or press Ctrl+Alt+J";
    } else {
      wakeHint.textContent = "Voice loading — chat works now; Talk enables shortly";
    }
    refreshButtons();
  }

  function applyHello(msg) {
    modelName.textContent = msg.model || "—";
    ragProject.textContent = msg.rag_project || "—";
    renderCaps(msg.capabilities || {});
    renderHistory(msg.history || []);
    renderPanels(msg);
    setStatus(msg.status || "idle");
    applyVoiceState(msg.capabilities || {}, msg.wake_hint);
    if (msg.pending_confirm && msg.pending_confirm.prompt) {
      openConfirm(msg.pending_confirm.prompt);
    }
    if (msg.error) toast("Warning", msg.error);
  }

  function openConfirm(prompt) {
    confirmPrompt.textContent = prompt;
    if (typeof confirmDialog.showModal === "function") {
      confirmDialog.showModal();
    }
  }

  function handleMessage(msg) {
    switch (msg.type) {
      case "hello":
        applyHello(msg);
        setConnected(true);
        break;
      case "voice_ready":
        renderCaps(msg.capabilities || {});
        applyVoiceState(msg.capabilities || {}, msg.wake_hint);
        toast("Voice", "Talk is ready");
        break;
      case "status":
        setStatus(msg.status);
        break;
      case "user":
        assistantEl = null;
        addBubble("user", msg.content || "");
        break;
      case "token":
        if (!assistantEl) assistantEl = addBubble("assistant", "");
        assistantEl.textContent += msg.content || "";
        transcript.scrollTop = transcript.scrollHeight;
        break;
      case "assistant_reset":
        if (assistantEl) {
          assistantEl.textContent = "";
        }
        break;
      case "stopped":
        setBusy(false);
        setStatus("idle");
        break;
      case "tool":
        pushTool(msg);
        break;
      case "listening":
        setBusy(true);
        setStatus("listening");
        break;
      case "done":
        setBusy(false);
        if (!assistantEl && msg.text) addBubble("assistant", msg.text);
        assistantEl = null;
        break;
      case "error":
        setBusy(false);
        toast("Error", msg.message || "Something went wrong");
        break;
      case "confirm_request":
        openConfirm(msg.prompt || "Confirm this action?");
        break;
      case "notification":
        toast(msg.title, msg.message);
        break;
      case "panels":
        renderPanels(msg);
        break;
      case "history":
        renderHistory(msg.messages || []);
        break;
      default:
        break;
    }
  }

  function connectEvents() {
    if (es) {
      try {
        es.close();
      } catch (_) {}
    }
    es = new EventSource("/api/events");
    es.onopen = () => setConnected(true);
    es.onerror = () => {
      setConnected(false);
      try {
        es.close();
      } catch (_) {}
      setTimeout(connectEvents, 1200);
    };
    es.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      handleMessage(msg);
    };
  }

  composer.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || busy || !connected) return;
    setBusy(true);
    assistantEl = null;
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
      });
      if (!res.ok) throw new Error("chat failed");
      input.value = "";
    } catch {
      setBusy(false);
      toast("Offline", "Could not reach Jarvis");
    }
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      composer.requestSubmit();
    }
  });

  talkBtn.addEventListener("click", async () => {
    if (!voiceOn) {
      toast("Voice", "Still loading the mic stack — try again in a few seconds");
      return;
    }
    if (busy || !connected) return;
    setBusy(true);
    assistantEl = null;
    try {
      const res = await fetch("/api/listen", { method: "POST" });
      if (res.status === 503) {
        setBusy(false);
        toast("Voice", "Still loading — wait for Talk to enable");
        return;
      }
      if (!res.ok) throw new Error("listen failed");
    } catch {
      setBusy(false);
      toast("Offline", "Could not start listening");
    }
  });

  if (stopBtn) {
    stopBtn.addEventListener("click", () => {
      fetch("/api/stop", { method: "POST" });
      setBusy(false);
      setStatus("idle");
    });
  }

  newChatBtn.addEventListener("click", () => {
    fetch("/api/new-chat", { method: "POST" });
    toolFeed.innerHTML = "";
  });

  confirmForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const submitter = e.submitter;
    const allowed = !!(submitter && submitter.value === "allow");
    fetch("/api/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ allowed }),
    });
    confirmDialog.close();
  });

  // Immediate enable via REST even before SSE hello
  fetch("/api/snapshot")
    .then((r) => r.json())
    .then((snap) => {
      applyHello({ type: "hello", ...snap });
      setConnected(true);
    })
    .catch(() => setConnected(false));

  connectEvents();
})();
