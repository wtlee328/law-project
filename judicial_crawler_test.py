#!/usr/bin/env python
# coding: utf-8

import requests
import time
import re
import csv
import logging
import os
import sys
import json
from bs4 import BeautifulSoup
from urllib.parse import quote, unquote, parse_qs, urlparse, urljoin
from datetime import datetime

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("judicial_crawler.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
        self.debug_dir = "debug_files"
        os.makedirs(self.debug_dir, exist_ok=True)
        
    def save_debug_file(self, content, filename):
        """保存內容到調試文件"""
        filepath = os.path.join(self.debug_dir, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                if isinstance(content, str):
                    f.write(content)
                else:
                    import json
                    json.dump(content, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存調試文件: {filepath}")
        except Exception as e:
            logger.error(f"保存調試文件失敗: {str(e)}")
    
    def extract_query_result_url(self, html_content):
        """從搜尋結果頁面提取結果列表URL"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 保存HTML以便調試
        self.save_debug_file(html_content, "search_results_page.html")
        
        # 1. 檢查是否有錯誤信息
        error_messages = [
            "檢索之檢索詞彙無效",
            "查無符合條件資料",
            "系統忙碌中",
            "系統發生錯誤"
        ]
        
        for error in error_messages:
            if error in html_content:
                logger.error(f"搜尋頁面返回錯誤: {error}")
                return None
        
        # 2. 直接查找結果URL
        # 方法一: 查找包含q=參數的鏈接
        query_id_pattern = re.compile(r'q=([a-f0-9]+)')
        for a in soup.find_all('a'):
            href = a.get('href', '')
            match = query_id_pattern.search(href)
            if match and 'qryresultlst.aspx' in href:
                full_url = href if href.startswith('http') else (
                    "https://judgment.judicial.gov.tw" + href if href.startswith('/') else self.base_url + href
                )
                logger.info(f"從鏈接找到結果URL: {full_url}")
                return full_url
        
        # 方法二: 檢查是否有重定向到結果頁面的JavaScript
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
                        logger.info(f"從腳本找到重定向URL: {full_url}")
                        return full_url
        
        # 方法三: 從頁面文本中提取查詢ID
        page_text = soup.get_text()
        match = query_id_pattern.search(page_text)
        if match:
            query_id = match.group(1)
            result_url = f"{self.base_url}qryresultlst.aspx?ty=SIMJUDBOOK&q={query_id}"
            logger.info(f"從頁面文本提取查詢ID得到URL: {result_url}")
            return result_url
        
        logger.error("無法找到結果URL")
        return None
    
    def extract_judgments_from_list(self, html_content, result_url):
        """從結果列表頁面提取判決信息"""
        soup = BeautifulSoup(html_content, 'html.parser')
        judgments = []
        
        # 保存原始HTML以便調試
        self.save_debug_file(html_content, "results_page_content.html")
        
        # 檢查是否有總筆數信息
        total_count_text = soup.get_text()
        count_match = re.search(r'共\s*(\d+)\s*筆', total_count_text)
        if count_match:
            total_count = count_match.group(1)
            logger.info(f"搜尋結果共 {total_count} 筆")
            
            # 檢查結果是否過多
            try:
                if int(total_count) > 1000:
                    logger.warning(f"結果數量過多 ({total_count} 筆)，可能需要縮小搜索範圍")
                if int(total_count) > 1000000:
                    logger.error(f"結果數量異常 ({total_count} 筆)，可能的搜索語法錯誤")
                    # 檢查結果URL是否正確
                    logger.info(f"當前結果URL: {result_url}")
            except ValueError:
                pass
        
        # 如果我們能找到結果表格，這是最可靠的方法
        result_table = None
        for table in soup.find_all('table'):
            if table.get('id') == 'gvMain' or '裁判字號' in table.get_text() and '裁判日期' in table.get_text():
                result_table = table
                break
        
        if result_table:
            # 從表格中提取判決
            rows = result_table.find_all('tr')
            # 跳過表頭行
            for i, row in enumerate(rows[1:], 1):
                try:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) < 3:  # 需要至少3列: 序號, 裁判字號, 裁判日期
                        continue
                    
                    # 通常第二列是裁判字號
                    judgment_cell = cells[1] if len(cells) > 1 else None
                    if not judgment_cell:
                        continue
                    
                    # 從裁判字號單元格提取信息
                    judgment_text = judgment_cell.get_text(strip=True)
                    judgment_id = re.sub(r'\s*（.*?）\s*|\s*\(.*?\)\s*', '', judgment_text)
                    
                    # 提取日期 (通常是第三列)
                    date_cell = cells[2] if len(cells) > 2 else None
                    judgment_date = date_cell.get_text(strip=True) if date_cell else ""
                    
                    # 提取案由 (通常是第四列)
                    case_type_cell = cells[3] if len(cells) > 3 else None
                    case_type = case_type_cell.get_text(strip=True) if case_type_cell else ""
                    
                    # 提取URL
                    judgment_url = ""
                    links = judgment_cell.find_all('a')
                    if links:
                        href = links[0].get('href', '')
                        judgment_url = href if href.startswith('http') else (
                            "https://judgment.judicial.gov.tw" + href if href.startswith('/') else self.base_url + href
                        )
                    
                    judgments.append({
                        'id': judgment_id,
                        'date': judgment_date,
                        'case_type': case_type,
                        'url': judgment_url
                    })
                    logger.info(f"從表格提取第 {i} 個判決: {judgment_id}, 日期={judgment_date}")
                    
                except Exception as e:
                    logger.error(f"提取第 {i} 行時出錯: {str(e)}")
            
        else:
            # 如果找不到表格，嘗試從文本中提取判決信息
            logger.warning("找不到結果表格，嘗試從文本提取判決信息")
            
            # 司法院結果通常有序號、裁判字號等格式
            judgment_blocks = soup.find_all('div', class_='jud')
            if not judgment_blocks:
                # 如果沒有特定的div，尋找可能包含判決信息的段落
                judgment_pattern = re.compile(r'(\d+)\.\s+([\w\s]+)\s+(\d+)\s*年度\s*([\w\s]+)字\s*第\s*(\d+)\s*號')
                for p in soup.find_all(['p', 'div']):
                    text = p.get_text(strip=True)
                    match = judgment_pattern.search(text)
                    if match:
                        judgment_blocks.append(p)
            
            for i, block in enumerate(judgment_blocks):
                try:
                    text = block.get_text(strip=True)
                    
                    # 提取裁判字號
                    id_match = re.search(r'([\w\s]+)\s+(\d+)\s*年度\s*([\w\s]+)字\s*第\s*(\d+)\s*號', text)
                    if not id_match:
                        continue
                    
                    court_name = id_match.group(1).strip()
                    year = id_match.group(2).strip()
                    case_type_name = id_match.group(3).strip()
                    case_number = id_match.group(4).strip()
                    judgment_id = f"{court_name} {year} 年度 {case_type_name}字 第 {case_number} 號"
                    
                    # 提取裁判日期
                    date_match = re.search(r'(\d{1,3})\.(\d{1,2})\.(\d{1,2})', text)
                    judgment_date = ""
                    if date_match:
                        judgment_date = f"{date_match.group(1)}.{date_match.group(2)}.{date_match.group(3)}"
                    
                    # 提取案由
                    case_type = ""
                    case_match = re.search(r'號[\w\s]*?(?:\（.*?\）|\(.*?\))?\s*([\w\s]+)(?:\s|$)', text)
                    if case_match:
                        case_type = case_match.group(1).strip()
                    
                    # 提取URL
                    judgment_url = ""
                    links = block.find_all('a')
                    if links:
                        href = links[0].get('href', '')
                        judgment_url = href if href.startswith('http') else (
                            "https://judgment.judicial.gov.tw" + href if href.startswith('/') else self.base_url + href
                        )
                    
                    judgments.append({
                        'id': judgment_id,
                        'date': judgment_date,
                        'case_type': case_type,
                        'url': judgment_url
                    })
                    logger.info(f"從文本提取第 {i+1} 個判決: {judgment_id}, 日期={judgment_date}")
                    
                except Exception as e:
                    logger.error(f"提取第 {i+1} 個文本塊時出錯: {str(e)}")
        
        # 最後嘗試: 如果上面方法都失敗，直接尋找所有包含裁判字號格式的文本
        if not judgments:
            logger.warning("嘗試使用正則表達式直接搜索頁面內容")
            judgment_pattern = re.compile(r'([\w\s]+)\s+(\d+)\s*年度\s*([\w\s]+)字\s*第\s*(\d+)\s*號')
            date_pattern = re.compile(r'(\d{1,3})\.(\d{1,2})\.(\d{1,2})')
            
            text = soup.get_text()
            for match in judgment_pattern.finditer(text):
                try:
                    # 提取裁判字號
                    court_name = match.group(1).strip()
                    year = match.group(2).strip()
                    case_type_name = match.group(3).strip()
                    case_number = match.group(4).strip()
                    judgment_id = f"{court_name} {year} 年度 {case_type_name}字 第 {case_number} 號"
                    
                    # 尋找附近的日期
                    context = text[max(0, match.start() - 50):min(len(text), match.end() + 100)]
                    date_match = date_pattern.search(context)
                    judgment_date = ""
                    if date_match:
                        judgment_date = f"{date_match.group(1)}.{date_match.group(2)}.{date_match.group(3)}"
                    
                    # 簡單假設案由在字號後面
                    case_type = ""
                    
                    judgments.append({
                        'id': judgment_id,
                        'date': judgment_date,
                        'case_type': case_type,
                        'url': ""
                    })
                    logger.info(f"從文本正則搜索提取判決: {judgment_id}, 日期={judgment_date}")
                    
                except Exception as e:
                    logger.error(f"正則提取判決時出錯: {str(e)}")
        
        return judgments
    
    def get_court_code(self, court_name):
        """將法院名稱轉換為代碼"""
        # 法院代碼映射表 (可根據需要擴充)
        court_code_map = {
            "臺灣基隆地方法院": "KLDV",
            "內湖簡易庭": "NHEV",
            "臺灣臺北地方法院": "TPDV",
            "士林地方法院": "SLDV",
            "臺灣新北地方法院": "PCDV",
            "臺灣桃園地方法院": "TYDV",
            "臺灣新竹地方法院": "SCDV",
            "臺灣苗栗地方法院": "MLDV",
            "臺灣臺中地方法院": "TCDV",
            "臺灣南投地方法院": "NTDV",
            "臺灣彰化地方法院": "CHDV",
            "臺灣雲林地方法院": "YLDV",
            "臺灣嘉義地方法院": "CYDV",
            "臺灣臺南地方法院": "TNDV",
            "臺灣高雄地方法院": "KSDV",
            "臺灣屏東地方法院": "PTDV",
            "臺灣臺東地方法院": "TTDV",
            "臺灣花蓮地方法院": "HLDV",
            "臺灣宜蘭地方法院": "ILDV",
            "臺灣高等法院": "TPHV",
            "羅東簡易庭": "LDEV",
            "宜蘭地方法院羅東簡易庭": "LDEV",
            "臺東簡易庭": "TTEV",
            "臺北簡易庭": "TPEV",
            "中壢簡易庭": "TYEV",
            "高雄簡易庭": "KSEV"
        }
        
        # 直接匹配
        if court_name in court_code_map:
            return court_code_map[court_name]
        
        # 部分匹配
        for name, code in court_code_map.items():
            if name in court_name or court_name in name:
                return code
        
        # 針對簡易庭的特殊處理
        if "簡易庭" in court_name:
            # 嘗試找出簡易庭所屬地區
            for name, code in court_code_map.items():
                if name.replace("地方法院", "") in court_name:
                    # 針對簡易庭，代碼可能有所不同，這裡是猜測
                    return code.replace("DV", "EV")
        
        return None
    
    def construct_plain_text_url(self, court_code, year, case_type, case_number, judgment_date, version):
        """構造去格式版裁判書URL"""
        # 將參數拼接成ID
        id_parts = [court_code, year, case_type, str(case_number), judgment_date, str(version)]
        id_param = ','.join(id_parts)
        
        # 對ID參數進行URL編碼
        encoded_id = quote(id_param)
        
        # 構造去格式版URL
        for ispdf in ["1", "0"]:  # 嘗試ispdf=1和ispdf=0
            url = f"https://judgment.judicial.gov.tw/EXPORTFILE/reformat.aspx?type=JD&id={encoded_id}&lawpara=&ispdf={ispdf}"
            try:
                response = self.session.get(url, headers=self.headers, timeout=10)
                # 檢查是否有效（簡單檢查內容長度和是否包含錯誤訊息）
                if (response.status_code == 200 and 
                    len(response.text) > 100 and 
                    "查無資料" not in response.text and
                    "錯誤" not in response.text):
                    logger.info(f"找到有效去格式版URL (ispdf={ispdf})")
                    return url
            except Exception as e:
                logger.error(f"檢查去格式版URL時出錯: {str(e)}")
                continue
        
        # 如果都失敗，返回ispdf=1版本
        logger.warning("無法確定有效的去格式版URL，默認使用ispdf=1")
        return f"https://judgment.judicial.gov.tw/EXPORTFILE/reformat.aspx?type=JD&id={encoded_id}&lawpara=&ispdf=1"
    
    def parse_judgment_id(self, judgment_id):
        """解析裁判字號，提取法院、年度、字別和案號"""
        # 裁判字號格式: 臺灣基隆地方法院 108 年度家繼訴字第 12 號民事判決
        match = re.search(r'([\w\s]+)\s+(\d+)\s*年度\s*([\w\s]+)字\s*第\s*(\d+)\s*號', judgment_id)
        
        if not match:
            logger.error(f"無法解析裁判字號: {judgment_id}")
            return None, None, None, None
            
        court_name = match.group(1).strip()
        year = match.group(2).strip()
        case_type = match.group(3).strip()
        case_number = match.group(4).strip()
        
        return court_name, year, case_type, case_number
    
    def convert_roc_date_to_ad(self, roc_date):
        """將民國日期轉換為西元日期格式YYYYMMDD"""
        logger.debug(f"轉換民國日期: {roc_date}")
        
        # 處理格式如 "111.02.15"
        if '.' in roc_date:
            parts = roc_date.split('.')
            if len(parts) == 3:
                try:
                    roc_year = int(parts[0])
                    month = int(parts[1])
                    day = int(parts[2])
                    year_ad = roc_year + 1911
                    formatted_date = f"{year_ad:04d}{month:02d}{day:02d}"
                    logger.debug(f"轉換民國日期 {roc_date} 為西元日期 {formatted_date}")
                    return formatted_date
                except ValueError as e:
                    logger.error(f"日期轉換錯誤: {str(e)}")
                    return None
        
        logger.warning(f"無法轉換日期 {roc_date}")
        return None

    def fetch_judgment_content(self, url):
        """獲取判決書內容"""
        try:
            logger.info(f"獲取判決書內容: {url}")
            response = self.session.get(url, headers=self.headers, timeout=30)  # 增加超時時間，因為判決書可能很大
            response.raise_for_status()
            
            # 使用BeautifulSoup解析HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 提取純文字內容
            # 移除腳本和樣式
            for script in soup(['script', 'style']):
                script.decompose()
                
            # 提取所有文字
            text = soup.get_text(separator='\n').strip()
            
            # 標準化空白字元
            text = re.sub(r'[\r\n]+', '\n', text)  # 將多個換行符合併為一個
            text = re.sub(r' +', ' ', text)  # 將多個空格合併為一個
            
            # 去掉頭尾多餘的空行
            text = text.strip()
            
            # 如果內容太長，可能要考慮截取或摘要
            if len(text) > 500000:  # 約50萬字元
                logger.warning(f"判決書內容過長 ({len(text)} 字元)，將被截斷")
                text = text[:500000] + "...(內容過長，已截斷)"
            
            return text
            
        except Exception as e:
            logger.error(f"獲取判決書內容時出錯: {str(e)}")
            return f"獲取內容失敗: {str(e)}"
    
    def generate_plain_text_url_for_judgment(self, judgment_info):
        """為單個判決生成去格式版URL"""
        judgment_id = judgment_info['id']
        judgment_date = judgment_info['date']
        original_url = judgment_info.get('url', '')
        
        logger.info(f"為判決生成URL: {judgment_id}, 日期={judgment_date}")
        
        # 如果已有原始URL，嘗試直接轉換
        if original_url and 'FJUD/data.aspx' in original_url:
            try:
                # 從URL中提取id參數
                parsed_url = urlparse(original_url)
                query_params = parse_qs(parsed_url.query)
                if 'id' in query_params:
                    id_param = query_params['id'][0]
                    plain_text_url_base = "https://judgment.judicial.gov.tw/EXPORTFILE/reformat.aspx"
                    
                    # 嘗試ispdf=1和ispdf=0
                    for ispdf in ["1", "0"]:
                        plain_text_url = f"{plain_text_url_base}?type=JD&id={id_param}&lawpara=&ispdf={ispdf}"
                        try:
                            response = self.session.get(plain_text_url, headers=self.headers, timeout=10)
                            if (response.status_code == 200 and 
                                len(response.text) > 100 and 
                                "查無資料" not in response.text and
                                "錯誤" not in response.text):
                                logger.info(f"直接從原始URL轉換得到去格式版URL: {plain_text_url}")
                                return plain_text_url
                        except Exception as e:
                            logger.error(f"檢查去格式版URL時出錯: {str(e)}")
                            continue
            except Exception as e:
                logger.error(f"從原始URL轉換時出錯: {str(e)}")
        
        # 如果直接轉換失敗，使用解析方法
        # 解析裁判字號
        court_name, year, case_type, case_number = self.parse_judgment_id(judgment_id)
        if not all([court_name, year, case_type, case_number]):
            logger.error(f"無法解析裁判字號: {judgment_id}")
            return None
        
        # 轉換法院名稱為代碼
        court_code = self.get_court_code(court_name)
        if not court_code:
            logger.error(f"無法找到法院代碼: {court_name}")
            return None
        
        # 轉換判決日期為西元年格式
        judgment_date_ad = self.convert_roc_date_to_ad(judgment_date)
        if not judgment_date_ad:
            logger.error(f"無法轉換判決日期: {judgment_date}")
            return None
        
        # 嘗試不同的版本號
        for version in range(1, 6):  # 嘗試版本1-5
            plain_text_url = self.construct_plain_text_url(
                court_code, year, case_type, case_number, judgment_date_ad, version
            )
            if plain_text_url:
                logger.info(f"成功生成URL (版本 {version}): {plain_text_url}")
                return plain_text_url
        
        logger.warning(f"無法為判決生成URL: {judgment_id}")
        return None
    
    def search_judgments(self, query_string):
        """搜尋裁判書"""
        logger.info(f"開始搜尋: {query_string}")
        
        try:
            # 使用直接的URL格式進行搜索，避免表單處理的複雜性
            # 將查詢字串編碼
            encoded_query = quote(query_string)
            direct_url = f"{self.direct_search_url}?akw={encoded_query}"
            
            logger.info(f"使用直接URL進行搜索: {direct_url}")
            
            # 發送請求
            response = self.session.get(direct_url, headers=self.headers)
            response.raise_for_status()
            
            # 保存搜尋回應
            self.save_debug_file(response.text, "search_response.html")
            self.save_debug_file(response.url, "response_url.txt")
            
            # 檢查是否已經在結果頁面
            if 'qryresultlst.aspx' in response.url:
                # 已經重定向到結果頁面
                logger.info(f"已重定向到結果頁面: {response.url}")
                result_url = response.url
            else:
                # 需要提取結果URL
                result_url = self.extract_query_result_url(response.text)
                if not result_url:
                    logger.error("無法從回應中提取結果URL")
                    return None
                    
                logger.info(f"從回應中提取結果URL: {result_url}")
                
                # 訪問結果頁面
                logger.info(f"訪問結果頁面: {result_url}")
                response = self.session.get(result_url, headers=self.headers)
                response.raise_for_status()
            
            # 保存結果頁面
            self.save_debug_file(response.text, "result_list_page.html")
            
            # 從結果頁面提取判決信息
            judgments = self.extract_judgments_from_list(response.text, result_url)
            if not judgments:
                logger.warning("未找到判決")
                return []
                
            logger.info(f"找到 {len(judgments)} 個判決")
            
            # 生成去格式版URL並獲取內容
            result_judgments = []
            for judgment in judgments:
                plain_text_url = self.generate_plain_text_url_for_judgment(judgment)
                if plain_text_url:
                    judgment['plain_text_url'] = plain_text_url
                    
                    # 獲取判決書內容
                    judgment_content = self.fetch_judgment_content(plain_text_url)
                    judgment['content'] = judgment_content
                    
                    result_judgments.append(judgment)
                    logger.info(f"成功生成URL和獲取內容: {plain_text_url}")
            
            return result_judgments
            
        except Exception as e:
            logger.error(f"搜尋過程中發生錯誤: {str(e)}", exc_info=True)
            return None
    
    def save_to_csv(self, judgments, output_file="judgment_results.csv"):
        """將判決信息保存為CSV文件"""
        if not judgments:
            logger.warning("沒有判決可保存")
            return False
            
        try:
            with open(output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
                # 添加新欄位 "內容"
                fieldnames = ['裁判字號', '裁判日期', '裁判案由', 'URL', '內容']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for judgment in judgments:
                    writer.writerow({
                        '裁判字號': judgment.get('id', ''),
                        '裁判日期': judgment.get('date', ''),
                        '裁判案由': judgment.get('case_type', ''),
                        'URL': judgment.get('plain_text_url', ''),
                        '內容': judgment.get('content', '')  # 添加判決書內容
                    })
                    
            logger.info(f"成功將 {len(judgments)} 個判決保存到 {output_file}")
            return True
        except Exception as e:
            logger.error(f"保存CSV時發生錯誤: {str(e)}", exc_info=True)
            return False
            
    def run(self, query_string, output_file="judgment_results.csv"):
        """運行爬蟲程序"""
        start_time = time.time()
        logger.info(f"開始運行爬蟲，查詢: '{query_string}'")
        
        # 搜尋判決
        judgments = self.search_judgments(query_string)
        
        if judgments:
            # 保存結果
            success = self.save_to_csv(judgments, output_file)
            if success:
                logger.info(f"爬蟲運行成功，結果已保存到 {output_file}")
            else:
                logger.error("保存結果失敗")
        else:
            logger.error("搜尋判決失敗或沒有找到判決")
            
        end_time = time.time()
        execution_time = end_time - start_time
        logger.info(f"爬蟲總執行時間: {execution_time:.2f} 秒")
        
        return judgments is not None

def main():
    # 顯示程式資訊
    print(f"程式執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("司法院裁判書查詢系統爬蟲")
    print("=" * 60)
    
    # 輸出搜尋語法說明
    print("""
檢索字詞輔助說明:
+ 表示「或」關係 (例如: 法院+管轄)
- 表示「不含」關係 (例如: 法院-管轄)
& 表示「且」關係 (例如: 法院&管轄)
() 表示「組合」關係 (例如: (法院+管轄)&公證處)
    """)
    
    # 處理命令行參數或用戶輸入
    if len(sys.argv) > 1:
        query_string = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else "judgment_results.csv"
    else:
        query_string = input("請輸入搜尋字串 (例如: 不變期間&所有權移轉&贈與之債權): ").strip()
        output_file = input("請輸入輸出文件名 (預設: judgment_results.csv): ").strip()
        if not output_file:
            output_file = "judgment_results.csv"
    
    # 創建爬蟲並運行
    crawler = JudicialCrawler()
    success = crawler.run(query_string, output_file)
    
    if success:
        print(f"\n爬蟲運行成功！結果已保存到 {output_file}")
    else:
        print("\n爬蟲運行失敗，請查看日誌文件獲取詳細信息。")

if __name__ == "__main__":
    main()