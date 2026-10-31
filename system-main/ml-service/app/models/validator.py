import httpx


class ModelValidationError(ValueError): pass


class ModelValidator:
    PARAMETER_TYPES = {"int", "float", "enum"}

    VALIDATION_IMAGE_B64 = ("Qk1mAAAAAAAAADYAAAAoAAAABAAAAAQAAAABABgAAAAAADAAAADEDgAAxA4AAAAAAAAAAAAAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA")

    def __init__(self, model_url, expected_name, expected_version):
        self.expected_name = expected_name
        self.expected_version = expected_version
        self.client = httpx.Client(
            base_url=model_url.rstrip("/"),
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    def close(self): self.client.close()

    def validate(self):
        session_id = None

        try:
            metadata = self._get_and_validate_metadata()
            session_id = self._start_validation_session(metadata)
            self._send_probe_batch(session_id)

            return metadata

        finally:
            if session_id is not None:
                try: self._close_session(session_id)
                except httpx.HTTPError: pass

    def _get_and_validate_metadata(self):
        response = self.client.get("/metadata")
        response.raise_for_status()

        try:
            metadata = response.json()
        except ValueError as error:
            raise ModelValidationError("Endpoint /metadata должен возвращать JSON") from error

        if not isinstance(metadata, dict):
            raise ModelValidationError("Ответ /metadata должен быть JSON-объектом")

        required_fields = {
            "api_version",
            "name",
            "version",
            "task_type",
            "hyperparameters",
        }

        missing_fields = required_fields - metadata.keys()
        if missing_fields:
            raise ModelValidationError("В /metadata отсутствуют поля: " + ", ".join(sorted(missing_fields)))
        if metadata["api_version"] != "1":
            raise ModelValidationError("Неподдерживаемая версия API модели")
        if metadata["task_type"] != "classification":
            raise ModelValidationError("Поддерживаются только модели классификации")
        if not isinstance(metadata["name"], str) or not metadata["name"].strip():
            raise ModelValidationError("Некорректное имя модели")
        if (not isinstance(metadata["version"], str) or not metadata["version"].strip()):
            raise ModelValidationError("Некорректная версия модели")
        if (self.expected_name is not None and metadata["name"] != self.expected_name):
            raise ModelValidationError("Имя модели в /metadata не совпадает с указанным при регистрации")
        if (self.expected_version is not None and metadata["version"] != self.expected_version):
            raise ModelValidationError("Версия модели в /metadata не совпадает с указанной при регистрации")

        self._validate_hyperparameters(metadata["hyperparameters"])
        return metadata

    def _validate_hyperparameters(self, hyperparameters):
        if not isinstance(hyperparameters, list):
            raise ModelValidationError("Поле hyperparameters должно быть списком")

        names = set()
        for parameter in hyperparameters:
            if not isinstance(parameter, dict):
                raise ModelValidationError("Каждый гиперпараметр должен быть JSON-объектом")

            required_fields = {"name", "type", "default", "description"}
            missing_fields = required_fields - parameter.keys()

            if missing_fields:
                raise ModelValidationError("У гиперпараметра отсутствуют поля: " + ", ".join(sorted(missing_fields)))

            name = parameter["name"]
            parameter_type = parameter["type"]
            default = parameter["default"]

            if not isinstance(name, str) or not name.strip():
                raise ModelValidationError("Имя гиперпараметра должно быть непустой строкой")
            if name in names:
                raise ModelValidationError(f"Гиперпараметр {name!r} указан несколько раз")

            names.add(name)
            if parameter_type not in self.PARAMETER_TYPES:
                raise ModelValidationError(f"Неподдерживаемый тип гиперпараметра: {parameter_type!r}")
            if (not isinstance(parameter["description"], str) or not parameter["description"].strip()):
                raise ModelValidationError(f"У гиперпараметра {name!r} отсутствует описание")
            if parameter_type == "int":
                if isinstance(default, bool) or not isinstance(default, int):
                    raise ModelValidationError(f"default параметра {name!r} должен быть int")
            elif parameter_type == "float":
                if isinstance(default, bool) or not isinstance(default, (int, float)):
                    raise ModelValidationError(f"default параметра {name!r} должен быть float")
            elif parameter_type == "enum":
                enum_values = parameter.get("enum_values")

                if (not isinstance(enum_values, list) or not enum_values):
                    raise ModelValidationError(f"enum_values параметра {name!r} должен быть непустым списком")
                if default not in enum_values:
                    raise ModelValidationError(f"default параметра {name!r} отсутствует в enum_values")

    def _start_validation_session(self, metadata):
        hyperparameters = {
            parameter["name"]: parameter["default"]
            for parameter in metadata["hyperparameters"]
        }

        response = self.client.post("/sessions",
                                    json={
                                        "run_id": "validation",
                                        "hyperparameters": hyperparameters,
                                    })
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as error:
            raise ModelValidationError("Endpoint /sessions должен возвращать JSON") from error

        if not isinstance(payload, dict): raise ModelValidationError("Endpoint /sessions должен возвращать JSON")

        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ModelValidationError("Ответ /sessions не содержит корректный session_id")
        return session_id

    def _send_probe_batch(self, session_id):
        response = self.client.post(
            f"/sessions/{session_id}/batch",
            json={
                "test_request": True,
            },
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise ModelValidationError(
                "Endpoint batch вернул {}: {}".format(
                    error.response.status_code,
                    error.response.text[:2000],
                )
            ) from error

        try:
            payload = response.json()
        except ValueError as error:
            raise ModelValidationError("Endpoint batch должен возвращать JSON") from error

        if not isinstance(payload, dict): raise ModelValidationError("Endpoint batch должен возвращать JSON-объект")

        logits = payload.get("logits")

        if (
            not isinstance(logits, list)
            or len(logits) != 1
            or not isinstance(logits[0], list)
            or not logits[0]
        ):
            raise ModelValidationError("Ответ batch должен содержать logits для одного изображения")

        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            for value in logits[0]
        ):
            raise ModelValidationError("Все значения logits должны быть числами")

        loss = payload.get("loss")
        if (loss is not None and (isinstance(loss, bool) or not isinstance(loss, (int, float)))):
            raise ModelValidationError("loss должен быть числом или null")

    def _close_session(self, session_id):
        response = self.client.post(f"/sessions/{session_id}/close",
                                    json={})
        response.raise_for_status()