const DEFAULTS = { backendUrl: "http://127.0.0.1:8765", headless: false, token: "" };
const backendUrl = document.querySelector("#backendUrl");
const token = document.querySelector("#token");
const headless = document.querySelector("#headless");
const status = document.querySelector("#status");
chrome.storage.local.get(DEFAULTS).then(values => {
  backendUrl.value = values.backendUrl;
  token.value = values.token;
  headless.checked = values.headless;
});
async function save() {
  await chrome.storage.local.set({
    backendUrl: backendUrl.value.trim() || DEFAULTS.backendUrl,
    token: token.value.trim(), headless: headless.checked
  });
  status.textContent = "已保存";
}
document.querySelector("#save").addEventListener("click", save);
document.querySelector("#check").addEventListener("click", async () => {
  try {
    await save();
    const response = await chrome.runtime.sendMessage({ type: "health" });
    status.textContent = response?.ok ? "服务连接正常" : response?.error || "无法连接";
  } catch (error) { status.textContent = error.message; }
});

