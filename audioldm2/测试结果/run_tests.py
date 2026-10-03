# -*- coding: utf-8 -*-
"""AudioLDM2 项目自动化测试脚本: 接口、功能、参数边界、复现性、显存管理。"""
import hashlib
import json
import os
import sys
import time

import requests
import soundfile as sf
import numpy as np

BASE = "http://127.0.0.1:7862"
HERE = os.path.dirname(os.path.abspath(__file__))

results = []


def record(case, name, ok, detail):
    results.append({"case": case, "name": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {case} {name}: {detail}", flush=True)


def wav_check(url):
    r = requests.get(BASE + url, timeout=60)
    path = os.path.join(HERE, "samples", os.path.basename(url))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(r.content)
    info = sf.info(path)
    w, sr = sf.read(path)
    return {
        "samplerate": info.samplerate,
        "duration": round(info.duration, 2),
        "channels": info.channels,
        "peak": round(float(np.abs(w).max()), 3),
        "rms": round(float(np.sqrt((w ** 2).mean())), 4),
        "md5": hashlib.md5(r.content).hexdigest(),
    }


def gen(payload, timeout=2400):
    t0 = time.time()
    r = requests.post(BASE + "/api/generate", json=payload, timeout=timeout)
    return r, round(time.time() - t0, 1)


print("========== T1 服务与页面 ==========", flush=True)
r = requests.get(BASE + "/", timeout=10)
record("T1.1", "首页加载", r.status_code == 200 and "AudioLDM" in r.text, f"HTTP {r.status_code}")
r = requests.get(BASE + "/api/status", timeout=10)
st = r.json()
record("T1.2", "状态API", r.status_code == 200 and st["device"] == "cuda", f"gpu={st['gpu_name']} sr={st['sample_rate']}")
r = requests.get(BASE + "/", timeout=10)
record("T1.3", "页面内联样式与脚本", "<style>" in r.text and "refreshStatus" in r.text,
       f"style={('<style>' in r.text)}, script={('refreshStatus' in r.text)}")

print("========== T2 音乐生成 ==========", flush=True)
r, wall = gen({"prompt": "A grand orchestral piece with violins and timpani, epic and majestic",
               "duration": 10, "steps": 100, "guidance": 4.5})
j = r.json()
record("T2.1", "10s 管弦乐", j.get("ok") and abs(j["duration"] - 10) < 1,
       f"耗时 {j.get('elapsed')}s 峰值显存 {j.get('peak_gb')}GB")
w = wav_check(j["file"])
record("T2.2", "WAV 有效性", w["peak"] > 0.1 and w["rms"] > 0.005,
       f"{w['samplerate']}Hz {w['duration']}s peak={w['peak']} rms={w['rms']}")

print("========== T3 音效生成 ==========", flush=True)
r, _ = gen({"prompt": "Rain falling on leaves with distant thunder, peaceful nature ambience",
            "duration": 10, "steps": 80, "negative_prompt": "low quality, musical"})
j = r.json()
w = wav_check(j["file"])
record("T3.1", "10s 雨声雷鸣+反向提示词", j.get("ok") and w["rms"] > 0.005,
       f"耗时 {j.get('elapsed')}s rms={w['rms']}")

print("========== T4 时长上限 20s ==========", flush=True)
r, _ = gen({"prompt": "Sci-fi spaceship engine humming, deep electronic drone", "duration": 20, "steps": 60})
j = r.json()
record("T4.1", "20s 科幻音效", j.get("ok") and abs(j["duration"] - 20) < 1.2,
       f"实际 {j.get('duration')}s 耗时 {j.get('elapsed')}s")

print("========== T5 种子复现性 ==========", flush=True)
p = {"prompt": "Ocean waves crashing on the beach, seagulls in the distance", "duration": 8,
     "steps": 50, "seed": 42}
r1, _ = gen(dict(p)); w1 = wav_check(r1.json()["file"])
r2, _ = gen(dict(p)); w2 = wav_check(r2.json()["file"])
record("T5.1", "同种子两次一致", w1["md5"] == w2["md5"],
       f"{w1['md5'][:12]} vs {w2['md5'][:12]} -> {'一致' if w1['md5']==w2['md5'] else '不一致'}")

print("========== T6 参数边界 ==========", flush=True)
r, _ = gen({"prompt": "a bird chirping", "duration": 5, "steps": 30})
j = r.json()
record("T6.1", "最短 5s + 最少步数", j.get("ok") and abs(j["duration"] - 5) < 1, f"实际 {j.get('duration')}s")
r, _ = gen({"prompt": "fire crackling", "duration": 999, "steps": 9999})
j = r.json()
record("T6.2", "越界钳制(时长20s/步数300)", j.get("ok") and j["duration"] <= 21,
       f"请求 999s/9999步 -> {j.get('duration')}s/{j.get('steps')}步")
r = requests.post(BASE + "/api/generate", json={"prompt": ""}, timeout=30)
record("T6.3", "空提示词 400", r.status_code == 400, str(r.json().get("error", ""))[:40])

print("========== T7 显存释放 ==========", flush=True)
r = requests.post(BASE + "/api/unload", timeout=60)
v = r.json()["vram"]
record("T7.1", "卸载后显存归零", v["allocated_gb"] < 0.1, f"allocated={v['allocated_gb']}GB")
r, _ = gen({"prompt": "wind blowing through trees", "duration": 5, "steps": 40})
record("T7.2", "卸载后自动重载生成", r.json().get("ok", False), f"elapsed={r.json().get('elapsed')}s")

passed = sum(1 for x in results if x["ok"])
summary = {"total": len(results), "passed": passed, "failed": len(results) - passed,
           "time": time.strftime("%Y-%m-%d %H:%M:%S")}
with open(os.path.join(HERE, "test_results.json"), "w", encoding="utf-8") as f:
    json.dump({"summary": summary, "results": results}, f, ensure_ascii=False, indent=2)
print(f"\n===== 测试完成: {passed}/{len(results)} 通过 =====", flush=True)
sys.exit(0 if passed == len(results) else 1)
