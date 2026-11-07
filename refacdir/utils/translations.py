import gettext
import os
from refacdir.utils.logger import setup_logger

# Set up logger for translations
logger = setup_logger('translations')

from refacdir.utils.app_paths import resource_path
from refacdir.utils.utils import Utils

_locale = os.environ['LANG'] if "LANG" in os.environ else None
if not _locale or _locale == '':
    _locale = Utils.get_default_user_language()
elif _locale is not None and "_" in _locale:
    _locale = _locale[:_locale.index("_")]

class I18N:
    localedir = resource_path('locale')
    locale = _locale
    translate = gettext.translation('base', localedir, languages=[_locale])

    @staticmethod
    def install_locale(locale, verbose=True):
        I18N.locale = locale
        I18N.translate = gettext.translation('base', I18N.localedir, languages=[locale], fallback=True)
        I18N.translate.install()
        if verbose:
            logger.info("Switched locale to: " + locale)

    @staticmethod
    def _(s):
        # return gettext.gettext(s)
        try:
            return I18N.translate.gettext(s)
        except KeyError:
            return s

    @staticmethod
    def day_of_the_week(day_index=0):
        if day_index == 0:
            return I18N._('Monday')
        elif day_index == 1:
            return I18N._('Tuesday')
        elif day_index == 2:
            return I18N._('Wednesday')
        elif day_index == 3:
            return I18N._('Thursday')
        elif day_index == 4:
            return I18N._('Friday')
        elif day_index == 5:
            return I18N._('Saturday')
        else:
            return I18N._('Sunday')

    @staticmethod
    def time_ago(seconds: float) -> tuple[int, str]:
        """Convert seconds into a human-readable time difference.
        
        Returns:
            tuple[int, str]: A tuple containing:
                - The number of time units
                - The translated time unit (e.g. "hours", "minutes", etc.)
        """
        if seconds < 60:
            return int(seconds), I18N._("seconds")
        elif seconds < 3600:
            return int(seconds / 60), I18N._("minutes")
        elif seconds < 86400:
            return int(seconds / 3600), I18N._("hours")
        elif seconds < 604800:
            return int(seconds / 86400), I18N._("days")
        elif seconds < 2592000:
            return int(seconds / 604800), I18N._("weeks")
        elif seconds < 31536000:
            return int(seconds / 2592000), I18N._("months")
        else:
            return int(seconds / 31536000), I18N._("years")

    r'''
    NOTE when gathering the translation strings, set _() == to gettext.gettext() instead of the above, and run:

        ```python C:\Python310\Tools\i18n\pygettext.py -d base -k LocalizedText -o locale\base.pot .```

    ``-k LocalizedText`` also extracts the templates passed to LocalizedText (below).

    in the base directory. The POT output file can be used as source for the PO files in each locale.
    Run personal script C:\Scripts\i18n_manager.py to generate new PO files and look for invalid translations.

    Bonus command:
        ```git diff Weidr\locale\de\LC_MESSAGES\base.po Weidr\locale\de\LC_MESSAGES\base1.po | rg -v "^.*#" | rg -C 3 "^(-|\+)"```

    Then for each locale once the PO files are set up as desired, run below in the deepest locale directory to produce the MO file from the PO file:
        ```python C:\Python310\Tools\i18n\msgfmt.py -o base.mo base```
    '''


# Module-level alias for ``from refacdir.utils.translations import _``. Binding the
# function object here stays correct across a locale switch: ``I18N._`` resolves
# ``I18N.translate`` on every call, and ``install_locale`` rebinds that attribute.
_ = I18N._


class LocalizedText(str):
    """English text that can also produce its translation.

    For a message that goes both to the user and somewhere that needs stable
    English: the LLM retry prompt, substring checks on error text, the log
    file. As a ``str`` it is the English text, so equality, ``in``, joins,
    f-strings and ``str(exc)`` for an exception raised with it all see
    English; ``localized()`` translates the template at call time and fills
    in the same arguments. Raise as ``Exception(LocalizedText("… {0}", x))``
    and display through ``localized_str``.
    """

    def __new__(cls, template, *args):
        text = super().__new__(cls, template.format(*args) if args else template)
        text.template = template
        text.template_args = args
        return text

    def __getnewargs__(self):
        # Pickling and copying rebuild from the template, not the English text.
        return (self.template, *self.template_args)

    def localized(self) -> str:
        translated = I18N._(self.template)
        return translated.format(*self.template_args) if self.template_args else translated


def as_localized_text(value):
    """The ``LocalizedText`` an exception was raised with, else ``str(value)``."""
    if isinstance(value, BaseException) and len(value.args) == 1 and isinstance(value.args[0], LocalizedText):
        return value.args[0]
    if isinstance(value, LocalizedText):
        return value
    return str(value)


def localized_str(value) -> str:
    """Text to show the user for *value*: a ``LocalizedText``, an exception
    raised with one, or anything else via ``str()``."""
    text = as_localized_text(value)
    return text.localized() if isinstance(text, LocalizedText) else text
