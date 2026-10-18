"""Configuration: a TOML file under the user's config directory, tolerant to a fault.

Precedence, lowest to highest: built-in defaults, the file, command-line flags
(:func:`apply_overrides`). Flags never write back to the file.

Loading never raises. A missing file is the defaults. A file that is not valid
TOML is the defaults plus a warning. A key of the wrong type or out of range is
dropped with a warning and the default stands. Unknown keys are ignored without
comment, so a newer file still opens in an older build. The file is created
only by :func:`save_config`, never by loading.

Favorites are stored as ESPN team ids (``favorites.team_ids``), which are
stable across weeks and the only thing a card can hand back reliably. The
abbreviation list ``favorites.abbreviations`` is for hand-editing: it is
matched against each team's abbreviation as games arrive.

.. code-block:: toml

    [poll]
    live = 20            # seconds between polls while someone is at the computer
    idle = 120           # seconds between polls once they have walked away
    backoff_max = 120
    away_after = 300     # seconds without keyboard or mouse input before "away"

    [view]
    glyph_set = "nerd"   # ascii, unicode, emoji, nerd
    week = 7             # 1-15, 16 for Bowls, 17 for the Playoff; omit for ESPN's current week
    group = "fbs"        # fbs or fcs
    layout = "grid"      # grid or list

    [favorites]
    team_ids = ["251"]
    abbreviations = ["TEX"]

    [alerts]
    enabled = true       # pulse a card on a score or a lead change

    [updates]
    check = true         # look for a newer release at startup
    auto = true          # standalone binaries download a new minor or patch version and install it when
                         # you quit, if it is still on then and cfbtui exited normally (the settings screen
                         # toggles it); a new major version only shows a link
"""
from __future__ import annotations

import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import tomli_w
from platformdirs import user_config_dir

from cfbtui.espn.client import GROUP_FBS, GROUP_FCS
from cfbtui.espn.periods import MAX_WEEK, MIN_WEEK
from cfbtui.poll import PollIntervals
from cfbtui.ui.glyphs import DEFAULT_SET, GLYPH_SET_NAMES

GROUPS: dict[str, int] = {"fbs": GROUP_FBS, "fcs": GROUP_FCS}
LAYOUTS = ("grid", "list")


@dataclass(frozen=True, slots=True)
class ViewConfig:
    glyph_set: str = DEFAULT_SET
    week: int | None = None  # None means ESPN's current week
    group: str = "fbs"
    layout: str = "grid"  # "grid" cards or "list" one line per game

    @property
    def group_id(self) -> int:
        return GROUPS[self.group]


@dataclass(frozen=True, slots=True)
class FavoritesConfig:
    team_ids: tuple[str, ...] = ()
    abbreviations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdatesConfig:
    check: bool = True
    auto: bool = True


@dataclass(frozen=True, slots=True)
class AlertsConfig:
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class Config:
    poll: PollIntervals = field(default_factory=PollIntervals)
    view: ViewConfig = field(default_factory=ViewConfig)
    favorites: FavoritesConfig = field(default_factory=FavoritesConfig)
    updates: UpdatesConfig = field(default_factory=UpdatesConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)


@dataclass(frozen=True, slots=True)
class LoadResult:
    config: Config
    warnings: tuple[str, ...] = ()
    path: Path | None = None


def default_path() -> Path:
    return Path(user_config_dir("cfbtui", appauthor=False)) / "config.toml"


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _section(data: dict, name: str, warnings: list[str]) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        warnings.append(f"[{name}] should be a table; ignored")
        return {}
    return value


def _strings(value: Any, where: str, warnings: list[str]) -> tuple[str, ...]:
    if not isinstance(value, list):
        warnings.append(f"{where} should be a list of strings; ignored")
        return ()
    items = [v for v in value if isinstance(v, str | int) and not isinstance(v, bool)]
    good = tuple(s for s in (str(v).strip() for v in items) if s)
    if len(good) != len(value):
        warnings.append(f"{where} had entries that are not strings; skipped")
    return good


MIN_LIVE = 5.0
MAX_INTERVAL = 3600.0


def parse_config(data: dict) -> tuple[Config, list[str]]:
    """Build a :class:`Config` from parsed TOML, collecting a warning per value it had to drop."""
    warnings: list[str] = []

    poll = PollIntervals()
    section = _section(data, "poll", warnings)
    values: dict[str, float] = {}
    for name in ("live", "idle", "backoff_max", "away_after"):
        if name not in section:
            continue
        v = section[name]
        if _is_number(v) and v > 0:
            clamped = min(max(float(v), MIN_LIVE if name == "live" else 1.0), MAX_INTERVAL)
            if clamped != float(v):
                warnings.append(f"poll.{name} was out of range; using {clamped:g}")
            values[name] = clamped
        else:
            warnings.append(f"poll.{name} should be a positive number of seconds; using {getattr(poll, name):g}")
    poll = replace(poll, **values)

    view = ViewConfig()
    section = _section(data, "view", warnings)
    if "glyph_set" in section:
        v = section["glyph_set"]
        if isinstance(v, str) and v.strip().lower() in GLYPH_SET_NAMES:
            view = replace(view, glyph_set=v.strip().lower())
        else:
            warnings.append(f"view.glyph_set should be one of {', '.join(GLYPH_SET_NAMES)}; using {view.glyph_set}")
    if "week" in section:
        v = section["week"]
        if isinstance(v, int) and not isinstance(v, bool) and MIN_WEEK <= v <= MAX_WEEK:
            view = replace(view, week=v)
        else:
            warnings.append(f"view.week should be a whole number from {MIN_WEEK} to {MAX_WEEK}; using the current week")
    if "group" in section:
        v = section["group"]
        if isinstance(v, str) and v.strip().lower() in GROUPS:
            view = replace(view, group=v.strip().lower())
        else:
            warnings.append('view.group should be "fbs" or "fcs"; using fbs')

    if "layout" in section:
        v = section["layout"]
        if isinstance(v, str) and v.strip().lower() in LAYOUTS:
            view = replace(view, layout=v.strip().lower())
        else:
            warnings.append('view.layout should be "grid" or "list"; using grid')

    section = _section(data, "favorites", warnings)
    ids = _strings(section["team_ids"], "favorites.team_ids", warnings) if "team_ids" in section else ()
    abbrs = ()
    if "abbreviations" in section:
        abbrs = _strings(section["abbreviations"], "favorites.abbreviations", warnings)
    favorites = FavoritesConfig(tuple(dict.fromkeys(ids)), tuple(dict.fromkeys(a.upper() for a in abbrs)))

    updates = UpdatesConfig()
    section = _section(data, "updates", warnings)
    for name in ("check", "auto"):
        if name in section:
            v = section[name]
            if isinstance(v, bool):
                updates = replace(updates, **{name: v})
            else:
                warnings.append(f"updates.{name} should be true or false; using true")

    alerts = AlertsConfig()
    section = _section(data, "alerts", warnings)
    if "enabled" in section:
        v = section["enabled"]
        if isinstance(v, bool):
            alerts = AlertsConfig(enabled=v)
        else:
            warnings.append("alerts.enabled should be true or false; using true")

    return Config(poll, view, favorites, updates, alerts), warnings


def load_config(path: Path | None = None) -> LoadResult:
    """Read the config file. Never raises; problems come back as ``warnings``."""
    path = path if path is not None else default_path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return LoadResult(Config(), (), path)
    except OSError as exc:
        return LoadResult(Config(), (f"could not read {path}: {exc.strerror or exc}; using defaults",), path)
    try:
        data = tomllib.loads(raw.decode("utf-8-sig"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return LoadResult(Config(), (f"{path} is not valid TOML ({exc}); using defaults",), path)
    config, warnings = parse_config(data)
    return LoadResult(config, tuple(warnings), path)


def _num(x: float) -> int | float:
    return int(x) if float(x).is_integer() else x


def to_toml_data(config: Config) -> dict:
    view: dict[str, Any] = {
        "glyph_set": config.view.glyph_set,
        "group": config.view.group,
        "layout": config.view.layout,
    }
    if config.view.week is not None:
        view["week"] = config.view.week
    return {
        "poll": {
            "live": _num(config.poll.live),
            "idle": _num(config.poll.idle),
            "backoff_max": _num(config.poll.backoff_max),
            "away_after": _num(config.poll.away_after),
        },
        "view": view,
        "favorites": {
            "team_ids": list(config.favorites.team_ids),
            "abbreviations": list(config.favorites.abbreviations),
        },
        "updates": {"check": config.updates.check, "auto": config.updates.auto},
        "alerts": {"enabled": config.alerts.enabled},
    }


def save_config(config: Config, path: Path | None = None) -> Path:
    """Write the config, creating the directory and file on first save. Raises ``OSError`` on failure."""
    path = path if path is not None else default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(tomli_w.dumps(to_toml_data(config)), encoding="utf-8")
    tmp.replace(path)  # a crash mid-write must not leave a half file behind
    return path


def apply_overrides(
    config: Config,
    *,
    week: int | None = None,
    group: str | None = None,
    glyph_set: str | None = None,
    layout: str | None = None,
    check_updates: bool | None = None,
) -> Config:
    """Command-line flags on top of the file, for this run only."""
    view = config.view
    if week is not None:
        view = replace(view, week=week)
    if group is not None:
        view = replace(view, group=group)
    if glyph_set is not None:
        view = replace(view, glyph_set=glyph_set)
    if layout is not None:
        view = replace(view, layout=layout)
    updates = config.updates
    if check_updates is False:
        updates = replace(updates, check=False)
    return replace(config, view=view, updates=updates)


def favorite_ids(config: Config, teams: Iterable[tuple[str, str]] = ()) -> frozenset[str]:
    """Ids of the favorite teams. ``teams`` is (id, abbreviation) pairs, for abbreviation matches."""
    ids = set(config.favorites.team_ids)
    wanted = set(config.favorites.abbreviations)
    if wanted:
        ids.update(team_id for team_id, abbr in teams if abbr.upper() in wanted)
    return frozenset(ids)
