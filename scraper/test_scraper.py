import unittest
from bs4 import BeautifulSoup
from fastapi import HTTPException

from main import (
    validate_ssrf,
    extract_metadata,
    extract_images,
    extract_videos,
)


class TestScraperSimple(unittest.TestCase):
    """
    Tests unitaires simples pour le microservice de scraping Python.
    Vérifie la sécurité (SSRF) et les fonctions d'extraction HTML.
    """

    def test_ssrf_bloque_localhost(self):
        """1. Sécurité : vérifie que localhost est bloqué (HTTP 403)."""
        with self.assertRaises(HTTPException) as ctx:
            validate_ssrf("http://localhost:8000")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_ssrf_bloque_ip_privee(self):
        """2. Sécurité : vérifie que l'IP 127.0.0.1 est bloquée (HTTP 403)."""
        with self.assertRaises(HTTPException) as ctx:
            validate_ssrf("http://127.0.0.1:3000")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_ssrf_rejette_url_invalide(self):
        """3. Erreur : vérifie qu'un protocole non supporté (ftp://) est rejeté (HTTP 400)."""
        with self.assertRaises(HTTPException) as ctx:
            validate_ssrf("ftp://example.com/fichier.txt")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_extraction_metadonnees(self):
        """4. Extraction : vérifie l'extraction du titre, description, auteur et langue."""
        html = """
        <html lang="fr">
        <head>
            <title>Mon Titre d'Article</title>
            <meta name="description" content="Une description simple pour le test">
            <meta name="author" content="Jean Dupont">
        </head>
        <body>
            <h1>Article</h1>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        metadata = extract_metadata(soup)

        self.assertEqual(metadata["title"], "Mon Titre d'Article")
        self.assertEqual(metadata["description"], "Une description simple pour le test")
        self.assertEqual(metadata["author"], "Jean Dupont")
        self.assertEqual(metadata["language"], "fr")

    def test_extraction_images_et_liens_absolus(self):
        """5. Images : transforme les liens relatifs en liens absolus et supprime les doublons."""
        html = """
        <html>
        <body>
            <img src="/photo1.jpg" alt="Première photo">
            <img src="/photo1.jpg" alt="Photo en doublon">
            <img src="https://cdn.example.com/photo2.jpg" alt="Deuxième photo">
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        images = extract_images(soup, base_url="https://example.com")

        # Doit contenir exactement 2 images (le doublon a été supprimé)
        self.assertEqual(len(images), 2)
        # Le chemin relatif /photo1.jpg est devenu absolu
        self.assertEqual(images[0]["url"], "https://example.com/photo1.jpg")
        self.assertEqual(images[0]["alt"], "Première photo")
        self.assertEqual(images[1]["url"], "https://cdn.example.com/photo2.jpg")

    def test_extraction_videos(self):
        """6. Vidéos : extrait les balises vidéo et les embeds YouTube."""
        html = """
        <html>
        <body>
            <video src="/media/video.mp4" type="video/mp4"></video>
            <iframe src="https://www.youtube.com/embed/12345"></iframe>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        videos = extract_videos(soup, base_url="https://example.com")

        self.assertEqual(len(videos), 2)
        self.assertEqual(videos[0]["url"], "https://example.com/media/video.mp4")
        self.assertEqual(videos[1]["url"], "https://www.youtube.com/embed/12345")
        self.assertEqual(videos[1]["type"], "youtube")


if __name__ == "__main__":
    unittest.main()
