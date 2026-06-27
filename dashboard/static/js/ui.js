/* Yunaki — render layer for stats, skill registry, and run history. */
(function (Y) {
  "use strict";

  const { el, escapeHtml, scoreClass, truncate, relTime, animateCount } = Y.utils;

  /* ── Hero stats ───────────────────────────────────────────────────────── */
  function renderStats(stats) {
    if (!stats) return;
    animateCount(el("stat-total-skills"), stats.total_skills);
    animateCount(el("stat-avg-score"), stats.avg_score, { decimals: 1 });
    animateCount(el("stat-total-runs"), stats.total_runs);
    animateCount(el("stat-avg-improvement"), stats.avg_improvement, { decimals: 1, suffix: "%" });
    // Mini header stats
    animateCount(el("mini-skills"), stats.total_skills);
    animateCount(el("mini-runs"), stats.total_runs);
  }

  /* ── Skill registry ───────────────────────────────────────────────────── */
  function filteredSkills(skills, filter) {
    if (filter === "all") return skills;
    if (filter === "pending") return skills.filter((s) => s.status === "pending");
    return skills.filter((s) => s.granularity === filter);
  }

  function triggerHtml(trigger) {
    if (!trigger) return "";
    if (trigger.type === "semantic") {
      return `<span class="pattern-tag">semantic</span><span class="pattern-tag">"${escapeHtml(trigger.query)}"</span>`;
    }
    const pats = (trigger.patterns || []).map((p) => `<span class="pattern-tag">${escapeHtml(p)}</span>`).join("");
    return `<span class="pattern-tag">pattern</span>${pats}`;
  }

  function skillCard(s) {
    const status = s.status || "active";
    const isPending = status === "pending";
    const prov = s.provenance || {};
    const actions = isPending
      ? `<div class="skill-actions">
           <button class="btn-ghost approve" data-approve="${escapeHtml(s.id)}">Approve</button>
           <button class="btn-ghost reject" data-reject="${escapeHtml(s.id)}">Reject</button>
         </div>`
      : `<div class="skill-actions">
           <button class="btn-ghost history" data-history="${escapeHtml(s.id)}">Version history</button>
         </div>`;

    return `
      <div class="skill-card ${isPending ? "pending" : ""}" data-skill="${escapeHtml(s.id)}">
        <div class="skill-card-head" data-toggle="${escapeHtml(s.id)}">
          <span class="skill-title">${escapeHtml(s.title)}</span>
          <span class="score-badge ${scoreClass(s.score)}">${Math.round(s.score)}</span>
        </div>
        <div class="skill-meta">
          <span class="badge gran-${s.granularity}">${escapeHtml(s.granularity)}</span>
          <span class="badge">v${escapeHtml(s.version)}</span>
          <span class="badge status-${status}">${escapeHtml(status)}</span>
          <span class="mono" style="color:var(--text-faint)">${escapeHtml(s.id)}</span>
        </div>
        <div class="skill-body">
          <div class="detail-block"><strong>When to apply</strong><p>${escapeHtml(s.when_to_apply)}</p></div>
          <div class="detail-block"><strong>Trigger</strong>${triggerHtml(s.trigger)}</div>
          <div class="detail-block"><strong>Instructions</strong>
            <ol>${(s.instructions || []).map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ol>
          </div>
          <div class="detail-block"><strong>Provenance</strong>
            <p class="mono">from ${escapeHtml(prov.created_from || "?")} · iter ${prov.iteration ?? 0}${prov.parent_skill ? " · ⤴ " + escapeHtml(prov.parent_skill) : ""}</p>
          </div>
          <div class="skill-history" id="history-${escapeHtml(s.id)}"></div>
          ${actions}
        </div>
      </div>`;
  }

  function renderSkills(skills, filter) {
    const container = el("skill-grid");
    if (!container) return;
    const list = filteredSkills(skills, filter || "all");
    if (!list.length) {
      container.innerHTML = `<p class="empty">No skills match this filter yet.</p>`;
      return;
    }
    container.innerHTML = list.map(skillCard).join("");
  }

  function renderHistory(skillId, history) {
    const target = el("history-" + skillId);
    if (!target) return;
    if (!history || !history.length) {
      target.innerHTML = `<p class="hint">Only the seed version (v0.1) exists.</p>`;
      return;
    }
    target.innerHTML =
      `<div class="timeline">` +
      history.map((h, i) => {
        const prov = h.provenance || {};
        const cur = i === history.length - 1;
        return `<div class="timeline-item ${cur ? "current" : ""}">
            <div class="timeline-v">v${escapeHtml(h.version)} · score ${Math.round(h.score)}</div>
            <div class="timeline-sub">${escapeHtml(prov.evolved_at || "seed")}${prov.parent_skill ? " · from " + escapeHtml(prov.parent_skill) : ""}</div>
          </div>`;
      }).join("") +
      `</div>`;
  }

  /* ── Run history ──────────────────────────────────────────────────────── */
  function deltaPill(before, after) {
    const d = after - before;
    const cls = d > 0.05 ? "pos" : "zero";
    const sign = d > 0 ? "+" : "";
    return `<span class="delta-pill ${cls}">${sign}${d.toFixed(0)}</span>`;
  }

  function runRow(r, idx) {
    const used = (r.skills_used || []).length;
    const created = (r.skills_created || []).length;
    const evolved = (r.skills_evolved || []).length;
    return `
      <tr data-run="${idx}">
        <td class="run-task-cell"><div class="t">${escapeHtml(truncate(r.task_description, 70))}</div></td>
        <td>
          <span class="score-flow">
            <span class="score-low">${r.score_before.toFixed(0)}</span>
            <span class="arrow">→</span>
            <span class="${scoreClass(r.score_after)}">${r.score_after.toFixed(0)}</span>
          </span>
        </td>
        <td>${deltaPill(r.score_before, r.score_after)}</td>
        <td>${r.iterations}</td>
        <td>
          <div class="skill-count-cell">
            <span class="scount" title="used"><b>${used}</b> used</span>
            <span class="scount" title="created"><b>${created}</b> new</span>
            <span class="scount" title="evolved"><b>${evolved}</b> evo</span>
          </div>
        </td>
        <td class="mono" style="color:var(--text-faint)">${escapeHtml(relTime(r.timestamp))}</td>
      </tr>
      <tr class="run-detail-row hidden" id="run-detail-${idx}">
        <td colspan="6"><pre>${escapeHtml(r.trace || "No trace recorded.")}</pre></td>
      </tr>`;
  }

  function renderRuns(runs) {
    const body = el("runs-body");
    const empty = el("runs-empty");
    if (!body) return;
    if (!runs.length) {
      body.innerHTML = "";
      if (empty) empty.classList.remove("hidden");
      return;
    }
    if (empty) empty.classList.add("hidden");
    body.innerHTML = runs.map((r, i) => runRow(r, i)).join("");
  }

  Y.ui = { renderStats, renderSkills, renderHistory, renderRuns };
})(window.Y = window.Y || {});
