"""Adds Configuration-module specific configuration options"""

from django.utils.translation import ugettext_lazy as _
from livesettings import BooleanValue, config_register
from product.config import PRODUCT_GROUP

config_register(
    BooleanValue(PRODUCT_GROUP,
        'SEARCH_SHOW_PRODUCTVARIATIONS',
        description=_("Show product variations in search results?"),
        help_text=_("If yes, the product variations will show up in searches."),
        default=True
    ))
