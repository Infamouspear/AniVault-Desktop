"""Generate screenshots from an isolated synthetic library; no account or internet needed."""
from pathlib import Path
import tempfile
import sys
from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter, QColor, QLinearGradient
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from anime_hub import app

output=Path(sys.argv[1]).resolve()
output.mkdir(parents=True,exist_ok=True)
q=QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
q.setFont(QFont('Segoe UI',10));q.setStyleSheet(app.STYLE)
titles=['Aster Station','Bluewater Express','City of Lanterns','Dawn Circuit','Evening on Vega','Field Notes from Luna','Glass Harbor','Horizon Letters','Indigo Storm','Juniper Days']
colors=['#b1788c','#7798c8','#bb694c','#38547d','#685386','#537f73','#766273','#ab805d','#4e648a','#338078']
with tempfile.TemporaryDirectory(prefix='anivault-preview-') as temp:
    app.APP_DIR=Path(temp)
    app.Window._request_discover_page=lambda *args,**kwargs:None
    app.Window._request_library_relations=lambda *args,**kwargs:None
    db=app.Database(app.APP_DIR/'anime_hub.db')
    db.set_setting('setup_complete','1');db.set_setting('library_root',temp)
    for i,(title,tint) in enumerate(zip(titles,colors)):
        image=QImage(360,540,QImage.Format_RGB32);paint=QPainter(image);paint.setRenderHint(QPainter.Antialiasing)
        gradient=QLinearGradient(0,0,330,540);gradient.setColorAt(0,QColor(tint).lighter(165));gradient.setColorAt(1,QColor(tint).darker(300));paint.fillRect(image.rect(),gradient)
        paint.setPen(Qt.NoPen);paint.setBrush(QColor(255,235,233,145));paint.drawEllipse(QPointF(180,155),65+i*2,65+i*2);paint.setBrush(QColor(18,21,41,205))
        for j in range(8):paint.drawRect(j*52,310+(j*23+i*32)%90,39,200)
        paint.setPen(QColor('white'));paint.setFont(QFont('Segoe UI',18));paint.drawText(image.rect().adjusted(20,20,-20,-26),Qt.AlignBottom|Qt.AlignHCenter|Qt.TextWordWrap,title.upper())
        paint.end();path=Path(temp)/f'art-{i}.jpg';image.save(str(path))
        aid=db.upsert_anime('preview-'+str(i),title,'','Watching',temp)
        db.set_metadata(aid,1000+i,{'title':{'english':title},'cover_path':str(path),'genres':['Adventure','Drama'],'description':'A synthetic library entry for testing the new artwork layout.'})
        if i<6:db.set_personal_rating('ANIME',aid,4.5+i)
        if i<4:
            from types import SimpleNamespace
            for episode in range(1,5):
                video=Path(temp)/f'{i}-{episode}.mp4'
                video.touch()
                db.upsert_media(aid,SimpleNamespace(path=video,kind='episode',season=1,episode=episode))
            db.set_watched(db.media(aid)[0]['id'],True)
        if i>=4:db.set_manual_status('Planning','normal',anime_id=aid)
    db.connection.commit();db.connection.close()
    if len(sys.argv)>2: db=app.Database(app.APP_DIR/"anime_hub.db"); db.set_setting("compact_navigation","1"); db.connection.close()
    w=app.Window();w.resize(1100 if len(sys.argv)>2 else 1440,900);w.show()
    for name,show in [('Home',w.show_home),('Statistics',w.show_statistics),('Rated-detail',lambda:w.show_detail(1)),('All-Anime',lambda:w.show_library(view_mode='Individual Titles')),('Planning',lambda:w.show_status_list('Planning'))]:
        show();QTest.qWait(220);q.processEvents()
        page=w.stack.currentWidget()
        cards=page.findChildren(app.Card)
        if cards:
            QTest.mouseClick(cards[0],Qt.LeftButton);q.processEvents()
        assert w.grab().save(str(output/(name+'.png'))),name
        if name=='Statistics':
            from PySide6.QtWidgets import QScrollArea
            bar=page.findChild(QScrollArea).verticalScrollBar();bar.setValue(bar.maximum());q.processEvents()
            assert w.grab().save(str(output/'Personal-ratings.png'))
    w.close();q.processEvents()
