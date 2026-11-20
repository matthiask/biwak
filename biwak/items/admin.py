from django.contrib import admin

from biwak.items.models import MessageCategory


@admin.register(MessageCategory)
class MessageCategoryAdmin(admin.ModelAdmin):
    """The categories of the message board: one list for the installation
    (specs/files.md)"""

    list_display = ["name", "emoji", "position"]
    list_editable = ["emoji", "position"]
