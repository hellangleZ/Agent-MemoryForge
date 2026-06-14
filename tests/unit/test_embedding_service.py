import importlib
import sys
import types

import numpy as np


class _FakeTokenizer:
    def __call__(self, inputs, return_tensors=None, padding=None, truncation=None, max_length=None):
        batch = len(inputs)
        return {
            "input_ids": np.ones((batch, 2), dtype=np.int64),
            "attention_mask": np.ones((batch, 2), dtype=np.int64),
        }


class _FakeSession:
    def __init__(self, *args, **kwargs):
        self._providers = ["CPUExecutionProvider"]

    def get_providers(self):
        return self._providers

    def run(self, *_args, **_kwargs):
        return [np.ones((2, 2, 3), dtype=np.float32)]


def _install_fake_embedding_deps(monkeypatch):
    fake_coloredlogs = types.SimpleNamespace(install=lambda *a, **k: None)
    fake_onnx = types.SimpleNamespace(InferenceSession=_FakeSession)

    class _FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(*_args, **_kwargs):
            return _FakeTokenizer()

    fake_modelscope = types.SimpleNamespace(AutoTokenizer=_FakeAutoTokenizer)
    fake_transformers = types.SimpleNamespace(PreTrainedTokenizerFast=object)
    fake_uvicorn = types.SimpleNamespace(run=lambda *a, **k: None)

    monkeypatch.setitem(sys.modules, "coloredlogs", fake_coloredlogs)
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_onnx)
    monkeypatch.setitem(sys.modules, "modelscope", fake_modelscope)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)


def _import_embedding_service(monkeypatch):
    _install_fake_embedding_deps(monkeypatch)
    if "embedding_service" in sys.modules:
        del sys.modules["embedding_service"]
    return importlib.import_module("embedding_service")


def test_onnx_model_inference(monkeypatch):
    embedding_service = _import_embedding_service(monkeypatch)
    model = embedding_service.OnnxModel(
        base_model_path=embedding_service.Path("/tmp"),
        tokenizer=_FakeTokenizer(),
        ort_session=_FakeSession(),
        model_config={"max_length": 4},
    )
    tokens, embeddings = model.inference(["hi", "there"], normalize=False)
    assert tokens == 4
    assert embeddings.shape == (2, 3)


def test_model_manager_load_and_inference(monkeypatch, tmp_path):
    embedding_service = _import_embedding_service(monkeypatch)
    model_dir = tmp_path / "model-a"
    model_dir.mkdir()
    (model_dir / "model.onnx").write_text("x", encoding="utf-8")
    (model_dir / "onnx_config.json").write_text("{}", encoding="utf-8")

    manager = embedding_service.OnnxModelManager(base_path=tmp_path)
    manager.init_available_models()
    manager.load_model("model-a")
    assert "model-a" in manager._OnnxModelManager__loaded_models

    total_tokens, embeddings = asyncio_run(manager.inference_async("model-a", ["a"]))
    assert total_tokens == 2
    assert embeddings.shape[0] == 2


def asyncio_run(coro):
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_health_and_embeddings(monkeypatch):
    embedding_service = _import_embedding_service(monkeypatch)

    class _StubManager:
        async def inference_async(self, model_name, inputs, normalize):
            return 2, np.ones((1, 3), dtype=np.float32)

    embedding_service.onnx_model_manager = _StubManager()
    health = embedding_service.health_check()
    assert health["status"] == "healthy"

    request = embedding_service.EmbeddingRequest(model="m", input=["x"], normalize=True)
    response = asyncio_run(embedding_service.create_embeddings(request))
    assert response.model == "m"
    assert response.data
