(function () {
  function update(input) {
    var suffix = 'realisasi_nilai_dampak';
    var prefix = input.name.slice(0, -suffix.length);
    var form = input.form;
    function field(name) { return form.elements.namedItem(prefix + name); }
    var probability = field('realisasi_nilai_probabilitas');
    if (!probability) return;
    var config = JSON.parse(input.getAttribute('data-risk-scale-auto'));
    var d = input.value === '' ? null : Number(input.value);
    var p = probability.value === '' ? null : Number(probability.value);
    var dl = d === null || !Number.isFinite(d) || d < 0 ? null : d < 33e9 ? 1 : d <= 66e9 ? 2 : d <= 100e9 ? 3 : d <= 133e9 ? 4 : 5;
    var pl = p === null || !Number.isFinite(p) || p < 0 || p > 100 ? null : p < 20 ? 1 : p <= 40 ? 2 : p <= 60 ? 3 : p <= 80 ? 4 : 5;
    // AUTO_EXPOSURE_PREVIEW_V1
    var exposure = field('realisasi_eksposur');
    if (exposure) {
      exposure.readOnly = true;
      exposure.value = (
        d !== null && p !== null &&
        Number.isFinite(d) && Number.isFinite(p) &&
        d >= 0 && p >= 0 && p <= 100
      ) ? (d * p / 100).toFixed(2) : '';
    }
    var cell = config.cells[dl + ',' + pl];
    [['realisasi_skala_dampak', config.impact[dl]],
     ['realisasi_skala_probabilitas', config.probability[pl]],
     ['realisasi_skor_risiko', cell && cell[0]],
     ['realisasi_level_risiko_bumn', cell && cell[1]]].forEach(function (entry) {
      var element = field(entry[0]);
      if (element) element.value = entry[1] == null ? '' : entry[1];
    });
  }
  document.addEventListener('input', function (event) {
    var target = event.target;
    if (!target.name || !/realisasi_nilai_(dampak|probabilitas)$/.test(target.name)) return;
    var name = target.name.replace(/realisasi_nilai_(dampak|probabilitas)$/, 'realisasi_nilai_dampak');
    var input = target.form && target.form.elements.namedItem(name);
    if (input && input.hasAttribute('data-risk-scale-auto')) update(input);
  });
})();
