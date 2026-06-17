from django.contrib import admin
from django.urls import include, path

from alerts import views as alerts_views
from core import views as core_views

urlpatterns = [
    path("", alerts_views.dashboard, name="home"),
    path("preferences/", alerts_views.preferences, name="preferences"),
    path("about/", alerts_views.about, name="about"),
    path("healthz", core_views.healthz, name="healthz"),
    path("keywords/", include("keywords.urls")),
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("admin/", admin.site.urls),
]
