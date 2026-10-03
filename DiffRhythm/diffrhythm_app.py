# -*- coding: utf-8 -*-
"""
DiffRhythm 歌词生成完整歌曲 - Web 服务
模型: ASLP-lab/DiffRhythm-1_2 (GitHub: ASLP-lab/DiffRhythm)
功能: LRC 时间戳歌词 + 风格提示词 → 最长 95 秒带人声完整歌曲(44.1kHz)
说明: 必须在仓库根目录运行(依赖 ./model ./g2p ./infer/example/vocal.npy 相对路径)。
      英文/中文歌词音素化依赖 eSpeak NG (phonemizer)。
"""
import os
import sys
import time
import random
import threading
import secrets

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)  # prepare_model / g2p / vocal.npy 均使用相对路径
sys.path.insert(0, APP_DIR)

import torch
from flask import Flask, render_template, request, jsonify, send_from_directory

PORT = int(os.environ.get("DIFFRHYTHM_PORT", "7863"))
MAX_FRAMES = 2048          # v1.2 标准版: 95 秒
SONG_SECONDS = 95
SR = 44100

app = Flask(__name__)

_state = {
    "cfm": None, "tokenizer": None, "muq": None, "vae": None,
    "loaded": False, "loading": False,
    "device": "cuda" if torch.cuda.is_available() else "cpu",
    "error": None, "history": [],
}
_lock = threading.Lock()
_gpu_lock = threading.Lock()


def _patch_muq_loader():
    """muq 0.1.0 依赖旧版 huggingface_hub 的 PyTorchModelHubMixin 传参方式;
    新版(>=0.26)不再向 __init__(config) 传位置参数导致 TypeError。
    这里手动读取本地缓存中的 config.json 与权重并构造模型, 绕开 from_pretrained。
    同时覆盖 MuQMuLan(MuLan 主模型) 与 MuQ(其 AST 音频骨干网)。"""
    import glob
    import json
    import muq as _muq_pkg
    from muq.muq_mulan import MuQMuLan as _MuQMuLan

    def _make_loader():
        import inspect

        def _from_pretrained(cls, model_id=None, cache_dir=None, **kwargs):
            # MuQ 骨干网由 MuLan 内部加载时不带 cache_dir, 回退到仓库约定的 ./pretrained
            cache_dir = cache_dir or "./pretrained"
            pattern = os.path.join(
                cache_dir, f"models--{model_id.replace('/', '--')}", "snapshots", "*"
            )
            snap = sorted(glob.glob(pattern))
            if not snap:
                raise FileNotFoundError(f"未找到 {model_id} 的本地缓存: {pattern}")
            snap = snap[-1]
            with open(os.path.join(snap, "config.json"), encoding="utf-8") as f:
                config = json.load(f)
            params = inspect.signature(cls.__init__).parameters
            if "hf_hub_cache_dir" in params:
                model = cls(config, hf_hub_cache_dir=cache_dir)
            else:
                model = cls(config)
            bin_path = os.path.join(snap, "pytorch_model.bin")
            sd = torch.load(bin_path, map_location="cpu", weights_only=True)
            model.load_state_dict(sd, strict=False)
            del sd  # 及时释放权重副本, 降低加载期内存峰值
            import gc
            gc.collect()
            print(f"[DiffRhythm] {cls.__name__} 已从本地缓存加载: {snap}", flush=True)
            return model
        return _from_pretrained

    _loader = _make_loader()
    _muq_pkg.MuQ.from_pretrained = classmethod(_loader)
    _MuQMuLan.from_pretrained = classmethod(_loader)


def load_model():
    if _state["loaded"] or _state["loading"]:
        return
    _state["loading"] = True
    try:
        t0 = time.time()
        print(f"[DiffRhythm] 正在加载模型(DiT-1B + VAE + MuQ-MuLan) 到 {_state['device']} ...", flush=True)
        _patch_muq_loader()  # muq 0.1.0 与 huggingface_hub>=0.26 的 mixin 不兼容, 打兼容垫片
        from infer.infer_utils import prepare_model
        cfm, tokenizer, muq, vae = prepare_model(MAX_FRAMES, _state["device"])
        _state.update(cfm=cfm, tokenizer=tokenizer, muq=muq, vae=vae)
        _state["loaded"] = True
        print(f"[DiffRhythm] 模型加载完成, 耗时 {time.time() - t0:.1f}s", flush=True)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        _state["error"] = f"{type(e).__name__}: {e}"
        print(f"[DiffRhythm] 模型加载失败: {_state['error']}", flush=True)
        raise
    finally:
        _state["loading"] = False


def unload_model():
    with _lock:
        for k in ("cfm", "tokenizer", "muq", "vae"):
            _state[k] = None
        _state["loaded"] = False
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    print("[DiffRhythm] 模型已卸载, 显存已释放", flush=True)


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
    return jsonify(
        {
            "model": "ASLP-lab/DiffRhythm-1_2",
            "loaded": _state["loaded"],
            "loading": _state["loading"],
            "device": _state["device"],
            "error": _state["error"],
            "song_seconds": SONG_SECONDS,
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
    lrc = (data.get("lyrics") or "").strip()
    style = (data.get("style") or "").strip()
    seed = data.get("seed")
    seed = int(seed) if seed not in (None, "") else secrets.randbelow(2**31)

    if not lrc:
        return jsonify({"ok": False, "error": "请输入 LRC 格式歌词"}), 400
    if not style:
        return jsonify({"ok": False, "error": "请输入风格提示词(英文)"}), 400

    if not _state["loaded"]:
        try:
            with _lock:
                load_model()
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": f"模型加载失败: {_state['error'] or e}"}), 500

    from infer.infer_utils import (
        decode_audio,
        get_lrc_token,
        get_negative_style_prompt,
        get_reference_latent,
        get_style_prompt,
    )
    from einops import rearrange

    with _gpu_lock:
        t0 = time.time()
        random.seed(seed)
        torch.manual_seed(seed)
        if _state["device"] == "cuda":
            torch.cuda.reset_peak_memory_stats()
        try:
            with torch.inference_mode():
                lrc_prompt, start_time, end_frame, song_duration = get_lrc_token(
                    MAX_FRAMES, lrc, _state["tokenizer"], SONG_SECONDS, _state["device"]
                )
                style_prompt = get_style_prompt(_state["muq"], prompt=style)
                negative_style_prompt = get_negative_style_prompt(_state["device"])
                cond, pred_frames = get_reference_latent(
                    _state["device"], MAX_FRAMES, False, None, None, _state["vae"]
                )

                latents, _ = _state["cfm"].sample(
                    cond=cond,
                    text=lrc_prompt,
                    duration=end_frame,
                    style_prompt=style_prompt,
                    max_duration=end_frame,
                    song_duration=song_duration,
                    negative_style_prompt=negative_style_prompt,
                    steps=32,
                    cfg_strength=4.0,
                    start_time=start_time,
                    latent_pred_segments=pred_frames,
                    batch_infer_num=1,
                )

                latent = latents[0].to(torch.float32).transpose(1, 2)
                output = decode_audio(latent, _state["vae"], chunked=False)
                output = rearrange(output, "b d n -> d (b n)")
                output = (
                    output.to(torch.float32)
                    .div(torch.max(torch.abs(output)))
                    .clamp(-1, 1)
                    .mul(32767)
                    .to(torch.int16)
                    .cpu()
                )
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                unload_model()
                return jsonify({"ok": False, "error": "显存不足, 已自动卸载模型, 请重试"}), 500
            return jsonify({"ok": False, "error": f"RuntimeError: {e}"}), 500
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500

        elapsed = time.time() - t0

    import torchaudio

    fname = f"song_{time.strftime('%Y%m%d_%H%M%S')}_{seed}.wav"
    out_dir = os.path.join(APP_DIR, "outputs")
    os.makedirs(out_dir, exist_ok=True)
    torchaudio.save(os.path.join(out_dir, fname), output, sample_rate=SR)

    peak_gb = (
        round(torch.cuda.max_memory_allocated(0) / 1024**3, 2)
        if torch.cuda.is_available()
        else 0
    )
    n_lines = len([l for l in lrc.splitlines() if l.strip().startswith("[")])
    item = {
        "file": f"/outputs/{fname}",
        "style": style,
        "lines": n_lines,
        "duration": SONG_SECONDS,
        "elapsed": round(elapsed, 1),
        "seed": seed,
        "peak_gb": peak_gb,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _state["history"].append(item)
    print(f"[DiffRhythm] 生成完成: {fname} (耗时 {elapsed:.1f}s)", flush=True)
    return jsonify({"ok": True, **item})


@app.get("/outputs/<path:fname>")
def outputs(fname):
    return send_from_directory(os.path.join(APP_DIR, "outputs"), fname)


if __name__ == "__main__":
    print(f"[DiffRhythm] Web 页面: http://127.0.0.1:{PORT}", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
