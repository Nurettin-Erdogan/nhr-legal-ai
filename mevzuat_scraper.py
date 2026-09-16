"""
Mevzuat Bilgi Sistemi Scraper
https://www.mevzuat.gov.tr
"""

from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
from datetime import datetime
import re
from .base_scraper import PaginatedScraper


class MevzuatScraper(PaginatedScraper):
    """T.C. Cumhubaşkanlığı Mevzuat Bilgi Sistemi'nden veri çeker"""
    
    def __init__(self):
        super().__init__(
            site_name="Mevzuat Bilgi Sistemi",
            base_url="https://www.mevzuat.gov.tr",
            delay=2.5
        )
    
    def scrape(self, page: int = 1, category: str = None) -> List[Dict[str, Any]]:
        """
        Mevzuatı scrape et
        
        Args:
            page: Sayfa numarası
            category: Kategori (Kanunlar, Yönetmelikler, vb.)
        
        Returns:
            Mevzuat verileri listesi
        """
        mevzuatlar = []
        
        try:
            # URL oluştur
            if category:
                url = f"{self.base_url}/Act?page={page}&category={category}"
            else:
                url = f"{self.base_url}/Act?page={page}"
            
            response = self._get(url)
            
            if not response:
                return mevzuatlar
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Mevzuat listesini bul
            mevzuat_items = soup.find_all('div', class_='act-item')
            
            if not mevzuat_items:
                # Alternatif selector
                mevzuat_items = soup.find_all('tr', class_='act-row')
            
            for item in mevzuat_items:
                try:
                    mevzuat_data = self._parse_mevzuat_item(item)
                    if mevzuat_data:
                        mevzuatlar.append(mevzuat_data)
                except Exception as e:
                    self.logger.warning(f"Error parsing mevzuat: {str(e)}")
                    continue
        
        except Exception as e:
            self.logger.error(f"Error scraping page {page}: {str(e)}")
        
        return mevzuatlar
    
    def _parse_mevzuat_item(self, item) -> Optional[Dict[str, Any]]:
        """Mevzuat öğesini parse et"""
        try:
            # Mevzuat adı
            title_elem = item.find('a', class_='act-link') or item.find('h4')
            if not title_elem:
                title_elem = item.find('td', class_='title')
            
            title = title_elem.get_text(strip=True) if title_elem else "N/A"
            
            # URL
            link_elem = item.find('a', href=True)
            link = link_elem.get('href', '') if link_elem else ""
            link = f"{self.base_url}{link}" if link and link.startswith('/') else link
            
            # Mevzuat Numarası
            number_elem = item.find('span', class_='number') or item.find('td', class_='number')
            number = number_elem.get_text(strip=True) if number_elem else "N/A"
            
            # Tarih
            date_elem = item.find('span', class_='date') or item.find('td', class_='date')
            date_str = date_elem.get_text(strip=True) if date_elem else "N/A"
            
            # Tür (Kanun, Yönetmelik, vb.)
            type_elem = item.find('span', class_='type') or item.find('td', class_='type')
            mevzuat_type = type_elem.get_text(strip=True) if type_elem else "N/A"
            
            # Durum (Yürürlükte, İlga, vb.)
            status_elem = item.find('span', class_='status')
            status = status_elem.get_text(strip=True) if status_elem else "Yürürlükte"
            
            return {
                'title': title,
                'number': number,
                'date': date_str,
                'type': mevzuat_type,
                'status': status,
                'url': link,
                'source': 'Mevzuat Bilgi Sistemi'
            }
        
        except Exception as e:
            self.logger.error(f"Error parsing mevzuat item: {str(e)}")
            return None
    
    def search_mevzuat(self, query: str, max_pages: int = 5) -> List[Dict[str, Any]]:
        """Mevzuat ara"""
        self.logger.info(f"Searching for: {query}")
        
        all_results = []
        
        for page in range(1, max_pages + 1):
            url = f"{self.base_url}/Search/OpenAdvanced?q={query}&page={page}"
            response = self._get(url)
            
            if not response:
                break
            
            soup = BeautifulSoup(response.content, 'html.parser')
            results = soup.find_all('div', class_='search-result-item')
            
            if not results:
                break
            
            for result in results:
                parsed = self._parse_mevzuat_item(result)
                if parsed:
                    all_results.append(parsed)
        
        return all_results
    
    def get_mevzuat_details(self, mevzuat_url: str) -> Dict[str, Any]:
        """Mevzuatın tam detaylarını al"""
        response = self._get(mevzuat_url)
        
        if not response:
            return {'error': 'Could not fetch mevzuat'}
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Başlık
        title_elem = soup.find('h1', class_='act-title')
        title = title_elem.get_text(strip=True) if title_elem else "N/A"
        
        # Mevzuat Numarası ve Tarihi
        meta_elem = soup.find('div', class_='act-meta')
        number = "N/A"
        date = "N/A"
        
        if meta_elem:
            # Metatag'lardan bilgi al
            number_span = meta_elem.find('span', class_='number')
            date_span = meta_elem.find('span', class_='date')
            
            number = number_span.get_text(strip=True) if number_span else "N/A"
            date = date_span.get_text(strip=True) if date_span else "N/A"
        
        # Maddeler
        articles = []
        article_elems = soup.find_all('div', class_='article')
        
        for article_elem in article_elems:
            article_number = article_elem.find('span', class_='article-number')
            article_content = article_elem.find('div', class_='article-content')
            
            if article_number and article_content:
                articles.append({
                    'number': article_number.get_text(strip=True),
                    'content': article_content.get_text(strip=True)
                })
        
        # Tam metin
        text_elem = soup.find('div', class_='act-content')
        content = text_elem.get_text(strip=True) if text_elem else "N/A"
        
        return {
            'title': title,
            'number': number,
            'date': date,
            'articles': articles,
            'content': content,
            'url': mevzuat_url,
            'scraped_at': datetime.now().isoformat()
        }
    
    def get_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Kategoriye göre mevzuat al"""
        self.logger.info(f"Fetching {category}")
        
        valid_categories = [
            'Kanun',
            'Cumhuribaşkanlığı Kararnamesi',
            'Bakanlar Kurulu Kararnamesi',
            'Yönetmelik',
            'Tebliğ',
            'Genelge',
            'İçtüzük'
        ]
        
        if category not in valid_categories:
            self.logger.warning(f"Invalid category: {category}")
            return []
        
        return self.scrape_all_pages(max_pages=10, category=category)
