"""
Anayasa Mahkemesi Kararlar Bankası Scraper
https://kararlarbankasi.anayasa.gov.tr
"""

from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
from datetime import datetime
import re
from .base_scraper import PaginatedScraper


class AnayasaMahkemesiScraper(PaginatedScraper):
    """Anayasa Mahkemesi Kararlar Bankası'ndan veri çeker"""
    
    def __init__(self):
        super().__init__(
            site_name="Anayasa Mahkemesi",
            base_url="https://kararlarbankasi.anayasa.gov.tr",
            delay=2.5
        )
        self.search_url = f"{self.base_url}/Search"
    
    def scrape(self, page: int = 1, court_type: str = None) -> List[Dict[str, Any]]:
        """
        Anayasa Mahkemesi kararlarını scrape et
        
        Args:
            page: Sayfa numarası
            court_type: Mahkeme türü
        
        Returns:
            Karar verileri listesi
        """
        kararlar = []
        
        try:
            # Arama sayfasını al
            url = f"{self.search_url}?page={page}"
            response = self._get_cloudflare_protected(url)
            
            if not response:
                return kararlar
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Karar satırlarını bul
            decision_table = soup.find('table', class_='decisions-table')
            
            if not decision_table:
                return kararlar
            
            rows = decision_table.find_all('tr')[1:]  # Header'ı atla
            
            for row in rows:
                try:
                    karar_data = self._parse_decision_row(row)
                    if karar_data:
                        kararlar.append(karar_data)
                except Exception as e:
                    self.logger.warning(f"Error parsing decision: {str(e)}")
                    continue
        
        except Exception as e:
            self.logger.error(f"Error scraping page {page}: {str(e)}")
        
        return kararlar
    
    def _parse_decision_row(self, row) -> Optional[Dict[str, Any]]:
        """Karar satırını parse et"""
        try:
            tds = row.find_all('td')
            
            if len(tds) < 4:
                return None
            
            # Başvuru/Karar Numarası
            number = tds[0].get_text(strip=True)
            
            # Tarih
            date_str = tds[1].get_text(strip=True)
            
            # Konu
            subject = tds[2].get_text(strip=True)
            
            # Sonuç/Karar
            result = tds[3].get_text(strip=True) if len(tds) > 3 else "N/A"
            
            # Link
            link_elem = row.find('a', href=True)
            link = link_elem.get('href', '') if link_elem else ""
            link = f"{self.base_url}{link}" if link and link.startswith('/') else link
            
            return {
                'number': number,
                'date': date_str,
                'subject': subject,
                'result': result,
                'url': link,
                'source': 'Anayasa Mahkemesi'
            }
        
        except Exception as e:
            self.logger.error(f"Error parsing decision row: {str(e)}")
            return None
    
    def search_decisions(self,
                        query: str = None,
                        application_number: str = None,
                        decision_type: str = None,
                        start_date: str = None,
                        end_date: str = None,
                        max_pages: int = 5) -> List[Dict[str, Any]]:
        """
        Anayasa Mahkemesi kararlarında arama
        
        Args:
            query: Arama terimi
            application_number: Başvuru numarası
            decision_type: Karar türü (Kabul, Red, vb.)
            start_date: Başlangıç tarihi
            end_date: Bitiş tarihi
            max_pages: Maksimum sayfa sayısı
        
        Returns:
            Karar listesi
        """
        all_results = []
        
        for page in range(1, max_pages + 1):
            params = {'page': page}
            
            if query:
                params['query'] = query
            if application_number:
                params['applicationNumber'] = application_number
            if decision_type:
                params['decisionType'] = decision_type
            if start_date:
                params['startDate'] = start_date
            if end_date:
                params['endDate'] = end_date
            
            # URL oluştur
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            url = f"{self.search_url}?{query_string}"
            
            response = self._get_cloudflare_protected(url)
            
            if not response:
                break
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            decision_table = soup.find('table', class_='decisions-table')
            if not decision_table:
                break
            
            rows = decision_table.find_all('tr')[1:]
            
            if not rows:
                break
            
            for row in rows:
                parsed = self._parse_decision_row(row)
                if parsed:
                    all_results.append(parsed)
        
        self.logger.info(f"Found {len(all_results)} decisions")
        return all_results
    
    def get_decision_details(self, decision_url: str) -> Dict[str, Any]:
        """Kararın tam detaylarını al"""
        response = self._get_cloudflare_protected(decision_url)
        
        if not response:
            return {'error': 'Could not fetch decision'}
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        details = {
            'url': decision_url,
            'scraped_at': datetime.now().isoformat()
        }
        
        # Başvuru Numarası
        app_num_elem = soup.find('span', class_='application-number')
        details['application_number'] = app_num_elem.get_text(strip=True) if app_num_elem else "N/A"
        
        # Karar Numarası
        dec_num_elem = soup.find('span', class_='decision-number')
        details['decision_number'] = dec_num_elem.get_text(strip=True) if dec_num_elem else "N/A"
        
        # Başvuru Tarihi
        app_date_elem = soup.find('span', class_='application-date')
        details['application_date'] = app_date_elem.get_text(strip=True) if app_date_elem else "N/A"
        
        # Karar Tarihi
        dec_date_elem = soup.find('span', class_='decision-date')
        details['decision_date'] = dec_date_elem.get_text(strip=True) if dec_date_elem else "N/A"
        
        # Başvurucular
        petitioner_elem = soup.find('div', class_='petitioner')
        details['petitioner'] = petitioner_elem.get_text(strip=True) if petitioner_elem else "N/A"
        
        # Başvuru Konusu
        subject_elem = soup.find('div', class_='subject')
        details['subject'] = subject_elem.get_text(strip=True) if subject_elem else "N/A"
        
        # Karar Konusu
        decision_subject_elem = soup.find('div', class_='decision-subject')
        details['decision_subject'] = decision_subject_elem.get_text(strip=True) if decision_subject_elem else "N/A"
        
        # Karar Metni
        decision_text_elem = soup.find('div', class_='decision-text')
        details['decision_text'] = decision_text_elem.get_text(strip=True) if decision_text_elem else "N/A"
        
        # Karar Sonucu (Kabul, Red, vb.)
        result_elem = soup.find('span', class_='decision-result')
        details['result'] = result_elem.get_text(strip=True) if result_elem else "N/A"
        
        # İlgili Anayasa Maddeleri
        articles = []
        article_elems = soup.find_all('span', class_='constitution-article')
        for art_elem in article_elems:
            articles.append(art_elem.get_text(strip=True))
        details['constitution_articles'] = articles
        
        return details
    
    def search_by_constitution_article(self, article_number: str, max_pages: int = 10) -> List[Dict[str, Any]]:
        """Anayasa maddesine göre kararları ara"""
        self.logger.info(f"Searching decisions for Constitution Article {article_number}")
        
        all_results = []
        
        for page in range(1, max_pages + 1):
            url = f"{self.search_url}?article={article_number}&page={page}"
            response = self._get_cloudflare_protected(url)
            
            if not response:
                break
            
            soup = BeautifulSoup(response.content, 'html.parser')
            decision_table = soup.find('table', class_='decisions-table')
            
            if not decision_table:
                break
            
            rows = decision_table.find_all('tr')[1:]
            
            if not rows:
                break
            
            for row in rows:
                parsed = self._parse_decision_row(row)
                if parsed:
                    all_results.append(parsed)
        
        return all_results
