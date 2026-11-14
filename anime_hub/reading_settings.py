"""Global reading preferences; book progress stays in ReaderStore."""
from PySide6.QtWidgets import QWidget,QFormLayout,QComboBox,QCheckBox,QLabel

def save_reading_preferences(db,values):
    changed=[('reader_'+key,str(value)) for key,value in values if db.setting('reader_'+key)!=str(value)]
    if changed:
        with db.connection:
            db.connection.executemany('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',changed)

class ReadingSettings(QWidget):
    def __init__(self,db,parent=None):
        super().__init__(parent);self.setObjectName('readingSettings');self.db=db
        layout=QFormLayout(self);layout.setContentsMargins(0,0,0,0)
        self.direction=QComboBox();self.direction.addItem('Right-to-Left (Manga)','RTL');self.direction.addItem('Left-to-Right','LTR')
        self.direction.setCurrentIndex(max(0,self.direction.findData(db.setting('reader_direction','RTL'))));layout.addRow('Reading direction',self.direction)
        self.spread=QComboBox();self.spread.addItems(['Single Page','Spread / Double Page']);self.spread.setCurrentIndex(int(db.setting('reader_spread','0')=='1'));layout.addRow('Page layout',self.spread)
        self.cover=QCheckBox('First page as a single cover');self.cover.setChecked(db.setting('reader_cover','1')=='1');layout.addRow(self.cover)
        self.toolbar=QCheckBox('Show persistent reader toolbar');self.toolbar.setChecked(db.setting('reader_toolbar','1')=='1');layout.addRow(self.toolbar)
        self.fit=QComboBox();self.fit.addItems(['Fit Page','Fit Width','100%','Manual']);self.fit.setCurrentText(db.setting('reader_fit','Fit Page'));layout.addRow('Fit mode',self.fit)
        hint=QLabel('Click page edges to turn · Wheel to zoom · Drag to pan\nT: toolbar · P/W: fit page/width · F: fullscreen · B: bookmark');hint.setObjectName('muted');hint.setWordWrap(True);layout.addRow(hint)
    def save(self):
        save_reading_preferences(self.db,[('direction',self.direction.currentData()),('spread',int(self.spread.currentIndex()==1)),('cover',int(self.cover.isChecked())),('toolbar',int(self.toolbar.isChecked())),('fit',self.fit.currentText())])
