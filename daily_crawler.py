import random
import re

import requests
import time

from playwright.sync_api import sync_playwright

WEB_APP_URL = "https://script.google.com/macros/s/AKfycbxEBCTatqBA-kyEkbuf3iO03DsmUVxji6gjsy2A4swNyRtmlE1aa4GVHyffIM6O7ksB/exec"
QUERY = "Lập trình viên"
LOCATION = "Thành phố Hồ Chí Minh"
card_selector = "div.job_seen_beacon"   

def clean_salary_text(text):
    if not text or text == "N/A":
        return "N/A"
    
    text = text.lower().strip()
    
    text = text.replace("một tháng", "").replace("một năm", "").strip()
    
    # Xử lý định dạng 11000K -> 11.000.000
    if 'k' in text:
        # Tìm tất cả các số đi với K
        numbers = re.findall(r"(\d+)k", text)
        for num in numbers:
            # Chuyển 11000K thành 11.000.000 để dễ nhìn hơn trên Sheet
            formatted_num = "{:,.0f}".format(float(num) * 1000).replace(",", ".")
            text = text.replace(f"{num}k", formatted_num)
            
    return text.upper() # Trả về VND cho đẹp

class Crawler:
    def __init__(self, query, location, pages):
        self.query = query
        self.location = location
        self.data = []
        self.seen_ids = self.get_existing_job_keys()
        self.pages = pages
        self.playwright, self.browser, self.context, self.page = None, None, None, None
        
    def prepare_playwright(self):        
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        self.page = self.context.new_page()
    def get_existing_job_keys(self):
        try:
            params = {"sheetName": self.query}
            response = requests.get(WEB_APP_URL, params=params, timeout=3000)
            
            if response.status_code == 200:
                data = response.json()
                return set(data.get("ids", []))
            else:
                print(f"Failed to fetch existing job keys. Status code: {response.status_code}")
                return set()
        except Exception as e:
            print(f"Error fetching existing job keys: {e}")
            return set()
    
    def fetch_job_detail(self, browser_context, job_key):
        detail_url = f"https://vn.indeed.com/viewjob?jk={job_key}"
        detail_page = None
        try:
            detail_page = browser_context.new_page()
            detail_page.goto(detail_url, wait_until="networkidle", timeout=45000)
            time.sleep(random.uniform(3, 7))  # Random sleep to mimic human behavior
            
            description_selector = detail_page.query_selector("#jobDescriptionText")
            if description_selector is None:
                return "N/A", "Unknown"
            
            description_text = description_selector.inner_text().lower()
            full_html = detail_page.content().lower()
            salary = "N/A"
            
            money_regex = r"(\d+[\d.,]*\s*(?:K|k|triệu|tr|vnđ|vnd|usd|\$))"
            
            match = re.search(money_regex, description_text)
            if match:
                salary = clean_salary_text(match.group(0))
            elif "thỏa thuận" in description_text:
                salary = "Thỏa thuận"
                
            # Lấy Apply Method
            apply_method = "Apply on Company Site"
            if "indeedapplybutton" in full_html or "nộp đơn ngay" in description_text or "apply now" in description_text:
                apply_method = "Apply Now with Indeed"
                
            return salary, apply_method
        except Exception as e:
            print(f"Error fetching job details from {detail_url}: {e}")
            return "N/A", "Unknown"
        finally:
            if detail_page:
                detail_page.close() # Đóng trang chi tiết sau khi lấy xong để tiết kiệm tài nguyên

    def crawl(self):
        for p in range(self.pages):
            start = p * 10
            indeed_url = f"https://vn.indeed.com/jobs?q={self.query}&l={self.location}&start={start}"
            print(f"🚀 Đang quét trang {p + 1}: {indeed_url}")
            
            try:
                self.page.goto(indeed_url, wait_until="domcontentloaded", timeout=90000)
                self.page.wait_for_timeout(3000)  # Wait for 5 seconds to ensure the page is fully loaded
                
                cards = self.page.query_selector_all(card_selector)
                
                for card in cards:
                    #  Scroll to the card to ensure it's in view
                    card.scroll_into_view_if_needed()
                    
                    title_link = card.query_selector("h2.jobTitle a")
                    
                    # Extract jk as job key in URL query parameter
                    if title_link:
                        job_key = title_link.get_attribute("data-jk")
                        
                        if job_key in self.seen_ids:
                            continue
                        
                        job_title = title_link.inner_text().strip()
                        
                        job_company = card.query_selector("[data-testid='company-name']").inner_text().strip() if card.query_selector("[data-testid='company-name']") else "N/A"
                        job_location = card.query_selector("[data-testid='text-location']").inner_text().strip() if card.query_selector("[data-testid='text-location']") else "N/A"
                        
                        job_link = f"https://vn.indeed.com/viewjob?jk={job_key}" if job_key else "N/A"
                        easily_apply = "Yes" if (card.query_selector("[data-testid='indeedApply']") or "nộp đơn" in card.inner_text().lower() or "apply" in card.inner_text().lower()) else "No"
                        time.sleep(random.uniform(1, 5))  # Random sleep to mimic human behavior
                        
                        salary = "N/A"
                        apply_method = "Unknown"
                        
                        salary_on_card = card.query_selector("[data-testid*='salary-snippet']").inner_text().strip() if card.query_selector("[data-testid*='salary-snippet']") else "N/A"
                        
                        if salary_on_card != "N/A":
                            salary = clean_salary_text(salary_on_card)
                        else:
                            salary, apply_method = self.fetch_job_detail(self.context, job_key)
                            
                        job_data = {
                            "key": job_key,
                            "title": job_title,
                            "company": job_company,
                            "location": job_location,
                            "salary": salary,
                            "link": job_link,
                            "page": p + 1,
                            "easily_apply": easily_apply,
                            "apply_method": apply_method
                        }
                        
                        self.data.append(job_data)
                        self.seen_ids.add(job_key)
                        print(f"✅ Found: {job_title} at {job_company} - {salary} - Apply Method: {apply_method}")
                time.sleep(random.uniform(10, 40))  # Random sleep between page navigations
                        
            except Exception as e:
                print(f"Error navigating to {indeed_url}: {e}")
                return

    def send_data(self):
        payload = { "sheetName": QUERY, "jobs": self.data }
        response = requests.post(WEB_APP_URL, json=payload, timeout=30)
        return response.status_code
    
    def run(self):
        self.prepare_playwright()
        
        self.crawl()
        
        if self.data:
            print(f"Sending {len(self.data)} job listings to Google Sheets...")
            status_code = self.send_data()
            if status_code == 200:
                print("Data sent successfully!")
            else:
                print(f"Failed to send data. Status code: {status_code}")
        else:
            print("No job listings found to send.")
            
        self.close()

    def close(self):
        self.browser.close()
        self.playwright.stop()
        
def main():
    crawler = Crawler(QUERY, LOCATION, pages=2)
    crawler.run()
    
if __name__ == "__main__":
    main()