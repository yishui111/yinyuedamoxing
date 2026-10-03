const $ = (id) => document.getElementById(id);
const sliders = [
  { id: "duration", suffix: "s" },
  { id: "guidance", fmt: (v) => Number(v).toFixed(1) },
  { id: "temperature", fmt: (v) => Number(v).toFixed(1) },
  { id: "topk", fmt: (v) => (Number(v) === 0 ? "禁用" : v) },
];
sliders.forEach(({ id, suffix = "", fmt }) => {
  const el = $(id), label = $(id + "Val");
  const update = () => (label.textContent = (fmt ? fmt(el.value) : el.value) + suffix);
  el.addEventListener("input", update);
  update();
});

document.querySelectorAll(".chip").forEach((c) =>
  c.addEventListener("click", () => ($("prompt").value = c.dataset.p))
);

async function refreshStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    const dot = $("dot");
    dot.className = "dot " + (s.error ? "bad" : "ok");
    $("statusText").textContent = s.error
      ? "异常"
      : s.loaded ? "模型已就绪" : s.loading ? "模型加载中" : "待加载（首次生成时加载）";
    $("vram").textContent = s.gpu_name
      ? ` · ${s.gpu_name} · 显存 ${s.vram.used_gb}/${s.vram.total_gb}GB`
      : "";
    renderHistory(s.history || []);
  } catch (e) {
    $("dot").className = "dot bad";
    $("statusText").textContent = "服务未连接";
  }
}

function renderHistory(list) {
  const ul = $("history");
  if (!list.length) { ul.innerHTML = '<li class="empty">暂无记录</li>'; return; }
  ul.innerHTML = list
    .slice()
    .reverse()
    .map(
      (h) => `<li>
        <div class="h-top">
          <span class="h-prompt" title="${h.prompt.replace(/"/g, "&quot;")}">${h.prompt}</span>
          <span class="h-meta">#${h.seed}</span>
        </div>
        <div class="h-meta">${h.time} · 时长 ${h.duration}s · 耗时 ${h.elapsed}s · 峰值显存 ${h.peak_gb}GB</div>
        <audio controls preload="none" src="${h.file}"></audio>
      </li>`
    )
    .join("");
}

$("genBtn").addEventListener("click", async () => {
  const prompt = $("prompt").value.trim();
  const errBox = $("error");
  errBox.hidden = true;
  if (!prompt) { errBox.textContent = "请先输入音乐描述"; errBox.hidden = false; return; }

  $("genBtn").disabled = true;
  $("progress").hidden = false;
  $("progressText").textContent = `正在生成 ${$("duration").value}s 音乐，首次运行需先加载模型（约 1-2 分钟）…`;

  const t0 = Date.now();
  const timer = setInterval(() => {
    $("progressText").textContent =
      `生成中… 已等待 ${Math.round((Date.now() - t0) / 1000)}s（时长越长耗时越久）`;
  }, 1000);

  try {
    const body = {
      prompt,
      duration: +$("duration").value,
      guidance: +$("guidance").value,
      temperature: +$("temperature").value,
      top_k: +$("topk").value,
      seed: $("seed").value || null,
    };
    const r = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "生成失败");
    $("resultCard").hidden = false;
    $("player").src = j.file;
    $("player").play().catch(() => {});
    $("downloadBtn").href = j.file;
    $("resultMeta").innerHTML =
      `提示词：<b>${j.prompt}</b><br>时长 ${j.duration}s · 生成耗时 ${j.elapsed}s · 种子 <b>${j.seed}</b> · 峰值显存 ${j.peak_gb}GB`;
    $("resultCard").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    errBox.textContent = "❌ " + e.message;
    errBox.hidden = false;
  } finally {
    clearInterval(timer);
    $("progress").hidden = true;
    $("genBtn").disabled = false;
    refreshStatus();
  }
});

$("unloadBtn").addEventListener("click", async () => {
  $("unloadBtn").disabled = true;
  try {
    await fetch("/api/unload", { method: "POST" });
  } finally {
    $("unloadBtn").disabled = false;
    refreshStatus();
  }
});

refreshStatus();
setInterval(refreshStatus, 8000);
