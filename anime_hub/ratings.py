"""Local half-point ratings."""
from decimal import Decimal, InvalidOperation

def rating_units(value):
    if value is None:
        return None
    try:
        score=Decimal(str(value))
        if score.is_finite() and 1<=score<=10 and score*2==int(score*2):
            return int(score*2)
    except (InvalidOperation, TypeError, ValueError):
        pass
    raise ValueError("Use a rating from 1.0 to 10.0 in half-point increments.")

def rating_control(window, scope, kind, identifier):
    from PySide6.QtWidgets import QComboBox,QHBoxLayout,QLabel,QWidget
    from PySide6.QtCore import QObject,Slot
    row=QWidget();layout=QHBoxLayout(row);layout.setContentsMargins(0,0,0,0)
    title=QLabel("Personal rating");combo=QComboBox();combo.setAccessibleName(title.text());title.setBuddy(combo)
    layout.addWidget(title);layout.addWidget(combo);layout.addStretch()
    combo.addItem("Unrated",None)
    for units in range(2,21):combo.addItem(f"{units/2:.1f}",units)
    class Listener(QObject):
        @Slot()
        def refresh(self):
            if not window._closing and window._organization_allowed(scope):
                previous=combo.blockSignals(True)
                combo.setCurrentIndex(combo.findData(window.db.personal_rating(kind,identifier)))
                combo.blockSignals(previous)
    listener=Listener(row);window.personal_rating_changed.connect(listener.refresh);listener.refresh()
    def save():
        if not window._closing and window._organization_allowed(scope):
            units=combo.currentData()
            window.db.set_personal_rating(kind,identifier,units/2 if units else None)
            window.personal_rating_changed.emit()
    combo.currentIndexChanged.connect(save)
    return row
