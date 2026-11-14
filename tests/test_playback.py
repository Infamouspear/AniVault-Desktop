from anime_hub.playback import (PlaybackMonitor, extract_rc_integer,
                                vlc_command, watched_threshold_reached)


class Process:
    def __init__(self): self.ended=False
    def poll(self): return 0 if self.ended else None


class Connection:
    def settimeout(self,value): pass
    def close(self): pass


def test_vlc_command_isolates_launched_episode():
    command=vlc_command("vlc.exe",r"F:\Anime\Show\S01E01.mkv",43123)
    assert "--no-one-instance" in command
    assert "--rc-host=127.0.0.1:43123" in command
    assert command[-1].endswith("S01E01.mkv")


def test_rc_reply_and_threshold():
    assert extract_rc_integer("> get_time\r\n95\r\n>")==95
    assert watched_threshold_reached(90,100)
    assert watched_threshold_reached(95,100)
    assert not watched_threshold_reached(89,100)
    assert not watched_threshold_reached(1,0)


def test_monitor_marks_seek_to_95_percent(monkeypatch):
    process=Process(); monitor=PlaybackMonitor(process,1,"episode.mkv",7,3,poll_seconds=0)
    monkeypatch.setattr("anime_hub.playback.socket.create_connection",lambda *a,**k:Connection())
    monkeypatch.setattr(monitor,"_drain",lambda connection:None)
    monkeypatch.setattr(monitor,"_query",lambda connection,command:100 if command=="get_length" else 95)
    updates=[]; monitor.watched.connect(lambda anime_id,media_id:updates.append((anime_id,media_id)))
    monitor.run()
    assert updates==[(3,7)]


def test_monitor_does_not_mark_20_percent(monkeypatch):
    process=Process(); monitor=PlaybackMonitor(process,1,"episode.mkv",8,4,poll_seconds=0)
    monkeypatch.setattr("anime_hub.playback.socket.create_connection",lambda *a,**k:Connection())
    monkeypatch.setattr(monitor,"_drain",lambda connection:None)
    def query(connection,command):
        if command=="get_length": return 100
        process.ended=True
        return 20
    monkeypatch.setattr(monitor,"_query",query)
    updates=[]; monitor.watched.connect(lambda anime_id,media_id:updates.append((anime_id,media_id)))
    monitor.run()
    assert updates==[]
