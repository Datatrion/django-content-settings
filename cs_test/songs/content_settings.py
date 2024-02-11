from content_settings.types.basic import (
    SimpleString,
    SimpleInt,
    SimpleHTML,
    SimpleDecimal,
)
from content_settings.types.datetime import DateString
from content_settings.types.mixins import (
    MinMaxValidationMixin,
    mix,
    DictSuffixesPreviewMixin,
)
from content_settings.types.array import SimpleStringsList, TypedStringsList
from content_settings.types.markup import SimpleYAML
from content_settings.types.each import EachMixin, Keys
from content_settings.types.template import DjangoTemplateHTML, DjangoModelTemplateHTML

from content_settings.context_managers import context_defaults, add_tags
from content_settings import permissions

from .models import Artist

with context_defaults(add_tags(["main"]), fetch_permission=permissions.any):
    TITLE = SimpleString("My Site", help="Title of the site")

    AFTER_TITLE = DjangoTemplateHTML(
        "", help="The html goes right after the title", tags=["html"]
    )

    DAYS_WITHOUT_FAIL = mix(MinMaxValidationMixin, SimpleInt)(
        "5", min_value=0, max_value=10, help="How many days without fail"
    )


FAVORITE_SUBJECTS = SimpleStringsList("", help="my favorive songs subjects")

PRICES = mix(DictSuffixesPreviewMixin, TypedStringsList)(
    "",
    line_type=SimpleDecimal(),
    suffixes={"positive": lambda value: [v for v in value if v >= 0]},
)

START_DATE = DateString("2024-02-11", constant=True)

MY_YAML = mix(EachMixin, SimpleYAML)("", each=Keys(price=SimpleDecimal()))

ARTIST_LINE = DjangoModelTemplateHTML(
    "",
    model_queryset=Artist.objects.all(),
    obj_name="artist",
)
