/* Yunaki — API client. Thin fetch wrappers over the FastAPI backend. */
(function (Y) {
  "use strict";

  async function request(path, opts) {
    const res = await fetch("/api/" + path, opts || {});
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || detail;
      } catch (_) { /* non-JSON error body */ }
      throw new Error(`${res.status} ${detail}`);
    }
    return res.json();
  }

  function postJSON(path, body) {
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  Y.api = {
    stats: () => request("stats"),
    skills: () => request("skills"),
    skillHistory: (id) => request(`skills/${encodeURIComponent(id)}/history`),
    runs: () => request("runs"),
    startRun: (task, maxIterations) =>
      postJSON("run/start", { task_description: task, max_iterations: maxIterations }),
    approveSkill: (id) => postJSON(`skills/${encodeURIComponent(id)}/approve`),
    rejectSkill: (id) => postJSON(`skills/${encodeURIComponent(id)}/reject`),
  };
})(window.Y = window.Y || {});
