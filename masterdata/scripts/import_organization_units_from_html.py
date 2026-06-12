import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path

from django.db import transaction

from masterdata.models import (
    BusinessArea,
    CompanyCode,
    OrganizationUnit,
    PersonnelArea,
    PersonnelSubArea,
)


HTML_FILES = [
    Path("/Users/armeizir/Downloads/Cyber Security Awareness _ Organization Unit.html"),
    Path("/Users/armeizir/Downloads/Cyber Security Awareness _ Organization Unit 2.html"),
]


@dataclass
class OrgUnitRow:
    code: str
    name: str
    business_area: str
    personnel_sub_area: str
    parent_code: str
    active: bool


ROW_RE = re.compile(r'<tr[^>]*role="row"[^>]*>(.*?)</tr>', re.S)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def clean_html(value):
    text = TAG_RE.sub("", value)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize(value):
    text = str(value or "").lower()
    text = text.replace("disrtribusi", "distribusi")
    text = text.replace("distribusi", "distribusi")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_rows():
    rows_by_code = {}
    for path in HTML_FILES:
        if not path.exists():
            raise FileNotFoundError(path)

        html = path.read_text(errors="ignore")
        for row_match in ROW_RE.finditer(html):
            cells = [clean_html(cell) for cell in TD_RE.findall(row_match.group(1))]
            if len(cells) != 6 or not cells[0].isdigit():
                continue

            row = OrgUnitRow(
                code=cells[0],
                name=cells[1],
                business_area="" if cells[2] == "-" else cells[2],
                personnel_sub_area="" if cells[3] == "-" else cells[3],
                parent_code=cells[4],
                active=normalize(cells[5]) == "active",
            )
            rows_by_code[row.code] = row
    return list(rows_by_code.values())


def map_by_description(queryset):
    return {normalize(obj.description): obj for obj in queryset}


def get_business_area(description, company, cache, missing):
    if not description:
        return None
    key = normalize(description)
    obj = cache.get(key)
    if not obj:
        missing.add(description)
    return obj


def get_personnel_sub_area(description, cache, missing):
    if not description:
        return None
    key = normalize(description)
    obj = cache.get(key)
    if not obj:
        missing.add(description)
    return obj


def run():
    rows = parse_rows()
    company = CompanyCode.objects.get(code="1000")
    personnel_area = PersonnelArea.objects.get(code="1000")
    business_area_cache = map_by_description(BusinessArea.objects.filter(company=company))
    personnel_sub_area_cache = map_by_description(
        PersonnelSubArea.objects.filter(personnel_area=personnel_area)
    )

    missing_business_areas = set()
    missing_personnel_sub_areas = set()
    created = 0
    updated = 0

    with transaction.atomic():
        for row in rows:
            business_area = get_business_area(
                row.business_area,
                company,
                business_area_cache,
                missing_business_areas,
            )
            personnel_sub_area = get_personnel_sub_area(
                row.personnel_sub_area,
                personnel_sub_area_cache,
                missing_personnel_sub_areas,
            )
            _, was_created = OrganizationUnit.objects.update_or_create(
                code=row.code,
                defaults={
                    "name": row.name,
                    "company": company,
                    "business_area": business_area,
                    "personnel_area": personnel_area if personnel_sub_area else None,
                    "personnel_sub_area": personnel_sub_area,
                    "aktif": row.active,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        org_units = {obj.code: obj for obj in OrganizationUnit.objects.all()}
        missing_parents = set()
        for row in rows:
            obj = org_units[row.code]
            parent = org_units.get(row.parent_code) if row.parent_code else None
            if row.parent_code and not parent:
                missing_parents.add(row.parent_code)
            obj.parent = parent
            obj.save(update_fields=["parent", "updated_at"])

    print(f"Parsed rows: {len(rows)}")
    print(f"Created: {created}")
    print(f"Updated: {updated}")
    print(f"OrganizationUnit total: {OrganizationUnit.objects.count()}")

    if missing_business_areas:
        print("\nMissing Business Area mapping:")
        for item in sorted(missing_business_areas):
            print(f"- {item}")

    if missing_personnel_sub_areas:
        print("\nMissing Personnel Sub Area mapping:")
        for item in sorted(missing_personnel_sub_areas):
            print(f"- {item}")

    if missing_parents:
        print("\nMissing Parent Org Code:")
        for item in sorted(missing_parents):
            print(f"- {item}")


if __name__ == "__main__":
    run()
