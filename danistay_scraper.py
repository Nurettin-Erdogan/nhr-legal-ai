"""
Danıştay Kararlar Scraper
https://kararlar.danistay.gov.tr
"""

from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
from datetime import datetime
import re
from .base_scraper import PaginatedScraper


class DanistayKaralarScraper(PaginatedScraper):
    """Danıştay Kararları'ndan veri çeker"""
    
    def __init__(self):
        super().__init__(
            site_name="Danıştay Kararlar",
            base_url="https://kararlar.danistay.gov.tr",
            delay=2.5
        )
        self.search_url = f"{self.base_url}/search"
    
    def scrape(self, page: int = 1, chamber: str = None) -> List[Dict[str, Any]]:
        """
        Danıştay kararlarını scrape et
        
        Args:
            page: Sayfa numarası
            chamber: Daire (İdari, Vergi, vb.)
        
        Returns:
            Karar verileri listesi
        """
        kararlar = []
        
        try:
            url = f"{self.search_url}?page={page}"
            if chamber:
                url += f"&chamber={chamber}"
            
            response = self._get_cloudflare_protected(url)
            
            if not response:
                return kararlar
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Karar öğelerini bul
            decision_items = soup.find_all('div', class_='decision-item')
            
            if not decision_items:
                # Alternatif: table format
                decision_table = soup.find('table', class_='decisions-table')
                if decision_table:
                    rows = decision_table.find_all('tr')[1:]
                    for row in rows:
                        try:
                            karar_data = self._parse_decision_row(row)
                            if karar_data:
                                kararlar.append(karar_data)
                        except Exception as e:
                            self.logger.warning(f"Error parsing decision: {str(e)}")
                    return kararlar
            
            for item in decision_items:
                try:
                    karar_data = self._parse_decision_item(item)
                    if karar_data:
                        kararlar.append(karar_data)
                except Exception as e:
                    self.logger.warning(f"Error parsing decision: {str(e)}")
                    continue
        
        except Exception as e:
            self.logger.error(f"Error scraping page {page}: {str(e)}")
        
        return kararlar
    
    def _parse_decision_item(self, item) -> Optional[Dict[str, Any]]:
        """Karar öğesini parse et (div format)"""
        try:
            # Karar Numarası
            number_elem = item.find('span', class_='decision-number')
            number = number_elem.get_text(strip=True) if number_elem else "N/A"
            
            # Tarih
            date_elem = item.find('span', class_='date')
            date_str = date_elem.get_text(strip=True) if date_elem else "N/A"
            
            # Daire
            chamber_elem = item.find('span', class_='chamber')
            chamber = chamber_elem.get_text(strip=True) if chamber_elem else "N/A"
            
            # Konu
            subject_elem = item.find('p', class_='subject')
            subject = subject_elem.get_text(strip=True) if subject_elem else "N/A"
            
            # Link
            link_elem = item.find('a', href=True)
            link = link_elem.get('href', '') if link_elem else ""
            link = f"{self.base_url}{link}" if link and link.startswith('/') else link
            
            return {
                'number': number,
                'date': date_str,
                'chamber': chamber,
                'subject': subject,
                'url': link,
                'source': 'Danıştay Kararlar'
            }
        
        except Exception as e:
            self.logger.error(f"Error parsing decision item: {str(e)}")
            return None
    
    def _parse_decision_row(self, row) -> Optional[Dict[str, Any]]:
        """Karar satırını parse et (table format)"""
        try:
            tds = row.find_all('td')
            
            if len(tds) < 4:
                return None
            
            number = tds[0].get_text(strip=True)
            date_str = tds[1].get_text(strip=True)
            chamber = tds[2].get_text(strip=True)
            subject = tds[3].get_text(strip=True)
            
            link_elem = row.find('a', href=True)
            link = link_elem.get('href', '') if link_elem else ""
            link = f"{self.base_url}{link}" if link and link.startswith('/') else link
            
            return {
                'number': number,
                'date': date_str,
                'chamber': chamber,
                'subject': subject,
                'url': link,
                'source': 'Danıştay Kararlar'
            }
        
        except Exception as e:
            self.logger.error(f"Error parsing decision row: {str(e)}")
            return None
    
    def search_decisions(self,
                        query: str = None,
                        case_number: str = None,
                        chamber: str = None,
                        start_date: str = None,
                        end_date: str = None,
                        max_pages: int = 5) -> List[Dict[str, Any]]:
        """
        Danıştay kararlarında arama
        
        Args:
            query: Arama terimi
            case_number: Dava numarası
            chamber: Daire
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
                params['q'] = query
            if case_number:
                params['caseNumber'] = case_number
            if chamber:
                params['chamber'] = chamber
            if start_date:
                params['startDate'] = start_date
            if end_date:
                params['endDate'] = end_date
            
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            url = f"{self.search_url}?{query_string}"
            
            response = self._get_cloudflare_protected(url)
            
            if not response:
                break
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            items = soup.find_all('div', class_='decision-item')
            
            if not items:
                break
            
            for item in items:
                parsed = self._parse_decision_item(item)
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
        
        # Karar Numarası
        number_elem = soup.find('span', class_='decision-number')
        details['number'] = number_elem.get_text(strip=True) if number_elem else "N/A"
        
        # Tarih
        date_elem = soup.find('span', class_='decision-date')
        details['date'] = date_elem.get_text(strip=True) if date_elem else "N/A"
        
        # Daire
        chamber_elem = soup.find('span', class_='chamber')
        details['chamber'] = chamber_elem.get_text(strip=True) if chamber_elem else "N/A"
        
        # Dava Numarası
        case_num_elem = soup.find('span', class_='case-number')
        details['case_number'] = case_num_elem.get_text(strip=True) if case_num_elem else "N/A"
        
        # Başvurucular
        plaintiff_elem = soup.find('div', class_='plaintiff')
        details['plaintiff'] = plaintiff_elem.get_text(strip=True) if plaintiff_elem else "N/A"
        
        # Davalı Kurumlar
        defendant_elem = soup.find('div', class_='defendant')
        details['defendant'] = defendant_elem.get_text(strip=True) if defendant_elem else "N/A"
        
        # Konu
        subject_elem = soup.find('div', class_='subject')
        details['subject'] = subject_elem.get_text(strip=True) if subject_elem else "N/A"
        
        # Karar Metni
        decision_text_elem = soup.find('div', class_='decision-text')
        details['decision_text'] = decision_text_elem.get_text(strip=True) if decision_text_elem else "N/A"
        
        # Kanuni Dayanak
        legal_basis_elem = soup.find('div', class_='legal-basis')
        details['legal_basis'] = legal_basis_elem.get_text(strip=True) if legal_basis_elem else "N/A"
        
        return details
    
    def get_by_chamber(self, chamber: str, max_pages: int = 10) -> List[Dict[str, Any]]:
        """Daireye göre kararları getir"""
        valid_chambers = [
            'İdari',
            'Vergi',
            'Dava Daireleri',
            'İdari İhtilaflar Kurulu'
        ]
        
        if chamber not in valid_chambers:
            self.logger.warning(f"Invalid chamber: {chamber}")
            return []
        
        return self.search_decisions(chamber=chamber, max_pages=max_pages)
