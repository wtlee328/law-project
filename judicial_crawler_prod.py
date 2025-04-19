#!/usr/bin/env python
# coding: utf-8

import requests
import re
import sys
import json
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin

class JudicialCrawlerSimplified:
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

        error_messages = [
            "檢索之檢索詞彙無效", "查無符合條件資料", "系統忙碌中", "系統發生錯誤"
        ]
        for error in error_messages:
            if error in html_content:
                return None # 發生錯誤或查無資料

        # 查找包含 q= 參數的結果列表頁面鏈接
        query_id_pattern = re.compile(r'q=([a-f0-9]+)')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'qryresultlst.aspx' in href and query_id_pattern.search(href):
                return urljoin(self.base_url, href)

        # 檢查是否有重定向到結果頁面的JavaScript
        redirect_patterns = [
            r'window\.location\.href\s*=\s*[\'"]?([^\'"]*qryresultlst\.aspx[^\'"]*)[\'"]?',
            r'location\.href\s*=\s*[\'"]?([^\'"]*qryresultlst\.aspx[^\'"]*)[\'"]?',
            r'window\.location\s*=\s*[\'"]?([^\'"]*qryresultlst\.aspx[^\'"]*)[\'"]?'
        ]
        for script in soup.find_all('script'):
            script_text = script.string if script.string else ""
            for pattern in redirect_patterns:
                match = re.search(pattern, script_text)
                if match:
                    redirect_url = match.group(1)
                    return urljoin(self.base_url, redirect_url)

        return None # 找不到結果URL

    def extract_judgments_from_list(self, html_content):
        """從結果列表頁面提取判決字號和URL"""
        soup = BeautifulSoup(html_content, 'html.parser')
        judgments = []

        # 尋找結果表格
        result_table = None
        for table in soup.find_all('table'):
            # 判斷是否為結果表格 (通常包含 '裁判字號' 和 '裁判日期' 等標頭)
            header_text = table.find('tr')
            if header_text and '裁判字號' in header_text.get_text():
                 result_table = table
                 break

        if result_table:
            rows = result_table.find_all('tr')
            for row in rows[1:]: # 跳過表頭行
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2: # 需要至少有序號和裁判字號列
                    judgment_cell = cells[1] # 第二列通常是裁判字號
                    link = judgment_cell.find('a', href=True)
                    if link:
                        judgment_id_text = link.get_text(strip=True)
                        # 清理可能的額外資訊 (如: （歷史判決）)
                        judgment_id = re.sub(r'\s*（.*?）\s*|\s*\(.*?\)\s*', '', judgment_id_text).strip()
                        judgment_url = urljoin(self.base_url, link['href'])
                        judgments.append({
                            'id': judgment_id,
                            'url': judgment_url
                        })
        return judgments

    def run(self, query_string):
        """執行搜尋並返回結果列表"""
        try:
            # 使用直接的 URL 格式進行搜索
            encoded_query = quote(query_string)
            direct_url = f"{self.direct_search_url}?akw={encoded_query}"

            response = self.session.get(direct_url, headers=self.headers, timeout=20)
            response.raise_for_status()

            result_url = None
            # 檢查是否直接跳轉到結果列表頁面
            if 'qryresultlst.aspx' in response.url:
                result_url = response.url
                results_page_html = response.text
            else:
                # 如果沒有跳轉，嘗試從初始回應中提取結果 URL
                result_url = self.extract_query_result_url(response.text)
                if not result_url:
                    # print("無法找到結果列表頁面 URL。", file=sys.stderr)
                    return [] # 返回空列表表示找不到

                # 訪問結果列表頁面
                response = self.session.get(result_url, headers=self.headers, timeout=20)
                response.raise_for_status()
                results_page_html = response.text

            # 從結果列表頁面提取判決信息
            judgments = self.extract_judgments_from_list(results_page_html)
            return judgments

        except requests.exceptions.RequestException as e:
            # print(f"請求錯誤: {e}", file=sys.stderr)
            return [] # 返回空列表表示錯誤
        except Exception as e:
            # print(f"處理過程中發生未知錯誤: {e}", file=sys.stderr)
            return [] # 返回空列表表示錯誤

def main():
    if len(sys.argv) < 2:
        print("用法: python script_name.py \"<搜尋字串>\"", file=sys.stderr)
        sys.exit(1)

    query_string = sys.argv[1]

    crawler = JudicialCrawlerSimplified()
    results = crawler.run(query_string)

    # 以JSON格式輸出到標準輸出
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()