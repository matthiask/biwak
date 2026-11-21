from django.urls import path

from biwak.files import board, docs, library, views


urlpatterns = [
    path(
        "projects/<int:pk>/attachments/",
        views.attachment_upload,
        name="attachment_upload",
    ),
    path("attachments/<str:key>/<path:name>", views.attachment, name="attachment"),
    # The message board
    path(
        "projects/<int:pk>/messages/", board.project_messages, name="project_messages"
    ),
    path("projects/<int:pk>/messages/new/", board.message_new, name="message_new"),
    path("messages/<int:pk>/", board.message, name="message"),
    path("messages/<int:pk>/edit/", board.message_edit, name="message_edit"),
    path("messages/<int:pk>/pin/", board.message_pin, name="message_pin"),
    # Folders
    path("projects/<int:pk>/files/", library.project_files, name="project_files"),
    path("folders/<int:pk>/", library.folder, name="folder"),
    path("projects/<int:pk>/folders/new/", library.folder_new, name="folder_new"),
    path("folders/<int:pk>/rename/", library.folder_rename, name="folder_rename"),
    path("folders/<int:pk>/order/", library.folder_order, name="folder_order"),
    path(
        "projects/<int:pk>/files/order/",
        library.project_files_order,
        name="project_files_order",
    ),
    path("items/<int:pk>/move/", library.item_move, name="item_move"),
    path("projects/<int:pk>/files/move/", library.files_move, name="files_move"),
    path("projects/<int:pk>/files/trash/", library.files_trash, name="files_trash"),
    # Docs
    path("projects/<int:pk>/docs/new/", docs.doc_new, name="doc_new"),
    path("docs/<int:pk>/", docs.doc, name="doc"),
    path("docs/<int:pk>/edit/", docs.doc_edit, name="doc_edit"),
    path("docs/<int:pk>/read-only/", docs.doc_read_only, name="doc_read_only"),
    path("docs/<int:pk>/versions/", docs.doc_versions, name="doc_versions"),
    path(
        "docs/<int:pk>/versions/<int:version_pk>/",
        docs.doc_version,
        name="doc_version",
    ),
    path(
        "docs/<int:pk>/versions/<int:version_pk>/restore/",
        docs.doc_version_restore,
        name="doc_version_restore",
    ),
    # Files
    path("projects/<int:pk>/files/new/", library.file_new, name="file_new"),
    path("projects/<int:pk>/files/upload/", library.file_upload, name="file_upload"),
    path("files/<int:pk>/", library.file, name="file"),
    path("files/<int:pk>/edit/", library.file_edit, name="file_edit"),
    path("files/<int:pk>/replace/", library.file_replace, name="file_replace"),
    path("files/<int:pk>/download/", library.file_download, name="file_download"),
    path("files/<int:pk>/preview/", library.file_preview, name="file_preview"),
    path(
        "files/<int:pk>/versions/<int:version_pk>/download/",
        library.file_download,
        name="file_version_download",
    ),
    path(
        "files/<int:pk>/versions/<int:version_pk>/preview/",
        library.file_preview,
        name="file_version_preview",
    ),
]
