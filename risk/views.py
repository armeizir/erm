from django.shortcuts import render, get_object_or_404
from .models import KPMRSummary


def dashboard(request):
    return render(request, 'dashboard.html')


def kpmr_review_view(request, summary_id):
    summary = get_object_or_404(KPMRSummary, pk=summary_id)

    items = summary.item.select_related(
        'reassessment_item',
        'reassessment_item__km_item'
    ).order_by('no_item')

    context = {
        'summary': summary,
        'items': items,
    }

    return render(request, 'risk/kpmr_review.html', context)


from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import KPMRItem
import json


@csrf_exempt
def kpmr_update_item(request):
    if request.method == "POST":
        data = json.loads(request.body)

        item_id = data.get("id")
        field = data.get("field")
        value = data.get("value")

        try:
            item = KPMRItem.objects.get(id=item_id)

            if field == "perlakuan_risiko":
                item.perlakuan_risiko = value
            elif field == "bukti":
                item.bukti = value
            elif field == "nilai_kpmr":
                item.nilai_kpmr = int(value) if value else None
            elif field == "status_kpmr":
                item.status_kpmr = value
            elif field == "catatan":
                item.catatan = value

            item.save()

            return JsonResponse({"status": "success"})

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})

    return JsonResponse({"status": "invalid"})