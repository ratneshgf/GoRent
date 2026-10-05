from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve
from django.http import JsonResponse
F = {"document_root": settings.FRONTEND_DIR}
urlpatterns = [
    path("api/health/", lambda request: JsonResponse({"status": "ok"})),
    path("api/", include("core.urls")),
    path("", serve, {"path": "index.html", **F}),
    path("config.js", serve, {"path": "config.js", **F}),
    re_path(r"^(?P<path>(css|js|media)/.*)$", serve, F),   # dev-time static serving of the front end
]
