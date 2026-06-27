/* Yunaki — live run panel. Starts a run, streams progress over a WebSocket,
   and reconnects with backoff. The backend replays event history on connect,
   so a dropped socket recovers without losing state. */
(function (Y) {
  "use strict";

  const { el, escapeHtml, scoreClass } = Y.utils;
  const MAX_BACKOFF_MS = 8000;

  const live = {
    runId: null,
    socket: null,
    backoff: 1000,
    finished: false,
    onComplete: null,
    seenSkills: new Set(),
  };

  function setStatus(mode, label) {
    const pill = el("conn-status");
    if (!pill) return;
    pill.className = "status-pill " + mode;
    el("conn-label").textContent = label;
  }

  function resetStage() {
    live.finished = false;
    live.seenSkills = new Set();
    el("live-stage").classList.remove("hidden");
    el("run-result").classList.add("hidden");
    el("run-result").innerHTML = "";
    el("skill-flow").innerHTML = "";
    el("terminal-body").innerHTML = '<span class="cursor">▋</span>';
    setScore(0);
    setProgress(0, 1);
  }

  function setScore(score) {
    const node = el("live-score");
    if (!node) return;
    node.textContent = Math.round(score);
    node.classList.add("bump");
    setTimeout(() => node.classList.remove("bump"), 280);
  }

  function setProgress(iter, max) {
    el("live-iter").textContent = `Iteration ${iter} / ${max}`;
    const pct = max > 0 ? Math.min(100, (iter / max) * 100) : 0;
    el("progress-fill").style.width = pct + "%";
  }

  function appendTerminal(chunk) {
    const body = el("terminal-body");
    const cursor = body.querySelector(".cursor");
    if (cursor) cursor.remove();
    body.insertAdjacentText("beforeend", chunk);
    body.insertAdjacentHTML("beforeend", '<span class="cursor">▋</span>');
    body.scrollTop = body.scrollHeight;
  }

  function addSkillChip(action, skillId, title) {
    const key = action + ":" + skillId;
    if (live.seenSkills.has(key)) return;
    live.seenSkills.add(key);
    const verb = { retrieved: "↓ retrieved", created: "✦ created", evolved: "⟳ evolved" }[action] || action;
    const chip = document.createElement("span");
    chip.className = "flow-chip " + action;
    chip.innerHTML = `<span class="dot"></span>${verb}: ${escapeHtml(title || skillId)}`;
    el("skill-flow").appendChild(chip);
  }

  function showResult(result) {
    const before = result.score_before || 0;
    const after = result.score_after || 0;
    const delta = after - before;
    const node = el("run-result");
    node.classList.remove("hidden");
    node.innerHTML = `
      <div class="result-scores">
        <div class="result-score-box"><span class="l">Before</span><span class="v score-low">${before.toFixed(0)}</span></div>
        <div class="result-arrow">→</div>
        <div class="result-score-box"><span class="l">After</span><span class="v ${scoreClass(after)}">${after.toFixed(0)}</span></div>
        <span class="delta-badge ${delta < 0 ? "neg" : ""}">${delta >= 0 ? "+" : ""}${delta.toFixed(0)} pts</span>
      </div>
      <p class="hint" style="margin-top:.7rem">
        ${result.iterations} iteration(s) ·
        ${(result.skills_used || []).length} used ·
        ${(result.skills_created || []).length} created ·
        ${(result.skills_evolved || []).length} evolved
      </p>`;
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case "run_started":
        setProgress(0, ev.max_iterations || 1);
        break;
      case "iteration":
        setProgress(ev.iteration, ev.max_iterations || 1);
        if (typeof ev.score === "number") setScore(ev.score);
        break;
      case "score_update":
        setScore(ev.score);
        break;
      case "skill_event":
        addSkillChip(ev.action, ev.skill_id, ev.title);
        break;
      case "agent_output":
        appendTerminal(ev.chunk || "");
        break;
      case "run_completed":
        showResult(ev.result || {});
        finish(true);
        break;
      case "run_failed":
        Y.utils.toast("Run failed: " + (ev.error || "unknown"), "bad");
        finish(false);
        break;
      case "_stream_done":
        finish(live.finished);
        break;
    }
  }

  function connect() {
    if (!live.runId) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/runs/${live.runId}`;
    setStatus("connecting", "Connecting…");
    const socket = new WebSocket(url);
    live.socket = socket;

    socket.onopen = () => {
      live.backoff = 1000;
      setStatus("live", "Live");
    };
    socket.onmessage = (msg) => {
      try { handleEvent(JSON.parse(msg.data)); }
      catch (e) { console.error("bad event", e); }
    };
    socket.onclose = () => {
      if (live.finished || !live.runId) return;
      // Unexpected drop — reconnect with backoff; backend replays history.
      setStatus("connecting", "Reconnecting…");
      setTimeout(connect, live.backoff);
      live.backoff = Math.min(live.backoff * 2, MAX_BACKOFF_MS);
    };
    socket.onerror = () => socket.close();
  }

  function finish(ok) {
    live.finished = true;
    if (live.socket) { try { live.socket.close(); } catch (_) {} }
    live.socket = null;
    live.runId = null;
    const cursor = el("terminal-body").querySelector(".cursor");
    if (cursor) cursor.remove();
    setStatus("offline", "Idle");
    el("run-btn").disabled = false;
    el("run-btn").textContent = "Run task";
    if (ok && live.onComplete) live.onComplete();
  }

  async function start() {
    const input = el("task-input");
    const task = input.value.trim();
    if (!task) { input.focus(); return; }
    const maxIter = parseInt(el("max-iterations").value, 10) || 3;

    el("run-btn").disabled = true;
    el("run-btn").textContent = "Running…";
    resetStage();
    setStatus("connecting", "Starting…");

    try {
      const { run_id } = await Y.api.startRun(task, maxIter);
      live.runId = run_id;
      connect();
    } catch (e) {
      Y.utils.toast("Could not start run: " + e.message, "bad");
      finish(false);
    }
  }

  Y.live = {
    start,
    setCompleteHandler(fn) { live.onComplete = fn; },
    isActive: () => Boolean(live.runId) && !live.finished,
  };
})(window.Y = window.Y || {});
