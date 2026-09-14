"""
JurisAI - Yargıtay Karar Scraper (Production Versiyonu)
Playwright ile dinamik elemanları yönetir, DOM yerine gerçek payload ve eventleri bekler.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('yargitay_scraper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("YargitayScraper")


class ProductionYargitayScraper:
    def __init__(
        self,
        daire_adi: str = "9. Hukuk Dairesi",
        storage_path: str = "./yargitay_data",
        headless: bool = True,
        timeout: int = 45000
    ):
        self.daire_adi = daire_adi
        self.base_url = "https://karararama.yargitay.gov.tr"
        self.storage_path = Path(storage_path) / daire_adi.replace(" ", "_").lower()
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.timeout = timeout
        self.metadata_file = self.storage_path / "metadata.json"
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> Dict:
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "total_saved": 0,
            "saved_kararlar": []
        }

    def _save_metadata(self):
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    async def _safe_save_decision(self, decision_data: Dict) -> bool:
        """Kararı anında diske JSON olarak basar (bellekte biriktirmez)."""
        karar_no = decision_data.get("karar_no", "bilinmeyen").replace("/", "_").replace(" ", "")
        esas_no = decision_data.get("esas_no", "bilinmeyen").replace("/", "_").replace(" ", "")
        
        if karar_no in self.metadata["saved_kararlar"]:
            return False

        filename = f"{karar_no}_E_{esas_no}.json"
        filepath = self.storage_path / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(decision_data, f, ensure_ascii=False, indent=2)

        self.metadata["saved_kararlar"].append(karar_no)
        self.metadata["total_saved"] += 1
        self._save_metadata()
        return True

    async def scrape(self, search_keyword: str = "", max_decisions: int = 500):
        logger.info(f"Scraper başlatılıyor: {self.daire_adi} | Hedef: {max_decisions} karar")

        async with async_playwright() as p:
            # Gerçek bir tarayıcı taklidi (Anti-bot bypass)
            browser = await p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            try:
                logger.info(f"Ana sayfaya bağlanılıyor: {self.base_url}")
                await page.goto(self.base_url, timeout=self.timeout, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                # Detaylı Arama panelini aç (Portal açılışında arama butonları)
                # Yargıtay portalındaki arama kutusu ve dinamik alanlar:
                search_input = page.locator("#aranan")
                if await search_input.count() > 0:
                    await search_input.fill(search_keyword)
                
                # Arama butonuna tıkla
                search_btn = page.locator("#btnArama")
                await search_btn.click()
                logger.info("Arama tetiklendi, sonuç listesi bekleniyor...")

                # Sonuçların DOM'a yüklenmesini bekle
                await page.wait_for_selector(".search-result, .karar-listesi, .panel-group", timeout=self.timeout)
                await page.wait_for_timeout(2000)

                saved_count = 0
                page_idx = 1

                while saved_count < max_decisions:
                    logger.info(f"Sayfa {page_idx} taranıyor...")

                    # Liste içerisindeki tüm tıklanabilir karar satırlarını al
                    # Yargıtay listelemesinde satırlar panel başlıklarıdır
                    decision_rows = page.locator(".panel-heading, .karar-row")
                    row_count = await decision_rows.count()

                    if row_count == 0:
                        logger.warning("Sayfada karar bulunamadı veya sonuçlar bitti.")
                        break

                    for i in range(row_count):
                        if saved_count >= max_decisions:
                            break

                        try:
                            row = decision_rows.nth(i)
                            header_text = await row.inner_text()

                            # Karar detayını açmak için satıra tıkla (Accordion yapısı)
                            await row.click()
                            await page.wait_for_timeout(500)

                            # Açılan panel gövdesini yakala
                            body_locator = page.locator(".panel-body, .karar-icerik").nth(i)
                            decision_html = await body_locator.inner_html()
                            decision_text = await body_locator.inner_text()

                            # Temel metadata ayıklama
                            decision_data = {
                                "daire": self.daire_adi,
                                "header_info": header_text.strip(),
                                "esas_no": "",  # Regex modülü parse edecek
                                "karar_no": f"K_{page_idx}_{i}_{int(time.time())}",
                                "karar_tarihi": "",
                                "raw_text": decision_text.strip(),
                                "raw_html": decision_html,
                                "scraped_at": datetime.now().isoformat()
                            }

                            saved = await self._safe_save_decision(decision_data)
                            if saved:
                                saved_count += 1
                                logger.info(f"[{saved_count}/{max_decisions}] Karar kaydedildi.")

                        except Exception as item_err:
                            logger.error(f"Satır çekilirken hata: {item_err}")
                            continue

                    # Sayfalama (Sonraki Sayfa Butonu)
                    next_btn = page.locator("a:has-text('»'), .pagination-next, #btnNext")
                    if await next_btn.count() > 0 and await next_btn.is_visible():
                        await next_btn.click()
                        page_idx += 1
                        await page.wait_for_timeout(3000)
                    else:
                        logger.info("Son sayfaya gelindi.")
                        break

            except PlaywrightTimeoutError:
                logger.error("Sayfa zaman aşımına uğradı (Timeout). Portal yavaş yanıt veriyor olabilir.")
            except Exception as e:
                logger.error(f"Beklenmeyen akış hatası: {e}")
            finally:
                await context.close()
                await browser.close()
                logger.info(f"İşlem bitti. Toplam indirilen karar: {self.metadata['total_saved']}")


if __name__ == "__main__":
    scraper = ProductionYargitayScraper(
        daire_adi="9. Hukuk Dairesi",
        storage_path="./yargitay_data",
        headless=False,  # İlk çalıştırmada portalın DOM yapısını izlemek için False tutun
        timeout=40000
    )
    asyncio.run(scraper.scrape(search_keyword="kıdem tazminatı", max_decisions=50))