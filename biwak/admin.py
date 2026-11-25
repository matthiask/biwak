# Copyright (c) 2026, Feinheit AG and individual contributors (Governance's
# governance/admin.py, see NOTICE)
"""The admin is read only unless a model admin opts in

Changes go through the operations, which check permissions, record events
and send mails; the admin is for looking things up. Model admins which
need editing use ``ReadWriteModelAdmin`` (or allow single permissions
themselves). Like Workbench's ``workbench.tools.admin``.
"""

from django.contrib.admin import (  # noqa: F401
    ModelAdmin as ReadWriteModelAdmin,
    SimpleListFilter,
    StackedInline as ReadWriteStackedInline,
    TabularInline as ReadWriteTabularInline,
    action,
    display,
    register,
    site,
)


class ReadOnlyMixin:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ModelAdmin(ReadOnlyMixin, ReadWriteModelAdmin):
    pass


class TabularInline(ReadOnlyMixin, ReadWriteTabularInline):
    pass


class StackedInline(ReadOnlyMixin, ReadWriteStackedInline):
    pass
