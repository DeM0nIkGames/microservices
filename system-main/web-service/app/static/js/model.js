document.addEventListener("DOMContentLoaded", () => {
  const hyperparametersForm = document.querySelector(
    "[data-hyperparameters-form]"
  );
  const resetButton = document.querySelector(
    "[data-reset-hyperparameters]"
  );

  const runForm = document.querySelector("[data-run-form]");
  const datasetSelect = document.querySelector(
    "[data-run-dataset-select]"
  );
  const summaryContainer = document.querySelector(
    "[data-dataset-summary]"
  );
  const summaryBody = document.querySelector(
    "[data-dataset-summary-body]"
  );
  const summaryError = document.querySelector(
    "[data-dataset-summary-error]"
  );
  const submitButton = document.querySelector(
    "[data-run-submit]"
  );
  const hiddenHyperparameters = document.querySelector(
    "[data-run-hyperparameters]"
  );

  resetButton?.addEventListener("click", () => {
    hyperparametersForm
      ?.querySelectorAll("[data-default-value]")
      .forEach((field) => {
        field.value = field.dataset.defaultValue ?? "";
      });

    hyperparametersForm
      ?.querySelectorAll("[data-default-checked]")
      .forEach((field) => {
        field.checked =
          field.dataset.defaultChecked === "true";
      });
  });

  const serializeHyperparameters = () => {
    const result = {};

    if (!hyperparametersForm) {
      return result;
    }

    const fields = hyperparametersForm.querySelectorAll(
      "[name][data-parameter-type]"
    );

    fields.forEach((field) => {
      const parameterType = field.dataset.parameterType;
      const name = field.name;

      if (parameterType === "boolean") {
        result[name] = field.checked;
        return;
      }

      if (parameterType === "integer") {
        const value = Number.parseInt(field.value, 10);

        if (!Number.isInteger(value)) {
          throw new Error(
            `Параметр «${name}» должен быть целым числом.`
          );
        }

        result[name] = value;
        return;
      }

      if (parameterType === "number") {
        const value = Number(field.value);

        if (!Number.isFinite(value)) {
          throw new Error(
            `Параметр «${name}» должен быть числом.`
          );
        }

        result[name] = value;
        return;
      }

      result[name] = field.value;
    });

    return result;
  };

  const clearSummary = () => {
    if (summaryBody) {
      summaryBody.replaceChildren();
    }

    if (summaryContainer) {
      summaryContainer.hidden = true;
    }

    if (summaryError) {
      summaryError.hidden = true;
      summaryError.textContent = "";
    }

    if (submitButton) {
      submitButton.disabled = true;
    }
  };

  const showSummaryError = (message) => {
    if (summaryContainer) {
      summaryContainer.hidden = true;
    }

    if (summaryError) {
      summaryError.textContent = message;
      summaryError.hidden = false;
    }

    if (submitButton) {
      submitButton.disabled = true;
    }
  };

  const createCell = (value) => {
    const cell = document.createElement("td");
    cell.textContent = String(value);
    return cell;
  };

  const renderSummary = (classes) => {
    if (!summaryBody || !summaryContainer) {
      return;
    }

    summaryBody.replaceChildren();

    classes.forEach((classInfo) => {
      const row = document.createElement("tr");

      const percent =
        Math.round(Number(classInfo.train_percent) * 10000)
        / 100;

      row.append(
        createCell(classInfo.label),
        createCell(classInfo.train_count),
        createCell(classInfo.test_count),
        createCell(`${percent}%`)
      );

      summaryBody.append(row);
    });

    summaryContainer.hidden = false;

    if (summaryError) {
      summaryError.hidden = true;
      summaryError.textContent = "";
    }

    if (submitButton) {
      submitButton.disabled = false;
    }
  };

  let currentSummaryRequest = 0;

  datasetSelect?.addEventListener("change", async () => {
    clearSummary();

    const selectedOption =
      datasetSelect.options[datasetSelect.selectedIndex];
    const summaryUrl = selectedOption?.dataset.summaryUrl;

    if (!summaryUrl) {
      return;
    }

    const requestNumber = ++currentSummaryRequest;

    try {
      const response = await fetch(summaryUrl, {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
        credentials: "same-origin",
      });

      const payload = await response.json();

      if (requestNumber !== currentSummaryRequest) {
        return;
      }

      if (!response.ok) {
        throw new Error(
          payload.error || "Не удалось загрузить датасет."
        );
      }

      if (!Array.isArray(payload.classes)) {
        throw new Error(
          "Сервис вернул некорректную статистику датасета."
        );
      }

      renderSummary(payload.classes);
    } catch (error) {
      if (requestNumber !== currentSummaryRequest) {
        return;
      }

      showSummaryError(
        error.message
        || "Не удалось загрузить статистику датасета."
      );
    }
  });

  runForm?.addEventListener("submit", (event) => {
    if (submitButton?.disabled) {
      event.preventDefault();
      return;
    }

    try {
      const hyperparameters = serializeHyperparameters();

      hiddenHyperparameters.value =
        JSON.stringify(hyperparameters);
    } catch (error) {
      event.preventDefault();
      showSummaryError(
        error.message
        || "Не удалось прочитать гиперпараметры."
      );
    }
  });
});