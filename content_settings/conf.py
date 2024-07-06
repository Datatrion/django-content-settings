"""
the module collects all settings from all apps and makes them available as `content_settings` object.
"""

from importlib import import_module
from functools import partial
from typing import Any, Callable, Optional, List, Set, Dict, Tuple

from django.apps import apps

from .types.basic import BaseSetting
from .caching import (
    get_value,
    get_type_by_name,
    get_all_names,
    get_checksum_from_local,
    get_checksum_from_user_local,
)
from .settings import USER_DEFINED_TYPES, TAGS
from .store import add_app_name

USER_DEFINED_TYPES_INSTANCE = {}
USER_DEFINED_TYPES_INITIAL = {}
USER_DEFINED_TYPES_NAME = {}
ALL = {}
PREFIXSES = {}


def import_object(path: str) -> Any:
    """
    getting an object from the module by the path. `full.path.to.Object` -> `Object`
    """
    parts = path.split(".")
    module = import_module(".".join(parts[:-1]))
    return getattr(module, parts[-1])


if USER_DEFINED_TYPES:
    for slug, imp_line, name in USER_DEFINED_TYPES:
        type_class = import_object(imp_line)
        USER_DEFINED_TYPES_INSTANCE[slug] = partial(
            type_class, user_defined_slug=slug, version=type_class.version
        )
        USER_DEFINED_TYPES_INITIAL[slug] = USER_DEFINED_TYPES_INSTANCE[slug]()
        USER_DEFINED_TYPES_NAME[slug] = name


CALL_TAGS = None


def get_call_tags() -> List[Callable]:
    """
    returns list of functions from `CONTENT_SETTINGS_TAGS` setting that are used to generate tags for settings.
    the result is cached in `CALL_TAGS` variable.
    """
    global CALL_TAGS

    if CALL_TAGS is not None:
        return CALL_TAGS

    CALL_TAGS = []
    for func_tag in TAGS:
        if isinstance(func_tag, str):
            func_tag = import_object(func_tag)
        elif callable(func_tag):
            pass
        else:
            raise AssertionError(f"func_tag: {func_tag} should be str or callable")
        CALL_TAGS.append(func_tag)
    return CALL_TAGS


def gen_tags(name: str, cs_type: BaseSetting, value: Any) -> Set[str]:
    """
    generate tags based on `CONTENT_SETTINGS_TAGS` setting.
    """
    tags = set()
    for func_tag in get_call_tags():
        tags |= func_tag(name, cs_type, value)
    return tags


def register_prefix(name: str) -> Callable:
    """
    decorator for registration a new prefix
    """

    def _cover(func: Callable) -> Callable:
        assert name not in PREFIXSES
        PREFIXSES[name] = func
        return func

    return _cover


@register_prefix("lazy")
def lazy_prefix(name: str, suffix: str) -> Any:
    """
    lazy__ prefix that gives a lazy proxy object by the name of the setting.
    """
    return get_type_by_name(name).lazy_give(lambda: get_value(name, suffix), suffix)


@register_prefix("type")
def type_prefix(name: str, suffix: str) -> Any:
    """
    type__ prefix that return setting type by the name of the setting.
    """
    assert not suffix, "type prefix can not have suffix"

    return get_type_by_name(name)


@register_prefix("startswith")
def startswith_prefix(name: str, suffix: str) -> Dict[str, Any]:
    """
    startswith__ prefix that returns all settings as a dict (setting name: setting value) that start with the given name.
    """
    return {
        k: get_value(k, suffix) for k in dir(content_settings) if k.startswith(name)
    }


@register_prefix("withtag")
def withtag_prefix(name: str, suffix: str) -> Dict[str, Any]:
    """
    withtag__ prefix that returns all settings as a dict (setting name: setting value) that have the given tag.
    """
    return {
        k: get_value(k, suffix)
        for k in dir(content_settings)
        if name in get_type_by_name(k).get_tags()
        or name.lower() in get_type_by_name(k).get_tags()
    }


for app_config in apps.app_configs.values():
    app = app_config.name
    try:
        content_settings = import_module(app + ".content_settings")
    except ImportError as e:
        if e.name != app + ".content_settings":
            raise
        continue
    for attr in dir(content_settings):
        if not attr.isupper():
            continue

        val = getattr(content_settings, attr)

        if not isinstance(val, BaseSetting):
            continue

        assert attr not in ALL, "Content Setting {} defined twice".format(attr)

        if attr in ALL and not ALL[attr].user_defined_slug:
            raise AssertionError("Overwriting content setting {}".format(attr))

        assert (
            not val.user_defined_slug
        ), "Do not set user_defined_slug in content_settings.py"

        ALL[attr] = val
        add_app_name(attr, app)


def split_attr(value: str) -> Tuple[Optional[str], str, Optional[str]]:
    """
    splits the name of the attr on 3 parts: prefix, name, suffix

    * prefix should be registered by register_prefix
    * name should be uppercase
    * suffix can be any string, but not uppercase
    """
    prefix = None
    parts = value.split("__")

    if parts[0] in PREFIXSES:
        prefix = parts.pop(0)

    assert len(parts), f"Invalid attribute name: {value}; can not be only prefix"

    name = parts.pop(0)
    assert name.isupper(), f"Invalid attribute name: {value}; name should be uppercase"

    while parts:
        if not parts[0].isupper():
            break

        name += "__" + parts.pop(0)

    if len(parts):
        return prefix, name, "__".join(parts).lower()

    return prefix, name, None


def get_str_tags(
    cs_name: str, cs_type: BaseSetting, value: Optional[str] = None
) -> str:
    """
    get tags as a text (joined by `\n`) for specific setting type. name and value are used to generate content tags.

    from saving in DB.
    """
    tags = cs_type.get_tags()
    if not cs_type.user_defined_slug:
        tags |= cs_type.get_content_tags(
            cs_name, cs_type.default if value is None else value
        )
    return "\n".join(sorted(tags))


def set_initial_values_for_db(apply: bool = False) -> List[Tuple[str, str]]:
    """
    sync settings with DB.
        * creates settings that are not in DB
        * updates settings that are in DB but have different attributes such as help text or tags
        * deletes settings that are in DB but are not in ALL

    attribute `apply` is used to apply changes in DB immediately. Can be used in tests.
    """
    from content_settings.models import ContentSetting, HistoryContentSetting

    changes = []

    def execute(name, key, func):
        changes.append((name, key))
        if apply:
            func()
            HistoryContentSetting.update_last_record_for_name(name)

    def execute_update_obj(name, cs, show="update", **kwargs):
        def _up():
            for k, v in kwargs.items():
                setattr(cs, k, v)
            cs.save()

        execute(name, show, _up)

    for k, cs_type in ALL.items():
        if cs_type.constant:
            continue

        try:
            ContentSetting.objects.get(name=k)
        except ContentSetting.DoesNotExist:
            execute(
                k,
                "create",
                lambda: ContentSetting.objects.create(
                    name=k,
                    value=cs_type.default,
                    version=cs_type.version,
                    tags=get_str_tags(k, cs_type),
                    help=cs_type.get_help(),
                ),
            )

    for cs in ContentSetting.objects.all():
        if cs.name in ALL:
            cs_type = ALL[cs.name]
            if cs_type.constant:
                execute(cs.name, "delete", lambda: cs.delete())
                continue

            assert (
                not cs.user_defined_type or cs_type.overwrite_user_defined
            ), f"{cs.name} is not a code setting and not overwrite_user_defined"

            if cs.version != cs_type.version:
                execute_update_obj(
                    cs.name,
                    cs,
                    value=cs_type.default,
                    version=cs_type.version,
                    user_defined_type=None,
                )

            if cs.user_defined_type:
                execute_update_obj(
                    cs.name,
                    cs,
                    user_defined_type=None,
                    show="adjust",
                )

            str_tags = get_str_tags(cs.name, cs_type, cs.value)
            str_help = cs_type.get_help()

            if cs.tags != str_tags or cs.help != str_help:
                execute_update_obj(
                    cs.name,
                    cs,
                    tags=str_tags,
                    help=str_help,
                    show="adjust",
                )

        else:
            if cs.user_defined_type:
                if cs.user_defined_type not in USER_DEFINED_TYPES_INSTANCE:
                    execute(cs.name, "delete", lambda: cs.delete())
                elif (
                    cs.version
                    != USER_DEFINED_TYPES_INITIAL[cs.user_defined_type].version
                ):
                    cs_type = USER_DEFINED_TYPES_INSTANCE[cs.user_defined_type]()
                    execute_update_obj(
                        cs.name, cs, value=cs_type.default, version=cs_type.version
                    )
            else:
                execute(cs.name, "delete", lambda: cs.delete())

    return changes


class _Settings:
    """
    the main object that uses for getting settings for cache.
    """

    def __getattr__(self, value):
        prefix, name, suffix = split_attr(value)
        if prefix:
            assert (
                prefix in PREFIXSES
            ), f"Invalid attribute name: {value}; prefix not found"
            return PREFIXSES[prefix](name, suffix)
        return get_value(name, suffix)

    def __dir__(self):
        """
        dir() returns all settings names
        """
        return get_all_names()

    def __contains__(self, value):
        _, name, suffix = split_attr(value)
        cs_type = get_type_by_name(name)
        return cs_type is not None and cs_type.can_suffix(suffix)

    @property
    def full_checksum(self):
        """
        the current checksum of the settings.

        used for validation of settings weren't changed over time.
        """
        return get_checksum_from_local() + get_checksum_from_user_local()


content_settings = _Settings()
