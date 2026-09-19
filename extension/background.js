const DEFAULTS = { backendUrl: "http://127.0.0.1:8765", headless: false, token: "" };

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id) return false;
  handle(message).then(respond).catch(error => respond({ ok: false, error: error.message }));
  return true;
});

async function handle(message) {
  const config = await chrome.storage.local.get(DEFAULTS);
  const url = new URL(config.backendUrl);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) {
    throw new Error("服务地址必须是本机 http://127.0.0.1:端口");
  }
  if (!config.token) throw new Error("请先在插件设置填写服务配对码");
  let path, body;
  if (message.type === "startDownload") {
    path = "/download";
    body = { title: message.payload.title, scholar_url: message.payload.scholarUrl,
             headless: config.headless };
  } else if (message.type === "getTask" && /^[a-f0-9]{32}$/.test(message.taskId)) {
    path = "/tasks/" + message.taskId;
  } else if (message.type === "health") {
    path = "/health";
  } else {
    throw new Error("Unknown message");
  }
  const response = await fetch(url.origin + path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + config.token },
    ...(body ? { body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(15000)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  return { ok: true, data };
}
