from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


USD_EXTENSIONS = {".usd", ".usda", ".usdc", ".usdz"}


@dataclass(frozen=True)
class UsdFile:
    path: Path
    library_root: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def file_type(self) -> str:
        return self.path.suffix[1:].upper()

    @property
    def category(self) -> str:
        relative_parts = self.path.relative_to(self.library_root).parts
        return relative_parts[0] if len(relative_parts) > 1 else "Uncategorised"

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(self.library_root).as_posix()

    @property
    def size_mb(self) -> float:
        return self.path.stat().st_size / (1024 * 1024)


class UsdFileModel(QtCore.QAbstractTableModel):
    headers = ("Name", "Category", "Type", "Relative path", "Size")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.files: list[UsdFile] = []

    def set_files(self, files: list[UsdFile]) -> None:
        self.beginResetModel()
        self.files = files
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return len(self.files)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return len(self.headers)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        usd_file = self.files[index.row()]

        if role == QtCore.Qt.UserRole:
            return usd_file

        if role == QtCore.Qt.DecorationRole and index.column() == 0:
            return QtWidgets.QApplication.style().standardIcon(
                QtWidgets.QStyle.SP_FileIcon
            )

        if role != QtCore.Qt.DisplayRole:
            return None

        values = (
            usd_file.name,
            usd_file.category,
            usd_file.file_type,
            usd_file.relative_path,
            f"{usd_file.size_mb:.2f} MB",
        )
        return values[index.column()]


class UsdFilterModel(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_text = ""
        self.category_name = "All"

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        index = self.sourceModel().index(source_row, 0, source_parent)
        usd_file: UsdFile = index.data(QtCore.Qt.UserRole)

        if self.category_name != "All" and usd_file.category != self.category_name:
            return False

        searchable = " ".join(
            (
                usd_file.name,
                usd_file.category,
                usd_file.file_type,
                usd_file.relative_path,
            )
        ).lower()

        return self.search_text.lower() in searchable


class LayerVaultWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("LayerVault — Local USD Browser")
        self.resize(1240, 720)

        self.settings = QtCore.QSettings("LayerVault", "LocalUsdBrowser")

        self.model = UsdFileModel(self)
        self.proxy_model = UsdFilterModel(self)
        self.proxy_model.setSourceModel(self.model)

        self._build_ui()
        self._restore_library_path()

    def _build_ui(self) -> None:
        self.library_path = QtWidgets.QLineEdit()
        self.library_path.setPlaceholderText(
            "Choose the root folder of a local USD library"
        )

        browse_button = QtWidgets.QPushButton("Choose library")
        browse_button.clicked.connect(self.choose_library)

        scan_button = QtWidgets.QPushButton("Scan")
        scan_button.clicked.connect(self.scan_library)

        path_layout = QtWidgets.QHBoxLayout()
        path_layout.addWidget(QtWidgets.QLabel("Library root:"))
        path_layout.addWidget(self.library_path, 1)
        path_layout.addWidget(browse_button)
        path_layout.addWidget(scan_button)

        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Search USD file name, category, or path")
        self.search_box.textChanged.connect(self.apply_filter)

        self.category_filter = QtWidgets.QComboBox()
        self.category_filter.addItem("All")
        self.category_filter.currentTextChanged.connect(self.apply_filter)

        filter_layout = QtWidgets.QHBoxLayout()
        filter_layout.addWidget(self.search_box, 1)
        filter_layout.addWidget(QtWidgets.QLabel("Category:"))
        filter_layout.addWidget(self.category_filter)

        self.table = QtWidgets.QTableView()
        self.table.setModel(self.proxy_model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self.open_selected_file)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)

        self.details = QtWidgets.QTextBrowser()
        self.details.setMinimumWidth(340)

        self.table.selectionModel().selectionChanged.connect(self.update_details)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(self.details)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.addLayout(path_layout)
        layout.addLayout(filter_layout)
        layout.addWidget(splitter)

        self.setCentralWidget(container)
        self.statusBar().showMessage("Choose a library root to start")

    def _restore_library_path(self) -> None:
        previous_path = self.settings.value("library_root", "")
        if previous_path and Path(previous_path).is_dir():
            self.library_path.setText(previous_path)

    def choose_library(self) -> None:
        selected_path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose local USD library root",
            self.library_path.text() or str(Path.home()),
        )

        if selected_path:
            self.library_path.setText(selected_path)
            self.scan_library()

    def scan_library(self) -> None:
        root = Path(self.library_path.text()).expanduser()

        if not root.is_dir():
            self.statusBar().showMessage("Choose an existing local directory")
            return

        usd_files = [
            UsdFile(path=file_path, library_root=root)
            for file_path in root.rglob("*")
            if file_path.is_file() and file_path.suffix.lower() in USD_EXTENSIONS
        ]

        usd_files.sort(key=lambda item: (item.category.lower(), item.name.lower()))
        self.model.set_files(usd_files)

        categories = sorted({usd_file.category for usd_file in usd_files})
        current_category = self.category_filter.currentText()

        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("All")
        self.category_filter.addItems(categories)

        if current_category in categories:
            self.category_filter.setCurrentText(current_category)

        self.category_filter.blockSignals(False)

        self.settings.setValue("library_root", str(root))
        self.apply_filter()

    def apply_filter(self) -> None:
        self.proxy_model.search_text = self.search_box.text().strip()
        self.proxy_model.category_name = self.category_filter.currentText()
        self.proxy_model.invalidateFilter()

        self.statusBar().showMessage(
            f"Showing {self.proxy_model.rowCount()} of "
            f"{self.model.rowCount()} local USD file(s) — files are read-only"
        )

    def selected_usd_file(self) -> UsdFile | None:
        selected_rows = self.table.selectionModel().selectedRows()

        if not selected_rows:
            return None

        return selected_rows[0].data(QtCore.Qt.UserRole)

    def update_details(self) -> None:
        usd_file = self.selected_usd_file()

        if usd_file is None:
            self.details.clear()
            return

        self.details.setHtml(
            f"""
            <h3>{usd_file.name}</h3>
            <p><b>Category</b><br>{usd_file.category}</p>
            <p><b>File type</b><br>{usd_file.file_type}</p>
            <p><b>Size</b><br>{usd_file.size_mb:.2f} MB</p>
            <p><b>Relative path</b><br>
            <code>{usd_file.relative_path}</code></p>
            <p><b>Full path</b><br>
            <code>{usd_file.path}</code></p>
            """
        )

    def open_selected_file(self) -> None:
        usd_file = self.selected_usd_file()

        if usd_file is not None:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(usd_file.path))
            )


def main() -> None:
    application = QtWidgets.QApplication(sys.argv)
    application.setOrganizationName("LayerVault")
    application.setApplicationName("LocalUsdBrowser")

    window = LayerVaultWindow()
    window.show()

    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()