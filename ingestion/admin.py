from django.contrib import admin

from .models import IngestionRun, Opinion, OpinionText


@admin.register(Opinion)
class OpinionAdmin(admin.ModelAdmin):
    list_display = ("case_name", "docket", "opinion_type", "court", "filed_date", "first_seen_at")
    list_filter = ("opinion_type", "court")
    search_fields = ("case_name", "docket", "source_url")
    date_hierarchy = "filed_date"


@admin.register(OpinionText)
class OpinionTextAdmin(admin.ModelAdmin):
    list_display = ("opinion", "extracted_at")
    raw_id_fields = ("opinion",)


@admin.register(IngestionRun)
class IngestionRunAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "status",
        "periods",
        "pages_fetched",
        "opinions_found",
        "new_opinions",
        "pdfs_processed",
        "pdf_failures",
        "parser_branch",
    )
    list_filter = ("status",)
    readonly_fields = [f.name for f in IngestionRun._meta.fields]
