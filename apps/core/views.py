from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render


def home(request: HttpRequest) -> HttpResponse:
    return render(request, "core/home.html", {"page_title": "EHR Mirror"})


def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True, "service": "sirhosp"})
