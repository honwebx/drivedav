import errno
import traceback
import logging
from http.client import responses
from xml.sax.saxutils import escape as xml_escape

from wsgidav.error_printer import ErrorPrinter
from wsgidav import util
from wsgidav.dav_error import (
    DAVError,
    as_DAVError,
    get_http_status_string,
    HTTP_INTERNAL_ERROR,
    HTTP_NOT_MODIFIED,
    HTTP_NO_CONTENT,
    HTTP_FORBIDDEN,
)

_logger = logging.getLogger(__name__)


def _clean_headers(headers):
    """
    过滤掉 value 为 None 的 header，避免 Cheroot 报错
    """

    return [(k, str(v)) for (k, v) in headers if v is not None]

def _get_http_status_phrase(code):
    return responses.get(code, "Unknown")

def _safe_status(e):
    """
    确保 HTTP 状态行合法，例如 '500 Internal Server Error'
    """

    status = get_http_status_string(e)
    if not status or " " not in status:
        phrase = _get_http_status_phrase(e.value)
        status = f"{e.value} {phrase}"
    return status


class XmlErrorPrinter(ErrorPrinter):
    """
    打印 DAVError 为 XML 格式
    """

    def __call__(self, environ, start_response):
        sub = util.SubAppStartResponse()

        try:
            try:
                response_started = False
                app_iter = self.next_app(environ, sub)

                for v in app_iter:
                    if not response_started:
                        clean_headers = _clean_headers(sub.response_headers)
                        start_response(sub.status, clean_headers, sub.exc_info)

                    response_started = True
                    yield v

                if hasattr(app_iter, "close"):
                    app_iter.close()

                if not response_started:
                    clean_headers = _clean_headers(sub.response_headers)
                    start_response(sub.status, clean_headers, sub.exc_info)

                return

            except DAVError:
                raise

            except OSError as e:
                if e.errno == errno.EACCES:
                    raise DAVError(HTTP_FORBIDDEN, e.strerror) from None
                raise as_DAVError(e) from None

            except Exception as e:
                _logger.error(f"{traceback.format_exc(10)}")
                raise as_DAVError(e) from None

        except DAVError as e:
            _logger.debug(f"Caught {e}")

            status = _safe_status(e)

            if e.value == HTTP_INTERNAL_ERROR:
                tb = traceback.format_exc(10)
                _logger.error(f"Caught HTTP_INTERNAL_ERROR\n{tb}")
                _logger.error(f"e.src_exception:\n{e.src_exception}")

            elif e.value in (HTTP_NOT_MODIFIED, HTTP_NO_CONTENT):
                start_response(
                    status,
                    [("Content-Length", "0"),
                    ("Date", util.get_rfc1123_time())],
                )
                yield b""
                return

            message = xml_escape(e.get_user_info() or str(e))
            xml = f"""<?xml version="1.0" encoding="utf-8"?>
<d:error xmlns:d="DAV:">
    <d:message>{message}</d:message>
</d:error>"""

            body = xml.encode("utf-8")
            
            headers = _clean_headers(e.add_headers or [])

            start_response(
                status,
                _clean_headers(
                    [
                        ("Content-Type", "application/xml; charset=utf-8"),
                        ("Content-Length", str(len(body))),
                        ("Date", util.get_rfc1123_time()),
                    ]
                    + headers
                )
            )

            yield body
            return
