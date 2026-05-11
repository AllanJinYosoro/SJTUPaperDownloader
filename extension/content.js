const BUTTON_CLASS = "sjtu-paper-download-button";
const STATUS_CLASS = "sjtu-paper-download-status";
const CAPTCHA_CLASS = "sjtu-paper-captcha-panel";

injectButtons();

const observer = new MutationObserver(() => injectButtons());
observer.observe(document.documentElement, { childList: true, subtree: true });

function injectButtons() {
  const results = document.querySelectorAll(".gs_r.gs_or, .gs_r");
  for (const result of results) {
    if (result.querySelector(`.${BUTTON_CLASS}`)) {
      continue;
    }
    const titleNode = result.querySelector("h3.gs_rt");
    const title = extractTitle(titleNode);
    if (!title) {
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = BUTTON_CLASS;
    button.textContent = "SJTU PDF";
    button.title = "Download this paper through SJTU library";
    button.addEventListener("click", () => startDownload(button, result, title));

    const status = document.createElement("span");
    status.className = STATUS_CLASS;
    status.setAttribute("aria-live", "polite");

    const container = document.createElement("span");
    container.className = "sjtu-paper-download-container";
    container.append(button, status);

    titleNode.insertAdjacentElement("afterend", container);
  }
}

function extractTitle(titleNode) {
  if (!titleNode) {
    return "";
  }
  const clone = titleNode.cloneNode(true);
  for (const marker of clone.querySelectorAll(".gs_ct1, .gs_ct2")) {
    marker.remove();
  }
  return clone.textContent.replace(/\[[^\]]+\]/g, "").trim();
}

async function startDownload(button, result, title) {
  setState(button, result, "queued", "Queued");
  const started = await chrome.runtime.sendMessage({
    type: "startDownload",
    payload: {
      title,
      scholarUrl: window.location.href
    }
  });
  if (!started?.ok) {
    setState(button, result, "error", started?.error || "Local service unavailable");
    return;
  }
  await pollTask(button, result, started.data.task_id);
}

async function pollTask(button, result, taskId) {
  for (;;) {
    await sleep(1500);
    const response = await chrome.runtime.sendMessage({ type: "getTask", taskId });
    if (!response?.ok) {
      setState(button, result, "error", response?.error || "Could not read task");
      return;
    }
    const task = response.data;
    if (task.status === "success") {
      removeCaptchaPrompt(result);
      setState(button, result, "success", "Downloaded");
      return;
    }
    if (task.status === "error") {
      removeCaptchaPrompt(result);
      setState(button, result, "error", task.error || "Failed");
      return;
    }
    if (task.metadata?.captcha_required && task.metadata?.captcha_image) {
      setState(button, result, "running", "Captcha needed");
      renderCaptchaPrompt(result, taskId, task.metadata.captcha_image);
      continue;
    }
    removeCaptchaPrompt(result);
    setState(button, result, "running", task.step || task.status);
  }
}

function setState(button, result, state, message) {
  button.dataset.state = state;
  button.disabled = state === "queued" || state === "running";
  const status = result.querySelector(`.${STATUS_CLASS}`);
  if (status) {
    status.textContent = message;
    status.dataset.state = state;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function renderCaptchaPrompt(result, taskId, imageData) {
  let panel = result.querySelector(`.${CAPTCHA_CLASS}`);
  if (panel?.dataset.image === imageData) {
    return;
  }
  removeCaptchaPrompt(result);

  panel = document.createElement("form");
  panel.className = CAPTCHA_CLASS;
  panel.dataset.image = imageData;

  const image = document.createElement("img");
  image.src = imageData;
  image.alt = "JAccount captcha";

  const input = document.createElement("input");
  input.type = "text";
  input.autocomplete = "off";
  input.inputMode = "latin";
  input.maxLength = 8;
  input.placeholder = "验证码";

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "提交";

  const message = document.createElement("span");
  message.className = "sjtu-paper-captcha-message";

  panel.append(image, input, submit, message);
  panel.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) {
      message.textContent = "请输入验证码";
      return;
    }
    submit.disabled = true;
    message.textContent = "Submitting";
    const response = await chrome.runtime.sendMessage({
      type: "submitCaptcha",
      taskId,
      text
    });
    if (!response?.ok) {
      submit.disabled = false;
      message.textContent = response?.error || "提交失败";
      return;
    }
    message.textContent = "Submitted";
  });

  const container = result.querySelector(".sjtu-paper-download-container");
  container?.insertAdjacentElement("afterend", panel);
  input.focus();
}

function removeCaptchaPrompt(result) {
  result.querySelector(`.${CAPTCHA_CLASS}`)?.remove();
}
