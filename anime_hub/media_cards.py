"""Shared dimensions/slots for standard media cards; organizational covers stay compact."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel,QVBoxLayout,QWidget,QScrollArea,QListWidget

POSTER_WIDTH=172
POSTER_HEIGHT=258
POSTER_CARD_WIDTH=184
POSTER_CARD_HEIGHT=350

def poster_layout(card):
    card.setProperty("posterCard", True)
    card.setFixedSize(POSTER_CARD_WIDTH, POSTER_CARD_HEIGHT)
    layout=QVBoxLayout(card)
    layout.setContentsMargins(6,5,6,5)
    layout.setSpacing(3)
    layout.setAlignment(Qt.AlignTop)
    return layout

CARD_WIDTH=228
CARD_HEIGHT=460
COVER_WIDTH=210
COVER_HEIGHT=258

def media_layout(card):
    card.setFixedSize(CARD_WIDTH,CARD_HEIGHT)
    layout=QVBoxLayout(card);layout.setContentsMargins(9,9,9,9);layout.setSpacing(4);layout.setAlignment(Qt.AlignTop)
    return layout

def text_slot(layout,name,height,word_wrap=False):
    label=QLabel();label.setObjectName(name);label.setFixedHeight(height);label.setWordWrap(word_wrap);label.setMinimumWidth(0)
    layout.addWidget(label);return label

def footer_slot(layout):
    footer=QWidget();footer.setStyleSheet('background:transparent');footer.setFixedHeight(28);layout.addWidget(footer);return footer

class ContainedScrollArea(QScrollArea):
    """Consume wheel input even at boundaries; keyboard focus behaves normally."""
    def wheelEvent(self,event):
        super().wheelEvent(event);event.accept()

class ContainedListWidget(QListWidget):
    def wheelEvent(self,event):
        super().wheelEvent(event);event.accept()


def card_input(card,activate=None):
    """Route decorative child hits to the existing card handler; buttons stay independent."""
    from PySide6.QtCore import QObject,QEvent
    from PySide6.QtWidgets import QLabel,QProgressBar
    card.setCursor(Qt.PointingHandCursor);card.setFocusPolicy(Qt.StrongFocus)
    if activate is not None:
        class Keys(QObject):
            def eventFilter(self,obj,event):
                if event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
                    activate();event.accept();return True
                return False
        guard=Keys(card);card._card_keys=guard;card.installEventFilter(guard)
    for child in [*card.findChildren(QLabel),*card.findChildren(QProgressBar)]:
        child.setAttribute(Qt.WA_TransparentForMouseEvents)
