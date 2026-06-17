from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    list_display = (
        "username",
        "display_name",
        "email",
        "is_staff",
        "digest_cadence",
        "last_digest_at",
    )
    fieldsets = UserAdmin.fieldsets + (
        (
            "MD Opinion Alert",
            {"fields": ("entra_oid", "display_name", "digest_cadence", "last_digest_at")},
        ),
    )
    readonly_fields = ("entra_oid", "last_digest_at")
