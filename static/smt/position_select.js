(function($) {
    function init() {
        $('.smt-position-select').each(function() {
            if (!$(this).hasClass('select2-hidden-accessible')) {
                $(this).select2({width: 'resolve', placeholder: 'Cari jabatan...', allowClear: true});
            }
        });
    }
    $(init);
})(django.jQuery);
