#!/usr/bin/env python
# coding: utf-8

import requests
import re
import sys
import json
from bs4 import BeautifulSoup
from urllib.parse import quote

class JudicialCrawler:
    def __init__(self):
        self.base_url = "https://judgment.judicial.gov.tw/FJUD/"
        self.search_url = self.base_url + "Default.aspx"
        self.direct_search_url = self.base_url + "qryresult.aspx"
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            'Referer': 'https://judgment.judicial.gov.tw/FJUD/Default.aspx',
            'Origin': 'https://judgment.judicial.gov.tw'
        }

    def extract_query_result_url(self, html_content):
        """從搜尋結果頁面提取結果列表URL"""
        soup = BeautifulSoup(html_content, 'html.parser')

        # 1. 檢查是否有錯誤信息
        error_messages = [
            "檢索之檢索詞彙無效",
            "查無符合條件資料",
            "系統忙碌中",
            "系統發生錯誤"
        ]
        for error in error_messages:
            if error in html_content:
                return None # Return None on error

        # 2. 直接查找結果URL
        query_id_pattern = re.compile(r'q=([a-f0-9]+)')
        for a in soup.find_all('a'):
            href = a.get('href', '')
            match = query_id_pattern.search(href)
            if match and 'qryresultlst.aspx' in href:
                full_url = href if href.startswith('http') else (
                    "https://judgment.judicial.gov.tw" + href if href.startswith('/') else self.base_url + href
                )
                return full_url

        # 3. 檢查是否有重定向到結果頁面的JavaScript
        redirect_patterns = [
            r'window\.location\.href\s*=\s*[\'"]?([^\'"]+)[\'"]?',
            r'location\.href\s*=\s*[\'"]?([^\'"]+)[\'"]?',
            r'window\.location\s*=\s*[\'"]?([^\'"]+)[\'"]?'
        ]
        for pattern in redirect_patterns:
            redirect_regex = re.compile(pattern)
            for script in soup.find_all('script'):
                script_text = script.string if script.string else ""
                match = redirect_regex.search(script_text)
                if match:
                    redirect_url = match.group(1)
                    if "qryresultlst.aspx" in redirect_url:
                        full_url = redirect_url if redirect_url.startswith('http') else (
                            "https://judgment.judicial.gov.tw" + redirect_url if redirect_url.startswith('/') else self.base_url + redirect_url
                        )
                        return full_url

        # 4. 從頁面文本中提取查詢ID
        page_text = soup.get_text()
        match = query_id_pattern.search(page_text)
        if match:
            query_id = match.group(1)
            result_url = f"{self.base_url}qryresultlst.aspx?ty=SIMJUDBOOK&q={query_id}"
            return result_url

        return None # Return None if no URL found

    def extract_judgments_from_list(self, html_content):
        """從結果列表頁面提取判決字號，並確保只輸出標準格式且不重複。"""
        soup = BeautifulSoup(html_content, 'html.parser')
        potential_ids = [] # 先收集所有可能包含 ID 的字串

        # --- 原有的提取邏輯 (稍微修改以收集至 potential_ids) ---

        # 方法一：從表格提取
        result_table = None
        for table in soup.find_all('table'):
            if table.get('id') == 'gvMain' or ('裁判字號' in table.get_text() and '裁判日期' in table.get_text()):
                result_table = table
                break

        if result_table:
            rows = result_table.find_all('tr')
            for row in rows[1:]:
                try:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        judgment_cell = cells[1]
                        # 直接獲取單元格的原始文本，後續再清理
                        potential_ids.append(judgment_cell.get_text(strip=True))
                except Exception:
                    continue

        # 方法二：從文本塊提取 (如果表格提取失敗或不完整)
        # 使用更精確的模式來查找可能的ID格式
        # (法院名稱 年度 字別 字 第 字號 號)
        # 注意：法院名稱部分允許更多變化，例如包含分院
        judgment_pattern_precise = re.compile(r'((?:臺灣|福建)[\w\s]+?法院(?:[\w\s]+?分院)?)\s+(\d+)\s*年度\s*([\w\s]+?)字\s*第\s*(\d+)\s*號')

        # 如果表格沒提取到內容，或為了更全面，可以搜尋整個文本
        if not potential_ids: # 或者即使表格有內容也執行，以防萬一
                text_content = soup.get_text(separator='\n', strip=True)
                matches = judgment_pattern_precise.finditer(text_content)
                for match in matches:
                    # 直接從匹配結果重建標準格式
                    court = match.group(1).strip()
                    year = match.group(2).strip()
                    case_type = match.group(3).strip()
                    number = match.group(4).strip()
                    reconstructed_id = f"{court} {year} 年度 {case_type}字 第 {number} 號"
                    potential_ids.append(reconstructed_id) # 添加重建後的標準格式

        # --- 清理和去重 ---
        clean_judgment_ids = set() # 使用 set 自動去重

        # 再次定義精確的匹配模式，確保只提取標準格式
        # 這次使用 match 確保字串 *開頭* 就符合模式，或者 search 查找第一個匹配
        for text in potential_ids:
            if not text: continue # 跳過空字串

            # 嘗試從字串中搜索第一個符合格式的部分
            match = judgment_pattern_precise.search(text.strip())
            if match:
                # 從匹配到的部分重建標準ID格式
                court = match.group(1).strip()
                year = match.group(2).strip()
                case_type = match.group(3).strip()
                number = match.group(4).strip()
                final_id = f"{court} {year} 年度 {case_type}字 第 {number} 號"

                # (可選) 檢查是否有多餘的後綴，例如 "民事判決"
                # 如果需要完全精確匹配無後綴的，可以在這裡加判斷
                # if match.end() == len(text.strip()): # 如果匹配到字串結尾
                #     clean_judgment_ids.add(final_id)
                # else: # 如果後面還有文字，可能需要判斷是否保留
                #     # 根據需求，這裡決定是否添加，目前只要匹配到就添加
                clean_judgment_ids.add(final_id)
            # else:
                # 如果字串本身不包含標準格式，則忽略

        # 將 set 轉換回 list 返回
        return list(clean_judgment_ids)


    def search_judgments(self, query_string):
        """搜尋裁判書並返回裁判字號列表"""
        try:
            # 使用直接的URL格式進行搜索
            encoded_query = quote(query_string)
            direct_url = f"{self.direct_search_url}?akw={encoded_query}"

            # 發送請求
            response = self.session.get(direct_url, headers=self.headers, timeout=30)
            response.raise_for_status()
            response.encoding = response.apparent_encoding # Ensure correct encoding

            result_list_html = response.text
            result_url = response.url

            # 檢查是否需要再次訪問結果頁面
            if 'qryresultlst.aspx' not in result_url:
                extracted_url = self.extract_query_result_url(result_list_html)
                if not extracted_url:
                    return [] # Return empty list if cannot find result URL

                # 訪問結果頁面
                response = self.session.get(extracted_url, headers=self.headers, timeout=30)
                response.raise_for_status()
                response.encoding = response.apparent_encoding # Ensure correct encoding
                result_list_html = response.text

            # 從結果頁面提取判決字號
            judgment_ids = self.extract_judgments_from_list(result_list_html)
            return judgment_ids

        except requests.exceptions.RequestException as e:
            # Silently fail on request errors in production, return empty list
            return []
        except Exception:
            # Silently fail on other errors
            return []

def main():
    if len(sys.argv) > 1:
        query_string = sys.argv[1]
    else:
        # If no argument, exit silently or provide a default behavior if needed
        # For this requirement (only JSON output), exiting might be appropriate
        # Or print an empty JSON array:
        print(json.dumps([], ensure_ascii=False))
        sys.exit(1) # Exit with an error code if no query provided

    crawler = JudicialCrawler()
    judgment_ids = crawler.search_judgments(query_string)

    # Output only the JSON array of judgment IDs
    print(json.dumps(judgment_ids, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()