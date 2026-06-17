from django.contrib import admin

from .models import Keyword, KeywordList, Subscription


class KeywordInline(admin.TabularInline):
    model = Keyword
    extra = 1
    fields = ("text", "match_whole_word", "case_insensitive")


@admin.register(KeywordList)
class KeywordListAdmin(admin.ModelAdmin):
    list_display = ("name", "is_shared", "keyword_count", "subscriber_count")
    inlines = [KeywordInline]

    @admin.display(description="Keywords")
    def keyword_count(self, obj):
        return obj.keywords.count()

    @admin.display(description="Subscribers")
    def subscriber_count(self, obj):
        return obj.subscriptions.count()


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("text", "list", "owner", "match_whole_word", "case_insensitive")
    list_filter = ("list", "match_whole_word")
    search_fields = ("text",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "keyword_list", "created_at")
    list_filter = ("keyword_list",)
