/* Yunaki — shared state store + DOM/format utilities.
   Tiny immutable-ish store: setState returns a new merged object and notifies
   subscribers. Render code reads from Y.store.get(). */
(function (Y) {
  "use strict";

  let state = { skills: [], runs: [], stats: null, filter: "all" };
  const subscribers = new Set();

  Y.store = {
    get: () => state,
    set(patch) {
      state = Object.assign({}, state, patch);
      subscribers.forEach((fn) => fn(state));
      return state;
    },
    subscribe(fn) {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
  };

  /* ── Utilities ────────────────────────────────────────────────────────── */
  const utils = {
    el(id) { return document.getElementById(id); },

    escapeHtml(text) {
      const d = document.createElement("div");
      d.textContent = text == null ? "" : String(text);
      return d.innerHTML;
    },

    scoreClass(score) {
      if (score >= 70) return "score-high";
      if (score >= 40) return "score-mid";
      return "score-low";
    },

    truncate(text, n) {
      const s = String(text || "");
      return s.length > n ? s.slice(0, n - 1) + "…" : s;
    },

    relTime(iso) {
      if (!iso) return "—";
      const then = new Date(iso).getTime();
      if (Number.isNaN(then)) return iso;
      const diff = Math.max(0, Date.now() - then);
      const m = Math.floor(diff / 60000);
      if (m < 1) return "just now";
      if (m < 60) return `${m}m ago`;
      const h = Math.floor(m / 60);
      if (h < 24) return `${h}h ago`;
      return `${Math.floor(h / 24)}d ago`;
    },

    /* Animate a number from its current displayed value to `target`. */
    animateCount(node, target, opts) {
      if (!node) return;
      const o = opts || {};
      const decimals = o.decimals || 0;
      const suffix = o.suffix || "";
      const start = parseFloat(node.dataset.val || "0") || 0;
      const duration = o.duration || 700;
      const startT = performance.now();
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        node.dataset.val = target;
        node.textContent = target.toFixed(decimals) + suffix;
        return;
      }
      function frame(now) {
        const p = Math.min(1, (now - startT) / duration);
        const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
        const v = start + (target - start) * eased;
        node.textContent = v.toFixed(decimals) + suffix;
        if (p < 1) requestAnimationFrame(frame);
        else node.dataset.val = target;
      }
      requestAnimationFrame(frame);
    },

    toast(message, kind) {
      let stack = utils.el("toast-stack");
      if (!stack) {
        stack = document.createElement("div");
        stack.id = "toast-stack";
        stack.className = "toast-stack";
        document.body.appendChild(stack);
      }
      const t = document.createElement("div");
      t.className = "toast" + (kind ? " " + kind : "");
      t.textContent = message;
      stack.appendChild(t);
      setTimeout(() => {
        t.style.transition = "opacity .3s, transform .3s";
        t.style.opacity = "0";
        t.style.transform = "translateX(24px)";
        setTimeout(() => t.remove(), 300);
      }, 3200);
    },
  };

  Y.utils = utils;
})(window.Y = window.Y || {});
