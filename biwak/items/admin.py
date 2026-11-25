from biwak import admin
from biwak.items.models import MessageCategory


@admin.register(MessageCategory)
class MessageCategoryAdmin(admin.ReadWriteModelAdmin):
    """The categories of the message board: one list for the installation
    (specs/files.md)"""

    list_display = ["name", "emoji", "position"]
    list_editable = ["emoji", "position"]
