# -*- coding: utf-8 -*-
"""
MusicGen 文本生成音乐 - Web 服务
模型: facebook/musicgen-medium (1.5B, Meta audiocraft 项目)
说明: audiocraft 官方依赖(torch==2.1.0/xformers<0.0.23)在 Windows 上安装困难,
      本服务采用 HuggingFace transformers 提供的 MusicGen 官方实现加载同一模型权重,
      生成质量与 audiocraft 一致, 详见 测试结果/测试报告.md。
"""
import gc
import os
import time
import threading
import secrets

import torch
import flask
from flask import Flask, render_template, request, jsonify, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

MODEL_ID = os.environ.get(
    "MUSICGEN_MODEL", os.path.join(BASE_DIR, "models", "musicgen-medium-fp16")
)
PORT = int(os.environ.get("MUSICGEN_PORT", "7861"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

_state = {
    "model": None,
    "processor": None,
    "loaded": False,
    "loading": False,
    "device": "cuda" if torch.cuda.is_available() else "cpu",
    "dtype": "float16",
    "error": None,
    "history": [],  # [{file, prompt, duration, elapsed, seed, time}]
}
_lock = threading.Lock()  # 防止并发占用 GPU
_gpu_lock = threading.Lock()


def load_model():
    """惰性加载模型(首次生成时触发)。"""
    if _state["loaded"] or _state["loading"]:
        return
    _state["loading"] = True
    try:
        from transformers import AutoProcessor, MusicgenForConditionalGeneration

        t0 = time.time()
        print(f"[MusicGen] 正在加载 {MODEL_ID} 到 {_state['device']} ...", flush=True)
        processor = AutoProcessor.from_pretrained(MODEL_ID)
        dtype = torch.float16 if _state["device"] == "cuda" else torch.float32
        model = MusicgenForConditionalGeneration.from_pretrained(
            MODEL_ID, torch_dtype=dtype
        ).to(_state["device"])
        model.eval()
        _state["model"] = model
        _state["processor"] = processor
        _state["loaded"] = True
        _state["dtype"] = str(dtype).replace("torch.", "")
        print(f"[MusicGen] 模型加载完成, 耗时 {time.time() - t0:.1f}s", flush=True)
    except Exception as e:  # noqa: BLE001
        _state["error"] = f"{type(e).__name__}: {e}"
        print(f"[MusicGen] 模型加载失败: {_state['error']}", flush=True)
        raise
    finally:
        _state["loading"] = False


def unload_model():
    """卸载模型并释放显存。"""
    with _lock:
        _state["model"] = None
        _state["processor"] = None
        _state["loaded"] = False
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    print("[MusicGen] 模型已卸载, 显存已释放", flush=True)


def vram_info():
    if not torch.cuda.is_available():
        return {"total_gb": 0, "used_gb": 0, "allocated_gb": 0}
    total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    used = torch.cuda.memory_reserved(0) / 1024**3
    alloc = torch.cuda.memory_allocated(0) / 1024**3
    return {
        "total_gb": round(total, 2),
        "used_gb": round(used, 2),
        "allocated_gb": round(alloc, 2),
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    return jsonify(
        {
            "model": MODEL_ID,
            "loaded": _state["loaded"],
            "loading": _state["loading"],
            "device": _state["device"],
            "dtype": _state["dtype"],
            "error": _state["error"],
            "gpu_name": (
                torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
            ),
            "vram": vram_info(),
            "history": _state["history"][-20:],
        }
    )


@app.post("/api/unload")
def api_unload():
    unload_model()
    return jsonify({"ok": True, "vram": vram_info()})


@app.post("/api/generate")
def api_generate():
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "请输入音乐描述文本"}), 400

    duration = min(max(float(data.get("duration", 10)), 5), 30)
    temperature = min(max(float(data.get("temperature", 1.0)), 0.1), 2.0)
    top_k = min(max(int(data.get("top_k", 250)), 0), 500)
    guidance = min(max(float(data.get("guidance", 3.0)), 1.0), 10.0)
    seed = data.get("seed")
    seed = int(seed) if seed not in (None, "") else secrets.randbelow(2**31)

    if not _state["loaded"]:
        try:
            with _lock:
                load_model()
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": f"模型加载失败: {_state['error'] or e}"}), 500

    with _gpu_lock:
        t0 = time.time()
        torch.manual_seed(seed)
        if _state["device"] == "cuda":
            torch.cuda.reset_peak_memory_stats()

        try:
            inputs = _state["processor"](
                text=[prompt], padding=True, return_tensors="pt"
            ).to(_state["device"])
            frame_rate = _state["model"].config.audio_encoder.frame_rate  # 50
            max_tokens = int(duration * frame_rate)
            audio = _state["model"].generate(
                **inputs,
                do_sample=True,
                guidance_scale=guidance,
                temperature=temperature,
                top_k=top_k if top_k > 0 else None,
                max_new_tokens=max_tokens,
            )
        except torch.cuda.OutOfMemoryError:
            unload_model()
            return (
                jsonify({"ok": False, "error": "显存不足, 已自动卸载模型, 请缩短时长后重试"}),
                500,
            )
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500

        sr = _state["model"].config.audio_encoder.sampling_rate  # 32000
        wav = audio[0, 0].float().cpu().numpy()
        elapsed = time.time() - t0

    import soundfile as sf

    fname = f"music_{time.strftime('%Y%m%d_%H%M%S')}_{seed}.wav"
    fpath = os.path.join(OUT_DIR, fname)
    sf.write(fpath, wav, sr)

    peak_gb = (
        round(torch.cuda.max_memory_allocated(0) / 1024**3, 2)
        if torch.cuda.is_available()
        else 0
    )
    item = {
        "file": f"/outputs/{fname}",
        "prompt": prompt,
        "duration": round(len(wav) / sr, 1),
        "elapsed": round(elapsed, 1),
        "seed": seed,
        "peak_gb": peak_gb,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _state["history"].append(item)
    print(f"[MusicGen] 生成完成: {fname} ({item['duration']}s, 耗时 {elapsed:.1f}s)", flush=True)
    return jsonify({"ok": True, **item})


@app.get("/outputs/<path:fname>")
def outputs(fname):
    return send_from_directory(OUT_DIR, fname)


if __name__ == "__main__":
    print(f"[MusicGen] Web 页面: http://127.0.0.1:{PORT}", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
