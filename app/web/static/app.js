const STATUS_RU = {
  "queued": "В очереди",
  "running": "Выполняется",
  "done": "Завершено",
  "failed": "Ошибка",
  "cancelled": "Остановлено",
};

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
  const cancelBtn = document.getElementById("cancelBtn");
  if (cancelBtn) {
    const finished = (st.status === "done" || st.status === "failed" || st.status === "cancelled"); 
    cancelBtn.disabled = finished;
    if (st.status === "cancelled") cancelBtn.textContent = "Остановлено";
  }

  const statusRu = STATUS_RU[st.status] || st.status
  document.getElementById("status").textContent = `Статус: ${statusRu}`;

  const p = st.progress || {};
  const processed = p.processed || 0;
  const total = p.total || 0;

  document.getElementById("progressText").textContent = `${processed}/${total}`;
  document.getElementById("matched").textContent = p.matched || 0;
  document.getElementById("notFound").textContent = p.not_found || 0;
  document.getElementById("failed").textContent = p.failed || 0;

  const percent = total > 0 ? (processed / total) * 100 : 0;
  document.getElementById("barFill").style.width = `${clamp(percent, 0, 100)}%`;

  const done = (st.status === "done" || st.status === "failed" || st.status === "cancelled");
  setDownload(window.JOB_ID, done);
  return done;
}

async function fetchLog(jobId, tail=200) {
  const r = await fetch(`/jobs/${jobId}/log?tail=${tail}`);
  if(!r.ok) throw new Error(`log http ${r.status}`);
    return await r.json();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderLog(payload) {
  const el = document.getElementById("log");
  if (!el) return;

  const nearBottom = (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 40);
  const lines = payload.lines || [];
  const html = lines.map((line) => {
    const safeLine = escapeHtml(line);
    if (line.includes("Найдено: Не найдено")) {
      return `<span class="log-line-not-found">${safeLine}</span>`;
    }
    return safeLine;
  }).join("\n");

  el.innerHTML = html || "(лог пуст)";
  if (nearBottom) {
    el.scrollTop = el.scrollHeight;
  }
}

async function cancelJob(jobId) {
  const r = await fetch(`/jobs/${jobId}/cancel`, { method: "POST"});
  if (!r.ok) throw new Error(`cancel http ${r.status}`);
  return await r.json();
}

async function loop() {
  const jobId = window.JOB_ID;
  let stopped = false;

  setDownload(jobId, false);
  const cancelBtn = document.getElementById("cancelBtn");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", async () => {
      cancelBtn.disabled = true;
      cancelBtn.textContent = "Останавливаю...";
      try {
        await cancelJob(jobId);
      } catch (e) {
        cancelBtn.disabled = false;
        cancelBtn.textContent = "Остановить";
        alert("Не удалось остановить: " + e);
      }
    })
  }

  while (!stopped) {
    try {
      const st = await fetchStatus(jobId);
      const done = render(st);
      const logPayload = await fetchLog(jobId, 200);
      renderLog(logPayload)
      if (done) break;
    } catch (e) {
      document.getElementById("status").textContent = `status: error (${e})`;
    }
    await new Promise(r => setTimeout(r, 1000));
  }
}

loop();
