const BUTTON_CLASS = "sjtu-paper-download-button";
injectButtons();
let scheduled = false;
new MutationObserver(() => {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => { scheduled = false; injectButtons(); });
}).observe(document.documentElement, { childList: true, subtree: true });

function injectButtons() {
  for (const result of document.querySelectorAll(".gs_r")) {
    if (result.querySelector("." + BUTTON_CLASS)) continue;
    const titleNode = result.querySelector("h3.gs_rt");
    if (!titleNode) continue;
    const clone = titleNode.cloneNode(true);
    clone.querySelectorAll(".gs_ct1, .gs_ct2").forEach(node => node.remove());
    const title = clone.textContent.trim();
    if (!title) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = BUTTON_CLASS;
    button.textContent = "SJTU PDF";
    const status = document.createElement("span");
    status.className = "sjtu-paper-download-status";
    status.setAttribute("aria-live", "polite");
    const container = document.createElement("span");
    container.className = "sjtu-paper-download-container";
    container.append(button, status);
    titleNode.insertAdjacentElement("afterend", container);
    button.addEventListener("click", async () => {
      button.disabled = true;
      status.textContent = "排队中…";
      try {
        const started = await send({ type: "startDownload", payload: { title, scholarUrl: location.href } });
        while (button.isConnected) {
          await new Promise(resolve => setTimeout(resolve, 1500));
          const task = await send({ type: "getTask", taskId: started.task_id });
          if (task.status === "error") throw new Error(task.error || "下载失败");
          if (task.status === "success") {
            status.textContent = "已保存（" + (task.metadata?.provider || "SJTU") + "）：" + task.result_path +
              (task.metadata?.provider === "SSRN" ? "；可能为工作论文版本" : "");
            button.dataset.state = "success";
            return;
          }
          status.textContent = task.step === "queued" ? "排队中…" : task.step;
        }
      } catch (error) {
        status.textContent = error.message || "无法连接本地服务";
        button.dataset.state = "error";
      } finally {
        button.disabled = false;
      }
    });
  }
}

async function send(message) {
  const result = await chrome.runtime.sendMessage(message);
  if (!result?.ok) throw new Error(result?.error || "请检查本地服务是否启动");
  return result.data;
}
