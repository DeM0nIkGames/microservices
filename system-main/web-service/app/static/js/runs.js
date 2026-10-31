document.addEventListener("DOMContentLoaded", () => {
  const statusLabels = {
    queued: "В очереди",
    running: "Исполняется",
    completed: "Завершён",
    failed: "Ошибка",
    cancelled: "Отменён",
  };

  const updateCard = (card, run) => {
    const status = run.status;

    const statusElement = card.querySelector("[data-run-status]");
    const progressBlock = card.querySelector("[data-run-progress]");
    const metricsBlock = card.querySelector("[data-run-metrics]");

    if (statusElement && status) {
      statusElement.className = `run-status run-status-${status}`;
      statusElement.textContent = statusLabels[status] ?? status;
    }

    if (progressBlock) {
      progressBlock.hidden = status !== "running";
    }

    if (metricsBlock) {
      metricsBlock.hidden = status !== "completed";
    }

    if (status === "running") {
      const progress = Number(run.progress ?? 0);
      const percentage = Math.round(progress * 1000) / 10;

      const progressBar = card.querySelector("[data-run-progress-bar]");
      const progressLabel = card.querySelector("[data-run-progress-label]");
      const progressValue = card.querySelector("[data-run-progress-value]");

      if (progressBar) {
        progressBar.value = progress;
      }

      if (progressLabel) {
        progressLabel.textContent =
          `Эпоха ${run.epoch ?? 0} из ${run.total_epochs ?? "—"}`;
      }

      if (progressValue) {
        progressValue.textContent = `${percentage}%`;
      }
    }

    if (status === "completed") {
      const accuracy = card.querySelector("[data-run-accuracy]");
      const rocAuc = card.querySelector("[data-run-roc-auc]");

      if (accuracy) {
        accuracy.textContent =
          run.accuracy == null
            ? "—"
            : `${Math.round(Number(run.accuracy) * 10000) / 100}%`;
      }

      if (rocAuc) {
        rocAuc.textContent =
          run.roc_auc == null
            ? "—"
            : Number(run.roc_auc).toFixed(4);
      }
    }
  };

  const cards = [...document.querySelectorAll("[data-run-card]")];

  const refreshCard = async (card) => {
    try {
      const response = await fetch(card.dataset.progressUrl, {
        headers: {
          Accept: "application/json",
        },
        credentials: "same-origin",
      });

      if (!response.ok) {
        return;
      }

      const run = await response.json();
      updateCard(card, run);
    } catch {
      // При временной сетевой ошибке карточка сохраняет последнее состояние.
    }
  };

  const refreshActiveRuns = async () => {
    const activeCards = cards.filter((card) => {
      const status = card.querySelector("[data-run-status]")?.textContent;

      return (
        status === statusLabels.queued ||
        status === statusLabels.running
      );
    });

    await Promise.all(activeCards.map(refreshCard));
  };

  if (cards.length > 0) {
    refreshActiveRuns();
    window.setInterval(refreshActiveRuns, 5000);
  }
});