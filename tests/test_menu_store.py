"""menu_store: atomic writes, locked reads, slug stability. (review findings 6, 12)"""
import json
import os
import threading
import time


def test_save_load_round_trip(store):
    store.save_menu("Fortune", ["a", "b"])
    assert store.load_menu("fortune") == ("Fortune", ["a", "b"])


def test_is_today_only_for_todays_menu(store):
    store.save_menu("Fortune", ["a"])
    assert store.is_today("fortune") is True
    assert store.is_today("never-seen") is False


def test_stale_menu_is_not_today(store):
    store.save_menu("Fortune", ["a"])
    data = json.loads(store._FILE.read_text(encoding="utf-8"))
    data["fortune"]["date"] = "2020-01-01"
    store._FILE.write_text(json.dumps(data), encoding="utf-8")
    assert store.is_today("fortune") is False


def test_concurrent_reads_never_see_a_partial_write(store):
    """Finding 6: the scheduler thread writes while webhook threads read."""
    store.save_menu("Fortune", ["seed"])
    errors: list[str] = []
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            store.save_menu("Fortune", ["item %d" % i] * 60)
            i += 1

    def reader():
        while not stop.is_set():
            try:
                store.is_today("fortune")
                store.load_menu("fortune")
            except Exception as exc:  # a torn read would surface here
                errors.append(repr(exc))

    threads = [threading.Thread(target=writer)] + [
        threading.Thread(target=reader) for _ in range(2)
    ]
    for t in threads:
        t.start()
    time.sleep(0.8)
    stop.set()
    for t in threads:
        t.join()

    assert errors == []
    assert isinstance(json.loads(store._FILE.read_text(encoding="utf-8")), dict)


def test_write_leaves_no_temp_files(store):
    store.save_menu("Fortune", ["a"])
    leftovers = [f for f in os.listdir(store._FILE.parent) if f.endswith(".tmp")]
    assert leftovers == []


def test_corrupt_store_degrades_instead_of_raising(store):
    """A damaged file must not 500 the webhook."""
    store._FILE.write_text("{ not json at all", encoding="utf-8")
    assert store.is_today("fortune") is False
    assert store.load_menu("fortune") == ("", [])


def test_slug_is_ascii_key_for_latin_names(store):
    assert store.slug("Da Fortune Kitchen") == "da_fortune_kitchen"
    assert store.slug("Tamar Myay - တမာမြေ") == "tamar_myay"


def test_slug_falls_back_for_pure_burmese_names(store):
    """Finding 12: stripping non-ASCII used to leave "" for every such name."""
    a = store.slug("တမာမြေ")
    b = store.slug("ရွှေမန္တလေး")
    assert a and b
    assert a != b, "distinct Burmese names must not collide"
    assert a == store.slug("တမာမြေ"), "slug must be stable across calls"


def test_burmese_named_restaurants_do_not_overwrite_each_other(store):
    store.save_menu("တမာမြေ", ["one"])
    store.save_menu("ရွှေမန္တလေး", ["two"])
    assert store.load_menu(store.slug("တမာမြေ"))[1] == ["one"]
    assert store.load_menu(store.slug("ရွှေမန္တလေး"))[1] == ["two"]
