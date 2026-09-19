const DEFAULTS = {
  headless: true
};

const headless = document.querySelector("#headless");
const status = document.querySelector("#status");

document.querySelector("#save").addEventListener("click", save);
document.querySelector("#check").addEventListener("click", check);

load();

async function load() {
  const values = await chrome.storage.sync.get(DEFAULTS);
  headless.checked = values.headless !== false;
}

async function save() {
  await chrome.storage.sync.set({
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
  const mode = headless.checked ? "background" : "debug browser";
  setStatus("success", `Service ready in ${mode}, ${model}`);
}

function setStatus(state, message) {
  status.dataset.state = state;
  status.textContent = message;
}

