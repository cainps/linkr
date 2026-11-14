"""Regras de negócio puras (sem Flask) — fáceis de testar."""
import ipaddress, re, secrets
from datetime import datetime, timezone
from urllib.parse import urlparse

SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
RESERVED_SLUGS = {"api", "admin", "static", "login", "register", "dashboard", "health", "app", "www"}
BASE62 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
BOT_HINTS = ("bot", "crawler", "spider", "preview", "curl", "wget", "headless", "facebookexternalhit")


class RuleError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.message, self.status = message, status


def validate_target_url(url: str, own_host: str | None = None) -> str:
    url = (url or "").strip()
    if not url or len(url) > 2048:
        raise RuleError("URL vazia ou maior que 2048 caracteres")
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise RuleError("Só são aceitas URLs http:// ou https://")
    host = p.hostname.lower()
    if own_host and host == own_host.split(":")[0].lower():
        raise RuleError("Não é permitido encurtar um link do próprio encurtador (loop de redirect)")
    if host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        raise RuleError("Destino interno não permitido")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise RuleError("IP privado/interno não permitido")
    except ValueError:
        pass  # é um hostname, não um IP
    return url


def validate_slug(slug: str) -> str:
    if not SLUG_RE.match(slug or ""):
        raise RuleError("Slug deve ter 3–32 caracteres: letras, números, '-' ou '_'")
    if slug.lower() in RESERVED_SLUGS:
        raise RuleError("Slug reservado", 409)
    return slug


def generate_slug(length=7) -> str:
    return "".join(secrets.choice(BASE62) for _ in range(length))


def parse_expiry(value) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise RuleError("expires_at deve estar em formato ISO-8601")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt <= datetime.now(timezone.utc):
        raise RuleError("A data de expiração precisa estar no futuro")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_max_clicks(value) -> int | None:
    if value in (None, ""):
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 10_000_000:
        raise RuleError("max_clicks deve ser um inteiro positivo")
    return value


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return not ua or any(h in ua for h in BOT_HINTS)


def parse_user_agent(ua: str) -> tuple[str, str]:
    u = (ua or "").lower()
    device = "tablet" if ("ipad" in u or "tablet" in u) else "mobile" if ("mobi" in u or "android" in u or "iphone" in u) else "desktop"
    if "edg/" in u: browser = "Edge"
    elif "opr/" in u or "opera" in u: browser = "Opera"
    elif "chrome" in u or "crios" in u: browser = "Chrome"
    elif "firefox" in u or "fxios" in u: browser = "Firefox"
    elif "safari" in u: browser = "Safari"
    else: browser = "Other"
    return device, browser


def referrer_host(ref: str | None) -> str:
    if not ref:
        return "direct"
    return (urlparse(ref).hostname or "direct").removeprefix("www.")
