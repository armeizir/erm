(function () {
    'use strict';
    function mark(select) {
        var row = select.closest('.monitoring-risk');
        if (!row) return;
        var marker = row.querySelector('input[name$="-_row_touched"]');
        if (marker) marker.value = '1';
    }
    function init(root) {
        var $ = window.django && window.django.jQuery;
        (root || document).querySelectorAll('select[data-pic-scope="1"]').forEach(function (select) {
            if (select.dataset.picScopeReady === '1') return;
            select.dataset.picScopeReady = '1';
            select.addEventListener('change', function () { mark(select); });
            if (!$ || !$.fn.select2 || select.disabled) return;
            var field = $(select);
            if (field.hasClass('select2-hidden-accessible')) field.select2('destroy');
            field.select2({
                width: '100%', minimumResultsForSearch: 0,
                placeholder: 'Ketik kode atau nama unit…', allowClear: !select.required,
                language: { noResults: function () { return 'Unit tidak ditemukan dalam cakupan bidang laporan.'; } }
            });
            field.on('select2:select.picScope select2:clear.picScope', function () {
                mark(select);
                // jQuery's synthetic change does not reach native DOM listeners.
                select.dispatchEvent(new Event('change', {bubbles: true}));
            });
        });
    }
    function start() {
        init(document);
        document.addEventListener('formset:added', function () { init(document); });
        var $ = window.django && window.django.jQuery;
        if ($) $(document).on('formset:added.picScope', function () { init(document); });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
