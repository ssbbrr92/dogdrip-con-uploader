const DEFAULT_MAPPING = {
  mainFileName: "dogcon_main_file",
  extraFilePattern: "dogcon_file_{index}",
  contentSelector: 'textarea[name="content"], input[name="content"]',
  editorSelector: 'form [contenteditable="true"]',
  tagSelector: 'input[name="tags"], input[name="tag"]',
  titleSelector: 'input[name="title"]',
  priceSelector: 'input[name="price"]'
};

function dispatchValue(element, value) {
  const prototype = element instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  if (setter) setter.call(element, value);
  else element.value = value;
  element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function fillField(selector, value) {
  if (!value) return 0;
  const fields = [...document.querySelectorAll(selector)];
  fields.forEach((field) => dispatchValue(field, value));
  return fields.length;
}

function fillContent(html, mapping) {
  if (!html.trim()) return 0;
  let changed = 0;
  document.querySelectorAll(mapping.contentSelector).forEach((field) => {
    dispatchValue(field, html);
    changed += 1;
  });
  document.querySelectorAll("iframe").forEach((frame) => {
    try {
      const body = frame.contentDocument?.body;
      if (body?.isContentEditable || body?.getAttribute("contenteditable") === "true") {
        body.innerHTML = html;
        body.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText" }));
        changed += 1;
      }
    } catch (_) { /* cross-origin editor */ }
  });
  const editor = document.querySelector(mapping.editorSelector);
  if (editor) {
    editor.innerHTML = html;
    editor.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText" }));
    changed += 1;
  }
  return changed;
}

function base64ToFile(dataUrl, filename, type, lastModified) {
  const encoded = dataUrl.includes(",") ? dataUrl.split(",", 2)[1] : dataUrl;
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return new File([bytes], filename, { type: type || "application/octet-stream", lastModified });
}

function setFile(inputName, fileData) {
  const input = document.querySelector(`input[type="file"][name="${CSS.escape(inputName)}"]`);
  if (!input) throw new Error(`파일 입력란을 찾지 못했습니다: ${inputName}`);
  const transfer = new DataTransfer();
  transfer.items.add(base64ToFile(fileData.dataUrl, fileData.name, fileData.type, fileData.lastModified));
  input.files = transfer.files;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  try {
    const mapping = { ...DEFAULT_MAPPING, ...(message.mapping || {}) };
    if (message.type === "PING") {
      sendResponse({ ok: true });
    } else if (message.type === "FILL_FIELDS") {
      const results = {
        title: fillField(mapping.titleSelector, message.title),
        price: fillField(mapping.priceSelector, message.price),
        tags: fillField(mapping.tagSelector, message.tags),
        content: fillContent(message.content || "", mapping)
      };
      sendResponse({ ok: true, results });
    } else if (message.type === "SET_FILE") {
      setFile(message.inputName, message.file);
      sendResponse({ ok: true });
    }
  } catch (error) {
    sendResponse({ ok: false, error: error.message });
  }
  return true;
});
