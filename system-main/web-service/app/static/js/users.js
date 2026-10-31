document.addEventListener("DOMContentLoaded", () => {
  const dialog = document.getElementById("user-dialog");
  const form = document.getElementById("user-form");

  if (!dialog || !form) {
    return;
  }

  const title = document.getElementById("user-dialog-title");
  const hint = document.getElementById("user-dialog-hint");
  const submitButton = document.getElementById("user-form-submit");

  const loginInput = document.getElementById("user-login");
  const passwordInput = document.getElementById("user-password");
  const passwordRepeatInput = document.getElementById(
    "user-password-repeat",
  );
  const roleInput = document.getElementById("user-role");

  function openCreateDialog(createUrl) {
    form.action = createUrl;
    form.dataset.mode = "create";
    form.reset();

    title.textContent = "Добавить пользователя";
    hint.textContent = "Укажи логин, пароль и роль нового пользователя.";
    submitButton.textContent = "Добавить";

    passwordInput.required = true;
    passwordRepeatInput.required = true;

    dialog.showModal();
    loginInput.focus();
  }

  function openEditDialog(button) {
    form.action = button.dataset.editUrl;
    form.dataset.mode = "edit";
    form.reset();

    loginInput.value = button.dataset.login;
    roleInput.value = button.dataset.role;

    title.textContent = `Изменить пользователя: ${button.dataset.login}`;
    hint.textContent = "Оставь пароль пустым, если его менять не нужно.";
    submitButton.textContent = "Сохранить";

    passwordInput.required = false;
    passwordRepeatInput.required = false;

    dialog.showModal();
    loginInput.focus();
  }

  document
    .getElementById("add-user-button")
    ?.addEventListener("click", (event) => {
      openCreateDialog(event.currentTarget.dataset.createUrl);
    });

  document.querySelectorAll(".edit-user-button").forEach((button) => {
    button.addEventListener("click", () => openEditDialog(button));
  });

  document.querySelectorAll("[data-close-user-dialog]").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });

  form.addEventListener("submit", (event) => {
    const password = passwordInput.value;
    const passwordRepeat = passwordRepeatInput.value;
    const isCreate = form.dataset.mode === "create";

    if (isCreate && !password) {
      event.preventDefault();
      window.alert("Для нового пользователя нужно указать пароль.");
      return;
    }

    if (password || passwordRepeat) {
      if (password !== passwordRepeat) {
        event.preventDefault();
        window.alert("Пароли не совпадают.");
      }
    }
  });
});