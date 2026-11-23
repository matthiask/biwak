"""The editor's Markdown in Python (specs/rich-editor.md): the same
document (``tree``) as the browser's editor (``frontend/editor/``), parsed
(``parse``) and serialized (``serialize``) byte for byte like it, kept as
written where nothing changed (``preserve``), and read from and written to
the live docs' Yjs documents (``ydoc``, ``diff``). Also the Markdown and
HTML handling around it: task lists (``checklists``), pasted and imported
HTML (``htmlmarkdown``, ``paste``) and plain text (``text``)."""
