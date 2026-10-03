# -*- coding: utf-8 -*-
"""
AudioLDM2 文本生成音频/音乐 - Web 服务
模型: cvssp/audioldm2-large (AudioLDM 2, GitHub: haoheliu/audioldm2)
说明: 采用 HuggingFace diffusers 提供的 AudioLDM2Pipeline 官方实现加载同一模型权重,
      避免 audioldm2 仓库对 Linux 编译依赖的兼容问题, 详见 测试结果/测试报告.md。
"""
import gc
import os
import time
import threading
import secrets

import torch
from flask import Flask, render_template, request, jsonify, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

MODEL_ID = os.environ.get("AUDIOLDM2_MODEL", "cvssp/audioldm2-large")
PORT = int(os.environ.get("AUDIOLDM2_PORT", "7862"))

app = Flask(__name__)

_state = {
    "pipe": None,
    "loaded": False,
    "loading": False,
    "device": "cuda" if torch.cuda.is_available() else "cpu",
    "error": None,
    "history": [],
}
_lock = threading.Lock()
_gpu_lock = threading.Lock()


def load_model():
    if _state["loaded"] or _state["loading"]:
        return
    _state["loading"] = True
    try:
        from diffusers import AudioLDM2Pipeline

        t0 = time.time()
        print(f"[AudioLDM2] 正在加载 {MODEL_ID} 到 {_state['device']} ...", flush=True)
        dtype = torch.float16 if _state["device"] == "cuda" else torch.float32
        pipe = AudioLDM2Pipeline.from_pretrained(MODEL_ID, torch_dtype=dtype)
        pipe = pipe.to(_state["device"])
        # 开启 CPU offload 以防低显存机器 OOM(16GB 显卡不会触发, 保险起见保留注释)
        # pipe.enable_model_cpu_offload()
        _state["pipe"] = pipe
        _state["loaded"] = True
        print(f"[AudioLDM2] 模型加载完成, 耗时 {time.time() - t0:.1f}s", flush=True)
    except Exception as e:  # noqa: BLE001
        _state["error"] = f"{type(e).__name__}: {e}"
        print(f"[AudioLDM2] 模型加载失败: {_state['error']}", flush=True)
        raise
    finally:
        _state["loading"] = False


def unload_model():
    with _lock:
        _state["pipe"] = None
        _state["loaded"] = False
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    print("[AudioLDM2] 模型已卸载, 显存已释放", flush=True)


def vram_info():
    if not torch.cuda.is_available():
        return {"total_gb": 0, "used_gb": 0, "allocated_gb": 0}
    return {
        "total_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2),
        "used_gb": round(torch.cuda.memory_reserved(0) / 1024**3, 2),
        "allocated_gb": round(torch.cuda.memory_allocated(0) / 1024**3, 2),
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    sr = _state["pipe"].vocoder.config.sampling_rate if _state["loaded"] else 16000
    return jsonify(
        {
            "model": MODEL_ID,
            "loaded": _state["loaded"],
            "loading": _state["loading"],
            "device": _state["device"],
            "error": _state["error"],
            "sample_rate": sr,
            "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
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
        return jsonify({"ok": False, "error": "请输入音频描述文本"}), 400

    duration = min(max(float(data.get("duration", 10)), 5), 20)
    steps = min(max(int(data.get("steps", 100)), 20), 300)
    guidance = min(max(float(data.get("guidance", 4.5)), 1.0), 10.0)
    negative = (data.get("negative_prompt") or "").strip() or None
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
        generator = torch.Generator(device=_state["device"]).manual_seed(seed)
        if _state["device"] == "cuda":
            torch.cuda.reset_peak_memory_stats()
        try:
            audio = _state["pipe"](
                prompt=prompt,
                negative_prompt=negative,
                audio_length_in_s=duration,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=generator,
            ).audios[0]
        except torch.cuda.OutOfMemoryError:
            unload_model()
            return (
                jsonify({"ok": False, "error": "显存不足, 已自动卸载模型, 请稍后重试"}),
                500,
            )
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500

        sr = _state["pipe"].vocoder.config.sampling_rate
        elapsed = time.time() - t0

    import soundfile as sf
    import numpy as np

    audio = np.int16((audio / np.max(np.abs(audio))) * 32767)  # 峰值归一化
    fname = f"audio_{time.strftime('%Y%m%d_%H%M%S')}_{seed}.wav"
    fpath = os.path.join(OUT_DIR, fname)
    sf.write(fpath, audio, sr)

    peak_gb = (
        round(torch.cuda.max_memory_allocated(0) / 1024**3, 2)
        if torch.cuda.is_available()
        else 0
    )
    item = {
        "file": f"/outputs/{fname}",
        "prompt": prompt,
        "duration": round(len(audio) / sr, 1),
        "elapsed": round(elapsed, 1),
        "steps": steps,
        "seed": seed,
        "peak_gb": peak_gb,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _state["history"].append(item)
    print(f"[AudioLDM2] 生成完成: {fname} ({item['duration']}s, 耗时 {elapsed:.1f}s)", flush=True)
    return jsonify({"ok": True, **item})


@app.get("/outputs/<path:fname>")
def outputs(fname):
    return send_from_directory(OUT_DIR, fname)


if __name__ == "__main__":
    print(f"[AudioLDM2] Web 页面: http://127.0.0.1:{PORT}", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
