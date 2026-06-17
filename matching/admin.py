from django.contrib import admin

from .models import Match


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("keyword", "opinion", "user", "count", "created_at")
    list_filter = ("keyword__list",)
    search_fields = ("keyword__text", "opinion__case_name")
    raw_id_fields = ("opinion", "user", "keyword")
