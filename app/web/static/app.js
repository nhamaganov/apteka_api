async function fetchStatus(jobId) {
    const r = await fetch(`/jobs/${jobId}`);
    if (!r.ok) throw new Error(`status http ${r.status}`);
    return await r.json();
  }

function clamp(n, a, b) {
  return Math.max(a, Math.min(b, n));
}

function setDownload(jobId, enabled) {
  const a = document.getElementById("download");
  if (enabled) {
    a.classList.remove("disabled");
    a.href = `/jobs/${jobId}/download`;
    a.setAttribute("aria-disabled", "false");
  } else {
    a.classList.add("disabled");
    a.href = "#";
    a.setAttribute("aria-disabled", "true");
  }
}

function render(st) {
  document.getElementById("status").textContent = `status: ${st.status}`;

  const p = st.progress || {};
  const processed = p.processed || 0;
  const total = p.total || 0;

  document.getElementById("progressText").textContent = `${processed}/${total}`;
  document.getElementById("matched").textContent = p.matched || 0;
  document.getElementById("notFound").textContent = p.not_found || 0;
  document.getElementById("failed").textContent = p.failed || 0;

  const percent = total > 0 ? (processed / total) * 100 : 0;
  document.getElementById("barFill").style.width = `${clamp(percent, 0, 100)}%`;

  const done = (st.status === "done" || st.status === "failed");
  setDownload(window.JOB_ID, done);
  return done;
}

async function loop() {
  const jobId = window.JOB_ID;
  let stopped = false;

  setDownload(jobId, false);

  while (!stopped) {
    try {
      const st = await fetchStatus(jobId);
      const done = render(st);
      if (done) break;
    } catch (e) {
      document.getElementById("status").textContent = `status: error (${e})`;
    }
    await new Promise(r => setTimeout(r, 1000));
  }
}

loop();
