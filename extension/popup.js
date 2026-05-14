const DEFAULTS = {
  headless: true,
  downloadDir: "",
  captchaModelPath: ""
};

const downloadDir = document.querySelector("#downloadDir");
const captchaModelPath = document.querySelector("#captchaModelPath");
const headless = document.querySelector("#headless");
const status = document.querySelector("#status");

document.querySelector("#save").addEventListener("click", save);
document.querySelector("#check").addEventListener("click", check);

load();

async function load() {
  const values = await chrome.storage.sync.get(DEFAULTS);
  downloadDir.value = values.downloadDir || DEFAULTS.downloadDir;
  captchaModelPath.value = values.captchaModelPath || DEFAULTS.captchaModelPath;
  headless.checked = values.headless !== false;
}

async function save() {
  await chrome.storage.sync.set({
    downloadDir: downloadDir.value.trim(),
    captchaModelPath: captchaModelPath.value.trim(),
    headless: headless.checked
  });
  setStatus("success", "Saved");
}

async function check() {
  await save();
  const response = await chrome.runtime.sendMessage({ type: "health" });
  if (!response?.ok) {
    setStatus("error", response?.error || "Host unavailable");
    return;
  }
  const model = response.data.captcha_model_available ? "model ready" : "model missing";
  const platform = response.data.platform || "unknown platform";
  setStatus("success", `Host ready on ${platform}, ${model}`);
}

function setStatus(state, message) {
  status.dataset.state = state;
  status.textContent = message;
}
