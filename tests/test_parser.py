import tempfile
import unittest
from pathlib import Path

from anime_hub.parser import classify_file, is_structural_folder, parse_title
from anime_hub.scanner import discover_series_roots


class ParserTests(unittest.TestCase):
    def test_bilingual_title(self):
        p=parse_title("[Judas] Benriya Saitou-san, Isekai ni Iku (Handyman Saitou in Another World) (Season 01) [BD 1080p][HEVC x265 10bit]")
        self.assertEqual(p.title,"Handyman Saitou in Another World")
        self.assertEqual(p.season,1); self.assertEqual(p.release_group,"Judas")

    def test_sxe_episode(self):
        p=classify_file(Path("[Judas] Handyman Saitou - S01E12.mkv"))
        self.assertEqual((p.kind,p.season,p.episode),("episode",1,12))

    def test_oad_not_episode(self):
        p=classify_file(Path("Bakoun!! OAD - 01.mkv"))
        self.assertEqual(p.kind,"special")

    def test_number_episode(self):
        p=classify_file(Path("[Geonope] Bakoun!! - 02 [DEADBEEF].mkv"))
        self.assertEqual((p.kind,p.episode),("episode",2))

    def test_unbracketed_release_suffix_removed(self):
        p=parse_title("7th Time Loop The Villainess Enjoys a Carefree Life Married to Her Worst Enemy! 1080p BluRay REMUX AVC FLAC 2 0-NANO")
        self.assertEqual(p.title,"7th Time Loop The Villainess Enjoys a Carefree Life Married to Her Worst Enemy!")

    def test_structural_names(self):
        for name in ("01-12","13-24","25-37","Season 1","S02","2019","Episodes","Extras","SPs","Audio CDs"):
            self.assertTrue(is_structural_folder(name),name)

    def test_parent_fallback_never_blank(self):
        self.assertEqual(parse_title("01-12",("A Real Show",)).title,"A Real Show")
        self.assertEqual(parse_title("[]").title,"Unknown Anime")

    def test_batches_aggregate_to_one_series(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); series=root/"Watching"/"Some Anime"
            for batch in ("01-12","13-24","25-37","Extras"):
                folder=series/batch; folder.mkdir(parents=True)
                (folder/("cover.jpg" if batch=="Extras" else f"Some Anime - {batch[:2]}.mkv")).touch()
            found=list(discover_series_roots(root))
            self.assertEqual(len(found),1)
            self.assertEqual(found[0].path,series)

    def test_flat_library_folder_is_one_series(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); series=root/"Flat Anime"
            series.mkdir(); (series/"Flat Anime - 01.mkv").touch()
            found=list(discover_series_roots(root))
            self.assertEqual([(item.category,item.path) for item in found],[("Other",series)])

    def test_initial_d_complete_bundle_identifies_individual_child_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); bundle=root/"[Judas] Initial D (Complete Series + Movies) [BD 1080p]"
            for number,stage in enumerate(("First Stage","Second Stage","Extra Stage","Third Stage"),1):
                child=bundle/f"[Judas] {number:02} - Initial D {stage}"; child.mkdir(parents=True)
                (child/f"Initial D {stage} - 01.mkv").touch()
            child_log=[]; found=list(discover_series_roots(root,child_log))
            self.assertEqual(len(found),4); self.assertTrue(all(item.path.parent==bundle for item in found))
            self.assertTrue(all(not item.child_folders for item in found))
            self.assertTrue(all(str(bundle) in line for line in child_log))

    def test_flat_extras_remain_attached_to_series(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name,extras in (("[Geonope] Bakuon!!",("Audio CDs","Scans","SPs")),
                                ("Handyman Saitou",("Extras",))):
                series=root/name; series.mkdir(); (series/f"{name} - 01.mkv").touch()
                for extra in extras:
                    folder=series/extra; folder.mkdir(); (folder/"bonus.jpg").touch()
            found=list(discover_series_roots(root))
            self.assertEqual({item.path.name for item in found},{"[Geonope] Bakuon!!","Handyman Saitou"})

    def test_plain_episode_inherits_nested_season(self):
        p=classify_file(Path("Some Anime")/"Season 2"/"Some Anime - 03.mkv",1)
        self.assertEqual((p.kind,p.season,p.episode),("episode",2,3))

    def test_initial_d_descriptor_not_title(self):
        p=parse_title("[Judas] Initial D (Complete Series + Movies) [1080p][HEVC]")
        self.assertEqual(p.title,"Initial D")

    def test_trailing_complete_descriptor_removed(self):
        p=parse_title("[Reaktor] BECK - Mongolian Chop Squad Complete [1080p][x265][10-bit]")
        self.assertEqual(p.title,"BECK - Mongolian Chop Squad")

    def test_release_revision_removed(self):
        self.assertEqual(parse_title("BOFURI....S01.v2.1080p.BluRay.x265").title,"BOFURI")

    def test_mf_ghost_batches(self):
        for batch in ("01-12","13-24","25-37"):
            name=f"[SubsPlease] MF Ghost ({batch}) (1080p) [Batch]"
            self.assertEqual(parse_title(name).title,"MF Ghost")

    def test_marriagetoxin_cleanup(self):
        p=parse_title("[Trix] MARRIAGETOXIN S01 [WEBRip 1080p AV1] (Multi Subs)")
        self.assertEqual(p.title,"MARRIAGETOXIN")

    def test_girly_air_force_cleanup(self):
        p=parse_title("Girly Air Force (2019) S01 (BD Remux 1080p H264 8bit FLAC) [Japanese][ENSUB+PLSUB]-pcela")
        self.assertEqual(p.title,"Girly Air Force")

    def test_beck_numbered_episodes_exclude_music_videos(self):
        for number in range(1,27):
            parsed=classify_file(Path("BECK - Mongolian Chop Squad Complete")/f"BECK - E{number:02}.mkv")
            self.assertEqual((parsed.kind,parsed.episode),("episode",number))
        for title in ("Hit in the USA","Moon on the Water","My World Down","Slip Out"):
            self.assertEqual(classify_file(Path(f"{title}.mkv")).kind,"other")

    def test_special_codes_are_not_episodes(self):
        for name in ("Jujutsu Kaisen - S01SP1.mkv","Super Cub - NCOPv1.mkv",
                     "Super Cub - NCOPv2.mkv","Super Cub - NCED.mkv"):
            self.assertEqual(classify_file(Path(name)).kind,"special",name)

    def test_detected_season_and_year_are_preserved(self):
        parsed=parse_title("Girly Air Force (2019) S02 1080p")
        self.assertEqual((parsed.title,parsed.season,parsed.year,parsed.season_explicit),
                         ("Girly Air Force",2,2019,True))


if __name__ == "__main__": unittest.main()
