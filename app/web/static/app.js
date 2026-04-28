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

function setVisible(id, visible) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle("hidden", !visible);
}

function render(st, ui = {}) {
  const finished = (st.status === "done" || st.status === "failed" || st.status === "cancelled");
  const cancelRequested = Boolean(st.cancelled);
  const cancelPending = (Boolean(ui.cancelPending) || cancelRequested) && !finished;
  setVisible("cancelLoader", cancelPending);

  const cancelBtn = document.getElementById("cancelBtn");
  if (cancelBtn) {
    const disableCancel = finished || cancelPending;
    cancelBtn.disabled = disableCancel;
    cancelBtn.setAttribute("aria-disabled", String(disableCancel));
    cancelBtn.classList.toggle("disabled", disableCancel);
    if (cancelPending) cancelBtn.textContent = "Останавливаю...";
    if (st.status === "cancelled") cancelBtn.textContent = "Остановлено";
  }

  const deleteBtn = document.getElementById("deleteBtn");
  if (deleteBtn) {
    const disableDelete = !finished;
    deleteBtn.disabled = disableDelete;
    if (disableDelete) {
      deleteBtn.setAttribute("disabled", "");
    } else {
      deleteBtn.removeAttribute("disabled");
    }
    deleteBtn.setAttribute("aria-disabled", String(disableDelete));
    deleteBtn.classList.toggle("disabled", disableDelete);
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
  return { done, cancelPending };
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

function renderQueryLine(line) {
  const idx = line.indexOf("Запрос:");
  if (idx === -1) {
    return escapeHtml(line);
  }

  const prefix = line.slice(0, idx);
  const payload = line.slice(idx + "Запрос:".length).trim();
  const parts = payload.split("|").map((part) => part.trim()).filter(Boolean);

  const namePart = parts.find((part) => part.startsWith("Название:")) || "";
  const qtyPart = parts.find((part) => part.startsWith("Кол-во:")) || "Кол-во: —";
  const dosagePart = parts.find((part) => part.startsWith("Дозировка:")) || "Дозировка: —";

  const safePrefix = escapeHtml(prefix);
  const safeName = escapeHtml(namePart.replace(/^Название:\s*/, ""));
  const safeQty = escapeHtml(qtyPart.replace(/^Кол-во:\s*/, ""));
  const safeDosage = escapeHtml(dosagePart.replace(/^Дозировка:\s*/, ""));

  return `${safePrefix}<span class="log-line-query">Запрос:</span> ` +
    `<span class="log-query-name">${safeName}</span> ` +
    `<span class="log-query-chip">Дозировка: ${safeDosage}</span>` +
    `<span class="log-query-chip">Кол-во: ${safeQty}</span> `;
}

function renderLog(payload) {
  const el = document.getElementById("log");
  if (!el) return;

  const nearBottom = (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 40);
  const lines = (payload.lines || []).filter((line) => (
    line.includes("Запрос:") || line.includes("Найдено:")
  ));
  const html = lines.map((line) => {
    if (line.includes("Запрос:")) {
      return renderQueryLine(line);
    }
    
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
  let cancelPending = false;
  let cancelLoaderShownAt = null;
  const cancelHintDelayMs = 10_000;

  setDownload(jobId, false);
  const cancelBtn = document.getElementById("cancelBtn");
  const modalEl = document.getElementById("cancelConfirmModal");
  const modalConfirmBtn = document.getElementById("cancelConfirmYes");
  const modalDeclineBtn = document.getElementById("cancelConfirmNo");

  const openConfirmModal = () => setVisible("cancelConfirmModal", true);
  const closeConfirmModal = () => setVisible("cancelConfirmModal", false);

  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      if (cancelPending) return;
      openConfirmModal();
    });
  }

  if (modalDeclineBtn) {
    modalDeclineBtn.addEventListener("click", () => {
      closeConfirmModal();
    });
  }

  if (modalEl) {
    modalEl.addEventListener("click", (event) => {
      if (event.target === modalEl) {
        closeConfirmModal();
      }
    });
  }

  if (modalConfirmBtn) {
    modalConfirmBtn.addEventListener("click", async () => {
      if (!cancelBtn) return;
      closeConfirmModal();
      cancelPending = true;
      cancelBtn.disabled = true;
      cancelBtn.setAttribute("aria-disabled", "true");
      cancelBtn.classList.add("disabled");
      cancelBtn.textContent = "Останавливаю...";
      setVisible("cancelLoader", true);
      setVisible("cancelLoaderHint", false);
      cancelLoaderShownAt = Date.now();
      try {
        await cancelJob(jobId);
      } catch (e) {
        cancelPending = false;
        cancelLoaderShownAt = null;
        setVisible("cancelLoader", false);
        setVisible("cancelLoaderHint", false);
        cancelBtn.disabled = false;
        cancelBtn.setAttribute("aria-disabled", "false");
        cancelBtn.classList.remove("disabled");
        cancelBtn.textContent = "Остановить";
        alert("Не удалось остановить: " + e);
      }
    });
  }

  while (!stopped) {
    try {
      const st = await fetchStatus(jobId);
      const { done, cancelPending: isCancelPending } = render(st, { cancelPending });
      if (isCancelPending) {
        if (cancelLoaderShownAt === null) {
          cancelLoaderShownAt = Date.now();
        }
        const showHint = (Date.now() - cancelLoaderShownAt) >= cancelHintDelayMs;
        setVisible("cancelLoaderHint", showHint);
      } else {
        cancelLoaderShownAt = null;
        setVisible("cancelLoaderHint", false);
      }
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
