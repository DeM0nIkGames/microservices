document.addEventListener("DOMContentLoaded", () => {
  const chartsPanel = document.querySelector("[data-run-charts]");
  const chartsGrid = document.querySelector("[data-charts-grid]");
  const loading = document.querySelector("[data-chart-loading]");
  const errorMessage = document.querySelector("[data-chart-error]");
  const chartsTab = document.querySelector(
    "[data-tab-target='charts-panel']"
  );

  const thresholdControls = document.querySelector(
    "[data-threshold-controls]"
  );
  const slider = document.querySelector("[data-threshold-slider]");
  const percentileValue = document.querySelector(
    "[data-percentile-value]"
  );
  const thresholdValue = document.querySelector(
    "[data-threshold-value]"
  );
  const thresholdMode = document.querySelector(
    "[data-threshold-mode]"
  );
  const autoButton = document.querySelector(
    "[data-auto-threshold]"
  );

  if (!chartsPanel || !chartsGrid) {
    return;
  }

  let currentMode = "manual";
  let debounceTimer = null;
  let activeController = null;
  let chartsLoaded = false;

  const showLoading = () => {
    if (loading) {
      loading.hidden = false;
    }

    if (errorMessage) {
      errorMessage.hidden = true;
      errorMessage.textContent = "";
    }

    chartsPanel.setAttribute("aria-busy", "true");
  };

  const hideLoading = () => {
    if (loading) {
      loading.hidden = true;
    }

    chartsPanel.setAttribute("aria-busy", "false");
  };

  const showError = (message) => {
    hideLoading();

    if (errorMessage) {
      errorMessage.textContent = message;
      errorMessage.hidden = false;
    }
  };

  const createChart = (chart, index) => {
    const card = document.createElement("article");
    card.className = "chart-card";

    const heading = document.createElement("div");
    heading.className = "chart-card-heading";

    const title = document.createElement("h3");
    title.textContent = chart.title || `График ${index + 1}`;
    heading.append(title);

    if (chart.description) {
      const description = document.createElement("p");
      description.textContent = chart.description;
      heading.append(description);
    }

    const plot = document.createElement("div");
    plot.className = "plot";
    plot.id = `plot-${chart.id || index}`;

    card.append(heading, plot);
    chartsGrid.append(card);

    const layout = {
      paper_bgcolor: "rgba(0, 0, 0, 0)",
      plot_bgcolor: "rgba(7, 16, 13, .55)",
      font: {
        color: "#eaf7ef",
      },
      margin: {
        l: 56,
        r: 24,
        t: 20,
        b: 52,
      },
      hovermode: "closest",
      ...chart.layout,
    };

    const config = {
      responsive: true,
      scrollZoom: true,
      displaylogo: false,
      modeBarButtonsToRemove: [
        "lasso2d",
        "select2d",
      ],
    };

    window.Plotly.newPlot(
      plot,
      chart.data || [],
      layout,
      config
    );
  };

  const renderCharts = (charts) => {
    chartsGrid.replaceChildren();

    if (!Array.isArray(charts) || charts.length === 0) {
      chartsGrid.hidden = true;
      showError(
        "Для этого запуска пока нет доступных графиков."
      );
      return;
    }

    if (!window.Plotly) {
      chartsGrid.hidden = true;
      showError(
        "Не удалось загрузить библиотеку интерактивных графиков."
      );
      return;
    }

    chartsGrid.hidden = false;
    charts.forEach(createChart);
  };

  const updateThresholdControls = (payload) => {
    const percentile = Number(payload.percentile);
    const threshold = Number(payload.threshold);

    if (
      percentileValue
      && Number.isFinite(percentile)
    ) {
      percentileValue.textContent = String(
        Math.round(percentile)
      );
    }

    if (
      currentMode === "manual"
      && slider
      && Number.isFinite(percentile)
    ) {
      slider.value = String(Math.round(percentile));
    }

    if (thresholdValue) {
      thresholdValue.textContent = Number.isFinite(threshold)
        ? threshold.toFixed(6)
        : "—";
    }

    if (thresholdMode) {
      thresholdMode.textContent =
        payload.mode === "auto"
          ? "автоматический режим"
          : "ручной режим";
    }
  };

  const loadCharts = async () => {
    if (activeController) {
      activeController.abort();
    }

    const controller = new AbortController();
    activeController = controller;

    showLoading();

    if (autoButton) {
      autoButton.disabled = true;
    }

    try {
      const url = new URL(
        chartsPanel.dataset.chartsUrl,
        window.location.origin
      );

      url.searchParams.set("mode", currentMode);

      if (slider) {
        url.searchParams.set(
          "percentile",
          slider.value
        );
      }

      const response = await fetch(url, {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
        signal: controller.signal,
      });

      let payload;

      try {
        payload = await response.json();
      } catch (_jsonError) {
        throw new Error(
          "Сервис вернул ответ в неизвестном формате."
        );
      }

      if (!response.ok) {
        throw new Error(
          payload.error
          || "Не удалось получить анализ запуска."
        );
      }
      if (activeController !== controller) {
        return;
      }

      updateThresholdControls(payload);
      renderCharts(payload.charts);

      chartsLoaded = true;
      hideLoading();
    } catch (requestError) {
      if (requestError.name === "AbortError") {
        return;
      }

      if (activeController === controller) {
        showError(
          requestError.message
          || "Не удалось получить графики от сервиса визуализации."
        );
      }
    } finally {
      if (activeController === controller) {
        activeController = null;

        if (autoButton) {
          autoButton.disabled = false;
        }

        chartsPanel.setAttribute(
          "aria-busy",
          "false"
        );
      }
    }
  };

  const scheduleManualUpdate = () => {
    if (!slider) {
      return;
    }

    currentMode = "manual";

    if (percentileValue) {
      percentileValue.textContent = slider.value;
    }

    if (thresholdMode) {
      thresholdMode.textContent = "ручной режим";
    }

    clearTimeout(debounceTimer);

    debounceTimer = window.setTimeout(() => {
      loadCharts();
    }, 200);
  };

  slider?.addEventListener(
    "input",
    scheduleManualUpdate
  );
  slider?.addEventListener("change", () => {
    clearTimeout(debounceTimer);
    loadCharts();
  });

  autoButton?.addEventListener("click", () => {
    clearTimeout(debounceTimer);
    currentMode = "auto";

    if (thresholdMode) {
      thresholdMode.textContent =
        "автоматический подбор…";
    }

    loadCharts();
  });

  chartsTab?.addEventListener("click", () => {
    if (!chartsLoaded) {
      loadCharts();
    }
  });
  if (
    !chartsPanel.hidden
    || chartsPanel.classList.contains("is-active")
  ) {
    loadCharts();
  }
  if (!thresholdControls && thresholdMode) {
    thresholdMode.textContent = "";
  }
});