var busy = false;
var menuID;

function startup({ id }) {
  menuID = Zotero.MenuManager.registerMenu({
    menuID: "sjtu-import-attachments", pluginID: id, target: "main/menubar/tools",
    menus: [{
      menuType: "menuitem",
      onShowing: (_event, context) => {
        context.menuElem.label = "导入 SJTU PDF 附件…";
        context.setEnabled(!busy);
      },
      onCommand: (_event, context) => {
        const window = context.menuElem.ownerGlobal;
        importManifest(window).catch(error => {
          Zotero.logError(error);
          window.alert("导入失败：" + error.message);
        });
      }
    }]
  });
}
function shutdown() {
  if (menuID) Zotero.MenuManager.unregisterMenu(menuID);
}
function install() {}
function uninstall() {}

function normalizeTitle(value) {
  return String(value || "").normalize("NFKD").replace(/\p{M}/gu, "")
    .toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}
function normalizeDOI(value) {
  return decodeURIComponent(String(value || "").trim().replace(/^(https?:\/\/(dx\.)?doi\.org\/|doi:\s*)/i, "")).toLowerCase();
}

async function findParent(record, libraryID) {
  const uri = String(record.source?.id || "");
  const doi = normalizeDOI(record.doi);
  const title = normalizeTitle(record.title);
  if (!title) throw new Error("标题为空");
  if (/^https?:\/\/(www\.)?zotero\.org\/(users|groups)\//.test(uri)) {
    const parent = await Zotero.URI.getURIItem(uri.replace(/^https:/, "http:"));
    if (!parent || parent.deleted || !parent.isRegularItem() || parent.libraryID !== libraryID) {
      throw new Error("原条目不存在或不在当前选定的文献库");
    }
    const actualDOI = normalizeDOI(parent.getField("DOI"));
    if (doi && actualDOI && doi !== actualDOI) throw new Error("原条目 DOI 冲突");
    if (!(doi && actualDOI === doi) && normalizeTitle(parent.getField("title")) !== title) {
      throw new Error("原条目标题已改变，请重新导出");
    }
    return parent;
  }
  // ponytail: scan the chosen library once per record; add an index for large batches.
  const search = new Zotero.Search();
  search.libraryID = libraryID;
  search.addCondition("deleted", "false");
  if (doi) search.addCondition("DOI", "contains", doi);
  else search.addCondition("title", "contains", record.title);
  const matches = (await Zotero.Items.getAsync(await search.search())).filter(item =>
    item.isRegularItem() && !item.deleted && item.libraryID === libraryID &&
    (doi ? normalizeDOI(item.getField("DOI")) === doi : normalizeTitle(item.getField("title")) === title));
  if (matches.length !== 1) throw new Error("无法唯一匹配原条目（匹配数：" + matches.length + "）");
  return matches[0];
}

async function importRecord(record, folder, libraryID) {
  if (!/^[a-f0-9]{32}\.pdf$/.test(record.pdf || "") || !/^[a-f0-9]{64}$/.test(record.sha256 || "")) {
    throw new Error("附件文件名或校验值无效");
  }
  const parent = await findParent(record, libraryID);
  for (const id of parent.getAttachments()) {
    const attachment = await Zotero.Items.getAsync(id);
    if (attachment.attachmentContentType === "application/pdf" && await attachment.fileExists()) {
      return { status: "skipped", reason: "已有 PDF", itemKey: parent.key };
    }
  }
  const file = folder.clone();
  file.append(record.pdf);
  if (!file.exists() || !file.isFile() || file.isSymlink()) throw new Error("附件不存在或不是普通文件");
  // Stream the hash through XPCOM; no full PDF allocation in the Zotero UI process.
  const input = Cc["@mozilla.org/network/file-input-stream;1"].createInstance(Ci.nsIFileInputStream);
  input.init(file, 0x01, 0, 0);
  const hash = Cc["@mozilla.org/security/hash;1"].createInstance(Ci.nsICryptoHash);
  hash.init(hash.SHA256);
  try { hash.updateFromStream(input, 0xffffffff); } finally { input.close(); }
  const digest = Array.from(hash.finish(false), c => c.charCodeAt(0).toString(16).padStart(2, "0")).join("");
  if (digest !== record.sha256) throw new Error("PDF 校验失败，请重新下载");
  if ((await Zotero.File.getContentsAsync(file, "utf-8", 5)) !== "%PDF-") {
    throw new Error("附件不是 PDF");
  }
  const attachment = await Zotero.Attachments.importFromFile({
    file: file.path, parentItemID: parent.id,
    title: record.metadata?.provider === "SSRN" ? "SSRN Manuscript (版本可能不同)" :
           record.metadata?.provider === "Sci-Hub" ? "Sci-Hub PDF (版本未核验)" : "SJTU Full Text",
    contentType: "application/pdf"
  });
  return { status: "imported", itemKey: parent.key, attachmentKey: attachment.key };
}

async function importManifest(window) {
  if (busy) throw new Error("已有附件导入正在进行");
  busy = true;
  try {
    const { FilePicker } = ChromeUtils.importESModule("chrome://zotero/content/modules/filePicker.mjs");
    const picker = new FilePicker();
    picker.init(window, "选择 sjtu-attachments.json", picker.modeOpen);
    picker.appendFilter("SJTU attachment manifest", "*.json");
    if (await picker.show() !== picker.returnOK) return;
    const manifestFile = Zotero.File.pathToFile(picker.file);
    const manifest = JSON.parse(await Zotero.File.getContentsAsync(manifestFile));
    if (manifest.format !== "sjtu-attachments" || manifest.version !== 1 || !Array.isArray(manifest.items)) {
      throw new Error("不是 SJTU 附件清单");
    }
    const libraryID = window.ZoteroPane.getSelectedLibraryID();
    const library = Zotero.Libraries.get(libraryID);
    if (!library?.editable || !library.filesEditable) throw new Error("当前文献库不允许添加附件");
    const records = manifest.items.filter(record => record?.status === "success");
    if (!window.confirm("将为“" + library.name + "”中的原条目补充 " + records.length +
                        " 个候选 PDF；已有 PDF 或无法唯一匹配的条目会跳过。继续？")) return;
    const results = [];
    for (const record of records) {
      try {
        results.push({ title: record.title, ...await importRecord(record, manifestFile.parent, libraryID) });
      } catch (error) {
        results.push({ title: record.title, status: "error", error: error.message });
      }
      // Persist per item so a later failure does not hide successful imports.
      await Zotero.File.putContentsAsync(manifestFile.path + ".import-report.json", JSON.stringify(results, null, 2));
    }
    const imported = results.filter(r => r.status === "imported").length;
    const errors = results.filter(r => r.status === "error");
    window.alert("已补充 " + imported + " 个 PDF，跳过 " + (results.length - imported - errors.length) +
                 " 个，失败 " + errors.length + " 个。\n报告：" + manifestFile.path + ".import-report.json" +
                 (errors.length ? "\n" + errors.slice(0, 5).map(r => r.title + ": " + r.error).join("\n") : ""));
  } finally { busy = false; }
}
