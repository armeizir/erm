/* Search existing authorized choices only; no new users or AJAX permission changes. */
(function () {
    'use strict';
    function init() {
        const $ = window.django && window.django.jQuery;
        if (!$ || !$.fn.select2) return;
        ['reviewed_by', 'approved_by'].forEach(function (name) {
            const element = document.getElementById('id_' + name);
            if (!element || element.tagName !== 'SELECT' || element.disabled) return;
            const field = $(element);
            if (field.hasClass('select2-hidden-accessible')) return;
            field.select2({
                width: '100%',
                minimumResultsForSearch: 0,
                placeholder: 'Ketik nama, username, atau email…',
                allowClear: !element.required,
                language: {
                    noResults: function () { return 'Pengguna tidak ditemukan pada pilihan yang diizinkan.'; },
                    searching: function () { return 'Mencari pengguna…'; }
                },
                matcher: function (params, data) {
                    if (!params.term || !params.term.trim()) return data;
                    const words = params.term.toLocaleLowerCase().trim().split(/\s+/);
                    const label = (data.text || '').toLocaleLowerCase();
                    return words.every(function (word) { return label.includes(word); }) ? data : null;
                }
            });
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
    window.addEventListener('pageshow', init);
})();
