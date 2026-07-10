"""Tests for text VDF parsing: libraryfolders, appmanifest, loginusers, registry."""

from steamdeck_bridge.detect.registry import running_appid_from_registry
from steamdeck_bridge.steam.library import (
    parse_appmanifest,
    parse_libraryfolders,
    parse_loginusers,
)

LIBRARYFOLDERS = """
"libraryfolders"
{
    "0"
    {
        "path"      "/home/deck/.local/share/Steam"
        "label"     ""
    }
    "1"
    {
        "path"      "/run/media/mmcblk0p1"
        "label"     "SD Card"
    }
    "contentstatsid"    "12345"
}
"""

APPMANIFEST = """
"AppState"
{
    "appid"      "632470"
    "name"       "Disco Elysium"
    "installdir" "Disco Elysium"
    "StateFlags" "4"
}
"""

LOGINUSERS = """
"users"
{
    "76561198000000001"
    {
        "AccountName"  "olduser"
        "PersonaName"  "Old User"
        "MostRecent"   "0"
    }
    "76561198000000002"
    {
        "AccountName"  "brett"
        "PersonaName"  "Brett"
        "MostRecent"   "1"
    }
}
"""


def test_parse_libraryfolders():
    paths = parse_libraryfolders(LIBRARYFOLDERS)
    assert paths == ["/home/deck/.local/share/Steam", "/run/media/mmcblk0p1"]


def test_parse_appmanifest():
    app = parse_appmanifest(APPMANIFEST, "/lib")
    assert app is not None
    assert app.appid == 632470
    assert app.name == "Disco Elysium"
    assert app.library_path == "/lib"


def test_parse_appmanifest_rejects_garbage():
    assert parse_appmanifest('"NotAppState" {}') is None


def test_parse_loginusers_most_recent():
    assert parse_loginusers(LOGINUSERS) == "Brett"


def test_registry_running_appid():
    text = '"Registry" { "HKCU" { "Software" { "Valve" { "Steam" {\n'
    text += '"RunningAppID"\t\t"632470"\n} } } } }'
    assert running_appid_from_registry(text) == 632470


def test_registry_zero_is_untrusted():
    assert running_appid_from_registry('"RunningAppID"  "0"') is None
    assert running_appid_from_registry("no key here") is None
