/* Yunaki — skill graph (D3 v7 force-directed).
   Nodes = skills (radius ∝ score, color = granularity).
   Links = evolution lineage (parent_skill → child, merged_from → child). */
(function (Y) {
  "use strict";

  const COLOR = {
    "task-level": "#8b5cff",
    "event-driven": "#22d3ee",
  };

  let sim = null;
  let onSelect = null;

  function radius(score) { return 9 + (Math.max(0, Math.min(100, score)) / 100) * 16; }

  function buildLinks(skills, ids) {
    const links = [];
    skills.forEach((s) => {
      const p = s.provenance || {};
      if (p.parent_skill && ids.has(p.parent_skill)) {
        links.push({ source: p.parent_skill, target: s.id, kind: "evolved" });
      }
      (p.merged_from || []).forEach((m) => {
        if (ids.has(m)) links.push({ source: m, target: s.id, kind: "merged" });
      });
    });
    return links;
  }

  function render(skills) {
    const host = Y.utils.el("skill-graph");
    if (!host || typeof d3 === "undefined") return;
    const wrap = host.parentElement;
    const width = wrap.clientWidth || 600;
    const height = wrap.clientHeight || 460;

    const ids = new Set(skills.map((s) => s.id));
    const nodes = skills.map((s) => ({
      id: s.id,
      title: s.title,
      score: s.score || 0,
      gran: s.granularity,
      version: s.version,
      status: s.status,
    }));
    const links = buildLinks(skills, ids);

    const svg = d3.select(host);
    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    if (!nodes.length) {
      svg.append("text").attr("x", width / 2).attr("y", height / 2)
        .attr("text-anchor", "middle").attr("fill", "#5c6478")
        .attr("font-size", 13).text("No skills to graph yet");
      return;
    }

    const tip = Y.utils.el("graph-tip");

    const link = svg.append("g").attr("class", "links")
      .selectAll("line").data(links).join("line")
      .attr("class", "link")
      .attr("stroke-dasharray", (d) => (d.kind === "merged" ? "3 3" : null));

    const node = svg.append("g").selectAll("g.node")
      .data(nodes).join("g").attr("class", "node");

    node.append("circle")
      .attr("r", (d) => radius(d.score))
      .attr("fill", (d) => COLOR[d.gran] || "#6366f1")
      .attr("fill-opacity", 0.85)
      .attr("stroke", "#0b0d14")
      .attr("stroke-width", 2)
      .on("mouseover", function (event, d) {
        d3.select(this).attr("stroke", "#fff").attr("stroke-width", 2.5);
        if (tip) {
          tip.innerHTML =
            `<div class="gt-title">${Y.utils.escapeHtml(d.title)}</div>` +
            `<div class="hint">v${d.version} · ${d.gran} · score ${Math.round(d.score)}</div>`;
          tip.classList.add("show");
        }
      })
      .on("mousemove", function (event) {
        if (!tip) return;
        const r = host.getBoundingClientRect();
        tip.style.left = event.clientX - r.left + "px";
        tip.style.top = event.clientY - r.top + "px";
      })
      .on("mouseout", function () {
        d3.select(this).attr("stroke", "#0b0d14").attr("stroke-width", 2);
        if (tip) tip.classList.remove("show");
      })
      .on("click", (event, d) => { if (onSelect) onSelect(d.id); });

    node.append("text")
      .attr("dy", (d) => radius(d.score) + 12)
      .attr("text-anchor", "middle")
      .text((d) => Y.utils.truncate(d.title, 22));

    node.call(
      d3.drag()
        .on("start", (event, d) => {
          if (!event.active) sim.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end", (event, d) => {
          if (!event.active) sim.alphaTarget(0);
          d.fx = null; d.fy = null;
        })
    );

    if (sim) sim.stop();
    sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id((d) => d.id).distance(110).strength(0.6))
      .force("charge", d3.forceManyBody().strength(-340))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide().radius((d) => radius(d.score) + 18))
      .on("tick", () => {
        link
          .attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
        node.attr("transform", (d) => `translate(${d.x},${d.y})`);
      });
  }

  Y.graph = {
    render,
    setSelectHandler(fn) { onSelect = fn; },
  };
})(window.Y = window.Y || {});
