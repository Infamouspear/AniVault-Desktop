from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QVBoxLayout, QWidget

from anime_hub.app import Window
from anime_hub.library_franchises import franchise_relationship


def test_franchise_labels_follow_target_and_reverse_edges():
    assert franchise_relationship([(1, 2, 'SEQUEL'), (2, 1, 'PREQUEL')], 1, 1) == 'First in this group'
    assert franchise_relationship([(2, 1, 'PREQUEL')], 1, 2) == 'Sequel'
    assert franchise_relationship([(1, 2, 'SEQUEL'), (2, 3, 'SEQUEL')], 1, 3) == 'Related'


def test_closed_combo_wheel_scrolls_parent(monkeypatch, tmp_path):
    from anime_hub import app
    monkeypatch.setattr(app, 'APP_DIR', tmp_path)
    window = Window()
    try:
        scroll = QScrollArea(window)
        scroll.resize(200, 100)
        body = QWidget()
        body.setFixedSize(170, 500)
        combo = QComboBox(body)
        combo.addItems(['One', 'Two'])
        scroll.setWidget(body)
        window.show()
        scroll.show()
        QApplication.processEvents()
        wheel = QWheelEvent(QPointF(5, 5), QPointF(combo.mapToGlobal(QPoint(5, 5))),
                            QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        assert scroll.verticalScrollBar().maximum() > 0
        QApplication.sendEvent(combo, wheel)
        assert combo.currentIndex() == 0
        assert scroll.verticalScrollBar().value() > 0
    finally:
        window.close()

