from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve
F = {"document_root": settings.FRONTEND_DIR}
urlpatterns = [
    path("api/", include("core.urls")),
    path("", serve, {"path": "index.html", **F}),
    re_path(r"^(?P<path>(css|js|media)/.*)$", serve, F),   # dev-time static serving of the front end
]
