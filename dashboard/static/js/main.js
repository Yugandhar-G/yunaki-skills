/* Yunaki — bootstrap: load data, wire events, poll when idle. */
(function (Y) {
  "use strict";

  const { el } = Y.utils;
  const POLL_MS = 5000;
  let pollTimer = null;

  /* ── Data loading ─────────────────────────────────────────────────────── */
  async function loadStats() {
    try { Y.store.set({ stats: await Y.api.stats() }); }
    catch (e) { console.error("stats", e); }
  }
  async function loadSkills() {
    try { Y.store.set({ skills: await Y.api.skills() }); }
    catch (e) { console.error("skills", e); }
  }
  async function loadRuns() {
    try { Y.store.set({ runs: await Y.api.runs() }); }
    catch (e) { console.error("runs", e); }
  }
  function refreshAll() { return Promise.all([loadStats(), loadSkills(), loadRuns()]); }

  /* ── Render reactions ─────────────────────────────────────────────────── */
  Y.store.subscribe((state) => {
    Y.ui.renderStats(state.stats);
    Y.ui.renderSkills(state.skills, state.filter);
    Y.ui.renderRuns(state.runs);
    Y.charts.render(state.runs);
    Y.graph.render(state.skills);
  });

  /* ── Skill registry interactions (event delegation) ───────────────────── */
  function wireRegistry() {
    el("skill-grid").addEventListener("click", async (e) => {
      const toggle = e.target.closest("[data-toggle]");
      if (toggle) {
        toggle.closest(".skill-card").classList.toggle("open");
        return;
      }
      const hist = e.target.closest("[data-history]");
      if (hist) {
        const id = hist.dataset.history;
        try { Y.ui.renderHistory(id, await Y.api.skillHistory(id)); }
        catch (err) { Y.utils.toast("History unavailable: " + err.message, "bad"); }
        return;
      }
      const approve = e.target.closest("[data-approve]");
      if (approve) { await governance(approve.dataset.approve, "approve"); return; }
      const reject = e.target.closest("[data-reject]");
      if (reject) { await governance(reject.dataset.reject, "reject"); return; }
    });
  }

  async function governance(id, action) {
    try {
      await (action === "approve" ? Y.api.approveSkill(id) : Y.api.rejectSkill(id));
      Y.utils.toast(`Skill ${action === "approve" ? "approved" : "rejected"}: ${id}`, "good");
      await loadSkills();
    } catch (e) {
      Y.utils.toast(`Could not ${action}: ${e.message}`, "bad");
    }
  }

  /* ── Filters ──────────────────────────────────────────────────────────── */
  function wireFilters() {
    const bar = el("registry-toolbar");
    if (!bar) return;
    bar.addEventListener("click", (e) => {
      const chip = e.target.closest(".filter-chip");
      if (!chip) return;
      bar.querySelectorAll(".filter-chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      Y.store.set({ filter: chip.dataset.filter });
    });
  }

  /* ── Run history drill-down ───────────────────────────────────────────── */
  function wireRunTable() {
    el("runs-body").addEventListener("click", (e) => {
      const row = e.target.closest("tr[data-run]");
      if (!row) return;
      const detail = el("run-detail-" + row.dataset.run);
      if (detail) detail.classList.toggle("hidden");
    });
  }

  /* ── Polling (pauses during an active live run) ───────────────────────── */
  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      if (Y.live.isActive()) return; // WS is driving the UI
      loadStats();
      loadRuns();
    }, POLL_MS);
  }

  /* ── Init ─────────────────────────────────────────────────────────────── */
  function init() {
    wireRegistry();
    wireFilters();
    wireRunTable();
    el("run-btn").addEventListener("click", () => Y.live.start());
    el("task-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") Y.live.start();
    });
    Y.live.setCompleteHandler(refreshAll);
    Y.graph.setSelectHandler((id) => {
      const card = document.querySelector(`.skill-card[data-skill="${CSS.escape(id)}"]`);
      if (card) {
        card.classList.add("open");
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        card.animate(
          [{ boxShadow: "0 0 0 2px var(--accent)" }, { boxShadow: "0 0 0 0 transparent" }],
          { duration: 1200, easing: "ease-out" }
        );
      }
    });
    refreshAll();
    startPolling();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window.Y = window.Y || {});
