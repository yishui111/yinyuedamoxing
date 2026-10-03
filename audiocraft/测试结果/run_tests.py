# -*- coding: utf-8 -*-
"""MusicGen 项目自动化测试脚本: 覆盖接口、功能、参数边界、复现性、显存管理。"""
import hashlib
import json
import os
import sys
import time

import requests

BASE = f"http://127.0.0.1:{os.environ.get('MUSICGEN_PORT', '7861')}"
HERE = os.path.dirname(os.path.abspath(__file__))
import soundfile as sf
import numpy as np

results = []


def record(case, name, ok, detail):
    results.append({"case": case, "name": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {case} {name}: {detail}", flush=True)


def wav_check(url):
    """下载生成的 wav 并校验有效性。"""
    r = requests.get(BASE + url, timeout=60)
    path = os.path.join(HERE, "samples", os.path.basename(url))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(r.content)
    info = sf.info(path)
    w, sr = sf.read(path)
    return {
        "path": path,
        "samplerate": info.samplerate,
        "duration": round(info.duration, 2),
        "channels": info.channels,
        "peak": round(float(np.abs(w).max()), 3),
        "rms": round(float(np.sqrt((w ** 2).mean())), 4),
        "md5": hashlib.md5(r.content).hexdigest(),
        "bytes": len(r.content),
    }


def gen(payload, timeout=2400):
    t0 = time.time()
    r = requests.post(BASE + "/api/generate", json=payload, timeout=timeout)
    elapsed = round(time.time() - t0, 1)
    return r, elapsed


print("========== T1 服务与页面 ==========", flush=True)
r = requests.get(BASE + "/", timeout=10)
record("T1.1", "首页加载", r.status_code == 200 and "MusicGen" in r.text,
       f"HTTP {r.status_code}, 包含标题: {'MusicGen' in r.text}")
r = requests.get(BASE + "/api/status", timeout=10)
st = r.json()
record("T1.2", "状态API", r.status_code == 200 and st["device"] == "cuda",
       f"device={st['device']}, dtype={st['dtype']}, gpu={st['gpu_name']}")
for asset in ["/static/style.css", "/static/app.js"]:
    r = requests.get(BASE + asset, timeout=10)
    record("T1.3", f"静态资源 {asset}", r.status_code == 200, f"HTTP {r.status_code}, {len(r.content)}B")

print("========== T2 基础生成功能 ==========", flush=True)
r, wall = gen({"prompt": "epic orchestral cinematic music, strings and drums, dramatic and powerful",
               "duration": 15, "guidance": 3.5, "temperature": 1.0, "top_k": 250})
j = r.json()
ok = j.get("ok") and abs(j["duration"] - 15) < 1.5
record("T2.1", "15s 史诗管弦乐", ok, json.dumps(j, ensure_ascii=False))
wav = wav_check(j["file"]) if j.get("ok") else {}
record("T2.2", "WAV 文件有效性", wav.get("peak", 0) > 0.1 and wav.get("rms", 0) > 0.01,
       f"{wav.get('samplerate')}Hz {wav.get('duration')}s ch={wav.get('channels')} peak={wav.get('peak')} rms={wav.get('rms')}")

print("========== T3 最长时长 30s ==========", flush=True)
r, wall = gen({"prompt": "energetic electronic dance music, heavy bass and synth leads, 128 bpm", "duration": 30})
j = r.json()
ok = j.get("ok") and abs(j["duration"] - 30) < 2
record("T3.1", "30s 电子舞曲(上限)", ok,
       f"请求30s 实际{j.get('duration')}s 生成耗时{j.get('elapsed')}s 峰值显存{j.get('peak_gb')}GB")

print("========== T4 种子复现性 ==========", flush=True)
p = {"prompt": "lo-fi hip hop beat with rainy vinyl crackle, chill and cozy", "duration": 8, "seed": 12345}
r1, _ = gen(dict(p))
j1 = r1.json()
w1 = wav_check(j1["file"])
r2, _ = gen(dict(p))
j2 = r2.json()
w2 = wav_check(j2["file"])
same = w1["md5"] == w2["md5"]
record("T4.1", "同种子两次生成一致", same, f"md5 {w1['md5'][:12]} vs {w2['md5'][:12]} -> {'一致' if same else '不一致'}")

print("========== T5 参数边界 ==========", flush=True)
r, _ = gen({"prompt": "gentle piano", "duration": 5})
j = r.json()
record("T5.1", "最短时长 5s", j.get("ok") and abs(j["duration"] - 5) < 1.2, f"实际 {j.get('duration')}s")
r, _ = gen({"prompt": "folk guitar", "duration": 999})
j = r.json()
record("T5.2", "超长时长钳制到 30s", j.get("ok") and j["duration"] <= 31, f"请求999s 实际 {j.get('duration')}s")
r = requests.post(BASE + "/api/generate", json={"prompt": ""}, timeout=30)
record("T5.3", "空提示词返回 400", r.status_code == 400, f"HTTP {r.status_code}, {r.json().get('error','')}")
r = requests.post(BASE + "/api/generate", data="{bad json", headers={"Content-Type": "application/json"}, timeout=30)
record("T5.4", "非法 JSON 返回 400", r.status_code == 400, f"HTTP {r.status_code}")

print("========== T6 中文提示词 ==========", flush=True)
r, _ = gen({"prompt": "欢快的爵士乐，萨克斯和钢琴", "duration": 8})
j = r.json()
wav = wav_check(j["file"]) if j.get("ok") else {}
record("T6.1", "中文提示词不报错且有输出", j.get("ok") and wav.get("rms", 0) > 0.005,
       f"ok={j.get('ok')} rms={wav.get('rms')} (MusicGen 文本编码器为英文 T5, 中文效果需人工试听)")

print("========== T7 显存释放 ==========", flush=True)
r = requests.post(BASE + "/api/unload", timeout=60)
v = r.json()["vram"]
record("T7.1", "卸载后显存归零", v["allocated_gb"] < 0.1, f"allocated={v['allocated_gb']}GB reserved={v['used_gb']}GB")
r = requests.get(BASE + "/api/status", timeout=10)
record("T7.2", "状态显示未加载", r.json()["loaded"] is False, f"loaded={r.json()['loaded']}")
r, _ = gen({"prompt": "soft ambient pad", "duration": 5})
record("T7.3", "卸载后可再次生成(自动重载)", r.json().get("ok", False),
       f"elapsed={r.json().get('elapsed')}s peak={r.json().get('peak_gb')}GB")

# 汇总
passed = sum(1 for x in results if x["ok"])
summary = {"total": len(results), "passed": passed, "failed": len(results) - passed,
           "time": time.strftime("%Y-%m-%d %H:%M:%S")}
with open(os.path.join(HERE, "test_results.json"), "w", encoding="utf-8") as f:
    json.dump({"summary": summary, "results": results}, f, ensure_ascii=False, indent=2)
print(f"\n===== 测试完成: {passed}/{len(results)} 通过 =====", flush=True)
sys.exit(0 if passed == len(results) else 1)
