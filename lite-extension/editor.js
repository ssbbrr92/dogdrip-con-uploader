CKEDITOR.disableAutoInline = true;

const editorSurface = document.getElementById("editor");

function editorIsEmpty() {
  const text = (editorSurface.textContent || "").replace(/\u200b/g, "").trim();
  const media = editorSurface.querySelector("img,hr,table,iframe,video,audio");
  return !text && !media;
}

// On an already-empty inline editor CKEditor removes and recreates its filler
// node on Backspace, which triggers floating-space layout and visibly shifts
// the side panel. There is nothing to delete, so stop that key before CKEditor
// sees it.
document.addEventListener("keydown", (event) => {
  if (!(event.ctrlKey || event.metaKey)) return;
  const key = event.key.toLowerCase();
  if (key === "s") {
    event.preventDefault();
    event.stopImmediatePropagation();
    parent.postMessage({ source: "dogdrip-lite-editor", type: "SAVE_SHORTCUT" }, "*");
  }
  if (key === "l") {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

editorSurface.addEventListener("keydown", (event) => {
  if ((event.key === "Backspace" || event.key === "Delete") && editorIsEmpty()) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

const instance = CKEDITOR.inline("editor", {
  language: "ko",
  // CKEditor 4.22.1 is intentionally pinned for compatibility with DogDrip's
  // editor.  Suppress its upgrade notice so it never covers the editing area.
  versionCheck: false,
  removePlugins: "exportpdf,scayt,wsc,sourcearea,wysiwygarea",
  allowedContent: true,
  autoParagraph: false,
  enterMode: CKEDITOR.ENTER_BR,
  shiftEnterMode: CKEDITOR.ENTER_BR,
  startupFocus: true,
  resize_enabled: false,
  toolbar: []
});

function placeCaretAtEmptyStart(event) {
  if (!editorIsEmpty()) return;
  if (event) event.preventDefault();
  instance.focus();
  const range = instance.createRange();
  range.moveToElementEditStart(instance.editable());
  instance.getSelection().selectRanges([range]);
}

editorSurface.addEventListener("pointerdown", (event) => {
  if (editorIsEmpty()) placeCaretAtEmptyStart(event);
}, true);

// Once docked, CKEditor's floating-space plug-in must no longer recalculate
// toolbar coordinates on an empty-document selection change.
instance.on("floatingSpaceLayout", (event) => event.cancel(), null, null, 0);

let savedBookmarks = null;

function closestTag(element, tags) {
  if (!element) return "";
  for (const tag of tags) {
    if (element.getAscendant(tag, true)) return tag;
  }
  return "";
}

function selectExistingValue(selectId, value) {
  const select = document.getElementById(selectId);
  const exists = Array.from(select.options).some((option) => option.value === value);
  select.value = exists ? value : "";
}

function syncNativeCombos() {
  const selection = instance.getSelection();
  const start = selection && selection.getStartElement();
  if (!start) return;

  selectExistingValue("styleSelect", closestTag(start, ["strong", "code", "mark"]));
  selectExistingValue("formatSelect", closestTag(start, ["h1", "h2", "h3", "pre", "p"]));

  const fontFamily = (start.getComputedStyle("font-family") || "")
    .split(",")[0].trim().replace(/^['\"]|['\"]$/g, "");
  const fontSize = (start.getComputedStyle("font-size") || "").trim();
  selectExistingValue("fontSelect", fontFamily);
  selectExistingValue("sizeSelect", fontSize);

  document.querySelectorAll("[data-command]").forEach((button) => {
    const command = instance.getCommand(button.dataset.command);
    const isActive = Boolean(command && command.state === CKEDITOR.TRISTATE_ON);
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
    button.disabled = Boolean(command && command.state === CKEDITOR.TRISTATE_DISABLED);
  });
}

function rememberEditorSelection() {
  const selection = instance.getSelection();
  if (selection && !selection.isLocked) {
    try {
      savedBookmarks = selection.createBookmarks2(true);
    } catch (_error) {
      savedBookmarks = null;
    }
  }
}

function restoreEditorSelection() {
  instance.focus();
  if (!savedBookmarks) return;
  try {
    instance.getSelection().selectBookmarks(savedBookmarks);
  } catch (_error) {
    // The document may have changed since the selection was captured. In that
    // case CKEditor safely applies the style at the current caret instead.
  }
}

document.getElementById("toolbar").addEventListener("pointerdown", rememberEditorSelection, true);
instance.on("selectionChange", () => {
  rememberEditorSelection();
  syncNativeCombos();
});

function applyElementStyle(element, styles = {}) {
  restoreEditorSelection();
  instance.applyStyle(new CKEDITOR.style({ element, styles }));
  rememberEditorSelection();
  syncNativeCombos();
  instance.fire("change");
}

document.getElementById("styleSelect").addEventListener("change", (event) => {
  if (event.target.value) applyElementStyle(event.target.value);
});

document.getElementById("formatSelect").addEventListener("change", (event) => {
  if (event.target.value) applyElementStyle(event.target.value);
});

document.getElementById("fontSelect").addEventListener("change", (event) => {
  if (event.target.value) applyElementStyle("span", { "font-family": event.target.value });
});

document.getElementById("sizeSelect").addEventListener("change", (event) => {
  if (event.target.value) applyElementStyle("span", { "font-size": event.target.value });
});

function runEditorCommand(commandName) {
  restoreEditorSelection();
  instance.execCommand(commandName);
  rememberEditorSelection();
  syncNativeCombos();
  instance.fire("change");
}

document.querySelectorAll("[data-command]").forEach((button) => {
  button.setAttribute("aria-pressed", "false");
  button.addEventListener("click", () => runEditorCommand(button.dataset.command));
});

document.getElementById("textColor").addEventListener("input", (event) => {
  applyElementStyle("span", { color: event.target.value });
});

document.getElementById("backgroundColor").addEventListener("input", (event) => {
  applyElementStyle("span", { "background-color": event.target.value });
});

const editorDialog = document.getElementById("editorDialog");
const editorDialogForm = document.getElementById("editorDialogForm");
const editorDialogFields = document.getElementById("editorDialogFields");
let dialogSubmit = null;

function escapeHtml(value) {
  const holder = document.createElement("div");
  holder.textContent = String(value || "");
  return holder.innerHTML;
}

function showEditorDialog(title, fields, onSubmit) {
  document.getElementById("editorDialogTitle").textContent = title;
  editorDialogFields.replaceChildren();
  for (const field of fields) {
    const row = document.createElement("div");
    row.className = "dialog-field";
    if (["text", "url", "alt", "character"].includes(field.name)) {
      row.classList.add("dialog-field-full");
    }
    const label = document.createElement("label");
    label.textContent = field.label;
    const input = document.createElement("input");
    input.name = field.name;
    input.type = field.type || "text";
    input.value = field.value || "";
    input.required = Boolean(field.required);
    if (field.min) input.min = field.min;
    row.append(label, input);
    editorDialogFields.append(row);
  }
  dialogSubmit = onSubmit;
  editorDialog.hidden = false;
  editorDialogFields.querySelector("input")?.focus();
}

function closeEditorDialog() {
  editorDialog.hidden = true;
  dialogSubmit = null;
  restoreEditorSelection();
}

document.getElementById("editorDialogCancel").addEventListener("click", closeEditorDialog);
editorDialog.addEventListener("pointerdown", (event) => {
  if (event.target === editorDialog) closeEditorDialog();
});
editorDialogForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(editorDialogForm).entries());
  const submit = dialogSubmit;
  editorDialog.hidden = true;
  dialogSubmit = null;
  restoreEditorSelection();
  submit?.(values);
  rememberEditorSelection();
  instance.fire("change");
});

function insertHtml(html) {
  restoreEditorSelection();
  instance.insertHtml(html);
}

document.querySelector('[data-action="link"]').addEventListener("click", () => {
  const selectedText = instance.getSelection()?.getSelectedText() || "";
  showEditorDialog("링크 삽입", [
    { name: "text", label: "표시 텍스트", value: selectedText, required: true },
    { name: "url", label: "링크 URL", value: "https://", required: true }
  ], ({ text, url }) => insertHtml(`<a href="${escapeHtml(url)}">${escapeHtml(text)}</a>`));
});

document.querySelector('[data-action="image"]').addEventListener("click", () => {
  showEditorDialog("이미지 삽입", [
    { name: "url", label: "이미지 URL", value: "https://", required: true },
    { name: "alt", label: "설명 텍스트" },
    { name: "width", label: "가로 (선택)", type: "number", min: "1" },
    { name: "height", label: "세로 (선택)", type: "number", min: "1" }
  ], ({ url, alt, width, height }) => {
    const dimensions = `${width ? ` width="${Number(width)}"` : ""}${height ? ` height="${Number(height)}"` : ""}`;
    insertHtml(`<img src="${escapeHtml(url)}" alt="${escapeHtml(alt)}"${dimensions}>`);
  });
});

document.querySelector('[data-action="table"]').addEventListener("click", () => {
  showEditorDialog("표 삽입", [
    { name: "rows", label: "행", type: "number", value: "2", min: "1", required: true },
    { name: "columns", label: "열", type: "number", value: "2", min: "1", required: true }
  ], ({ rows, columns }) => {
    const rowCount = Math.min(20, Math.max(1, Number(rows) || 1));
    const columnCount = Math.min(10, Math.max(1, Number(columns) || 1));
    const row = `<tr>${"<td>&nbsp;</td>".repeat(columnCount)}</tr>`;
    insertHtml(`<table border="1"><tbody>${row.repeat(rowCount)}</tbody></table>`);
  });
});

document.querySelector('[data-action="specialchar"]').addEventListener("click", () => {
  showEditorDialog("특수 문자 삽입", [
    { name: "character", label: "삽입할 문자", value: "★", required: true }
  ], ({ character }) => insertHtml(escapeHtml(character)));
});

function notify(type, extra = {}) {
  parent.postMessage({ source: "dogdrip-lite-editor", type, ...extra }, "*");
}

instance.on("instanceReady", () => {
  document.querySelectorAll(".cke_float").forEach((floatingSpace) => {
    floatingSpace.setAttribute("aria-hidden", "true");
    floatingSpace.style.pointerEvents = "none";
  });
  document.querySelectorAll("[data-command]").forEach((button) => {
    instance.getCommand(button.dataset.command)?.on("state", syncNativeCombos);
  });
  syncNativeCombos();
  notify("EDITOR_READY", { version: CKEDITOR.version });
});
instance.on("change", () => notify("EDITOR_CHANGED", { html: instance.getData() }));
instance.on("blur", () => notify("EDITOR_CHANGED", { html: instance.getData() }));

window.addEventListener("message", (event) => {
  const message = event.data;
  if (!message || message.source !== "dogdrip-lite-panel") return;
  if (message.type === "EDITOR_SET_DATA") {
    const incomingHtml = (message.html || "").trim();
    instance.setData(incomingHtml, () => {
      if (!incomingHtml) placeCaretAtEmptyStart();
      notify("EDITOR_CHANGED", { html: instance.getData() });
    });
  } else if (message.type === "EDITOR_GET_DATA") {
    notify("EDITOR_DATA", { requestId: message.requestId, html: instance.getData() });
  }
});
