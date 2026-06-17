from django.contrib import admin

from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("user", "cadence", "match_count", "sent_at", "status")
    list_filter = ("cadence", "status")
    readonly_fields = [f.name for f in NotificationLog._meta.fields]
