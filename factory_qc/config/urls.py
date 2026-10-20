from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Home -> post-login redirect (which sends anonymous users to login).
    path("", RedirectView.as_view(pattern_name="accounts:post_login"), name="home"),
    path("accounts/", include("accounts.urls")),
    path("inspections/", include("inspections.urls")),
    path("approvals/", include("approvals.urls")),
    path("audit/", include("audit.urls")),
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
