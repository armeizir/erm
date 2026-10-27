(function () {
  'use strict';
  function init() {
    document.querySelectorAll('textarea.smt-rich-editor').forEach(function (textarea) {
      if (textarea.dataset.editorReady || textarea.disabled || textarea.readOnly) return;
      textarea.dataset.editorReady = '1';
      var wrapper = document.createElement('div');
      wrapper.className = 'smt-editor';
      var toolbar = document.createElement('div');
      toolbar.className = 'smt-editor-toolbar';
      toolbar.setAttribute('role', 'toolbar');
      toolbar.setAttribute('aria-label', 'Format teks');
      var content = document.createElement('div');
      content.className = 'smt-editor-content';
      content.contentEditable = 'true';
      content.setAttribute('role', 'textbox');
      content.setAttribute('aria-multiline', 'true');
      var label = document.querySelector('label[for="' + textarea.id + '"]');
      content.setAttribute('aria-label', label ? label.textContent : textarea.name);
      content.innerHTML = textarea.dataset.editorHtml || '';
      content.id = textarea.id + '_editor';
      function sync() {
        textarea.value = content.textContent.trim() ? content.innerHTML : '';
        textarea.dispatchEvent(new Event('change', { bubbles: true }));
      }
      var commands = [
        ['bold', 'B', 'Tebal'], ['italic', 'I', 'Miring'], ['underline', 'U', 'Garis bawah'],
        ['insertOrderedList', '1. Daftar', 'Daftar bernomor'],
        ['insertUnorderedList', '• Daftar', 'Daftar bullet'],
        ['outdent', '←', 'Kurangi inden'], ['indent', '→', 'Tambah inden'],
        ['justifyLeft', 'Kiri', 'Rata kiri'], ['justifyCenter', 'Tengah', 'Rata tengah'],
        ['justifyRight', 'Kanan', 'Rata kanan'], ['justifyFull', 'Rata', 'Rata kiri kanan'],
        ['undo', '↶', 'Batalkan'], ['redo', '↷', 'Ulangi'],
        ['removeFormat', 'Hapus format', 'Hapus format teks']
      ];
      commands.forEach(function (item) {
        var button = document.createElement('button');
        button.type = 'button';
        button.textContent = item[1];
        button.title = item[2];
        button.setAttribute('aria-label', item[2]);
        button.addEventListener('mousedown', function (event) { event.preventDefault(); });
        button.addEventListener('click', function () {
          content.focus();
          document.execCommand(item[0], false, null);
          sync();
        });
        toolbar.appendChild(button);
      });
      content.addEventListener('input', sync);
      // Word/browser pastes can contain arbitrary markup. Paste literal text;
      // the local toolbar then applies the formats supported by both editor and PDF.
      content.addEventListener('paste', function (event) {
        if (!event.clipboardData) return;
        event.preventDefault();
        document.execCommand('insertText', false, event.clipboardData.getData('text/plain'));
        sync();
      });
      content.addEventListener('drop', function (event) { event.preventDefault(); });
      wrapper.appendChild(toolbar);
      wrapper.appendChild(content);
      textarea.insertAdjacentElement('afterend', wrapper);
      textarea.hidden = true;
      if (label) label.htmlFor = content.id;
      textarea.form.addEventListener('submit', sync);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
