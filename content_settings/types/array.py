from typing import Any, Optional, List, Callable, Generator, Iterable
from collections.abc import Iterable

from django.core.exceptions import ValidationError

from .basic import (
    SimpleText,
    SimpleTextPreview,
    SimpleString,
    BaseSetting,
    PREVIEW_PYTHON,
    PREVIEW_TEXT,
    PREVIEW_NONE,
    PREVIEW_HTML,
)
from .mixins import AdminPreviewSuffixesMixin
from .each import EachMixin, Item, Keys, Values


def f_empty(value: str) -> Optional[str]:
    value = value.strip()
    if not value:
        return None
    return value


def f_comment(prefix: str) -> Callable[[str], Optional[str]]:
    def _(value: str) -> Optional[str]:
        if value.strip().startswith(prefix):
            return None
        return value

    return _


class SimpleStringsList(SimpleText):
    """
    Split a text into a list of strings.
    * comment_starts_with (default: #): if not None, the lines that start with this string are removed
    * filter_empty (default: True): if True, empty lines are removed
    * split_lines (default: \n): the string that separates the lines
    * filters (default: None): a list of additional filters to apply to the lines.
    """

    comment_starts_with: Optional[str] = "#"
    filter_empty: bool = True
    split_lines: str = "\n"
    filters: Optional[Iterable[callable]] = None
    admin_preview_as: str = PREVIEW_PYTHON

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        assert isinstance(self.comment_starts_with, (str, type(None)))
        assert isinstance(self.filter_empty, bool)
        assert isinstance(self.split_lines, str)
        assert isinstance(self.filters, (Iterable, type(None)))

    def get_filters(self):
        """
        Get the filters based on the current configuration.
        * If filters is not None, it is returned.
        * If filter_empty is True, f_empty is added to the filters.
        * If comment_starts_with is not None, f_comment is added to the filters.
        """
        if self.filters is not None:
            filters = [*self.filters]
        else:
            filters = []

        if self.filter_empty:
            filters.append(f_empty)

        if self.comment_starts_with:
            filters.append(f_comment(self.comment_starts_with))

        return filters

    def get_help_format(self) -> Generator[str, None, None]:
        yield "List of values with the following format:"
        yield "<ul>"
        if self.split_lines == "\n":
            yield "<li>each line is a new value</li>"
        else:
            yield f"<li>{self.split_lines} separates values</li>"
        yield "<li>strip spaces from the beginning and from the end of the value</li>"
        yield "<li>remove empty values</li>"
        if self.comment_starts_with:
            yield f"<li> use {self.comment_starts_with} to comment a line</li>"
        if self.filter_empty:
            yield "<li>empty values are removed</li>"
        yield "</ul>"

    def filter_line(self, line: str) -> str:
        for f in self.get_filters():
            line = f(line)
            if line is None:
                break
        return line

    def gen_to_python(self, value: str) -> Generator[str, None, None]:
        """
        Converts a string value into a generator of filtered lines.
        """
        lines = value.split(self.split_lines)
        for line in lines:
            line = self.filter_line(line)

            if line is not None:
                yield line

    def to_python(self, value: str) -> List[str]:
        return list(self.gen_to_python(value))


class TypedStringsList(EachMixin, SimpleStringsList):
    line_type = SimpleString()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.each = Item(self.line_type)


NOT_FOUND_DEFAULT = "default"
NOT_FOUND_KEY_ERROR = "key_error"
NOT_FOUND_VALUE = "value"

SPLIT_FAIL_IGNORE = "ignore"
SPLIT_FAIL_RAISE = "raise"


def split_validator_in(values: List[str]) -> callable:
    """
    Returns a validator function that checks if a given value is in the specified list of values.
    It uses for SplitTextByFirstLine.split_key_validator.
    """

    def _(value: str) -> bool:
        return value in values

    return _


class SplitTextByFirstLine(SimpleText):
    """
    Split text by the separator that can be found in the first line.
    The result is a dictionary where the keys are the separators and the values are the text after the separator.

    If your defaukt key is "EN", the first line can be "===== EN =====" to initialize the separator.
    The next separator is initialized by the next line that starts with "=====", ends with "=====" and has a key in the middle.


    """

    split_default_key = None
    split_default_chooser = None
    split_not_found = NOT_FOUND_DEFAULT
    split_not_found_value = None
    split_key_validator = None
    split_key_validator_failed = SPLIT_FAIL_IGNORE
    admin_preview_as = PREVIEW_HTML

    def get_split_default_key(self):
        return self.split_default_key

    def split_default_choose(self, value):
        if self.split_default_chooser is None:
            return self.get_split_default_key()
        else:
            return self.split_default_chooser(value)

    def get_split_not_found(self):
        return self.split_not_found

    def get_split_not_found_value(self):
        return self.split_not_found_value

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        assert (
            self.get_split_default_key()
        ), "split_default_key should be set and it should not be empty"
        assert isinstance(
            self.get_split_default_key(), str
        ), "split_default_key should be str"

        assert self.split_default_chooser is None or callable(
            self.split_default_chooser
        ), "split_default_chooser should be callable or None"
        assert self.split_key_validator is None or callable(
            self.split_key_validator
        ), "split_key_validator should be callable or None"
        assert self.split_key_validator_failed in (
            SPLIT_FAIL_IGNORE,
            SPLIT_FAIL_RAISE,
        ), "split_key_validator_failed should be one of SPLIT_FAIL_IGNORE, SPLIT_FAIL_RAISE"
        assert self.get_split_not_found() in (
            NOT_FOUND_DEFAULT,
            NOT_FOUND_KEY_ERROR,
            NOT_FOUND_VALUE,
        ), "split_not_found should be one of NOT_FOUND_DEFAULT, NOT_FOUND_KEY_ERROR, NOT_FOUND_VALUE"

    def validate_split_key(self, key):
        return self.split_key_validator is None or self.split_key_validator(key)

    def split_value(self, value):
        lines = value.splitlines()
        if (
            not lines
            or self.get_split_default_key() not in lines[0]
            or lines[0].count(self.get_split_default_key()) > 1
        ):
            return {self.get_split_default_key(): value}

        before, after = lines[0].split(self.get_split_default_key())
        ret = {self.get_split_default_key(): []}
        cur_iter = ret[self.get_split_default_key()]
        for num, line in enumerate(lines[1:], start=2):
            if line.startswith(before) and line.endswith(after):
                line_key = line[len(before) : len(line) - len(after)]
                if self.validate_split_key(line_key):
                    cur_iter = ret[line_key] = []
                    continue

                if self.split_key_validator_failed == SPLIT_FAIL_RAISE:
                    raise ValidationError(
                        f"Invalid split key: {line_key} in line {num}"
                    )

            cur_iter.append(line)

        return {k: "\n".join(v) for k, v in ret.items()}

    def to_python(self, value):
        return self.split_value(value)

    def give(self, value, suffix=None):
        if suffix is None:
            suffix = self.split_default_choose(value)

        try:
            ret_val = value[suffix.upper()]
        except KeyError:
            if self.get_split_not_found() == NOT_FOUND_KEY_ERROR:
                raise
            elif self.get_split_not_found() == NOT_FOUND_DEFAULT:
                ret_val = value[self.get_split_default_key()]
            elif self.get_split_not_found() == NOT_FOUND_VALUE:
                ret_val = self.get_split_not_found_value()

        return ret_val


class SplitByFirstLine(AdminPreviewSuffixesMixin, EachMixin, SplitTextByFirstLine):
    split_type = SimpleTextPreview()

    def get_admin_preview_suffixes_default(self):
        return self.get_split_default_key()

    def get_admin_preview_suffixes(self, value: dict, name: str, **kwargs):
        keys = list(value.keys())
        keys.remove(self.get_split_default_key())
        return tuple(keys)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        if isinstance(self.split_type, dict):
            self.each = Keys(**self.split_type)
        else:
            self.each = Values(self.split_type)

    def get_admin_preview_under_menu_object(self, value, name, suffix=None, **kwargs):
        if suffix is None:
            suffix = self.get_split_default_key()
        cs_type = self.split_type
        if isinstance(cs_type, dict):
            cs_type = self.split_type.get(suffix.upper(), SimpleTextPreview())

        value = SplitTextByFirstLine.give(self, value, suffix)
        return cs_type.get_admin_preview_object(value, name, **kwargs)


class SplitTranslation(SplitByFirstLine):
    split_default_key = "EN"
    split_not_found = NOT_FOUND_DEFAULT

    def get_help_format(self):
        yield "Translated Text. "
        yield "The first line can initialize the translation splitter. "
        yield f"The initial language is {self.split_default_key}. "
        yield f"The first line can be '===== {self.split_default_key} ====='. "
        yield "The format for the value inside the translation is: "
        yield from self.split_type.get_help_format()

    def split_default_choose(self, value):
        from django.utils.translation import get_language

        return get_language().upper().replace("-", "_")
