import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "lite-extension"


class LiteExtensionTests(unittest.TestCase):
    def test_manifest_is_standalone_v1(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(manifest["version"], "1.0.1")
        self.assertEqual(manifest["name"], "DogDrip.Con Uploader Lite")
        self.assertIn("https://*.dogdrip.net/*", manifest["host_permissions"])
        self.assertIn("sidePanel", manifest["permissions"])
        self.assertIn("downloads", manifest["permissions"])
        self.assertEqual(manifest["side_panel"]["default_path"], "popup.html")
        self.assertNotIn("default_popup", manifest["action"])

    def test_manifest_references_only_packaged_files(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
        referenced = [
            manifest["side_panel"]["default_path"],
            manifest["background"]["service_worker"],
        ]
        for script in manifest["content_scripts"]:
            referenced.extend(script.get("js", []))
            referenced.extend(script.get("css", []))
        for filename in referenced:
            self.assertTrue((EXTENSION / filename).is_file(), filename)

    def test_ckeditor_4221_is_bundled_locally(self):
        html = (EXTENSION / "popup.html").read_text(encoding="utf-8")
        editor = (EXTENSION / "vendor" / "ckeditor" / "ckeditor.js").read_text(
            encoding="utf-8", errors="ignore"
        )
        editor_html = (EXTENSION / "editor.html").read_text(encoding="utf-8")
        self.assertIn('src="vendor/ckeditor/ckeditor.js"', editor_html)
        self.assertIn('src="editor.html"', html)
        self.assertIn('version:"4.22.1"', editor)
        self.assertTrue((EXTENSION / "vendor" / "ckeditor" / "LICENSE.md").is_file())
        self.assertTrue((EXTENSION / "vendor" / "ckeditor" / "lang" / "ko.js").is_file())

    def test_ckeditor_runs_in_manifest_sandbox(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
        editor_script = (EXTENSION / "editor.js").read_text(encoding="utf-8")
        editor_html = (EXTENSION / "editor.html").read_text(encoding="utf-8")
        editor_css = (EXTENSION / "editor.css").read_text(encoding="utf-8")
        popup_css = (EXTENSION / "popup.css").read_text(encoding="utf-8")
        self.assertIn("editor.html", manifest["sandbox"]["pages"])
        self.assertIn("'unsafe-inline'", manifest["content_security_policy"]["sandbox"])
        self.assertIn("versionCheck: false", editor_script)
        self.assertIn('CKEDITOR.inline("editor"', editor_script)
        self.assertNotIn("CKEDITOR.replace", editor_script)
        self.assertIn('id="toolbar"', editor_html)
        self.assertIn('contenteditable="true"', editor_html)
        self.assertIn("toolbar: []", editor_script)
        self.assertIn('querySelectorAll(".cke_float")', editor_script)
        self.assertIn("pointerEvents = \"none\"", editor_script)
        self.assertIn(".cke_float", editor_css)
        self.assertIn("pointer-events: none", editor_css)
        self.assertNotIn("forceIFrame", editor_script)
        self.assertIn('event.key === "Backspace"', editor_script)
        self.assertIn("event.stopImmediatePropagation()", editor_script)
        self.assertIn('document.addEventListener("keydown"', editor_script)
        self.assertIn('if (key === "s")', editor_script)
        self.assertIn('if (key === "l")', editor_script)
        self.assertIn("autoParagraph: false", editor_script)
        self.assertIn("enterMode: CKEDITOR.ENTER_BR", editor_script)
        self.assertIn("placeCaretAtEmptyStart", editor_script)
        self.assertIn('addEventListener("pointerdown"', editor_script)
        self.assertIn(".editor-surface p:first-child", editor_css)
        for control_id in ("styleSelect", "formatSelect", "fontSelect", "sizeSelect"):
            self.assertIn(f'id="{control_id}"', editor_html)
            self.assertIn(f'getElementById("{control_id}")', editor_script)
        self.assertNotIn('["Styles", "Format", "Font", "FontSize"', editor_script)
        self.assertIn('instance.on("floatingSpaceLayout"', editor_script)
        self.assertIn("selection.createBookmarks2(true)", editor_script)
        self.assertIn("selectBookmarks(savedBookmarks)", editor_script)
        self.assertIn('addEventListener("pointerdown", rememberEditorSelection', editor_script)
        self.assertNotIn("selectedIndex = 0", editor_script)
        self.assertIn('instance.on("selectionChange"', editor_script)
        self.assertIn("syncNativeCombos()", editor_script)
        self.assertIn('getComputedStyle("font-family")', editor_script)
        self.assertIn('getComputedStyle("font-size")', editor_script)
        self.assertIn('closestTag(start, ["strong", "code", "mark"])', editor_script)
        self.assertIn('closestTag(start, ["h1", "h2", "h3", "pre", "p"])', editor_script)
        for action in ("link", "image", "table", "specialchar"):
            self.assertIn(f'data-action="{action}"', editor_html)
            self.assertIn(f"data-action=\"{action}\"", editor_script)
        self.assertIn('id="editorDialog"', editor_html)
        self.assertIn("instance.execCommand(commandName)", editor_script)
        self.assertIn("instance.insertHtml(html)", editor_script)
        self.assertIn('button.classList.toggle("is-active", isActive)', editor_script)
        self.assertIn('button.setAttribute("aria-pressed", String(isActive))', editor_script)
        self.assertIn('getCommand(button.dataset.command)?.on("state", syncNativeCombos)', editor_script)
        self.assertIn('button[aria-pressed="true"]', editor_css)
        self.assertNotIn("padding-top", editor_css)
        self.assertNotIn(":empty::before", editor_css)
        self.assertIn("height: clamp(290px, 31vh, 320px)", popup_css)
        self.assertNotIn("height: 420px", popup_css)
        self.assertNotIn("height: 440px", popup_css)
        self.assertIn("min-height: 0", editor_css)
        self.assertIn("* { box-sizing: border-box; }", editor_css)
        self.assertIn("width: min(350px, 100%)", editor_css)
        self.assertIn("max-height: calc(100% - 2px)", editor_css)
        self.assertIn("height: 29px", editor_css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)", editor_css)
        self.assertIn(".dialog-field-full { grid-column: 1 / -1; }", editor_css)
        self.assertIn('["text", "url", "alt", "character"].includes(field.name)', editor_script)

    def test_extension_uses_no_remote_script(self):
        html = (EXTENSION / "popup.html").read_text(encoding="utf-8")
        self.assertNotIn("<script src=\"http", html)
        self.assertIn('<script src="popup.js"></script>', html)

    def test_panel_scales_to_the_available_viewport(self):
        popup_script = (EXTENSION / "popup.js").read_text(encoding="utf-8")
        self.assertIn("function fitInterfaceToViewport()", popup_script)
        self.assertIn('document.body.style.removeProperty("zoom")', popup_script)
        self.assertNotIn("const scale =", popup_script)
        self.assertNotIn("style.zoom = String", popup_script)
        self.assertIn('document.documentElement.style.overflowY = "hidden"', popup_script)
        self.assertIn('window.addEventListener("resize", fitInterfaceToViewport)', popup_script)

    def test_extension_uses_original_packaged_d_icons(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
        html = (EXTENSION / "popup.html").read_text(encoding="utf-8")
        self.assertIn('src="icons/icon-128.png"', html)
        self.assertNotIn("ic_profile_dd.png", html)
        for size in (16, 32, 48, 128):
            path = f"icons/icon-{size}.png"
            self.assertEqual(manifest["icons"][str(size)], path)
            self.assertTrue((EXTENSION / path).is_file())
        self.assertEqual(manifest["action"]["default_icon"]["16"], "icons/icon-16.png")

    def test_file_and_field_mapping_matches_registration_page_defaults(self):
        content_script = (EXTENSION / "content.js").read_text(encoding="utf-8")
        popup_script = (EXTENSION / "popup.js").read_text(encoding="utf-8")
        for expected in (
            "dogcon_main_file",
            "dogcon_file_{index}",
            'input[name="title"]',
            'input[name="price"]',
        ):
            self.assertIn(expected, content_script)
        self.assertIn('extraFilePattern: "dogcon_file_{index}"', popup_script)
        self.assertIn('mapping.extraFilePattern.replace("{index}"', popup_script)
        self.assertIn("MAX_FILES = 50", popup_script)

    def test_lite_mapping_settings_are_editable_persistent_and_forwarded(self):
        html = (EXTENSION / "popup.html").read_text(encoding="utf-8")
        popup_script = (EXTENSION / "popup.js").read_text(encoding="utf-8")
        self.assertIn('id="mappingSettings"', html)
        self.assertIn('id="mappingDialog"', html)
        self.assertIn("const DEFAULT_MAPPING", popup_script)
        self.assertIn("liteMapping", popup_script)
        self.assertIn("renderMappingFields(DEFAULT_MAPPING)", popup_script)
        self.assertIn('includes("{index}")', popup_script)
        self.assertIn("mapping.mainFileName", popup_script)
        self.assertIn("mapping.extraFilePattern", popup_script)
        self.assertGreaterEqual(popup_script.count("mapping"), 10)

    def test_registration_url_and_workspace_tabs_are_supported(self):
        html = (EXTENSION / "popup.html").read_text(encoding="utf-8")
        popup_script = (EXTENSION / "popup.js").read_text(encoding="utf-8")
        popup_css = (EXTENSION / "popup.css").read_text(encoding="utf-8")
        editor_script = (EXTENSION / "editor.js").read_text(encoding="utf-8")
        for control_id in (
            "registrationUrl", "defaultRegistrationUrl", "profileTabs", "tabScrollbar", "tabScrollThumb", "addProfileTab",
            "postInfoToggle", "postInfoContent", "postInfoScrollShell", "postInfoScrollbar", "postInfoScrollThumb",
            "saveProfile", "deleteTabDialog", "confirmDeleteTab", "skipDeleteConfirmSession", "exportProfiles", "importProfiles"
        ):
            self.assertIn(f'id="{control_id}"', html)
        self.assertIn("liteProfiles", popup_script)
        self.assertIn("async function saveCurrentProfile()", popup_script)
        self.assertIn("let profileDrafts = {}", popup_script)
        self.assertIn("const dirtyProfiles = new Set()", popup_script)
        self.assertIn("function currentInputSnapshot()", popup_script)
        self.assertIn("function updateDirtyState(name, draft)", popup_script)
        self.assertIn('content: "*"', popup_css)
        self.assertIn('chrome.storage.local.remove("liteForm")', popup_script)
        self.assertNotIn("await chrome.storage.local.set({\n    liteForm:", popup_script)
        self.assertIn("async function addProfileTab()", popup_script)
        self.assertIn("function startTabRename(tab, oldName)", popup_script)
        self.assertIn("async function reorderProfileTabs(sourceName, targetName, placeAfter)", popup_script)
        self.assertIn('tab.addEventListener("dragstart"', popup_script)
        self.assertIn('tab.addEventListener("drop"', popup_script)
        self.assertIn("function updateTabScrollbar()", popup_script)
        self.assertIn('elements.profileTabs.addEventListener("scroll"', popup_script)
        self.assertIn("async function confirmDeleteProfile()", popup_script)
        self.assertIn("let skipDeleteConfirmationForSession = false", popup_script)
        self.assertIn("if (skipDeleteConfirmationForSession)", popup_script)
        self.assertIn("skipDeleteConfirmationForSession = true", popup_script)
        self.assertIn("liteActiveProfile", popup_script)
        self.assertIn("async function exportProfilesToJson()", popup_script)
        self.assertIn("async function importProfilesFromJson(file)", popup_script)
        self.assertIn("chrome.downloads.download", popup_script)
        self.assertIn("saveAs: true", popup_script)
        self.assertIn('event.key.toLowerCase() === "s"', popup_script)
        self.assertIn('type: "SAVE_SHORTCUT"', editor_script)
        self.assertIn("registrationUrl: elements.registrationUrl.value", popup_script)
        self.assertIn('title="내보내기"', html)
        self.assertIn('title="가져오기"', html)
        self.assertIn('d="M12 18v-6"', html)
        self.assertIn('class="content-scroll"', html)
        self.assertIn('aria-expanded="true"', html)
        self.assertIn('elements.postInfoToggle.addEventListener("click"', popup_script)
        self.assertIn("function updatePostInfoScrollbar()", popup_script)
        self.assertNotIn('elements.postInfoScrollbar.classList.toggle("is-hidden"', popup_script)
        self.assertIn('elements.postInfoScrollThumb.classList.add("is-static")', popup_script)
        self.assertIn('elements.postInfoContent.addEventListener("scroll"', popup_script)
        self.assertIn('elements.postInfoScrollShell.addEventListener("pointerenter"', popup_script)
        self.assertIn("new ResizeObserver(updatePostInfoScrollbar)", popup_script)
        self.assertIn(".post-info-scroll-shell:hover .post-info-scrollbar", popup_css)
        self.assertIn(".post-info-scroll-shell.is-scroll-hover .post-info-scrollbar", popup_css)
        self.assertIn(".content-scroll { display: flex", popup_css)
        self.assertIn(".actions-section { flex: 0 0 auto", popup_css)


if __name__ == "__main__":
    unittest.main()
