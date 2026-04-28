import random
import re

import requests
import time

from playwright.sync_api import sync_playwright

WEB_APP_URL = "https://script.google.com/macros/s/AKfycbxEBCTatqBA-kyEkbuf3iO03DsmUVxji6gjsy2A4swNyRtmlE1aa4GVHyffIM6O7ksB/exec"
QUERY = "Lập trình viên"
LOCATION = "Thành phố Hồ Chí Minh"
card_selector = "div.job_seen_beacon"   

money_patterns = [
    # 1. Range: 10 - 20 triệu, 2500k–3000k
    r"(\d+[\d.,]*\s*(?:-|–|to)\s*\d+[\d.,]*\s*(?:k|triệu|tr|vnđ|vnd|usd|\$))",
    # 2. From / Up to
    r"(?:from|từ)\s*\d+[\d.,]*\s*(?:k|triệu|tr|vnđ|vnd|usd|\$)",
    r"(?:up to|đến)\s*\d+[\d.,]*\s*(?:k|triệu|tr|vnđ|vnd|usd|\$)",

    # 3. Single value
    r"(\d+[\d.,]*\s*(?:k|triệu|tr|vnđ|vnd|usd|\$))",

    # 4. Có chữ “lương”
    r"(lương[:\s]*\d+[\d.,]*.*?(?:k|triệu|tr|vnđ|vnd|usd|\$))",

    # 5. Có /tháng /month /year
    r"(\d+[\d.,]*\s*(?:k|triệu|tr|usd|\$)\s*/\s*(?:tháng|month|năm|year))",
    
    # 6. Có chữ “khoảng”
    r"(khoảng\s*\d+[\d.,]*\s*(?:k|triệu|tr|vnđ|vnd|usd|\$))",
]

def extract_salary(text):
    if not text or text == "N/A":
        return "N/A"
    
    text = text.lower().strip()
    
    for pattern in money_patterns:
        match = re.search(pattern, text)
        if match:
            return clean_salary_text(match.group(0))
    
    return "N/A"

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
        def block_resources(route):
            if route.request.resource_type in ["image", "font", "media"]:
                route.abort()
            else:
                route.continue_()

        self.context.route("**/*", block_resources)
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
    def crawl(self):
        for p in range(self.pages):
            start = p * 10
            indeed_url = f"https://vn.indeed.com/jobs?q={self.query}&l={self.location}&start={start}"
            print(f"🚀 Đang quét trang {p + 1}: {indeed_url}")
            
            try:
                self.page.goto(indeed_url, wait_until="domcontentloaded", timeout=90000)
                self.page.wait_for_timeout(3000)  # Wait for 3 seconds to ensure the page is fully loaded
                
                cards = self.page.query_selector_all(card_selector)
                
                for card in cards:
                    title_link = card.query_selector("h2.jobTitle a")
                    
                    if not title_link:
                        continue
                    
                    # Click on the title link for the right card to load the job detail in the side panel
                    
                    job_key = title_link.get_attribute("data-jk")
                    
                    if job_key in self.seen_ids:
                        continue
                    
                     # Tạm thời chặn tất cả các request để tránh bị timeout khi mở trang chi tiết
                    
                    job_title = title_link.inner_text().strip()
                    
                    job_company = card.query_selector("[data-testid='company-name']").inner_text().strip() if card.query_selector("[data-testid='company-name']") else "N/A"
                    job_location = card.query_selector("[data-testid='text-location']").inner_text().strip() if card.query_selector("[data-testid='text-location']") else "N/A"
                    
                    job_link = f"https://vn.indeed.com/viewjob?jk={job_key}" if job_key else "N/A"
                    easily_apply = "Yes" if (
                        card.locator("[data-testid='indeedApply']").count() > 0 or
                        card.locator("text=Dễ dàng nộp đơn").count() > 0
                    ) else "No"
                    time.sleep(random.uniform(1, 5))  # Random sleep to mimic human behavior
                    
                    salary = "N/A"
                    apply_method = "Unknown"
                    
                    salary_on_card = card.query_selector("[data-testid*='salary-snippet']").inner_text().strip() if card.query_selector("[data-testid*='salary-snippet']") else "N/A"
                    
                    if salary_on_card != "N/A":
                        salary = clean_salary_text(salary_on_card)
                    else:
                        title_link.scroll_into_view_if_needed()
                        title_link.click()
                        self.page.wait_for_timeout(300)  # Wait for 2 seconds to allow the side panel to load
                        
                        self.page.locator("#jobDescriptionText").first.wait_for()

                        try:
                            apply_btn = self.page.locator("#applyButtonLinkContainer button")
                            apply_btn.wait_for(timeout=5000)
                            
                            apply_text = apply_btn.inner_text().lower()
                            
                            if "indeed" in apply_text:
                                apply_method = "Apply Now with Indeed"
                            else:
                                apply_method = "Apply on Company Site"
                        except:
                            apply_method = "Unknown"
                        
                        desc_el = self.page.query_selector("#jobDescriptionText")
                        description = desc_el.inner_text().strip() if desc_el else ""
                        salary = extract_salary(description)
                        
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
                time.sleep(random.uniform(2, 5))  # Random sleep between page navigations
                        
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