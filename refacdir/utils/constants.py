class AppInfo:
    SERVICE_NAME = "MyPersonalApplicationsService"
    APP_IDENTIFIER = "RefacDir"
    #: Identifiers this app has used before. Key material is filed per
    #: identifier, so a rename orphans the old keys and everything encrypted
    #: under them -- an old name listed here keeps scripts/key_material.py
    #: reporting and backing it up. Empty: this app has never been renamed.
    LEGACY_APP_IDENTIFIERS = ()
