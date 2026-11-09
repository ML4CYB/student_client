"""Istemci tanilama gunlugu.

Amac: bir ogrenci "atildim" dediginde ne oldugunu tahmin etmek yerine bilmek. Her calistirma
icin ayri bir dosya yazilir; icinde hangi olayin (pencere, dugme, zamanlayici, sunucu istegi,
sinyal) hangi zamanda ve kimin tarafindan (ogrenci / zamanlayici / sistem) tetiklendigi vardir.

KAYDEDILMEZ (bilerek): yazilan metin ve tus icerikleri, parolalar, token'lar, Guacamole
adresindeki token, sunucuya giden istek govdeleri. Tuslardan yalnizca Tab/Esc/F tuslari,
Alt/Meta kombinasyonlari ve Ctrl+Q/W adlari kaydedilir; geri kalan girdi sadece sayilir.

Zaman damgalari UTC'dir (sunucu saati America/New_York).
Log yazmak uygulamayi ASLA bozmamali: buradaki her sey hata yutar.
"""
import atexit
import faulthandler
import logging
import os
import platform
import sys
import tempfile
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler
from urllib.parse import urlsplit

import requests

CLIENT_VERSION = "2026-11-09-log1"   # hangi surumun calistigini loglardan ogrenmek icin
KEEP_LOG_FILES = 40                  # bundan eski calistirma dosyalari silinir
MAX_LOG_BYTES = 5_000_000
# Sunucu cevabindan yalnizca bu alanlar loglanir (url, token, liste gibi hassas/buyuk alanlar degil)
_LOGGED_FIELDS = ("status", "detail", "server_status", "log_reg_id", "guac")
SLOW_REQUEST_SECONDS = 3.0

log = logging.getLogger("jetstream")
log.setLevel(logging.INFO)
log.propagate = False
log.addHandler(logging.NullHandler())   # setup_logging cagrilmazsa (testler) hicbir sey yazilmaz

_session_id = uuid.uuid4().hex[:6]
_log_path = None
_crash_file = None


class _UtcFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return "%s.%03dZ" % (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(record.created)), int(record.msecs))


def log_dir():
    """Log klasoru. JETSTREAM_LOG_DIR ortam degiskeni ile degistirilebilir."""
    override = os.environ.get("JETSTREAM_LOG_DIR")
    if override:
        return override
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(base, "JetstreamClient", "logs")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Logs", "JetstreamClient")
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")
    return os.path.join(base, "jetstream-client")


def _prune_old_logs(directory):
    try:
        names = sorted(n for n in os.listdir(directory) if n.startswith("client_") and n.endswith(".log"))
        for n in names[:-KEEP_LOG_FILES]:
            for suffix in ("", ".1", ".crash"):
                try:
                    os.remove(os.path.join(directory, n + suffix))
                except OSError:
                    pass
    except Exception:
        pass


def setup_logging():
    """Dosya log'unu ve cokme kayitlarini ac. Birden cok kez cagrilabilir. Log dosyasinin yolunu doner."""
    global _log_path, _crash_file
    if _log_path:
        return _log_path
    for directory in (log_dir(), os.path.join(tempfile.gettempdir(), "JetstreamClientLogs")):
        try:
            os.makedirs(directory, exist_ok=True)
            name = "client_%s_pid%d.log" % (time.strftime("%Y%m%d_%H%M%S", time.gmtime()), os.getpid())
            path = os.path.join(directory, name)
            handler = RotatingFileHandler(path, maxBytes=MAX_LOG_BYTES, backupCount=1, encoding="utf-8")
            handler.setFormatter(_UtcFormatter("%(asctime)s [" + _session_id + "] %(levelname)-7s %(message)s"))
            log.addHandler(handler)
            _log_path = path
            _prune_old_logs(directory)
            break
        except Exception:
            continue
    if not _log_path:
        return None

    # Python/Qt'nin yakalayamadigi yerel cokmeler (segfault vb.) icin ayri dosya; bos kalirsa kapanista silinir
    try:
        _crash_file = open(_log_path + ".crash", "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:
        _crash_file = None
    atexit.register(_at_exit)

    log.info("=== Jetstream client starting === version=%s pid=%d", CLIENT_VERSION, os.getpid())
    log.info("times are UTC (this computer's offset: %s); log file: %s", time.strftime("%z"), _log_path)
    log.info("python=%s os=%s frozen=%s", sys.version.split()[0], platform.platform(), bool(getattr(sys, "frozen", False)))
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        log.info("PyQt6=%s Qt=%s", PYQT_VERSION_STR, QT_VERSION_STR)
    except Exception:
        pass
    return _log_path


def _at_exit():
    try:
        log.info("process exit (normal)")
        if _crash_file:
            _crash_file.flush()
            size = os.path.getsize(_crash_file.name)
            faulthandler.disable()
            _crash_file.close()
            if size == 0:
                os.remove(_crash_file.name)
    except Exception:
        pass


def install_excepthook():
    """Yakalanmamis hatalari logla ve uygulamayi dusurme.

    PyQt6 varsayilan sys.excepthook ile bir slot/sanal metotta yakalanmamis hata gorurse uygulamayi
    abort eder (pencere sessizce yok olur, set_passive gitmez, oturum active=1 kalir). Ozel bir
    excepthook kurulunca PyQt onu cagirir ve uygulama calismaya devam eder."""
    def hook(exc_type, exc, tb):
        try:
            log.error("UNHANDLED EXCEPTION (application keeps running)", exc_info=(exc_type, exc, tb))
        except Exception:
            pass
        try:
            if sys.stderr:
                sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = hook
    try:
        threading.excepthook = lambda args: hook(args.exc_type, args.exc_value, args.exc_traceback)
    except Exception:
        pass


def safe_url(url):
    """Adresin token tasiyan kisimlarini (sorgu ve '?' sonrasi) atip kisa bir ozet verir."""
    try:
        u = urlsplit(str(url))
        if u.scheme in ("data", "about", "javascript", ""):
            return (u.scheme or "?") + ":..."
        fragment = u.fragment.split("?")[0]
        return "%s://%s%s%s" % (u.scheme, u.netloc, u.path, ("#" + fragment) if fragment else "")
    except Exception:
        return "<unparseable url>"


def _endpoint(url):
    try:
        path = urlsplit(str(url)).path.strip("/")
        return path or "login"
    except Exception:
        return "?"


def api_post(url, payload, timeout):
    """requests.post + JSON ayristirma + gunluk (adres sonu, sure, status/detail).

    Cevabin ayristirilmis halini (dict) doner; ag hatasi ya da JSON olmayan cevapta istisna firlatir
    (cagiranlarin mevcut hata isleme davranisi degismez). Istek govdesi ve token ASLA yazilmaz."""
    ep = _endpoint(url)
    t0 = time.monotonic()
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except Exception as e:
        log.warning("POST %s FAILED after %.2fs (timeout=%ss): %s: %s",
                    ep, time.monotonic() - t0, timeout, type(e).__name__, str(e)[:200])
        raise
    elapsed = time.monotonic() - t0
    try:
        data = response.json()
    except Exception as e:
        log.warning("POST %s -> NOT JSON after %.2fs (http %s): %s",
                    ep, elapsed, getattr(response, "status_code", "?"), type(e).__name__)
        raise
    try:
        if isinstance(data, dict):
            fields = " ".join("%s=%s" % (k, str(data[k])[:160]) for k in _LOGGED_FIELDS if k in data)
        else:
            fields = "(response is %s)" % type(data).__name__
        slow = " SLOW" if elapsed >= SLOW_REQUEST_SECONDS else ""
        log.log(logging.WARNING if slow else logging.INFO, "POST %s -> %s %.2fs%s", ep, fields, elapsed, slow)
    except Exception:
        pass
    return data
