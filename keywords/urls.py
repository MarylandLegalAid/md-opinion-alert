from django.urls import path

from . import views

app_name = "keywords"

urlpatterns = [
    path("", views.manage, name="manage"),
    path("lists/<int:list_id>/subscribe/", views.subscribe, name="subscribe"),
    path("lists/<int:list_id>/unsubscribe/", views.unsubscribe, name="unsubscribe"),
    path("personal/add/", views.add_personal, name="add_personal"),
    path("personal/<int:keyword_id>/delete/", views.delete_personal, name="delete_personal"),
]
