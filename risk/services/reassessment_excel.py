"""Excel export for Unit/Business Risk Profiles.

The exporter treats the official workbook as an immutable visual template and
updates only the data cells inside the XLSX package.  This keeps sheet names,
colors, borders, widths, print settings, formulas, hidden reference sheets, and
other workbook content identical to the approved working paper.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"

ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", REL_NS)

COMPANY_NAME = "PT Perusahaan Listrik Negara (Persero)"
COMPANY_CODE = "PLNA"
COMPANY_SHORT_NAME = "PLN BATAM"

PROFILE_SHEET = "Profil Risiko"
TREATMENT_SHEET = "Rencana Perlakuan Risiko"
SUMMARY_SHEET = "SUMMARY"
JUSTIFICATION_SHEET = "Justifikasi Risk Assessment"
QUARTERLY_SHEET = "LAP REAL III.A"
HEATMAP_SHEET = "Heatmap"
INHERENT_QUANT_SHEET = "Risiko Inheren Kuantitatif"
INHERENT_QUAL_SHEET = "Risiko Inheren Kualitatif"
RESIDUAL_QUANT_SHEET = "Risiko Residual Kuantitatif"
RESIDUAL_QUAL_SHEET = "Risiko Residual Kualitatif"
STRATEGY_SHEET = "Pilihan Sasaran&Strategi Bisnis"


class ProfileWorkbookError(Exception):
    """Raised when an official risk-profile workbook cannot be produced."""


def profile_workbook_template_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "excel_templates"
        / "reassessment_profile_template.xlsx"
    )


def profile_workbook_filename(summary) -> str:
    unit = re.sub(r"[^A-Za-z0-9._-]+", "_", str(summary.unit_bisnis or "UNIT"))
    unit = unit.strip("._-") or "UNIT"
    return f"Profil_Risiko_{unit}_{summary.tahun}.xlsx"


def _qname(local_name: str) -> str:
    return f"{{{MAIN_NS}}}{local_name}"


def _column_number(column_name: str) -> int:
    result = 0
    for char in column_name:
        result = result * 26 + (ord(char.upper()) - 64)
    return result


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _split_coordinate(coordinate: str) -> tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", coordinate.upper())
    if not match:
        raise ValueError(f"Koordinat sel tidak valid: {coordinate}")
    return match.group(1), int(match.group(2))


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _excel_number(value):
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    return value


def _probability_fraction(value):
    if value in (None, ""):
        return None
    return Decimal(str(value)) / Decimal("100")


def _related_label(value):
    return str(value) if value not in (None, "") else None


def _scale_value(value):
    if value in (None, ""):
        return None
    order = getattr(value, "urutan", None)
    if order not in (None, ""):
        return order
    match = re.search(r"\b([1-5])\b", str(value))
    return int(match.group(1)) if match else None


def _level_value(value):
    if value in (None, ""):
        return None
    label = str(value).strip()
    canonical = {
        "low": "Low",
        "low to moderate": "Low To Moderate",
        "moderate": "Moderate",
        "moderate to high": "Moderate To High",
        "high": "High",
    }
    return canonical.get(label.casefold(), label)


def _impact_is_qualitative(item) -> bool:
    category = str(getattr(item, "kategori_dampak", "") or "").casefold()
    return "kualitatif" in category


def _base_impact(item):
    return getattr(item, "nilai_dampak", None) or getattr(item, "nilai_dampak_q1", None)


def _base_probability(item):
    return getattr(item, "nilai_probabilitas", None) or getattr(
        item, "nilai_probabilitas_q1", None
    )


def _base_scale_impact(item):
    return _scale_value(getattr(item, "skala_dampak_q1", None))


def _base_scale_probability(item):
    return _scale_value(
        getattr(item, "skala_probabilitas", None)
        or getattr(item, "skala_probabilitas_q1", None)
    )


def _base_exposure(item):
    stored = getattr(item, "eksposur_risiko_q1", None)
    if stored not in (None, ""):
        return stored
    impact = _base_impact(item)
    probability = _base_probability(item)
    if impact in (None, "") or probability in (None, ""):
        return None
    return Decimal(str(impact)) * Decimal(str(probability)) / Decimal("100")


def _items_for_summary(summary):
    return list(
        summary.item.filter(is_active=True).select_related(
            "km_item",
            "km_item__master_bagian",
            "sasaran_kbumn",
            "taksonomi_t3",
            "kategori_risiko",
            "jenis_existing_control",
            "penilaian_efektivitas_kontrol",
            "kategori_dampak",
            "skala_dampak_q1",
            "skala_dampak_q2",
            "skala_dampak_q3",
            "skala_dampak_q4",
            "skala_probabilitas",
            "skala_probabilitas_q1",
            "skala_probabilitas_q2",
            "skala_probabilitas_q3",
            "skala_probabilitas_q4",
            "opsi_perlakuan_risiko",
            "pos_anggaran",
            "jenis_program_dalam_rkap",
            "pic_organization_unit",
            "pic_user_assignment__user",
        )
        .prefetch_related("jenis_rencana_perlakuan_risiko")
        .order_by("no_item", "no_risiko", "no_penyebab_risiko", "id")
    )


def _risk_representatives(items):
    grouped = OrderedDict()
    for item in items:
        risk_number = getattr(item, "no_risiko", None)
        key = ("number", risk_number) if risk_number not in (None, "") else ("item", id(item))
        grouped.setdefault(key, item)
    return list(grouped.values())


def _unit_name(item):
    unit = getattr(item, "unit_bisnis", None)
    if unit:
        return str(unit)
    summary = getattr(item, "summary", None)
    return str(getattr(summary, "unit_bisnis", "") or "")


def _treatment_types(item):
    relation = getattr(item, "jenis_rencana_perlakuan_risiko", None)
    if relation is None:
        return None
    try:
        values = [str(value) for value in relation.all()]
    except (AttributeError, TypeError):
        values = [str(value) for value in relation]
    return "\n".join(value for value in values if value) or None


def _pic_organization(item):
    value = getattr(item, "pic_organization_display", None)
    if value and value != "Belum ditentukan":
        return value
    return getattr(item, "pic", None)


class _WorkbookPackage:
    def __init__(self, template_path: Path):
        if not template_path.exists():
            raise ProfileWorkbookError(
                f"Template Excel Profil Risiko tidak ditemukan: {template_path}"
            )
        with ZipFile(template_path, "r") as archive:
            self.infos = archive.infolist()
            self.files = {info.filename: archive.read(info.filename) for info in self.infos}
        self.sheet_paths = self._resolve_sheet_paths()
        self.sheet_roots = {}

    def _resolve_sheet_paths(self):
        workbook_root = ET.fromstring(self.files["xl/workbook.xml"])
        relationship_root = ET.fromstring(
            self.files["xl/_rels/workbook.xml.rels"]
        )
        relationship_map = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationship_root.findall(
                f"{{{PACKAGE_REL_NS}}}Relationship"
            )
        }
        result = {}
        sheets = workbook_root.find(_qname("sheets"))
        for sheet in sheets:
            relationship_id = sheet.attrib[f"{{{REL_NS}}}id"]
            target = relationship_map[relationship_id]
            if target.startswith("/"):
                path = target.lstrip("/")
            else:
                path = str(PurePosixPath("xl") / target)
            result[sheet.attrib["name"]] = path
        return result

    def sheet(self, name: str):
        if name not in self.sheet_paths:
            raise ProfileWorkbookError(
                f"Sheet wajib tidak ditemukan pada template: {name}"
            )
        if name not in self.sheet_roots:
            self.sheet_roots[name] = ET.fromstring(self.files[self.sheet_paths[name]])
        return self.sheet_roots[name]

    @staticmethod
    def _sheet_data(root):
        sheet_data = root.find(_qname("sheetData"))
        if sheet_data is None:
            sheet_data = ET.SubElement(root, _qname("sheetData"))
        return sheet_data

    def _find_row(self, root, row_number: int):
        for row in self._sheet_data(root).findall(_qname("row")):
            if int(row.attrib.get("r", 0)) == row_number:
                return row
        return None

    def _ensure_row(self, root, row_number: int, style_source_row: int | None = None):
        existing = self._find_row(root, row_number)
        if existing is not None:
            return existing

        sheet_data = self._sheet_data(root)
        source = self._find_row(root, style_source_row) if style_source_row else None
        if source is not None:
            row = deepcopy(source)
            row.attrib["r"] = str(row_number)
            for cell in row.findall(_qname("c")):
                column, _ = _split_coordinate(cell.attrib["r"])
                cell.attrib["r"] = f"{column}{row_number}"
                for child in list(cell):
                    cell.remove(child)
                cell.attrib.pop("t", None)
        else:
            row = ET.Element(_qname("row"), {"r": str(row_number)})

        inserted = False
        for index, current in enumerate(sheet_data.findall(_qname("row"))):
            if int(current.attrib.get("r", 0)) > row_number:
                sheet_data.insert(index, row)
                inserted = True
                break
        if not inserted:
            sheet_data.append(row)
        return row

    def _style_from(self, root, column: str, style_source_row: int | None):
        if style_source_row is None:
            return None
        row = self._find_row(root, style_source_row)
        if row is None:
            return None
        coordinate = f"{column}{style_source_row}"
        for cell in row.findall(_qname("c")):
            if cell.attrib.get("r") == coordinate:
                return cell.attrib.get("s")
        return None

    def _ensure_cell(
        self,
        root,
        coordinate: str,
        *,
        style_source_row: int | None = None,
    ):
        column, row_number = _split_coordinate(coordinate)
        row = self._ensure_row(root, row_number, style_source_row)
        for cell in row.findall(_qname("c")):
            if cell.attrib.get("r") == coordinate:
                return cell

        attributes = {"r": coordinate}
        style = self._style_from(root, column, style_source_row)
        if style is not None:
            attributes["s"] = style
        cell = ET.Element(_qname("c"), attributes)
        target_column = _column_number(column)
        inserted = False
        for index, current in enumerate(row.findall(_qname("c"))):
            current_column, _ = _split_coordinate(current.attrib["r"])
            if _column_number(current_column) > target_column:
                row.insert(index, cell)
                inserted = True
                break
        if not inserted:
            row.append(cell)
        return cell

    def set_value(
        self,
        sheet_name: str,
        coordinate: str,
        value,
        *,
        style_source_row: int | None = None,
    ):
        root = self.sheet(sheet_name)
        cell = self._ensure_cell(
            root,
            coordinate,
            style_source_row=style_source_row,
        )
        for child in list(cell):
            cell.remove(child)
        cell.attrib.pop("t", None)

        if value in (None, ""):
            return

        if isinstance(value, bool):
            cell.attrib["t"] = "b"
            ET.SubElement(cell, _qname("v")).text = "1" if value else "0"
            return

        if isinstance(value, (int, float, Decimal)):
            text = _decimal_text(value) if isinstance(value, Decimal) else str(value)
            ET.SubElement(cell, _qname("v")).text = text
            return

        cell.attrib["t"] = "inlineStr"
        inline = ET.SubElement(cell, _qname("is"))
        text_node = ET.SubElement(inline, _qname("t"))
        text = str(value)
        if text != text.strip() or "\n" in text or "\t" in text:
            text_node.attrib[f"{{{XML_NS}}}space"] = "preserve"
        text_node.text = text

    def clear_range(
        self,
        sheet_name: str,
        start_column: str,
        end_column: str,
        start_row: int,
        end_row: int,
        *,
        style_source_row: int | None = None,
    ):
        for row in range(start_row, end_row + 1):
            for column_number in range(
                _column_number(start_column), _column_number(end_column) + 1
            ):
                self.set_value(
                    sheet_name,
                    f"{_column_name(column_number)}{row}",
                    None,
                    style_source_row=style_source_row,
                )

    def update_dimension(self, sheet_name: str, end_column: str, end_row: int):
        root = self.sheet(sheet_name)
        dimension = root.find(_qname("dimension"))
        if dimension is not None:
            start_ref = dimension.attrib.get("ref", "A1").split(":", 1)[0]
            dimension.attrib["ref"] = f"{start_ref}:{end_column}{end_row}"

    def enable_full_calculation(self):
        root = ET.fromstring(self.files["xl/workbook.xml"])
        calculation = root.find(_qname("calcPr"))
        if calculation is None:
            calculation = ET.SubElement(root, _qname("calcPr"))
        calculation.attrib.update(
            {
                "calcMode": "auto",
                "fullCalcOnLoad": "1",
                "forceFullCalc": "1",
                "calcId": "0",
            }
        )
        self.files["xl/workbook.xml"] = ET.tostring(
            root, encoding="utf-8", xml_declaration=True
        )

    def to_bytes(self) -> bytes:
        for sheet_name, root in self.sheet_roots.items():
            self.files[self.sheet_paths[sheet_name]] = ET.tostring(
                root, encoding="utf-8", xml_declaration=True
            )
        self.enable_full_calculation()
        output = BytesIO()
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            written = set()
            for info in self.infos:
                archive.writestr(info, self.files[info.filename])
                written.add(info.filename)
            for filename, content in self.files.items():
                if filename not in written:
                    archive.writestr(filename, content)
        return output.getvalue()


def _profile_row(item, sequence: int, first: bool):
    return {
        "A": "Start Pengisian" if first else None,
        "B": sequence,
        "C": COMPANY_NAME,
        "D": COMPANY_CODE,
        "E": getattr(item, "sasaran_pln_batam", None),
        "F": _related_label(getattr(item, "sasaran_kbumn", None)),
        "G": _related_label(getattr(item, "kategori_risiko", None)),
        "H": _related_label(getattr(item, "taksonomi_t3", None)),
        "I": getattr(item, "no_risiko", None),
        "J": getattr(item, "peristiwa_risiko", None),
        "K": getattr(item, "deskripsi_peristiwa_risiko", None),
        "L": getattr(item, "no_penyebab_risiko", None),
        "M": getattr(item, "kode_penyebab_risiko", None),
        "N": getattr(item, "penyebab_risiko", None),
        "O": getattr(item, "key_risk_indicators", None),
        "P": getattr(item, "unit_satuan_kri", None),
        "Q": getattr(item, "threshold_aman", None),
        "R": getattr(item, "threshold_hati_hati", None),
        "S": getattr(item, "threshold_bahaya", None),
        "T": _related_label(getattr(item, "jenis_existing_control", None)),
        "U": getattr(item, "existing_control", None),
        "V": _related_label(getattr(item, "penilaian_efektivitas_kontrol", None)),
        "W": _related_label(getattr(item, "kategori_dampak", None)),
        "X": getattr(item, "deskripsi_dampak", None),
        "Y": getattr(item, "perkiraan_waktu_terpapar_risiko", None),
    }


def _treatment_row(item, sequence: int, first: bool):
    row = {
        "A": "Start Pengisian" if first else None,
        "B": sequence,
        "C": COMPANY_NAME,
        "D": COMPANY_CODE,
        "E": getattr(item, "no_risiko", None),
        "F": getattr(item, "no_penyebab_risiko", None),
        "G": getattr(item, "penyebab_risiko", None),
        "H": _related_label(getattr(item, "opsi_perlakuan_risiko", None)),
        "I": _treatment_types(item),
        "J": getattr(item, "rencana_perlakuan_risiko", None),
        "K": getattr(item, "output_perlakuan_risiko", None),
        "L": _excel_number(getattr(item, "biaya_perlakuan_risiko", None)),
        "M": None,
        "N": None,
        "O": None,
        "P": _related_label(getattr(item, "jenis_program_dalam_rkap", None)),
        "Q": _pic_organization(item),
    }
    for month in range(1, 13):
        row[_column_name(17 + month)] = getattr(item, f"timeline_{month}", 0)
    return row


def _summary_row(item, sequence: int, first: bool):
    row = {
        "A": "Start Pengisian" if first else None,
        "B": sequence,
        "C": COMPANY_NAME,
        "D": COMPANY_SHORT_NAME,
        "E": _unit_name(item),
        "F": getattr(item, "sasaran_pln_batam", None),
        "G": getattr(getattr(item, "km_item", None), "no_urut", None),
        "H": getattr(item, "sasaran_pln_batam", None),
        "I": _related_label(getattr(item, "sasaran_kbumn", None)),
        "J": _related_label(getattr(item, "taksonomi_t3", None)),
        "K": _related_label(getattr(item, "kategori_risiko", None)),
        "L": getattr(item, "no_risiko", None),
        "M": getattr(item, "peristiwa_risiko", None),
        "N": getattr(item, "deskripsi_peristiwa_risiko", None),
        "O": getattr(item, "no_penyebab_risiko", None),
        "P": getattr(item, "kode_penyebab_risiko", None),
        "Q": getattr(item, "penyebab_risiko", None),
        "R": getattr(item, "key_risk_indicators", None),
        "S": getattr(item, "unit_satuan_kri", None),
        "T": getattr(item, "threshold_aman", None),
        "U": getattr(item, "threshold_hati_hati", None),
        "V": getattr(item, "threshold_bahaya", None),
        "W": _related_label(getattr(item, "jenis_existing_control", None)),
        "X": getattr(item, "existing_control", None),
        "Y": _related_label(getattr(item, "penilaian_efektivitas_kontrol", None)),
        "Z": _related_label(getattr(item, "kategori_dampak", None)),
        "AA": getattr(item, "deskripsi_dampak", None),
        "AB": getattr(item, "perkiraan_waktu_terpapar_risiko", None),
        "AC": getattr(item, "asumsi_perhitungan_dampak", None),
        "AD": "Wajib Isi" if _base_impact(item) is not None else None,
        "AE": _excel_number(_base_impact(item)),
        "AF": _base_scale_impact(item),
        "AG": _probability_fraction(_base_probability(item)),
        "AH": _base_scale_probability(item),
        "AI": _excel_number(_base_exposure(item)),
        "AJ": getattr(item, "skala_risiko_q1", None),
        "AK": _level_value(getattr(item, "level_nilai_risiko_q1", None)),
        "BU": "Start Pengisian" if first else None,
        "BV": sequence,
        "BW": COMPANY_NAME,
        "BX": COMPANY_CODE,
        "BY": getattr(item, "no_risiko", None),
        "BZ": getattr(item, "no_penyebab_risiko", None),
        "CA": getattr(item, "penyebab_risiko", None),
        "CB": _related_label(getattr(item, "opsi_perlakuan_risiko", None)),
        "CC": _treatment_types(item),
        "CD": getattr(item, "rencana_perlakuan_risiko", None),
        "CE": getattr(item, "output_perlakuan_risiko", None),
        "CF": _excel_number(getattr(item, "biaya_perlakuan_risiko", None)),
        "CG": _related_label(getattr(item, "pos_anggaran", None)),
        "CH": getattr(item, "prk", None),
        "CI": _related_label(getattr(item, "jenis_program_dalam_rkap", None)),
        "CJ": _pic_organization(item),
    }
    for quarter, column in enumerate(("AO", "AP", "AQ", "AR"), start=1):
        row[column] = _excel_number(getattr(item, f"nilai_dampak_q{quarter}", None))
    for quarter, column in enumerate(("AS", "AT", "AU", "AV"), start=1):
        row[column] = _scale_value(getattr(item, f"skala_dampak_q{quarter}", None))
    for quarter, column in enumerate(("AW", "AX", "AY", "AZ"), start=1):
        row[column] = _probability_fraction(
            getattr(item, f"nilai_probabilitas_q{quarter}", None)
        )
    for quarter, column in enumerate(("BA", "BB", "BC", "BD"), start=1):
        row[column] = _scale_value(
            getattr(item, f"skala_probabilitas_q{quarter}", None)
        )
    for quarter, column in enumerate(("BE", "BF", "BG", "BH"), start=1):
        row[column] = _excel_number(
            getattr(item, f"eksposur_risiko_q{quarter}", None)
        )
    for quarter, column in enumerate(("BI", "BJ", "BK", "BL"), start=1):
        row[column] = getattr(item, f"skala_risiko_q{quarter}", None)
    for quarter, column in enumerate(("BM", "BN", "BO", "BP"), start=1):
        row[column] = _level_value(
            getattr(item, f"level_nilai_risiko_q{quarter}", None)
        )
    for month in range(1, 13):
        row[_column_name(_column_number("CK") + month - 1)] = getattr(
            item, f"timeline_{month}", 0
        )
    return row


def _quarterly_row(item, sequence: int, first: bool):
    row = {
        "A": "Start pengisian" if first else sequence,
        "B": getattr(item, "asumsi_perhitungan_dampak", None),
    }
    for quarter, column in enumerate(("C", "D", "E", "F"), start=1):
        row[column] = _excel_number(getattr(item, f"nilai_dampak_q{quarter}", None))
    for quarter, column in enumerate(("G", "H", "I", "J"), start=1):
        row[column] = _scale_value(getattr(item, f"skala_dampak_q{quarter}", None))
    for quarter, column in enumerate(("K", "L", "M", "N"), start=1):
        row[column] = _probability_fraction(
            getattr(item, f"nilai_probabilitas_q{quarter}", None)
        )
    for quarter, column in enumerate(("O", "P", "Q", "R"), start=1):
        row[column] = _scale_value(
            getattr(item, f"skala_probabilitas_q{quarter}", None)
        )
    for quarter, column in enumerate(("S", "T", "U", "V"), start=1):
        row[column] = _excel_number(
            getattr(item, f"eksposur_risiko_q{quarter}", None)
        )
    for quarter, column in enumerate(("W", "X", "Y", "Z"), start=1):
        row[column] = getattr(item, f"skala_risiko_q{quarter}", None)
    for quarter, column in enumerate(("AA", "AB", "AC", "AD"), start=1):
        row[column] = _level_value(
            getattr(item, f"level_nilai_risiko_q{quarter}", None)
        )
    row["AE"] = None
    return row


def _write_row(package, sheet_name, row_number, values, style_source_row):
    for column, value in values.items():
        package.set_value(
            sheet_name,
            f"{column}{row_number}",
            value,
            style_source_row=style_source_row,
        )


def _populate_profile(package, items):
    start_row = 7
    existing_end = 35
    target_end = max(existing_end, start_row + len(items) - 1)
    package.clear_range(PROFILE_SHEET, "A", "Y", start_row, target_end, style_source_row=35)
    for index, item in enumerate(items):
        _write_row(
            package,
            PROFILE_SHEET,
            start_row + index,
            _profile_row(item, index + 1, index == 0),
            35,
        )
    package.update_dimension(PROFILE_SHEET, "Y", target_end)


def _populate_treatment(package, items):
    start_row = 7
    existing_end = 322
    target_end = max(existing_end, start_row + len(items) - 1)
    package.clear_range(
        TREATMENT_SHEET, "A", "AC", start_row, target_end, style_source_row=322
    )
    for index, item in enumerate(items):
        _write_row(
            package,
            TREATMENT_SHEET,
            start_row + index,
            _treatment_row(item, index + 1, index == 0),
            322,
        )
    package.update_dimension(TREATMENT_SHEET, "AC", target_end)


def _populate_summary(package, items):
    start_row = 10
    existing_end = 29
    target_end = max(existing_end, start_row + len(items) - 1)
    package.clear_range(SUMMARY_SHEET, "A", "CV", start_row, target_end, style_source_row=29)
    for index, item in enumerate(items):
        _write_row(
            package,
            SUMMARY_SHEET,
            start_row + index,
            _summary_row(item, index + 1, index == 0),
            29,
        )
    package.update_dimension(SUMMARY_SHEET, "CV", target_end)


def _populate_quarterly(package, items):
    start_row = 11
    existing_end = 17
    target_end = max(existing_end, start_row + len(items) - 1)
    package.clear_range(
        QUARTERLY_SHEET, "A", "AE", start_row, target_end, style_source_row=17
    )
    for index, item in enumerate(items):
        _write_row(
            package,
            QUARTERLY_SHEET,
            start_row + index,
            _quarterly_row(item, index + 1, index == 0),
            17,
        )
    package.update_dimension(QUARTERLY_SHEET, "AE", target_end)


def _populate_justification(package, risks):
    package.clear_range(
        JUSTIFICATION_SHEET, "B", "Z", 9, 288, style_source_row=10
    )
    row_number = 9
    for risk in risks:
        package.set_value(
            JUSTIFICATION_SHEET,
            f"B{row_number}",
            getattr(risk, "no_risiko", None),
            style_source_row=9,
        )
        package.set_value(
            JUSTIFICATION_SHEET,
            f"C{row_number}",
            getattr(risk, "peristiwa_risiko", None),
            style_source_row=9,
        )
        package.set_value(
            JUSTIFICATION_SHEET,
            f"C{row_number + 1}",
            getattr(risk, "asumsi_perhitungan_dampak", None)
            or getattr(risk, "deskripsi_dampak", None),
            style_source_row=10,
        )
        period = getattr(risk, "perkiraan_waktu_terpapar_risiko", None)
        if period:
            package.set_value(
                JUSTIFICATION_SHEET,
                f"C{row_number + 2}",
                f"Perkiraan waktu terpapar risiko: {period}",
                style_source_row=10,
            )
        row_number += 3
    package.update_dimension(JUSTIFICATION_SHEET, "Z", max(288, row_number))


def _populate_strategy(package, risks):
    package.clear_range(STRATEGY_SHEET, "A", "H", 9, 28, style_source_row=28)
    seen = set()
    sequence = 0
    for risk in risks:
        target = getattr(risk, "sasaran_pln_batam", None)
        if not target or target in seen:
            continue
        seen.add(target)
        sequence += 1
        row = 8 + sequence
        values = {
            "A": "Start pengisian" if sequence == 1 else None,
            "B": sequence,
            "C": target,
            "D": getattr(risk, "rencana_perlakuan_risiko", None),
            "E": getattr(risk, "output_perlakuan_risiko", None),
            "F": _excel_number(getattr(risk, "eksposur_risiko_q1", None)),
            "G": None,
            "H": "Lanjut",
        }
        _write_row(package, STRATEGY_SHEET, row, values, 28)


def _populate_heatmap(package, risks):
    package.clear_range(HEATMAP_SHEET, "AE", "AR", 6, 19, style_source_row=19)
    for index, risk in enumerate(risks[:14]):
        row = 6 + index
        values = {
            "AE": index + 1,
            "AF": getattr(risk, "peristiwa_risiko", None),
            "AG": _scale_value(getattr(risk, "skala_dampak_q1", None)),
            "AH": _scale_value(getattr(risk, "skala_probabilitas_q1", None)),
            "AI": _level_value(getattr(risk, "level_nilai_risiko_q1", None)),
            "AJ": None,
            "AK": None,
            "AL": None,
            "AM": _scale_value(getattr(risk, "skala_dampak_q4", None)),
            "AN": _scale_value(getattr(risk, "skala_probabilitas_q4", None)),
            "AO": _level_value(getattr(risk, "level_nilai_risiko_q4", None)),
            "AP": None,
            "AQ": None,
            "AR": None,
        }
        _write_row(package, HEATMAP_SHEET, row, values, 19)


def _inherent_row(item, sequence: int, first: bool):
    return {
        "A": "Start Pengisian" if first else None,
        "B": sequence,
        "C": COMPANY_NAME,
        "D": COMPANY_CODE,
        "E": getattr(item, "no_risiko", None),
        "F": getattr(item, "peristiwa_risiko", None),
        "G": getattr(item, "asumsi_perhitungan_dampak", None)
        or getattr(item, "deskripsi_dampak", None),
        "H": _excel_number(_base_impact(item)),
        "I": _base_scale_impact(item),
        "J": None,
        "K": _probability_fraction(_base_probability(item)),
        "L": _base_scale_probability(item),
        "M": None,
        "N": _excel_number(_base_exposure(item)),
        "O": getattr(item, "skala_risiko_q1", None),
        "P": None,
        "Q": _level_value(getattr(item, "level_nilai_risiko_q1", None)),
        "R": None,
    }


def _residual_row(item, sequence: int, first: bool):
    row = {
        "A": "Start Pengisian" if first else None,
        "B": sequence,
        "C": COMPANY_NAME,
        "D": COMPANY_CODE,
        "E": getattr(item, "no_risiko", None),
        "F": getattr(item, "peristiwa_risiko", None),
    }
    groups = [
        ("G", "nilai_dampak_q"),
        ("K", "skala_dampak_q"),
        ("S", "nilai_probabilitas_q"),
        ("W", "skala_probabilitas_q"),
        ("AE", "eksposur_risiko_q"),
        ("AI", "skala_risiko_q"),
        ("AQ", "level_nilai_risiko_q"),
    ]
    for start_column, field_prefix in groups:
        start = _column_number(start_column)
        for quarter in range(1, 5):
            value = getattr(item, f"{field_prefix}{quarter}", None)
            if field_prefix == "nilai_probabilitas_q":
                value = _probability_fraction(value)
            elif field_prefix == "skala_dampak_q" or field_prefix == "skala_probabilitas_q":
                value = _scale_value(value)
            elif field_prefix == "level_nilai_risiko_q":
                value = _level_value(value)
            else:
                value = _excel_number(value)
            row[_column_name(start + quarter - 1)] = value
    return row


def _populate_secondary_risk_sheets(package, risks):
    quantitative = [risk for risk in risks if not _impact_is_qualitative(risk)]
    qualitative = [risk for risk in risks if _impact_is_qualitative(risk)]

    configurations = [
        (INHERENT_QUANT_SHEET, quantitative, 8, 13, _inherent_row),
        (INHERENT_QUAL_SHEET, qualitative, 8, 14, _inherent_row),
        (RESIDUAL_QUANT_SHEET, quantitative, 9, 13, _residual_row),
        (RESIDUAL_QUAL_SHEET, qualitative, 9, 11, _residual_row),
    ]
    for sheet_name, sheet_items, start_row, end_row, row_builder in configurations:
        package.clear_range(sheet_name, "A", "AX" if "Residual" in sheet_name else "R", start_row, end_row, style_source_row=end_row)
        for index, item in enumerate(sheet_items[: end_row - start_row + 1]):
            _write_row(
                package,
                sheet_name,
                start_row + index,
                row_builder(item, index + 1, index == 0),
                end_row,
            )


def build_reassessment_profile_workbook(summary, *, items=None) -> bytes:
    """Build the official Excel working paper for one risk profile."""

    profile_items = list(items) if items is not None else _items_for_summary(summary)
    package = _WorkbookPackage(profile_workbook_template_path())
    risks = _risk_representatives(profile_items)

    _populate_profile(package, profile_items)
    _populate_treatment(package, profile_items)
    _populate_summary(package, profile_items)
    _populate_quarterly(package, profile_items)
    _populate_justification(package, risks)
    _populate_strategy(package, risks)
    _populate_heatmap(package, risks)
    _populate_secondary_risk_sheets(package, risks)

    return package.to_bytes()
