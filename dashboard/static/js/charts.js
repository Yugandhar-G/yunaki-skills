/* Yunaki — improvement curve (Chart.js 4). Score before → after per run. */
(function (Y) {
  "use strict";

  let chart = null;

  function greenGradient(ctx, area) {
    const g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, "rgba(52, 211, 153, 0.45)");
    g.addColorStop(1, "rgba(52, 211, 153, 0.02)");
    return g;
  }

  function render(runs) {
    const canvas = Y.utils.el("improvement-chart");
    if (!canvas || typeof Chart === "undefined") return;

    // Oldest → newest along the x-axis (backend returns newest-first).
    const ordered = [...runs].reverse();
    const labels = ordered.map((_, i) => `Run ${i + 1}`);
    const before = ordered.map((r) => r.score_before);
    const after = ordered.map((r) => r.score_after);

    if (chart) chart.destroy();

    chart = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "After skills",
            data: after,
            borderColor: "#34d399",
            borderWidth: 2.5,
            tension: 0.4,
            fill: true,
            pointRadius: 3,
            pointHoverRadius: 6,
            pointBackgroundColor: "#34d399",
            backgroundColor(context) {
              const { ctx, chartArea } = context.chart;
              if (!chartArea) return "rgba(52,211,153,0.1)";
              return greenGradient(ctx, chartArea);
            },
          },
          {
            label: "Baseline",
            data: before,
            borderColor: "#f87171",
            borderWidth: 1.5,
            borderDash: [5, 4],
            tension: 0.4,
            fill: false,
            pointRadius: 2,
            pointHoverRadius: 5,
            pointBackgroundColor: "#f87171",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            labels: { color: "#9aa3b8", usePointStyle: true, boxWidth: 8, font: { size: 11 } },
          },
          tooltip: {
            backgroundColor: "#161a26",
            borderColor: "rgba(255,255,255,0.14)",
            borderWidth: 1,
            titleColor: "#e9ecf4",
            bodyColor: "#9aa3b8",
            padding: 10,
            callbacks: { label: (c) => ` ${c.dataset.label}: ${c.parsed.y.toFixed(0)}` },
          },
        },
        scales: {
          y: {
            min: 0,
            max: 100,
            ticks: { color: "#5c6478", callback: (v) => v + "%" },
            grid: { color: "rgba(255,255,255,0.05)" },
            border: { display: false },
          },
          x: {
            ticks: { color: "#5c6478" },
            grid: { display: false },
            border: { display: false },
          },
        },
      },
    });
  }

  Y.charts = { render };
})(window.Y = window.Y || {});
