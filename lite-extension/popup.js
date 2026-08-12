const DEFAULT_URL = "https://www.dogdrip.net/index.php?mid=dogcon&act=dispDogconWrite";
const ALLOWED_EXTENSIONS = /\.(png|jpe?g|gif|webp)$/i;
const MAX_FILES = 50;
const DEFAULT_MAPPING = {
  targetHost: "dogdrip.net",
  mainFileName: "dogcon_main_file",
  extraFilePattern: "dogcon_file_{index}",
  contentSelector: 'textarea[name="content"], input[name="content"]',
  editorSelector: 'form [contenteditable="true"]',
  tagSelector: 'input[name="tags"], input[name="tag"]',
  titleSelector: 'input[name="title"]',
  priceSelector: 'input[name="price"]'
};
const MAPPING_LABELS = {
  targetHost: "대상 도메인",
  mainFileName: "메인 이미지 input name",
  extraFilePattern: "추가 이미지 패턴",
  contentSelector: "본문 input CSS 선택자",
  editorSelector: "본문 에디터 CSS 선택자",
  tagSelector: "태그 input CSS 선택자",
  titleSelector: "제목 input CSS 선택자",
  priceSelector: "판매 포인트 CSS 선택자"
};

const elements = Object.fromEntries([
  "folderInput", "folderSummary", "sortMode", "filePreview", "title", "price",
  "contentFrame", "tags", "openPage", "fillPage", "status", "log",
  "mappingSettings", "mappingDialog", "mappingForm", "mappingFields",
  "mappingDefaults", "mappingCancel", "registrationUrl", "defaultRegistrationUrl",
  "profileTabs", "saveProfile", "exportProfiles", "importProfiles", "addProfileTab",
  "deleteTabDialog", "deleteTabName", "cancelDeleteTab", "confirmDeleteTab",
  "tabScrollbar", "tabScrollThumb", "postInfoToggle", "postInfoContent",
  "postInfoScrollShell", "postInfoScrollbar", "postInfoScrollThumb",
  "skipDeleteConfirmSession"
].map((id) => [id, document.getElementById(id)]));

let selectedFiles = [];
let contentHtml = "";
let editorReady = false;
let formLoaded = false;
let mapping = { ...DEFAULT_MAPPING };
let profiles = {};
let profileDrafts = {};
const dirtyProfiles = new Set();
let activeProfileName = "";
let pendingDeleteProfileName = "";
let skipDeleteConfirmationForSession = false;
let draggedProfileName = "";
let ignoreTabClickUntil = 0;
let editorRequestCounter = 0;
const editorRequests = new Map();
let fitFrame = 0;

function fitInterfaceToViewport() {
  cancelAnimationFrame(fitFrame);
  fitFrame = requestAnimationFrame(() => {
    // Fractional CSS zoom made text and 1 px borders blurry on common
    // 1920x1080 displays. Keep the panel at native 100% CSS pixels and let
    // the document scroll vertically when its natural height exceeds the view.
    document.body.style.removeProperty("zoom");
    document.documentElement.style.overflowY = "hidden";
  });
}

window.addEventListener("resize", fitInterfaceToViewport);

function getContentHtml() {
  return contentHtml;
}

function postToEditor(message) {
  elements.contentFrame.contentWindow?.postMessage({ source: "dogdrip-lite-panel", ...message }, "*");
}

function syncEditorData() {
  if (editorReady && formLoaded) postToEditor({ type: "EDITOR_SET_DATA", html: contentHtml });
}

function requestEditorHtml() {
  if (!editorReady) return Promise.resolve(contentHtml);
  const requestId = ++editorRequestCounter;
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      editorRequests.delete(requestId);
      resolve(contentHtml);
    }, 1500);
    editorRequests.set(requestId, (html) => {
      clearTimeout(timeout);
      resolve(html);
    });
    postToEditor({ type: "EDITOR_GET_DATA", requestId });
  });
}

window.addEventListener("message", (event) => {
  if (event.source !== elements.contentFrame.contentWindow) return;
  const message = event.data;
  if (!message || message.source !== "dogdrip-lite-editor") return;
  if (message.type === "EDITOR_READY") {
    editorReady = true;
    syncEditorData();
  } else if (message.type === "EDITOR_CHANGED") {
    contentHtml = message.html || "";
    saveForm();
  } else if (message.type === "EDITOR_DATA") {
    contentHtml = message.html || "";
    const resolve = editorRequests.get(message.requestId);
    if (resolve) {
      editorRequests.delete(message.requestId);
      resolve(contentHtml);
    }
  } else if (message.type === "SAVE_SHORTCUT") {
    saveCurrentProfile();
  }
});

function naturalCompare(left, right) {
  return left.localeCompare(right, "ko", { numeric: true, sensitivity: "base" });
}

function sortedFiles() {
  const files = [...selectedFiles];
  const mode = elements.sortMode.value;
  if (mode === "name") files.sort((a, b) => naturalCompare(a.name, b.name));
  if (mode === "name_desc") files.sort((a, b) => naturalCompare(b.name, a.name));
  if (mode === "mtime") files.sort((a, b) => a.lastModified - b.lastModified || naturalCompare(a.name, b.name));
  if (mode === "mtime_desc") files.sort((a, b) => b.lastModified - a.lastModified || naturalCompare(a.name, b.name));
  return files.slice(0, MAX_FILES);
}

function renderFiles() {
  const files = sortedFiles();
  elements.filePreview.replaceChildren(...files.map((file) => {
    const item = document.createElement("li");
    item.textContent = file.name;
    return item;
  }));
  if (!selectedFiles.length) elements.folderSummary.textContent = "폴더를 선택해 주세요.";
  else {
    const ignored = Math.max(0, selectedFiles.length - files.length);
    elements.folderSummary.textContent = `${files.length}개 이미지가 배치됩니다.${ignored ? ` (${ignored}개 제외)` : ""}`;
  }
}

function log(message) {
  const time = new Date().toLocaleTimeString("ko-KR", { hour12: false });
  elements.log.textContent += `[${time}] ${message}\n`;
  elements.log.scrollTop = elements.log.scrollHeight;
}

function setStatus(message, error = false) {
  elements.status.textContent = message;
  elements.status.style.background = error ? "#fff0f0" : "#eaf1fc";
  elements.status.style.color = error ? "#a43a3a" : "#294f80";
}

function send(tabId, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else if (!response?.ok) reject(new Error(response?.error || "페이지에서 처리하지 못했습니다."));
      else resolve(response);
    });
  });
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("파일을 읽지 못했습니다."));
    reader.readAsDataURL(file);
  });
}

async function findTargetTab() {
  const tabs = await chrome.tabs.query({ url: ["https://*.dogdrip.net/*"] });
  const hostMatches = (tab) => {
    try {
      const hostname = new URL(tab.url || "").hostname;
      return hostname === mapping.targetHost || hostname.endsWith(`.${mapping.targetHost}`);
    } catch (_error) {
      return false;
    }
  };
  const matchingTabs = tabs.filter(hostMatches);
  const target = matchingTabs.find((tab) => /[?&]mid=dogcon(?:&|$)/.test(tab.url || ""))
    || matchingTabs.find((tab) => (tab.url || "").includes("dogcon"));
  if (!target?.id) throw new Error("개드립콘 등록 페이지를 먼저 열어 주세요.");
  await send(target.id, { type: "PING" });
  return target;
}

function currentInputSnapshot() {
  return {
    sortMode: elements.sortMode.value,
    title: elements.title.value,
    price: elements.price.value,
    content: getContentHtml(),
    tags: elements.tags.value,
    registrationUrl: elements.registrationUrl.value.trim() || DEFAULT_URL
  };
}

function comparableProfile(profile = {}) {
  return JSON.stringify({
    registrationUrl: profile.registrationUrl || DEFAULT_URL,
    sortMode: profile.sortMode || "name",
    title: profile.title || "",
    price: profile.price || "",
    content: profile.content || "",
    tags: profile.tags || ""
  });
}

function updateDirtyState(name, draft) {
  if (!name || !profiles[name]) return;
  if (comparableProfile(draft) === comparableProfile(profiles[name])) dirtyProfiles.delete(name);
  else dirtyProfiles.add(name);
  const tab = elements.profileTabs.querySelector(`.profile-tab[data-name="${CSS.escape(name)}"]`);
  if (tab) {
    tab.classList.toggle("is-dirty", dirtyProfiles.has(name));
    const title = tab.querySelector(".profile-tab-name");
    if (title) title.title = dirtyProfiles.has(name) ? "저장되지 않은 변경사항이 있습니다" : (name === activeProfileName ? "클릭하여 탭 이름 변경" : `${name} 열기`);
  }
}

function saveForm() {
  if (!formLoaded || !activeProfileName) return;
  profileDrafts[activeProfileName] = currentInputSnapshot();
  updateDirtyState(activeProfileName, profileDrafts[activeProfileName]);
}

function blankProfile() {
  return { registrationUrl: DEFAULT_URL, sortMode: "name", title: "", price: "", content: "", tags: "" };
}

function uniqueProfileName(base = "작업") {
  let index = 1;
  let name = `${base} ${index}`;
  while (profiles[name]) name = `${base} ${++index}`;
  return name;
}

function renderProfileTabs() {
  const tabs = Object.keys(profiles).map((name) => {
    const tab = document.createElement("div");
    tab.className = `profile-tab${name === activeProfileName ? " active" : ""}${dirtyProfiles.has(name) ? " is-dirty" : ""}`;
    tab.draggable = true;
    tab.dataset.name = name;
    const title = document.createElement("button");
    title.type = "button";
    title.className = "profile-tab-name";
    title.textContent = name;
    title.title = dirtyProfiles.has(name) ? "저장되지 않은 변경사항이 있습니다" : (name === activeProfileName ? "클릭하여 탭 이름 변경" : `${name} 열기`);
    title.addEventListener("click", () => {
      if (Date.now() < ignoreTabClickUntil) return;
      name === activeProfileName ? startTabRename(tab, name) : activateProfile(name);
    });
    const close = document.createElement("button");
    close.type = "button";
    close.className = "profile-tab-close";
    close.title = `${name} 삭제`;
    close.setAttribute("aria-label", `${name} 삭제`);
    const closeIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    closeIcon.setAttribute("viewBox", "0 0 24 24");
    closeIcon.setAttribute("aria-hidden", "true");
    const closeLineA = document.createElementNS("http://www.w3.org/2000/svg", "path");
    closeLineA.setAttribute("d", "M18 6 6 18");
    const closeLineB = document.createElementNS("http://www.w3.org/2000/svg", "path");
    closeLineB.setAttribute("d", "m6 6 12 12");
    closeIcon.append(closeLineA, closeLineB);
    close.append(closeIcon);
    close.addEventListener("click", (event) => { event.stopPropagation(); requestDeleteProfile(name); });
    tab.addEventListener("dragstart", (event) => {
      draggedProfileName = name;
      ignoreTabClickUntil = Date.now() + 500;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", name);
      requestAnimationFrame(() => tab.classList.add("dragging"));
    });
    tab.addEventListener("dragover", (event) => {
      if (!draggedProfileName || draggedProfileName === name) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      const rect = tab.getBoundingClientRect();
      tab.classList.toggle("drop-after", event.clientX >= rect.left + rect.width / 2);
      tab.classList.toggle("drop-before", event.clientX < rect.left + rect.width / 2);
    });
    tab.addEventListener("dragleave", () => tab.classList.remove("drop-before", "drop-after"));
    tab.addEventListener("drop", async (event) => {
      event.preventDefault();
      const rect = tab.getBoundingClientRect();
      await reorderProfileTabs(draggedProfileName || event.dataTransfer.getData("text/plain"), name, event.clientX >= rect.left + rect.width / 2);
    });
    tab.addEventListener("dragend", () => {
      draggedProfileName = "";
      ignoreTabClickUntil = Date.now() + 200;
      elements.profileTabs.querySelectorAll(".profile-tab").forEach((item) => item.classList.remove("dragging", "drop-before", "drop-after"));
    });
    tab.append(title, close);
    return tab;
  });
  elements.profileTabs.replaceChildren(...tabs);
  requestAnimationFrame(() => {
    elements.profileTabs.querySelector(".profile-tab.active")?.scrollIntoView({ block: "nearest", inline: "nearest" });
    updateTabScrollbar();
  });
}

function updateTabScrollbar() {
  const { clientWidth, scrollWidth, scrollLeft } = elements.profileTabs;
  const trackWidth = elements.tabScrollbar.clientWidth;
  const overflow = scrollWidth - clientWidth;
  elements.tabScrollbar.classList.toggle("is-hidden", overflow <= 1 || trackWidth <= 0);
  if (overflow <= 1 || trackWidth <= 0) return;
  const thumbWidth = Math.max(28, Math.round(trackWidth * clientWidth / scrollWidth));
  const thumbLeft = Math.round((trackWidth - thumbWidth) * scrollLeft / overflow);
  elements.tabScrollThumb.style.width = `${thumbWidth}px`;
  elements.tabScrollThumb.style.transform = `translateX(${thumbLeft}px)`;
}

function updatePostInfoScrollbar() {
  const { clientHeight, scrollHeight, scrollTop } = elements.postInfoContent;
  const trackHeight = elements.postInfoScrollbar.clientHeight;
  const overflow = scrollHeight - clientHeight;
  if (trackHeight <= 0 || elements.postInfoScrollShell.hidden) return;
  if (overflow <= 1) {
    elements.postInfoScrollThumb.style.height = `${trackHeight}px`;
    elements.postInfoScrollThumb.style.transform = "translateY(0)";
    elements.postInfoScrollThumb.classList.add("is-static");
    return;
  }
  elements.postInfoScrollThumb.classList.remove("is-static");
  const thumbHeight = Math.max(32, Math.round(trackHeight * clientHeight / scrollHeight));
  const thumbTop = Math.round((trackHeight - thumbHeight) * scrollTop / overflow);
  elements.postInfoScrollThumb.style.height = `${thumbHeight}px`;
  elements.postInfoScrollThumb.style.transform = `translateY(${thumbTop}px)`;
}

async function reorderProfileTabs(sourceName, targetName, placeAfter) {
  if (!sourceName || sourceName === targetName || !profiles[sourceName] || !profiles[targetName]) return;
  const names = Object.keys(profiles).filter((name) => name !== sourceName);
  let targetIndex = names.indexOf(targetName);
  if (placeAfter) targetIndex += 1;
  names.splice(targetIndex, 0, sourceName);
  profiles = Object.fromEntries(names.map((name) => [name, profiles[name]]));
  await saveProfilesStorage();
  renderProfileTabs();
  setStatus(`'${sourceName}' 탭의 위치를 변경했습니다.`);
}

function startTabRename(tab, oldName) {
  if (tab.querySelector("input")) return;
  const input = document.createElement("input");
  input.className = "profile-tab-rename";
  input.value = oldName;
  input.maxLength = 60;
  tab.querySelector(".profile-tab-name").replaceWith(input);
  input.focus();
  input.select();
  let finished = false;
  const finish = async (commit) => {
    if (finished) return;
    finished = true;
    const newName = input.value.trim();
    if (!commit || !newName || newName === oldName) return renderProfileTabs();
    if (profiles[newName]) {
      setStatus("같은 이름의 탭이 이미 있습니다.", true);
      return renderProfileTabs();
    }
    profiles[newName] = profiles[oldName];
    delete profiles[oldName];
    if (profileDrafts[oldName]) {
      profileDrafts[newName] = profileDrafts[oldName];
      delete profileDrafts[oldName];
    }
    if (dirtyProfiles.delete(oldName)) dirtyProfiles.add(newName);
    activeProfileName = newName;
    await saveProfilesStorage();
    renderProfileTabs();
    setStatus(`탭 이름을 '${newName}'(으)로 변경했습니다.`);
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); finish(true); }
    if (event.key === "Escape") { event.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}

async function captureCurrentInput() {
  contentHtml = await requestEditorHtml();
  return {
    registrationUrl: elements.registrationUrl.value.trim() || DEFAULT_URL,
    sortMode: elements.sortMode.value,
    title: elements.title.value,
    price: elements.price.value,
    content: contentHtml,
    tags: elements.tags.value,
    savedAt: new Date().toISOString()
  };
}

async function saveProfilesStorage() {
  await chrome.storage.local.set({ liteProfiles: profiles, liteActiveProfile: activeProfileName });
}

async function saveCurrentProfile() {
  if (!activeProfileName || !profiles[activeProfileName]) activeProfileName = uniqueProfileName();
  profiles[activeProfileName] = await captureCurrentInput();
  delete profileDrafts[activeProfileName];
  dirtyProfiles.delete(activeProfileName);
  await saveProfilesStorage();
  renderProfileTabs();
  setStatus(`'${activeProfileName}' 탭을 저장했습니다.`);
  log(`입력내용 탭 저장: ${activeProfileName}`);
}

function applyProfile(profile) {
  elements.registrationUrl.value = profile.registrationUrl || DEFAULT_URL;
  elements.sortMode.value = profile.sortMode || "name";
  elements.title.value = profile.title || "";
  elements.price.value = profile.price || "";
  elements.tags.value = profile.tags || "";
  contentHtml = profile.content || "";
  postToEditor({ type: "EDITOR_SET_DATA", html: contentHtml });
  renderFiles();
  fitInterfaceToViewport();
}

async function activateProfile(name) {
  if (!profiles[name] || name === activeProfileName) return;
  if (activeProfileName && profiles[activeProfileName]) {
    profileDrafts[activeProfileName] = await captureCurrentInput();
    updateDirtyState(activeProfileName, profileDrafts[activeProfileName]);
  }
  activeProfileName = name;
  applyProfile(profileDrafts[name] || profiles[name]);
  await chrome.storage.local.set({ liteActiveProfile: activeProfileName });
  renderProfileTabs();
}

async function addProfileTab() {
  if (activeProfileName && profiles[activeProfileName]) {
    profileDrafts[activeProfileName] = await captureCurrentInput();
    updateDirtyState(activeProfileName, profileDrafts[activeProfileName]);
  }
  activeProfileName = uniqueProfileName();
  profiles[activeProfileName] = blankProfile();
  await saveProfilesStorage();
  applyProfile(profiles[activeProfileName]);
  renderProfileTabs();
  const tab = elements.profileTabs.querySelector(".profile-tab.active");
  if (tab) startTabRename(tab, activeProfileName);
}

function requestDeleteProfile(name) {
  pendingDeleteProfileName = name;
  if (skipDeleteConfirmationForSession) {
    confirmDeleteProfile();
    return;
  }
  elements.deleteTabName.textContent = `'${name}'`;
  elements.skipDeleteConfirmSession.checked = false;
  elements.deleteTabDialog.hidden = false;
  elements.confirmDeleteTab.focus();
}

function closeDeleteDialog() {
  pendingDeleteProfileName = "";
  elements.deleteTabDialog.hidden = true;
}

async function confirmDeleteProfile() {
  const name = pendingDeleteProfileName;
  if (!name || !profiles[name]) return closeDeleteDialog();
  if (!elements.deleteTabDialog.hidden && elements.skipDeleteConfirmSession.checked) {
    skipDeleteConfirmationForSession = true;
  }
  const names = Object.keys(profiles);
  const deletedIndex = names.indexOf(name);
  delete profiles[name];
  delete profileDrafts[name];
  dirtyProfiles.delete(name);
  if (!Object.keys(profiles).length) {
    activeProfileName = uniqueProfileName();
    profiles[activeProfileName] = blankProfile();
  } else if (name === activeProfileName) {
    const remaining = Object.keys(profiles);
    activeProfileName = remaining[Math.min(deletedIndex, remaining.length - 1)];
  }
  await saveProfilesStorage();
  applyProfile(profileDrafts[activeProfileName] || profiles[activeProfileName]);
  renderProfileTabs();
  closeDeleteDialog();
  setStatus(`'${name}' 탭을 삭제했습니다.`);
  log(`입력내용 탭 삭제: ${name}`);
}

async function exportProfilesToJson() {
  const current = await captureCurrentInput();
  const exportedProfiles = activeProfileName ? { ...profiles, [activeProfileName]: current } : profiles;
  const payload = JSON.stringify({
    format: "dogdrip-con-uploader-lite-profiles",
    version: 1,
    exportedAt: new Date().toISOString(),
    profiles: exportedProfiles,
    current,
    activeProfile: activeProfileName
  }, null, 2);
  const url = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
  chrome.downloads.download({
    url,
    filename: "dogdrip-con-uploader-lite-profiles.json",
    saveAs: true
  }, () => {
    const error = chrome.runtime.lastError;
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    if (error) setStatus(error.message, true);
    else setStatus("프로파일 JSON 저장 위치를 선택했습니다.");
  });
}

async function importProfilesFromJson(file) {
  const parsed = JSON.parse(await file.text());
  if (parsed?.format !== "dogdrip-con-uploader-lite-profiles" || typeof parsed.profiles !== "object") {
    throw new Error("DogDrip.Con Uploader Lite 프로파일 파일이 아닙니다.");
  }
  profiles = { ...profiles, ...parsed.profiles };
  const importedNames = Object.keys(parsed.profiles);
  importedNames.forEach((name) => {
    delete profileDrafts[name];
    dirtyProfiles.delete(name);
  });
  if (parsed.current) {
    activeProfileName = parsed.activeProfile && profiles[parsed.activeProfile]
      ? parsed.activeProfile
      : uniqueProfileName("가져온 작업");
    profiles[activeProfileName] = parsed.current;
  } else if (importedNames.length) activeProfileName = importedNames[0];
  await saveProfilesStorage();
  renderProfileTabs();
  if (profiles[activeProfileName]) applyProfile(profiles[activeProfileName]);
  setStatus(`${Object.keys(parsed.profiles).length}개 프로파일을 가져왔습니다.`);
  log(`프로파일 JSON 가져오기: ${file.name}`);
}

async function saveMapping() {
  await chrome.storage.local.set({ liteMapping: mapping });
}

function renderMappingFields(values = mapping) {
  elements.mappingFields.replaceChildren(...Object.entries(MAPPING_LABELS).flatMap(([key, labelText]) => {
    const label = document.createElement("label");
    label.htmlFor = `mapping-${key}`;
    label.textContent = labelText;
    const input = document.createElement("input");
    input.id = `mapping-${key}`;
    input.name = key;
    input.value = values[key] || DEFAULT_MAPPING[key];
    input.required = true;
    return [label, input];
  }));
}

function openMappingDialog() {
  renderMappingFields();
  elements.mappingDialog.hidden = false;
  elements.mappingFields.querySelector("input")?.focus();
}

function closeMappingDialog() {
  elements.mappingDialog.hidden = true;
  fitInterfaceToViewport();
}

async function loadForm() {
  const { liteForm = {}, liteMapping = {}, liteProfiles = {}, liteActiveProfile = "" } = await chrome.storage.local.get(["liteForm", "liteMapping", "liteProfiles", "liteActiveProfile"]);
  mapping = { ...DEFAULT_MAPPING, ...liteMapping };
  profiles = liteProfiles && typeof liteProfiles === "object" ? liteProfiles : {};
  activeProfileName = liteActiveProfile && profiles[liteActiveProfile] ? liteActiveProfile : Object.keys(profiles)[0] || "";
  if (!activeProfileName) {
    activeProfileName = uniqueProfileName();
    profiles[activeProfileName] = {
      ...blankProfile(),
      ...(liteForm && typeof liteForm === "object" ? liteForm : {})
    };
    await saveProfilesStorage();
  }
  applyProfile(profiles[activeProfileName]);
  await chrome.storage.local.remove("liteForm");
  renderProfileTabs();
}

elements.folderInput.addEventListener("change", () => {
  selectedFiles = [...elements.folderInput.files].filter((file) => ALLOWED_EXTENSIONS.test(file.name));
  renderFiles();
  fitInterfaceToViewport();
});
elements.profileTabs.addEventListener("scroll", updateTabScrollbar, { passive: true });
elements.postInfoToggle.addEventListener("click", () => {
  const expanded = elements.postInfoToggle.getAttribute("aria-expanded") === "true";
  elements.postInfoToggle.setAttribute("aria-expanded", String(!expanded));
  elements.postInfoScrollShell.hidden = expanded;
  requestAnimationFrame(updatePostInfoScrollbar);
  fitInterfaceToViewport();
});
elements.postInfoContent.addEventListener("scroll", updatePostInfoScrollbar, { passive: true });
elements.postInfoScrollShell.addEventListener("pointerenter", () => {
  elements.postInfoScrollShell.classList.add("is-scroll-hover");
  updatePostInfoScrollbar();
});
elements.postInfoScrollShell.addEventListener("pointerleave", () => {
  elements.postInfoScrollShell.classList.remove("is-scroll-hover");
});
new ResizeObserver(updatePostInfoScrollbar).observe(elements.postInfoScrollShell);
elements.profileTabs.addEventListener("wheel", (event) => {
  if (elements.profileTabs.scrollWidth <= elements.profileTabs.clientWidth) return;
  const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
  if (!delta) return;
  event.preventDefault();
  elements.profileTabs.scrollLeft += delta;
  updateTabScrollbar();
}, { passive: false });
window.addEventListener("resize", updateTabScrollbar);
window.addEventListener("resize", updatePostInfoScrollbar);
elements.sortMode.addEventListener("change", () => { renderFiles(); saveForm(); });
[elements.title, elements.price, elements.tags, elements.registrationUrl].forEach((field) => field.addEventListener("input", saveForm));

elements.defaultRegistrationUrl.addEventListener("click", () => {
  elements.registrationUrl.value = DEFAULT_URL;
  saveForm();
});
elements.saveProfile.addEventListener("click", saveCurrentProfile);
elements.addProfileTab.addEventListener("click", addProfileTab);
elements.cancelDeleteTab.addEventListener("click", closeDeleteDialog);
elements.confirmDeleteTab.addEventListener("click", confirmDeleteProfile);
elements.deleteTabDialog.addEventListener("pointerdown", (event) => {
  if (event.target === elements.deleteTabDialog) closeDeleteDialog();
});
elements.exportProfiles.addEventListener("click", exportProfilesToJson);
elements.importProfiles.addEventListener("change", async () => {
  const [file] = elements.importProfiles.files;
  if (!file) return;
  try { await importProfilesFromJson(file); }
  catch (error) { setStatus(error.message, true); }
  finally { elements.importProfiles.value = ""; }
});
window.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveCurrentProfile();
  }
});

elements.mappingSettings.addEventListener("click", openMappingDialog);
elements.mappingCancel.addEventListener("click", closeMappingDialog);
elements.mappingDefaults.addEventListener("click", () => renderMappingFields(DEFAULT_MAPPING));
elements.mappingDialog.addEventListener("pointerdown", (event) => {
  if (event.target === elements.mappingDialog) closeMappingDialog();
});
elements.mappingForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const updated = Object.fromEntries(new FormData(elements.mappingForm).entries());
  if (!updated.extraFilePattern.includes("{index}")) {
    setStatus("추가 이미지 패턴에는 {index}가 필요합니다.", true);
    return;
  }
  for (const key of ["contentSelector", "editorSelector", "tagSelector", "titleSelector", "priceSelector"]) {
    try { document.querySelector(updated[key]); }
    catch (_error) {
      setStatus(`${MAPPING_LABELS[key]} 값이 올바른 CSS 선택자가 아닙니다.`, true);
      return;
    }
  }
  updated.targetHost = updated.targetHost.replace(/^https?:\/\//i, "").replace(/\/$/, "");
  mapping = { ...DEFAULT_MAPPING, ...updated };
  await saveMapping();
  setStatus("매핑 설정을 저장했습니다.");
  log("페이지 매핑 설정 저장 완료");
  closeMappingDialog();
});

elements.openPage.addEventListener("click", () => {
  const url = elements.registrationUrl.value.trim() || DEFAULT_URL;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" || !(parsed.hostname === "dogdrip.net" || parsed.hostname.endsWith(".dogdrip.net"))) {
      throw new Error();
    }
    chrome.tabs.create({ url: parsed.href });
  } catch (_error) {
    setStatus("등록 페이지 주소는 dogdrip.net의 HTTPS 주소로 입력해 주세요.", true);
  }
});
elements.fillPage.addEventListener("click", async () => {
  const files = sortedFiles();
  if (!files.length) {
    setStatus("이미지 폴더를 먼저 선택해 주세요.", true);
    return;
  }
  if (elements.price.value && (!/^\d+$/.test(elements.price.value) || Number(elements.price.value) < 0)) {
    setStatus("판매 포인트는 0 이상의 숫자로 입력해 주세요.", true);
    return;
  }
  elements.fillPage.disabled = true;
  try {
    contentHtml = await requestEditorHtml();
    const tab = await findTargetTab();
    setStatus("게시글 정보를 입력하는 중입니다…");
    await send(tab.id, {
      type: "FILL_FIELDS",
      title: elements.title.value.trim(),
      price: elements.price.value.trim(),
      content: getContentHtml(),
      tags: elements.tags.value.trim(),
      mapping
    });
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      setStatus(`이미지 배치 중… ${index + 1}/${files.length}`);
      await send(tab.id, {
        type: "SET_FILE",
        inputName: index === 0
          ? mapping.mainFileName
          : mapping.extraFilePattern.replace("{index}", String(index)),
        mapping,
        file: {
          name: file.name,
          type: file.type,
          lastModified: file.lastModified,
          dataUrl: await fileToDataUrl(file)
        }
      });
    }
    await saveForm();
    setStatus(`${files.length}개 이미지와 내용을 배치했습니다.`);
    log(`${files.length}개 파일 배치 완료 — 브라우저에서 내용을 확인해 주세요.`);
    await chrome.tabs.update(tab.id, { active: true });
    if (tab.windowId) await chrome.windows.update(tab.windowId, { focused: true });
  } catch (error) {
    setStatus(error.message, true);
    log(`오류: ${error.message}`);
  } finally {
    elements.fillPage.disabled = false;
  }
});

loadForm()
  .then(() => {
    formLoaded = true;
    syncEditorData();
    renderFiles();
    fitInterfaceToViewport();
    requestAnimationFrame(updatePostInfoScrollbar);
  })
  .catch((error) => {
    setStatus(error.message, true);
    log(`오류: ${error.message}`);
  });

elements.contentFrame.addEventListener("load", () => {
  fitInterfaceToViewport();
  requestAnimationFrame(updatePostInfoScrollbar);
});
document.querySelector("details")?.addEventListener("toggle", fitInterfaceToViewport);
