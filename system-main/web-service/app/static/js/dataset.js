document.addEventListener("DOMContentLoaded", () => {
  const settingsForm = document.querySelector("[data-dataset-settings-form]");

  const updateStatistics = (slider) => {
    const classId = slider.dataset.classId;
    const row = document.querySelector(`[data-class-id="${classId}"]`);
    const percentage = Number(slider.value);
    const total = Number(row?.dataset.itemsCount ?? 0);
    const trainCount = Math.floor(total * percentage);

    const value = document.querySelector(
      `[data-slider-value="${classId}"]`
    );
    const trainCell = row?.querySelector("[data-train-count]");
    const testCell = row?.querySelector("[data-test-count]");

    if (value) {
      value.textContent = `${Math.round(percentage * 100)}%`;
    }

    if (trainCell) {
      trainCell.textContent = String(trainCount);
    }

    if (testCell) {
      testCell.textContent = String(total - trainCount);
    }
  };

  document.querySelectorAll("[data-train-slider]").forEach((slider) => {
    slider.addEventListener("input", () => updateStatistics(slider));
  });

  settingsForm?.addEventListener("submit", () => {
    const trainPercent = {};

    settingsForm.querySelectorAll("[data-train-slider]").forEach((slider) => {
      trainPercent[slider.dataset.classId] = Number(slider.value);
    });

    settingsForm.querySelector("[data-train-percent-json]").value =
      JSON.stringify(trainPercent);
  });

  const labelDialog = document.getElementById("class-label-dialog");
  const labelForm = labelDialog?.querySelector("[data-class-label-form]");
  const labelInput = labelDialog?.querySelector("[data-class-label-input]");

  document.querySelectorAll("[data-edit-class]").forEach((button) => {
    button.addEventListener("click", () => {
      labelInput.value = button.dataset.classLabel;
      labelForm.action = button.dataset.editUrl;

      labelDialog.showModal();
      labelInput.focus();
    });
  });
});