# -*- coding: utf-8 -*-
"""
embedding_service.py

一个基于 FastAPI 和 ONNX Runtime 的高性能文本嵌入服务。
这个服务会加载本地的 ONNX 模型 (如 qwen3-embedding-0.6b) 并提供 API 接口。

前置依赖安装 (Prerequisites):
pip install modelscope onnxruntime fastapi "uvicorn[standard]" pydantic coloredlogs transformers

运行前准备:
1. 下载模型文件到指定目录, 例如 /path/to/ai-models/qwen3-embedding-0.6b
2. 设置环境变量: export MODEL_PATH=/path/to/ai-models

启动命令:
uvicorn embedding_service:app --host 0.0.0.0 --port 7999
"""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

import coloredlogs
import numpy as np
import onnxruntime as ort
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from modelscope import AutoTokenizer
from transformers import PreTrainedTokenizerFast

# --- 日志配置 ---
logger = logging.getLogger(__name__)
coloredlogs.install(
    level="INFO",
    datefmt="%Y-%m-%d %H:%M:%S",
    milliseconds=True,
    fmt="%(levelname)s %(asctime)s - [t-%(threadName)s] (%(filename)s:%(lineno)d) %(funcName)s : %(message)s",
)


# --- Pydantic 模型定义 ---
class EmbeddingRequest(BaseModel):
    model: str
    input: List[str]
    normalize: bool = True


class EmbeddingData(BaseModel):
    object: str = "embedding"
    embedding: List[float]
    index: int


class Usage(BaseModel):
    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    id: str
    model: str
    object: str = "list"
    data: List[EmbeddingData]
    usage: Usage


# --- ONNX 模型封装 ---
class OnnxModel:
    def __init__(
        self,
        base_model_path: Path,
        tokenizer: PreTrainedTokenizerFast,
        ort_session: ort.InferenceSession,
        model_config: Dict[str, Any],
    ):
        self.__base_model_path: Path = base_model_path
        self.__tokenizer: PreTrainedTokenizerFast = tokenizer
        self.__ort_session: ort.InferenceSession = ort_session
        self.__model_config: Dict[str, Any] = model_config
        self.__last_access_time: float = time.time()

    def update_last_access_time(self):
        self.__last_access_time = time.time()

    def get_last_access_time(self) -> float:
        return self.__last_access_time

    def release(self):
        self.__ort_session = None
        self.__tokenizer = None
        logger.info(f"资源已为模型释放: {self.__base_model_path.name}")

    def inference(self, inputs: List[str], normalize: bool = True) -> (int, np.ndarray):
        self.update_last_access_time()
        max_length = self.__model_config.get("max_length", 1024)
        encode_inputs = self.__tokenizer(
            inputs,
            return_tensors="np",
            padding="longest",
            truncation=True,
            max_length=max_length,
        )

        total_tokens = int(np.sum(encode_inputs["attention_mask"]))

        ort_inputs = {
            "input_ids": encode_inputs["input_ids"].astype(np.int64),
            "attention_mask": encode_inputs["attention_mask"].astype(np.int64),
        }

        ort_outputs = self.__ort_session.run(None, ort_inputs)
        embeddings = ort_outputs[0]

        # 使用 last_token 池化
        embeddings = embeddings[:, -1, :]

        if normalize:
            embeddings = embeddings / np.linalg.norm(
                embeddings, ord=2, axis=1, keepdims=True
            )

        return total_tokens, embeddings


# --- ONNX 模型管理器 ---
class OnnxModelManager:
    def __init__(
        self,
        base_path: Path,
        max_executors: int = 2,
        max_active_models: int = 3,
        max_idle_time: int = 300,
    ):
        self.__base_path = base_path
        self.__max_active_models = max_active_models
        self.__max_idle_time = max_idle_time
        self.__available_models: List[str] = []
        self.__loaded_models: Dict[str, OnnxModel] = {}
        self.__embedding_executor = ThreadPoolExecutor(
            max_workers=max_executors, thread_name_prefix="embedding"
        )
        self.__lock = threading.RLock()
        self.__running = True

    def init_available_models(self):
        logger.info("正在扫描可用的模型...")
        if not self.__base_path.is_dir():
            raise ValueError(f"模型基础路径 ({self.__base_path}) 不是一个目录")
        for model_path in self.__base_path.iterdir():
            if model_path.is_dir():
                self.__available_models.append(model_path.name)
        logger.info(f"可用的模型: {self.__available_models}")

    def load_model(self, model_name: str):
        with self.__lock:
            if len(self.__loaded_models) >= self.__max_active_models:
                raise ValueError(f"激活的模型过多 ({len(self.__loaded_models)})")
            if model_name not in self.__available_models:
                raise ValueError(f"模型 {model_name} 不可用")

            model_path = self.__base_path / model_name
            tokenizer = AutoTokenizer.from_pretrained(
                str(model_path), trust_remote_code=True
            )
            ort_session = ort.InferenceSession(
                str(model_path / "model.onnx"),
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )

            model_config = {}
            if (model_path / "onnx_config.json").exists():
                model_config = json.loads(
                    (model_path / "onnx_config.json").read_text(encoding="utf-8")
                )

            self.__loaded_models[model_name] = OnnxModel(
                model_path, tokenizer, ort_session, model_config
            )
            logger.info(
                f"模型 {model_name} 已加载。推理提供者: {ort_session.get_providers()}"
            )

    def unload_idle_models(self):
        while self.__running:
            time.sleep(10)  # 每10秒检查一次
            with self.__lock:
                idle_models = []
                for name, model in self.__loaded_models.items():
                    if (
                        time.time() - model.get_last_access_time()
                        > self.__max_idle_time
                    ):
                        idle_models.append(name)

                for name in idle_models:
                    logger.info(f"卸载空闲模型 {name}...")
                    self.__loaded_models[name].release()
                    del self.__loaded_models[name]

    async def inference_async(
        self, model_name: str, inputs: List[str], normalize: bool = True
    ):
        with self.__lock:
            if model_name not in self.__loaded_models:
                self.load_model(model_name)

        onnx_model = self.__loaded_models[model_name]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.__embedding_executor, onnx_model.inference, inputs, normalize
        )

    def stop(self):
        self.__running = False
        self.__embedding_executor.shutdown(wait=True)


# --- FastAPI 应用实例和生命周期 ---
onnx_model_manager: OnnxModelManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化
    model_path_str = os.getenv("MODEL_PATH", "/ai-models")  # 推荐使用环境变量
    base_path = Path(model_path_str)
    if not base_path.exists():
        logger.error(f"模型路径不存在: {base_path}")
        raise FileNotFoundError(f"模型路径不存在: {base_path}")

    global onnx_model_manager
    onnx_model_manager = OnnxModelManager(base_path)
    onnx_model_manager.init_available_models()

    # 启动后台线程来卸载空闲模型
    unload_thread = threading.Thread(
        target=onnx_model_manager.unload_idle_models, name="unload-models", daemon=True
    )
    unload_thread.start()

    logger.info("应用启动完成。")
    yield
    # 清理
    onnx_model_manager.stop()
    logger.info("应用已关闭。")


app = FastAPI(title="ONNX Embedding Service", version="1.0", lifespan=lifespan)


# --- API 端点 ---
@app.get("/health")
def health_check():
    """健康检查端点"""
    return {"status": "healthy", "message": "Embedding service is running"}


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def create_embeddings(request: EmbeddingRequest):
    try:
        total_tokens, embeddings = await onnx_model_manager.inference_async(
            request.model, request.input, request.normalize
        )

        data = [
            EmbeddingData(embedding=embedding.tolist(), index=i)
            for i, embedding in enumerate(embeddings)
        ]

        return EmbeddingResponse(
            id=f"emb_{uuid.uuid4()}",
            model=request.model,
            data=data,
            usage=Usage(prompt_tokens=total_tokens, total_tokens=total_tokens),
        )
    except Exception as e:
        logger.error(f"嵌入推理时出错: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7999)
