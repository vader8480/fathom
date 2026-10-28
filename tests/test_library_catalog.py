"""Rackula catalog tier of ``fathom.library`` (contract section F): loader, precedence, list filters, new template keys."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from _helpers import call, get_app, jbody, requires, temp_data_dir
except ImportError:  # pragma: no cover
    from tests._helpers import call, get_app, jbody, requires, temp_data_dir


def _t(tid, manufacturer, model, kind="other", ru=1, **extra):
    t = {"id": tid, "manufacturer": manufacturer, "model": model, "name": model, "kind": kind, "tags": ["rackula"], "ports": []}
    if ru is not None:
        t["ru"] = ru
    t.update(extra)
    return t


FIXTURE = {
    "source": "https://github.com/RackulaLives/Rackula", "license": "MIT (Rackula) / CC0 (NetBox devicetype-library data)",
    "commit": "9c7af6dd28209a776aebdb92080bcf2916cd29e6", "generated": "2026-10-28", "count": 7,
    "templates": [
        _t("apc-smt1500rmi2uc", "APC", "SMT1500RMI2UC", kind="power", ru=2, full_depth=True, airflow="front-to-rear", weight_kg=26.0,
           rack_category="power", part_number="SMT1500RMI2UC", image_front="apc/apc-smt1500rmi2uc.front.webp",
           image_rear="apc/apc-smt1500rmi2uc.rear.webp", power_w=1000),
        _t("zyxtek-zs-24", "Zyxtek", "ZS-24", kind="switch", ru=1, full_depth=False, rack_category="network",
           ports=[{"group": "Port", "dir": "io", "medium": "network", "connector": "RJ45", "count": 24}]),
        _t("acme-cooler", "Acme", "Cooler", kind="other", ru=None, rack_category="cooling"),
        _t("yamaha-rio-rk", "Yamaha", "Rio3224-D", kind="stage_io", ru=3, rack_category="av-media"),
        _t("generic-pdu-8", "Catalog", "Shadowed PDU", kind="power", ru=1),
        _t("generic-ups", "Catalog", "Shadowed UPS", kind="power", ru=2),
        {"id": "Bad Id", "manufacturer": "X", "model": "Y", "kind": "other", "ports": []},
        _t("zyxtek-zs-24", "Duplicate", "Second copy", kind="switch"),
        _t("bad-airflow", "X", "Y", airflow=5),
    ],
}
CATALOG_IDS = ["apc-smt1500rmi2uc", "zyxtek-zs-24", "acme-cooler", "yamaha-rio-rk", "generic-pdu-8", "generic-ups"]


class _CatalogCase(unittest.TestCase):
    catalog = FIXTURE

    def setUp(self):
        self.library = requires("library")
        if not hasattr(self.library, "CATALOG_PATH"):
            self.skipTest("awaiting library.CATALOG_PATH")
        self._dd = temp_data_dir()
        self.data = self._dd.__enter__()
        self.tmp = Path(tempfile.mkdtemp(prefix="fathom-cat-"))
        self.path = self.tmp / "catalog.json"
        if self.catalog is not None:
            self.path.write_text(self.catalog if isinstance(self.catalog, str) else json.dumps(self.catalog), encoding="utf-8")
        self._patch = mock.patch.object(self.library, "CATALOG_PATH", self.path)
        self._patch.start()
        self.library._catalog_cache["sig"] = None
        self.library.load_library(refresh=True)

    def tearDown(self):
        self._patch.stop()
        self.library._catalog_cache["sig"] = None
        self._dd.__exit__(None, None, None)

    def ids(self, **kw):
        return [s["id"] for s in self.library.list_templates(**kw)]


class Loader(_CatalogCase):
    def test_loads_valid_entries_stamped_catalog(self):
        ts = self.library.catalog_templates()
        self.assertEqual([t["id"] for t in ts], CATALOG_IDS, "file order, invalid and duplicate entries dropped")
        self.assertTrue(all(t["source"] == "catalog" for t in ts))
        self.assertEqual(next(t for t in ts if t["id"] == "zyxtek-zs-24")["manufacturer"], "Zyxtek", "first duplicate wins")

    def test_cached_until_file_changes(self):
        a = self.library.catalog_templates()
        self.assertIs(a[0], self.library.catalog_templates()[0], "second call reuses the cache")
        doc = dict(FIXTURE, templates=[_t("new-one", "N", "One")])
        self.path.write_text(json.dumps(doc) + "\n" * 3, encoding="utf-8")
        self.assertEqual([t["id"] for t in self.library.catalog_templates()], ["new-one"])

    def test_bare_list_accepted(self):
        self.path.write_text(json.dumps([_t("only-one", "O", "One")]), encoding="utf-8")
        self.assertEqual([t["id"] for t in self.library.catalog_templates()], ["only-one"])


class MissingFile(_CatalogCase):
    catalog = None

    def test_missing_file_is_empty_tier(self):
        self.assertEqual(self.library.catalog_templates(), [])
        self.assertEqual(self.library.list_templates(source="catalog"), [])
        self.assertIsNone(self.library.get_template("apc-smt1500rmi2uc"))
        self.assertEqual(self.ids(source="all"), self.ids(), "all = the default tiers when the catalog is empty")


class UnreadableFile(_CatalogCase):
    catalog = "{not json"

    def test_unreadable_file_is_empty_tier(self):
        self.assertEqual(self.library.catalog_templates(), [])
        self.assertIsNone(self.library.get_template("zyxtek-zs-24"))


class DefaultExclusion(_CatalogCase):
    def test_load_library_and_list_templates_exclude_catalog(self):
        lib = self.library.load_library(refresh=True)
        self.assertNotIn("apc-smt1500rmi2uc", lib)
        self.assertFalse(any(t.get("source") == "catalog" for t in lib.values()))
        ids = self.ids()
        self.assertNotIn("apc-smt1500rmi2uc", ids)
        self.assertEqual(self.library.list_templates(q="zyxtek"), [])
        self.assertEqual(self.library.list_templates(q="rio"), self.library.list_templates(q="rio", source=None))
        self.assertNotIn("yamaha-rio-rk", [s["id"] for s in self.library.list_templates(q="rio")])

    def test_default_results_match_an_empty_catalog(self):
        with_cat = (self.library.list_templates(), sorted(self.library.load_library(refresh=True)))
        self.path.unlink()
        self.assertEqual((self.library.list_templates(), sorted(self.library.load_library(refresh=True))), with_cat)

    def test_suggest_never_sees_the_catalog(self):
        suggest = requires("library.suggest")
        doc = {"templates": [_t("proj-rio", "Yamaha", "Rio3224-D", kind="stage_io")]}
        queries = [("Yamaha", "Rio3224-D", ""), ("Zyxtek", "ZS-24", ""), ("APC", "SMT1500RMI2UC", ""), ("", "", "Shadowed UPS")]
        got = [suggest.suggest_models(m, mo, tx, doc=doc, limit=20) for m, mo, tx in queries]
        for out in got:
            self.assertFalse({s.get("template") for s in out} & set(CATALOG_IDS) - {"generic-pdu-8", "generic-ups"})
            self.assertFalse(any(s.get("source") == "catalog" for s in out))
        self.path.unlink()
        self.assertEqual([suggest.suggest_models(m, mo, tx, doc=doc, limit=20) for m, mo, tx in queries], got)


class SourceFilters(_CatalogCase):
    def test_catalog_only(self):
        out = self.library.list_templates(source="catalog")
        self.assertEqual({s["id"] for s in out}, set(CATALOG_IDS))
        self.assertTrue(all(s["source"] == "catalog" for s in out))
        self.assertEqual([s["id"] for s in out], [s["id"] for s in sorted(out, key=lambda s: (s["manufacturer"].lower(), s["model"].lower(), s["id"]))])
        self.assertEqual(self.ids(source="catalog", q="zyxtek"), ["zyxtek-zs-24"])
        self.assertEqual(self.ids(source="catalog", kind="power"), ["apc-smt1500rmi2uc", "generic-pdu-8", "generic-ups"])
        self.assertEqual(self.ids(source="catalog", q="SMT1500RMI2UC"), ["apc-smt1500rmi2uc"], "part numbers are searchable")

    def test_all_tiers_with_shadowing(self):
        out = {s["id"]: s for s in self.library.list_templates(source="all", doc={"templates": [_t("proj-one", "P", "One")]})}
        for tid in ("apc-smt1500rmi2uc", "zyxtek-zs-24", "proj-one"):
            self.assertIn(tid, out)
        self.assertEqual(out["generic-pdu-8"]["source"], "builtin", "built-in shadows the catalog")
        self.assertEqual(out["generic-ups"]["source"], "preset", "preset shadows the catalog")
        self.assertEqual(out["proj-one"]["source"], "project")
        self.assertTrue(set(self.ids()) < set(out), "all = default tiers + catalog")

    def test_other_sources_filter(self):
        doc = {"templates": [_t("proj-one", "P", "One")]}
        self.assertEqual(self.ids(source="project", doc=doc), ["proj-one"])
        presets = self.ids(source="preset")
        self.assertIn("generic-ups", presets)
        self.assertTrue(all(s["source"] == "preset" for s in self.library.list_templates(source="preset")))
        builtin = self.library.list_templates(source="builtin")
        self.assertTrue(builtin and all(s["source"] == "builtin" for s in builtin))
        self.assertEqual(self.ids(source="custom"), [])
        self.assertEqual(self.ids(source=" BUILTIN "), [s["id"] for s in builtin])


class IdsAndRack(_CatalogCase):
    def test_ids_in_given_order_any_tier(self):
        doc = {"templates": [_t("proj-one", "P", "One")]}
        want = ["zyxtek-zs-24", "proj-one", "nope", "generic-ups", "yamaha-rio1608-d", "apc-smt1500rmi2uc"]
        out = self.library.list_templates(ids=want, doc=doc)
        self.assertEqual([s["id"] for s in out], ["zyxtek-zs-24", "proj-one", "generic-ups", "yamaha-rio1608-d", "apc-smt1500rmi2uc"])
        self.assertEqual([s["source"] for s in out], ["catalog", "project", "preset", "builtin", "catalog"])

    def test_ids_comma_string_and_duplicates(self):
        self.assertEqual(self.ids(ids=" apc-smt1500rmi2uc, zyxtek-zs-24,,apc-smt1500rmi2uc "), ["apc-smt1500rmi2uc", "zyxtek-zs-24"])
        self.assertEqual(self.ids(ids=",,"), [])
        self.assertEqual(self.ids(ids="generic-pdu-8"), ["generic-pdu-8"])
        self.assertEqual(self.library.list_templates(ids="generic-pdu-8")[0]["source"], "builtin")

    def test_ids_with_source(self):
        self.assertEqual(self.library.list_templates(ids="generic-pdu-8", source="catalog")[0]["model"], "Shadowed PDU")
        self.assertEqual(self.ids(ids="generic-pdu-8,apc-smt1500rmi2uc", source="builtin"), ["generic-pdu-8"])

    def test_rack_filter(self):
        cat = self.ids(source="catalog", rack=True)
        self.assertNotIn("acme-cooler", cat)
        self.assertIn("apc-smt1500rmi2uc", cat)
        everything = self.library.list_templates(source="all", rack=True)
        self.assertTrue(everything and all(isinstance(s["ru"], int) and s["ru"] >= 1 for s in everything))
        self.assertEqual(self.ids(source="catalog", rack="1"), cat)
        self.assertEqual(self.ids(source="catalog", rack="0"), self.ids(source="catalog"))
        self.assertEqual(self.ids(ids="acme-cooler,zyxtek-zs-24", rack=True), ["zyxtek-zs-24"])

    def test_summary_carries_rack_fields(self):
        s = self.library.list_templates(ids="apc-smt1500rmi2uc")[0]
        for k, v in (("full_depth", True), ("airflow", "front-to-rear"), ("rack_category", "power"), ("weight_kg", 26.0),
                     ("power_w", 1000), ("image_front", "apc/apc-smt1500rmi2uc.front.webp"),
                     ("image_rear", "apc/apc-smt1500rmi2uc.rear.webp"), ("part_number", "SMT1500RMI2UC"), ("ru", 2)):
            self.assertEqual(s[k], v, k)
        self.assertNotIn("airflow", self.library.list_templates(ids="zyxtek-zs-24")[0], "absent keys stay absent")


class Precedence(_CatalogCase):
    def test_get_template_falls_back_to_catalog(self):
        t = self.library.get_template("apc-smt1500rmi2uc")
        self.assertEqual((t["source"], t["ru"], t["weight_kg"], t["power_w"], t["image_front"]),
                         ("catalog", 2, 26.0, 1000, "apc/apc-smt1500rmi2uc.front.webp"))
        t["ru"] = 9
        self.assertEqual(self.library.get_template("apc-smt1500rmi2uc")["ru"], 2, "get_template returns a copy")

    def test_higher_tiers_win(self):
        self.assertEqual(self.library.get_template("generic-pdu-8")["source"], "builtin")
        self.assertEqual(self.library.get_template("generic-ups")["source"], "preset")
        doc = {"templates": [_t("apc-smt1500rmi2uc", "APC", "Project UPS", kind="power", ru=3)]}
        t = self.library.get_template("apc-smt1500rmi2uc", doc)
        self.assertEqual((t["source"], t["model"], t["ru"]), ("project", "Project UPS", 3))
        custom = _t("zyxtek-zs-24", "Zyxtek", "My ZS", kind="switch")
        self.library.save_custom_template(custom)
        self.assertEqual(self.library.get_template("zyxtek-zs-24")["source"], "custom")
        self.assertEqual(self.library.list_templates(ids="zyxtek-zs-24")[0]["source"], "custom")
        self.library.delete_custom_template("zyxtek-zs-24")
        self.assertEqual(self.library.get_template("zyxtek-zs-24")["source"], "catalog")

    def test_device_with_catalog_template_resolves_rack_values(self):
        racks = requires("racks")
        doc = {"racks": [{"id": "rk-a", "name": "A", "units": 12}],
               "devices": [{"id": "ups", "name": "UPS", "kind": "power", "template": "apc-smt1500rmi2uc", "rack": {"id": "rk-a", "u": 1}}]}
        tpl_ru = getattr(racks, "_template_ru", None)
        if tpl_ru is not None:
            self.assertEqual(tpl_ru(doc, "apc-smt1500rmi2uc"), 2)
        totals = getattr(racks, "rack_totals", None)
        if totals is not None:
            got = totals(doc, "rk-a")
            self.assertEqual((got["weight_kg"], got["power_w"]), (26.0, 1000))

    def test_api_get_returns_catalog_template(self):
        app = get_app()
        status, _, body = call(app, "GET", "/api/v2/library/apc-smt1500rmi2uc")
        self.assertEqual(status, 200)
        self.assertEqual(jbody(body)["source"], "catalog")
        status, _, body = call(app, "GET", "/api/v2/library?q=zyxtek")
        self.assertEqual((status, jbody(body)["templates"]), (200, []), "the default library route stays catalog-free")


class NewTemplateKeys(unittest.TestCase):
    def setUp(self):
        self.library = requires("library")

    def base(self, **kw):
        t = _t("x-device", "X", "Device")
        t.update(kw)
        return t

    def test_new_keys_accepted(self):
        for k in ("full_depth", "airflow", "rack_category", "image_front", "image_rear", "part_number"):
            self.assertIn(k, self.library._TEMPLATE_KEYS)
        ok = self.base(full_depth=False, airflow="passive", rack_category="kvm", image_front="_generic/1u.front.webp",
                       image_rear="dell/dell-r650.rear.webp", part_number="R650-XS")
        self.assertEqual(self.library.validate_template(ok), [])
        self.assertEqual(self.library.validate_template(self.base(full_depth=None, airflow=None)), [])

    def test_wrong_types_rejected(self):
        bad = {"full_depth": "yes", "airflow": 1, "rack_category": ["server"], "image_front": 3, "image_rear": {}, "part_number": 12}
        for k, v in bad.items():
            errs = self.library.validate_template(self.base(**{k: v}))
            self.assertTrue(errs and any(k in e for e in errs), (k, errs))
        self.assertTrue(self.library.validate_template(self.base(full_depth=1)), "1 is not a bool")

    def test_image_paths_stay_relative(self):
        for p in ("../secret.webp", "/etc/passwd", "a/../../b.webp", "a//b.webp", "http://x/y.webp", "a\\b.webp", "./a.webp"):
            self.assertTrue(self.library.validate_template(self.base(image_front=p)), p)

    def test_custom_save_keeps_new_keys(self):
        with temp_data_dir():
            t = self.base(full_depth=True, airflow="front-to-rear", rack_category="server", part_number="PN-1",
                          image_front="_generic/1u.front.webp")
            path = self.library.save_custom_template(t)
            saved = json.loads(path.read_text(encoding="utf-8"))
            for k in ("full_depth", "airflow", "rack_category", "part_number", "image_front"):
                self.assertEqual(saved[k], t[k])


class RealCatalog(unittest.TestCase):
    def setUp(self):
        self.library = requires("library")
        path = getattr(self.library, "CATALOG_PATH", None)
        if path is None or not Path(path).is_file():
            self.skipTest("fathom/library/rackula/catalog.json is absent")
        self._dd = temp_data_dir()
        self._dd.__enter__()
        self.library._catalog_cache["sig"] = None

    def tearDown(self):
        self._dd.__exit__(None, None, None)

    def test_real_catalog_tier(self):
        raw = json.loads(Path(self.library.CATALOG_PATH).read_text(encoding="utf-8"))
        ts = self.library.catalog_templates()
        self.assertEqual(len(ts), len(raw["templates"]), "every entry in the shipped catalog loads")
        self.assertTrue(all(t["source"] == "catalog" for t in ts))
        lib = self.library.load_library(refresh=True)
        self.assertFalse(set(t["id"] for t in ts) & set(lib), "catalog ids do not collide with built-in / preset ids")
        self.assertFalse(any(s["source"] == "catalog" for s in self.library.list_templates()))
        sample = ts[:: max(1, len(ts) // 25)]
        for t in sample:
            got = self.library.get_template(t["id"])
            self.assertEqual((got["source"], got.get("ru")), ("catalog", t.get("ru")), t["id"])
        listed = self.library.list_templates(source="catalog", rack=True)
        self.assertEqual(len(listed), sum(1 for t in ts if isinstance(t.get("ru"), int) and t["ru"] >= 1))


if __name__ == "__main__":
    unittest.main()
