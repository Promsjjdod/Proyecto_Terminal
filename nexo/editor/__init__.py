"""Motor de edición de archivos con diff, transacciones y reversión."""
from nexo.editor.diff import DiffResult, compute_diff, diff_line_count
from nexo.editor.engine import FileEditor, ChangeSet, EditError, CommitReport

__all__ = [
    "DiffResult",
    "compute_diff",
    "diff_line_count",
    "FileEditor",
    "ChangeSet",
    "EditError",
    "CommitReport",
]
