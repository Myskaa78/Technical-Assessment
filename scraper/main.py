from contextlib import asynccontextmanager
import ipaddress
import logging
import socket
import urllib.parse
from typing import Any, Dict, List, Optional
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, status
import httpx
from playwright.async_api import async_playwright, Browser, Playwright
from pydantic import BaseModel, HttpUrl
import trafilatura

#config Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scraper-microservice")

playwright_driver: Optional[Playwright] = None
browser_instance: Optional[Browser] = None


# chromium et playwright pour recuperer le JS de la page
@asynccontextmanager
async def lifespan(app: FastAPI):
    global playwright_driver, browser_instance
    try:
        playwright_driver = await async_playwright().start()
        #set up des privilege du chromium
        browser_instance = await playwright_driver.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        logger.info("Chromium Playwright démarré avec succès pour le rendu dynamique.")
    except Exception as exc:
        logger.warning(f"Initialisation Playwright au démarrage échouée : {exc}")
    yield
    if browser_instance:
        try:
            await browser_instance.close()
        except Exception:
            pass
    if playwright_driver:
        try:
            await playwright_driver.stop()
        except Exception:
            pass


app = FastAPI(
    title="Web Scraper Microservice",
    description="Microservice FastAPI de web scraping haute performance avec protection SSRF et respect des robots.txt",
    version="2.0.0",
    lifespan=lifespan,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT_SECONDS = 10.0


# --- DTO  Pydantic ---

class ScrapeRequest(BaseModel):
    url: str
    dynamic: bool = False


class MediaImage(BaseModel):
    url: str
    alt: Optional[str] = None


class MediaVideo(BaseModel):
    url: str
    type: str


class ScrapeMetadata(BaseModel):
    author: Optional[str] = None
    publishedAt: Optional[str] = None
    language: Optional[str] = None


class ScrapeResponse(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    text: str
    images: List[MediaImage] = []
    videos: List[MediaVideo] = []
    metadata: ScrapeMetadata


# --- SSRF secu

def validate_ssrf(url_str: str) -> urllib.parse.ParseResult:
    """
    Valide l Url pour prevent le Forgery
    Resout NDD + verification que l'ip n'est pas privée ou en loopback
    """
    try:
        parsed = urllib.parse.urlparse(url_str)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL malformée : {str(exc)}",
        )

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Protocole non autorisé : '{parsed.scheme}'. Seuls http et https sont acceptés",
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="L'URL n'a pas de nom d' hote valide",
        )

    # Résolution DNS avoir toutes les addr IP
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        logger.warning(f"Échec de résolution DNS pour {hostname}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Impossible de résoudre le NDD: '{hostname}'.",
        )

    # Get toutes les addr ip du NDD 
    for entry in addr_info:
        # Get l'adrr ip de l addr_socket 
        ip_str = entry[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_unspecified
                or ip_obj.is_reserved
                or ip_obj.is_link_local
            ):
                logger.warning(
                    f"Tentative SSRF bloquée vers l'hote:  {hostname} résolu sur l'ip: {ip_str}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Interdiction de requêter le réseau local ou les adresses IP privées/loopback (SSRF Protection).",
                )
        except ValueError:
            continue

    return parsed


# --- Étape B : Courtoisie (robots.txt) ---

async def verify_robots_txt(parsed_url: urllib.parse.ParseResult, full_url: str) -> None:
    """
    Vérifie le fichier robot.txt pour qu'il ne scrap pas san l'autorisation du site 
    """
    robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
    rfp = RobotFileParser()
    rfp.set_url(robots_url)

    try:
        # async socket tcp propre
        # Client asynchrone pour ne pas bloquer l'event loop d'Uvicorn
        # mets une signature de navigateur au user agent pour ne pas se faire flagged directement
        async with httpx.AsyncClient(
            timeout=5.0,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            res = await client.get(robots_url)
            if res.status_code == 200:
                rfp.parse(res.text.splitlines())
            elif res.status_code in (401, 403):
                rfp.disallow_all = True
            else:
                # 404 pas de fichier on considere qu'il n y a pas de fichier
                rfp.allow_all = True
    except Exception as exc:
        logger.info(f"Fichier robots.txt inaccessible pour {parsed_url.netloc} ({exc}), autorisation par défaut.")
        rfp.allow_all = True

    # est ce que le bot peut il aller sur l'Url 
    if not rfp.can_fetch("*", full_url):
        logger.warning(f"Scraping interdit par robots.txt pour {full_url}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Scraping interdit par le fichier robots.txt du domaine cible.",
        )


# - Endpoint Health Check 

@app.get("/")
def health_check():
    return {"status": "ok", "service": "scraper", "version": "2.0.0"}


# rendu dynamique playwright chronium

async def render_dynamic_page(url: str, timeout_seconds: float = 15.0) -> tuple[str, str]:
    """
    ON recuperer le JS de la page via le navigateur Chromium 
    Retourne (html_rendu, final_url)
    """
    global browser_instance, playwright_driver
    if not browser_instance:
        playwright_driver = await async_playwright().start()
        browser_instance = await playwright_driver.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )

    # playwright new window without cache or cookie 
    context = await browser_instance.new_context(
        user_agent=USER_AGENT,
        locale="fr-FR",
    )
    try:
        page = await context.new_page()
        timeout_ms = int(timeout_seconds * 1000)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Délai d'attente dépassé lors du rendu JavaScript ({timeout_seconds}s) : {str(exc)}",
            )

        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

        final_url = page.url
        html = await page.content()
        return html, final_url
    finally:
        await context.close()


# extraire differnte data

def extract_metadata(soup: BeautifulSoup) -> dict:
    #Extrait le Title
    title: Optional[str] = None
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        title = title_tag.get_text(strip=True)
    if not title:
        og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()

    # Extrait la description
    description: Optional[str] = None
    meta_desc = (
        soup.find("meta", attrs={"name": "description"})
        or soup.find("meta", attrs={"property": "description"})
    )
    if meta_desc and meta_desc.get("content"):
        description = meta_desc["content"].strip()
    if not description:
        og_desc = (
            soup.find("meta", property="og:description")
            or soup.find("meta", attrs={"name": "og:description"})
        )
        if og_desc and og_desc.get("content"):
            description = og_desc["content"].strip()

    # Ecctrait la balise lang
    language: Optional[str] = None
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        language = html_tag.get("lang").strip()

    # get different meta data 
    author: Optional[str] = None
    meta_author = (
        soup.find("meta", attrs={"name": "author"})
        or soup.find("meta", property="article:author")
        or soup.find("meta", attrs={"name": "article:author"})
        or soup.find("meta", property="og:article:author")
        or soup.find("meta", attrs={"name": "twitter:creator"})
    )
    if meta_author and meta_author.get("content"):
        author = meta_author["content"].strip()

    # Extrait la date de publication si cest un article 
    published_at: Optional[str] = None
    meta_date = (
        soup.find("meta", property="article:published_time")
        or soup.find("meta", attrs={"name": "article:published_time"})
        or soup.find("meta", property="og:published_time")
        or soup.find("meta", attrs={"name": "publication_date"})
        or soup.find("meta", attrs={"name": "date"})
        or soup.find("meta", attrs={"name": "DC.date.issued"})
        or soup.find("time", datetime=True)
    )
    if meta_date:
        if meta_date.name == "time":
            published_at = meta_date.get("datetime", "").strip() or meta_date.get_text(strip=True)
        elif meta_date.get("content"):
            published_at = meta_date["content"].strip()

    return {
        "title": title,
        "description": description,
        "language": language,
        "author": author,
        "publishedAt": published_at,
    }


def extract_images(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Optional[str]]]:
    # Extrait les image 
    images: List[Dict[str, Optional[str]]] = []
    seen_images = set()

    for img in soup.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        src = src.strip()
        if src.startswith("data:"):
            continue

        abs_url = urllib.parse.urljoin(base_url, src)
        if not abs_url.startswith(("http://", "https://")):
            continue

        if abs_url not in seen_images:
            seen_images.add(abs_url)
            alt = img.get("alt")
            alt_clean = alt.strip() if alt and isinstance(alt, str) else None
            images.append({
                "url": abs_url,
                "alt": alt_clean,
            })

    return images


def extract_videos(soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
    # Extrait des video, leurs sources et les iframes (youtube, vimeo)
    videos: List[Dict[str, str]] = []
    seen_videos = set()

    for video in soup.find_all("video"):
        # Source directe sur la balise <video>
        v_src = video.get("src")
        if v_src and not v_src.strip().startswith("data:"):
            abs_v_url = urllib.parse.urljoin(base_url, v_src.strip())
            if abs_v_url.startswith(("http://", "https://")) and abs_v_url not in seen_videos:
                seen_videos.add(abs_v_url)
                videos.append({
                    "url": abs_v_url,
                    "type": video.get("type", "video/mp4"),
                })

        # on verifie la srouces dans video pour ne pas rater un media video
        for source in video.find_all("source"):
            s_src = source.get("src")
            # Ignored pour eviter les videos encoder directement sur le site 
            if s_src and not s_src.strip().startswith("data:"):
                absolu_url = urllib.parse.urljoin(base_url, s_src.strip())
                # on evite les doublons 
                if absolu_url.startswith(("http://", "https://")) and absolu_url not in seen_videos:
                    seen_videos.add(absolu_url)
                    videos.append({
                        "url": absolu_url,
                        "type": source.get("type", "video/mp4"),
                    })

    for iframe in soup.find_all("iframe"):
        i_src = iframe.get("src")
        if not i_src:
            continue
        i_src = i_src.strip()
        abs_i_url = urllib.parse.urljoin(base_url, i_src)
        if not abs_i_url.startswith(("http://", "https://")):
            continue

        lower_url = abs_i_url.lower()
        if "youtube.com" in lower_url or "youtu.be" in lower_url:
            if abs_i_url not in seen_videos:
                seen_videos.add(abs_i_url)
                videos.append({
                    "url": abs_i_url,
                    "type": "youtube"})
        elif "vimeo.com" in lower_url:
            if abs_i_url not in seen_videos:
                seen_videos.add(abs_i_url)
                videos.append({
                    "url": abs_i_url,
                    "type": "vimeo"})

    return videos


# - Route Post de scrape

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(payload: ScrapeRequest):
    url = payload.url.strip()

    # Verification du SSRF
    parsed_url = validate_ssrf(url)

    # Verification des droits aux scrapping dans le robot .txt
    await verify_robots_txt(parsed_url, url)

    if payload.dynamic:
        html, base_url = await render_dynamic_page(url, timeout_seconds=15.0)
    else:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS),
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
                },
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Délai d'attente dépassé lors de la récupération de la page ({REQUEST_TIMEOUT_SECONDS}s).",
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Erreur réseau lors de la récupération de l'URL cible : {str(exc)}",
            )

        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code if response.status_code < 500 else status.HTTP_502_BAD_GATEWAY,
                detail=f"Le serveur cible a répondu avec le statut HTTP {response.status_code}.",
            )

        # Verification du content-type text/html
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Type de contenu non supporté : '{content_type}'. Seul 'text/html' est autorisé.",
            )

        html = response.text

        #  On reprend response.url au cas ou il y aurait eu des redirections 
        base_url = str(response.url)

    # extraction du contenue recuperé

    # trafilatura pour supprimer le bruit de la page 
    extracted_text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
    )
    main_text = extracted_text if extracted_text else ""

    # si le texte est vide et on a pas de SPA on tente le rendu JS
    if not payload.dynamic and not main_text and ('id="root"' in html or 'id="app"' in html or "javascript" in html.lower()):
        logger.info(f"Détection d'une coquille SPA vide pour {url}, fallback automatique vers Playwright...")
        try:
            dyn_html, dyn_base_url = await render_dynamic_page(url, timeout_seconds=15.0)
            dyn_text = trafilatura.extract(dyn_html, include_comments=False, include_tables=True)
            if dyn_text:
                html = dyn_html
                base_url = dyn_base_url
                main_text = dyn_text
        except Exception as exc:
            logger.warning(f"Échec du fallback dynamique pour {url}: {exc}")

    # BeautifulSoup pour tranformer en arbre de donner plus facile a naviguer 
    soup = BeautifulSoup(html, "lxml")

    base_tag = soup.find("base", href=True)
    # si le site a mis en place la balise Base on l utilsie
    if base_tag:
        base_url = urllib.parse.urljoin(base_url, base_tag["href"].strip())

    metadata = extract_metadata(soup)
    images = extract_images(soup, base_url)
    videos = extract_videos(soup, base_url)

    return {
        "url": payload.url,
        "title": metadata["title"],
        "description": metadata["description"],
        "text": main_text,
        "images": images,
        "videos": videos,
        "metadata": {
            "author": metadata["author"],
            "publishedAt": metadata["publishedAt"],
            "language": metadata["language"],
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
