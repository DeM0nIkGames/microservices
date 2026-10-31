document.addEventListener("DOMContentLoaded", () => {
  const tabs = document.querySelectorAll("[data-tab-target]");
  const panels = document.querySelectorAll(".tab-panel");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetId = tab.dataset.tabTarget;

      tabs.forEach((item) => {
        const isActive = item === tab;
        item.classList.toggle("is-active", isActive);
        item.setAttribute("aria-selected", String(isActive));
      });

      panels.forEach((panel) => {
        const isActive = panel.id === targetId;
        panel.classList.toggle("is-active", isActive);
        panel.hidden = !isActive;
      });
    });
  });

  document.querySelectorAll(".clickable-row[data-href]").forEach((row) => {
    const navigate = () => {
      window.location.href = row.dataset.href;
    };

    row.addEventListener("click", navigate);

    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        navigate();
      }
    });
  });

  document.querySelectorAll("[data-open-dialog]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById(button.dataset.openDialog)?.showModal();
    });
  });

  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => {
      button.closest("dialog")?.close();
    });
  });

  document
    .querySelectorAll("[data-register-form='True'], [data-register-form='true']")
    .forEach((form) => {
      form.addEventListener("submit", (event) => {
        const password = form.elements.password.value;
        const repeat = form.elements.password_repeat.value;

        if (password !== repeat) {
          event.preventDefault();
          window.alert("Пароли не совпадают.");
        }
      });
    });

  document.querySelectorAll("[data-password-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (
        form.elements.new_password.value
        !== form.elements.new_password_repeat.value
      ) {
        event.preventDefault();
        window.alert("Новые пароли не совпадают.");
      }
    });
  });

  document.querySelectorAll("[data-confirm-delete]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const message = form.dataset.confirmMessage
        || "Удалить объект? Это действие нельзя отменить.";

      if (!window.confirm(message)) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll("[data-dataset-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const archive = form.elements.archive.files[0];
      const trainPercent = form.elements.train_percent.value.trim();
      const error = form.querySelector("[data-form-error]");

      let message = "";

      if (!archive || !archive.name.toLowerCase().endsWith(".zip")) {
        message = "Выбери ZIP-архив с изображениями и файлом разметки.";
      } else if (trainPercent) {
        const value = Number(trainPercent);

        if (!Number.isFinite(value) || value < 0 || value > 1) {
          message = "Доля обучения должна быть числом от 0 до 1.";
        }
      }

      if (message) {
        event.preventDefault();
        error.textContent = message;
        error.hidden = false;
      } else {
        error.hidden = true;
      }
    });
  });

  document.querySelectorAll("[data-model-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const url = form.elements.import_url.value.trim();
      const error = form.querySelector("[data-form-error]");

      if (!/^https?:\/\/.+/i.test(url)) {
        event.preventDefault();
        error.textContent = "Укажи полный HTTP(S)-адрес модели.";
        error.hidden = false;
      } else {
        error.hidden = true;
      }
    });
  });
});