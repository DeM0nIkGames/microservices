import base64
import io
import math
import os
import threading
import uuid
import torch
from PIL import Image
from flask import Blueprint, jsonify, request, current_app
from torch.optim import Adam
from torchvision import transforms
from app.model.DPA.pg_decoders import Resnet18DecoderNetworks
from app.model.DPA.pg_encoders import Resnet18EncoderNetworks
from app.model.DPA.pg_networks import ProgGrowStageType
from app.model.DPA.rec_losses import RelativePerceptualL1Loss


bp = Blueprint("model", __name__)

SESSIONS = {}
SESSIONS_LOCK = threading.RLock()

MODEL_ROOT = os.environ.get("MODEL_ROOT", "/data/models")


def get_json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict): return {}
    else: return body


def decode_base64_image(item, image_size):
    encoded = item.get("image_base64")

    if encoded is None: encoded = item.get("image")
    if encoded is None: encoded = item.get("image_b64")
    if isinstance(encoded, dict): encoded = encoded.get("base64")
    if not isinstance(encoded, str): raise ValueError("В элементе батча отсутствует изображение в Base64")
    if encoded.startswith("data:"): encoded = encoded.split(",", 1)[1]
    try:
        raw_image = base64.b64decode(encoded)
        image = Image.open(io.BytesIO(raw_image)).convert("RGB")
    except Exception as error:
        raise ValueError("Не удалось декодировать изображение") from error

    transform = transforms.Compose([
        transforms.Resize((image_size, image_size)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=(0.5, 0.5, 0.5),
            std=(0.5, 0.5, 0.5),
        ),
    ])
    return transform(image)


class DPASession:
    def __init__(self, run_id, hyperparameters):
        self.run_id = run_id
        self.hyperparameters = dict(hyperparameters)
        self.lock = threading.RLock()

        self.image_size = int(hyperparameters.get("image_size", 32))
        self.latent_dim = int(hyperparameters.get("latent_dim", 32))
        self.base_channels = int(hyperparameters.get("base_channels", 32))
        self.learning_rate = float(hyperparameters.get("learning_rate", 0.002))
        self.threshold = float(hyperparameters.get("threshold", 0.1))        
        self.temperature = float(hyperparameters.get("temperature", 0.05))
        device_name = hyperparameters.get("device", "auto")

        if device_name == "cuda": self.device = torch.device("cuda")
        elif device_name == "cpu": self.device = torch.device("cpu")
        else: self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        stages_count = int(math.log(self.image_size, 2)) - 1
        inner_dims = [self.base_channels] * stages_count

        encoder_networks = Resnet18EncoderNetworks(
            max_input_res=self.image_size,
            output_res=1,
            input_dim=3,
            output_dim=self.latent_dim,
            inner_dims=inner_dims,
        )

        decoder_networks = Resnet18DecoderNetworks(
            input_res=1,
            max_output_res=self.image_size,
            input_dim=self.latent_dim,
            output_dim=3,
            inner_dims=inner_dims,
        )

        self.encoder = encoder_networks.get_net(
            ProgGrowStageType.stab,
            self.image_size,
        ).to(self.device)

        self.decoder = decoder_networks.get_net(
            ProgGrowStageType.stab,
            self.image_size,
        ).to(self.device)

        self.reconstruction_loss = RelativePerceptualL1Loss(
            reduction="mean",
            img_weight=0,
            feature_weights={
                "r32": 1,
            },
        ).to(self.device)

        self.reconstruction_loss.eval()

        self.optimizer = Adam(
            list(self.encoder.parameters())
            + list(self.decoder.parameters()),
            lr=self.learning_rate,
        )

    def reconstruct(self, images):
        latent = self.encoder(images)
        return self.decoder(latent)

    def get_anomaly_scores(self, images):
        self.encoder.eval()
        self.decoder.eval()
        self.reconstruction_loss.set_reduction("none")

        with torch.no_grad():
            reconstructed = self.reconstruct(images)
            scores = self.reconstruction_loss(
                images,
                reconstructed,
            )
        return scores

    def scores_to_logits(self, scores):
        temperature = max(self.temperature, 1e-8)
        anomaly_logit = (scores - self.threshold) / temperature
        normal_logit = -anomaly_logit
        return torch.stack([normal_logit, anomaly_logit], dim=1)

    def process_tensor_batch(self, images, labels, is_train):
        images = images.to(self.device)

        training_loss = None

        if is_train:
            normal_mask = torch.tensor(
                [label == 0 for label in labels],
                dtype=torch.bool,
                device=self.device,
            )

            normal_images = images[normal_mask]
            if normal_images.size(0) > 0:
                self.encoder.train()
                self.decoder.train()
                self.reconstruction_loss.set_reduction("mean")
                reconstructed = self.reconstruct(normal_images)
                training_loss = self.reconstruction_loss(normal_images, reconstructed)
                self.optimizer.zero_grad()
                training_loss.backward()
                self.optimizer.step()

        scores = self.get_anomaly_scores(images)
        logits = self.scores_to_logits(scores)
        if training_loss is None: loss_value = scores.mean().item()
        else: loss_value = training_loss.item()

        return {
            "loss": float(loss_value),
            "logits": logits.detach().cpu().tolist(),
            "anomaly_scores": scores.detach().cpu().tolist(),
        }

    def process_items(self, items, is_train):
        images = []
        labels = []

        for item in items:
            images.append(decode_base64_image(item=item, image_size=self.image_size))
            labels.append(int(item["label"]))

        image_tensor = torch.stack(images, dim=0)
        with self.lock:
            return self.process_tensor_batch(
                images=image_tensor,
                labels=labels,
                is_train=is_train,
            )

    def test_response(self):
        images = torch.zeros(1, 3, self.image_size, self.image_size)
        with self.lock:
            return self.process_tensor_batch(
                images=images,
                labels=[0],
                is_train=False,
            )

    def save(self, session_id):
        os.makedirs(MODEL_ROOT, exist_ok=True)

        checkpoint_path = os.path.join(MODEL_ROOT, "{}.pt".format(session_id))
        encoder_state = {name: value.detach().cpu() for name, value in self.encoder.state_dict().items()}
        decoder_state = {name: value.detach().cpu() for name, value in self.decoder.state_dict().items()}

        torch.save(
            {
                "run_id": self.run_id,
                "hyperparameters": self.hyperparameters,
                "encoder": encoder_state,
                "decoder": decoder_state,
            },
            checkpoint_path,
        )
        return checkpoint_path

    def close(self):
        del self.encoder
        del self.decoder
        del self.optimizer
        del self.reconstruction_loss

        if torch.cuda.is_available(): torch.cuda.empty_cache()


@bp.get("/metadata")
def get_metadata():
    return jsonify(
        name="Deep Perceptual Autoencoder",
        task_type="classification",
        classes={
            "0": "normal",
            "1": "anomaly",
        },
        api_version="1",
        version="1.1.0",
        hyperparameters=[
            {
                "name": "epochs",
                "type": "int",
                "default": 5,
                "description": "Количество эпох обучения.",
            },
            {
                "name": "batch_size",
                "type": "int",
                "default": 16,
                "description": "Размер батча.",
            },
            {
                "name": "learning_rate",
                "type": "float",
                "default": 0.002,
                "description": "Скорость обучения Adam.",
            },
            {
                "name": "latent_dim",
                "type": "int",
                "default": 32,
                "description": "Число каналов латентного представления.",
            },
            {
                "name": "base_channels",
                "type": "int",
                "default": 32,
                "description": "Число каналов во внутренних блоках.",
            },
            {
                "name": "image_size",
                "type": "enum",
                "enum_values": [32, 64],
                "default": 32,
                "description": "Размер изображения на входе модели.",
            },
            {
                "name": "threshold",
                "type": "float",
                "default": 0.1,
                "description": (
                    "Порог perceptual loss, после которого "
                    "изображение считается аномальным."
                ),
            },
            {
                "name": "temperature",
                "type": "float",
                "default": 0.05,
                "description": (
                    "Масштаб преобразования anomaly score в logits."
                ),
            },
            {
                "name": "device",
                "type": "enum",
                "enum_values": ["auto", "cpu", "cuda"],
                "default": "auto",
                "description": "Устройство выполнения модели.",
            },
        ],
    ), 200


@bp.post("/sessions")
def create_session():
    body = get_json_body()

    run_id = body.get("run_id")
    hyperparameters = body.get("hyperparameters", {})

    if not isinstance(hyperparameters, dict):
        return jsonify(
            error="hyperparameters должен быть JSON-объектом"
        ), 400

    session_id = str(uuid.uuid4())

    try:
        model_session = DPASession(
            run_id=run_id,
            hyperparameters=hyperparameters,
        )
    except Exception as error:
        return jsonify(
            error="Не удалось создать сессию: {}".format(error)
        ), 500

    with SESSIONS_LOCK:
        SESSIONS[session_id] = model_session

    return jsonify(
        session_id=session_id,
    ), 201


@bp.post("/sessions/<session_id>/batch")
def process_batch(session_id):
    body = get_json_body()

    with SESSIONS_LOCK:
        model_session = SESSIONS.get(session_id)

    if model_session is None:
        return jsonify(
            error="Сессия не найдена"
        ), 404

    if body.get("test_request") and not body.get("images"):
        try:
            result = model_session.test_response()
        except Exception as error:
            current_app.logger.exception(
                "Ошибка тестового запроса в сессии %s",
                session_id,
            )
            return jsonify(
                error="Тестовый запрос завершился ошибкой: {}".format(error)
            ), 500

        return jsonify(result), 200

    items = body.get("images")
    is_train = bool(body.get("is_train", False))

    if not isinstance(items, list) or not items:
        return jsonify(
            error="Поле images должно быть непустым списком"
        ), 400

    try:
        result = model_session.process_items(
            items=items,
            is_train=is_train,
        )
    except Exception as error:
        current_app.logger.exception(
            "Ошибка обработки батча в сессии %s",
            session_id,
        )
        return jsonify(
            error="Не удалось обработать батч: {}".format(error)
        ), 500

    return jsonify(result), 200


@bp.post("/sessions/<session_id>/close")
def close_session(session_id):
    with SESSIONS_LOCK:
        model_session = SESSIONS.pop(session_id, None)

    if model_session is None:
        return jsonify(
            error="Сессия не найдена"
        ), 404

    try:
        checkpoint_path = model_session.save(session_id)
        model_session.close()
    except Exception as error:
        return jsonify(
            error="Не удалось закрыть сессию: {}".format(error)
        ), 500

    return jsonify(
        status="closed",
        checkpoint_path=checkpoint_path,
    ), 200