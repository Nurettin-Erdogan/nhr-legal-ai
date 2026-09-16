"""
Yargıtay Kararlar Bankası Scraper
https://kararlarbankasi.yargitay.gov.tr
"""

from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
from datetime import datetime
import re
from .base_scraper import PaginatedScraper


class YargitayScraper(PaginatedScraper):
    """Yargıtay Kararlar Bankası'ndan veri çeker"""
    
    def __init__(self):
        super().__init__(
            site_name="Yargıtay Kararlar Bankası",
            base_url="https://kararlarbankasi.yargitay.gov.tr",
            delay=2.5
        )
        self.search_url = f"{self.base_url}/karararama.aspx"
    
    def scrape(self, page: int = 1, department: str = None) -> List[Dict[str, Any]]:
        """
        Yargıtay kararlarını scrape et
        
        Args:
            page: Sayfa numarası
            department: Daire (Hukuk, Ceza, vb.)
        
        Returns:
            Karar verileri listesi
        """
        kararlar = []
        
        try:
            # Ana liste sayfasını al
            url = f"{self.search_url}?page={page}"
            response = self._get_cloudflare_protected(url)
            
            if not response:
                return kararlar
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Karar satırlarını bul
            decision_rows = soup.find_all('tr', class_='decision-row')
            
            if not decision_rows:
                decision_rows = soup.find_all('table')[0].find_all('tr')[1:]  # Header hariç
            
            for row in decision_rows:
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
            
            if len(tds) < 5:
                return None
            
            # Karar Sayısı
            decision_number = tds[0].get_text(strip=True)
            
            # Daire
            department = tds[1].get_text(strip=True)
            
            # Tarihi
            date_str = tds[2].get_text(strip=True)
            
            # Konu
            subject = tds[3].get_text(strip=True)
            
            # Link
            link_elem = row.find('a', href=True)
            link = link_elem.get('href', '') if link_elem else ""
            link = f"{self.base_url}{link}" if link and link.startswith('/') else link
            
            return {
                'decision_number': decision_number,
                'department': department,
                'date': date_str,
                'subject': subject,
                'url': link,
                'source': 'Yargıtay Kararlar Bankası'
            }
        
        except Exception as e:
            self.logger.error(f"Error parsing decision row: {str(e)}")
            return None
    
    def search_decisions(self, 
                        query: str = None,
                        decision_number: str = None,
                        department: str = None,
                        start_date: str = None,
                        end_date: str = None,
                        max_pages: int = 5) -> List[Dict[str, Any]]:
        """
        Yargıtay kararlarında gelişmiş arama
        
        Args:
            query: Arama terimi
            decision_number: Karar numarası
            department: Daire
            start_date: Başlangıç tarihi (GG/AA/YYYY)
            end_date: Bitiş tarihi (GG/AA/YYYY)
            max_pages: Maksimum sayfa sayısı
        
        Returns:
            Karar listesi
        """
        all_results = []
        
        for page in range(1, max_pages + 1):
            params = {
                'page': page
            }
            
            if query:
                params['arama'] = query
            if decision_number:
                params['kararsayisi'] = decision_number
            if department:
                params['daire'] = department
            if start_date:
                params['tarihbaslangic'] = start_date
            if end_date:
                params['tarihbitis'] = end_date
            
            # URL oluştur
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            url = f"{self.search_url}?{query_string}"
            
            response = self._get_cloudflare_protected(url)
            
            if not response:
                break
            
            soup = BeautifulSoup(response.content, 'html.parser')
            rows = soup.find_all('tr', class_='decision-row')
            
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
        
        # Ana bilgiler
        details = {
            'url': decision_url,
            'scraped_at': datetime.now().isoformat()
        }
        
        # Karar Sayısı
        number_elem = soup.find('span', class_='decision-number')
        details['number'] = number_elem.get_text(strip=True) if number_elem else "N/A"
        
        # Daire
        dept_elem = soup.find('span', class_='department')
        details['department'] = dept_elem.get_text(strip=True) if dept_elem else "N/A"
        
        # Tarihi
        date_elem = soup.find('span', class_='decision-date')
        details['date'] = date_elem.get_text(strip=True) if date_elem else "N/A"
        
        # Başvurucular
        plaintiff_elem = soup.find('div', class_='plaintiff')
        details['plaintiff'] = plaintiff_elem.get_text(strip=True) if plaintiff_elem else "N/A"
        
        # Davalılar
        defendant_elem = soup.find('div', class_='defendant')
        details['defendant'] = defendant_elem.get_text(strip=True) if defendant_elem else "N/A"
        
        # Karar Konusu
        subject_elem = soup.find('div', class_='subject')
        details['subject'] = subject_elem.get_text(strip=True) if subject_elem else "N/A"
        
        # Karar Metni
        decision_text_elem = soup.find('div', class_='decision-text')
        details['decision_text'] = decision_text_elem.get_text(strip=True) if decision_text_elem else "N/A"
        
        # Kanuni Dayanak
        legal_basis_elem = soup.find('div', class_='legal-basis')
        details['legal_basis'] = legal_basis_elem.get_text(strip=True) if legal_basis_elem else "N/A"
        
        return details
    
    def get_by_department(self, department: str, max_pages: int = 10) -> List[Dict[str, Any]]:
        """Daireye göre kararları getir"""
        valid_departments = {
            'hukuk': 'Hukuk Dairesi',
            'ceza': 'Ceza Dairesi',
            'idari': 'İdari Daire',
            'vergi': 'Vergi Dairesi'
        }
        
        if department.lower() not in valid_departments:
            self.logger.warning(f"Invalid department: {department}")
            return []
        
        return self.search_decisions(department=department, max_pages=max_pages)
