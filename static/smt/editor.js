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
      // SMT_SUBSECTION_V1: native ordered-list counters survive Enter and deletion.
      var subsectionButton = document.createElement('button');
      subsectionButton.type = 'button';
      subsectionButton.textContent = '3.1 Subbab';
      subsectionButton.title = 'Daftar subbab otomatis (misalnya 3.1, 3.2)';
      subsectionButton.addEventListener('mousedown', function (event) { event.preventDefault(); });
      subsectionButton.addEventListener('click', function () {
        var sections = {tujuan: '1', ruang_lingkup: '2', referensi: '3', tanggung_jawab: '4', langkah_kerja: '5'};
        var key = textarea.name.split('-').pop();
        var section = window.prompt('Nomor bagian (1 sampai 99):', sections[key] || '3');
        if (section === null) return;
        section = section.trim();
        if (!/^[1-9][0-9]?$/.test(section)) {
          window.alert('Isi nomor bagian 1 sampai 99.'); return;
        }
        content.focus();
        var selection = window.getSelection();
        var current = selection && selection.anchorNode;
        current = current && (current.nodeType === 1 ? current : current.parentElement);
        var list = current && current.closest('ol');
        if (!list || !content.contains(list)) {
          var range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
          var blocks = Array.from(content.childNodes).filter(function (node) {
            return !range || range.collapsed || range.intersectsNode(node);
          });
          if (!blocks.length) return;
          if (blocks.some(function (node) { return node.nodeType === 1 && node.querySelector('ol,ul'); })) {
            window.alert('Pilih paragraf biasa atau letakkan kursor dalam daftar bernomor.'); return;
          }
          list = document.createElement('ol');
          content.insertBefore(list, blocks[0]);
          blocks.forEach(function (node) {
            var container = document.createElement('div');
            container.appendChild(node.cloneNode(true));
            // Existing imported references commonly use one paragraph with BR separators.
            var pieces = container.innerHTML.split(/<br\s*\/?\s*>|\r?\n/gi);
            pieces.forEach(function (html) {
              var li = document.createElement('li');
              li.innerHTML = html;
              if (li.textContent.trim()) list.appendChild(li);
            });
            node.remove();
          });
        }
        list.setAttribute('data-section', section);
        list.removeAttribute('start');
        Array.from(list.children).forEach(function (li) {
          // Avoid doubled numbers when converting manually numbered text.
          var walker = document.createTreeWalker(li, NodeFilter.SHOW_TEXT);
          var first = walker.nextNode();
          if (first) first.nodeValue = first.nodeValue.replace(/^\s*\d{1,2}\.\d{1,4}(?:\.\s*|\s+)|^\s*\d{1,4}\.\s+/, '');
        });
        if (!list.children.length) list.innerHTML = '<li><br></li>';
        var caret = document.createRange();
        caret.selectNodeContents(list.firstElementChild);
        caret.collapse(false);
        selection.removeAllRanges(); selection.addRange(caret);
        sync();
      });
      toolbar.appendChild(subsectionButton);
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
