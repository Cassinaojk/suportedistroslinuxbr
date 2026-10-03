import os, re, json, requests, time, random, io, contextlib, unicodedata, warnings
import builtins

# Log resumido por padrão. Use VERBOSE_LOG=true no GitHub Actions para diagnóstico.
_VERBOSE_LOG = os.getenv("VERBOSE_LOG", "false").lower() in ("1", "true", "yes", "sim")
_original_print = builtins.print

def print(*args, **kwargs):
    if _VERBOSE_LOG:
        return _original_print(*args, **kwargs)

    message = " ".join(str(a) for a in args).strip()
    important = (
        message.startswith("SUPORTE DISTROS LINUX BR - ROBÔ")
        or message.startswith("VERSÃO ")
        or message.startswith("Fontes:")
        or message.startswith("Posts existentes no Blogger:")
        or message.startswith("Fontes já registradas:")
        or message.startswith("Fontes encontradas:")
        or message.startswith("Novas matérias:")
        or message.startswith("Puladas:")
        or message == "RESULTADO"
        or message.startswith("Publicações:")
        or message.startswith("Ignoradas:")
        or message.startswith("Falhas:")
        or message.startswith("✓ Publicada:")
        or message.startswith("✓ Imagem:")
        or message.startswith("✓ SEO:")
        or message.startswith("✓ Labels:")
        or message.startswith("⚠ Blogger:")
        or message.startswith("⚠ IA:")
        or message.startswith("⚠ Gemini:")
        or message.startswith("⚠ Imagem:")
        or message.startswith("⚠ Pulada:")
        or message.startswith("Erro ao consultar Blogger:")
        or message.startswith("Erro:")
    )
    if important:
        return _original_print(*args, **kwargs)

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
from datetime import datetime, date, timezone, timedelta
from urllib.parse import urlparse, urljoin, quote
from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

print("SUPORTE DISTROS LINUX BR - ROBÔ DE NOTÍCIAS 1.0 (SEO Automático)")

BLOGGER_BLOG_ID = os.environ["BLOGGER_BLOG_ID"]
GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
BLOGGER_REFRESH_TOKEN = os.environ["BLOGGER_REFRESH_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# ===== SEO =====
BLOG_NAME = os.getenv("BLOG_NAME", "Suporte Distros Linux BR").strip() or "Suporte Distros Linux BR"
BLOG_HOME_URL = os.getenv("BLOG_HOME_URL", "https://suportedistroslinuxbr.blogspot.com").strip().rstrip("/")
BLOG_LOCALE = os.getenv("BLOG_LOCALE", "pt_BR").strip() or "pt_BR"
BLOG_TWITTER = os.getenv("BLOG_TWITTER", "").strip()
SEO_TITLE_SUFFIX = os.getenv("SEO_TITLE_SUFFIX", f" | {BLOG_NAME}").strip()
SEO_DESCRIPTION_MAX = int(os.getenv("SEO_DESCRIPTION_MAX", "160"))
SEO_KEYWORDS_MAX = int(os.getenv("SEO_KEYWORDS_MAX", "12"))

# Limites
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "1"))
MAX_GEMINI_TEXT_CALLS_PER_RUN = int(os.getenv("MAX_GEMINI_TEXT_CALLS_PER_RUN", "6"))
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_BASE_SECONDS = 4
MAX_LINKS_PER_SOURCE = 80

MAX_AGE_DAYS = 3650

MIN_SOURCE_CHARS = 500
MIN_SOURCE_PARAGRAPHS = 3
TIMEOUT = 25

GEMINI_MODEL_TEXT = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.6-flash")

GEMINI_API_KEY_2 = os.getenv("GEMINI_API_KEY_2", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest").strip()
AI_PROVIDER_TIMEOUT = int(os.getenv("AI_PROVIDER_TIMEOUT", "90"))

# ===== Filtro de Tecnologia/Linux =====
LINUX_TERMS = (
    "linux", "ubuntu", "fedora", "debian", "arch", "manjaro", "mint",
    "opensuse", "red hat", "centos", "kali", "gentoo", "slackware",
    "kernel", "open source", "código aberto", "software livre",
    "gnome", "kde", "xfce", "servidor", "terminal", "bash", "shell",
    "distro", "distribuição", "desktop", "segurança", "hacker",
    "programação", "python", "rust", "c++", "git", "docker",
    "kubernetes", "cloud", "aws", "azure", "google cloud",
    "nvidia", "amd", "intel", "processador", "placa de vídeo",
    "steam", "proton", "gaming", "jogos", "hardware",
)

def _tech_norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value.lower()).strip()

def is_tech_related(article=None, generated=None, raw_text=""):
    article = article or {}
    generated = generated or {}
    parts = [
        article.get("title", ""),
        article.get("text", ""),
        generated.get("titulo", ""),
        generated.get("resumo", ""),
        generated.get("materia", ""),
        raw_text,
    ]
    combined = _tech_norm(" ".join(str(x or "") for x in parts))
    if not combined:
        return False
    return any(term in combined for term in LINUX_TERMS)


# ===== Fontes =====
SOURCES = [
    {
        "nome": "Linux.com",
        "url": "https://www.linux.com/",
        "feeds": [
            "https://www.linux.com/feed/",
        ],
    },
    {
        "nome": "Phoronix",
        "url": "https://www.phoronix.com/",
        "feeds": [
            "https://www.phoronix.com/rss.php",
        ],
    },
    {
        "nome": "LinuxToday",
        "url": "https://www.linuxtoday.com/",
        "feeds": [
            "https://www.linuxtoday.com/feed/",
        ],
    },
]

BAD_PATHS = (
    "/category/", "/tag/", "/author/", "/page/", "/search/", "/feed/",
    "/wp-json/", "/comments/", "/sobre", "/contato", "/contact",
    "/politica", "/privacidade", "/privacy", "/anuncie", "/publicidade",
    "/advertising", "/login", "/cadastro", "/register", "/sitemap", "/robots.txt",
)

SHARE_DOMAINS = (
    "pinterest.", "reddit.com/submit", "facebook.com/sharer",
    "twitter.com/intent", "x.com/intent", "whatsapp.com/",
    "t.me/share", "linkedin.com/share",
)

VIDEO_HOSTS = (
    "youtube.com/embed/",
    "youtube.com/watch",
    "youtube-nocookie.com/embed/",
    "youtu.be/",
    "player.vimeo.com",
    "vimeo.com/video",
    "facebook.com/plugins/video",
    "web.facebook.com/plugins/video",
    "instagram.com/p/",
    "instagram.com/reel/",
    "instagram.com/tv/",
    "dailymotion.com/embed",
    "twitch.tv/",
    "streamable.com/e/",
    "rumble.com/embed",
)

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; SuporteDistrosLinuxBot/1.0)"})

gemini_calls = 0
gemini_quota_hit = False
_ai_config_logged = False

def normalize_url(u):
    if not u:
        return ""
    u = u.strip().split("#")[0]
    u = u.rstrip("/")
    return u


def bad_url(u):
    u = normalize_url(u).lower()
    if not u.startswith(("http://", "https://")):
        return True
    if any(x in u for x in SHARE_DOMAINS):
        return True
    path = urlparse(u).path
    if any(x in path for x in BAD_PATHS):
        return True
    if re.search(r"\.(pdf|jpg|jpeg|png|gif|webp|svg|xml|zip)$", path):
        return True
    return False


def soup(url, xml=False):
    try:
        r = s.get(url, timeout=TIMEOUT)
        print(f"Abrindo: {url}\nHTTP: {r.status_code}")
        if r.status_code != 200:
            return None
        if xml:
            try:
                return BeautifulSoup(r.text, "xml")
            except Exception as e:
                print("Parser XML indisponível; usando parser HTML:", e)
        return BeautifulSoup(r.text, "html.parser")
    except requests.exceptions.SSLError:
        return None
    except Exception as e:
        print("Erro:", e)
        return None


def date_parse(v):
    if not v:
        return None
    value = str(v).strip()
    formats = (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
    )
    for f in formats:
        try:
            d = datetime.strptime(value[:32], f)
            return d.replace(tzinfo=None) if d.tzinfo else d
        except Exception:
            pass
    return None


def article_date(x):
    selectors = (
        'meta[property="article:published_time"]',
        'meta[property="og:published_time"]',
        'meta[name="date"]',
        'meta[name="publish_date"]',
        'meta[itemprop="datePublished"]',
    )
    for sel in selectors:
        n = x.select_one(sel)
        if n:
            d = date_parse(n.get("content", ""))
            if d:
                return d
    for sc in x.find_all("script", type="application/ld+json"):
        try:
            raw = sc.string or sc.get_text()
            data = json.loads(raw)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("@graph"), list):
                    for graph_item in item["@graph"]:
                        if isinstance(graph_item, dict):
                            d = date_parse(graph_item.get("datePublished"))
                            if d:
                                return d
                d = date_parse(item.get("datePublished"))
                if d:
                    return d
        except Exception:
            pass
    for sel in ("time.entry-date", "time.published", "time",
                ".entry-date", ".posted-on"):
        n = x.select_one(sel)
        if n:
            d = date_parse(n.get("datetime") or n.get_text(" ", strip=True))
            if d:
                return d
    return None


def image_original(x):
    values = []
    for sel in (
        'meta[property="og:image"]',
        'meta[name="twitter:image"]',
        'meta[itemprop="image"]',
    ):
        n = x.select_one(sel)
        if n and n.get("content"):
            values.append(n["content"])
    for sel in (
        "article img", ".entry-content img", ".post-content img",
        ".td-post-content img", "main img",
    ):
        for n in x.select(sel)[:10]:
            values.append(
                n.get("src") or n.get("data-src") or n.get("data-lazy-src") or ""
            )
    for u in values:
        u = u.strip()
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith(("http://", "https://")) and not any(
            z in u.lower() for z in ("logo", "avatar", "icon", "favicon")
        ):
            return u
    return ""


def videos(x):
    BLOCK_HOSTS = (
        "doubleclick.net", "googlesyndication.com", "googleadservices.com",
        "adservice.google", "taboola.com", "outbrain.com", "criteo.",
        "pubmatic.", "rubiconproject.", "adnxs.com", "amazon-adsystem.",
        "facebook.com/plugins/post", "instagram.com/embed.js",
    )
    out = []
    for n in x.find_all("iframe"):
        u = (n.get("src") or n.get("data-src") or "").strip()
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith(("http://", "https://")):
            continue
        u_lower = u.lower()
        if any(b in u_lower for b in BLOCK_HOSTS):
            continue
        if not any(host in u_lower for host in VIDEO_HOSTS):
            continue
        style = (n.get("style") or "").lower().replace(" ", "")
        if any(z in style for z in (
            "display:none", "visibility:hidden", "opacity:0", "width:0", "height:0",
        )):
            continue
        try:
            w_attr = (n.get("width") or "").strip()
            h_attr = (n.get("height") or "").strip()
            w = int(re.sub(r"[^\d]", "", w_attr) or "0")
            h = int(re.sub(r"[^\d]", "", h_attr) or "0")
            if (w and w < 100) or (h and h < 100):
                continue
        except Exception:
            pass
        parent_hidden = n.find_parent(
            style=re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
        )
        if parent_hidden:
            continue
        if u not in out:
            out.append(u)
    return out[:3]


# ============================================================
# ARTIGO
# ============================================================

def get_article(url):
    x = soup(url)
    if not x:
        return None

    n = x.find("h1") or x.find("title")
    title = re.sub(r"\s+", " ", n.get_text(" ", strip=True) if n else "").strip()
    if not title:
        return None

    title_lower = title.lower()
    index_titles = {
        "lançamentos", "notícias", "noticias", "home", "início", "inicio",
        "últimas notícias", "ultimas noticias", "404",
        "página não encontrada", "pagina nao encontrada",
    }
    if title_lower in index_titles:
        print("Página de índice/categoria. Pulando.")
        return None

    d = article_date(x)
    if d:
        print("Data encontrada:", d)
        age = (datetime.now() - d).total_seconds() / 86400
        if age > MAX_AGE_DAYS:
            print(f"Notícia muito antiga ({age:.1f} dias). Pulando.")
            return None
    else:
        print("Data não identificada. Aceitando para análise.")

    img = image_original(x) or ""

    box = x.find("article") or x.find("main") or x
    paragraphs = []
    for p in box.find_all("p"):
        text = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
        if len(text) >= 35:
            paragraphs.append(text)
    text = "\n\n".join(paragraphs)

    if len(text) < MIN_SOURCE_CHARS or len(paragraphs) < MIN_SOURCE_PARAGRAPHS:
        print(f"Conteúdo insuficiente: {len(text)} caracteres; {len(paragraphs)} parágrafos")
        return None

    link_count = len(box.find_all("a"))
    if len(text) < 1000 and link_count > len(paragraphs) * 4:
        print("Página parece índice/listagem. Pulando.")
        return None

    vv = videos(x)
    print("Notícia encontrada:", title)
    print("Texto extraído:", len(text), "caracteres")
    if vv:
        print(f"Vídeos válidos encontrados: {len(vv)}")

    return {
        "url": normalize_url(url),
        "title": title,
        "date": d,
        "image": img,
        "text": text[:16000],
        "videos": vv,
    }


def links(source):
    out = []
    seen = set()
    source_host = urlparse(source["url"]).netloc.lower()

    def host_matches(u):
        h = urlparse(u).netloc.lower()
        if h == source_host:
            return True
        if h.endswith("." + source_host):
            return True
        h_no_www = h.replace("www.", "", 1)
        s_no_www = source_host.replace("www.", "", 1)
        return h_no_www == s_no_www or h_no_www.endswith("." + s_no_www)

    for feed in source["feeds"]:
        x = soup(feed, True)
        if not x:
            continue
        for item in x.find_all(["item", "entry"]):
            n = item.find("link")
            if not n:
                continue
            u = n.get("href") or n.get_text(strip=True) or ""
            u = normalize_url(u)
            if not u or bad_url(u):
                continue
            if not host_matches(u):
                continue
            if u not in seen:
                seen.add(u)
                out.append(u)

    x = soup(source["url"])
    if x:
        for a in x.find_all("a", href=True):
            u = urljoin(source["url"], a["href"])
            u = normalize_url(u)
            if bad_url(u):
                continue
            if not host_matches(u):
                continue
            if u not in seen:
                seen.add(u)
                out.append(u)

    print(f"Links encontrados em {source['nome']}: {len(out)}")
    return out[:MAX_LINKS_PER_SOURCE]


def blogger():
    credentials = Credentials(
        None,
        refresh_token=BLOGGER_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/blogger"],
    )
    return build("blogger", "v3", credentials=credentials, cache_discovery=False)


def existing(api, show_log=True):
    blog_urls = set()
    source_urls = set()
    token = None
    try:
        while True:
            kwargs = {
                "blogId": BLOGGER_BLOG_ID,
                "maxResults": 500,
                "fetchBodies": True,
            }
            if token:
                kwargs["pageToken"] = token
            data = api.posts().list(**kwargs).execute()
            for post in data.get("items", []):
                post_url = normalize_url(post.get("url", ""))
                if post_url:
                    blog_urls.add(post_url)
                content = post.get("content", "") or ""
                for match in re.findall(
                    r'href=["\'](https?://[^"\']+)["\']', content, flags=re.I
                ):
                    source_urls.add(normalize_url(match))
                for match in re.findall(
                    r'SUPORTE_DISTROS_LINUX_BR_SOURCE_URL:\s*(https?://[^\s]+?)\s*-->',
                    content, flags=re.I,
                ):
                    source_urls.add(normalize_url(match))
            token = data.get("nextPageToken")
            if not token:
                break
    except Exception as e:
        print("Erro ao consultar Blogger:", e)
    if show_log:
        print("Posts existentes no Blogger:", len(blog_urls))
        print("Fontes já registradas:", len(source_urls))
    return blog_urls, source_urls


# ============================================================
# IA
# ============================================================

def is_transient_gemini_error(exc):
    msg = str(exc).upper()
    return any(code in msg for code in (
        "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
        "500", "502", "504", "TIMEOUT",
    ))


def gemini_request(client, model, prompt):
    last_error = None
    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                return client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )
        except Exception as e:
            last_error = e
            msg = str(e).upper()
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                raise
            if not is_transient_gemini_error(e) or attempt >= GEMINI_MAX_RETRIES:
                raise
            delay = GEMINI_RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 2)
            time.sleep(delay)
    raise last_error


def norm_words(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.findall(r"[a-z0-9]+", text)


def ngrams(words, n=8):
    return {" ".join(words[i:i+n]) for i in range(max(0, len(words)-n+1))}


def longest_common_phrase(src_words, out_words, min_words=15):
    if not src_words or not out_words:
        return 0
    positions = {}
    for i, word in enumerate(src_words):
        positions.setdefault(word, []).append(i)
    best = 0
    for j, word in enumerate(out_words):
        for i in positions.get(word, [])[:20]:
            k = 0
            while i+k < len(src_words) and j+k < len(out_words) and src_words[i+k] == out_words[j+k]:
                k += 1
            best = max(best, k)
            if best >= min_words:
                return best
    return best


def originality_check(source_text, generated_text):
    src = norm_words(source_text)
    out = norm_words(generated_text)
    if len(out) < 100:
        return False, "matéria curta demais"
    src8 = ngrams(src, 8)
    out8 = ngrams(out, 8)
    overlap = len(src8 & out8) / max(1, min(len(src8), len(out8)))
    longest = longest_common_phrase(src, out)
    if longest >= 15:
        return False, f"há sequência de {longest} palavras iguais"
    if overlap > 0.12:
        return False, f"sobreposição 8-gram alta ({overlap:.3f})"
    return True, "OK"


def _ai_extract_text(provider, response):
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return str(content).strip()


def _provider_is_quota_error(status_code, body):
    text = str(body or "").upper()
    return status_code == 429 or any(x in text for x in (
        "RESOURCE_EXHAUSTED", "RATE LIMIT", "RATE_LIMIT", "QUOTA",
        "TOO MANY REQUESTS", "DAILY LIMIT", "LIMIT EXCEEDED",
    ))


def _call_http_provider(provider, api_key, model, prompt):
    endpoint = {
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "mistral": "https://api.mistral.ai/v1/chat/completions",
    }.get(provider)
    if not endpoint:
        raise ValueError(f"Provedor HTTP desconhecido: {provider}")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 5000,
        "response_format": {"type": "json_object"},
    }
    if provider == "groq":
        payload["include_reasoning"] = False
    r = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=AI_PROVIDER_TIMEOUT,
    )
    body = r.text[:1200]
    if _provider_is_quota_error(r.status_code, body):
        raise RuntimeError(f"QUOTA_HTTP_{r.status_code}: {body}")
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP_{r.status_code}: {body}")
    try:
        return r.json()
    except Exception as exc:
        raise RuntimeError(f"Resposta JSON inválida do {provider}: {exc}")


def _build_ai_providers():
    providers = []
    if GEMINI_API_KEY:
        providers.append(("gemini", GEMINI_API_KEY, GEMINI_MODEL_TEXT))
    if GEMINI_API_KEY_2:
        providers.append(("gemini-2", GEMINI_API_KEY_2, GEMINI_FALLBACK_MODEL))
    if GROQ_API_KEY:
        providers.append(("groq", GROQ_API_KEY, GROQ_MODEL))
    if MISTRAL_API_KEY:
        providers.append(("mistral", MISTRAL_API_KEY, MISTRAL_MODEL))
    return providers


def _provider_request(provider, api_key, model, prompt):
    if provider.startswith("gemini"):
        return gemini_request(genai.Client(api_key=api_key), model, prompt)
    return _call_http_provider(provider, api_key, model, prompt)


def _provider_text(provider, response):
    if provider.startswith("gemini"):
        return (getattr(response, "text", None) or "").strip()
    return _ai_extract_text(provider, response)


def _is_quota_exception(exc):
    msg = str(exc).upper()
    return any(x in msg for x in (
        "429", "RESOURCE_EXHAUSTED", "QUOTA", "RATE LIMIT", "RATE_LIMIT",
        "TOO MANY REQUESTS", "DAILY LIMIT", "LIMIT EXCEEDED",
    ))


def gemini(article, client=None):
    global gemini_calls, gemini_quota_hit, _ai_config_logged
    if gemini_calls >= MAX_GEMINI_TEXT_CALLS_PER_RUN:
        print("⚠ IA: limite de chamadas desta execução atingido.")
        return None

    providers = _build_ai_providers()
    if not _ai_config_logged:
        print(
            "IA: "
            f"Gemini={'SIM' if GEMINI_API_KEY else 'NÃO'} | "
            f"Gemini-2={'SIM' if GEMINI_API_KEY_2 else 'NÃO'} | "
            f"Groq={'SIM' if GROQ_API_KEY else 'NÃO'} | "
            f"Mistral={'SIM' if MISTRAL_API_KEY else 'NÃO'}"
        )
        _ai_config_logged = True
    if not providers:
        print("⚠ IA: nenhuma chave configurada.")
        return None

    prompt = f"""
Você é um jornalista especializado em tecnologia, Linux e Open Source.
Sua tarefa é escrever uma matéria NOVA e ORIGINAL, em português do Brasil.

REGRAS CRÍTICAS:
1. TRADUZA e escreva OBRIGATORIAMENTE em português do Brasil. Traduza nomes técnicos quando houver tradução consagrada (ex: "kernel" -> "núcleo", mas "kernel" também é aceito).
2. Use SOMENTE os fatos presentes no texto-fonte.
3. Não invente nomes, datas, números, locais, declarações ou acontecimentos.
4. Não acrescente informações externas.
5. Crie título, resumo e matéria em português do Brasil.
6. A matéria deve ter aproximadamente 700 a 1200 palavras.
7. Não diga que foi escrita por IA.

REGRAS DE CONTEÚDO:
- Foque em notícias de Linux, distribuições, open source, hardware, segurança, programação e tecnologia.
- Se a matéria for sobre um assunto completamente alheio a tecnologia, marque publicar=false.
- Caso contrário, marque publicar=true.

OUTRAS REGRAS:
- título novo e jornalístico;
- resumo de 2 a 3 frases;
- não copiar frases ou parágrafos da fonte;
- não traduzir nem reproduzir a estrutura da matéria original;
- retornar SOMENTE JSON válido, sem Markdown;
- no campo "assunto_principal", informe o NOME DA PESSOA, EMPRESA OU PROJETO mais importante citado na matéria (ex.: "Linus Torvalds", "Canonical", "KDE Plasma").
- no campo "palavras_chave", informe uma lista com 5 a 10 palavras-chave de SEO relacionadas ao conteúdo.
- no campo "categoria_seo", informe a categoria principal do assunto: "Linux", "Open Source", "Distribuições", "Hardware", "Segurança", "Programação", "Notícia Tech".

FORMATO:
{{"publicar":true,"titulo":"...","resumo":"...","materia":"...","assunto_principal":"...","palavras_chave":["..."],"categoria_seo":"..."}}

TÍTULO ORIGINAL:
{article['title']}

FONTE:
{article['url']}

TEXTO-FONTE:
{article['text']}
"""

    exhausted = set()
    last_reason = "erro"
    for pass_index in range(2):
        pass_prompt = prompt if pass_index == 0 else prompt + """

ATENÇÃO: a versão anterior foi rejeitada por originalidade. Faça uma nova
redação, reorganizando completamente a ordem das informações e variando as
construções das frases. Não repita sequências da fonte.
"""
        for provider, api_key, model in providers:
            if gemini_calls >= MAX_GEMINI_TEXT_CALLS_PER_RUN:
                break
            if provider in exhausted:
                continue
            try:
                print(f"IA: tentando {provider} / {model}...")
                response = _provider_request(provider, api_key, model, pass_prompt)
                gemini_calls += 1
                raw = _provider_text(provider, response)
                if not raw:
                    last_reason = "resposta vazia"
                    print(f"⚠ {provider}: resposta vazia.")
                    continue
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
                data = json.loads(raw)
                if data.get("publicar") is False:
                    last_reason = "sem informação suficiente"
                    print(f"⚠ {provider}: marcou a matéria como não publicável; tentando próximo provedor.")
                    continue
                titulo = str(data.get("titulo", "")).strip()
                resumo = str(data.get("resumo", "")).strip()
                materia = str(data.get("materia", "")).strip()
                assunto = str(data.get("assunto_principal", "")).strip()
                palavras_chave = data.get("palavras_chave", []) or []
                if isinstance(palavras_chave, str):
                    palavras_chave = [p.strip() for p in palavras_chave.split(",") if p.strip()]
                categoria_seo = str(data.get("categoria_seo", "")).strip()
                if not titulo or not resumo or len(materia) < 700:
                    last_reason = "resposta inválida"
                    print(f"⚠ {provider}: resposta inválida ou curta demais.")
                    continue
                ok, reason = originality_check(article["text"], titulo + "\n" + resumo + "\n" + materia)
                if not ok:
                    last_reason = "originalidade"
                    print(f"⚠ {provider}: matéria recusada por originalidade ({reason}) — tentando outra IA.")
                    continue
                print(f"✓ IA: matéria aprovada ({provider} / {model}, tentativa {pass_index + 1})")
                if assunto:
                    print(f"✓ IA: assunto principal identificado: {assunto}")
                return {
                    "publicar": True,
                    "titulo": titulo,
                    "resumo": resumo,
                    "materia": materia,
                    "assunto_principal": assunto,
                    "palavras_chave": palavras_chave[:SEO_KEYWORDS_MAX],
                    "categoria_seo": categoria_seo,
                }
            except Exception as exc:
                if _is_quota_exception(exc):
                    exhausted.add(provider)
                    last_reason = "quota"
                    print(f"⚠ {provider}: quota/limite atingido — passando para o próximo provedor.")
                else:
                    last_reason = "erro"
                    print(f"⚠ {provider}: erro na geração: {str(exc)[:240]}")

    if last_reason == "quota":
        gemini_quota_hit = True
        print("⚠ IA: provedores disponíveis atingiram quota/limite; restante ficará para a próxima execução")
    elif last_reason == "originalidade":
        print("⚠ IA: todas as tentativas foram recusadas por originalidade")
    elif last_reason == "sem informação suficiente":
        print("⚠ IA: provedores não consideraram a fonte suficiente para publicação")
    elif last_reason in ("resposta inválida", "resposta_invalida"):
        print("⚠ IA: geração retornou formato inválido")
    else:
        print("⚠ IA: nenhum provedor disponível conseguiu gerar a matéria")
    return None


# ============================================================
# SEO AUTOMÁTICO
# ============================================================

def _strip_html(text):
    return re.sub(r"\s+", " ", BeautifulSoup(str(text or ""), "html.parser").get_text(" ", strip=True)).strip()


def _truncate(text, limit):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.6:
        cut = cut[:last_space]
    return cut.rstrip(" ,;:-") + "..."


def build_seo_payload(article, generated, final_image="", image_origin=""):
    titulo_base = str(generated.get("titulo", "")).strip()
    resumo = str(generated.get("resumo", "")).strip()
    materia = str(generated.get("materia", "")).strip()
    assunto = str(generated.get("assunto_principal", "")).strip()
    categoria_seo = str(generated.get("categoria_seo", "")).strip()
    palavras = list(generated.get("palavras_chave", []) or [])

    title = titulo_base
    if SEO_TITLE_SUFFIX and not title.lower().endswith(SEO_TITLE_SUFFIX.lower()):
        title = f"{titulo_base}{SEO_TITLE_SUFFIX}"

    base_desc = resumo or _strip_html(materia)[:SEO_DESCRIPTION_MAX]
    description = _truncate(base_desc, SEO_DESCRIPTION_MAX)

    kw = []
    if assunto:
        kw.append(assunto)
    if categoria_seo:
        kw.append(categoria_seo)
    for p in palavras:
        p = str(p).strip()
        if p and p.lower() not in {k.lower() for k in kw}:
            kw.append(p)
    for fallback in ("linux", "open source", "tecnologia", "notícias de tecnologia", BLOG_NAME):
        if fallback.lower() not in {k.lower() for k in kw}:
            kw.append(fallback)
    keywords = ", ".join(kw[:SEO_KEYWORDS_MAX])

    labels = ["Notícias", "Tecnologia", "Linux", "Open Source"]
    if categoria_seo:
        cat_clean = re.sub(r"\s+", " ", categoria_seo).strip()
        if cat_clean and cat_clean not in labels:
            labels.append(cat_clean)
    if assunto:
        assunto_clean = re.sub(r"\s+", " ", assunto).strip()
        if assunto_clean and assunto_clean not in labels and len(assunto_clean) <= 40:
            labels.append(assunto_clean)
    if article.get("date"):
        labels.append(str(article["date"].year))

    seen = set()
    labels_final = []
    for l in labels:
        l = str(l).strip()
        if not l:
            continue
        key = l.lower()
        if key in seen:
            continue
        seen.add(key)
        labels_final.append(l)
    labels_final = labels_final[:10]

    image_url = final_image or article.get("image", "")
    canonical = article.get("url", "")

    published = (article.get("date") or datetime.now()).isoformat()
    date_modified = datetime.now().isoformat()

    schema = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": canonical,
        },
        "headline": titulo_base[:110],
        "description": description,
        "image": [image_url] if image_url else [],
        "datePublished": published,
        "dateModified": date_modified,
        "author": {
            "@type": "Organization",
            "name": BLOG_NAME,
            "url": BLOG_HOME_URL,
        },
        "publisher": {
            "@type": "Organization",
            "name": BLOG_NAME,
            "url": BLOG_HOME_URL,
            "logo": {
                "@type": "ImageObject",
                "url": image_url or f"{BLOG_HOME_URL}/favicon.ico",
            },
        },
        "articleSection": categoria_seo or "Tecnologia",
        "keywords": keywords,
        "inLanguage": "pt-BR",
        "isAccessibleForFree": True,
        "url": canonical,
        "sourceOrganization": {
            "@type": "Organization",
            "name": urlparse(article.get("url", "")).netloc,
            "url": article.get("url", ""),
        },
    }

    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Início", "item": BLOG_HOME_URL},
            {"@type": "ListItem", "position": 2, "name": "Notícias", "item": f"{BLOG_HOME_URL}/search/label/Not%C3%ADcias"},
            {"@type": "ListItem", "position": 3, "name": titulo_base[:80], "item": canonical},
        ],
    }

    safe_title = (
        title.replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )
    safe_desc = (
        description.replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )
    safe_keywords = (
        keywords.replace("&", "&amp;").replace('"', "&quot;")
    )
    safe_canonical = (
        canonical.replace("&", "&amp;").replace('"', "&quot;")
    )
    safe_image = (
        (image_url or "").replace("&", "&amp;").replace('"', "&quot;")
    )
    twitter_site = f'<meta name="twitter:site" content="{BLOG_TWITTER}">' if BLOG_TWITTER else ""

    json_ld_article = json.dumps(schema, ensure_ascii=False)
    json_ld_breadcrumb = json.dumps(breadcrumb, ensure_ascii=False)

    html_head = f"""<!-- ===== SEO SUPORTE DISTROS LINUX BR ===== -->
<title>{safe_title}</title>
<meta name="description" content="{safe_desc}">
<meta name="keywords" content="{safe_keywords}">
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">
<meta name="author" content="{BLOG_NAME}">
<meta name="language" content="Portuguese">
<meta name="revisit-after" content="1 days">
<meta name="rating" content="general">
<meta name="distribution" content="global">
<link rel="canonical" href="{safe_canonical}">

<!-- Open Graph -->
<meta property="og:type" content="article">
<meta property="og:site_name" content="{BLOG_NAME}">
<meta property="og:title" content="{safe_title}">
<meta property="og:description" content="{safe_desc}">
<meta property="og:url" content="{safe_canonical}">
<meta property="og:locale" content="{BLOG_LOCALE}">
{f'<meta property="og:image" content="{safe_image}">' if safe_image else ''}
{f'<meta property="og:image:width" content="1200">' if safe_image else ''}
{f'<meta property="og:image:height" content="630">' if safe_image else ''}
<meta property="article:published_time" content="{published}">
<meta property="article:modified_time" content="{date_modified}">
<meta property="article:section" content="{schema['articleSection']}">
{f'<meta property="article:tag" content="{assunto}">' if assunto else ''}

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{safe_title}">
<meta name="twitter:description" content="{safe_desc}">
{f'<meta name="twitter:image" content="{safe_image}">' if safe_image else ''}
{twitter_site}

<!-- Schema.org NewsArticle -->
<script type="application/ld+json">{json_ld_article}</script>

<!-- Schema.org BreadcrumbList -->
<script type="application/ld+json">{json_ld_breadcrumb}</script>
<!-- ===== FIM SEO ===== -->"""

    return {
        "title": title,
        "titulo_base": titulo_base,
        "description": description,
        "keywords": keywords,
        "labels": labels_final,
        "canonical": canonical,
        "schema": schema,
        "breadcrumb": breadcrumb,
        "html_head": html_head,
        "source_url": article.get("url", ""),
        "assunto": assunto,
        "categoria_seo": categoria_seo,
    }


def build_seo_head_for_blogger(seo):
    return seo.get("html_head", "")


# ============================================================
# HTML DO POST
# ============================================================

def html(article, generated, final_image="", image_origin="", seo=None):
    seo = seo or {}
    titulo_exibicao = seo.get("titulo_base") or generated.get("titulo", "")
    safe_title = (
        titulo_exibicao
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    image_url = final_image or article["image"]
    safe_image = image_url.replace("&", "&amp;").replace('"', "&quot;")

    safe_source_url = (
        article["url"]
        .replace("&", "&amp;")
        .replace('"', "&quot;")
    )

    seo_head = build_seo_head_for_blogger(seo)

    content = []

    if seo_head:
        content.append(seo_head)

    content.extend([
        f'<p><strong>{generated["resumo"]}</strong></p>',
        (
            f'<p><img src="{safe_image}" '
            f'alt="{safe_title}" '
            f'title="{safe_title}" '
            f'width="1200" height="630" '
            f'style="max-width:100%;height:auto;border-radius:12px;">'
            f'</p>'
        ),
    ])

    article_paragraphs = []
    for paragraph in re.split(r"\n+", generated["materia"]):
        paragraph = paragraph.strip()
        if paragraph:
            article_paragraphs.append(paragraph)

    for index, paragraph in enumerate(article_paragraphs):
        content.append(f"<p>{paragraph}</p>")

    for video_url in article["videos"]:
        content.append(
            '<div style="margin:24px 0;padding:0;">'
            '<div style="position:relative;width:100%;padding-bottom:56.25%;'
            'height:0;overflow:hidden;border-radius:12px;'
            'box-shadow:0 4px 12px rgba(0,0,0,0.15);">'
            f'<iframe src="{video_url}" '
            'style="position:absolute;top:0;left:0;width:100%;height:100%;'
            'border:0;" '
            'frameborder="0" '
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; '
            'gyroscope; picture-in-picture; web-share" '
            'allowfullscreen '
            'loading="lazy" '
            'title="Vídeo da matéria">'
            '</iframe>'
            '</div>'
            '</div>'
        )

    # Banner de divulgação do blog (opcional, mas mantido limpo)
    source_marker = f"<!-- SUPORTE_DISTROS_LINUX_BR_SOURCE_URL: {safe_source_url} -->"
    image_marker = ""
    if image_origin:
        image_marker = f"\n<!-- SUPORTE_DISTROS_LINUX_BR_IMAGE_SOURCE: {image_origin} -->"

    seo_marker = ""
    if seo:
        seo_marker = (
            f"\n<!-- SUPORTE_DISTROS_LINUX_BR_SEO_DESCRIPTION: {seo.get('description','')[:300]} -->"
            f"\n<!-- SUPORTE_DISTROS_LINUX_BR_SEO_KEYWORDS: {seo.get('keywords','')[:300]} -->"
        )

    return "\n".join(content) + "\n" + source_marker + image_marker + seo_marker


def main():
    print("Fontes: Linux.com + Phoronix + LinuxToday | Tradução automática para PT-BR")
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    api = blogger()
    old_blog_urls, old_source_urls = existing(api)

    candidates = []
    candidate_urls = set()
    source_counts = {}
    prefiltered_out = 0

    for source in SOURCES:
        source_links = links(source)
        source_counts[source["nome"]] = len(source_links)
        for url in source_links:
            normalized = normalize_url(url)
            if normalized in candidate_urls or normalized in old_blog_urls or normalized in old_source_urls:
                continue
            article = get_article(normalized)
            if article:
                if not is_tech_related(article=article):
                    prefiltered_out += 1
                    continue
                candidate_urls.add(normalized)
                candidates.append(article)

    source_summary = " | ".join(f"{name}: {count}" for name, count in source_counts.items())
    print(f"Fontes encontradas: {source_summary}")
    print(f"Puladas: {prefiltered_out}")

    candidates.sort(key=lambda a: a["date"] or datetime.min, reverse=True)
    print(f"Novas matérias de tecnologia: {len(candidates)}")

    published = 0
    failed = 0
    ignored = 0

    while candidates and published < MAX_POSTS_PER_RUN:
        article = candidates.pop(0)
        normalized = normalize_url(article["url"])
        if normalized in old_source_urls:
            ignored += 1
            continue

        if gemini_calls >= MAX_GEMINI_TEXT_CALLS_PER_RUN:
            print("⚠ Gemini: limite desta execução atingido; restante ficará para a próxima execução")
            break

        generated = gemini(article, gemini_client)
        if not generated:
            ignored += 1
            if gemini_quota_hit:
                break
            continue

        # Usa a imagem original do artigo
        final_image = article.get("image", "")
        if not final_image:
            print("⚠ Imagem: artigo sem imagem original. Publicando sem imagem.")
            final_image = "https://images.unsplash.com/photo-1629654297299-c8506221ca97?w=1200&h=630&fit=crop"
        
        image_origin = "Imagem original da fonte"
        print(f"✓ Imagem final: {image_origin}")

        seo = build_seo_payload(
            article=article,
            generated=generated,
            final_image=final_image,
            image_origin=image_origin,
        )
        print(f"✓ SEO: título final = {seo['title'][:90]}")
        print(f"✓ SEO: description = {seo['description'][:120]}...")
        print(f"✓ SEO: keywords = {seo['keywords'][:160]}")
        print(f"✓ Labels: {', '.join(seo['labels'])}")

        try:
            post_body = {
                "title": seo["title"].strip(),
                "content": html(article, generated, final_image=final_image,
                                image_origin=image_origin, seo=seo),
                "labels": seo["labels"],
            }

            try:
                post_body["customMetaData"] = seo["description"]
            except Exception:
                pass

            response = api.posts().insert(
                blogId=BLOGGER_BLOG_ID,
                body=post_body,
                isDraft=False,
            ).execute()

            published += 1
            old_source_urls.add(normalized)
            if response.get("url"):
                old_blog_urls.add(normalize_url(response["url"]))
                try:
                    new_url = response["url"]
                    if new_url and new_url != seo["canonical"]:
                        updated_content = html(
                            article, generated,
                            final_image=final_image,
                            image_origin=image_origin,
                            seo={**seo, "canonical": new_url},
                        )
                        api.posts().patch(
                            blogId=BLOGGER_BLOG_ID,
                            postId=response["id"],
                            body={"content": updated_content},
                        ).execute()
                        print(f"✓ SEO: canonical atualizado para {new_url}")
                except Exception as canon_exc:
                    print(f"⚠ SEO: não foi possível atualizar canonical: {canon_exc}")

            print(f"✓ Publicada: {seo['title'].strip()}")
        except Exception as exc:
            failed += 1
            print(f"⚠ Blogger: falha ao publicar ({str(exc)[:200]})")

    print("RESULTADO")
    print(f"Publicações: {published}")
    print(f"Ignoradas: {ignored}")
    print(f"Falhas: {failed}")


print("VERSÃO 1.0 ATIVA: Tradução automática PT-BR | imagens e vídeos originais | SEO automático | Blogger")

main()
