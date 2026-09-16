"""
Resmi Gazete Scraper
https://www.resmigazete.gov.tr
"""

from typing import Dict, List, Any
from bs4 import BeautifulSoup
from datetime import datetime
from .base_scraper import PaginatedScraper


class ResmiGazeteScraper(PaginatedScraper):
    """T.C. Resmi Gazete'den veri çeker"""
    
    def __init__(self):
        super().__init__(
            site_name="Resmi Gazete",
            base_url="https://www.resmigazete.gov.tr",
            delay=2.5
        )
    
    def scrape(self, page: int = 1, query: str = None) -> List[Dict[str, Any]]:
        """
        Resmi Gazete'den gazete sayılarını scrape et
        
        Args:
            page: Sayfa numarası
            query: Arama terimi (opsiyonel)
        
        Returns:
            Gazete verileri listesi
        """
        gazeteler = []
        
        # Resmi Gazete API kullanabiliriz veya HTML scrape edebiliriz
        # Önce API endpoint'i deneyelim
        try:
            # Ana sayfayı al
            url = f"{self.base_url}/pub/page?page={page}"
            response = self._get(url)
            
            if not response:
                return gazeteler
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Gazete bültünlerini bul
            gazette_items = soup.find_all('div', class_='gazette-item')
            
            if not gazette_items:
                # Alternatif selector deneyelim
                gazette_items = soup.find_all('article', class_='gazete')
            
            for item in gazette_items:
                try:
                    gazete_data = self._parse_gazette_item(item)
                    if gazete_data:
                        gazeteler.append(gazete_data)
                except Exception as e:
                    self.logger.warning(f"Error parsing gazette item: {str(e)}")
                    continue
        
        except Exception as e:
            self.logger.error(f"Error scraping page {page}: {str(e)}")
        
        return gazeteler
    
    def _parse_gazette_item(self, item) -> Dict[str, Any]:
        """Gazete öğesini parse et"""
        try:
            # Başlık
            title_elem = item.find('h3', class_='title') or item.find('a', class_='gazette-link')
            title = title_elem.get_text(strip=True) if title_elem else "N/A"
            
            # URL
            link_elem = item.find('a', href=True)
            link = link_elem.get('href', '') if link_elem else ""
            link = f"{self.base_url}{link}" if link.startswith('/') else link
            
            # Tarih
            date_elem = item.find('span', class_='date') or item.find('time')
            date_str = date_elem.get_text(strip=True) if date_elem else "N/A"
            
            # Gazete Sayısı
            number_elem = item.find('span', class_='number')
            number = number_elem.get_text(strip=True) if number_elem else "N/A"
            
            # Tür
            type_elem = item.find('span', class_='type')
            gazette_type = type_elem.get_text(strip=True) if type_elem else "N/A"
            
            return {
                'title': title,
                'number': number,
                'date': date_str,
                'type': gazette_type,
                'url': link,
                'source': 'Resmi Gazete'
            }
        
        except Exception as e:
            self.logger.error(f"Error parsing gazette: {str(e)}")
            return None
    
    def search(self, query: str, max_pages: int = 5) -> List[Dict[str, Any]]:
        """Resmi Gazete'de ara"""
        self.logger.info(f"Searching for: {query}")
        
        all_results = []
        
        for page in range(1, max_pages + 1):
            url = f"{self.base_url}/search?q={query}&page={page}"
            response = self._get(url)
            
            if not response:
                break
            
            soup = BeautifulSoup(response.content, 'html.parser')
            results = soup.find_all('div', class_='search-result')
            
            if not results:
                break
            
            for result in results:
                parsed = self._parse_gazette_item(result)
                if parsed:
                    all_results.append(parsed)
        
        return all_results
    
    def get_gazette_content(self, gazette_url: str) -> Dict[str, Any]:
        """Gazete içeriğini al"""
        response = self._get(gazette_url)
        
        if not response:
            return {'error': 'Could not fetch gazette'}
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # İçeriği ekstrak et
        content_elem = soup.find('div', class_='gazette-content')
        content = content_elem.get_text(strip=True) if content_elem else "N/A"
        
        return {
            'url': gazette_url,
            'content': content,
            'scraped_at': datetime.now().isoformat()
        }
