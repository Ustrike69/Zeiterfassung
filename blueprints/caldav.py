"""
Blueprint: CalDAV-Endpunkte.
"""
from flask import Blueprint, request, make_response
from db import connect
from auth import current_user
from translations import t

_CALDAV_P_METHODS = ["GET", "HEAD", "PROPFIND", "OPTIONS"]
_CALDAV_C_METHODS = ["GET", "HEAD", "PROPFIND", "REPORT", "OPTIONS"]

caldav_bp = Blueprint("caldav", __name__)


@caldav_bp.route("/caldav/basic/", methods=_CALDAV_P_METHODS)
def caldav_basic_principal():
    from app import bootstrap, _caldav_options, _caldav_user_by_basic, _caldav_do_principal
    bootstrap()
    if request.method.upper() == "OPTIONS":
        return _caldav_options()
    user, err = _caldav_user_by_basic()
    if err:
        return err
    return _caldav_do_principal(user, "/caldav/basic/")


@caldav_bp.route("/caldav/basic/calendar/", methods=_CALDAV_C_METHODS)
def caldav_basic_calendar():
    from app import bootstrap, _caldav_options, _caldav_user_by_basic, _caldav_do_calendar
    bootstrap()
    if request.method.upper() == "OPTIONS":
        return _caldav_options()
    user, err = _caldav_user_by_basic()
    if err:
        return err
    lang = user.get("language") or "en"
    return _caldav_do_calendar(user, "/caldav/basic/calendar/", lang)


@caldav_bp.get("/caldav/basic/calendar/<filename>")
def caldav_basic_event(filename: str):
    from app import bootstrap, _caldav_user_by_basic, _caldav_do_event
    bootstrap()
    user, err = _caldav_user_by_basic()
    if err:
        return err
    lang = user.get("language") or "en"
    return _caldav_do_event(user, lang, filename)


@caldav_bp.route("/caldav/<token>/", methods=_CALDAV_P_METHODS)
def caldav_token_principal(token: str):
    from app import bootstrap, _caldav_user_by_token, _caldav_do_principal
    from flask import abort
    bootstrap()
    user = _caldav_user_by_token(token)
    if not user:
        abort(404)
    lang = user.get("language") or "en"
    return _caldav_do_principal(user, f"/caldav/{token}/")


@caldav_bp.route("/caldav/<token>/calendar/", methods=_CALDAV_C_METHODS)
def caldav_token_calendar(token: str):
    from app import bootstrap, _caldav_user_by_token, _caldav_do_calendar
    from flask import abort
    bootstrap()
    user = _caldav_user_by_token(token)
    if not user:
        abort(404)
    lang = user.get("language") or "en"
    return _caldav_do_calendar(user, f"/caldav/{token}/calendar/", lang)


@caldav_bp.get("/caldav/<token>/calendar/<filename>")
def caldav_token_event(token: str, filename: str):
    from app import bootstrap, _caldav_user_by_token, _caldav_do_event
    from flask import abort
    bootstrap()
    user = _caldav_user_by_token(token)
    if not user:
        abort(404)
    lang = user.get("language") or "en"
    return _caldav_do_event(user, lang, filename)
