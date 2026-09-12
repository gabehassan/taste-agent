"""Loads prompts.toml (repo root of server/). Edit that file, not this one."""
import pathlib
import tomllib

_PATH = pathlib.Path(__file__).resolve().parent.parent / "prompts.toml"
P = tomllib.loads(_PATH.read_text())


def prompt(section):
    return P[section]["prompt"].strip()


def field(section, name):
    return P[section]["fields"][name]


def copy(name, **kw):
    return P["copy"][name].strip().format(**kw) if kw else P["copy"][name].strip()


def style(name):
    return P["voice"]["style"][name]


def tool(name):
    return P["chat"]["tools"][name]


def surface_format():
    return P["surface"]["format"].strip()
