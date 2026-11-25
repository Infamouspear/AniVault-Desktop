import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_hub.database import Database
from anime_hub.metadata import AniListClient, LookupReport, lookup_anilist, search_variants
from anime_hub.scanner import scan


class FakeResponse:
    status = 200
    def __init__(self, payload, headers=None): self.payload=payload; self.headers=headers or {}
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return json.dumps(self.payload).encode()


class MetadataTests(unittest.TestCase):
    def test_known_title_selects_exact_anilist_candidate(self):
        payload={"data":{"Page":{"media":[
            {"id":127230,"title":{"english":"Chainsaw Man","romaji":"Chainsaw Man","native":"チェンソーマン"},
             "synonyms":[],"coverImage":{},"bannerImage":None},
            {"id":171627,"title":{"english":"Chainsaw Man – The Movie: Reze Arc","romaji":"Chainsaw Man Movie: Reze-hen","native":""},
             "synonyms":[],"coverImage":{},"bannerImage":None}
        ]}}}
        with patch("urllib.request.urlopen",return_value=FakeResponse(payload)):
            report=lookup_anilist("Chainsaw Man")
        self.assertEqual(report.http_status,200)
        self.assertEqual(report.selected["id"],127230)
        self.assertEqual(report.confidence,1.0)

    def test_rescan_matches_existing_unresolved_series(self):
        candidate={"id":127230,"title":{"english":"Chainsaw Man","romaji":"Chainsaw Man","native":"チェンソーマン"},
                   "synonyms":[],"coverImage":{},"bannerImage":None}
        def fake_lookup(title,*_args):
            return LookupReport(title,True,200,"",[candidate],candidate,1.0,"")
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); release=base/"Anime"/"Watching"/"Chainsaw Man"
            release.mkdir(parents=True); (release/"Chainsaw Man - 01.mkv").touch()
            db=Database(base/"anime_hub.db")
            try:
                with patch("anime_hub.scanner.lookup_anilist",side_effect=fake_lookup), \
                     patch("anime_hub.scanner.cache_artwork",side_effect=lambda item,_:item):
                    scan(base/"Anime",db,diagnostics_path=base/"scanner.log")
                row=db.anime_list()[0]
                self.assertEqual(row["anilist_id"],127230)
                self.assertIn("Selected AniList ID: 127230",(base/"scanner.log").read_text())
            finally:
                db.connection.close()

    def test_season_two_candidate_beats_exact_season_one_title(self):
        payload={"data":{"Page":{"media":[
            {"id":106479,"title":{"english":"BOFURI: I Don't Want to Get Hurt, so I'll Max Out My Defense.","romaji":"BOFURI","native":""},"synonyms":[],"seasonYear":2020},
            {"id":116867,"title":{"english":"BOFURI: I Don't Want to Get Hurt, so I'll Max Out My Defense. Season 2","romaji":"BOFURI 2nd Season","native":""},"synonyms":[],"seasonYear":2023}
        ]}}}
        client=AniListClient(min_interval=0)
        with patch("urllib.request.urlopen",return_value=FakeResponse(payload)):
            report=client.lookup("BOFURI: I Don't Want to Get Hurt, so I'll Max Out My Defense",2)
        self.assertEqual(report.selected["id"],116867)

    def test_nagatoro_fallback_restores_apostrophe(self):
        empty={"data":{"Page":{"media":[]}}}
        candidate={"id":120697,"title":{"english":"Don't Toy with Me, Miss Nagatoro","romaji":"Ijiranaide, Nagatoro-san","native":""},
                   "synonyms":[],"seasonYear":2021,"episodes":12}
        found={"data":{"Page":{"media":[candidate]}}}
        client=AniListClient(min_interval=0)
        with patch("urllib.request.urlopen",side_effect=[FakeResponse(empty),FakeResponse(found)]):
            report=client.lookup("Dont Toy With Me Miss Nagatoro",1,None,(),12)
        self.assertEqual(report.selected["id"],120697)
        self.assertIn("Don't Toy With Me Miss Nagatoro",report.search_variants)

    def test_nagatoro_season_two_prefers_sequel(self):
        candidates=[
            {"id":120697,"title":{"english":"Don't Toy with Me, Miss Nagatoro","romaji":"Ijiranaide, Nagatoro-san","native":""},"synonyms":[],"seasonYear":2021,"episodes":12},
            {"id":140596,"title":{"english":"Don't Toy with Me, Miss Nagatoro 2nd Attack","romaji":"Ijiranaide, Nagatoro-san 2nd Attack","native":""},"synonyms":["Don't Toy with Me, Miss Nagatoro Season 2"],"seasonYear":2023,"episodes":12}
        ]
        payload={"data":{"Page":{"media":candidates}}}
        client=AniListClient(min_interval=0)
        with patch("urllib.request.urlopen",return_value=FakeResponse(payload)):
            report=client.lookup("Don't Toy with Me, Miss Nagatoro",2,None,(),12)
        self.assertEqual(report.selected["id"],140596)

    def test_beck_clean_title_matches(self):
        candidate={"id":57,"title":{"english":"BECK: Mongolian Chop Squad","romaji":"BECK","native":""},
                   "synonyms":[],"seasonYear":2004,"episodes":26}
        payload={"data":{"Page":{"media":[candidate]}}}
        client=AniListClient(min_interval=0)
        with patch("urllib.request.urlopen",return_value=FakeResponse(payload)):
            report=client.lookup("BECK - Mongolian Chop Squad",1,None,(),26)
        self.assertEqual(report.selected["id"],57)

    def test_all_works_maid_uses_meaningful_word_coverage(self):
        candidate={"id":192800,"title":{"english":"Heroine? Saint? No, I’m an All-Works Maid (And Proud of It)!","romaji":"","native":""},
                   "synonyms":[],"seasonYear":2026,"episodes":12}
        payload={"data":{"Page":{"media":[candidate]}}}
        client=AniListClient(min_interval=0)
        with patch("urllib.request.urlopen",return_value=FakeResponse(payload)):
            report=client.lookup("All Works Maid",1,None,(),5)
        self.assertEqual(report.selected["id"],192800)
        self.assertGreaterEqual(report.confidence,0.84)

    def test_gals_title_retains_low_confidence_manual_candidates(self):
        candidate={"id":999001,"title":{"english":"There Are No Gals Who Are Kind to Otaku!?","romaji":"Otaku ni Yasashii Gal wa Inai!?","native":""},
                   "synonyms":[],"seasonYear":2026,"episodes":12}
        variants=search_variants("Gals Cant Be Kind To Otaku")
        responses=[FakeResponse({"data":{"Page":{"media":[]}}}) for _ in variants]
        responses[-1]=FakeResponse({"data":{"Page":{"media":[candidate]}}})
        client=AniListClient(min_interval=0)
        with patch("urllib.request.urlopen",side_effect=responses):
            report=client.lookup("Gals Cant Be Kind To Otaku",1,None,(),12)
        self.assertTrue(report.candidates)

    def test_generic_fallback_cannot_auto_match_unrelated_fight_title(self):
        candidate={"id":999002,"title":{"english":"Fight Da!! Pyuta","romaji":"Fight Da!! Pyuta","native":""},
                   "synonyms":[],"seasonYear":1968,"episodes":26}
        variants=search_variants("Hanori Still wants to fight")
        self.assertNotIn("to fight",[value.casefold() for value in variants])
        self.assertNotIn("fight",[value.casefold() for value in variants])
        responses=[FakeResponse({"data":{"Page":{"media":[]}}}) for _ in variants]
        responses[-1]=FakeResponse({"data":{"Page":{"media":[candidate]}}})
        client=AniListClient(min_interval=0)
        with patch("urllib.request.urlopen",side_effect=responses):
            report=client.lookup("Hanori Still wants to fight",1)
        self.assertIsNone(report.selected)
        self.assertIn(candidate,report.candidates)
        self.assertLess(report.confidence,0.84)
        self.assertIn("manual match",report.failure_reason)

    def test_generic_shortened_queries_are_rejected(self):
        variants=search_variants("The Last Dungeon Boss")
        lowered={value.casefold() for value in variants}
        self.assertNotIn("boss",lowered)

    def test_real_alternate_title_remains_strong_evidence(self):
        candidate={"id":999003,"title":{"english":"Fight Da!! Pyuta","romaji":"Fight Da!! Pyuta","native":""},
                   "synonyms":["Hanori Still Wants to Fight"],"seasonYear":1968,"episodes":26}
        payload={"data":{"Page":{"media":[candidate]}}}
        client=AniListClient(min_interval=0)
        with patch("urllib.request.urlopen",return_value=FakeResponse(payload)):
            report=client.lookup("Hanori Still wants to fight",1)
        self.assertEqual(report.selected["id"],999003)

    def test_expanded_heavy_knight_title_still_matches(self):
        candidate={"id":999004,"title":{"english":"The Exiled Heavy Knight Knows How to Game the System","romaji":"","native":""},
                   "synonyms":[],"seasonYear":2026,"episodes":12}
        payload={"data":{"Page":{"media":[candidate]}}}
        client=AniListClient(min_interval=0)
        with patch("urllib.request.urlopen",return_value=FakeResponse(payload)):
            report=client.lookup("Heavy Knight",1)
        self.assertEqual(report.selected["id"],999004)

    def test_expanded_last_dungeon_title_still_matches(self):
        candidate={"id":999005,"title":{"english":"Suppose a Kid from the Last Dungeon Boonies Moved to a Starter Town","romaji":"","native":""},
                   "synonyms":[],"seasonYear":2021,"episodes":12}
        payload={"data":{"Page":{"media":[candidate]}}}
        client=AniListClient(min_interval=0)
        with patch("urllib.request.urlopen",return_value=FakeResponse(payload)):
            report=client.lookup("Last Dungeon Boonies",1)
        self.assertEqual(report.selected["id"],999005)

    def test_429_waits_and_retries_successfully(self):
        payload={"data":{"Page":{"media":[
            {"id":127230,"title":{"english":"Chainsaw Man","romaji":"Chainsaw Man","native":""},"synonyms":[],"seasonYear":2022}
        ]}}}
        now=[0.0]
        def fake_time(): return now[0]
        def fake_sleep(seconds): now[0]+=seconds
        error=__import__("urllib.error").error.HTTPError("https://graphql.anilist.co",429,"Too Many Requests",{"Retry-After":"1"},io.BytesIO(b'{"errors":[{"message":"Too Many Requests"}]}'))
        from anime_hub.anilist_transport import Scheduler
        scheduler=Scheduler(clock=fake_time,sleep=fake_sleep,min_interval=0)
        statuses=[]
        client=AniListClient(scheduler=scheduler,min_interval=0,max_retries=2,status_callback=statuses.append,
                             time_func=fake_time,sleep_func=fake_sleep)
        with patch("urllib.request.urlopen",side_effect=[error,FakeResponse(payload)]):
            report=client.lookup("Chainsaw Man",1)
        self.assertEqual(report.selected["id"],127230)
        self.assertEqual(report.retry_count,1)
        self.assertTrue(report.rate_limited)
        self.assertTrue(statuses)

    def test_repeated_429_stays_pending_and_stops_retrying(self):
        now=[0.0]
        def fake_time(): return now[0]
        def fake_sleep(seconds): now[0]+=seconds
        def rate_error():
            return __import__("urllib.error").error.HTTPError(
                "https://graphql.anilist.co",429,"Too Many Requests",{"Retry-After":"1"},
                io.BytesIO(b'{"errors":[{"message":"Too Many Requests"}]}'))
        from anime_hub.anilist_transport import Scheduler
        client=AniListClient(scheduler=Scheduler(clock=fake_time,sleep=fake_sleep,min_interval=0),min_interval=0,max_retries=1,time_func=fake_time,sleep_func=fake_sleep)
        with patch("urllib.request.urlopen",side_effect=[rate_error(),rate_error()]) as request:
            report=client.lookup("Super Cub",1)
        self.assertEqual(request.call_count,2)
        self.assertIsNone(report.selected)
        self.assertTrue(report.rate_limited)
        self.assertIn("Pending / Rate Limited",report.failure_reason)

    def test_rescan_does_not_query_existing_match(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); release=base/"Anime"/"Watching"/"Chainsaw Man"
            release.mkdir(parents=True); (release/"Chainsaw Man - 01.mkv").touch()
            db=Database(base/"anime_hub.db")
            try:
                scan(base/"Anime",db,diagnostics_path=base/"first.log",
                     should_cancel=lambda:True)
                # Build the same row directly, then prove the scanner preserves it.
                anime_id=db.upsert_anime("chainsawman","Chainsaw Man","","Watching",str(release),
                                         release.name,"Chainsaw Man")
                db.set_metadata(anime_id,127230,{"id":127230,"title":{"english":"Chainsaw Man"}})
                with patch("anime_hub.scanner.lookup_anilist") as lookup:
                    scan(base/"Anime",db,diagnostics_path=base/"second.log")
                lookup.assert_not_called()
            finally:
                db.connection.close()

    def test_initial_d_bundle_rescan_has_one_card_and_preserves_match(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); root=base/"Anime"; bundle=root/"[Judas] Initial D (Complete Series + Movies) [BD 1080p]"
            for number,stage in enumerate(("First Stage","Second Stage","Extra Stage"),1):
                child=bundle/f"[Judas] {number:02} - Initial D {stage}"; child.mkdir(parents=True)
                (child/f"Initial D {stage} - 01.mkv").touch()
            db=Database(base/"anime_hub.db")
            try:
                unmatched=LookupReport("Initial D",True,200,"",[],None,0.0,"no candidate")
                with patch("anime_hub.scanner.lookup_anilist",return_value=unmatched): scan(root,db)
                row=db.anime_list()[0]; db.set_metadata(row["id"],185,{"id":185,"title":{"english":"Initial D First Stage"}})
                with patch("anime_hub.scanner.lookup_anilist") as lookup: count=scan(root,db)
                self.assertEqual(count,1); self.assertEqual(len(db.anime_list()),1)
                self.assertEqual(db.anime_list()[0]["anilist_id"],185); lookup.assert_not_called()
            finally:
                db.connection.close()

    def test_full_52_series_metadata_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); root=base/"Anime"
            for number in range(52):
                release=root/"Unwatched"/f"Test Anime {number:02}"
                release.mkdir(parents=True); (release/"Episode - 01.mkv").touch()
            db=Database(base/"anime_hub.db"); counter=iter(range(1000,1052))
            try:
                def fake_lookup(title,*_args):
                    anime_id=next(counter)
                    candidate={"id":anime_id,"title":{"english":title,"romaji":title},
                               "coverImage":{},"bannerImage":None}
                    return LookupReport(title,True,200,"",[candidate],candidate,1.0,"")
                with patch("anime_hub.scanner.lookup_anilist",side_effect=fake_lookup), \
                     patch("anime_hub.scanner.cache_artwork",side_effect=lambda item,_:item):
                    count=scan(root,db,diagnostics_path=base/"scanner.log")
                rows=db.anime_list()
                self.assertEqual(count,52)
                self.assertEqual(len(rows),52)
                self.assertTrue(all(row["anilist_id"] for row in rows))
            finally:
                db.connection.close()


if __name__ == "__main__": unittest.main()
