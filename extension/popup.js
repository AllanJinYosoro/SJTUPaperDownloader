const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8765",
  headless: true
};

const backendUrl = document.querySelector("#backendUrl");
const headless = document.querySelector("#headless");
const status = document.querySelector("#status");

document.querySelector("#save").addEventListener("click", save);
document.querySelector("#check").addEventListener("click", check);

load();

async function load() {
  const values = await chrome.storage.sync.get(DEFAULTS);
  backendUrl.value = values.backendUrl || DEFAULTS.backendUrl;
  headless.checked = values.headless !== false;
}

async function save() {
  await chrome.storage.sync.set({
    backendUrl: backendUrl.value.replace(/\/+$/, "") || DEFAULTS.backendUrl,
    headless: headless.checked
  });
  setStatus("success", "Saved");
}

async function check() {
  await save();
  const response = await chrome.runtime.sendMessage({ type: "health" });
  if (!response?.ok) {
    setStatus("error", response?.error || "Service unavailable");
    return;
  }
  const model = response.data.captcha_model_available ? "model ready" : "model missing";
  setStatus("success", `Service ready, ${model}`);
}

function setStatus(state, message) {
  status.dataset.state = state;
  status.textContent = message;
}

