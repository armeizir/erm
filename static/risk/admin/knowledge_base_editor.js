(function () {
  function initKnowledgeBaseEditor() {
    if (!window.CKEDITOR) {
      return;
    }

    document.querySelectorAll("textarea.kb-rich-editor").forEach(function (textarea) {
      if (textarea.dataset.ckeditorReady === "1") {
        return;
      }
      textarea.dataset.ckeditorReady = "1";

      CKEDITOR.replace(textarea.id, {
        height: 460,
        width: "100%",
        removePlugins: "elementspath",
        resize_enabled: true,
        allowedContent: true,
        toolbar: [
          { name: "document", items: ["Source", "-", "Preview", "Print"] },
          { name: "clipboard", items: ["Cut", "Copy", "Paste", "PasteText", "PasteFromWord", "-", "Undo", "Redo"] },
          { name: "editing", items: ["Find", "Replace", "-", "SelectAll", "-", "Scayt"] },
          { name: "basicstyles", items: ["Bold", "Italic", "Underline", "Strike", "Subscript", "Superscript", "-", "RemoveFormat"] },
          { name: "paragraph", items: ["NumberedList", "BulletedList", "-", "Outdent", "Indent", "-", "Blockquote", "-", "JustifyLeft", "JustifyCenter", "JustifyRight", "JustifyBlock"] },
          { name: "links", items: ["Link", "Unlink", "Anchor"] },
          { name: "insert", items: ["Image", "Table", "HorizontalRule", "SpecialChar"] },
          { name: "styles", items: ["Styles", "Format", "Font", "FontSize"] },
          { name: "colors", items: ["TextColor", "BGColor"] },
          { name: "tools", items: ["Maximize", "ShowBlocks"] }
        ]
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initKnowledgeBaseEditor);
  } else {
    initKnowledgeBaseEditor();
  }
})();
